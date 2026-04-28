"""Skill 2: Box entry condition evaluator.

Spec:
  - 02_TRADING_RULES.md §3.8~§3.11 (entry conditions, PATH_A/PATH_B)
  - 02_TRADING_RULES.md §10.9   (PATH_B opening-VI safety net)
  - 07_SKILLS_SPEC.md §2

Constitution: every box-entry decision MUST go through
:func:`evaluate_box_entry`. Hand-rolled if/elif chains over candle/box
fields in callers are forbidden (Harness 3 will pin this).

Candle reuse:
  We import V7.0's :class:`Candle` (``src.core.candle_builder.Candle``)
  verbatim -- Constitution 3 (no V7.0/V7.1 collision; Harness 1) and
  the P2.3 decision recorded in WORK_LOG.md.

PATH_B safety net (P3.1 patch):
  PATH_B's 09:01 buy can miss when the open auction triggers a static VI
  (single-price area). We surface a fallback at 09:05 (market order)
  through :class:`EntryDecision`. The actual fallback execution lives in
  P3.2 (V71BuyExecutor).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from src.core.v71.candle.types import V71Candle as Candle
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

PathType = Literal["PATH_A", "PATH_B"]
StrategyType = Literal["PULLBACK", "BREAKOUT"]


@dataclass(frozen=True)
class Box:
    """Minimal box info for entry evaluation.

    The full record lives in ``support_boxes``; box_manager hydrates this
    structure for the skill so the skill is testable without DB.
    """

    upper_price: int
    lower_price: int
    strategy_type: StrategyType
    path_type: PathType


@dataclass(frozen=True)
class MarketContext:
    """Market-side flags needed for entry decisions."""

    is_market_open: bool         # regular session 09:00~15:30
    is_vi_active: bool           # VI currently triggered for the stock
    is_vi_recovered_today: bool  # already recovered from VI today
    current_time: datetime


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EntryDecision:
    """Outcome of a box-entry evaluation.

    The ``reason`` string is a stable machine-readable code (logged + used
    by tests). Fallback fields are populated only for PATH_B successful
    decisions; see §3.10/§3.11/§10.9.
    """

    should_enter: bool
    reason: str
    box_id: str | None
    expected_buy_price: int | None
    expected_buy_at: datetime | None

    # PATH_B safety net. Defaults make PATH_A and rejections trivially safe.
    fallback_buy_at: datetime | None = None
    fallback_uses_market_order: bool = False
    fallback_gap_recheck_required: bool = False


# ---------------------------------------------------------------------------
# Public skill API
# ---------------------------------------------------------------------------

def evaluate_box_entry(
    *,
    box: Box,
    current_candle: Candle,
    previous_candle: Candle | None,
    market_context: MarketContext,
) -> EntryDecision:
    """Single decision point for box entry (PATH_A and PATH_B).

    Raises:
        ValueError: invalid input (e.g. ``upper <= lower``,
            missing previous candle for PATH_A pullback).
        RuntimeError: feature flag ``v71.box_system`` disabled.
    """
    require_enabled("v71.box_system")
    _validate_inputs(box, current_candle, previous_candle)

    # Market-state guards (early reject).
    if not market_context.is_market_open:
        return EntryDecision(False, "MARKET_CLOSED", None, None, None)

    if market_context.is_vi_active:
        # VI handling delegated to vi_skill (§10.4).
        return EntryDecision(False, "VI_ACTIVE_USE_VI_SKILL", None, None, None)

    if market_context.is_vi_recovered_today:
        return EntryDecision(False, "VI_RECOVERED_TODAY_BLOCKED", None, None, None)

    if box.strategy_type == "PULLBACK":
        return _evaluate_pullback(box, current_candle, previous_candle, market_context)
    if box.strategy_type == "BREAKOUT":
        return _evaluate_breakout(box, current_candle, market_context)

    raise ValueError(f"Unknown strategy_type: {box.strategy_type!r}")


def is_pullback_setup(
    *,
    box: Box,
    current_candle: Candle,
    previous_candle: Candle,
) -> bool:
    """Pure check -- True iff PULLBACK conditions hold.

    Callers should prefer :func:`evaluate_box_entry`. This helper exists
    for tests and for places that need the bare condition without market
    context.
    """
    return _pullback_conditions_met(box, current_candle, previous_candle)


def is_breakout_setup(*, box: Box, current_candle: Candle) -> bool:
    """Pure check -- True iff BREAKOUT conditions hold."""
    return _breakout_conditions_met(box, current_candle)


def is_bullish(candle: Candle) -> bool:
    """Helper for callers (V7.0 ``Candle`` has no convenience method)."""
    return candle.close > candle.open


def check_gap_up_for_path_b(
    previous_close: int,
    reference_price: int,
) -> tuple[bool, float]:
    """Gap-up check for PATH_B (1차 09:01 + 2차 09:05 fallback 공통).

    Args:
        previous_close: closing price on the entry-condition day.
        reference_price: probe price (open at 09:01, current at 09:05).

    Returns:
        ``(should_proceed, gap_pct)``.

        - 1차 시점 gap >= 5%: skip primary buy (no fallback either; §3.10).
        - 2차 시점 gap >= 5%: invalidate the safety net (§10.9).
    """
    if previous_close <= 0 or reference_price <= 0:
        raise ValueError("prices must be positive")
    gap_pct = (reference_price - previous_close) / previous_close
    should_proceed = gap_pct < V71Constants.PATH_B_GAP_UP_LIMIT
    return should_proceed, gap_pct


# ---------------------------------------------------------------------------
# Strategy implementations (private)
# ---------------------------------------------------------------------------

def _evaluate_pullback(
    box: Box,
    current: Candle,
    previous: Candle | None,
    context: MarketContext,
) -> EntryDecision:
    """Pullback: §3.8 (PATH_A 3-min) / §3.10 (PATH_B daily)."""
    if box.path_type == "PATH_A":
        # PATH_A requires both candles to satisfy conditions.
        assert previous is not None  # checked by _validate_inputs
        if not _candle_inside_box_bullish(previous, box):
            return EntryDecision(False, "PULLBACK_A_PREV_NOT_MET", None, None, None)
        if not _candle_inside_box_bullish(current, box):
            return EntryDecision(False, "PULLBACK_A_CURR_NOT_MET", None, None, None)
        return EntryDecision(
            should_enter=True,
            reason="PULLBACK_A_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close,
            expected_buy_at=context.current_time,
        )

    if box.path_type == "PATH_B":
        if not _candle_inside_box_bullish(current, box):
            return EntryDecision(False, "PULLBACK_B_NOT_MET", None, None, None)
        primary, fallback = _next_trading_day_buy_times(context.current_time)
        return EntryDecision(
            should_enter=True,
            reason="PULLBACK_B_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close,  # ref only; actual at next-day open
            expected_buy_at=primary,
            fallback_buy_at=fallback,
            fallback_uses_market_order=V71Constants.PATH_B_FALLBACK_USES_MARKET_ORDER,
            fallback_gap_recheck_required=True,
        )

    raise ValueError(f"Unknown path_type: {box.path_type!r}")


def _evaluate_breakout(
    box: Box,
    current: Candle,
    context: MarketContext,
) -> EntryDecision:
    """Breakout: §3.9 (PATH_A) / §3.11 (PATH_B)."""
    if not (current.close > box.upper_price):
        return EntryDecision(False, "BREAKOUT_NO_BREAK", None, None, None)
    if not is_bullish(current):
        return EntryDecision(False, "BREAKOUT_NOT_BULLISH", None, None, None)
    if current.open < box.lower_price:
        # Gap-up case excluded -- box.lower is the floor for "normal" breakout.
        return EntryDecision(False, "BREAKOUT_GAP_OPEN", None, None, None)

    if box.path_type == "PATH_A":
        return EntryDecision(
            should_enter=True,
            reason="BREAKOUT_A_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close,
            expected_buy_at=context.current_time,
        )

    if box.path_type == "PATH_B":
        primary, fallback = _next_trading_day_buy_times(context.current_time)
        return EntryDecision(
            should_enter=True,
            reason="BREAKOUT_B_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close,
            expected_buy_at=primary,
            fallback_buy_at=fallback,
            fallback_uses_market_order=V71Constants.PATH_B_FALLBACK_USES_MARKET_ORDER,
            fallback_gap_recheck_required=True,
        )

    raise ValueError(f"Unknown path_type: {box.path_type!r}")


# ---------------------------------------------------------------------------
# Pure condition helpers (no flag check, no datetime)
# ---------------------------------------------------------------------------

def _pullback_conditions_met(
    box: Box, current: Candle, previous: Candle
) -> bool:
    return (
        _candle_inside_box_bullish(current, box)
        and _candle_inside_box_bullish(previous, box)
    )


def _breakout_conditions_met(box: Box, current: Candle) -> bool:
    return (
        current.close > box.upper_price
        and is_bullish(current)
        and current.open >= box.lower_price
    )


def _candle_inside_box_bullish(candle: Candle, box: Box) -> bool:
    return (
        is_bullish(candle)
        and box.lower_price <= candle.close <= box.upper_price
    )


# ---------------------------------------------------------------------------
# Datetime helpers (PATH_B)
# ---------------------------------------------------------------------------

def _next_trading_day_buy_times(
    current_time: datetime,
) -> tuple[datetime, datetime]:
    """Return ``(primary 09:01, fallback 09:05)`` for the next trading day."""
    primary = _calculate_next_trading_day_at(
        current_time, V71Constants.PATH_B_PRIMARY_BUY_TIME_HHMM
    )
    fallback = _calculate_next_trading_day_at(
        current_time, V71Constants.PATH_B_FALLBACK_BUY_TIME_HHMM
    )
    return primary, fallback


def _calculate_next_trading_day_at(
    current_time: datetime, hhmm: str
) -> datetime:
    """Next trading day at the given HH:MM.

    Uses :mod:`src.core.market_schedule` (V7.0 infrastructure). Tests may
    monkey-patch :func:`_get_holiday_checker` to inject a fake (no V7.0
    singleton dependency in unit tests).
    """
    is_holiday = _get_holiday_checker()
    next_day = current_time.date() + timedelta(days=1)
    for _ in range(30):  # safety bound
        if next_day.weekday() < 5 and not is_holiday(next_day):
            break
        next_day += timedelta(days=1)
    else:
        raise RuntimeError(
            "No trading day found within 30 days after "
            f"{current_time.date().isoformat()}"
        )
    h, m = (int(p) for p in hhmm.split(":"))
    return datetime.combine(next_day, time(h, m))


def _get_holiday_checker() -> Callable[[date], bool]:
    """V7.0 holiday checker; tests monkey-patch this indirection."""
    from src.core.v71.market.v71_market_schedule import (
        get_v71_market_schedule as get_market_schedule,
    )
    schedule = get_market_schedule()
    return schedule.is_holiday


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_inputs(
    box: Box,
    current: Candle,
    previous: Candle | None,
) -> None:
    if box.upper_price <= box.lower_price:
        raise ValueError("Box upper_price must be > lower_price")
    if box.lower_price <= 0:
        raise ValueError("Box prices must be positive")
    if current.close <= 0 or current.open <= 0:
        raise ValueError("Invalid current candle prices")
    if (
        box.strategy_type == "PULLBACK"
        and box.path_type == "PATH_A"
        and previous is None
    ):
        raise ValueError("PULLBACK + PATH_A requires previous candle")


__all__ = [
    "Box",
    "MarketContext",
    "EntryDecision",
    "PathType",
    "StrategyType",
    "evaluate_box_entry",
    "is_pullback_setup",
    "is_breakout_setup",
    "is_bullish",
    "check_gap_up_for_path_b",
]
