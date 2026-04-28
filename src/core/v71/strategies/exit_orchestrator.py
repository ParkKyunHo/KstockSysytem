"""V71ExitOrchestrator -- glue between WebSocket PRICE_TICK and the
exit decision/execution pipeline.

Spec:
  - 02_TRADING_RULES.md §5 (post-buy management)
  - 02_TRADING_RULES.md §10.4 (VI 해제 후 1초 내 stop/TS 발동 -- NFR1)
  - 04_ARCHITECTURE.md §5.3

Phase: P-Wire-6

The Phase 3 building blocks ship as pure modules:

    PRICE_TICK ──┐                ┌── V71ExitExecutor.execute_stop_loss
                 │                ├── V71ExitExecutor.execute_ts_exit
                 ▼                └── V71ExitExecutor.execute_profit_take
            V71ExitCalculator.on_tick(pos, price, atr) -> ExitDecision
                              ▲
                  V71PositionManager.list_for_stock

This module wires those three together inside one async-friendly class
that owns:

  * Per-stock subscribe/unsubscribe lifecycle on the V71KiwoomWebSocket.
  * A single global PRICE_TICK handler that fans out to every open
    position on the incoming stock.
  * A per-stock asyncio.Lock so a burst of ticks for the same stock
    cannot trigger duplicate exits (idempotency complements the
    ExitExecutor's own state mutations).
  * An ATR cache the orchestrator reads from -- production wiring
    refreshes it externally (e.g. via an indicator job that walks
    ka10081 daily bars).

Constitution:
  * §1 user judgment: stop/profit decisions come from
    :class:`V71ExitCalculator` only -- the orchestrator never invents a
    price or short-circuits a check.
  * §2 NFR1: VI resolved → :meth:`reevaluate_stock` re-runs the pipeline
    immediately so PRD §10.4 1-second budget can be met.
  * §4 always-on: every handler is wrapped to log + swallow exceptions
    so a single tick failure cannot starve the rest of the queue.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.core.v71.exchange.kiwoom_websocket import (
    V71KiwoomChannelType,
    V71WebSocketMessage,
)
from src.utils.feature_flags import require_enabled

if TYPE_CHECKING:
    # Heavy imports (exit_executor pulls kiwoom_api_skill →
    # exchange.__init__ which has a known circular boot-time path).
    # Type-only imports stay outside the runtime graph.
    from src.core.v71.exit.exit_calculator import (
        ExitDecision,
        V71ExitCalculator,
    )
    from src.core.v71.exit.exit_executor import V71ExitExecutor
    from src.core.v71.position.state import PositionState

log = logging.getLogger(__name__)


# Common 0B (체결) WebSocket payload field aliases. The wire-level
# canonical name is confirmed in P-Wire-5 paper smoke; the orchestrator
# stays permissive in the interim so receiving an unknown shape produces
# a structured WARNING rather than a silent miss.
_PRICE_TICK_KEYS = ("10", "stck_prpr", "cur_prc", "current_price")


# Async callable supplied by the buy executor / orchestrator wiring -- it
# tells the price feed which stock_code to start streaming for.
SubscribeFn = Callable[[V71KiwoomChannelType, str], Any]
UnsubscribeFn = Callable[[V71KiwoomChannelType, str], Any]


class V71ExitOrchestrator:
    """Glue object that drives the exit pipeline from WebSocket ticks.

    Attach pattern:

        orch = V71ExitOrchestrator(
            position_manager=pm,
            exit_calculator=calc,
            exit_executor=executor,
            websocket=ws,
        )
        await orch.start()
        # Buy executor calls: await orch.subscribe("005930") on FILLED
        # ExitExecutor calls: await orch.on_position_closed("005930", pid)

    The handler is registered on ``start()`` and never re-registered on
    its own; ``stop()`` is idempotent and safe to call from detach.
    """

    def __init__(
        self,
        *,
        position_manager: Any,
        exit_calculator: V71ExitCalculator,
        exit_executor: V71ExitExecutor,
        websocket: Any,
        exchange: Any | None = None,
        atr_cache: dict[str, float] | None = None,
    ) -> None:
        require_enabled("v71.exit_v71")
        self._pm = position_manager
        self._calc = exit_calculator
        self._executor = exit_executor
        self._ws = websocket
        # Optional exchange for VI resume current-price fetch (P-Wire-7).
        # Tests can pass None and use the explicit-price reevaluate_stock.
        self._exchange = exchange
        self._atr_cache: dict[str, float] = atr_cache if atr_cache is not None else {}
        self._subscribed: set[str] = set()
        self._stock_locks: dict[str, asyncio.Lock] = {}
        self._handler_registered = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register the PRICE_TICK handler. Idempotent."""
        if self._handler_registered:
            return
        self._ws.register_handler(
            V71KiwoomChannelType.PRICE_TICK, self._handle_price_message,
        )
        self._handler_registered = True

    async def stop(self) -> None:
        """Best-effort unsubscribe and detach. Idempotent."""
        for stock_code in tuple(self._subscribed):
            try:
                await self._ws.unsubscribe(
                    V71KiwoomChannelType.PRICE_TICK, stock_code,
                )
            except Exception as exc:  # noqa: BLE001 -- best effort
                log.warning(
                    "v71_exit_orch_unsubscribe_failed: %s",
                    type(exc).__name__,
                )
        self._subscribed.clear()
        # Handler unregister is intentionally not attempted -- the WS
        # client tears its handler list down on aclose() anyway, and
        # double-stop must remain safe.

    # ------------------------------------------------------------------
    # Per-stock subscription
    # ------------------------------------------------------------------

    async def subscribe(self, stock_code: str) -> None:
        """Add ``stock_code`` to the PRICE_TICK feed.

        Buy executor calls this after a position FILLs so the price
        stream begins flowing for the position's life.
        """
        if stock_code in self._subscribed:
            return
        await self._ws.subscribe(V71KiwoomChannelType.PRICE_TICK, stock_code)
        self._subscribed.add(stock_code)

    async def unsubscribe(self, stock_code: str) -> None:
        """Remove ``stock_code`` from the PRICE_TICK feed.

        Caller must guarantee no remaining open positions on the stock;
        the orchestrator does NOT re-check (cheap O(1) and the caller
        owns the position lifecycle).
        """
        if stock_code not in self._subscribed:
            return
        try:
            await self._ws.unsubscribe(
                V71KiwoomChannelType.PRICE_TICK, stock_code,
            )
        except Exception as exc:  # noqa: BLE001 -- best effort
            log.warning(
                "v71_exit_orch_unsubscribe_failed: %s",
                type(exc).__name__,
            )
        self._subscribed.discard(stock_code)
        # Drop the per-stock lock + ATR entry so memory does not grow
        # unbounded across the trading day.
        self._stock_locks.pop(stock_code, None)
        self._atr_cache.pop(stock_code, None)

    # ------------------------------------------------------------------
    # Callbacks (wirable from BuyExecutor / ExitExecutor / ViMonitor)
    # ------------------------------------------------------------------

    async def on_position_closed(
        self, stock_code: str, position_id: str,  # noqa: ARG002
    ) -> None:
        """Wireable as :class:`ExitExecutorContext.on_position_closed`.

        Triggers an unsubscribe IFF no remaining open positions on the
        stock so the price feed is not dropped while sibling boxes (PRD
        §3.7) still hold open quantity.
        """
        if not self._has_open_position(stock_code):
            await self.unsubscribe(stock_code)

    async def reevaluate_stock(
        self, stock_code: str, current_price: int,
    ) -> None:
        """Direct entry point -- caller already has the price.

        Used by tests + paper-smoke harnesses. Production callers
        normally go through :meth:`on_vi_resumed` which fetches the
        price first.
        """
        await self._evaluate_stock(stock_code, current_price)

    async def on_vi_resumed(
        self, stock_code: str,
        *, exchange: Any | None = None,
    ) -> None:
        """ViMonitorContext.on_vi_resumed-compatible signature.

        PRD §10.4 mandates a 1-second window from VI 해제 to stop/TS
        re-evaluation. ViMonitor passes only ``stock_code``; this method
        fetches the resume-price via the injected ``exchange`` (or a
        cached one captured at construction) and delegates to
        :meth:`reevaluate_stock`. Failures fall through to the next
        PRICE_TICK so a single transient kiwoom error does not break
        the §4 always-running invariant.
        """
        ex = exchange if exchange is not None else self._exchange
        if ex is None:
            log.warning(
                "v71_exit_orch_vi_resumed_no_exchange for %s -- next "
                "PRICE_TICK will catch up",
                stock_code,
            )
            return
        try:
            current_price = await ex.get_current_price(stock_code)
        except Exception as exc:  # noqa: BLE001 -- next tick fallback
            log.warning(
                "v71_exit_orch_vi_resumed_fetch_failed for %s: %s",
                stock_code, type(exc).__name__,
            )
            return
        if not isinstance(current_price, int) or current_price <= 0:
            log.warning(
                "v71_exit_orch_vi_resumed_invalid_price for %s",
                stock_code,
            )
            return
        await self._evaluate_stock(stock_code, current_price)

    # ------------------------------------------------------------------
    # PRICE_TICK plumbing
    # ------------------------------------------------------------------

    async def _handle_price_message(
        self, message: V71WebSocketMessage,
    ) -> None:
        """Parse the WS payload and dispatch to ``_evaluate_stock``."""
        try:
            stock_code = (message.item or "").strip().upper()
            if not stock_code:
                return
            values = message.values or {}
            raw = next(
                (values[k] for k in _PRICE_TICK_KEYS if k in values),
                None,
            )
            if raw is None:
                log.warning(
                    "v71_exit_orch_price_field_missing: tried=%s for %s",
                    _PRICE_TICK_KEYS, stock_code,
                )
                return
            try:
                current_price = int(str(raw).strip().lstrip("0") or "0")
            except (TypeError, ValueError):
                log.warning(
                    "v71_exit_orch_price_parse_failed for %s",
                    stock_code,
                )
                return
            if current_price <= 0:
                return
            await self._evaluate_stock(stock_code, current_price)
        except BaseException:  # noqa: BLE001 -- handler must never raise
            log.exception(
                "v71_exit_orch_handler_unhandled_exception"
            )

    async def _evaluate_stock(
        self, stock_code: str, current_price: int,
    ) -> None:
        lock = self._stock_locks.setdefault(stock_code, asyncio.Lock())
        async with lock:
            positions = list(self._pm.list_for_stock(stock_code))
            atr = self._atr_cache.get(stock_code, 0.0)
            for position in positions:
                if position.status == "CLOSED":
                    continue
                if position.total_quantity <= 0:
                    continue
                try:
                    decision = self._calc.on_tick(
                        position, current_price, atr,
                    )
                except Exception as exc:  # noqa: BLE001 -- isolation
                    log.warning(
                        "v71_exit_orch_calc_failed for %s/%s: %s",
                        stock_code, position.position_id,
                        type(exc).__name__,
                    )
                    continue
                await self._route_decision(position, decision)

    async def _route_decision(
        self, position: PositionState, decision: ExitDecision,
    ) -> None:
        """Translate ``ExitDecision`` to ExitExecutor calls."""
        try:
            if decision.stop_triggered:
                if decision.effective_stop.source == "TS":
                    await self._executor.execute_ts_exit(position)
                else:
                    await self._executor.execute_stop_loss(position)
                return
            if decision.profit_take.should_exit:
                await self._executor.execute_profit_take(
                    position, decision.profit_take,
                )
        except Exception as exc:  # noqa: BLE001 -- isolation
            log.warning(
                "v71_exit_orch_executor_failed for %s/%s: %s",
                position.stock_code, position.position_id,
                type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_open_position(self, stock_code: str) -> bool:
        return any(
            getattr(p, "status", "OPEN") != "CLOSED"
            for p in self._pm.list_for_stock(stock_code)
        )


__all__ = ["V71ExitOrchestrator"]
