"""V71BaseCandleBuilder Protocol -- common interface for 3분봉 + 일봉 builders.

Spec:
  - 02_TRADING_RULES.md §4.1/§4.2/§4.3 (3분봉 / 일봉)
  - 04_ARCHITECTURE.md §5.3

Architect Q2 decision: Protocol (not ABC). The 3분봉 (PRICE_TICK
aggregation) and 일봉 (ka10081 EOD polling) builders have fundamentally
different input shapes; Protocol enforces only the common surface.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from src.core.v71.candle.types import V71Candle
from src.core.v71.v71_constants import V71Timeframe

# Async callback fired when a candle bucket closes. Caller (CandleManager)
# fan-outs to box_entry_detector + indicator subscribers.
OnCandleCompleteFn = Callable[[V71Candle], Awaitable[None]]


@runtime_checkable
class V71BaseCandleBuilder(Protocol):
    """Common surface for V71ThreeMinuteCandleBuilder + V71DailyCandleBuilder.

    Implementations MUST keep ``stock_code`` and ``timeframe`` as
    instance attributes (Protocol checks). They MUST also expose
    :meth:`get_candles` returning a ``tuple`` so callers cannot mutate
    internal state.
    """

    stock_code: str
    timeframe: V71Timeframe

    def get_candles(self, n: int | None = None) -> tuple[V71Candle, ...]:
        """Return up to ``n`` most recent completed candles (oldest first).
        ``None`` means "all"."""
        ...

    def register_on_complete(self, callback: OnCandleCompleteFn) -> None:
        """Subscribe to bucket-close events. Multiple subscribers fire in
        registration order; one raising must not block others (handler
        isolation policy mirrors V71KiwoomWebSocket)."""
        ...

    def unregister_on_complete(self, callback: OnCandleCompleteFn) -> None:
        """Idempotent removal. Pairs with :meth:`register_on_complete`
        so subscribers (V71BoxEntryDetector etc.) can detach cleanly
        without leaking refs into the builder's subscriber list.

        Raises nothing if ``callback`` was never registered (defensive
        for re-attach cycles where the same detector instance might be
        unregistered twice during overlapping shutdowns)."""
        ...


__all__ = ["OnCandleCompleteFn", "V71BaseCandleBuilder"]
