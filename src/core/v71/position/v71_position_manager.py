"""V71PositionManager -- positions table CRUD + invariants.

Spec: docs/v71/02_TRADING_RULES.md §6, docs/v71/03_DATA_MODEL.md §2.3
Implementation: P3.4
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71PositionManager:
    """All writes to ``positions`` go through this class -- direct
    SQL UPDATEs to weighted_avg_price are forbidden (avg_price_skill
    is the only place that math lives).

    Responsibilities:
      - apply_buy()  -> wraps avg_price_skill.update_position_after_buy
      - apply_sell() -> wraps avg_price_skill.update_position_after_sell
      - persist + emit trade_events row (BUY_EXECUTED / EVENT_RESET / etc)
    """

    def __init__(self, db_context: object) -> None:
        require_enabled("v71.position_v71")
        raise NotImplementedError("P3.4 -- see docs/v71/02_TRADING_RULES.md §6")
