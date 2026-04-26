"""Unit tests for ``src/core/v71/exit/exit_executor.py``.

Spec:
  - 02_TRADING_RULES.md §5.1 (stop loss)
  - 02_TRADING_RULES.md §5.2 / §5.3 (partial profit-take)
  - 02_TRADING_RULES.md §5.5 (TS exit)
  - 02_TRADING_RULES.md §5.9 (post-exit state machine)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    os.environ["V71_FF__V71__EXIT_V71"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
from src.core.v71.box.box_state_machine import BoxStatus  # noqa: E402
from src.core.v71.exit.exit_executor import (  # noqa: E402
    ExitExecutorContext,
    ExitOutcomeStatus,
    V71ExitExecutor,
)
from src.core.v71.position.state import PositionState  # noqa: E402
from src.core.v71.skills.exit_calc_skill import ProfitTakeResult  # noqa: E402
from src.core.v71.skills.kiwoom_api_skill import (  # noqa: E402
    KiwoomAPIError,
    OrderRejectedError,
    V71Orderbook,
    V71OrderResult,
    V71OrderSide,
    V71OrderStatus,
    V71OrderType,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 28, 11, 0)
    )
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_value = self.now_value + timedelta(seconds=seconds)

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)

    async def notify(self, **kwargs) -> None:
        self.events.append(kwargs)


class FakeExchange:
    def __init__(
        self,
        *,
        bid_1: int = 110_000,
        ask_1: int = 110_100,
        last_price: int = 110_050,
    ) -> None:
        self.bid_1 = bid_1
        self.ask_1 = ask_1
        self.last_price = last_price
        self.orders_sent: list[dict] = []
        self.cancellations: list[str] = []
        self._next_id = 1
        self.status_sequence: dict[str, list[V71OrderStatus]] = {}
        self.fail_send: Exception | None = None
        self.default_full_fill = True

    async def get_orderbook(self, stock_code: str) -> V71Orderbook:
        return V71Orderbook(
            stock_code=stock_code,
            bid_1=self.bid_1,
            ask_1=self.ask_1,
            last_price=self.last_price,
        )

    async def get_current_price(self, stock_code: str) -> int:  # noqa: ARG002
        return self.last_price

    async def send_order(
        self,
        *,
        stock_code: str,
        side: V71OrderSide,
        quantity: int,
        price: int,
        order_type: V71OrderType,
    ) -> V71OrderResult:
        if self.fail_send is not None:
            raise self.fail_send
        order_id = f"ord-{self._next_id}"
        self._next_id += 1
        self.orders_sent.append(
            {
                "order_id": order_id,
                "stock_code": stock_code,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
            }
        )
        if order_id not in self.status_sequence:
            fill_price = price if price > 0 else self.last_price
            if self.default_full_fill:
                self.status_sequence[order_id] = [
                    V71OrderStatus(
                        order_id=order_id,
                        stock_code=stock_code,
                        requested_quantity=quantity,
                        filled_quantity=quantity,
                        avg_fill_price=fill_price,
                        is_open=False,
                        is_cancelled=False,
                    )
                ]
            else:
                self.status_sequence[order_id] = [
                    V71OrderStatus(
                        order_id=order_id,
                        stock_code=stock_code,
                        requested_quantity=quantity,
                        filled_quantity=0,
                        avg_fill_price=0,
                        is_open=True,
                        is_cancelled=False,
                    )
                ]
        return V71OrderResult(
            order_id=order_id,
            stock_code=stock_code,
            side=side,
            order_type=order_type,
            requested_quantity=quantity,
            requested_price=price,
        )

    async def cancel_order(
        self, *, order_id: str, stock_code: str
    ) -> V71OrderResult:
        self.cancellations.append(order_id)
        return V71OrderResult(
            order_id=order_id,
            stock_code=stock_code,
            side=V71OrderSide.SELL,
            order_type=V71OrderType.LIMIT,
            requested_quantity=0,
            requested_price=0,
        )

    async def get_order_status(self, order_id: str) -> V71OrderStatus:
        seq = self.status_sequence.get(order_id)
        if not seq:
            raise AssertionError(f"No status pre-loaded for {order_id}")
        return seq.pop(0) if len(seq) > 1 else seq[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _position(
    *,
    avg: int = 100_000,
    qty: int = 100,
    fixed_stop: int = 95_000,
    profit_5: bool = False,
    profit_10: bool = False,
    status: str = "OPEN",
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
        status=status,
    )


def _build(
    *,
    bid: int = 110_000,
    on_position_closed: Callable | None = None,
) -> tuple[V71ExitExecutor, FakeExchange, V71BoxManager, FakeNotifier, FakeClock]:
    ex = FakeExchange(bid_1=bid, ask_1=bid + 100, last_price=bid + 50)
    bm = V71BoxManager()
    notifier = FakeNotifier()
    clock = FakeClock()
    ctx = ExitExecutorContext(
        exchange=ex,
        box_manager=bm,
        notifier=notifier,
        clock=clock,
        on_position_closed=on_position_closed,
    )
    executor = V71ExitExecutor(context=ctx)
    return executor, ex, bm, notifier, clock


# ---------------------------------------------------------------------------
# Stop loss (§5.1)
# ---------------------------------------------------------------------------


class TestStopLoss:
    @pytest.mark.asyncio
    async def test_full_market_sell_closes_position(self):
        executor, ex, bm, notifier, _ = _build(bid=95_000)
        pos = _position(avg=100_000, qty=100)
        outcome = await executor.execute_stop_loss(pos)
        assert outcome.status == ExitOutcomeStatus.FILLED
        assert outcome.reason == "STOP_LOSS"
        assert outcome.sold_quantity == 100
        assert pos.total_quantity == 0
        assert pos.status == "CLOSED"
        # Market order issued (skipped limit phase).
        assert ex.orders_sent[0]["order_type"] is V71OrderType.MARKET
        # CRITICAL alert.
        assert any(
            ev.get("severity") == "CRITICAL"
            and ev.get("event_type") == "STOP_LOSS"
            for ev in notifier.events
        )

    @pytest.mark.asyncio
    async def test_full_exit_cancels_sibling_waiting_boxes(self):
        executor, ex, bm, notifier, _ = _build(bid=95_000)
        pos = _position(avg=100_000, qty=100)
        # Two siblings WAITING on the same tracked stock.
        b1 = bm.create_box(
            tracked_stock_id="t1",
            upper_price=120_000,
            lower_price=110_000,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        b2 = bm.create_box(
            tracked_stock_id="t1",
            upper_price=105_000,
            lower_price=100_000,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        outcome = await executor.execute_stop_loss(pos)
        assert outcome.status == ExitOutcomeStatus.FILLED
        assert bm.get(b1.id).status is BoxStatus.CANCELLED
        assert bm.get(b2.id).status is BoxStatus.CANCELLED
        assert bm.get(b1.id).invalidation_reason == "POSITION_CLOSED"

    @pytest.mark.asyncio
    async def test_on_position_closed_callback_fires(self):
        called: list[tuple[str, str]] = []

        async def cb(stock, pos_id):
            called.append((stock, pos_id))

        executor, ex, bm, _, _ = _build(bid=95_000, on_position_closed=cb)
        pos = _position(avg=100_000, qty=100)
        await executor.execute_stop_loss(pos)
        assert called == [("005930", "pos-1")]

    @pytest.mark.asyncio
    async def test_market_failure_no_state_change(self):
        executor, ex, bm, notifier, _ = _build(bid=95_000)
        ex.default_full_fill = False  # market also unfilled
        pos = _position(avg=100_000, qty=100)
        outcome = await executor.execute_stop_loss(pos)
        assert outcome.status == ExitOutcomeStatus.FAILED
        assert pos.total_quantity == 100  # untouched
        assert pos.status == "OPEN"


# ---------------------------------------------------------------------------
# TS exit (§5.5 trigger)
# ---------------------------------------------------------------------------


class TestTSExit:
    @pytest.mark.asyncio
    async def test_full_market_sell_high_severity(self):
        executor, ex, bm, notifier, _ = _build(bid=115_000)
        pos = _position(avg=100_000, qty=49, profit_5=True, profit_10=True)
        outcome = await executor.execute_ts_exit(pos)
        assert outcome.status == ExitOutcomeStatus.FILLED
        assert outcome.reason == "TS_EXIT"
        assert pos.status == "CLOSED"
        assert any(
            ev.get("event_type") == "TS_EXIT" and ev.get("severity") == "HIGH"
            for ev in notifier.events
        )


# ---------------------------------------------------------------------------
# Partial profit-take (§5.2 / §5.3)
# ---------------------------------------------------------------------------


class TestProfitTake:
    @pytest.mark.asyncio
    async def test_profit_5_partial_fills_and_advances_stage(self):
        executor, ex, bm, notifier, _ = _build(bid=105_000)
        pos = _position(avg=100_000, qty=100, fixed_stop=95_000)
        pt = ProfitTakeResult(
            should_exit=True,
            level="PROFIT_5",
            quantity_to_sell=30,
            new_position_status="PARTIAL_CLOSED",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.status == ExitOutcomeStatus.FILLED
        assert outcome.reason == "PROFIT_5"
        assert outcome.sold_quantity == 30
        # State: profit_5 flag set, stage 2 stop = avg * 0.98 = 98_000
        assert pos.profit_5_executed is True
        assert pos.profit_10_executed is False
        assert pos.fixed_stop_price == 98_000
        assert pos.total_quantity == 70
        assert pos.status == "PARTIAL_CLOSED"
        # Limit order at bid_1
        assert ex.orders_sent[0]["price"] == 105_000
        assert ex.orders_sent[0]["side"] is V71OrderSide.SELL
        assert ex.orders_sent[0]["order_type"] is V71OrderType.LIMIT

    @pytest.mark.asyncio
    async def test_profit_10_partial_fills_and_advances_stage(self):
        executor, ex, bm, notifier, _ = _build(bid=110_000)
        pos = _position(
            avg=100_000, qty=70, fixed_stop=98_000, profit_5=True
        )
        pt = ProfitTakeResult(
            should_exit=True,
            level="PROFIT_10",
            quantity_to_sell=21,
            new_position_status="PARTIAL_CLOSED",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.status == ExitOutcomeStatus.FILLED
        assert pos.profit_10_executed is True
        # Stage 3: fixed_stop_price = avg +4% = 104_000
        assert pos.fixed_stop_price == 104_000
        assert pos.total_quantity == 49

    @pytest.mark.asyncio
    async def test_profit_take_noop_when_should_exit_false(self):
        executor, ex, bm, _, _ = _build()
        pos = _position(avg=100_000, qty=100)
        pt = ProfitTakeResult(
            should_exit=False, level="NONE",
            quantity_to_sell=0, new_position_status="OPEN",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.status == ExitOutcomeStatus.FAILED
        assert outcome.reason == "PROFIT_TAKE_NO_OP"
        assert pos.total_quantity == 100  # untouched
        assert ex.orders_sent == []

    @pytest.mark.asyncio
    async def test_profit_take_caps_at_total_quantity(self):
        """Asking for more than available -- cap at total_quantity."""
        executor, ex, bm, _, _ = _build(bid=105_000)
        pos = _position(avg=100_000, qty=10)
        pt = ProfitTakeResult(
            should_exit=True,
            level="PROFIT_5",
            quantity_to_sell=30,  # bigger than available
            new_position_status="PARTIAL_CLOSED",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.sold_quantity == 10
        assert pos.total_quantity == 0
        assert pos.status == "CLOSED"

    @pytest.mark.asyncio
    async def test_profit_take_rejected(self):
        executor, ex, bm, notifier, _ = _build(bid=105_000)
        ex.fail_send = OrderRejectedError("halted")
        pos = _position(avg=100_000, qty=100)
        pt = ProfitTakeResult(
            should_exit=True, level="PROFIT_5",
            quantity_to_sell=30, new_position_status="PARTIAL_CLOSED",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.status == ExitOutcomeStatus.REJECTED
        assert pos.total_quantity == 100  # untouched
        assert any(
            ev.get("event_type") == "EXIT_REJECTED" for ev in notifier.events
        )

    @pytest.mark.asyncio
    async def test_profit_take_transport_failure(self):
        executor, ex, bm, notifier, _ = _build(bid=105_000)
        ex.fail_send = KiwoomAPIError("network down")
        pos = _position(avg=100_000, qty=100)
        pt = ProfitTakeResult(
            should_exit=True, level="PROFIT_5",
            quantity_to_sell=30, new_position_status="PARTIAL_CLOSED",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.status == ExitOutcomeStatus.FAILED
        assert pos.total_quantity == 100


# ---------------------------------------------------------------------------
# Sell sequence retry (limit x3 -> market)
# ---------------------------------------------------------------------------


class TestSellSequence:
    @pytest.mark.asyncio
    async def test_three_unfilled_limits_then_market(self):
        executor, ex, bm, _, _ = _build(bid=105_000)
        ex.default_full_fill = False  # limit phase unfilled

        # Flip default_full_fill on the 4th call (market) to fill.
        original_send = ex.send_order
        send_count = {"n": 0}

        async def patched_send(**kw):
            send_count["n"] += 1
            if send_count["n"] >= 4:
                ex.default_full_fill = True
            return await original_send(**kw)

        ex.send_order = patched_send  # type: ignore[method-assign]

        pos = _position(avg=100_000, qty=100)
        pt = ProfitTakeResult(
            should_exit=True, level="PROFIT_5",
            quantity_to_sell=30, new_position_status="PARTIAL_CLOSED",
        )
        outcome = await executor.execute_profit_take(pos, pt)
        assert outcome.status == ExitOutcomeStatus.FILLED
        assert outcome.attempts == 4  # 3 limits + 1 market
        assert len(ex.cancellations) == 3
        # Last order is MARKET
        assert ex.orders_sent[-1]["order_type"] is V71OrderType.MARKET
