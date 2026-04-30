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
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from datetime import time as _Time
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
        # Shared SQLAlchemy async session factory (DatabaseManager._session_factory).
        # Captured at attach time so position_manager / buy_executor / reconciler
        # all share the same factory for atomic transactions (P-Wire-Box-4 Q3/Q9).
        self.session_factory: Any = None
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
        # #1 (2026-04-30): Kiwoom maintenance window auto-SAFE_MODE.
        # 매일 4회 점검 시간(KST 06:55-07:35 + 00:55-01:05 + 02:55-03:05 +
        # 16:55-17:05) 도달 시 SAFE_MODE 자동 진입 + 종료 시 reconcile_all
        # 호출. detach 가 cancel + await 책임.
        self.maintenance_task: asyncio.Task[None] | None = None
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
        # P-Wire-6: V71ExitCalculator + V71ExitOrchestrator. The
        # orchestrator owns the PRICE_TICK handler that fans out to
        # ExitExecutor; the calculator is the stateless pure-decision
        # leaf the orchestrator calls. No background task -- handler
        # registration is sufficient.
        self.exit_calculator: Any = None
        self.exit_orchestrator: Any = None
        # P-Wire-8: V71DailySummary + V71DailySummaryScheduler. Scheduler
        # owns an asyncio.Task that wakes at 15:30 each trading day and
        # dispatches the LOW-severity daily summary through the
        # notification queue. detach must call ``scheduler.stop()`` so
        # the task is cancelled before notification_service goes away.
        self.daily_summary: Any = None
        self.daily_summary_scheduler: Any = None
        # P-Wire-9: V71MonthlyReview + V71MonthlyReviewScheduler. Same
        # pattern as P-Wire-8 but fires on the 1st of every month at
        # 09:00 KST.
        self.monthly_review: Any = None
        self.monthly_review_scheduler: Any = None
        # P-Wire-10: V7.0 TelegramBot (shared for outbound + commands) +
        # V71TelegramCommands. Polling task is owned by the V7.0 bot's
        # ``start_polling`` / ``stop_polling`` -- detach must call stop
        # before notification stack tears down.
        self.telegram_bot: Any = None
        self.telegram_commands: Any = None
        # P-Wire-11: V71RestartRecovery (§13 7-step). Run-once at attach
        # to clean up orphan orders + reconcile state after a restart.
        # Position-side V71Reconciler is built specifically for this
        # (the exchange-side reconciler in P-Wire-2 has different API).
        self.position_reconciler: Any = None
        self.restart_recovery: Any = None
        self.restart_recovery_report: Any = None
        # P-Wire-12: V71CandleManager (PATH_A 3분봉 + PATH_B 일봉 dispatcher).
        # Owns the PRICE_TICK handler on V71KiwoomWebSocket and the EOD
        # asyncio.Task scheduler. ``candle_history_task`` is the
        # background ka10081 priming task (architect Q6 -- non-blocking
        # boot). Both must release before kiwoom_websocket.aclose().
        self.candle_manager: Any = None
        self.candle_history_task: asyncio.Task[None] | None = None
        # P-Wire-13 (Phase A Step F follow-up): V71BoxEntryDetector pair.
        # PATH_A subscribes to 3분봉 candles and dispatches PULLBACK_A /
        # BREAKOUT_A entries; PATH_B subscribes to daily candles and
        # dispatches PATH_B entries. Both register with V71CandleManager
        # via ``register_on_complete`` and release through
        # ``unregister_on_complete`` on detach (P-Wire-13 H1 leak fix).
        self.box_entry_detector_path_a: Any = None
        self.box_entry_detector_path_b: Any = None
        # P-Wire-14 (Phase A Step F follow-up): market_calendar holiday
        # seed source for diagnostics. ``"db"`` when the DB had rows;
        # ``"hardcoded_fallback"`` when KR_HOLIDAYS_2026 was used (DB
        # empty / unreachable). Surfaced in /system/status so operators
        # know whether to seed the table.
        self.market_calendar_source: str | None = None


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


# ---------------------------------------------------------------------
# #1 + #4 (2026-04-30): 키움 점검 시간 자동 SAFE_MODE + orphan order 정리
# ---------------------------------------------------------------------
#
# 사용자 키움 답변 (2026-04-30): 매일 07:00-07:30 조건검색 재기동 + 추가
# 01:00 / 03:00 / 17:00 close 보고. 우리 시스템이 점검 시간을 인지하지
# 못하면 BuyExecutor / ExitExecutor 가 매매 trigger -> 키움 reject ->
# 박스 invalidation 위험. ±5분 buffer 로 사전 차단 + 재가동 직후
# reconcile_all 호출로 drift 보정.

# 사용자 키움 답변 정정 (2026-04-30, Q8): 정확한 점검 시간:
#   * 01:00-01:30 (30 분)
#   * 05:50-06:10 (20 분)
#   * 07:00-07:30 (30 분 -- 조건검색 재기동)
# 주말 동일. ±5 분 buffer 로 매매 trigger 사전 차단. 03:00 / 17:00 은
# 최초 답변에서 close 보고로 추정되었으나 정밀 답변에 명시되지 않아
# 제거 (false positive 매매 차단 회피).
_MAINTENANCE_WINDOWS_KST: tuple[tuple[_Time, _Time], ...] = (
    (_Time(0, 55), _Time(1, 35)),    # 01:00-01:30 ±5분
    (_Time(5, 45), _Time(6, 15)),    # 05:50-06:10 ±5분
    (_Time(6, 55), _Time(7, 35)),    # 07:00-07:30 ±5분 (조건검색 재기동)
)
_MAINTENANCE_REASON_PREFIX = "kiwoom_maintenance:"
_MAINTENANCE_POLL_SECONDS = 30.0

# #4: WS-only 끊김 시 키움 체결 통보 누락으로 SUBMITTED 영구 stuck
# 회피. 5분 이상 SUBMITTED/PARTIAL 인 주문을 일괄 cancel.
_ORPHAN_ORDER_THRESHOLD_SECONDS = 300


def _current_maintenance_window() -> tuple[_Time, _Time] | None:
    """현재 KST 시간이 점검 윈도우 안이면 (start, end) 반환, 아니면 None."""
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).time()
    for start, end in _MAINTENANCE_WINDOWS_KST:
        if start <= now_kst <= end:
            return (start, end)
    return None


async def _maintenance_schedule_loop(handle: _TradingEngineHandle) -> None:
    """매일 점검 시간 ±buffer 자동 SAFE_MODE 진입 + 종료 시 reconcile_all.

    auto-safe 와 manual safe_mode 구분: ``safe_mode_reason`` 이
    ``_MAINTENANCE_REASON_PREFIX`` 로 시작하면 auto, 그 외는 운영자 수동.
    auto 만 자동 해제되며 manual 은 사용자 수동 resume 까지 유지된다.
    """
    from src.web.v71.api.system.state import system_state

    logger.info("trading_bridge: maintenance schedule loop started")
    while True:
        try:
            window = _current_maintenance_window()
            current_reason = system_state.safe_mode_reason or ""
            was_auto_safe = current_reason.startswith(
                _MAINTENANCE_REASON_PREFIX
            )

            if window is not None and not system_state.safe_mode:
                window_str = (
                    f"{window[0].strftime('%H:%M')}-"
                    f"{window[1].strftime('%H:%M')}"
                )
                system_state.safe_mode = True
                system_state.safe_mode_reason = (
                    f"{_MAINTENANCE_REASON_PREFIX} {window_str} KST"
                )
                system_state.safe_mode_entered_at = datetime.now(timezone.utc)
                logger.warning(
                    "trading_bridge: 키움 점검 시간 진입 (%s KST) -- "
                    "SAFE_MODE 자동 진입 (BuyExecutor / ExitExecutor 차단)",
                    window_str,
                )
            elif window is None and was_auto_safe:
                logger.warning(
                    "trading_bridge: 키움 점검 시간 종료 -- SAFE_MODE 자동 "
                    "해제 + reconcile_all (drift 보정)"
                )
                system_state.safe_mode = False
                system_state.safe_mode_reason = None
                system_state.safe_mode_resumed_at = datetime.now(timezone.utc)
                if handle.reconciler is not None:
                    try:
                        await handle.reconciler.reconcile_all()
                        logger.info(
                            "trading_bridge: post-maintenance reconcile_all "
                            "complete"
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "trading_bridge: post-maintenance reconcile_all "
                            "failed: %s",
                            type(exc).__name__,
                        )
                # #7 post-maintenance: TS state 재계산 -- 점검 30분 동안
                # PRICE_TICK 누락 가능성 큼.
                try:
                    ts_updated = await _refresh_ts_base_prices(handle)
                    if ts_updated > 0:
                        logger.info(
                            "trading_bridge: post-maintenance refreshed "
                            "%d ts_base_price values",
                            ts_updated,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "trading_bridge: post-maintenance "
                        "refresh_ts_base_prices failed: %s",
                        type(exc).__name__,
                    )
                # #6 post-maintenance: VI state 재확인 (점검 동안 발동
                # 가능성).
                try:
                    vi_triggered = await _refresh_vi_state(handle)
                    if vi_triggered > 0:
                        logger.info(
                            "trading_bridge: post-maintenance applied %d "
                            "new VI triggers",
                            vi_triggered,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "trading_bridge: post-maintenance "
                        "refresh_vi_state failed: %s",
                        type(exc).__name__,
                    )

            await asyncio.sleep(_MAINTENANCE_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - always-run policy
            logger.error(
                "trading_bridge: maintenance loop iteration failed: %s",
                type(exc).__name__,
            )
            try:
                await asyncio.sleep(_MAINTENANCE_POLL_SECONDS)
            except asyncio.CancelledError:
                raise


async def _refresh_ts_base_prices(
    handle: _TradingEngineHandle,
) -> int:
    """OPEN position 의 ts_base_price 를 ka10081 직전 20영업일 high 로
    재계산 (#7).

    PRD §5 BasePrice = ``Highest(High, 20)``. WS 끊김 사이 PRICE_TICK
    누락 -> ts_base_price stale -> effective_stop 잘못 계산 -> 잘못된
    자동 청산 위험. 재연결 직후 + post-maintenance 에서 catch-up.

    TS 는 단조증가 (PRD §5) -- 새 high > 기존 일 때만 update, 작거나
    같으면 skip. Returns 갱신된 position 수.

    키움 답변 (2026-04-30, Q6): ka10081 단일 호출 최대 600개 + 휴장일
    자동 제외 -> cont_yn 없이 직전 20영업일 high 추출 가능.
    """
    if handle.kiwoom_client is None:
        return 0

    from decimal import Decimal as _Decimal

    from sqlalchemy import select

    from src.database.connection import get_db_manager
    from src.database.models_v71 import PositionStatus, V71Position

    db = get_db_manager()
    today_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime(
        "%Y%m%d"
    )

    updated = 0
    failed = 0
    try:
        async with db.session() as session:
            stmt = select(V71Position).where(
                V71Position.status != PositionStatus.CLOSED
            )
            result = await session.execute(stmt)
            positions = list(result.scalars().all())
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "trading_bridge: refresh_ts_base_prices DB fetch failed: %s",
            type(exc).__name__,
        )
        return 0

    for position in positions:
        try:
            resp = await handle.kiwoom_client.get_daily_chart(
                stock_code=position.stock_code,
                base_date=today_kst,
            )
            data = resp.data or {}
            bars = data.get("stk_dt_pole_chart_qry") or []
            if not bars:
                continue

            # 직전 20영업일 high (휴장일 자동 제외 -- 키움 spec).
            highs: list[int] = []
            for bar in bars[:20]:
                high_raw = bar.get("high_pric") or bar.get("high") or "0"
                high = _coerce_int(high_raw)
                if high > 0:
                    highs.append(high)
            if not highs:
                continue

            new_base = max(highs)

            # 단조증가 update -- 새 base > 기존 일 때만.
            async with db.session() as session:
                pos = await session.get(V71Position, position.id)
                if pos is None:
                    continue
                current_base = int(pos.ts_base_price or 0)
                if new_base > current_base:
                    pos.ts_base_price = _Decimal(new_base)
                    pos.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    updated += 1
                    logger.info(
                        "trading_bridge: refresh ts_base_price stock=%s "
                        "old=%d new=%d",
                        position.stock_code,
                        current_base,
                        new_base,
                    )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning(
                "refresh_ts_base_price failed stock=%s: %s",
                position.stock_code,
                type(exc).__name__,
            )

    if updated > 0 or failed > 0:
        logger.info(
            "trading_bridge: refresh_ts_base_prices updated=%d failed=%d "
            "(total positions=%d)",
            updated,
            failed,
            len(positions),
        )
    return updated


async def _refresh_vi_state(handle: _TradingEngineHandle) -> int:
    """ka10054 호출 + V71ViMonitor 일괄 갱신 (#6, 2026-04-30).

    WS 끊김 사이 1h 채널 push 누락 -> 미인지 VI 발동 종목 -> BuyExecutor
    가 vi_active=False 로 인식 후 매수 진행 위험 (헌법 §1 위반). ka10054
    snapshot 으로 catch-up.

    키움 답변 (Q4): ka10054 가 당일 누적 VI 발동 종목 list 반환 -> WS
    끊김 보완에 충분. 별도 history endpoint 없음.

    Returns 신규 트리거된 종목 수 (이미 활성인 종목 idempotent skip).
    """
    if handle.kiwoom_client is None or handle.vi_monitor is None:
        return 0

    try:
        resp = await handle.kiwoom_client.get_vi_active_stocks()
        data = resp.data or {}
        motn_stk = data.get("motn_stk") or []
        if not motn_stk:
            logger.debug(
                "trading_bridge: refresh_vi_state -- no active VI stocks"
            )
            return 0

        triggered = await handle.vi_monitor.apply_kiwoom_snapshot(
            motn_stk=motn_stk,
        )
        if triggered > 0:
            logger.warning(
                "trading_bridge: refresh_vi_state applied %d new VI "
                "triggers (catch-up from missed 1h push)",
                triggered,
            )
        return triggered
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "trading_bridge: refresh_vi_state failed: %s",
            type(exc).__name__,
        )
        return 0


async def _cancel_orphan_submitted_orders(
    handle: _TradingEngineHandle,
) -> int:
    """SUBMITTED / PARTIAL 5분 이상 stuck 주문 일괄 cancel.

    WS-only 끊김 시 키움 체결 통보 누락 -> DB orders state 영구 stuck
    회피. on_reconnect_recovered 에서 reconcile_all 직후 호출.

    Returns 정리된 주문 수.
    """
    if handle.order_manager is None:
        return 0

    from sqlalchemy import select

    from src.database.connection import get_db_manager
    from src.database.models_v71 import OrderState, V71Order

    db = get_db_manager()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=_ORPHAN_ORDER_THRESHOLD_SECONDS
    )

    cancelled = 0
    failed = 0
    try:
        async with db.session() as session:
            stmt = (
                select(V71Order)
                .where(V71Order.state.in_(
                    [OrderState.SUBMITTED, OrderState.PARTIAL]
                ))
                .where(V71Order.submitted_at < cutoff)
            )
            result = await session.execute(stmt)
            orders = list(result.scalars().all())

        for order in orders:
            try:
                await handle.order_manager.cancel_order(order.id)
                cancelled += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning(
                    "cancel_orphan_order failed order_id=%s: %s",
                    order.id,
                    type(exc).__name__,
                )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "trading_bridge: cancel_orphan_orders fetch failed: %s",
            type(exc).__name__,
        )
        return 0

    if cancelled > 0 or failed > 0:
        logger.info(
            "trading_bridge: cancel_orphan_orders cancelled=%d failed=%d",
            cancelled,
            failed,
        )
    return cancelled


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


def _build_telegram_bot() -> Any:
    """Construct a single V7.0 :class:`TelegramBot` instance to be shared
    by the notification service (outbound) and command registrar (inbound).

    Returns ``None`` when ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``
    are missing -- the notification service then operates in *queue
    only* mode and the command registrar is skipped.
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

    return TelegramBot()


def _build_telegram_send_fn(bot: Any) -> Any:
    """Wrap a constructed :class:`TelegramBot` into the V7.1
    ``TelegramSendFn`` callable contract.

    parse_mode is intentionally not forwarded -- CLAUDE.md Part 1.1
    forbids it, and V7.0 TelegramBot already guards (defence in depth).
    """
    if bot is None:
        return None

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
    bot = _build_telegram_bot()
    telegram_send = _build_telegram_send_fn(bot)

    return {
        "clock": clock,
        "telegram_bot": bot,
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
_HOLIDAY_CACHE_DB_TIMEOUT_SECONDS = 10.0  # P-Wire-14 mirror — same boot bound
# Top-level kt00018 keys (KIWOOM_API_ANALYSIS.md).
#
# Priority order (2026-04-30 production observation + 키움 답변):
#   1. ``prsm_dpst_aset_amt`` (추정 예탁 자산 = 예수금 + 주식 평가).
#      비중 결정 + 30 % per-stock cap 계산에 가장 적합 -- 보유 주식이
#      없어도 예수금 만큼은 매수 가능하므로 ``tot_evlt_amt`` 0 -> capital
#      0 -> 모든 매수 차단 회귀를 방지한다.
#   2. ``tot_evlt_amt`` (총 주식 평가금) -- 예수금 키 부재 시 fallback.
#   3. ``tot_pur_amt`` (총 매입금, 역사적) -- 위 둘 다 0 일 때 마지막
#      fallback.
#
# 또한 첫 매칭 키가 0 이면 다음 키 시도 (위 회귀 방지). 모든 키 부재
# 또는 모두 0 이면 캐시 0 + WARNING -> 헌법 §1 매수 차단.
_KT00018_TOTAL_EVAL_KEYS = ("prsm_dpst_aset_amt", "tot_evlt_amt", "tot_pur_amt")
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
        body = getattr(response, "data", None)
        if not isinstance(body, dict):
            logger.warning(
                "trading_bridge: get_total_capital response shape "
                "unexpected: %s -- caching 0",
                type(body).__name__,
            )
            state["value"] = 0
            state["fetched_at"] = time.monotonic()
            return
        # 키 우선순위 + 0 fallback: 첫 매칭 키 값이 > 0 이면 즉시 채택,
        # 0 이면 다음 키 시도. 모든 키가 부재 또는 모두 0 이면 캐시 0.
        matched_key: str | None = None
        matched_value = 0
        present_keys: list[str] = []
        for key in _KT00018_TOTAL_EVAL_KEYS:
            if key in body:
                present_keys.append(key)
                v = _coerce_int(body[key])
                if v > 0:
                    matched_key = key
                    matched_value = v
                    break
        if matched_key is not None:
            state["value"] = matched_value
            state["fetched_at"] = time.monotonic()
            logger.info(
                "trading_bridge: capital matched key=%s value=%d "
                "(present_keys=%s)",
                matched_key,
                matched_value,
                present_keys,
            )
            return
        # 부재 또는 모두 0
        logger.warning(
            "trading_bridge: get_total_capital all keys missing or zero "
            "(checked=%s, present=%s) -- caching 0 (PATH_A buys will "
            "abandon via cap check)",
            list(_KT00018_TOTAL_EVAL_KEYS),
            present_keys,
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


async def _load_holidays_seed() -> tuple[frozenset, str]:
    """Load market_calendar holidays once at lifespan start (P-Wire-14).

    Returns ``(holidays, source)`` where ``source`` is one of:
      * ``"db"`` -- DB had at least one HOLIDAY/EMERGENCY_CLOSED row.
      * ``"hardcoded_fallback"`` -- DB unreachable / timed out / empty.
        ``KR_HOLIDAYS_2026`` is used so the schedule is never blank.

    Constitution §4 (system always runs) takes precedence over a clean
    failure here: a hung Supabase pooler or a forgotten DB seed must
    not stop trading -- the fallback list ships well-known holidays so
    the box-entry pipeline can short-circuit on at least the obvious
    closures while operators investigate.
    """
    from sqlalchemy import select

    from src.core.v71.market.v71_kr_holidays import KR_HOLIDAYS_2026
    from src.database.connection import get_db_manager
    from src.database.models_v71 import MarketCalendar, MarketDayType

    db = get_db_manager()
    closed_types = (
        MarketDayType.HOLIDAY,
        MarketDayType.EMERGENCY_CLOSED,
    )
    try:
        async with asyncio.timeout(_HOLIDAY_CACHE_DB_TIMEOUT_SECONDS), \
                db.session() as session:
            result = await session.execute(
                select(MarketCalendar.trading_date).where(
                    MarketCalendar.day_type.in_(closed_types),
                ),
            )
            rows = [row[0] for row in result.all()]
    except asyncio.TimeoutError:
        logger.warning(
            "trading_bridge: market_calendar prime timed out (>%.0fs) "
            "-- using hardcoded KR_HOLIDAYS_2026 fallback",
            _HOLIDAY_CACHE_DB_TIMEOUT_SECONDS,
        )
        return KR_HOLIDAYS_2026, "hardcoded_fallback"
    except Exception as exc:  # noqa: BLE001 -- never block boot
        logger.warning(
            "trading_bridge: market_calendar prime failed (%s) "
            "-- using hardcoded KR_HOLIDAYS_2026 fallback",
            type(exc).__name__,
        )
        return KR_HOLIDAYS_2026, "hardcoded_fallback"

    if not rows:
        logger.warning(
            "trading_bridge: market_calendar table empty -- using "
            "hardcoded KR_HOLIDAYS_2026 fallback. Operators should "
            "seed market_calendar via dashboard or SQL for accurate "
            "KRX holidays + half-days.",
        )
        return KR_HOLIDAYS_2026, "hardcoded_fallback"
    return frozenset(rows), "db"


async def _build_market_calendar(
    handle: _TradingEngineHandle,
) -> None:
    """Seed V71MarketSchedule with the latest holiday list (P-Wire-14).

    Runs unconditionally (no feature flag) because the box-entry
    pipeline's safety net depends on it -- a flag-off path would let
    an operator silently ship a configuration where every weekday is
    treated as a trading day. The fallback list keeps the wiring safe
    even when the DB is empty/unreachable.
    """
    from src.core.v71.market.v71_market_schedule import (
        get_v71_market_schedule,
    )

    holidays, source = await _load_holidays_seed()
    schedule = get_v71_market_schedule()
    schedule.set_holidays(holidays)
    handle.market_calendar_source = source
    logger.info(
        "trading_bridge: V71MarketSchedule seeded (count=%d, source=%s)",
        len(holidays), source,
    )


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

    # Surface the capital getter to the web layer (system/status) so the
    # box wizard can size positions against the real account balance
    # instead of a hardcoded constant. Idempotent overwrite -- last
    # buy_executor build wins (only one is built per attach).
    from src.web.v71.api.system.state import system_state as _system_state
    _system_state.get_total_capital = get_total_capital
    try:
        _initial_cap = get_total_capital()
        # WARNING level 로 강제 (uvicorn logging 설정에서 stdlib INFO 가
        # 일부 누락되는 케이스 관찰됨). 진단 후 INFO 로 다시 낮출 예정.
        logger.warning(
            "trading_bridge: capital getter registered to system_state "
            "(initial_value=%s, type=%s)",
            _initial_cap,
            type(_initial_cap).__name__,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        logger.error(
            "trading_bridge: capital getter registered but initial call "
            "failed: %s",
            type(exc).__name__,
        )
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

    # P-Wire-Box-4: cooldown dispatcher closure. The detectors are
    # constructed *after* this builder runs, so we resolve them lazily
    # from the handle every call. No-op when the detectors are not
    # wired yet (legacy mode / paper smoke without auto-entry).
    def _set_box_cooldown(box_id: str, seconds: float) -> None:
        for detector in (
            handle.box_entry_detector_path_a,
            handle.box_entry_detector_path_b,
        ):
            if detector is not None and hasattr(detector, "set_cooldown"):
                try:
                    detector.set_cooldown(box_id, seconds)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "trading_bridge: detector.set_cooldown failed "
                        "(box=%s, type=%s)",
                        box_id, type(exc).__name__,
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
        session_factory=handle.session_factory,
        set_box_cooldown=_set_box_cooldown,
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

    async def _on_ws_reconnect_recovered() -> None:
        """WS 끊김 후 재연결 직후 트리거.

        주말 / 새벽 키움 점검으로 WS 가 끊기면 그 사이의 체결 / 잔고 변동 /
        VI 발동은 키움이 buffered 로 보내주지 않는다 (push-only). 5분 주기
        reconciler loop 가 fallback 이지만 짧은 끊김 사이의 drift 는 5분간
        반영되지 않는다. 이 콜백이 재연결 직후 ``reconcile_all()`` 을 즉시
        실행해서 drift 를 즉시 closure -> 자동 매매 안전성 보장.

        ``handle.reconciler`` 가 None (reconciliation_v71 flag 비활성)
        이면 안내 로그만 남기고 noop -- 운영자가 의도적으로 reconciler 를
        끈 케이스에 강제 활성화하지 않는다.
        """
        if handle.reconciler is None:
            logger.info(
                "trading_bridge: WS reconnect recovered but reconciler is "
                "None (v71.reconciliation_v71 disabled) -- 5-min loop "
                "fallback only",
            )
            return
        try:
            await handle.reconciler.reconcile_all()
            logger.info(
                "trading_bridge: WS reconnect reconcile_all complete",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "trading_bridge: WS reconnect reconcile_all failed: %s",
                type(exc).__name__,
            )

        # #4 (2026-04-30): WS-only 끊김 시 키움 체결 통보 누락으로
        # 영구 SUBMITTED stuck 된 주문이 있으면 일괄 cancel. reconcile_all
        # 이 잔고 차이를 이미 catch 했으므로 stuck 주문은 빈 껍데기.
        try:
            cleaned = await _cancel_orphan_submitted_orders(handle)
            if cleaned > 0:
                logger.warning(
                    "trading_bridge: WS reconnect cancelled %d orphan "
                    "SUBMITTED/PARTIAL orders",
                    cleaned,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "trading_bridge: WS reconnect orphan cancel failed: %s",
                type(exc).__name__,
            )

        # #7 (2026-04-30): TS state 재계산 -- 끊김 사이 PRICE_TICK 누락으로
        # ts_base_price stale 가능 -> effective_stop 잘못 계산 -> 잘못된
        # 자동 청산. ka10081 직전 20봉 high 로 catch-up. 단조증가 보장.
        try:
            ts_updated = await _refresh_ts_base_prices(handle)
            if ts_updated > 0:
                logger.warning(
                    "trading_bridge: WS reconnect refreshed %d "
                    "ts_base_price values",
                    ts_updated,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "trading_bridge: WS reconnect refresh_ts_base_prices "
                "failed: %s",
                type(exc).__name__,
            )

        # #6 (2026-04-30): VI state 재확인 -- 끊김 사이 1h 채널 push 누락
        # -> 미인지 VI 발동 -> BuyExecutor 매수 차단 안 됨 (헌법 §1).
        # ka10054 snapshot 으로 catch-up.
        try:
            vi_triggered = await _refresh_vi_state(handle)
            if vi_triggered > 0:
                logger.warning(
                    "trading_bridge: WS reconnect applied %d new VI "
                    "triggers from ka10054",
                    vi_triggered,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "trading_bridge: WS reconnect refresh_vi_state failed: %s",
                type(exc).__name__,
            )

    ws = V71KiwoomWebSocket(
        token_manager=handle.token_manager,
        is_paper=is_paper,
        on_reconnect_recovered=_on_ws_reconnect_recovered,
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


async def _build_daily_summary(
    handle: _TradingEngineHandle,
) -> Any:
    """Construct V71DailySummary + V71DailySummaryScheduler at 15:30 KST.

    Cross-flag invariant:
      * v71.notification_v71 ON (notifier required)
      * v71.position_v71 ON (position manager required)
      * v71.box_system ON (box manager required)
    Optional:
      * v71.kiwoom_exchange ON → get_total_capital provides PnL %
      * list_tracked: empty list (TrackedSummary wiring is a follow-up)
    """
    from src.utils.feature_flags import is_enabled

    if not is_enabled("v71.notification_v71"):
        raise RuntimeError(
            "trading_bridge: v71.daily_summary requires v71.notification_v71"
        )
    if handle.notification_service is None:
        raise RuntimeError(
            "trading_bridge: V71DailySummary requires notification_service"
        )
    if handle.position_manager is None:
        raise RuntimeError(
            "trading_bridge: V71DailySummary requires position_manager"
        )
    if handle.box_manager is None:
        raise RuntimeError(
            "trading_bridge: V71DailySummary requires box_manager"
        )

    from src.core.v71.notification.v71_daily_summary import (
        DailySummaryContext,
        ScheduledTime,
        V71DailySummary,
        V71DailySummaryScheduler,
    )

    clock = handle.clock if handle.clock is not None else V71RealClock()
    # P-Wire-Box-3: list_tracked now hits the DB through the shared
    # session_factory the box_manager already owns.
    from src.web.v71.tracked_summary import make_list_tracked_callable
    _list_tracked = make_list_tracked_callable(handle.box_manager._sm)  # noqa: SLF001

    # get_total_capital is a kiwoom-backed callable assembled in
    # _build_buy_executor. Reuse its closure so capital appears in the
    # summary's PnL % when buy_executor is wired.
    get_total_capital_fn: Any = None
    if handle.buy_executor is not None:
        ctx = handle.buy_executor._ctx
        get_total_capital_fn = ctx.get_total_capital

    summary_ctx = DailySummaryContext(
        position_manager=handle.position_manager,
        box_manager=handle.box_manager,
        notifier=handle.notification_service,
        clock=clock,
        list_tracked=_list_tracked,
        get_total_capital=get_total_capital_fn,
        get_tomorrow_events=None,
    )
    summary = V71DailySummary(context=summary_ctx)
    scheduler = V71DailySummaryScheduler(
        daily_summary=summary, clock=clock,
        target=ScheduledTime(hour=15, minute=30),
    )
    await scheduler.start()
    return summary, scheduler


async def _build_restart_recovery(
    handle: _TradingEngineHandle,
) -> Any:
    """Build V71RestartRecovery (§13 7-step) + run once at attach.

    Cross-flag invariant:
      * v71.restart_recovery ON
      * v71.notification_v71 ON (CRITICAL alert at Step 7)
      * v71.kiwoom_exchange ON (kt00018 + cancel_order needed)
      * v71.reconciliation_v71 ON (Step 3 reconciliation)

    Position-side V71Reconciler is built locally (the P-Wire-2
    exchange-side reconciler has a different ``reconcile_all()`` API
    that already fetches balances internally; the recovery context
    expects ``reconcile(broker_balances=...)``).

    Production safety:
      * Step 2 cancels orphan orders (state in [SUBMITTED, PARTIAL])
      * Step 3 reconciles broker balance vs DB positions
      * Step 4 re-subscribes PRICE_TICK for all open positions
      * Step 0/6 toggles ``system_state.safe_mode`` so dashboard +
        BuyExecutor see the recovery window
    """
    from src.utils.feature_flags import is_enabled

    for flag in (
        "v71.notification_v71",
        "v71.kiwoom_exchange",
        "v71.reconciliation_v71",
    ):
        if not is_enabled(flag):
            raise RuntimeError(
                f"trading_bridge: v71.restart_recovery requires {flag}"
            )
    for slot, name in (
        (handle.notification_service, "notification_service"),
        (handle.kiwoom_client, "kiwoom_client"),
        (handle.order_manager, "order_manager"),
        (handle.position_manager, "position_manager"),
        (handle.box_manager, "box_manager"),
    ):
        if slot is None:
            raise RuntimeError(
                f"trading_bridge: V71RestartRecovery requires {name}"
            )

    from src.core.v71.position.v71_reconciler import (
        ReconcilerContext as PositionReconcilerContext,
    )
    from src.core.v71.position.v71_reconciler import (
        V71Reconciler as PositionV71Reconciler,
    )
    from src.core.v71.restart_recovery import (
        RecoveryContext,
        V71RestartRecovery,
    )
    from src.core.v71.skills.reconciliation_skill import KiwoomBalance

    clock = handle.clock if handle.clock is not None else V71RealClock()

    # Position-side reconciler -- TrackedSummary callbacks are stubs
    # (follow-up unit). end_tracking is a soft no-op.
    def _list_tracked_for_stock(_stock_code: str) -> list[Any]:
        return []

    async def _end_tracking(
        _tracked_stock_id: str, _reason: str,
    ) -> None:
        return None

    pos_ctx = PositionReconcilerContext(
        position_manager=handle.position_manager,
        box_manager=handle.box_manager,
        notifier=handle.notification_service,
        clock=clock,
        list_tracked_for_stock=_list_tracked_for_stock,
        end_tracking=_end_tracking,
        session_factory=handle.session_factory,
    )
    position_reconciler = PositionV71Reconciler(context=pos_ctx)

    # 10 callable derivation
    async def _connect_db() -> None:
        from sqlalchemy import text

        from src.database.connection import get_db_manager
        db = get_db_manager()
        async with db.session() as session:
            await session.execute(text("SELECT 1"))

    async def _refresh_kiwoom_token() -> None:
        if handle.token_manager is None:
            raise RuntimeError("token_manager not built")
        # Force fresh token (current implementation re-issues on
        # expiry; calling get_token() at restart re-validates).
        await handle.token_manager.get_token()

    async def _connect_websocket() -> None:
        # WS run loop runs in background. State check + raise if CLOSED
        # so RecoveryReport.failures captures it.
        if handle.kiwoom_websocket is None:
            raise RuntimeError("kiwoom_websocket not built")
        from src.core.v71.exchange.kiwoom_websocket import V71WebSocketState
        st = handle.kiwoom_websocket.state
        if st == V71WebSocketState.CLOSED:
            raise RuntimeError(
                f"kiwoom_websocket state is {st.value}",
            )

    async def _connect_telegram() -> None:
        if handle.telegram_bot is None:
            raise RuntimeError("telegram_bot not built")
        # No active probe -- a getMe call here would land in transcripts
        # during dry-run. Boot-time wiring is sufficient signal.

    async def _cancel_all_pending_orders() -> int:
        from sqlalchemy import select

        from src.core.v71.exchange.order_manager import V71OrderManager
        from src.database.connection import get_db_manager
        from src.database.models_v71 import OrderState, V71Order

        db = get_db_manager()
        try:
            async with db.session() as session:
                result = await session.execute(
                    select(V71Order.id).where(
                        V71Order.state.in_(
                            [OrderState.SUBMITTED, OrderState.PARTIAL],
                        ),
                    ),
                )
                order_ids = [row[0] for row in result.all()]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: cancel_all_pending DB query failed: %s",
                type(exc).__name__,
            )
            return 0
        cancelled = 0
        om: V71OrderManager = handle.order_manager
        for oid in order_ids:
            try:
                await om.cancel_order(oid)
                cancelled += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "trading_bridge: cancel order %s failed: %s",
                    str(oid)[:8], type(exc).__name__,
                )
        return cancelled

    async def _fetch_broker_balances() -> list[Any]:
        try:
            response = await handle.kiwoom_client.get_account_balance()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: fetch_broker_balances kt00018 failed: %s",
                type(exc).__name__,
            )
            return []
        body = getattr(response, "body", response)
        if not isinstance(body, dict):
            return []
        holdings = body.get("acnt_evlt_remn_indv_tot") or []
        balances: list[KiwoomBalance] = []
        for row in holdings:
            try:
                stock_code = str(row.get("stk_cd", "")).strip().upper()
                if not _VALID_STOCK_CODE.match(stock_code):
                    continue
                balances.append(
                    KiwoomBalance(
                        stock_code=stock_code,
                        quantity=_coerce_int(row.get("rmnd_qty", 0)),
                        avg_price=_coerce_int(row.get("pur_pric", 0)),
                    ),
                )
            except Exception:  # noqa: BLE001 -- skip malformed rows
                continue
        return balances

    async def _resubscribe_market_data() -> int:
        if handle.kiwoom_websocket is None:
            return 0
        from src.core.v71.exchange.kiwoom_websocket import (
            V71KiwoomChannelType,
        )
        open_positions = handle.position_manager.list_open()
        stock_codes = {p.stock_code for p in open_positions}
        count = 0
        for code in stock_codes:
            try:
                await handle.kiwoom_websocket.subscribe(
                    V71KiwoomChannelType.PRICE_TICK, code,
                )
                count += 1
            except Exception:  # noqa: BLE001
                continue
        return count

    def _enter_safe_mode() -> None:
        system_state.safe_mode = True
        system_state.safe_mode_entered_at = datetime.now(timezone.utc)
        system_state.safe_mode_reason = "RESTART_RECOVERY"

    def _exit_safe_mode() -> None:
        system_state.safe_mode = False
        system_state.safe_mode_resumed_at = datetime.now(timezone.utc)
        system_state.safe_mode_reason = None

    recovery_ctx = RecoveryContext(
        reconciler=position_reconciler,
        notifier=handle.notification_service,
        clock=clock,
        connect_db=_connect_db,
        refresh_kiwoom_token=_refresh_kiwoom_token,
        connect_websocket=_connect_websocket,
        connect_telegram=_connect_telegram,
        cancel_all_pending_orders=_cancel_all_pending_orders,
        fetch_broker_balances=_fetch_broker_balances,
        resubscribe_market_data=_resubscribe_market_data,
        enter_safe_mode=_enter_safe_mode,
        exit_safe_mode=_exit_safe_mode,
    )
    recovery = V71RestartRecovery(context=recovery_ctx)
    return position_reconciler, recovery


async def _build_telegram_commands(
    handle: _TradingEngineHandle,
) -> Any:
    """Wire V71TelegramCommands onto the shared V7.0 TelegramBot +
    start polling so /status, /positions, etc. can be invoked.

    Cross-flag invariant:
      * v71.notification_v71 ON (queue + repository required)
      * v71.kiwoom_exchange ON (cancel_order needs V71OrderManager)
      * telegram_bot must exist (TELEGRAM_BOT_TOKEN/CHAT_ID env present)
    """
    import os

    from src.utils.feature_flags import is_enabled

    if not is_enabled("v71.notification_v71"):
        raise RuntimeError(
            "trading_bridge: v71.telegram_commands_v71 requires "
            "v71.notification_v71"
        )
    if handle.notification_queue is None:
        raise RuntimeError(
            "trading_bridge: V71TelegramCommands requires notification_queue"
        )
    if handle.notification_repository is None:
        raise RuntimeError(
            "trading_bridge: V71TelegramCommands requires notification_repository"
        )
    if handle.notification_circuit_breaker is None:
        raise RuntimeError(
            "trading_bridge: V71TelegramCommands requires circuit_breaker"
        )
    if handle.box_manager is None:
        raise RuntimeError(
            "trading_bridge: V71TelegramCommands requires box_manager"
        )
    if handle.position_manager is None:
        raise RuntimeError(
            "trading_bridge: V71TelegramCommands requires position_manager"
        )
    if handle.telegram_bot is None:
        raise RuntimeError(
            "trading_bridge: V71TelegramCommands requires a telegram_bot "
            "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID must be set)"
        )

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError(
            "trading_bridge: TELEGRAM_CHAT_ID required for command "
            "authorization (commands silently ignore non-listed chats)"
        )

    from src.core.v71.notification.v71_telegram_commands import (
        CommandContext,
        V71TelegramCommands,
    )

    bot = handle.telegram_bot
    clock = handle.clock if handle.clock is not None else V71RealClock()

    async def _telegram_send(text: str, *, chat_id: str | None = None) -> bool:
        """V7.0 TelegramBot.send_message uses positional + chat_id kwarg."""
        return await bot.send_message(text, chat_id=chat_id)

    async def _audit_log(**kwargs: Any) -> None:
        """Log audit events as structured WARNING. The V7.1 audit pipeline
        (per 12_SECURITY.md §8.3) will replace this when wired."""
        logger.warning("v71_telegram_command_audit: %s", kwargs)

    def _safe_mode_get() -> bool:
        return bool(system_state.safe_mode)

    async def _safe_mode_set(active: bool) -> None:
        system_state.safe_mode = bool(active)
        if active:
            system_state.safe_mode_entered_at = datetime.now(timezone.utc)
        else:
            system_state.safe_mode_resumed_at = datetime.now(timezone.utc)

    async def _cancel_order(order_id: str) -> bool:
        if handle.order_manager is None:
            logger.warning(
                "v71_telegram_cancel_order: order_manager not wired",
            )
            return False
        try:
            from uuid import UUID
            await handle.order_manager.cancel_order(UUID(order_id))
            return True
        except Exception as exc:  # noqa: BLE001 -- command must not raise
            logger.warning(
                "v71_telegram_cancel_order failed: %s",
                type(exc).__name__,
            )
            return False

    # P-Wire-Box-3: list_tracked hits the DB via build_tracked_summaries.
    from src.web.v71.tracked_summary import (
        make_list_tracked_callable as _make_list_tracked_for_telegram,
    )
    _list_tracked = _make_list_tracked_for_telegram(
        handle.box_manager._sm,  # noqa: SLF001
    )

    cmd_ctx = CommandContext(
        box_manager=handle.box_manager,
        position_manager=handle.position_manager,
        notification_queue=handle.notification_queue,
        notification_repository=handle.notification_repository,
        circuit_breaker=handle.notification_circuit_breaker,
        clock=clock,
        telegram_send=_telegram_send,
        audit_log=_audit_log,
        authorized_chat_ids=(chat_id,),
        safe_mode_get=_safe_mode_get,
        safe_mode_set=_safe_mode_set,
        cancel_order=_cancel_order,
        list_tracked=_list_tracked,
        report_handler=None,  # Phase 6
    )
    commands = V71TelegramCommands(context=cmd_ctx)
    commands.register(bot)
    # Start polling so registered commands actually receive updates.
    # User decision (2026-04-28): test telegram after deploy. The polling
    # is harmless when no chats send commands; first real /status hits
    # this path.
    await bot.start_polling()
    return commands


async def _build_monthly_review(
    handle: _TradingEngineHandle,
) -> Any:
    """Construct V71MonthlyReview + V71MonthlyReviewScheduler.

    Cross-flag: v71.notification_v71 ON. Stateless ``list_review_items``
    placeholder returns empty list (full TrackedSummary build is a
    follow-up unit). The review still fires monthly with header + zero
    items so production receives a heartbeat.
    """
    from src.utils.feature_flags import is_enabled

    if not is_enabled("v71.notification_v71"):
        raise RuntimeError(
            "trading_bridge: v71.monthly_review requires v71.notification_v71"
        )
    if handle.notification_service is None:
        raise RuntimeError(
            "trading_bridge: V71MonthlyReview requires notification_service"
        )

    from src.core.v71.notification.v71_monthly_review import (
        MonthlyReviewContext,
        V71MonthlyReview,
        V71MonthlyReviewScheduler,
    )

    clock = handle.clock if handle.clock is not None else V71RealClock()

    def _list_review_items() -> list[Any]:
        # TrackedSummary aggregation is a follow-up unit. Empty list lets
        # the monthly review fire with a header-only body.
        return []

    review_ctx = MonthlyReviewContext(
        notifier=handle.notification_service,
        clock=clock,
        list_review_items=_list_review_items,
        list_expiring_boxes=None,
    )
    review = V71MonthlyReview(context=review_ctx)
    scheduler = V71MonthlyReviewScheduler(
        monthly_review=review, clock=clock, hour=9, minute=0,
    )
    await scheduler.start()
    return review, scheduler


async def _build_exit_orchestrator(
    handle: _TradingEngineHandle,
) -> Any:
    """Construct V71ExitCalculator + V71ExitOrchestrator + register
    PRICE_TICK handler on the WebSocket.

    Cross-flag invariant: depends on P-Wire-4b (exit_executor) +
    P-Wire-5 (kiwoom_websocket) being wired -- the orchestrator has
    nothing to drive without both.

    P-Wire-7 callback wiring (best-effort): once the orchestrator is
    built, mutate ExitExecutor / ViMonitor frozen contexts in place via
    ``dataclasses.replace`` so that:

      * ExitExecutor full-exit fires
        ``orchestrator.on_position_closed(stock_code, position_id)``
        -> price feed unsubscribes when no positions remain.
      * ViMonitor RESUMED handler fires
        ``orchestrator.on_vi_resumed(stock_code)`` -> immediate
        re-evaluation pass (PRD §10.4 1초 budget).
    """
    if handle.exit_executor is None:
        raise RuntimeError(
            "trading_bridge: v71.exit_orchestrator requires exit_executor "
            "(v71.exit_executor_v71 must be ON)",
        )
    if handle.position_manager is None:
        raise RuntimeError(
            "trading_bridge: v71.exit_orchestrator requires position_manager",
        )
    if handle.kiwoom_websocket is None:
        raise RuntimeError(
            "trading_bridge: v71.exit_orchestrator requires kiwoom_websocket "
            "(v71.kiwoom_websocket must be ON)",
        )

    import dataclasses

    from src.core.v71.exit.exit_calculator import V71ExitCalculator
    from src.core.v71.strategies.exit_orchestrator import V71ExitOrchestrator

    calculator = V71ExitCalculator()
    orchestrator = V71ExitOrchestrator(
        position_manager=handle.position_manager,
        exit_calculator=calculator,
        exit_executor=handle.exit_executor,
        websocket=handle.kiwoom_websocket,
        exchange=handle.exchange_adapter,
    )
    await orchestrator.start()

    # P-Wire-7 — wire orchestrator callbacks into existing executors.
    # ExitExecutorContext / ViMonitorContext are frozen, so we use
    # ``dataclasses.replace`` to build a fresh context with the callback
    # populated and reassign the executor's ``_ctx`` slot. The instances
    # themselves are not frozen so this is well-defined Python semantics.
    try:
        old_exit_ctx = handle.exit_executor._ctx
        new_exit_ctx = dataclasses.replace(
            old_exit_ctx, on_position_closed=orchestrator.on_position_closed,
        )
        handle.exit_executor._ctx = new_exit_ctx
    except Exception as exc:  # noqa: BLE001 -- callback is opt-in
        logger.warning(
            "trading_bridge: P-Wire-7 on_position_closed wire failed: %s",
            type(exc).__name__,
        )
    if handle.vi_monitor is not None:
        try:
            old_vi_ctx = handle.vi_monitor._ctx
            new_vi_ctx = dataclasses.replace(
                old_vi_ctx, on_vi_resumed=orchestrator.on_vi_resumed,
            )
            handle.vi_monitor._ctx = new_vi_ctx
        except Exception as exc:  # noqa: BLE001 -- callback is opt-in
            logger.warning(
                "trading_bridge: P-Wire-7 on_vi_resumed wire failed: %s",
                type(exc).__name__,
            )

    return calculator, orchestrator


# P-Wire-12 (Phase A Step F): V71CandleManager wiring constants.
# KRX market sessions are KST; AWS Lightsail typically runs UTC, so EOD
# base_date and trigger comparisons must explicitly use KST. The V71
# CandleManager's own ``_default_eod_date`` / ``_is_after_hhmm`` were
# patched to KST in the same commit -- this constant exists for the
# bridge-level history priming on attach.
_CANDLE_KST = timezone(timedelta(hours=9))


async def _build_candle_manager(
    handle: _TradingEngineHandle,
) -> None:
    """Construct V71CandleManager + register PRICE_TICK handler + add
    tracked stocks + start EOD scheduler. Background-launches
    ``fetch_history_for_all`` so boot stays non-blocking.

    Cross-flag invariant (architect Q1): depends on P-Wire-1
    (``v71.kiwoom_exchange``) + P-Wire-5 (``v71.kiwoom_websocket``).
    V71CandleManager.start() registers a PRICE_TICK handler on the
    WebSocket and EOD fetch needs the kiwoom_client for ka10081 -- the
    manager is dead on arrival without both.

    Architect Q3 (cache=None gate): when ``v71.buy_executor_v71`` is
    OFF, ``handle.tracked_stock_cache`` is None. Log WARNING and skip
    the add_stock loop -- V71CandleManager is constructed and ready but
    has no stocks until something else calls ``add_stock`` later.

    Architect Q6 (boot priming): ``fetch_history_for_all`` primes the
    daily candle cache so the first PATH_B 09:01 evaluation has bars
    to work with. Run as a background task so a slow Kiwoom (4 req/sec
    real / 0.33 req/sec paper) doesn't gate lifespan boot.
    """
    from src.utils.feature_flags import is_enabled

    missing = [
        flag
        for flag in ("v71.kiwoom_exchange", "v71.kiwoom_websocket")
        if not is_enabled(flag)
    ]
    if missing:
        raise RuntimeError(
            "trading_bridge: v71.candle_builder enabled but required "
            f"dependencies are OFF: {missing}",
        )
    if handle.kiwoom_client is None:
        raise RuntimeError(
            "trading_bridge: v71.candle_builder requires kiwoom_client "
            "(v71.kiwoom_exchange must be wired)",
        )
    if handle.kiwoom_websocket is None:
        raise RuntimeError(
            "trading_bridge: v71.candle_builder requires kiwoom_websocket "
            "(v71.kiwoom_websocket must be wired)",
        )

    from src.core.v71.candle.v71_candle_manager import V71CandleManager

    manager = V71CandleManager(
        kiwoom_client=handle.kiwoom_client,
        kiwoom_websocket=handle.kiwoom_websocket,
    )
    await manager.start()
    # Security M1 (P-Wire-12): once start() registers the WS PRICE_TICK
    # handler the manager owns external state. If a downstream step
    # fails before the manager is attached to the handle, the lifespan
    # detach path can't reach it and the WS handler leaks. Wrap the
    # remaining steps so any failure rolls back the manager.
    try:
        if handle.tracked_stock_cache is None:
            logger.warning(
                "trading_bridge: v71.candle_builder enabled but "
                "tracked_stock_cache is None (v71.buy_executor_v71 OFF) "
                "-- 0 stocks tracked until BuyExecutor wires",
            )
        else:
            for _tracked_id, stock_code in handle.tracked_stock_cache.items():
                try:
                    manager.add_stock(stock_code)
                except Exception as exc:  # noqa: BLE001 -- backstop, idempotent
                    logger.warning(
                        "trading_bridge: candle_manager.add_stock(%s) "
                        "failed: %s",
                        stock_code, type(exc).__name__,
                    )

        await manager.start_eod_scheduler(interval_seconds=60.0)

        handle.candle_manager = manager
        base_date = datetime.now(_CANDLE_KST).strftime("%Y%m%d")
        handle.candle_history_task = asyncio.create_task(
            manager.fetch_history_for_all(base_date=base_date),
            name="v71_candle_history_priming",
        )
    except BaseException:
        with contextlib.suppress(Exception):
            await manager.stop()
        raise


# ---------------------------------------------------------------------------
# P-Wire-13 (Phase A Step F follow-up): V71BoxEntryDetector wiring helpers.
# ---------------------------------------------------------------------------


def _build_bidirectional_tracked_lookup(
    seed: dict | None,
) -> tuple[Callable[[str], object], Callable[[str], str | None]]:
    """Return ``(forward, reverse)`` lookups sharing a single backing dict.

    Architect Q6 (P-Wire-13) decided the resolver must mirror live
    cache mutations (P-Wire-11 restart_recovery refresh) so the reverse
    closure walks the *same* dict the forward path reads. The dict is
    captured by reference (no copy), so any mutation visible to forward
    is also visible to reverse on the next call.

    Reverse is O(N). Hot path frequency = bar completion (3-min + daily)
    × tracked stocks (~10-50). Architect Q6 confirmed acceptable cost.
    """
    forward_dict: dict = dict(seed or {})

    def forward(tracked_id: str) -> object:
        return forward_dict.get(tracked_id)

    def reverse(stock_code: str) -> str | None:
        if not stock_code:
            return None
        for tid, code in forward_dict.items():
            if code == stock_code:
                return str(tid)
        return None

    return forward, reverse


def _build_market_context_provider(
    handle: _TradingEngineHandle,
) -> Callable[[Any], Any]:
    """Build the MarketContext closure for V71BoxEntryDetector.

    Combines V71MarketSchedule (singleton) + handle.vi_monitor. Wraps
    candle.timestamp in KST timezone before passing to the schedule
    (architect Q7 + security M1) -- the schedule compares naive local
    time and AWS Lightsail runs UTC, so a tzinfo guard prevents a
    9-hour drift that would mis-classify market_open / closed.

    Note (P-Wire-14 follow-up): V71MarketSchedule.set_holidays is not
    yet wired -- holiday detection is empty so weekday checks treat
    every weekday as a trading day. The detector itself is robust to
    that gap (entry conditions also require regular session window),
    but Phase 7 paper smoke must verify or land P-Wire-14 first.
    """
    from src.core.v71.market.v71_market_schedule import (
        get_v71_market_schedule,
    )
    from src.core.v71.skills.box_entry_skill import MarketContext

    schedule = get_v71_market_schedule()
    vi_monitor = handle.vi_monitor

    def provider(candle: Any) -> Any:
        ts = candle.timestamp
        # Security M1 (P-Wire-13): defend against naive timestamps from
        # restart_recovery / replay paths -- naive datetime.astimezone()
        # would silently drift by the host's local offset (UTC on AWS,
        # KST on dev) producing wrong market-phase decisions.
        if ts.tzinfo is None:
            logger.warning(
                "trading_bridge: market_context received naive timestamp "
                "(stock=%s timeframe=%s) -- treating as UTC",
                candle.stock_code, candle.timeframe.name,
            )
            ts = ts.replace(tzinfo=timezone.utc)
        kst_now = ts.astimezone(_CANDLE_KST).replace(tzinfo=None)
        return MarketContext(
            is_market_open=schedule.is_market_open(kst_now),
            is_vi_active=(
                vi_monitor.is_vi_active(candle.stock_code)
                if vi_monitor is not None
                else False
            ),
            is_vi_recovered_today=(
                vi_monitor.is_vi_recovered_today(candle.stock_code)
                if vi_monitor is not None
                else False
            ),
            current_time=ts,
        )

    return provider


async def _build_box_entry_detectors(
    handle: _TradingEngineHandle,
) -> None:
    """Construct PATH_A + PATH_B V71BoxEntryDetector pair and subscribe
    them to V71CandleManager.

    Cross-flag invariant (architect Q3, opt B): direct dependencies
    only -- ``v71.candle_builder`` (subscribe target) +
    ``v71.box_system`` (detector __init__ require_enabled) +
    ``v71.buy_executor_v71`` (on_entry callback source). The
    transitive ``v71.kiwoom_*`` flags are already enforced by P-Wire-12.

    Slot invariant: candle_manager + box_manager + buy_executor +
    vi_monitor + tracked_stock_cache must all be wired. Anything
    missing means an upstream P-Wire skipped -- raise so the lifespan
    surfaces the misconfiguration rather than silently wiring half a
    pipeline.

    Security H1 rollback: ``register_on_complete`` is append-only on
    the V71CandleManager + builder fan-out. If the second detector's
    ``start()`` raises, roll back the first detector's subscription
    via ``stop()`` so the manager doesn't end up with an orphan
    callback (P-Wire-12 M1 pattern mirror).
    """
    from src.utils.feature_flags import is_enabled

    missing = [
        flag
        for flag in (
            "v71.candle_builder",
            "v71.box_system",
            "v71.buy_executor_v71",
        )
        if not is_enabled(flag)
    ]
    if missing:
        raise RuntimeError(
            "trading_bridge: v71.box_entry_detector enabled but required "
            f"dependencies are OFF: {missing}",
        )

    slot_checks = (
        ("candle_manager", handle.candle_manager),
        ("box_manager", handle.box_manager),
        ("buy_executor", handle.buy_executor),
        ("vi_monitor", handle.vi_monitor),
        ("tracked_stock_cache", handle.tracked_stock_cache),
    )
    for slot_name, slot_value in slot_checks:
        if slot_value is None:
            raise RuntimeError(
                "trading_bridge: v71.box_entry_detector requires "
                f"{slot_name} (upstream P-Wire must be wired)",
            )

    from src.core.v71.box.box_entry_detector import V71BoxEntryDetector
    from src.core.v71.v71_constants import V71Timeframe

    _forward, reverse_lookup = _build_bidirectional_tracked_lookup(
        handle.tracked_stock_cache,
    )
    market_context_provider = _build_market_context_provider(handle)

    detector_a = V71BoxEntryDetector(
        path_type="PATH_A",
        candle_manager=handle.candle_manager,
        timeframe_filter=V71Timeframe.THREE_MINUTE,
        box_manager=handle.box_manager,
        on_entry=handle.buy_executor.on_entry_decision,
        resolve_tracked_id=reverse_lookup,
        market_context=market_context_provider,
    )
    detector_a.start()
    try:
        detector_b = V71BoxEntryDetector(
            path_type="PATH_B",
            candle_manager=handle.candle_manager,
            timeframe_filter=V71Timeframe.DAILY,
            box_manager=handle.box_manager,
            on_entry=handle.buy_executor.on_entry_decision,
            resolve_tracked_id=reverse_lookup,
            market_context=market_context_provider,
        )
        detector_b.start()
    except BaseException:
        # Security H1 rollback -- detector_a already registered with
        # the candle manager; release before propagating so the
        # subscriber list stays clean.
        with contextlib.suppress(Exception):
            detector_a.stop()
        raise

    handle.box_entry_detector_path_a = detector_a
    handle.box_entry_detector_path_b = detector_b


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
    if handle.position_manager is None:
        raise RuntimeError(
            "trading_bridge: ExitExecutor requires position_manager "
            "(v71.position_v71 ON) for P-Wire-Box-4 apply_sell delegation",
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
        position_manager=handle.position_manager,
        notifier=handle.notification_service,
        clock=clock,
        on_position_closed=None,  # P-Wire-4c (ViMonitor) wires this
    )
    return V71ExitExecutor(context=ctx)


def _make_manual_buy_callback(notifier: Any) -> Any:
    """Build the V71OrderManager.on_manual_order callback.

    P-Wire-Manual-Buy-Notification: external (HTS / MTS) buys arrive
    through the Kiwoom WebSocket 00 channel as orders that have no
    v71_orders row. The callback fires HIGH-severity notifications
    with the stock code only — security 12_SECURITY §6.3 forbids
    sending price / quantity over Telegram for manual events the
    system did not authorise.
    """

    async def _callback(msg: Any) -> None:
        try:
            from src.core.v71.exchange.order_manager import WS_FIELD

            stock_code = (
                msg.values.get(WS_FIELD["STOCK_CODE"]) or ""
            ).strip() or None
            await notifier.notify(
                severity="HIGH",
                event_type="MANUAL_BUY_DETECTED",
                stock_code=stock_code,
                message=(
                    "[수동매수 감지] V7.1이 발주하지 않은 주문\n"
                    f"종목: {stock_code or '(unknown)'}\n"
                    "외부 (HTS / MTS) 매수로 추정 — Reconciler가 5분 안에 "
                    "시나리오 C 처리"
                ),
                rate_limit_key=f"manual_buy:{stock_code or 'unknown'}",
            )
        except Exception as exc:  # noqa: BLE001 -- handler isolation
            logger.warning(
                "manual buy callback failed: %s",
                type(exc).__name__,
            )

    return _callback


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

    is_paper = os.environ.get("KIWOOM_ENV", "PRODUCTION").strip().upper() == "SANDBOX"
    # Production = real funds (사용자 결정 2026-04-28: paper 단계 건너뜀).
    # Paper variant of KIWOOM_PAPER_APP_* keys is supported for harness /
    # smoke runs but production deployment uses KIWOOM_APP_* directly.
    if is_paper:
        app_key = os.environ.get("KIWOOM_PAPER_APP_KEY", "").strip()
        app_secret = os.environ.get("KIWOOM_PAPER_APP_SECRET", "").strip()
        key_label = "KIWOOM_PAPER_APP_KEY / KIWOOM_PAPER_APP_SECRET"
    else:
        app_key = os.environ.get("KIWOOM_APP_KEY", "").strip()
        app_secret = os.environ.get("KIWOOM_APP_SECRET", "").strip()
        key_label = "KIWOOM_APP_KEY / KIWOOM_APP_SECRET"
    if not app_key or not app_secret:
        raise RuntimeError(
            "trading_bridge: v71.kiwoom_exchange enabled but "
            f"{key_label} are not set in environment"
        )
    if not is_paper:
        # 실전 자금이 들어가는 경로 -- 부팅 시 운영자에게 명시적으로 보이도록
        # WARNING 레벨로 한 번 흘려준다 (lifespan 로그에 단일 진입점).
        logger.warning(
            "trading_bridge: kiwoom exchange wiring in PRODUCTION mode "
            "(real funds at risk -- KIWOOM_ENV=%s, app_key_prefix=%s)",
            os.environ.get("KIWOOM_ENV", "PRODUCTION"),
            app_key[:4] + "***",
        )

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

    # P-Wire-14 (Phase A Step F follow-up): seed V71MarketSchedule
    # holidays as the very first step. The box-entry pipeline's
    # safety net depends on this -- a missing holiday seed would let
    # automatic entries fire on KRX closures (Constitution §1
    # violation). Always-on (no feature flag) because the fallback
    # list (KR_HOLIDAYS_2026) keeps wiring safe even when the DB is
    # empty or unreachable, and a flag-off path would silently expose
    # the very risk this guard exists to prevent.
    try:
        await _build_market_calendar(handle)
    except Exception as exc:  # noqa: BLE001 -- never block boot
        # _load_holidays_seed already swallows DB failures, but a bug
        # in the wiring layer itself must not stop trading. Schedule
        # is left empty if everything above fails -- entry conditions
        # still require the regular session window so the blast
        # radius is bounded.
        logger.error(
            "trading_bridge: V71MarketSchedule wiring failed: %s "
            "(holidays empty -- entries depend solely on session window)",
            type(exc).__name__,
        )

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
        # P-Wire-Box-1: DB-backed manager. The legacy in-memory dict path
        # is gone — sessions come from the shared DatabaseManager (same
        # singleton FastAPI dependencies + V71Reconciler use).
        from src.core.v71.box.box_manager import V71BoxManager
        from src.database.connection import get_db_manager

        db = get_db_manager()
        sf = db._session_factory  # noqa: SLF001 -- intentional shared factory
        if sf is None:
            raise RuntimeError(
                "trading_bridge: v71.box_system enabled but DatabaseManager "
                "session factory not ready (call init_database() first)"
            )
        handle.box_manager = V71BoxManager(session_factory=sf)
        handle.session_factory = sf  # P-Wire-Box-4: shared across pos/buy/reconcile

        # P-Wire-Box-4 land complete (2026-04-30): atomic position-INSERT +
        # box-UPDATE transactions are now wired (BuyExecutor Q3, Reconciler
        # Q9). The 5 automatic-entry flags can safely be ON in concert
        # with box_system. We still emit a one-line audit log when any
        # of them is enabled so operators can confirm the runtime
        # configuration matches their expectations.
        active_auto_flags = [
            name for name in (
                "v71.box_entry_detector",
                "v71.pullback_strategy",
                "v71.breakout_strategy",
                "v71.path_b_daily",
                "v71.buy_executor_v71",
            )
            if is_enabled(name)
        ]
        if active_auto_flags:
            logger.info(
                "trading_bridge: P-Wire-Box-4 atomic-trade path active. "
                "Auto-entry flags ON: %s",
                active_auto_flags,
            )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.box_system' disabled -- "
            "box_manager not constructed",
        )

    if is_enabled("v71.position_v71"):
        from src.core.v71.position.v71_position_manager import (
            V71PositionManager,
        )

        # P-Wire-Box-4: V71PositionManager is now DB-backed and requires
        # the shared session factory. It must come from the box_system
        # block above (handle.session_factory is set there) -- if
        # ``v71.position_v71`` is on but ``v71.box_system`` is off the
        # boot configuration is internally inconsistent.
        if handle.session_factory is None:
            raise RuntimeError(
                "trading_bridge: v71.position_v71 enabled but "
                "session_factory is None -- enable v71.box_system first "
                "(both share the same DatabaseManager factory)",
            )
        handle.position_manager = V71PositionManager(
            session_factory=handle.session_factory,
        )
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
            handle.telegram_bot = built["telegram_bot"]
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

                # P-Wire-Manual-Buy-Notification: external (HTS/MTS)
                # buys land via the Kiwoom WS as orders V71OrderManager
                # has no v71_orders row for. Pre-P-Wire callback was
                # None → silent log. Wire the alert now that the
                # notification service is up so the user sees the
                # event immediately, well before the 5-minute
                # reconciler scenario C cycle.
                if handle.order_manager is not None:
                    handle.order_manager.set_on_manual_order(
                        _make_manual_buy_callback(service),
                    )
                    logger.info(
                        "trading_bridge: V71OrderManager.on_manual_order wired",
                    )
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

    # P-Wire-12 (Phase A Step F): V71CandleManager. Must run AFTER
    # P-Wire-5 wired the WS so the PRICE_TICK handler registration lands
    # on a real client, and BEFORE P-Wire-11 restart_recovery resubscribes
    # market data so any new subscriptions land in the candle dispatcher.
    # Wired BEFORE P-Wire-6 (exit_orchestrator) so future BoxEntryDetector
    # subscriber registration is symmetric with the orchestrator's PRICE
    # handler -- both consume the same WS source for different concerns.
    if is_enabled("v71.candle_builder"):
        try:
            await _build_candle_manager(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.candle_builder enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        logger.info(
            "trading_bridge: V71CandleManager wired "
            "(stocks=%d, eod_interval=60s, history_priming=running)",
            len(handle.candle_manager.tracked_stocks()),
        )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.candle_builder' disabled "
            "-- 3분봉 + 일봉 dispatcher off (PATH_A/B detection blocked)",
        )

    # P-Wire-13 (Phase A Step F follow-up): V71BoxEntryDetector pair.
    # Must run AFTER P-Wire-12 wired the candle manager (subscribe
    # target) and BEFORE P-Wire-11 restart_recovery (which resubscribes
    # PRICE_TICK -- the box detector's subscription chain must already
    # be in place so re-subscription naturally fans into it). Sits
    # between candle and exit pipelines so the candle->box->buy and
    # candle->exit pipelines are wired symmetrically.
    if is_enabled("v71.box_entry_detector"):
        try:
            await _build_box_entry_detectors(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.box_entry_detector enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        logger.info(
            "trading_bridge: V71BoxEntryDetector wired "
            "(path_a=%s, path_b=%s)",
            "ready" if handle.box_entry_detector_path_a else "off",
            "ready" if handle.box_entry_detector_path_b else "off",
        )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.box_entry_detector' "
            "disabled -- automatic box entries will not fire",
        )

    # P-Wire-6: V71ExitOrchestrator (PRICE_TICK -> ExitCalculator ->
    # ExitExecutor pipeline). Must run AFTER P-Wire-5 wired the WS so
    # ``register_handler`` lands on a real client; the orchestrator
    # itself does not start a background task.
    if is_enabled("v71.exit_orchestrator"):
        try:
            calculator, orchestrator = await _build_exit_orchestrator(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.exit_orchestrator enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.exit_calculator = calculator
        handle.exit_orchestrator = orchestrator
        logger.info("trading_bridge: V71ExitOrchestrator wired")
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.exit_orchestrator' disabled "
            "-- price-driven exits not active",
        )

    # P-Wire-8: V71DailySummary scheduler at 15:30 KST. Independent of
    # kiwoom -- only needs the notification stack + position/box
    # managers. Capital % is opt-in via the BuyExecutor's get_total_capital.
    if is_enabled("v71.daily_summary"):
        try:
            summary, scheduler = await _build_daily_summary(handle)
        except Exception as exc:  # noqa: BLE001 -- boot failure surfaces
            logger.error(
                "trading_bridge: v71.daily_summary enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.daily_summary = summary
        handle.daily_summary_scheduler = scheduler
        logger.info("trading_bridge: V71DailySummary scheduler started (15:30)")
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.daily_summary' disabled "
            "-- daily PnL alert at 15:30 not scheduled",
        )

    # P-Wire-10: V71TelegramCommands. Registers 13 commands on the
    # shared V7.0 TelegramBot and starts polling so the user can
    # /status / /positions / /stop after deployment. User policy
    # 2026-04-28: actual command testing happens after deploy; the
    # registration code path runs now.
    if is_enabled("v71.telegram_commands_v71"):
        try:
            commands = await _build_telegram_commands(handle)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "trading_bridge: v71.telegram_commands_v71 enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.telegram_commands = commands
        logger.info(
            "trading_bridge: V71TelegramCommands wired + polling started"
        )
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.telegram_commands_v71' "
            "disabled -- /status etc. not registered (web dashboard "
            "only)",
        )

    # P-Wire-9: V71MonthlyReview scheduler (1st of month, 09:00 KST).
    # Same dependencies as daily_summary; minimal review body when
    # list_review_items returns empty (placeholder, follow-up unit).
    if is_enabled("v71.monthly_review"):
        try:
            review, review_scheduler = await _build_monthly_review(handle)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "trading_bridge: v71.monthly_review enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
        handle.monthly_review = review
        handle.monthly_review_scheduler = review_scheduler
        logger.info("trading_bridge: V71MonthlyReview scheduler started")
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.monthly_review' disabled "
            "-- monthly review on 1st of month not scheduled",
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

    # P-Wire-11: V71RestartRecovery — runs the §13 7-step sequence ONCE
    # at attach. Cancels orphan orders + reconciles state + resubscribes
    # market data. Failures land in RecoveryReport.failures rather than
    # raising so a botched recovery never blocks lifespan boot
    # (Constitution 4 — system always runs).
    if is_enabled("v71.restart_recovery"):
        try:
            (
                handle.position_reconciler,
                handle.restart_recovery,
            ) = await _build_restart_recovery(handle)
            handle.restart_recovery_report = await handle.restart_recovery.run(
                reason="PROCESS_START",
            )
            failures = handle.restart_recovery_report.failures
            logger.info(
                "trading_bridge: V71RestartRecovery completed "
                "(cancelled=%d, resubscribed=%d, failures=%d)",
                handle.restart_recovery_report.cancelled_orders,
                handle.restart_recovery_report.resubscribed_count,
                len(failures),
            )
            if failures:
                logger.warning(
                    "trading_bridge: restart recovery had failures: %s",
                    failures,
                )
        except Exception as exc:  # noqa: BLE001 -- don't block boot
            logger.error(
                "trading_bridge: v71.restart_recovery enabled but "
                "construction failed: %s",
                type(exc).__name__,
            )
            raise
    else:
        logger.warning(
            "trading_bridge: feature flag 'v71.restart_recovery' disabled "
            "-- orphan orders + state drift caught only by 5-min reconciler",
        )

    # #1 (2026-04-30): maintenance schedule loop -- 매일 4회 점검 시간에
    # 자동 SAFE_MODE 진입 + 종료 시 reconcile_all. detach 가 cancel + await.
    handle.maintenance_task = asyncio.create_task(
        _maintenance_schedule_loop(handle),
        name="v71_maintenance_schedule_loop",
    )
    logger.info(
        "trading_bridge: maintenance schedule task started (windows=%s)",
        [
            f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}"
            for s, e in _MAINTENANCE_WINDOWS_KST
        ],
    )

    logger.info(
        "trading_bridge: V7.1 engine objects constructed "
        "(kiwoom=%s, box=%s, position=%s, reconciler=%s, notification=%s, "
        "maintenance=%s)",
        "yes" if handle.kiwoom_client else "no",
        type(handle.box_manager).__name__ if handle.box_manager else "none",
        type(handle.position_manager).__name__
        if handle.position_manager
        else "none",
        "running" if handle.reconciler_task else "off",
        "running"
        if handle.notification_service
        else ("queue-only" if handle.notification_queue else "off"),
        "running" if handle.maintenance_task else "off",
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

    # P-Wire-11: drop restart recovery slots (stateless wrapper, no
    # background task to cancel).
    handle.restart_recovery_report = None
    handle.restart_recovery = None
    handle.position_reconciler = None

    # P-Wire-10: stop telegram polling BEFORE notification service so
    # in-flight command handlers (which call telegram_send) don't fight
    # over the bot during shutdown. The bot itself is closed implicitly
    # when polling stops.
    if handle.telegram_bot is not None:
        try:
            await handle.telegram_bot.stop_polling()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: telegram_bot.stop_polling() failed: %s",
                type(exc).__name__,
            )
    handle.telegram_commands = None
    handle.telegram_bot = None

    # P-Wire-9: stop monthly review scheduler before notification service
    if handle.monthly_review_scheduler is not None:
        try:
            await handle.monthly_review_scheduler.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: monthly_review_scheduler.stop() failed: %s",
                type(exc).__name__,
            )
    handle.monthly_review_scheduler = None
    handle.monthly_review = None

    # P-Wire-8: stop the daily summary scheduler before notification
    # service goes away (the scheduler enqueues into the same queue).
    if handle.daily_summary_scheduler is not None:
        try:
            await handle.daily_summary_scheduler.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: daily_summary_scheduler.stop() failed: %s",
                type(exc).__name__,
            )
    handle.daily_summary_scheduler = None
    handle.daily_summary = None

    # P-Wire-4a/4b/4c/6: drop executors + monitor + orchestrator +
    # supporting closures. All are stateless (no aclose / cancel
    # needed) -- the underlying caches die with the closures. The
    # orchestrator's stop() is best-effort unsubscribe; do it before
    # nulling the slot.
    if handle.exit_orchestrator is not None:
        try:
            await handle.exit_orchestrator.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: exit_orchestrator.stop() failed: %s",
                type(exc).__name__,
            )
    handle.exit_orchestrator = None
    handle.exit_calculator = None

    # P-Wire-13 (Phase A Step F follow-up): stop the box entry
    # detectors BEFORE candle_manager.stop() flushes the final 3분봉
    # bucket. ``detector.stop()`` calls ``unregister_on_complete`` so
    # the manager's subscriber list is clean by the time
    # ``manager.stop()`` runs. Both detectors are independent --
    # failure on one must not block the other (best-effort).
    for slot in (
        "box_entry_detector_path_a",
        "box_entry_detector_path_b",
    ):
        det = getattr(handle, slot, None)
        if det is not None:
            try:
                det.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "trading_bridge: %s.stop() failed: %s",
                    slot, type(exc).__name__,
                )
            setattr(handle, slot, None)

    # P-Wire-12 (Phase A Step F): stop candle manager + cancel boot
    # priming task BEFORE buy_executor/exit_executor nullify (subscribers
    # could still touch them) and BEFORE notification + WebSocket
    # shutdown. ``stop()`` flushes the final 3분봉 bucket while
    # subscribers remain alive; the priming task is cancelled first so
    # an in-flight ka10081 fetch doesn't outlive the kiwoom_client.
    if handle.candle_history_task is not None:
        handle.candle_history_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await handle.candle_history_task
        handle.candle_history_task = None
    if handle.candle_manager is not None:
        try:
            await handle.candle_manager.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "trading_bridge: candle_manager.stop() failed: %s",
                type(exc).__name__,
            )
        handle.candle_manager = None

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

    # #1 (2026-04-30): stop maintenance schedule loop. SAFE_MODE 자동
    # 해제 책임은 detach 가 아니라 운영자(또는 다음 attach) -- 단순히
    # task cancel 만. Polling sleep 이라 cancel 즉시 종료.
    if handle.maintenance_task is not None:
        handle.maintenance_task.cancel()
        try:
            await handle.maintenance_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 -- shutdown best-effort
            logger.warning(
                "trading_bridge: maintenance_task await failed: %s",
                type(exc).__name__,
            )
        handle.maintenance_task = None

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
