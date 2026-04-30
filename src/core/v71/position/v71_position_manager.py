"""V71PositionManager -- positions table CRUD + invariants.

Spec:
  - 02_TRADING_RULES.md §6  (avg-price + event reset)
  - 03_DATA_MODEL.md §2.3  (positions table)
  - 07_SKILLS_SPEC.md §4   (avg_price_skill)

Phase: P3.4

All writes to ``positions`` go through this class -- direct mutation
of ``weighted_avg_price`` from business code is forbidden.
:mod:`avg_price_skill` is the only place the math lives.

P3.4 keeps the store in-memory (dict[position_id, PositionState]).
A later phase swaps the dict for a Supabase-backed implementation; this
class's public surface (PositionStore Protocol + apply_buy / apply_sell
/ close_position) stays stable so callers don't change.

Trade events:
    Each buy / sell appends a `TradeEvent` to the in-memory log.
    P3.4 writes to a Python list; later phases hydrate to the
    ``trade_events`` table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from src.core.v71.position.state import PositionState
from src.core.v71.skills.avg_price_skill import (
    PositionUpdate,
    update_position_after_buy,
    update_position_after_sell,
)
from src.core.v71.skills.exit_calc_skill import stage_after_partial_exit
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

# ---------------------------------------------------------------------------
# Trade events
# ---------------------------------------------------------------------------

# Allowed buy event types (§6.2 + Scenario A).
BUY_EVENT_TYPES = frozenset(
    {"BUY_EXECUTED", "PYRAMID_BUY", "MANUAL_PYRAMID_BUY"}
)

# Allowed sell event types -- maps to whether they advance the stop ladder.
SELL_EVENT_TYPES = frozenset(
    {"PROFIT_TAKE_5", "PROFIT_TAKE_10", "STOP_LOSS", "TS_EXIT", "MANUAL_SELL"}
)


@dataclass(frozen=True)
class TradeEvent:
    """One row of the future ``trade_events`` table."""

    event_type: str
    position_id: str
    stock_code: str
    quantity: int
    price: int
    timestamp: datetime
    events_reset: bool = False
    """Set when an add-buy triggered the §6 reset (logged for audit)."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PositionNotFoundError(KeyError):
    """No position with the given id."""


class InvalidEventTypeError(ValueError):
    """``event_type`` is not in the allowed set for the call."""


# ---------------------------------------------------------------------------
# V71PositionManager
# ---------------------------------------------------------------------------

class V71PositionManager:
    """In-memory positions store + avg-price-skill applicator.

    Implements :class:`PositionStore` from
    :mod:`src.core.v71.strategies.v71_buy_executor` so a buy executor
    can call ``add_position`` directly.
    """

    def __init__(self) -> None:
        require_enabled("v71.position_v71")
        self._positions: dict[str, PositionState] = {}
        self._events: list[TradeEvent] = []

    # ------------------------------------------------------------------
    # PositionStore Protocol  (consumed by V71BuyExecutor)
    # ------------------------------------------------------------------

    async def rollback_in_memory_position(self, position_id: str) -> None:
        """Compensating rollback used by V71BuyExecutor when the
        subsequent ``box_manager.mark_triggered`` fails (P-Wire-Box-1).

        Removes the position record AND the most recently-appended
        BUY_EXECUTED event tied to it. Idempotent: rolling back an
        unknown position_id is a no-op (the in-memory state is already
        the desired post-rollback shape).

        Removed in P-Wire-Box-4 once positions live in the same DB
        transaction as the box update.
        """
        state = self._positions.pop(position_id, None)
        if state is None:
            return
        # Remove the most recent BUY_EXECUTED event for this position.
        # In normal flow add_position appends exactly one such event
        # immediately before mark_triggered runs; scanning from the end
        # keeps this safe under any future reordering.
        for idx in range(len(self._events) - 1, -1, -1):
            event = self._events[idx]
            if (
                event.position_id == position_id
                and event.event_type == "BUY_EXECUTED"
            ):
                del self._events[idx]
                break

    async def add_position(
        self,
        *,
        stock_code: str,
        tracked_stock_id: str,
        triggered_box_id: str,
        path_type: str,
        quantity: int,
        weighted_avg_price: int,
        opened_at: datetime,
    ) -> str:
        """Insert a new OPEN position. Returns ``position_id``."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if weighted_avg_price <= 0:
            raise ValueError("weighted_avg_price must be positive")

        position_id = str(uuid.uuid4())
        fixed_stop = int(
            round(weighted_avg_price * (1.0 + V71Constants.STOP_LOSS_INITIAL_PCT))
        )
        state = PositionState(
            position_id=position_id,
            stock_code=stock_code,
            tracked_stock_id=tracked_stock_id,
            triggered_box_id=triggered_box_id,
            path_type=path_type,
            weighted_avg_price=weighted_avg_price,
            initial_avg_price=weighted_avg_price,
            total_quantity=quantity,
            fixed_stop_price=fixed_stop,
            status="OPEN",
            opened_at=opened_at,
        )
        self._positions[position_id] = state
        self._events.append(
            TradeEvent(
                event_type="BUY_EXECUTED",
                position_id=position_id,
                stock_code=stock_code,
                quantity=quantity,
                price=weighted_avg_price,
                timestamp=opened_at,
            )
        )
        return position_id

    # ------------------------------------------------------------------
    # apply_buy / apply_sell
    # ------------------------------------------------------------------

    async def apply_buy(
        self,
        position_id: str,
        *,
        buy_price: int,
        buy_quantity: int,
        event_type: str = "PYRAMID_BUY",
        when: datetime | None = None,
    ) -> PositionUpdate:
        """Add to an existing position (§6.2 weighted avg + event reset).

        Args:
            event_type: one of ``BUY_EVENT_TYPES`` -- distinguishes
                automated PYRAMID_BUY from MANUAL_PYRAMID_BUY (Scenario A).
        """
        if event_type not in BUY_EVENT_TYPES:
            raise InvalidEventTypeError(
                f"buy event_type must be one of {sorted(BUY_EVENT_TYPES)}; "
                f"got {event_type!r}"
            )
        state = self._get(position_id)
        update = update_position_after_buy(
            state, buy_price=buy_price, buy_quantity=buy_quantity
        )
        self._apply(state, update)
        self._events.append(
            TradeEvent(
                event_type=event_type,
                position_id=position_id,
                stock_code=state.stock_code,
                quantity=buy_quantity,
                price=buy_price,
                timestamp=when or datetime.now(),
                events_reset=update.events_reset,
            )
        )
        return update

    async def apply_sell(
        self,
        position_id: str,
        *,
        sell_quantity: int,
        sell_price: int,
        event_type: str,
        when: datetime | None = None,
    ) -> PositionUpdate:
        """Reduce a position's quantity (§6.4 avg unchanged).

        Advances the stop ladder when ``event_type`` is a profit-take:
            PROFIT_TAKE_5  -> profit_5_executed = True, stop -> -2%
            PROFIT_TAKE_10 -> profit_10_executed = True, stop -> +4%
            STOP_LOSS / TS_EXIT / MANUAL_SELL -> ladder unchanged.

        Sets ``status = CLOSED`` + records ``closed_at`` when total reaches 0.
        """
        if event_type not in SELL_EVENT_TYPES:
            raise InvalidEventTypeError(
                f"sell event_type must be one of {sorted(SELL_EVENT_TYPES)}; "
                f"got {event_type!r}"
            )
        state = self._get(position_id)
        update = update_position_after_sell(state, sell_quantity=sell_quantity)

        # Advance ladder for profit-takes (§5.4) before applying.
        new_p5 = state.profit_5_executed
        new_p10 = state.profit_10_executed
        if event_type == "PROFIT_TAKE_5":
            new_p5 = True
        elif event_type == "PROFIT_TAKE_10":
            new_p10 = True

        new_fixed_stop = (
            stage_after_partial_exit(new_p5, new_p10, state.weighted_avg_price)
            if event_type in {"PROFIT_TAKE_5", "PROFIT_TAKE_10"}
            else state.fixed_stop_price
        )

        # Build the effective update and apply.
        effective = PositionUpdate(
            weighted_avg_price=update.weighted_avg_price,
            initial_avg_price=update.initial_avg_price,
            total_quantity=update.total_quantity,
            fixed_stop_price=new_fixed_stop,
            profit_5_executed=new_p5,
            profit_10_executed=new_p10,
            ts_activated=update.ts_activated,
            ts_base_price=update.ts_base_price,
            ts_stop_price=update.ts_stop_price,
            ts_active_multiplier=update.ts_active_multiplier,
            events_reset=False,
        )
        self._apply(state, effective)

        # Lifecycle transitions.
        now = when or datetime.now()
        if state.total_quantity == 0:
            state.status = "CLOSED"
            state.closed_at = now
        elif state.status == "OPEN":
            state.status = "PARTIAL_CLOSED"

        self._events.append(
            TradeEvent(
                event_type=event_type,
                position_id=position_id,
                stock_code=state.stock_code,
                quantity=sell_quantity,
                price=sell_price,
                timestamp=now,
            )
        )
        return effective

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def close_position(
        self,
        position_id: str,
        *,
        when: datetime | None = None,
    ) -> PositionState:
        """Mark a zero-quantity position as CLOSED.

        Idempotent: closing an already-CLOSED position is a no-op.
        Raises if quantity is non-zero (caller must apply_sell first).
        """
        state = self._get(position_id)
        if state.total_quantity != 0:
            raise ValueError(
                f"Cannot close position {position_id} with non-zero quantity "
                f"({state.total_quantity})"
            )
        if state.status != "CLOSED":
            state.status = "CLOSED"
            state.closed_at = when or datetime.now()
        return state

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, position_id: str) -> PositionState:
        return self._get(position_id)

    def get_by_stock(
        self, stock_code: str, path_type: str
    ) -> PositionState | None:
        """Return the active (OPEN/PARTIAL_CLOSED) position for the
        given (stock_code, path_type) pair, or None.

        Same-stock-same-path active positions are unique by tracked-stock
        construction (gist EXCLUDE on tracked_stocks).
        """
        for pos in self._positions.values():
            if pos.status == "CLOSED":
                continue
            if pos.stock_code == stock_code and pos.path_type == path_type:
                return pos
        return None

    def list_open(self) -> list[PositionState]:
        """All positions that are still OPEN or PARTIAL_CLOSED."""
        return [p for p in self._positions.values() if p.status != "CLOSED"]

    def list_for_stock(self, stock_code: str) -> list[PositionState]:
        return [p for p in self._positions.values() if p.stock_code == stock_code]

    def list_events(self, *, position_id: str | None = None) -> list[TradeEvent]:
        if position_id is None:
            return list(self._events)
        return [e for e in self._events if e.position_id == position_id]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, position_id: str) -> PositionState:
        try:
            return self._positions[position_id]
        except KeyError as e:
            raise PositionNotFoundError(
                f"No position with id {position_id!r}"
            ) from e

    @staticmethod
    def _apply(state: PositionState, update: PositionUpdate) -> None:
        state.weighted_avg_price = update.weighted_avg_price
        state.initial_avg_price = update.initial_avg_price
        state.total_quantity = update.total_quantity
        state.fixed_stop_price = update.fixed_stop_price
        state.profit_5_executed = update.profit_5_executed
        state.profit_10_executed = update.profit_10_executed
        state.ts_activated = update.ts_activated
        state.ts_base_price = update.ts_base_price
        state.ts_stop_price = update.ts_stop_price
        state.ts_active_multiplier = update.ts_active_multiplier


__all__ = [
    "BUY_EVENT_TYPES",
    "SELL_EVENT_TYPES",
    "InvalidEventTypeError",
    "PositionNotFoundError",
    "TradeEvent",
    "V71PositionManager",
]
