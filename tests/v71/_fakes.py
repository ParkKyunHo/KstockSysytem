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
