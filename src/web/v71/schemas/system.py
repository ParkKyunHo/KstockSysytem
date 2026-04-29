"""System schemas (09_API_SPEC §9)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WebsocketStatus(BaseModel):
    connected: bool
    last_disconnect_at: datetime | None = None
    reconnect_count_today: int = 0


class KiwoomApiStatus(BaseModel):
    available: bool
    rate_limit_used_per_sec: float = 0.0
    rate_limit_max: float = 4.5


class TelegramBotStatus(BaseModel):
    active: bool
    circuit_breaker_state: Literal["CLOSED", "OPEN", "HALF_OPEN"] = "CLOSED"


class DatabaseStatus(BaseModel):
    connected: bool
    latency_ms: int = 0


class MarketStatus(BaseModel):
    is_open: bool
    session: Literal["PRE", "REGULAR", "POST"] | None = None
    next_open_at: datetime | None = None
    next_close_at: datetime | None = None


class AccountSnapshot(BaseModel):
    """Real Kiwoom account total (kt00018 총평가금액, 5분 TTL cache).

    박스 wizard 가 비중 (%) 입력 시 실제 잔고 대비 매수 규모를 표시하기
    위해 노출. ``None`` 인 경우는 buy_executor 비활성 또는 키움 fetch 실패
    -- frontend 는 fallback 메시지 처리.
    """

    total_capital: float | None = None


SystemStatusLit = Literal["RUNNING", "SAFE_MODE", "RECOVERING"]


class SystemStatusOut(BaseModel):
    """09_API_SPEC §9.1."""

    status: SystemStatusLit
    uptime_seconds: int

    websocket: WebsocketStatus
    kiwoom_api: KiwoomApiStatus
    telegram_bot: TelegramBotStatus
    database: DatabaseStatus

    feature_flags: dict[str, bool]

    market: MarketStatus
    current_time: datetime

    # 비중 결정 UX (BoxWizard) 에 사용하는 실제 계좌 잔고. 노출 안 됐다면
    # 키움 미연결 또는 fetch 실패. 없을 시 None.
    account: AccountSnapshot = AccountSnapshot()


class SystemHealthOut(BaseModel):
    """09_API_SPEC §9.2."""

    status: Literal["healthy", "degraded"]
    checks: dict[str, Literal["ok", "fail"]]
    details: dict[str, str] | None = None


class SafeModeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SafeModeResponse(BaseModel):
    safe_mode: bool
    entered_at: datetime | None = None
    resumed_at: datetime | None = None


class SystemRestartOut(BaseModel):
    """09_API_SPEC §9.5."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restart_at: datetime
    recovery_completed_at: datetime | None
    recovery_duration_seconds: int | None
    reason: str | None
    reason_detail: str | None
    reconciliation_summary: dict[str, Any] | None
    cancelled_orders_count: int


TaskStatusLit = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]


class AsyncTaskOut(BaseModel):
    """09_API_SPEC §9.6."""

    task_id: UUID
    type: str
    status: TaskStatusLit
    progress: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class BoxEntryMissResponse(BaseModel):
    """09_API_SPEC §9.7."""

    task_id: UUID
    checked_stocks: int = 0
    found_misses: int = 0
