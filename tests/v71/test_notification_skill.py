"""Unit tests for ``src/core/v71/skills/notification_skill.py`` (P4.1).

Spec:
  - 02_TRADING_RULES.md §9 (severity, rate limit, message format)
  - 07_SKILLS_SPEC.md §6 (notification_skill)
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags() -> AsyncIterator[None]:
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
    V71NotificationQueue,
)
from src.core.v71.notification.v71_notification_repository import (  # noqa: E402
    InMemoryNotificationRepository,
)
from src.core.v71.skills.notification_skill import (  # noqa: E402
    EventType,
    NotificationRequest,
    Severity,
    format_box_entry_imminent_message,
    format_buy_message,
    format_manual_trade_message,
    format_profit_take_message,
    format_stop_loss_message,
    format_system_restart_message,
    format_vi_triggered_message,
    format_websocket_disconnected_message,
    make_rate_limit_key,
    send_notification,
    severity_to_priority,
)

# ---------------------------------------------------------------------------
# FakeClock (sync only -- queue uses now())
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, *, start: datetime) -> None:
        self.now_value = start

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, _seconds: float) -> None:
        return None

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target

    def advance(self, **kwargs: int) -> None:
        self.now_value = self.now_value + timedelta(**kwargs)


# ---------------------------------------------------------------------------
# severity_to_priority
# ---------------------------------------------------------------------------


class TestSeverityToPriority:
    def test_critical_is_one(self) -> None:
        assert severity_to_priority(Severity.CRITICAL) == 1

    def test_high_is_two(self) -> None:
        assert severity_to_priority(Severity.HIGH) == 2

    def test_medium_is_three(self) -> None:
        assert severity_to_priority(Severity.MEDIUM) == 3

    def test_low_is_four(self) -> None:
        assert severity_to_priority(Severity.LOW) == 4

    def test_accepts_string(self) -> None:
        assert severity_to_priority("CRITICAL") == 1
        assert severity_to_priority("LOW") == 4

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown severity"):
            severity_to_priority("URGENT")

    def test_strict_ordering(self) -> None:
        # Pinning the canonical 1<2<3<4 ladder used by the queue ORDER BY.
        priorities = [
            severity_to_priority(s)
            for s in [
                Severity.CRITICAL,
                Severity.HIGH,
                Severity.MEDIUM,
                Severity.LOW,
            ]
        ]
        assert priorities == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# make_rate_limit_key
# ---------------------------------------------------------------------------


class TestRateLimitKey:
    def test_with_stock_code(self) -> None:
        assert (
            make_rate_limit_key(EventType.STOP_LOSS, "036040")
            == "STOP_LOSS:036040"
        )

    def test_without_stock_code_uses_underscore(self) -> None:
        assert (
            make_rate_limit_key(EventType.RECOVERY_COMPLETED, None)
            == "RECOVERY_COMPLETED:_"
        )

    def test_accepts_string_event_type(self) -> None:
        assert make_rate_limit_key("VI_TRIGGERED", "005930") == "VI_TRIGGERED:005930"

    def test_distinct_per_stock(self) -> None:
        a = make_rate_limit_key(EventType.BUY_EXECUTED, "036040")
        b = make_rate_limit_key(EventType.BUY_EXECUTED, "005930")
        assert a != b


# ---------------------------------------------------------------------------
# Formatters (smoke + structural assertions)
# ---------------------------------------------------------------------------


class TestFormatters:
    timestamp = datetime(2026, 4, 26, 14, 23, 45)

    def test_stop_loss_matches_prd_skeleton(self) -> None:
        title, body = format_stop_loss_message(
            stock_name="에프알텍",
            stock_code="036040",
            sell_price=17_200,
            avg_price=18_100,
            quantity=125,
            timestamp=self.timestamp,
            pnl_amount=-2_250_000,
            pnl_pct=-0.0497,
            reason="평단가 -5% 도달",
        )
        assert title == "[CRITICAL] 손절 실행"
        assert "에프알텍 (036040)" in body
        assert "17,200원" in body
        assert "18,100원" in body
        assert "14:23:45" in body
        assert "-4.97%" in body
        assert "-2,250,000원" in body
        assert "평단가 -5% 도달" in body

    def test_stop_loss_with_extra(self) -> None:
        _, body = format_stop_loss_message(
            stock_name="X",
            stock_code="000",
            sell_price=1,
            avg_price=2,
            quantity=1,
            timestamp=self.timestamp,
            pnl_amount=-1,
            pnl_pct=-0.5,
            reason="r",
            extra="다음 매수: 추적 종료",
        )
        assert "다음 매수: 추적 종료" in body

    def test_buy(self) -> None:
        title, body = format_buy_message(
            stock_name="주성엔지니어링",
            stock_code="036930",
            buy_price=32_000,
            quantity=50,
            timestamp=self.timestamp,
            path_type="PATH_A",
            box_label="1차 (31,500~32,500원, 비중 10%)",
            stop_price=30_400,
            stop_pct=-0.05,
        )
        assert title == "[HIGH] 매수 실행"
        assert "32,000원" in body
        assert "x 50주" in body
        assert "1,600,000원" in body  # total = 32000 * 50
        assert "PATH_A" in body
        assert "30,400원" in body
        assert "-5.00%" in body

    def test_profit_take(self) -> None:
        title, body = format_profit_take_message(
            stock_name="X",
            stock_code="000",
            level="+5%",
            sell_price=18_900,
            quantity=30,
            timestamp=self.timestamp,
            pnl_amount=27_000,
            pnl_pct=0.05,
            remaining_quantity=70,
            new_stop_price=17_640,
        )
        assert title == "[HIGH] +5% 익절"
        assert "잔여: 70주" in body
        assert "+5.00%" in body
        assert "17,640원" in body

    def test_manual_trade(self) -> None:
        title, body = format_manual_trade_message(
            stock_name="X",
            stock_code="000",
            direction="매수",
            quantity=100,
            price=18_000,
            timestamp=self.timestamp,
            note="이중 경로 합산",
        )
        assert title == "[HIGH] 수동 매수 감지"
        assert "100주 @ 18,000원" in body
        assert "이중 경로 합산" in body

    def test_vi_triggered(self) -> None:
        title, body = format_vi_triggered_message(
            stock_name="X",
            stock_code="000",
            trigger_price=20_000,
            timestamp=self.timestamp,
        )
        assert title == "[HIGH] VI 발동"
        assert "20,000원" in body
        assert "단일가 매매" in body

    def test_box_entry_imminent(self) -> None:
        title, body = format_box_entry_imminent_message(
            stock_name="X",
            stock_code="000",
            current_price=10_000,
            box_label="2차 (9,500~10,200원)",
            distance_pct=-0.02,
        )
        assert title == "[MEDIUM] 박스 진입 임박"
        assert "9,500~10,200원" in body
        assert "-2.00%" in body

    def test_system_restart(self) -> None:
        title, body = format_system_restart_message(
            timestamp=self.timestamp,
            duration_seconds=12.34,
            cancelled_orders=3,
            reconciliation_summary="A x 1, E x 5",
            failures=["Telegram"],
        )
        assert title == "[CRITICAL] 시스템 재시작 복구 완료"
        assert "12.3초" in body
        assert "3건" in body
        assert "A x 1, E x 5" in body
        assert "Telegram" in body

    def test_websocket_disconnected_severity_renders(self) -> None:
        _, body_med = format_websocket_disconnected_message(
            timestamp=self.timestamp,
            elapsed_seconds=12.0,
            severity=Severity.MEDIUM,
        )
        assert "12.0초" in body_med

        title_crit, _ = format_websocket_disconnected_message(
            timestamp=self.timestamp,
            elapsed_seconds=35.0,
            severity=Severity.CRITICAL,
        )
        assert "[CRITICAL]" in title_crit


# ---------------------------------------------------------------------------
# send_notification (queue integration)
# ---------------------------------------------------------------------------


@pytest.fixture
def queue_and_clock() -> tuple[V71NotificationQueue, FakeClock]:
    clock = FakeClock(start=datetime(2026, 4, 26, 9, 0))
    repo = InMemoryNotificationRepository()
    queue = V71NotificationQueue(repository=repo, clock=clock)
    return queue, clock


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_critical_queued(
        self, queue_and_clock: tuple[V71NotificationQueue, FakeClock]
    ) -> None:
        queue, _ = queue_and_clock
        result = await send_notification(
            NotificationRequest(
                severity=Severity.CRITICAL,
                event_type=EventType.STOP_LOSS,
                title="[CRITICAL] 손절 실행",
                message="...",
                stock_code="036040",
            ),
            queue=queue,
        )
        assert result.status == "QUEUED"
        assert result.notification_id is not None
        assert result.suppression_reason is None

    @pytest.mark.asyncio
    async def test_high_rate_limit_suppresses(
        self, queue_and_clock: tuple[V71NotificationQueue, FakeClock]
    ) -> None:
        queue, _ = queue_and_clock
        # First HIGH call goes through.
        first = await send_notification(
            NotificationRequest(
                severity=Severity.HIGH,
                event_type=EventType.BUY_EXECUTED,
                title="t",
                message="m",
                stock_code="000",
            ),
            queue=queue,
        )
        assert first.status == "QUEUED"

        # Second within 5 minutes is suppressed.
        second = await send_notification(
            NotificationRequest(
                severity=Severity.HIGH,
                event_type=EventType.BUY_EXECUTED,
                title="t",
                message="m",
                stock_code="000",
            ),
            queue=queue,
        )
        assert second.status == "SUPPRESSED"
        assert second.suppression_reason == "RATE_LIMIT"
        assert second.notification_id is None

    @pytest.mark.asyncio
    async def test_critical_bypasses_rate_limit(
        self, queue_and_clock: tuple[V71NotificationQueue, FakeClock]
    ) -> None:
        queue, _ = queue_and_clock
        for _ in range(3):
            r = await send_notification(
                NotificationRequest(
                    severity=Severity.CRITICAL,
                    event_type=EventType.STOP_LOSS,
                    title="t",
                    message="m",
                    stock_code="000",
                ),
                queue=queue,
            )
            assert r.status == "QUEUED"

    @pytest.mark.asyncio
    async def test_explicit_rate_limit_key(
        self, queue_and_clock: tuple[V71NotificationQueue, FakeClock]
    ) -> None:
        queue, _ = queue_and_clock
        r = await send_notification(
            NotificationRequest(
                severity=Severity.HIGH,
                event_type=EventType.MANUAL_TRADE_DETECTED,
                title="t",
                message="m",
                stock_code="000",
                rate_limit_key="custom:000",
            ),
            queue=queue,
        )
        assert r.status == "QUEUED"
        # The same custom key suppresses.
        r2 = await send_notification(
            NotificationRequest(
                severity=Severity.HIGH,
                event_type=EventType.MANUAL_TRADE_DETECTED,
                title="t",
                message="m",
                stock_code="000",
                rate_limit_key="custom:000",
            ),
            queue=queue,
        )
        assert r2.status == "SUPPRESSED"
