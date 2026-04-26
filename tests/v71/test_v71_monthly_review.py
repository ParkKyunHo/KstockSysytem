"""Unit tests for ``src/core/v71/notification/v71_monthly_review.py``.

Spec:
  - 02_TRADING_RULES.md §9.8 (월 1회 추적 리뷰)
  - 05_MIGRATION_PLAN.md §6.5 (P4.4)
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags() -> Iterator[None]:
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__MONTHLY_REVIEW"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.notification.v71_monthly_review import (  # noqa: E402
    DEFAULT_STALE_DAYS,
    MonthlyCounts,
    MonthlyReviewContext,
    MonthlyReviewItem,
    V71MonthlyReview,
    V71MonthlyReviewScheduler,
    compose_monthly_review_body,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 5, 1, 9, 0, 0)
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


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)
    raise_on_call: BaseException | None = None

    async def notify(self, **kwargs) -> None:
        if self.raise_on_call is not None:
            raise self.raise_on_call
        self.events.append(kwargs)


# ---------------------------------------------------------------------------
# Item builder
# ---------------------------------------------------------------------------


def _item(
    *,
    code: str = "036040",
    name: str = "에프알텍",
    status: str = "TRACKING",
    box_count: int = 1,
    waiting_box_count: int = 1,
    has_position: bool = False,
    has_partial_exit: bool = False,
    created_at: datetime | None = None,
    path_type: str = "PATH_A",
) -> MonthlyReviewItem:
    return MonthlyReviewItem(
        stock_code=code,
        stock_name=name,
        path_type=path_type,
        status=status,
        box_count=box_count,
        waiting_box_count=waiting_box_count,
        has_position=has_position,
        has_partial_exit=has_partial_exit,
        created_at=created_at or datetime(2026, 4, 1),
    )


def _build_review(
    *,
    items: list[MonthlyReviewItem] | None = None,
    expiring_boxes: int | None = None,
    items_raises: BaseException | None = None,
    expiring_raises: BaseException | None = None,
    notifier: FakeNotifier | None = None,
) -> tuple[V71MonthlyReview, MonthlyReviewContext, FakeClock, FakeNotifier]:
    clock = FakeClock()
    notifier = notifier or FakeNotifier()

    def _list_items() -> list[MonthlyReviewItem]:
        if items_raises is not None:
            raise items_raises
        return items or []

    def _expiring() -> int:
        if expiring_raises is not None:
            raise expiring_raises
        assert expiring_boxes is not None
        return expiring_boxes

    ctx = MonthlyReviewContext(
        notifier=notifier,
        clock=clock,
        list_review_items=_list_items,
        list_expiring_boxes=(
            _expiring
            if expiring_boxes is not None or expiring_raises is not None
            else None
        ),
    )
    review = V71MonthlyReview(context=ctx)
    return review, ctx, clock, notifier


# ---------------------------------------------------------------------------
# MonthlyCounts
# ---------------------------------------------------------------------------


class TestMonthlyCounts:
    def test_aggregates(self) -> None:
        items = [
            _item(code="A", waiting_box_count=2, has_position=False),
            _item(code="B", waiting_box_count=0, has_position=True),
            _item(
                code="C",
                waiting_box_count=1,
                has_position=True,
                has_partial_exit=True,
            ),
            _item(code="D", status="EXITED", waiting_box_count=0),
        ]
        counts = MonthlyCounts.from_items(items)
        assert counts.tracking == 3  # D is EXITED
        assert counts.waiting_boxes == 3  # 2 + 0 + 1 + 0
        assert counts.holding == 2  # B + C
        assert counts.partial == 1  # only C


# ---------------------------------------------------------------------------
# compose_monthly_review_body
# ---------------------------------------------------------------------------


class TestComposeBody:
    now = datetime(2026, 5, 1, 9, 0)

    def test_header_includes_year_month(self) -> None:
        body = compose_monthly_review_body(
            now=self.now, items=[], expiring_boxes_count=0
        )
        assert "[월간 리뷰] 2026-05" in body
        assert "추적 중인 종목이 없습니다" in body

    def test_full_status_block(self) -> None:
        items = [
            _item(code="A", waiting_box_count=2),
            _item(code="B", has_position=True, waiting_box_count=0),
        ]
        body = compose_monthly_review_body(
            now=self.now, items=items, expiring_boxes_count=0
        )
        assert "[전체 현황]" in body
        assert "추적 중: 2개" in body
        assert "박스 대기: 2개" in body
        assert "포지션 보유: 1개" in body
        assert "부분 청산: 0개" in body

    def test_stale_listed(self) -> None:
        old = self.now - timedelta(days=DEFAULT_STALE_DAYS + 5)
        items = [
            _item(code="OLD", name="장기정체", created_at=old),
            _item(
                code="NEW",
                name="최근",
                created_at=self.now - timedelta(days=10),
            ),
        ]
        body = compose_monthly_review_body(
            now=self.now, items=items, expiring_boxes_count=0
        )
        assert "[주의 필요]" in body
        assert "장기 정체: 1개" in body
        assert "장기정체(OLD)" in body
        # The "최근" entry must not appear inside the stale-listing line,
        # though it still shows up in the [전체 목록] roster.
        stale_line = next(
            line for line in body.splitlines() if "장기 정체:" in line
        )
        assert "최근" not in stale_line

    def test_stale_excludes_holders(self) -> None:
        # A held position is exempt from "장기 정체".
        old = self.now - timedelta(days=DEFAULT_STALE_DAYS + 5)
        items = [
            _item(code="OLD", created_at=old, has_position=True),
        ]
        body = compose_monthly_review_body(
            now=self.now, items=items, expiring_boxes_count=0
        )
        assert "[주의 필요]" not in body

    def test_expiring_boxes_count(self) -> None:
        body = compose_monthly_review_body(
            now=self.now, items=[], expiring_boxes_count=4
        )
        assert "[주의 필요]" in body
        assert "박스 만료 임박 (30일): 4개" in body

    def test_status_breakdown_sections(self) -> None:
        items = [
            _item(code="W1", waiting_box_count=2),
            _item(code="W2", waiting_box_count=1),
            _item(code="H1", has_position=True, waiting_box_count=0),
            _item(
                code="H2",
                has_position=True,
                has_partial_exit=True,
                waiting_box_count=0,
            ),
        ]
        body = compose_monthly_review_body(
            now=self.now, items=items, expiring_boxes_count=0
        )
        assert "[상태별 분류]" in body
        assert "박스 대기 (2)" in body
        assert "포지션 보유 (2)" in body
        assert "(부분 청산)" in body
        # Roster always renders.
        assert "[전체 목록] (4)" in body

    def test_full_roster_truncates_long_lists(self) -> None:
        # 11 waiting items -> truncated at 10.
        items = [
            _item(code=f"W{i}", waiting_box_count=1) for i in range(11)
        ]
        body = compose_monthly_review_body(
            now=self.now, items=items, expiring_boxes_count=0
        )
        assert "박스 대기 (11)" in body
        assert "외 1개" in body  # 11 - 10 = 1

    def test_top5_stale_truncates(self) -> None:
        old = self.now - timedelta(days=DEFAULT_STALE_DAYS + 5)
        items = [
            _item(code=f"S{i}", name=f"Stock{i}", created_at=old)
            for i in range(7)
        ]
        body = compose_monthly_review_body(
            now=self.now, items=items, expiring_boxes_count=0
        )
        assert "장기 정체: 7개" in body
        assert "외 2개" in body  # 7 - 5


# ---------------------------------------------------------------------------
# V71MonthlyReview.send
# ---------------------------------------------------------------------------


class TestSend:
    def test_feature_flag_required(self) -> None:
        del os.environ["V71_FF__V71__MONTHLY_REVIEW"]
        ff.reload()
        with pytest.raises(RuntimeError, match="monthly_review"):
            _build_review()

    @pytest.mark.asyncio
    async def test_send_uses_low_severity_and_event(self) -> None:
        review, _ctx, clock, notifier = _build_review(items=[_item()])
        body = await review.send()
        ev = notifier.events[-1]
        assert ev["severity"] == "LOW"
        assert ev["event_type"] == "MONTHLY_REVIEW"
        assert ev["stock_code"] is None
        assert ev["rate_limit_key"] == "monthly_review:2026-05"
        assert "[월간 리뷰] 2026-05" in body

    @pytest.mark.asyncio
    async def test_items_callback_failure_renders_empty(self) -> None:
        review, _ctx, _c, notifier = _build_review(
            items_raises=RuntimeError("db down")
        )
        await review.send()
        body = notifier.events[-1]["message"]
        assert "추적 중인 종목이 없습니다" in body

    @pytest.mark.asyncio
    async def test_expiring_callback_failure_skips_line(self) -> None:
        review, _ctx, _c, notifier = _build_review(
            expiring_raises=RuntimeError("box manager down")
        )
        await review.send()
        body = notifier.events[-1]["message"]
        # Section absent when callback fails (no items also -> no warning block)
        assert "박스 만료 임박" not in body

    @pytest.mark.asyncio
    async def test_expiring_callback_value(self) -> None:
        review, _ctx, _c, notifier = _build_review(
            items=[_item()], expiring_boxes=3
        )
        await review.send()
        body = notifier.events[-1]["message"]
        assert "박스 만료 임박 (30일): 3개" in body

    @pytest.mark.asyncio
    async def test_notifier_failure_propagates(self) -> None:
        notifier = FakeNotifier(raise_on_call=RuntimeError("queue full"))
        review, *_ = _build_review(notifier=notifier)
        with pytest.raises(RuntimeError, match="queue full"):
            await review.send()


# ---------------------------------------------------------------------------
# V71MonthlyReviewScheduler
# ---------------------------------------------------------------------------


def _make_scheduler(
    clock: FakeClock,
    *,
    notifier: FakeNotifier | None = None,
    hour: int = 9,
    minute: int = 0,
) -> tuple[V71MonthlyReviewScheduler, FakeNotifier]:
    notifier = notifier or FakeNotifier()
    ctx = MonthlyReviewContext(
        notifier=notifier,
        clock=clock,
        list_review_items=lambda: [],
    )
    review = V71MonthlyReview(context=ctx)
    sched = V71MonthlyReviewScheduler(
        monthly_review=review, clock=clock, hour=hour, minute=minute
    )
    return sched, notifier


class TestSchedulerNextTarget:
    def test_before_target_today_first_of_month(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 5, 1, 8, 0))
        sched, _ = _make_scheduler(clock)
        assert sched.next_target() == datetime(2026, 5, 1, 9, 0)

    def test_after_target_rolls_to_next_month(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 5, 1, 9, 0))
        sched, _ = _make_scheduler(clock)
        assert sched.next_target() == datetime(2026, 6, 1, 9, 0)

    def test_mid_month_rolls_to_first_of_next(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 5, 15, 9, 0))
        sched, _ = _make_scheduler(clock)
        assert sched.next_target() == datetime(2026, 6, 1, 9, 0)

    def test_december_rolls_to_january(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 12, 5, 0, 0))
        sched, _ = _make_scheduler(clock)
        assert sched.next_target() == datetime(2027, 1, 1, 9, 0)

    def test_invalid_time_raises(self) -> None:
        clock = FakeClock()
        with pytest.raises(ValueError):
            _make_scheduler(clock, hour=24)
        with pytest.raises(ValueError):
            _make_scheduler(clock, minute=60)


class TestSchedulerRunOnce:
    @pytest.mark.asyncio
    async def test_run_once_sleeps_until_target_then_sends(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 5, 1, 8, 0))
        sched, notifier = _make_scheduler(clock)
        body = await sched.run_once()
        assert body is not None
        assert clock.sleep_targets == [datetime(2026, 5, 1, 9, 0)]
        assert notifier.events
        assert notifier.events[-1]["event_type"] == "MONTHLY_REVIEW"

    @pytest.mark.asyncio
    async def test_run_once_send_failure_swallowed(self) -> None:
        notifier = FakeNotifier(raise_on_call=RuntimeError("boom"))
        clock = FakeClock(now_value=datetime(2026, 5, 1, 8, 0))
        sched, _ = _make_scheduler(clock, notifier=notifier)
        body = await sched.run_once()
        assert body is None  # failure swallowed


class TestSchedulerLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_idempotent(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 5, 1, 8, 0))
        sched, _ = _make_scheduler(clock)
        await sched.start()
        assert sched.is_running
        await sched.start()  # no-op
        await sched.stop()
        assert not sched.is_running
        await sched.stop()  # no-op

    @pytest.mark.asyncio
    async def test_loop_fires_review_at_least_once(self) -> None:
        clock = FakeClock(now_value=datetime(2026, 5, 1, 8, 0))
        sched, notifier = _make_scheduler(clock)
        await sched.start()
        for _ in range(10):
            if notifier.events:
                break
            await asyncio.sleep(0)
        await sched.stop()
        assert notifier.events
        assert notifier.events[0]["event_type"] == "MONTHLY_REVIEW"
