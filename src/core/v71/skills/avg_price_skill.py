"""Skill 4: Weighted-average price + event reset on adds.

Spec:
  - 02_TRADING_RULES.md §6  (average-price management)
  - 07_SKILLS_SPEC.md §4

Phase: P3.4

Constitution: never assign ``position.weighted_avg_price = ...`` from
business code. Always go through :func:`update_position_after_buy` or
:func:`update_position_after_sell`. Harness 3 will block the bare
attribute write once the rule lands.

§6 core rules (must hold):
  - first buy:  avg = buy_price; initial_avg = buy_price; events fresh
  - add buy:    new_avg = (qty*avg + new_qty*new_price) / total_qty
                profit_5_executed -> False
                profit_10_executed -> False
                fixed_stop_price -> avg * (1 + STOP_LOSS_INITIAL_PCT) (stage 1)
                ts_base_price preserved (highest-high history kept)
                initial_avg_price preserved
  - sell:       avg unchanged; only total_quantity decreases
                event flags preserved (profit_5_executed stays True etc.)
                fixed_stop_price unchanged here -- caller advances the
                ladder via stage_after_partial_exit() if appropriate

This skill is pure (no IO, no V71 state mutation). Application of the
returned :class:`PositionUpdate` to the live :class:`PositionState` is
:class:`V71PositionManager`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.v71.position.state import PositionState
from src.core.v71.v71_constants import V71Constants

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionUpdate:
    """Result of a buy/sell -- pure data, caller persists it.

    Mirrors :class:`PositionState` fields plus an ``events_reset`` flag
    so callers (e.g. notification layer) can highlight the §6 reset to
    the user.
    """

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
    """True when a buy triggered the §6 event reset (i.e. add-buy)."""


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------

def compute_weighted_average(
    existing_qty: int, existing_avg: int, new_qty: int, new_price: int
) -> int:
    """Pure helper -- ``(existing_qty*existing_avg + new_qty*new_price) / total``.

    Returns an integer KRW value (rounded half-to-even via :func:`round`).

    Raises:
        ValueError: on non-positive prices, negative quantities, or
            empty total.
    """
    if existing_qty < 0 or new_qty < 0:
        raise ValueError("quantities must be non-negative")
    if existing_avg < 0 or new_price <= 0:
        raise ValueError("prices must be non-negative / new_price positive")
    total = existing_qty + new_qty
    if total <= 0:
        raise ValueError("total quantity must be positive")
    if existing_qty == 0:
        return new_price  # first buy
    return int(round((existing_qty * existing_avg + new_qty * new_price) / total))


# ---------------------------------------------------------------------------
# Buy
# ---------------------------------------------------------------------------

def update_position_after_buy(
    state: PositionState,
    buy_price: int,
    buy_quantity: int,
) -> PositionUpdate:
    """Apply a buy and recompute weighted avg + event reset (§6.2).

    Branching:
      - state.total_quantity == 0  -> first buy (initial_avg = buy_price,
        events stay False which is the intended default; events_reset = False
        because there is nothing to reset)
      - state.total_quantity > 0   -> add buy (PYRAMID / MANUAL_PYRAMID):
        weighted average + force events to False + reset ladder to stage 1.
        ts_base_price + initial_avg_price preserved (§6.2).
    """
    if buy_quantity <= 0:
        raise ValueError("buy_quantity must be positive")
    if buy_price <= 0:
        raise ValueError("buy_price must be positive")

    is_first_buy = state.total_quantity == 0

    if is_first_buy:
        new_avg = buy_price
        new_initial = buy_price
        events_reset = False
        new_p5 = state.profit_5_executed  # already False per default
        new_p10 = state.profit_10_executed
    else:
        new_avg = compute_weighted_average(
            state.total_quantity, state.weighted_avg_price,
            buy_quantity, buy_price,
        )
        new_initial = state.initial_avg_price  # preserved
        events_reset = True
        new_p5 = False  # §6.2 reset
        new_p10 = False

    new_total = state.total_quantity + buy_quantity

    # §6.2 stop ladder reset to stage 1 on add-buy.
    new_fixed_stop = int(
        round(new_avg * (1.0 + V71Constants.STOP_LOSS_INITIAL_PCT))
    )

    return PositionUpdate(
        weighted_avg_price=new_avg,
        initial_avg_price=new_initial,
        total_quantity=new_total,
        fixed_stop_price=new_fixed_stop,
        profit_5_executed=new_p5,
        profit_10_executed=new_p10,
        ts_activated=state.ts_activated,
        ts_base_price=state.ts_base_price,         # preserved (§6.2)
        ts_stop_price=state.ts_stop_price,         # preserved
        ts_active_multiplier=state.ts_active_multiplier,
        events_reset=events_reset,
    )


# ---------------------------------------------------------------------------
# Sell
# ---------------------------------------------------------------------------

def update_position_after_sell(
    state: PositionState,
    sell_quantity: int,
) -> PositionUpdate:
    """Apply a sell -- avg price unchanged, only quantity decreases (§6.4).

    Event flags (``profit_5_executed`` etc.) are NOT touched here. The
    caller decides whether to advance the stop ladder via
    :func:`exit_calc_skill.stage_after_partial_exit` based on the type
    of sell (profit-take vs stop loss).
    """
    if sell_quantity <= 0:
        raise ValueError("sell_quantity must be positive")
    if sell_quantity > state.total_quantity:
        raise ValueError(
            f"sell_quantity {sell_quantity} exceeds total {state.total_quantity}"
        )

    new_total = state.total_quantity - sell_quantity

    return PositionUpdate(
        weighted_avg_price=state.weighted_avg_price,  # unchanged (§6.4)
        initial_avg_price=state.initial_avg_price,
        total_quantity=new_total,
        fixed_stop_price=state.fixed_stop_price,      # caller may advance
        profit_5_executed=state.profit_5_executed,    # preserved
        profit_10_executed=state.profit_10_executed,
        ts_activated=state.ts_activated,
        ts_base_price=state.ts_base_price,
        ts_stop_price=state.ts_stop_price,
        ts_active_multiplier=state.ts_active_multiplier,
        events_reset=False,
    )


__all__ = [
    "PositionUpdate",
    "compute_weighted_average",
    "update_position_after_buy",
    "update_position_after_sell",
]
