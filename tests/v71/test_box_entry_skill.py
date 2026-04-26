"""Unit tests for ``src/core/v71/skills/box_entry_skill.py``.

Spec:
  - 02_TRADING_RULES.md §3.8 (PULLBACK PATH_A)
  - 02_TRADING_RULES.md §3.9 (BREAKOUT PATH_A)
  - 02_TRADING_RULES.md §3.10 (PULLBACK PATH_B + 09:05 fallback)
  - 02_TRADING_RULES.md §3.11 (BREAKOUT PATH_B + 09:05 fallback)
  - 02_TRADING_RULES.md §10.9 (opening-VI safety net)
  - 07_SKILLS_SPEC.md §2

These tests pin every entry-condition rule. A failure here means either
the PRD changed (and the skill needs updating) or someone introduced a
non-spec branch.
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_box_system():
    """Activate v71.box_system for every test in this module."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


# Imports below the fixture so feature flag is set when the skill module
# loads. The flag is checked inside functions, not at import, so this is
# defensive only.
from src.core.candle_builder import Candle, Timeframe  # noqa: E402
from src.core.v71.skills import box_entry_skill as bes  # noqa: E402
from src.core.v71.v71_constants import V71Constants  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_candle(
    *,
    open_: int,
    high: int,
    low: int,
    close: int,
    timeframe: Timeframe = Timeframe.M3,
    when: datetime | None = None,
) -> Candle:
    return Candle(
        stock_code="005930",
        timeframe=timeframe,
        time=when or datetime(2026, 4, 27, 14, 30),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
        is_complete=True,
    )


def make_box(
    *,
    upper: int = 100,
    lower: int = 90,
    strategy: str = "PULLBACK",
    path: str = "PATH_A",
) -> bes.Box:
    return bes.Box(
        upper_price=upper,
        lower_price=lower,
        strategy_type=strategy,  # type: ignore[arg-type]
        path_type=path,  # type: ignore[arg-type]
    )


def make_context(
    *,
    is_market_open: bool = True,
    is_vi_active: bool = False,
    is_vi_recovered_today: bool = False,
    when: datetime | None = None,
) -> bes.MarketContext:
    return bes.MarketContext(
        is_market_open=is_market_open,
        is_vi_active=is_vi_active,
        is_vi_recovered_today=is_vi_recovered_today,
        current_time=when or datetime(2026, 4, 27, 14, 30),  # Monday
    )


@pytest.fixture
def no_holidays(monkeypatch):
    """Patch holiday checker to always-False (only weekend skipping)."""
    monkeypatch.setattr(bes, "_get_holiday_checker", lambda: lambda _d: False)


# ---------------------------------------------------------------------------
# PATH_A pullback (§3.8)
# ---------------------------------------------------------------------------


class TestPullbackPathA:
    def test_both_candles_meet_conditions(self):
        prev = make_candle(open_=92, high=98, low=91, close=95)
        curr = make_candle(open_=95, high=99, low=94, close=97)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.should_enter is True
        assert decision.reason == "PULLBACK_A_TRIGGERED"
        assert decision.expected_buy_price == 97
        # PATH_A: no fallback metadata.
        assert decision.fallback_buy_at is None
        assert decision.fallback_uses_market_order is False
        assert decision.fallback_gap_recheck_required is False

    def test_prev_candle_not_bullish(self):
        prev = make_candle(open_=98, high=99, low=94, close=95)  # Open > Close
        curr = make_candle(open_=95, high=99, low=94, close=97)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.should_enter is False
        assert decision.reason == "PULLBACK_A_PREV_NOT_MET"

    def test_curr_candle_not_bullish(self):
        prev = make_candle(open_=92, high=98, low=91, close=95)
        curr = make_candle(open_=97, high=98, low=92, close=94)  # Open > Close
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.should_enter is False
        assert decision.reason == "PULLBACK_A_CURR_NOT_MET"

    def test_prev_close_above_box(self):
        prev = make_candle(open_=99, high=105, low=98, close=104)  # close > upper
        curr = make_candle(open_=95, high=99, low=94, close=97)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.reason == "PULLBACK_A_PREV_NOT_MET"

    def test_curr_close_below_box(self):
        prev = make_candle(open_=92, high=98, low=91, close=95)
        curr = make_candle(open_=85, high=89, low=80, close=88)  # close < lower
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.reason == "PULLBACK_A_CURR_NOT_MET"

    def test_close_equals_open_is_not_bullish(self):
        """Doji bar (Close == Open) must fail bullish check (§3.8 edge)."""
        prev = make_candle(open_=92, high=98, low=91, close=95)
        curr = make_candle(open_=95, high=98, low=94, close=95)  # doji
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.reason == "PULLBACK_A_CURR_NOT_MET"

    def test_close_at_box_upper_is_inside(self):
        """Close == upper is "inside" (inclusive bounds)."""
        prev = make_candle(open_=92, high=100, low=91, close=100)  # close = upper
        curr = make_candle(open_=99, high=100, low=98, close=100)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.should_enter is True

    def test_close_at_box_lower_is_inside(self):
        """Close == lower is "inside"."""
        prev = make_candle(open_=89, high=92, low=88, close=90)  # close = lower
        curr = make_candle(open_=89, high=93, low=88, close=90)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
            market_context=make_context(),
        )
        assert decision.should_enter is True

    def test_missing_previous_candle_raises(self):
        curr = make_candle(open_=95, high=99, low=94, close=97)
        with pytest.raises(ValueError, match="previous candle"):
            bes.evaluate_box_entry(
                box=make_box(strategy="PULLBACK", path="PATH_A"),
                current_candle=curr,
                previous_candle=None,
                market_context=make_context(),
            )


# ---------------------------------------------------------------------------
# PATH_A breakout (§3.9)
# ---------------------------------------------------------------------------


class TestBreakoutPathA:
    def test_normal_breakout(self):
        curr = make_candle(open_=95, high=105, low=94, close=103)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_A"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(),
        )
        assert decision.should_enter is True
        assert decision.reason == "BREAKOUT_A_TRIGGERED"
        assert decision.fallback_buy_at is None  # PATH_A: no fallback

    def test_close_equals_upper_is_no_break(self):
        curr = make_candle(open_=95, high=100, low=94, close=100)  # close == upper
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_A"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(),
        )
        assert decision.reason == "BREAKOUT_NO_BREAK"

    def test_breakout_with_bearish_candle_rejected(self):
        curr = make_candle(open_=110, high=112, low=100, close=103)  # bearish
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_A"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(),
        )
        assert decision.reason == "BREAKOUT_NOT_BULLISH"

    def test_gap_open_breakout_rejected(self):
        # open below box.lower -> gap-up case (excluded per §3.9).
        curr = make_candle(open_=85, high=110, low=85, close=108)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_A"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(),
        )
        assert decision.reason == "BREAKOUT_GAP_OPEN"

    def test_open_at_lower_is_normal(self):
        """Open == lower is the boundary -- still a normal breakout."""
        curr = make_candle(open_=90, high=105, low=90, close=103)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_A"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(),
        )
        assert decision.should_enter is True


# ---------------------------------------------------------------------------
# PATH_B (§3.10, §3.11) + safety-net metadata (§10.9)
# ---------------------------------------------------------------------------


class TestPullbackPathB:
    @pytest.mark.usefixtures("no_holidays")
    def test_pullback_b_triggered_with_fallback(self):
        # Mon 14:30 -> next trading day is Tuesday.
        when = datetime(2026, 4, 27, 14, 30)  # Monday
        curr = make_candle(
            open_=92, high=98, low=91, close=95, timeframe=Timeframe.M3, when=when
        )
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_B"),
            current_candle=curr,
            previous_candle=None,  # PATH_B does not require previous
            market_context=make_context(when=when),
        )
        assert decision.should_enter is True
        assert decision.reason == "PULLBACK_B_TRIGGERED"
        # 1차 09:01 + 2차 09:05 (Tuesday)
        assert decision.expected_buy_at == datetime(2026, 4, 28, 9, 1)
        assert decision.fallback_buy_at == datetime(2026, 4, 28, 9, 5)
        assert decision.fallback_uses_market_order is True
        assert decision.fallback_gap_recheck_required is True

    def test_pullback_b_not_met(self):
        when = datetime(2026, 4, 27, 14, 30)
        curr = make_candle(
            open_=85, high=89, low=80, close=88, when=when
        )  # below box
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_B"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(when=when),
        )
        assert decision.should_enter is False
        assert decision.reason == "PULLBACK_B_NOT_MET"


class TestBreakoutPathB:
    @pytest.mark.usefixtures("no_holidays")
    def test_breakout_b_triggered_with_fallback(self):
        when = datetime(2026, 4, 27, 14, 30)
        curr = make_candle(open_=95, high=110, low=94, close=108, when=when)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_B"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(when=when),
        )
        assert decision.should_enter is True
        assert decision.reason == "BREAKOUT_B_TRIGGERED"
        assert decision.expected_buy_at == datetime(2026, 4, 28, 9, 1)
        assert decision.fallback_buy_at == datetime(2026, 4, 28, 9, 5)
        assert decision.fallback_uses_market_order is True
        assert decision.fallback_gap_recheck_required is True

    def test_breakout_b_gap_open_rejected(self):
        when = datetime(2026, 4, 27, 14, 30)
        curr = make_candle(open_=85, high=110, low=85, close=108, when=when)
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="BREAKOUT", path="PATH_B"),
            current_candle=curr,
            previous_candle=None,
            market_context=make_context(when=when),
        )
        assert decision.reason == "BREAKOUT_GAP_OPEN"


class TestNextTradingDayCalculation:
    @pytest.mark.usefixtures("no_holidays")
    def test_friday_to_monday(self):
        """Friday 14:30 -> Monday 09:01."""
        friday = datetime(2026, 4, 24, 14, 30)  # Fri (verify weekday=4)
        assert friday.weekday() == 4
        primary, fallback = bes._next_trading_day_buy_times(friday)
        assert primary == datetime(2026, 4, 27, 9, 1)
        assert fallback == datetime(2026, 4, 27, 9, 5)
        assert primary.weekday() == 0  # Monday

    def test_skips_holiday(self, monkeypatch):
        """Holiday on the next day -> skip to the day after."""
        # Tue 4/28 is "holiday" -> next trading day is Wed 4/29.
        holiday_set = {date(2026, 4, 28)}
        monkeypatch.setattr(
            bes, "_get_holiday_checker", lambda: holiday_set.__contains__
        )
        monday = datetime(2026, 4, 27, 14, 30)
        primary, fallback = bes._next_trading_day_buy_times(monday)
        assert primary == datetime(2026, 4, 29, 9, 1)
        assert fallback == datetime(2026, 4, 29, 9, 5)

    def test_30_day_safety_bound(self, monkeypatch):
        """Pathological -- everything is a holiday -> RuntimeError."""
        monkeypatch.setattr(bes, "_get_holiday_checker", lambda: lambda _d: True)
        with pytest.raises(RuntimeError, match="No trading day"):
            bes._next_trading_day_buy_times(datetime(2026, 4, 27, 14, 30))


# ---------------------------------------------------------------------------
# Market-state guards
# ---------------------------------------------------------------------------


class TestMarketStateGuards:
    def test_market_closed(self):
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=make_candle(open_=95, high=99, low=94, close=97),
            previous_candle=make_candle(open_=92, high=98, low=91, close=95),
            market_context=make_context(is_market_open=False),
        )
        assert decision.should_enter is False
        assert decision.reason == "MARKET_CLOSED"

    def test_vi_active_defers_to_vi_skill(self):
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=make_candle(open_=95, high=99, low=94, close=97),
            previous_candle=make_candle(open_=92, high=98, low=91, close=95),
            market_context=make_context(is_vi_active=True),
        )
        assert decision.reason == "VI_ACTIVE_USE_VI_SKILL"

    def test_vi_recovered_today_blocks(self):
        decision = bes.evaluate_box_entry(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=make_candle(open_=95, high=99, low=94, close=97),
            previous_candle=make_candle(open_=92, high=98, low=91, close=95),
            market_context=make_context(is_vi_recovered_today=True),
        )
        assert decision.reason == "VI_RECOVERED_TODAY_BLOCKED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_upper_le_lower_raises(self):
        with pytest.raises(ValueError, match="upper_price"):
            bes.evaluate_box_entry(
                box=bes.Box(
                    upper_price=90,
                    lower_price=90,
                    strategy_type="PULLBACK",
                    path_type="PATH_A",
                ),
                current_candle=make_candle(open_=92, high=98, low=91, close=95),
                previous_candle=make_candle(open_=92, high=98, low=91, close=95),
                market_context=make_context(),
            )

    def test_negative_box_raises(self):
        with pytest.raises(ValueError, match="positive"):
            bes.evaluate_box_entry(
                box=bes.Box(
                    upper_price=10,
                    lower_price=-5,
                    strategy_type="PULLBACK",
                    path_type="PATH_A",
                ),
                current_candle=make_candle(open_=5, high=8, low=4, close=7),
                previous_candle=make_candle(open_=5, high=8, low=4, close=7),
                market_context=make_context(),
            )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestPureHelpers:
    def test_is_bullish(self):
        assert bes.is_bullish(make_candle(open_=10, high=12, low=9, close=11)) is True
        assert bes.is_bullish(make_candle(open_=11, high=12, low=9, close=10)) is False
        assert bes.is_bullish(make_candle(open_=10, high=10, low=10, close=10)) is False  # doji

    def test_is_pullback_setup_pure(self):
        prev = make_candle(open_=92, high=98, low=91, close=95)
        curr = make_candle(open_=95, high=99, low=94, close=97)
        assert bes.is_pullback_setup(
            box=make_box(strategy="PULLBACK", path="PATH_A"),
            current_candle=curr,
            previous_candle=prev,
        ) is True

    def test_is_breakout_setup_pure(self):
        curr = make_candle(open_=95, high=110, low=94, close=108)
        assert bes.is_breakout_setup(
            box=make_box(strategy="BREAKOUT", path="PATH_A"),
            current_candle=curr,
        ) is True


# ---------------------------------------------------------------------------
# Gap-up check (§3.10 1차 + §10.9 2차 fallback 공통)
# ---------------------------------------------------------------------------


class TestGapUpCheck:
    def test_gap_under_5pct_proceed(self):
        proceed, gap = bes.check_gap_up_for_path_b(10000, 10400)
        assert proceed is True
        assert pytest.approx(gap, abs=1e-9) == 0.04

    def test_gap_at_exact_5pct_does_not_proceed(self):
        """Strict less-than: 5.0% itself should block."""
        proceed, gap = bes.check_gap_up_for_path_b(10000, 10500)
        assert proceed is False
        assert pytest.approx(gap, abs=1e-9) == V71Constants.PATH_B_GAP_UP_LIMIT

    def test_gap_over_5pct_abandon(self):
        proceed, gap = bes.check_gap_up_for_path_b(10000, 10550)
        assert proceed is False
        assert gap > V71Constants.PATH_B_GAP_UP_LIMIT

    def test_gap_negative_proceeds(self):
        """A gap-down also "proceeds" -- the rule is only about gap-ups."""
        proceed, gap = bes.check_gap_up_for_path_b(10000, 9800)
        assert proceed is True
        assert gap < 0

    def test_invalid_prices_raises(self):
        with pytest.raises(ValueError):
            bes.check_gap_up_for_path_b(0, 10000)
        with pytest.raises(ValueError):
            bes.check_gap_up_for_path_b(10000, -1)


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFeatureFlagGate:
    def test_runtime_error_when_flag_disabled(self):
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.box_system"):
                bes.evaluate_box_entry(
                    box=make_box(),
                    current_candle=make_candle(open_=92, high=98, low=91, close=95),
                    previous_candle=make_candle(open_=92, high=98, low=91, close=95),
                    market_context=make_context(),
                )
        finally:
            os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
            ff.reload()
