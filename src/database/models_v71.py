"""V7.1 SQLAlchemy 2.0 declarative models.

Shares the same :class:`Base` as ``src.database.models`` so the existing
``DatabaseManager.create_all`` flow registers V7.1 tables alongside the
legacy V7.0 ones (per ``03_DATA_MODEL.md §0.1`` -- V7.0 호환, V7.1 추가만).

The migrations in ``src/database/migrations/v71/*.up.sql`` remain the
**source of truth** in production. This module mirrors them for
SQLAlchemy ORM access; mismatches must be reconciled toward the
migrations.

Currently modelled (P5.4.2):

* ``users``                (001_create_users.up.sql)
* ``user_sessions``        (002_create_user_sessions.up.sql)
* ``user_settings``        (003_create_user_settings.up.sql)
* ``audit_logs``           (004_create_audit_logs.up.sql)

Later sub-phases (P5.4.3+) add tracked_stocks, support_boxes, positions,
trade_events, notifications, daily_reports, etc.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import INET as PG_INET
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.models import Base

# Cross-database type aliases. PostgreSQL uses native INET/JSONB/UUID;
# SQLite (test/fallback) gets sane VARCHAR/JSON equivalents so the
# DatabaseManager fallback path keeps working.
_INET = PG_INET().with_variant(String(45), "sqlite")
_JSONB = PG_JSONB().with_variant(JSON, "sqlite")


# ---------------------------------------------------------------------
# Enums (mirror migrations 004 audit_action ENUM exactly)
# ---------------------------------------------------------------------


class AuditAction(str, Enum):
    """Mirrors PostgreSQL ENUM ``audit_action`` (migration 004)."""

    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    TOTP_ENABLED = "TOTP_ENABLED"
    TOTP_DISABLED = "TOTP_DISABLED"
    NEW_IP_DETECTED = "NEW_IP_DETECTED"
    BOX_CREATED = "BOX_CREATED"
    BOX_MODIFIED = "BOX_MODIFIED"
    BOX_DELETED = "BOX_DELETED"
    TRACKING_REGISTERED = "TRACKING_REGISTERED"
    TRACKING_REMOVED = "TRACKING_REMOVED"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    REPORT_REQUESTED = "REPORT_REQUESTED"
    API_KEY_ROTATED = "API_KEY_ROTATED"


# ---------------------------------------------------------------------
# users (migration 001)
# ---------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    totp_secret: Mapped[str | None] = mapped_column(String(100))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    backup_codes: Mapped[list[str] | None] = mapped_column(JSON)

    telegram_chat_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(50))

    role: Mapped[str] = mapped_column(String(20), default="OWNER", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_ip: Mapped[str | None] = mapped_column(_INET)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    settings: Mapped[UserSettings | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------
# user_sessions (migration 002)
# ---------------------------------------------------------------------


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    access_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    ip_address: Mapped[str | None] = mapped_column(_INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    access_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    refresh_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="sessions")


# ---------------------------------------------------------------------
# user_settings (migration 003)
# ---------------------------------------------------------------------


class UserSettings(Base):
    """1:1 with users -- ``notify_critical`` may NOT be turned off (app lock)."""

    __tablename__ = "user_settings"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    total_capital: Mapped[Decimal | None] = mapped_column(Numeric(15, 0))

    notify_critical: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_high: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_medium: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_low: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quiet_hours_start: Mapped[Any | None] = mapped_column(Time)
    quiet_hours_end: Mapped[Any | None] = mapped_column(Time)

    theme: Mapped[str] = mapped_column(String(20), default="dark", nullable=False)
    language: Mapped[str] = mapped_column(String(5), default="ko", nullable=False)

    preferences: Mapped[dict[str, Any] | None] = mapped_column(_JSONB, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship(back_populates="settings")


# ---------------------------------------------------------------------
# audit_logs (migration 004)
# ---------------------------------------------------------------------


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id"),
        index=True,
    )

    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(
            AuditAction,
            name="audit_action",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
        index=True,
    )

    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[UUID | None] = mapped_column(Uuid)

    before_state: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    ip_address: Mapped[str | None] = mapped_column(_INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )


# ---------------------------------------------------------------------
# stocks (master, migration 006) -- PRD 03_DATA_MODEL §6.2
# ---------------------------------------------------------------------


class Stock(Base):
    """Master cache of listable stocks (search + flag lookups)."""

    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    market: Mapped[str | None] = mapped_column(String(20))
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))

    is_listed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_warning: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_alert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_danger: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    name_normalized: Mapped[str | None] = mapped_column(String(100))

    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


# ---------------------------------------------------------------------
# market_calendar (mirrors migration 005 -- PRD §6.1)
# ---------------------------------------------------------------------


class MarketDayType(str, Enum):
    """KRX market day classification (matches migration 005 ENUM)."""

    TRADING = "TRADING"
    HOLIDAY = "HOLIDAY"
    HALF_DAY = "HALF_DAY"
    EMERGENCY_CLOSED = "EMERGENCY_CLOSED"


class MarketCalendar(Base):
    """Master KRX schedule (operator-managed via dashboard or SQL).

    Spec: ``docs/v71/03_DATA_MODEL.md`` §6.1 + migration 005. The
    repository layer (``src/database/repositories/v71/...``) reads this
    on attach and seeds the in-memory ``V71MarketSchedule`` so the
    bar-completion path can short-circuit on holidays without touching
    the DB on every check.
    """

    __tablename__ = "market_calendar"

    trading_date: Mapped[date] = mapped_column(Date, primary_key=True)
    day_type: Mapped[MarketDayType] = mapped_column(
        SQLEnum(MarketDayType, name="market_day_type"), nullable=False,
    )
    market_open_time: Mapped[time | None] = mapped_column(Time)
    market_close_time: Mapped[time | None] = mapped_column(Time)
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


# ---------------------------------------------------------------------
# Trading enums (mirror migrations 007/008/009)
# ---------------------------------------------------------------------


class TrackedStatus(str, Enum):
    TRACKING = "TRACKING"
    BOX_SET = "BOX_SET"
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_PARTIAL = "POSITION_PARTIAL"
    EXITED = "EXITED"


class PathType(str, Enum):
    PATH_A = "PATH_A"
    PATH_B = "PATH_B"


class BoxStatus(str, Enum):
    WAITING = "WAITING"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class StrategyType(str, Enum):
    PULLBACK = "PULLBACK"
    BREAKOUT = "BREAKOUT"


class PositionSource(str, Enum):
    SYSTEM_A = "SYSTEM_A"
    SYSTEM_B = "SYSTEM_B"
    MANUAL = "MANUAL"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL_CLOSED = "PARTIAL_CLOSED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------
# tracked_stocks (migration 007 + PRD Patch #3 -- path_type removed)
# ---------------------------------------------------------------------


class TrackedStock(Base):
    """User-tracked stock. PRD Patch #3: path_type lives on boxes now."""

    __tablename__ = "tracked_stocks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str | None] = mapped_column(String(20))

    status: Mapped[TrackedStatus] = mapped_column(
        SQLEnum(
            TrackedStatus,
            name="tracked_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=TrackedStatus.TRACKING,
        nullable=False,
        index=True,
    )

    user_memo: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))

    vi_recovered_today: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vi_recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    auto_exit_reason: Mapped[str | None] = mapped_column(String(50))
    auto_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    boxes: Mapped[list[SupportBox]] = relationship(
        back_populates="tracked_stock",
        cascade="all, delete-orphan",
    )
    positions: Mapped[list[V71Position]] = relationship(
        back_populates="tracked_stock",
    )


# ---------------------------------------------------------------------
# support_boxes (migration 008 + PRD Patch #3 -- path_type required)
# ---------------------------------------------------------------------


class SupportBox(Base):
    __tablename__ = "support_boxes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    tracked_stock_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracked_stocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # PRD Patch #3 -- required
    path_type: Mapped[PathType] = mapped_column(
        SQLEnum(
            PathType,
            name="path_type",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
        index=True,
    )

    box_tier: Mapped[int] = mapped_column(nullable=False)
    upper_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    lower_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)

    position_size_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    stop_loss_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), default=Decimal("-0.05"), nullable=False,
    )

    strategy_type: Mapped[StrategyType] = mapped_column(
        SQLEnum(
            StrategyType,
            name="strategy_type",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
    )

    status: Mapped[BoxStatus] = mapped_column(
        SQLEnum(
            BoxStatus,
            name="box_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=BoxStatus.WAITING,
        nullable=False,
        index=True,
    )

    memo: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    modified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invalidation_reason: Mapped[str | None] = mapped_column(String(100))

    tracked_stock: Mapped[TrackedStock] = relationship(back_populates="boxes")


# ---------------------------------------------------------------------
# positions (migration 009)
# ---------------------------------------------------------------------


class V71Position(Base):
    __tablename__ = "positions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    source: Mapped[PositionSource] = mapped_column(
        SQLEnum(
            PositionSource,
            name="position_source",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
        index=True,
    )

    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)

    tracked_stock_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tracked_stocks.id"), index=True,
    )
    triggered_box_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("support_boxes.id"),
    )

    initial_avg_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    weighted_avg_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)
    total_quantity: Mapped[int] = mapped_column(nullable=False)

    fixed_stop_price: Mapped[Decimal] = mapped_column(Numeric(12, 0), nullable=False)

    profit_5_executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    profit_10_executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    ts_activated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ts_base_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))
    ts_stop_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))
    ts_active_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))

    status: Mapped[PositionStatus] = mapped_column(
        SQLEnum(
            PositionStatus,
            name="position_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=PositionStatus.OPEN,
        nullable=False,
        index=True,
    )

    actual_capital_invested: Mapped[Decimal] = mapped_column(Numeric(15, 0), nullable=False)

    # ★ PRD Patch #5 (V7.1.0d, 2026-04-27): live-price columns (migration 019).
    # Update policy: WebSocket 0B (<1s) > kt00018 (5s) > ka10001 (재시작).
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))
    current_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pnl_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 0))
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_pnl: Mapped[Decimal | None] = mapped_column(Numeric(15, 0))
    final_pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    close_reason: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tracked_stock: Mapped[TrackedStock | None] = relationship(back_populates="positions")


# ---------------------------------------------------------------------
# trade_events (migration 010) -- audit trail
# ---------------------------------------------------------------------


class TradeEventType(str, Enum):
    BUY_EXECUTED = "BUY_EXECUTED"
    PYRAMID_BUY = "PYRAMID_BUY"
    MANUAL_BUY = "MANUAL_BUY"
    MANUAL_PYRAMID_BUY = "MANUAL_PYRAMID_BUY"
    PROFIT_TAKE_5 = "PROFIT_TAKE_5"
    PROFIT_TAKE_10 = "PROFIT_TAKE_10"
    STOP_LOSS = "STOP_LOSS"
    TS_EXIT = "TS_EXIT"
    MANUAL_PARTIAL_EXIT = "MANUAL_PARTIAL_EXIT"
    MANUAL_FULL_EXIT = "MANUAL_FULL_EXIT"
    AUTO_EXIT = "AUTO_EXIT"
    ORDER_SENT = "ORDER_SENT"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_PARTIAL_FILLED = "ORDER_PARTIAL_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_FAILED = "ORDER_FAILED"
    POSITION_RECONCILED = "POSITION_RECONCILED"
    EVENT_RESET = "EVENT_RESET"
    STOP_UPDATED = "STOP_UPDATED"
    TS_ACTIVATED = "TS_ACTIVATED"
    TS_VALIDATED = "TS_VALIDATED"


class TradeEvent(Base):
    __tablename__ = "trade_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    position_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("positions.id"), index=True,
    )
    tracked_stock_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tracked_stocks.id"), index=True,
    )
    box_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("support_boxes.id"),
    )

    event_type: Mapped[TradeEventType] = mapped_column(
        SQLEnum(
            TradeEventType,
            name="trade_event_type",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
        index=True,
    )

    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))
    quantity: Mapped[int | None] = mapped_column()

    order_id: Mapped[str | None] = mapped_column(String(50))
    client_order_id: Mapped[str | None] = mapped_column(String(50))
    attempt: Mapped[int | None] = mapped_column()

    pnl_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 0))
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    avg_price_before: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))
    avg_price_after: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))

    payload: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    reason: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


# ---------------------------------------------------------------------
# notifications (migration 014) -- priority queue + history
# ---------------------------------------------------------------------


class NotificationSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NotificationChannel(str, Enum):
    TELEGRAM = "TELEGRAM"
    WEB = "WEB"
    BOTH = "BOTH"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"
    EXPIRED = "EXPIRED"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    severity: Mapped[NotificationSeverity] = mapped_column(
        SQLEnum(
            NotificationSeverity,
            name="notification_severity",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        SQLEnum(
            NotificationChannel,
            name="notification_channel",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    stock_code: Mapped[str | None] = mapped_column(String(10), index=True)

    title: Mapped[str | None] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    status: Mapped[NotificationStatus] = mapped_column(
        SQLEnum(
            NotificationStatus,
            name="notification_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=NotificationStatus.PENDING,
        nullable=False,
        index=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)

    rate_limit_key: Mapped[str | None] = mapped_column(String(100))

    # 1=CRITICAL, 2=HIGH, 3=MEDIUM, 4=LOW (lower = sent first).
    priority: Mapped[int] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------
# daily_reports (migration 015)
# ---------------------------------------------------------------------


class ReportStatus(str, Enum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    stock_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)

    tracked_stock_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tracked_stocks.id"),
    )

    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )

    generation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_duration_seconds: Mapped[int | None] = mapped_column()

    model_version: Mapped[str] = mapped_column(
        String(50), default="claude-opus-4-7", nullable=False,
    )
    prompt_tokens: Mapped[int | None] = mapped_column()
    completion_tokens: Mapped[int | None] = mapped_column()

    status: Mapped[ReportStatus] = mapped_column(
        SQLEnum(
            ReportStatus,
            name="report_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=ReportStatus.PENDING,
        nullable=False,
        index=True,
    )

    narrative_part: Mapped[str | None] = mapped_column(Text)
    facts_part: Mapped[str | None] = mapped_column(Text)

    data_sources: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)

    pdf_path: Mapped[str | None] = mapped_column(String(500))
    excel_path: Mapped[str | None] = mapped_column(String(500))

    user_notes: Mapped[str | None] = mapped_column(Text)

    error_message: Mapped[str | None] = mapped_column(Text)

    # ★ PRD Patch #5 (V7.1.0d, 2026-04-27): soft-delete (migration 020).
    # DELETE /api/v71/reports/{id} sets is_hidden=TRUE; reports are never row-deleted.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_reason: Mapped[str | None] = mapped_column(String(50))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------
# orders (migration 018) -- ★ PRD Patch #5 (V7.1.0d, 2026-04-27)
#
# Kiwoom REST API has no client_order_id field; V7.1 maintains its own
# mapping via kiwoom_order_no (UNIQUE) and kiwoom_orig_order_no (정정/취소
# 시 원주문 추적). See docs/v71/13_APPENDIX.md §6.2.Z.
# ---------------------------------------------------------------------


class OrderDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderTradeType(str, Enum):
    LIMIT = "LIMIT"                    # 키움 trde_tp=0
    MARKET = "MARKET"                  # 키움 trde_tp=3
    CONDITIONAL = "CONDITIONAL"        # 키움 trde_tp=5
    AFTER_HOURS = "AFTER_HOURS"        # 키움 trde_tp=81
    BEST_LIMIT = "BEST_LIMIT"          # 키움 trde_tp=6
    PRIORITY_LIMIT = "PRIORITY_LIMIT"  # 키움 trde_tp=7


class V71Order(Base):
    """PRD Patch #5: 키움 주문 추적 (v71_orders 테이블).

    키움 API에 ``client_order_id`` 필드 없음 → V7.1 자체 매핑 키
    ``kiwoom_order_no`` (UNIQUE) 사용. 정정/취소 시 ``kiwoom_orig_order_no``로
    원주문 추적.

    명명 결정 (PRD §1.4 V71 접두사 + 헌법 §3 충돌 금지):
      V7.0의 ``src.database.models.Order`` (orders 테이블)와 같은 Base metadata
      를 공유하기 때문에 V7.1은 ``v71_orders`` 테이블 + ``V71Order`` 클래스로
      격리. V7.0 정리 (PRD §3.2 P1.X) 완료 후 단순 ``Order/orders``로 통합 검토.
    """

    __tablename__ = "v71_orders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    # Kiwoom mapping (★ V7.1 자체 매핑 키)
    kiwoom_order_no: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True,
    )
    kiwoom_orig_order_no: Mapped[str | None] = mapped_column(String(20))

    # Linkage (NULL 가능)
    position_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("positions.id"),
    )
    box_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("support_boxes.id"),
    )
    tracked_stock_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tracked_stocks.id"),
    )

    # Order content
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)

    direction: Mapped[OrderDirection] = mapped_column(
        SQLEnum(
            OrderDirection,
            name="order_direction",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
    )
    trade_type: Mapped[OrderTradeType] = mapped_column(
        SQLEnum(
            OrderTradeType,
            name="order_trade_type",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 0))  # NULL = MARKET
    exchange: Mapped[str] = mapped_column(String(10), default="KRX", nullable=False)

    # State
    state: Mapped[OrderState] = mapped_column(
        SQLEnum(
            OrderState,
            name="order_state",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=OrderState.SUBMITTED,
        nullable=False,
    )
    filled_quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    filled_avg_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Reject / cancel reasons
    reject_reason: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(100))

    # Retry tracking (PRD §3.3 5초 × 3회)
    retry_attempt: Mapped[int] = mapped_column(default=1, nullable=False)

    # Timestamps
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Kiwoom raw payload (audit + debugging). 토큰/API 키 미포함.
    kiwoom_raw_request: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    kiwoom_raw_response: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)


# ---------------------------------------------------------------------
# system_restarts (migration 012) -- minimal model for PRD §9.5
# ---------------------------------------------------------------------


class SystemRestart(Base):
    __tablename__ = "system_restarts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)

    restart_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    recovery_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_duration_seconds: Mapped[int | None] = mapped_column()

    reason: Mapped[str | None] = mapped_column(String(50))
    reason_detail: Mapped[str | None] = mapped_column(Text)

    reconciliation_summary: Mapped[dict[str, Any] | None] = mapped_column(_JSONB)
    cancelled_orders_count: Mapped[int] = mapped_column(default=0, nullable=False)


__all__ = [
    "AuditAction",
    "AuditLog",
    "BoxStatus",
    "DailyReport",
    "Notification",
    "NotificationChannel",
    "NotificationSeverity",
    "NotificationStatus",
    "OrderDirection",
    "OrderState",
    "OrderTradeType",
    "PathType",
    "V71Order",
    "V71Position",
    "PositionSource",
    "PositionStatus",
    "ReportStatus",
    "Stock",
    "StrategyType",
    "SupportBox",
    "SystemRestart",
    "TradeEvent",
    "TradeEventType",
    "TrackedStatus",
    "TrackedStock",
    "User",
    "UserSession",
    "UserSettings",
]
