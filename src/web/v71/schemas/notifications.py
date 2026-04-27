"""Notification schemas (09_API_SPEC §7)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NotificationSeverityLit = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
NotificationChannelLit = Literal["TELEGRAM", "WEB", "BOTH"]
NotificationStatusLit = Literal[
    "PENDING", "SENT", "FAILED", "SUPPRESSED", "EXPIRED"
]


class NotificationOut(BaseModel):
    """09_API_SPEC §7.1."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    severity: NotificationSeverityLit
    channel: NotificationChannelLit
    event_type: str
    stock_code: str | None
    title: str | None
    message: str
    payload: dict[str, Any] | None
    status: NotificationStatusLit
    sent_at: datetime | None
    created_at: datetime


class NotificationUnreadOut(BaseModel):
    """09_API_SPEC §7.2."""

    unread_count: int
    items: list[NotificationOut]


class NotificationTestRequest(BaseModel):
    """09_API_SPEC §7.4."""

    severity: NotificationSeverityLit = "MEDIUM"
    channel: NotificationChannelLit = "TELEGRAM"


class NotificationTestResponse(BaseModel):
    notification_id: UUID
    status: NotificationStatusLit
    sent_at: datetime | None = None
