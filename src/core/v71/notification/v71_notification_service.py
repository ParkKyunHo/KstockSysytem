"""V71NotificationService -- Notifier Protocol implementation (P4.1).

Spec:
  - 02_TRADING_RULES.md §9 (severity, queue, circuit breaker, retry)
  - 07_SKILLS_SPEC.md §6 (notification_skill -- this is the impl side)

Wiring:
  - Producer side: every V7.1 module that imports the
    :class:`Notifier` Protocol from
    ``src.core.v71.strategies.v71_buy_executor`` calls
    :meth:`V71NotificationService.notify`. The 14 known callsites
    today are: V71BuyExecutor (2), V71ExitExecutor (4),
    V71ViMonitor (2), V71Reconciler (1 internal helper, 4 cases),
    V71RestartRecovery (2). All of them pass the same kwargs:
    ``severity, event_type, stock_code, message, rate_limit_key``.
  - Consumer side: :meth:`start` spawns an async worker that
    drains the queue through ``telegram_send``. The worker honours
    the Circuit Breaker, applies CRITICAL retry (3 x 5s), and gracefully
    handles transient failures.

Telegram client: :class:`V71NotificationService` does NOT import the
V7.0 ``TelegramBot`` directly. The bootstrap layer wires
``telegram_send=telegram_bot.send_message`` so the service stays a pure
Protocol-driven module.

Constitution:
  - 3 (no V7.0 collision): no V7.0 import here. The Telegram bot is
    handed in as a callable.
  - 4 (system keeps running): worker swallows non-cancelled exceptions
    and keeps polling. Circuit OPEN does not stop the worker; it only
    pauses delivery while the queue accepts new entries.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.core.v71.notification.v71_circuit_breaker import (
    V71CircuitBreaker,
    V71CircuitState,
)
from src.core.v71.notification.v71_notification_queue import (
    V71NotificationQueue,
)
from src.core.v71.notification.v71_notification_repository import (
    NotificationRecord,
)
from src.core.v71.skills.notification_skill import make_rate_limit_key
from src.core.v71.strategies.v71_buy_executor import Clock
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wiring Protocols
# ---------------------------------------------------------------------------

# Telegram delivery callable. Returns True on success.
# Wraps ``src.notification.telegram.TelegramBot.send_message`` in production.
TelegramSendFn = Callable[[str], Awaitable[bool]]

# Web channel dispatcher. Phase 5 wires the dashboard's WebSocket push;
# Phase 4 leaves this None (records remain in the queue with channel=BOTH
# for later reconciliation).
WebDispatchFn = Callable[[NotificationRecord], Awaitable[None]]


# ---------------------------------------------------------------------------
# Outcome of one delivery attempt
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchOutcome:
    """Result of :meth:`V71NotificationService._dispatch`.

    Surfaced for white-box tests.
    """

    record_id: str
    sent: bool
    revert_to_pending: bool
    reason: str | None = None
    attempts: int = 1


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class V71NotificationService:
    """Notifier Protocol implementation that owns the queue + worker."""

    def __init__(
        self,
        *,
        queue: V71NotificationQueue,
        circuit_breaker: V71CircuitBreaker,
        telegram_send: TelegramSendFn,
        clock: Clock,
        web_dispatch: WebDispatchFn | None = None,
        critical_retry_count: int | None = None,
        critical_retry_delay_seconds: int | None = None,
        worker_interval_seconds: float | None = None,
    ) -> None:
        require_enabled("v71.notification_v71")

        self._queue = queue
        self._cb = circuit_breaker
        self._telegram_send = telegram_send
        self._clock = clock
        self._web_dispatch = web_dispatch

        self._critical_retry_count = (
            critical_retry_count
            if critical_retry_count is not None
            else V71Constants.NOTIFICATION_CRITICAL_RETRY_COUNT
        )
        self._critical_retry_delay_seconds = (
            critical_retry_delay_seconds
            if critical_retry_delay_seconds is not None
            else V71Constants.NOTIFICATION_CRITICAL_RETRY_DELAY_SECONDS
        )
        self._worker_interval_seconds = (
            worker_interval_seconds
            if worker_interval_seconds is not None
            else V71Constants.NOTIFICATION_WORKER_INTERVAL_SECONDS
        )
        if self._critical_retry_count < 1:
            raise ValueError("critical_retry_count must be >= 1")
        if self._critical_retry_delay_seconds < 0:
            raise ValueError("critical_retry_delay_seconds must be >= 0")
        if self._worker_interval_seconds <= 0:
            raise ValueError("worker_interval_seconds must be > 0")

        self._worker_task: asyncio.Task[None] | None = None
        self._stopping = False

    # ------------------------------------------------------------------
    # Notifier Protocol surface
    # ------------------------------------------------------------------

    async def notify(
        self,
        *,
        severity: str,
        event_type: str,
        stock_code: str | None,
        message: str,
        rate_limit_key: str | None = None,
    ) -> None:
        """Enqueue a notification (P3 callsites land here).

        ``rate_limit_key`` defaults to ``f"{event_type}:{stock_code or '_'}"``
        so callers may omit it when the default scope is appropriate.
        """
        key = rate_limit_key or make_rate_limit_key(event_type, stock_code)
        outcome = await self._queue.enqueue(
            severity=severity,
            event_type=event_type,
            message=message,
            stock_code=stock_code,
            rate_limit_key=key,
        )
        # Suppression is silent on the Protocol surface; callers don't
        # care whether the rate-limit fired. The queue state already
        # records the most recent attempt.
        if not outcome.accepted:
            log.debug(
                "notify suppressed (severity=%s event=%s stock=%s reason=%s)",
                severity,
                event_type,
                stock_code,
                outcome.suppression_reason,
            )

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the worker coroutine if not already running."""
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._stopping = False
        self._worker_task = asyncio.create_task(
            self._worker_loop(), name="v71-notification-worker"
        )

    async def stop(self) -> None:
        """Signal the worker to stop and await it."""
        self._stopping = True
        task = self._worker_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            # CancelledError -> normal stop; other exceptions already
            # surfaced inside the worker (logged); we don't want stop()
            # itself to raise.
            pass
        finally:
            self._worker_task = None

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    # ------------------------------------------------------------------
    # Worker step (also driven directly by unit tests)
    # ------------------------------------------------------------------

    async def run_once(self) -> DispatchOutcome | None:
        """Execute one drain step.

        Returns the outcome of the dispatched record, or ``None`` if
        nothing was dispatched (queue empty or Circuit OPEN).

        Behaviour mirrors :meth:`_worker_loop` minus the loop and sleep,
        for deterministic testing.
        """
        # Reap stale MEDIUM/LOW first so we don't pick them up below.
        await self._queue.expire_stale()

        if self._cb.state() is V71CircuitState.OPEN:
            return None

        record = await self._queue.next_pending()
        if record is None:
            return None

        return await self._dispatch(record)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        """Drain the queue at ``worker_interval_seconds``."""
        try:
            while not self._stopping:
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    # Constitution 4: keep running after unexpected errors.
                    log.exception("notification worker step raised")
                # Sleep regardless of step outcome (avoid hot loop on
                # empty queue or Circuit OPEN).
                try:
                    await self._clock.sleep(self._worker_interval_seconds)
                except asyncio.CancelledError:
                    raise
        except asyncio.CancelledError:
            return

    async def _dispatch(
        self, record: NotificationRecord
    ) -> DispatchOutcome:
        """Send one record via Telegram (+ web side-channel)."""
        if record.severity == "CRITICAL":
            return await self._dispatch_critical(record)
        return await self._dispatch_standard(record)

    async def _dispatch_standard(
        self, record: NotificationRecord
    ) -> DispatchOutcome:
        """HIGH/MEDIUM/LOW -- single attempt; on failure decide revert."""
        text = self._render_text(record)
        try:
            sent = await self._telegram_send(text)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "telegram_send raised for record %s: %s", record.id, e
            )
            self._cb.record_failure()
            revert = record.severity == "HIGH"
            await self._queue.mark_failed(
                record.id,
                reason=f"telegram_send raised: {e}",
                revert_to_pending=revert,
            )
            return DispatchOutcome(
                record_id=record.id,
                sent=False,
                revert_to_pending=revert,
                reason=f"exception: {e}",
            )

        if sent:
            self._cb.record_success()
            await self._queue.mark_sent(record.id)
            await self._maybe_dispatch_web(record)
            return DispatchOutcome(record_id=record.id, sent=True, revert_to_pending=False)

        # send_message returned False -- transient failure.
        self._cb.record_failure()
        revert = record.severity == "HIGH"
        await self._queue.mark_failed(
            record.id,
            reason="telegram_send returned False",
            revert_to_pending=revert,
        )
        return DispatchOutcome(
            record_id=record.id,
            sent=False,
            revert_to_pending=revert,
            reason="send returned False",
        )

    async def _dispatch_critical(
        self, record: NotificationRecord
    ) -> DispatchOutcome:
        """CRITICAL -- 3 retries x 5 seconds (02 §9.3 last clause).

        On total failure the record stays PENDING (revert_to_pending=True);
        the queue keeps it forever so the operator notices the next time
        Telegram comes back online.
        """
        text = self._render_text(record)
        last_reason: str | None = None
        attempts = 0

        for attempt in range(self._critical_retry_count):
            attempts = attempt + 1
            try:
                sent = await self._telegram_send(text)
            except Exception as e:  # noqa: BLE001
                sent = False
                last_reason = f"exception: {e}"
                log.warning(
                    "telegram_send raised for CRITICAL record %s "
                    "(attempt %d/%d): %s",
                    record.id,
                    attempts,
                    self._critical_retry_count,
                    e,
                )

            if sent:
                self._cb.record_success()
                await self._queue.mark_sent(record.id)
                await self._maybe_dispatch_web(record)
                return DispatchOutcome(
                    record_id=record.id,
                    sent=True,
                    revert_to_pending=False,
                    attempts=attempts,
                )

            self._cb.record_failure()
            if attempts < self._critical_retry_count:
                await self._clock.sleep(self._critical_retry_delay_seconds)
            if last_reason is None:
                last_reason = "send returned False"

        # All retries failed. CRITICAL is queued indefinitely.
        log.error(
            "CRITICAL notification %s exhausted %d retries; left PENDING",
            record.id,
            self._critical_retry_count,
        )
        await self._queue.mark_failed(
            record.id,
            reason=f"critical retry exhausted: {last_reason}",
            revert_to_pending=True,
        )
        return DispatchOutcome(
            record_id=record.id,
            sent=False,
            revert_to_pending=True,
            reason=last_reason,
            attempts=attempts,
        )

    async def _maybe_dispatch_web(
        self, record: NotificationRecord
    ) -> None:
        """Web fan-out for CRITICAL/HIGH (channel=BOTH).

        Failures here never affect the Telegram primary path (already
        marked SENT). Phase 5 wires a real dispatcher; until then this
        is a no-op when ``web_dispatch is None``.
        """
        if self._web_dispatch is None:
            return
        if record.channel != "BOTH":
            return
        try:
            await self._web_dispatch(record)
        except Exception:  # noqa: BLE001
            log.exception("web_dispatch raised for record %s", record.id)

    @staticmethod
    def _render_text(record: NotificationRecord) -> str:
        """Compose the telegram body: ``{title}\\n{message}`` or just message."""
        if record.title:
            return f"{record.title}\n{record.message}"
        return record.message


__all__ = [
    "DispatchOutcome",
    "TelegramSendFn",
    "V71NotificationService",
    "WebDispatchFn",
]
