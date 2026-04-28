"""Unit tests for KR_HOLIDAYS_2026 fallback list (P-Wire-14)."""

from __future__ import annotations

from datetime import date

from src.core.v71.market.v71_kr_holidays import KR_HOLIDAYS_2026


def test_holiday_set_is_frozen():
    assert isinstance(KR_HOLIDAYS_2026, frozenset)


def test_all_entries_are_date_instances():
    assert all(isinstance(d, date) for d in KR_HOLIDAYS_2026)


def test_all_entries_are_in_2026():
    assert all(d.year == 2026 for d in KR_HOLIDAYS_2026)


def test_includes_well_known_holidays():
    # New Year, Buddha's birthday (KR), Children's Day, Christmas.
    assert date(2026, 1, 1) in KR_HOLIDAYS_2026
    assert date(2026, 5, 5) in KR_HOLIDAYS_2026
    assert date(2026, 12, 25) in KR_HOLIDAYS_2026


def test_includes_krx_specific_closures():
    # KRX-specific (not a public holiday): Workers' Day + year-end close.
    assert date(2026, 5, 1) in KR_HOLIDAYS_2026
    assert date(2026, 12, 31) in KR_HOLIDAYS_2026


def test_lunar_new_year_window_present():
    # Operators set 3-day Lunar New Year closure (2/16-2/18).
    assert date(2026, 2, 16) in KR_HOLIDAYS_2026
    assert date(2026, 2, 17) in KR_HOLIDAYS_2026
    assert date(2026, 2, 18) in KR_HOLIDAYS_2026


def test_chuseok_window_present():
    # Chuseok 2026 falls on Sep 25 (Fri) with Sep 24 (Thu) as run-up.
    assert date(2026, 9, 24) in KR_HOLIDAYS_2026
    assert date(2026, 9, 25) in KR_HOLIDAYS_2026
