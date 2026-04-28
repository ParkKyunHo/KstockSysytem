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

import asyncio
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
    """Opaque handle returned to lifespan; lets detach run cleanly.

    Holds references to every long-lived V7.1 trading object so the
    teardown path can release them in reverse order (kiwoom client owns
    a network connection -- it must close after everything that uses it).
    """

    def __init__(self) -> None:
        self.box_manager: Any = None
        self.position_manager: Any = None
        # P-Wire-1: Kiwoom exchange infrastructure (feature flag
        # ``v71.kiwoom_exchange``). ``aclose()`` must run on detach.
        self.token_manager: Any = None
        self.rate_limiter: Any = None
        self.kiwoom_client: Any = None
        self.order_manager: Any = None
        self.exchange_adapter: Any = None
        # P-Wire-2: Reconciler periodic task (feature flag
        # ``v71.reconciliation_v71``). ``reconciler_task`` is the
        # asyncio.Task background loop -- detach cancels + awaits.
        self.reconciler: Any = None
        self.reconciler_task: asyncio.Task[None] | None = None
        # P-Wire-3: Notification stack (feature flag
        # ``v71.notification_v71``). ``notification_service.stop()`` must
        # run BEFORE ``kiwoom_client.aclose()`` so the worker drains
        # cleanly. Repository / queue / circuit breaker are stateless
        # references kept for handle inspection.
        self.notification_repository: Any = None
        self.notification_queue: Any = None
        self.notification_circuit_breaker: Any = None
        self.notification_service: Any = None


# Default reconciliation cadence (PRD 02_TRADING_RULES.md §7.1 -- "매 5분마다").
# Local override available via ``V71_RECONCILER_INTERVAL_SECONDS`` env var
# (paper smoke / tests use a much shorter interval).
_RECONCILER_INTERVAL_DEFAULT_SECONDS = 300.0


async def _reconciler_loop(
    reconciler: Any, *, interval_seconds: float,
) -> None:
    """Run ``reconciler.reconcile_all()`` on a fixed cadence.

    Boundaries:
      * The first pass fires immediately on startup (post-restart §13.1
        Step 3 -- broker may have moved during downtime).
      * Each pass is wrapped in try/except -- a single failure must not
        starve the loop (헌법 §4 항상 운영). The reconciler itself
        already isolates per-stock failures into ``failed_stock_codes``
        so this catch is a defence-in-depth backstop for transport
        outages where ``reconcile_all`` raises ``V71ReconcilerError``.
      * Sleeping is interrupted by ``asyncio.CancelledError`` on detach.
    """
    while True:
        try:
            await reconciler.reconcile_all()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- always-run policy
            logger.warning(
                "trading_bridge: reconciler pass failed: %s",
                type(exc).__name__,
            )
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise


def _resolve_reconciler_interval() -> float:
    """Read the reconciler cadence from ``V71_RECONCILER_INTERVAL_SECONDS``,
    falling back to PRD default (300 s)."""
    import os

    raw = os.environ.get("V71_RECONCILER_INTERVAL_SECONDS", "").strip()
    if not raw:
        return _RECONCILER_INTERVAL_DEFAULT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "trading_bridge: invalid V71_RECONCILER_INTERVAL_SECONDS=%r; "
            "falling back to %.0fs",
            raw, _RECONCILER_INTERVAL_DEFAULT_SECONDS,
        )
        return _RECONCILER_INTERVAL_DEFAULT_SECONDS
    if value <= 0:
        logger.warning(
            "trading_bridge: V71_RECONCILER_INTERVAL_SECONDS must be > 0 "
            "(got %s); falling back to %.0fs",
            value, _RECONCILER_INTERVAL_DEFAULT_SECONDS,
        )
        return _RECONCILER_INTERVAL_DEFAULT_SECONDS
    return value


def _build_reconciler(handle: _TradingEngineHandle) -> Any:
    """Construct V71Reconciler from the already-built kiwoom infrastructure.

    Requires the ``v71.kiwoom_exchange`` flag to have produced a client +
    order_manager; otherwise the reconciler has nothing to reconcile.
    """
    from src.core.v71.exchange.reconciler import (
        V71Reconciler,
        V71ReconciliationApplyMode,
    )
    from src.database.connection import get_db_manager

    if handle.kiwoom_client is None:
        raise RuntimeError(
            "trading_bridge: v71.reconciliation_v71 enabled but "
            "v71.kiwoom_exchange is OFF -- enable kiwoom_exchange first"
        )

    db = get_db_manager()
    return V71Reconciler(
        kiwoom_client=handle.kiwoom_client,
        db_session_factory=db.session,
        apply_mode=V71ReconciliationApplyMode.SIMPLE_APPLY,
    )


class _AsyncioRealClock:
    """Production :class:`Clock` impl wrapping ``asyncio.sleep`` + UTC ``now``.

    Defined here so multiple V7.1 background services (notification
    worker, daily summary scheduler, etc.) share a single concrete
    clock. ``Clock`` Protocol lives at
    ``src.core.v71.strategies.v71_buy_executor:Clock``; tests inject
    fakes, production wires this class.
    """

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def sleep_until(self, target: datetime) -> None:
        delta = (target - self.now()).total_seconds()
        if delta > 0:
            await asyncio.sleep(delta)


async def _build_pg_notification_execute() -> Any:
    """Adapter shim: SQLAlchemy ``AsyncSession.execute`` -> asyncpg-style
    ``(sql, *params) -> rows | rowcount`` callable consumed by
    :class:`PostgresNotificationRepository`.

    Two transforms:

      * ``$1, $2, ...`` placeholders -> SQLAlchemy named binds
        (``:p1, :p2, ...``). The substitution is right-to-left so
        ``$10`` does not collide with ``$1``.
      * Result shape: returns ``list(result.mappings().all())`` for
        SELECT, ``result.rowcount`` for INSERT/UPDATE/DELETE. The repo
        only treats ``expire_stale`` as int; everything else either
        ignores the return or expects rows.
    """
    from sqlalchemy import text

    from src.database.connection import get_db_manager

    db = get_db_manager()

    async def execute(sql: str, *params: Any) -> Any:
        named = {f"p{i}": v for i, v in enumerate(params, 1)}
        rewritten = sql
        for i in range(len(params), 0, -1):
            rewritten = rewritten.replace(f"${i}", f":p{i}")
        async with db.session() as session:
            result = await session.execute(text(rewritten), named)
            if result.returns_rows:
                return list(result.mappings().all())
            return result.rowcount

    return execute


def _build_telegram_send_fn() -> Any:
    """Wrap V7.0 ``TelegramBot.send_message`` into the V7.1
    ``TelegramSendFn`` callable contract.

    Returns ``None`` when ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``
    are missing -- the notification service then operates in *queue
    only* mode (records persisted, worker not started). This is the
    fail-secure path used during paper smoke + early Phase 7 work
    before the Telegram bot is reactivated.

    parse_mode is intentionally not forwarded -- CLAUDE.md Part 1.1
    forbids it, and V7.0 TelegramBot already guards (defence in depth).
    """
    import os

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        logger.warning(
            "trading_bridge: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing "
            "-- notification service runs in queue-only mode (no delivery)"
        )
        return None

    from src.notification.telegram import TelegramBot

    bot = TelegramBot()

    async def send(text: str) -> bool:
        return await bot.send_message(text)

    return send


def _build_notification_stack() -> dict[str, Any]:
    """P-Wire-3: build the V71NotificationService and its dependencies.

    No external dependency on kiwoom (independent of P-Wire-1). The
    service worker is started by the caller after the stack is fully
    assembled to avoid a half-built worker observing partial state.

    Returns a dict so the caller can attach references onto
    :class:`_TradingEngineHandle` after deciding whether to start the
    worker (``service`` is ``None`` when ``telegram_send`` is missing).
    """
    from src.core.v71.notification.v71_circuit_breaker import V71CircuitBreaker
    from src.core.v71.notification.v71_notification_queue import (
        V71NotificationQueue,
    )
    from src.core.v71.notification.v71_notification_service import (
        V71NotificationService,
    )
    from src.core.v71.notification.v71_postgres_notification_repository import (
        PostgresNotificationRepository,
    )

    clock = _AsyncioRealClock()
    telegram_send = _build_telegram_send_fn()

    return {
        "clock": clock,
        "telegram_send": telegram_send,
        "_PostgresNotificationRepository": PostgresNotificationRepository,
        "_V71NotificationQueue": V71NotificationQueue,
        "_V71CircuitBreaker": V71CircuitBreaker,
        "_V71NotificationService": V71NotificationService,
    }


def _build_kiwoom_exchange() -> dict[str, Any]:
    """Construct the V7.1 Kiwoom transport stack from environment.

    Returns the freshly-built objects in a dict so the caller can attach
    them onto the handle after deciding (via feature flag) whether to
    keep them. The same V71KiwoomClient instance is shared between
    V71OrderManager and V71KiwoomExchangeAdapter (P5-Kiwoom-Adapter
    same-instance invariant).
    """
    import os

    from src.core.v71.exchange.exchange_adapter import V71KiwoomExchangeAdapter
    from src.core.v71.exchange.kiwoom_client import V71KiwoomClient
    from src.core.v71.exchange.order_manager import V71OrderManager
    from src.core.v71.exchange.rate_limiter import V71RateLimiter
    from src.core.v71.exchange.token_manager import V71TokenManager
    from src.core.v71.v71_constants import V71Constants

    app_key = os.environ.get("KIWOOM_APP_KEY", "").strip()
    app_secret = os.environ.get("KIWOOM_SECRET", "").strip()
    if not app_key or not app_secret:
        raise RuntimeError(
            "trading_bridge: v71.kiwoom_exchange enabled but "
            "KIWOOM_APP_KEY / KIWOOM_SECRET are not set in environment"
        )

    is_paper = os.environ.get("KIWOOM_ENV", "PRODUCTION").strip().upper() == "SANDBOX"

    token_manager = V71TokenManager(
        app_key=app_key, app_secret=app_secret, is_paper=is_paper,
    )
    rate_limiter = V71RateLimiter(
        rate_per_second=(
            V71Constants.API_RATE_LIMIT_PAPER_PER_SECOND
            if is_paper
            else V71Constants.API_RATE_LIMIT_PER_SECOND
        ),
    )
    kiwoom_client = V71KiwoomClient(
        token_manager=token_manager,
        rate_limiter=rate_limiter,
        is_paper=is_paper,
    )

    # V71OrderManager needs a DB session factory. Lifespan owns the
    # database manager; the bridge reaches it through the established
    # publisher state surface so we don't double-import.
    from src.database.connection import get_db_manager

    db = get_db_manager()
    order_manager = V71OrderManager(
        kiwoom_client=kiwoom_client,
        db_session_factory=db.session,
    )
    exchange_adapter = V71KiwoomExchangeAdapter(
        kiwoom_client=kiwoom_client,
        order_manager=order_manager,
    )

    logger.info(
        "trading_bridge: kiwoom exchange constructed (is_paper=%s)",
        is_paper,
    )
    return {
        "token_manager": token_manager,
        "rate_limiter": rate_limiter,
        "kiwoom_client": kiwoom_client,
        "order_manager": order_manager,
        "exchange_adapter": exchange_adapter,
    }


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

    # P-Wire-1: Kiwoom exchange infrastructure -- shared by V71OrderManager
    # and V71KiwoomExchangeAdapter.
    if is_enabled("v71.kiwoom_exchange"):
        try:
            built = _build_kiwoom_exchange()
        except Exception as exc:  # noqa: BLE001 -- boot failure must surface
            logger.error(
                "trading_bridge: v71.kiwoom_exchange enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.token_manager = built["token_manager"]
        handle.rate_limiter = built["rate_limiter"]
        handle.kiwoom_client = built["kiwoom_client"]
        handle.order_manager = built["order_manager"]
        handle.exchange_adapter = built["exchange_adapter"]
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.kiwoom_exchange' disabled "
            "-- kiwoom_client / order_manager / exchange_adapter not built",
        )

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

    # P-Wire-3: Notification stack -- V71NotificationService + queue +
    # circuit breaker + Postgres repository. Independent of kiwoom (any
    # V7.1 module that imports the Notifier Protocol will resolve to
    # ``handle.notification_service`` once Phase 6 wires executors).
    if is_enabled("v71.notification_v71"):
        try:
            built = _build_notification_stack()
            execute_fn = await _build_pg_notification_execute()
            repository = built["_PostgresNotificationRepository"](
                execute=execute_fn,
            )
            queue = built["_V71NotificationQueue"](
                repository=repository, clock=built["clock"],
            )
            circuit_breaker = built["_V71CircuitBreaker"](clock=built["clock"])
            handle.notification_repository = repository
            handle.notification_queue = queue
            handle.notification_circuit_breaker = circuit_breaker
            if built["telegram_send"] is not None:
                service = built["_V71NotificationService"](
                    queue=queue,
                    circuit_breaker=circuit_breaker,
                    telegram_send=built["telegram_send"],
                    clock=built["clock"],
                )
                await service.start()
                handle.notification_service = service
                mark_telegram_active(True)
            else:
                logger.warning(
                    "trading_bridge: notification stack built but worker "
                    "not started (telegram credentials absent) -- queue "
                    "accepts records, delivery suspended"
                )
                # security-reviewer L1: surface degraded delivery to system
                # state so the dashboard / health endpoint reflects it.
                mark_telegram_active(False)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.notification_v71 enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.notification_v71' disabled "
            "-- notification stack not constructed",
        )

    # P-Wire-2: V71Reconciler periodic task. Only spins up when the
    # exchange infrastructure is already wired -- there is nothing to
    # reconcile against without a kiwoom_client.
    if is_enabled("v71.reconciliation_v71"):
        try:
            handle.reconciler = _build_reconciler(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.reconciliation_v71 enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        interval = _resolve_reconciler_interval()
        handle.reconciler_task = asyncio.create_task(
            _reconciler_loop(
                handle.reconciler, interval_seconds=interval,
            ),
            name="v71_reconciler_loop",
        )
        logger.info(
            "trading_bridge: reconciler loop started (interval=%.0fs)",
            interval,
        )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.reconciliation_v71' disabled "
            "-- reconciler periodic loop not started",
        )

    logger.info(
        "trading_bridge: V7.1 engine objects constructed "
        "(kiwoom=%s, box=%s, position=%s, reconciler=%s, notification=%s)",
        "yes" if handle.kiwoom_client else "no",
        type(handle.box_manager).__name__ if handle.box_manager else "none",
        type(handle.position_manager).__name__
        if handle.position_manager
        else "none",
        "running" if handle.reconciler_task else "off",
        "running"
        if handle.notification_service
        else ("queue-only" if handle.notification_queue else "off"),
    )
    return handle


async def detach_trading_engine(handle: _TradingEngineHandle) -> None:
    """Release the engine handle in reverse construction order.

    The Kiwoom client owns an httpx.AsyncClient connection pool -- close
    it last (after the order_manager / exchange_adapter / reconciler
    that use it).
    """
    handle.box_manager = None
    handle.position_manager = None

    # P-Wire-3: stop the notification worker first. Worker only depends
    # on telegram_send + clock (not kiwoom), but stopping early ensures
    # the queue stops draining before its consumer (telegram bot HTTP
    # client) can be touched by other shutdown paths.
    if handle.notification_service is not None:
        try:
            await handle.notification_service.stop()
        except Exception as exc:  # noqa: BLE001 -- shutdown is best-effort
            logger.warning(
                "trading_bridge: notification_service.stop() failed: %s",
                type(exc).__name__,
            )
        handle.notification_service = None
    handle.notification_circuit_breaker = None
    handle.notification_queue = None
    handle.notification_repository = None

    # P-Wire-2: stop the reconciler loop before tearing down the client
    # it depends on. CancelledError propagates out of asyncio.sleep /
    # reconcile_all naturally; we still await the task so the cancel
    # actually completes before we close the client.
    if handle.reconciler_task is not None:
        handle.reconciler_task.cancel()
        try:
            await handle.reconciler_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 -- shutdown is best-effort
            logger.warning(
                "trading_bridge: reconciler_task await failed: %s",
                type(exc).__name__,
            )
        handle.reconciler_task = None
    handle.reconciler = None

    handle.exchange_adapter = None
    handle.order_manager = None
    if handle.kiwoom_client is not None:
        try:
            await handle.kiwoom_client.aclose()
        except Exception as exc:  # noqa: BLE001 -- shutdown is best-effort
            logger.warning(
                "trading_bridge: kiwoom_client.aclose() failed: %s",
                type(exc).__name__,
            )
        handle.kiwoom_client = None
    handle.rate_limiter = None
    handle.token_manager = None


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
