"""Trade event schemas (09_API_SPEC §6)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TradeEventOut(BaseModel):
    """09_API_SPEC §6.1."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position_id: UUID | None
    tracked_stock_id: UUID | None
    box_id: UUID | None
    stock_code: str
    stock_name: str | None = None  # filled by service via join
    event_type: str

    price: Decimal | None
    quantity: int | None

    order_id: str | None
    client_order_id: str | None
    attempt: int | None

    pnl_amount: Decimal | None
    pnl_pct: Decimal | None

    avg_price_before: Decimal | None
    avg_price_after: Decimal | None

    payload: dict[str, Any] | None
    reason: str | None
    error_message: str | None

    occurred_at: datetime


class TradeEventTodayBuy(BaseModel):
    stock_code: str
    quantity: int | None
    price: Decimal | None
    occurred_at: datetime


class TradeEventTodaySell(BaseModel):
    stock_code: str
    quantity: int | None
    price: Decimal | None
    pnl: Decimal | None
    pnl_pct: Decimal | None
    reason: str | None
    occurred_at: datetime


class TradeEventTodayOut(BaseModel):
    """09_API_SPEC §6.2."""

    date: date
    total_pnl: Decimal
    total_pnl_pct: Decimal | None

    buys: list[TradeEventTodayBuy]
    sells: list[TradeEventTodaySell]
    auto_exits: list[TradeEventTodaySell]
    manual_trades: list[TradeEventTodaySell]
