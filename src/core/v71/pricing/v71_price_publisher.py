"""V71PricePublisher — PRICE_TICK → DB UPDATE + WebSocket publish (display-only).

Spec:
  - 09_API_SPEC.md §11.3 (POSITION_PRICE_UPDATE envelope, 1Hz throttle)
  - 03_DATA_MODEL.md §2.3 (V71Position.current_price/at/pnl_amount/pnl_pct
    columns — PRD Patch #5 land 2026-04-27)
  - 02_TRADING_RULES.md §5/§6/§10/§11 (격리: 거래 룰 위반 0)
  - 12_SECURITY.md §0.1 (Zero Trust + Fail Secure)
  - 04_ARCHITECTURE.md §0.1 (격리 / SRP / Feature Flag / 테스트 가능성)

Phase: P-Wire-Price-Tick (2026-04-30)

WHY THIS MODULE EXISTS:
  Frontend Dashboard / Positions / TrackedStocks 등 모든 페이지가
  운영 환경에서 mock 가격을 표시하는 결함 fix. PRICE_TICK이 들어오면:
    - V71ExitOrchestrator: 청산 판정 (별도 핸들러, 즉시)
    - V71PricePublisher: 표시용 DB UPDATE + WebSocket publish (이 모듈)

CONSTITUTION (HARD CONSTRAINTS — do NOT relax):
  P1: UPDATE columns LIMITED to (current_price, current_price_at,
      pnl_amount, pnl_pct). Never touch status / total_quantity /
      weighted_avg_price / fixed_stop_price / profit_5_executed /
      profit_10_executed / ts_* / actual_capital_invested.
      Violating P1 = 02_TRADING_RULES.md §5/§6/§11 위반 + Harness 3 차단.

  P2: Separate _publisher_locks per stock_code. Never share with
      V71ExitOrchestrator's _stock_locks. Sharing = 1Hz throttle이 청산
      판정 1초 차단 → §5.1/§10.5 NFR1 위반.

  P3: Never cache weighted_avg_price. Call ``position_manager.list_for_stock``
      every flush so pyramid-buy events_reset (§6.2/§6.3) reflects in
      pnl_pct immediately. Caching avg_price → stale pnl 표시 → 사용자
      잘못된 +5%/+10% 도달 판단 → 수동 매수 위험.

  P4 (recommended): Skip publish + UPDATE during VI_TRIGGERED for the
      stock (§10.5 "VI 중 매 틱 판정 일시 정지"). 자금 안전 영향 0이지만
      사용자 헌법 1 (사용자 판단 신뢰성) 보호. ``vi_monitor`` 가 None이면
      기본 fail-open (publish 진행).

  P5: Never assign ``position.weighted_avg_price = ...`` or
      ``UPDATE positions SET weighted_avg_price``. avg-price math는
      :mod:`src.core.v71.skills.avg_price_skill` 만 담당 (Harness 3 차단).

NFR1 3-TIER (security S3 CRITICAL):
  Tier 1 (handler, < 1ms): memory cache update + sanity check. NO await DB.
  Tier 2 (handler, optional throttled publish): event_bus.publish_nowait
         (in-process Queue, < 5ms). _NOT_ implemented in handler — moved
         to flush loop together with DB UPDATE so handler stays sub-ms.
  Tier 3 (background 1Hz task): batch UPDATE + publish. Separate task,
         awaits DB, never blocks PRICE_TICK handler.

  Why: V71KiwoomWebSocket._dispatch_real fires handlers sequentially.
  ExitOrchestrator + PricePublisher both register on PRICE_TICK; if
  PricePublisher awaits DB inside handler the chain accumulates 100ms+
  latency → ExitOrchestrator's stop/TS 1-second NFR1 budget violated.

INVARIANTS (운영 자금 안전):
  - DB pool 압박 (M3): asyncio.Semaphore(N) for max concurrent UPDATEs.
  - per-stock autocommit transaction (M2): single-stock UPDATE 분리해서
    한 종목 lock wait가 다른 종목 차단하지 않음.
  - delta-only UPDATE: last_published_price와 같으면 skip (network +
    DB write 절약).
  - WHERE status != 'CLOSED' guard (M1): apply_sell이 같은 row를 commit
    한 후 stale UPDATE 방지.

LOG REDACT (security S4 HIGH):
  - log.warning + type(exc).__name__ pattern only.
  - NEVER log price values in INFO level (자금 정보 평문화 방지).
  - log.debug only when needed (production INFO 미노출).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.v71.exchange.kiwoom_websocket import (
    V71KiwoomChannelType,
    V71WebSocketMessage,
)
from src.core.v71.v71_constants import V71Constants
from src.database.models_v71 import PositionStatus, V71Position
from src.utils.feature_flags import require_enabled

if TYPE_CHECKING:
    from src.core.v71.position.v71_position_manager import V71PositionManager

log = logging.getLogger(__name__)

# Common 0B (체결) WebSocket payload field aliases (mirror
# exit_orchestrator._PRICE_TICK_KEYS for parser parity).
_PRICE_TICK_KEYS = ("10", "stck_prpr", "cur_prc", "current_price")


# Async callable signature matching :func:`trading_bridge.publish_position_price_update`.
PublishFn = Callable[..., Awaitable[None]]
ClockFn = Callable[[], datetime]


class V71PricePublisher:
    """1Hz throttled PRICE_TICK → DB UPDATE + event_bus publish.

    Attach pattern (trading_bridge wires this AFTER V71ExitOrchestrator
    so handler registration order = orchestrator first, publisher second.
    Both receive every PRICE_TICK in registration order — see
    kiwoom_websocket.py:651 ``_dispatch_real`` fan-out)::

        publisher = V71PricePublisher(
            position_manager=pm,
            websocket=ws,
            sessionmaker=sm,
            publish_fn=trading_bridge.publish_position_price_update,
            clock=lambda: datetime.now(timezone.utc),
            vi_monitor=vi_monitor,  # P4: optional
        )
        await publisher.start()
        # ... PRICE_TICK 들어올 때마다 _handle_price_message 호출됨
        # ... 1초마다 _flush_loop가 batch UPDATE + publish
        await publisher.stop()  # idempotent

    Lifecycle:
        - ``start()`` registers PRICE_TICK handler + spawns flush task.
        - ``stop()`` cancels flush task + handler은 register는 그대로
          (V71KiwoomWebSocket이 aclose 시 handler list teardown 담당,
          double-stop 안전).
    """

    def __init__(
        self,
        *,
        position_manager: V71PositionManager,
        websocket: Any,
        sessionmaker: async_sessionmaker[AsyncSession],
        publish_fn: PublishFn,
        clock: ClockFn,
        vi_monitor: Any | None = None,
        flush_interval_seconds: float | None = None,
        max_concurrent_db: int | None = None,
    ) -> None:
        require_enabled("v71.price_publisher")
        self._pm = position_manager
        self._ws = websocket
        self._sm = sessionmaker
        self._publish_fn = publish_fn
        self._clock = clock
        self._vi = vi_monitor
        self._flush_interval = (
            flush_interval_seconds
            if flush_interval_seconds is not None
            else V71Constants.PRICE_PUBLISHER_FLUSH_INTERVAL_SECONDS
        )
        self._db_semaphore = asyncio.Semaphore(
            max_concurrent_db
            if max_concurrent_db is not None
            else V71Constants.PRICE_PUBLISHER_DB_SEMAPHORE,
        )
        # P2: separate locks per stock — NEVER share with ExitOrchestrator's
        # _stock_locks. Currently the flush loop is a single task so locks
        # are unused, but the field is kept to make the constraint
        # impossible to accidentally violate in future edits.
        self._publisher_locks: dict[str, asyncio.Lock] = {}
        # In-memory tick cache (handler writes, flush loop reads).
        # CPython dict.__setitem__ is GIL-atomic; no lock required for the
        # write side. Read side uses a snapshot copy.
        self._last_received: dict[str, tuple[int, datetime]] = {}
        # Last published price per stock — delta-only UPDATE gate.
        self._last_published: dict[str, int] = {}
        self._handler_registered = False
        self._flush_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register PRICE_TICK handler + start 1Hz flush loop. Idempotent."""
        if self._handler_registered:
            return
        self._ws.register_handler(
            V71KiwoomChannelType.PRICE_TICK, self._handle_price_message,
        )
        self._handler_registered = True
        self._stop_event.clear()
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Cancel flush task. Idempotent + safe to call from detach."""
        self._stop_event.set()
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 -- best effort
                log.warning(
                    "v71_price_publisher_stop_task_error: %s",
                    type(exc).__name__,
                )
        self._flush_task = None

    # ------------------------------------------------------------------
    # PRICE_TICK handler — Tier 1 (memory cache only, < 1ms)
    # ------------------------------------------------------------------

    async def _handle_price_message(
        self, message: V71WebSocketMessage,
    ) -> None:
        """Update in-memory cache. Sub-millisecond budget (NFR1 3-tier).

        NEVER awaits DB or event_bus here — flush loop handles those.
        """
        try:
            stock_code = (message.item or "").strip().upper()
            if not stock_code:
                return
            values = message.values or {}
            raw = next(
                (values[k] for k in _PRICE_TICK_KEYS if k in values), None,
            )
            if raw is None:
                return
            try:
                price = int(str(raw).strip().lstrip("0") or "0")
            except (TypeError, ValueError):
                return
            if not self._sanity_ok(stock_code, price):
                return
            # P4 (recommended): VI gate. fail-open if vi_monitor None or
            # raises (publish proceeds — heart of "헌법 4 always-on").
            if self._is_vi_active(stock_code):
                return
            now = self._clock()
            self._last_received[stock_code] = (price, now)
        except BaseException:  # noqa: BLE001 -- handler must never raise
            log.exception("v71_price_publisher_handler_unhandled_exception")

    # ------------------------------------------------------------------
    # Sanity / VI gates
    # ------------------------------------------------------------------

    def _sanity_ok(self, stock_code: str, price: int) -> bool:
        """Reject malformed / impossible prices (security S2 MEDIUM)."""
        if price <= 0:
            return False
        if price > V71Constants.PRICE_TICK_SANITY_MAX:
            log.warning(
                "v71_price_publisher_sanity_exceeded for %s",
                stock_code,
            )
            return False
        prev = self._last_received.get(stock_code)
        if prev is not None:
            prev_price = prev[0]
            if prev_price > 0:
                jump_pct = abs(price - prev_price) / prev_price
                if jump_pct > V71Constants.PRICE_TICK_JUMP_REJECT_PCT:
                    log.warning(
                        "v71_price_publisher_jump_rejected for %s",
                        stock_code,
                    )
                    return False
        return True

    def _is_vi_active(self, stock_code: str) -> bool:
        """P4: skip publish during VI_TRIGGERED. fail-open on errors."""
        if self._vi is None:
            return False
        try:
            return bool(self._vi.is_vi_active(stock_code))
        except Exception as exc:  # noqa: BLE001 -- fail-open
            log.warning(
                "v71_price_publisher_vi_check_failed for %s: %s",
                stock_code,
                type(exc).__name__,
            )
            return False

    # ------------------------------------------------------------------
    # Flush loop — Tier 3 (background 1Hz batch UPDATE + publish)
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """1Hz batch flush. Cancellable; CancelledError propagates."""
        try:
            while not self._stop_event.is_set():
                # Sleep with cancellation responsiveness via wait_for.
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._flush_interval,
                    )
                    return  # stop signaled
                except asyncio.TimeoutError:
                    pass
                try:
                    await self._flush_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 -- isolate
                    log.warning(
                        "v71_price_publisher_flush_iteration_failed: %s",
                        type(exc).__name__,
                    )
        except asyncio.CancelledError:
            raise

    async def _flush_once(self) -> None:
        """Iterate snapshot of cache; per-stock autocommit transaction.

        Per-stock isolation (M2): a long-running ``apply_sell`` lock on
        stock A does not block flush of stock B.
        """
        if not self._last_received:
            return
        snapshot = dict(self._last_received)
        for stock_code, (price, ts) in snapshot.items():
            last_pub = self._last_published.get(stock_code)
            if last_pub == price:
                continue  # delta = 0 (M5 delta-only)
            try:
                async with self._db_semaphore:
                    await self._flush_stock(stock_code, price, ts)
                self._last_published[stock_code] = price
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- isolation
                log.warning(
                    "v71_price_publisher_flush_failed for %s: %s",
                    stock_code,
                    type(exc).__name__,
                )

    async def _flush_stock(
        self, stock_code: str, price: int, ts: datetime,
    ) -> None:
        """P1+P3+P5: 4-column UPDATE per active position; publish each.

        - P3: ``list_for_stock`` called every flush — never cache avg.
        - P1: UPDATE columns limited to current_price/at/pnl_amount/pnl_pct.
        - P5: NEVER touches weighted_avg_price (skill-only domain).
        - M1 guard: ``WHERE status != 'CLOSED'`` defends against an
          ``apply_sell`` commit landing between list and UPDATE.
        """
        # P3: re-fetch every flush so pyramid-buy events_reset reflects.
        positions = await self._pm.list_for_stock(stock_code)
        if not positions:
            return
        async with self._sm() as session, session.begin():
            for pos in positions:
                if pos.status == PositionStatus.CLOSED:
                    continue
                if pos.total_quantity <= 0:
                    continue
                wap = pos.weighted_avg_price
                if wap is None or wap <= 0:
                    continue  # defensive: cannot compute pnl_pct
                price_d = Decimal(price)
                pnl_amount = (price_d - wap) * pos.total_quantity
                pnl_pct = (price_d - wap) / wap
                # P1: 4 columns ONLY. Adding any other column here =
                # 02_TRADING_RULES.md §5/§6/§11 violation + Harness 3.
                #
                # Idempotent timestamp guard (test-strategy 회귀 #5):
                # PRD Patch #5 우선순위 = WebSocket 0B (<1s) > kt00018
                # (5s) > ka10001 (restart). Reconciler / kt00018 fetch
                # 와 race할 때 stale tick이 fresh tick을 덮지 않도록
                # current_price_at < :new_at 일 때만 UPDATE.
                stmt = (
                    update(V71Position)
                    .where(V71Position.id == pos.position_id)
                    .where(V71Position.status != PositionStatus.CLOSED)
                    .where(
                        (V71Position.current_price_at.is_(None))
                        | (V71Position.current_price_at < ts)
                    )
                    .values(
                        current_price=price_d,
                        current_price_at=ts,
                        pnl_amount=pnl_amount,
                        pnl_pct=pnl_pct,
                    )
                )
                await session.execute(stmt)
                # publish (PRD §11.3 envelope) — per-position so sibling
                # boxes (same stock, different position) get distinct
                # pnl values on the frontend.
                try:
                    await self._publish_fn(
                        position_id=pos.position_id,
                        stock_code=stock_code,
                        current_price=float(price_d),
                        pnl_amount=float(pnl_amount),
                        pnl_pct=float(pnl_pct),
                    )
                except Exception as exc:  # noqa: BLE001 -- publish best-effort
                    log.warning(
                        "v71_price_publisher_publish_failed for %s: %s",
                        stock_code,
                        type(exc).__name__,
                    )


__all__ = ["V71PricePublisher"]
