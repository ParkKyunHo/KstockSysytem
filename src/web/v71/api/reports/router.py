"""Reports REST endpoints (09_API_SPEC §8)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...audit import record_audit
from ...auth.dependencies import CurrentUserDep
from ...db_models import AuditAction
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import BusinessRuleError, NotFoundError, V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.reports import (
    ReportOut,
    ReportPatch,
    ReportRequest,
    ReportRequestResponse,
)
from src.database.models_v71 import (
    DailyReport,
    ReportStatus,
    Stock,
    TrackedStock,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _to_out(r: DailyReport) -> ReportOut:
    elapsed: int | None = None
    if r.status == ReportStatus.GENERATING and r.generation_started_at:
        elapsed = int(
            (datetime.now(timezone.utc) - r.generation_started_at).total_seconds()
        )
    progress: int | None = None
    if r.status == ReportStatus.GENERATING:
        # PRD §8.2 progress 0-100. We expose elapsed-based estimate
        # (5min target) until P5.4.6 wires the real generator.
        if elapsed is not None:
            progress = max(0, min(99, int(elapsed / 300 * 100)))
        else:
            progress = 0
    return ReportOut(
        id=r.id,
        stock_code=r.stock_code,
        stock_name=r.stock_name,
        status=r.status.value,  # type: ignore[arg-type]
        model_version=r.model_version,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
        narrative_part=r.narrative_part,
        facts_part=r.facts_part,
        data_sources=r.data_sources,
        pdf_path=r.pdf_path,
        excel_path=r.excel_path,
        user_notes=r.user_notes,
        error_message=r.error_message,
        progress=progress,
        elapsed_seconds=elapsed,
        generation_started_at=r.generation_started_at,
        generation_completed_at=r.generation_completed_at,
        generation_duration_seconds=r.generation_duration_seconds,
        requested_at=r.requested_at,
        created_at=r.created_at,
        # ★ PRD Patch #5: soft-delete metadata
        is_hidden=r.is_hidden,
        hidden_at=r.hidden_at,
        hidden_reason=r.hidden_reason,
    )


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


# ---------------------------------------------------------------------
# POST /reports/request (PRD §8.1)
# ---------------------------------------------------------------------


@router.post("/request", status_code=status.HTTP_202_ACCEPTED)
async def request_report(
    body: ReportRequest,
    session: SessionDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    # PRD §8.1: stocks 마스터에서 종목 검증
    stock = await session.get(Stock, body.stock_code)
    if stock is None:
        raise BusinessRuleError(
            f"Unknown stock_code: {body.stock_code}",
            error_code="INVALID_STOCK_CODE",
        )

    r = DailyReport(
        stock_code=body.stock_code,
        stock_name=stock.name,
        tracked_stock_id=body.tracked_stock_id,
        requested_by=user.id,
        status=ReportStatus.PENDING,
    )
    session.add(r)
    await session.commit()

    await record_audit(
        action=AuditAction.REPORT_REQUESTED,
        user_id=user.id,
        target_type="daily_report",
        target_id=r.id,
        after_state={"stock_code": body.stock_code},
    )

    payload = ReportRequestResponse(
        report_id=r.id,
        status=r.status.value,  # type: ignore[arg-type]
        estimated_seconds=300,
        stock_code=r.stock_code,
        stock_name=r.stock_name,
        requested_at=r.requested_at,
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /reports (PRD §8.3)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_reports(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    stock_code: str | None = Query(default=None, max_length=10),
    status_q: str | None = Query(default=None, alias="status"),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    include_hidden: bool = Query(default=False),  # ★ PRD Patch #5
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    stmt = select(DailyReport)
    if stock_code is not None:
        stmt = stmt.where(DailyReport.stock_code == stock_code)
    if status_q is not None:
        try:
            stmt = stmt.where(DailyReport.status == ReportStatus(status_q))
        except ValueError as exc:
            raise V71Error(
                "Invalid status",
                error_code="INVALID_PARAMETER",
                details={"field": "status", "value": status_q},
            ) from exc
    if from_date is not None:
        stmt = stmt.where(DailyReport.requested_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(DailyReport.requested_at <= to_date)

    # ★ PRD Patch #5: 기본은 visible only (idx_reports_visible 부분 인덱스 활용)
    if not include_hidden:
        stmt = stmt.where(DailyReport.is_hidden == False)  # noqa: E712

    after_dt, after_id = _decode_cursor(cursor)
    if after_dt is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                DailyReport.requested_at < after_dt,
                (DailyReport.requested_at == after_dt) & (DailyReport.id < after_id),
            )
        )

    stmt = stmt.order_by(
        DailyReport.requested_at.desc(), DailyReport.id.desc()
    ).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [_to_out(r).model_dump(mode="json") for r in rows]
    next_cursor: str | None = None
    if has_more and rows:
        next_cursor = PaginationCursor(
            id=str(rows[-1].id),
            sort_value=rows[-1].requested_at.isoformat(),
        ).encode()
    meta = build_list_meta(request_id=request_id, limit=limit, next_cursor=next_cursor)
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# GET /reports/{id} (PRD §8.2)
# ---------------------------------------------------------------------


@router.get("/{report_id}", status_code=status.HTTP_200_OK)
async def get_report(
    report_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    r = await session.get(DailyReport, report_id)
    if r is None:
        raise NotFoundError(
            f"report {report_id} not found", error_code="REPORT_NOT_FOUND",
        )
    return {"data": _to_out(r).model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /reports/{id}/pdf  (PRD §8.4)
# ---------------------------------------------------------------------


@router.get("/{report_id}/pdf")
async def get_report_pdf(
    report_id: UUID,
    session: SessionDep,
    _user: CurrentUserDep,
) -> Response:
    r = await session.get(DailyReport, report_id)
    if r is None or r.pdf_path is None:
        raise NotFoundError(
            f"report pdf {report_id} not found", error_code="REPORT_NOT_FOUND",
        )
    if not os.path.isfile(r.pdf_path):
        raise NotFoundError("PDF file missing", error_code="REPORT_NOT_FOUND")
    filename = (
        f"report_{r.stock_code}_{r.requested_at.date().isoformat()}.pdf"
    )
    return FileResponse(
        path=r.pdf_path,
        media_type="application/pdf",
        filename=filename,
    )


# ---------------------------------------------------------------------
# GET /reports/{id}/excel  (PRD §8.5)
# ---------------------------------------------------------------------


@router.get("/{report_id}/excel")
async def get_report_excel(
    report_id: UUID,
    session: SessionDep,
    _user: CurrentUserDep,
) -> Response:
    r = await session.get(DailyReport, report_id)
    if r is None or r.excel_path is None:
        raise NotFoundError(
            f"report excel {report_id} not found",
            error_code="REPORT_NOT_FOUND",
        )
    if not os.path.isfile(r.excel_path):
        raise NotFoundError("Excel file missing", error_code="REPORT_NOT_FOUND")
    filename = (
        f"report_{r.stock_code}_{r.requested_at.date().isoformat()}.xlsx"
    )
    return FileResponse(
        path=r.excel_path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        filename=filename,
    )


# ---------------------------------------------------------------------
# PATCH /reports/{id} (PRD §8.6)
# ---------------------------------------------------------------------


@router.patch("/{report_id}", status_code=status.HTTP_200_OK)
async def patch_report(
    report_id: UUID,
    body: ReportPatch,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    r = await session.get(DailyReport, report_id)
    if r is None:
        raise NotFoundError(
            f"report {report_id} not found", error_code="REPORT_NOT_FOUND",
        )
    if body.user_notes is not None:
        r.user_notes = body.user_notes
    await session.commit()
    return {"data": _to_out(r).model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# DELETE /reports/{id} (PRD §8.7) — ★ PRD Patch #5: SOFT DELETE
# ---------------------------------------------------------------------


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> Response:
    """PRD Patch #5: 리포트 영구 보존 -- 실제 row 삭제 금지, is_hidden=true로만 표시.

    See 09_API_SPEC.md §8.7 + 13_APPENDIX.md §6.2.Z (한계 2 해결).
    """
    r = await session.get(DailyReport, report_id)
    if r is None:
        raise NotFoundError(
            f"report {report_id} not found", error_code="REPORT_NOT_FOUND",
        )
    r.is_hidden = True
    r.hidden_at = datetime.now(timezone.utc)
    r.hidden_reason = "USER_REQUEST"
    await session.commit()

    await record_audit(
        action=AuditAction.SETTINGS_CHANGED,  # generic audit; specific action in payload
        user_id=user.id,
        target_type="daily_report",
        target_id=str(report_id),
        before_state={"is_hidden": False},
        after_state={"is_hidden": True, "hidden_reason": "USER_REQUEST"},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# POST /reports/{id}/restore (PRD §8.8) — ★ PRD Patch #5: 숨긴 리포트 복구
# ---------------------------------------------------------------------


@router.post("/{report_id}/restore", status_code=status.HTTP_200_OK)
async def restore_report(
    report_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    user: CurrentUserDep,
) -> dict[str, Any]:
    """PRD Patch #5: 숨긴 리포트 복구.

    See 09_API_SPEC.md §8.8.
    """
    r = await session.get(DailyReport, report_id)
    if r is None:
        raise NotFoundError(
            f"report {report_id} not found", error_code="REPORT_NOT_FOUND",
        )
    if not r.is_hidden:
        raise BusinessRuleError(
            "이미 표시 중인 리포트는 복구할 필요 없습니다",
            error_code="REPORT_NOT_HIDDEN",
        )
    r.is_hidden = False
    r.hidden_at = None
    r.hidden_reason = None
    await session.commit()

    await record_audit(
        action=AuditAction.SETTINGS_CHANGED,
        user_id=user.id,
        target_type="daily_report",
        target_id=str(report_id),
        before_state={"is_hidden": True},
        after_state={"is_hidden": False},
    )
    return {"data": _to_out(r).model_dump(mode="json"), "meta": build_meta(request_id)}
