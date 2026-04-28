"""V71CandleManager -- multi-stock candle dispatcher.

Spec:
  - 02_TRADING_RULES.md §4 (PATH_A 3분봉 + PATH_B 일봉)
  - 02_TRADING_RULES.md §7 (폴링 전략)
  - 04_ARCHITECTURE.md §5.3

Architect Q8 decision: explicit ``add_stock`` / ``remove_stock`` API.
The manager does NOT depend on V71BoxManager (that's the wiring caller's
job) — keeps dependency arrows one-way.

Responsibilities:
  * Per-stock V71ThreeMinuteCandleBuilder (PRICE_TICK aggregation)
  * Per-stock V71DailyCandleBuilder (ka10081 EOD polling)
  * V71KiwoomWebSocket PRICE_TICK message → tick → builder routing
  * EOD scheduler asyncio.Task (15:35 daily fetch)
  * Subscriber fan-out: register_on_complete(callback) registers on
    every existing + future builder (so box_entry_detector can subscribe
    once and receive both 3분봉 and 일봉 events)

Failure isolation:
  * One bad PRICE_TICK message → WARNING + skip, others continue
  * EOD fetch failure for one stock → other stocks proceed
  * Subscriber callback failure → other subscribers continue
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.core.v71.candle.types import V71Candle, V71Tick, message_to_tick
from src.core.v71.candle.v71_daily_builder import V71DailyCandleBuilder
from src.core.v71.candle.v71_three_minute_builder import (
    V71ThreeMinuteCandleBuilder,
)

log = logging.getLogger(__name__)


OnCandleCompleteFn = Callable[[V71Candle], Awaitable[None]]


class V71CandleManager:
    """Multi-stock candle dispatcher.

    Construction is cheap (no IO). Call :meth:`add_stock` for each
    tracked stock. The manager registers itself as a PRICE_TICK handler
    on the V71KiwoomWebSocket; the EOD scheduler is started via
    :meth:`start_eod_scheduler`.
    """

    def __init__(
        self,
        *,
        kiwoom_client: Any,
        kiwoom_websocket: Any,
        eod_fetch_provider: Callable[[], str] | None = None,
    ) -> None:
        """
        Args:
            kiwoom_client: V71KiwoomClient (for ka10081 EOD).
            kiwoom_websocket: V71KiwoomWebSocket (PRICE_TICK source).
            eod_fetch_provider: optional callable returning the YYYYMMDD
                string for the next EOD fetch. Default = today's date in
                KST. Tests inject deterministic values.
        """
        self._kiwoom = kiwoom_client
        self._ws = kiwoom_websocket
        self._eod_provider = eod_fetch_provider or _default_eod_date
        self._three_min: dict[str, V71ThreeMinuteCandleBuilder] = {}
        self._daily: dict[str, V71DailyCandleBuilder] = {}
        self._subscribers: list[OnCandleCompleteFn] = []
        self._handler_registered = False
        self._eod_task: asyncio.Task[None] | None = None
        self._eod_stop = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register the PRICE_TICK handler. Idempotent."""
        if self._handler_registered:
            return
        from src.core.v71.exchange.kiwoom_websocket import V71KiwoomChannelType
        self._ws.register_handler(
            V71KiwoomChannelType.PRICE_TICK, self._on_price_message,
        )
        self._handler_registered = True

    async def stop(self) -> None:
        """Stop the EOD scheduler (if running) + flush in-progress 3분봉
        buckets so the final candle of the session is dispatched."""
        if self._eod_task is not None and not self._eod_task.done():
            self._eod_stop.set()
            self._eod_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._eod_task
            self._eod_task = None
        for builder in self._three_min.values():
            try:
                await builder.flush()
            except Exception as exc:  # noqa: BLE001 -- best effort
                log.warning(
                    "v71_candle_manager: flush failed for %s: %s",
                    builder.stock_code, type(exc).__name__,
                )

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def add_stock(self, stock_code: str) -> None:
        """Register a stock for both 3분봉 and 일봉 tracking. Idempotent."""
        if stock_code not in self._three_min:
            tm = V71ThreeMinuteCandleBuilder(stock_code)
            for cb in self._subscribers:
                tm.register_on_complete(cb)
            self._three_min[stock_code] = tm
        if stock_code not in self._daily:
            d = V71DailyCandleBuilder(
                stock_code, kiwoom_client=self._kiwoom,
            )
            for cb in self._subscribers:
                d.register_on_complete(cb)
            self._daily[stock_code] = d

    def remove_stock(self, stock_code: str) -> None:
        """Drop a stock from tracking. Idempotent. Builders are dropped
        without flushing in-progress buckets — caller is responsible for
        ordering vs ``stop()`` if a final candle is needed."""
        self._three_min.pop(stock_code, None)
        self._daily.pop(stock_code, None)

    def register_on_complete(self, callback: OnCandleCompleteFn) -> None:
        """Subscribe to candle-complete events. Registers on all existing
        AND future builders (re-registration on add_stock)."""
        self._subscribers.append(callback)
        for tm in self._three_min.values():
            tm.register_on_complete(callback)
        for d in self._daily.values():
            d.register_on_complete(callback)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def get_three_minute_builder(
        self, stock_code: str,
    ) -> V71ThreeMinuteCandleBuilder | None:
        return self._three_min.get(stock_code)

    def get_daily_builder(
        self, stock_code: str,
    ) -> V71DailyCandleBuilder | None:
        return self._daily.get(stock_code)

    def tracked_stocks(self) -> tuple[str, ...]:
        return tuple(sorted(self._three_min))

    # ------------------------------------------------------------------
    # PRICE_TICK plumbing
    # ------------------------------------------------------------------

    async def _on_price_message(self, message: Any) -> None:
        """V71KiwoomWebSocket PRICE_TICK handler. Routes the tick to
        the appropriate per-stock builder."""
        tick: V71Tick | None = message_to_tick(message)
        if tick is None:
            return  # message_to_tick already logged WARNING
        builder = self._three_min.get(tick.stock_code)
        if builder is None:
            return  # not tracked; common during boot before add_stock
        try:
            await builder.on_tick(tick)
        except Exception as exc:  # noqa: BLE001 -- handler isolation
            log.warning(
                "v71_candle_manager: on_tick failed for %s: %s",
                tick.stock_code, type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # EOD scheduler (architect Q5/Q7)
    # ------------------------------------------------------------------

    async def start_eod_scheduler(
        self, *, interval_seconds: float = 60.0,
    ) -> None:
        """Spin up the EOD daily-poll loop. Idempotent.

        ``interval_seconds`` is the wake-up cadence; the loop checks
        whether the configured EOD time has been reached and only then
        fires fetch_eod for each tracked stock. Tests pass a small value
        for fast iteration.
        """
        if self._eod_task is not None and not self._eod_task.done():
            return
        self._eod_stop.clear()
        self._eod_task = asyncio.create_task(
            self._eod_loop(interval_seconds),
            name="v71_candle_eod_scheduler",
        )

    async def fetch_eod_for_all(self, base_date: str) -> int:
        """Trigger ka10081 EOD fetch for every tracked stock. Returns
        the count of stocks where a NEW candle landed (idempotent days
        + parse errors don't count). Caller drives this; the EOD scheduler
        is just one such caller."""
        new_count = 0
        for builder in tuple(self._daily.values()):
            try:
                candle = await builder.fetch_eod(base_date=base_date)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "v71_candle_manager: fetch_eod failed for %s: %s",
                    builder.stock_code, type(exc).__name__,
                )
                continue
            if candle is not None:
                new_count += 1
        return new_count

    async def fetch_history_for_all(self, base_date: str) -> int:
        """Boot-time bulk priming of daily builders. Returns total
        candles cached across all stocks (silent — no dispatch)."""
        total = 0
        for builder in tuple(self._daily.values()):
            try:
                total += await builder.fetch_history(base_date=base_date)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "v71_candle_manager: fetch_history failed for %s: %s",
                    builder.stock_code, type(exc).__name__,
                )
        return total

    async def _eod_loop(self, interval_seconds: float) -> None:
        from src.core.v71.v71_constants import V71Constants

        target_hhmm = V71Constants.DAILY_CANDLE_FETCH_HHMM
        last_fetched_date: str | None = None
        while not self._eod_stop.is_set():
            try:
                base_date = self._eod_provider()
                # Trigger only after the configured wall-clock time and
                # only once per date.
                if (
                    _is_after_hhmm(target_hhmm)
                    and last_fetched_date != base_date
                ):
                    new = await self.fetch_eod_for_all(base_date)
                    last_fetched_date = base_date
                    log.info(
                        "v71_candle_manager: EOD fetch base_date=%s "
                        "new_candles=%d",
                        base_date, new,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- always-run policy
                log.warning(
                    "v71_candle_manager: EOD loop tick failed: %s",
                    type(exc).__name__,
                )
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                raise


def _default_eod_date() -> str:
    """Default EOD base_date provider: today (system local) as YYYYMMDD."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d")


def _is_after_hhmm(hhmm: str) -> bool:
    """True if current local time >= hhmm. Format ``HH:MM``."""
    from datetime import datetime
    h, m = hhmm.split(":", 1)
    target_minutes = int(h) * 60 + int(m)
    now = datetime.now()
    current_minutes = now.hour * 60 + now.minute
    return current_minutes >= target_minutes


__all__ = ["V71CandleManager"]
