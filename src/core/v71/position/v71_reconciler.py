"""V71Reconciler -- broker <-> DB position reconciliation.

Spec: docs/v71/02_TRADING_RULES.md §7 + §13
Implementation: P3.5

Used in two contexts:
  - periodic poll (manual-trade detection, scenarios A/B/C/D)
  - post-restart 7-step recovery
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71Reconciler:
    """Wraps reconciliation_skill.reconcile_positions() and persists
    the resulting actions (event log + audit log + notifications).
    """

    def __init__(self, db_context: object, kiwoom_context: object) -> None:
        require_enabled("v71.reconciliation_v71")
        raise NotImplementedError("P3.5 -- see docs/v71/02_TRADING_RULES.md §7")
