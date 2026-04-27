"""Order schemas (09_API_SPEC §13). ★ PRD Patch #5 (V7.1.0d, 2026-04-27).

Kiwoom REST API has no ``client_order_id`` field; V7.1 maintains its own
mapping via ``orders.kiwoom_order_no`` (UNIQUE) and
``orders.kiwoom_orig_order_no`` (정정/취소 시 원주문 추적).

See:
- 03_DATA_MODEL.md §2.4 (orders 테이블)
- 09_API_SPEC.md §13 (주문 API)
- 13_APPENDIX.md §6.2.Z (PRD Patch #5 결정 이력)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

OrderDirectionLit = Literal["BUY", "SELL"]
OrderStateLit = Literal["SUBMITTED", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"]
OrderTradeTypeLit = Literal[
    "LIMIT",
    "MARKET",
    "CONDITIONAL",
    "AFTER_HOURS",
    "BEST_LIMIT",
    "PRIORITY_LIMIT",
]


class OrderOut(BaseModel):
    """09_API_SPEC §13.1 GET /api/v71/orders item shape."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kiwoom_order_no: str
    kiwoom_orig_order_no: str | None = None

    position_id: UUID | None = None
    box_id: UUID | None = None
    tracked_stock_id: UUID | None = None

    stock_code: str
    direction: OrderDirectionLit
    trade_type: OrderTradeTypeLit
    quantity: int
    price: Decimal | None = None
    exchange: str = "KRX"

    state: OrderStateLit
    filled_quantity: int = 0
    filled_avg_price: Decimal | None = None

    reject_reason: str | None = None
    cancel_reason: str | None = None
    retry_attempt: int = 1

    submitted_at: datetime
    filled_at: datetime | None = None
    cancelled_at: datetime | None = None
    rejected_at: datetime | None = None


class OrderDetailOut(OrderOut):
    """09_API_SPEC §13.2 includes raw Kiwoom payloads (audit + debugging)."""

    kiwoom_raw_request: dict[str, Any] | None = None
    kiwoom_raw_response: dict[str, Any] | None = None


class OrderListParams(BaseModel):
    """09_API_SPEC §13.1 query params."""

    state: OrderStateLit | None = None
    position_id: UUID | None = None
    box_id: UUID | None = None
    stock_code: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
    sort: Literal["-submitted_at", "submitted_at"] = "-submitted_at"


class OrderCancelTaskOut(BaseModel):
    """09_API_SPEC §13.3 POST /orders/{id}/cancel response."""

    task_id: UUID
    estimated_seconds: int = 5
