"""TrackedSummary DB query (P-Wire-Box-3).

Provides ``build_tracked_summaries`` -- the async function that
``DailySummary`` and ``TelegramCommands`` ``list_tracked`` callbacks
delegate to. Pre-P-Wire-Box-3 returned an empty list (stub); now we
JOIN tracked_stocks with support_boxes and positions so /tracking
actually shows what the user registered.

Output shape: one :class:`TrackedSummary` per (tracked_stock, path_type)
pair that has at least one box on that path. Tracked stocks with no
boxes but an active manual position emit one row with path_type
"MANUAL". EXITED tracked stocks are excluded.

Spec:
  - 02_TRADING_RULES.md §9.x (telegram /tracking)
  - 03_DATA_MODEL.md §2.1 / §2.2 / §2.3 (tracked_stocks, support_boxes, positions)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.database.models_v71 import (
    BoxStatus,
    PathType,
    PositionStatus,
    SupportBox,
    TrackedStatus,
    TrackedStock,
    V71Position,
)

if TYPE_CHECKING:
    from src.core.v71.notification.v71_telegram_commands import TrackedSummary


async def build_tracked_summaries(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[TrackedSummary]:
    """Return one TrackedSummary per (tracked_stock, path) with active rows."""
    from src.core.v71.notification.v71_telegram_commands import TrackedSummary

    async with session_factory() as session:
        # Load tracked stocks (excluding EXITED) with their boxes +
        # positions in one round-trip via selectinload-style fan-out.
        rows = list(
            (
                await session.execute(
                    select(TrackedStock).where(
                        TrackedStock.status != TrackedStatus.EXITED,
                    )
                )
            ).scalars().all()
        )
        if not rows:
            return []

        tracked_ids = [ts.id for ts in rows]

        # Box rows for these tracked stocks, status WAITING only.
        box_rows = list(
            (
                await session.execute(
                    select(SupportBox).where(
                        SupportBox.tracked_stock_id.in_(tracked_ids),
                        SupportBox.status == BoxStatus.WAITING,
                    )
                )
            ).scalars().all()
        )

        # Active positions per tracked stock.
        pos_rows = list(
            (
                await session.execute(
                    select(V71Position).where(
                        V71Position.tracked_stock_id.in_(tracked_ids),
                        V71Position.status != PositionStatus.CLOSED,
                    )
                )
            ).scalars().all()
        )

    # Group boxes by (tracked_stock_id, path_type) -> count.
    box_count: dict[tuple[str, PathType], int] = {}
    for b in box_rows:
        key = (str(b.tracked_stock_id), b.path_type)
        box_count[key] = box_count.get(key, 0) + 1

    # has_position per tracked_stock_id.
    has_pos: set[str] = {str(p.tracked_stock_id) for p in pos_rows if p.tracked_stock_id is not None}

    summaries: list[TrackedSummary] = []
    for ts in rows:
        ts_id_str = str(ts.id)
        path_a_count = box_count.get((ts_id_str, PathType.PATH_A), 0)
        path_b_count = box_count.get((ts_id_str, PathType.PATH_B), 0)
        has_position = ts_id_str in has_pos

        # Emit one row per non-empty path; both empty + has_position falls
        # back to a single "MANUAL" row so manual buys still surface.
        emitted = False
        if path_a_count > 0:
            summaries.append(TrackedSummary(
                tracked_stock_id=ts_id_str,
                stock_code=ts.stock_code,
                stock_name=ts.stock_name,
                path_type=PathType.PATH_A.value,
                status=ts.status.value,
                box_count=path_a_count,
                has_position=has_position,
            ))
            emitted = True
        if path_b_count > 0:
            summaries.append(TrackedSummary(
                tracked_stock_id=ts_id_str,
                stock_code=ts.stock_code,
                stock_name=ts.stock_name,
                path_type=PathType.PATH_B.value,
                status=ts.status.value,
                box_count=path_b_count,
                has_position=has_position,
            ))
            emitted = True
        if not emitted and has_position:
            summaries.append(TrackedSummary(
                tracked_stock_id=ts_id_str,
                stock_code=ts.stock_code,
                stock_name=ts.stock_name,
                path_type="MANUAL",
                status=ts.status.value,
                box_count=0,
                has_position=True,
            ))
        elif not emitted:
            # TRACKING stock with no boxes / positions yet -- still show
            # the row so /tracking reflects the registration.
            summaries.append(TrackedSummary(
                tracked_stock_id=ts_id_str,
                stock_code=ts.stock_code,
                stock_name=ts.stock_name,
                path_type="",
                status=ts.status.value,
                box_count=0,
                has_position=False,
            ))

    return summaries


def make_list_tracked_callable(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], Awaitable[list[TrackedSummary]]]:
    """trading_bridge wires this into DailySummary + TelegramCommands."""

    async def _list_tracked() -> list[TrackedSummary]:
        try:
            return await build_tracked_summaries(session_factory)
        except Exception:  # noqa: BLE001 - never crash the caller
            import logging
            logging.getLogger(__name__).exception(
                "build_tracked_summaries failed; falling back to empty",
            )
            return []

    return _list_tracked


__all__ = ["build_tracked_summaries", "make_list_tracked_callable"]
