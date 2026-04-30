"""Unit tests for ``src/core/v71/strategies/v71_buy_executor.py``.

Spec:
  - 02_TRADING_RULES.md §4   (buy execution sequence)
  - 02_TRADING_RULES.md §3.10/§3.11/§10.9 (PATH_B 09:01 + 09:05 fallback)
  - 02_TRADING_RULES.md §3.4  (30% per-stock cap)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_box_system():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
from src.core.v71.box.box_state_machine import BoxStatus  # noqa: E402
from src.core.v71.skills.box_entry_skill import EntryDecision  # noqa: E402
from src.core.v71.skills.kiwoom_api_skill import (  # noqa: E402
    KiwoomAPIError,
    OrderRejectedError,
    V71Orderbook,
    V71OrderResult,
    V71OrderSide,
    V71OrderStatus,
    V71OrderType,
)
from src.core.v71.strategies.v71_buy_executor import (  # noqa: E402
    BuyExecutorContext,
    BuyOutcomeStatus,
    V71BuyExecutor,
)
from tests.v71.conftest import FakeBoxManager  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime
    sleeps: list[float] = field(default_factory=list)
    sleep_untils: list[datetime] = field(default_factory=list)

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_value = self.now_value + timedelta(seconds=seconds)

    async def sleep_until(self, target: datetime) -> None:
        self.sleep_untils.append(target)
        if target > self.now_value:
            self.now_value = target


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)

    async def notify(self, **kwargs) -> None:
        self.events.append(kwargs)


@dataclass
class FakePositionStore:
    added: list[dict] = field(default_factory=list)

    async def add_position(self, **kwargs):
        from src.core.v71.position.state import PositionState, PositionStatus

        pos_id = f"pos-{len(self.added) + 1}"
        self.added.append({"id": pos_id, **kwargs})
        # P-Wire-Box-4: PositionStore protocol now returns PositionState.
        return PositionState(
            position_id=pos_id,
            stock_code=kwargs["stock_code"],
            tracked_stock_id=kwargs.get("tracked_stock_id"),
            triggered_box_id=kwargs.get("triggered_box_id"),
            path_type=kwargs.get("path_type", "PATH_A"),
            weighted_avg_price=int(kwargs["weighted_avg_price"]),
            initial_avg_price=int(kwargs["weighted_avg_price"]),
            total_quantity=int(kwargs["quantity"]),
            fixed_stop_price=int(kwargs["weighted_avg_price"] * 0.95),
            status=PositionStatus.OPEN,
            opened_at=kwargs["opened_at"],
        )


class FakeExchange:
    """Programmable broker. Each test pre-loads the next ``V71OrderStatus``
    sequence per order id (or relies on the default full-fill behavior).
    """

    def __init__(
        self,
        *,
        ask_1: int = 18050,
        bid_1: int = 18000,
        last_price: int = 18025,
        current_price: int | None = None,
    ) -> None:
        self.ask_1 = ask_1
        self.bid_1 = bid_1
        self.last_price = last_price
        self.current_price = current_price if current_price is not None else last_price
        self.orders_sent: list[dict] = []
        self.cancellations: list[str] = []
        self._next_id = 1
        # order_id -> list[V71OrderStatus] returned on successive polls.
        self.status_sequence: dict[str, list[V71OrderStatus]] = {}
        self.fail_send: Exception | None = None
        self.default_full_fill = True
        self.default_unfilled_then_full = False  # not used; reserved
        self.fixed_fill_price: int | None = None  # if None, uses requested

    async def get_orderbook(self, stock_code: str) -> V71Orderbook:
        return V71Orderbook(
            stock_code=stock_code,
            bid_1=self.bid_1,
            ask_1=self.ask_1,
            last_price=self.last_price,
        )

    async def get_current_price(self, stock_code: str) -> int:  # noqa: ARG002
        return self.current_price

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
            fill_price = (
                self.fixed_fill_price
                if self.fixed_fill_price is not None
                else (price if price > 0 else self.last_price)
            )
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
            side=V71OrderSide.BUY,
            order_type=V71OrderType.LIMIT,
            requested_quantity=0,
            requested_price=0,
        )

    async def get_order_status(self, order_id: str) -> V71OrderStatus:
        seq = self.status_sequence.get(order_id)
        if not seq:
            raise AssertionError(
                f"FakeExchange has no status pre-loaded for {order_id}"
            )
        return seq.pop(0) if len(seq) > 1 else seq[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


STOCK = "005930"
TRACKED = "tracked-001"


def _make_decision(
    *,
    path_type: str,  # noqa: ARG001 -- documents intent; reason actually drives branch
    expected_buy_price: int = 18000,
    expected_buy_at: datetime | None = None,
    fallback_buy_at: datetime | None = None,
    fallback_uses_market_order: bool = False,
    fallback_gap_recheck_required: bool = False,
    reason: str = "PULLBACK_A_TRIGGERED",
) -> EntryDecision:
    return EntryDecision(
        should_enter=True,
        reason=reason,
        box_id=None,
        expected_buy_price=expected_buy_price,
        expected_buy_at=expected_buy_at,
        fallback_buy_at=fallback_buy_at,
        fallback_uses_market_order=fallback_uses_market_order,
        fallback_gap_recheck_required=fallback_gap_recheck_required,
    )


async def _make_box(
    box_manager: V71BoxManager,
    *,
    path_type: str = "PATH_A",
    strategy: str = "PULLBACK",
    position_size_pct: float = 10.0,
):
    return await box_manager.create_box(
        tracked_stock_id=TRACKED,
        upper_price=20000,
        lower_price=15000,
        position_size_pct=position_size_pct,
        strategy_type=strategy,  # type: ignore[arg-type]
        path_type=path_type,  # type: ignore[arg-type]
    )


def _build_executor(
    *,
    exchange: FakeExchange,
    box_manager: V71BoxManager,
    is_vi_active: Callable[[str], bool] = lambda _s: False,
    invested_pct=None,
    total_capital: int = 100_000_000,
    previous_close: int = 18000,
    clock: FakeClock | None = None,
) -> tuple[V71BuyExecutor, FakeNotifier, FakePositionStore, FakeClock]:
    notifier = FakeNotifier()
    position_store = FakePositionStore()
    clock = clock or FakeClock(now_value=datetime(2026, 4, 27, 14, 30))

    # P-Wire-Box-4: get_invested_pct_for_stock is now async. Wrap a
    # plain sync callable (or a constant) so legacy test fixtures keep
    # working without rewriting every caller.
    if invested_pct is None:
        async def _default_invested_pct(_s):
            return 0.0
        invested_pct_async = _default_invested_pct
    elif callable(invested_pct):
        async def _wrap_invested_pct(stock_code):
            result = invested_pct(stock_code)
            if hasattr(result, "__await__"):
                return await result
            return result
        invested_pct_async = _wrap_invested_pct
    else:
        raise TypeError("invested_pct must be a callable or None")

    ctx = BuyExecutorContext(
        exchange=exchange,
        box_manager=box_manager,
        position_store=position_store,
        notifier=notifier,
        clock=clock,
        is_vi_active=is_vi_active,
        get_previous_close=lambda _s: previous_close,
        get_total_capital=lambda: total_capital,
        get_invested_pct_for_stock=invested_pct_async,
    )
    executor = V71BuyExecutor(
        context=ctx,
        tracked_stock_resolver=lambda _tracked_id: STOCK,
    )
    return executor, notifier, position_store, clock


# ---------------------------------------------------------------------------
# PATH_A (immediate)
# ---------------------------------------------------------------------------


class TestPathAImmediate:
    @pytest.mark.asyncio
    async def test_normal_full_fill(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange(ask_1=18050)
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm
        )
        decision = _make_decision(path_type="PATH_A")

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FILLED
        # 1차 시도에서 full fill
        assert outcome.attempts == 1
        # Quantity = floor(100M * 10% / expected_buy_price=18000) = 555
        assert outcome.filled_quantity == 555
        assert outcome.position_id == "pos-1"
        # Box marked TRIGGERED
        assert (await bm.get(box.id)).status is BoxStatus.TRIGGERED
        # Position record created
        assert store.added[0]["stock_code"] == STOCK
        assert store.added[0]["quantity"] == 555
        # HIGH BUY_EXECUTED notification
        assert any(
            ev.get("event_type") == "BUY_EXECUTED" and ev.get("severity") == "HIGH"
            for ev in notifier.events
        )

    @pytest.mark.asyncio
    async def test_cap_exceeded_blocks_buy(self):
        bm = FakeBoxManager()
        box = await _make_box(bm, position_size_pct=15.0)
        ex = FakeExchange()
        # already 20% invested -> 20+15 = 35 > 30
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm, invested_pct=lambda _s: 20.0
        )
        decision = _make_decision(path_type="PATH_A")

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.ABANDONED_CAP
        assert "CAP_EXCEEDED" in outcome.reason
        # Box NOT triggered
        assert (await bm.get(box.id)).status is BoxStatus.WAITING
        # No position created
        assert store.added == []
        # Abandon notification fired
        assert any(
            ev.get("event_type") == "BUY_ABANDONED" for ev in notifier.events
        )

    @pytest.mark.asyncio
    async def test_vi_active_blocks_path_a(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange()
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm, is_vi_active=lambda _s: True
        )
        decision = _make_decision(path_type="PATH_A")

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.ABANDONED_VI
        assert (await bm.get(box.id)).status is BoxStatus.WAITING
        assert store.added == []

    @pytest.mark.asyncio
    async def test_target_quantity_zero_blocks_buy(self):
        bm = FakeBoxManager()
        # tiny position pct + huge price => 0 shares
        box = await _make_box(bm, position_size_pct=0.01)
        ex = FakeExchange(ask_1=99_999_999)
        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm, total_capital=1_000
        )
        decision = _make_decision(path_type="PATH_A", expected_buy_price=99_999_999)

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.ABANDONED_CAP
        assert "ZERO_QUANTITY" in outcome.reason
        assert store.added == []


# ---------------------------------------------------------------------------
# Buy sequence (limit x3 -> market)
# ---------------------------------------------------------------------------


class TestBuySequenceRetry:
    @pytest.mark.asyncio
    async def test_three_unfilled_limits_then_market_fills(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange(ask_1=18050)
        ex.default_full_fill = False  # limits return unfilled

        # Pre-load: orders 1, 2, 3 are limits returning unfilled; order 4 is market full fill.
        # Build empty placeholders so send_order picks default_full_fill False.
        # Then we override order 4 (market) to be a full fill.

        # Strategy: after each unfilled limit, executor cancels (no status read).
        # We need order id 4 (market) to return full fill.
        # Trick: post-hoc patch status_sequence for order-4 once we know its id.

        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm
        )

        # Pre-arrange: when send_order is called for the market fallback,
        # default_full_fill must be True. We'll flip it after the 3rd limit.
        # Workaround: monkey-patch send_order to flip after 3 calls.
        original_send = ex.send_order
        send_count = {"n": 0}

        async def patched_send(**kw):
            send_count["n"] += 1
            if send_count["n"] >= 4:  # market call
                ex.default_full_fill = True
            return await original_send(**kw)

        ex.send_order = patched_send  # type: ignore[method-assign]

        decision = _make_decision(path_type="PATH_A")
        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FILLED
        assert outcome.attempts == 4  # 3 limits + 1 market
        # 3 limits sent + 1 market = 4 orders
        assert len(ex.orders_sent) == 4
        # 3 cancels (after each unfilled limit)
        assert len(ex.cancellations) == 3
        # Last order is MARKET
        assert ex.orders_sent[-1]["order_type"] is V71OrderType.MARKET

    @pytest.mark.asyncio
    async def test_all_attempts_fail(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange(ask_1=18050)
        ex.default_full_fill = False  # everything (incl. market) unfilled

        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm
        )

        decision = _make_decision(path_type="PATH_A")
        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FAILED
        assert "NO_FILL" in outcome.reason
        assert (await bm.get(box.id)).status is BoxStatus.WAITING
        assert store.added == []


# ---------------------------------------------------------------------------
# PATH_B 1차 (09:01) + 09:05 fallback (§3.10/§3.11/§10.9)
# ---------------------------------------------------------------------------


class TestPathBPrimaryAndFallback:
    @pytest.mark.asyncio
    async def test_primary_normal_fill(self):
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        # opening at 18200 vs prev close 18000 = 1.1% gap, OK
        ex = FakeExchange(ask_1=18250, current_price=18200)
        when_decision = datetime(2026, 4, 27, 14, 30)
        clock = FakeClock(now_value=when_decision)
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )

        primary_at = datetime(2026, 4, 28, 9, 1)
        fallback_at = datetime(2026, 4, 28, 9, 5)
        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=primary_at,
            fallback_buy_at=fallback_at,
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FILLED
        assert clock.sleep_untils == [primary_at]
        assert (await bm.get(box.id)).status is BoxStatus.TRIGGERED
        assert store.added[0]["path_type"] == "PATH_B"

    @pytest.mark.asyncio
    async def test_primary_gap_up_5pct_blocks_buy_no_fallback(self):
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        # opening 18900 vs prev 18000 = 5% exactly -> blocked
        ex = FakeExchange(ask_1=18900, current_price=18900)
        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )

        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.ABANDONED_GAP
        assert "PRIMARY_GAP" in outcome.reason
        # Did NOT proceed to fallback (only one sleep_until = primary).
        assert clock.sleep_untils == [datetime(2026, 4, 28, 9, 1)]
        assert (await bm.get(box.id)).status is BoxStatus.WAITING
        assert store.added == []

    @pytest.mark.asyncio
    async def test_primary_unfilled_triggers_905_fallback_and_fills(self):
        """1차 미체결 → 09:05 시장가 → FILLED."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        ex = FakeExchange(ask_1=18200, current_price=18200)
        # 1차: limits 모두 미체결, market 실패; 2차 시점에서는 시장가 체결로 swap
        ex.default_full_fill = False

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )

        # Patch send: flip default_full_fill to True after 4 sends (1차 끝)
        # so the fallback market order fills.
        original_send = ex.send_order
        send_count = {"n": 0}

        async def patched_send(**kw):
            send_count["n"] += 1
            if send_count["n"] == 5:  # 1st call inside fallback (market_only)
                ex.default_full_fill = True
            return await original_send(**kw)

        ex.send_order = patched_send  # type: ignore[method-assign]

        primary_at = datetime(2026, 4, 28, 9, 1)
        fallback_at = datetime(2026, 4, 28, 9, 5)
        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=primary_at,
            fallback_buy_at=fallback_at,
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FILLED
        # Both primary (09:01) and fallback (09:05) sleep_untils observed.
        assert clock.sleep_untils == [primary_at, fallback_at]
        assert (await bm.get(box.id)).status is BoxStatus.TRIGGERED
        # Buy notification mentions fallback context
        msg = next(
            ev for ev in notifier.events if ev.get("event_type") == "BUY_EXECUTED"
        )
        assert "fallback" in msg["message"].lower()

    @pytest.mark.asyncio
    async def test_fallback_gap_recheck_invalidates_safety_net(self):
        """1차 미체결 + 09:05 시점 갭업 5% 이상 → ABANDONED_GAP."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        # At decision time and 09:01 the open was 18200 (1.1% gap).
        # At 09:05 the price has run up to 18900 (5% gap).
        ex = FakeExchange(ask_1=18250, current_price=18200)
        ex.default_full_fill = False  # primary unfilled

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )

        # After primary phase, bump current_price up to trigger fallback gap rejection.
        original_send = ex.send_order
        send_count = {"n": 0}

        async def patched_send(**kw):
            send_count["n"] += 1
            return await original_send(**kw)

        ex.send_order = patched_send  # type: ignore[method-assign]

        # We can't easily know "fallback time has come" inside send_order,
        # but check_gap is called via get_current_price *before* send_order.
        # So we monkey-patch get_current_price to return 18900 the SECOND time.
        prices_returned = {"n": 0}

        async def patched_get_price(stock_code):  # noqa: ARG001
            prices_returned["n"] += 1
            if prices_returned["n"] >= 2:  # fallback time
                return 18900
            return 18200  # primary time

        ex.get_current_price = patched_get_price  # type: ignore[method-assign]

        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.ABANDONED_GAP
        assert "FALLBACK_GAP" in outcome.reason
        assert (await bm.get(box.id)).status is BoxStatus.WAITING
        assert store.added == []

    @pytest.mark.asyncio
    async def test_fallback_after_partial_fill_uses_weighted_average(self):
        """1차에서 부분 체결, 09:05에 잔량 시장가 → 가중평균 평단가 정확."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B", position_size_pct=10.0)
        ex = FakeExchange(ask_1=18200, current_price=18200, last_price=18000)

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )

        # 1차 한 시도에서 200/549 부분 체결. Then later attempts: 0 fill.
        # Then fallback market: 349 (잔량) full fill.
        # We orchestrate this via custom status sequences keyed by order id.
        original_send = ex.send_order
        send_count = {"n": 0}

        async def patched_send(**kw):
            send_count["n"] += 1
            order = await original_send(**kw)
            order_id = order.order_id
            if send_count["n"] == 1:
                # First limit: 200 filled out of 549
                ex.status_sequence[order_id] = [
                    V71OrderStatus(
                        order_id=order_id,
                        stock_code=order.stock_code,
                        requested_quantity=549,
                        filled_quantity=200,
                        avg_fill_price=18200,
                        is_open=True,
                        is_cancelled=False,
                    )
                ]
            elif send_count["n"] in (2, 3, 4):
                # Subsequent limits + market in 1st phase: no fill
                ex.status_sequence[order_id] = [
                    V71OrderStatus(
                        order_id=order_id,
                        stock_code=order.stock_code,
                        requested_quantity=349,
                        filled_quantity=0,
                        avg_fill_price=0,
                        is_open=True,
                        is_cancelled=False,
                    )
                ]
            elif send_count["n"] == 5:
                # Fallback market (market_only=True): full fill 349 @ 18500
                ex.status_sequence[order_id] = [
                    V71OrderStatus(
                        order_id=order_id,
                        stock_code=order.stock_code,
                        requested_quantity=349,
                        filled_quantity=349,
                        avg_fill_price=18500,
                        is_open=False,
                        is_cancelled=False,
                    )
                ]
            return order

        ex.send_order = patched_send  # type: ignore[method-assign]

        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            expected_buy_price=18200,
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FILLED
        # Total filled = 200 (primary) + 349 (fallback) = 549
        assert outcome.filled_quantity == 549
        # Weighted avg = (200*18200 + 349*18500) / 549
        expected_avg = round((200 * 18200 + 349 * 18500) / 549)
        assert outcome.weighted_avg_price == expected_avg
        # Position record reflects merged quantity
        assert store.added[0]["quantity"] == 549


# ---------------------------------------------------------------------------
# Negative decision (defensive)
# ---------------------------------------------------------------------------


class TestNegativeDecisionGuard:
    @pytest.mark.asyncio
    async def test_should_enter_false_is_noop(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange()
        executor, _, store, _ = _build_executor(exchange=ex, box_manager=bm)

        decision = EntryDecision(
            should_enter=False,
            reason="VI_RECOVERED_TODAY_BLOCKED",
            box_id=None,
            expected_buy_price=None,
            expected_buy_at=None,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status is BuyOutcomeStatus.ABANDONED_VI
        assert ex.orders_sent == []
        assert store.added == []


# ---------------------------------------------------------------------------
# Broker-error paths
# ---------------------------------------------------------------------------


class TestBrokerErrors:
    @pytest.mark.asyncio
    async def test_order_rejected_short_circuits(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange(ask_1=18050)
        ex.fail_send = OrderRejectedError("insufficient cash")

        executor, notifier, store, _ = _build_executor(
            exchange=ex, box_manager=bm
        )
        decision = _make_decision(path_type="PATH_A")

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.REJECTED
        assert (await bm.get(box.id)).status is BoxStatus.WAITING
        assert store.added == []

    @pytest.mark.asyncio
    async def test_transport_error_returns_failed(self):
        bm = FakeBoxManager()
        box = await _make_box(bm)
        ex = FakeExchange(ask_1=18050)
        ex.fail_send = KiwoomAPIError("network down")

        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm
        )
        decision = _make_decision(path_type="PATH_A")

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FAILED
        assert store.added == []

    @pytest.mark.asyncio
    async def test_path_b_primary_rejected_short_circuits(self):
        """PATH_B 1차 broker reject -> REJECTED (no fallback attempt)."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        ex = FakeExchange(ask_1=18250, current_price=18200)
        ex.fail_send = OrderRejectedError("insufficient cash")

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )
        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        # Reject is permanent -- no fallback attempted.
        assert outcome.status == BuyOutcomeStatus.REJECTED
        assert clock.sleep_untils == [datetime(2026, 4, 28, 9, 1)]
        assert store.added == []

    @pytest.mark.asyncio
    async def test_path_b_primary_transport_error_defers_to_fallback(self):
        """PATH_B 1차 transport error + fallback metadata -> 2차 시도."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        ex = FakeExchange(ask_1=18250, current_price=18200)
        # Primary phase: transport error on every send.
        # Fallback phase (after sleep_until 09:05): we restore behavior
        # so the market order fills.
        primary_calls = {"n": 0}
        original_send = ex.send_order

        async def patched_send(**kw):
            primary_calls["n"] += 1
            if primary_calls["n"] == 1:
                raise KiwoomAPIError("transient")
            # subsequent (fallback) sends succeed
            ex.fail_send = None
            return await original_send(**kw)

        ex.send_order = patched_send  # type: ignore[method-assign]

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )
        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        # 1차 transport error -> fallback fills.
        assert outcome.status == BuyOutcomeStatus.FILLED
        assert clock.sleep_untils == [
            datetime(2026, 4, 28, 9, 1),
            datetime(2026, 4, 28, 9, 5),
        ]
        # primary_reason includes the error.
        msg = next(
            ev for ev in (executor._ctx.notifier.events)  # type: ignore[attr-defined]
            if ev.get("event_type") == "BUY_EXECUTED"
        )
        assert "PRIMARY_API_ERROR" in msg["message"]

    @pytest.mark.asyncio
    async def test_fallback_transport_error_returns_failed(self):
        """1차 미체결 + 09:05 fallback에서도 transport error -> FAILED."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B")
        ex = FakeExchange(ask_1=18250, current_price=18200)
        ex.default_full_fill = False  # primary unfilled

        # Patch: primary returns unfilled normally; fallback raises.
        original_send = ex.send_order
        send_count = {"n": 0}

        async def patched_send(**kw):
            send_count["n"] += 1
            if send_count["n"] == 5:  # fallback market call
                raise KiwoomAPIError("transient at fallback")
            return await original_send(**kw)

        ex.send_order = patched_send  # type: ignore[method-assign]

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, _, store, _ = _build_executor(
            exchange=ex, box_manager=bm, previous_close=18000, clock=clock
        )
        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        assert outcome.status == BuyOutcomeStatus.FAILED
        assert "transient at fallback" in outcome.reason
        assert store.added == []

    @pytest.mark.asyncio
    async def test_fallback_cap_exceeded_during_window(self):
        """1차 미체결 + 09:01~09:05 사이 사용자 수동 매수 -> cap 초과 -> ABANDONED_CAP."""
        bm = FakeBoxManager()
        box = await _make_box(bm, path_type="PATH_B", position_size_pct=15.0)
        ex = FakeExchange(ask_1=18250, current_price=18200)
        ex.default_full_fill = False

        # invested_pct callable that returns 0 for primary cap_check, then
        # 20 for fallback cap_check (simulating manual buy during window).
        cap_lookup_count = {"n": 0}

        def invested_pct(_stock):
            cap_lookup_count["n"] += 1
            return 0.0 if cap_lookup_count["n"] == 1 else 20.0

        clock = FakeClock(now_value=datetime(2026, 4, 27, 14, 30))
        executor, _, store, _ = _build_executor(
            exchange=ex,
            box_manager=bm,
            invested_pct=invested_pct,
            previous_close=18000,
            clock=clock,
        )
        decision = _make_decision(
            path_type="PATH_B",
            reason="PULLBACK_B_TRIGGERED",
            expected_buy_at=datetime(2026, 4, 28, 9, 1),
            fallback_buy_at=datetime(2026, 4, 28, 9, 5),
            fallback_uses_market_order=True,
            fallback_gap_recheck_required=True,
        )

        outcome = await executor.on_entry_decision(decision, box)

        # Primary cap_check passes (0%); fallback cap_check rejects (20+15=35>30).
        assert outcome.status == BuyOutcomeStatus.ABANDONED_CAP
        assert "CAP_EXCEEDED" in outcome.reason
