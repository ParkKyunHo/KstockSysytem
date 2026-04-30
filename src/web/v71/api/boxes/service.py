"""Box business rules (09_API_SPEC §4).

P-Wire-Box-2 (2026-04-30): write paths now delegate persistence to the
shared :class:`V71BoxManager`. The web layer keeps the surrounding
business rules that the manager does not know about (30%/100% capital
caps, audit log, tracked_stock state transitions); the manager is the
single source of truth for the support_boxes row itself, including
overlap detection (§3.4) and FOR UPDATE locking on the parent
tracked_stock.

Why route through the manager: the trading engine reads boxes through
the same manager. Going around it (the pre-P-Wire-Box-2 ``repo.insert_box``
direct call) was the regression that caused user-registered boxes to
be invisible to ``/status`` / ``/pending`` / auto-entry detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.v71.box import box_repository as v71_box_repo
from src.core.v71.box.box_manager import (
    BoxModificationError,
    BoxNotFoundError,
    BoxOverlapError,
    BoxValidationError,
)
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

if TYPE_CHECKING:
    from src.core.v71.box.box_manager import V71BoxManager

# 09_API_SPEC §4.1 -- 종목당 30% 한도.
MAX_PCT_PER_STOCK = Decimal(30)


def _ensure_transaction(session: AsyncSession) -> None:
    """Implicit-begin handshake.

    SQLAlchemy 2.0 starts a transaction on the first SQL emitted on a
    fresh session, but V71BoxManager.create_box guards external sessions
    with ``session.in_transaction()`` so the SELECT FOR UPDATE lock is
    not silently dropped (security H1). The web service emits a SELECT
    (parent_tracked_stock) before delegating to the manager, which
    flips ``in_transaction()`` true; this helper just makes the pattern
    explicit so future maintainers do not reorder the calls.
    """
    # No-op: the SELECT below begins the transaction. Documented for
    # readers, not for the runtime.


def _wrap_box_error(exc: Exception) -> Exception:
    """Translate V71BoxManager exceptions to web-layer exceptions."""
    if isinstance(exc, BoxOverlapError):
        # PRD §4.1 example status code is 422 for overlap.
        return ConflictError(
            "박스 가격 범위가 기존 박스와 겹칩니다",
            error_code="BOX_OVERLAP",
            status_code=422,
        )
    if isinstance(exc, BoxValidationError):
        return V71Error(
            str(exc),
            error_code="VALIDATION_FAILED",
            status_code=422,
        )
    if isinstance(exc, BoxModificationError):
        return BusinessRuleError(
            str(exc),
            error_code="BOX_NOT_EDITABLE",
        )
    if isinstance(exc, BoxNotFoundError):
        return NotFoundError(
            str(exc),
            error_code="BOX_NOT_FOUND",
        )
    return exc


# ---------------------------------------------------------------------
# Create (PRD §4.1)
# ---------------------------------------------------------------------


async def create_box(
    session: AsyncSession,
    *,
    box_manager: V71BoxManager,
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

    # Lock the parent tracked_stocks row before the cap check so a
    # concurrent create_box on the same stock can not race past the
    # 30% limit. V71BoxManager.create_box re-acquires this same lock
    # internally; Postgres allows nested FOR UPDATE within one txn.
    await v71_box_repo.fetch_tracked_for_update(session, tracked_stock_id)

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

    # Delegate the row write (overlap check + INSERT + box_tier
    # numbering) to the manager. Outer session is shared so this stays
    # in the same transaction as the cap check + audit prep.
    try:
        record = await box_manager.create_box(
            session=session,
            tracked_stock_id=str(tracked_stock_id),
            upper_price=int(upper_price),
            lower_price=int(lower_price),
            position_size_pct=float(position_size_pct),
            strategy_type=strategy_type,
            path_type=path_type,
            stop_loss_pct=float(stop_loss_pct),
            memo=memo,
        )
    except (
        BoxOverlapError,
        BoxValidationError,
        BoxModificationError,
        BoxNotFoundError,
    ) as exc:
        raise _wrap_box_error(exc) from exc

    # tracked_stock.status TRACKING -> BOX_SET 전이 (PRD §4.1 자동 처리).
    ts_service.transition_to_box_set(ts)

    await session.commit()

    # The manager added the ORM row inside this same session, so a
    # session.get() hits the identity map and returns the same instance
    # the caller can pass to router._to_out().
    box = await session.get(SupportBox, UUID(record.id))
    assert box is not None  # impossible: we just wrote it

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
            "box_tier": record.box_tier,
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
    box_manager: V71BoxManager,
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

    # 30% 한도 재검증. tracked_stock FOR UPDATE 락으로 race 차단.
    await v71_box_repo.fetch_tracked_for_update(session, box.tracked_stock_id)
    used_pct = await repo.stock_capital_usage(
        session,
        tracked_stock_id=box.tracked_stock_id,
        total_capital=total_capital,
    )
    new_size = (
        position_size_pct
        if position_size_pct is not None
        else Decimal(str(box.position_size_pct))
    )
    diff = new_size - Decimal(str(box.position_size_pct))
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

    if stop_loss_pct is not None and stop_loss_pct < box.stop_loss_pct:
        warnings.append("STOP_LOSS_RELAXED")

    try:
        record = await box_manager.modify_box(
            str(box_id),
            upper_price=int(upper_price) if upper_price is not None else None,
            lower_price=int(lower_price) if lower_price is not None else None,
            position_size_pct=(
                float(position_size_pct)
                if position_size_pct is not None
                else None
            ),
            stop_loss_pct=(
                float(stop_loss_pct) if stop_loss_pct is not None else None
            ),
            memo=memo,
            force_relax_stop=bool(warnings),  # auto-confirm when relaxing
            session=session,
        )
    except (
        BoxOverlapError,
        BoxValidationError,
        BoxModificationError,
        BoxNotFoundError,
    ) as exc:
        raise _wrap_box_error(exc) from exc

    await session.commit()

    box = await session.get(SupportBox, box_id)
    assert box is not None

    await record_audit(
        action=AuditAction.BOX_MODIFIED,
        user_id=user_id,
        target_type="support_box",
        target_id=box.id,
        before_state=before,
        after_state={
            "upper_price": str(record.upper_price),
            "lower_price": str(record.lower_price),
            "position_size_pct": str(record.position_size_pct),
            "stop_loss_pct": str(record.stop_loss_pct),
            "memo": record.memo,
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
    box_manager: V71BoxManager,
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

    tracked_id = box.tracked_stock_id
    try:
        await box_manager.delete_box(str(box_id), session=session)
    except (BoxModificationError, BoxNotFoundError) as exc:
        raise _wrap_box_error(exc) from exc

    # 마지막 활성 박스 삭제 시 tracked_stock.status BOX_SET -> TRACKING.
    ts = await repo.parent_tracked_stock(session, tracked_stock_id=tracked_id)
    if ts is not None:
        await session.refresh(ts, attribute_names=["boxes"])
        ts_service.transition_back_to_tracking_if_no_boxes(ts)

    await session.commit()

    await record_audit(
        action=AuditAction.BOX_DELETED,
        user_id=user_id,
        target_type="support_box",
        target_id=box_id,
        ip_address=ip_address,
        user_agent=user_agent,
        before_state={"status": "WAITING"},
        after_state={"status": "CANCELLED"},
    )


# Mark unused imports as intentional (kept for future restorations).
_ = (datetime, timezone)
