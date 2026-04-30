"""V71BoxPullbackStrategy -- PULLBACK box construction helper.

Spec:
  - 02_TRADING_RULES.md §3.2 (PATH_A pullback)
  - 02_TRADING_RULES.md §3.10 (PATH_B pullback + 09:05 fallback)
  - 02_TRADING_RULES.md §4   (buy execution)
  - 04_ARCHITECTURE.md §5.3
  - 05_MIGRATION_PLAN.md §5.3

Phase: P3.2

Why this module is thin:
    The actual pullback condition logic lives in
    :func:`box_entry_skill.evaluate_box_entry` (single point of truth, per
    Constitution 3 + Harness 3). The dispatch / sequencing logic lives in
    :class:`V71BuyExecutor` (one path-aware coordinator).

    What's left for a "Pullback Strategy" object is only:
      * a factory that builds a PULLBACK :class:`BoxRecord` correctly
      * type-pinning convenience for code that wants to talk about
        "the pullback strategy" explicitly

The class therefore exposes a single :meth:`create_box` and reuses the
existing V71BoxManager underneath. A separate Feature Flag
(``v71.pullback_strategy``) lets operators disable PULLBACK boxes
without touching the rest of the box system.
"""

from __future__ import annotations

from src.core.v71.box.box_manager import BoxRecord, V71BoxManager
from src.core.v71.skills.box_entry_skill import PathType
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled


class V71BoxPullbackStrategy:
    """PULLBACK strategy factory + flag gate.

    Decision: every PULLBACK entry goes through
    :func:`box_entry_skill.evaluate_box_entry`. Order placement: every
    PULLBACK fill goes through :class:`V71BuyExecutor`. This class is
    glue that ensures boxes flagged ``PULLBACK`` are constructed under
    the dedicated feature flag.
    """

    STRATEGY: str = "PULLBACK"

    def __init__(self, *, box_manager: V71BoxManager) -> None:
        require_enabled("v71.pullback_strategy")
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
        """Create a PULLBACK box on the underlying box manager.

        Same validation/overlap/cap logic as
        :meth:`V71BoxManager.create_box` -- this wrapper just pins
        ``strategy_type="PULLBACK"`` so callers cannot accidentally
        register a BREAKOUT box through the pullback strategy.
        """
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


__all__ = ["V71BoxPullbackStrategy"]
