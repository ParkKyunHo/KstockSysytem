"""Unit tests for src/core/v71/candle/types.py (Step A-1)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core.v71.candle.types import V71Candle, V71Tick, message_to_tick
from src.core.v71.v71_constants import V71Timeframe

# ---------------------------------------------------------------------------
# Tick / Candle frozen
# ---------------------------------------------------------------------------


def test_tick_is_frozen():
    tick = V71Tick(
        stock_code="005930",
        timestamp=datetime.now(timezone.utc),
        price=70_000,
        volume=10,
        side="BUY",
    )
    with pytest.raises((AttributeError, TypeError)):
        tick.price = 80_000  # type: ignore[misc]


def test_candle_is_frozen_and_carries_tick_count():
    candle = V71Candle(
        stock_code="005930",
        timeframe=V71Timeframe.THREE_MINUTE,
        timestamp=datetime.now(timezone.utc),
        open=70_000,
        high=71_000,
        low=69_500,
        close=70_500,
        volume=1_000,
        tick_count=42,
    )
    assert candle.tick_count == 42
    with pytest.raises((AttributeError, TypeError)):
        candle.close = 99  # type: ignore[misc]


def test_timeframe_enum_values():
    assert V71Timeframe.THREE_MINUTE.value == "3m"
    assert V71Timeframe.DAILY.value == "1d"


# ---------------------------------------------------------------------------
# message_to_tick
# ---------------------------------------------------------------------------


def _msg(item, values, received_at=None):
    return SimpleNamespace(
        item=item,
        values=values,
        received_at=received_at or datetime.now(timezone.utc),
    )


def test_message_to_tick_happy_path_with_alias_10():
    tick = message_to_tick(_msg(
        "005930",
        {"10": "70500", "15": "100", "12": "+150"},
    ))
    assert tick is not None
    assert tick.stock_code == "005930"
    assert tick.price == 70_500
    assert tick.volume == 100
    assert tick.side == "BUY"


def test_message_to_tick_alternative_aliases():
    tick = message_to_tick(_msg(
        "005930",
        {"stck_prpr": "70500", "trde_qty": "10"},
    ))
    assert tick is not None
    assert tick.price == 70_500
    assert tick.volume == 10


def test_message_to_tick_zero_padded_price():
    tick = message_to_tick(_msg(
        "005930",
        {"10": "0000070500", "15": "0000000010"},
    ))
    assert tick.price == 70_500
    assert tick.volume == 10


def test_message_to_tick_sell_side():
    tick = message_to_tick(_msg(
        "005930",
        {"10": "70500", "12": "-100"},
    ))
    assert tick.side == "SELL"


def test_message_to_tick_unknown_side_returns_blank():
    tick = message_to_tick(_msg(
        "005930",
        {"10": "70500", "12": "?"},
    ))
    assert tick.side == ""


def test_message_to_tick_missing_price_returns_none(caplog):
    with caplog.at_level("WARNING"):
        result = message_to_tick(_msg("005930", {"15": "100"}))
    assert result is None
    assert any("price field missing" in r.message for r in caplog.records)


def test_message_to_tick_zero_price_returns_none(caplog):
    with caplog.at_level("WARNING"):
        result = message_to_tick(_msg("005930", {"10": "0"}))
    assert result is None
    assert any("price <= 0" in r.message for r in caplog.records)


def test_message_to_tick_empty_stock_code_returns_none(caplog):
    with caplog.at_level("WARNING"):
        result = message_to_tick(_msg("", {"10": "70000"}))
    assert result is None
    assert any("empty stock_code" in r.message for r in caplog.records)


def test_message_to_tick_unparseable_price_returns_none(caplog):
    with caplog.at_level("WARNING"):
        result = message_to_tick(_msg("005930", {"10": "abc"}))
    # _coerce_int returns 0 for unparseable -> price <= 0 path
    assert result is None


def test_message_to_tick_values_not_dict_returns_none(caplog):
    with caplog.at_level("WARNING"):
        result = message_to_tick(_msg("005930", "not_a_dict"))
    assert result is None
    assert any("values not dict" in r.message for r in caplog.records)


def test_message_to_tick_uppercases_stock_code():
    tick = message_to_tick(_msg("a005930", {"10": "70000"}))
    assert tick.stock_code == "A005930"
