"""V71BoxManager -- box CRUD + overlap validation + 30-day expiry.

Spec:
  - 02_TRADING_RULES.md §3.1   (Box definition)
  - 02_TRADING_RULES.md §3.4   (Constraints)
  - 02_TRADING_RULES.md §3.6   (Modification policy)
  - 02_TRADING_RULES.md §3.7   (30-day reminder, no auto-delete)
  - 02_TRADING_RULES.md §3.13  (Box status lifecycle)
  - 03_DATA_MODEL.md §2.2      (support_boxes)

Phase: P3.1

Storage:
    P3.1 keeps boxes in an in-memory dict (UUID -> BoxRecord). DB persistence
    is wired in later phases (P3.4 V71PositionManager, P3.5 V71Reconciler).
    Keeping the manager pure-Python now lets us pin the rules without a DB.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.core.v71.box.box_state_machine import (
    BoxEvent,
    BoxStatus,
    transition_box,
)
from src.core.v71.skills.box_entry_skill import PathType, StrategyType
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

# ---------------------------------------------------------------------------
# Box record (mirrors support_boxes row)
# ---------------------------------------------------------------------------

@dataclass
class BoxRecord:
    """In-memory box record -- mirrors a ``support_boxes`` row.

    Mutable: state transitions modify ``status`` and timestamps.
    """

    id: str
    tracked_stock_id: str
    box_tier: int
    upper_price: int
    lower_price: int
    position_size_pct: float    # 0 < x <= 100, percent of total capital
    stop_loss_pct: float        # < 0 (e.g. -0.05)
    strategy_type: StrategyType
    path_type: PathType
    status: BoxStatus = BoxStatus.WAITING
    memo: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    triggered_at: datetime | None = None
    invalidated_at: datetime | None = None
    last_reminder_at: datetime | None = None
    invalidation_reason: str | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class BoxValidationError(ValueError):
    """Box-level CHECK violation (price/size/stop)."""


class BoxOverlapError(ValueError):
    """New box overlaps an existing WAITING box on the same (stock, path)."""


class BoxModificationError(ValueError):
    """Modification rejected (e.g., editing a TRIGGERED box)."""


class BoxNotFoundError(KeyError):
    """No box with the given id."""


# ---------------------------------------------------------------------------
# V71BoxManager
# ---------------------------------------------------------------------------

class V71BoxManager:
    """Owns the lifecycle of ``support_boxes`` rows.

    P3.1 stores everything in-memory (no DB). Callers pass an
    ``on_orphan_cancel`` to :meth:`delete_box` to wire pending-order
    cancellation in later phases (no implicit globals).
    """

    def __init__(self) -> None:
        require_enabled("v71.box_system")
        self._boxes: dict[str, BoxRecord] = {}
        # Index: tracked_stock_id -> set of box ids (cheap lookup).
        self._by_tracked: dict[str, set[str]] = {}

    # -- create / modify / delete ----------------------------------------

    def create_box(
        self,
        *,
        tracked_stock_id: str,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        strategy_type: StrategyType,
        path_type: PathType,
        stop_loss_pct: float = V71Constants.STOP_LOSS_INITIAL_PCT,
        memo: str | None = None,
    ) -> BoxRecord:
        """Validate + insert a new box. Returns the created record.

        Raises:
            BoxValidationError: CHECK violations (price/size/stop).
            BoxOverlapError: overlap with an existing WAITING box on the
                same ``(tracked_stock_id, path_type)`` group.
        """
        self._validate_box_fields(
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
        )
        # Overlap is checked only against same-path WAITING siblings (§3.4).
        siblings = self._waiting_boxes_for_tracked(tracked_stock_id, path_type)
        if not self.validate_no_overlap(siblings, upper_price, lower_price):
            raise BoxOverlapError(
                f"Box [{lower_price}~{upper_price}] overlaps an existing "
                f"WAITING box on tracked_stock={tracked_stock_id} path={path_type}"
            )

        record = BoxRecord(
            id=str(uuid.uuid4()),
            tracked_stock_id=tracked_stock_id,
            box_tier=self._next_tier(tracked_stock_id, path_type),
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            strategy_type=strategy_type,
            path_type=path_type,
            memo=memo,
        )
        self._boxes[record.id] = record
        self._by_tracked.setdefault(tracked_stock_id, set()).add(record.id)
        return record

    def modify_box(
        self,
        box_id: str,
        *,
        upper_price: int | None = None,
        lower_price: int | None = None,
        position_size_pct: float | None = None,
        stop_loss_pct: float | None = None,
        memo: str | None = None,
        force_relax_stop: bool = False,
    ) -> BoxRecord:
        """Modify a WAITING box's fields.

        Non-WAITING boxes are immutable (§3.6).

        Args:
            force_relax_stop: must be True if the new ``stop_loss_pct`` is
                more lenient (lower / further-from-zero) than the current
                value -- corresponds to the §3.6 "loosen warning" check.
        """
        record = self._get(box_id)
        if record.status is not BoxStatus.WAITING:
            raise BoxModificationError(
                f"Cannot modify box {box_id} in status {record.status.value}"
            )

        new_upper = upper_price if upper_price is not None else record.upper_price
        new_lower = lower_price if lower_price is not None else record.lower_price
        new_size = (
            position_size_pct
            if position_size_pct is not None
            else record.position_size_pct
        )
        new_stop = stop_loss_pct if stop_loss_pct is not None else record.stop_loss_pct

        self._validate_box_fields(
            upper_price=new_upper,
            lower_price=new_lower,
            position_size_pct=new_size,
            stop_loss_pct=new_stop,
        )

        # Stop-loss relaxation guard (§3.6). Tightening (-5% -> -3%) is fine,
        # loosening (-5% -> -7%) needs explicit confirmation.
        if new_stop < record.stop_loss_pct - 1e-9 and not force_relax_stop:
            raise BoxModificationError(
                f"stop_loss_pct relaxed from {record.stop_loss_pct} to {new_stop}; "
                "pass force_relax_stop=True to confirm (UI must show warning)."
            )

        if upper_price is not None or lower_price is not None:
            siblings = [
                b
                for b in self._waiting_boxes_for_tracked(
                    record.tracked_stock_id, record.path_type
                )
                if b.id != box_id
            ]
            if not self.validate_no_overlap(siblings, new_upper, new_lower):
                raise BoxOverlapError(
                    "Modified prices overlap a sibling WAITING box"
                )

        record.upper_price = new_upper
        record.lower_price = new_lower
        record.position_size_pct = new_size
        record.stop_loss_pct = new_stop
        if memo is not None:
            record.memo = memo
        record.modified_at = datetime.now()
        return record

    def delete_box(
        self,
        box_id: str,
        *,
        on_orphan_cancel: Callable[[str], None] | None = None,
    ) -> BoxRecord:
        """Cancel a WAITING box (status -> CANCELLED).

        TRIGGERED / INVALIDATED / CANCELLED boxes cannot be deleted.

        Args:
            on_orphan_cancel: callback invoked with ``box_id`` so callers
                can cancel any pending exchange order tied to this box
                (P3.2 will wire OrderExecutor here).
        """
        record = self._get(box_id)
        if record.status is not BoxStatus.WAITING:
            raise BoxModificationError(
                f"Cannot delete box {box_id} in status {record.status.value}"
            )
        record.status = transition_box(record.status, BoxEvent.USER_DELETED)
        record.modified_at = datetime.now()
        record.invalidation_reason = "USER_DELETED"
        if on_orphan_cancel is not None:
            on_orphan_cancel(box_id)
        return record

    # -- state transitions ----------------------------------------------

    def mark_triggered(self, box_id: str) -> BoxRecord:
        """Mark a WAITING box as TRIGGERED after a buy executes."""
        record = self._get(box_id)
        record.status = transition_box(record.status, BoxEvent.BUY_EXECUTED)
        record.triggered_at = datetime.now()
        record.modified_at = record.triggered_at
        return record

    def mark_invalidated(self, box_id: str, *, reason: str) -> BoxRecord:
        """Mark a WAITING box as INVALIDATED.

        Args:
            reason: one of ``"MANUAL_BUY_DETECTED"`` (Scenario C, §7) or
                ``"AUTO_EXIT_BOX_DROP"`` (-20% drop, §3.4).
        """
        if reason not in {"MANUAL_BUY_DETECTED", "AUTO_EXIT_BOX_DROP"}:
            raise ValueError(
                f"reason must be MANUAL_BUY_DETECTED or AUTO_EXIT_BOX_DROP; "
                f"got {reason!r}"
            )
        event = (
            BoxEvent.MANUAL_BUY_DETECTED
            if reason == "MANUAL_BUY_DETECTED"
            else BoxEvent.AUTO_EXIT_BOX_DROP
        )
        record = self._get(box_id)
        record.status = transition_box(record.status, event)
        record.invalidated_at = datetime.now()
        record.modified_at = record.invalidated_at
        record.invalidation_reason = reason
        return record

    # -- queries ---------------------------------------------------------

    def get(self, box_id: str) -> BoxRecord:
        return self._get(box_id)

    def list_for_tracked(self, tracked_stock_id: str) -> list[BoxRecord]:
        ids = self._by_tracked.get(tracked_stock_id, set())
        return [self._boxes[i] for i in ids]

    def list_waiting_for_tracked(
        self, tracked_stock_id: str, path_type: PathType
    ) -> list[BoxRecord]:
        return self._waiting_boxes_for_tracked(tracked_stock_id, path_type)

    # -- 30-day expiry (§3.7) -------------------------------------------

    def check_30day_expiry(
        self, *, now: datetime | None = None
    ) -> list[BoxRecord]:
        """Return WAITING boxes due for a 30-day reminder.

        Reminder is due when the box has been WAITING for at least
        ``BOX_EXPIRY_REMINDER_DAYS`` days since either creation or the
        previous reminder. Callers must emit the notification AND call
        :meth:`mark_reminded` to record the send (otherwise the same boxes
        will keep showing up).
        """
        now = now or datetime.now()
        threshold = timedelta(days=V71Constants.BOX_EXPIRY_REMINDER_DAYS)
        due: list[BoxRecord] = []
        for box in self._boxes.values():
            if box.status is not BoxStatus.WAITING:
                continue
            anchor = box.last_reminder_at or box.created_at
            if now - anchor >= threshold:
                due.append(box)
        return due

    def mark_reminded(
        self, box_id: str, *, when: datetime | None = None
    ) -> BoxRecord:
        record = self._get(box_id)
        record.last_reminder_at = when or datetime.now()
        return record

    # -- overlap helper (pure) ------------------------------------------

    @staticmethod
    def validate_no_overlap(
        existing: Iterable[BoxRecord],
        new_upper: int,
        new_lower: int,
    ) -> bool:
        """True iff ``[new_lower, new_upper]`` does not intersect any
        existing box's ``[lower, upper]`` interval.

        Overlap (§3.4): ``a.upper > b.lower AND a.lower < b.upper``.

        Boundary (e.g., ``a.upper == b.lower``) is NOT an overlap -- prices
        are strict bounds in this rule.
        """
        for box in existing:
            if new_upper > box.lower_price and new_lower < box.upper_price:
                return False
        return True

    # -- internal -------------------------------------------------------

    def _waiting_boxes_for_tracked(
        self, tracked_stock_id: str, path_type: PathType
    ) -> list[BoxRecord]:
        ids = self._by_tracked.get(tracked_stock_id, set())
        return [
            self._boxes[i]
            for i in ids
            if self._boxes[i].status is BoxStatus.WAITING
            and self._boxes[i].path_type == path_type
        ]

    def _next_tier(self, tracked_stock_id: str, path_type: PathType) -> int:
        siblings = [
            b
            for b in self.list_for_tracked(tracked_stock_id)
            if b.path_type == path_type
        ]
        if not siblings:
            return 1
        return max(b.box_tier for b in siblings) + 1

    def _get(self, box_id: str) -> BoxRecord:
        try:
            return self._boxes[box_id]
        except KeyError as e:
            raise BoxNotFoundError(f"No box with id {box_id!r}") from e

    @staticmethod
    def _validate_box_fields(
        *,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        stop_loss_pct: float,
    ) -> None:
        if upper_price <= lower_price:
            raise BoxValidationError("upper_price must be > lower_price")
        if lower_price <= 0:
            raise BoxValidationError("prices must be positive")
        if not (0 < position_size_pct <= 100):
            raise BoxValidationError(
                "position_size_pct must satisfy 0 < x <= 100"
            )
        if stop_loss_pct >= 0:
            raise BoxValidationError("stop_loss_pct must be negative")


__all__ = [
    "BoxRecord",
    "V71BoxManager",
    "BoxValidationError",
    "BoxOverlapError",
    "BoxModificationError",
    "BoxNotFoundError",
]
