"""Unit tests for P-Wire-14 — V71MarketSchedule holidays seed wiring.

Spec: docs/v71/03_DATA_MODEL.md §6.1, docs/v71/02_TRADING_RULES.md §7/§10.

Covers:
  * `_load_holidays_seed` DB-success path → ``"db"`` source
  * `_load_holidays_seed` empty-table path → hardcoded fallback
  * `_load_holidays_seed` DB timeout / exception → hardcoded fallback
  * `_build_market_calendar` seeds the singleton + records source
  * V71MarketSchedule receives the holidays as ``frozenset[date]``
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    """Each test starts with a fresh V71MarketSchedule singleton."""
    monkeypatch.setattr(
        "src.core.v71.market.v71_market_schedule._singleton", None,
    )
    yield


def _patch_db_session(monkeypatch, *, rows=None, raise_with=None):
    """Patch ``trading_bridge`` DB access to return canned rows or raise."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    if rows is None:
        rows = []

    class _FakeResult:
        def all(self):
            return [(d,) for d in rows]

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(
        return_value=_FakeResult(),
        side_effect=raise_with,
    )

    @asynccontextmanager
    async def _session_cm():
        yield fake_session

    fake_db = MagicMock()
    fake_db.session = _session_cm

    monkeypatch.setattr(
        "src.database.connection.get_db_manager",
        lambda: fake_db,
    )


@pytest.mark.asyncio
async def test_load_holidays_seed_returns_db_when_table_has_rows(monkeypatch):
    rows = [date(2026, 1, 1), date(2026, 12, 25)]
    _patch_db_session(monkeypatch, rows=rows)
    from src.web.v71.trading_bridge import _load_holidays_seed
    holidays, source = await _load_holidays_seed()
    assert source == "db"
    assert holidays == frozenset(rows)


@pytest.mark.asyncio
async def test_load_holidays_seed_falls_back_when_db_empty(
    monkeypatch, caplog,
):
    import logging
    _patch_db_session(monkeypatch, rows=[])
    from src.core.v71.market.v71_kr_holidays import KR_HOLIDAYS_2026
    from src.web.v71.trading_bridge import _load_holidays_seed
    with caplog.at_level(logging.WARNING):
        holidays, source = await _load_holidays_seed()
    assert source == "hardcoded_fallback"
    assert holidays == KR_HOLIDAYS_2026
    assert any(
        "market_calendar table empty" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_load_holidays_seed_falls_back_on_db_exception(
    monkeypatch, caplog,
):
    import logging
    _patch_db_session(monkeypatch, raise_with=RuntimeError("simulated_db"))
    from src.core.v71.market.v71_kr_holidays import KR_HOLIDAYS_2026
    from src.web.v71.trading_bridge import _load_holidays_seed
    with caplog.at_level(logging.WARNING):
        holidays, source = await _load_holidays_seed()
    assert source == "hardcoded_fallback"
    assert holidays == KR_HOLIDAYS_2026
    assert any(
        "market_calendar prime failed" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_load_holidays_seed_falls_back_on_timeout(
    monkeypatch, caplog,
):
    import logging
    _patch_db_session(monkeypatch, raise_with=asyncio.TimeoutError())
    from src.core.v71.market.v71_kr_holidays import KR_HOLIDAYS_2026
    from src.web.v71.trading_bridge import _load_holidays_seed
    with caplog.at_level(logging.WARNING):
        holidays, source = await _load_holidays_seed()
    # asyncio.TimeoutError surfaces via the Exception fallback path
    # (the timeout context manager itself is a separate trigger).
    assert source == "hardcoded_fallback"
    assert holidays == KR_HOLIDAYS_2026


@pytest.mark.asyncio
async def test_build_market_calendar_seeds_singleton(monkeypatch):
    rows = [date(2026, 5, 5)]
    _patch_db_session(monkeypatch, rows=rows)
    from src.core.v71.market.v71_market_schedule import (
        get_v71_market_schedule,
    )
    from src.web.v71.trading_bridge import (
        _build_market_calendar,
        _TradingEngineHandle,
    )
    handle = _TradingEngineHandle()
    await _build_market_calendar(handle)
    assert handle.market_calendar_source == "db"
    schedule = get_v71_market_schedule()
    assert schedule.is_holiday(date(2026, 5, 5)) is True
    assert schedule.is_holiday(date(2026, 1, 1)) is False  # not in seed


@pytest.mark.asyncio
async def test_build_market_calendar_records_fallback_source(monkeypatch):
    _patch_db_session(monkeypatch, rows=[])
    from src.core.v71.market.v71_kr_holidays import KR_HOLIDAYS_2026
    from src.core.v71.market.v71_market_schedule import (
        get_v71_market_schedule,
    )
    from src.web.v71.trading_bridge import (
        _build_market_calendar,
        _TradingEngineHandle,
    )
    handle = _TradingEngineHandle()
    await _build_market_calendar(handle)
    assert handle.market_calendar_source == "hardcoded_fallback"
    schedule = get_v71_market_schedule()
    # All hardcoded entries are loaded
    for d in KR_HOLIDAYS_2026:
        assert schedule.is_holiday(d) is True
