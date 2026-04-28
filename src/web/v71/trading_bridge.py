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
import contextlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

# P-Wire-4 extraction: ``V71RealClock`` is the production Clock impl
# shared by every V7.1 background service (NotificationService worker,
# BuyExecutor, ExitExecutor, ViMonitor). The local alias below keeps
# downstream tests that read ``_AsyncioRealClock`` from this module
# functional during the Phase 6/7 transition.
from src.core.v71.v71_realclock import V71RealClock

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
        # P-Wire-4a: V71BuyExecutor + supporting callables. The executor
        # itself is stateless, but the cache/closure references are
        # retained on the handle for visibility (paper smoke + tests).
        self.clock: Any = None
        self.buy_executor: Any = None
        self.total_capital_refresh: Any = None
        self.prev_close_cache: Any = None
        self.tracked_stock_cache: Any = None
        # P-Wire-4b: V71ExitExecutor (stop loss / TS / partial profit-take).
        # Stateless wrapper around ExchangeAdapter + Notifier + Clock; the
        # ``on_position_closed`` callback is wired in P-Wire-4c (ViMonitor)
        # or by a future orchestrator. None in 4b → silent (OK for paper).
        self.exit_executor: Any = None
        # P-Wire-4c: V71ViMonitor (PRD 02 §10 single-price interval state
        # machine). Per-stock in-memory tracker; consumed by BuyExecutor's
        # ``is_vi_active`` callable (replacing the P-Wire-4a stub) and by
        # the ExitCalculator/orchestrator pipeline. WebSocket 9068
        # subscription is wired in P-Wire-5 paper smoke alongside the WS
        # dispatcher.
        self.vi_monitor: Any = None
        # P-Wire-5: V71KiwoomWebSocket realtime channels (PRICE_TICK /
        # ORDER_EXECUTION / BALANCE / VI). The run loop is an
        # ``asyncio.Task``; detach must cancel + await before
        # ``kiwoom_client.aclose()`` so the active WS connection drains
        # cleanly. The VI handler dispatches 9068 events to
        # ``vi_monitor.on_vi_triggered`` / ``on_vi_resolved``.
        self.kiwoom_websocket: Any = None
        self.kiwoom_websocket_task: asyncio.Task[None] | None = None


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


_AsyncioRealClock = V71RealClock  # backwards-compatible alias for tests


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


# ---------------------------------------------------------------------------
# P-Wire-4: V71BuyExecutor wiring helpers
# ---------------------------------------------------------------------------
#
# BuyExecutor needs four callables that the strategies module captures as
# closures (BuyExecutorContext is frozen). Two are kt00018-backed with a
# 5 minute TTL cache (PRD 02_TRADING_RULES.md §3.4 cap check tolerates
# minute-level staleness; per-call kt00018 burns one of the 4.5/sec slots
# during regular session). One is a per-trading-day cache for previous
# close (PATH_B 09:01 gap-up). One is a tracked_stocks DB lookup.
#
# Architect Q3: VI is wired in P-Wire-4c. P-Wire-4a uses a stub
# ``is_vi_active = lambda code: False`` + system_state.degraded_vi=True
# so the dashboard reflects the gap.

_TOTAL_CAPITAL_TTL_SECONDS = 300.0  # PRD §6.2 / §3.4: 5분 단위 평가
_TRACKED_CACHE_DB_TIMEOUT_SECONDS = 10.0  # security M3: bound boot blocking
# Top-level kt00018 keys (KIWOOM_API_ANALYSIS.md). Wire-level field
# correction may land in P-Wire-5 paper smoke; the cache falls back to
# 0 + WARNING when neither key resolves so PATH_A naturally abandons
# (헌법 §1: 자본금 추정 실패는 매수 차단).
_KT00018_TOTAL_EVAL_KEYS = ("tot_evlt_amt", "prsm_dpst_aset_amt", "tot_pur_amt")
# security M1: KRX (6 digits) + NXT (5-8 alphanumeric) whitelist. Mirrors
# ``src/core/v71/exchange/reconciler.py:140``.
_VALID_STOCK_CODE = re.compile(r"^[A-Z0-9]{5,8}$")


def _coerce_int(raw: Any) -> int:
    """Robust string→int that accepts kiwoom's zero-padded numeric strings.

    security L2: clamp negatives to 0 -- a negative ``total_capital`` would
    invert the §3.4 cap check and let buys through against the user's
    intent (헌법 §1).
    """
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip().lstrip("0") or "0")
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _build_total_capital_cache(kiwoom_client: Any) -> Any:
    """Return a sync ``Callable[[], int]`` backed by a 5-min TTL cache.

    security H1: ``_refresh`` is wrapped in ``BaseException`` catch-all
    so an orphan ``asyncio.create_task(...)`` cannot leak unhandled
    exceptions into the default loop handler. ``inflight`` guards against
    a burst of TTL-expired sync calls each scheduling their own refresh
    (memory + rate-limit slot exhaustion).

    security M4: ``response.body`` shape is validated -- non-dict bodies
    fall through to the fallback path (cache 0 + WARNING).
    """
    state: dict[str, Any] = {
        "value": 0,
        "fetched_at": 0.0,    # time.monotonic timestamp of last fetch
        "inflight": False,
    }

    async def _refresh_inner() -> None:
        try:
            response = await kiwoom_client.get_account_balance()
        except Exception as exc:  # noqa: BLE001 -- callable must not raise
            logger.warning(
                "trading_bridge: get_total_capital refresh failed: %s",
                type(exc).__name__,
            )
            return
        body = getattr(response, "body", response)
        if not isinstance(body, dict):
            logger.warning(
                "trading_bridge: get_total_capital response shape "
                "unexpected: %s -- caching 0",
                type(body).__name__,
            )
            state["value"] = 0
            state["fetched_at"] = time.monotonic()
            return
        for key in _KT00018_TOTAL_EVAL_KEYS:
            if key in body:
                state["value"] = _coerce_int(body[key])
                state["fetched_at"] = time.monotonic()
                return
        logger.warning(
            "trading_bridge: get_total_capital response missing all of %s "
            "-- caching 0 (PATH_A buys will abandon via cap check)",
            _KT00018_TOTAL_EVAL_KEYS,
        )
        state["value"] = 0
        state["fetched_at"] = time.monotonic()

    async def _refresh() -> None:
        # Outer wrapper guards orphan tasks from leaking BaseException
        # (e.g., KeyboardInterrupt during shutdown) into the default loop
        # handler.
        state["inflight"] = True
        try:
            await _refresh_inner()
        except BaseException:  # noqa: BLE001 -- orphan task must not raise
            logger.exception(
                "trading_bridge: _refresh leaked unexpected exception"
            )
        finally:
            state["inflight"] = False

    def get_total_capital() -> int:
        if (
            not state["inflight"]
            and time.monotonic() - state["fetched_at"]
            > _TOTAL_CAPITAL_TTL_SECONDS
        ):
            # Mark inflight synchronously so a burst of sync callers all
            # see the guard and stop scheduling duplicate refreshes.
            state["inflight"] = True
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(_refresh())
            except RuntimeError:
                # No running loop (sync test) -- release the guard so
                # caller can prime synchronously by awaiting _refresh().
                state["inflight"] = False
        return int(state["value"])

    return get_total_capital, _refresh


def _build_invested_pct_factory(
    position_manager: Any, get_total_capital: Any,
) -> Any:
    """Return ``Callable[[str], float]`` computing per-stock invested
    percentage of total capital.

    Formula: ``sum(weighted_avg_price * total_quantity for OPEN/PARTIAL_CLOSED
    positions on stock_code) / total_capital * 100``.

    Returns ``0.0`` when total_capital is 0 (cache uninitialised) -- this
    feeds straight into PATH_A cap check, which then trips on
    ``box.position_size_pct`` alone.
    """
    def get_invested_pct_for_stock(stock_code: str) -> float:
        capital = get_total_capital()
        if capital <= 0:
            return 0.0
        positions = position_manager.list_for_stock(stock_code)
        cost = sum(
            int(getattr(p, "weighted_avg_price", 0))
            * int(getattr(p, "total_quantity", 0))
            for p in positions
            if getattr(p, "status", "OPEN") != "CLOSED"
        )
        return (cost / capital) * 100.0

    return get_invested_pct_for_stock


def _build_prev_close_cache(kiwoom_client: Any) -> Any:  # noqa: ARG001
    """Return ``Callable[[str], int]`` backed by a per-trading-day cache.

    PATH_B 1차 매수 (PRD §3.10) only needs the previous close, fetched
    once per day. The sync callable performs a dict lookup; cache misses
    schedule an async fetch (kiwoom_client.request ka10081) and return 0.
    Returning 0 makes ``check_gap_up_for_path_b`` interpret as
    ``ABANDONED_GAP``-equivalent (defensive; the priming task should
    have run before 09:01).

    security H1: ``inflight`` set guards against duplicate fetches for
    the same stock_code within the same fetch window.
    """
    cache: dict[str, tuple[str, int]] = {}  # stock -> (yyyymmdd, prev_close)
    inflight: set[str] = set()

    async def _fetch_inner(stock_code: str) -> None:
        # ka10081 daily chart -- last completed bar's close.
        # The wire-level call is in P-Wire-5; here we only stub the
        # sync surface so BuyExecutor wiring lands. Tests inject the
        # cache contents directly via the returned `cache` dict.
        logger.warning(
            "trading_bridge: prev_close cache miss for %s -- "
            "P-Wire-5 paper smoke must pre-warm via ka10081",
            stock_code,
        )

    async def _fetch(stock_code: str) -> None:
        try:
            await _fetch_inner(stock_code)
        except BaseException:  # noqa: BLE001 -- orphan task must not raise
            logger.exception(
                "trading_bridge: prev_close fetch leaked exception"
            )
        finally:
            inflight.discard(stock_code)

    def get_previous_close(stock_code: str) -> int:
        entry = cache.get(stock_code)
        if entry is None:
            if stock_code not in inflight:
                inflight.add(stock_code)
                try:
                    loop = asyncio.get_event_loop()
                    loop.create_task(_fetch(stock_code))
                except RuntimeError:
                    inflight.discard(stock_code)
            return 0
        return int(entry[1])

    return get_previous_close, cache


def _build_tracked_stock_lookup(initial: dict[str, str] | None = None) -> Any:
    """Return ``Callable[[str], str]`` mapping
    ``tracked_stock_id -> stock_code``.

    Lifespan-time wiring loads the current ``tracked_stocks`` table once
    so BuyExecutor can resolve ``BoxRecord.tracked_stock_id`` to the
    six-digit Kiwoom stock_code without touching the DB on the hot path.
    Cache misses raise KeyError (BuyExecutor abandons the box).
    """
    cache: dict[str, str] = dict(initial or {})

    def lookup(tracked_stock_id: str) -> str:
        try:
            return cache[tracked_stock_id]
        except KeyError as exc:
            raise KeyError(
                f"tracked_stock_id={tracked_stock_id!r} not in cache "
                "(re-prime via DB SELECT or restart)"
            ) from exc

    return lookup, cache


async def _load_tracked_stocks_cache() -> dict[str, str]:
    """Load tracked_stocks (id, stock_code) once at lifespan start.

    security M1: stock_code values from the DB are validated against
    ``_VALID_STOCK_CODE`` -- malformed rows (data corruption, malicious
    inputs) are skipped so they cannot reach the kiwoom wire.

    security M3: the SELECT is bounded by
    ``_TRACKED_CACHE_DB_TIMEOUT_SECONDS`` so a hung Supabase pooler
    cannot block lifespan boot indefinitely (PRD §13 boot budget).
    """
    from sqlalchemy import select

    from src.database.connection import get_db_manager
    from src.database.models_v71 import TrackedStock

    db = get_db_manager()
    cache: dict[str, str] = {}
    skipped = 0
    try:
        async with asyncio.timeout(_TRACKED_CACHE_DB_TIMEOUT_SECONDS), \
                db.session() as session:
            result = await session.execute(
                select(TrackedStock.id, TrackedStock.stock_code),
            )
            for tid, stock_code in result.all():
                code = str(stock_code).strip().upper()
                if not _VALID_STOCK_CODE.match(code):
                    skipped += 1
                    continue  # value itself never logged (M1 PII rule)
                cache[str(tid)] = code
    except asyncio.TimeoutError:
        logger.warning(
            "trading_bridge: tracked_stocks cache prime timed out (>%.0fs) "
            "-- BuyExecutor will abandon every PATH_A box until restart",
            _TRACKED_CACHE_DB_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 -- cache miss path is safe
        logger.warning(
            "trading_bridge: tracked_stocks cache prime failed: %s",
            type(exc).__name__,
        )
    if skipped:
        logger.warning(
            "trading_bridge: tracked_stocks cache primed with %d valid "
            "rows; %d invalid stock_code rows skipped",
            len(cache), skipped,
        )
    return cache


async def _build_buy_executor(handle: _TradingEngineHandle) -> dict[str, Any]:
    """Construct V71BuyExecutor + supporting callables.

    Cross-flag invariant (architect Q8): all of
    ``v71.box_system`` / ``v71.kiwoom_exchange`` / ``v71.notification_v71``
    must be ON. Otherwise raise so lifespan surfaces the misconfig.
    """
    from src.utils.feature_flags import is_enabled

    missing = [
        flag
        for flag in (
            "v71.box_system",
            "v71.kiwoom_exchange",
            "v71.notification_v71",
        )
        if not is_enabled(flag)
    ]
    if missing:
        raise RuntimeError(
            "trading_bridge: v71.buy_executor_v71 enabled but required "
            f"dependencies are OFF: {missing}"
        )
    if handle.exchange_adapter is None:
        raise RuntimeError(
            "trading_bridge: BuyExecutor requires exchange_adapter "
            "(v71.kiwoom_exchange flag built no adapter)"
        )
    if handle.box_manager is None:
        raise RuntimeError(
            "trading_bridge: BuyExecutor requires box_manager",
        )
    if handle.position_manager is None:
        raise RuntimeError(
            "trading_bridge: BuyExecutor requires position_manager",
        )
    if handle.notification_service is None:
        raise RuntimeError(
            "trading_bridge: BuyExecutor requires notification_service "
            "(v71.notification_v71 ON but service is queue-only -- "
            "BuyExecutor cannot accept Notifier=None)",
        )

    from src.core.v71.strategies.v71_buy_executor import (
        BuyExecutorContext,
        V71BuyExecutor,
    )

    clock = V71RealClock()
    get_total_capital, refresh_total = _build_total_capital_cache(
        handle.kiwoom_client,
    )
    # Prime the capital cache once so the first PATH_A buy doesn't fall
    # through to fallback 0.
    await refresh_total()
    get_invested_pct = _build_invested_pct_factory(
        handle.position_manager, get_total_capital,
    )
    get_previous_close, prev_close_cache = _build_prev_close_cache(
        handle.kiwoom_client,
    )
    tracked_seed = await _load_tracked_stocks_cache()
    tracked_lookup, tracked_cache = _build_tracked_stock_lookup(tracked_seed)

    # P-Wire-4c integration: prefer the real V71ViMonitor when it is
    # already wired on the handle (`v71.vi_monitor` ON earlier in
    # attach). Falls back to the stub + degraded_vi flag when ViMonitor
    # is OFF -- keeping paper smoke without VI safe (PATH_A entries
    # land but caller knows from the dashboard).
    if handle.vi_monitor is not None:
        is_vi_active_callable = handle.vi_monitor.is_vi_active
        system_state.degraded_vi = False
    else:
        def is_vi_active_callable(stock_code: str) -> bool:
            logger.warning(
                "trading_bridge: VI stub returned False for %s "
                "(P-Wire-4c not yet wired)",
                stock_code,
            )
            return False

        system_state.degraded_vi = True
        logger.warning(
            "trading_bridge: VI monitor not wired -- is_vi_active stub "
            "returns False; PATH_A entries will not be blocked by VI "
            "state (system_state.degraded_vi=True)",
        )

    ctx = BuyExecutorContext(
        exchange=handle.exchange_adapter,
        box_manager=handle.box_manager,
        position_store=handle.position_manager,
        notifier=handle.notification_service,
        clock=clock,
        is_vi_active=is_vi_active_callable,
        get_previous_close=get_previous_close,
        get_total_capital=get_total_capital,
        get_invested_pct_for_stock=get_invested_pct,
    )
    buy_executor = V71BuyExecutor(
        context=ctx, tracked_stock_resolver=tracked_lookup,
    )
    return {
        "buy_executor": buy_executor,
        "clock": clock,
        "total_capital_refresh": refresh_total,
        "prev_close_cache": prev_close_cache,
        "tracked_stock_cache": tracked_cache,
    }


# ---------------------------------------------------------------------------
# P-Wire-5: V71KiwoomWebSocket wiring + VI dispatcher
# ---------------------------------------------------------------------------
#
# Kiwoom realtime channels (PRICE_TICK / ORDER_EXECUTION / BALANCE / VI)
# arrive on a dedicated WebSocket. Phase 5 wired the transport client; this
# unit lifts it into the lifespan handle and registers a VI handler that
# dispatches 9068 (TRIGGERED / RESOLVED) events to V71ViMonitor.
#
# Wire-level field names for VI 9068 are not authoritatively documented;
# the handler tries common variants and falls back to a structured WARNING
# + silent skip rather than dispatching with garbage prices (헌법 §1).

# Common VI WS payload field aliases. Paper smoke (P7) will confirm the
# canonical names; the handler is intentionally permissive at this stage.
_VI_STATUS_KEYS = ("9068", "vi_kind", "vi_state")    # 1 = TRIGGERED, 2 = RESOLVED
_VI_TRIGGER_PRICE_KEYS = ("10", "vi_prc", "trigger_price")
_VI_PREV_CLOSE_KEYS = ("11", "prev_close", "last_close")
_VI_FIRST_PRICE_KEYS = ("10", "vi_prc", "resume_price")


def _make_vi_handler(vi_monitor: Any) -> Any:
    """Return an async coroutine that translates VI WS messages into
    ``vi_monitor.on_vi_triggered`` / ``on_vi_resolved`` calls.

    Permissive parsing (multiple field aliases) + structured WARNING +
    silent skip on unknown format. The handler must not raise -- the
    WebSocket dispatcher already isolates handler errors per-channel,
    but the bridge keeps the same fail-secure stance to avoid noisy
    alerts during paper smoke validation.
    """
    async def vi_handler(message: Any) -> None:
        try:
            stock_code = (message.item or "").strip().upper()
            if not _VALID_STOCK_CODE.match(stock_code):
                logger.warning(
                    "trading_bridge: VI WS message item is not a valid "
                    "stock_code (length=%d) -- skipping",
                    len(stock_code),
                )
                return
            values = message.values or {}
            status_raw = next(
                (values[k] for k in _VI_STATUS_KEYS if k in values),
                None,
            )
            if status_raw is None:
                logger.warning(
                    "trading_bridge: VI WS message for %s missing status "
                    "(tried %s) -- skipping",
                    stock_code, _VI_STATUS_KEYS,
                )
                return
            status = str(status_raw).strip()
            if status == "1":
                trigger_price = _coerce_int(
                    next(
                        (values[k] for k in _VI_TRIGGER_PRICE_KEYS
                         if k in values),
                        0,
                    ),
                )
                prev_close = _coerce_int(
                    next(
                        (values[k] for k in _VI_PREV_CLOSE_KEYS
                         if k in values),
                        0,
                    ),
                )
                if trigger_price <= 0:
                    logger.warning(
                        "trading_bridge: VI TRIGGERED for %s but no "
                        "trigger_price field -- skipping",
                        stock_code,
                    )
                    return
                await vi_monitor.on_vi_triggered(
                    stock_code,
                    trigger_price=trigger_price,
                    last_close_before_vi=prev_close or trigger_price,
                )
            elif status == "2":
                first_price = _coerce_int(
                    next(
                        (values[k] for k in _VI_FIRST_PRICE_KEYS
                         if k in values),
                        0,
                    ),
                )
                if first_price <= 0:
                    logger.warning(
                        "trading_bridge: VI RESOLVED for %s but no "
                        "first_price field -- skipping",
                        stock_code,
                    )
                    return
                await vi_monitor.on_vi_resolved(
                    stock_code, first_price_after_resume=first_price,
                )
            else:
                logger.warning(
                    "trading_bridge: VI WS for %s -- unknown status %r "
                    "(expected '1' or '2')",
                    stock_code, status,
                )
        except BaseException:  # noqa: BLE001 -- handler must not raise
            logger.exception(
                "trading_bridge: VI handler leaked unexpected exception"
            )

    return vi_handler


async def _build_kiwoom_websocket(
    handle: _TradingEngineHandle,
) -> dict[str, Any]:
    """Construct V71KiwoomWebSocket + register VI handler + subscribe.

    Cross-flag invariant: ``v71.kiwoom_exchange`` must be ON so the
    token_manager (shared with V71KiwoomClient) is available. ViMonitor
    is OPTIONAL -- the WebSocket can run without it (other channels
    still feed downstream consumers in future units).
    """
    import os

    from src.utils.feature_flags import is_enabled

    if not is_enabled("v71.kiwoom_exchange"):
        raise RuntimeError(
            "trading_bridge: v71.kiwoom_websocket enabled but "
            "v71.kiwoom_exchange is OFF -- WS depends on token_manager "
            "from the exchange stack"
        )
    if handle.token_manager is None:
        raise RuntimeError(
            "trading_bridge: V71KiwoomWebSocket requires a built "
            "token_manager (kiwoom_exchange flag built nothing)",
        )

    from src.core.v71.exchange.kiwoom_websocket import (
        V71KiwoomChannelType,
        V71KiwoomWebSocket,
    )

    is_paper = (
        os.environ.get("KIWOOM_ENV", "PRODUCTION").strip().upper() == "SANDBOX"
    )
    ws = V71KiwoomWebSocket(
        token_manager=handle.token_manager,
        is_paper=is_paper,
    )

    if handle.vi_monitor is not None:
        ws.register_handler(
            V71KiwoomChannelType.VI, _make_vi_handler(handle.vi_monitor),
        )
        # Account-level subscription (item="" -> auto-routed by Kiwoom).
        await ws.subscribe(V71KiwoomChannelType.VI)
    else:
        logger.warning(
            "trading_bridge: V71KiwoomWebSocket built but VI handler not "
            "registered (handle.vi_monitor=None) -- 9068 events will be "
            "ignored",
        )

    return {"ws": ws, "is_paper": is_paper}


def _build_vi_monitor(handle: _TradingEngineHandle) -> Any:
    """Construct V71ViMonitor (PRD 02 §10 VI state machine).

    Cross-flag invariant:
      * ``v71.vi_monitor`` is checked by V71ViMonitor.__init__'s
        ``require_enabled`` -- keeping the lifespan/constructor gate
        consistent.
      * ``v71.notification_v71`` must be ON because TRIGGERED / RESUMED
        emit HIGH alerts.

    Reuses ``handle.clock`` when P-Wire-4a/4b already built one;
    otherwise creates a fresh V71RealClock (stateless).
    """
    from src.utils.feature_flags import is_enabled

    if not is_enabled("v71.notification_v71"):
        raise RuntimeError(
            "trading_bridge: v71.vi_monitor enabled but "
            "v71.notification_v71 is OFF -- VI alerts cannot be delivered"
        )
    if handle.notification_service is None:
        raise RuntimeError(
            "trading_bridge: V71ViMonitor requires notification_service "
            "(v71.notification_v71 ON but service is queue-only)",
        )

    from src.core.v71.vi_monitor import V71ViMonitor, ViMonitorContext

    clock = handle.clock if handle.clock is not None else V71RealClock()
    ctx = ViMonitorContext(
        notifier=handle.notification_service,
        clock=clock,
        on_vi_resumed=None,  # orchestrator/ExitCalculator wiring later
    )
    return V71ViMonitor(context=ctx), clock


async def _build_exit_executor(handle: _TradingEngineHandle) -> Any:
    """Construct V71ExitExecutor.

    Cross-flag invariant (mirrors P-Wire-4a Buy):
    ``v71.exit_v71`` (used by V71ExitExecutor.__init__'s require_enabled)
    AND ``v71.kiwoom_exchange`` AND ``v71.notification_v71`` must be ON.

    Reuses ``handle.clock`` (V71RealClock instance) when P-Wire-4a is
    also active; otherwise builds a fresh one (V71RealClock is stateless).
    """
    from src.utils.feature_flags import is_enabled

    missing = [
        flag
        for flag in (
            "v71.exit_v71",
            "v71.kiwoom_exchange",
            "v71.notification_v71",
        )
        if not is_enabled(flag)
    ]
    if missing:
        raise RuntimeError(
            "trading_bridge: v71.exit_executor_v71 enabled but required "
            f"dependencies are OFF: {missing}"
        )
    if handle.exchange_adapter is None:
        raise RuntimeError(
            "trading_bridge: ExitExecutor requires exchange_adapter "
            "(v71.kiwoom_exchange flag built no adapter)"
        )
    if handle.box_manager is None:
        raise RuntimeError(
            "trading_bridge: ExitExecutor requires box_manager",
        )
    if handle.notification_service is None:
        raise RuntimeError(
            "trading_bridge: ExitExecutor requires notification_service "
            "(v71.notification_v71 ON but service is queue-only -- "
            "ExitExecutor cannot accept Notifier=None)",
        )

    from src.core.v71.exit.exit_executor import (
        ExitExecutorContext,
        V71ExitExecutor,
    )

    clock = handle.clock if handle.clock is not None else V71RealClock()
    ctx = ExitExecutorContext(
        exchange=handle.exchange_adapter,
        box_manager=handle.box_manager,
        notifier=handle.notification_service,
        clock=clock,
        on_position_closed=None,  # P-Wire-4c (ViMonitor) wires this
    )
    return V71ExitExecutor(context=ctx)


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

    # P-Wire-4c: V71ViMonitor wiring. Must run BEFORE BuyExecutor so the
    # real ``is_vi_active`` callable replaces the P-Wire-4a stub. Fail
    # closed if notification_service is missing (TRIGGERED/RESUMED HIGH
    # alerts cannot be delivered).
    if is_enabled("v71.vi_monitor"):
        try:
            vi_monitor, vi_clock = _build_vi_monitor(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.vi_monitor enabled but construction "
                "failed: %s",
                type(exc).__name__,
            )
            raise
        handle.vi_monitor = vi_monitor
        if handle.clock is None:
            handle.clock = vi_clock
        logger.info("trading_bridge: V71ViMonitor wired")
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.vi_monitor' disabled "
            "-- VI state machine OFF (BuyExecutor falls back to stub)",
        )

    # P-Wire-4a: V71BuyExecutor wiring. Cross-flag invariant requires
    # box_system + kiwoom_exchange + notification_v71 all ON; missing
    # any of those raises (handled by lifespan).
    if is_enabled("v71.buy_executor_v71"):
        try:
            built = await _build_buy_executor(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.buy_executor_v71 enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.buy_executor = built["buy_executor"]
        handle.clock = built["clock"]
        handle.total_capital_refresh = built["total_capital_refresh"]
        handle.prev_close_cache = built["prev_close_cache"]
        handle.tracked_stock_cache = built["tracked_stock_cache"]
        logger.info(
            "trading_bridge: V71BuyExecutor wired "
            "(tracked_stocks_cached=%d, vi_stub=true)",
            len(built["tracked_stock_cache"]),
        )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.buy_executor_v71' disabled "
            "-- buy_executor not constructed",
        )

    # P-Wire-4b: V71ExitExecutor wiring. Mirrors P-Wire-4a invariants
    # (cross-flag fail-loud); reuses handle.clock when available so Buy
    # and Exit share the same Clock instance.
    if is_enabled("v71.exit_executor_v71"):
        try:
            handle.exit_executor = await _build_exit_executor(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.exit_executor_v71 enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        # If P-Wire-4a left handle.clock=None (Buy disabled), re-use the
        # one ExitExecutor just built so future units (4c, P-Wire-5) see
        # a single shared clock.
        if handle.clock is None:
            handle.clock = handle.exit_executor._ctx.clock
        logger.info("trading_bridge: V71ExitExecutor wired")
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.exit_executor_v71' disabled "
            "-- exit_executor not constructed",
        )

    # P-Wire-5: V71KiwoomWebSocket realtime channels. Background asyncio
    # task is started after WS + handlers + subscriptions are in place so
    # detach can cancel cleanly. VI handler dispatches to vi_monitor
    # when wired (P-Wire-4c); other channels (PRICE_TICK, ORDER_EXECUTION,
    # BALANCE) join in subsequent units.
    if is_enabled("v71.kiwoom_websocket"):
        try:
            built = await _build_kiwoom_websocket(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.kiwoom_websocket enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.kiwoom_websocket = built["ws"]
        handle.kiwoom_websocket_task = asyncio.create_task(
            built["ws"].run(), name="v71_kiwoom_websocket",
        )
        logger.info(
            "trading_bridge: V71KiwoomWebSocket started "
            "(is_paper=%s, vi_handler=%s)",
            built["is_paper"],
            "wired" if handle.vi_monitor is not None else "off",
        )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.kiwoom_websocket' disabled "
            "-- realtime channels not subscribed",
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

    # P-Wire-4a/4b/4c: drop executors + monitor + supporting closures.
    # All are stateless (no aclose / cancel needed) -- the underlying
    # caches die with the closures.
    handle.buy_executor = None
    handle.exit_executor = None
    handle.vi_monitor = None
    handle.clock = None
    handle.total_capital_refresh = None
    handle.prev_close_cache = None
    handle.tracked_stock_cache = None
    # Reset M2 degraded flag so a clean detach + re-attach doesn't leak
    # the prior session's mode into the dashboard.
    system_state.degraded_vi = False

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

    # P-Wire-5: stop WebSocket BEFORE kiwoom_client (both depend on the
    # token_manager; the WS owns its own connection). Cancel the run
    # loop first so it stops fetching new tokens, then aclose the
    # underlying socket.
    if handle.kiwoom_websocket_task is not None:
        if handle.kiwoom_websocket is not None:
            try:
                await handle.kiwoom_websocket.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "trading_bridge: kiwoom_websocket.aclose() failed: %s",
                    type(exc).__name__,
                )
        handle.kiwoom_websocket_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await handle.kiwoom_websocket_task
        handle.kiwoom_websocket_task = None
    handle.kiwoom_websocket = None

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
