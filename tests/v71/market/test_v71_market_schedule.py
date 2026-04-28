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


# ---------------------------------------------------------------------------
# KST timezone normalisation (Phase A Step F follow-up — P-Wire-14)
# ---------------------------------------------------------------------------


def test_is_market_open_tz_aware_utc_is_normalised_to_kst():
    """UTC tz-aware input must be converted to KST before window check.

    UTC 23:00 = KST 08:00 -- before market open. UTC 02:00 = KST
    11:00 -- inside market open.
    """
    from datetime import timezone

    s = V71MarketSchedule()
    # Friday 2026-01-02 23:00 UTC = Saturday 2026-01-03 08:00 KST -> closed
    fri_utc_late = datetime(2026, 1, 2, 23, 0, 0, tzinfo=timezone.utc)
    assert s.is_market_open(fri_utc_late) is False
    # Monday 2026-01-05 02:00 UTC = Monday 2026-01-05 11:00 KST -> open
    mon_utc_morning = datetime(2026, 1, 5, 2, 0, 0, tzinfo=timezone.utc)
    assert s.is_market_open(mon_utc_morning) is True


def test_is_market_open_naive_input_logs_warning_and_treats_as_kst(caplog):
    import logging
    s = V71MarketSchedule()
    naive_moment = datetime(2026, 1, 5, 10, 0, 0)  # no tzinfo
    with caplog.at_level(logging.WARNING):
        assert s.is_market_open(naive_moment) is True
    assert any(
        "naive datetime" in r.message for r in caplog.records
    )


def test_is_market_open_default_path_uses_kst(monkeypatch):
    """``now=None`` should call ``datetime.now(_KST)``, not the naive
    system clock. Verified by monkey-patching ``datetime`` in the
    schedule module."""
    from datetime import timezone

    import src.core.v71.market.v71_market_schedule as mod

    captured: list = []

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            captured.append(tz)
            # Return a value that's clearly inside the trading window
            # so the assertion focuses on the tz argument.
            base = datetime(2026, 1, 5, 10, 0, 0, tzinfo=timezone.utc)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(mod, "datetime", FakeDateTime)
    s = V71MarketSchedule()
    s.is_market_open()  # default None
    # _KST timezone passed (not None / not system local)
    assert captured == [mod._KST]
