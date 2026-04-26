"""Skill 5: Volatility Interruption (VI) state machine.

Spec: docs/v71/07_SKILLS_SPEC.md §5, docs/v71/02_TRADING_RULES.md §10

VI rule summary:
  - On TRIGGERED: pause stop/take-profit checks; new buys can join the
    single-price auction, but post-VI gap >= 3% aborts the entry.
  - On RESUMED: re-evaluate immediately (target latency < 1s); honor
    stops as market orders if breached; set vi_recovered_today on
    tracked_stocks so no new entries fire today on this stock.

State machine: NORMAL -> TRIGGERED -> RESUMED -> NORMAL.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VIState(Enum):
    NORMAL = "NORMAL"
    TRIGGERED = "TRIGGERED"
    RESUMED = "RESUMED"


@dataclass(frozen=True)
class VIStateContext:
    """Inputs at the moment of decision."""

    stock_code: str
    current_state: VIState
    trigger_price: int | None
    triggered_at: object | None  # datetime | None
    last_close_before_vi: int | None
    current_price: int | None


@dataclass(frozen=True)
class VIDecision:
    next_state: VIState
    block_new_entries_today: bool
    abort_in_flight_buy: bool
    force_market_sell: bool
    reason: str


def handle_vi_state(
    context: VIStateContext,
    event: str,  # "TRIGGER" | "RESUME" | "POLL"
) -> VIDecision:
    """Apply the VI state machine and produce the resulting decision.

    Pure function: caller persists ``next_state`` and triggers the
    appropriate Kiwoom action (cancel pending orders, market-sell on
    breached stop, set vi_recovered_today).
    """
    raise NotImplementedError("P3.6 -- see docs/v71/07_SKILLS_SPEC.md §5.3")


def check_post_vi_gap(
    last_close_before_vi: int,
    first_price_after_resume: int,
) -> tuple[bool, float]:
    """Return (abort_buy, gap_pct).

    abort_buy is True when |gap_pct| >= V71Constants.VI_GAP_LIMIT.
    """
    raise NotImplementedError("P3.6 -- see docs/v71/07_SKILLS_SPEC.md §5.4")


def transition_vi_state(current: VIState, event: str) -> VIState:
    """Pure transition -- raises ValueError on illegal event."""
    raise NotImplementedError("P3.6 -- see docs/v71/07_SKILLS_SPEC.md §5.2")


__all__ = [
    "VIState",
    "VIStateContext",
    "VIDecision",
    "handle_vi_state",
    "check_post_vi_gap",
    "transition_vi_state",
]
