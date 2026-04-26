"""Skill 3: Stop / take-profit / trailing-stop calculator.

Spec:
  - 02_TRADING_RULES.md §5  (post-buy management)
  - 07_SKILLS_SPEC.md §3
  - 04_ARCHITECTURE.md §5.3

Phase: P3.3

Single source of truth for V7.1 exit math. Callers MUST NOT compute
stop ladders, ATR multipliers, or partial-exit thresholds inline --
Harness 3 blocks magic literals against the V71Constants tier values.

Effective stop is always:
    effective_stop = max(fixed_stop, ts_stop_if_valid)

All functions are pure: no IO, no side effects. Stateful TS bookkeeping
(BasePrice carryover, multiplier ratchet) lives in V71TrailingStop /
V71PositionManager; this skill only computes the next state given the
current snapshot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.core.v71.v71_constants import V71Constants

# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionSnapshot:
    """Read-only view of a position at the moment of exit calculation."""

    weighted_avg_price: int
    initial_avg_price: int
    fixed_stop_price: int
    profit_5_executed: bool
    profit_10_executed: bool
    ts_activated: bool
    ts_base_price: int | None
    ts_stop_price: int | None
    ts_active_multiplier: float | None
    current_price: int
    atr_value: float
    """ATR(10) of the active timeframe."""


@dataclass(frozen=True)
class EffectiveStopResult:
    effective_stop_price: int
    source: str  # "FIXED" | "TS"
    triggered: bool
    reason: str


@dataclass(frozen=True)
class ProfitTakeResult:
    should_exit: bool
    level: str  # "PROFIT_5" | "PROFIT_10" | "NONE"
    quantity_to_sell: int
    new_position_status: str  # "PARTIAL_CLOSED" | "CLOSED" | "OPEN"


@dataclass(frozen=True)
class TSUpdateResult:
    activate: bool
    new_base_price: int | None
    new_stop_price: int | None
    new_multiplier: float | None
    reason: str


# ---------------------------------------------------------------------------
# Effective stop  --  §5.6
# ---------------------------------------------------------------------------

def calculate_effective_stop(snapshot: PositionSnapshot) -> EffectiveStopResult:
    """Combine fixed stop and TS into one effective exit line.

    Rules (§5.6):
      - TS stop is only binding once ``profit_10_executed`` is True
        (TS_VALID_LEVEL gate).
      - Otherwise effective = ``fixed_stop_price``.
      - ``triggered=True`` when ``current_price <= effective_stop_price``.
    """
    fixed = snapshot.fixed_stop_price

    ts_is_binding = (
        snapshot.profit_10_executed
        and snapshot.ts_activated
        and snapshot.ts_stop_price is not None
    )

    if ts_is_binding and snapshot.ts_stop_price is not None:
        if snapshot.ts_stop_price > fixed:
            effective = snapshot.ts_stop_price
            source = "TS"
        else:
            effective = fixed
            source = "FIXED"
    else:
        effective = fixed
        source = "FIXED"

    triggered = snapshot.current_price <= effective
    reason = (
        f"current {snapshot.current_price} <= effective {effective} "
        f"(source={source})"
        if triggered
        else f"current {snapshot.current_price} > effective {effective}"
    )
    return EffectiveStopResult(
        effective_stop_price=effective,
        source=source,
        triggered=triggered,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Profit-take  --  §5.2 / §5.3
# ---------------------------------------------------------------------------

def evaluate_profit_take(
    snapshot: PositionSnapshot, total_quantity: int
) -> ProfitTakeResult:
    """Decide whether to slice +5% or +10% partial exit (30% each).

    Each level fires at most once per position (idempotent via the
    ``profit_*_executed`` flags); +10% is gated on +5% having executed
    first per §5.3.
    """
    if total_quantity <= 0:
        return ProfitTakeResult(
            should_exit=False, level="NONE",
            quantity_to_sell=0, new_position_status="CLOSED",
        )

    profit_pct = _profit_pct(snapshot)

    # +10% second slice -- gated on +5% having executed.
    if (
        profit_pct >= V71Constants.PROFIT_TAKE_LEVEL_2
        and snapshot.profit_5_executed
        and not snapshot.profit_10_executed
    ):
        qty = _slice_quantity(total_quantity)
        return ProfitTakeResult(
            should_exit=True,
            level="PROFIT_10",
            quantity_to_sell=qty,
            new_position_status=(
                "CLOSED" if qty >= total_quantity else "PARTIAL_CLOSED"
            ),
        )

    # +5% first slice.
    if (
        profit_pct >= V71Constants.PROFIT_TAKE_LEVEL_1
        and not snapshot.profit_5_executed
    ):
        qty = _slice_quantity(total_quantity)
        return ProfitTakeResult(
            should_exit=True,
            level="PROFIT_5",
            quantity_to_sell=qty,
            new_position_status=(
                "CLOSED" if qty >= total_quantity else "PARTIAL_CLOSED"
            ),
        )

    return ProfitTakeResult(
        should_exit=False, level="NONE",
        quantity_to_sell=0, new_position_status="OPEN",
    )


def _slice_quantity(total_quantity: int) -> int:
    """30% slice with floor + minimum 1 share."""
    raw = math.floor(total_quantity * V71Constants.PROFIT_TAKE_RATIO)
    return max(raw, 1)


# ---------------------------------------------------------------------------
# Trailing stop  --  §5.5
# ---------------------------------------------------------------------------

def update_trailing_stop(snapshot: PositionSnapshot) -> TSUpdateResult:
    """Recompute TS BasePrice / stop / multiplier per V7.1 ladder.

    Activation timeline (§5.5):
      - profit_pct >= TS_ACTIVATION_LEVEL (+5%)  -> activate, start
        BasePrice tracking. Stop line is NOT yet binding.
      - profit_10_executed == True  -> stop line becomes binding (this
        is enforced by ``calculate_effective_stop``, not here).

    BasePrice (§5.5):
      - V7.0's "Highest(High, 20)" rule is dropped.
      - V7.1: simple "post-buy running high" -- max of current_price and
        the previous BasePrice.

    Multiplier ladder (one-way tightening, never widens):
      +10~15% -> 4.0, +15~25% -> 3.0, +25~40% -> 2.5, +40%~ -> 2.0

    Stop line (one-way upward):
      candidate = base_price - atr_value * multiplier
      new_stop  = max(candidate, previous_stop) -- never falls.
    """
    profit_pct = _profit_pct(snapshot)

    # Below activation: nothing to do.
    if profit_pct < V71Constants.TS_ACTIVATION_LEVEL:
        return TSUpdateResult(
            activate=False,
            new_base_price=None,
            new_stop_price=None,
            new_multiplier=None,
            reason=f"profit_pct {profit_pct:.4f} < {V71Constants.TS_ACTIVATION_LEVEL}",
        )

    # Activation / re-activation: ensure base price is tracked from here.
    base_seed = snapshot.ts_base_price or snapshot.current_price
    new_base = max(base_seed, snapshot.current_price)

    # Multiplier: pick or tighten.
    new_multiplier = select_atr_multiplier(profit_pct, snapshot.ts_active_multiplier)

    # Candidate stop line.
    if snapshot.atr_value <= 0:
        # ATR not ready yet (warm-up). Activate but no stop yet.
        return TSUpdateResult(
            activate=True,
            new_base_price=new_base,
            new_stop_price=snapshot.ts_stop_price,  # keep previous (or None)
            new_multiplier=new_multiplier,
            reason="ATR_WARMUP",
        )

    candidate = int(round(new_base - snapshot.atr_value * new_multiplier))

    # One-way upward.
    if snapshot.ts_stop_price is None:
        new_stop = candidate
        reason = "INITIAL_TS"
    elif candidate > snapshot.ts_stop_price:
        new_stop = candidate
        reason = "RAISED"
    else:
        new_stop = snapshot.ts_stop_price
        reason = "HELD"

    return TSUpdateResult(
        activate=True,
        new_base_price=new_base,
        new_stop_price=new_stop,
        new_multiplier=new_multiplier,
        reason=reason,
    )


def select_atr_multiplier(
    profit_pct: float, current_multiplier: float | None
) -> float:
    """Pure helper -- pick the right tier without widening.

    Tiers (§5.5):
      +10~15% -> 4.0
      +15~25% -> 3.0
      +25~40% -> 2.5
      +40%~  -> 2.0
      < +10%  -> 4.0 (first tier; treat as initial)

    One-way tightening: ``min(new, current)`` so the multiplier never
    widens after a tightening tick.
    """
    thresholds = V71Constants.ATR_TIER_THRESHOLDS  # (0.10, 0.15, 0.25, 0.40)
    tiers = (
        V71Constants.ATR_MULTIPLIER_TIER_1,  # 4.0
        V71Constants.ATR_MULTIPLIER_TIER_2,  # 3.0
        V71Constants.ATR_MULTIPLIER_TIER_3,  # 2.5
        V71Constants.ATR_MULTIPLIER_TIER_4,  # 2.0
    )

    if profit_pct >= thresholds[3]:
        new = tiers[3]
    elif profit_pct >= thresholds[2]:
        new = tiers[2]
    elif profit_pct >= thresholds[1]:
        new = tiers[1]
    else:
        # +10~15% range OR below +10% (treated as initial tier 1).
        new = tiers[0]

    if current_multiplier is None:
        return new
    return min(new, current_multiplier)


# ---------------------------------------------------------------------------
# Stage after partial exit  --  §5.4
# ---------------------------------------------------------------------------

def stage_after_partial_exit(
    profit_5_executed: bool,
    profit_10_executed: bool,
    weighted_avg_price: int,
) -> int:
    """Recompute fixed_stop_price after a partial exit completes (§5.4).

    Stage 1 (entry .. < +5%):       avg * (1 + STOP_LOSS_INITIAL_PCT)
    Stage 2 (+5% executed):         avg * (1 + STOP_LOSS_AFTER_PROFIT_5)
    Stage 3 (+10% executed):        avg * (1 + STOP_LOSS_AFTER_PROFIT_10)

    One-way upward only -- the caller never passes "downgrade" inputs;
    even if it tried, the math here just returns the higher stage's
    price (caller responsibility to monotonize).
    """
    if weighted_avg_price <= 0:
        raise ValueError("weighted_avg_price must be positive")

    if profit_10_executed:
        pct = V71Constants.STOP_LOSS_AFTER_PROFIT_10  # +0.04
    elif profit_5_executed:
        pct = V71Constants.STOP_LOSS_AFTER_PROFIT_5   # -0.02
    else:
        pct = V71Constants.STOP_LOSS_INITIAL_PCT      # -0.05

    return int(round(weighted_avg_price * (1.0 + pct)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profit_pct(snapshot: PositionSnapshot) -> float:
    """(current - avg) / avg ; 0.0 when avg is degenerate."""
    if snapshot.weighted_avg_price <= 0:
        return 0.0
    return (
        (snapshot.current_price - snapshot.weighted_avg_price)
        / snapshot.weighted_avg_price
    )


__all__ = [
    "PositionSnapshot",
    "EffectiveStopResult",
    "ProfitTakeResult",
    "TSUpdateResult",
    "calculate_effective_stop",
    "evaluate_profit_take",
    "update_trailing_stop",
    "select_atr_multiplier",
    "stage_after_partial_exit",
]
