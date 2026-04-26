"""Skill 6: Notification queue + delivery.

Spec: docs/v71/07_SKILLS_SPEC.md §6, docs/v71/02_TRADING_RULES.md §9

Constitution: do NOT call ``telegram.send_message()`` directly. Always
go through :func:`send_notification`, which:
  - assigns priority (CRITICAL=1 ... LOW=4),
  - applies rate limiting per (event_type, stock_code) -- CRITICAL bypasses,
  - persists to the ``notifications`` table for retry / audit,
  - resolves channel routing (Telegram primary, Web for HIGH+).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EventType(Enum):
    # CRITICAL
    STOP_LOSS = "STOP_LOSS"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    NEW_IP_DETECTED = "NEW_IP_DETECTED"
    # HIGH
    BUY_EXECUTED = "BUY_EXECUTED"
    PROFIT_TAKE_5 = "PROFIT_TAKE_5"
    PROFIT_TAKE_10 = "PROFIT_TAKE_10"
    MANUAL_TRADE_DETECTED = "MANUAL_TRADE_DETECTED"
    # MEDIUM
    BOX_ENTRY_IMMINENT = "BOX_ENTRY_IMMINENT"
    WEBSOCKET_DISCONNECTED = "WEBSOCKET_DISCONNECTED"
    BOX_EXPIRY_REMINDER = "BOX_EXPIRY_REMINDER"
    # LOW
    DAILY_SUMMARY = "DAILY_SUMMARY"
    HEALTH_CHECK = "HEALTH_CHECK"
    MONTHLY_REVIEW = "MONTHLY_REVIEW"


@dataclass(frozen=True)
class NotificationRequest:
    severity: Severity
    event_type: EventType
    title: str
    message: str
    stock_code: str | None = None
    payload: dict | None = None


@dataclass(frozen=True)
class NotificationResult:
    notification_id: str
    status: str  # "SENT" | "PENDING" | "SUPPRESSED" | "FAILED"
    suppression_reason: str | None


async def send_notification(
    request: NotificationRequest,
    *,
    db_context: object,        # SQLAlchemy session / connection pool
    telegram_client: object,   # V7.0 src.notification.telegram.TelegramBot
    web_dispatcher: object | None = None,
) -> NotificationResult:
    """Enqueue and deliver per severity rules (07_SKILLS_SPEC.md §6.3)."""
    raise NotImplementedError("P4.1 -- see docs/v71/07_SKILLS_SPEC.md §6.3")


def severity_to_priority(severity: Severity) -> int:
    """CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4. Used by the queue order-by."""
    raise NotImplementedError("P4.1 -- see docs/v71/07_SKILLS_SPEC.md §6.4")


def make_rate_limit_key(event_type: EventType, stock_code: str | None) -> str:
    """Stable per-(event, stock) key for the rate-limit window."""
    raise NotImplementedError("P4.1 -- see docs/v71/07_SKILLS_SPEC.md §6.5")


def format_stop_loss_message(stock_code: str, stock_name: str,
                             avg_price: int, exit_price: int,
                             pnl_amount: int, pnl_pct: float) -> str:
    """Standard CRITICAL stop-loss telegram body."""
    raise NotImplementedError("P4.1 -- see docs/v71/07_SKILLS_SPEC.md §6.6")


__all__ = [
    "Severity",
    "EventType",
    "NotificationRequest",
    "NotificationResult",
    "send_notification",
    "severity_to_priority",
    "make_rate_limit_key",
    "format_stop_loss_message",
]
