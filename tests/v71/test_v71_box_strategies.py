"""Unit tests for thin strategy wrappers.

Spec:
  - 02_TRADING_RULES.md §3.2 / §3.10 / §3.11
  - 04_ARCHITECTURE.md §5.3
  - 05_MIGRATION_PLAN.md §5.3
"""

from __future__ import annotations

import os

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_v71_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    os.environ["V71_FF__V71__PULLBACK_STRATEGY"] = "true"
    os.environ["V71_FF__V71__BREAKOUT_STRATEGY"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
from src.core.v71.strategies.v71_box_breakout import (  # noqa: E402
    V71BoxBreakoutStrategy,
)
from src.core.v71.strategies.v71_box_pullback import (  # noqa: E402
    V71BoxPullbackStrategy,
)

TRACKED = "tracked-001"


# ---------------------------------------------------------------------------
# V71BoxPullbackStrategy
# ---------------------------------------------------------------------------


class TestPullbackStrategy:
    def test_create_box_pins_strategy_pullback(self):
        bm = V71BoxManager()
        strat = V71BoxPullbackStrategy(box_manager=bm)
        rec = strat.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            path_type="PATH_A",
        )
        assert rec.strategy_type == "PULLBACK"
        assert rec.path_type == "PATH_A"

    def test_create_box_path_b_too(self):
        bm = V71BoxManager()
        strat = V71BoxPullbackStrategy(box_manager=bm)
        rec = strat.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            path_type="PATH_B",
        )
        assert rec.strategy_type == "PULLBACK"
        assert rec.path_type == "PATH_B"

    def test_flag_disabled_blocks_init(self):
        os.environ["V71_FF__V71__PULLBACK_STRATEGY"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.pullback_strategy"):
                V71BoxPullbackStrategy(box_manager=V71BoxManager())
        finally:
            os.environ["V71_FF__V71__PULLBACK_STRATEGY"] = "true"
            ff.reload()


# ---------------------------------------------------------------------------
# V71BoxBreakoutStrategy
# ---------------------------------------------------------------------------


class TestBreakoutStrategy:
    def test_create_box_pins_strategy_breakout(self):
        bm = V71BoxManager()
        strat = V71BoxBreakoutStrategy(box_manager=bm)
        rec = strat.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            path_type="PATH_A",
        )
        assert rec.strategy_type == "BREAKOUT"
        assert rec.path_type == "PATH_A"

    def test_flag_disabled_blocks_init(self):
        os.environ["V71_FF__V71__BREAKOUT_STRATEGY"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.breakout_strategy"):
                V71BoxBreakoutStrategy(box_manager=V71BoxManager())
        finally:
            os.environ["V71_FF__V71__BREAKOUT_STRATEGY"] = "true"
            ff.reload()
