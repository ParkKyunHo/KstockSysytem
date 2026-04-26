"""Skill 6: Notification queue + delivery (P4.1 implementation).

Spec:
  - 02_TRADING_RULES.md §9 (severity tiers, priority queue, rate limit,
    Circuit Breaker, standard message format)
  - 07_SKILLS_SPEC.md §6 (notification_skill surface)
  - 03_DATA_MODEL.md §3.4 (notifications table)

Constitution:
  - Do NOT call ``telegram.send_message()`` directly anywhere in V7.1
    code. Always go through :func:`send_notification` (this module) or
    :class:`V71NotificationService` (Notifier Protocol implementation).
    Harness 3 (``trading_rule_enforcer.py``) enforces this.

This module provides:
  - :class:`Severity` and :class:`EventType` enums (canonical names).
  - :class:`NotificationRequest` and :class:`NotificationResult`
    dataclasses for the public API.
  - :func:`severity_to_priority` and :func:`make_rate_limit_key` --
    pure helpers reused by the queue, the service, and the formatters.
  - 8 standard message formatters mirroring 02_TRADING_RULES.md §9.6.
  - :func:`send_notification` -- thin async wrapper that enqueues the
    request through :class:`V71NotificationQueue`. The actual worker
    that drains the queue lives in :class:`V71NotificationService`.

Severity policy (§9.1):
    CRITICAL  손절, 시스템 오류, WebSocket 30초+ 끊김, 새 IP, 자동 이탈, 시스템 재시작
    HIGH      매수, 익절, 추매, VI 발동, 매수 실패, 수동 거래
    MEDIUM    박스 진입 임박, WebSocket 10초 끊김, 박스 만료 임박, VI 해제
    LOW       일일 마감, 월 1회 리뷰, 헬스 체크
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from src.core.v71.v71_constants import V71Constants

# Note: ``V71NotificationQueue`` is referenced as a string forward
# reference in :func:`send_notification` to avoid a static dependency
# cycle (``v71_notification_queue`` imports from this module). The
# ``from __future__ import annotations`` import keeps all annotations
# as strings at runtime, so no actual import is required.


# ---------------------------------------------------------------------------
# Enums (frozen public surface)
# ---------------------------------------------------------------------------


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
    AUTO_EXIT = "AUTO_EXIT"
    EXIT_REJECTED = "EXIT_REJECTED"
    EXIT_FAILED = "EXIT_FAILED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    RESTART_FREQUENCY_ALERT = "RESTART_FREQUENCY_ALERT"
    # HIGH
    BUY_EXECUTED = "BUY_EXECUTED"
    BUY_ABANDONED = "BUY_ABANDONED"
    PROFIT_5 = "PROFIT_5"
    PROFIT_10 = "PROFIT_10"
    PROFIT_TAKE_5 = "PROFIT_TAKE_5"
    PROFIT_TAKE_10 = "PROFIT_TAKE_10"
    TS_EXIT = "TS_EXIT"
    MANUAL_BUY_DETECTED = "MANUAL_BUY_DETECTED"
    MANUAL_SELL_DETECTED = "MANUAL_SELL_DETECTED"
    MANUAL_TRADE_DETECTED = "MANUAL_TRADE_DETECTED"
    VI_TRIGGERED = "VI_TRIGGERED"
    # MEDIUM
    BOX_ENTRY_IMMINENT = "BOX_ENTRY_IMMINENT"
    BOX_EXPIRY_REMINDER = "BOX_EXPIRY_REMINDER"
    WEBSOCKET_DISCONNECTED = "WEBSOCKET_DISCONNECTED"
    WEBSOCKET_RECONNECTED = "WEBSOCKET_RECONNECTED"
    VI_RESUMED = "VI_RESUMED"
    # LOW
    DAILY_SUMMARY = "DAILY_SUMMARY"
    MONTHLY_REVIEW = "MONTHLY_REVIEW"
    HEALTH_CHECK = "HEALTH_CHECK"


@dataclass(frozen=True)
class NotificationRequest:
    """Inbound request handed to :func:`send_notification`."""

    severity: Severity
    event_type: EventType
    title: str
    message: str
    stock_code: str | None = None
    payload: dict[str, Any] | None = None
    rate_limit_key: str | None = None


@dataclass(frozen=True)
class NotificationResult:
    notification_id: str | None
    status: str  # "QUEUED" | "SUPPRESSED"
    suppression_reason: str | None = None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


_PRIORITY_BY_SEVERITY: dict[str, int] = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 4,
}


def severity_to_priority(severity: str | Severity) -> int:
    """``CRITICAL`` -> 1, ``HIGH`` -> 2, ``MEDIUM`` -> 3, ``LOW`` -> 4.

    Lower numbers sort first in the queue (07_SKILLS_SPEC.md §6.4).
    Accepts both the :class:`Severity` enum and its raw string value.
    """
    key = severity.value if isinstance(severity, Severity) else severity
    if key not in _PRIORITY_BY_SEVERITY:
        raise ValueError(
            f"unknown severity {severity!r}; expected CRITICAL/HIGH/MEDIUM/LOW"
        )
    return _PRIORITY_BY_SEVERITY[key]


def make_rate_limit_key(
    event_type: str | EventType, stock_code: str | None
) -> str:
    """Stable per-(event, stock) key for the rate-limit window.

    Format: ``"{event_type}:{stock_code or '_'}"`` -- keeps the absence
    of a stock distinguishable from stocks named ``""`` or ``"None"``.
    """
    et = event_type.value if isinstance(event_type, EventType) else event_type
    return f"{et}:{stock_code or '_'}"


# ---------------------------------------------------------------------------
# Standard message formatters (02_TRADING_RULES.md §9.6)
# ---------------------------------------------------------------------------
#
# Notes:
#   - All formatters return plain text (no Markdown / HTML).
#     parse_mode is forbidden everywhere (CLAUDE.md 1.1, V6.2-Q FIX).
#   - Korean trader colour convention is honoured by punctuation alone
#     here -- the web side renders the colour. Telegram is monochrome.
#   - Numbers are formatted with thousand separators; percentages use
#     two decimals with explicit ``+`` for gains.


def _fmt_won(amount: int) -> str:
    return f"{amount:,}원"


def _fmt_pct(pct: float) -> str:
    return f"{pct * 100:+.2f}%"


def _fmt_pnl_amount(amount: int) -> str:
    return f"{amount:+,}원"


def _fmt_time(ts: datetime) -> str:
    return ts.strftime("%H:%M:%S")


def format_stop_loss_message(
    *,
    stock_name: str,
    stock_code: str,
    sell_price: int,
    avg_price: int,
    quantity: int,
    timestamp: datetime,
    pnl_amount: int,
    pnl_pct: float,
    reason: str,
    extra: str | None = None,
) -> tuple[str, str]:
    """CRITICAL stop-loss telegram body (02 §9.6)."""
    title = "[CRITICAL] 손절 실행"
    lines = [
        f"종목: {stock_name} ({stock_code})",
        f"매도가: {_fmt_won(sell_price)} (평단가 {_fmt_won(avg_price)})",
        f"수량: {quantity}주",
        f"시각: {_fmt_time(timestamp)}",
        "",
        f"손익: {_fmt_pct(pnl_pct)} ({_fmt_pnl_amount(pnl_amount)})",
        f"사유: {reason}",
    ]
    if extra:
        lines.append("")
        lines.append(extra)
    return title, "\n".join(lines)


def format_buy_message(
    *,
    stock_name: str,
    stock_code: str,
    buy_price: int,
    quantity: int,
    timestamp: datetime,
    path_type: str,
    box_label: str,
    stop_price: int,
    stop_pct: float = V71Constants.STOP_LOSS_INITIAL_PCT,
) -> tuple[str, str]:
    """HIGH buy-executed telegram body (02 §9.6)."""
    title = "[HIGH] 매수 실행"
    total = buy_price * quantity
    lines = [
        f"종목: {stock_name} ({stock_code})",
        (
            f"매수가: {_fmt_won(buy_price)} x {quantity}주 = "
            f"{_fmt_won(total)}"
        ),
        f"시각: {_fmt_time(timestamp)}",
        f"경로: {path_type}",
        f"박스: {box_label}",
        f"손절선: {_fmt_won(stop_price)} ({_fmt_pct(stop_pct)})",
    ]
    return title, "\n".join(lines)


def format_profit_take_message(
    *,
    stock_name: str,
    stock_code: str,
    level: str,  # "+5%" or "+10%"
    sell_price: int,
    quantity: int,
    timestamp: datetime,
    pnl_amount: int,
    pnl_pct: float,
    remaining_quantity: int,
    new_stop_price: int,
) -> tuple[str, str]:
    """HIGH partial take-profit telegram body (02 §9.6)."""
    title = f"[HIGH] {level} 익절"
    lines = [
        f"종목: {stock_name} ({stock_code})",
        f"매도가: {_fmt_won(sell_price)} x {quantity}주",
        f"시각: {_fmt_time(timestamp)}",
        "",
        f"손익: {_fmt_pct(pnl_pct)} ({_fmt_pnl_amount(pnl_amount)})",
        f"잔여: {remaining_quantity}주",
        f"새 손절선: {_fmt_won(new_stop_price)}",
    ]
    return title, "\n".join(lines)


def format_manual_trade_message(
    *,
    stock_name: str,
    stock_code: str,
    direction: str,  # "매수" or "매도"
    quantity: int,
    price: int,
    timestamp: datetime,
    note: str | None = None,
) -> tuple[str, str]:
    """HIGH manual trade detection (02 §7 + §9.6)."""
    title = f"[HIGH] 수동 {direction} 감지"
    lines = [
        f"종목: {stock_name} ({stock_code})",
        f"{direction}: {quantity}주 @ {_fmt_won(price)}",
        f"시각: {_fmt_time(timestamp)}",
    ]
    if note:
        lines.append("")
        lines.append(note)
    return title, "\n".join(lines)


def format_vi_triggered_message(
    *,
    stock_name: str,
    stock_code: str,
    trigger_price: int,
    timestamp: datetime,
) -> tuple[str, str]:
    """HIGH VI triggered (02 §10 + §9.6)."""
    title = "[HIGH] VI 발동"
    lines = [
        f"종목: {stock_name} ({stock_code})",
        f"가격: {_fmt_won(trigger_price)}",
        f"시각: {_fmt_time(timestamp)}",
        "",
        "단일가 매매 진입 (손절/익절 판정 일시 정지)",
    ]
    return title, "\n".join(lines)


def format_box_entry_imminent_message(
    *,
    stock_name: str,
    stock_code: str,
    current_price: int,
    box_label: str,
    distance_pct: float,
) -> tuple[str, str]:
    """MEDIUM box-entry-imminent (02 §9.1)."""
    title = "[MEDIUM] 박스 진입 임박"
    lines = [
        f"종목: {stock_name} ({stock_code})",
        f"현재가: {_fmt_won(current_price)}",
        f"박스: {box_label}",
        f"이격: {_fmt_pct(distance_pct)}",
    ]
    return title, "\n".join(lines)


def format_system_restart_message(
    *,
    timestamp: datetime,
    duration_seconds: float,
    cancelled_orders: int,
    reconciliation_summary: str,
    failures: list[str] | None = None,
) -> tuple[str, str]:
    """CRITICAL post-restart recovery report (02 §13 + §9.6)."""
    title = "[CRITICAL] 시스템 재시작 복구 완료"
    lines = [
        f"완료 시각: {_fmt_time(timestamp)}",
        f"소요: {duration_seconds:.1f}초",
        f"미완료 주문 취소: {cancelled_orders}건",
        f"포지션 정합성: {reconciliation_summary}",
    ]
    if failures:
        lines.append("")
        lines.append("실패한 단계:")
        for f in failures:
            lines.append(f" - {f}")
    return title, "\n".join(lines)


def format_websocket_disconnected_message(
    *,
    timestamp: datetime,
    elapsed_seconds: float,
    severity: Severity,
) -> tuple[str, str]:
    """MEDIUM (10s) or CRITICAL (30s+) websocket-disconnect (02 §9.1)."""
    severity_str = severity.value if isinstance(severity, Severity) else severity
    title = f"[{severity_str}] WebSocket 끊김"
    lines = [
        f"끊김 시각: {_fmt_time(timestamp)}",
        f"경과: {elapsed_seconds:.1f}초",
        "",
        "자동 재연결 시도 중",
    ]
    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def send_notification(
    request: NotificationRequest,
    *,
    queue: V71NotificationQueue,  # noqa: F821 -- forward reference; see header
) -> NotificationResult:
    """Enqueue ``request`` according to severity rules (07 §6.3).

    Behaviour:
      - CRITICAL bypasses the rate limit.
      - HIGH/MEDIUM/LOW are suppressed when an entry with the same
        ``rate_limit_key`` was created within the last 5 minutes.
      - Channel: CRITICAL/HIGH -> ``BOTH`` (telegram + web),
        otherwise ``TELEGRAM`` only.
      - Expiry: CRITICAL/HIGH -> ``None`` (never expire),
        MEDIUM/LOW -> ``now + 5 min`` (Circuit OPEN reaper).

    Args:
        request: composed payload.
        queue: target queue. The :class:`V71NotificationService` owns
            this queue; direct callers pass the same instance.

    Returns:
        :class:`NotificationResult` -- ``status="QUEUED"`` with the
        notification id on success, or ``status="SUPPRESSED"`` with
        ``suppression_reason="RATE_LIMIT"`` if the rate limit fired.
    """
    rate_limit_key = request.rate_limit_key or make_rate_limit_key(
        request.event_type, request.stock_code
    )

    outcome = await queue.enqueue(
        severity=request.severity,
        event_type=(
            request.event_type.value
            if isinstance(request.event_type, EventType)
            else request.event_type
        ),
        message=request.message,
        stock_code=request.stock_code,
        title=request.title,
        payload=request.payload,
        rate_limit_key=rate_limit_key,
    )
    if outcome.accepted:
        assert outcome.record is not None  # for type narrowing
        return NotificationResult(
            notification_id=outcome.record.id,
            status="QUEUED",
        )
    return NotificationResult(
        notification_id=None,
        status="SUPPRESSED",
        suppression_reason=outcome.suppression_reason,
    )


__all__ = [
    "EventType",
    "NotificationRequest",
    "NotificationResult",
    "Severity",
    "format_box_entry_imminent_message",
    "format_buy_message",
    "format_manual_trade_message",
    "format_profit_take_message",
    "format_stop_loss_message",
    "format_system_restart_message",
    "format_vi_triggered_message",
    "format_websocket_disconnected_message",
    "make_rate_limit_key",
    "send_notification",
    "severity_to_priority",
]
