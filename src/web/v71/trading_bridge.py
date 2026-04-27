"""Trading-engine ↔ web-backend bridge.

The V7.1 trading engine (Phase 3 building blocks under
``src/core/v71/``) and the web backend share a single asyncio loop and
need to talk to each other.  This module is the *only* surface used for
that conversation -- routes, services, and the trading engine all reach
it through narrow public functions instead of importing each other.

Two responsibilities:

1. **Outbound events**: trading-engine modules call
   :func:`publish_event` / :func:`publish_position_*` / etc. The bridge
   forwards them onto the WebSocket :data:`event_bus` (see PRD §11) and
   keeps :data:`system_state` (PRD §9.1) up to date.

2. **System status mutators**: small helpers
   (:func:`mark_websocket_disconnected`, :func:`mark_safe_mode`, ...)
   so the trading engine never imports the WebSocket router internals.

The bridge does **not** start the trading engine. Phase 5 lifespan
hooks may opt into it via ``V71_WEB_BOOT_TRADING_ENGINE=true``; until
then the bridge is dormant and only carries publisher state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .api.system.state import feature_flags, system_state
from .ws.event_bus import event_bus
from .ws.messages import (
    CHANNEL_BOXES,
    CHANNEL_NOTIFICATIONS,
    CHANNEL_POSITIONS,
    CHANNEL_SYSTEM,
    CHANNEL_TRACKED_STOCKS,
    TYPE_BOX_ENTRY_PROXIMITY,
    TYPE_BOX_INVALIDATED,
    TYPE_BOX_TRIGGERED,
    TYPE_NEW_NOTIFICATION,
    TYPE_POSITION_CHANGED,
    TYPE_POSITION_CLOSED,
    TYPE_POSITION_OPENED,
    TYPE_POSITION_PRICE_UPDATE,
    TYPE_SYSTEM_RESTARTING,
    TYPE_TRACKED_STOCK_STATUS,
    TYPE_VI_TRIGGERED,
    TYPE_WEBSOCKET_DISCONNECTED,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Generic publisher (escape hatch -- prefer the typed helpers below)
# ---------------------------------------------------------------------


async def publish_event(
    *,
    type: str,
    channel: str,
    data: dict[str, Any],
) -> None:
    await event_bus.publish(type=type, channel=channel, data=data)


# ---------------------------------------------------------------------
# Position events (PRD §11.3 positions 채널)
# ---------------------------------------------------------------------


async def publish_position_price_update(
    *,
    position_id: UUID,
    stock_code: str,
    current_price: float,
    pnl_amount: float,
    pnl_pct: float,
) -> None:
    await event_bus.publish(
        type=TYPE_POSITION_PRICE_UPDATE,
        channel=CHANNEL_POSITIONS,
        data={
            "position_id": str(position_id),
            "stock_code": stock_code,
            "current_price": current_price,
            "pnl_amount": pnl_amount,
            "pnl_pct": pnl_pct,
        },
    )


async def publish_position_changed(
    *,
    position_id: UUID,
    event: str,
    old_quantity: int,
    new_quantity: int,
    trigger_price: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "position_id": str(position_id),
        "event": event,
        "old_quantity": old_quantity,
        "new_quantity": new_quantity,
    }
    if trigger_price is not None:
        payload["trigger_price"] = trigger_price
    if extra:
        payload.update(extra)
    await event_bus.publish(
        type=TYPE_POSITION_CHANGED,
        channel=CHANNEL_POSITIONS,
        data=payload,
    )


async def publish_position_opened(*, data: dict[str, Any]) -> None:
    await event_bus.publish(
        type=TYPE_POSITION_OPENED,
        channel=CHANNEL_POSITIONS,
        data=data,
    )


async def publish_position_closed(
    *,
    position_id: UUID,
    close_reason: str,
    final_pnl: float,
    final_pnl_pct: float,
) -> None:
    await event_bus.publish(
        type=TYPE_POSITION_CLOSED,
        channel=CHANNEL_POSITIONS,
        data={
            "position_id": str(position_id),
            "close_reason": close_reason,
            "final_pnl": final_pnl,
            "final_pnl_pct": final_pnl_pct,
        },
    )


# ---------------------------------------------------------------------
# Box events (PRD §11.3 boxes 채널)
# ---------------------------------------------------------------------


async def publish_box_entry_proximity(
    *,
    box_id: UUID,
    stock_code: str,
    current_price: float,
    upper_price: float,
    proximity_pct: float,
) -> None:
    await event_bus.publish(
        type=TYPE_BOX_ENTRY_PROXIMITY,
        channel=CHANNEL_BOXES,
        data={
            "box_id": str(box_id),
            "stock_code": stock_code,
            "current_price": current_price,
            "upper_price": upper_price,
            "proximity_pct": proximity_pct,
        },
    )


async def publish_box_triggered(
    *,
    box_id: UUID,
    trigger_price: float,
    buy_order_id: str | None = None,
) -> None:
    await event_bus.publish(
        type=TYPE_BOX_TRIGGERED,
        channel=CHANNEL_BOXES,
        data={
            "box_id": str(box_id),
            "trigger_price": trigger_price,
            "buy_order_id": buy_order_id,
        },
    )


async def publish_box_invalidated(
    *,
    box_id: UUID,
    reason: str,
) -> None:
    await event_bus.publish(
        type=TYPE_BOX_INVALIDATED,
        channel=CHANNEL_BOXES,
        data={"box_id": str(box_id), "reason": reason},
    )


# ---------------------------------------------------------------------
# Notification (PRD §11.3 notifications 채널)
# ---------------------------------------------------------------------


async def publish_new_notification(
    *,
    notification_id: UUID,
    severity: str,
    title: str,
    message: str,
    stock_code: str | None,
    created_at: datetime,
) -> None:
    await event_bus.publish(
        type=TYPE_NEW_NOTIFICATION,
        channel=CHANNEL_NOTIFICATIONS,
        data={
            "id": str(notification_id),
            "severity": severity,
            "title": title,
            "message": message,
            "stock_code": stock_code,
            "created_at": created_at.isoformat(),
        },
    )


# ---------------------------------------------------------------------
# System events (PRD §11.3 system 채널) + system_state mutators
# ---------------------------------------------------------------------


async def publish_websocket_disconnected(
    *,
    duration_seconds: int,
    reconnect_phase: str = "PHASE_1",
) -> None:
    system_state.websocket_connected = False
    system_state.last_websocket_disconnect_at = datetime.now(timezone.utc)
    await event_bus.publish(
        type=TYPE_WEBSOCKET_DISCONNECTED,
        channel=CHANNEL_SYSTEM,
        data={
            "duration_seconds": duration_seconds,
            "reconnect_phase": reconnect_phase,
        },
    )


async def publish_websocket_reconnected() -> None:
    system_state.websocket_connected = True
    system_state.websocket_reconnect_count_today += 1


async def publish_vi_triggered(
    *,
    stock_code: str,
    trigger_price: float,
    resume_at: datetime | None = None,
) -> None:
    await event_bus.publish(
        type=TYPE_VI_TRIGGERED,
        channel=CHANNEL_SYSTEM,
        data={
            "stock_code": stock_code,
            "trigger_price": trigger_price,
            "resume_at": resume_at.isoformat() if resume_at else None,
        },
    )


async def publish_system_restarting(
    *,
    reason: str,
    estimated_recovery_seconds: int = 60,
) -> None:
    await event_bus.publish(
        type=TYPE_SYSTEM_RESTARTING,
        channel=CHANNEL_SYSTEM,
        data={
            "reason": reason,
            "estimated_recovery_seconds": estimated_recovery_seconds,
        },
    )


# ---------------------------------------------------------------------
# Tracked stocks events (PRD §11.2 tracked_stocks 채널)
# ---------------------------------------------------------------------


async def publish_tracked_stock_status(
    *,
    tracked_stock_id: UUID,
    stock_code: str,
    new_status: str,
    old_status: str | None = None,
) -> None:
    await event_bus.publish(
        type=TYPE_TRACKED_STOCK_STATUS,
        channel=CHANNEL_TRACKED_STOCKS,
        data={
            "tracked_stock_id": str(tracked_stock_id),
            "stock_code": stock_code,
            "new_status": new_status,
            "old_status": old_status,
        },
    )


# ---------------------------------------------------------------------
# Plain mutators for the trading engine to call without going through
# the websocket bus (status panel, telemetry, etc.).
# ---------------------------------------------------------------------


def mark_kiwoom_unavailable() -> None:
    system_state.kiwoom_available = False


def mark_kiwoom_available() -> None:
    system_state.kiwoom_available = True


def mark_telegram_active(active: bool) -> None:
    system_state.telegram_active = bool(active)


def set_feature_flag(key: str, value: bool) -> None:
    feature_flags.set(key, bool(value))


# ---------------------------------------------------------------------
# Trading-engine attach / detach (V7.1 entry point)
# ---------------------------------------------------------------------
#
# ``attach_trading_engine`` is the single seam where the FastAPI lifespan
# hook (lifespan.py) wires the V7.1 trading engine into the running
# asyncio loop. The handle returned MUST be passed back to
# ``detach_trading_engine`` on shutdown.
#
# This entry point is intentionally minimal -- it only constructs the
# objects that exist today (P3 building blocks). Concrete callbacks that
# bridge engine events to ``publish_*`` will be wired in subsequent
# phases as the V7.1 strategy/exit pipeline graduates from unit-tested
# building blocks to a coordinated runtime. Until then the handle keeps
# the engine quiescent and returns cleanly.


class _TradingEngineHandle:
    """Opaque handle returned to lifespan; lets detach run cleanly."""

    def __init__(self) -> None:
        self.box_manager: Any = None
        self.position_manager: Any = None


async def attach_trading_engine() -> _TradingEngineHandle:
    """Construct the V7.1 trading engine objects and attach publishers.

    Wiring publishers to engine events is deferred to a follow-up phase
    -- this stub ensures the integration seam exists, that lifespan can
    boot/teardown the engine, and that future commits only need to add
    ``self._notifier = ...`` calls inside the engine constructors.

    The V7.1 modules consult ``feature_flags`` in ``__init__``; if the
    flags are disabled we keep the handle empty and let lifespan boot
    cleanly.
    """
    from src.utils.feature_flags import is_enabled

    handle = _TradingEngineHandle()

    if is_enabled("v71.box_system"):
        from src.core.v71.box.box_manager import V71BoxManager

        handle.box_manager = V71BoxManager()
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.box_system' disabled -- "
            "box_manager not constructed",
        )

    if is_enabled("v71.position_v71"):
        from src.core.v71.position.v71_position_manager import (
            V71PositionManager,
        )

        handle.position_manager = V71PositionManager()
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.position_v71' disabled -- "
            "position_manager not constructed",
        )

    logger.info(
        "trading_bridge: V7.1 engine objects constructed "
        "(box=%s, position=%s)",
        type(handle.box_manager).__name__ if handle.box_manager else "none",
        type(handle.position_manager).__name__
        if handle.position_manager
        else "none",
    )
    return handle


async def detach_trading_engine(handle: _TradingEngineHandle) -> None:
    """Release the engine handle. Currently no async resources to drain."""
    handle.box_manager = None
    handle.position_manager = None


__all__ = [
    "attach_trading_engine",
    "detach_trading_engine",
    "mark_kiwoom_available",
    "mark_kiwoom_unavailable",
    "mark_telegram_active",
    "publish_box_entry_proximity",
    "publish_box_invalidated",
    "publish_box_triggered",
    "publish_event",
    "publish_new_notification",
    "publish_position_changed",
    "publish_position_closed",
    "publish_position_opened",
    "publish_position_price_update",
    "publish_system_restarting",
    "publish_tracked_stock_status",
    "publish_vi_triggered",
    "publish_websocket_disconnected",
    "publish_websocket_reconnected",
    "set_feature_flag",
]
