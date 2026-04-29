"""TrackedStocks REST endpoints (09_API_SPEC §3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from ...auth.dependencies import CurrentUserDep
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.trading import (
    StockSearchItem,
    StockSearchRequest,
    TrackedStockBoxOut,
    TrackedStockCreate,
    TrackedStockDetailOut,
    TrackedStockOut,
    TrackedStockPatch,
    TrackedStockPositionOut,
    TrackedStockSummaryOut,
)
from src.database.models_v71 import TrackedStatus, TrackedStock

from . import repo, service

router = APIRouter(prefix="/tracked_stocks", tags=["tracked_stocks"])
stocks_search_router = APIRouter(prefix="/stocks", tags=["tracked_stocks"])


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


def _to_out(ts: TrackedStock, summary: dict[str, Any]) -> TrackedStockOut:
    return TrackedStockOut(
        id=ts.id,
        stock_code=ts.stock_code,
        stock_name=ts.stock_name,
        market=ts.market,
        status=ts.status.value,
        user_memo=ts.user_memo,
        source=ts.source,
        vi_recovered_today=ts.vi_recovered_today,
        auto_exit_reason=ts.auto_exit_reason,
        created_at=ts.created_at,
        last_status_changed_at=ts.last_status_changed_at,
        summary=TrackedStockSummaryOut(**summary),
    )


def _parse_status(raw: str | None) -> TrackedStatus | None:
    if raw is None:
        return None
    try:
        return TrackedStatus(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid status filter",
            error_code="INVALID_PARAMETER",
            details={"field": "status", "value": raw},
        ) from exc


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if not cursor:
        return None, None
    try:
        c = PaginationCursor.decode(cursor)
        # sort_value is ISO-8601 UTC for tracked_stocks (sorted by created_at)
        return datetime.fromisoformat(c.sort_value), UUID(c.id)
    except Exception as exc:  # noqa: BLE001
        raise V71Error(
            "Invalid pagination cursor",
            error_code="INVALID_CURSOR",
            details={"cursor": cursor},
        ) from exc


def _encode_cursor(ts: TrackedStock) -> str:
    return PaginationCursor(id=str(ts.id), sort_value=ts.created_at.isoformat()).encode()


# Until P5.4.4 wires real user_settings, fall back to PRD example.
_DEFAULT_TOTAL_CAPITAL = Decimal(100_000_000)


# ---------------------------------------------------------------------
# GET /tracked_stocks (PRD §3.1)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_tracked_stocks(
    request: Request,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    status_q: str | None = Query(default=None, alias="status"),
    stock_code: str | None = Query(default=None, max_length=10),
    q: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="-created_at"),
) -> dict[str, Any]:
    sort_field = sort.lstrip("-")
    if sort_field not in {"created_at"}:
        # PRD §3.1 mentions other sort fields; we restrict to the
        # cursor-supported one for now and reject the rest explicitly.
        raise V71Error(
            "Unsupported sort field",
            error_code="INVALID_PARAMETER",
            details={"field": "sort", "value": sort},
        )
    sort_desc = sort.startswith("-")

    after_dt, after_id = _decode_cursor(cursor)
    rows, has_more = await service.list_tracked_stocks(
        session,
        status=_parse_status(status_q),
        stock_code=stock_code,
        q=q,
        limit=limit,
        sort_desc=sort_desc,
        after_created_at=after_dt,
        after_id=after_id,
        total_capital=_DEFAULT_TOTAL_CAPITAL,
    )
    data = [_to_out(ts, summary).model_dump(mode="json") for ts, summary in rows]
    next_cursor = _encode_cursor(rows[-1][0]) if has_more and rows else None

    meta = build_list_meta(
        request_id=request_id,
        limit=limit,
        next_cursor=next_cursor,
    )
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# POST /tracked_stocks (PRD §3.2)
# ---------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tracked_stock(
    body: TrackedStockCreate,
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    ts = await service.register_tracking(
        session,
        stock_code=body.stock_code,
        user_memo=body.user_memo,
        source=body.source,
        user_id=user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    summary = await repo.build_summary(
        session,
        tracked_stock_id=ts.id,
        total_capital=_DEFAULT_TOTAL_CAPITAL,
    )
    payload = _to_out(ts, summary).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /tracked_stocks/{id} (PRD §3.3)
# ---------------------------------------------------------------------


@router.get("/{tracked_stock_id}", status_code=status.HTTP_200_OK)
async def get_tracked_stock(
    tracked_stock_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    ts, summary = await service.get_detail(
        session,
        tracked_stock_id=tracked_stock_id,
        total_capital=_DEFAULT_TOTAL_CAPITAL,
    )
    base = _to_out(ts, summary).model_dump(mode="json")
    base["boxes"] = [
        TrackedStockBoxOut.model_validate(b).model_dump(mode="json")
        for b in ts.boxes
    ]
    base["positions"] = [
        TrackedStockPositionOut.model_validate(p).model_dump(mode="json")
        for p in ts.positions
    ]
    payload = TrackedStockDetailOut.model_validate(base).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# PATCH /tracked_stocks/{id} (PRD §3.4)
# ---------------------------------------------------------------------


@router.patch("/{tracked_stock_id}", status_code=status.HTTP_200_OK)
async def patch_tracked_stock(
    tracked_stock_id: UUID,
    body: TrackedStockPatch,
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    ts = await service.update_memo(
        session,
        tracked_stock_id=tracked_stock_id,
        user_memo=body.user_memo,
        source=body.source,
        user_id=user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    summary = await repo.build_summary(
        session,
        tracked_stock_id=ts.id,
        total_capital=_DEFAULT_TOTAL_CAPITAL,
    )
    payload = _to_out(ts, summary).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# DELETE /tracked_stocks/{id} (PRD §3.5)
# ---------------------------------------------------------------------


@router.delete("/{tracked_stock_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tracked_stock(
    tracked_stock_id: UUID,
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
) -> Response:
    await service.stop_tracking(
        session,
        tracked_stock_id=tracked_stock_id,
        user_id=user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# POST /stocks/search (PRD §3.6)
# ---------------------------------------------------------------------


@stocks_search_router.post("/search", status_code=status.HTTP_200_OK)
async def search_stocks(
    body: StockSearchRequest,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    rows = await repo.search_stocks(session, body.q)
    items = [
        StockSearchItem(
            stock_code=s.code,
            stock_name=s.name,
            market=s.market,
            current_price=None,  # TODO: P5.4.6 wires kiwoom price feed
            is_managed=s.is_managed,
            is_warning=s.is_warning,
        ).model_dump(mode="json")
        for s in rows
    ]
    return {"data": items, "meta": build_meta(request_id)}
