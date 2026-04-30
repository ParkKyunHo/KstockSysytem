"""V71DailySummary -- daily 15:30 close-of-market summary (P4.3).

Spec:
  - 02_TRADING_RULES.md §9.7 (일일 마감 알림 -- LOW severity)
  - 05_MIGRATION_PLAN.md §6.4 (P4.3 work plan)
  - 07_SKILLS_SPEC.md §6 (notification_skill -- DAILY_SUMMARY event)

Behaviour:
  - Composes a Korean text body covering: today's PnL, BUY / SELL log,
    tracked-stock changes (자동 이탈, 진입 임박 -- delegated callbacks),
    and tomorrow's notable events (delegated callback).
  - Sends ALWAYS, even on no-trade days ("오늘 거래 없음" placeholder).
    The 15:30 cadence is the user's primary signal that the system is
    alive (Constitution 4 -- system keeps running, observably).
  - Severity is LOW; the message routes through the standard
    Notifier Protocol so it inherits queue + circuit breaker semantics.

Constitution check:
  3 (no V7.0 collision): module lives in v71/notification/. The notifier
    is wired in by the bootstrap layer; no direct V7.0 imports.
  5 (simplicity): a frozen-dataclass context + 5 module-level pure
    helpers + a single ``send()`` orchestrator. No globals.

Pairs with :mod:`v71_daily_summary_scheduler` for the 15:30 trigger.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from src.core.v71.box.box_manager import V71BoxManager
from src.core.v71.notification.v71_telegram_commands import TrackedSummary
from src.core.v71.position.v71_position_manager import (
    BUY_EVENT_TYPES,
    SELL_EVENT_TYPES,
    TradeEvent,
    V71PositionManager,
)
from src.core.v71.strategies.v71_buy_executor import Clock
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wiring Protocols
# ---------------------------------------------------------------------------


class Notifier(Protocol):
    """Subset of :class:`V71NotificationService` we depend on.

    Re-declaring locally rather than importing avoids a heavier dep on
    the service module from a pure summary builder.
    """

    async def notify(
        self,
        *,
        severity: str,
        event_type: str,
        stock_code: str | None,
        message: str,
        rate_limit_key: str | None = None,
    ) -> None: ...


# ``list_tracked() -> Awaitable[list[TrackedSummary]]`` -- same provider
# that /tracking uses; reused so the daily summary stays in sync with
# the user's mental model. P-Wire-Box-3 made this async (DB query).
ListTrackedFn = Callable[[], Awaitable[list[TrackedSummary]]]

# ``get_tomorrow_events() -> list[str]`` -- free-form lines (e.g.
# "09:00 LG엔솔 실적 발표"). Returns empty list when no schedule.
TomorrowEventsFn = Callable[[], list[str]]

# ``get_total_capital() -> int`` -- optional. When provided, the summary
# renders a percentage figure alongside the absolute PnL.
TotalCapitalFn = Callable[[], int]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _filter_events_today(
    events: list[TradeEvent], *, now: datetime
) -> list[TradeEvent]:
    start = _start_of_day(now)
    return [e for e in events if e.timestamp >= start]


def compute_event_pnl(
    event: TradeEvent,
    *,
    avg_price_for_position: dict[str, int],
) -> int | None:
    """Realised PnL for a SELL ``event``, ``None`` for BUY events.

    ``avg_price_for_position`` maps each position's id to its current
    ``weighted_avg_price``. We deliberately use the *current* avg --
    after pyramid buys, the §6 reset means events reference the
    most-recent post-pyramid avg, which is what the user expects to see
    on the daily summary.
    """
    if event.event_type in BUY_EVENT_TYPES:
        return None
    if event.event_type not in SELL_EVENT_TYPES:
        return None
    avg = avg_price_for_position.get(event.position_id)
    if avg is None:
        return None
    return (event.price - avg) * event.quantity


def _fmt_won(amount: int) -> str:
    return f"{amount:,}원"


def _fmt_signed_won(amount: int) -> str:
    return f"{amount:+,}원"


def _fmt_signed_pct(pct: float) -> str:
    return f"{pct:+.2f}%"


def _fmt_clock(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Body composition (pure)
# ---------------------------------------------------------------------------


def compose_daily_summary_body(
    *,
    now: datetime,
    buys: list[TradeEvent],
    sells: list[TradeEvent],
    realised_pnl_amount: int,
    total_capital: int | None,
    tracked: list[TrackedSummary],
    tomorrow_events: list[str],
) -> str:
    """Render the 02 §9.7 body (Korean).

    Sections (in order):
      1. ``[일일 마감] {date}`` header
      2. PnL summary (absolute always; percent when ``total_capital`` provided)
      3. Trade log: BUY count + entries, SELL count + entries
      4. Tracked changes: 자동 이탈 (status == EXITED), 진입 임박 (현재
         시점에서 callback 결과의 marker -- /tracking과 동일 기준)
      5. Tomorrow's notable events (skipped when empty list)

    Empty days still emit the header + "오늘 거래 없음" line so the
    user sees evidence that the scheduler ran.
    """
    lines: list[str] = []
    lines.append(f"[일일 마감] {_fmt_date(now)}")
    lines.append("")

    # PnL.
    if buys or sells:
        if total_capital and total_capital > 0:
            pnl_pct = (realised_pnl_amount / total_capital) * 100
            lines.append(
                f"손익: {_fmt_signed_won(realised_pnl_amount)} "
                f"({_fmt_signed_pct(pnl_pct)})"
            )
        else:
            lines.append(f"손익: {_fmt_signed_won(realised_pnl_amount)}")
    else:
        lines.append("손익: 오늘 거래 없음")

    # Trade log.
    if buys or sells:
        lines.append("")
        lines.append("거래:")
        if buys:
            lines.append(f"  매수 {len(buys)}건")
            for e in buys:
                lines.append(
                    f"    {e.stock_code} {e.quantity}주 @ {_fmt_won(e.price)}"
                )
        if sells:
            lines.append(f"  매도 {len(sells)}건")
            for e in sells:
                lines.append(
                    f"    {e.stock_code} {e.quantity}주 @ {_fmt_won(e.price)} "
                    f"({e.event_type})"
                )

    # Tracked changes.
    exited = [t for t in tracked if t.status.upper() == "EXITED"]
    waiting_with_box = [
        t
        for t in tracked
        if t.status.upper() == "TRACKING"
        and t.box_count > 0
        and not t.has_position
    ]
    if exited or waiting_with_box:
        lines.append("")
        lines.append("추적 변화:")
        if exited:
            joined = ", ".join(f"{t.stock_name}({t.stock_code})" for t in exited)
            lines.append(f"  자동 이탈: {len(exited)}개 ({joined})")
        if waiting_with_box:
            sample = waiting_with_box[:3]
            joined = ", ".join(t.stock_name for t in sample)
            extra = "" if len(waiting_with_box) <= 3 else f" 외 {len(waiting_with_box) - 3}개"
            lines.append(
                f"  대기 중 추적: {len(waiting_with_box)}개 ({joined}{extra})"
            )

    # Tomorrow.
    if tomorrow_events:
        lines.append("")
        lines.append("내일 주목:")
        for ev in tomorrow_events:
            lines.append(f"  {ev}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context (DI bundle)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailySummaryContext:
    """Bundle of dependencies for :class:`V71DailySummary`."""

    position_manager: V71PositionManager
    box_manager: V71BoxManager
    notifier: Notifier
    clock: Clock
    list_tracked: ListTrackedFn

    # Optional.
    get_total_capital: TotalCapitalFn | None = None
    get_tomorrow_events: TomorrowEventsFn | None = None


# ---------------------------------------------------------------------------
# V71DailySummary
# ---------------------------------------------------------------------------


class V71DailySummary:
    """Build + send the daily 15:30 summary.

    Stateless across calls: :meth:`send` reads from the in-memory
    managers + callbacks each invocation. The scheduler module owns
    the timing.
    """

    def __init__(self, *, context: DailySummaryContext) -> None:
        require_enabled("v71.daily_summary")
        self._ctx = context

    async def send(self) -> str:
        """Compose and dispatch the summary; returns the body sent.

        Returning the body lets the scheduler audit-log what went out
        without re-formatting and keeps the unit tests assertion-friendly.

        Notifier failures bubble up -- the scheduler decides whether to
        retry on the next 15:30 (Constitution 4 -- a missed summary is
        not fatal).
        """
        now = self._ctx.clock.now()
        body = await self._build_body(now=now)
        await self._ctx.notifier.notify(
            severity="LOW",
            event_type="DAILY_SUMMARY",
            stock_code=None,
            message=body,
            rate_limit_key=f"daily_summary:{_fmt_date(now)}",
        )
        return body

    # ------------------------------------------------------------------
    # Body construction
    # ------------------------------------------------------------------

    async def _build_body(self, *, now: datetime) -> str:
        events_today = _filter_events_today(
            self._ctx.position_manager.list_events(), now=now
        )
        buys = [e for e in events_today if e.event_type in BUY_EVENT_TYPES]
        sells = [e for e in events_today if e.event_type in SELL_EVENT_TYPES]

        avg_index = self._build_avg_price_index(events_today)
        realised_pnl = sum(
            (
                compute_event_pnl(e, avg_price_for_position=avg_index) or 0
                for e in sells
            ),
            start=0,
        )

        total_capital: int | None = None
        if self._ctx.get_total_capital is not None:
            try:
                total_capital = self._ctx.get_total_capital()
            except Exception:  # noqa: BLE001 -- soft-fail, don't crash summary
                log.exception("get_total_capital raised; skipping percentage")

        tomorrow_events: list[str] = []
        if self._ctx.get_tomorrow_events is not None:
            try:
                tomorrow_events = list(self._ctx.get_tomorrow_events())
            except Exception:  # noqa: BLE001
                log.exception("get_tomorrow_events raised; skipping section")

        try:
            tracked = list(await self._ctx.list_tracked())
        except Exception:  # noqa: BLE001
            log.exception("list_tracked raised; rendering empty")
            tracked = []

        return compose_daily_summary_body(
            now=now,
            buys=buys,
            sells=sells,
            realised_pnl_amount=realised_pnl,
            total_capital=total_capital,
            tracked=tracked,
            tomorrow_events=tomorrow_events,
        )

    def _build_avg_price_index(
        self, events_today: list[TradeEvent]
    ) -> dict[str, int]:
        """Map ``position_id -> weighted_avg_price`` for PnL computation.

        Uses :meth:`V71PositionManager.get` to look up each unique id.
        Skips ids that aren't found (defensive -- Constitution 4).
        """
        ids = {e.position_id for e in events_today}
        avg_index: dict[str, int] = {}
        for pid in ids:
            try:
                pos = self._ctx.position_manager.get(pid)
            except KeyError:
                continue
            avg_index[pid] = pos.weighted_avg_price
        return avg_index


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledTime:
    """Hour + minute pair (24h)."""

    hour: int
    minute: int

    @classmethod
    def from_hhmm(cls, hh_mm: str) -> ScheduledTime:
        try:
            h, m = hh_mm.split(":", 1)
            hour, minute = int(h), int(m)
        except (ValueError, AttributeError) as e:
            raise ValueError(f"invalid HH:MM string {hh_mm!r}") from e
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"invalid time {hh_mm!r}")
        return cls(hour=hour, minute=minute)


class V71DailySummaryScheduler:
    """Drives :class:`V71DailySummary` at the configured wall-clock minute.

    Sleeps until the next firing using ``Clock.sleep_until``. After each
    firing it advances by 1 minute before computing the next target so a
    short clock skew or a fast-returning Clock fake doesn't fire twice
    for the same 15:30.

    Failures inside :meth:`V71DailySummary.send` are caught + logged so
    a single bad day doesn't take the loop down (Constitution 4).
    """

    def __init__(
        self,
        *,
        daily_summary: V71DailySummary,
        clock: Clock,
        target: ScheduledTime | None = None,
    ) -> None:
        require_enabled("v71.daily_summary")
        self._summary = daily_summary
        self._clock = clock
        self._target = target or ScheduledTime(hour=15, minute=30)

        import asyncio  # local import keeps module test-friendlier

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
            self._loop(), name="v71-daily-summary-scheduler"
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
    # Step (driven directly by tests)
    # ------------------------------------------------------------------

    def next_target(self, *, now: datetime | None = None) -> datetime:
        """Datetime of the next firing, strictly in the future."""
        now = now if now is not None else self._clock.now()
        candidate = now.replace(
            hour=self._target.hour,
            minute=self._target.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    async def run_once(self) -> str | None:
        """Sleep until the next firing then call :meth:`V71DailySummary.send`.

        Returns the dispatched body, or ``None`` when the summary failed
        (failure already logged).
        """
        target = self.next_target()
        await self._clock.sleep_until(target)
        try:
            return await self._summary.send()
        except Exception:  # noqa: BLE001
            log.exception("daily summary send raised; will retry tomorrow")
            return None

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        try:
            while not self._stopping:
                try:
                    await self.run_once()
                except self._asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    log.exception("daily summary loop step raised")
                # Advance past the firing minute so next_target moves
                # to tomorrow rather than now-which-is-15:30 again.
                await self._clock.sleep(60)
        except self._asyncio.CancelledError:
            return


__all__ = [
    "DailySummaryContext",
    "ListTrackedFn",
    "Notifier",
    "ScheduledTime",
    "TomorrowEventsFn",
    "TotalCapitalFn",
    "V71DailySummary",
    "V71DailySummaryScheduler",
    "compose_daily_summary_body",
    "compute_event_pnl",
]
