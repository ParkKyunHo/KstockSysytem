"""V7.1 Kiwoom error → notification helper.

Spec sources:
  - 02_TRADING_RULES.md §9 (severity tiers + standard message format)
  - 07_SKILLS_SPEC.md §6 (notification_skill -- canonical surface)
  - error_mapper severity / fatal / refresh / backoff policy hints
  - KIWOOM_API_ANALYSIS.md (1700 / 1999 / 8005 / 8010 / 8030 / 8031)

Design (architect-aligned):
  * Pure transport-aware wrapper. Domain layer (skills) stays decoupled
    from broker-specific exception types; this module is the bridge.
  * No queue ownership: the helper takes a queue + an error and
    returns the resulting :class:`NotificationResult` from
    ``send_notification``. The orchestrator owns the queue lifecycle.
  * Mapping is read-only via ``MappingProxyType`` (P5-Kiwoom-3 pattern).
    Unknown error subclasses fall through to ``SYSTEM_ERROR`` so the
    helper never silently drops an alert.

Out of scope:
  * Telegram delivery (handled downstream by V71NotificationService).
  * Per-error rate-limit policy override (the queue's 5-minute window
    + ``send_notification`` CRITICAL bypass already cover §9.5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Final

from src.core.v71.exchange.error_mapper import (
    V71KiwoomEnvMismatchError,
    V71KiwoomIPMismatchError,
    V71KiwoomMappedError,
    V71KiwoomRateLimitError,
    V71KiwoomServerError,
    V71KiwoomTokenInvalidError,
    is_fatal,
    should_force_token_refresh,
    should_retry_with_backoff,
)
from src.core.v71.skills.notification_skill import (
    EventType,
    NotificationRequest,
    NotificationResult,
    Severity,
    format_kiwoom_error_message,
    send_notification,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Security M1 (Step 4 review): mirror order_manager._FORBIDDEN_RESPONSE_KEYS
# so caller-supplied ``extra_payload`` cannot smuggle a credential into
# the persisted notifications.payload column. Kept local (small fixed
# set) instead of cross-module import to avoid private-attribute coupling.
_FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset({
    "token",
    "access_token",
    "Authorization",
    "authorization",
    "app_key",
    "appkey",
    "app_secret",
    "secretkey",
    "secret",
})
_REDACTED = "***REDACTED***"

# Reserved keys the helper itself owns; ``extra_payload`` cannot
# overwrite them or operators would see a falsified ``is_fatal=False``
# on a CRITICAL incident.
_RESERVED_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset({
    "return_code",
    "api_id",
    "is_fatal",
    "should_force_token_refresh",
    "should_retry_with_backoff",
})


# Subclass → EventType. Anything outside this map (e.g.
# V71StockNotFoundError, V71KiwoomInvalidInputError) is rare and not
# operationally interesting at the transport level; treat as SYSTEM_ERROR
# so the operator still sees it once.
_KIWOOM_ERROR_TO_EVENT_TYPE: Mapping[type[V71KiwoomMappedError], EventType] = (
    MappingProxyType({
        V71KiwoomRateLimitError: EventType.KIWOOM_RATE_LIMIT_EXCEEDED,
        V71KiwoomTokenInvalidError: EventType.KIWOOM_TOKEN_INVALID,
        V71KiwoomIPMismatchError: EventType.KIWOOM_IP_MISMATCH,
        V71KiwoomEnvMismatchError: EventType.KIWOOM_ENV_MISMATCH,
        V71KiwoomServerError: EventType.KIWOOM_SERVER_ERROR,
    })
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_kiwoom_error_request(
    error: V71KiwoomMappedError,
    *,
    api_id_override: str | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> NotificationRequest:
    """Compose a :class:`NotificationRequest` from a typed Kiwoom error.

    The severity comes from ``error_mapper.severity_for`` (already bound
    to the error instance as ``error.severity``). The event type comes
    from ``_KIWOOM_ERROR_TO_EVENT_TYPE`` -- unknown subclasses degrade
    to ``EventType.SYSTEM_ERROR`` so callers never lose an alert.

    The payload carries the three operator-actionable hints
    (``is_fatal`` / ``should_force_token_refresh`` /
    ``should_retry_with_backoff``) plus the raw broker fields, so the
    web side can render the same context the message body shows.
    """
    # Security M2 (Step 4 review): a notification helper must never
    # raise -- swallowing a CRITICAL alert because of a future Severity
    # enum drift would be a silent operator-blindness bug. Fall back to
    # HIGH and log so the cast failure is itself observable.
    try:
        severity = Severity(error.severity)
    except ValueError:
        logger.error(
            "v71_kiwoom_severity_cast_failed",
            error_type=type(error).__name__,
            return_code=error.return_code,
        )
        severity = Severity.HIGH
    event_type = _KIWOOM_ERROR_TO_EVENT_TYPE.get(
        type(error), EventType.SYSTEM_ERROR,
    )
    fatal = is_fatal(error)
    refresh = should_force_token_refresh(error)
    backoff = should_retry_with_backoff(error)
    timestamp = (clock or _utcnow)()
    title, message = format_kiwoom_error_message(
        severity=severity,
        event_type=event_type,
        return_code=error.return_code,
        api_id=api_id_override or error.api_id,
        return_msg=error.return_msg,
        timestamp=timestamp,
        is_fatal=fatal,
        should_force_token_refresh=refresh,
        should_retry_with_backoff=backoff,
    )
    payload: dict[str, Any] = {
        "return_code": error.return_code,
        "api_id": api_id_override or error.api_id,
        "is_fatal": fatal,
        "should_force_token_refresh": refresh,
        "should_retry_with_backoff": backoff,
    }
    if extra_payload:
        # Security M1 (Step 4 review): redact forbidden keys + drop
        # reserved keys. The helper owns canonical alert metadata; a
        # buggy / malicious caller cannot overwrite ``is_fatal=True``
        # on an 8010 IP mismatch by passing ``is_fatal=False``.
        for key, value in extra_payload.items():
            if key in _RESERVED_PAYLOAD_KEYS:
                logger.warning(
                    "v71_kiwoom_extra_payload_reserved_key_dropped",
                    key=key,
                )
                continue
            if key in _FORBIDDEN_PAYLOAD_KEYS:
                payload[key] = _REDACTED
                logger.warning(
                    "v71_kiwoom_extra_payload_forbidden_key_redacted",
                    key=key,
                )
                continue
            payload[key] = value
    return NotificationRequest(
        severity=severity,
        event_type=event_type,
        title=title,
        message=message,
        stock_code=None,
        payload=payload,
    )


async def notify_kiwoom_error(
    error: V71KiwoomMappedError,
    *,
    queue: Any,  # V71NotificationQueue, runtime forward reference
    api_id_override: str | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> NotificationResult:
    """Build + enqueue a notification for a typed Kiwoom error.

    Convenience over ``build_kiwoom_error_request`` + ``send_notification``
    -- the two-step form is also exported for tests / advanced callers.
    """
    request = build_kiwoom_error_request(
        error,
        api_id_override=api_id_override,
        extra_payload=extra_payload,
        clock=clock,
    )
    return await send_notification(request, queue=queue)


__all__ = [
    "build_kiwoom_error_request",
    "notify_kiwoom_error",
]
