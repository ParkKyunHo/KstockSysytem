"""V71ThreeMinuteCandleBuilder -- PRICE_TICK aggregation into 3분봉.

Spec:
  - 02_TRADING_RULES.md §4.1 (PATH_A 눌림: 3분봉 N-1 + N)
  - 02_TRADING_RULES.md §4.2 (PATH_A 돌파: 3분봉 N)

Per-stock stateful builder. Buckets ticks into 3-minute boundaries
(``[09:00, 09:03), [09:03, 09:06), ...``). When a tick arrives in a
new bucket, the previous bucket's OHLCV is finalised into a
:class:`V71Candle` and dispatched to registered subscribers.

Memory: deque(maxlen=CANDLE_HISTORY_PER_STOCK_MAX) caps history per
stock so a long-running session never grows unbounded (architect Q6).

Failure isolation: subscriber callbacks are awaited individually with
try/except so a buggy box_entry_detector cannot block a slow indicator.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from src.core.v71.candle.types import V71Candle, V71Tick
from src.core.v71.v71_constants import V71Constants, V71Timeframe

log = logging.getLogger(__name__)


OnCandleCompleteFn = Callable[[V71Candle], Awaitable[None]]


def _bucket_start(timestamp: datetime) -> datetime:
    """Floor ``timestamp`` to the nearest 3-minute boundary (same date,
    same hour). Microseconds + seconds discarded."""
    rounded_minute = (timestamp.minute // 3) * 3
    return timestamp.replace(
        minute=rounded_minute, second=0, microsecond=0,
    )


class _Bucket:
    """In-progress 3-minute bucket state. Mutable (one alive at a time)."""

    __slots__ = (
        "close", "high", "low", "open", "start", "tick_count", "volume",
    )

    def __init__(self, *, start: datetime, first_tick: V71Tick) -> None:
        self.start: datetime = start
        self.open: int = first_tick.price
        self.high: int = first_tick.price
        self.low: int = first_tick.price
        self.close: int = first_tick.price
        self.volume: int = first_tick.volume
        self.tick_count: int = 1

    def add(self, tick: V71Tick) -> None:
        if tick.price > self.high:
            self.high = tick.price
        if tick.price < self.low:
            self.low = tick.price
        self.close = tick.price
        self.volume += tick.volume
        self.tick_count += 1

    def to_candle(self, *, stock_code: str) -> V71Candle:
        return V71Candle(
            stock_code=stock_code,
            timeframe=V71Timeframe.THREE_MINUTE,
            timestamp=self.start,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            tick_count=self.tick_count,
        )


class V71ThreeMinuteCandleBuilder:
    """Per-stock 3분봉 builder.

    Implements :class:`V71BaseCandleBuilder` Protocol (duck-typed).
    """

    def __init__(
        self,
        stock_code: str,
        *,
        history_max: int | None = None,
    ) -> None:
        self.stock_code: str = stock_code
        self.timeframe: V71Timeframe = V71Timeframe.THREE_MINUTE
        self._history: deque[V71Candle] = deque(
            maxlen=history_max
            if history_max is not None
            else V71Constants.CANDLE_HISTORY_PER_STOCK_MAX,
        )
        self._current: _Bucket | None = None
        self._subscribers: list[OnCandleCompleteFn] = []

    # ------------------------------------------------------------------
    # Public API (Protocol surface)
    # ------------------------------------------------------------------

    def get_candles(self, n: int | None = None) -> tuple[V71Candle, ...]:
        """Return up to ``n`` most recent completed candles (oldest first)."""
        if n is None:
            return tuple(self._history)
        if n <= 0:
            return ()
        # deque slicing: convert to tuple then take last n
        return tuple(self._history)[-n:]

    def register_on_complete(self, callback: OnCandleCompleteFn) -> None:
        self._subscribers.append(callback)

    # ------------------------------------------------------------------
    # Tick ingestion
    # ------------------------------------------------------------------

    async def on_tick(self, tick: V71Tick) -> None:
        """Add a tick to the in-progress bucket; emit a candle when the
        bucket boundary advances.

        Stock_code mismatch is treated as a programming error -- caller
        (CandleManager) MUST route ticks to the right builder.
        """
        if tick.stock_code != self.stock_code:
            log.warning(
                "v71_3m_builder: stock_code mismatch (got %s, expected %s) "
                "-- skipping",
                tick.stock_code, self.stock_code,
            )
            return
        bucket_start = _bucket_start(tick.timestamp)
        if self._current is None:
            self._current = _Bucket(start=bucket_start, first_tick=tick)
            return
        if bucket_start == self._current.start:
            self._current.add(tick)
            return
        if bucket_start < self._current.start:
            # Out-of-order tick crossing buckets -- ignore + WARNING.
            # The candle for this older bucket has already been emitted.
            log.warning(
                "v71_3m_builder: out-of-order tick for %s "
                "(tick=%s, bucket=%s) -- dropping",
                self.stock_code, tick.timestamp.isoformat(),
                self._current.start.isoformat(),
            )
            return
        # Bucket advanced -- finalise the previous bucket, dispatch, start new.
        finalised = self._current.to_candle(stock_code=self.stock_code)
        self._current = _Bucket(start=bucket_start, first_tick=tick)
        self._history.append(finalised)
        await self._dispatch(finalised)

    async def flush(self) -> V71Candle | None:
        """Force-close the in-progress bucket (e.g., end-of-session at
        15:30). Returns the finalised candle if any. Idempotent.
        """
        if self._current is None:
            return None
        finalised = self._current.to_candle(stock_code=self.stock_code)
        self._current = None
        self._history.append(finalised)
        await self._dispatch(finalised)
        return finalised

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _dispatch(self, candle: V71Candle) -> None:
        for cb in tuple(self._subscribers):
            try:
                await cb(candle)
            except Exception as exc:  # noqa: BLE001 -- handler isolation
                log.warning(
                    "v71_3m_builder_subscriber_failed for %s: %s",
                    self.stock_code, type(exc).__name__,
                )

    @staticmethod
    def bucket_window(timestamp: datetime) -> tuple[datetime, datetime]:
        """Return ``(start, end)`` of the 3-minute bucket containing
        ``timestamp``. Surfaced for tests + V71CandleManager scheduler."""
        start = _bucket_start(timestamp)
        return start, start + timedelta(seconds=V71Constants.CANDLE_THREE_MINUTE_SECONDS)


__all__ = [
    "OnCandleCompleteFn",
    "V71ThreeMinuteCandleBuilder",
]
