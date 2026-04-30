"""Unit tests for ``src/core/v71/notification/v71_telegram_commands.py``.

Spec:
  - 02_TRADING_RULES.md §9 (notification surface)
  - 05_MIGRATION_PLAN.md §6.3 (P4.2 -- 13 commands)
  - 12_SECURITY.md §3.4, §8.3 (chat_id whitelist + audit)
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags() -> Iterator[None]:
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    os.environ["V71_FF__V71__POSITION_V71"] = "true"
    os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
    os.environ["V71_FF__V71__TELEGRAM_COMMANDS_V71"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
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
    new_notification_id,
)
from src.core.v71.notification.v71_telegram_commands import (  # noqa: E402
    COMMANDS,
    CommandContext,
    TrackedSummary,
    V71TelegramCommands,
    format_alerts_response,
    format_help_response,
    format_pending_response,
    format_positions_response,
    format_status_response,
    format_tracking_response,
)
from src.core.v71.position.state import PositionState  # noqa: E402
from src.core.v71.position.v71_position_manager import (  # noqa: E402
    TradeEvent,
    V71PositionManager,
)
from src.core.v71.skills.box_entry_skill import (  # noqa: E402, F401
    PathType,
    StrategyType,
)
from tests.v71.conftest import FakeBoxManager  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 26, 14, 0)
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


@dataclass
class FakeBot:
    """Captures register_command + send_message invocations."""

    handlers: dict[str, Callable[[str, list[str]], Awaitable[None]]] = field(
        default_factory=dict
    )
    sent: list[tuple[str, str]] = field(default_factory=list)
    raise_on_send: BaseException | None = None

    def register_command(
        self,
        command: str,
        handler: Callable[[str, list[str]], Awaitable[None]],
    ) -> None:
        self.handlers[command] = handler

    async def send(
        self, text: str, chat_id: str | None = None
    ) -> bool:
        if self.raise_on_send is not None:
            raise self.raise_on_send
        self.sent.append((chat_id or "", text))
        return True


@dataclass
class FakeAudit:
    events: list[dict] = field(default_factory=list)
    raise_on_call: BaseException | None = None

    async def __call__(self, **kwargs) -> None:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.events.append(kwargs)


@dataclass
class SafeModeFlag:
    on: bool = False
    history: list[bool] = field(default_factory=list)

    def get(self) -> bool:
        return self.on

    async def set(self, value: bool) -> None:
        self.on = value
        self.history.append(value)


@dataclass
class FakeCancel:
    next_results: list = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    async def __call__(self, order_id: str) -> bool:
        self.cancelled.append(order_id)
        if not self.next_results:
            return True
        outcome = self.next_results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return bool(outcome)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


_AUTHORISED_CHAT = "1234567890"
_UNAUTHORISED_CHAT = "9999999999"


def _make_record(
    *,
    severity: str = "HIGH",
    created_at: datetime,
    event_type: str = "TEST",
    status: NotificationStatus = NotificationStatus.PENDING,
    message: str = "msg",
) -> NotificationRecord:
    return NotificationRecord(
        id=new_notification_id(),
        severity=severity,
        channel="BOTH" if severity in ("CRITICAL", "HIGH") else "TELEGRAM",
        event_type=event_type,
        stock_code="000",
        title=None,
        message=message,
        payload=None,
        status=status,
        priority={"CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}[severity],
        rate_limit_key=None,
        retry_count=0,
        sent_at=None,
        failed_at=None,
        failure_reason=None,
        created_at=created_at,
        expires_at=None,
    )


def _build_commands(
    *,
    list_tracked_result: list[TrackedSummary] | None = None,
    report_handler=None,
    cancel: FakeCancel | None = None,
    bot: FakeBot | None = None,
    audit: FakeAudit | None = None,
    safe_mode_flag: SafeModeFlag | None = None,
    authorized_chat_ids: tuple[str, ...] = (_AUTHORISED_CHAT,),
) -> tuple[
    V71TelegramCommands,
    CommandContext,
    FakeBot,
    FakeAudit,
    SafeModeFlag,
    FakeCancel,
    InMemoryNotificationRepository,
    V71BoxManager,
    V71PositionManager,
    FakeClock,
]:
    clock = FakeClock()
    bm = FakeBoxManager()
    pm = V71PositionManager()
    repo = InMemoryNotificationRepository()
    queue = V71NotificationQueue(repository=repo, clock=clock)
    cb = V71CircuitBreaker(clock=clock)
    bot = bot or FakeBot()
    audit = audit or FakeAudit()
    safe_mode_flag = safe_mode_flag or SafeModeFlag()
    cancel = cancel or FakeCancel()

    ctx = CommandContext(
        box_manager=bm,
        position_manager=pm,
        notification_queue=queue,
        notification_repository=repo,
        circuit_breaker=cb,
        clock=clock,
        telegram_send=bot.send,
        audit_log=audit,
        authorized_chat_ids=authorized_chat_ids,
        safe_mode_get=safe_mode_flag.get,
        safe_mode_set=safe_mode_flag.set,
        cancel_order=cancel,
        list_tracked=lambda: (list_tracked_result or []),
        report_handler=report_handler,
    )
    cmds = V71TelegramCommands(context=ctx)
    cmds.register(bot)
    return cmds, ctx, bot, audit, safe_mode_flag, cancel, repo, bm, pm, clock


# ---------------------------------------------------------------------------
# Construction / registration
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_feature_flag_required(self) -> None:
        del os.environ["V71_FF__V71__TELEGRAM_COMMANDS_V71"]
        ff.reload()
        with pytest.raises(RuntimeError, match="telegram_commands_v71"):
            _build_commands()

    def test_authorised_chat_ids_required(self) -> None:
        with pytest.raises(ValueError, match="authorized_chat_ids"):
            _build_commands(authorized_chat_ids=())

    def test_register_binds_all_thirteen(self) -> None:
        _, _, bot, *_ = _build_commands()
        assert set(bot.handlers.keys()) == set(COMMANDS)
        assert len(bot.handlers) == 13


# ---------------------------------------------------------------------------
# Authorisation gating
# ---------------------------------------------------------------------------


class TestAuthorisation:
    @pytest.mark.asyncio
    async def test_unauthorised_silently_ignored(self) -> None:
        _, _, bot, audit, *_ = _build_commands()
        await bot.handlers["status"](_UNAUTHORISED_CHAT, [])
        # Nothing sent on the wire.
        assert bot.sent == []
        # But the breach is audited.
        assert any(
            ev["authorised"] is False
            and ev["chat_id"] == _UNAUTHORISED_CHAT
            and ev["command"] == "status"
            and ev["reason"] == "UNAUTHORIZED_TELEGRAM_ACCESS"
            for ev in audit.events
        )

    @pytest.mark.asyncio
    async def test_authorised_audit_records_command(self) -> None:
        _, _, bot, audit, *_ = _build_commands()
        await bot.handlers["help"](_AUTHORISED_CHAT, [])
        success = [ev for ev in audit.events if ev["authorised"] is True]
        assert success
        assert success[-1]["command"] == "help"

    @pytest.mark.asyncio
    async def test_handler_exception_is_swallowed_and_reported(self) -> None:
        _, ctx, bot, *_ = _build_commands()
        # Sabotage list_tracked so /tracking blows up.
        object.__setattr__(
            ctx,
            "list_tracked",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        await bot.handlers["tracking"](_AUTHORISED_CHAT, [])
        # User got the error message; the polling loop did NOT crash.
        assert bot.sent
        assert "오류" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_command(self) -> None:
        bot = FakeBot()
        audit = FakeAudit(raise_on_call=RuntimeError("audit down"))
        _, *_ = _build_commands(bot=bot, audit=audit)
        await bot.handlers["help"](_AUTHORISED_CHAT, [])
        # Help still went through despite audit.
        assert bot.sent
        assert bot.sent[-1][1].startswith("[HELP]")


# ---------------------------------------------------------------------------
# Individual commands
# ---------------------------------------------------------------------------


class TestStatusPositionsTracking:
    @pytest.mark.asyncio
    async def test_status_includes_safe_mode_and_cb(self) -> None:
        cmds, ctx, bot, *_ = _build_commands()
        await bot.handlers["status"](_AUTHORISED_CHAT, [])
        assert bot.sent
        body = bot.sent[-1][1]
        assert "[STATUS]" in body
        assert "OFF (정상 운영)" in body
        assert V71CircuitState.CLOSED.value in body

    @pytest.mark.asyncio
    async def test_positions_empty(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["positions"](_AUTHORISED_CHAT, [])
        assert "보유 포지션이 없습니다" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_positions_lists_open(self) -> None:
        _, _, bot, _audit, _sm, _cancel, _repo, _bm, pm, _clock = (
            _build_commands()
        )
        # Inject a position into the in-memory PM.
        pm._positions["pos1"] = PositionState(  # type: ignore[attr-defined]
            position_id="pos1",
            stock_code="036040",
            tracked_stock_id="t1",
            triggered_box_id="b1",
            path_type="PATH_A",
            weighted_avg_price=18_100,
            initial_avg_price=18_100,
            total_quantity=125,
            fixed_stop_price=17_195,
            status="OPEN",
        )
        await bot.handlers["positions"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "036040" in body
        assert "125주" in body

    @pytest.mark.asyncio
    async def test_tracking_renders_summaries(self) -> None:
        items = [
            TrackedSummary(
                tracked_stock_id="t1",
                stock_code="036040",
                stock_name="에프알텍",
                path_type="PATH_A",
                status="TRACKING",
                box_count=2,
                has_position=True,
            )
        ]
        _, _, bot, *_ = _build_commands(list_tracked_result=items)
        await bot.handlers["tracking"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "에프알텍" in body
        assert "036040" in body
        assert "PATH_A" in body


class TestPendingTodayRecent:
    @pytest.mark.asyncio
    async def test_pending_filters_waiting(self) -> None:
        _, _, bot, _a, _s, _c, _r, bm, _pm, _clock = _build_commands()
        await bm.create_box(
            tracked_stock_id="t1",
            upper_price=10_200,
            lower_price=9_500,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        await bot.handlers["pending"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "9,500원" in body
        assert "10,200원" in body

    @pytest.mark.asyncio
    async def test_today_only_today(self) -> None:
        _, _, bot, _a, _s, _c, _r, _bm, pm, clock = _build_commands()
        # Yesterday event (not in /today)
        pm._events.append(  # type: ignore[attr-defined]
            TradeEvent(
                event_type="BUY_EXECUTED",
                position_id="p1",
                stock_code="000",
                quantity=10,
                price=1000,
                timestamp=clock.now() - timedelta(days=1),
            )
        )
        # Today event
        pm._events.append(  # type: ignore[attr-defined]
            TradeEvent(
                event_type="PROFIT_TAKE_5",
                position_id="p1",
                stock_code="000",
                quantity=3,
                price=1100,
                timestamp=clock.now() - timedelta(hours=1),
            )
        )
        await bot.handlers["today"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "PROFIT_TAKE_5" in body
        assert "BUY_EXECUTED" not in body  # filtered out

    @pytest.mark.asyncio
    async def test_recent_seven_day_window(self) -> None:
        _, _, bot, _a, _s, _c, _r, _bm, pm, clock = _build_commands()
        # 8 days ago -> excluded
        pm._events.append(  # type: ignore[attr-defined]
            TradeEvent(
                event_type="OLD",
                position_id="p1",
                stock_code="000",
                quantity=1,
                price=1,
                timestamp=clock.now() - timedelta(days=8),
            )
        )
        # 3 days ago -> included
        pm._events.append(  # type: ignore[attr-defined]
            TradeEvent(
                event_type="MID",
                position_id="p1",
                stock_code="000",
                quantity=1,
                price=1,
                timestamp=clock.now() - timedelta(days=3),
            )
        )
        await bot.handlers["recent"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "MID" in body
        assert "OLD" not in body


class TestStopResume:
    @pytest.mark.asyncio
    async def test_stop_toggles_safe_mode(self) -> None:
        _, _, bot, _a, sm, *_ = _build_commands()
        await bot.handlers["stop"](_AUTHORISED_CHAT, [])
        assert sm.on is True
        assert "[STOP]" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_stop_when_already_safe_no_toggle(self) -> None:
        sm = SafeModeFlag(on=True)
        _, _, bot, *_ = _build_commands(safe_mode_flag=sm)
        await bot.handlers["stop"](_AUTHORISED_CHAT, [])
        # No second toggle.
        assert sm.history == []
        assert "이미 안전 모드" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_resume_toggles_off(self) -> None:
        sm = SafeModeFlag(on=True)
        _, _, bot, *_ = _build_commands(safe_mode_flag=sm)
        await bot.handlers["resume"](_AUTHORISED_CHAT, [])
        assert sm.on is False
        assert sm.history == [False]
        assert "[RESUME]" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_resume_when_already_running(self) -> None:
        sm = SafeModeFlag(on=False)
        _, _, bot, *_ = _build_commands(safe_mode_flag=sm)
        await bot.handlers["resume"](_AUTHORISED_CHAT, [])
        assert sm.history == []
        assert "안전 모드가 아닙니다" in bot.sent[-1][1]


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_no_args(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["cancel"](_AUTHORISED_CHAT, [])
        assert "사용법" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_cancel_success(self) -> None:
        cancel = FakeCancel(next_results=[True])
        _, _, bot, *_ = _build_commands(cancel=cancel)
        await bot.handlers["cancel"](_AUTHORISED_CHAT, ["ORDER123"])
        assert cancel.cancelled == ["ORDER123"]
        assert "성공" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_cancel_returns_false(self) -> None:
        cancel = FakeCancel(next_results=[False])
        _, _, bot, *_ = _build_commands(cancel=cancel)
        await bot.handlers["cancel"](_AUTHORISED_CHAT, ["ORDER999"])
        assert "실패" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_cancel_raises(self) -> None:
        cancel = FakeCancel(next_results=[RuntimeError("broker timeout")])
        _, _, bot, *_ = _build_commands(cancel=cancel)
        await bot.handlers["cancel"](_AUTHORISED_CHAT, ["ORDER000"])
        assert "취소 실패" in bot.sent[-1][1]
        assert "broker timeout" in bot.sent[-1][1]


class TestReport:
    @pytest.mark.asyncio
    async def test_report_no_args(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["report"](_AUTHORISED_CHAT, [])
        assert "사용법" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_report_phase_6_stub(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["report"](_AUTHORISED_CHAT, ["036040"])
        body = bot.sent[-1][1]
        assert "036040" in body
        assert "Phase 6" in body

    @pytest.mark.asyncio
    async def test_report_handler_invoked(self) -> None:
        async def handler(stock_code: str) -> str:
            return f"[REPORT] {stock_code} OK"

        _, _, bot, *_ = _build_commands(report_handler=handler)
        await bot.handlers["report"](_AUTHORISED_CHAT, ["036040"])
        assert bot.sent[-1][1] == "[REPORT] 036040 OK"

    @pytest.mark.asyncio
    async def test_report_handler_failure(self) -> None:
        async def handler(_stock_code: str) -> str:
            raise RuntimeError("LLM down")

        _, _, bot, *_ = _build_commands(report_handler=handler)
        await bot.handlers["report"](_AUTHORISED_CHAT, ["036040"])
        body = bot.sent[-1][1]
        assert "리포트 생성 실패" in body
        assert "LLM down" in body


class TestAlerts:
    @pytest.mark.asyncio
    async def test_alerts_empty(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["alerts"](_AUTHORISED_CHAT, [])
        assert "최근 알림이 없습니다" in bot.sent[-1][1]

    @pytest.mark.asyncio
    async def test_alerts_within_window(self) -> None:
        _, _, bot, _a, _s, _c, repo, _bm, _pm, clock = _build_commands()
        # Inside the default 24h window
        await repo.insert(
            _make_record(
                created_at=clock.now() - timedelta(hours=2),
                event_type="BUY_EXECUTED",
                message="bought stuff",
            )
        )
        # Outside window -- should be excluded
        await repo.insert(
            _make_record(
                created_at=clock.now() - timedelta(days=2),
                event_type="OLD",
                message="ancient",
            )
        )
        await bot.handlers["alerts"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "BUY_EXECUTED" in body
        assert "ancient" not in body

    @pytest.mark.asyncio
    async def test_alerts_explicit_limit(self) -> None:
        _, _, bot, _a, _s, _c, repo, _bm, _pm, clock = _build_commands()
        for i in range(5):
            await repo.insert(
                _make_record(
                    created_at=clock.now() - timedelta(minutes=i),
                    event_type=f"E{i}",
                )
            )
        await bot.handlers["alerts"](_AUTHORISED_CHAT, ["2"])
        body = bot.sent[-1][1]
        # Only 2 entry rows included (count by line prefix to avoid
        # matching the '--' inside each entry's body).
        entry_lines = [
            line for line in body.split("\n") if line.startswith("- ")
        ]
        assert len(entry_lines) == 2

    @pytest.mark.asyncio
    async def test_alerts_invalid_limit_arg(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["alerts"](_AUTHORISED_CHAT, ["abc"])
        assert "사용법" in bot.sent[-1][1]


class TestSettingsHelp:
    @pytest.mark.asyncio
    async def test_settings_includes_flags_and_constants(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["settings"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        assert "Feature flags" in body
        assert "v71.notification_v71" in body
        assert "5분" in body  # rate limit
        assert "3회 실패" in body  # CB threshold

    @pytest.mark.asyncio
    async def test_help_lists_all_commands(self) -> None:
        _, _, bot, *_ = _build_commands()
        await bot.handlers["help"](_AUTHORISED_CHAT, [])
        body = bot.sent[-1][1]
        for cmd in COMMANDS:
            assert f"/{cmd}" in body


# ---------------------------------------------------------------------------
# Pure formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_status_safe_mode_on(self) -> None:
        body = format_status_response(
            safe_mode=True,
            box_total=5,
            box_waiting=3,
            box_triggered=2,
            open_positions=1,
            circuit_state=V71CircuitState.OPEN,
            queue_pending_pending=4,
            now=datetime(2026, 4, 26, 14, 0, 0),
        )
        assert "ON (안전 모드)" in body
        assert "5 / 3 / 2" in body
        assert "OPEN" in body

    def test_positions_empty(self) -> None:
        assert "없습니다" in format_positions_response([])

    def test_pending_empty(self) -> None:
        assert "없습니다" in format_pending_response([])

    def test_tracking_empty(self) -> None:
        assert "없습니다" in format_tracking_response([])

    def test_alerts_empty(self) -> None:
        assert "없습니다" in format_alerts_response([])

    def test_help_lists_thirteen(self) -> None:
        body = format_help_response()
        for cmd in COMMANDS:
            assert f"/{cmd}" in body
