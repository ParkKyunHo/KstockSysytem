"""Boxes REST endpoints (09_API_SPEC §4)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from src.database.models_v71 import (
    BoxStatus,
    PathType,
    StrategyType,
    SupportBox,
)

from ...auth.dependencies import CurrentUserDep
from ...dependencies import BoxManagerDep, RequestIdDep, SessionDep
from ...exceptions import V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.trading import BoxCreate, BoxOut, BoxPatch
from . import repo, service

router = APIRouter(prefix="/boxes", tags=["boxes"])

# Until P5.4.4 wires real user_settings, fall back to PRD example.
_DEFAULT_TOTAL_CAPITAL = Decimal(100_000_000)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _to_out(box: SupportBox) -> BoxOut:
    return BoxOut(
        id=box.id,
        tracked_stock_id=box.tracked_stock_id,
        stock_code=box.tracked_stock.stock_code if box.tracked_stock else "",
        stock_name=box.tracked_stock.stock_name if box.tracked_stock else "",
        path_type=box.path_type.value,
        box_tier=box.box_tier,
        upper_price=box.upper_price,
        lower_price=box.lower_price,
        position_size_pct=box.position_size_pct,
        stop_loss_pct=box.stop_loss_pct,
        strategy_type=box.strategy_type.value,
        status=box.status.value,
        memo=box.memo,
        created_at=box.created_at,
        modified_at=box.modified_at,
        triggered_at=box.triggered_at,
        invalidated_at=box.invalidated_at,
        invalidation_reason=box.invalidation_reason,
        last_reminder_at=box.last_reminder_at,
    )


def _parse_path(raw: str | None) -> PathType | None:
    if raw is None:
        return None
    try:
        return PathType(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid path_type",
            error_code="INVALID_PARAMETER",
            details={"field": "path_type", "value": raw},
        ) from exc


def _parse_status(raw: str | None) -> BoxStatus | None:
    if raw is None:
        return None
    try:
        return BoxStatus(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid status",
            error_code="INVALID_PARAMETER",
            details={"field": "status", "value": raw},
        ) from exc


def _parse_strategy(raw: str | None) -> StrategyType | None:
    if raw is None:
        return None
    try:
        return StrategyType(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid strategy_type",
            error_code="INVALID_PARAMETER",
            details={"field": "strategy_type", "value": raw},
        ) from exc


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if not cursor:
        return None, None
    try:
        c = PaginationCursor.decode(cursor)
        return datetime.fromisoformat(c.sort_value), UUID(c.id)
    except Exception as exc:  # noqa: BLE001
        raise V71Error(
            "Invalid pagination cursor",
            error_code="INVALID_CURSOR",
            details={"cursor": cursor},
        ) from exc


def _encode_cursor(box: SupportBox) -> str:
    return PaginationCursor(
        id=str(box.id), sort_value=box.created_at.isoformat()
    ).encode()


# ---------------------------------------------------------------------
# POST /boxes (PRD §4.1)
# ---------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_box(
    body: BoxCreate,
    request: Request,
    session: SessionDep,
    box_manager: BoxManagerDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    box = await service.create_box(
        session,
        box_manager=box_manager,
        tracked_stock_id=body.tracked_stock_id,
        path_type=PathType(body.path_type),
        upper_price=body.upper_price,
        lower_price=body.lower_price,
        position_size_pct=body.position_size_pct,
        stop_loss_pct=body.stop_loss_pct,
        strategy_type=StrategyType(body.strategy_type),
        memo=body.memo,
        user_id=user.id,
        total_capital=_DEFAULT_TOTAL_CAPITAL,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    # Fresh load (relationship needed for stock_code/name).
    await session.refresh(box, attribute_names=["tracked_stock"])
    payload = _to_out(box).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /boxes (PRD §4.2)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_boxes(
    request: Request,  # noqa: ARG001 -- kept for symmetry with create/patch
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    tracked_stock_id: UUID | None = Query(default=None),
    path_type: str | None = Query(default=None),
    status_q: str | None = Query(default=None, alias="status"),
    strategy_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="-created_at"),
) -> dict[str, Any]:
    sort_field = sort.lstrip("-")
    if sort_field not in {"created_at"}:
        raise V71Error(
            "Unsupported sort field",
            error_code="INVALID_PARAMETER",
            details={"field": "sort", "value": sort},
        )
    sort_desc = sort.startswith("-")

    after_dt, after_id = _decode_cursor(cursor)
    rows = await repo.list_boxes(
        session,
        tracked_stock_id=tracked_stock_id,
        path_type=_parse_path(path_type),
        status=_parse_status(status_q),
        strategy_type=_parse_strategy(strategy_type),
        limit=limit,
        sort_desc=sort_desc,
        after_created_at=after_dt,
        after_id=after_id,
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    # Pre-load parents so _to_out can read stock_code/name.
    for box in rows:
        await session.refresh(box, attribute_names=["tracked_stock"])

    data = [_to_out(b).model_dump(mode="json") for b in rows]
    next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None

    meta = build_list_meta(
        request_id=request_id,
        limit=limit,
        next_cursor=next_cursor,
    )
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# GET /boxes/{id} (PRD §4.3)
# ---------------------------------------------------------------------


@router.get("/{box_id}", status_code=status.HTTP_200_OK)
async def get_box(
    box_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    box = await repo.get_by_id(session, box_id)
    if box is None:
        raise V71Error(
            "Box not found",
            error_code="BOX_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    await session.refresh(box, attribute_names=["tracked_stock"])
    payload = _to_out(box).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# PATCH /boxes/{id} (PRD §4.4)
# ---------------------------------------------------------------------


@router.patch("/{box_id}", status_code=status.HTTP_200_OK)
async def patch_box(
    box_id: UUID,
    body: BoxPatch,
    request: Request,
    session: SessionDep,
    box_manager: BoxManagerDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
    response: Response,
) -> dict[str, Any]:
    box, warnings = await service.patch_box(
        session,
        box_manager=box_manager,
        box_id=box_id,
        upper_price=body.upper_price,
        lower_price=body.lower_price,
        position_size_pct=body.position_size_pct,
        stop_loss_pct=body.stop_loss_pct,
        memo=body.memo,
        user_id=user.id,
        total_capital=_DEFAULT_TOTAL_CAPITAL,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    if warnings:
        # PRD §4.4 -- 손절폭 완화 등 경고는 X-Warning 헤더로.
        response.headers["X-Warning"] = ",".join(warnings)
    await session.refresh(box, attribute_names=["tracked_stock"])
    payload = _to_out(box).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# DELETE /boxes/{id} (PRD §4.5)
# ---------------------------------------------------------------------


@router.delete("/{box_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_box(
    box_id: UUID,
    request: Request,
    session: SessionDep,
    box_manager: BoxManagerDep,
    user: CurrentUserDep,
) -> Response:
    await service.delete_box(
        session,
        box_manager=box_manager,
        box_id=box_id,
        user_id=user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
