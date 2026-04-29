"""Pydantic schemas for tracked_stocks / boxes / stocks.search.

Source of truth: ``docs/v71/09_API_SPEC.md §3, §4`` with PRD Patch #3
applied (path_type lives on Box, not TrackedStock).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------
# Enum-as-string values (mirror DB ENUMs)
# ---------------------------------------------------------------------

TrackedStatusLit = Literal[
    "TRACKING", "BOX_SET", "POSITION_OPEN", "POSITION_PARTIAL", "EXITED"
]
PathTypeLit = Literal["PATH_A", "PATH_B"]
BoxStatusLit = Literal["WAITING", "TRIGGERED", "INVALIDATED", "CANCELLED"]
StrategyTypeLit = Literal["PULLBACK", "BREAKOUT"]
PositionSourceLit = Literal["SYSTEM_A", "SYSTEM_B", "MANUAL"]
PositionStatusLit = Literal["OPEN", "PARTIAL_CLOSED", "CLOSED"]


# ---------------------------------------------------------------------
# tracked_stocks (PRD §3)
# ---------------------------------------------------------------------


class TrackedStockSummaryOut(BaseModel):
    """Per-stock aggregates (09_API_SPEC §3.1 -- PRD Patch #3)."""

    model_config = ConfigDict(json_encoders={Decimal: float})

    active_box_count: int
    path_a_box_count: int
    path_b_box_count: int
    triggered_box_count: int
    current_position_qty: int
    current_position_avg_price: Decimal | None
    total_position_pct: Decimal


class TrackedStockOut(BaseModel):
    """List item shape (09_API_SPEC §3.1)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    stock_code: str
    stock_name: str
    market: str | None
    status: TrackedStatusLit
    user_memo: str | None
    source: str | None
    vi_recovered_today: bool
    auto_exit_reason: str | None
    created_at: datetime
    last_status_changed_at: datetime
    summary: TrackedStockSummaryOut


class TrackedStockBoxOut(BaseModel):
    """Box shape inside ``GET /tracked_stocks/{id}`` (09_API_SPEC §3.3)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    path_type: PathTypeLit
    box_tier: int
    upper_price: Decimal
    lower_price: Decimal
    position_size_pct: Decimal
    stop_loss_pct: Decimal
    strategy_type: StrategyTypeLit
    status: BoxStatusLit
    created_at: datetime


class TrackedStockPositionOut(BaseModel):
    """Position shape inside ``GET /tracked_stocks/{id}`` (09_API_SPEC §3.3)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    source: PositionSourceLit
    weighted_avg_price: Decimal
    total_quantity: int
    status: PositionStatusLit


class TrackedStockDetailOut(TrackedStockOut):
    boxes: list[TrackedStockBoxOut]
    positions: list[TrackedStockPositionOut]


class TrackedStockCreate(BaseModel):
    """09_API_SPEC §3.2. PRD Patch #3 -- no path_type here."""

    stock_code: str = Field(min_length=6, max_length=10, pattern=r"^\d{6,10}$")
    user_memo: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=50)


class TrackedStockPatch(BaseModel):
    """09_API_SPEC §3.4 -- only memo/source mutable."""

    user_memo: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=50)


# ---------------------------------------------------------------------
# stocks.search (PRD §3.6)
# ---------------------------------------------------------------------


class StockSearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=50)


class StockSearchItem(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    stock_code: str
    stock_name: str
    market: str | None
    current_price: Decimal | None = None
    is_managed: bool = False
    is_warning: bool = False


# ---------------------------------------------------------------------
# boxes (PRD §4)
# ---------------------------------------------------------------------


class BoxOut(BaseModel):
    """List + create response (09_API_SPEC §4.1, §4.2)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={Decimal: float},
    )

    id: UUID
    tracked_stock_id: UUID
    stock_code: str
    stock_name: str
    path_type: PathTypeLit
    box_tier: int
    upper_price: Decimal
    lower_price: Decimal
    position_size_pct: Decimal
    stop_loss_pct: Decimal
    strategy_type: StrategyTypeLit
    status: BoxStatusLit
    memo: str | None
    created_at: datetime
    modified_at: datetime
    triggered_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    last_reminder_at: datetime | None = None
    entry_proximity_pct: Decimal | None = None  # populated by service when known


class BoxCreate(BaseModel):
    """09_API_SPEC §4.1. PRD Patch #3 -- path_type required."""

    tracked_stock_id: UUID
    path_type: PathTypeLit
    upper_price: Decimal = Field(gt=0)
    lower_price: Decimal = Field(gt=0)
    position_size_pct: Decimal = Field(gt=0, le=100)
    stop_loss_pct: Decimal = Field(default=Decimal("-0.05"), lt=0)
    strategy_type: StrategyTypeLit
    memo: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check_prices(self) -> "BoxCreate":
        if self.upper_price <= self.lower_price:
            from ..exceptions import V71Error

            raise V71Error(
                "Box upper price must be greater than lower price",
                error_code="VALIDATION_FAILED",
                details={
                    "fields": [
                        {
                            "field": "upper_price",
                            "value": str(self.upper_price),
                            "constraint": f"> lower_price (= {self.lower_price})",
                        }
                    ]
                },
            )
        return self


class BoxPatch(BaseModel):
    """09_API_SPEC §4.4 -- WAITING boxes editable."""

    upper_price: Decimal | None = Field(default=None, gt=0)
    lower_price: Decimal | None = Field(default=None, gt=0)
    position_size_pct: Decimal | None = Field(default=None, gt=0, le=100)
    stop_loss_pct: Decimal | None = Field(default=None, lt=0)
    memo: str | None = Field(default=None, max_length=2000)
