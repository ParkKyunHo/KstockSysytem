"""Unit tests for ``src/core/v71/notification/v71_notification_queue.py``.

Spec:
  - 02_TRADING_RULES.md §9 (priority queue, rate limit, expiry)
"""

from __future__ import annotations

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


from src.core.v71.notification.v71_notification_queue import (  # noqa: E402
    EnqueueOutcome,
    V71NotificationQueue,
)
from src.core.v71.notification.v71_notification_repository import (  # noqa: E402
    InMemoryNotificationRepository,
    NotificationStatus,
)
from src.core.v71.skills.notification_skill import Severity  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 26, 9, 0)
    )

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, _seconds: float) -> None:
        return None

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target

    def advance(self, **kwargs: int) -> None:
        self.now_value = self.now_value + timedelta(**kwargs)


def _make_queue(
    *, rate_limit_minutes: int | None = None
) -> tuple[V71NotificationQueue, InMemoryNotificationRepository, FakeClock]:
    repo = InMemoryNotificationRepository()
    clock = FakeClock()
    queue = V71NotificationQueue(
        repository=repo, clock=clock, rate_limit_minutes=rate_limit_minutes
    )
    return queue, repo, clock


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFeatureFlagGate:
    def test_disabled_flag_blocks_construction(self) -> None:
        # Drop the env override and reload.
        del os.environ["V71_FF__V71__NOTIFICATION_V71"]
        ff.reload()
        with pytest.raises(RuntimeError, match="notification_v71"):
            V71NotificationQueue(
                repository=InMemoryNotificationRepository(), clock=FakeClock()
            )

    def test_negative_rate_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="rate_limit_minutes"):
            V71NotificationQueue(
                repository=InMemoryNotificationRepository(),
                clock=FakeClock(),
                rate_limit_minutes=-1,
            )


# ---------------------------------------------------------------------------
# Enqueue: priority + channel + expiry
# ---------------------------------------------------------------------------


class TestEnqueueShape:
    @pytest.mark.asyncio
    async def test_critical_channel_both_no_expiry(self) -> None:
        queue, repo, _ = _make_queue()
        outcome = await queue.enqueue(
            severity=Severity.CRITICAL,
            event_type="STOP_LOSS",
            message="loss",
            stock_code="000",
            rate_limit_key="STOP_LOSS:000",
        )
        assert isinstance(outcome, EnqueueOutcome)
        assert outcome.accepted is True
        rec = outcome.record
        assert rec is not None
        assert rec.priority == 1
        assert rec.channel == "BOTH"
        assert rec.expires_at is None
        assert rec.severity == "CRITICAL"
        assert rec.status is NotificationStatus.PENDING
        assert repo.get(rec.id) is rec

    @pytest.mark.asyncio
    async def test_high_channel_both_no_expiry(self) -> None:
        queue, _, _ = _make_queue()
        outcome = await queue.enqueue(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            message="m",
            stock_code="000",
            rate_limit_key="BUY:000",
        )
        rec = outcome.record
        assert rec is not None
        assert rec.priority == 2
        assert rec.channel == "BOTH"
        assert rec.expires_at is None

    @pytest.mark.asyncio
    async def test_medium_channel_telegram_with_expiry(self) -> None:
        queue, _, clock = _make_queue()
        outcome = await queue.enqueue(
            severity=Severity.MEDIUM,
            event_type="BOX_ENTRY_IMMINENT",
            message="m",
            stock_code="000",
            rate_limit_key="BOX:000",
        )
        rec = outcome.record
        assert rec is not None
        assert rec.priority == 3
        assert rec.channel == "TELEGRAM"
        # 5 minutes after enqueue.
        assert rec.expires_at == clock.now_value + timedelta(minutes=5)

    @pytest.mark.asyncio
    async def test_low_channel_telegram_with_expiry(self) -> None:
        queue, _, _ = _make_queue()
        outcome = await queue.enqueue(
            severity=Severity.LOW,
            event_type="DAILY_SUMMARY",
            message="m",
        )
        rec = outcome.record
        assert rec is not None
        assert rec.priority == 4
        assert rec.channel == "TELEGRAM"
        assert rec.expires_at is not None

    @pytest.mark.asyncio
    async def test_unknown_severity_raises(self) -> None:
        queue, _, _ = _make_queue()
        with pytest.raises(ValueError, match="unknown severity"):
            await queue.enqueue(
                severity="URGENT", event_type="X", message="m"
            )


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_high_within_window_suppressed(self) -> None:
        queue, _, clock = _make_queue()
        first = await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            stock_code="000",
            rate_limit_key="K",
        )
        assert first.accepted

        clock.advance(minutes=2)
        second = await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            stock_code="000",
            rate_limit_key="K",
        )
        assert second.accepted is False
        assert second.suppression_reason == "RATE_LIMIT"

    @pytest.mark.asyncio
    async def test_window_expiry_lets_through(self) -> None:
        queue, _, clock = _make_queue()
        first = await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            stock_code="000",
            rate_limit_key="K",
        )
        assert first.accepted

        clock.advance(minutes=6)  # past the 5-minute window
        third = await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            stock_code="000",
            rate_limit_key="K",
        )
        assert third.accepted is True

    @pytest.mark.asyncio
    async def test_critical_bypasses_rate_limit(self) -> None:
        queue, _, _ = _make_queue()
        for _ in range(5):
            r = await queue.enqueue(
                severity=Severity.CRITICAL,
                event_type="STOP_LOSS",
                message="m",
                stock_code="000",
                rate_limit_key="K",
            )
            assert r.accepted is True

    @pytest.mark.asyncio
    async def test_distinct_keys_independent(self) -> None:
        queue, _, _ = _make_queue()
        a = await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            rate_limit_key="A",
        )
        b = await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            rate_limit_key="B",
        )
        assert a.accepted is True
        assert b.accepted is True

    @pytest.mark.asyncio
    async def test_zero_window_disables_rate_limit(self) -> None:
        queue, _, _ = _make_queue(rate_limit_minutes=0)
        for _ in range(3):
            r = await queue.enqueue(
                severity=Severity.HIGH,
                event_type="BUY_EXECUTED",
                message="m",
                rate_limit_key="K",
            )
            assert r.accepted is True

    @pytest.mark.asyncio
    async def test_no_key_means_no_rate_limit(self) -> None:
        # Without a rate_limit_key, enqueue cannot suppress.
        queue, _, _ = _make_queue()
        a = await queue.enqueue(
            severity=Severity.HIGH, event_type="X", message="m"
        )
        b = await queue.enqueue(
            severity=Severity.HIGH, event_type="X", message="m"
        )
        assert a.accepted and b.accepted

    @pytest.mark.asyncio
    async def test_is_rate_limited_query(self) -> None:
        queue, _, _ = _make_queue()
        await queue.enqueue(
            severity=Severity.HIGH,
            event_type="BUY_EXECUTED",
            message="m",
            rate_limit_key="K",
        )
        assert await queue.is_rate_limited(rate_limit_key="K") is True
        assert await queue.is_rate_limited(rate_limit_key="OTHER") is False
        # Critical bypasses.
        assert (
            await queue.is_rate_limited(
                rate_limit_key="K", severity=Severity.CRITICAL
            )
            is False
        )


# ---------------------------------------------------------------------------
# Consumer side
# ---------------------------------------------------------------------------


class TestConsumerSide:
    @pytest.mark.asyncio
    async def test_next_pending_priority_order(self) -> None:
        queue, _, clock = _make_queue()
        await queue.enqueue(
            severity=Severity.LOW, event_type="X", message="low"
        )
        clock.advance(seconds=1)
        await queue.enqueue(
            severity=Severity.CRITICAL, event_type="Y", message="crit"
        )
        chosen = await queue.next_pending()
        assert chosen is not None
        assert chosen.severity == "CRITICAL"

    @pytest.mark.asyncio
    async def test_mark_sent(self) -> None:
        queue, repo, clock = _make_queue()
        out = await queue.enqueue(
            severity=Severity.HIGH, event_type="X", message="m"
        )
        rec = out.record
        assert rec is not None

        clock.advance(seconds=10)
        await queue.mark_sent(rec.id)
        updated = repo.get(rec.id)
        assert updated is not None
        assert updated.status is NotificationStatus.SENT
        assert updated.sent_at == clock.now_value

    @pytest.mark.asyncio
    async def test_mark_failed_revert(self) -> None:
        queue, repo, _ = _make_queue()
        out = await queue.enqueue(
            severity=Severity.HIGH, event_type="X", message="m"
        )
        rec = out.record
        assert rec is not None
        await queue.mark_failed(rec.id, reason="boom", revert_to_pending=True)
        updated = repo.get(rec.id)
        assert updated is not None
        assert updated.status is NotificationStatus.PENDING
        assert updated.retry_count == 1

    @pytest.mark.asyncio
    async def test_mark_failed_terminal(self) -> None:
        queue, repo, _ = _make_queue()
        out = await queue.enqueue(
            severity=Severity.MEDIUM, event_type="X", message="m"
        )
        rec = out.record
        assert rec is not None
        await queue.mark_failed(rec.id, reason="boom", revert_to_pending=False)
        updated = repo.get(rec.id)
        assert updated is not None
        assert updated.status is NotificationStatus.FAILED

    @pytest.mark.asyncio
    async def test_expire_stale(self) -> None:
        queue, repo, clock = _make_queue()
        out = await queue.enqueue(
            severity=Severity.MEDIUM, event_type="X", message="m"
        )
        rec = out.record
        assert rec is not None

        clock.advance(minutes=10)
        n = await queue.expire_stale()
        assert n == 1
        assert repo.get(rec.id).status is NotificationStatus.EXPIRED  # type: ignore[union-attr]
