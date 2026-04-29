"""V71MonthlyReview -- monthly tracked-stock review (P4.4).

Spec:
  - 02_TRADING_RULES.md §9.8 (월 1회 추적 리뷰 -- LOW severity)
  - 05_MIGRATION_PLAN.md §6.5 (P4.4 work plan)
  - 03_DATA_MODEL.md §4 (monthly_reviews -- migration 016)

Behaviour:
  - Composes a Korean text body matching 02 §9.8's ABC structure:
      ■ 전체 현황      -- counts (tracking, waiting, holding, partial)
      ⚠️ 주의 필요     -- 60-day staleness, expiring 30-day reminders
      ● 상태별 분류    -- waiting / holding lists
      📋 전체 목록     -- compact roster
  - Fires once per month (rate_limit_key=``monthly_review:{YYYY-MM}``)
    so an unscheduled re-trigger never double-spams the user.
  - Emits LOW severity through the standard Notifier Protocol so it
    inherits queue + circuit breaker semantics.
  - The companion :class:`V71MonthlyReviewScheduler` aligns the firing
    to "1st of month at 09:00" using ``Clock.sleep_until``.

Constitution check:
  3 (no V7.0 collision): module lives in v71/notification/. The notifier
    is wired in by the bootstrap layer; no V7.0 imports.
  4 (system keeps running): callback failures are swallowed (the
    section is skipped); scheduler retries the next month.
  5 (simplicity): pure compose function + thin send wrapper + simple
    cron loop (no APScheduler).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from src.core.v71.strategies.v71_buy_executor import Clock
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wiring Protocols / data
# ---------------------------------------------------------------------------


class Notifier(Protocol):
    """Subset of :class:`V71NotificationService` we depend on."""

    async def notify(
        self,
        *,
        severity: str,
        event_type: str,
        stock_code: str | None,
        message: str,
        rate_limit_key: str | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class MonthlyReviewItem:
    """Per-stock snapshot for the monthly review.

    The bootstrap layer composes these from ``tracked_stocks`` +
    ``support_boxes`` + ``positions`` and hands the list to
    :class:`V71MonthlyReview`. Keeping it as a flat dataclass means the
    compose function does not reach into any V71 manager.
    """

    stock_code: str
    stock_name: str
    path_type: str  # PATH_A | PATH_B | MANUAL
    status: str  # TRACKING | EXITED
    box_count: int
    waiting_box_count: int
    has_position: bool
    has_partial_exit: bool
    created_at: datetime
    """When the user first registered the tracked stock."""


# Stale threshold (matches 02 §9.8 "장기 정체 60일+").
DEFAULT_STALE_DAYS = 60


# Callbacks -- the bootstrap layer wires these.
ListReviewItemsFn = Callable[[], list[MonthlyReviewItem]]
ListExpiringBoxesFn = Callable[[], int]
"""Returns the number of WAITING boxes whose 30-day reminder is due
(02 §3.7 + V71BoxManager.check_30day_expiry). Used for the
``박스 만료 임박`` line."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _fmt_year_month(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _is_stale(item: MonthlyReviewItem, *, now: datetime) -> bool:
    """True for ``TRACKING`` items at least :data:`DEFAULT_STALE_DAYS`
    days old that have NOT taken a position (60일+ 박스 미체결)."""
    if item.status.upper() != "TRACKING":
        return False
    if item.has_position:
        return False
    age = now - item.created_at
    return age >= timedelta(days=DEFAULT_STALE_DAYS)


@dataclass(frozen=True)
class MonthlyCounts:
    """Aggregate counts for the ``전체 현황`` block."""

    tracking: int
    waiting_boxes: int
    holding: int
    partial: int

    @classmethod
    def from_items(cls, items: list[MonthlyReviewItem]) -> MonthlyCounts:
        tracking = sum(1 for i in items if i.status.upper() == "TRACKING")
        waiting_boxes = sum(i.waiting_box_count for i in items)
        holding = sum(1 for i in items if i.has_position)
        partial = sum(1 for i in items if i.has_partial_exit)
        return cls(
            tracking=tracking,
            waiting_boxes=waiting_boxes,
            holding=holding,
            partial=partial,
        )


# ---------------------------------------------------------------------------
# Body composition (pure)
# ---------------------------------------------------------------------------


def compose_monthly_review_body(
    *,
    now: datetime,
    items: list[MonthlyReviewItem],
    expiring_boxes_count: int = 0,
) -> str:
    """Render the 02 §9.8 ABC body (Korean)."""
    counts = MonthlyCounts.from_items(items)
    lines: list[str] = []
    lines.append(f"[월간 리뷰] {_fmt_year_month(now)}")
    lines.append("")

    # ■ 전체 현황
    lines.append("[전체 현황]")
    lines.append(f"  추적 중: {counts.tracking}개")
    lines.append(f"  박스 대기: {counts.waiting_boxes}개")
    lines.append(f"  포지션 보유: {counts.holding}개")
    lines.append(f"  부분 청산: {counts.partial}개")

    # ⚠️ 주의 필요
    stale = [i for i in items if _is_stale(i, now=now)]
    if stale or expiring_boxes_count > 0:
        lines.append("")
        lines.append("[주의 필요]")
        if stale:
            joined = ", ".join(
                f"{i.stock_name}({i.stock_code})" for i in stale[:5]
            )
            extra = (
                ""
                if len(stale) <= 5
                else f" 외 {len(stale) - 5}개"
            )
            lines.append(
                f"  장기 정체: {len(stale)}개 -- {joined}{extra}"
            )
        if expiring_boxes_count > 0:
            lines.append(f"  박스 만료 임박 (30일): {expiring_boxes_count}개")

    # ● 상태별 분류
    waiting = [
        i
        for i in items
        if i.status.upper() == "TRACKING"
        and i.waiting_box_count > 0
        and not i.has_position
    ]
    holding = [i for i in items if i.has_position]
    if waiting or holding:
        lines.append("")
        lines.append("[상태별 분류]")
        if waiting:
            lines.append(f"  박스 대기 ({len(waiting)})")
            for item in waiting[:10]:
                lines.append(
                    f"    - {item.stock_name}({item.stock_code}) "
                    f"{item.path_type} 박스 {item.waiting_box_count}개"
                )
            if len(waiting) > 10:
                lines.append(f"    외 {len(waiting) - 10}개")
        if holding:
            lines.append(f"  포지션 보유 ({len(holding)})")
            for item in holding[:10]:
                marker = " (부분 청산)" if item.has_partial_exit else ""
                lines.append(
                    f"    - {item.stock_name}({item.stock_code}) "
                    f"{item.path_type}{marker}"
                )
            if len(holding) > 10:
                lines.append(f"    외 {len(holding) - 10}개")

    # 📋 전체 목록
    if items:
        lines.append("")
        lines.append(f"[전체 목록] ({len(items)})")
        for item in items:
            lines.append(
                f"  {item.stock_code} {item.stock_name} "
                f"({item.path_type}, {item.status})"
            )
    else:
        lines.append("")
        lines.append("추적 중인 종목이 없습니다.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context (DI bundle)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthlyReviewContext:
    """Bundle of dependencies for :class:`V71MonthlyReview`."""

    notifier: Notifier
    clock: Clock
    list_review_items: ListReviewItemsFn

    list_expiring_boxes: ListExpiringBoxesFn | None = None
    """Optional. ``None`` skips the ``박스 만료 임박`` line."""


# ---------------------------------------------------------------------------
# V71MonthlyReview
# ---------------------------------------------------------------------------


class V71MonthlyReview:
    """Build + send the monthly tracked-stock review."""

    def __init__(self, *, context: MonthlyReviewContext) -> None:
        require_enabled("v71.monthly_review")
        self._ctx = context

    async def send(self) -> str:
        now = self._ctx.clock.now()
        body = self._build_body(now=now)
        await self._ctx.notifier.notify(
            severity="LOW",
            event_type="MONTHLY_REVIEW",
            stock_code=None,
            message=body,
            rate_limit_key=f"monthly_review:{_fmt_year_month(now)}",
        )
        return body

    def _build_body(self, *, now: datetime) -> str:
        try:
            items = list(self._ctx.list_review_items())
        except Exception:  # noqa: BLE001
            log.exception("list_review_items raised; rendering empty review")
            items = []

        expiring = 0
        if self._ctx.list_expiring_boxes is not None:
            try:
                expiring = int(self._ctx.list_expiring_boxes())
            except Exception:  # noqa: BLE001
                log.exception(
                    "list_expiring_boxes raised; skipping 만료 임박 line"
                )
                expiring = 0

        return compose_monthly_review_body(
            now=now,
            items=items,
            expiring_boxes_count=expiring,
        )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def _first_of_next_month(dt: datetime) -> datetime:
    """1st of the month strictly after ``dt``'s month, at 00:00.

    Preserves ``dt.tzinfo`` (None for naive, KST/UTC for aware) so callers
    that pass tz-aware ``now`` get tz-aware results -- avoids
    ``can't compare offset-naive and offset-aware datetimes``.
    """
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1, tzinfo=dt.tzinfo)
    return datetime(dt.year, dt.month + 1, 1, tzinfo=dt.tzinfo)


class V71MonthlyReviewScheduler:
    """Drive :class:`V71MonthlyReview` on the 1st of every month at 09:00.

    Design:
      - ``next_target(now)`` returns the next 1st-of-month at the
        configured hour/minute strictly in the future. If today is the
        1st but the wall clock is already past the target, the next
        firing rolls to next month -- this prevents double-firing for
        the same month after a process restart on the 1st (rate_limit_key
        also guards via the queue's RATE_LIMIT, but skipping at the
        scheduler keeps the loop simple).
      - ``run_once`` awaits ``Clock.sleep_until(next_target)`` then calls
        :meth:`V71MonthlyReview.send`. Send failures are swallowed +
        logged so the loop survives.
      - ``_loop`` advances by one minute after each firing so the
        next ``next_target`` rolls to the following month.

    Constitution 5: same shape as :class:`V71DailySummaryScheduler`
    (intentionally similar -- one cron loop pattern, two firings).
    """

    def __init__(
        self,
        *,
        monthly_review: V71MonthlyReview,
        clock: Clock,
        hour: int = 9,
        minute: int = 0,
    ) -> None:
        require_enabled("v71.monthly_review")
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"invalid time {hour}:{minute}")
        self._review = monthly_review
        self._clock = clock
        self._hour = hour
        self._minute = minute

        import asyncio

        self._asyncio = asyncio
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = self._asyncio.create_task(
            self._loop(), name="v71-monthly-review-scheduler"
        )

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except (self._asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        finally:
            self._task = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------

    def next_target(self, *, now: datetime | None = None) -> datetime:
        """Datetime of the next monthly firing, strictly in the future.

        ``self._clock.now()`` returns a tz-aware datetime (V71RealClock =
        KST). ``candidate`` must inherit ``now.tzinfo`` to allow comparison
        without ``can't compare offset-naive and offset-aware`` TypeError.
        """
        now = now if now is not None else self._clock.now()
        candidate = datetime(
            now.year, now.month, 1, self._hour, self._minute, 0,
            tzinfo=now.tzinfo,
        )
        if candidate <= now:
            candidate = _first_of_next_month(now).replace(
                hour=self._hour, minute=self._minute
            )
        return candidate

    async def run_once(self) -> str | None:
        target = self.next_target()
        await self._clock.sleep_until(target)
        try:
            return await self._review.send()
        except Exception:  # noqa: BLE001
            log.exception("monthly review send raised; will retry next month")
            return None

    async def _loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    await self.run_once()
                except self._asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    log.exception("monthly review loop step raised")
                # Sleep one minute so next_target rolls to the next month.
                await self._clock.sleep(60)
        except self._asyncio.CancelledError:
            return


__all__ = [
    "DEFAULT_STALE_DAYS",
    "ListExpiringBoxesFn",
    "ListReviewItemsFn",
    "MonthlyCounts",
    "MonthlyReviewContext",
    "MonthlyReviewItem",
    "Notifier",
    "V71MonthlyReview",
    "V71MonthlyReviewScheduler",
    "compose_monthly_review_body",
]
