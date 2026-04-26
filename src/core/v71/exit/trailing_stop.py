"""V71TrailingStop -- TS BasePrice + ATR-multiplier ladder applicator.

Spec:
  - 02_TRADING_RULES.md §5.5 (BasePrice + multiplier ladder)
  - 07_SKILLS_SPEC.md §3.5

Phase: P3.3

The math lives in
:func:`src.core.v71.skills.exit_calc_skill.update_trailing_stop`. This
module is the *applicator* -- it owns no state; given a
:class:`PositionState` and the latest price/ATR, it calls the skill and
writes the new TS values back into the position in-place.
"""

from __future__ import annotations

from src.core.v71.position.state import PositionState
from src.core.v71.skills.exit_calc_skill import (
    PositionSnapshot,
    TSUpdateResult,
    update_trailing_stop,
)
from src.utils.feature_flags import require_enabled


class V71TrailingStop:
    """Stateless TS applicator (one instance shared across all positions)."""

    def __init__(self) -> None:
        require_enabled("v71.exit_v71")

    def on_bar_complete(
        self,
        position: PositionState,
        current_price: int,
        atr_value: float,
    ) -> TSUpdateResult:
        """Recompute TS state and apply to ``position`` in-place.

        Returns the raw :class:`TSUpdateResult` so the caller (typically
        V71ExitCalculator) can log / decide.
        """
        snapshot = _snapshot(position, current_price, atr_value)
        result = update_trailing_stop(snapshot)
        if result.activate:
            position.ts_activated = True
            if result.new_base_price is not None:
                position.ts_base_price = result.new_base_price
            if result.new_stop_price is not None:
                position.ts_stop_price = result.new_stop_price
            if result.new_multiplier is not None:
                position.ts_active_multiplier = result.new_multiplier
        return result


def _snapshot(
    position: PositionState, current_price: int, atr_value: float
) -> PositionSnapshot:
    return PositionSnapshot(
        weighted_avg_price=position.weighted_avg_price,
        initial_avg_price=position.initial_avg_price,
        fixed_stop_price=position.fixed_stop_price,
        profit_5_executed=position.profit_5_executed,
        profit_10_executed=position.profit_10_executed,
        ts_activated=position.ts_activated,
        ts_base_price=position.ts_base_price,
        ts_stop_price=position.ts_stop_price,
        ts_active_multiplier=position.ts_active_multiplier,
        current_price=current_price,
        atr_value=atr_value,
    )


__all__ = ["V71TrailingStop"]
