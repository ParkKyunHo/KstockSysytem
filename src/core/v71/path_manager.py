"""PathManager -- routes signal flow between PATH_A (3min) and PATH_B (daily).

Spec: docs/v71/02_TRADING_RULES.md §4.3, §6 (dual-path positions)
Implementation: P3.2 (PATH_A wired) / P3.7 (PATH_B daily scheduler)
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class PathManager:
    """Decides which timeframe + entry strategy fires for a given
    tracked_stock, given its path_type ENUM.

    PATH_A:  3-min candle completion -> immediate buy
    PATH_B:  daily candle completion -> queue for 09:01 next day buy,
             abort if next-day open gaps >= 5%
    """

    def __init__(self) -> None:
        require_enabled("v71.box_system")
        raise NotImplementedError("P3.2 -- see docs/v71/02_TRADING_RULES.md §4.3")
