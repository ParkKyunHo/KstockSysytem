"""Unit tests for V71CandleManager (Step A-4)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.v71.candle.v71_candle_manager import V71CandleManager


def _factory():
    kiwoom = MagicMock()
    kiwoom.get_daily_chart = AsyncMock(
        return_value=SimpleNamespace(data={"stk_dt_pole_chart_qry": []}),
    )
    ws = MagicMock()
    ws.register_handler = MagicMock()
    return V71CandleManager(
        kiwoom_client=kiwoom,
        kiwoom_websocket=ws,
        eod_fetch_provider=lambda: "20260427",
    ), kiwoom, ws


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_registers_price_tick_handler_idempotent():
    mgr, _kiwoom, ws = _factory()
    await mgr.start()
    await mgr.start()  # idempotent
    assert ws.register_handler.call_count == 1


@pytest.mark.asyncio
async def test_stop_flushes_three_minute_builders():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    builder = mgr.get_three_minute_builder("005930")
    builder.flush = AsyncMock()
    await mgr.stop()
    builder.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# add_stock / remove_stock
# ---------------------------------------------------------------------------


def test_add_stock_creates_three_minute_and_daily_builders():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    assert mgr.get_three_minute_builder("005930") is not None
    assert mgr.get_daily_builder("005930") is not None
    assert "005930" in mgr.tracked_stocks()


def test_add_stock_idempotent():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    first_tm = mgr.get_three_minute_builder("005930")
    mgr.add_stock("005930")
    assert mgr.get_three_minute_builder("005930") is first_tm


def test_remove_stock_drops_builders():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    mgr.remove_stock("005930")
    assert mgr.get_three_minute_builder("005930") is None
    assert mgr.get_daily_builder("005930") is None
    assert "005930" not in mgr.tracked_stocks()


# ---------------------------------------------------------------------------
# Subscriber fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_on_complete_attaches_to_existing_builders():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    cb = AsyncMock()
    mgr.register_on_complete(cb)
    assert cb in mgr.get_three_minute_builder("005930")._subscribers
    assert cb in mgr.get_daily_builder("005930")._subscribers


def test_register_on_complete_propagates_to_future_builders():
    mgr, _kiwoom, _ws = _factory()
    cb = AsyncMock()
    mgr.register_on_complete(cb)
    mgr.add_stock("005930")
    assert cb in mgr.get_three_minute_builder("005930")._subscribers
    assert cb in mgr.get_daily_builder("005930")._subscribers


# ---------------------------------------------------------------------------
# PRICE_TICK routing
# ---------------------------------------------------------------------------


def _msg(stock_code, values, received_at=None):
    return SimpleNamespace(
        item=stock_code,
        values=values,
        received_at=received_at or datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_price_message_routes_to_correct_builder():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    builder = mgr.get_three_minute_builder("005930")
    builder.on_tick = AsyncMock()
    await mgr._on_price_message(_msg("005930", {"10": "70000", "15": "10"}))
    builder.on_tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_price_message_for_untracked_stock_is_ignored():
    mgr, _kiwoom, _ws = _factory()
    # No add_stock; message arrives anyway
    await mgr._on_price_message(_msg("005930", {"10": "70000"}))
    # No exception, no builder. Pass = no exception thrown.


@pytest.mark.asyncio
async def test_price_message_failed_parse_returns_none():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    builder = mgr.get_three_minute_builder("005930")
    builder.on_tick = AsyncMock()
    # Empty values -> message_to_tick returns None
    await mgr._on_price_message(_msg("005930", {}))
    builder.on_tick.assert_not_awaited()


# ---------------------------------------------------------------------------
# fetch_eod_for_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_eod_for_all_returns_new_count():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    mgr.add_stock("000660")
    fake_candle = MagicMock()
    for stock_code in ("005930", "000660"):
        builder = mgr.get_daily_builder(stock_code)
        builder.fetch_eod = AsyncMock(return_value=fake_candle)
    new_count = await mgr.fetch_eod_for_all(base_date="20260427")
    assert new_count == 2


@pytest.mark.asyncio
async def test_fetch_eod_for_all_isolates_per_stock_failure(caplog):
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    mgr.add_stock("000660")
    fake_candle = MagicMock()
    mgr.get_daily_builder("005930").fetch_eod = AsyncMock(
        side_effect=RuntimeError("kt 5xx"),
    )
    mgr.get_daily_builder("000660").fetch_eod = AsyncMock(
        return_value=fake_candle,
    )
    with caplog.at_level("WARNING"):
        new_count = await mgr.fetch_eod_for_all(base_date="20260427")
    assert new_count == 1  # 005930 failed but 000660 succeeded
    assert any("fetch_eod failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fetch_history_for_all_sums_returned_counts():
    mgr, _kiwoom, _ws = _factory()
    mgr.add_stock("005930")
    mgr.add_stock("000660")
    mgr.get_daily_builder("005930").fetch_history = AsyncMock(return_value=10)
    mgr.get_daily_builder("000660").fetch_history = AsyncMock(return_value=15)
    total = await mgr.fetch_history_for_all(base_date="20260427")
    assert total == 25


# ---------------------------------------------------------------------------
# KST timezone helpers (Phase A Step F P-Wire-12)
# ---------------------------------------------------------------------------
#
# Purpose: prove that EOD scheduling and base_date calculation align with
# the KST market clock even when the host OS runs UTC (the AWS Lightsail
# default). Patches ``datetime`` inside the candle manager module so
# ``datetime.now(_KST)`` resolves deterministically.


class _FakeDateTime:
    """``datetime`` stand-in returning a fixed UTC instant for ``now()``.

    ``now(tz)`` honours ``tz.astimezone`` like the real class so callers
    that pass ``_KST`` receive a KST-shifted clock.
    """

    _frozen_utc: datetime

    @classmethod
    def now(cls, tz=None):
        utc = cls._frozen_utc
        if tz is not None:
            return utc.astimezone(tz)
        return utc.replace(tzinfo=None)

    def __new__(cls, *args, **kwargs):
        return datetime(*args, **kwargs)


def _patch_datetime(monkeypatch, frozen_utc: datetime) -> None:
    import src.core.v71.candle.v71_candle_manager as candle_mod

    fake = type(
        "_FakeDateTimeBound",
        (_FakeDateTime,),
        {"_frozen_utc": frozen_utc},
    )
    monkeypatch.setattr(candle_mod, "datetime", fake)


def test_default_eod_date_returns_kst_today_when_host_is_utc(monkeypatch):
    # UTC 00:30 == KST 09:30 same day. Naive system local on a UTC host
    # would also emit "20260428"; this test pins the OK case.
    frozen = datetime(2026, 4, 28, 0, 30, 0, tzinfo=timezone.utc)
    _patch_datetime(monkeypatch, frozen)
    from src.core.v71.candle.v71_candle_manager import _default_eod_date
    assert _default_eod_date() == "20260428"


def test_default_eod_date_rolls_to_next_day_in_kst(monkeypatch):
    # UTC 22:00 == KST 07:00 next day. Naive system local on UTC would
    # emit "20260428" (the previous KST date). KST-aware path emits the
    # next day -- this is the breaking case the patch fixes.
    frozen = datetime(2026, 4, 28, 22, 0, 0, tzinfo=timezone.utc)
    _patch_datetime(monkeypatch, frozen)
    from src.core.v71.candle.v71_candle_manager import _default_eod_date
    assert _default_eod_date() == "20260429"


@pytest.mark.parametrize(
    "utc_h,utc_m,target_hhmm,expected",
    [
        # KST 15:34 (UTC 06:34) < 15:35 -> False
        (6, 34, "15:35", False),
        # KST 15:35 (UTC 06:35) >= 15:35 -> True (boundary)
        (6, 35, "15:35", True),
        # KST 15:36 (UTC 06:36) >= 15:35 -> True
        (6, 36, "15:35", True),
    ],
)
def test_is_after_hhmm_boundary_at_kst_15_35(
    monkeypatch, utc_h, utc_m, target_hhmm, expected,
):
    frozen = datetime(2026, 4, 28, utc_h, utc_m, 0, tzinfo=timezone.utc)
    _patch_datetime(monkeypatch, frozen)
    from src.core.v71.candle.v71_candle_manager import _is_after_hhmm
    assert _is_after_hhmm(target_hhmm) is expected
