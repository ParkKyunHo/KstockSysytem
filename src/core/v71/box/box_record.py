"""BoxRecord -- read-only DTO for ``support_boxes`` rows.

P-Wire-Box-1 split this out of ``box_manager.py`` so the manager can
return frozen snapshots of DB rows without exposing detached ORM
objects (DetachedInstanceError / MissingGreenlet risk) or letting
callers mutate state behind the manager's back.

Spec:
  - 03_DATA_MODEL.md §2.2  (support_boxes schema)
  - 02_TRADING_RULES.md §3 (box rules)

Conversion rules (ORM → BoxRecord):
  * UUID columns -> str (callers already treat box_id as string)
  * Numeric(12, 0) prices -> int (PRD §2.2 stores whole won)
  * Numeric(5, 2) / Numeric(8, 6) percent -> float (display + arithmetic)
  * TIMESTAMPTZ -> tz-aware datetime (preserved as-is)
  * Enum fields stay as enums (caller imports the same types)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from src.core.v71.box.box_state_machine import BoxStatus

# Single source of truth for the path / strategy enums is the ORM
# (PRD 03 §2.2). The Literal alias in ``box_entry_skill`` predates the
# DB-backed manager and stays for read-only contexts.
from src.database.models_v71 import PathType, StrategyType

if TYPE_CHECKING:
    from src.database.models_v71 import SupportBox


@dataclass(frozen=True)
class BoxRecord:
    """Frozen snapshot of a ``support_boxes`` row.

    Mutation is forbidden -- callers that need a different status / price
    must go through :class:`V71BoxManager` so the change persists to DB.
    """

    id: str
    tracked_stock_id: str
    box_tier: int
    upper_price: int
    lower_price: int
    position_size_pct: float
    stop_loss_pct: float
    strategy_type: StrategyType
    path_type: PathType
    status: BoxStatus = BoxStatus.WAITING
    memo: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    triggered_at: datetime | None = None
    invalidated_at: datetime | None = None
    last_reminder_at: datetime | None = None
    invalidation_reason: str | None = None


def from_orm(orm: SupportBox) -> BoxRecord:
    """Convert a ``SupportBox`` ORM row to a :class:`BoxRecord` snapshot.

    The conversion is lossless for the columns the application reads.
    Decimals are widened to int / float at the type boundary; precision
    is preserved because PRD §2.2 stores whole-won prices and bounded
    percentages.
    """
    return BoxRecord(
        id=str(orm.id),
        tracked_stock_id=str(orm.tracked_stock_id),
        box_tier=int(orm.box_tier),
        upper_price=int(orm.upper_price),
        lower_price=int(orm.lower_price),
        position_size_pct=float(orm.position_size_pct),
        stop_loss_pct=float(orm.stop_loss_pct),
        strategy_type=orm.strategy_type,
        path_type=orm.path_type,
        status=orm.status,
        memo=orm.memo,
        created_at=orm.created_at,
        modified_at=orm.modified_at,
        triggered_at=orm.triggered_at,
        invalidated_at=orm.invalidated_at,
        last_reminder_at=orm.last_reminder_at,
        invalidation_reason=orm.invalidation_reason,
    )


def _decimal_to_int(value: Decimal | int) -> int:
    """Helper for tests / future ORM call sites; preserved for symmetry."""
    return int(value)


__all__ = ["BoxRecord", "from_orm"]
