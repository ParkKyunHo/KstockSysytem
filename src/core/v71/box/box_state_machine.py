"""Box / tracked_stock state machine.

Spec:
  - 02_TRADING_RULES.md §3.13 (박스 상태 변경)
  - 03_DATA_MODEL.md §2.1 (tracked_stocks.status), §2.2 (support_boxes.status)

Phase: P3.1

State chart (tracked_stocks.status):

    TRACKING ----BOX_REGISTERED-----> BOX_SET
       |                                |
       |                                +--ALL_BOXES_REMOVED--> TRACKING
       |                                |
       |                                +--POSITION_OPENED----> POSITION_OPEN
       |                                |                          |
       |                                |                          +--PARTIAL_EXIT--> POSITION_PARTIAL
       |                                |                          |                       |
       |                                |                          +--FULL_EXIT-->-+      +--PARTIAL_EXIT--> POSITION_PARTIAL (idem)
       |                                |                                          |      |
       +--TRACKING_TERMINATED-----------+----------------------------------------> EXITED <--FULL_EXIT--+

State chart (support_boxes.status, all targets terminal):

    WAITING --BUY_EXECUTED-----------> TRIGGERED
       |---MANUAL_BUY_DETECTED------> INVALIDATED
       |---AUTO_EXIT_BOX_DROP-------> INVALIDATED
       +---USER_DELETED-------------> CANCELLED

Functions are pure: no IO, no DB. Persistence is the caller's responsibility
(box_manager / position_manager).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from src.utils.feature_flags import require_enabled


class TrackedStatus(Enum):
    """Lifecycle of a tracked stock (one path)."""

    TRACKING = "TRACKING"            # registered, no boxes yet
    BOX_SET = "BOX_SET"              # at least one WAITING box
    POSITION_OPEN = "POSITION_OPEN"  # bought, no partial exit yet
    POSITION_PARTIAL = "POSITION_PARTIAL"  # at least one partial exit done
    EXITED = "EXITED"                # terminal, history preserved


class BoxStatus(Enum):
    """Lifecycle of a single support box."""

    WAITING = "WAITING"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class TrackedEvent(Enum):
    """Events that transition a tracked stock."""

    BOX_REGISTERED = "BOX_REGISTERED"
    ALL_BOXES_REMOVED = "ALL_BOXES_REMOVED"
    POSITION_OPENED = "POSITION_OPENED"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    FULL_EXIT = "FULL_EXIT"
    TRACKING_TERMINATED = "TRACKING_TERMINATED"


class BoxEvent(Enum):
    """Events that transition a box (all are terminal targets)."""

    BUY_EXECUTED = "BUY_EXECUTED"
    MANUAL_BUY_DETECTED = "MANUAL_BUY_DETECTED"
    AUTO_EXIT_BOX_DROP = "AUTO_EXIT_BOX_DROP"
    USER_DELETED = "USER_DELETED"


# Transition tables --------------------------------------------------------

_TRACKED_TRANSITIONS: Mapping[TrackedStatus, Mapping[TrackedEvent, TrackedStatus]] = {
    TrackedStatus.TRACKING: {
        TrackedEvent.BOX_REGISTERED: TrackedStatus.BOX_SET,
        TrackedEvent.TRACKING_TERMINATED: TrackedStatus.EXITED,
    },
    TrackedStatus.BOX_SET: {
        TrackedEvent.POSITION_OPENED: TrackedStatus.POSITION_OPEN,
        TrackedEvent.ALL_BOXES_REMOVED: TrackedStatus.TRACKING,
        TrackedEvent.TRACKING_TERMINATED: TrackedStatus.EXITED,
    },
    TrackedStatus.POSITION_OPEN: {
        TrackedEvent.PARTIAL_EXIT: TrackedStatus.POSITION_PARTIAL,
        TrackedEvent.FULL_EXIT: TrackedStatus.EXITED,
    },
    TrackedStatus.POSITION_PARTIAL: {
        # Idempotent: each partial exit keeps us in POSITION_PARTIAL.
        TrackedEvent.PARTIAL_EXIT: TrackedStatus.POSITION_PARTIAL,
        TrackedEvent.FULL_EXIT: TrackedStatus.EXITED,
    },
    TrackedStatus.EXITED: {},  # terminal
}

_BOX_TRANSITIONS: Mapping[BoxStatus, Mapping[BoxEvent, BoxStatus]] = {
    BoxStatus.WAITING: {
        BoxEvent.BUY_EXECUTED: BoxStatus.TRIGGERED,
        BoxEvent.MANUAL_BUY_DETECTED: BoxStatus.INVALIDATED,
        BoxEvent.AUTO_EXIT_BOX_DROP: BoxStatus.INVALIDATED,
        BoxEvent.USER_DELETED: BoxStatus.CANCELLED,
    },
    BoxStatus.TRIGGERED: {},      # terminal
    BoxStatus.INVALIDATED: {},    # terminal
    BoxStatus.CANCELLED: {},      # terminal
}


class IllegalTransitionError(ValueError):
    """Raised when an event is not allowed from the current state."""


# Public API ---------------------------------------------------------------

def transition_tracked_stock(
    current: TrackedStatus, event: TrackedEvent
) -> TrackedStatus:
    """Pure state transition for tracked_stocks.status.

    Args:
        current: current TrackedStatus.
        event:   TrackedEvent that occurred.

    Returns:
        Next TrackedStatus.

    Raises:
        IllegalTransitionError: when ``event`` is not allowed from ``current``.
        TypeError: when args are not the expected enum types.
    """
    require_enabled("v71.box_system")
    _check_type(current, TrackedStatus, "current")
    _check_type(event, TrackedEvent, "event")

    allowed = _TRACKED_TRANSITIONS[current]
    if event not in allowed:
        raise IllegalTransitionError(
            f"Illegal tracked-stock transition: {current.value} "
            f"--[{event.value}]--> ?  "
            f"Allowed events for {current.value}: "
            f"{[e.value for e in allowed] or '(terminal)'}"
        )
    return allowed[event]


def transition_box(current: BoxStatus, event: BoxEvent) -> BoxStatus:
    """Pure state transition for support_boxes.status.

    All non-WAITING states are terminal -- any event from them is rejected.

    Raises:
        IllegalTransitionError: when transition is not allowed.
        TypeError: on wrong arg types.
    """
    require_enabled("v71.box_system")
    _check_type(current, BoxStatus, "current")
    _check_type(event, BoxEvent, "event")

    allowed = _BOX_TRANSITIONS[current]
    if event not in allowed:
        raise IllegalTransitionError(
            f"Illegal box transition: {current.value} "
            f"--[{event.value}]--> ?  "
            f"Allowed events for {current.value}: "
            f"{[e.value for e in allowed] or '(terminal)'}"
        )
    return allowed[event]


def is_tracked_terminal(status: TrackedStatus) -> bool:
    """True if no further transitions are possible from ``status``."""
    return not _TRACKED_TRANSITIONS[status]


def is_box_terminal(status: BoxStatus) -> bool:
    """True if no further transitions are possible from ``status``."""
    return not _BOX_TRANSITIONS[status]


def allowed_tracked_events(current: TrackedStatus) -> tuple[TrackedEvent, ...]:
    """List of events legal from ``current`` (empty tuple if terminal)."""
    return tuple(_TRACKED_TRANSITIONS[current].keys())


def allowed_box_events(current: BoxStatus) -> tuple[BoxEvent, ...]:
    """List of events legal from ``current`` (empty tuple if terminal)."""
    return tuple(_BOX_TRANSITIONS[current].keys())


# Helpers ------------------------------------------------------------------

def _check_type(value: object, expected: type, name: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(
            f"{name} must be {expected.__name__}, got {type(value).__name__}"
        )


__all__ = [
    "TrackedStatus",
    "BoxStatus",
    "TrackedEvent",
    "BoxEvent",
    "IllegalTransitionError",
    "transition_tracked_stock",
    "transition_box",
    "is_tracked_terminal",
    "is_box_terminal",
    "allowed_tracked_events",
    "allowed_box_events",
]
