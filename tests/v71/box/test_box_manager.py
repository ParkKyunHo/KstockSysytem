"""V71BoxManager DB-backed tests (P-Wire-Box-1).

Scope (this file):
    - Happy paths for every public method.
    - Validation + state-transition guards (§3.1, §3.4, §3.6, §3.13, §5.9).
    - 30-day reminder TZ-awareness (§3.7, architect Q5).
    - on_orphan_cancel callback isolation (trading-logic blocker 2).
    - Regression for the user-reported symptom: a box created via
      manager.create_box() is visible to subsequent list_all() /
      list_waiting_for_tracked() calls and survives manager restart
      (the in-memory dict regression).

Excluded (separate units):
    - Postgres-only race + partial-index behaviour (tests/v71/box/db/).
    - BuyExecutor compensation chain (tests/v71/strategies/
      test_buy_executor_box_compensation.py).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.core.v71.box.box_manager import (
    BoxModificationError,
    BoxOverlapError,
    BoxValidationError,
    V71BoxManager,
)
from src.core.v71.box.box_record import BoxRecord, from_orm
from src.core.v71.box.box_state_machine import BoxStatus
from src.database.models_v71 import PathType, StrategyType, SupportBox

KST = timezone(timedelta(hours=9))
UTC = timezone.utc


# ============================================================
# Group 1: BoxRecord frozen DTO (3 cases)
# ============================================================


class TestBoxRecordFrozen:
    def test_box_record_is_frozen(self):
        record = BoxRecord(
            id="abc", tracked_stock_id="x", box_tier=1,
            upper_price=100, lower_price=90, position_size_pct=10.0,
            stop_loss_pct=-0.05,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        with pytest.raises(FrozenInstanceError):
            record.status = BoxStatus.TRIGGERED  # type: ignore[misc]

    def test_from_orm_lossless_int_decimal(self):
        from uuid import uuid4
        orm = SupportBox(
            id=uuid4(),
            tracked_stock_id=uuid4(),
            path_type=PathType.PATH_A,
            box_tier=2,
            upper_price=Decimal("71000"),
            lower_price=Decimal("70000"),
            position_size_pct=Decimal("10.00"),
            stop_loss_pct=Decimal("-0.050000"),
            strategy_type=StrategyType.PULLBACK,
            status=BoxStatus.WAITING,
        )
        record = from_orm(orm)
        assert record.upper_price == 71000
        assert record.lower_price == 70000
        assert record.position_size_pct == pytest.approx(10.0)
        assert record.stop_loss_pct == pytest.approx(-0.05)

    def test_from_orm_preserves_optional_fields(self):
        from uuid import uuid4
        orm = SupportBox(
            id=uuid4(), tracked_stock_id=uuid4(),
            path_type=PathType.PATH_B, box_tier=1,
            upper_price=Decimal("100"), lower_price=Decimal("90"),
            position_size_pct=Decimal("5.00"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=StrategyType.BREAKOUT,
            status=BoxStatus.WAITING,
            memo=None, last_reminder_at=None, invalidation_reason=None,
        )
        r = from_orm(orm)
        assert r.memo is None
        assert r.last_reminder_at is None
        assert r.invalidation_reason is None
        assert r.path_type == PathType.PATH_B


# ============================================================
# Group 2: create_box happy + validation + overlap (5 cases)
# ============================================================


class TestCreateBox:
    @pytest.mark.asyncio
    async def test_creates_with_status_waiting(self, make_box_manager, seeded_tracked):
        manager = make_box_manager()
        record = await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=71000, lower_price=70000,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        assert record.status is BoxStatus.WAITING
        assert record.box_tier == 1

    @pytest.mark.asyncio
    async def test_box_tier_increments_per_path(self, make_box_manager, seeded_tracked):
        manager = make_box_manager()
        await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=71000, lower_price=70000,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        second = await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=72000, lower_price=71500,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        assert second.box_tier == 2

    @pytest.mark.asyncio
    async def test_overlap_rejects_same_path(self, make_box_manager, seeded_tracked):
        manager = make_box_manager()
        await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=71000, lower_price=70000,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        with pytest.raises(BoxOverlapError):
            await manager.create_box(
                tracked_stock_id=str(seeded_tracked.id),
                upper_price=70500, lower_price=69000,  # overlaps
                position_size_pct=5.0,
                strategy_type=StrategyType.PULLBACK,
                path_type=PathType.PATH_A,
            )

    @pytest.mark.asyncio
    async def test_boundary_touch_is_not_overlap(self, make_box_manager, seeded_tracked):
        """§3.4 strict bounds: upper == lower is NOT overlap."""
        manager = make_box_manager()
        await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=71000, lower_price=70000,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        record = await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=70000, lower_price=69000,  # boundary touch
            position_size_pct=5.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        assert record.box_tier == 2

    @pytest.mark.asyncio
    async def test_validation_upper_le_lower(self, make_box_manager, seeded_tracked):
        manager = make_box_manager()
        with pytest.raises(BoxValidationError):
            await manager.create_box(
                tracked_stock_id=str(seeded_tracked.id),
                upper_price=70000, lower_price=70000,
                position_size_pct=10.0,
                strategy_type=StrategyType.PULLBACK,
                path_type=PathType.PATH_A,
            )


# ============================================================
# Group 3: modify_box (3 cases)
# ============================================================


class TestModifyBox:
    @pytest.mark.asyncio
    async def test_modify_waiting_box(self, make_box_manager, seeded_tracked, seed_box):
        box = await seed_box(tracked_id=seeded_tracked.id)
        manager = make_box_manager()
        record = await manager.modify_box(
            str(box.id), upper_price=71500, position_size_pct=15.0,
        )
        assert record.upper_price == 71500
        assert record.position_size_pct == pytest.approx(15.0)

    @pytest.mark.asyncio
    async def test_modify_triggered_blocked(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        box = await seed_box(
            tracked_id=seeded_tracked.id, status=BoxStatus.TRIGGERED,
        )
        manager = make_box_manager()
        with pytest.raises(BoxModificationError):
            await manager.modify_box(str(box.id), upper_price=72000)

    @pytest.mark.asyncio
    async def test_relax_stop_requires_force(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        box = await seed_box(tracked_id=seeded_tracked.id)
        manager = make_box_manager()
        with pytest.raises(BoxModificationError):
            await manager.modify_box(str(box.id), stop_loss_pct=-0.07)
        record = await manager.modify_box(
            str(box.id), stop_loss_pct=-0.07, force_relax_stop=True,
        )
        assert record.stop_loss_pct == pytest.approx(-0.07)


# ============================================================
# Group 4: delete_box + callback (2 cases)
# ============================================================


class TestDeleteBox:
    @pytest.mark.asyncio
    async def test_delete_to_cancelled(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        box = await seed_box(tracked_id=seeded_tracked.id)
        manager = make_box_manager()
        record = await manager.delete_box(str(box.id))
        assert record.status is BoxStatus.CANCELLED
        assert record.invalidation_reason == "USER_DELETED"

    @pytest.mark.asyncio
    async def test_callback_failure_isolated(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        """Trading-logic blocker 2: failing callback MUST NOT revert
        DB state nor crash the manager."""
        box = await seed_box(tracked_id=seeded_tracked.id)
        manager = make_box_manager()

        async def boom(_box_id: str) -> None:
            raise RuntimeError("broker timeout")

        # Manager swallows the exception (logs it) and still returns
        # the cancelled record.
        record = await manager.delete_box(str(box.id), on_orphan_cancel=boom)
        assert record.status is BoxStatus.CANCELLED


# ============================================================
# Group 5: mark_triggered + mark_invalidated (4 cases)
# ============================================================


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_mark_triggered_happy(
        self, make_box_manager, seeded_tracked, seed_box, fixed_clock,
    ):
        box = await seed_box(tracked_id=seeded_tracked.id)
        manager = make_box_manager()
        record = await manager.mark_triggered(str(box.id))
        assert record.status is BoxStatus.TRIGGERED
        # SQLite drops the tzinfo on TIMESTAMPTZ round-trip; compare on
        # the naive parts. Postgres preserves TZ (verified in
        # tests/v71/box/db/).
        assert record.triggered_at is not None
        expected = fixed_clock().replace(tzinfo=None)
        actual = record.triggered_at.replace(tzinfo=None)
        # Manager clock returns KST tz-aware; SQLite stores it as KST
        # wall-clock without TZ. Compare naive wall-clock equality.
        assert actual == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reason",
        ["MANUAL_BUY_DETECTED", "AUTO_EXIT_BOX_DROP", "COMPENSATION_FAILED"],
    )
    async def test_mark_invalidated_three_reasons(
        self, make_box_manager, seeded_tracked, seed_box, reason,
    ):
        box = await seed_box(tracked_id=seeded_tracked.id)
        manager = make_box_manager()
        record = await manager.mark_invalidated(str(box.id), reason=reason)
        assert record.status is BoxStatus.INVALIDATED
        assert record.invalidation_reason == reason


# ============================================================
# Group 6: cancel_waiting_for_tracked (2 cases, §5.9)
# ============================================================


class TestCancelWaitingForTracked:
    @pytest.mark.asyncio
    async def test_cancels_only_waiting(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        await seed_box(
            tracked_id=seeded_tracked.id, upper=71000, lower=70000, box_tier=1,
        )
        await seed_box(
            tracked_id=seeded_tracked.id, upper=72000, lower=71500, box_tier=2,
        )
        await seed_box(
            tracked_id=seeded_tracked.id,
            upper=80000, lower=79000, box_tier=3,
            status=BoxStatus.TRIGGERED,
        )
        manager = make_box_manager()
        cancelled = await manager.cancel_waiting_for_tracked(
            str(seeded_tracked.id),
        )
        assert len(cancelled) == 2

    @pytest.mark.asyncio
    async def test_callbacks_isolated_per_box(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        await seed_box(
            tracked_id=seeded_tracked.id, upper=71000, lower=70000, box_tier=1,
        )
        await seed_box(
            tracked_id=seeded_tracked.id, upper=72000, lower=71500, box_tier=2,
        )
        manager = make_box_manager()
        seen: list[str] = []

        async def callback(box_id: str) -> None:
            if not seen:  # first call raises, second still fires
                seen.append(box_id)
                raise RuntimeError("flaky broker")
            seen.append(box_id)

        cancelled = await manager.cancel_waiting_for_tracked(
            str(seeded_tracked.id), on_orphan_cancel=callback,
        )
        assert len(cancelled) == 2
        assert len(seen) == 2  # both invoked despite first failure


# ============================================================
# Group 7: list_all + list_waiting + LIMIT (3 cases)
# ============================================================


class TestQueries:
    @pytest.mark.asyncio
    async def test_list_all_no_filter(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        await seed_box(tracked_id=seeded_tracked.id, upper=71000, lower=70000)
        manager = make_box_manager()
        records = await manager.list_all()
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_list_all_filter_status_waiting(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        await seed_box(
            tracked_id=seeded_tracked.id, upper=71000, lower=70000, box_tier=1,
        )
        await seed_box(
            tracked_id=seeded_tracked.id,
            upper=80000, lower=79000, box_tier=2,
            status=BoxStatus.TRIGGERED,
        )
        manager = make_box_manager()
        waiting = await manager.list_all(status=BoxStatus.WAITING)
        assert len(waiting) == 1
        assert waiting[0].status is BoxStatus.WAITING

    @pytest.mark.asyncio
    async def test_list_waiting_for_tracked_path_filter(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        await seed_box(
            tracked_id=seeded_tracked.id, upper=71000, lower=70000,
            path_type=PathType.PATH_A, box_tier=1,
        )
        await seed_box(
            tracked_id=seeded_tracked.id, upper=80000, lower=79000,
            path_type=PathType.PATH_B, box_tier=1,
        )
        manager = make_box_manager()
        a_only = await manager.list_waiting_for_tracked(
            str(seeded_tracked.id), PathType.PATH_A,
        )
        assert len(a_only) == 1
        assert a_only[0].path_type is PathType.PATH_A


# ============================================================
# Group 8: 30-day reminder TZ-aware (3 cases, Q5)
# ============================================================


class Test30DayReminder:
    @pytest.mark.asyncio
    async def test_naive_now_rejected(self, make_box_manager):
        manager = make_box_manager()
        with pytest.raises(ValueError, match="tz-aware"):
            await manager.check_30day_expiry(now=datetime(2026, 5, 15))

    @pytest.mark.asyncio
    async def test_due_after_30_days(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        manager = make_box_manager()
        old = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        await seed_box(tracked_id=seeded_tracked.id, created_at=old)
        now = datetime(2026, 5, 15, 0, 0, tzinfo=UTC)
        due = await manager.check_30day_expiry(now=now)
        assert len(due) == 1

    @pytest.mark.asyncio
    async def test_not_due_before_30_days(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        manager = make_box_manager()
        recent = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
        await seed_box(tracked_id=seeded_tracked.id, created_at=recent)
        now = datetime(2026, 5, 15, 0, 0, tzinfo=UTC)
        due = await manager.check_30day_expiry(now=now)
        assert len(due) == 0


# ============================================================
# Group 9: Regression — user-reported "박스 등록했는데 텔레그램 0" symptom
# ============================================================


class TestUserReportRegression:
    """User report 2026-04-30: web POST /api/v71/boxes succeeded but
    Telegram /status / /pending / /tracking returned empty. Root cause
    was the in-memory-dict / DB-row split that P-Wire-Box-1 fixes.
    """

    @pytest.mark.asyncio
    async def test_box_visible_after_create_via_list_all(
        self, make_box_manager, seeded_tracked,
    ):
        """create_box -> list_all() returns the same row."""
        manager = make_box_manager()
        await manager.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=71000, lower_price=70000,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        all_boxes = await manager.list_all()
        assert len(all_boxes) == 1
        assert all_boxes[0].path_type is PathType.PATH_A

    @pytest.mark.asyncio
    async def test_box_visible_after_manager_restart(
        self, make_box_manager, session_factory, seeded_tracked,
    ):
        """Old manager instance writes a box; a fresh manager (e.g.
        after systemd restart) reads it back. The in-memory-dict
        regression would silently lose this."""
        manager_a = make_box_manager()
        await manager_a.create_box(
            tracked_stock_id=str(seeded_tracked.id),
            upper_price=71000, lower_price=70000,
            position_size_pct=10.0,
            strategy_type=StrategyType.PULLBACK,
            path_type=PathType.PATH_A,
        )
        manager_b = V71BoxManager(session_factory=session_factory)
        records = await manager_b.list_all()
        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_pending_response_matches_db_waiting(
        self, make_box_manager, seeded_tracked, seed_box,
    ):
        """Telegram /pending uses list_all(status=WAITING). Two WAITING
        boxes + one TRIGGERED -> /pending sees 2."""
        await seed_box(
            tracked_id=seeded_tracked.id, upper=71000, lower=70000, box_tier=1,
        )
        await seed_box(
            tracked_id=seeded_tracked.id, upper=72000, lower=71500, box_tier=2,
        )
        await seed_box(
            tracked_id=seeded_tracked.id,
            upper=80000, lower=79000, box_tier=3,
            status=BoxStatus.TRIGGERED,
        )
        manager = make_box_manager()
        waiting = await manager.list_all(status=BoxStatus.WAITING)
        assert len(waiting) == 2
