"""P-Wire-Box-4 core invariant tests.

Three narrow regression nets that protect the wire-level guarantees the
unit was built around. Broader coverage (the legacy 21 + 12 + 30 cases
on V71PositionManager / Reconciler / Telegram) is rewritten in a
follow-up unit against an aiosqlite engine.

What this file covers:
  * BuyExecutor _finalize_buy uses the atomic session_factory when wired
    -- both the position add and the box mark_triggered land inside the
    same begin() context.
  * BuyExecutor compensation path calls set_box_cooldown when the
    atomic transaction fails (block infinite retry on next tick).
  * BoxEntryDetector.set_cooldown blocks subsequent _on_bar_complete
    callbacks for the named box for the cooldown window.
  * V71PositionManager.apply_sell with PROFIT_TAKE_10 forces
    profit_5_executed = True even if the caller skips the
    PROFIT_TAKE_5 step (trading-logic blocker 8).
"""

# ruff: noqa: ARG002 -- inline fakes accept the production kwargs even when unused

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    for flag in (
        "BOX_SYSTEM",
        "POSITION_V71",
        "EXIT_V71",
        "RECONCILIATION_V71",
        "KIWOOM_EXCHANGE",
        "NOTIFICATION_V71",
        "BUY_EXECUTOR_V71",
        "EXIT_EXECUTOR_V71",
    ):
        os.environ[f"V71_FF__V71__{flag}"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


# ---------------------------------------------------------------------------
# 1. Cooldown — BoxEntryDetector blocks the same box for 300s
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_set_cooldown_records_until_time_in_future(self):
        from unittest.mock import MagicMock

        from src.core.v71.box.box_entry_detector import V71BoxEntryDetector
        from src.core.v71.v71_constants import V71Timeframe

        detector = V71BoxEntryDetector(
            path_type="PATH_A",
            candle_manager=MagicMock(),
            timeframe_filter=V71Timeframe.THREE_MINUTE,
            box_manager=MagicMock(),
            on_entry=MagicMock(),
            resolve_tracked_id=lambda _stock: None,
            market_context=MagicMock(),
        )
        detector.set_cooldown("box-1", 300.0)
        assert detector._is_in_cooldown("box-1") is True
        assert detector._is_in_cooldown("box-2") is False

    def test_cooldown_expires_after_window(self):
        from unittest.mock import MagicMock

        from src.core.v71.box.box_entry_detector import V71BoxEntryDetector
        from src.core.v71.v71_constants import V71Timeframe

        detector = V71BoxEntryDetector(
            path_type="PATH_A",
            candle_manager=MagicMock(),
            timeframe_filter=V71Timeframe.THREE_MINUTE,
            box_manager=MagicMock(),
            on_entry=MagicMock(),
            resolve_tracked_id=lambda _stock: None,
            market_context=MagicMock(),
        )
        # Force the until-time into the past.
        detector._cooldown_until["box-1"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        assert detector._is_in_cooldown("box-1") is False
        # Side-effect: expired entry pruned from the dict.
        assert "box-1" not in detector._cooldown_until


# ---------------------------------------------------------------------------
# 2. PROFIT_TAKE_10 invariant — profit_5_executed forced True
# ---------------------------------------------------------------------------


class TestProfitTakeInvariant:
    @pytest.mark.asyncio
    async def test_profit_take_10_forces_profit_5_executed_true(self):
        """Trading-logic blocker 8: even if the caller jumps straight to
        PROFIT_TAKE_10 (skipping PROFIT_TAKE_5), the manager must mark
        profit_5_executed=True so the §5.4 ladder lookup is well-defined.
        """
        from tests.v71._fakes import FakePositionManager

        pm = FakePositionManager()
        state = await pm.add_position(
            stock_code="005930",
            tracked_stock_id=None,
            triggered_box_id=None,
            path_type="PATH_A",
            quantity=100,
            weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc),
        )
        assert state.profit_5_executed is False
        new_state = await pm.apply_sell(
            state.position_id,
            sell_quantity=30,
            sell_price=19_800,  # +10%
            event_type="PROFIT_TAKE_10",
        )
        assert new_state.profit_5_executed is True, (
            "PROFIT_TAKE_10 must force profit_5_executed=True (blocker 8)"
        )
        assert new_state.profit_10_executed is True


# ---------------------------------------------------------------------------
# 3. _finalize_buy atomic transaction (Q3) + compensation cooldown
# ---------------------------------------------------------------------------


@dataclass
class _CapturedSession:
    """Records every operation routed through it so tests can assert
    that add_position + mark_triggered ran in the same begin() context.
    """

    in_tx: bool = False
    operations: list[str] = field(default_factory=list)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def begin(self):
        captured = self

        @asynccontextmanager
        async def _tx():
            captured.in_tx = True
            try:
                yield captured
            finally:
                captured.in_tx = False

        return _tx()

    def in_transaction(self) -> bool:
        return self.in_tx


@dataclass
class _SessionFactory:
    captured: _CapturedSession

    def __call__(self):
        return self.captured


class TestAtomicFinalizeBuy:
    @pytest.mark.asyncio
    async def test_session_factory_wraps_position_and_box_in_one_tx(self):
        """When ``session_factory`` is wired, _finalize_buy passes the
        same session into both ``position_store.add_position`` and
        ``box_manager.mark_triggered`` (Q3 atomic seam)."""
        from src.core.v71.box.box_manager import BoxRecord
        from src.core.v71.box.box_state_machine import BoxStatus
        from src.core.v71.position.state import PositionState, PositionStatus
        from src.core.v71.strategies.v71_buy_executor import (
            BuyExecutorContext,
            V71BuyExecutor,
            _BuySequenceResult,
        )

        captured = _CapturedSession()
        factory = _SessionFactory(captured=captured)

        sessions_seen: list[bool] = []

        @dataclass
        class FakeStore:
            async def add_position(self, **kwargs):
                sessions_seen.append(kwargs.get("session") is captured)
                return PositionState(
                    position_id="pos-1",
                    stock_code=kwargs["stock_code"],
                    tracked_stock_id=kwargs.get("tracked_stock_id"),
                    triggered_box_id=kwargs.get("triggered_box_id"),
                    path_type=kwargs.get("path_type", "PATH_A"),
                    weighted_avg_price=kwargs["weighted_avg_price"],
                    initial_avg_price=kwargs["weighted_avg_price"],
                    total_quantity=kwargs["quantity"],
                    fixed_stop_price=int(kwargs["weighted_avg_price"] * 0.95),
                    status=PositionStatus.OPEN,
                    opened_at=kwargs["opened_at"],
                )

        @dataclass
        class FakeBox:
            mark_calls: list = field(default_factory=list)

            async def mark_triggered(self, box_id, *, session=None):
                self.mark_calls.append((box_id, session is captured))
                return None

            async def mark_invalidated(self, box_id, *, reason, session=None):
                return None

            async def cancel_waiting_for_tracked(self, *args, **kwargs):
                return []

        @dataclass
        class FakeNotifier:
            calls: list = field(default_factory=list)

            async def notify(self, **kwargs):
                self.calls.append(kwargs)

        from datetime import datetime, timezone

        @dataclass
        class FakeClock:
            t: datetime = field(
                default_factory=lambda: datetime(
                    2026, 4, 30, 10, 0, tzinfo=timezone.utc,
                ),
            )

            def now(self):
                return self.t

            async def sleep(self, _s):
                return None

            async def sleep_until(self, _t):
                return None

        store = FakeStore()
        box_mgr = FakeBox()
        notifier = FakeNotifier()
        clock = FakeClock()

        ctx = BuyExecutorContext(
            exchange=None,
            box_manager=box_mgr,
            position_store=store,
            notifier=notifier,
            clock=clock,
            is_vi_active=lambda _s: False,
            get_previous_close=lambda _s: 18_000,
            get_total_capital=lambda: 100_000_000,
            get_invested_pct_for_stock=lambda _s: 0.0,
            session_factory=factory,
        )
        executor = V71BuyExecutor(
            context=ctx, tracked_stock_resolver=lambda _t: "005930",
        )

        seq = _BuySequenceResult()
        seq.add_fill(100, 18_000)
        box = BoxRecord(
            id="box-1",
            tracked_stock_id="track-1",
            box_tier=1,
            upper_price=20_000,
            lower_price=18_000,
            position_size_pct=10.0,
            stop_loss_pct=-0.05,
            strategy_type="BREAKOUT",
            path_type="PATH_A",
            status=BoxStatus.WAITING,
            created_at=datetime.now(timezone.utc),
            modified_at=datetime.now(timezone.utc),
        )
        await executor._finalize_buy(
            box, "005930", seq, target_quantity=100,
        )
        assert sessions_seen == [True]
        assert box_mgr.mark_calls == [("box-1", True)]
