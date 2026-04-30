"""V71TelegramCommands -- 13 telegram commands (P4.2).

Spec:
  - 02_TRADING_RULES.md §9.x (notification surface)
  - 05_MIGRATION_PLAN.md §6.3 (P4.2 -- 13 telegram commands)
  - 12_SECURITY.md §3.4 + §8.3 (authorized_chat_ids whitelist + audit)

Commands::

    /status    -- system snapshot (safe-mode, box / position counts, CB,
                  queue depth)
    /positions -- open positions table
    /tracking  -- tracked stocks summary (delegated to ``list_tracked``)
    /pending   -- WAITING boxes
    /today     -- trade events that happened today
    /recent    -- trade events in the last 7 days
    /report    -- on-demand stock report (Phase 6 wiring; this phase
                  returns a stub pointing the user at /tracking + the
                  upcoming integration)
    /stop      -- toggle safe-mode ON
    /resume    -- toggle safe-mode OFF
    /cancel    -- cancel an outstanding broker order by id
    /alerts    -- recent notification history
    /settings  -- feature flag dump + rate-limit / CB defaults
    /help      -- command reference

Authorisation:
    Every command goes through :meth:`_wrap_handler` which:
      1. Checks ``chat_id`` against ``authorized_chat_ids``. Unauthorised
         calls are silently ignored on the wire and recorded in
         audit_logs (12 §8.3).
      2. Delegates to the actual handler.
      3. Captures and logs handler exceptions (Constitution 4: a buggy
         command never crashes the polling loop).

The class is feature-flagged behind ``v71.telegram_commands_v71``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from src.core.v71.box.box_manager import BoxRecord, V71BoxManager
from src.core.v71.box.box_state_machine import BoxStatus
from src.core.v71.notification.v71_circuit_breaker import (
    V71CircuitBreaker,
    V71CircuitState,
)
from src.core.v71.notification.v71_notification_queue import (
    V71NotificationQueue,
)
from src.core.v71.notification.v71_notification_repository import (
    NotificationRecord,
    NotificationRepository,
    NotificationStatus,
)
from src.core.v71.position.state import PositionState
from src.core.v71.position.v71_position_manager import (
    TradeEvent,
    V71PositionManager,
)
from src.core.v71.strategies.v71_buy_executor import Clock
from src.utils import feature_flags as ff
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wiring Protocols / Aliases
# ---------------------------------------------------------------------------


class CommandRegistrar(Protocol):
    """Subset of V7.0 ``TelegramBot`` we depend on for registration."""

    def register_command(
        self,
        command: str,
        handler: Callable[[str, list[str]], Awaitable[None]],
    ) -> None: ...


# ``async def telegram_send(text, *, chat_id=None) -> bool``.
TelegramSendFn = Callable[..., Awaitable[bool]]


# Audit log signature -- wired to the V7.0 audit pipeline by the
# bootstrap layer. Raising an exception here MUST NOT crash a command.
AuditLogFn = Callable[..., Awaitable[None]]


# ``list_tracked()`` returns a snapshot of the user's tracked stocks.
# Defined as a small dataclass so /tracking output is deterministic
# without coupling to a future tracked_stocks ORM model.


@dataclass(frozen=True)
class TrackedSummary:
    """Read-only view of a tracked_stocks row for /tracking responses."""

    tracked_stock_id: str
    stock_code: str
    stock_name: str
    path_type: str  # PATH_A | PATH_B | MANUAL
    status: str  # TRACKING | EXITED ...
    box_count: int
    has_position: bool


# Misc callables (kept as type aliases for readability).
# P-Wire-Box-3: list_tracked is async — the implementation now hits the
# DB (build_tracked_summaries) so the snapshot reflects the current
# tracked_stocks / support_boxes / positions state.
ListTrackedFn = Callable[[], Awaitable[list[TrackedSummary]]]
SafeModeGetFn = Callable[[], bool]
SafeModeSetFn = Callable[[bool], Awaitable[None]]
CancelOrderFn = Callable[[str], Awaitable[bool]]
ReportHandlerFn = Callable[[str], Awaitable[str]]


# Names of the 13 P4.2 commands -- exposed for tests + /help formatter.
COMMANDS: tuple[str, ...] = (
    "status",
    "positions",
    "tracking",
    "pending",
    "today",
    "recent",
    "report",
    "stop",
    "resume",
    "cancel",
    "alerts",
    "settings",
    "help",
)


# ---------------------------------------------------------------------------
# Context (DI bundle)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandContext:
    """Dependencies the 13 commands need.

    Kept as a frozen dataclass so callers compose it once at startup
    and the command instance never reaches into globals.
    """

    box_manager: V71BoxManager
    position_manager: V71PositionManager
    notification_queue: V71NotificationQueue
    notification_repository: NotificationRepository
    circuit_breaker: V71CircuitBreaker
    clock: Clock

    telegram_send: TelegramSendFn
    audit_log: AuditLogFn

    authorized_chat_ids: tuple[str, ...]

    safe_mode_get: SafeModeGetFn
    safe_mode_set: SafeModeSetFn

    cancel_order: CancelOrderFn

    list_tracked: ListTrackedFn

    # Phase 6 wires the real generator. None means /report is a stub.
    report_handler: ReportHandlerFn | None = None

    # /alerts default look-back window. Configurable for tests.
    alerts_default_limit: int = 10
    alerts_default_window_hours: int = 24

    # /recent look-back window in days (02 §9.7 references "최근 7일").
    recent_window_days: int = 7


# ---------------------------------------------------------------------------
# Pure formatters (module-level so unit tests can pin them in isolation)
# ---------------------------------------------------------------------------


def _fmt_won(amount: int) -> str:
    return f"{amount:,}원"


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_today(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


def format_status_response(
    *,
    safe_mode: bool,
    box_total: int,
    box_waiting: int,
    box_triggered: int,
    open_positions: int,
    circuit_state: V71CircuitState,
    queue_pending_pending: int,
    now: datetime,
) -> str:
    """[/status] system snapshot."""
    safe = "ON (안전 모드)" if safe_mode else "OFF (정상 운영)"
    cb = circuit_state.value
    return (
        "[STATUS] 시스템 상태\n"
        f"시각: {_fmt_dt(now)}\n"
        f"안전 모드: {safe}\n"
        f"박스 (전체/대기/체결): {box_total} / {box_waiting} / {box_triggered}\n"
        f"OPEN 포지션: {open_positions}\n"
        f"알림 큐 PENDING: {queue_pending_pending}\n"
        f"Telegram Circuit: {cb}"
    )


def format_positions_response(positions: list[PositionState]) -> str:
    """[/positions] open positions table."""
    if not positions:
        return "[POSITIONS] 보유 포지션이 없습니다."
    lines = ["[POSITIONS] 보유 포지션"]
    for p in positions:
        lines.append(
            f"- {p.stock_code} ({p.path_type}) "
            f"{p.total_quantity}주 @ {_fmt_won(p.weighted_avg_price)} "
            f"손절: {_fmt_won(p.fixed_stop_price)} 상태: {p.status}"
        )
    return "\n".join(lines)


def format_tracking_response(items: list[TrackedSummary]) -> str:
    """[/tracking] tracked stocks list."""
    if not items:
        return "[TRACKING] 추적 종목이 없습니다."
    lines = ["[TRACKING] 추적 종목"]
    for t in items:
        pos_marker = "P" if t.has_position else "-"
        lines.append(
            f"- {t.stock_name} ({t.stock_code}) {t.path_type} "
            f"박스 {t.box_count}개 / {t.status} [{pos_marker}]"
        )
    return "\n".join(lines)


def format_pending_response(boxes: list[BoxRecord]) -> str:
    """[/pending] WAITING boxes."""
    if not boxes:
        return "[PENDING] 대기 중인 박스가 없습니다."
    lines = ["[PENDING] 매수 대기 박스"]
    for b in boxes:
        lines.append(
            f"- {b.path_type} {b.strategy_type} "
            f"{_fmt_won(b.lower_price)} ~ {_fmt_won(b.upper_price)} "
            f"비중 {b.position_size_pct:.1f}% (id: {b.id[:8]})"
        )
    return "\n".join(lines)


def format_trade_events_response(
    *, header: str, events: list[TradeEvent]
) -> str:
    """[/today] [/recent] trade-event list."""
    if not events:
        return f"{header} 거래 내역이 없습니다."
    lines = [header]
    for e in events:
        lines.append(
            f"- {_fmt_today(e.timestamp)} {e.event_type} "
            f"{e.stock_code} {e.quantity}주 @ {_fmt_won(e.price)}"
        )
    return "\n".join(lines)


def format_alerts_response(records: list[NotificationRecord]) -> str:
    """[/alerts] recent notifications."""
    if not records:
        return "[ALERTS] 최근 알림이 없습니다."
    lines = ["[ALERTS] 최근 알림"]
    for r in records:
        status = r.status.value
        head = (
            f"- {_fmt_today(r.created_at)} [{r.severity}] "
            f"{r.event_type} ({status})"
        )
        body_first_line = r.message.splitlines()[0] if r.message else ""
        if body_first_line:
            head += f" -- {body_first_line[:80]}"
        lines.append(head)
    return "\n".join(lines)


def format_settings_response(
    *,
    flags: dict[str, object],
    rate_limit_minutes: int,
    cb_threshold: int,
    cb_timeout_seconds: int,
    critical_retry_count: int,
) -> str:
    """[/settings] feature flag + alert defaults."""
    lines = ["[SETTINGS] 설정"]
    lines.append(f"빈도 제한: {rate_limit_minutes}분")
    lines.append(
        f"Circuit Breaker: {cb_threshold}회 실패 / {cb_timeout_seconds}초 timeout"
    )
    lines.append(f"CRITICAL 재시도: {critical_retry_count}회")
    lines.append("")
    lines.append("Feature flags:")
    for key in sorted(flags):
        lines.append(f"  {key} = {flags[key]}")
    return "\n".join(lines)


def format_help_response() -> str:
    """[/help] command reference."""
    return (
        "[HELP] 사용 가능한 명령어\n"
        "/status     - 시스템 상태 요약\n"
        "/positions  - 보유 포지션\n"
        "/tracking   - 추적 종목 리스트\n"
        "/pending    - 매수 대기 박스\n"
        "/today      - 오늘 거래 내역\n"
        "/recent     - 최근 7일 거래\n"
        "/report <종목코드> - 종목 리포트 생성 (Phase 6)\n"
        "/stop       - 시스템 일시 중지 (안전 모드 ON)\n"
        "/resume     - 시스템 재개 (안전 모드 OFF)\n"
        "/cancel <주문ID> - 미체결 주문 취소\n"
        "/alerts     - 최근 알림 이력\n"
        "/settings   - 설정 조회\n"
        "/help       - 명령어 도움말"
    )


# ---------------------------------------------------------------------------
# V71TelegramCommands
# ---------------------------------------------------------------------------


class V71TelegramCommands:
    """Owns the 13 P4.2 commands and registers them on a TelegramBot."""

    def __init__(self, *, context: CommandContext) -> None:
        require_enabled("v71.telegram_commands_v71")
        if not context.authorized_chat_ids:
            raise ValueError("authorized_chat_ids must not be empty")
        self._ctx = context

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, bot: CommandRegistrar) -> None:
        """Register all 13 commands on the bot.

        Idempotent if the bot's ``register_command`` overwrites existing
        bindings (V7.0 ``TelegramBot`` does -- last write wins).
        """
        for name in COMMANDS:
            handler = getattr(self, f"_cmd_{name}")
            bot.register_command(name, self._wrap_handler(name, handler))

    # ------------------------------------------------------------------
    # Authorisation wrapper (Constitution 4 + 12 §8.3)
    # ------------------------------------------------------------------

    def _wrap_handler(
        self,
        name: str,
        fn: Callable[[str, list[str]], Awaitable[None]],
    ) -> Callable[[str, list[str]], Awaitable[None]]:
        async def wrapped(chat_id: str, args: list[str]) -> None:
            if chat_id not in self._ctx.authorized_chat_ids:
                # Silent ignore + audit (12 §8.3 -- never reveal that
                # an authorised user exists).
                await self._safe_audit(
                    chat_id=chat_id,
                    command=name,
                    args=args,
                    authorised=False,
                    reason="UNAUTHORIZED_TELEGRAM_ACCESS",
                )
                return

            await self._safe_audit(
                chat_id=chat_id,
                command=name,
                args=args,
                authorised=True,
            )
            try:
                await fn(chat_id, args)
            except Exception as e:  # noqa: BLE001 -- Constitution 4
                log.exception("command /%s raised", name)
                await self._safe_send(
                    chat_id, f"명령 처리 중 오류: {e}"
                )

        return wrapped

    async def _safe_audit(self, **kwargs: object) -> None:
        try:
            await self._ctx.audit_log(**kwargs)
        except Exception:  # noqa: BLE001
            log.exception("audit_log raised; continuing")

    async def _safe_send(self, chat_id: str, text: str) -> None:
        try:
            await self._ctx.telegram_send(text, chat_id=chat_id)
        except Exception:  # noqa: BLE001
            log.exception("telegram_send raised for chat %s", chat_id)

    # ------------------------------------------------------------------
    # 13 command handlers
    # ------------------------------------------------------------------

    async def _cmd_status(self, chat_id: str, _args: list[str]) -> None:
        all_boxes = await self._ctx.box_manager.list_all()
        waiting = sum(1 for b in all_boxes if b.status is BoxStatus.WAITING)
        triggered = sum(
            1 for b in all_boxes if b.status is BoxStatus.TRIGGERED
        )
        # P-Wire-Box-4: position_manager.list_open is now async.
        positions = await self._ctx.position_manager.list_open()
        queue_pending = await self._count_pending_notifications()

        text = format_status_response(
            safe_mode=self._ctx.safe_mode_get(),
            box_total=len(all_boxes),
            box_waiting=waiting,
            box_triggered=triggered,
            open_positions=len(positions),
            circuit_state=self._ctx.circuit_breaker.state(),
            queue_pending_pending=queue_pending,
            now=self._ctx.clock.now(),
        )
        await self._safe_send(chat_id, text)

    async def _cmd_positions(self, chat_id: str, _args: list[str]) -> None:
        positions = await self._ctx.position_manager.list_open()
        await self._safe_send(chat_id, format_positions_response(positions))

    async def _cmd_tracking(self, chat_id: str, _args: list[str]) -> None:
        items = await self._ctx.list_tracked()
        await self._safe_send(chat_id, format_tracking_response(items))

    async def _cmd_pending(self, chat_id: str, _args: list[str]) -> None:
        boxes = await self._ctx.box_manager.list_all(status=BoxStatus.WAITING)
        await self._safe_send(chat_id, format_pending_response(boxes))

    async def _cmd_today(self, chat_id: str, _args: list[str]) -> None:
        events = await self._filter_events_since(self._start_of_today())
        await self._safe_send(
            chat_id,
            format_trade_events_response(
                header="[TODAY] 오늘 거래 내역", events=events
            ),
        )

    async def _cmd_recent(self, chat_id: str, _args: list[str]) -> None:
        cutoff = self._ctx.clock.now() - timedelta(
            days=self._ctx.recent_window_days
        )
        events = await self._filter_events_since(cutoff)
        await self._safe_send(
            chat_id,
            format_trade_events_response(
                header=f"[RECENT] 최근 {self._ctx.recent_window_days}일 거래",
                events=events,
            ),
        )

    async def _cmd_report(self, chat_id: str, args: list[str]) -> None:
        if not args:
            await self._safe_send(
                chat_id, "사용법: /report <종목코드>"
            )
            return
        stock_code = args[0]
        if self._ctx.report_handler is None:
            await self._safe_send(
                chat_id,
                f"[REPORT] {stock_code} -- 리포트 시스템은 Phase 6에서 활성화됩니다.",
            )
            return
        try:
            body = await self._ctx.report_handler(stock_code)
        except Exception as e:  # noqa: BLE001
            await self._safe_send(
                chat_id, f"리포트 생성 실패 ({stock_code}): {e}"
            )
            return
        await self._safe_send(chat_id, body)

    async def _cmd_stop(self, chat_id: str, _args: list[str]) -> None:
        if self._ctx.safe_mode_get():
            await self._safe_send(
                chat_id, "[STOP] 이미 안전 모드입니다."
            )
            return
        await self._ctx.safe_mode_set(True)
        await self._safe_send(
            chat_id,
            "[STOP] 안전 모드 ON -- 신규 매수 차단. /resume 으로 해제.",
        )

    async def _cmd_resume(self, chat_id: str, _args: list[str]) -> None:
        if not self._ctx.safe_mode_get():
            await self._safe_send(
                chat_id, "[RESUME] 안전 모드가 아닙니다."
            )
            return
        await self._ctx.safe_mode_set(False)
        await self._safe_send(
            chat_id, "[RESUME] 안전 모드 OFF -- 정상 운영 재개."
        )

    async def _cmd_cancel(self, chat_id: str, args: list[str]) -> None:
        if not args:
            await self._safe_send(
                chat_id, "사용법: /cancel <주문ID>"
            )
            return
        order_id = args[0]
        try:
            ok = await self._ctx.cancel_order(order_id)
        except Exception as e:  # noqa: BLE001
            await self._safe_send(
                chat_id, f"[CANCEL] {order_id} 취소 실패: {e}"
            )
            return
        suffix = "성공" if ok else "실패 (이미 체결 또는 미존재)"
        await self._safe_send(
            chat_id, f"[CANCEL] {order_id} {suffix}"
        )

    async def _cmd_alerts(self, chat_id: str, args: list[str]) -> None:
        limit = self._ctx.alerts_default_limit
        if args:
            try:
                limit = max(1, int(args[0]))
            except ValueError:
                await self._safe_send(
                    chat_id,
                    f"사용법: /alerts [건수] (기본 {self._ctx.alerts_default_limit})",
                )
                return
        since = self._ctx.clock.now() - timedelta(
            hours=self._ctx.alerts_default_window_hours
        )
        records = await self._ctx.notification_repository.list_recent(
            limit=limit, since=since
        )
        await self._safe_send(chat_id, format_alerts_response(records))

    async def _cmd_settings(self, chat_id: str, _args: list[str]) -> None:
        from src.core.v71.v71_constants import V71Constants

        flags = ff.all_flags()
        await self._safe_send(
            chat_id,
            format_settings_response(
                flags=flags,
                rate_limit_minutes=V71Constants.NOTIFICATION_RATE_LIMIT_MINUTES,
                cb_threshold=V71Constants.NOTIFICATION_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                cb_timeout_seconds=V71Constants.NOTIFICATION_CIRCUIT_BREAKER_TIMEOUT_SECONDS,
                critical_retry_count=V71Constants.NOTIFICATION_CRITICAL_RETRY_COUNT,
            ),
        )

    async def _cmd_help(self, chat_id: str, _args: list[str]) -> None:
        await self._safe_send(chat_id, format_help_response())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _count_pending_notifications(self) -> int:
        # Best-effort -- the repo Protocol doesn't expose a count; we
        # piggyback on list_recent with a wide window. Production
        # Postgres impl can short-circuit with a COUNT(*).
        records = await self._ctx.notification_repository.list_recent(
            limit=1000
        )
        return sum(
            1 for r in records if r.status is NotificationStatus.PENDING
        )

    def _start_of_today(self) -> datetime:
        now = self._ctx.clock.now()
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    async def _filter_events_since(
        self, cutoff: datetime,
    ) -> list[TradeEvent]:
        # P-Wire-Box-4: list_events is async after the DB-backed conversion.
        events = await self._ctx.position_manager.list_events()
        return [e for e in events if e.timestamp >= cutoff]


__all__ = [
    "COMMANDS",
    "AuditLogFn",
    "CancelOrderFn",
    "CommandContext",
    "CommandRegistrar",
    "ListTrackedFn",
    "ReportHandlerFn",
    "SafeModeGetFn",
    "SafeModeSetFn",
    "TelegramSendFn",
    "TrackedSummary",
    "V71TelegramCommands",
    "format_alerts_response",
    "format_help_response",
    "format_pending_response",
    "format_positions_response",
    "format_settings_response",
    "format_status_response",
    "format_trade_events_response",
    "format_tracking_response",
]
