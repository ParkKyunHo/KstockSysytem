"""Skill 7: Position reconciliation (DB <-> broker).

Spec: docs/v71/07_SKILLS_SPEC.md §7, docs/v71/02_TRADING_RULES.md §7+§13

Used by:
  - the post-restart 7-step recovery (§13);
  - the periodic position-sync (§7 manual-trade scenarios A/B/C/D).

Reconciliation cases:
  A: SYSTEM + user added more  -> recompute weighted avg + event reset
  B: SYSTEM + user partial sold -> reduce qty (proportional split when
                                   dual-path)
  C: tracked-not-yet-bought + user bought -> end tracking (EXITED),
                                            invalidate boxes, create
                                            MANUAL position
  D: untracked + user bought    -> create MANUAL position only
  E: full match                 -> no-op
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReconciliationCase(Enum):
    A_SYSTEM_PLUS_MANUAL_BUY = "A"
    B_SYSTEM_PLUS_MANUAL_SELL = "B"
    C_TRACKED_BUT_MANUAL_BUY = "C"
    D_UNTRACKED_MANUAL_BUY = "D"
    E_FULL_MATCH = "E"


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
    rows: list[object]  # list[positions row dataclass]

    def total_qty(self) -> int:
        raise NotImplementedError("P3.5 -- see §7.2")

    def system_total_qty(self) -> int:
        """SYSTEM_A + SYSTEM_B only (excludes MANUAL)."""
        raise NotImplementedError("P3.5 -- see §7.2")


@dataclass(frozen=True)
class ReconciliationResult:
    case: ReconciliationCase
    actions_taken: list[str]
    """Human-readable list logged to system_events + audit_logs."""

    new_position_id: str | None
    invalidated_box_ids: list[str]
    ended_tracking_id: str | None


async def reconcile_positions(
    *,
    broker_balances: list[KiwoomBalance],
    system_positions: list[SystemPosition],
    db_context: object,
) -> list[ReconciliationResult]:
    """Walk both sides, classify each stock into a case, apply the fix.

    Pure intent: deterministic outcomes per case. Side effects (DB
    writes, notifications) are emitted via the injected db_context and
    by callers consuming :class:`ReconciliationResult`.
    """
    raise NotImplementedError("P3.5 -- see docs/v71/07_SKILLS_SPEC.md §7.3")


def classify_case(
    broker: KiwoomBalance | None,
    system: SystemPosition | None,
) -> ReconciliationCase:
    """Pure case dispatcher. Both None is invalid input -> ValueError."""
    raise NotImplementedError("P3.5 -- see docs/v71/07_SKILLS_SPEC.md §7.4")


__all__ = [
    "ReconciliationCase",
    "KiwoomBalance",
    "SystemPosition",
    "ReconciliationResult",
    "reconcile_positions",
    "classify_case",
]
