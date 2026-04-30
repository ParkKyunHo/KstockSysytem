"""Unit tests for ``src/core/v71/box/box_state_machine.py``.

Spec:
  - 02_TRADING_RULES.md §3.13 (Box status lifecycle)
  - 03_DATA_MODEL.md §2.1 (tracked_stocks.status)
  - 03_DATA_MODEL.md §2.2 (support_boxes.status)

These tests pin the legal/illegal transition matrix.  A failure here means
either the PRD changed (and the table needs updating) or someone introduced
a non-spec transition.
"""

from __future__ import annotations

import os

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_box_system():
    """Activate the v71.box_system flag for every test in this module."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


# Import after the fixture so that require_enabled() at import time is fine.
from src.core.v71.box.box_state_machine import (  # noqa: E402
    BoxEvent,
    BoxStatus,
    IllegalTransitionError,
    TrackedEvent,
    TrackedStatus,
    allowed_box_events,
    allowed_tracked_events,
    is_box_terminal,
    is_tracked_terminal,
    transition_box,
    transition_tracked_stock,
)

# ---------------------------------------------------------------------------
# TrackedStatus transitions
# ---------------------------------------------------------------------------


class TestTrackedStatusLegal:
    def test_tracking_to_box_set_on_box_registered(self):
        assert (
            transition_tracked_stock(TrackedStatus.TRACKING, TrackedEvent.BOX_REGISTERED)
            == TrackedStatus.BOX_SET
        )

    def test_tracking_to_exited_on_termination(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.TRACKING, TrackedEvent.TRACKING_TERMINATED
            )
            == TrackedStatus.EXITED
        )

    def test_box_set_to_position_open_on_buy(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.BOX_SET, TrackedEvent.POSITION_OPENED
            )
            == TrackedStatus.POSITION_OPEN
        )

    def test_box_set_back_to_tracking_when_all_boxes_removed(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.BOX_SET, TrackedEvent.ALL_BOXES_REMOVED
            )
            == TrackedStatus.TRACKING
        )

    def test_box_set_to_exited_on_termination(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.BOX_SET, TrackedEvent.TRACKING_TERMINATED
            )
            == TrackedStatus.EXITED
        )

    def test_position_open_to_partial_on_partial_exit(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.POSITION_OPEN, TrackedEvent.PARTIAL_EXIT
            )
            == TrackedStatus.POSITION_PARTIAL
        )

    def test_position_open_to_exited_on_full_exit(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.POSITION_OPEN, TrackedEvent.FULL_EXIT
            )
            == TrackedStatus.EXITED
        )

    def test_position_partial_partial_exit_is_idempotent(self):
        """Each subsequent partial exit keeps us in POSITION_PARTIAL."""
        assert (
            transition_tracked_stock(
                TrackedStatus.POSITION_PARTIAL, TrackedEvent.PARTIAL_EXIT
            )
            == TrackedStatus.POSITION_PARTIAL
        )

    def test_position_partial_to_exited_on_full_exit(self):
        assert (
            transition_tracked_stock(
                TrackedStatus.POSITION_PARTIAL, TrackedEvent.FULL_EXIT
            )
            == TrackedStatus.EXITED
        )


class TestTrackedStatusIllegal:
    def test_tracking_cannot_open_position_directly(self):
        with pytest.raises(IllegalTransitionError):
            transition_tracked_stock(
                TrackedStatus.TRACKING, TrackedEvent.POSITION_OPENED
            )

    def test_tracking_cannot_partial_exit(self):
        with pytest.raises(IllegalTransitionError):
            transition_tracked_stock(
                TrackedStatus.TRACKING, TrackedEvent.PARTIAL_EXIT
            )

    def test_box_set_cannot_partial_exit_without_position(self):
        with pytest.raises(IllegalTransitionError):
            transition_tracked_stock(
                TrackedStatus.BOX_SET, TrackedEvent.PARTIAL_EXIT
            )

    def test_position_open_cannot_register_box_event(self):
        with pytest.raises(IllegalTransitionError):
            transition_tracked_stock(
                TrackedStatus.POSITION_OPEN, TrackedEvent.BOX_REGISTERED
            )

    @pytest.mark.parametrize("event", list(TrackedEvent))
    def test_exited_is_terminal(self, event):
        with pytest.raises(IllegalTransitionError):
            transition_tracked_stock(TrackedStatus.EXITED, event)


# ---------------------------------------------------------------------------
# BoxStatus transitions
# ---------------------------------------------------------------------------


class TestBoxStatusLegal:
    def test_waiting_to_triggered_on_buy(self):
        assert (
            transition_box(BoxStatus.WAITING, BoxEvent.BUY_EXECUTED)
            == BoxStatus.TRIGGERED
        )

    def test_waiting_to_invalidated_on_manual_buy(self):
        """Scenario C: user manually bought before system trigger -> all boxes invalid."""
        assert (
            transition_box(BoxStatus.WAITING, BoxEvent.MANUAL_BUY_DETECTED)
            == BoxStatus.INVALIDATED
        )

    def test_waiting_to_invalidated_on_auto_box_drop(self):
        """-20% drop below box -> auto invalidation (§3.1)."""
        assert (
            transition_box(BoxStatus.WAITING, BoxEvent.AUTO_EXIT_BOX_DROP)
            == BoxStatus.INVALIDATED
        )

    def test_waiting_to_cancelled_on_user_delete(self):
        assert (
            transition_box(BoxStatus.WAITING, BoxEvent.USER_DELETED)
            == BoxStatus.CANCELLED
        )


class TestBoxStatusTerminal:
    @pytest.mark.parametrize(
        "terminal", [BoxStatus.TRIGGERED, BoxStatus.INVALIDATED, BoxStatus.CANCELLED]
    )
    @pytest.mark.parametrize("event", list(BoxEvent))
    def test_terminal_states_reject_all_events(self, terminal, event):
        with pytest.raises(IllegalTransitionError):
            transition_box(terminal, event)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestTerminalHelpers:
    def test_tracked_exited_is_terminal(self):
        assert is_tracked_terminal(TrackedStatus.EXITED) is True

    def test_tracked_others_are_not_terminal(self):
        for s in TrackedStatus:
            if s is TrackedStatus.EXITED:
                continue
            assert is_tracked_terminal(s) is False

    def test_box_terminal_states(self):
        assert is_box_terminal(BoxStatus.TRIGGERED) is True
        assert is_box_terminal(BoxStatus.INVALIDATED) is True
        assert is_box_terminal(BoxStatus.CANCELLED) is True

    def test_box_waiting_not_terminal(self):
        assert is_box_terminal(BoxStatus.WAITING) is False


class TestAllowedEvents:
    def test_tracking_allowed_events(self):
        events = allowed_tracked_events(TrackedStatus.TRACKING)
        assert set(events) == {
            TrackedEvent.BOX_REGISTERED,
            TrackedEvent.TRACKING_TERMINATED,
        }

    def test_exited_allowed_events_empty(self):
        assert allowed_tracked_events(TrackedStatus.EXITED) == ()

    def test_waiting_box_allowed_events(self):
        events = allowed_box_events(BoxStatus.WAITING)
        assert set(events) == {
            BoxEvent.BUY_EXECUTED,
            BoxEvent.MANUAL_BUY_DETECTED,
            BoxEvent.AUTO_EXIT_BOX_DROP,
            BoxEvent.USER_DELETED,
            BoxEvent.COMPENSATION_FAILED,
        }

    def test_terminal_box_allowed_events_empty(self):
        for s in (BoxStatus.TRIGGERED, BoxStatus.INVALIDATED, BoxStatus.CANCELLED):
            assert allowed_box_events(s) == ()


# ---------------------------------------------------------------------------
# Type safety
# ---------------------------------------------------------------------------


class TestTypeSafety:
    def test_tracked_rejects_string_event(self):
        with pytest.raises(TypeError):
            transition_tracked_stock(TrackedStatus.TRACKING, "BOX_REGISTERED")  # type: ignore[arg-type]

    def test_tracked_rejects_box_event(self):
        with pytest.raises(TypeError):
            transition_tracked_stock(TrackedStatus.TRACKING, BoxEvent.BUY_EXECUTED)  # type: ignore[arg-type]

    def test_tracked_rejects_string_state(self):
        with pytest.raises(TypeError):
            transition_tracked_stock("TRACKING", TrackedEvent.BOX_REGISTERED)  # type: ignore[arg-type]

    def test_box_rejects_string_event(self):
        with pytest.raises(TypeError):
            transition_box(BoxStatus.WAITING, "BUY_EXECUTED")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFeatureFlagGate:
    def test_runtime_error_when_flag_disabled(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.box_system"):
                transition_tracked_stock(
                    TrackedStatus.TRACKING, TrackedEvent.BOX_REGISTERED
                )
        finally:
            os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
            ff.reload()

    def test_runtime_error_for_box_when_flag_disabled(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.box_system"):
                transition_box(BoxStatus.WAITING, BoxEvent.BUY_EXECUTED)
        finally:
            os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
            ff.reload()
