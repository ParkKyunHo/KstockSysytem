"""V71BoxBreakoutStrategy -- BREAKOUT box construction helper.

Spec:
  - 02_TRADING_RULES.md §3.2 (PATH_A breakout)
  - 02_TRADING_RULES.md §3.11 (PATH_B breakout + 09:05 fallback)
  - 02_TRADING_RULES.md §4   (buy execution)
  - 04_ARCHITECTURE.md §5.3
  - 05_MIGRATION_PLAN.md §5.3

Phase: P3.2

Why this module is thin:
    The actual breakout condition logic lives in
    :func:`box_entry_skill.evaluate_box_entry` (single point of truth,
    per Constitution 3 + Harness 3). Order placement lives in
    :class:`V71BuyExecutor`. This class only:
      * pins ``strategy_type="BREAKOUT"`` when constructing boxes
      * gates on the dedicated feature flag (``v71.breakout_strategy``)
"""

from __future__ import annotations

from src.core.v71.box.box_manager import BoxRecord, V71BoxManager
from src.core.v71.skills.box_entry_skill import PathType
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled


class V71BoxBreakoutStrategy:
    """BREAKOUT strategy factory + flag gate."""

    STRATEGY: str = "BREAKOUT"

    def __init__(self, *, box_manager: V71BoxManager) -> None:
        require_enabled("v71.breakout_strategy")
        self._box_manager = box_manager

    async def create_box(
        self,
        *,
        tracked_stock_id: str,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        path_type: PathType,
        stop_loss_pct: float = V71Constants.STOP_LOSS_INITIAL_PCT,
        memo: str | None = None,
    ) -> BoxRecord:
        """Create a BREAKOUT box on the underlying box manager."""
        return await self._box_manager.create_box(
            tracked_stock_id=tracked_stock_id,
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            strategy_type=self.STRATEGY,  # type: ignore[arg-type]
            path_type=path_type,
            stop_loss_pct=stop_loss_pct,
            memo=memo,
        )


__all__ = ["V71BoxBreakoutStrategy"]
