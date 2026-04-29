"""Position schemas (09_API_SPEC §5)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

PositionSourceLit = Literal["SYSTEM_A", "SYSTEM_B", "MANUAL"]
PositionStatusLit = Literal["OPEN", "PARTIAL_CLOSED", "CLOSED"]


class PositionOut(BaseModel):
    """09_API_SPEC §5.1."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    source: PositionSourceLit
    stock_code: str
    stock_name: str
    tracked_stock_id: UUID | None
    triggered_box_id: UUID | None

    initial_avg_price: Decimal
    weighted_avg_price: Decimal
    total_quantity: int

    fixed_stop_price: Decimal

    profit_5_executed: bool
    profit_10_executed: bool

    ts_activated: bool
    ts_base_price: Decimal | None
    ts_stop_price: Decimal | None
    ts_active_multiplier: Decimal | None

    actual_capital_invested: Decimal

    status: PositionStatusLit

    # ★ PRD Patch #5 (V7.1.0d, 2026-04-27): live-price columns.
    # Update: WebSocket 0B (<1s) > kt00018 (5s) > ka10001 (재시작).
    current_price: Decimal | None = None
    current_price_at: datetime | None = None
    pnl_amount: Decimal | None = None
    pnl_pct: Decimal | None = None

    closed_at: datetime | None
    final_pnl: Decimal | None
    close_reason: str | None

    created_at: datetime
    updated_at: datetime


class TradeEventInline(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    event_type: str
    price: Decimal | None
    quantity: int | None
    occurred_at: datetime


class EffectiveStopOut(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: float})

    fixed_stop: Decimal
    ts_stop: Decimal | None
    effective: Decimal
    should_exit: bool


class PositionDetailOut(PositionOut):
    events: list[TradeEventInline]
    effective_stop: EffectiveStopOut


class PositionSourceBreakdown(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: float})

    count: int
    capital: Decimal


class PositionStockAtLimit(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: float})

    stock_code: str
    actual_pct: Decimal
    limit_pct: Decimal


class PositionSummaryOut(BaseModel):
    """09_API_SPEC §5.3.

    Decimal 4 field는 ``field_serializer`` 로 JSON 직렬화 시 ``float`` 변환.
    Pydantic v2 default 는 ``Decimal -> str`` 인데, 프론트엔드가 ``toFixed()``
    호출 시 ``string.toFixed`` TypeError -> 컴포넌트 unmount -> 블랙 화면이
    되므로 number 직렬화로 강제. 정확성은 서버 내부 Decimal 연산에서 유지.
    """

    total_positions: int
    total_capital_invested: Decimal
    total_capital_pct: Decimal
    total_pnl_amount: Decimal
    total_pnl_pct: Decimal

    by_source: dict[str, PositionSourceBreakdown]
    by_status: dict[str, int]

    top_pnl: list[PositionOut]
    bottom_pnl: list[PositionOut]

    stocks_at_limit: list[PositionStockAtLimit]

    @field_serializer(
        "total_capital_invested",
        "total_capital_pct",
        "total_pnl_amount",
        "total_pnl_pct",
    )
    def _decimal_to_float(self, v: Decimal) -> float:
        return float(v)


class ReconcileTaskOut(BaseModel):
    """09_API_SPEC §5.4."""

    task_id: UUID
    started_at: datetime
    estimated_seconds: int
