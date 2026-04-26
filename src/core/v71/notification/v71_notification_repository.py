"""Notification persistence layer (P4.1).

Two implementations:
  - :class:`InMemoryNotificationRepository` -- the unit-test bedrock and
    the bootstrap impl used until Supabase is wired in. Mirrors the
    PostgreSQL semantics needed by the queue (priority order, FIFO within
    a priority, atomic dequeue, expiry filter).
  - :class:`PostgresNotificationRepository` -- production impl that maps
    onto the ``notifications`` table (migration 014). Uses
    ``FOR UPDATE SKIP LOCKED`` to dequeue safely under multi-worker /
    multi-process scenarios. Body kept thin so unit-test coverage focuses
    on :class:`InMemoryNotificationRepository`; the PG variant is exercised
    by the Phase 5 integration suite.

The :class:`NotificationRepository` Protocol is the only surface other
V7.1 modules see.

Spec:
  - 02_TRADING_RULES.md §9 (severity tiers, priority queue, expiry)
  - 03_DATA_MODEL.md §3.4 (notifications table schema)
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class NotificationStatus(Enum):
    """Mirrors ``notification_status`` ENUM in migration 014."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class NotificationRecord:
    """One row in the notifications queue.

    Field names mirror the ``notifications`` table (migration 014). The
    dataclass is frozen so every state transition (mark_sent / mark_failed
    / etc.) returns a new copy -- callers cannot mutate the queue out from
    under a worker mid-dequeue.
    """

    id: str
    severity: str  # CRITICAL / HIGH / MEDIUM / LOW
    channel: str  # TELEGRAM / WEB / BOTH
    event_type: str
    stock_code: str | None
    title: str | None
    message: str
    payload: dict[str, Any] | None
    status: NotificationStatus
    priority: int  # 1 (CRITICAL) ... 4 (LOW)
    rate_limit_key: str | None
    retry_count: int
    sent_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    expires_at: datetime | None


class NotificationRepository(Protocol):
    """Persistence surface for the queue."""

    async def insert(self, record: NotificationRecord) -> NotificationRecord:
        """Persist a new ``PENDING`` row. Returns the stored record."""
        ...

    async def fetch_next_pending(
        self, *, now: datetime
    ) -> NotificationRecord | None:
        """Atomically claim the highest-priority PENDING row.

        Atomicity matters: in PG this is ``SELECT ... FOR UPDATE SKIP LOCKED``;
        in-memory uses an :class:`asyncio.Lock`. Returns ``None`` when the
        queue is empty.

        Implementations may ignore expired MEDIUM/LOW rows -- callers
        also call :meth:`expire_stale` separately so workers don't pull
        already-stale entries.
        """
        ...

    async def mark_sent(
        self, notification_id: str, *, sent_at: datetime
    ) -> None:
        """Transition a row to ``SENT`` after successful delivery."""
        ...

    async def mark_failed(
        self,
        notification_id: str,
        *,
        failed_at: datetime,
        reason: str,
        revert_to_pending: bool,
    ) -> None:
        """Record a failure.

        ``revert_to_pending=True`` keeps the row in the queue (CRITICAL/HIGH
        on Circuit OPEN, transient telegram error, etc.). ``False`` retires
        the row to ``FAILED`` permanently (CRITICAL after retry_count
        exhausted, MEDIUM/LOW on permanent error).

        ``retry_count`` is incremented in either case.
        """
        ...

    async def find_recent_by_rate_limit_key(
        self,
        *,
        rate_limit_key: str,
        since: datetime,
    ) -> NotificationRecord | None:
        """Most recent record with matching key whose ``created_at >= since``.

        Used by the queue for the 5-minute rate-limit window
        (02_TRADING_RULES.md §9.5). CRITICAL records bypass this check
        upstream so they are never suppressed.
        """
        ...

    async def expire_stale(self, *, now: datetime) -> int:
        """Mark MEDIUM/LOW PENDING rows past ``expires_at`` as ``EXPIRED``.

        CRITICAL/HIGH rows are never expired (§9.4 -- they are queued
        indefinitely until the Circuit closes). Returns the number of rows
        affected.
        """
        ...

    async def list_recent(
        self, *, limit: int, since: datetime | None = None
    ) -> list[NotificationRecord]:
        """Return up to ``limit`` records ordered by ``created_at`` DESC.

        ``since`` filters to records with ``created_at >= since`` when
        provided (no filter when None). Used by the ``/alerts`` telegram
        command to surface recent notification history.
        """
        ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


@dataclass
class InMemoryNotificationRepository:
    """In-memory queue used by tests and the bootstrap bring-up.

    Storage: an ordered dict ``id -> record``. Concurrent ``fetch_next_pending``
    calls are serialised through an :class:`asyncio.Lock`, which is sufficient
    for the single-process worker layout in §9.3.
    """

    _records: dict[str, NotificationRecord] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ------------------------------------------------------------------
    # NotificationRepository Protocol surface
    # ------------------------------------------------------------------

    async def insert(self, record: NotificationRecord) -> NotificationRecord:
        # Guard against accidental id collisions; never silently overwrite.
        if record.id in self._records:
            raise ValueError(f"duplicate notification id {record.id}")
        self._records[record.id] = record
        return record

    async def fetch_next_pending(
        self, *, now: datetime
    ) -> NotificationRecord | None:
        async with self._lock:
            candidate: NotificationRecord | None = None
            for record in self._records.values():
                if record.status is not NotificationStatus.PENDING:
                    continue
                if self._is_expired(record, now):
                    # Skip stale MEDIUM/LOW; they are reaped by ``expire_stale``.
                    continue
                if candidate is None or self._is_better(record, candidate):
                    candidate = record
            if candidate is None:
                return None
            # Hand the row out as still-pending (the worker calls
            # mark_sent / mark_failed afterwards). No reservation
            # state -- a single-worker layout is sufficient (§9.3).
            return candidate

    async def mark_sent(
        self, notification_id: str, *, sent_at: datetime
    ) -> None:
        record = self._require(notification_id)
        self._records[notification_id] = replace(
            record,
            status=NotificationStatus.SENT,
            sent_at=sent_at,
        )

    async def mark_failed(
        self,
        notification_id: str,
        *,
        failed_at: datetime,
        reason: str,
        revert_to_pending: bool,
    ) -> None:
        record = self._require(notification_id)
        new_status = (
            NotificationStatus.PENDING
            if revert_to_pending
            else NotificationStatus.FAILED
        )
        self._records[notification_id] = replace(
            record,
            status=new_status,
            failed_at=failed_at,
            failure_reason=reason,
            retry_count=record.retry_count + 1,
        )

    async def find_recent_by_rate_limit_key(
        self,
        *,
        rate_limit_key: str,
        since: datetime,
    ) -> NotificationRecord | None:
        latest: NotificationRecord | None = None
        for record in self._records.values():
            if record.rate_limit_key != rate_limit_key:
                continue
            if record.created_at < since:
                continue
            if latest is None or record.created_at > latest.created_at:
                latest = record
        return latest

    async def expire_stale(self, *, now: datetime) -> int:
        count = 0
        for nid, record in list(self._records.items()):
            if record.status is not NotificationStatus.PENDING:
                continue
            if not self._is_expired(record, now):
                continue
            self._records[nid] = replace(
                record,
                status=NotificationStatus.EXPIRED,
            )
            count += 1
        return count

    async def list_recent(
        self, *, limit: int, since: datetime | None = None
    ) -> list[NotificationRecord]:
        if limit <= 0:
            return []
        candidates: list[NotificationRecord] = [
            r
            for r in self._records.values()
            if since is None or r.created_at >= since
        ]
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        return candidates[:limit]

    # ------------------------------------------------------------------
    # Test-only helpers (NOT part of the Protocol surface)
    # ------------------------------------------------------------------

    def all_records(self) -> list[NotificationRecord]:
        """Snapshot for assertions."""
        return list(self._records.values())

    def get(self, notification_id: str) -> NotificationRecord | None:
        return self._records.get(notification_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_expired(record: NotificationRecord, now: datetime) -> bool:
        # CRITICAL/HIGH never expire (§9.4).
        if record.severity in ("CRITICAL", "HIGH"):
            return False
        if record.expires_at is None:
            return False
        return now >= record.expires_at

    @staticmethod
    def _is_better(
        candidate: NotificationRecord, current_best: NotificationRecord
    ) -> bool:
        """Lower priority number wins; FIFO within the same priority."""
        if candidate.priority < current_best.priority:
            return True
        if candidate.priority > current_best.priority:
            return False
        return candidate.created_at < current_best.created_at

    def _require(self, notification_id: str) -> NotificationRecord:
        record = self._records.get(notification_id)
        if record is None:
            raise KeyError(f"notification {notification_id} not found")
        return record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_notification_id() -> str:
    """Stable UUIDv4 generator -- isolated for testability (monkey-patchable).

    Note:
        The Postgres-backed implementation lives in
        :mod:`src.core.v71.notification.v71_postgres_notification_repository`.
        It satisfies :class:`NotificationRepository` and is wired in by
        the runtime bootstrap; unit tests use
        :class:`InMemoryNotificationRepository`.
    """
    return str(uuid.uuid4())


__all__ = [
    "InMemoryNotificationRepository",
    "NotificationRecord",
    "NotificationRepository",
    "NotificationStatus",
    "new_notification_id",
]
