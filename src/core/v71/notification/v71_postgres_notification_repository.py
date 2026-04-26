"""Postgres-backed :class:`NotificationRepository` (P4.1).

Production wiring for the Supabase ``notifications`` table created by
migration 014. Kept in a dedicated module because:

  - it is a thin SQL adapter (no pure logic worth unit-testing in
    isolation) -- exercising it requires a real Postgres instance,
    which lands in the Phase 5 integration suite;
  - separating it lets Harness 7 (90% coverage) skip this file without
    excluding the in-memory implementation that the unit tests rely on.

Spec:
  - 03_DATA_MODEL.md §3.4 (notifications table schema)
  - 02_TRADING_RULES.md §9.3 (FOR UPDATE SKIP LOCKED dequeue)

Wiring:
  - The bootstrap layer (Phase 5 / runtime startup) supplies an
    ``execute(sql, *params) -> rows`` async callable that wraps the
    project's :class:`AsyncSession`. This module does not import
    SQLAlchemy or asyncpg directly; it stays a pure adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.core.v71.notification.v71_notification_repository import (
    NotificationRecord,
    NotificationStatus,
)


@dataclass
class PostgresNotificationRepository:  # pragma: no cover -- integration only
    """Thin SQL adapter; real coverage comes from Phase 5 integration tests."""

    execute: Any
    """Async callable: ``execute(sql: str, *params) -> Sequence[Mapping]``."""

    async def insert(self, record: NotificationRecord) -> NotificationRecord:
        sql = (
            "INSERT INTO notifications "
            "(id, severity, channel, event_type, stock_code, title, message, "
            " payload, status, priority, rate_limit_key, retry_count, "
            " sent_at, failed_at, failure_reason, created_at, expires_at) "
            "VALUES "
            "($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, "
            " $13, $14, $15, $16, $17)"
        )
        await self.execute(
            sql,
            record.id,
            record.severity,
            record.channel,
            record.event_type,
            record.stock_code,
            record.title,
            record.message,
            record.payload,
            record.status.value,
            record.priority,
            record.rate_limit_key,
            record.retry_count,
            record.sent_at,
            record.failed_at,
            record.failure_reason,
            record.created_at,
            record.expires_at,
        )
        return record

    async def fetch_next_pending(
        self, *, now: datetime
    ) -> NotificationRecord | None:
        sql = (
            "SELECT id, severity, channel, event_type, stock_code, title, "
            "       message, payload, status, priority, rate_limit_key, "
            "       retry_count, sent_at, failed_at, failure_reason, "
            "       created_at, expires_at "
            "FROM notifications "
            "WHERE status = 'PENDING' "
            "  AND (severity IN ('CRITICAL', 'HIGH') "
            "       OR expires_at IS NULL "
            "       OR expires_at > $1) "
            "ORDER BY priority ASC, created_at ASC "
            "LIMIT 1 "
            "FOR UPDATE SKIP LOCKED"
        )
        rows = await self.execute(sql, now)
        if not rows:
            return None
        return self._row_to_record(rows[0])

    async def mark_sent(
        self, notification_id: str, *, sent_at: datetime
    ) -> None:
        sql = (
            "UPDATE notifications SET status = 'SENT', sent_at = $2 "
            "WHERE id = $1"
        )
        await self.execute(sql, notification_id, sent_at)

    async def mark_failed(
        self,
        notification_id: str,
        *,
        failed_at: datetime,
        reason: str,
        revert_to_pending: bool,
    ) -> None:
        new_status = "PENDING" if revert_to_pending else "FAILED"
        sql = (
            "UPDATE notifications "
            "SET status = $2, failed_at = $3, failure_reason = $4, "
            "    retry_count = retry_count + 1 "
            "WHERE id = $1"
        )
        await self.execute(
            sql, notification_id, new_status, failed_at, reason
        )

    async def find_recent_by_rate_limit_key(
        self,
        *,
        rate_limit_key: str,
        since: datetime,
    ) -> NotificationRecord | None:
        sql = (
            "SELECT id, severity, channel, event_type, stock_code, title, "
            "       message, payload, status, priority, rate_limit_key, "
            "       retry_count, sent_at, failed_at, failure_reason, "
            "       created_at, expires_at "
            "FROM notifications "
            "WHERE rate_limit_key = $1 AND created_at >= $2 "
            "ORDER BY created_at DESC "
            "LIMIT 1"
        )
        rows = await self.execute(sql, rate_limit_key, since)
        if not rows:
            return None
        return self._row_to_record(rows[0])

    async def expire_stale(self, *, now: datetime) -> int:
        sql = (
            "UPDATE notifications "
            "SET status = 'EXPIRED' "
            "WHERE status = 'PENDING' "
            "  AND severity IN ('MEDIUM', 'LOW') "
            "  AND expires_at IS NOT NULL "
            "  AND expires_at <= $1"
        )
        result = await self.execute(sql, now)
        if isinstance(result, int):
            return result
        return 0

    @staticmethod
    def _row_to_record(row: Any) -> NotificationRecord:
        getter = (
            (lambda key: row[key])
            if hasattr(row, "__getitem__")
            else (lambda key: getattr(row, key))
        )
        return NotificationRecord(
            id=str(getter("id")),
            severity=getter("severity"),
            channel=getter("channel"),
            event_type=getter("event_type"),
            stock_code=getter("stock_code"),
            title=getter("title"),
            message=getter("message"),
            payload=getter("payload"),
            status=NotificationStatus(getter("status")),
            priority=int(getter("priority")),
            rate_limit_key=getter("rate_limit_key"),
            retry_count=int(getter("retry_count")),
            sent_at=getter("sent_at"),
            failed_at=getter("failed_at"),
            failure_reason=getter("failure_reason"),
            created_at=getter("created_at"),
            expires_at=getter("expires_at"),
        )


__all__ = ["PostgresNotificationRepository"]
