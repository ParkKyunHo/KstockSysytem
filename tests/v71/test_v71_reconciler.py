"""Unit tests for ``src/core/v71/position/v71_reconciler.py``.

Spec: 02_TRADING_RULES.md §7 (Scenarios A/B/C/D + E)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    os.environ["V71_FF__V71__POSITION_V71"] = "true"
    os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
from src.core.v71.box.box_state_machine import BoxStatus  # noqa: E402
from src.core.v71.position.v71_position_manager import (  # noqa: E402
    V71PositionManager,
)
from src.core.v71.position.v71_reconciler import (  # noqa: E402
    ReconcilerContext,
    TrackedInfo,
    V71Reconciler,
)
from src.core.v71.skills.reconciliation_skill import (  # noqa: E402
    KiwoomBalance,
    ReconciliationCase,
)
from tests.v71.conftest import FakeBoxManager  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 28, 11, 0)
    )

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.now_value = self.now_value + timedelta(seconds=seconds)

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)

    async def notify(self, **kwargs) -> None:
        self.events.append(kwargs)


@dataclass
class FakeTrackedStore:
    """In-memory tracked_stocks store for tests."""

    items: dict[str, TrackedInfo] = field(default_factory=dict)
    end_calls: list[tuple[str, str]] = field(default_factory=list)

    def add(self, info: TrackedInfo) -> None:
        self.items[info.tracked_stock_id] = info

    def list_for_stock(self, stock_code: str) -> list[TrackedInfo]:
        return [
            t for t in self.items.values()
            if t.stock_code == stock_code and t.status != "EXITED"
        ]

    async def end(self, tracked_id: str, reason: str) -> None:
        self.end_calls.append((tracked_id, reason))
        if tracked_id in self.items:
            old = self.items[tracked_id]
            self.items[tracked_id] = TrackedInfo(
                tracked_stock_id=old.tracked_stock_id,
                stock_code=old.stock_code,
                path_type=old.path_type,
                status="EXITED",
            )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _build() -> tuple[
    V71Reconciler,
    V71PositionManager,
    V71BoxManager,
    FakeNotifier,
    FakeTrackedStore,
    FakeClock,
]:
    pm = V71PositionManager()
    bm = FakeBoxManager()
    notifier = FakeNotifier()
    clock = FakeClock()
    tracked = FakeTrackedStore()
    ctx = ReconcilerContext(
        position_manager=pm,
        box_manager=bm,
        notifier=notifier,
        clock=clock,
        list_tracked_for_stock=tracked.list_for_stock,
        end_tracking=tracked.end,
    )
    rec = V71Reconciler(context=ctx)
    return rec, pm, bm, notifier, tracked, clock


STOCK = "005930"
TRACKED_ID = "track-005930-A"


# ---------------------------------------------------------------------------
# Case E -- full match
# ---------------------------------------------------------------------------


class TestCaseE:
    @pytest.mark.asyncio
    async def test_full_match_no_op(self):
        rec, pm, bm, notifier, _, _ = _build()
        await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28),
        )
        results = await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=100, avg_price=18_000),
            ],
        )
        assert len(results) == 1
        assert results[0].case is ReconciliationCase.E_FULL_MATCH
        # No notification on E.
        assert notifier.events == []


# ---------------------------------------------------------------------------
# Case A -- system + user added
# ---------------------------------------------------------------------------


class TestCaseA:
    @pytest.mark.asyncio
    async def test_single_path_a_apply_buy_with_event_reset(self):
        rec, pm, _, notifier, _, _ = _build()
        pid = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        # Simulate +5% partial took place (so we can verify the reset).
        state = pm.get(pid)
        state.profit_5_executed = True
        state.fixed_stop_price = int(180_000 * 0.98)

        results = await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=150, avg_price=181_667),
            ],
        )
        assert results[0].case is ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY
        # Position state reflects pyramid buy + event reset.
        state = pm.get(pid)
        assert state.total_quantity == 150
        assert state.profit_5_executed is False  # RESET
        assert state.weighted_avg_price == round(
            (100 * 180_000 + 50 * 181_667) / 150
        )
        # MANUAL_PYRAMID_BUY event logged.
        events = pm.list_events(position_id=pid)
        assert any(e.event_type == "MANUAL_PYRAMID_BUY" for e in events)
        # HIGH alert.
        assert any(
            n["severity"] == "HIGH" and n["event_type"] == "MANUAL_PYRAMID_BUY"
            for n in notifier.events
        )

    @pytest.mark.asyncio
    async def test_dual_path_attributes_to_larger(self):
        rec, pm, _, _, _, _ = _build()
        pid_a = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        pid_b = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t2", triggered_box_id="b2",
            path_type="PATH_B", quantity=50, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        # Add 30 -> attributed to PATH_A (larger).
        await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=180, avg_price=181_000),
            ],
        )
        assert pm.get(pid_a).total_quantity == 130
        assert pm.get(pid_b).total_quantity == 50

    @pytest.mark.asyncio
    async def test_dual_path_tie_attributes_to_path_a(self):
        rec, pm, _, _, _, _ = _build()
        pid_a = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=50, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        pid_b = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t2", triggered_box_id="b2",
            path_type="PATH_B", quantity=50, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=120, avg_price=181_000),
            ],
        )
        # 20 added; tie -> PATH_A
        assert pm.get(pid_a).total_quantity == 70
        assert pm.get(pid_b).total_quantity == 50


# ---------------------------------------------------------------------------
# Case B -- system + user partial sold
# ---------------------------------------------------------------------------


class TestCaseB:
    @pytest.mark.asyncio
    async def test_single_path_a_qty_decreases(self):
        rec, pm, _, notifier, _, _ = _build()
        pid = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=50, avg_price=180_000),
            ],
        )
        state = pm.get(pid)
        assert state.total_quantity == 50
        assert state.weighted_avg_price == 180_000  # avg unchanged
        # MANUAL_SELL event.
        events = pm.list_events(position_id=pid)
        assert any(e.event_type == "MANUAL_SELL" for e in events)
        # HIGH alert MANUAL_PARTIAL_EXIT.
        assert any(
            n["event_type"] == "MANUAL_PARTIAL_EXIT" for n in notifier.events
        )

    @pytest.mark.asyncio
    async def test_manual_drained_first(self):
        """Single path + MANUAL: MANUAL drains first."""
        rec, pm, _, _, _, _ = _build()
        pid_sys = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        pid_manual = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="", triggered_box_id="",
            path_type="MANUAL", quantity=30, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        # Sold 50 -> MANUAL 30 fully drained, then PATH_A -20.
        await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=80, avg_price=180_000),
            ],
        )
        assert pm.get(pid_manual).total_quantity == 0
        assert pm.get(pid_manual).status == "CLOSED"
        assert pm.get(pid_sys).total_quantity == 80

    @pytest.mark.asyncio
    async def test_dual_path_proportional_split(self):
        """PRD §7.3 case 3: 100/100 holdings, sell 50 -> 25/25."""
        rec, pm, _, _, _, _ = _build()
        pid_a = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        pid_b = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t2", triggered_box_id="b2",
            path_type="PATH_B", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=150, avg_price=180_000),
            ],
        )
        assert pm.get(pid_a).total_quantity == 75
        assert pm.get(pid_b).total_quantity == 75

    @pytest.mark.asyncio
    async def test_full_sell_closes_positions(self):
        rec, pm, _, _, _, _ = _build()
        pid = await pm.add_position(
            stock_code=STOCK, tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await rec.reconcile(
            broker_balances=[],  # broker reports 0 -- user sold all
        )
        assert pm.get(pid).status == "CLOSED"
        assert pm.get(pid).total_quantity == 0


# ---------------------------------------------------------------------------
# Case C -- tracked but user bought
# ---------------------------------------------------------------------------


class TestCaseC:
    @pytest.mark.asyncio
    async def test_ends_tracking_invalidates_boxes_creates_manual(self):
        rec, pm, bm, notifier, tracked_store, _ = _build()
        # Tracked record with two WAITING boxes on PATH_A.
        tracked_store.add(TrackedInfo(
            tracked_stock_id=TRACKED_ID,
            stock_code=STOCK,
            path_type="PATH_A",
            status="BOX_SET",
        ))
        b1 = await bm.create_box(
            tracked_stock_id=TRACKED_ID,
            upper_price=74_000, lower_price=73_000,
            position_size_pct=10.0,
            strategy_type="PULLBACK", path_type="PATH_A",
        )
        b2 = await bm.create_box(
            tracked_stock_id=TRACKED_ID,
            upper_price=71_000, lower_price=70_000,
            position_size_pct=10.0,
            strategy_type="PULLBACK", path_type="PATH_A",
        )

        results = await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code=STOCK, quantity=50, avg_price=75_500),
            ],
        )
        assert results[0].case is ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY
        # end_tracking called.
        assert tracked_store.end_calls == [(TRACKED_ID, "MANUAL_BUY_DETECTED")]
        # Boxes INVALIDATED.
        assert (await bm.get(b1.id)).status is BoxStatus.INVALIDATED
        assert (await bm.get(b2.id)).status is BoxStatus.INVALIDATED
        # MANUAL position created.
        manuals = [p for p in pm.list_open() if p.path_type == "MANUAL"]
        assert len(manuals) == 1
        assert manuals[0].stock_code == STOCK
        assert manuals[0].weighted_avg_price == 75_500
        # HIGH alert.
        assert any(
            n["event_type"] == "MANUAL_BUY_TRACKED_TERMINATED"
            for n in notifier.events
        )


# ---------------------------------------------------------------------------
# Case D -- untracked + user bought
# ---------------------------------------------------------------------------


class TestCaseD:
    @pytest.mark.asyncio
    async def test_creates_manual_position_only(self):
        rec, pm, bm, notifier, _, _ = _build()
        # No tracked records, no system positions.
        results = await rec.reconcile(
            broker_balances=[
                KiwoomBalance(
                    stock_code="000660", quantity=100, avg_price=120_000
                ),
            ],
        )
        assert results[0].case is ReconciliationCase.D_UNTRACKED_MANUAL_BUY
        manuals = [p for p in pm.list_open() if p.path_type == "MANUAL"]
        assert len(manuals) == 1
        assert manuals[0].stock_code == "000660"
        assert manuals[0].weighted_avg_price == 120_000
        # HIGH alert.
        assert any(
            n["event_type"] == "MANUAL_BUY_UNTRACKED" for n in notifier.events
        )


# ---------------------------------------------------------------------------
# Multi-stock reconcile pass
# ---------------------------------------------------------------------------


class TestMultipleStocks:
    @pytest.mark.asyncio
    async def test_walks_all_stocks_on_either_side(self):
        rec, pm, _, _, tracked_store, _ = _build()
        # Stock A: full match (E)
        await pm.add_position(
            stock_code="005930", tracked_stock_id="ta",
            triggered_box_id="ba", path_type="PATH_A",
            quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28),
        )
        # Stock B: untracked manual buy (D) -- only on broker side
        # Stock C: system + manual sell (B)
        await pm.add_position(
            stock_code="000660", tracked_stock_id="tc",
            triggered_box_id="bc", path_type="PATH_A",
            quantity=50, weighted_avg_price=120_000,
            opened_at=datetime(2026, 4, 28),
        )

        results = await rec.reconcile(
            broker_balances=[
                KiwoomBalance(stock_code="005930", quantity=100, avg_price=18_000),
                KiwoomBalance(stock_code="035420", quantity=20, avg_price=200_000),
                KiwoomBalance(stock_code="000660", quantity=20, avg_price=120_000),
            ],
        )
        cases = {r.stock_code: r.case for r in results}
        assert cases["005930"] is ReconciliationCase.E_FULL_MATCH
        assert cases["035420"] is ReconciliationCase.D_UNTRACKED_MANUAL_BUY
        assert cases["000660"] is ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_runtime_error_when_disabled(self):
        os.environ["V71_FF__V71__RECONCILIATION_V71"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.reconciliation_v71"):
                pm = V71PositionManager()
                bm = FakeBoxManager()
                ctx = ReconcilerContext(
                    position_manager=pm, box_manager=bm,
                    notifier=FakeNotifier(), clock=FakeClock(),
                    list_tracked_for_stock=lambda _: [],
                    end_tracking=lambda *_: None,  # type: ignore[arg-type]
                )
                V71Reconciler(context=ctx)
        finally:
            os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
            ff.reload()
