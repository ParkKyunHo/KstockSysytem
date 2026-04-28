"""Unit tests for V71ThreeMinuteCandleBuilder (Step A-2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.core.v71.candle.types import V71Candle, V71Tick
from src.core.v71.candle.v71_candle_builder import V71BaseCandleBuilder
from src.core.v71.candle.v71_three_minute_builder import (
    V71ThreeMinuteCandleBuilder,
)
from src.core.v71.v71_constants import V71Timeframe


def _tick(stock_code, ts, price, volume=10, side="BUY"):
    return V71Tick(
        stock_code=stock_code,
        timestamp=ts,
        price=price,
        volume=volume,
        side=side,
    )


def _ts(year=2026, month=4, day=28, hour=9, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_three_minute_builder_satisfies_protocol():
    builder = V71ThreeMinuteCandleBuilder("005930")
    assert isinstance(builder, V71BaseCandleBuilder)
    assert builder.stock_code == "005930"
    assert builder.timeframe == V71Timeframe.THREE_MINUTE


# ---------------------------------------------------------------------------
# Bucket boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "minute,expected_minute",
    [
        (0, 0), (1, 0), (2, 0),
        (3, 3), (4, 3), (5, 3),
        (27, 27), (28, 27), (29, 27),
    ],
)
def test_bucket_window_floors_to_3_minute(minute, expected_minute):
    ts = _ts(minute=minute, second=30)
    start, end = V71ThreeMinuteCandleBuilder.bucket_window(ts)
    assert start.minute == expected_minute
    assert (end - start).total_seconds() == 180


# ---------------------------------------------------------------------------
# Tick aggregation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_tick_starts_bucket_no_emit():
    builder = V71ThreeMinuteCandleBuilder("005930")
    cb = AsyncMock()
    builder.register_on_complete(cb)
    await builder.on_tick(_tick("005930", _ts(minute=0, second=15), 70_000))
    assert builder.get_candles() == ()
    cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_ticks_in_same_bucket_aggregate_ohlcv():
    builder = V71ThreeMinuteCandleBuilder("005930")
    cb = AsyncMock()
    builder.register_on_complete(cb)
    # All within [09:00, 09:03)
    await builder.on_tick(_tick("005930", _ts(minute=0, second=10), 70_000))
    await builder.on_tick(_tick("005930", _ts(minute=1, second=20), 71_000))
    await builder.on_tick(_tick("005930", _ts(minute=2, second=30), 70_500, volume=5))
    assert builder.get_candles() == ()  # not yet emitted
    cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_tick_in_next_bucket_emits_previous():
    builder = V71ThreeMinuteCandleBuilder("005930")
    cb = AsyncMock()
    builder.register_on_complete(cb)
    # Bucket 1 [09:00, 09:03): 3 ticks
    await builder.on_tick(_tick("005930", _ts(minute=0), 70_000, volume=10))
    await builder.on_tick(_tick("005930", _ts(minute=1), 71_000, volume=20))
    await builder.on_tick(_tick("005930", _ts(minute=2), 69_500, volume=15))
    # Bucket 2 [09:03, ...): triggers emit of bucket 1
    await builder.on_tick(_tick("005930", _ts(minute=3), 70_000, volume=5))
    history = builder.get_candles()
    assert len(history) == 1
    candle = history[0]
    assert isinstance(candle, V71Candle)
    assert candle.timestamp == _ts(minute=0)
    assert candle.open == 70_000
    assert candle.high == 71_000
    assert candle.low == 69_500
    assert candle.close == 69_500
    assert candle.volume == 45
    assert candle.tick_count == 3
    cb.assert_awaited_once_with(candle)


@pytest.mark.asyncio
async def test_get_candles_n_returns_last_n():
    builder = V71ThreeMinuteCandleBuilder("005930")
    base = _ts(minute=0)
    # Emit 5 candles via bucket transitions
    for i in range(6):
        ts = base + timedelta(minutes=3 * i)
        await builder.on_tick(_tick("005930", ts, 70_000 + i, volume=10))
    history = builder.get_candles(n=2)
    assert len(history) == 2
    # Last 2 of 5 emitted (sixth bucket still open)
    assert history[0].open == 70_003
    assert history[1].open == 70_004


@pytest.mark.asyncio
async def test_history_max_caps_deque():
    builder = V71ThreeMinuteCandleBuilder("005930", history_max=3)
    base = _ts(minute=0)
    # 6 transitions → 5 emitted, but maxlen=3
    for i in range(6):
        ts = base + timedelta(minutes=3 * i)
        await builder.on_tick(_tick("005930", ts, 70_000 + i))
    history = builder.get_candles()
    assert len(history) == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_code_mismatch_warns_and_skips(caplog):
    builder = V71ThreeMinuteCandleBuilder("005930")
    with caplog.at_level("WARNING"):
        await builder.on_tick(_tick("000660", _ts(minute=0), 50_000))
    assert builder.get_candles() == ()
    assert any("stock_code mismatch" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_out_of_order_tick_dropped(caplog):
    builder = V71ThreeMinuteCandleBuilder("005930")
    # Start in bucket [09:03, 09:06)
    await builder.on_tick(_tick("005930", _ts(minute=3), 70_000))
    # Out-of-order tick from earlier bucket [09:00, 09:03)
    with caplog.at_level("WARNING"):
        await builder.on_tick(_tick("005930", _ts(minute=1), 65_000))
    assert builder.get_candles() == ()  # dropped, no emission
    assert any("out-of-order tick" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_flush_emits_in_progress_bucket():
    builder = V71ThreeMinuteCandleBuilder("005930")
    cb = AsyncMock()
    builder.register_on_complete(cb)
    await builder.on_tick(_tick("005930", _ts(minute=0), 70_000))
    await builder.on_tick(_tick("005930", _ts(minute=1), 71_000))
    candle = await builder.flush()
    assert candle is not None
    assert candle.open == 70_000
    assert candle.close == 71_000
    cb.assert_awaited_once_with(candle)
    # Idempotent
    second = await builder.flush()
    assert second is None


@pytest.mark.asyncio
async def test_subscriber_failure_does_not_block_others():
    builder = V71ThreeMinuteCandleBuilder("005930")
    bad = AsyncMock(side_effect=RuntimeError("boom"))
    good = AsyncMock()
    builder.register_on_complete(bad)
    builder.register_on_complete(good)
    await builder.on_tick(_tick("005930", _ts(minute=0), 70_000))
    await builder.on_tick(_tick("005930", _ts(minute=3), 71_000))
    bad.assert_awaited_once()
    good.assert_awaited_once()
