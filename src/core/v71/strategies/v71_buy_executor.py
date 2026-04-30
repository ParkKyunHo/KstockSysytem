"""V71BuyExecutor -- turns box-entry decisions into actual buy orders.

Spec:
  - 02_TRADING_RULES.md §4   (매수 실행: 시퀀스, 부분 체결, 갭업, 매수 후 처리)
  - 02_TRADING_RULES.md §3.10/§3.11 (PATH_B + 09:01/09:05 안전장치)
  - 02_TRADING_RULES.md §10.9 (시초 VI 시나리오)
  - 03_DATA_MODEL.md §2.3 (positions)
  - 04_ARCHITECTURE.md §5.3

Phase: P3.2

Responsibilities:
  - PATH_A: bar-completion -> immediate limit-then-market sequence
  - PATH_B 1차 (09:01): wait for time, gap-up check, sequence
  - PATH_B 2차 (09:05): if 1차 unfilled, market order with gap recheck
  - 30% per-stock cap (§3.4) -- defer-deny at buy time
  - VI guard (§10) -- defer-deny at buy time (vi_active or
    vi_recovered_today)
  - On fill: mark box TRIGGERED, persist position, notify HIGH
  - On abandon: notify HIGH (gap, cap, VI, broker reject, total miss)

Boundaries:
  - DB: opened positions go through :class:`PositionStore` Protocol.
    P3.4 V71PositionManager implements it on top of Supabase.
  - VI: queried through ``is_vi_active(stock_code)``. P3.6
    V71ViMonitor wires the real signal.
  - Time: :class:`Clock` Protocol so PATH_B 09:05 fallback is testable
    without real sleep.
  - Notifications: :class:`Notifier` Protocol. P4.1 V71NotificationService
    is the real impl.

Constitution check:
  1. user judgment intact   -- box decisions drive every step
  2. NFR1 first             -- PATH_A path uses no DB call before order
  3. no V7.0 collision      -- v71/strategies/, V71 prefix
  4. system keeps running   -- failures raise typed errors + HIGH alert,
                               no auto-stop code
  5. simplicity             -- 4-step retry, single 09:05 fallback
"""

from __future__ import annotations

import contextlib
import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from src.core.v71.box.box_manager import BoxRecord, V71BoxManager
from src.core.v71.position.state import PositionState
from src.core.v71.skills.box_entry_skill import (
    EntryDecision,
    check_gap_up_for_path_b,
)
from src.core.v71.skills.kiwoom_api_skill import (
    ExchangeAdapter,
    KiwoomAPIError,
    OrderRejectedError,
    V71OrderSide,
    V71OrderType,
)
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocols (DI surface)
# ---------------------------------------------------------------------------

class Clock(Protocol):
    """Async clock abstraction.

    Tests inject a fake that returns scheduled times and short-circuits
    sleep. Production wraps :func:`asyncio.sleep` and ``datetime.now``.
    """

    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...

    async def sleep_until(self, target: datetime) -> None: ...


class PositionStore(Protocol):
    """Where opened positions land.

    P-Wire-Box-4: DB-backed V71PositionManager implements this against
    the ``positions`` + ``trade_events`` tables. ``add_position`` accepts
    an optional ``session`` so the BuyExecutor can wrap the position
    INSERT and the box ``mark_triggered`` UPDATE in a single atomic
    transaction (Q3 — orphan box vs orphan position elimination).
    """

    async def add_position(
        self,
        *,
        stock_code: str,
        stock_name: str | None = None,
        tracked_stock_id: str | None,
        triggered_box_id: str | None,
        path_type: str,  # PATH_A | PATH_B | MANUAL
        quantity: int,
        weighted_avg_price: int,
        opened_at: datetime,
        actual_capital_invested: int | None = None,
        session: AsyncSession | None = None,
    ) -> PositionState:
        """Insert a new OPEN position + BUY_EXECUTED trade_event.

        Returns the frozen :class:`PositionState` snapshot. When
        ``session`` is supplied the manager runs inside that
        transaction (atomic with ``box_manager.mark_triggered``).
        """
        ...


class Notifier(Protocol):
    """User-facing alerts. P4.1 V71NotificationService is the real impl."""

    async def notify(
        self,
        *,
        severity: str,        # CRITICAL/HIGH/MEDIUM/LOW
        event_type: str,
        stock_code: str | None,
        message: str,
        rate_limit_key: str | None = None,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Outcome / errors
# ---------------------------------------------------------------------------

class BuyOutcomeStatus(Enum):
    FILLED = "FILLED"                  # full fill -- box triggered
    PARTIAL_FILLED = "PARTIAL_FILLED"  # some shares; remainder gone
    ABANDONED_GAP = "ABANDONED_GAP"    # 5% gap-up at 09:01 or 09:05
    ABANDONED_CAP = "ABANDONED_CAP"    # 30% per-stock cap exceeded
    ABANDONED_VI = "ABANDONED_VI"      # vi_active / vi_recovered_today
    REJECTED = "REJECTED"              # broker reject (insufficient cash etc.)
    FAILED = "FAILED"                  # all 3 limits + market all empty
    SCHEDULED_FALLBACK = "SCHEDULED_FALLBACK"  # PATH_B awaiting 09:05


@dataclass(frozen=True)
class BuyOutcome:
    """Result of an :meth:`V71BuyExecutor.on_entry_decision` call.

    For PATH_B 1차 calls that miss, ``status == SCHEDULED_FALLBACK`` and
    the executor independently schedules the 09:05 retry; callers should
    treat the scheduled fallback as in-flight and not trigger a duplicate.
    """

    status: BuyOutcomeStatus
    stock_code: str
    box_id: str
    filled_quantity: int = 0
    weighted_avg_price: int = 0
    position_id: str | None = None
    reason: str = ""
    attempts: int = 0


@dataclass
class _BuySequenceResult:
    """Internal aggregate of one limit-then-market loop."""

    filled_quantity: int = 0
    weighted_avg_price: int = 0
    attempts: int = 0
    fills: list[tuple[int, int]] = field(default_factory=list)  # (qty, price)

    def add_fill(self, qty: int, price: int) -> None:
        if qty <= 0:
            return
        self.fills.append((qty, price))
        total_qty = sum(q for q, _ in self.fills)
        total_cost = sum(q * p for q, p in self.fills)
        self.filled_quantity = total_qty
        self.weighted_avg_price = (
            int(round(total_cost / total_qty)) if total_qty else 0
        )


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuyExecutorContext:
    """Bundle of injected dependencies."""

    exchange: ExchangeAdapter
    box_manager: V71BoxManager
    position_store: PositionStore
    notifier: Notifier
    clock: Clock

    # Side-channel queries (kept as callables to avoid pulling in the full
    # services they live behind).
    is_vi_active: Callable[[str], bool]
    """True iff the named stock is currently in a VI single-price area."""

    get_previous_close: Callable[[str], int]
    """Previous trading day's close, used for PATH_B gap-up checks."""

    get_total_capital: Callable[[], int]
    """Total capital base used for box position sizing."""

    get_invested_pct_for_stock: Callable[[str], Awaitable[float]]
    """Currently invested percentage of total capital for the stock.

    P-Wire-Box-4: async after V71PositionManager went DB-backed.
    Awaiting a single ``list_for_stock`` query stays inside the
    NFR1 1-second hot-path budget (~10 ms typical)."""

    session_factory: async_sessionmaker[AsyncSession] | None = None
    """P-Wire-Box-4 (Q3): when supplied, ``_finalize_buy`` opens a single
    transaction wrapping ``add_position`` + ``box_manager.mark_triggered``.
    Atomic semantics: both rows commit together, or both roll back, so a
    crashed mark_triggered can never leave the DB with a position row but
    the box still WAITING (which would re-trigger on the next tick). The
    legacy non-atomic path is kept for backward compatibility with tests
    that don't wire a session_factory; production callers always set it."""

    set_box_cooldown: Callable[[str, float], None] | None = None
    """P-Wire-Box-4 cooldown injection: BoxEntryDetector.set_cooldown
    callback. Called from the compensation path on atomic-transaction
    failure to block the next tick from re-firing the same box for the
    cooldown window (default 300s)."""

    enter_safe_mode: Callable[[str], Awaitable[None]] | None = None
    """Last-resort safety toggle used by the box-trigger compensation
    path when atomic transaction itself fails (broker fill landed but
    DB state untouched). None means the executor emits a CRITICAL alert
    only -- the operator must reconcile manually."""


# ---------------------------------------------------------------------------
# V71BuyExecutor
# ---------------------------------------------------------------------------

class V71BuyExecutor:
    """Coordinator that turns an :class:`EntryDecision` into broker orders.

    Single entry point: :meth:`on_entry_decision`. The executor is
    stateless across decisions -- each call schedules its own coroutine
    chain and returns a :class:`BuyOutcome`.
    """

    def __init__(
        self,
        *,
        context: BuyExecutorContext,
        tracked_stock_resolver: Callable[[str], str],
    ) -> None:
        """Args:
            context: shared dependencies.
            tracked_stock_resolver: maps box_id -> tracked_stock_id so the
                position record can link back. This is plumbed by the
                detector / orchestrator.
        """
        require_enabled("v71.box_system")
        self._ctx = context
        self._resolve_tracked = tracked_stock_resolver

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def on_entry_decision(
        self, decision: EntryDecision, box: BoxRecord
    ) -> BuyOutcome:
        """Dispatch a positive entry decision to the matching path.

        Negative decisions (``should_enter is False``) are no-ops -- the
        detector should not call this in that case, but we guard anyway.
        """
        if not decision.should_enter:
            return BuyOutcome(
                status=BuyOutcomeStatus.ABANDONED_VI,  # placeholder; not used
                stock_code="",
                box_id=box.id,
                reason=f"non-entry decision: {decision.reason}",
            )

        if box.path_type == "PATH_A":
            return await self._execute_path_a(decision, box)

        if box.path_type == "PATH_B":
            return await self._execute_path_b_primary(decision, box)

        raise ValueError(f"Unknown path_type: {box.path_type!r}")

    # ------------------------------------------------------------------
    # PATH_A: immediate sequence at bar completion
    # ------------------------------------------------------------------

    async def _execute_path_a(
        self, decision: EntryDecision, box: BoxRecord
    ) -> BuyOutcome:
        stock_code = self._stock_code_for(box)

        if (cap_outcome := await self._check_cap(box, stock_code)) is not None:
            return cap_outcome

        if (vi_outcome := await self._check_vi(box, stock_code)) is not None:
            return vi_outcome

        target_qty = self._compute_target_quantity(box, decision.expected_buy_price)
        if target_qty <= 0:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.ABANDONED_CAP,
                reason="ZERO_QUANTITY_FROM_CAP",
                severity="HIGH",
            )

        try:
            seq = await self._buy_sequence(
                stock_code, target_qty, market_only=False
            )
        except OrderRejectedError as e:
            return await self._abandon(
                box, stock_code, BuyOutcomeStatus.REJECTED, reason=str(e)
            )
        except KiwoomAPIError as e:
            return await self._abandon(
                box, stock_code, BuyOutcomeStatus.FAILED, reason=str(e)
            )

        return await self._finalize_buy(
            box, stock_code, seq, target_quantity=target_qty
        )

    # ------------------------------------------------------------------
    # PATH_B 1차: wait for 09:01 then sequence
    # ------------------------------------------------------------------

    async def _execute_path_b_primary(
        self, decision: EntryDecision, box: BoxRecord
    ) -> BuyOutcome:
        stock_code = self._stock_code_for(box)

        # Wait until 09:01 of next trading day.
        if decision.expected_buy_at is None:
            raise ValueError("PATH_B decision missing expected_buy_at")
        await self._ctx.clock.sleep_until(decision.expected_buy_at)

        # 1차 시점 갭업 검증.
        prev_close = self._ctx.get_previous_close(stock_code)
        opening_price = await self._ctx.exchange.get_current_price(stock_code)
        proceed, gap_pct = check_gap_up_for_path_b(prev_close, opening_price)
        if not proceed:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.ABANDONED_GAP,
                reason=f"PRIMARY_GAP_{gap_pct * 100:.2f}%",
                severity="HIGH",
            )

        if (cap_outcome := await self._check_cap(box, stock_code)) is not None:
            return cap_outcome

        # PATH_B 1차에서는 VI active를 hard-block하지 않는다 (§10.9):
        # 단일가 매매 영역에서도 매수 시도를 던지고, 미체결 시 09:05
        # fallback이 마무리한다. _check_vi은 ABANDONED_VI 알림을 동반하므로
        # 여기서는 사용하지 않는다.

        target_qty = self._compute_target_quantity(
            box, decision.expected_buy_price or opening_price
        )
        if target_qty <= 0:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.ABANDONED_CAP,
                reason="ZERO_QUANTITY_FROM_CAP",
                severity="HIGH",
            )

        try:
            seq = await self._buy_sequence(
                stock_code, target_qty, market_only=False
            )
        except OrderRejectedError as e:
            return await self._abandon(
                box, stock_code, BuyOutcomeStatus.REJECTED, reason=str(e)
            )
        except KiwoomAPIError as e:
            # Transport failure -- defer to fallback if we have one.
            if decision.fallback_buy_at is not None:
                return await self._execute_path_b_fallback(
                    decision,
                    box,
                    primary_reason=f"PRIMARY_API_ERROR:{e}",
                    already_filled=None,
                    target_quantity=target_qty,
                )
            return await self._abandon(
                box, stock_code, BuyOutcomeStatus.FAILED, reason=str(e)
            )

        # Full fill -> finalize.
        if seq.filled_quantity == target_qty:
            return await self._finalize_buy(
                box, stock_code, seq, target_quantity=target_qty
            )

        # Partial or zero fill -> 09:05 fallback (if metadata present).
        if decision.fallback_buy_at is not None:
            return await self._execute_path_b_fallback(
                decision,
                box,
                primary_reason=(
                    f"PRIMARY_PARTIAL_{seq.filled_quantity}/{target_qty}"
                ),
                already_filled=seq,
                target_quantity=target_qty,
            )

        # No fallback configured and not full -- finalize what we have.
        return await self._finalize_buy(
            box, stock_code, seq, target_quantity=target_qty
        )

    # ------------------------------------------------------------------
    # PATH_B 2차 (09:05 fallback)  --  §3.10/§3.11/§10.9
    # ------------------------------------------------------------------

    async def _execute_path_b_fallback(
        self,
        decision: EntryDecision,
        box: BoxRecord,
        *,
        primary_reason: str,
        already_filled: _BuySequenceResult | None,
        target_quantity: int,
    ) -> BuyOutcome:
        """09:05 market-order fallback when the 09:01 attempt missed.

        Sequence (§10.9):
          1. sleep until ``decision.fallback_buy_at``
          2. recheck gap-up vs previous close (5% cap, same threshold)
          3. recheck per-stock cap (user might have manually bought
             between 09:01 and 09:05)
          4. recompute remaining quantity (``target_quantity`` minus
             already filled in 1차)
          5. submit market order (§10.9 demands immediate fill)
          6. finalize: position record + box mark_triggered + HIGH alert
             with explicit "fallback" annotation

        Notes:
          - ``vi_recovered_today`` flag is intentionally NOT checked here
            (PRD §10.9: safety net is the completion of an already-decided
            entry, not a new one).
          - ``is_vi_active`` is also not checked: if the open auction is
            still single-price at 09:05, a market order participates in
            the auction and fills there.
        """
        stock_code = self._stock_code_for(box)

        if decision.fallback_buy_at is None:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.FAILED,
                reason="FALLBACK_NO_TIME",
            )

        # 1. wait for 09:05.
        await self._ctx.clock.sleep_until(decision.fallback_buy_at)

        # 2. gap-up recheck (§10.9).
        if decision.fallback_gap_recheck_required:
            prev_close = self._ctx.get_previous_close(stock_code)
            current_price = await self._ctx.exchange.get_current_price(stock_code)
            proceed, gap_pct = check_gap_up_for_path_b(prev_close, current_price)
            if not proceed:
                return await self._abandon(
                    box,
                    stock_code,
                    BuyOutcomeStatus.ABANDONED_GAP,
                    reason=f"FALLBACK_GAP_{gap_pct * 100:.2f}%",
                    severity="HIGH",
                )

        # 3. cap recheck (user could have manually bought during the 4-min wait).
        if (cap_outcome := await self._check_cap(box, stock_code)) is not None:
            return cap_outcome

        # 4. compute remaining (target minus 1차 fills).
        remaining = target_quantity
        if already_filled is not None:
            remaining = max(target_quantity - already_filled.filled_quantity, 0)

        if remaining <= 0:
            # Already fully bought in 1차 (race: detector could have triggered
            # the fallback and the last 1차 limit filled before sleep_until
            # returned). Finalize as a normal full fill.
            if already_filled is not None and already_filled.filled_quantity > 0:
                return await self._finalize_buy(
                    box,
                    stock_code,
                    already_filled,
                    target_quantity=target_quantity,
                    extra_note=f"primary_done:{primary_reason}",
                )
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.ABANDONED_CAP,
                reason="ZERO_REMAINING_AT_FALLBACK",
                severity="HIGH",
            )

        # 5. market order for remaining.
        try:
            seq = await self._buy_sequence(
                stock_code,
                remaining,
                market_only=decision.fallback_uses_market_order,
            )
        except OrderRejectedError as e:
            return await self._abandon(
                box, stock_code, BuyOutcomeStatus.REJECTED, reason=str(e)
            )
        except KiwoomAPIError as e:
            return await self._abandon(
                box, stock_code, BuyOutcomeStatus.FAILED, reason=str(e)
            )

        # 6. merge 1차 + 2차 fills, finalize.
        if already_filled is not None:
            for qty, price in already_filled.fills:
                seq.add_fill(qty, price)

        if seq.filled_quantity == 0:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.FAILED,
                reason=f"FALLBACK_NO_FILL ({primary_reason})",
                severity="HIGH",
            )

        return await self._finalize_buy(
            box,
            stock_code,
            seq,
            target_quantity=target_quantity,
            extra_note=f"fallback_after:{primary_reason}",
        )

    # ------------------------------------------------------------------
    # Buy sequence (4 steps: 3 limits + 1 market)
    # ------------------------------------------------------------------

    async def _buy_sequence(
        self,
        stock_code: str,
        target_quantity: int,
        *,
        market_only: bool,
    ) -> _BuySequenceResult:
        """Execute §4.2 retry cycle.

        Args:
            market_only: skip limit attempts and go straight to market.
                Used by the 09:05 fallback (§10.9 demands immediate fill).

        Returns:
            :class:`_BuySequenceResult` aggregating fills.
        """
        seq = _BuySequenceResult()
        remaining = target_quantity

        if not market_only:
            for _attempt in range(V71Constants.ORDER_RETRY_COUNT):
                if remaining <= 0:
                    break
                seq.attempts += 1

                orderbook = await self._ctx.exchange.get_orderbook(stock_code)
                limit_price = orderbook.ask_1  # §4.1: 매도 1호가
                if limit_price <= 0:
                    # No ask depth -- skip to market.
                    break

                order = await self._ctx.exchange.send_order(
                    stock_code=stock_code,
                    side=V71OrderSide.BUY,
                    quantity=remaining,
                    price=limit_price,
                    order_type=V71OrderType.LIMIT,
                )

                # Wait 5s for fill.
                await self._ctx.clock.sleep(V71Constants.ORDER_WAIT_SECONDS)

                status = await self._ctx.exchange.get_order_status(order.order_id)
                if status.filled_quantity > 0:
                    fill_price = status.avg_fill_price or limit_price
                    seq.add_fill(status.filled_quantity, fill_price)
                    remaining -= status.filled_quantity

                if status.is_open and remaining > 0:
                    # Cancel before next attempt so we don't double-fill.
                    # Cancel failure is non-fatal; continue to next attempt.
                    with contextlib.suppress(KiwoomAPIError):
                        await self._ctx.exchange.cancel_order(
                            order_id=order.order_id, stock_code=stock_code
                        )

        # Market fallback (or market-only entry).
        if remaining > 0:
            seq.attempts += 1
            market = await self._ctx.exchange.send_order(
                stock_code=stock_code,
                side=V71OrderSide.BUY,
                quantity=remaining,
                price=0,  # market: price ignored
                order_type=V71OrderType.MARKET,
            )
            # Short wait for market fill (typically immediate).
            await self._ctx.clock.sleep(2)
            status = await self._ctx.exchange.get_order_status(market.order_id)
            if status.filled_quantity > 0:
                fill_price = status.avg_fill_price or status.filled_quantity
                seq.add_fill(status.filled_quantity, fill_price)

        return seq

    # ------------------------------------------------------------------
    # Cap / VI / quantity helpers
    # ------------------------------------------------------------------

    async def _check_cap(
        self, box: BoxRecord, stock_code: str
    ) -> BuyOutcome | None:
        """Return an ABANDONED_CAP outcome if buying would exceed §3.4 cap."""
        invested_pct = await self._ctx.get_invested_pct_for_stock(stock_code)
        # Conservative: assume the box's full position_size_pct will be
        # invested -- if invested_pct + box.position_size_pct exceeds the
        # cap, deny up front. (Partial fills are impossible to predict.)
        projected = invested_pct + box.position_size_pct
        if projected > V71Constants.MAX_POSITION_PCT_PER_STOCK:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.ABANDONED_CAP,
                reason=(
                    f"CAP_EXCEEDED: existing {invested_pct:.2f}% + "
                    f"box {box.position_size_pct:.2f}% = "
                    f"{projected:.2f}% > {V71Constants.MAX_POSITION_PCT_PER_STOCK}%"
                ),
                severity="HIGH",
            )
        return None

    async def _check_vi(
        self, box: BoxRecord, stock_code: str
    ) -> BuyOutcome | None:
        """Return an ABANDONED_VI outcome when VI guards block entry.

        For PATH_A this is a hard block. PATH_B 1차 callers handle VI
        differently (see :meth:`_execute_path_b_primary`).
        """
        if self._ctx.is_vi_active(stock_code):
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.ABANDONED_VI,
                reason="VI_ACTIVE",
                severity="HIGH",
            )
        return None

    def _compute_target_quantity(
        self, box: BoxRecord, reference_price: int | None
    ) -> int:
        """floor(total_capital * box_pct / reference_price) -- §3.3."""
        if reference_price is None or reference_price <= 0:
            return 0
        capital = self._ctx.get_total_capital()
        budget = capital * box.position_size_pct / 100.0
        qty = math.floor(budget / reference_price)
        return max(qty, 0)

    # ------------------------------------------------------------------
    # Finalize / abandon
    # ------------------------------------------------------------------

    async def _finalize_buy(
        self,
        box: BoxRecord,
        stock_code: str,
        seq: _BuySequenceResult,
        *,
        target_quantity: int,
        extra_note: str | None = None,
    ) -> BuyOutcome:
        """§4.9: position record + box TRIGGERED + alert.

        P-Wire-Box-4 (Q3): when ``session_factory`` is supplied, the
        position INSERT and the ``box_manager.mark_triggered`` UPDATE
        run inside a single transaction. Either both commit or both
        roll back — the orphan-position-vs-orphan-box window is
        eliminated. On atomic failure, the broker still has the fill
        (irreversible from our side); ``_compensate_box_trigger_failure``
        sets cooldown + invalidates the box (best-effort, separate
        transaction since the atomic session was rolled back) +
        trips safe-mode + CRITICAL alert.

        Args:
            target_quantity: original requested size; used to decide
                FILLED vs PARTIAL_FILLED.
            extra_note: appended to the alert message (e.g. fallback
                trail).
        """
        if seq.filled_quantity == 0:
            return await self._abandon(
                box,
                stock_code,
                BuyOutcomeStatus.FAILED,
                reason=f"NO_FILL_AFTER_{seq.attempts}_ATTEMPTS",
                severity="HIGH",
            )

        opened_at = self._ctx.clock.now()
        # Trading-logic blocker 4: tracked_stock_id is nullable. The
        # legacy "" convention crashed on UUID cast. Manual buys have
        # no tracked_stock; system entries (PATH_A/PATH_B) always do.
        tracked_id: str | None = box.tracked_stock_id or None

        if self._ctx.session_factory is not None:
            # Q3 atomic transaction (production path).
            try:
                async with self._ctx.session_factory() as s, s.begin():
                    position_state = await self._ctx.position_store.add_position(
                        session=s,
                        stock_code=stock_code,
                        tracked_stock_id=tracked_id,
                        triggered_box_id=box.id,
                        path_type=box.path_type,
                        quantity=seq.filled_quantity,
                        weighted_avg_price=seq.weighted_avg_price,
                        opened_at=opened_at,
                    )
                    await self._ctx.box_manager.mark_triggered(box.id, session=s)
                position_id = position_state.position_id
            except Exception as atomic_exc:  # noqa: BLE001
                await self._compensate_box_trigger_failure(
                    box=box,
                    stock_code=stock_code,
                    position_id=None,  # auto-rolled-back; no position row exists
                    mark_exc=atomic_exc,
                )
                raise
        else:
            # Legacy / test path: no session_factory wired.
            position_state = await self._ctx.position_store.add_position(
                stock_code=stock_code,
                tracked_stock_id=tracked_id,
                triggered_box_id=box.id,
                path_type=box.path_type,
                quantity=seq.filled_quantity,
                weighted_avg_price=seq.weighted_avg_price,
                opened_at=opened_at,
            )
            position_id = position_state.position_id
            try:
                await self._ctx.box_manager.mark_triggered(box.id)
            except Exception as mark_exc:  # noqa: BLE001
                await self._compensate_box_trigger_failure(
                    box=box,
                    stock_code=stock_code,
                    position_id=position_id,
                    mark_exc=mark_exc,
                )
                raise

        status = (
            BuyOutcomeStatus.FILLED
            if seq.filled_quantity == target_quantity
            else BuyOutcomeStatus.PARTIAL_FILLED
        )

        # Compose the alert message; PATH_B fallback annotates via extra_note.
        suffix = f" [{extra_note}]" if extra_note else ""
        partial_tag = (
            f" (부분 체결 {seq.filled_quantity}/{target_quantity})"
            if status is BuyOutcomeStatus.PARTIAL_FILLED
            else ""
        )
        await self._ctx.notifier.notify(
            severity="HIGH",
            event_type="BUY_EXECUTED",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] {box.path_type} 매수 체결 "
                f"{seq.filled_quantity}주 @ {seq.weighted_avg_price}원"
                f"{partial_tag}{suffix}"
            ),
            rate_limit_key=f"buy:{stock_code}",
        )

        return BuyOutcome(
            status=status,
            stock_code=stock_code,
            box_id=box.id,
            filled_quantity=seq.filled_quantity,
            weighted_avg_price=seq.weighted_avg_price,
            position_id=position_id,
            attempts=seq.attempts,
        )

    async def _abandon(
        self,
        box: BoxRecord,
        stock_code: str,
        status: BuyOutcomeStatus,
        *,
        reason: str,
        severity: str = "HIGH",
    ) -> BuyOutcome:
        """Emit the abandon notification and return the outcome."""
        await self._ctx.notifier.notify(
            severity=severity,
            event_type="BUY_ABANDONED",
            stock_code=stock_code,
            message=f"[{stock_code}] 매수 포기 ({status.value}): {reason}",
            rate_limit_key=f"buy_abandon:{stock_code}",
        )
        return BuyOutcome(
            status=status,
            stock_code=stock_code,
            box_id=box.id,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stock_code_for(self, box: BoxRecord) -> str:
        """Resolve a stock_code for the box.

        The :class:`BoxRecord` does not carry stock_code directly; the
        ``tracked_stock_resolver`` callback bridges this. P3.4 will add
        an explicit ``stock_code`` field to :class:`BoxRecord` and remove
        this hop.
        """
        return self._resolve_tracked(box.tracked_stock_id)

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Box-trigger persistence failure compensation (P-Wire-Box-4)
    # ------------------------------------------------------------------

    async def _compensate_box_trigger_failure(
        self,
        *,
        box: BoxRecord,
        stock_code: str,
        position_id: str | None,
        mark_exc: Exception,
    ) -> None:
        """Best-effort recovery for the irreducibly bad case: broker fill
        landed but the position+box atomic transaction failed.

        With Q3 atomic transactions, position INSERT and box UPDATE
        commit together or roll back together. Compensation only needs
        to handle the broker-fill leftover and prevent infinite retry:

          1. ``set_box_cooldown(box.id, 300)`` blocks the next 5 min of
             ticks from re-firing the same box (trading-logic blocker 1).
          2. ``box_manager.mark_invalidated`` runs in a separate session
             (the atomic one was rolled back) to mark the box
             COMPENSATION_FAILED so it never re-emits.
          3. ``enter_safe_mode`` halts new entries — the operator must
             reconcile the broker-side fill manually (next periodic
             reconcile catches it as Scenario D in 5 min).
          4. CRITICAL alert with no money figures (12_SECURITY §6.3).

        Each step is independently try/except'd so a downstream failure
        does not prevent the next step (Constitution 4: never crash the
        trading loop).
        """
        log.critical(
            "v71_box_atomic_buy_failed",
            extra={
                "box_id": box.id,
                "tracked_stock_id": box.tracked_stock_id,
                "stock_code": stock_code,
                "position_id": position_id,
                "error": type(mark_exc).__name__,
            },
        )

        # 1. Cooldown — block infinite retry on the next PRICE_TICK.
        if self._ctx.set_box_cooldown is not None:
            try:
                self._ctx.set_box_cooldown(box.id, 300.0)
            except Exception as cd_exc:  # noqa: BLE001
                log.critical(
                    "v71_box_compensation_cooldown_failed",
                    extra={"box_id": box.id, "error": type(cd_exc).__name__},
                )

        # 2. Mark the box INVALIDATED in a fresh transaction.
        try:
            await self._ctx.box_manager.mark_invalidated(
                box.id, reason="COMPENSATION_FAILED",
            )
        except Exception as inv_exc:  # noqa: BLE001
            log.critical(
                "v71_box_compensation_invalidate_failed",
                extra={"box_id": box.id, "error": type(inv_exc).__name__},
            )

        # 3. Safe mode — the broker-side leftover is the operator's
        #    problem now (next reconcile picks it up as Scenario D).
        if self._ctx.enter_safe_mode is not None:
            try:
                await self._ctx.enter_safe_mode(
                    "BOX_TRIGGER_ATOMIC_FAILED"
                )
            except Exception as sm_exc:  # noqa: BLE001
                log.critical(
                    "v71_box_compensation_safemode_failed",
                    extra={"error": type(sm_exc).__name__},
                )

        # 4. CRITICAL alert — money figures redacted (12_SECURITY §6.3).
        try:
            await self._ctx.notifier.notify(
                severity="CRITICAL",
                event_type="BOX_TRIGGER_DB_FAILURE",
                stock_code=stock_code,
                message=(
                    f"[CRITICAL] 박스 매수 atomic 트랜잭션 실패\n"
                    f"종목: {stock_code}\n"
                    f"박스 ID: {box.id}\n"
                    f"브로커 체결분은 다음 reconcile (5분) 시나리오 D로 처리\n"
                    f"SAFE_MODE 진입, 박스 5분 cooldown"
                ),
                rate_limit_key=f"box_trigger_dbfail:{stock_code}",
            )
        except Exception as nx_exc:  # noqa: BLE001
            log.critical(
                "v71_box_compensation_notify_failed",
                extra={"error": type(nx_exc).__name__},
            )


__all__ = [
    "BuyExecutorContext",
    "BuyOutcome",
    "BuyOutcomeStatus",
    "Clock",
    "Notifier",
    "PositionStore",
    "V71BuyExecutor",
]
