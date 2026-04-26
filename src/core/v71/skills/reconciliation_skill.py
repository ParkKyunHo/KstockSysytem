"""Skill 7: Position reconciliation -- case classification + helpers.

Spec:
  - 02_TRADING_RULES.md §7  (manual-trade scenarios A/B/C/D)
  - 02_TRADING_RULES.md §13 (post-restart 7-step recovery)
  - 07_SKILLS_SPEC.md §7

Phase: P3.5

This skill contains only the *pure* parts of reconciliation:
  - :func:`classify_case`         maps (broker_qty, system_qty, has_tracking)
                                  to a :class:`ReconciliationCase`.
  - :func:`compute_proportional_split`
                                  splits a sell quantity across PATH_A and
                                  PATH_B with "larger-path-first" rounding.

Stateful execution (DB writes, V71PositionManager / V71BoxManager calls,
notifications) lives on :class:`V71Reconciler`.  Keeping the case logic
pure makes the §7 truth table testable without DB or broker fakes.

Cases (§7):
  A: SYSTEM + user added more   -> recompute weighted avg + event reset
                                   (V71PositionManager.apply_buy, MANUAL_PYRAMID_BUY)
  B: SYSTEM + user partial sold -> reduce qty (MANUAL drained first;
                                   leftover proportionally split across
                                   PATH_A / PATH_B with larger-first rounding)
  C: tracked-not-yet-bought + user bought -> end tracking (EXITED),
                                   invalidate boxes, create MANUAL position
  D: untracked + user bought    -> create MANUAL position only
  E: full match                  -> no-op
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.core.v71.position.state import PositionState

# ---------------------------------------------------------------------------
# Case enum
# ---------------------------------------------------------------------------

class ReconciliationCase(Enum):
    A_SYSTEM_PLUS_MANUAL_BUY = "A"
    B_SYSTEM_PLUS_MANUAL_SELL = "B"
    C_TRACKED_BUT_MANUAL_BUY = "C"
    D_UNTRACKED_MANUAL_BUY = "D"
    E_FULL_MATCH = "E"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KiwoomBalance:
    """Single broker-side balance row for one stock."""

    stock_code: str
    quantity: int
    avg_price: int


@dataclass(frozen=True)
class SystemPosition:
    """All system-known positions for one stock (PATH_A + PATH_B + MANUAL)."""

    stock_code: str
    positions: list[PositionState]
    """Active (OPEN / PARTIAL_CLOSED) positions only."""

    def total_qty(self) -> int:
        return sum(p.total_quantity for p in self.positions)

    def system_total_qty(self) -> int:
        """SYSTEM_A + SYSTEM_B only (excludes MANUAL)."""
        return sum(
            p.total_quantity
            for p in self.positions
            if p.path_type in {"PATH_A", "PATH_B"}
        )

    def manual_total_qty(self) -> int:
        return sum(
            p.total_quantity
            for p in self.positions
            if p.path_type == "MANUAL"
        )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconciliationResult:
    """Audit trail of one reconciliation pass for a stock."""

    stock_code: str
    case: ReconciliationCase
    actions_taken: list[str]
    """Human-readable list logged to system_events + audit_logs."""

    new_position_id: str | None = None
    invalidated_box_ids: tuple[str, ...] = ()
    ended_tracking_id: str | None = None


# ---------------------------------------------------------------------------
# Case classification (pure)
# ---------------------------------------------------------------------------

def classify_case(
    broker_qty: int,
    system_qty: int,
    *,
    has_active_tracking: bool,
) -> ReconciliationCase:
    """Map a (broker_qty, system_qty, has_tracking) triple to a §7 case.

    Args:
        broker_qty: Kiwoom-side balance for the stock (0 if not held).
        system_qty: sum of active V7.1 positions (SYSTEM + MANUAL).
        has_active_tracking: True iff a TRACKING/BOX_SET/POSITION_*
            ``tracked_stocks`` row exists for the stock (used to
            distinguish C from D when system_qty == 0).

    Raises:
        ValueError: if broker_qty < system_qty while system_qty == 0,
            i.e. negative diff with empty system -- logically impossible.
    """
    if broker_qty < 0 or system_qty < 0:
        raise ValueError("quantities must be non-negative")

    diff = broker_qty - system_qty

    if diff == 0:
        return ReconciliationCase.E_FULL_MATCH

    if diff > 0:
        if system_qty > 0:
            return ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY
        # system_qty == 0 -- new buy on empty system.
        return (
            ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY
            if has_active_tracking
            else ReconciliationCase.D_UNTRACKED_MANUAL_BUY
        )

    # diff < 0
    if system_qty > 0:
        return ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL

    # diff < 0 with system_qty == 0 -> impossible.
    raise ValueError(
        f"Invalid: broker_qty={broker_qty} less than system_qty={system_qty} "
        "but system holds nothing"
    )


# ---------------------------------------------------------------------------
# Proportional split (Case B with dual paths)
# ---------------------------------------------------------------------------

def compute_proportional_split(
    sell_quantity: int,
    path_a_qty: int,
    path_b_qty: int,
) -> tuple[int, int]:
    """Distribute ``sell_quantity`` across PATH_A and PATH_B (§7.3 case 3).

    Larger-path-first rounding: when the proportional share is fractional,
    the path with the larger holding receives the rounded-up unit so the
    sum of the two values equals ``sell_quantity`` exactly.

    Args:
        sell_quantity:    total to sell across both paths (already net of
                          MANUAL drainage).
        path_a_qty:       current PATH_A holding.
        path_b_qty:       current PATH_B holding.

    Returns:
        ``(qty_from_path_a, qty_from_path_b)`` with
        ``qty_from_path_a + qty_from_path_b == sell_quantity``.

    Raises:
        ValueError: if ``sell_quantity`` exceeds ``path_a_qty + path_b_qty``
            or the inputs are negative.
    """
    if sell_quantity < 0 or path_a_qty < 0 or path_b_qty < 0:
        raise ValueError("quantities must be non-negative")
    total = path_a_qty + path_b_qty
    if sell_quantity > total:
        raise ValueError(
            f"sell_quantity {sell_quantity} exceeds total {total}"
        )
    if sell_quantity == 0:
        return 0, 0
    if total == 0:
        # Defensive: should be caught by the guard above, but be explicit.
        return 0, 0

    # Edge: only one path holds shares.
    if path_a_qty == 0:
        return 0, sell_quantity
    if path_b_qty == 0:
        return sell_quantity, 0

    # Float share, then floor; the "leftover" goes to the larger path.
    a_share = sell_quantity * path_a_qty / total
    b_share = sell_quantity * path_b_qty / total

    a_floor = int(a_share)
    b_floor = int(b_share)
    leftover = sell_quantity - a_floor - b_floor

    if leftover == 0:
        return a_floor, b_floor

    # Distribute the leftover to the larger path first.  Tie -> PATH_A.
    if path_a_qty >= path_b_qty:
        # Give leftover to PATH_A first; if still leftover (max 1 here),
        # we already return single-unit assignment.
        return a_floor + leftover, b_floor
    return a_floor, b_floor + leftover


__all__ = [
    "ReconciliationCase",
    "KiwoomBalance",
    "SystemPosition",
    "ReconciliationResult",
    "classify_case",
    "compute_proportional_split",
]
