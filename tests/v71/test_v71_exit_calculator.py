"""Unit tests for ``src/core/v71/exit/exit_calculator.py``.

Spec: 02_TRADING_RULES.md §5
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


from src.core.v71.exit.exit_calculator import V71ExitCalculator  # noqa: E402
from src.core.v71.position.state import PositionState  # noqa: E402


def _pos(
    *,
    avg: int = 100_000,
    qty: int = 100,
    fixed_stop: int = 95_000,
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
        fixed_stop_price=fixed_stop,
        profit_5_executed=profit_5,
        profit_10_executed=profit_10,
        ts_activated=ts_activated,
        ts_base_price=ts_base,
        ts_stop_price=ts_stop,
        ts_active_multiplier=ts_mult,
    )


class TestOnTick:
    def test_no_signals_below_5pct(self):
        calc = V71ExitCalculator()
        pos = _pos(avg=100_000, fixed_stop=95_000)
        decision = calc.on_tick(pos, current_price=103_000, atr_value=1500)
        assert decision.stop_triggered is False
        assert decision.profit_take.should_exit is False
        assert decision.effective_stop.source == "FIXED"

    def test_stop_triggered_at_neg_5pct(self):
        calc = V71ExitCalculator()
        pos = _pos(avg=100_000, fixed_stop=95_000)
        decision = calc.on_tick(pos, current_price=95_000, atr_value=1500)
        assert decision.stop_triggered is True

    def test_profit_5_signal_at_5pct(self):
        calc = V71ExitCalculator()
        pos = _pos(avg=100_000, qty=100, fixed_stop=95_000)
        decision = calc.on_tick(pos, current_price=105_000, atr_value=1500)
        assert decision.stop_triggered is False
        assert decision.profit_take.should_exit is True
        assert decision.profit_take.level == "PROFIT_5"
        assert decision.profit_take.quantity_to_sell == 30

    def test_profit_10_signal_after_5_executed(self):
        calc = V71ExitCalculator()
        pos = _pos(
            avg=100_000, qty=70, fixed_stop=98_000, profit_5=True
        )
        decision = calc.on_tick(pos, current_price=110_000, atr_value=1500)
        assert decision.profit_take.level == "PROFIT_10"

    def test_ts_binding_only_after_profit_10(self):
        calc = V71ExitCalculator()
        # +12%, +5 only executed -- TS not yet binding
        pos = _pos(
            avg=100_000,
            qty=70,
            fixed_stop=98_000,
            profit_5=True,
            ts_activated=True,
            ts_base=112_000,
            ts_stop=108_000,
            ts_mult=4.0,
        )
        decision = calc.on_tick(pos, current_price=109_000, atr_value=1500)
        # TS would have triggered if binding, but +5 stage means fixed only.
        assert decision.stop_triggered is False
        assert decision.effective_stop.source == "FIXED"

    def test_ts_triggers_after_profit_10(self):
        calc = V71ExitCalculator()
        pos = _pos(
            avg=100_000,
            qty=49,
            fixed_stop=104_000,
            profit_5=True,
            profit_10=True,
            ts_activated=True,
            ts_base=120_000,
            ts_stop=115_000,
            ts_mult=3.0,
        )
        # current 115_000 -> exactly TS line -> triggered (TS source)
        decision = calc.on_tick(pos, current_price=115_000, atr_value=1500)
        assert decision.stop_triggered is True
        assert decision.effective_stop.source == "TS"
