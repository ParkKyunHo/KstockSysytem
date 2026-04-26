"""V71BoxBreakoutStrategy -- PATH_A 3-min breakout entry.

Spec: docs/v71/02_TRADING_RULES.md §4.2, §4.4
Implementation: P3.2
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71BoxBreakoutStrategy:
    """3-min breakout entry: close > box.upper, bullish, open >= box.lower
    (excludes gap-ups). Buy fires on bar completion.
    """

    def __init__(self) -> None:
        require_enabled("v71.breakout_strategy")
        raise NotImplementedError("P3.2 -- see docs/v71/02_TRADING_RULES.md §4.2")
