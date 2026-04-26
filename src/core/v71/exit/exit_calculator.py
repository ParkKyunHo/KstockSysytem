"""V71ExitCalculator -- per-tick exit decision orchestrator.

Spec:
  - 02_TRADING_RULES.md §5
  - 04_ARCHITECTURE.md §5.3

Phase: P3.3

Pure decision layer: combines the two exit-skill calls
(:func:`calculate_effective_stop` and :func:`evaluate_profit_take`) into
a single :class:`ExitDecision`. The actual order placement is the job
of :class:`V71ExitExecutor`.

Calling pattern (typical wiring, P3.5 will plumb the orchestrator):

    @on_tick(stock_code)
    def handle(price):
        decision = calculator.on_tick(position, price, atr_value)
        if decision.stop_triggered:
            await executor.execute_stop_loss(position)
        elif decision.profit_take.should_exit:
            await executor.execute_profit_take(
                position, decision.profit_take
            )
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.v71.position.state import PositionState
from src.core.v71.skills.exit_calc_skill import (
    EffectiveStopResult,
    PositionSnapshot,
    ProfitTakeResult,
    calculate_effective_stop,
    evaluate_profit_take,
)
from src.utils.feature_flags import require_enabled


@dataclass(frozen=True)
class ExitDecision:
    """Aggregated read-only output of one tick.

    The caller routes:
      - ``stop_triggered`` -> :meth:`V71ExitExecutor.execute_stop_loss` or
        ``execute_ts_exit`` depending on ``effective_stop.source``
      - ``profit_take.should_exit`` -> ``execute_profit_take``
    """

    stop_triggered: bool
    profit_take: ProfitTakeResult
    effective_stop: EffectiveStopResult


class V71ExitCalculator:
    """Stateless per-tick evaluator (one instance shared)."""

    def __init__(self) -> None:
        require_enabled("v71.exit_v71")

    def on_tick(
        self,
        position: PositionState,
        current_price: int,
        atr_value: float,
    ) -> ExitDecision:
        """Compute the exit decision without mutating state."""
        snapshot = _snapshot(position, current_price, atr_value)
        effective = calculate_effective_stop(snapshot)
        profit_take = evaluate_profit_take(snapshot, position.total_quantity)
        return ExitDecision(
            stop_triggered=effective.triggered,
            profit_take=profit_take,
            effective_stop=effective,
        )


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


__all__ = ["ExitDecision", "V71ExitCalculator"]
