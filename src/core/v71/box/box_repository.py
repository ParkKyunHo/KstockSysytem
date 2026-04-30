"""Repository helpers for the ``support_boxes`` table.

P-Wire-Box-1 split: previously the manager held an in-memory dict. The
DB-backed manager now calls into this module under explicit transaction
contexts. All functions take an open ``AsyncSession``; transactional
boundaries are the caller's responsibility (typically V71BoxManager
opens a sessionmaker context per top-level operation).

Spec:
  - 03_DATA_MODEL.md §2.2 (support_boxes schema + indexes)
  - 02_TRADING_RULES.md §3.4 (overlap rule, strict bounds)
  - 02_TRADING_RULES.md §3.7 (30-day reminder)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.v71.box.box_state_machine import BoxStatus
from src.database.models_v71 import PathType, SupportBox, TrackedStock


def _as_uuid(value: str | UUID) -> UUID:
    """Accept str or UUID; raise ValueError on malformed string."""
    if isinstance(value, UUID):
        return value
    return UUID(value)


async def fetch_box(
    session: AsyncSession,
    box_id: str | UUID,
    *,
    for_update: bool = False,
) -> SupportBox | None:
    """Return the row or ``None``. ``for_update`` adds ``SELECT ... FOR UPDATE``."""
    stmt = select(SupportBox).where(SupportBox.id == _as_uuid(box_id))
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def fetch_tracked_for_update(
    session: AsyncSession, tracked_stock_id: str | UUID
) -> TrackedStock | None:
    """Lock the parent tracked_stocks row to serialize sibling box writes.

    Used by create_box / cancel_waiting_for_tracked / mark_invalidated to
    prevent two concurrent overlap checks from both passing (§3.4).
    """
    stmt = (
        select(TrackedStock)
        .where(TrackedStock.id == _as_uuid(tracked_stock_id))
        .with_for_update()
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_for_tracked(
    session: AsyncSession, tracked_stock_id: str | UUID
) -> list[SupportBox]:
    stmt = (
        select(SupportBox)
        .where(SupportBox.tracked_stock_id == _as_uuid(tracked_stock_id))
        .order_by(SupportBox.box_tier.asc(), SupportBox.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_waiting_for_tracked(
    session: AsyncSession,
    tracked_stock_id: str | UUID,
    path_type: PathType,
) -> list[SupportBox]:
    """Hot path -- matches ``idx_boxes_active(tracked_stock_id, path_type, status)``
    partial index (PRD §2.2 line 356, after migration 021).
    """
    stmt = (
        select(SupportBox)
        .where(
            SupportBox.tracked_stock_id == _as_uuid(tracked_stock_id),
            SupportBox.path_type == path_type,
            SupportBox.status == BoxStatus.WAITING,
        )
        .order_by(SupportBox.box_tier.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_all(
    session: AsyncSession,
    *,
    status: BoxStatus | None = None,
    limit: int = 1000,
) -> list[SupportBox]:
    """Default ``limit=1000`` guards against unbounded scans (security M4)."""
    stmt = select(SupportBox)
    if status is not None:
        stmt = stmt.where(SupportBox.status == status)
    stmt = stmt.order_by(SupportBox.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def find_overlap(
    session: AsyncSession,
    *,
    tracked_stock_id: str | UUID,
    path_type: PathType,
    new_lower: Decimal | int,
    new_upper: Decimal | int,
    exclude_box_id: str | UUID | None = None,
) -> SupportBox | None:
    """Return the first WAITING sibling that overlaps the given range.

    Strict bounds (PRD §3.4): ``existing.upper > new_lower
    AND existing.lower < new_upper``. Boundary touch is NOT overlap.

    ``exclude_box_id`` is required by ``modify_box`` so the box being
    edited is not flagged as overlapping with itself.
    """
    conds = [
        SupportBox.tracked_stock_id == _as_uuid(tracked_stock_id),
        SupportBox.path_type == path_type,
        SupportBox.status == BoxStatus.WAITING,
        SupportBox.upper_price > Decimal(new_lower),
        SupportBox.lower_price < Decimal(new_upper),
    ]
    if exclude_box_id is not None:
        conds.append(SupportBox.id != _as_uuid(exclude_box_id))
    stmt = select(SupportBox).where(and_(*conds)).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def next_box_tier(
    session: AsyncSession,
    *,
    tracked_stock_id: str | UUID,
    path_type: PathType,
) -> int:
    """``max(box_tier) + 1`` for the (tracked, path) pair, 1 if empty."""
    stmt = select(func.max(SupportBox.box_tier)).where(
        SupportBox.tracked_stock_id == _as_uuid(tracked_stock_id),
        SupportBox.path_type == path_type,
    )
    current_max = (await session.execute(stmt)).scalar_one_or_none()
    return 1 if current_max is None else int(current_max) + 1


async def find_30day_due(
    session: AsyncSession,
    *,
    now: datetime,
    days: int,
) -> list[SupportBox]:
    """WAITING boxes whose reminder anchor (last_reminder_at or created_at)
    is at or older than ``now - days``.

    Matches ``idx_boxes_pending_reminder`` partial index (008.up.sql).
    ``now`` must be tz-aware: PRD §2.2 columns are TIMESTAMPTZ.
    """
    if now.tzinfo is None:
        raise ValueError(
            "find_30day_due: now must be tz-aware "
            "(PRD §2.2 columns are TIMESTAMPTZ)"
        )
    cutoff = now - timedelta(days=days)
    stmt = (
        select(SupportBox)
        .where(
            SupportBox.status == BoxStatus.WAITING,
            func.coalesce(SupportBox.last_reminder_at, SupportBox.created_at)
            <= cutoff,
        )
        .order_by(SupportBox.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "fetch_box",
    "fetch_tracked_for_update",
    "list_for_tracked",
    "list_waiting_for_tracked",
    "list_all",
    "find_overlap",
    "next_box_tier",
    "find_30day_due",
]
