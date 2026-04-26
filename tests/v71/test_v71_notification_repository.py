"""Unit tests for ``src/core/v71/notification/v71_notification_repository.py``.

Focus: :class:`InMemoryNotificationRepository`. The Postgres impl is
exercised by Phase 5 integration tests (excluded from Harness 7 90%).

Spec:
  - 02_TRADING_RULES.md §9.3 (priority ordering)
  - 02_TRADING_RULES.md §9.4 (CRITICAL/HIGH never expire)
  - 02_TRADING_RULES.md §9.5 (rate-limit window query)
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.core.v71.notification.v71_notification_repository import (
    InMemoryNotificationRepository,
    NotificationRecord,
    NotificationStatus,
    new_notification_id,
)

# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def _make_record(
    *,
    severity: str = "HIGH",
    priority: int = 2,
    created_at: datetime,
    expires_at: datetime | None = None,
    rate_limit_key: str | None = None,
    status: NotificationStatus = NotificationStatus.PENDING,
    record_id: str | None = None,
) -> NotificationRecord:
    return NotificationRecord(
        id=record_id or new_notification_id(),
        severity=severity,
        channel="BOTH" if severity in ("CRITICAL", "HIGH") else "TELEGRAM",
        event_type="TEST_EVENT",
        stock_code="000",
        title=None,
        message="m",
        payload=None,
        status=status,
        priority=priority,
        rate_limit_key=rate_limit_key,
        retry_count=0,
        sent_at=None,
        failed_at=None,
        failure_reason=None,
        created_at=created_at,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------


class TestInsert:
    @pytest.mark.asyncio
    async def test_returns_stored_record(self) -> None:
        repo = InMemoryNotificationRepository()
        rec = _make_record(created_at=datetime(2026, 4, 26, 9, 0))
        stored = await repo.insert(rec)
        assert stored is rec
        assert repo.get(rec.id) is rec

    @pytest.mark.asyncio
    async def test_duplicate_id_raises(self) -> None:
        repo = InMemoryNotificationRepository()
        rec = _make_record(created_at=datetime(2026, 4, 26, 9, 0))
        await repo.insert(rec)
        with pytest.raises(ValueError, match="duplicate"):
            await repo.insert(rec)


# ---------------------------------------------------------------------------
# fetch_next_pending
# ---------------------------------------------------------------------------


class TestFetchNextPending:
    @pytest.mark.asyncio
    async def test_empty_returns_none(self) -> None:
        repo = InMemoryNotificationRepository()
        assert (
            await repo.fetch_next_pending(now=datetime(2026, 4, 26, 9, 0))
            is None
        )

    @pytest.mark.asyncio
    async def test_priority_order(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        # Insert in reverse priority order to prove ORDER BY priority works.
        low = await repo.insert(
            _make_record(severity="LOW", priority=4, created_at=base)
        )
        med = await repo.insert(
            _make_record(
                severity="MEDIUM",
                priority=3,
                created_at=base + timedelta(seconds=1),
            )
        )
        high = await repo.insert(
            _make_record(
                severity="HIGH",
                priority=2,
                created_at=base + timedelta(seconds=2),
            )
        )
        crit = await repo.insert(
            _make_record(
                severity="CRITICAL",
                priority=1,
                created_at=base + timedelta(seconds=3),
            )
        )
        chosen = await repo.fetch_next_pending(now=base + timedelta(minutes=1))
        assert chosen is not None
        assert chosen.id == crit.id

        # After marking the critical sent, HIGH wins, then MEDIUM, then LOW.
        await repo.mark_sent(crit.id, sent_at=base + timedelta(minutes=2))
        chosen = await repo.fetch_next_pending(now=base + timedelta(minutes=2))
        assert chosen is not None
        assert chosen.id == high.id

        await repo.mark_sent(high.id, sent_at=base + timedelta(minutes=2))
        chosen = await repo.fetch_next_pending(now=base + timedelta(minutes=2))
        assert chosen is not None
        assert chosen.id == med.id

        await repo.mark_sent(med.id, sent_at=base + timedelta(minutes=2))
        chosen = await repo.fetch_next_pending(now=base + timedelta(minutes=2))
        assert chosen is not None
        assert chosen.id == low.id

    @pytest.mark.asyncio
    async def test_fifo_within_priority(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        first = await repo.insert(
            _make_record(severity="HIGH", priority=2, created_at=base)
        )
        await repo.insert(
            _make_record(
                severity="HIGH",
                priority=2,
                created_at=base + timedelta(seconds=1),
            )
        )
        chosen = await repo.fetch_next_pending(now=base + timedelta(minutes=1))
        assert chosen is not None
        assert chosen.id == first.id

    @pytest.mark.asyncio
    async def test_skips_expired_medium(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        expired = await repo.insert(
            _make_record(
                severity="MEDIUM",
                priority=3,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )
        fresh = await repo.insert(
            _make_record(
                severity="LOW",
                priority=4,
                created_at=base + timedelta(seconds=1),
                expires_at=base + timedelta(minutes=20),
            )
        )
        # The MEDIUM is past expiry but the LOW is still fresh.
        chosen = await repo.fetch_next_pending(
            now=base + timedelta(minutes=10)
        )
        assert chosen is not None
        # MEDIUM (priority 3) is skipped, LOW (priority 4) wins.
        assert chosen.id == fresh.id
        # The expired record itself is still PENDING until expire_stale runs.
        assert repo.get(expired.id) is not None
        assert repo.get(expired.id).status is NotificationStatus.PENDING  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_critical_never_expires(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        # Even with an expires_at set, CRITICAL should still be picked.
        crit = await repo.insert(
            _make_record(
                severity="CRITICAL",
                priority=1,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )
        # 1 hour later -- well past the (incorrect) expires_at.
        chosen = await repo.fetch_next_pending(now=base + timedelta(hours=1))
        assert chosen is not None
        assert chosen.id == crit.id

    @pytest.mark.asyncio
    async def test_skips_non_pending(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        sent = await repo.insert(
            _make_record(
                severity="HIGH",
                priority=2,
                created_at=base,
                status=NotificationStatus.SENT,
            )
        )
        pending = await repo.insert(
            _make_record(
                severity="LOW",
                priority=4,
                created_at=base + timedelta(seconds=1),
            )
        )
        chosen = await repo.fetch_next_pending(now=base + timedelta(minutes=1))
        assert chosen is not None
        assert chosen.id == pending.id
        assert chosen.id != sent.id


# ---------------------------------------------------------------------------
# mark_sent / mark_failed
# ---------------------------------------------------------------------------


class TestMarkTransitions:
    @pytest.mark.asyncio
    async def test_mark_sent(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        rec = await repo.insert(_make_record(created_at=base))
        await repo.mark_sent(rec.id, sent_at=base + timedelta(seconds=2))
        updated = repo.get(rec.id)
        assert updated is not None
        assert updated.status is NotificationStatus.SENT
        assert updated.sent_at == base + timedelta(seconds=2)

    @pytest.mark.asyncio
    async def test_mark_failed_revert(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        rec = await repo.insert(_make_record(created_at=base))
        await repo.mark_failed(
            rec.id,
            failed_at=base + timedelta(seconds=3),
            reason="boom",
            revert_to_pending=True,
        )
        updated = repo.get(rec.id)
        assert updated is not None
        # revert=True keeps the row in the queue.
        assert updated.status is NotificationStatus.PENDING
        assert updated.failure_reason == "boom"
        assert updated.failed_at == base + timedelta(seconds=3)
        assert updated.retry_count == 1

    @pytest.mark.asyncio
    async def test_mark_failed_terminal(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        rec = await repo.insert(_make_record(created_at=base))
        await repo.mark_failed(
            rec.id,
            failed_at=base,
            reason="permanent",
            revert_to_pending=False,
        )
        updated = repo.get(rec.id)
        assert updated is not None
        assert updated.status is NotificationStatus.FAILED
        assert updated.retry_count == 1

    @pytest.mark.asyncio
    async def test_mark_unknown_id_raises(self) -> None:
        repo = InMemoryNotificationRepository()
        with pytest.raises(KeyError):
            await repo.mark_sent("missing", sent_at=datetime.now())


# ---------------------------------------------------------------------------
# find_recent_by_rate_limit_key
# ---------------------------------------------------------------------------


class TestFindRecentByRateLimitKey:
    @pytest.mark.asyncio
    async def test_returns_match_within_window(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        rec = await repo.insert(
            _make_record(
                created_at=base + timedelta(minutes=2),
                rate_limit_key="K:000",
            )
        )
        found = await repo.find_recent_by_rate_limit_key(
            rate_limit_key="K:000",
            since=base,  # 2 minutes ago counts
        )
        assert found is not None
        assert found.id == rec.id

    @pytest.mark.asyncio
    async def test_outside_window_returns_none(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        await repo.insert(
            _make_record(created_at=base, rate_limit_key="K:000")
        )
        found = await repo.find_recent_by_rate_limit_key(
            rate_limit_key="K:000",
            since=base + timedelta(minutes=10),
        )
        assert found is None

    @pytest.mark.asyncio
    async def test_returns_most_recent(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        await repo.insert(
            _make_record(created_at=base, rate_limit_key="K")
        )
        latest = await repo.insert(
            _make_record(
                created_at=base + timedelta(minutes=4),
                rate_limit_key="K",
            )
        )
        found = await repo.find_recent_by_rate_limit_key(
            rate_limit_key="K", since=base
        )
        assert found is not None
        assert found.id == latest.id

    @pytest.mark.asyncio
    async def test_distinct_keys_dont_collide(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        await repo.insert(
            _make_record(created_at=base, rate_limit_key="A")
        )
        found = await repo.find_recent_by_rate_limit_key(
            rate_limit_key="B", since=base - timedelta(hours=1)
        )
        assert found is None


# ---------------------------------------------------------------------------
# expire_stale
# ---------------------------------------------------------------------------


class TestExpireStale:
    @pytest.mark.asyncio
    async def test_expires_only_medium_low(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        med = await repo.insert(
            _make_record(
                severity="MEDIUM",
                priority=3,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )
        low = await repo.insert(
            _make_record(
                severity="LOW",
                priority=4,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )
        crit = await repo.insert(
            _make_record(
                severity="CRITICAL",
                priority=1,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )
        high = await repo.insert(
            _make_record(
                severity="HIGH",
                priority=2,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )

        count = await repo.expire_stale(now=base + timedelta(minutes=10))
        assert count == 2

        assert repo.get(med.id).status is NotificationStatus.EXPIRED  # type: ignore[union-attr]
        assert repo.get(low.id).status is NotificationStatus.EXPIRED  # type: ignore[union-attr]
        assert repo.get(crit.id).status is NotificationStatus.PENDING  # type: ignore[union-attr]
        assert repo.get(high.id).status is NotificationStatus.PENDING  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_idempotent(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        await repo.insert(
            _make_record(
                severity="LOW",
                priority=4,
                created_at=base,
                expires_at=base + timedelta(minutes=5),
            )
        )
        first = await repo.expire_stale(now=base + timedelta(minutes=10))
        second = await repo.expire_stale(now=base + timedelta(minutes=20))
        assert first == 1
        assert second == 0


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_all_records_snapshot(self) -> None:
        repo = InMemoryNotificationRepository()
        base = datetime(2026, 4, 26, 9, 0)
        await repo.insert(_make_record(created_at=base))
        await repo.insert(_make_record(created_at=base + timedelta(seconds=1)))
        assert len(repo.all_records()) == 2
