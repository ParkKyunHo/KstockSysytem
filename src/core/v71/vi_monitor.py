"""V71ViMonitor -- VI event subscription + state machine driver.

Spec:
  - 02_TRADING_RULES.md §10 (VI handling)
  - 07_SKILLS_SPEC.md §5
  - 04_ARCHITECTURE.md §5.3

Phase: P3.6

Subscribes to Kiwoom VI events (TRIGGERED / RESUMED) and drives
:func:`vi_skill.handle_vi_state`.

Side effects on state transitions:
  - TRIGGERED: HIGH alert; pending stop checks for the stock are paused
    (downstream V71ExitCalculator consults :meth:`is_vi_active`); cancel
    in-flight non-VI buy orders is the buy executor's job, not ours.
  - RESUMED:   HIGH alert; fire ``on_vi_resumed`` callback so the
    orchestrator can re-evaluate every position on the stock within 1s
    (NFR1); after the callback returns, auto-resettle to NORMAL and set
    ``vi_recovered_today`` so no new entries fire today on this stock.
  - DAILY_RESET (next-day 09:00): wipe per-stock state + the
    ``vi_recovered_today`` set.

Storage:
    P3.6 keeps everything in-memory.  P3.4 V71PositionManager already
    owns position state; the VI monitor only owns the "VI-side" view.

Idempotency:
    A second VI_TRIGGERED while already TRIGGERED is silently ignored
    (logged WARNING).  Same for a second VI_RESOLVED.  Avoids duplicate
    alerts when WebSocket replays.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from src.core.v71.skills.vi_skill import (
    EVENT_VI_DETECTED,
    EVENT_VI_RESETTLED,
    EVENT_VI_RESOLVED,
    VIState,
    VIStateContext,
    handle_vi_state,
)
from src.core.v71.strategies.v71_buy_executor import Clock, Notifier
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# Async callback fired right after VI_RESOLVED, before auto-resettle.
# Caller (orchestrator) re-evaluates every active position on the stock
# (V71ExitCalculator pipeline) so that stop/TS triggers fire within 1s
# of resume.
OnViResumedFn = Callable[[str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Context (DI bundle)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ViMonitorContext:
    """Bundle of injected dependencies."""

    notifier: Notifier
    clock: Clock
    on_vi_resumed: OnViResumedFn | None = None
    """Optional re-evaluation hook fired during VI_RESOLVED handling.
    P3.7 wires it; P3.6 unit tests inject a fake."""


# ---------------------------------------------------------------------------
# V71ViMonitor
# ---------------------------------------------------------------------------

class V71ViMonitor:
    """Per-stock VI state tracker + event dispatcher (in-memory)."""

    def __init__(self, *, context: ViMonitorContext) -> None:
        require_enabled("v71.vi_monitor")
        self._ctx = context

        self._states: dict[str, VIState] = {}
        self._triggered_at: dict[str, datetime] = {}
        self._trigger_price: dict[str, int] = {}
        self._last_close_before_vi: dict[str, int] = {}

        # Set of stocks that have completed a VI cycle today; new entries
        # blocked on these (§10.6).  Cleared on :meth:`reset_daily`.
        self._recovered_today: set[str] = set()

    # ------------------------------------------------------------------
    # Queries (consumed by V71BuyExecutor + V71ExitCalculator)
    # ------------------------------------------------------------------

    def get_state(self, stock_code: str) -> VIState:
        return self._states.get(stock_code, VIState.NORMAL)

    def is_vi_active(self, stock_code: str) -> bool:
        """True iff stock is currently in TRIGGERED state.

        Bound to ``BuyExecutorContext.is_vi_active`` callable.
        """
        return self.get_state(stock_code) is VIState.TRIGGERED

    def is_vi_recovered_today(self, stock_code: str) -> bool:
        """True iff a VI cycle recovered on this stock today (§10.6).

        Bound to ``MarketContext.is_vi_recovered_today`` provider so
        :func:`evaluate_box_entry` can block new entries.
        """
        return stock_code in self._recovered_today

    def get_last_close_before_vi(self, stock_code: str) -> int | None:
        return self._last_close_before_vi.get(stock_code)

    # ------------------------------------------------------------------
    # WebSocket event handlers
    # ------------------------------------------------------------------

    async def on_vi_triggered(
        self,
        stock_code: str,
        *,
        trigger_price: int,
        last_close_before_vi: int,
    ) -> None:
        """WebSocket VI 발동 (9068=1) handler.

        Idempotent: a second TRIGGERED while already TRIGGERED is dropped
        with a WARNING.
        """
        current = self.get_state(stock_code)
        if current is VIState.TRIGGERED:
            log.warning(
                "VI_DETECTED received while already TRIGGERED for %s -- ignoring",
                stock_code,
            )
            return

        decision = handle_vi_state(
            VIStateContext(
                stock_code=stock_code,
                current_state=current,
                trigger_price=trigger_price,
                triggered_at=self._ctx.clock.now(),
                last_close_before_vi=last_close_before_vi,
                current_price=trigger_price,
            ),
            event=EVENT_VI_DETECTED,
        )
        self._states[stock_code] = decision.next_state
        self._triggered_at[stock_code] = self._ctx.clock.now()
        self._trigger_price[stock_code] = trigger_price
        self._last_close_before_vi[stock_code] = last_close_before_vi

        await self._ctx.notifier.notify(
            severity="HIGH",
            event_type="VI_TRIGGERED",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] VI 발동: 가격 {trigger_price}원, "
                f"단일가 매매 진입 (손절/익절 판정 일시 정지)"
            ),
            rate_limit_key=f"vi_triggered:{stock_code}",
        )

    async def on_vi_resolved(
        self,
        stock_code: str,
        *,
        first_price_after_resume: int,
    ) -> None:
        """WebSocket VI 해제 (9068=2) handler.

        Drives RESUMED -> on_vi_resumed callback -> auto-resettle to
        NORMAL with vi_recovered_today flag set (§10.6).

        Idempotent: a second RESOLVED while not TRIGGERED is dropped.
        """
        current = self.get_state(stock_code)
        if current is not VIState.TRIGGERED:
            log.warning(
                "VI_RESOLVED received but state is %s for %s -- ignoring",
                current.value,
                stock_code,
            )
            return

        decision = handle_vi_state(
            VIStateContext(
                stock_code=stock_code,
                current_state=current,
                trigger_price=self._trigger_price.get(stock_code),
                triggered_at=self._triggered_at.get(stock_code),
                last_close_before_vi=self._last_close_before_vi.get(stock_code),
                current_price=first_price_after_resume,
            ),
            event=EVENT_VI_RESOLVED,
        )
        self._states[stock_code] = decision.next_state  # RESUMED

        await self._ctx.notifier.notify(
            severity="HIGH",
            event_type="VI_RESUMED",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] VI 해제: 즉시 재평가 시작 "
                f"(시초가 {first_price_after_resume}원)"
            ),
            rate_limit_key=f"vi_resumed:{stock_code}",
        )

        # Re-evaluation hook (P3.7 wires it).  Must complete < 1s (NFR1).
        if self._ctx.on_vi_resumed is not None:
            try:
                await self._ctx.on_vi_resumed(stock_code)
            except Exception:  # noqa: BLE001 -- one stock cannot kill the loop
                log.exception(
                    "on_vi_resumed callback failed for %s", stock_code
                )

        # Auto-resettle: RESUMED -> NORMAL with vi_recovered_today.
        await self._auto_resettle(stock_code)

    # ------------------------------------------------------------------
    # Auto-resettle
    # ------------------------------------------------------------------

    async def _auto_resettle(self, stock_code: str) -> None:
        """RESUMED -> NORMAL after re-evaluation.  Marks vi_recovered_today.

        Internal call only; idempotent if state has already transitioned.
        """
        current = self.get_state(stock_code)
        if current is not VIState.RESUMED:
            log.warning(
                "_auto_resettle skipped for %s: state is %s",
                stock_code,
                current.value,
            )
            return

        decision = handle_vi_state(
            VIStateContext(
                stock_code=stock_code,
                current_state=current,
                trigger_price=self._trigger_price.get(stock_code),
                triggered_at=self._triggered_at.get(stock_code),
                last_close_before_vi=self._last_close_before_vi.get(stock_code),
                current_price=None,
            ),
            event=EVENT_VI_RESETTLED,
        )
        self._states[stock_code] = decision.next_state  # NORMAL
        if decision.block_new_entries_today:
            self._recovered_today.add(stock_code)

    # ------------------------------------------------------------------
    # Daily reset (§10.6)  --  09:00 next-day
    # ------------------------------------------------------------------

    def reset_daily(self) -> None:
        """Wipe every stock's VI state + ``vi_recovered_today``.

        Called by the orchestrator at 09:00 on each trading day so
        previous-day VI flags do not block today's entries (§10.6).
        Synchronous: just clears in-memory dicts.
        """
        self._states.clear()
        self._triggered_at.clear()
        self._trigger_price.clear()
        self._last_close_before_vi.clear()
        self._recovered_today.clear()

    # ------------------------------------------------------------------
    # Sync hook (V7.0 WebSocketManager bridge)  --  optional
    # ------------------------------------------------------------------

    # The V7.0 WebSocket layer hands us VI events via a sync callback.
    # Tests can ignore this method and call on_vi_triggered / on_vi_resolved
    # directly. Production wiring (P3.7) installs this as the WebSocket
    # subscriber.
    def make_sync_dispatcher(
        self,
    ) -> Callable[[str, int, int, int | None], None]:
        """Return a sync callback for V7.0 WebSocketManager subscription.

        Signature: ``(stock_code, vi_flag, trigger_price, last_close)``
        where vi_flag is 1 (triggered) or 2 (resolved). last_close is
        only used on flag=1 (we cache it for the gap check).
        """
        import asyncio

        def dispatcher(
            stock_code: str,
            vi_flag: int,
            trigger_price: int,
            last_close: int | None,
        ) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                log.warning(
                    "No running loop for VI dispatch (stock=%s)", stock_code
                )
                return

            if vi_flag == 1:
                if last_close is None:
                    log.warning(
                        "VI flag=1 for %s without last_close -- using trigger_price",
                        stock_code,
                    )
                    last_close = trigger_price
                loop.create_task(
                    self.on_vi_triggered(
                        stock_code,
                        trigger_price=trigger_price,
                        last_close_before_vi=last_close,
                    )
                )
            elif vi_flag == 2:
                loop.create_task(
                    self.on_vi_resolved(
                        stock_code,
                        first_price_after_resume=trigger_price,
                    )
                )
            else:
                log.warning(
                    "Unknown vi_flag=%d for %s -- ignoring", vi_flag, stock_code
                )

        return dispatcher


__all__ = [
    "OnViResumedFn",
    "ViMonitorContext",
    "V71ViMonitor",
]
