"""Per-position frozen DTO for V7.1 exit logic (P-Wire-Box-4).

Spec:
  - 02_TRADING_RULES.md §5  (post-buy management)
  - 02_TRADING_RULES.md §6  (average-price management)
  - 02_TRADING_RULES.md §11 (position lifecycle)
  - 03_DATA_MODEL.md §2.3   (positions table)
  - 06_AGENTS_SPEC.md §1.3  (single source of truth)

P-Wire-Box-4 (2026-04-30): converted from mutable in-memory dataclass
to a frozen DTO that mirrors a single ``positions`` row. The DB-backed
:class:`V71PositionManager` returns these snapshots; ORM rows live
only inside the manager's transaction contexts (DetachedInstance and
lazy-load risk stays contained, P-Wire-Box-1 BoxRecord pattern mirror).

``PositionStatus`` is re-exported from ``models_v71`` so the SQLAlchemy
column type and the Python enum are identical objects (SQLEnum's value
lookup uses identity, not name -- two definitions silently diverge).

``tracked_stock_id`` and ``triggered_box_id`` are ``str | None``.
Manual buys (Scenario D) and broken atomic rollbacks (Scenario C
fallback) carry None; the previous empty-string convention crashed
on UUID cast (trading-logic blocker 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

# Single source of truth for the lifecycle enum. Importing from the
# ORM (rather than redeclaring) keeps SQLEnum and Python comparisons
# operating on the same class object.
from src.database.models_v71 import PositionStatus

if TYPE_CHECKING:
    from src.database.models_v71 import V71Position


@dataclass(frozen=True)
class PositionState:
    """Frozen snapshot of a ``positions`` row.

    Mutation is forbidden -- callers that need a different state must
    go through :class:`V71PositionManager` so the change persists to
    DB. This makes the ORM session boundary the single point where
    state can change, eliminating an entire class of "in-memory diverged
    from DB" bugs.
    """

    position_id: str
    stock_code: str
    tracked_stock_id: str | None
    triggered_box_id: str | None
    path_type: str  # "PATH_A" | "PATH_B" | "MANUAL"

    # Average-price state (§6).
    weighted_avg_price: int
    initial_avg_price: int
    total_quantity: int

    # Stop ladder (§5.1, §5.4).
    fixed_stop_price: int

    # Partial profit-take flags (§5.2 / §5.3).
    profit_5_executed: bool = False
    profit_10_executed: bool = False

    # Trailing stop bookkeeping (§5.5).
    ts_activated: bool = False
    ts_base_price: int | None = None
    ts_stop_price: int | None = None
    ts_active_multiplier: float | None = None

    # Lifecycle (§11).
    status: PositionStatus = PositionStatus.OPEN
    opened_at: datetime | None = None
    closed_at: datetime | None = None


_SOURCE_TO_PATH: dict[str, str] = {
    "SYSTEM_A": "PATH_A",
    "SYSTEM_B": "PATH_B",
    "MANUAL": "MANUAL",
}

_PATH_TO_SOURCE: dict[str, str] = {
    "PATH_A": "SYSTEM_A",
    "PATH_B": "SYSTEM_B",
    "MANUAL": "MANUAL",
}


def from_orm(orm: V71Position) -> PositionState:
    """Convert a ``V71Position`` ORM row to a frozen :class:`PositionState`.

    Numeric -> int (Numeric(12, 0) = whole won), Numeric -> float for
    ts_active_multiplier (Numeric(3, 1)). Nullable Decimal columns map
    to None branches; trading-logic blocker 9 — a single conversion
    helper is the single source of truth so caller code never sees the
    Decimal/int round-trip pitfalls.

    ``path_type`` field exposes "PATH_A" / "PATH_B" / "MANUAL" while
    the ORM column is ``source = SYSTEM_A | SYSTEM_B | MANUAL``;
    this helper does the rename so existing call sites stay stable.

    ``opened_at`` is the ORM ``created_at`` (server-default NOW at
    INSERT). The legacy in-memory state had a separate field; for the
    DB-backed manager that field is redundant.
    """
    source_value = orm.source.value if hasattr(orm.source, "value") else str(orm.source)
    path_type = _SOURCE_TO_PATH.get(source_value, source_value)
    return PositionState(
        position_id=str(orm.id),
        stock_code=orm.stock_code,
        tracked_stock_id=str(orm.tracked_stock_id) if orm.tracked_stock_id is not None else None,
        triggered_box_id=str(orm.triggered_box_id) if orm.triggered_box_id is not None else None,
        path_type=path_type,
        weighted_avg_price=int(orm.weighted_avg_price),
        initial_avg_price=int(orm.initial_avg_price),
        total_quantity=int(orm.total_quantity),
        fixed_stop_price=int(orm.fixed_stop_price),
        profit_5_executed=bool(orm.profit_5_executed),
        profit_10_executed=bool(orm.profit_10_executed),
        ts_activated=bool(orm.ts_activated),
        ts_base_price=int(orm.ts_base_price) if orm.ts_base_price is not None else None,
        ts_stop_price=int(orm.ts_stop_price) if orm.ts_stop_price is not None else None,
        ts_active_multiplier=(
            float(orm.ts_active_multiplier)
            if orm.ts_active_multiplier is not None
            else None
        ),
        status=orm.status,
        opened_at=orm.created_at,
        closed_at=orm.closed_at,
    )


__all__ = [
    "PositionState",
    "PositionStatus",
    "from_orm",
    "_PATH_TO_SOURCE",
    "_SOURCE_TO_PATH",
]
