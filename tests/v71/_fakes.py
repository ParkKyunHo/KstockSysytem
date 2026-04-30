"""Test stubs that replace pre-P-Wire-Box-1 V71BoxManager() call sites.

The legacy in-memory dict manager survives here as FakeBoxManager
so test files that drive the manager directly (telegram_commands,
buy_executor, exit_executor, ...) keep working without spinning up
an aiosqlite engine in every fixture.
"""

from __future__ import annotations

# ruff: noqa: ARG002 -- session= passthrough kwargs match the real V71BoxManager API
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# FakeBoxManager: async drop-in for tests that pre-date P-Wire-Box-1.
# ---------------------------------------------------------------------------
#
# Why this exists:
#   Pre-P-Wire-Box-1 tests called ``bm = V71BoxManager()`` and then
#   drove it directly (``bm.create_box(...)``, ``bm.list_all()``). The
#   real manager is now async + DB-backed and requires a
#   ``session_factory``. Rewriting nine test files to spin up an
#   aiosqlite engine in every fixture would dilute the test intent --
#   most of those files care about something else (telegram commands,
#   exit executor, daily summary, ...) and just need a working
#   box_manager.
#
#   FakeBoxManager keeps the original in-memory storage but exposes
#   the new async API surface (with ``await`` on every mutation).
#   Existing tests change minimally:
#       bm = V71BoxManager()        ->  bm = FakeBoxManager()
#       bm.create_box(...)          ->  await bm.create_box(...)
#       bm.mark_triggered(box.id)   ->  await bm.mark_triggered(box.id)
#
#   Tests that exercise the real DB-backed path live under
#   ``tests/v71/box/`` and use the production V71BoxManager directly.

if TYPE_CHECKING:
    from src.core.v71.box.box_record import BoxRecord


class FakeBoxManager:
    """In-memory async stub of :class:`V71BoxManager` for legacy tests."""

    def __init__(self) -> None:
        from src.utils.feature_flags import require_enabled

        require_enabled("v71.box_system")
        self._boxes: dict[str, BoxRecord] = {}
        self._by_tracked: dict[str, set[str]] = {}

    async def create_box(
        self,
        *,
        tracked_stock_id: str,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        strategy_type,
        path_type,
        stop_loss_pct: float = -0.05,
        memo: str | None = None,
        session=None,
    ):
        from src.core.v71.box.box_manager import (
            BoxOverlapError,
            V71BoxManager,
        )
        from src.core.v71.box.box_record import BoxRecord
        from src.core.v71.box.box_state_machine import BoxStatus

        # Re-use the production validator so legacy tests still hit
        # the same error surface.
        V71BoxManager._validate_box_fields(  # noqa: SLF001
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
        )
        siblings = [
            self._boxes[i]
            for i in self._by_tracked.get(tracked_stock_id, set())
            if self._boxes[i].status is BoxStatus.WAITING
            and self._boxes[i].path_type == path_type
        ]
        for sib in siblings:
            if upper_price > sib.lower_price and lower_price < sib.upper_price:
                raise BoxOverlapError(
                    f"Box overlaps an existing WAITING sibling "
                    f"(sibling={sib.id})"
                )
        existing = [
            self._boxes[i]
            for i in self._by_tracked.get(tracked_stock_id, set())
            if self._boxes[i].path_type == path_type
        ]
        tier = max((b.box_tier for b in existing), default=0) + 1
        record = BoxRecord(
            id=str(uuid.uuid4()),
            tracked_stock_id=tracked_stock_id,
            box_tier=tier,
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            strategy_type=strategy_type,
            path_type=path_type,
            status=BoxStatus.WAITING,
            memo=memo,
            created_at=datetime.now(timezone.utc),
            modified_at=datetime.now(timezone.utc),
        )
        self._boxes[record.id] = record
        self._by_tracked.setdefault(tracked_stock_id, set()).add(record.id)
        return record

    async def modify_box(
        self,
        box_id: str,
        *,
        upper_price: int | None = None,
        lower_price: int | None = None,
        position_size_pct: float | None = None,
        stop_loss_pct: float | None = None,
        memo: str | None = None,
        force_relax_stop: bool = False,
        session=None,
    ):
        from dataclasses import replace

        from src.core.v71.box.box_manager import (
            BoxModificationError,
            BoxNotFoundError,
            BoxOverlapError,
            V71BoxManager,
        )
        from src.core.v71.box.box_state_machine import BoxStatus

        record = self._boxes.get(box_id)
        if record is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        if record.status is not BoxStatus.WAITING:
            raise BoxModificationError(
                f"Cannot modify box {box_id} in status {record.status.value}"
            )
        new_upper = upper_price if upper_price is not None else record.upper_price
        new_lower = lower_price if lower_price is not None else record.lower_price
        new_size = (
            position_size_pct
            if position_size_pct is not None
            else record.position_size_pct
        )
        new_stop = stop_loss_pct if stop_loss_pct is not None else record.stop_loss_pct
        V71BoxManager._validate_box_fields(  # noqa: SLF001
            upper_price=new_upper,
            lower_price=new_lower,
            position_size_pct=new_size,
            stop_loss_pct=new_stop,
        )
        if new_stop < record.stop_loss_pct - 1e-9 and not force_relax_stop:
            raise BoxModificationError(
                f"stop_loss_pct relaxed from {record.stop_loss_pct} to "
                f"{new_stop}; pass force_relax_stop=True to confirm "
                "(UI must show warning)."
            )
        if upper_price is not None or lower_price is not None:
            siblings = [
                self._boxes[i]
                for i in self._by_tracked.get(record.tracked_stock_id, set())
                if i != box_id
                and self._boxes[i].status is BoxStatus.WAITING
                and self._boxes[i].path_type == record.path_type
            ]
            for sib in siblings:
                if new_upper > sib.lower_price and new_lower < sib.upper_price:
                    raise BoxOverlapError(
                        "Modified prices overlap a sibling WAITING box"
                    )
        new_record = replace(
            record,
            upper_price=new_upper,
            lower_price=new_lower,
            position_size_pct=new_size,
            stop_loss_pct=new_stop,
            memo=memo if memo is not None else record.memo,
            modified_at=datetime.now(timezone.utc),
        )
        self._boxes[box_id] = new_record
        return new_record

    async def delete_box(
        self,
        box_id: str,
        *,
        on_orphan_cancel: Callable[[str], Awaitable[None] | None] | None = None,
        session=None,
    ):
        from dataclasses import replace

        from src.core.v71.box.box_manager import (
            BoxModificationError,
            BoxNotFoundError,
        )
        from src.core.v71.box.box_state_machine import BoxStatus

        record = self._boxes.get(box_id)
        if record is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        if record.status is not BoxStatus.WAITING:
            raise BoxModificationError(
                f"Cannot delete box {box_id} in status {record.status.value}"
            )
        new_record = replace(
            record,
            status=BoxStatus.CANCELLED,
            invalidation_reason="USER_DELETED",
            modified_at=datetime.now(timezone.utc),
        )
        self._boxes[box_id] = new_record
        if on_orphan_cancel is not None:
            try:
                result = on_orphan_cancel(box_id)
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001 - callback isolation
                pass
        return new_record

    async def mark_triggered(self, box_id: str, *, session=None):
        from dataclasses import replace

        from src.core.v71.box.box_manager import BoxNotFoundError
        from src.core.v71.box.box_state_machine import (
            BoxEvent,
            transition_box,
        )

        record = self._boxes.get(box_id)
        if record is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        next_status = transition_box(record.status, BoxEvent.BUY_EXECUTED)
        new_record = replace(
            record,
            status=next_status,
            triggered_at=datetime.now(timezone.utc),
            modified_at=datetime.now(timezone.utc),
        )
        self._boxes[box_id] = new_record
        return new_record

    async def mark_invalidated(
        self, box_id: str, *, reason: str, session=None,
    ):
        from dataclasses import replace

        from src.core.v71.box.box_manager import BoxNotFoundError
        from src.core.v71.box.box_state_machine import (
            BoxEvent,
            transition_box,
        )

        valid_reasons = {
            "MANUAL_BUY_DETECTED": BoxEvent.MANUAL_BUY_DETECTED,
            "AUTO_EXIT_BOX_DROP": BoxEvent.AUTO_EXIT_BOX_DROP,
            "COMPENSATION_FAILED": BoxEvent.COMPENSATION_FAILED,
        }
        if reason not in valid_reasons:
            raise ValueError(
                f"reason must be one of {sorted(valid_reasons)}; "
                f"got {reason!r}"
            )
        record = self._boxes.get(box_id)
        if record is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        next_status = transition_box(record.status, valid_reasons[reason])
        new_record = replace(
            record,
            status=next_status,
            invalidation_reason=reason,
            invalidated_at=datetime.now(timezone.utc),
            modified_at=datetime.now(timezone.utc),
        )
        self._boxes[box_id] = new_record
        return new_record

    async def cancel_waiting_for_tracked(
        self,
        tracked_stock_id: str,
        *,
        reason: str = "POSITION_CLOSED",
        on_orphan_cancel: Callable[[str], Awaitable[None] | None] | None = None,
        session=None,
    ):
        from dataclasses import replace

        from src.core.v71.box.box_state_machine import (
            BoxEvent,
            BoxStatus,
            transition_box,
        )

        cancelled = []
        for box_id in list(self._by_tracked.get(tracked_stock_id, set())):
            record = self._boxes[box_id]
            if record.status is not BoxStatus.WAITING:
                continue
            next_status = transition_box(record.status, BoxEvent.USER_DELETED)
            new_record = replace(
                record,
                status=next_status,
                invalidation_reason=reason,
                modified_at=datetime.now(timezone.utc),
            )
            self._boxes[box_id] = new_record
            cancelled.append(new_record)
        if on_orphan_cancel is not None:
            for record in cancelled:
                try:
                    result = on_orphan_cancel(record.id)
                    if hasattr(result, "__await__"):
                        await result
                except Exception:  # noqa: BLE001 - per-callback isolation
                    pass
        return cancelled

    async def get(self, box_id: str, *, session=None):
        from src.core.v71.box.box_manager import BoxNotFoundError

        record = self._boxes.get(box_id)
        if record is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        return record

    async def list_for_tracked(self, tracked_stock_id: str, *, session=None):
        ids = self._by_tracked.get(tracked_stock_id, set())
        return [self._boxes[i] for i in ids]

    async def list_waiting_for_tracked(
        self, tracked_stock_id: str, path_type, *, session=None,
    ):
        from src.core.v71.box.box_state_machine import BoxStatus

        ids = self._by_tracked.get(tracked_stock_id, set())
        return [
            self._boxes[i]
            for i in ids
            if self._boxes[i].status is BoxStatus.WAITING
            and self._boxes[i].path_type == path_type
        ]

    async def list_all(self, *, status=None, limit: int = 1000, session=None):
        result = list(self._boxes.values())
        if status is not None:
            result = [b for b in result if b.status is status]
        return result[:limit]

    async def check_30day_expiry(self, *, now=None, session=None):
        from src.core.v71.box.box_state_machine import BoxStatus

        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be tz-aware")
        threshold = timedelta(days=30)
        result = []
        for box in self._boxes.values():
            if box.status is not BoxStatus.WAITING:
                continue
            anchor = box.last_reminder_at or box.created_at
            if anchor is None:
                continue
            if now - anchor >= threshold:
                result.append(box)
        return result

    async def mark_reminded(self, box_id: str, *, when=None, session=None):
        from dataclasses import replace

        from src.core.v71.box.box_manager import BoxNotFoundError

        record = self._boxes.get(box_id)
        if record is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        new_record = replace(
            record, last_reminder_at=when or datetime.now(timezone.utc),
        )
        self._boxes[box_id] = new_record
        return new_record


# ---------------------------------------------------------------------------
# FakePositionManager: in-memory async stub of V71PositionManager.
# ---------------------------------------------------------------------------
#
# Mirror of FakeBoxManager — keeps the pre-P-Wire-Box-4 in-memory storage
# but exposes the new async + frozen-PositionState API surface. Tests that
# drive the manager directly (BuyExecutor, ExitExecutor, Reconciler, ...)
# can swap V71PositionManager() -> FakePositionManager() with minimal
# diff. add_position / apply_buy / apply_sell return frozen
# PositionState snapshots; list_open is async; lock_active_for_stock
# returns the same as fetch_active_for_stock (no FOR UPDATE in memory).


class FakePositionManager:
    """In-memory async stub of :class:`V71PositionManager`."""

    def __init__(self) -> None:
        from src.utils.feature_flags import require_enabled

        require_enabled("v71.position_v71")
        from src.core.v71.position.state import PositionState

        self._positions: dict[str, PositionState] = {}
        self._events: list = []

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    async def add_position(
        self,
        *,
        stock_code: str,
        stock_name: str | None = None,
        tracked_stock_id: str | None,
        triggered_box_id: str | None,
        path_type: str,
        quantity: int,
        weighted_avg_price: int,
        opened_at: datetime,
        actual_capital_invested: int | None = None,
        session=None,
    ):
        from src.core.v71.position.state import PositionState, PositionStatus
        from src.core.v71.v71_constants import V71Constants

        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if weighted_avg_price <= 0:
            raise ValueError("weighted_avg_price must be positive")

        position_id = self._new_id()
        fixed_stop = int(
            round(weighted_avg_price * (1.0 + V71Constants.STOP_LOSS_INITIAL_PCT))
        )
        state = PositionState(
            position_id=position_id,
            stock_code=stock_code,
            tracked_stock_id=tracked_stock_id,
            triggered_box_id=triggered_box_id,
            path_type=path_type,
            weighted_avg_price=int(weighted_avg_price),
            initial_avg_price=int(weighted_avg_price),
            total_quantity=int(quantity),
            fixed_stop_price=fixed_stop,
            status=PositionStatus.OPEN,
            opened_at=opened_at,
        )
        self._positions[position_id] = state
        return state

    async def apply_buy(
        self,
        position_id: str,
        *,
        buy_price: int,
        buy_quantity: int,
        event_type: str = "PYRAMID_BUY",
        when=None,
        session=None,
    ):
        from dataclasses import replace

        from src.core.v71.position.state import PositionStatus
        from src.core.v71.position.v71_position_manager import (
            BUY_EVENT_TYPES,
            InvalidEventTypeError,
            PositionNotFoundError,
        )
        from src.core.v71.skills.avg_price_skill import (
            update_position_after_buy,
        )

        if event_type not in BUY_EVENT_TYPES:
            raise InvalidEventTypeError(f"buy event_type invalid: {event_type}")
        state = self._positions.get(position_id)
        if state is None:
            raise PositionNotFoundError(position_id)
        update = update_position_after_buy(
            state, buy_price=buy_price, buy_quantity=buy_quantity,
        )
        new_state = replace(
            state,
            weighted_avg_price=update.weighted_avg_price,
            initial_avg_price=update.initial_avg_price,
            total_quantity=update.total_quantity,
            fixed_stop_price=update.fixed_stop_price,
            profit_5_executed=update.profit_5_executed,
            profit_10_executed=update.profit_10_executed,
            ts_activated=update.ts_activated,
            ts_base_price=update.ts_base_price,
            ts_stop_price=update.ts_stop_price,
            ts_active_multiplier=update.ts_active_multiplier,
            status=(
                PositionStatus.OPEN
                if state.status is PositionStatus.PARTIAL_CLOSED
                else state.status
            ),
        )
        self._positions[position_id] = new_state
        return new_state

    async def apply_sell(
        self,
        position_id: str,
        *,
        sell_quantity: int,
        sell_price: int,
        event_type: str,
        when=None,
        session=None,
    ):
        from dataclasses import replace

        from src.core.v71.position.state import PositionStatus
        from src.core.v71.position.v71_position_manager import (
            SELL_EVENT_TYPES,
            InvalidEventTypeError,
            PositionNotFoundError,
        )
        from src.core.v71.skills.avg_price_skill import (
            update_position_after_sell,
        )
        from src.core.v71.skills.exit_calc_skill import (
            stage_after_partial_exit,
        )

        if event_type not in SELL_EVENT_TYPES:
            raise InvalidEventTypeError(f"sell event_type invalid: {event_type}")
        state = self._positions.get(position_id)
        if state is None:
            raise PositionNotFoundError(position_id)
        update = update_position_after_sell(state, sell_quantity=sell_quantity)

        new_p5 = state.profit_5_executed
        new_p10 = state.profit_10_executed
        if event_type == "PROFIT_TAKE_5":
            new_p5 = True
        elif event_type == "PROFIT_TAKE_10":
            new_p5 = True
            new_p10 = True
        new_fixed_stop = (
            stage_after_partial_exit(new_p5, new_p10, state.weighted_avg_price)
            if event_type in {"PROFIT_TAKE_5", "PROFIT_TAKE_10"}
            else state.fixed_stop_price
        )
        if update.total_quantity == 0:
            status = PositionStatus.CLOSED
            closed_at = when or datetime.now(timezone.utc)
        elif state.status is PositionStatus.OPEN:
            status = PositionStatus.PARTIAL_CLOSED
            closed_at = state.closed_at
        else:
            status = state.status
            closed_at = state.closed_at
        new_state = replace(
            state,
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
            status=status,
            closed_at=closed_at,
        )
        self._positions[position_id] = new_state
        return new_state

    async def close_position(
        self, position_id: str, *, when=None, reason=None, session=None,
    ):
        from dataclasses import replace

        from src.core.v71.position.state import PositionStatus
        from src.core.v71.position.v71_position_manager import (
            PositionNotFoundError,
        )

        state = self._positions.get(position_id)
        if state is None:
            raise PositionNotFoundError(position_id)
        if state.total_quantity != 0:
            raise ValueError("close_position requires zero quantity")
        if state.status is not PositionStatus.CLOSED:
            new_state = replace(
                state,
                status=PositionStatus.CLOSED,
                closed_at=when or datetime.now(timezone.utc),
            )
            self._positions[position_id] = new_state
            return new_state
        return state

    async def get(self, position_id: str, *, session=None):
        from src.core.v71.position.v71_position_manager import (
            PositionNotFoundError,
        )

        state = self._positions.get(position_id)
        if state is None:
            raise PositionNotFoundError(position_id)
        return state

    async def get_by_stock(
        self, stock_code: str, path_type: str, *, session=None,
    ):
        from src.core.v71.position.state import PositionStatus

        for state in self._positions.values():
            if (
                state.stock_code == stock_code
                and state.path_type == path_type
                and state.status is not PositionStatus.CLOSED
            ):
                return state
        return None

    async def list_open(self, *, limit: int = 1000, session=None):
        from src.core.v71.position.state import PositionStatus

        return [
            s for s in self._positions.values()
            if s.status is not PositionStatus.CLOSED
        ][:limit]

    async def list_for_stock(
        self,
        stock_code: str,
        *,
        include_closed: bool = False,
        session=None,
    ):
        from src.core.v71.position.state import PositionStatus

        result = [s for s in self._positions.values() if s.stock_code == stock_code]
        if not include_closed:
            result = [s for s in result if s.status is not PositionStatus.CLOSED]
        return result

    async def lock_active_for_stock(
        self, stock_code: str, *, session,
    ):
        # In-memory: no FOR UPDATE semantics. Return active list.
        return await self.list_for_stock(stock_code, include_closed=False)

    async def list_events(
        self,
        *,
        position_id: str | None = None,
        since: datetime | None = None,
        limit: int = 1000,
        session=None,
    ):
        return list(self._events)[:limit]
