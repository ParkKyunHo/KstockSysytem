"""V71BoxManager -- box CRUD + overlap validation + 30-day expiry.

Spec: docs/v71/02_TRADING_RULES.md §3, docs/v71/04_ARCHITECTURE.md §5.3
Implementation: P3.1
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71BoxManager:
    """Owns the lifecycle of ``support_boxes`` rows.

    Responsibilities (P3.1):
      - create_box(): insert with overlap validation against active boxes
        on the same tracked_stock; CHECK constraints enforce price/size/stop
      - mark_triggered() / mark_invalidated() / mark_cancelled():
        drive the box_status state machine
      - check_30day_expiry(): emit MEDIUM notification when a WAITING
        box has been quiet for 30 days; never auto-delete (PRD §3)
      - validate_no_overlap(): pure helper used by create_box()
    """

    def __init__(self, db_context: object) -> None:
        require_enabled("v71.box_system")
        raise NotImplementedError("P3.1 -- see docs/v71/02_TRADING_RULES.md §3")
