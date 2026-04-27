"""Box business rules (09_API_SPEC §4)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models_v71 import (
    BoxStatus,
    PathType,
    StrategyType,
    SupportBox,
)

from ...audit import record_audit
from ...db_models import AuditAction
from ...exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    V71Error,
)
from ..tracked_stocks import service as ts_service
from . import repo

# 09_API_SPEC §4.1 -- 종목당 30% 한도.
MAX_PCT_PER_STOCK = Decimal(30)


def _intervals_overlap(
    a_lower: Decimal, a_upper: Decimal, b_lower: Decimal, b_upper: Decimal,
) -> bool:
    """[a_lower, a_upper] ∩ [b_lower, b_upper] != ∅."""
    return not (a_upper < b_lower or b_upper < a_lower)


# ---------------------------------------------------------------------
# Create (PRD §4.1)
# ---------------------------------------------------------------------


async def create_box(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    path_type: PathType,
    upper_price: Decimal,
    lower_price: Decimal,
    position_size_pct: Decimal,
    stop_loss_pct: Decimal,
    strategy_type: StrategyType,
    memo: str | None,
    user_id: UUID,
    total_capital: Decimal,
    ip_address: str | None,
    user_agent: str | None,
) -> SupportBox:
    ts = await repo.parent_tracked_stock(session, tracked_stock_id=tracked_stock_id)
    if ts is None:
        raise NotFoundError(
            f"tracked_stock {tracked_stock_id} not found",
            error_code="TRACKED_STOCK_NOT_FOUND",
        )

    # PRD §4.1: 박스 겹침 검증 (같은 path 내).
    siblings = await repo.get_active_boxes_for_stock_path(
        session,
        tracked_stock_id=tracked_stock_id,
        path_type=path_type,
    )
    for sib in siblings:
        if _intervals_overlap(
            lower_price, upper_price, sib.lower_price, sib.upper_price
        ):
            raise ConflictError(
                "박스 가격 범위가 기존 박스와 겹칩니다",
                error_code="BOX_OVERLAP",
                status_code=422,  # PRD §4.1 example uses 422
                details={
                    "existing_box_id": str(sib.id),
                    "existing_range": {
                        "upper": str(sib.upper_price),
                        "lower": str(sib.lower_price),
                    },
                },
            )

    # PRD §4.1: 종목당 30% 한도 (실제 포지션 + 활성 박스).
    used_pct = await repo.stock_capital_usage(
        session,
        tracked_stock_id=tracked_stock_id,
        total_capital=total_capital,
    )
    if (used_pct + position_size_pct) > MAX_PCT_PER_STOCK:
        raise BusinessRuleError(
            "종목당 30% 한도 초과",
            error_code="POSITION_LIMIT_EXCEEDED",
            details={
                "current_actual_pct": float(used_pct),
                "requested_pct": float(position_size_pct),
                "limit_pct": float(MAX_PCT_PER_STOCK),
            },
        )

    tier = await repo.next_box_tier(session, tracked_stock_id=tracked_stock_id)
    box = repo.insert_box(
        session,
        tracked_stock_id=tracked_stock_id,
        path_type=path_type,
        box_tier=tier,
        upper_price=upper_price,
        lower_price=lower_price,
        position_size_pct=position_size_pct,
        stop_loss_pct=stop_loss_pct,
        strategy_type=strategy_type,
        memo=memo,
    )
    await session.flush()

    # tracked_stock.status TRACKING -> BOX_SET 전이 (PRD §4.1 자동 처리).
    ts_service.transition_to_box_set(ts)

    await session.commit()

    await record_audit(
        action=AuditAction.BOX_CREATED,
        user_id=user_id,
        target_type="support_box",
        target_id=box.id,
        ip_address=ip_address,
        user_agent=user_agent,
        after_state={
            "tracked_stock_id": str(tracked_stock_id),
            "path_type": path_type.value,
            "box_tier": tier,
            "upper_price": str(upper_price),
            "lower_price": str(lower_price),
            "position_size_pct": str(position_size_pct),
            "strategy_type": strategy_type.value,
        },
    )
    return box


# ---------------------------------------------------------------------
# Patch (PRD §4.4)
# ---------------------------------------------------------------------


async def patch_box(
    session: AsyncSession,
    *,
    box_id: UUID,
    upper_price: Decimal | None,
    lower_price: Decimal | None,
    position_size_pct: Decimal | None,
    stop_loss_pct: Decimal | None,
    memo: str | None,
    user_id: UUID,
    total_capital: Decimal,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[SupportBox, list[str]]:
    """Returns ``(box, warnings)``. ``warnings`` populates X-Warning."""
    box = await repo.get_by_id(session, box_id)
    if box is None:
        raise NotFoundError(
            f"support_box {box_id} not found",
            error_code="BOX_NOT_FOUND",
        )
    if box.status != BoxStatus.WAITING:
        # PRD §4.4 -- TRIGGERED 박스는 매수 완료라면 수정 불가 (단순화).
        raise BusinessRuleError(
            "이미 매수 실행된 박스는 수정 불가",
            error_code="BOX_NOT_EDITABLE",
            details={"current_status": box.status.value},
        )

    before: dict[str, Any] = {
        "upper_price": str(box.upper_price),
        "lower_price": str(box.lower_price),
        "position_size_pct": str(box.position_size_pct),
        "stop_loss_pct": str(box.stop_loss_pct),
        "memo": box.memo,
    }
    warnings: list[str] = []

    new_upper = upper_price if upper_price is not None else box.upper_price
    new_lower = lower_price if lower_price is not None else box.lower_price
    if new_upper <= new_lower:
        raise V71Error(
            "Box upper price must be greater than lower price",
            error_code="VALIDATION_FAILED",
            status_code=422,
            details={
                "fields": [
                    {
                        "field": "upper_price",
                        "value": str(new_upper),
                        "constraint": f"> lower_price (= {new_lower})",
                    }
                ]
            },
        )

    new_size = position_size_pct if position_size_pct is not None else box.position_size_pct
    new_stop = stop_loss_pct if stop_loss_pct is not None else box.stop_loss_pct

    # 30% 한도 재검증 (기존 box 비중 빼고 신규 비중 더해서).
    used_pct = await repo.stock_capital_usage(
        session,
        tracked_stock_id=box.tracked_stock_id,
        total_capital=total_capital,
    )
    diff = new_size - box.position_size_pct
    if (used_pct + diff) > MAX_PCT_PER_STOCK:
        raise BusinessRuleError(
            "종목당 30% 한도 초과",
            error_code="POSITION_LIMIT_EXCEEDED",
            details={
                "current_actual_pct": float(used_pct),
                "requested_pct": float(new_size),
                "limit_pct": float(MAX_PCT_PER_STOCK),
            },
        )

    # 손절폭 완화 (예: -0.05 → -0.07) 경고.
    if stop_loss_pct is not None and stop_loss_pct < box.stop_loss_pct:
        warnings.append("STOP_LOSS_RELAXED")

    box.upper_price = new_upper
    box.lower_price = new_lower
    box.position_size_pct = new_size
    box.stop_loss_pct = new_stop
    if memo is not None:
        box.memo = memo

    await session.commit()

    await record_audit(
        action=AuditAction.BOX_MODIFIED,
        user_id=user_id,
        target_type="support_box",
        target_id=box.id,
        before_state=before,
        after_state={
            "upper_price": str(box.upper_price),
            "lower_price": str(box.lower_price),
            "position_size_pct": str(box.position_size_pct),
            "stop_loss_pct": str(box.stop_loss_pct),
            "memo": box.memo,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return box, warnings


# ---------------------------------------------------------------------
# Delete (PRD §4.5)
# ---------------------------------------------------------------------


async def delete_box(
    session: AsyncSession,
    *,
    box_id: UUID,
    user_id: UUID,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    box = await repo.get_by_id(session, box_id)
    if box is None:
        raise NotFoundError(
            f"support_box {box_id} not found",
            error_code="BOX_NOT_FOUND",
        )
    if box.status == BoxStatus.TRIGGERED:
        raise BusinessRuleError(
            "매수 실행된 박스는 삭제 불가 (포지션 청산 필요)",
            error_code="BOX_TRIGGERED_CANNOT_DELETE",
        )

    box.status = BoxStatus.CANCELLED
    box.invalidated_at = datetime.now(timezone.utc)
    box.invalidation_reason = "MANUAL_DELETE"

    # 마지막 활성 박스 삭제 시 tracked_stock.status BOX_SET -> TRACKING.
    ts = await repo.parent_tracked_stock(
        session, tracked_stock_id=box.tracked_stock_id
    )
    if ts is not None:
        # Reload boxes to recompute (lazily fetched via attribute).
        await session.refresh(ts, attribute_names=["boxes"])
        ts_service.transition_back_to_tracking_if_no_boxes(ts)

    await session.commit()

    await record_audit(
        action=AuditAction.BOX_DELETED,
        user_id=user_id,
        target_type="support_box",
        target_id=box.id,
        ip_address=ip_address,
        user_agent=user_agent,
        before_state={"status": "WAITING"},
        after_state={"status": "CANCELLED"},
    )
