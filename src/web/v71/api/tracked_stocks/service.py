"""tracked_stocks business rules (09_API_SPEC §3 + PRD Patch #3)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models_v71 import (
    BoxStatus,
    SupportBox,
    TrackedStatus,
    TrackedStock,
)

from ...audit import record_audit
from ...db_models import AuditAction
from ...exceptions import BusinessRuleError, ConflictError, NotFoundError
from . import repo


# ---------------------------------------------------------------------
# List + paginate
# ---------------------------------------------------------------------


async def list_tracked_stocks(
    session: AsyncSession,
    *,
    status: TrackedStatus | None,
    stock_code: str | None,
    q: str | None,
    limit: int,
    sort_desc: bool,
    after_created_at: datetime | None,
    after_id: UUID | None,
    total_capital: Decimal | None,
) -> tuple[list[tuple[TrackedStock, dict[str, Any]]], bool]:
    rows = await repo.list_tracked(
        session,
        status=status,
        stock_code=stock_code,
        q=q,
        limit=limit,
        sort_desc=sort_desc,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    enriched = []
    for ts in rows:
        summary = await repo.build_summary(
            session,
            tracked_stock_id=ts.id,
            total_capital=total_capital,
        )
        enriched.append((ts, summary))
    return enriched, has_more


# ---------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------


async def get_detail(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    total_capital: Decimal | None,
) -> tuple[TrackedStock, dict[str, Any]]:
    ts = await repo.get_by_id(session, tracked_stock_id)
    if ts is None:
        raise NotFoundError(
            f"tracked_stock {tracked_stock_id} not found",
            error_code="TRACKED_STOCK_NOT_FOUND",
        )
    summary = await repo.build_summary(
        session,
        tracked_stock_id=ts.id,
        total_capital=total_capital,
    )
    return ts, summary


# ---------------------------------------------------------------------
# Register (POST)
# ---------------------------------------------------------------------


async def register_tracking(
    session: AsyncSession,
    *,
    stock_code: str,
    user_memo: str | None,
    source: str | None,
    user_id: UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> TrackedStock:
    # PRD §3.2 검증: stocks 마스터에 존재 여부 확인 (있으면 사용, 없으면 422).
    stock = await repo.get_stock_master(session, stock_code)
    if stock is None:
        raise BusinessRuleError(
            f"Unknown stock_code: {stock_code}",
            error_code="INVALID_STOCK_CODE",
        )

    existing = await repo.get_active_by_code(session, stock_code)
    if existing is not None:
        raise ConflictError(
            f"{stock.name}({stock_code}) 이미 추적 중입니다",
            error_code="DUPLICATE_TRACKING",
            details={"existing_id": str(existing.id)},
        )

    ts = repo.insert_new(
        session,
        stock_code=stock_code,
        stock_name=stock.name,
        market=stock.market,
        user_memo=user_memo,
        source=source,
    )
    await session.flush()
    await session.commit()

    await record_audit(
        action=AuditAction.TRACKING_REGISTERED,
        user_id=user_id,
        target_type="tracked_stock",
        target_id=ts.id,
        ip_address=ip_address,
        user_agent=user_agent,
        after_state={"stock_code": stock_code, "source": source},
    )
    return ts


# ---------------------------------------------------------------------
# Patch (memo/source)
# ---------------------------------------------------------------------


async def update_memo(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    user_memo: str | None,
    source: str | None,
    user_id: UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> TrackedStock:
    ts = await repo.get_by_id(session, tracked_stock_id)
    if ts is None:
        raise NotFoundError(
            f"tracked_stock {tracked_stock_id} not found",
            error_code="TRACKED_STOCK_NOT_FOUND",
        )
    before = {"user_memo": ts.user_memo, "source": ts.source}
    if user_memo is not None:
        ts.user_memo = user_memo
    if source is not None:
        ts.source = source
    await session.commit()

    await record_audit(
        action=AuditAction.SETTINGS_CHANGED,
        user_id=user_id,
        target_type="tracked_stock",
        target_id=ts.id,
        before_state=before,
        after_state={"user_memo": ts.user_memo, "source": ts.source},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return ts


# ---------------------------------------------------------------------
# Delete -> EXITED (PRD §3.5)
# ---------------------------------------------------------------------


async def stop_tracking(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    user_id: UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    ts = await repo.get_by_id(session, tracked_stock_id)
    if ts is None:
        raise NotFoundError(
            f"tracked_stock {tracked_stock_id} not found",
            error_code="TRACKED_STOCK_NOT_FOUND",
        )
    pos_count, qty = repo.has_active_position(ts.positions)
    if pos_count > 0:
        raise BusinessRuleError(
            "보유 포지션이 있어 추적 종료 불가",
            error_code="ACTIVE_POSITION_EXISTS",
            details={"position_count": pos_count, "total_quantity": qty},
        )

    # PRD §3.5: 모든 미진입 박스 CANCELLED + status=EXITED + 시세 구독 해제
    now = datetime.now(timezone.utc)
    cancelled_ids: list[str] = []
    for box in ts.boxes:
        if box.status == BoxStatus.WAITING:
            box.status = BoxStatus.CANCELLED
            box.invalidated_at = now
            box.invalidation_reason = "TRACKING_STOPPED"
            cancelled_ids.append(str(box.id))

    repo.mark_exited(ts, reason="MANUAL")
    await session.commit()

    await record_audit(
        action=AuditAction.TRACKING_REMOVED,
        user_id=user_id,
        target_type="tracked_stock",
        target_id=ts.id,
        before_state={"status": "ACTIVE", "cancelled_box_count": len(cancelled_ids)},
        after_state={"status": "EXITED"},
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------
# Status transition helpers (used by boxes service)
# ---------------------------------------------------------------------


def transition_to_box_set(ts: TrackedStock) -> bool:
    """If ``TRACKING``, advance to ``BOX_SET`` (called when a box is created)."""
    if ts.status == TrackedStatus.TRACKING:
        ts.status = TrackedStatus.BOX_SET
        ts.last_status_changed_at = datetime.now(timezone.utc)
        return True
    return False


def transition_back_to_tracking_if_no_boxes(ts: TrackedStock) -> bool:
    """If the last active box is removed, drop back to ``TRACKING``."""
    if ts.status != TrackedStatus.BOX_SET:
        return False
    has_active = any(b.status == BoxStatus.WAITING for b in ts.boxes)
    if has_active:
        return False
    ts.status = TrackedStatus.TRACKING
    ts.last_status_changed_at = datetime.now(timezone.utc)
    return True
