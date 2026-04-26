"""AuditScheduler -- monthly review + box expiry reminder timer.

Spec: docs/v71/02_TRADING_RULES.md §3.13 (expiry reminder),
      docs/v71/02_TRADING_RULES.md §9 (monthly review notification)
Implementation: Phase 4
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class AuditScheduler:
    """Periodic background tasks:
      - daily 15:30 -- daily summary notification (LOW)
      - monthly 1st -- generate monthly_reviews row + LOW notification
      - on demand  -- detect WAITING boxes >= 30 days and send MEDIUM
                     reminder (never auto-delete)
    """

    def __init__(self, db_context: object) -> None:
        require_enabled("v71.monthly_review")
        raise NotImplementedError("Phase 4 -- see docs/v71/02_TRADING_RULES.md §3.13")
