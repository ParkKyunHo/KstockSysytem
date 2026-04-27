"""Common response envelopes and pagination helpers (09_API_SPEC §2)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiMeta(BaseModel):
    """Meta block included in every response (09_API_SPEC §2.1)."""

    request_id: str
    timestamp: str  # ISO 8601 UTC


class ApiListMeta(ApiMeta):
    """Meta block for list responses with cursor pagination."""

    total: int | None = None
    limit: int = 20
    next_cursor: str | None = None
    prev_cursor: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Single-resource envelope. Usage: ``ApiResponse[StockOut](data=..., meta=...)``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: T
    meta: ApiMeta


class ApiListResponse(BaseModel, Generic[T]):
    """List envelope with cursor pagination."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: list[T]
    meta: ApiListMeta


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_meta(request_id: str | None = None) -> dict[str, str]:
    """Helper to assemble the ``meta`` block when assembling raw payloads."""
    return {
        "request_id": request_id or uuid4().hex,
        "timestamp": _now_iso(),
    }


def build_list_meta(
    *,
    request_id: str,
    limit: int,
    total: int | None = None,
    next_cursor: str | None = None,
    prev_cursor: str | None = None,
) -> ApiListMeta:
    return ApiListMeta(
        request_id=request_id,
        timestamp=_now_iso(),
        total=total,
        limit=limit,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
    )


# ---------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------


class PaginationCursor(BaseModel):
    """Opaque cursor encoded as Base64(JSON({"id": ..., "sort": ...}))."""

    id: str
    sort_value: str = Field(description="Encoded last-seen sort key")

    def encode(self) -> str:
        raw = json.dumps(self.model_dump(), separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii")

    @classmethod
    def decode(cls, value: str) -> "PaginationCursor":
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii"))
            return cls.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 -- bubble as 400
            from ..exceptions import V71Error

            raise V71Error(
                "Invalid pagination cursor",
                details={"cursor": value},
                error_code="INVALID_CURSOR",
            ) from exc
