"""Skill 3: Stop / take-profit / trailing-stop calculator.

Spec: docs/v71/07_SKILLS_SPEC.md §3, docs/v71/02_TRADING_RULES.md §5

Single source of truth for V7.1 exit math. Callers MUST NOT compute
stop ladders, ATR multipliers, or partial-exit thresholds inline --
Harness 3 will block magic literals against the V71Constants tier
values.

Effective stop is always:
  effective_stop = max(fixed_stop, ts_stop_if_valid)
"""

from __future__ import annotations

from dataclasses import dataclass


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
    new_position_status: str  # "PARTIAL_CLOSED" | "CLOSED" | unchanged


@dataclass(frozen=True)
class TSUpdateResult:
    activate: bool
    new_base_price: int | None
    new_stop_price: int | None
    new_multiplier: float | None
    reason: str


def calculate_effective_stop(snapshot: PositionSnapshot) -> EffectiveStopResult:
    """Combine fixed stop and TS into one effective exit line.

    Rules:
      - TS stop is only binding once profit_10_executed is True.
      - Otherwise effective = fixed_stop_price.
      - ``triggered=True`` when current_price <= effective_stop_price.
    """
    raise NotImplementedError("P3.3 -- see docs/v71/07_SKILLS_SPEC.md §3.3")


def evaluate_profit_take(
    snapshot: PositionSnapshot, total_quantity: int
) -> ProfitTakeResult:
    """Decide whether to slice +5% or +10% partial exit (30% each).

    Each level fires at most once per position (idempotent via the
    profit_*_executed flags); +10% is gated on +5% having executed first.
    """
    raise NotImplementedError("P3.3 -- see docs/v71/07_SKILLS_SPEC.md §3.4")


def update_trailing_stop(snapshot: PositionSnapshot) -> TSUpdateResult:
    """Recompute TS BasePrice / stop / multiplier per V7.1 ladder.

    ATR multiplier tier transitions (one-way tightening):
      +10~15% -> 4.0,  +15~25% -> 3.0,  +25~40% -> 2.5,  +40%~ -> 2.0
    Multiplier never widens once tightened.
    """
    raise NotImplementedError("P3.3 -- see docs/v71/07_SKILLS_SPEC.md §3.5")


def select_atr_multiplier(profit_pct: float, current_multiplier: float | None) -> float:
    """Pure helper -- pick the right tier without widening."""
    raise NotImplementedError("P3.3 -- see docs/v71/07_SKILLS_SPEC.md §3.5")


def stage_after_partial_exit(
    profit_5_executed: bool, profit_10_executed: bool, weighted_avg_price: int
) -> int:
    """Recompute fixed_stop_price after a partial exit completes.

    Returns the new fixed_stop_price expressed as an absolute KRW value
    derived from V71Constants.STOP_LOSS_AFTER_PROFIT_{5,10}.
    """
    raise NotImplementedError("P3.3 -- see docs/v71/07_SKILLS_SPEC.md §3.6")


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
