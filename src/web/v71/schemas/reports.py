"""Report schemas (09_API_SPEC §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReportStatusLit = Literal["PENDING", "GENERATING", "COMPLETED", "FAILED"]


class ReportRequest(BaseModel):
    """09_API_SPEC §8.1."""

    stock_code: str = Field(min_length=6, max_length=10, pattern=r"^\d{6,10}$")
    tracked_stock_id: UUID | None = None


class ReportRequestResponse(BaseModel):
    report_id: UUID
    status: ReportStatusLit
    estimated_seconds: int = 300
    stock_code: str
    stock_name: str
    requested_at: datetime


class ReportOut(BaseModel):
    """09_API_SPEC §8.2 + §8.3."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    stock_code: str
    stock_name: str
    status: ReportStatusLit
    model_version: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    narrative_part: str | None = None
    facts_part: str | None = None
    data_sources: dict[str, Any] | None = None
    pdf_path: str | None = None
    excel_path: str | None = None
    user_notes: str | None = None
    error_message: str | None = None
    progress: int | None = None  # populated when GENERATING
    elapsed_seconds: int | None = None
    generation_started_at: datetime | None = None
    generation_completed_at: datetime | None = None
    generation_duration_seconds: int | None = None
    requested_at: datetime
    created_at: datetime

    # ★ PRD Patch #5 (V7.1.0d, 2026-04-27): soft-delete metadata.
    is_hidden: bool = False
    hidden_at: datetime | None = None
    hidden_reason: str | None = None


class ReportPatch(BaseModel):
    """09_API_SPEC §8.6 -- user_notes only."""

    user_notes: str | None = Field(default=None, max_length=10000)


class ReportListParams(BaseModel):
    """09_API_SPEC §8.3 query params (PRD Patch #5: include_hidden 추가)."""

    stock_code: str | None = None
    status: ReportStatusLit | None = None
    from_date: str | None = None
    to_date: str | None = None
    include_hidden: bool = False  # ★ PRD Patch #5
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
