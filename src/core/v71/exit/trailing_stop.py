"""V71TrailingStop -- TS BasePrice + ATR-multiplier ladder state.

Spec: docs/v71/02_TRADING_RULES.md §5.4, §5.5
Implementation: P3.3
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71TrailingStop:
    """Per-position TS state container.

    Activates at +5%; binding for exits only after +10% partial.
    BasePrice = highest high since entry. ATR multiplier ladder is
    one-way tightening (4.0 -> 3.0 -> 2.5 -> 2.0).
    """

    def __init__(self) -> None:
        require_enabled("v71.exit_v71")
        raise NotImplementedError("P3.3 -- see docs/v71/02_TRADING_RULES.md §5.4")
