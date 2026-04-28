"""Unit tests for V71MarketSchedule (Step A-4)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.core.v71.market.v71_market_schedule import (
    V71MarketSchedule,
    get_v71_market_schedule,
)


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """Each test starts with a fresh singleton."""
    monkeypatch.setattr(
        "src.core.v71.market.v71_market_schedule._singleton", None,
    )
    yield


def test_default_schedule_no_holidays():
    s = V71MarketSchedule()
    assert s.is_holiday(date(2026, 1, 1)) is False


def test_set_holidays_replaces_existing():
    s = V71MarketSchedule()
    s.set_holidays([date(2026, 1, 1)])
    assert s.is_holiday(date(2026, 1, 1)) is True
    s.set_holidays([date(2026, 5, 5)])
    # Old holiday no longer present
    assert s.is_holiday(date(2026, 1, 1)) is False
    assert s.is_holiday(date(2026, 5, 5)) is True


def test_is_trading_day_excludes_weekends():
    s = V71MarketSchedule()
    # Saturday + Sunday in early 2026
    assert s.is_trading_day(date(2026, 1, 3)) is False  # Saturday
    assert s.is_trading_day(date(2026, 1, 4)) is False  # Sunday
    assert s.is_trading_day(date(2026, 1, 5)) is True   # Monday


def test_is_trading_day_excludes_holidays():
    s = V71MarketSchedule()
    s.set_holidays([date(2026, 1, 5)])  # Monday holiday
    assert s.is_trading_day(date(2026, 1, 5)) is False


def test_is_market_open_within_session_on_trading_day():
    s = V71MarketSchedule()
    # 2026-01-05 = Monday 10:00 -> open
    moment = datetime(2026, 1, 5, 10, 0, 0)
    assert s.is_market_open(moment) is True


def test_is_market_open_before_session():
    s = V71MarketSchedule()
    moment = datetime(2026, 1, 5, 8, 30, 0)  # before 09:00
    assert s.is_market_open(moment) is False


def test_is_market_open_after_session():
    s = V71MarketSchedule()
    moment = datetime(2026, 1, 5, 16, 0, 0)  # after 15:30
    assert s.is_market_open(moment) is False


def test_is_market_open_weekend_returns_false():
    s = V71MarketSchedule()
    moment = datetime(2026, 1, 3, 10, 0, 0)  # Saturday 10:00
    assert s.is_market_open(moment) is False


def test_is_market_open_holiday_returns_false():
    s = V71MarketSchedule()
    s.set_holidays([date(2026, 1, 5)])
    moment = datetime(2026, 1, 5, 10, 0, 0)
    assert s.is_market_open(moment) is False


def test_next_trading_day_skips_weekend():
    s = V71MarketSchedule()
    # Friday 2026-01-02 -> Monday 2026-01-05
    next_day = s.next_trading_day(date(2026, 1, 2))
    assert next_day == date(2026, 1, 5)


def test_next_trading_day_skips_holiday():
    s = V71MarketSchedule()
    s.set_holidays([date(2026, 1, 5)])  # Mon holiday
    next_day = s.next_trading_day(date(2026, 1, 2))
    assert next_day == date(2026, 1, 6)  # Tuesday


def test_get_v71_market_schedule_returns_singleton():
    a = get_v71_market_schedule()
    b = get_v71_market_schedule()
    assert a is b
