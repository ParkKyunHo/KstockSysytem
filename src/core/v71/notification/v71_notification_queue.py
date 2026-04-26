"""Priority queue with rate limit + expiry (P4.1).

Spec:
  - 02_TRADING_RULES.md §9.3 (priority queue ordering)
  - 02_TRADING_RULES.md §9.5 (rate limit -- 5 minutes per event+stock,
    CRITICAL bypasses)
  - 02_TRADING_RULES.md §9.4 (Circuit OPEN handling -- CRITICAL/HIGH
    queued indefinitely, MEDIUM/LOW expire after 5 min)
  - 03_DATA_MODEL.md §3.4 (notifications table)

Responsibilities:
  - Wrap a :class:`NotificationRepository` and add the queue semantics
    that don't belong on a pure persistence layer.
  - Resolve priority (CRITICAL=1 ... LOW=4) -- mirrors the
    ``priority`` ENUM in migration 014.
  - Enforce per-key rate limit: same ``(event_type, stock_code)``
    suppressed within 5 minutes (CRITICAL skips this).
  - Compute ``expires_at`` for MEDIUM/LOW (CRITICAL/HIGH stay forever).
  - Hand work to the worker through :meth:`next_pending`.

The queue is feature-flagged behind ``v71.notification_v71``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.v71.notification.v71_notification_repository import (
    NotificationRecord,
    NotificationRepository,
    NotificationStatus,
    new_notification_id,
)
from src.core.v71.skills.notification_skill import (
    Severity,
    severity_to_priority,
)
from src.core.v71.strategies.v71_buy_executor import Clock
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_VALUES: tuple[str, ...] = tuple(s.value for s in Severity)
_NEVER_EXPIRE: frozenset[str] = frozenset({"CRITICAL", "HIGH"})
_CRITICAL: str = "CRITICAL"


def _normalise_severity(severity: str) -> str:
    """Coerce ``severity`` to one of the four canonical values.

    Accepts :class:`Severity` enum members for ergonomic call sites
    (``Severity.CRITICAL``) as well as raw strings (``"CRITICAL"``).
    """
    if isinstance(severity, Severity):
        return severity.value
    if severity not in _SEVERITY_VALUES:
        raise ValueError(
            f"unknown severity {severity!r}; expected one of {_SEVERITY_VALUES}"
        )
    return severity


def _resolve_channel(severity: str) -> str:
    """CRITICAL/HIGH -> BOTH (telegram + web), MEDIUM/LOW -> TELEGRAM."""
    return "BOTH" if severity in _NEVER_EXPIRE else "TELEGRAM"


def _expires_at(severity: str, *, now: datetime) -> datetime | None:
    """``None`` for CRITICAL/HIGH; ``now + 5 min`` otherwise."""
    if severity in _NEVER_EXPIRE:
        return None
    return now + timedelta(
        minutes=V71Constants.NOTIFICATION_MEDIUM_LOW_EXPIRY_MINUTES
    )


# ---------------------------------------------------------------------------
# Suppression
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnqueueOutcome:
    """Result of an :meth:`V71NotificationQueue.enqueue` call.

    ``record`` is None when the request was suppressed (rate-limited).
    ``suppression_reason`` is set in that case (``RATE_LIMIT``).
    """

    record: NotificationRecord | None
    suppression_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.record is not None


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class V71NotificationQueue:
    """Priority queue API on top of a :class:`NotificationRepository`."""

    def __init__(
        self,
        *,
        repository: NotificationRepository,
        clock: Clock,
        rate_limit_minutes: int | None = None,
    ) -> None:
        require_enabled("v71.notification_v71")
        self._repo = repository
        self._clock = clock
        self._rate_limit_minutes = (
            rate_limit_minutes
            if rate_limit_minutes is not None
            else V71Constants.NOTIFICATION_RATE_LIMIT_MINUTES
        )
        if self._rate_limit_minutes < 0:
            raise ValueError("rate_limit_minutes must be >= 0")

    # ------------------------------------------------------------------
    # Producer side (V71NotificationService.notify -> here)
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        *,
        severity: str | Severity,
        event_type: str,
        message: str,
        stock_code: str | None = None,
        title: str | None = None,
        payload: dict[str, Any] | None = None,
        rate_limit_key: str | None = None,
    ) -> EnqueueOutcome:
        """Persist a new notification request, applying rate limit.

        Returns:
            :class:`EnqueueOutcome` with ``accepted=True`` and the stored
            record if persisted, ``accepted=False`` and a non-empty
            ``suppression_reason`` if suppressed (rate limited).
        """
        sev = _normalise_severity(
            severity.value if isinstance(severity, Severity) else severity
        )

        # CRITICAL bypasses rate limit (§9.5).
        if (
            sev != _CRITICAL
            and rate_limit_key
            and await self._is_rate_limited(rate_limit_key)
        ):
            return EnqueueOutcome(
                record=None,
                suppression_reason="RATE_LIMIT",
            )

        now = self._clock.now()
        record = NotificationRecord(
            id=new_notification_id(),
            severity=sev,
            channel=_resolve_channel(sev),
            event_type=event_type,
            stock_code=stock_code,
            title=title,
            message=message,
            payload=payload,
            status=NotificationStatus.PENDING,
            priority=severity_to_priority(sev),
            rate_limit_key=rate_limit_key,
            retry_count=0,
            sent_at=None,
            failed_at=None,
            failure_reason=None,
            created_at=now,
            expires_at=_expires_at(sev, now=now),
        )
        stored = await self._repo.insert(record)
        return EnqueueOutcome(record=stored)

    async def is_rate_limited(
        self, *, rate_limit_key: str, severity: str | Severity = "HIGH"
    ) -> bool:
        """Public-side rate-limit query.

        CRITICAL always returns False (it bypasses); other severities
        check the 5-minute window. Surfaced for the unit tests and for
        external callers that want to decide *before* allocating a record.
        """
        sev = _normalise_severity(
            severity.value if isinstance(severity, Severity) else severity
        )
        if sev == _CRITICAL:
            return False
        return await self._is_rate_limited(rate_limit_key)

    # ------------------------------------------------------------------
    # Consumer side (worker -> here)
    # ------------------------------------------------------------------

    async def next_pending(self) -> NotificationRecord | None:
        """Highest-priority PENDING record, or ``None`` if queue empty."""
        return await self._repo.fetch_next_pending(now=self._clock.now())

    async def mark_sent(self, notification_id: str) -> None:
        await self._repo.mark_sent(
            notification_id, sent_at=self._clock.now()
        )

    async def mark_failed(
        self,
        notification_id: str,
        *,
        reason: str,
        revert_to_pending: bool,
    ) -> None:
        """Record a delivery failure.

        ``revert_to_pending=True`` keeps the row in the queue so the
        worker can retry once the Circuit closes (CRITICAL/HIGH on
        OPEN). ``False`` retires the row to ``FAILED`` permanently.
        """
        await self._repo.mark_failed(
            notification_id,
            failed_at=self._clock.now(),
            reason=reason,
            revert_to_pending=revert_to_pending,
        )

    async def expire_stale(self) -> int:
        """Reap MEDIUM/LOW PENDING records past their ``expires_at``."""
        return await self._repo.expire_stale(now=self._clock.now())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _is_rate_limited(self, rate_limit_key: str) -> bool:
        if self._rate_limit_minutes == 0:
            return False
        since = self._clock.now() - timedelta(
            minutes=self._rate_limit_minutes
        )
        recent = await self._repo.find_recent_by_rate_limit_key(
            rate_limit_key=rate_limit_key,
            since=since,
        )
        return recent is not None


__all__ = ["EnqueueOutcome", "V71NotificationQueue"]
