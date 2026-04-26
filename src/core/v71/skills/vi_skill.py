"""Skill 5: Volatility Interruption (VI) state machine.

Spec:
  - 02_TRADING_RULES.md §10 (VI handling)
  - 07_SKILLS_SPEC.md §5

Phase: P3.6

VI rule summary (§10):
  - On TRIGGERED: pause stop/take-profit checks; new buys can join the
    single-price auction, but post-VI gap >= 3% aborts the entry.
  - On RESUMED: re-evaluate immediately (target latency < 1s); honor
    stops as market orders if breached; set vi_recovered_today on the
    affected stock so no new entries fire today on it.

State machine: NORMAL -> TRIGGERED -> RESUMED -> NORMAL

Events:
  VI_DETECTED  - WebSocket VI 발동 (9068=1)
  VI_RESOLVED  - WebSocket VI 해제 (9068=2)
  VI_RESETTLED - re-evaluation finished -> back to NORMAL with flag set
  DAILY_RESET  - next-day 09:00 wipe (any -> NORMAL)

The skill is pure: callers persist ``next_state`` and trigger the
appropriate Kiwoom action (cancel pending orders, market-sell on
breached stop, set vi_recovered_today).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.core.v71.v71_constants import V71Constants

# ---------------------------------------------------------------------------
# State + events
# ---------------------------------------------------------------------------

class VIState(Enum):
    NORMAL = "NORMAL"
    TRIGGERED = "TRIGGERED"
    RESUMED = "RESUMED"


# Events (string for easy logging; callers also use these in log messages).
EVENT_VI_DETECTED = "VI_DETECTED"
EVENT_VI_RESOLVED = "VI_RESOLVED"
EVENT_VI_RESETTLED = "VI_RESETTLED"
EVENT_DAILY_RESET = "DAILY_RESET"

ALLOWED_EVENTS = frozenset(
    {EVENT_VI_DETECTED, EVENT_VI_RESOLVED, EVENT_VI_RESETTLED, EVENT_DAILY_RESET}
)


_TRANSITIONS: Mapping[VIState, Mapping[str, VIState]] = {
    VIState.NORMAL: {
        EVENT_VI_DETECTED: VIState.TRIGGERED,
    },
    VIState.TRIGGERED: {
        EVENT_VI_RESOLVED: VIState.RESUMED,
    },
    VIState.RESUMED: {
        EVENT_VI_RESETTLED: VIState.NORMAL,
    },
}


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VIStateContext:
    """Inputs at the moment of decision."""

    stock_code: str
    current_state: VIState
    trigger_price: int | None
    triggered_at: datetime | None
    last_close_before_vi: int | None
    current_price: int | None


@dataclass(frozen=True)
class VIDecision:
    next_state: VIState
    block_new_entries_today: bool
    abort_in_flight_buy: bool
    force_market_sell: bool
    reason: str


# ---------------------------------------------------------------------------
# Pure transitions
# ---------------------------------------------------------------------------

def transition_vi_state(current: VIState, event: str) -> VIState:
    """Pure VI state transition.

    DAILY_RESET is special: it returns NORMAL from any state (so the
    09:00 next-day reset works regardless of how the prior day ended).
    Other events follow the strict A -> B -> C -> A linear chain.

    Raises:
        ValueError: if ``event`` is unknown or illegal from ``current``.
    """
    if event not in ALLOWED_EVENTS:
        raise ValueError(f"Unknown VI event: {event!r}")

    if event == EVENT_DAILY_RESET:
        return VIState.NORMAL

    allowed = _TRANSITIONS.get(current, {})
    if event not in allowed:
        raise ValueError(
            f"Illegal VI transition: {current.value} --[{event}]--> ?  "
            f"Allowed events for {current.value}: "
            f"{list(allowed) or '(terminal-ish)'}"
        )
    return allowed[event]


# ---------------------------------------------------------------------------
# Post-VI gap check  --  §10.4 Step 3
# ---------------------------------------------------------------------------

def check_post_vi_gap(
    last_close_before_vi: int,
    first_price_after_resume: int,
) -> tuple[bool, float]:
    """Return ``(abort_buy, gap_pct)`` for §10.4 step 3.

    abort_buy is True when ``|gap_pct| >= V71Constants.VI_GAP_LIMIT``
    (3%). Gap can be positive (gap-up) or negative (gap-down); both
    directions abort because in either case the post-VI price diverges
    materially from the pre-VI close.
    """
    if last_close_before_vi <= 0 or first_price_after_resume <= 0:
        raise ValueError("prices must be positive")
    gap_pct = (
        (first_price_after_resume - last_close_before_vi)
        / last_close_before_vi
    )
    abort = abs(gap_pct) >= V71Constants.VI_GAP_LIMIT
    return abort, gap_pct


# ---------------------------------------------------------------------------
# Combined state-machine + decision
# ---------------------------------------------------------------------------

def handle_vi_state(context: VIStateContext, event: str) -> VIDecision:
    """Apply the VI state machine and produce the resulting decision.

    Decision flags:
      - ``block_new_entries_today``: True only when transitioning out of
        RESUMED back to NORMAL via VI_RESETTLED -- this is when we set
        ``vi_recovered_today`` on the stock.
      - ``abort_in_flight_buy``: not used yet (callers track in-flight
        orders separately). Reserved for future.
      - ``force_market_sell``: not used yet. Caller decides per-position
        based on V71ExitCalculator's evaluation post-resume.

    Pure: no IO, just deterministic state + flags.
    """
    next_state = transition_vi_state(context.current_state, event)

    block_new_entries_today = event == EVENT_VI_RESETTLED
    reason = f"{context.current_state.value} --[{event}]--> {next_state.value}"

    return VIDecision(
        next_state=next_state,
        block_new_entries_today=block_new_entries_today,
        abort_in_flight_buy=False,
        force_market_sell=False,
        reason=reason,
    )


__all__ = [
    "VIState",
    "VIStateContext",
    "VIDecision",
    "EVENT_VI_DETECTED",
    "EVENT_VI_RESOLVED",
    "EVENT_VI_RESETTLED",
    "EVENT_DAILY_RESET",
    "ALLOWED_EVENTS",
    "transition_vi_state",
    "check_post_vi_gap",
    "handle_vi_state",
]
