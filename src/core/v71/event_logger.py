"""EventLogger -- write trade_events / system_events rows.

Spec: docs/v71/03_DATA_MODEL.md §2.4 + §3.1
Implementation: Phase 3 (used everywhere)

Infrastructure module; no feature-flag gate (logging must always work,
including before any V7.1 feature is activated).
"""

from __future__ import annotations


class EventLogger:
    """Single write path for trade_events and system_events.

    Tests can substitute an in-memory implementation; production uses
    SQLAlchemy session injection.
    """

    def __init__(self, db_context: object) -> None:
        raise NotImplementedError("Phase 3 -- see docs/v71/03_DATA_MODEL.md §2.4")
