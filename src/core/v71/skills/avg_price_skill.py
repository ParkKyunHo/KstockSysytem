"""Skill 4: Weighted-average price + event reset on adds.

Spec: docs/v71/07_SKILLS_SPEC.md §4, docs/v71/02_TRADING_RULES.md §6

Constitution: never assign ``position.weighted_avg_price = ...`` from
business code. Always go through :func:`update_position_after_buy` or
:func:`update_position_after_sell`. Harness 3 will block the bare
attribute write once the rule lands.

Event reset rule (CRITICAL):
  On any buy that increases total_quantity, profit_5_executed and
  profit_10_executed are reset to False, fixed_stop_price falls back to
  weighted_avg_price * (1 + STOP_LOSS_INITIAL_PCT). ts_base_price is
  preserved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionState:
    """Pure snapshot the skill operates on."""

    weighted_avg_price: int
    initial_avg_price: int
    total_quantity: int
    fixed_stop_price: int
    profit_5_executed: bool
    profit_10_executed: bool
    ts_activated: bool
    ts_base_price: int | None
    ts_stop_price: int | None
    ts_active_multiplier: float | None


@dataclass(frozen=True)
class PositionUpdate:
    """Result of a buy/sell -- pure data, caller persists it."""

    weighted_avg_price: int
    initial_avg_price: int
    total_quantity: int
    fixed_stop_price: int
    profit_5_executed: bool
    profit_10_executed: bool
    ts_activated: bool
    ts_base_price: int | None
    ts_stop_price: int | None
    ts_active_multiplier: float | None
    events_reset: bool
    """True when a buy triggered the §6 event reset."""


def update_position_after_buy(
    state: PositionState,
    buy_price: int,
    buy_quantity: int,
) -> PositionUpdate:
    """Apply a buy and recompute weighted avg + event reset.

    Formula:
        new_avg = (qty * avg + new_qty * new_price) / (qty + new_qty)

    Side effects encoded in the returned PositionUpdate:
      - profit_5_executed / profit_10_executed -> False
      - fixed_stop_price -> new_avg * (1 + STOP_LOSS_INITIAL_PCT)
      - ts_base_price preserved
      - initial_avg_price preserved
    """
    raise NotImplementedError("P3.4 -- see docs/v71/07_SKILLS_SPEC.md §4.3")


def update_position_after_sell(
    state: PositionState,
    sell_quantity: int,
) -> PositionUpdate:
    """Apply a sell -- avg price unchanged, only quantity decreases.

    Event flags (profit_5_executed etc.) are NOT reset on sell.
    Returns CLOSED-equivalent state when total_quantity reaches 0.
    """
    raise NotImplementedError("P3.4 -- see docs/v71/07_SKILLS_SPEC.md §4.4")


def compute_weighted_average(
    existing_qty: int, existing_avg: int, new_qty: int, new_price: int
) -> int:
    """Pure helper for tests."""
    raise NotImplementedError("P3.4 -- see docs/v71/07_SKILLS_SPEC.md §4.2")


__all__ = [
    "PositionState",
    "PositionUpdate",
    "update_position_after_buy",
    "update_position_after_sell",
    "compute_weighted_average",
]
