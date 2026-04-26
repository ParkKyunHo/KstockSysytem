"""V71BoxEntryDetector -- bar-completion entry checks.

Spec: docs/v71/02_TRADING_RULES.md §4, docs/v71/04_ARCHITECTURE.md §5.3
Implementation: P3.1 / P3.2
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71BoxEntryDetector:
    """Subscribes to candle-completion events and runs box-entry checks
    via :func:`box_entry_skill.evaluate_box_entry`.

    Responsibilities (P3.2):
      - receive completed Candle from CandleManager
      - look up active WAITING boxes for the stock+path
      - call evaluate_box_entry() -- never re-implements conditions
      - on positive decision: hand off to OrderExecutor
    """

    def __init__(self, candle_manager: object, box_manager: object) -> None:
        require_enabled("v71.box_system")
        raise NotImplementedError("P3.2 -- see docs/v71/02_TRADING_RULES.md §4")
