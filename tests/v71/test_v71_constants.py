"""Sanity tests for V71Constants.

These pin the values to PRD (02_TRADING_RULES.md, 01_PRD_MAIN.md App. C).
A test failure here means either (a) the PRD changed and constants need
to be re-aligned, or (b) someone edited constants without PRD approval --
either way it must surface immediately.
"""

from __future__ import annotations

from src.core.v71.v71_constants import V71Constants as K


class TestStopLadder:
    def test_initial_stop_is_neg_5pct(self):
        assert K.STOP_LOSS_INITIAL_PCT == -0.05

    def test_after_5pct_partial_stop_is_neg_2pct(self):
        assert K.STOP_LOSS_AFTER_PROFIT_5 == -0.02

    def test_after_10pct_partial_stop_is_pos_4pct(self):
        assert K.STOP_LOSS_AFTER_PROFIT_10 == 0.04

    def test_stop_ladder_is_strictly_one_way_upward(self):
        assert K.STOP_LOSS_INITIAL_PCT < K.STOP_LOSS_AFTER_PROFIT_5 < K.STOP_LOSS_AFTER_PROFIT_10


class TestPartialTakeProfit:
    def test_levels_are_5_and_10(self):
        assert K.PROFIT_TAKE_LEVEL_1 == 0.05
        assert K.PROFIT_TAKE_LEVEL_2 == 0.10

    def test_slice_is_30pct(self):
        assert K.PROFIT_TAKE_RATIO == 0.30


class TestTrailingStop:
    def test_activation_at_5pct(self):
        assert K.TS_ACTIVATION_LEVEL == 0.05

    def test_binding_after_10pct_partial(self):
        assert K.TS_VALID_LEVEL == 0.10


class TestAtrLadder:
    def test_tier_values(self):
        assert K.ATR_MULTIPLIER_TIER_1 == 4.0
        assert K.ATR_MULTIPLIER_TIER_2 == 3.0
        assert K.ATR_MULTIPLIER_TIER_3 == 2.5
        assert K.ATR_MULTIPLIER_TIER_4 == 2.0

    def test_tiers_strictly_tighten(self):
        assert (
            K.ATR_MULTIPLIER_TIER_1
            > K.ATR_MULTIPLIER_TIER_2
            > K.ATR_MULTIPLIER_TIER_3
            > K.ATR_MULTIPLIER_TIER_4
        )

    def test_thresholds_match_tier_count(self):
        assert len(K.ATR_TIER_THRESHOLDS) == 4

    def test_thresholds_strictly_increase(self):
        ths = K.ATR_TIER_THRESHOLDS
        assert all(ths[i] < ths[i + 1] for i in range(len(ths) - 1))

    def test_atr_period_is_10(self):
        assert K.ATR_PERIOD == 10

    def test_base_price_lookback_is_20(self):
        assert K.BASE_PRICE_LOOKBACK == 20


class TestBoxSystem:
    def test_position_cap_is_30pct(self):
        assert K.MAX_POSITION_PCT_PER_STOCK == 30.0

    def test_auto_exit_drop_is_neg_20pct(self):
        assert K.AUTO_EXIT_BOX_DROP_PCT == -0.20

    def test_expiry_reminder_is_30_days(self):
        assert K.BOX_EXPIRY_REMINDER_DAYS == 30


class TestBuyExecution:
    def test_order_retry_count_is_3(self):
        assert K.ORDER_RETRY_COUNT == 3

    def test_order_wait_is_5_seconds(self):
        assert K.ORDER_WAIT_SECONDS == 5


class TestGapLimits:
    def test_path_b_gap_up_5pct(self):
        assert K.PATH_B_GAP_UP_LIMIT == 0.05

    def test_vi_gap_3pct(self):
        assert K.VI_GAP_LIMIT == 0.03


class TestRestartRecovery:
    def test_5_restarts_in_1_hour_warning(self):
        assert K.RESTART_FREQUENCY_WARN_WINDOW_HOURS == 1
        assert K.RESTART_FREQUENCY_WARN_THRESHOLD == 5


class TestStrategyPaths:
    def test_path_a_is_3min(self):
        assert K.PATH_A_TIMEFRAME_MINUTES == 3

    def test_path_b_primary_buy_at_0901(self):
        assert K.PATH_B_PRIMARY_BUY_TIME_HHMM == "09:01"

    def test_path_b_fallback_buy_at_0905(self):
        """§3.10/§3.11/§10.9: 09:01 매수 실패 시 09:05 안전장치."""
        assert K.PATH_B_FALLBACK_BUY_TIME_HHMM == "09:05"

    def test_path_b_fallback_uses_market_order(self):
        """fallback 시점은 즉시 체결 우선 (시장가 강제)."""
        assert K.PATH_B_FALLBACK_USES_MARKET_ORDER is True

    def test_path_b_fallback_is_after_primary(self):
        """fallback 시각이 1차 시각보다 뒤여야 함 (시간순)."""
        from datetime import datetime
        primary = datetime.strptime(K.PATH_B_PRIMARY_BUY_TIME_HHMM, "%H:%M")
        fallback = datetime.strptime(K.PATH_B_FALLBACK_BUY_TIME_HHMM, "%H:%M")
        assert primary < fallback

    def test_path_b_fallback_within_morning_session(self):
        """fallback이 정규장 시간(09:00~) 내에 있어야 함."""
        from datetime import datetime
        fallback = datetime.strptime(K.PATH_B_FALLBACK_BUY_TIME_HHMM, "%H:%M")
        market_open = datetime.strptime("09:00", "%H:%M")
        market_close = datetime.strptime("15:30", "%H:%M")
        assert market_open <= fallback <= market_close


def test_constants_are_immutable_via_typing():
    """Final[...] should at least cause type-checkers to flag rebinds.

    Runtime is permissive, but verify the marker is present so tooling
    catches accidents.
    """
    annotations = K.__annotations__
    for name in ("STOP_LOSS_INITIAL_PCT", "PROFIT_TAKE_RATIO", "ATR_MULTIPLIER_TIER_1"):
        assert "Final" in str(annotations.get(name, "")), f"{name} should be Final[...]"
