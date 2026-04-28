"""V71BoxEntryDetector -- bar-completion entry checks.

Spec:
  - 02_TRADING_RULES.md §3.8~§3.11 (entry conditions)
  - 02_TRADING_RULES.md §4         (buy execution)
  - 04_ARCHITECTURE.md §5.3

Phase: P3.2

Responsibilities:
  - subscribe to CandleManager bar-complete events for a single path
  - on each completed candle, look up active WAITING boxes for the
    ``(stock_code, path_type)`` group from V71BoxManager
  - call :func:`evaluate_box_entry` -- never re-derives conditions
  - on a positive :class:`EntryDecision`, invoke ``on_entry`` (typically
    :meth:`V71BuyExecutor.on_entry_decision`)
  - propagate ``fallback_buy_at`` for the PATH_B 09:05 safety net
    (§10.9) -- the executor handles the actual scheduling

One-detector-per-path: the caller picks PATH_A (3-min) or PATH_B
(daily) when constructing. Mixing paths in a single detector is a
mistake -- ``box.path_type`` and ``candle.timeframe`` must agree.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from src.core.v71.box.box_manager import BoxRecord, V71BoxManager
from src.core.v71.candle.types import V71Candle as Candle
from src.core.v71.skills.box_entry_skill import (
    Box,
    EntryDecision,
    MarketContext,
    PathType,
    evaluate_box_entry,
)
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# Async callback shape: detector -> buy executor.
# The detector hands the executor both the decision (with fallback metadata)
# and the BoxRecord so the executor can mark_triggered + look up tier/stock.
OnEntryCallback = Callable[[EntryDecision, BoxRecord], Awaitable[object]]


class CandleSource(Protocol):
    """Minimal interface the detector requires from CandleManager.

    Concrete implementation lives in V7.0 ``src.core.candle_builder``;
    Protocol here lets unit tests fake the subscription without pulling
    the real subscription manager.
    """

    def subscribe_bar_complete(
        self, callback: Callable[[Candle], None]
    ) -> None: ...


# stock_code -> tracked_stock_id (or None if not tracked on this path).
TrackedIdResolver = Callable[[str], str | None]

# (candle) -> MarketContext (current_time, VI flags, market_open).
MarketContextProvider = Callable[[Candle], MarketContext]


class V71BoxEntryDetector:
    """Bar-completion -> evaluate_box_entry -> dispatch coordinator.

    One instance per :class:`PathType`. The detector caches the previous
    bar per stock so PULLBACK_PATH_A (which needs both bars) works
    without the candle source carrying that responsibility.
    """

    def __init__(
        self,
        *,
        path_type: PathType,
        candle_source: CandleSource,
        box_manager: V71BoxManager,
        on_entry: OnEntryCallback,
        resolve_tracked_id: TrackedIdResolver,
        market_context: MarketContextProvider,
    ) -> None:
        require_enabled("v71.box_system")
        self._path_type: PathType = path_type
        self._candle_source = candle_source
        self._box_manager = box_manager
        self._on_entry = on_entry
        self._resolve_tracked_id = resolve_tracked_id
        self._market_context = market_context
        # Per-stock previous-candle cache (PULLBACK PATH_A needs it).
        self._prev: dict[str, Candle] = {}
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register the bar-complete callback with the source.

        Idempotent: calling twice is a no-op so callers can re-arm after
        a reconnect without bookkeeping.
        """
        if self._started:
            return
        self._candle_source.subscribe_bar_complete(self._on_bar_complete_sync)
        self._started = True

    # ------------------------------------------------------------------
    # Sync hook for V7.0 CandleManager
    # ------------------------------------------------------------------

    def _on_bar_complete_sync(self, candle: Candle) -> None:
        """V7.0 CandleManager invokes this synchronously.

        We schedule the async :meth:`check_entry` on the running loop
        and swallow failures so a V7.1 bug never crashes the V7.0 pipeline.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.warning(
                "No running loop in _on_bar_complete_sync (stock=%s); "
                "skipping bar.",
                candle.stock_code,
            )
            return
        loop.create_task(self.check_entry(candle))

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    async def check_entry(self, completed_candle: Candle) -> list[object]:
        """Evaluate every active WAITING box for the candle's stock+path.

        Returns:
            List of whatever ``on_entry`` returned for positive decisions
            (typically :class:`BuyOutcome`). Empty when no boxes triggered.
        """
        stock_code = completed_candle.stock_code
        prev = self._prev.get(stock_code)
        # Update prev for next bar BEFORE running checks so re-entrancy on
        # the same stock starts fresh.
        self._prev[stock_code] = completed_candle

        tracked_id = self._resolve_tracked_id(stock_code)
        if tracked_id is None:
            # Not a tracked stock for this path -- common, just exit.
            return []

        boxes = self._box_manager.list_waiting_for_tracked(
            tracked_id, self._path_type
        )
        if not boxes:
            return []

        market_ctx = self._market_context(completed_candle)
        outcomes: list[object] = []
        for box_record in boxes:
            decision = self._evaluate_one(
                box_record=box_record,
                current_candle=completed_candle,
                previous_candle=prev,
                market_context=market_ctx,
            )
            if decision is None or not decision.should_enter:
                continue
            try:
                outcome = await self._on_entry(decision, box_record)
            except Exception:  # noqa: BLE001 -- one box mustn't kill the bar
                log.exception(
                    "on_entry callback failed for box=%s stock=%s",
                    box_record.id,
                    stock_code,
                )
                continue
            outcomes.append(outcome)
        return outcomes

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _evaluate_one(
        self,
        *,
        box_record: BoxRecord,
        current_candle: Candle,
        previous_candle: Candle | None,
        market_context: MarketContext,
    ) -> EntryDecision | None:
        """Adapt :class:`BoxRecord` -> :class:`Box` and call the skill.

        Catches :class:`ValueError` (bad inputs) so a single malformed box
        cannot drop the whole bar.
        """
        # Sanity: the box's path_type must match this detector's.
        if box_record.path_type != self._path_type:
            log.warning(
                "Skipping box=%s with path=%s on detector path=%s",
                box_record.id,
                box_record.path_type,
                self._path_type,
            )
            return None

        box = Box(
            upper_price=box_record.upper_price,
            lower_price=box_record.lower_price,
            strategy_type=box_record.strategy_type,
            path_type=box_record.path_type,
        )
        try:
            return evaluate_box_entry(
                box=box,
                current_candle=current_candle,
                previous_candle=previous_candle,
                market_context=market_context,
            )
        except ValueError as e:
            log.warning(
                "evaluate_box_entry rejected box=%s stock=%s: %s",
                box_record.id,
                current_candle.stock_code,
                e,
            )
            return None


__all__ = [
    "CandleSource",
    "OnEntryCallback",
    "TrackedIdResolver",
    "MarketContextProvider",
    "V71BoxEntryDetector",
]
