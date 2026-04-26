"""Unit tests for ``src/core/v71/skills/exit_calc_skill.py``.

Spec:
  - 02_TRADING_RULES.md §5.1 (stop loss)
  - 02_TRADING_RULES.md §5.2 / §5.3 (partial profit-take)
  - 02_TRADING_RULES.md §5.4 (stop ladder, one-way upward)
  - 02_TRADING_RULES.md §5.5 (TS BasePrice + ATR multiplier ladder)
  - 02_TRADING_RULES.md §5.6 (effective stop = max(fixed, TS-if-binding))
"""

from __future__ import annotations

import pytest

from src.core.v71.skills.exit_calc_skill import (
    PositionSnapshot,
    calculate_effective_stop,
    evaluate_profit_take,
    select_atr_multiplier,
    stage_after_partial_exit,
    update_trailing_stop,
)
from src.core.v71.v71_constants import V71Constants as K

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(
    *,
    avg: int = 100_000,
    current: int = 100_000,
    fixed_stop: int | None = None,
    profit_5: bool = False,
    profit_10: bool = False,
    ts_activated: bool = False,
    ts_base: int | None = None,
    ts_stop: int | None = None,
    ts_mult: float | None = None,
    atr: float = 1500.0,
) -> PositionSnapshot:
    if fixed_stop is None:
        fixed_stop = stage_after_partial_exit(profit_5, profit_10, avg)
    return PositionSnapshot(
        weighted_avg_price=avg,
        initial_avg_price=avg,
        fixed_stop_price=fixed_stop,
        profit_5_executed=profit_5,
        profit_10_executed=profit_10,
        ts_activated=ts_activated,
        ts_base_price=ts_base,
        ts_stop_price=ts_stop,
        ts_active_multiplier=ts_mult,
        current_price=current,
        atr_value=atr,
    )


# ---------------------------------------------------------------------------
# stage_after_partial_exit  (§5.4)
# ---------------------------------------------------------------------------


class TestStageAfterPartialExit:
    def test_stage_1_neg_5pct(self):
        assert stage_after_partial_exit(False, False, 100_000) == 95_000

    def test_stage_2_after_profit_5_neg_2pct(self):
        assert stage_after_partial_exit(True, False, 100_000) == 98_000

    def test_stage_3_after_profit_10_pos_4pct(self):
        assert stage_after_partial_exit(True, True, 100_000) == 104_000

    def test_strictly_upward(self):
        a = stage_after_partial_exit(False, False, 100_000)
        b = stage_after_partial_exit(True, False, 100_000)
        c = stage_after_partial_exit(True, True, 100_000)
        assert a < b < c

    def test_avg_zero_raises(self):
        with pytest.raises(ValueError):
            stage_after_partial_exit(False, False, 0)


# ---------------------------------------------------------------------------
# select_atr_multiplier  (§5.5)
# ---------------------------------------------------------------------------


class TestSelectAtrMultiplier:
    @pytest.mark.parametrize(
        "profit_pct,expected",
        [
            (0.05, K.ATR_MULTIPLIER_TIER_1),  # below +10% -> tier 1 (initial)
            (0.10, K.ATR_MULTIPLIER_TIER_1),
            (0.14, K.ATR_MULTIPLIER_TIER_1),
            (0.15, K.ATR_MULTIPLIER_TIER_2),
            (0.24, K.ATR_MULTIPLIER_TIER_2),
            (0.25, K.ATR_MULTIPLIER_TIER_3),
            (0.39, K.ATR_MULTIPLIER_TIER_3),
            (0.40, K.ATR_MULTIPLIER_TIER_4),
            (1.00, K.ATR_MULTIPLIER_TIER_4),
        ],
    )
    def test_tier_assignment(self, profit_pct, expected):
        assert select_atr_multiplier(profit_pct, current_multiplier=None) == expected

    def test_one_way_tightening_does_not_widen(self):
        # Currently at 2.5 (already in +25~40% tier).  If profit pct slips
        # back into +15~25% which would call for 3.0, we MUST keep 2.5.
        assert (
            select_atr_multiplier(profit_pct=0.20, current_multiplier=2.5)
            == 2.5
        )

    def test_one_way_tightening_can_tighten(self):
        # Currently at 4.0 -> moving into +20% should tighten to 3.0.
        assert (
            select_atr_multiplier(profit_pct=0.20, current_multiplier=4.0)
            == 3.0
        )


# ---------------------------------------------------------------------------
# update_trailing_stop  (§5.5)
# ---------------------------------------------------------------------------


class TestUpdateTrailingStop:
    def test_below_activation_does_nothing(self):
        s = _snap(avg=100_000, current=102_000)  # +2%
        out = update_trailing_stop(s)
        assert out.activate is False
        assert out.new_stop_price is None

    def test_activates_at_5pct(self):
        s = _snap(avg=100_000, current=105_000, atr=1500)  # +5%
        out = update_trailing_stop(s)
        assert out.activate is True
        # base = current; multiplier = TIER_1 (4.0); stop = 105k - 6k = 99k
        assert out.new_base_price == 105_000
        assert out.new_multiplier == K.ATR_MULTIPLIER_TIER_1
        assert out.new_stop_price == 99_000
        assert out.reason == "INITIAL_TS"

    def test_base_price_one_way_upward(self):
        # Previous base 110_000; current price drops to 108_000 -> base stays 110k
        s = _snap(
            avg=100_000,
            current=108_000,
            ts_base=110_000,
            ts_stop=104_000,
            ts_mult=4.0,
            atr=1500,
            profit_5=True,
            ts_activated=True,
        )
        out = update_trailing_stop(s)
        assert out.new_base_price == 110_000  # not lowered

    def test_stop_one_way_upward(self):
        # Previous stop 109_000; new candidate < 109_000 -> hold.
        s = _snap(
            avg=100_000,
            current=110_000,
            ts_base=110_000,
            ts_stop=109_000,
            ts_mult=4.0,
            atr=2000,  # 110k - 8k = 102k -> would lower
            profit_5=True,
            ts_activated=True,
        )
        out = update_trailing_stop(s)
        assert out.new_stop_price == 109_000
        assert out.reason == "HELD"

    def test_stop_raises_when_candidate_higher(self):
        s = _snap(
            avg=100_000,
            current=120_000,  # +20%, tier 3.0
            ts_base=120_000,
            ts_stop=110_000,
            ts_mult=4.0,
            atr=1500,
            profit_5=True,
            ts_activated=True,
        )
        out = update_trailing_stop(s)
        # multiplier tightens 4.0 -> 3.0
        assert out.new_multiplier == 3.0
        # candidate = 120k - 3.0*1500 = 115_500 -> raised over 110k
        assert out.new_stop_price == 115_500
        assert out.reason == "RAISED"

    def test_atr_warmup_keeps_previous_stop(self):
        s = _snap(
            avg=100_000,
            current=110_000,
            ts_base=110_000,
            ts_stop=104_000,
            ts_mult=4.0,
            atr=0.0,  # warmup
            profit_5=True,
            ts_activated=True,
        )
        out = update_trailing_stop(s)
        assert out.activate is True
        assert out.new_stop_price == 104_000  # unchanged
        assert out.reason == "ATR_WARMUP"


# ---------------------------------------------------------------------------
# calculate_effective_stop  (§5.6)
# ---------------------------------------------------------------------------


class TestCalculateEffectiveStop:
    def test_stage_1_uses_fixed_only(self):
        s = _snap(avg=100_000, current=99_000)  # below entry
        out = calculate_effective_stop(s)
        assert out.source == "FIXED"
        # fixed at -5% = 95_000; current 99k > 95k -> not triggered
        assert out.effective_stop_price == 95_000
        assert out.triggered is False

    def test_stage_1_triggered_at_neg_5pct(self):
        s = _snap(avg=100_000, current=95_000)  # exactly -5%
        out = calculate_effective_stop(s)
        assert out.triggered is True
        assert out.source == "FIXED"

    def test_stage_2_uses_fixed_only_even_if_ts_higher(self):
        """+5% executed, +10% NOT yet -> TS not binding."""
        s = _snap(
            avg=100_000,
            current=109_000,
            profit_5=True,
            ts_activated=True,
            ts_base=109_000,
            ts_stop=105_000,  # higher than fixed (-2% = 98_000)
            ts_mult=4.0,
        )
        out = calculate_effective_stop(s)
        # Stage 2 fixed = -2% = 98_000; TS not binding yet.
        assert out.source == "FIXED"
        assert out.effective_stop_price == 98_000

    def test_stage_3_max_of_fixed_and_ts(self):
        """+10% executed -> TS becomes binding."""
        s = _snap(
            avg=100_000,
            current=115_000,
            profit_5=True,
            profit_10=True,
            ts_activated=True,
            ts_base=115_000,
            ts_stop=109_000,  # higher than fixed +4% = 104_000
            ts_mult=4.0,
        )
        out = calculate_effective_stop(s)
        assert out.source == "TS"
        assert out.effective_stop_price == 109_000

    def test_stage_3_falls_back_to_fixed_when_higher(self):
        """Big ATR makes TS lower than fixed -- fixed wins."""
        s = _snap(
            avg=100_000,
            current=115_000,
            profit_5=True,
            profit_10=True,
            ts_activated=True,
            ts_base=115_000,
            ts_stop=99_000,  # below fixed +4% = 104_000
            ts_mult=4.0,
        )
        out = calculate_effective_stop(s)
        assert out.source == "FIXED"
        assert out.effective_stop_price == 104_000

    def test_triggered_flag_at_exact_match(self):
        s = _snap(avg=100_000, current=104_000, profit_5=True, profit_10=True)
        out = calculate_effective_stop(s)
        # fixed +4% = 104_000; current == effective -> triggered
        assert out.triggered is True


# ---------------------------------------------------------------------------
# evaluate_profit_take  (§5.2 / §5.3)
# ---------------------------------------------------------------------------


class TestEvaluateProfitTake:
    def test_below_5pct_no_exit(self):
        s = _snap(avg=100_000, current=104_000)
        out = evaluate_profit_take(s, total_quantity=100)
        assert out.should_exit is False
        assert out.level == "NONE"

    def test_at_5pct_exits_30pct_first_time(self):
        s = _snap(avg=100_000, current=105_000)
        out = evaluate_profit_take(s, total_quantity=100)
        assert out.should_exit is True
        assert out.level == "PROFIT_5"
        assert out.quantity_to_sell == 30
        assert out.new_position_status == "PARTIAL_CLOSED"

    def test_5pct_idempotent_after_executed(self):
        s = _snap(avg=100_000, current=108_000, profit_5=True)
        out = evaluate_profit_take(s, total_quantity=70)
        # +8% but profit_5 already executed and not yet at +10% -> NONE
        assert out.should_exit is False
        assert out.level == "NONE"

    def test_at_10pct_after_5_exits(self):
        s = _snap(avg=100_000, current=110_000, profit_5=True)
        out = evaluate_profit_take(s, total_quantity=70)
        assert out.should_exit is True
        assert out.level == "PROFIT_10"
        # 30% of 70 = 21 (floor)
        assert out.quantity_to_sell == 21

    def test_10pct_blocked_until_5_first(self):
        """+10% reached but +5% never executed -> +5% fires (catches up)."""
        s = _snap(avg=100_000, current=110_000, profit_5=False)
        out = evaluate_profit_take(s, total_quantity=100)
        assert out.level == "PROFIT_5"  # 5 fires first
        assert out.quantity_to_sell == 30

    def test_10pct_idempotent_after_executed(self):
        s = _snap(
            avg=100_000, current=120_000,
            profit_5=True, profit_10=True,
        )
        out = evaluate_profit_take(s, total_quantity=49)
        assert out.should_exit is False
        assert out.level == "NONE"

    def test_minimum_one_share_slice(self):
        """Tiny holdings (e.g. 3 shares) still slice >= 1 share."""
        s = _snap(avg=100_000, current=105_000)
        out = evaluate_profit_take(s, total_quantity=3)
        # floor(3*0.30) = 0 -> bumped to 1
        assert out.quantity_to_sell == 1

    def test_zero_quantity_returns_closed(self):
        s = _snap(avg=100_000, current=120_000, profit_5=True, profit_10=True)
        out = evaluate_profit_take(s, total_quantity=0)
        assert out.should_exit is False
        assert out.new_position_status == "CLOSED"
