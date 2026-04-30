"""V71PositionManager -- DB-backed positions + trade_events.

Spec:
  - 02_TRADING_RULES.md §5  (post-buy management)
  - 02_TRADING_RULES.md §6  (avg-price + event reset)
  - 02_TRADING_RULES.md §11 (position lifecycle)
  - 03_DATA_MODEL.md §2.3   (positions table)
  - 03_DATA_MODEL.md §2.4   (trade_events table)
  - 07_SKILLS_SPEC.md §4    (avg_price_skill)

Phase: P-Wire-Box-4 (2026-04-30) -- DB-backed conversion of P3.4
       in-memory dict. Single source of truth is now PostgreSQL
       (PRD 03 §0.1 #4). Caller-facing API is async + returns frozen
       :class:`PositionState` snapshots. ORM rows live only inside
       the manager's transaction contexts.

Architecture (architect Q1-Q12 + trading-logic verifier blockers):
  Q1: Frozen :class:`PositionState` DTO returned to callers
      (BoxRecord pattern mirror).
  Q2: ``position_repository`` SQL helpers in a dedicated module.
  Q3: Optional ``session=`` parameter so V71BuyExecutor can wrap
      ``add_position + box_manager.mark_triggered`` in a single
      atomic transaction. External sessions are validated with
      ``session.in_transaction()`` (security H1).
  Q4: trade_events INSERT in the same transaction as the position
      INSERT/UPDATE (FK + audit consistency).
  Q5: avg_price_skill is the only place the math lives.
      ``update_position_after_buy/sell`` is called inside the
      manager; ORM mutation happens once, with the skill result.
  Q6: ``PositionStatus`` re-exported from ``models_v71`` so SQLEnum
      and Python comparisons share the same class object.
  Q7: ``tracked_stock_id`` and ``triggered_box_id`` are ``None`` on
      manual buys (Scenario D); never empty strings.
  Q8: TS state nullable preserved.
  Q10: NFR1 measurement on ``apply_buy/apply_sell`` (warn > 100 ms).

  Blocker 1 (CHECK constraint): ``status`` and ``total_quantity``
      are written together in the same flush so PostgreSQL
      ``position_closed_consistency`` is never transiently violated.
  Blocker 5 (string vs Enum): all status comparisons use
      ``PositionStatus.OPEN`` etc., never the bare string.
  Blocker 9 (Decimal round-trip): ``state.from_orm`` is the single
      conversion site.

AUTHORIZATION INVARIANT (12_SECURITY.md §4):
    This manager performs NO authorization checks itself. Callers
    (V71BuyExecutor, V71ExitExecutor, V71Reconciler) are themselves
    system-only paths. Adding authorization here is FORBIDDEN.

LOG REDACT POLICY (12_SECURITY.md §6.3):
    Log records about positions never include the price / quantity
    / capital fields in plain text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass as _dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.v71.position import position_repository as repo
from src.core.v71.position.state import (
    _PATH_TO_SOURCE,
    PositionState,
    PositionStatus,
    from_orm,
)
from src.core.v71.skills.avg_price_skill import (
    update_position_after_buy,
    update_position_after_sell,
)
from src.core.v71.skills.exit_calc_skill import stage_after_partial_exit
from src.core.v71.v71_constants import V71Constants
from src.database.models_v71 import (
    PositionSource,
    TradeEventType,
)
from src.utils.feature_flags import require_enabled

if TYPE_CHECKING:
    pass


log = logging.getLogger(__name__)

_NFR1_HOT_PATH_BUDGET = V71Constants.NFR1_HOT_PATH_BUDGET_SECONDS

# Allowed buy / sell event types — kept as string sets for backward
# compatibility with caller code; mapped to TradeEventType enum at the
# trade_events INSERT site.
BUY_EVENT_TYPES = frozenset(
    {"BUY_EXECUTED", "PYRAMID_BUY", "MANUAL_PYRAMID_BUY", "MANUAL_BUY"}
)
SELL_EVENT_TYPES = frozenset(
    {"PROFIT_TAKE_5", "PROFIT_TAKE_10", "STOP_LOSS", "TS_EXIT", "MANUAL_SELL"}
)


# String event_type → TradeEventType enum. MANUAL_SELL maps to
# MANUAL_FULL_EXIT or MANUAL_PARTIAL_EXIT depending on remaining qty
# (caller decides; helper below).
_BUY_EVENT_MAP: dict[str, TradeEventType] = {
    "BUY_EXECUTED": TradeEventType.BUY_EXECUTED,
    "PYRAMID_BUY": TradeEventType.PYRAMID_BUY,
    "MANUAL_PYRAMID_BUY": TradeEventType.MANUAL_PYRAMID_BUY,
    "MANUAL_BUY": TradeEventType.MANUAL_BUY,
}
_SELL_EVENT_MAP: dict[str, TradeEventType] = {
    "PROFIT_TAKE_5": TradeEventType.PROFIT_TAKE_5,
    "PROFIT_TAKE_10": TradeEventType.PROFIT_TAKE_10,
    "STOP_LOSS": TradeEventType.STOP_LOSS,
    "TS_EXIT": TradeEventType.TS_EXIT,
}


# ---------------------------------------------------------------------------
# DTO mirror of trade_events (caller-facing TradeEvent type)
# ---------------------------------------------------------------------------

# Re-export the frozen dataclass shape callers used pre-P-Wire-Box-4.
# Implementation now reads from the trade_events ORM table; the in-memory
# dataclass survives so existing code paths (telegram /today, /recent,
# DailySummary) keep their type hints stable.


@_dataclass(frozen=True)
class TradeEvent:
    """Frozen snapshot of a ``trade_events`` row."""

    event_type: str
    position_id: str
    stock_code: str
    quantity: int
    price: int
    timestamp: datetime
    events_reset: bool = False


def _trade_event_from_orm(orm) -> TradeEvent:  # type: ignore[no-untyped-def]
    """Convert ORM TradeEvent → frozen TradeEvent (DTO)."""
    payload = orm.payload or {}
    events_reset = bool(payload.get("events_reset", False))
    return TradeEvent(
        event_type=orm.event_type.value if hasattr(orm.event_type, "value") else str(orm.event_type),
        position_id=str(orm.position_id) if orm.position_id is not None else "",
        stock_code=orm.stock_code,
        quantity=int(orm.quantity) if orm.quantity is not None else 0,
        price=int(orm.price) if orm.price is not None else 0,
        timestamp=orm.occurred_at,
        events_reset=events_reset,
    )


# ---------------------------------------------------------------------------
# Errors (preserved surface)
# ---------------------------------------------------------------------------


class PositionNotFoundError(KeyError):
    """No position with the given id."""


class InvalidEventTypeError(ValueError):
    """``event_type`` is not in the allowed set for the call."""


# ---------------------------------------------------------------------------
# V71PositionManager
# ---------------------------------------------------------------------------


class V71PositionManager:
    """DB-backed manager for ``positions`` rows (+ trade_events audit).

    See module docstring for architectural decisions. Callers see
    ``async`` methods returning frozen :class:`PositionState`. The
    manager's optional ``session=`` parameter lets V71BuyExecutor wrap
    ``add_position + box_manager.mark_triggered`` in a single atomic
    transaction (Q3).
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        require_enabled("v71.position_v71")
        if session_factory is None:
            raise ValueError("session_factory is required")
        self._sm = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- session helpers -------------------------------------------------

    @staticmethod
    def _ensure_in_transaction(session: AsyncSession) -> None:
        """Security H1: external session must own a transaction.

        ``with_for_update`` is silently lost when the session has no
        active begin() — failing loud is safer than a broken lock.
        """
        if not session.in_transaction():
            raise ValueError(
                "external session must be inside a transaction "
                "(call session.begin() before passing it to V71PositionManager)"
            )

    async def _with_session(
        self,
        provided: AsyncSession | None,
        inner: Callable[..., Awaitable[object]],
        **kwargs: object,
    ) -> object:
        if provided is not None:
            self._ensure_in_transaction(provided)
            return await inner(provided, **kwargs)
        async with self._sm() as session, session.begin():
            return await inner(session, **kwargs)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def add_position(
        self,
        *,
        stock_code: str,
        stock_name: str | None = None,
        tracked_stock_id: str | None,
        triggered_box_id: str | None,
        path_type: str,  # "PATH_A" | "PATH_B" | "MANUAL"
        quantity: int,
        weighted_avg_price: int,
        opened_at: datetime,
        actual_capital_invested: int | None = None,
        session: AsyncSession | None = None,
    ) -> PositionState:
        """Insert a new OPEN position + BUY_EXECUTED trade_event in one
        transaction. Returns the frozen state.

        The ``session=`` parameter is the Q3 atomic seam: V71BuyExecutor
        passes its outer session so this INSERT and a subsequent
        ``box_manager.mark_triggered`` either both commit or both roll
        back (orphan-box-vs-orphan-position elimination).
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if weighted_avg_price <= 0:
            raise ValueError("weighted_avg_price must be positive")

        return await self._with_session(
            session,
            self._add_position_inner,
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            tracked_stock_id=tracked_stock_id,
            triggered_box_id=triggered_box_id,
            path_type=path_type,
            quantity=quantity,
            weighted_avg_price=weighted_avg_price,
            opened_at=opened_at,
            actual_capital_invested=(
                actual_capital_invested
                if actual_capital_invested is not None
                else weighted_avg_price * quantity
            ),
        )

    async def _add_position_inner(
        self,
        session: AsyncSession,
        *,
        stock_code: str,
        stock_name: str,
        tracked_stock_id: str | None,
        triggered_box_id: str | None,
        path_type: str,
        quantity: int,
        weighted_avg_price: int,
        opened_at: datetime,
        actual_capital_invested: int,
    ) -> PositionState:
        # Map path_type → PositionSource. Unknown path_type defaults to
        # MANUAL so callers cannot silently invent enum values.
        source_value = _PATH_TO_SOURCE.get(path_type, "MANUAL")
        try:
            source = PositionSource(source_value)
        except ValueError as exc:
            raise ValueError(
                f"unknown path_type {path_type!r} (expected PATH_A / PATH_B / MANUAL)"
            ) from exc

        fixed_stop = int(
            round(weighted_avg_price * (1.0 + V71Constants.STOP_LOSS_INITIAL_PCT))
        )
        orm = repo.insert_position(
            session,
            stock_code=stock_code,
            stock_name=stock_name,
            tracked_stock_id=tracked_stock_id,
            triggered_box_id=triggered_box_id,
            source=source,
            weighted_avg_price=weighted_avg_price,
            total_quantity=quantity,
            fixed_stop_price=fixed_stop,
            actual_capital_invested=actual_capital_invested,
        )
        await session.flush()
        await session.refresh(orm)
        # trade_event same-tx INSERT (Q4)
        repo.insert_event(
            session,
            event_type=TradeEventType.BUY_EXECUTED,
            position_id=orm.id,
            stock_code=stock_code,
            quantity=quantity,
            price=weighted_avg_price,
            occurred_at=opened_at,
            avg_price_after=weighted_avg_price,
        )
        await session.flush()
        log.info(
            "v71_position_added",
            extra={
                "position_id": str(orm.id),
                "stock_code": stock_code,
                "tracked_stock_id": str(tracked_stock_id) if tracked_stock_id else None,
                "path_type": path_type,
            },
        )
        return from_orm(orm)

    async def apply_buy(
        self,
        position_id: str,
        *,
        buy_price: int,
        buy_quantity: int,
        event_type: str = "PYRAMID_BUY",
        when: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> PositionState:
        """Add to an existing position (§6.2 weighted avg + event reset).

        Calls avg_price_skill.update_position_after_buy and persists
        the result + trade_event in one transaction.
        """
        if event_type not in BUY_EVENT_TYPES:
            raise InvalidEventTypeError(
                f"buy event_type must be one of {sorted(BUY_EVENT_TYPES)}; "
                f"got {event_type!r}"
            )
        return await self._with_session(
            session,
            self._apply_buy_inner,
            position_id=position_id,
            buy_price=buy_price,
            buy_quantity=buy_quantity,
            event_type=event_type,
            when=when or self._clock(),
        )

    async def _apply_buy_inner(
        self,
        session: AsyncSession,
        *,
        position_id: str,
        buy_price: int,
        buy_quantity: int,
        event_type: str,
        when: datetime,
    ) -> PositionState:
        t0 = time.perf_counter()
        try:
            orm = await repo.fetch_position(session, position_id, for_update=True)
            if orm is None:
                raise PositionNotFoundError(f"No position with id {position_id!r}")
            state_before = from_orm(orm)
            avg_before = state_before.weighted_avg_price
            update = update_position_after_buy(
                state_before, buy_price=buy_price, buy_quantity=buy_quantity,
            )
            self._apply_update_to_orm(orm, update)
            # apply_buy never closes a position; status stays OPEN /
            # PARTIAL_CLOSED. PRD §6.2 — pyramid revives PARTIAL_CLOSED
            # back to OPEN (full lots restored, ladder reset to stage 1).
            if state_before.status is PositionStatus.PARTIAL_CLOSED:
                orm.status = PositionStatus.OPEN
            await session.flush()
            await session.refresh(orm)
            repo.insert_event(
                session,
                event_type=_BUY_EVENT_MAP.get(event_type, TradeEventType.PYRAMID_BUY),
                position_id=orm.id,
                stock_code=orm.stock_code,
                quantity=buy_quantity,
                price=buy_price,
                occurred_at=when,
                events_reset=update.events_reset,
                avg_price_before=avg_before,
                avg_price_after=int(orm.weighted_avg_price),
            )
            await session.flush()
            return from_orm(orm)
        finally:
            elapsed = time.perf_counter() - t0
            if elapsed > _NFR1_HOT_PATH_BUDGET:
                log.warning(
                    "v71_position_apply_buy_slow",
                    extra={
                        "position_id": position_id,
                        "elapsed_seconds": round(elapsed, 4),
                    },
                )

    async def apply_sell(
        self,
        position_id: str,
        *,
        sell_quantity: int,
        sell_price: int,
        event_type: str,
        when: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> PositionState:
        """Reduce a position's quantity (§6.4 avg unchanged).

        Advances the stop ladder for profit-takes (§5.4):
            PROFIT_TAKE_5  -> profit_5_executed = True, stop -> -2%
            PROFIT_TAKE_10 -> profit_10_executed = True, stop -> +4%
            STOP_LOSS / TS_EXIT / MANUAL_SELL -> ladder unchanged.

        Sets ``status = CLOSED`` + ``closed_at`` when total reaches 0.
        ``status`` and ``total_quantity`` are written in the same flush
        so PostgreSQL ``position_closed_consistency`` CHECK is never
        transiently violated (blocker 1).
        """
        if event_type not in SELL_EVENT_TYPES:
            raise InvalidEventTypeError(
                f"sell event_type must be one of {sorted(SELL_EVENT_TYPES)}; "
                f"got {event_type!r}"
            )
        return await self._with_session(
            session,
            self._apply_sell_inner,
            position_id=position_id,
            sell_quantity=sell_quantity,
            sell_price=sell_price,
            event_type=event_type,
            when=when or self._clock(),
        )

    async def _apply_sell_inner(
        self,
        session: AsyncSession,
        *,
        position_id: str,
        sell_quantity: int,
        sell_price: int,
        event_type: str,
        when: datetime,
    ) -> PositionState:
        t0 = time.perf_counter()
        try:
            orm = await repo.fetch_position(session, position_id, for_update=True)
            if orm is None:
                raise PositionNotFoundError(f"No position with id {position_id!r}")
            state_before = from_orm(orm)
            avg_before = state_before.weighted_avg_price
            update = update_position_after_sell(
                state_before, sell_quantity=sell_quantity,
            )

            # Profit-take ladder advance (§5.4).
            # Trading-logic blocker 8: PROFIT_TAKE_10 implies PROFIT_TAKE_5
            # was already executed (§5.2 then §5.3 sequence). Even if a
            # caller skips the sequence (unit-test bug, calculator regression),
            # we force ``profit_5_executed`` so the ladder lookup never
            # produces an undefined state.
            new_p5 = state_before.profit_5_executed
            new_p10 = state_before.profit_10_executed
            if event_type == "PROFIT_TAKE_5":
                new_p5 = True
            elif event_type == "PROFIT_TAKE_10":
                new_p5 = True
                new_p10 = True

            new_fixed_stop = (
                stage_after_partial_exit(new_p5, new_p10, state_before.weighted_avg_price)
                if event_type in {"PROFIT_TAKE_5", "PROFIT_TAKE_10"}
                else state_before.fixed_stop_price
            )

            # Apply skill update + ladder advance to ORM.
            orm.weighted_avg_price = Decimal(update.weighted_avg_price)
            orm.initial_avg_price = Decimal(update.initial_avg_price)
            orm.total_quantity = int(update.total_quantity)
            orm.fixed_stop_price = Decimal(new_fixed_stop)
            orm.profit_5_executed = bool(new_p5)
            orm.profit_10_executed = bool(new_p10)
            orm.ts_activated = bool(update.ts_activated)
            orm.ts_base_price = (
                Decimal(update.ts_base_price)
                if update.ts_base_price is not None
                else None
            )
            orm.ts_stop_price = (
                Decimal(update.ts_stop_price)
                if update.ts_stop_price is not None
                else None
            )
            orm.ts_active_multiplier = (
                Decimal(str(update.ts_active_multiplier))
                if update.ts_active_multiplier is not None
                else None
            )

            # Lifecycle (blocker 1: status + total_quantity together).
            if update.total_quantity == 0:
                orm.status = PositionStatus.CLOSED
                orm.closed_at = when
                if orm.close_reason is None:
                    orm.close_reason = event_type
            elif state_before.status is PositionStatus.OPEN:
                orm.status = PositionStatus.PARTIAL_CLOSED
            await session.flush()
            await session.refresh(orm)

            # Map sell event_type to ORM enum. MANUAL_SELL splits by
            # remaining quantity (full vs partial).
            if event_type == "MANUAL_SELL":
                ev_enum = (
                    TradeEventType.MANUAL_FULL_EXIT
                    if update.total_quantity == 0
                    else TradeEventType.MANUAL_PARTIAL_EXIT
                )
            else:
                ev_enum = _SELL_EVENT_MAP[event_type]
            repo.insert_event(
                session,
                event_type=ev_enum,
                position_id=orm.id,
                stock_code=orm.stock_code,
                quantity=sell_quantity,
                price=sell_price,
                occurred_at=when,
                avg_price_before=avg_before,
                avg_price_after=int(orm.weighted_avg_price),
            )
            await session.flush()
            return from_orm(orm)
        finally:
            elapsed = time.perf_counter() - t0
            if elapsed > _NFR1_HOT_PATH_BUDGET:
                log.warning(
                    "v71_position_apply_sell_slow",
                    extra={
                        "position_id": position_id,
                        "elapsed_seconds": round(elapsed, 4),
                    },
                )

    async def close_position(
        self,
        position_id: str,
        *,
        when: datetime | None = None,
        reason: str | None = None,
        session: AsyncSession | None = None,
    ) -> PositionState:
        """Mark a zero-quantity position as CLOSED.

        Idempotent — closing an already-CLOSED position is a no-op.
        Raises if quantity is non-zero (caller must apply_sell first).
        """
        return await self._with_session(
            session,
            self._close_position_inner,
            position_id=position_id,
            when=when or self._clock(),
            reason=reason,
        )

    async def _close_position_inner(
        self,
        session: AsyncSession,
        *,
        position_id: str,
        when: datetime,
        reason: str | None,
    ) -> PositionState:
        orm = await repo.fetch_position(session, position_id, for_update=True)
        if orm is None:
            raise PositionNotFoundError(f"No position with id {position_id!r}")
        if int(orm.total_quantity) != 0:
            raise ValueError(
                f"Cannot close position {position_id} with non-zero quantity "
                f"({orm.total_quantity})"
            )
        if orm.status is not PositionStatus.CLOSED:
            orm.status = PositionStatus.CLOSED
            orm.closed_at = when
            if reason is not None and orm.close_reason is None:
                orm.close_reason = reason
            await session.flush()
            await session.refresh(orm)
        return from_orm(orm)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get(
        self,
        position_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> PositionState:
        return await self._with_session(
            session, self._get_inner, position_id=position_id,
        )

    async def _get_inner(
        self, session: AsyncSession, *, position_id: str,
    ) -> PositionState:
        orm = await repo.fetch_position(session, position_id)
        if orm is None:
            raise PositionNotFoundError(f"No position with id {position_id!r}")
        return from_orm(orm)

    async def get_by_stock(
        self,
        stock_code: str,
        path_type: str,
        *,
        session: AsyncSession | None = None,
    ) -> PositionState | None:
        return await self._with_session(
            session,
            self._get_by_stock_inner,
            stock_code=stock_code,
            path_type=path_type,
        )

    async def _get_by_stock_inner(
        self,
        session: AsyncSession,
        *,
        stock_code: str,
        path_type: str,
    ) -> PositionState | None:
        source_value = _PATH_TO_SOURCE.get(path_type, path_type)
        orm = await repo.fetch_active_for_stock_path(
            session, stock_code, source_value,
        )
        return from_orm(orm) if orm is not None else None

    async def list_open(
        self,
        *,
        limit: int = 1000,
        session: AsyncSession | None = None,
    ) -> list[PositionState]:
        return await self._with_session(
            session, self._list_open_inner, limit=limit,
        )

    async def _list_open_inner(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[PositionState]:
        rows = await repo.list_open(session, limit=limit)
        return [from_orm(o) for o in rows]

    async def list_for_stock(
        self,
        stock_code: str,
        *,
        include_closed: bool = False,
        session: AsyncSession | None = None,
    ) -> list[PositionState]:
        return await self._with_session(
            session,
            self._list_for_stock_inner,
            stock_code=stock_code,
            include_closed=include_closed,
        )

    async def lock_active_for_stock(
        self,
        stock_code: str,
        *,
        session: AsyncSession,
    ) -> list[PositionState]:
        """``SELECT ... FOR UPDATE`` on every active (non-CLOSED) position
        for ``stock_code``. Caller owns the transaction.

        Used by V71Reconciler Scenario B (이중 경로 비례 차감) so the
        drain-MANUAL-then-split allocation is race-free against
        ExitExecutor / BuyExecutor running concurrently.

        Raises ``ValueError`` if ``session`` is not in a transaction
        (security H1: silently-lost FOR UPDATE is worse than no lock).
        """
        self._ensure_in_transaction(session)
        rows = await repo.fetch_active_for_stock(
            session, stock_code, for_update=True,
        )
        return [from_orm(o) for o in rows]

    async def _list_for_stock_inner(
        self,
        session: AsyncSession,
        *,
        stock_code: str,
        include_closed: bool,
    ) -> list[PositionState]:
        rows = await repo.list_for_stock(
            session, stock_code, include_closed=include_closed,
        )
        return [from_orm(o) for o in rows]

    async def list_events(
        self,
        *,
        position_id: str | None = None,
        since: datetime | None = None,
        limit: int = 1000,
        session: AsyncSession | None = None,
    ) -> list[TradeEvent]:
        return await self._with_session(
            session,
            self._list_events_inner,
            position_id=position_id,
            since=since,
            limit=limit,
        )

    async def _list_events_inner(
        self,
        session: AsyncSession,
        *,
        position_id: str | None,
        since: datetime | None,
        limit: int,
    ) -> list[TradeEvent]:
        if position_id is not None:
            rows = await repo.list_events_for_position(session, position_id)
        elif since is not None:
            rows = await repo.list_events_since(session, since=since, limit=limit)
        else:
            # No filter: return events for last 24 hours by default
            now = self._clock()
            from datetime import timedelta
            rows = await repo.list_events_since(
                session, since=now - timedelta(days=1), limit=limit,
            )
        return [_trade_event_from_orm(o) for o in rows]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_update_to_orm(orm, update) -> None:  # type: ignore[no-untyped-def]
        """Apply a PositionUpdate (avg_price_skill result) to an ORM row.

        Single mutation site so blocker 9 (Decimal/int round-trip) is
        contained — float ts_active_multiplier goes through ``str()``
        before Decimal cast to keep the precision PRD §5.5 intends.
        """
        orm.weighted_avg_price = Decimal(update.weighted_avg_price)
        orm.initial_avg_price = Decimal(update.initial_avg_price)
        orm.total_quantity = int(update.total_quantity)
        orm.fixed_stop_price = Decimal(update.fixed_stop_price)
        orm.profit_5_executed = bool(update.profit_5_executed)
        orm.profit_10_executed = bool(update.profit_10_executed)
        orm.ts_activated = bool(update.ts_activated)
        orm.ts_base_price = (
            Decimal(update.ts_base_price) if update.ts_base_price is not None else None
        )
        orm.ts_stop_price = (
            Decimal(update.ts_stop_price) if update.ts_stop_price is not None else None
        )
        orm.ts_active_multiplier = (
            Decimal(str(update.ts_active_multiplier))
            if update.ts_active_multiplier is not None
            else None
        )


__all__ = [
    "BUY_EVENT_TYPES",
    "InvalidEventTypeError",
    "PositionNotFoundError",
    "PositionState",
    "PositionStatus",
    "SELL_EVENT_TYPES",
    "TradeEvent",
    "V71PositionManager",
]
