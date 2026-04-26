"""Unit tests for ``src/core/v71/box/box_manager.py``.

Spec:
  - 02_TRADING_RULES.md §3.1   (Box definition)
  - 02_TRADING_RULES.md §3.4   (Constraints, overlap, multi-tier)
  - 02_TRADING_RULES.md §3.6   (Modification policy)
  - 02_TRADING_RULES.md §3.7   (30-day reminder)
  - 02_TRADING_RULES.md §3.13  (Status lifecycle)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_box_system():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import (  # noqa: E402
    BoxModificationError,
    BoxNotFoundError,
    BoxOverlapError,
    BoxValidationError,
    V71BoxManager,
)
from src.core.v71.box.box_state_machine import BoxStatus  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_manager() -> V71BoxManager:
    return V71BoxManager()


TRACKED = "tracked-001"


# ---------------------------------------------------------------------------
# create_box
# ---------------------------------------------------------------------------


class TestCreateBox:
    def test_creates_a_box_with_status_waiting(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        assert rec.status is BoxStatus.WAITING
        assert rec.upper_price == 100
        assert rec.lower_price == 90
        assert rec.position_size_pct == 10.0
        assert rec.box_tier == 1
        assert rec.id  # UUID assigned

    def test_default_stop_loss_is_neg_5pct(self):
        from src.core.v71.v71_constants import V71Constants

        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        assert rec.stop_loss_pct == V71Constants.STOP_LOSS_INITIAL_PCT  # -0.05

    def test_box_tier_increments_per_path(self):
        m = make_manager()
        a = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        b = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=85,
            lower_price=80,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        c = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=70,
            lower_price=60,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_B",
        )
        assert a.box_tier == 1
        assert b.box_tier == 2
        # Path B has its own tier sequence.
        assert c.box_tier == 1

    def test_upper_le_lower_rejected(self):
        m = make_manager()
        with pytest.raises(BoxValidationError, match="upper_price"):
            m.create_box(
                tracked_stock_id=TRACKED,
                upper_price=90,
                lower_price=90,
                position_size_pct=10.0,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )

    def test_size_zero_rejected(self):
        m = make_manager()
        with pytest.raises(BoxValidationError, match="position_size_pct"):
            m.create_box(
                tracked_stock_id=TRACKED,
                upper_price=100,
                lower_price=90,
                position_size_pct=0.0,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )

    def test_size_over_100_rejected(self):
        m = make_manager()
        with pytest.raises(BoxValidationError, match="position_size_pct"):
            m.create_box(
                tracked_stock_id=TRACKED,
                upper_price=100,
                lower_price=90,
                position_size_pct=101.0,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )

    def test_positive_stop_rejected(self):
        m = make_manager()
        with pytest.raises(BoxValidationError, match="stop_loss_pct"):
            m.create_box(
                tracked_stock_id=TRACKED,
                upper_price=100,
                lower_price=90,
                position_size_pct=10.0,
                stop_loss_pct=0.05,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )

    def test_negative_lower_rejected(self):
        m = make_manager()
        with pytest.raises(BoxValidationError, match="positive"):
            m.create_box(
                tracked_stock_id=TRACKED,
                upper_price=100,
                lower_price=-10,
                position_size_pct=10.0,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_overlap_blocked_same_path(self):
        m = make_manager()
        m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        with pytest.raises(BoxOverlapError):
            m.create_box(
                tracked_stock_id=TRACKED,
                upper_price=95,  # 95~85 overlaps 100~90
                lower_price=85,
                position_size_pct=10.0,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )

    def test_touching_boundary_not_overlap(self):
        """Strict less-than: upper==lower of neighbor is NOT overlap."""
        m = make_manager()
        m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        # 90 == lower of existing -> just touching
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=90,
            lower_price=80,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        assert rec.box_tier == 2

    def test_different_path_not_overlap(self):
        m = make_manager()
        m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        # Same prices, different path -> allowed.
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_B",
        )
        assert rec.path_type == "PATH_B"

    def test_different_tracked_stock_not_overlap(self):
        m = make_manager()
        m.create_box(
            tracked_stock_id="track-001",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        rec = m.create_box(
            tracked_stock_id="track-002",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        assert rec.tracked_stock_id == "track-002"

    def test_invalidated_box_does_not_block_new(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        m.mark_invalidated(rec.id, reason="AUTO_EXIT_BOX_DROP")
        # Now creating an overlapping box should succeed (invalidated is excluded).
        rec2 = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=95,
            lower_price=85,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        assert rec2.id != rec.id


class TestValidateNoOverlap:
    def test_pure_helper_strict_lt(self):
        from src.core.v71.box.box_manager import BoxRecord

        existing = [
            BoxRecord(
                id="b1",
                tracked_stock_id=TRACKED,
                box_tier=1,
                upper_price=100,
                lower_price=90,
                position_size_pct=10.0,
                stop_loss_pct=-0.05,
                strategy_type="PULLBACK",
                path_type="PATH_A",
            )
        ]
        # Touching at boundary -> not overlap.
        assert V71BoxManager.validate_no_overlap(existing, 90, 80) is True
        assert V71BoxManager.validate_no_overlap(existing, 110, 100) is True
        # Strict overlap.
        assert V71BoxManager.validate_no_overlap(existing, 95, 85) is False
        assert V71BoxManager.validate_no_overlap(existing, 110, 95) is False
        # Inside.
        assert V71BoxManager.validate_no_overlap(existing, 99, 91) is False


# ---------------------------------------------------------------------------
# modify_box
# ---------------------------------------------------------------------------


class TestModifyBox:
    def _make_one(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        return m, rec

    def test_modify_price_succeeds_when_waiting(self):
        m, rec = self._make_one()
        out = m.modify_box(rec.id, upper_price=105, lower_price=95)
        assert out.upper_price == 105
        assert out.lower_price == 95

    def test_modify_size_succeeds(self):
        m, rec = self._make_one()
        out = m.modify_box(rec.id, position_size_pct=20.0)
        assert out.position_size_pct == 20.0

    def test_tighten_stop_no_warning_needed(self):
        """-5% -> -3% is tightening (closer to zero) -- always OK."""
        m, rec = self._make_one()
        out = m.modify_box(rec.id, stop_loss_pct=-0.03)
        assert out.stop_loss_pct == -0.03

    def test_relax_stop_requires_force(self):
        """-5% -> -7% is relaxing (further from zero) -- needs force."""
        m, rec = self._make_one()
        with pytest.raises(BoxModificationError, match="relaxed"):
            m.modify_box(rec.id, stop_loss_pct=-0.07)

    def test_relax_stop_with_force_succeeds(self):
        m, rec = self._make_one()
        out = m.modify_box(rec.id, stop_loss_pct=-0.07, force_relax_stop=True)
        assert out.stop_loss_pct == -0.07

    def test_modify_overlap_blocked(self):
        m, rec = self._make_one()
        m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=85,
            lower_price=75,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        with pytest.raises(BoxOverlapError):
            m.modify_box(rec.id, upper_price=88, lower_price=78)  # would overlap

    def test_modify_triggered_box_blocked(self):
        m, rec = self._make_one()
        m.mark_triggered(rec.id)
        with pytest.raises(BoxModificationError, match="TRIGGERED"):
            m.modify_box(rec.id, upper_price=110)

    def test_modify_cancelled_box_blocked(self):
        m, rec = self._make_one()
        m.delete_box(rec.id)
        with pytest.raises(BoxModificationError, match="CANCELLED"):
            m.modify_box(rec.id, upper_price=110)

    def test_modify_unknown_id_raises(self):
        m = make_manager()
        with pytest.raises(BoxNotFoundError):
            m.modify_box("does-not-exist", upper_price=100)


# ---------------------------------------------------------------------------
# delete_box
# ---------------------------------------------------------------------------


class TestDeleteBox:
    def test_deletes_waiting_box(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        out = m.delete_box(rec.id)
        assert out.status is BoxStatus.CANCELLED
        assert out.invalidation_reason == "USER_DELETED"

    def test_orphan_callback_invoked_on_delete(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        seen: list[str] = []
        m.delete_box(rec.id, on_orphan_cancel=seen.append)
        assert seen == [rec.id]

    def test_cannot_delete_triggered(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        m.mark_triggered(rec.id)
        with pytest.raises(BoxModificationError):
            m.delete_box(rec.id)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestStateTransitions:
    def test_mark_triggered_sets_timestamp(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        out = m.mark_triggered(rec.id)
        assert out.status is BoxStatus.TRIGGERED
        assert out.triggered_at is not None

    def test_mark_invalidated_with_box_drop(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        out = m.mark_invalidated(rec.id, reason="AUTO_EXIT_BOX_DROP")
        assert out.status is BoxStatus.INVALIDATED
        assert out.invalidated_at is not None
        assert out.invalidation_reason == "AUTO_EXIT_BOX_DROP"

    def test_mark_invalidated_with_manual_buy(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        out = m.mark_invalidated(rec.id, reason="MANUAL_BUY_DETECTED")
        assert out.status is BoxStatus.INVALIDATED
        assert out.invalidation_reason == "MANUAL_BUY_DETECTED"

    def test_mark_invalidated_with_unknown_reason_rejected(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        with pytest.raises(ValueError, match="reason must be"):
            m.mark_invalidated(rec.id, reason="WHATEVER")


# ---------------------------------------------------------------------------
# 30-day expiry (§3.7)
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_no_due_when_fresh(self):
        m = make_manager()
        m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        assert m.check_30day_expiry() == []

    def test_due_after_30_days(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        # Simulate the box having been created 31 days ago.
        rec.created_at = datetime.now() - timedelta(days=31)
        due = m.check_30day_expiry()
        assert len(due) == 1
        assert due[0].id == rec.id

    def test_mark_reminded_resets_anchor(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        rec.created_at = datetime.now() - timedelta(days=31)
        assert m.check_30day_expiry()  # due
        m.mark_reminded(rec.id)
        # Right after reminder -> not due again immediately.
        assert m.check_30day_expiry() == []

    def test_due_again_after_another_30_days_post_reminder(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        rec.created_at = datetime.now() - timedelta(days=70)
        rec.last_reminder_at = datetime.now() - timedelta(days=31)
        due = m.check_30day_expiry()
        assert len(due) == 1

    def test_non_waiting_boxes_excluded(self):
        m = make_manager()
        rec = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        rec.created_at = datetime.now() - timedelta(days=31)
        m.mark_triggered(rec.id)
        assert m.check_30day_expiry() == []


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestQueries:
    def test_list_for_tracked(self):
        m = make_manager()
        a = m.create_box(
            tracked_stock_id="t1",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        b = m.create_box(
            tracked_stock_id="t1",
            upper_price=80,
            lower_price=70,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        m.create_box(
            tracked_stock_id="t2",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        ids = {x.id for x in m.list_for_tracked("t1")}
        assert ids == {a.id, b.id}

    def test_list_waiting_excludes_terminal(self):
        m = make_manager()
        a = m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        m.create_box(
            tracked_stock_id=TRACKED,
            upper_price=80,
            lower_price=70,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        m.mark_triggered(a.id)
        waiting = m.list_waiting_for_tracked(TRACKED, "PATH_A")
        assert len(waiting) == 1
        assert all(b.status is BoxStatus.WAITING for b in waiting)


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFeatureFlagGate:
    def test_runtime_error_when_flag_disabled(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.box_system"):
                V71BoxManager()
        finally:
            os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
            ff.reload()
