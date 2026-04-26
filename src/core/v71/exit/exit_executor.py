"""V71ExitExecutor -- order placement for stop / partial / TS exits.

Spec:
  - 02_TRADING_RULES.md §5.1 (stop loss)
  - 02_TRADING_RULES.md §5.2 / §5.3 (partial profit-take)
  - 02_TRADING_RULES.md §5.5 (trailing stop)
  - 02_TRADING_RULES.md §5.9 (post-exit state machine)
  - 04_ARCHITECTURE.md §5.3
  - 07_SKILLS_SPEC.md §1 (kiwoom_api_skill)

Phase: P3.3

Order policy mirrors V71BuyExecutor (§4.2) but in reverse:
    SELL limit at bid_1 (매수 1호가) x ORDER_RETRY_COUNT,
    then market fallback. Stop / TS exits go market-only for fastest fill.

State updates on the in-memory :class:`PositionState`:
    - profit_5_executed / profit_10_executed flags
    - fixed_stop_price (recomputed via stage_after_partial_exit)
    - total_quantity (decremented by sold qty)
    - status (OPEN -> PARTIAL_CLOSED -> CLOSED)
    - closed_at (on full exit)

On full exit additionally:
    - all sibling WAITING boxes -> CANCELLED (§5.9)
    - on_position_closed callback fired (price-feed unsubscribe etc.)
    - CRITICAL or HIGH notification

P3.4 V71PositionManager will swap the in-memory mutation for DB writes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from src.core.v71.box.box_manager import V71BoxManager
from src.core.v71.position.state import PositionState
from src.core.v71.skills.exit_calc_skill import (
    ProfitTakeResult,
    stage_after_partial_exit,
)
from src.core.v71.skills.kiwoom_api_skill import (
    ExchangeAdapter,
    KiwoomAPIError,
    OrderRejectedError,
    V71OrderSide,
    V71OrderType,
)
from src.core.v71.strategies.v71_buy_executor import Clock, Notifier
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------

class ExitOutcomeStatus(Enum):
    FILLED = "FILLED"                  # full target sold
    PARTIAL_FILLED = "PARTIAL_FILLED"  # only some of target sold
    REJECTED = "REJECTED"              # broker reject
    FAILED = "FAILED"                  # all attempts empty


@dataclass(frozen=True)
class ExitOutcome:
    status: ExitOutcomeStatus
    stock_code: str
    position_id: str
    reason: str  # STOP_LOSS / TS_EXIT / PROFIT_TAKE_5 / PROFIT_TAKE_10 / FAILED_*
    sold_quantity: int = 0
    weighted_avg_sell_price: int = 0
    attempts: int = 0


@dataclass
class _SellSequenceResult:
    """Internal aggregate of one limit-then-market sell loop."""

    filled_quantity: int = 0
    weighted_avg_price: int = 0
    attempts: int = 0
    fills: list[tuple[int, int]] = field(default_factory=list)

    def add_fill(self, qty: int, price: int) -> None:
        if qty <= 0:
            return
        self.fills.append((qty, price))
        total_qty = sum(q for q, _ in self.fills)
        total_cost = sum(q * p for q, p in self.fills)
        self.filled_quantity = total_qty
        self.weighted_avg_price = (
            int(round(total_cost / total_qty)) if total_qty else 0
        )


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

OnPositionClosed = Callable[[str, str], Awaitable[None]]
"""(stock_code, position_id) -> awaitable; e.g. price-feed unsubscribe."""


@dataclass(frozen=True)
class ExitExecutorContext:
    """Bundle of injected dependencies (mirror of BuyExecutorContext)."""

    exchange: ExchangeAdapter
    box_manager: V71BoxManager
    notifier: Notifier
    clock: Clock

    # Optional: invoked after a full exit so callers can unsubscribe price
    # feeds, refresh dashboards, etc.  P3.6 V71ViMonitor / orchestrator
    # wires this.
    on_position_closed: OnPositionClosed | None = None


# ---------------------------------------------------------------------------
# V71ExitExecutor
# ---------------------------------------------------------------------------

class V71ExitExecutor:
    """Translates exit decisions into Kiwoom orders.

    Three public entry points (called by orchestrator after V71ExitCalculator):
      * :meth:`execute_stop_loss`    -- full-quantity market sell on §5.1 trigger
      * :meth:`execute_ts_exit`      -- full-quantity market sell on §5.5 trigger
      * :meth:`execute_profit_take`  -- 30% slice (limit -> market) on §5.2/§5.3

    The executor mutates the supplied :class:`PositionState` in place
    (P3.3 in-memory). P3.4 will replace the mutation with V71PositionManager
    DB calls.
    """

    def __init__(self, *, context: ExitExecutorContext) -> None:
        require_enabled("v71.exit_v71")
        self._ctx = context

    # ------------------------------------------------------------------
    # Stop loss (§5.1)
    # ------------------------------------------------------------------

    async def execute_stop_loss(self, position: PositionState) -> ExitOutcome:
        return await self._sell_full(
            position,
            reason="STOP_LOSS",
            severity="CRITICAL",
            event_type="STOP_LOSS",
        )

    # ------------------------------------------------------------------
    # Trailing stop exit (§5.5)
    # ------------------------------------------------------------------

    async def execute_ts_exit(self, position: PositionState) -> ExitOutcome:
        return await self._sell_full(
            position,
            reason="TS_EXIT",
            severity="HIGH",
            event_type="TS_EXIT",
        )

    # ------------------------------------------------------------------
    # Partial profit-take (§5.2 / §5.3)
    # ------------------------------------------------------------------

    async def execute_profit_take(
        self,
        position: PositionState,
        profit_take: ProfitTakeResult,
    ) -> ExitOutcome:
        if not profit_take.should_exit:
            return ExitOutcome(
                status=ExitOutcomeStatus.FAILED,
                stock_code=position.stock_code,
                position_id=position.position_id,
                reason="PROFIT_TAKE_NO_OP",
            )

        sell_qty = min(profit_take.quantity_to_sell, position.total_quantity)
        if sell_qty <= 0:
            return ExitOutcome(
                status=ExitOutcomeStatus.FAILED,
                stock_code=position.stock_code,
                position_id=position.position_id,
                reason="PROFIT_TAKE_ZERO_QTY",
            )

        try:
            seq = await self._sell_sequence(
                position.stock_code, sell_qty, market_only=False
            )
        except OrderRejectedError as e:
            return await self._reject(position, profit_take.level, str(e))
        except KiwoomAPIError as e:
            return await self._fail(position, profit_take.level, str(e))

        if seq.filled_quantity == 0:
            return await self._fail(
                position,
                profit_take.level,
                f"NO_FILL_AFTER_{seq.attempts}_ATTEMPTS",
            )

        # State updates (§5.4 + §5.9 partial path).
        position.total_quantity -= seq.filled_quantity
        if profit_take.level == "PROFIT_5":
            position.profit_5_executed = True
        elif profit_take.level == "PROFIT_10":
            position.profit_10_executed = True

        position.fixed_stop_price = stage_after_partial_exit(
            position.profit_5_executed,
            position.profit_10_executed,
            position.weighted_avg_price,
        )

        if position.total_quantity == 0:
            await self._on_full_exit(position)
            status = ExitOutcomeStatus.FILLED
        else:
            position.status = "PARTIAL_CLOSED"
            status = (
                ExitOutcomeStatus.FILLED
                if seq.filled_quantity == sell_qty
                else ExitOutcomeStatus.PARTIAL_FILLED
            )

        await self._ctx.notifier.notify(
            severity="HIGH",
            event_type=profit_take.level,  # "PROFIT_5" or "PROFIT_10"
            stock_code=position.stock_code,
            message=(
                f"[{position.stock_code}] {profit_take.level} 청산 "
                f"{seq.filled_quantity}주 @ {seq.weighted_avg_price}원 "
                f"(잔여 {position.total_quantity}주)"
            ),
            rate_limit_key=f"profit_take:{position.stock_code}:{profit_take.level}",
        )

        return ExitOutcome(
            status=status,
            stock_code=position.stock_code,
            position_id=position.position_id,
            reason=profit_take.level,
            sold_quantity=seq.filled_quantity,
            weighted_avg_sell_price=seq.weighted_avg_price,
            attempts=seq.attempts,
        )

    # ------------------------------------------------------------------
    # Internal: full-quantity sell (stop loss / TS)
    # ------------------------------------------------------------------

    async def _sell_full(
        self,
        position: PositionState,
        *,
        reason: str,
        severity: str,
        event_type: str,
    ) -> ExitOutcome:
        target_qty = position.total_quantity
        if target_qty <= 0:
            return ExitOutcome(
                status=ExitOutcomeStatus.FAILED,
                stock_code=position.stock_code,
                position_id=position.position_id,
                reason=f"{reason}_ZERO_QTY",
            )

        try:
            seq = await self._sell_sequence(
                position.stock_code, target_qty, market_only=True
            )
        except OrderRejectedError as e:
            return await self._reject(position, reason, str(e))
        except KiwoomAPIError as e:
            return await self._fail(position, reason, str(e))

        if seq.filled_quantity == 0:
            return await self._fail(
                position, reason, f"NO_FILL_AFTER_{seq.attempts}_ATTEMPTS"
            )

        position.total_quantity -= seq.filled_quantity

        if position.total_quantity == 0:
            await self._on_full_exit(position)
            status = ExitOutcomeStatus.FILLED
        else:
            position.status = "PARTIAL_CLOSED"
            status = ExitOutcomeStatus.PARTIAL_FILLED

        await self._ctx.notifier.notify(
            severity=severity,
            event_type=event_type,
            stock_code=position.stock_code,
            message=(
                f"[{position.stock_code}] {reason} 청산 "
                f"{seq.filled_quantity}주 @ {seq.weighted_avg_price}원"
            ),
            rate_limit_key=f"exit:{position.stock_code}:{reason}",
        )

        return ExitOutcome(
            status=status,
            stock_code=position.stock_code,
            position_id=position.position_id,
            reason=reason,
            sold_quantity=seq.filled_quantity,
            weighted_avg_sell_price=seq.weighted_avg_price,
            attempts=seq.attempts,
        )

    # ------------------------------------------------------------------
    # Internal: sell sequence (mirror of BuyExecutor's _buy_sequence)
    # ------------------------------------------------------------------

    async def _sell_sequence(
        self,
        stock_code: str,
        target_quantity: int,
        *,
        market_only: bool,
    ) -> _SellSequenceResult:
        """Limit at bid_1 x ORDER_RETRY_COUNT, then market fallback.

        SELL limits price at the best bid (매수 1호가) for fastest fill,
        analogous to BUY limits at the best ask (§4.1 reverse).
        """
        seq = _SellSequenceResult()
        remaining = target_quantity

        if not market_only:
            for _ in range(V71Constants.ORDER_RETRY_COUNT):
                if remaining <= 0:
                    break
                seq.attempts += 1

                orderbook = await self._ctx.exchange.get_orderbook(stock_code)
                limit_price = orderbook.bid_1
                if limit_price <= 0:
                    break

                order = await self._ctx.exchange.send_order(
                    stock_code=stock_code,
                    side=V71OrderSide.SELL,
                    quantity=remaining,
                    price=limit_price,
                    order_type=V71OrderType.LIMIT,
                )

                await self._ctx.clock.sleep(V71Constants.ORDER_WAIT_SECONDS)

                status = await self._ctx.exchange.get_order_status(order.order_id)
                if status.filled_quantity > 0:
                    fill_price = status.avg_fill_price or limit_price
                    seq.add_fill(status.filled_quantity, fill_price)
                    remaining -= status.filled_quantity

                if status.is_open and remaining > 0:
                    with contextlib.suppress(KiwoomAPIError):
                        await self._ctx.exchange.cancel_order(
                            order_id=order.order_id, stock_code=stock_code
                        )

        if remaining > 0:
            seq.attempts += 1
            market = await self._ctx.exchange.send_order(
                stock_code=stock_code,
                side=V71OrderSide.SELL,
                quantity=remaining,
                price=0,
                order_type=V71OrderType.MARKET,
            )
            await self._ctx.clock.sleep(2)
            status = await self._ctx.exchange.get_order_status(market.order_id)
            if status.filled_quantity > 0:
                fill_price = status.avg_fill_price or status.filled_quantity
                seq.add_fill(status.filled_quantity, fill_price)

        return seq

    # ------------------------------------------------------------------
    # Internal: full-exit cleanup (§5.9)
    # ------------------------------------------------------------------

    async def _on_full_exit(self, position: PositionState) -> None:
        position.status = "CLOSED"
        position.closed_at = self._ctx.clock.now()

        # §5.9: cancel sibling WAITING boxes on the same tracked_stock.
        self._ctx.box_manager.cancel_waiting_for_tracked(
            position.tracked_stock_id,
            reason="POSITION_CLOSED",
        )

        # P3.6: price-feed unsubscribe / dashboard refresh.
        if self._ctx.on_position_closed is not None:
            await self._ctx.on_position_closed(
                position.stock_code, position.position_id
            )

    # ------------------------------------------------------------------
    # Internal: failure paths
    # ------------------------------------------------------------------

    async def _reject(
        self, position: PositionState, exit_reason: str, message: str
    ) -> ExitOutcome:
        await self._ctx.notifier.notify(
            severity="CRITICAL",
            event_type="EXIT_REJECTED",
            stock_code=position.stock_code,
            message=(
                f"[{position.stock_code}] {exit_reason} 청산 거부: {message}"
            ),
            rate_limit_key=f"exit_reject:{position.stock_code}:{exit_reason}",
        )
        return ExitOutcome(
            status=ExitOutcomeStatus.REJECTED,
            stock_code=position.stock_code,
            position_id=position.position_id,
            reason=f"REJECTED_{exit_reason}",
        )

    async def _fail(
        self, position: PositionState, exit_reason: str, message: str
    ) -> ExitOutcome:
        await self._ctx.notifier.notify(
            severity="CRITICAL",
            event_type="EXIT_FAILED",
            stock_code=position.stock_code,
            message=(
                f"[{position.stock_code}] {exit_reason} 청산 실패: {message}"
            ),
            rate_limit_key=f"exit_fail:{position.stock_code}:{exit_reason}",
        )
        return ExitOutcome(
            status=ExitOutcomeStatus.FAILED,
            stock_code=position.stock_code,
            position_id=position.position_id,
            reason=f"FAILED_{exit_reason}",
        )


__all__ = [
    "ExitExecutorContext",
    "ExitOutcome",
    "ExitOutcomeStatus",
    "OnPositionClosed",
    "V71ExitExecutor",
]
