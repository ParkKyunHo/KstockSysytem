"""Box / tracked_stock state machine.

Spec: docs/v71/02_TRADING_RULES.md §3.10, docs/v71/03_DATA_MODEL.md §2.1
Implementation: P3.1

States (tracked_stocks.status):
  TRACKING -> BOX_SET -> POSITION_OPEN -> POSITION_PARTIAL -> EXITED

Box transitions (support_boxes.status):
  WAITING -> TRIGGERED | INVALIDATED | CANCELLED
"""

from __future__ import annotations

from enum import Enum

from src.utils.feature_flags import require_enabled


class TrackedStatus(Enum):
    TRACKING = "TRACKING"
    BOX_SET = "BOX_SET"
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_PARTIAL = "POSITION_PARTIAL"
    EXITED = "EXITED"


class BoxStatus(Enum):
    WAITING = "WAITING"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


def transition_tracked_stock(
    current: TrackedStatus, event: str
) -> TrackedStatus:
    """Pure state transition. Raises ValueError on illegal transitions."""
    require_enabled("v71.box_system")
    raise NotImplementedError("P3.1 -- see docs/v71/03_DATA_MODEL.md §2.1")


def transition_box(current: BoxStatus, event: str) -> BoxStatus:
    """Pure state transition. Raises ValueError on illegal transitions."""
    require_enabled("v71.box_system")
    raise NotImplementedError("P3.1 -- see docs/v71/03_DATA_MODEL.md §2.2")


__all__ = [
    "TrackedStatus",
    "BoxStatus",
    "transition_tracked_stock",
    "transition_box",
]
