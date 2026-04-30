"""Unit tests for thin strategy wrappers (P-Wire-Box-1 mock-refresh).

Spec:
  - 02_TRADING_RULES.md §3.2 / §3.10 / §3.11
  - 04_ARCHITECTURE.md §5.3
  - 05_MIGRATION_PLAN.md §5.3

P-Wire-Box-1: V71BoxManager became async + DB-backed; the strategy
wrappers now ``await`` it. These tests verify the wrapper still pins
the right ``strategy_type`` (PULLBACK / BREAKOUT) without exercising
the box manager's DB layer (covered in tests/v71/box/).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

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
from src.core.v71.box.box_record import BoxRecord  # noqa: E402
from src.core.v71.box.box_state_machine import BoxStatus  # noqa: E402
from src.core.v71.strategies.v71_box_breakout import (  # noqa: E402
    V71BoxBreakoutStrategy,
)
from src.core.v71.strategies.v71_box_pullback import (  # noqa: E402
    V71BoxPullbackStrategy,
)
from src.database.models_v71 import PathType, StrategyType  # noqa: E402

TRACKED = "tracked-001"


def _stub_record(*, strategy: StrategyType, path: PathType) -> BoxRecord:
    return BoxRecord(
        id="b1",
        tracked_stock_id=TRACKED,
        box_tier=1,
        upper_price=100,
        lower_price=90,
        position_size_pct=10.0,
        stop_loss_pct=-0.05,
        strategy_type=strategy,
        path_type=path,
        status=BoxStatus.WAITING,
    )


def _mock_box_manager(record: BoxRecord) -> AsyncMock:
    bm = AsyncMock(spec=V71BoxManager)
    bm.create_box.return_value = record
    return bm


# ---------------------------------------------------------------------------
# V71BoxPullbackStrategy
# ---------------------------------------------------------------------------


class TestPullbackStrategy:
    @pytest.mark.asyncio
    async def test_create_box_pins_strategy_pullback(self):
        bm = _mock_box_manager(
            _stub_record(strategy=StrategyType.PULLBACK, path=PathType.PATH_A),
        )
        strat = V71BoxPullbackStrategy(box_manager=bm)
        rec = await strat.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            path_type="PATH_A",
        )
        assert rec.strategy_type == StrategyType.PULLBACK
        assert rec.path_type == PathType.PATH_A
        bm.create_box.assert_awaited_once()
        kwargs = bm.create_box.await_args.kwargs
        assert kwargs["strategy_type"] == "PULLBACK"
        assert kwargs["path_type"] == "PATH_A"

    @pytest.mark.asyncio
    async def test_create_box_path_b_too(self):
        bm = _mock_box_manager(
            _stub_record(strategy=StrategyType.PULLBACK, path=PathType.PATH_B),
        )
        strat = V71BoxPullbackStrategy(box_manager=bm)
        rec = await strat.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            path_type="PATH_B",
        )
        assert rec.strategy_type == StrategyType.PULLBACK
        assert rec.path_type == PathType.PATH_B

    def test_flag_disabled_blocks_init(self):
        os.environ["V71_FF__V71__PULLBACK_STRATEGY"] = "false"
        ff.reload()
        try:
            bm = AsyncMock(spec=V71BoxManager)
            with pytest.raises(RuntimeError, match="v71.pullback_strategy"):
                V71BoxPullbackStrategy(box_manager=bm)
        finally:
            os.environ["V71_FF__V71__PULLBACK_STRATEGY"] = "true"
            ff.reload()


# ---------------------------------------------------------------------------
# V71BoxBreakoutStrategy
# ---------------------------------------------------------------------------


class TestBreakoutStrategy:
    @pytest.mark.asyncio
    async def test_create_box_pins_strategy_breakout(self):
        bm = _mock_box_manager(
            _stub_record(strategy=StrategyType.BREAKOUT, path=PathType.PATH_A),
        )
        strat = V71BoxBreakoutStrategy(box_manager=bm)
        rec = await strat.create_box(
            tracked_stock_id=TRACKED,
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            path_type="PATH_A",
        )
        assert rec.strategy_type == StrategyType.BREAKOUT
        assert rec.path_type == PathType.PATH_A
        kwargs = bm.create_box.await_args.kwargs
        assert kwargs["strategy_type"] == "BREAKOUT"

    def test_flag_disabled_blocks_init(self):
        os.environ["V71_FF__V71__BREAKOUT_STRATEGY"] = "false"
        ff.reload()
        try:
            bm = AsyncMock(spec=V71BoxManager)
            with pytest.raises(RuntimeError, match="v71.breakout_strategy"):
                V71BoxBreakoutStrategy(box_manager=bm)
        finally:
            os.environ["V71_FF__V71__BREAKOUT_STRATEGY"] = "true"
            ff.reload()
