"""Unit tests for ``src/core/v71/skills/vi_skill.py``.

Spec: 02_TRADING_RULES.md §10
"""

from __future__ import annotations

import pytest

from src.core.v71.skills.vi_skill import (
    ALLOWED_EVENTS,
    EVENT_DAILY_RESET,
    EVENT_VI_DETECTED,
    EVENT_VI_RESETTLED,
    EVENT_VI_RESOLVED,
    VIDecision,
    VIState,
    VIStateContext,
    check_post_vi_gap,
    handle_vi_state,
    transition_vi_state,
)
from src.core.v71.v71_constants import V71Constants as K


def _ctx(state: VIState, *, current_price: int = 18_000) -> VIStateContext:
    return VIStateContext(
        stock_code="005930",
        current_state=state,
        trigger_price=18_000,
        triggered_at=None,
        last_close_before_vi=18_000,
        current_price=current_price,
    )


# ---------------------------------------------------------------------------
# transition_vi_state (§10.3)
# ---------------------------------------------------------------------------


class TestTransitionLegal:
    def test_normal_to_triggered(self):
        assert transition_vi_state(VIState.NORMAL, EVENT_VI_DETECTED) == (
            VIState.TRIGGERED
        )

    def test_triggered_to_resumed(self):
        assert transition_vi_state(VIState.TRIGGERED, EVENT_VI_RESOLVED) == (
            VIState.RESUMED
        )

    def test_resumed_to_normal_on_resettle(self):
        assert transition_vi_state(VIState.RESUMED, EVENT_VI_RESETTLED) == (
            VIState.NORMAL
        )

    @pytest.mark.parametrize("from_state", list(VIState))
    def test_daily_reset_returns_normal_from_any_state(self, from_state):
        assert transition_vi_state(from_state, EVENT_DAILY_RESET) == VIState.NORMAL


class TestTransitionIllegal:
    @pytest.mark.parametrize(
        "current,event",
        [
            (VIState.NORMAL, EVENT_VI_RESOLVED),
            (VIState.NORMAL, EVENT_VI_RESETTLED),
            (VIState.TRIGGERED, EVENT_VI_DETECTED),  # idempotent? rejected here, monitor handles
            (VIState.TRIGGERED, EVENT_VI_RESETTLED),
            (VIState.RESUMED, EVENT_VI_DETECTED),
            (VIState.RESUMED, EVENT_VI_RESOLVED),
        ],
    )
    def test_illegal_raises(self, current, event):
        with pytest.raises(ValueError, match="Illegal VI transition"):
            transition_vi_state(current, event)

    def test_unknown_event_raises(self):
        with pytest.raises(ValueError, match="Unknown VI event"):
            transition_vi_state(VIState.NORMAL, "BOGUS_EVENT")


# ---------------------------------------------------------------------------
# check_post_vi_gap (§10.4)
# ---------------------------------------------------------------------------


class TestPostViGap:
    def test_gap_under_3pct_proceeds(self):
        # 18_000 -> 18_500 = 2.78%
        abort, gap = check_post_vi_gap(18_000, 18_500)
        assert abort is False
        assert gap == pytest.approx(0.02777, abs=1e-4)

    def test_gap_at_3pct_aborts(self):
        # Strict greater-or-equal at threshold.
        abort, gap = check_post_vi_gap(10_000, 10_300)
        assert abort is True
        assert gap == pytest.approx(K.VI_GAP_LIMIT, abs=1e-9)

    def test_gap_over_3pct_aborts(self):
        abort, gap = check_post_vi_gap(10_000, 10_500)
        assert abort is True
        assert gap > K.VI_GAP_LIMIT

    def test_gap_down_3pct_also_aborts(self):
        # Negative gap >= 3% in absolute terms -- also abort.
        abort, gap = check_post_vi_gap(10_000, 9_700)
        assert abort is True
        assert gap == pytest.approx(-0.03, abs=1e-9)

    def test_invalid_prices_raises(self):
        with pytest.raises(ValueError):
            check_post_vi_gap(0, 10_000)
        with pytest.raises(ValueError):
            check_post_vi_gap(10_000, 0)


# ---------------------------------------------------------------------------
# handle_vi_state (combined)
# ---------------------------------------------------------------------------


class TestHandleViState:
    def test_detected_advances_state(self):
        decision = handle_vi_state(_ctx(VIState.NORMAL), EVENT_VI_DETECTED)
        assert decision.next_state == VIState.TRIGGERED
        assert decision.block_new_entries_today is False

    def test_resolved_advances_to_resumed(self):
        decision = handle_vi_state(_ctx(VIState.TRIGGERED), EVENT_VI_RESOLVED)
        assert decision.next_state == VIState.RESUMED
        assert decision.block_new_entries_today is False

    def test_resettled_sets_block_flag(self):
        decision = handle_vi_state(_ctx(VIState.RESUMED), EVENT_VI_RESETTLED)
        assert decision.next_state == VIState.NORMAL
        assert decision.block_new_entries_today is True

    def test_daily_reset_does_not_set_block_flag(self):
        # DAILY_RESET clears state without imposing today's block (it IS
        # the next day).
        decision = handle_vi_state(_ctx(VIState.NORMAL), EVENT_DAILY_RESET)
        assert decision.next_state == VIState.NORMAL
        assert decision.block_new_entries_today is False

    def test_decision_reason_logs_transition(self):
        decision = handle_vi_state(_ctx(VIState.NORMAL), EVENT_VI_DETECTED)
        assert "NORMAL" in decision.reason
        assert "VI_DETECTED" in decision.reason
        assert "TRIGGERED" in decision.reason


# ---------------------------------------------------------------------------
# Public surface sanity
# ---------------------------------------------------------------------------


class TestPublicSurface:
    def test_allowed_events_set(self):
        assert {
            EVENT_VI_DETECTED, EVENT_VI_RESOLVED,
            EVENT_VI_RESETTLED, EVENT_DAILY_RESET,
        } == ALLOWED_EVENTS

    def test_decision_dataclass_smoke(self):
        d = VIDecision(
            next_state=VIState.NORMAL,
            block_new_entries_today=False,
            abort_in_flight_buy=False,
            force_market_sell=False,
            reason="smoke",
        )
        assert d.next_state == VIState.NORMAL
