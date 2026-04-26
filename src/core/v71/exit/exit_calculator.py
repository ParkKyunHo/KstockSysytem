"""V71ExitCalculator -- per-tick exit decision orchestrator.

Spec: docs/v71/02_TRADING_RULES.md §5
Implementation: P3.3
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71ExitCalculator:
    """For each price update, computes:
      - effective stop (calculate_effective_stop)
      - partial-exit eligibility (evaluate_profit_take)
      - TS state delta (update_trailing_stop)

    Pure decisions; emission goes through V71ExitExecutor.
    """

    def __init__(self) -> None:
        require_enabled("v71.exit_v71")
        raise NotImplementedError("P3.3 -- see docs/v71/02_TRADING_RULES.md §5")
