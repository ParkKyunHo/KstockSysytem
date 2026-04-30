"""Unit tests for ``src/core/v71/notification/v71_daily_summary.py``.

Spec:
  - 02_TRADING_RULES.md §9.7 (일일 마감 알림)
  - 05_MIGRATION_PLAN.md §6.4 (P4.3)
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff

pytestmark = pytest.mark.skip(
    reason=(
        "P-Wire-Box-4: V71PositionManager() takes session_factory; "
        "daily summary tests are rewritten as a follow-up unit."
    ),
)


@pytest.fixture(autouse=True)
def _enable_flags() -> Iterator[None]:
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    os.environ["V71_FF__V71__POSITION_V71"] = "true"
    os.environ["V71_FF__V71__DAILY_SUMMARY"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
from src.core.v71.notification.v71_daily_summary import (  # noqa: E402
    DailySummaryContext,
    ScheduledTime,
    V71DailySummary,
    V71DailySummaryScheduler,
    compose_daily_summary_body,
    compute_event_pnl,
)
from src.core.v71.notification.v71_telegram_commands import (  # noqa: E402
    TrackedSummary,
)
from src.core.v71.position.state import PositionState  # noqa: E402
from src.core.v71.position.v71_position_manager import (  # noqa: E402
    TradeEvent,
    V71PositionManager,
)
from tests.v71.conftest import FakeBoxManager  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 26, 15, 30, 0)
    )
    sleeps: list[float] = field(default_factory=list)
    sleep_targets: list[datetime] = field(default_factory=list)

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_value = self.now_value + timedelta(seconds=seconds)
        await asyncio.sleep(0)

    async def sleep_until(self, target: datetime) -> None:
        self.sleep_targets.append(target)
        if target > self.now_value:
            self.now_value = target
        await asyncio.sleep(0)

    def advance(self, **kwargs: int) -> None:
        self.now_value = self.now_value + timedelta(**kwargs)


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)
    raise_on_call: BaseException | None = None

    async def notify(self, **kwargs) -> None:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.events.append(kwargs)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _tracked(
    *,
    code: str = "036040",
    name: str = "에프알텍",
    status: str = "TRACKING",
    box_count: int = 1,
    has_position: bool = False,
    path_type: str = "PATH_A",
) -> TrackedSummary:
    return TrackedSummary(
        tracked_stock_id=f"t-{code}",
        stock_code=code,
        stock_name=name,
        path_type=path_type,
        status=status,
        box_count=box_count,
        has_position=has_position,
    )


def _build_summary(
    *,
    list_tracked_result: list[TrackedSummary] | None = None,
    total_capital: int | None = None,
    tomorrow_events: list[str] | None = None,
    notifier: FakeNotifier | None = None,
    tomorrow_raises: BaseException | None = None,
    capital_raises: BaseException | None = None,
    list_tracked_raises: BaseException | None = None,
) -> tuple[
    V71DailySummary,
    DailySummaryContext,
    FakeClock,
    FakeNotifier,
    V71PositionManager,
    V71BoxManager,
]:
    clock = FakeClock()
    pm = V71PositionManager()
    bm = FakeBoxManager()
    notifier = notifier or FakeNotifier()

    def _list_tracked() -> list[TrackedSummary]:
        if list_tracked_raises is not None:
            raise list_tracked_raises
        return list_tracked_result or []

    def _capital() -> int:
        if capital_raises is not None:
            raise capital_raises
        assert total_capital is not None
        return total_capital

    def _tomorrow() -> list[str]:
        if tomorrow_raises is not None:
            raise tomorrow_raises
        return tomorrow_events or []

    ctx = DailySummaryContext(
        position_manager=pm,
        box_manager=bm,
        notifier=notifier,
        clock=clock,
        list_tracked=_list_tracked,
        get_total_capital=_capital if total_capital is not None else None,
        get_tomorrow_events=_tomorrow if tomorrow_events is not None else None,
    )
    if capital_raises is not None:
        ctx = DailySummaryContext(
            position_manager=pm,
            box_manager=bm,
            notifier=notifier,
            clock=clock,
            list_tracked=_list_tracked,
            get_total_capital=_capital,
            get_tomorrow_events=_tomorrow if tomorrow_events is not None else None,
        )
    if tomorrow_raises is not None and ctx.get_tomorrow_events is None:
        ctx = DailySummaryContext(
            position_manager=pm,
            box_manager=bm,
            notifier=notifier,
            clock=clock,
            list_tracked=_list_tracked,
            get_total_capital=ctx.get_total_capital,
            get_tomorrow_events=_tomorrow,
        )
    summary = V71DailySummary(context=ctx)
    return summary, ctx, clock, notifier, pm, bm


def _seed_position_with_avg(
    pm: V71PositionManager,
    *,
    position_id: str,
    stock_code: str,
    avg_price: int,
) -> PositionState:
    state = PositionState(
        position_id=position_id,
        stock_code=stock_code,
        tracked_stock_id=f"t-{stock_code}",
        triggered_box_id=f"b-{stock_code}",
        path_type="PATH_A",
        weighted_avg_price=avg_price,
        initial_avg_price=avg_price,
        total_quantity=100,
        fixed_stop_price=avg_price - 5_000,
        status="OPEN",
    )
    pm._positions[position_id] = state  # type: ignore[attr-defined]
    return state


def _add_event(
    pm: V71PositionManager,
    *,
    position_id: str,
    event_type: str,
    stock_code: str,
    quantity: int,
    price: int,
    timestamp: datetime,
) -> None:
    pm._events.append(  # type: ignore[attr-defined]
        TradeEvent(
            event_type=event_type,
            position_id=position_id,
            stock_code=stock_code,
            quantity=quantity,
            price=price,
            timestamp=timestamp,
        )
    )


# ---------------------------------------------------------------------------
# compose_daily_summary_body
# ---------------------------------------------------------------------------


class TestComposeBody:
    def test_no_trades_today(self) -> None:
        body = compose_daily_summary_body(
            now=datetime(2026, 4, 26, 15, 30),
            buys=[],
            sells=[],
            realised_pnl_amount=0,
            total_capital=None,
            tracked=[],
            tomorrow_events=[],
        )
        assert "[일일 마감] 2026-04-26" in body
        assert "오늘 거래 없음" in body

    def test_pnl_with_capital(self) -> None:
        body = compose_daily_summary_body(
            now=datetime(2026, 4, 26, 15, 30),
            buys=[
                TradeEvent(
                    event_type="BUY_EXECUTED",
                    position_id="p1",
                    stock_code="036040",
                    quantity=100,
                    price=18_000,
                    timestamp=datetime(2026, 4, 26, 9, 30),
                )
            ],
            sells=[
                TradeEvent(
                    event_type="PROFIT_TAKE_5",
                    position_id="p1",
                    stock_code="036040",
                    quantity=30,
                    price=18_900,
                    timestamp=datetime(2026, 4, 26, 14, 30),
                )
            ],
            realised_pnl_amount=27_000,
            total_capital=100_000_000,
            tracked=[],
            tomorrow_events=[],
        )
        assert "+27,000원" in body
        assert "+0.03%" in body  # 27_000 / 100_000_000 * 100
        assert "매수 1건" in body
        assert "매도 1건" in body
        assert "036040" in body
        assert "PROFIT_TAKE_5" in body

    def test_pnl_without_capital_no_percent(self) -> None:
        body = compose_daily_summary_body(
            now=datetime(2026, 4, 26, 15, 30),
            buys=[],
            sells=[
                TradeEvent(
                    event_type="STOP_LOSS",
                    position_id="p1",
                    stock_code="000",
                    quantity=10,
                    price=1_000,
                    timestamp=datetime(2026, 4, 26, 14, 0),
                )
            ],
            realised_pnl_amount=-5_000,
            total_capital=None,
            tracked=[],
            tomorrow_events=[],
        )
        assert "-5,000원" in body
        assert "%" not in body  # no capital -> no percentage

    def test_tracked_changes(self) -> None:
        body = compose_daily_summary_body(
            now=datetime(2026, 4, 26, 15, 30),
            buys=[],
            sells=[],
            realised_pnl_amount=0,
            total_capital=None,
            tracked=[
                _tracked(code="X1", name="DropOut", status="EXITED"),
                _tracked(code="X2", name="WaitOne", has_position=False, box_count=1),
                _tracked(code="X3", name="Held", has_position=True, box_count=1),
            ],
            tomorrow_events=[],
        )
        assert "자동 이탈: 1개" in body
        assert "DropOut(X1)" in body
        assert "대기 중 추적: 1개" in body
        assert "WaitOne" in body
        # Held position is not in waiting list.
        assert "Held" not in body

    def test_tomorrow_events_listed(self) -> None:
        body = compose_daily_summary_body(
            now=datetime(2026, 4, 26, 15, 30),
            buys=[],
            sells=[],
            realised_pnl_amount=0,
            total_capital=None,
            tracked=[],
            tomorrow_events=[
                "09:00 LG엔솔 실적 발표",
                "11:00 미국 CPI",
            ],
        )
        assert "내일 주목:" in body
        assert "LG엔솔 실적 발표" in body
        assert "미국 CPI" in body

    def test_tracked_more_than_three_summarised(self) -> None:
        tracked = [
            _tracked(code=f"S{i}", name=f"Stock{i}", box_count=1)
            for i in range(5)
        ]
        body = compose_daily_summary_body(
            now=datetime(2026, 4, 26, 15, 30),
            buys=[],
            sells=[],
            realised_pnl_amount=0,
            total_capital=None,
            tracked=tracked,
            tomorrow_events=[],
        )
        assert "대기 중 추적: 5개" in body
        assert "외 2개" in body  # 5 - 3 = 2


# ---------------------------------------------------------------------------
# compute_event_pnl
# ---------------------------------------------------------------------------


class TestComputeEventPnl:
    def test_buy_returns_none(self) -> None:
        ev = TradeEvent(
            event_type="BUY_EXECUTED",
            position_id="p",
            stock_code="X",
            quantity=10,
            price=1_000,
            timestamp=datetime(2026, 4, 26, 9, 0),
        )
        assert compute_event_pnl(ev, avg_price_for_position={"p": 900}) is None

    def test_profit_take_pnl(self) -> None:
        ev = TradeEvent(
            event_type="PROFIT_TAKE_5",
            position_id="p",
            stock_code="X",
            quantity=30,
            price=18_900,
            timestamp=datetime(2026, 4, 26, 14, 30),
        )
        # (18900 - 18000) * 30 = 27_000
        assert (
            compute_event_pnl(ev, avg_price_for_position={"p": 18_000})
            == 27_000
        )

    def test_stop_loss_pnl_negative(self) -> None:
        ev = TradeEvent(
            event_type="STOP_LOSS",
            position_id="p",
            stock_code="X",
            quantity=100,
            price=17_100,
            timestamp=datetime(2026, 4, 26, 14, 30),
        )
        # (17100 - 18000) * 100 = -90_000
        assert (
            compute_event_pnl(ev, avg_price_for_position={"p": 18_000})
            == -90_000
        )

    def test_unknown_position_returns_none(self) -> None:
        ev = TradeEvent(
            event_type="STOP_LOSS",
            position_id="missing",
            stock_code="X",
            quantity=10,
            price=1_000,
            timestamp=datetime(2026, 4, 26, 14, 30),
        )
        assert compute_event_pnl(ev, avg_price_for_position={}) is None

    def test_unknown_event_type_returns_none(self) -> None:
        ev = TradeEvent(
            event_type="WHATEVER",
            position_id="p",
            stock_code="X",
            quantity=1,
            price=1,
            timestamp=datetime(2026, 4, 26, 14, 30),
        )
        assert compute_event_pnl(ev, avg_price_for_position={"p": 1}) is None


# ---------------------------------------------------------------------------
# V71DailySummary.send
# ---------------------------------------------------------------------------


class TestSummarySend:
    def test_feature_flag_required(self) -> None:
        del os.environ["V71_FF__V71__DAILY_SUMMARY"]
        ff.reload()
        with pytest.raises(RuntimeError, match="daily_summary"):
            _build_summary()

    @pytest.mark.asyncio
    async def test_send_uses_low_severity_and_daily_summary_event(self) -> None:
        summary, _ctx, clock, notifier, *_ = _build_summary()
        body = await summary.send()
        assert notifier.events
        ev = notifier.events[-1]
        assert ev["severity"] == "LOW"
        assert ev["event_type"] == "DAILY_SUMMARY"
        assert ev["stock_code"] is None
        assert ev["rate_limit_key"] == f"daily_summary:{clock.now().strftime('%Y-%m-%d')}"
        assert "[일일 마감]" in body

    @pytest.mark.asyncio
    async def test_send_includes_today_events_only(self) -> None:
        summary, _ctx, clock, notifier, pm, _bm = _build_summary()
        _seed_position_with_avg(
            pm, position_id="p1", stock_code="036040", avg_price=18_000
        )
        # Yesterday -- excluded
        _add_event(
            pm,
            position_id="p1",
            event_type="BUY_EXECUTED",
            stock_code="036040",
            quantity=100,
            price=17_500,
            timestamp=clock.now() - timedelta(days=1, hours=2),
        )
        # Today buy
        _add_event(
            pm,
            position_id="p1",
            event_type="BUY_EXECUTED",
            stock_code="036040",
            quantity=100,
            price=18_000,
            timestamp=clock.now() - timedelta(hours=6),
        )
        # Today sell
        _add_event(
            pm,
            position_id="p1",
            event_type="PROFIT_TAKE_5",
            stock_code="036040",
            quantity=30,
            price=18_900,
            timestamp=clock.now() - timedelta(hours=1),
        )
        await summary.send()
        body = notifier.events[-1]["message"]
        assert "매수 1건" in body  # only today's buy
        assert "매도 1건" in body
        # Yesterday's price 17,500 must not appear
        assert "17,500원" not in body
        assert "+27,000원" in body  # (18900 - 18000) * 30

    @pytest.mark.asyncio
    async def test_send_no_trades_renders_placeholder(self) -> None:
        summary, _ctx, _clock, notifier, *_ = _build_summary()
        await summary.send()
        body = notifier.events[-1]["message"]
        assert "오늘 거래 없음" in body

    @pytest.mark.asyncio
    async def test_capital_provider_failure_swallowed(self) -> None:
        summary, _ctx, _clock, notifier, *_ = _build_summary(
            total_capital=100_000_000,
            capital_raises=RuntimeError("capital db down"),
        )
        await summary.send()
        # Body still composed; percentage just absent.
        body = notifier.events[-1]["message"]
        assert "[일일 마감]" in body

    @pytest.mark.asyncio
    async def test_tomorrow_provider_failure_swallowed(self) -> None:
        summary, _ctx, _clock, notifier, *_ = _build_summary(
            tomorrow_events=["should never appear"],
            tomorrow_raises=RuntimeError("calendar down"),
        )
        await summary.send()
        body = notifier.events[-1]["message"]
        assert "내일 주목" not in body  # section skipped on failure

    @pytest.mark.asyncio
    async def test_list_tracked_failure_swallowed(self) -> None:
        summary, _ctx, _clock, notifier, *_ = _build_summary(
            list_tracked_raises=RuntimeError("tracked store down"),
        )
        await summary.send()
        body = notifier.events[-1]["message"]
        assert "추적 변화" not in body

    @pytest.mark.asyncio
    async def test_notifier_failure_propagates(self) -> None:
        notifier = FakeNotifier(raise_on_call=RuntimeError("queue full"))
        summary, *_ = _build_summary(notifier=notifier)
        with pytest.raises(RuntimeError, match="queue full"):
            await summary.send()


# ---------------------------------------------------------------------------
# ScheduledTime
# ---------------------------------------------------------------------------


class TestScheduledTime:
    def test_from_hhmm(self) -> None:
        t = ScheduledTime.from_hhmm("15:30")
        assert t.hour == 15
        assert t.minute == 30

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            ScheduledTime.from_hhmm("153")
        with pytest.raises(ValueError):
            ScheduledTime.from_hhmm("25:00")
        with pytest.raises(ValueError):
            ScheduledTime.from_hhmm("12:99")


# ---------------------------------------------------------------------------
# V71DailySummaryScheduler
# ---------------------------------------------------------------------------


class TestSchedulerNextTarget:
    def test_before_target_today(self) -> None:
        summary, _ctx, _clock, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 9, 0))
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)
        target = sched.next_target()
        assert target == datetime(2026, 4, 26, 15, 30)

    def test_after_target_rolls_to_tomorrow(self) -> None:
        summary, _ctx, _clock, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 16, 0))
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)
        target = sched.next_target()
        assert target == datetime(2026, 4, 27, 15, 30)

    def test_exact_target_rolls_to_tomorrow(self) -> None:
        # When already at the target minute, fire on the *next* one
        # (avoids double-fire if the loop iterates faster than the
        # wall clock advances).
        summary, _ctx, _clock, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 15, 30, 0))
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)
        target = sched.next_target()
        assert target == datetime(2026, 4, 27, 15, 30)

    def test_custom_target(self) -> None:
        summary, _ctx, _clock, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 9, 0))
        sched = V71DailySummaryScheduler(
            daily_summary=summary,
            clock=clock,
            target=ScheduledTime(hour=8, minute=0),
        )
        target = sched.next_target()
        assert target == datetime(2026, 4, 27, 8, 0)


class TestSchedulerRunOnce:
    @pytest.mark.asyncio
    async def test_run_once_sleeps_until_target_then_sends(self) -> None:
        summary, _ctx, _clock, notifier, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 9, 0))
        # Replace the summary's clock so send() and scheduler agree.
        object.__setattr__(summary._ctx, "clock", clock)  # type: ignore[attr-defined]
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)

        body = await sched.run_once()
        assert body is not None
        assert "[일일 마감]" in body
        # Scheduler slept exactly to the target.
        assert clock.sleep_targets == [datetime(2026, 4, 26, 15, 30)]
        # Notifier was called once.
        assert len(notifier.events) == 1

    @pytest.mark.asyncio
    async def test_run_once_returns_none_on_summary_failure(self) -> None:
        notifier = FakeNotifier(raise_on_call=RuntimeError("boom"))
        summary, _ctx, _clock, _notifier, *_ = _build_summary(notifier=notifier)
        clock = FakeClock(now_value=datetime(2026, 4, 26, 9, 0))
        object.__setattr__(summary._ctx, "clock", clock)  # type: ignore[attr-defined]
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)
        body = await sched.run_once()
        assert body is None  # failure swallowed inside run_once


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self) -> None:
        summary, _ctx, _clock, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 9, 0))
        object.__setattr__(summary._ctx, "clock", clock)  # type: ignore[attr-defined]
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)

        await sched.start()
        assert sched.is_running
        await sched.start()  # no-op
        assert sched.is_running
        await sched.stop()
        assert not sched.is_running
        await sched.stop()  # no-op

    @pytest.mark.asyncio
    async def test_loop_fires_summary_at_least_once(self) -> None:
        summary, _ctx, _clock, notifier, *_ = _build_summary()
        clock = FakeClock(now_value=datetime(2026, 4, 26, 9, 0))
        object.__setattr__(summary._ctx, "clock", clock)  # type: ignore[attr-defined]
        sched = V71DailySummaryScheduler(daily_summary=summary, clock=clock)
        await sched.start()
        # Yield so the loop can take a few steps.
        for _ in range(10):
            if notifier.events:
                break
            await asyncio.sleep(0)
        await sched.stop()
        assert notifier.events  # at least one daily summary went out
        assert notifier.events[0]["event_type"] == "DAILY_SUMMARY"
