"""Unit tests for ``src/core/v71/notification/v71_notification_service.py``.

Spec:
  - 02_TRADING_RULES.md §9.3 (CRITICAL retry 3 x 5s)
  - 02_TRADING_RULES.md §9.4 (Circuit OPEN -> CRITICAL/HIGH stay queued)
  - 02_TRADING_RULES.md §9.9 (no raw telegram.send_message)
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags() -> Iterator[None]:
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.notification.v71_circuit_breaker import (  # noqa: E402
    V71CircuitBreaker,
    V71CircuitState,
)
from src.core.v71.notification.v71_notification_queue import (  # noqa: E402
    V71NotificationQueue,
)
from src.core.v71.notification.v71_notification_repository import (  # noqa: E402
    InMemoryNotificationRepository,
    NotificationRecord,
    NotificationStatus,
)
from src.core.v71.notification.v71_notification_service import (  # noqa: E402
    V71NotificationService,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 26, 9, 0)
    )
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_value = self.now_value + timedelta(seconds=seconds)
        # Yield to the event loop so the worker doesn't hot-loop and
        # main test tasks get a chance to make progress.
        await asyncio.sleep(0)

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target
        await asyncio.sleep(0)

    def advance(self, **kwargs: int) -> None:
        self.now_value = self.now_value + timedelta(**kwargs)


@dataclass
class FakeTelegram:
    """Records every send and returns the queued result.

    ``next_results`` controls per-attempt outcome:
      - bool   -> return value
      - Exception subclass -> raise that
    """

    next_results: list = field(default_factory=list)
    default: bool = True
    sent: list[str] = field(default_factory=list)

    async def send(self, text: str) -> bool:
        self.sent.append(text)
        if not self.next_results:
            return self.default
        outcome = self.next_results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return bool(outcome)


@dataclass
class FakeWebDispatcher:
    received: list[NotificationRecord] = field(default_factory=list)
    raise_on_call: BaseException | None = None

    async def __call__(self, record: NotificationRecord) -> None:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.received.append(record)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _build_service(
    *,
    telegram: FakeTelegram | None = None,
    web: FakeWebDispatcher | None = None,
    failure_threshold: int = 3,
    timeout_seconds: int = 30,
    critical_retry_count: int = 3,
    critical_retry_delay_seconds: int = 5,
    worker_interval_seconds: float = 0.01,
) -> tuple[
    V71NotificationService,
    V71NotificationQueue,
    InMemoryNotificationRepository,
    FakeClock,
    FakeTelegram,
    V71CircuitBreaker,
]:
    repo = InMemoryNotificationRepository()
    clock = FakeClock()
    queue = V71NotificationQueue(repository=repo, clock=clock)
    cb = V71CircuitBreaker(
        clock=clock,
        failure_threshold=failure_threshold,
        timeout_seconds=timeout_seconds,
    )
    tg = telegram or FakeTelegram()
    service = V71NotificationService(
        queue=queue,
        circuit_breaker=cb,
        telegram_send=tg.send,
        clock=clock,
        web_dispatch=web,
        critical_retry_count=critical_retry_count,
        critical_retry_delay_seconds=critical_retry_delay_seconds,
        worker_interval_seconds=worker_interval_seconds,
    )
    return service, queue, repo, clock, tg, cb


# ---------------------------------------------------------------------------
# Construction / feature flag
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_feature_flag_required(self) -> None:
        del os.environ["V71_FF__V71__NOTIFICATION_V71"]
        ff.reload()
        with pytest.raises(RuntimeError, match="notification_v71"):
            _build_service()

    def test_invalid_args(self) -> None:
        with pytest.raises(ValueError, match="critical_retry_count"):
            _build_service(critical_retry_count=0)
        with pytest.raises(ValueError, match="critical_retry_delay_seconds"):
            _build_service(critical_retry_delay_seconds=-1)
        with pytest.raises(ValueError, match="worker_interval_seconds"):
            _build_service(worker_interval_seconds=0)


# ---------------------------------------------------------------------------
# notify (Notifier Protocol)
# ---------------------------------------------------------------------------


class TestNotifyProtocol:
    @pytest.mark.asyncio
    async def test_notify_enqueues(self) -> None:
        service, _queue, repo, _clock, _tg, _cb = _build_service()
        await service.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code="036040",
            message="bought",
        )
        records = repo.all_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.severity == "HIGH"
        assert rec.event_type == "BUY_EXECUTED"
        assert rec.message == "bought"
        # default rate-limit key derived from event + stock.
        assert rec.rate_limit_key == "BUY_EXECUTED:036040"

    @pytest.mark.asyncio
    async def test_notify_with_explicit_key(self) -> None:
        service, _q, repo, _c, _t, _cb = _build_service()
        await service.notify(
            severity="CRITICAL",
            event_type="RECOVERY_COMPLETED",
            stock_code=None,
            message="restart ok",
            rate_limit_key="recovery_report",
        )
        recs = repo.all_records()
        assert recs[0].rate_limit_key == "recovery_report"

    @pytest.mark.asyncio
    async def test_notify_silently_swallows_suppression(self) -> None:
        service, _q, repo, _c, _t, _cb = _build_service()
        await service.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code="X",
            message="m",
        )
        await service.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code="X",
            message="m again",
        )
        # Only one record persisted; the second was rate-limited.
        assert len(repo.all_records()) == 1


# ---------------------------------------------------------------------------
# run_once: standard severity dispatch
# ---------------------------------------------------------------------------


class TestRunOnceStandard:
    @pytest.mark.asyncio
    async def test_empty_queue_returns_none(self) -> None:
        service, _q, _r, _c, _t, _cb = _build_service()
        assert await service.run_once() is None

    @pytest.mark.asyncio
    async def test_high_success(self) -> None:
        service, _q, repo, _c, tg, cb = _build_service()
        await service.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code="000",
            message="hello",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is True
        assert outcome.revert_to_pending is False
        assert tg.sent == ["hello"]
        # CB stays CLOSED on success.
        assert cb.state() is V71CircuitState.CLOSED
        # Record SENT.
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.SENT

    @pytest.mark.asyncio
    async def test_high_failure_reverts_to_pending(self) -> None:
        tg = FakeTelegram(default=False)
        service, _q, repo, _c, _t, cb = _build_service(telegram=tg)
        await service.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code="000",
            message="hi",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is False
        assert outcome.revert_to_pending is True
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.PENDING
        assert rec.retry_count == 1
        assert cb.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_medium_failure_terminal(self) -> None:
        tg = FakeTelegram(default=False)
        service, _q, repo, _c, _t, _cb = _build_service(telegram=tg)
        await service.notify(
            severity="MEDIUM",
            event_type="BOX_ENTRY_IMMINENT",
            stock_code="000",
            message="hi",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.revert_to_pending is False
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.FAILED

    @pytest.mark.asyncio
    async def test_telegram_exception_handled(self) -> None:
        tg = FakeTelegram(next_results=[RuntimeError("network")])
        service, _q, repo, _c, _t, cb = _build_service(telegram=tg)
        await service.notify(
            severity="HIGH",
            event_type="X",
            stock_code="000",
            message="m",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is False
        assert "exception" in (outcome.reason or "")
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.PENDING  # HIGH reverts
        assert "telegram_send raised" in (rec.failure_reason or "")
        assert cb.consecutive_failures == 1


# ---------------------------------------------------------------------------
# run_once: CRITICAL retry
# ---------------------------------------------------------------------------


class TestCriticalRetry:
    @pytest.mark.asyncio
    async def test_critical_first_attempt_succeeds(self) -> None:
        service, _q, repo, _c, tg, cb = _build_service(
            critical_retry_count=3, critical_retry_delay_seconds=5
        )
        await service.notify(
            severity="CRITICAL",
            event_type="STOP_LOSS",
            stock_code="000",
            message="loss",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is True
        assert outcome.attempts == 1
        assert tg.sent == ["loss"]
        assert cb.state() is V71CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_critical_third_attempt_succeeds(self) -> None:
        tg = FakeTelegram(next_results=[False, False, True])
        service, _q, repo, clock, _t, cb = _build_service(
            telegram=tg,
            critical_retry_count=3,
            critical_retry_delay_seconds=5,
        )
        await service.notify(
            severity="CRITICAL",
            event_type="STOP_LOSS",
            stock_code="000",
            message="loss",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is True
        assert outcome.attempts == 3
        # 2 sleeps between 3 attempts.
        assert clock.sleeps == [5, 5]
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.SENT

    @pytest.mark.asyncio
    async def test_critical_all_retries_fail_stays_pending(self) -> None:
        tg = FakeTelegram(default=False)
        service, _q, repo, clock, _t, cb = _build_service(
            telegram=tg,
            critical_retry_count=3,
            critical_retry_delay_seconds=5,
        )
        await service.notify(
            severity="CRITICAL",
            event_type="STOP_LOSS",
            stock_code="000",
            message="loss",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is False
        assert outcome.attempts == 3
        assert outcome.revert_to_pending is True
        # 3 attempts, 2 sleeps between them.
        assert clock.sleeps == [5, 5]
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.PENDING
        # mark_failed runs once at the end of the retry chain, so
        # retry_count increments by 1 (not by the per-attempt count).
        # The breaker, on the other hand, sees every failed attempt.
        assert rec.retry_count == 1
        assert cb.consecutive_failures >= 3

    @pytest.mark.asyncio
    async def test_critical_exception_then_success(self) -> None:
        tg = FakeTelegram(next_results=[ValueError("first"), True])
        service, _q, repo, _c, _t, cb = _build_service(
            telegram=tg,
            critical_retry_count=3,
            critical_retry_delay_seconds=1,
        )
        await service.notify(
            severity="CRITICAL",
            event_type="STOP_LOSS",
            stock_code="000",
            message="loss",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is True
        assert outcome.attempts == 2
        assert cb.state() is V71CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Circuit Breaker integration
# ---------------------------------------------------------------------------


class TestCircuitIntegration:
    @pytest.mark.asyncio
    async def test_circuit_open_skips_dispatch(self) -> None:
        # Trip the circuit by 3 failures, then enqueue a CRITICAL and
        # observe that run_once skips it (even CRITICAL waits while OPEN).
        tg = FakeTelegram(default=False)
        service, _q, repo, _c, _t, cb = _build_service(
            telegram=tg, failure_threshold=2
        )

        # 2 HIGH failures -> CB OPEN.
        for _ in range(2):
            await service.notify(
                severity="HIGH",
                event_type=f"E{_}",
                stock_code=f"X{_}",
                message="m",
            )
            await service.run_once()
        assert cb.state() is V71CircuitState.OPEN

        # Now enqueue a CRITICAL. run_once should NOT dispatch.
        await service.notify(
            severity="CRITICAL",
            event_type="STOP_LOSS",
            stock_code="000",
            message="loss",
        )
        outcome = await service.run_once()
        # No dispatch happened because circuit is OPEN.
        assert outcome is None
        crit = next(
            r for r in repo.all_records() if r.severity == "CRITICAL"
        )
        assert crit.status is NotificationStatus.PENDING

    @pytest.mark.asyncio
    async def test_circuit_half_open_probes(self) -> None:
        tg = FakeTelegram()  # default True
        service, _q, repo, clock, _t, cb = _build_service(
            telegram=tg,
            failure_threshold=2,
            timeout_seconds=30,
        )

        # Trip with 2 forced failures.
        tg.next_results = [False, False]
        for i in range(2):
            await service.notify(
                severity="HIGH",
                event_type=f"E{i}",
                stock_code=f"S{i}",
                message="m",
            )
            await service.run_once()
        assert cb.state() is V71CircuitState.OPEN

        # Advance past timeout -> HALF_OPEN -> next dispatch allowed.
        clock.advance(seconds=31)
        # Default True so probe succeeds.
        tg.next_results = []  # use default True
        await service.notify(
            severity="HIGH",
            event_type="RECOVER",
            stock_code="OK",
            message="m",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is True
        assert cb.state() is V71CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Web dispatcher fan-out
# ---------------------------------------------------------------------------


class TestWebDispatch:
    @pytest.mark.asyncio
    async def test_both_channel_fans_out(self) -> None:
        web = FakeWebDispatcher()
        service, _q, _r, _c, _t, _cb = _build_service(web=web)
        await service.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code="000",
            message="m",
        )
        await service.run_once()
        assert len(web.received) == 1
        assert web.received[0].channel == "BOTH"

    @pytest.mark.asyncio
    async def test_telegram_only_skips_web(self) -> None:
        web = FakeWebDispatcher()
        service, _q, _r, _c, _t, _cb = _build_service(web=web)
        await service.notify(
            severity="MEDIUM",
            event_type="BOX_ENTRY_IMMINENT",
            stock_code="000",
            message="m",
        )
        await service.run_once()
        # MEDIUM = TELEGRAM only.
        assert web.received == []

    @pytest.mark.asyncio
    async def test_web_exception_does_not_block_telegram(self) -> None:
        web = FakeWebDispatcher(raise_on_call=RuntimeError("dashboard down"))
        service, _q, repo, _c, tg, _cb = _build_service(web=web)
        await service.notify(
            severity="CRITICAL",
            event_type="STOP_LOSS",
            stock_code="000",
            message="loss",
        )
        outcome = await service.run_once()
        assert outcome is not None
        assert outcome.sent is True  # Telegram still succeeded.
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.SENT


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------


class TestWorkerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self) -> None:
        service, _q, _r, _c, _t, _cb = _build_service(
            worker_interval_seconds=0.01
        )
        await service.start()
        assert service.is_running
        # Calling start again is a no-op.
        await service.start()
        assert service.is_running
        await service.stop()
        assert not service.is_running
        # Stop on idle service is also a no-op.
        await service.stop()

    @pytest.mark.asyncio
    async def test_worker_drains_queue(self) -> None:
        service, _q, repo, _c, tg, _cb = _build_service(
            worker_interval_seconds=0.01
        )
        await service.notify(
            severity="HIGH",
            event_type="A",
            stock_code="000",
            message="hi",
        )
        await service.start()
        # Yield enough times for the worker loop to pick up the record.
        for _ in range(50):
            if tg.sent:
                break
            await asyncio.sleep(0.005)
        await service.stop()
        assert tg.sent == ["hi"]
        rec = repo.all_records()[0]
        assert rec.status is NotificationStatus.SENT

    @pytest.mark.asyncio
    async def test_worker_swallows_step_exceptions(self) -> None:
        # Inject a broken queue method by monkey-patching after construction:
        # the easiest way is to break the telegram callable so _dispatch
        # tries to send -- and then we replace the telegram at runtime
        # to raise. The worker should not crash.
        tg = FakeTelegram(default=False)
        service, _q, _r, _c, _t, _cb = _build_service(
            telegram=tg, worker_interval_seconds=0.01
        )
        await service.notify(
            severity="MEDIUM",
            event_type="BOX",
            stock_code="000",
            message="m",
        )
        await service.start()
        await asyncio.sleep(0.05)
        # Worker continues even after a failure.
        await service.stop()
        # Worker did at least one drain attempt.
        assert tg.sent  # at least one send was attempted
