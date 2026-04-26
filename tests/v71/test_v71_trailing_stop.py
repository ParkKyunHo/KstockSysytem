"""Unit tests for ``src/core/v71/exit/trailing_stop.py``.

Spec: 02_TRADING_RULES.md §5.5
"""

from __future__ import annotations

import os

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__EXIT_V71"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.exit.trailing_stop import V71TrailingStop  # noqa: E402
from src.core.v71.position.state import PositionState  # noqa: E402


def _position(
    *,
    avg: int = 100_000,
    qty: int = 100,
    profit_5: bool = False,
    profit_10: bool = False,
    ts_activated: bool = False,
    ts_base: int | None = None,
    ts_stop: int | None = None,
    ts_mult: float | None = None,
) -> PositionState:
    return PositionState(
        position_id="pos-1",
        stock_code="005930",
        tracked_stock_id="t1",
        triggered_box_id="b1",
        path_type="PATH_A",
        weighted_avg_price=avg,
        initial_avg_price=avg,
        total_quantity=qty,
        fixed_stop_price=int(avg * 0.95),
        profit_5_executed=profit_5,
        profit_10_executed=profit_10,
        ts_activated=ts_activated,
        ts_base_price=ts_base,
        ts_stop_price=ts_stop,
        ts_active_multiplier=ts_mult,
    )


class TestTrailingStopApplicator:
    def test_below_activation_does_not_mutate(self):
        ts = V71TrailingStop()
        pos = _position(avg=100_000)
        result = ts.on_bar_complete(pos, current_price=102_000, atr_value=1500)
        assert result.activate is False
        assert pos.ts_activated is False
        assert pos.ts_base_price is None

    def test_activates_at_5pct_and_writes_back(self):
        ts = V71TrailingStop()
        pos = _position(avg=100_000)
        result = ts.on_bar_complete(pos, current_price=105_000, atr_value=1500)
        assert result.activate is True
        assert pos.ts_activated is True
        assert pos.ts_base_price == 105_000
        # +5% -> tier 1 (4.0); 105_000 - 6_000 = 99_000
        assert pos.ts_stop_price == 99_000
        assert pos.ts_active_multiplier == 4.0

    def test_base_price_one_way_when_price_drops(self):
        ts = V71TrailingStop()
        pos = _position(
            avg=100_000,
            profit_5=True,
            ts_activated=True,
            ts_base=110_000,
            ts_stop=104_000,
            ts_mult=4.0,
        )
        ts.on_bar_complete(pos, current_price=108_000, atr_value=1500)
        assert pos.ts_base_price == 110_000  # not lowered

    def test_multiplier_tightens_then_locks(self):
        ts = V71TrailingStop()
        pos = _position(avg=100_000, profit_5=True)
        # First tick at +20% -> tier 3.0 selected (no current to widen from)
        ts.on_bar_complete(pos, current_price=120_000, atr_value=1500)
        assert pos.ts_active_multiplier == 3.0
        # Tick later at +18% -> would call for 3.0 still; locked anyway
        ts.on_bar_complete(pos, current_price=118_000, atr_value=1500)
        assert pos.ts_active_multiplier == 3.0
        # Surge to +45% -> tightens to 2.0
        ts.on_bar_complete(pos, current_price=145_000, atr_value=1500)
        assert pos.ts_active_multiplier == 2.0
        # Drop back to +30% -> would call for 2.5; LOCKED at 2.0 (no widen)
        ts.on_bar_complete(pos, current_price=130_000, atr_value=1500)
        assert pos.ts_active_multiplier == 2.0

    def test_atr_warmup_keeps_previous_stop(self):
        ts = V71TrailingStop()
        pos = _position(
            avg=100_000,
            profit_5=True,
            ts_activated=True,
            ts_base=110_000,
            ts_stop=104_000,
            ts_mult=4.0,
        )
        result = ts.on_bar_complete(pos, current_price=108_000, atr_value=0.0)
        assert result.activate is True
        assert pos.ts_stop_price == 104_000  # untouched
