"""Orders REST endpoints (09_API_SPEC §13). ★ PRD Patch #5 (V7.1.0d, 2026-04-27).

키움 API에 ``client_order_id`` 필드 없음 → V7.1 자체 매핑 (v71_orders 테이블).
주문 발주는 OrderManager (Phase 5 후속, src/core/v71/exchange/order_manager.py)
가 내부적으로 수행. 본 라우터는 read-only 조회 + 수동 취소만 노출.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, status
from sqlalchemy import or_, select

from ...auth.dependencies import CurrentUserDep
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import BusinessRuleError, NotFoundError, V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.orders import (
    OrderCancelTaskOut,
    OrderDetailOut,
    OrderOut,
)
from src.database.models_v71 import OrderState, V71Order

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_out(o: V71Order) -> OrderOut:
    return OrderOut(
        id=o.id,
        kiwoom_order_no=o.kiwoom_order_no,
        kiwoom_orig_order_no=o.kiwoom_orig_order_no,
        position_id=o.position_id,
        box_id=o.box_id,
        tracked_stock_id=o.tracked_stock_id,
        stock_code=o.stock_code,
        direction=o.direction.value,  # type: ignore[arg-type]
        trade_type=o.trade_type.value,  # type: ignore[arg-type]
        quantity=o.quantity,
        price=o.price,
        exchange=o.exchange,
        state=o.state.value,  # type: ignore[arg-type]
        filled_quantity=o.filled_quantity,
        filled_avg_price=o.filled_avg_price,
        reject_reason=o.reject_reason,
        cancel_reason=o.cancel_reason,
        retry_attempt=o.retry_attempt,
        submitted_at=o.submitted_at,
        filled_at=o.filled_at,
        cancelled_at=o.cancelled_at,
        rejected_at=o.rejected_at,
    )


def _to_detail(o: V71Order) -> OrderDetailOut:
    base = _to_out(o)
    return OrderDetailOut(
        **base.model_dump(),
        kiwoom_raw_request=o.kiwoom_raw_request,
        kiwoom_raw_response=o.kiwoom_raw_response,
    )


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if not cursor:
        return None, None
    try:
        c = PaginationCursor.decode(cursor)
        return datetime.fromisoformat(c.sort_value), UUID(c.id)
    except Exception:  # noqa: BLE001 -- cursor opaque to clients
        return None, None


# ---------------------------------------------------------------------
# GET /orders (PRD §13.1)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_orders(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    state_q: str | None = Query(default=None, alias="state"),
    position_id: UUID | None = Query(default=None),
    box_id: UUID | None = Query(default=None),
    stock_code: str | None = Query(default=None, max_length=10),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    stmt = select(V71Order)

    if state_q is not None:
        try:
            stmt = stmt.where(V71Order.state == OrderState(state_q))
        except ValueError as exc:
            raise V71Error(
                "Invalid state",
                error_code="INVALID_PARAMETER",
                details={"field": "state", "value": state_q},
            ) from exc

    if position_id is not None:
        stmt = stmt.where(V71Order.position_id == position_id)
    if box_id is not None:
        stmt = stmt.where(V71Order.box_id == box_id)
    if stock_code is not None:
        stmt = stmt.where(V71Order.stock_code == stock_code)
    if from_date is not None:
        stmt = stmt.where(V71Order.submitted_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(V71Order.submitted_at <= to_date)

    after_dt, after_id = _decode_cursor(cursor)
    if after_dt is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                V71Order.submitted_at < after_dt,
                (V71Order.submitted_at == after_dt) & (V71Order.id < after_id),
            )
        )

    stmt = stmt.order_by(V71Order.submitted_at.desc(), V71Order.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [_to_out(o).model_dump(mode="json") for o in rows]
    next_cursor: str | None = None
    if has_more and rows:
        next_cursor = PaginationCursor(
            id=str(rows[-1].id),
            sort_value=rows[-1].submitted_at.isoformat(),
        ).encode()
    meta = build_list_meta(request_id=request_id, limit=limit, next_cursor=next_cursor)
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# GET /orders/{id} (PRD §13.2)
# ---------------------------------------------------------------------


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def get_order(
    order_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    o = await session.get(V71Order, order_id)
    if o is None:
        raise NotFoundError(
            f"order {order_id} not found", error_code="ORDER_NOT_FOUND",
        )
    return {"data": _to_detail(o).model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# POST /orders/{id}/cancel (PRD §13.3)
# ---------------------------------------------------------------------


@router.post("/{order_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_order(
    order_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """PRD §13.3: 미체결 주문 수동 취소.

    OrderManager가 키움 kt10003 호출 → 새 row INSERT (kiwoom_orig_order_no = 원주문)
    + 원주문 state=CANCELLED. 본 endpoint는 task만 큐에 등록 후 task_id 반환.
    """
    if user.role not in {"OWNER", "ADMIN"}:
        raise BusinessRuleError(
            "Insufficient role",
            error_code="FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    o = await session.get(V71Order, order_id)
    if o is None:
        raise NotFoundError(
            f"order {order_id} not found", error_code="ORDER_NOT_FOUND",
        )

    if o.state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}:
        raise BusinessRuleError(
            "FILLED/CANCELLED/REJECTED 상태는 취소 불가",
            error_code="ORDER_NOT_CANCELLABLE",
            details={"current_state": o.state.value},
        )

    # OrderManager 도입 전: task_id만 발급 (Phase 5 후속에서 실제 처리)
    task_id = uuid4()
    payload = OrderCancelTaskOut(task_id=task_id, estimated_seconds=5)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}
