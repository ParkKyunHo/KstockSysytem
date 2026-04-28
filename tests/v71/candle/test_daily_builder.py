"""Unit tests for V71DailyCandleBuilder (Step A-3)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.v71.candle.types import V71Candle
from src.core.v71.candle.v71_candle_builder import V71BaseCandleBuilder
from src.core.v71.candle.v71_daily_builder import V71DailyCandleBuilder
from src.core.v71.v71_constants import V71Timeframe


def _row(date="20260427", open_p=70_000, high=71_000, low=69_500,
          close=70_500, volume=1_000_000):
    return {
        "dt": date,
        "open_pric": str(open_p),
        "high_pric": str(high),
        "low_pric": str(low),
        "cur_prc": str(close),
        "trde_qty": str(volume),
    }


def _response(rows):
    return SimpleNamespace(
        data={"stk_dt_pole_chart_qry": rows},
        cont_yn="N",
        next_key="",
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_daily_builder_satisfies_protocol():
    builder = V71DailyCandleBuilder("005930", kiwoom_client=MagicMock())
    assert isinstance(builder, V71BaseCandleBuilder)
    assert builder.stock_code == "005930"
    assert builder.timeframe == V71Timeframe.DAILY


# ---------------------------------------------------------------------------
# fetch_eod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_eod_caches_and_dispatches():
    client = MagicMock()
    client.get_daily_chart = AsyncMock(
        return_value=_response([_row()]),
    )
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    cb = AsyncMock()
    builder.register_on_complete(cb)

    candle = await builder.fetch_eod(base_date="20260427")
    assert candle is not None
    assert isinstance(candle, V71Candle)
    assert candle.stock_code == "005930"
    assert candle.timeframe == V71Timeframe.DAILY
    assert candle.timestamp == datetime(2026, 4, 27, tzinfo=timezone.utc)
    assert candle.open == 70_000
    assert candle.high == 71_000
    assert candle.low == 69_500
    assert candle.close == 70_500
    assert candle.volume == 1_000_000
    cb.assert_awaited_once_with(candle)


@pytest.mark.asyncio
async def test_fetch_eod_idempotent_on_same_date():
    client = MagicMock()
    client.get_daily_chart = AsyncMock(
        return_value=_response([_row(date="20260427")]),
    )
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    cb = AsyncMock()
    builder.register_on_complete(cb)

    first = await builder.fetch_eod(base_date="20260427")
    second = await builder.fetch_eod(base_date="20260427")  # cache hit
    assert first is not None
    assert second is None  # idempotent
    cb.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_eod_kiwoom_failure_returns_none(caplog):
    client = MagicMock()
    client.get_daily_chart = AsyncMock(
        side_effect=RuntimeError("kt 5xx"),
    )
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    cb = AsyncMock()
    builder.register_on_complete(cb)

    with caplog.at_level("WARNING"):
        result = await builder.fetch_eod(base_date="20260427")
    assert result is None
    cb.assert_not_awaited()
    assert any("ka10081 fetch failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fetch_eod_empty_response_returns_none():
    client = MagicMock()
    client.get_daily_chart = AsyncMock(return_value=_response([]))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    result = await builder.fetch_eod(base_date="20260427")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_eod_alternative_field_aliases():
    client = MagicMock()
    # Use {"open"/"high"/"low"/"close"/"volume"/"date"} aliases
    row = {
        "date": "20260427",
        "open": "60000",
        "high": "62000",
        "low": "59000",
        "close": "61000",
        "volume": "500000",
    }
    client.get_daily_chart = AsyncMock(return_value=_response([row]))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    candle = await builder.fetch_eod(base_date="20260427")
    assert candle is not None
    assert candle.open == 60_000
    assert candle.close == 61_000


@pytest.mark.asyncio
async def test_fetch_eod_invalid_date_skipped(caplog):
    client = MagicMock()
    bad_row = _row(date="ABC")
    client.get_daily_chart = AsyncMock(return_value=_response([bad_row]))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    with caplog.at_level("WARNING"):
        result = await builder.fetch_eod(base_date="20260427")
    assert result is None
    assert any("invalid date format" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_fetch_eod_zero_close_skipped(caplog):
    client = MagicMock()
    bad_row = _row(close=0)
    client.get_daily_chart = AsyncMock(return_value=_response([bad_row]))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    with caplog.at_level("WARNING"):
        result = await builder.fetch_eod(base_date="20260427")
    assert result is None
    assert any("missing OHLC" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# fetch_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_history_bulk_prime_no_dispatch():
    rows = [
        _row(date="20260427", open_p=70_000),
        _row(date="20260426", open_p=69_000),
        _row(date="20260425", open_p=68_000),
    ]
    client = MagicMock()
    client.get_daily_chart = AsyncMock(return_value=_response(rows))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    cb = AsyncMock()
    builder.register_on_complete(cb)

    added = await builder.fetch_history(base_date="20260427")
    assert added == 3
    cb.assert_not_awaited()  # priming is silent
    history = builder.get_candles()
    assert len(history) == 3
    # Chronological order
    assert history[0].timestamp == datetime(2026, 4, 25, tzinfo=timezone.utc)
    assert history[-1].timestamp == datetime(2026, 4, 27, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_history_skips_already_cached():
    rows = [_row(date="20260427"), _row(date="20260426")]
    client = MagicMock()
    client.get_daily_chart = AsyncMock(return_value=_response(rows))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    await builder.fetch_history(base_date="20260427")
    second_added = await builder.fetch_history(base_date="20260427")
    assert second_added == 0  # all dates already seen


# ---------------------------------------------------------------------------
# get_candles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_candles_n_returns_last_n_chronological():
    rows = [
        _row(date="20260427"), _row(date="20260426"), _row(date="20260425"),
    ]
    client = MagicMock()
    client.get_daily_chart = AsyncMock(return_value=_response(rows))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    await builder.fetch_history(base_date="20260427")
    last_two = builder.get_candles(n=2)
    assert len(last_two) == 2
    assert last_two[0].timestamp.day == 26
    assert last_two[1].timestamp.day == 27


# ---------------------------------------------------------------------------
# Subscriber isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscriber_failure_does_not_block_others():
    client = MagicMock()
    client.get_daily_chart = AsyncMock(return_value=_response([_row()]))
    builder = V71DailyCandleBuilder("005930", kiwoom_client=client)
    bad = AsyncMock(side_effect=RuntimeError("boom"))
    good = AsyncMock()
    builder.register_on_complete(bad)
    builder.register_on_complete(good)
    await builder.fetch_eod(base_date="20260427")
    bad.assert_awaited_once()
    good.assert_awaited_once()
