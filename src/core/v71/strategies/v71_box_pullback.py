"""V71BoxPullbackStrategy -- PATH_A 3-min pullback entry.

Spec: docs/v71/02_TRADING_RULES.md §4.1, §4.4
Implementation: P3.2
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71BoxPullbackStrategy:
    """3-min pullback entry: prev bullish + close-in-box, current bullish
    + close-in-box. Buy fires on bar completion.

    Glue between V71BoxEntryDetector and OrderExecutor. Decision
    delegated to box_entry_skill.evaluate_box_entry().
    """

    def __init__(self) -> None:
        require_enabled("v71.pullback_strategy")
        raise NotImplementedError("P3.2 -- see docs/v71/02_TRADING_RULES.md §4.1")
