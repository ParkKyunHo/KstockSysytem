"""V71Reconciler -- broker <-> DB position reconciliation.

Spec:
  - 02_TRADING_RULES.md §7   (manual-trade scenarios A/B/C/D)
  - 02_TRADING_RULES.md §13  (post-restart 7-step recovery)

Phase: P3.5

Used in two contexts:
  - periodic poll (every 5min, manual-trade detection)
  - post-restart 7-step recovery (Step 3)

Responsibilities:
  1. for each broker balance + system position pair, classify the §7 case
     (A/B/C/D/E) via :func:`reconciliation_skill.classify_case`;
  2. apply the resulting fix:
        A: V71PositionManager.apply_buy(MANUAL_PYRAMID_BUY)
           - dual path: prefer the existing path's record; if both paths
             exist, attribute to PATH_A (sole-record default).
        B: drain MANUAL first, then proportionally split leftover across
           PATH_A / PATH_B with larger-first rounding;
           apply_sell(MANUAL_SELL) per record.
        C: end_tracking() callback -> EXITED, V71BoxManager.cancel_waiting_for_tracked,
           V71PositionManager.add_position(path=MANUAL).
        D: V71PositionManager.add_position(path=MANUAL).
        E: no-op.
  3. emit one HIGH/CRITICAL notification per case (E silenced).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.core.v71.box.box_manager import BoxStatus, V71BoxManager
from src.core.v71.position.state import PositionState
from src.core.v71.position.v71_position_manager import V71PositionManager
from src.core.v71.skills.reconciliation_skill import (
    KiwoomBalance,
    ReconciliationCase,
    ReconciliationResult,
    SystemPosition,
    classify_case,
    compute_proportional_split,
)
from src.core.v71.strategies.v71_buy_executor import Clock, Notifier
from src.utils.feature_flags import require_enabled

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Tracked-store callback shape
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrackedInfo:
    """Minimal tracked-stock info needed for reconciliation."""

    tracked_stock_id: str
    stock_code: str
    path_type: str  # PATH_A or PATH_B
    status: str     # TRACKING / BOX_SET / POSITION_OPEN / POSITION_PARTIAL / EXITED


# Callback shapes -- a future V71TrackedStockManager will implement these.
ListTrackedFn = Callable[[str], list[TrackedInfo]]
"""(stock_code) -> list of active TrackedInfo (excludes EXITED)."""

EndTrackingFn = Callable[[str, str], Awaitable[None]]
"""(tracked_stock_id, reason) -> persist EXITED status."""


# ---------------------------------------------------------------------------
# Context (DI bundle)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconcilerContext:
    """Bundle of injected dependencies."""

    position_manager: V71PositionManager
    box_manager: V71BoxManager
    notifier: Notifier
    clock: Clock

    list_tracked_for_stock: ListTrackedFn
    """Returns active (non-EXITED) TrackedInfo records for the stock."""

    end_tracking: EndTrackingFn
    """Marks a tracked_stocks row as EXITED."""

    session_factory: async_sessionmaker[AsyncSession] | None = None
    """P-Wire-Box-4 (Q9): when supplied, each ``_handle_X`` mutation
    runs inside a single atomic session — position changes (apply_buy /
    apply_sell / add_position) and box changes (mark_invalidated /
    cancel_waiting_for_tracked) commit together or roll back together.
    Scenario B's proportional split also acquires
    ``SELECT ... FOR UPDATE`` via ``fetch_active_for_stock`` so the
    drain-MANUAL-then-split allocation is race-free against
    ExitExecutor / BuyExecutor running concurrently. Notifications
    fire after the commit so a rolled-back transaction never produces
    a misleading user-facing message."""


# ---------------------------------------------------------------------------
# V71Reconciler
# ---------------------------------------------------------------------------

class V71Reconciler:
    """Periodic broker <-> DB sync orchestrator (§7)."""

    def __init__(self, *, context: ReconcilerContext) -> None:
        require_enabled("v71.reconciliation_v71")
        self._ctx = context

    # ------------------------------------------------------------------
    # Atomic helper (P-Wire-Box-4 Q9)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _atomic_session(self) -> AsyncIterator[AsyncSession | None]:
        """Yield a single ``AsyncSession`` in a transaction when
        ``session_factory`` is wired; ``None`` otherwise (legacy test path).

        All mutations inside one ``_handle_X`` use the yielded session
        so they commit together or roll back together. Notifications
        are emitted **after** the context manager exits — a rolled-back
        transaction never leaves a misleading "수동 매수 감지" alert
        in the user's Telegram.
        """
        if self._ctx.session_factory is not None:
            async with self._ctx.session_factory() as s, s.begin():
                yield s
        else:
            yield None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def reconcile(
        self,
        *,
        broker_balances: list[KiwoomBalance],
    ) -> list[ReconciliationResult]:
        """Walk every stock that appears on either side and apply §7.

        Returns one :class:`ReconciliationResult` per stock processed
        (including E_FULL_MATCH, for audit completeness).

        P-Wire-Box-4: ``list_open`` now async (DB-backed manager). The
        snapshot is read at the top of reconcile so per-stock dispatch
        sees a consistent view; mutations inside ``_handle_X`` re-read
        with ``SELECT ... FOR UPDATE`` (Scenario B) when needed.
        """
        broker_by_stock: dict[str, KiwoomBalance] = {
            kb.stock_code: kb for kb in broker_balances
        }
        system_by_stock: dict[str, SystemPosition] = {}
        open_positions = await self._ctx.position_manager.list_open()
        for pos in open_positions:
            system_by_stock.setdefault(
                pos.stock_code,
                SystemPosition(stock_code=pos.stock_code, positions=[]),
            ).positions.append(pos)

        all_stocks = set(broker_by_stock) | set(system_by_stock)
        results: list[ReconciliationResult] = []
        for stock_code in sorted(all_stocks):
            broker = broker_by_stock.get(stock_code)
            system = system_by_stock.get(stock_code)
            result = await self._reconcile_one(stock_code, broker, system)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Per-stock dispatch
    # ------------------------------------------------------------------

    async def _reconcile_one(
        self,
        stock_code: str,
        broker: KiwoomBalance | None,
        system: SystemPosition | None,
    ) -> ReconciliationResult:
        broker_qty = broker.quantity if broker else 0
        system_qty = system.total_qty() if system else 0
        tracked = self._ctx.list_tracked_for_stock(stock_code)
        has_active_tracking = bool(tracked)

        case = classify_case(
            broker_qty, system_qty,
            has_active_tracking=has_active_tracking,
        )

        if case is ReconciliationCase.E_FULL_MATCH:
            return ReconciliationResult(
                stock_code=stock_code, case=case,
                actions_taken=["no diff"],
            )

        if case is ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY:
            assert broker is not None and system is not None
            return await self._handle_a(stock_code, broker, system)

        if case is ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL:
            assert system is not None
            sold_qty = system_qty - broker_qty
            return await self._handle_b(stock_code, sold_qty, system)

        if case is ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY:
            assert broker is not None
            return await self._handle_c(stock_code, broker, tracked)

        if case is ReconciliationCase.D_UNTRACKED_MANUAL_BUY:
            assert broker is not None
            return await self._handle_d(stock_code, broker)

        # Unreachable.
        raise RuntimeError(f"Unhandled case: {case!r}")

    # ------------------------------------------------------------------
    # Case A -- system + manual additional buy
    # ------------------------------------------------------------------

    async def _handle_a(
        self,
        stock_code: str,
        broker: KiwoomBalance,
        system: SystemPosition,
    ) -> ReconciliationResult:
        """User manually added shares -- attribute to an existing position.

        Tie-break rule: if both PATH_A and PATH_B exist, attribute to
        PATH_A (sole-record default per §7.2 "단일 경로 보유 시: 그 경로
        에 합산"; "이중 경로 보유 시: ... 사용자 결정 필요 → 디폴트:
        큰 경로 우선 합산").  We pick the larger of PATH_A vs PATH_B;
        ties go to PATH_A.
        """
        added_qty = broker.quantity - system.total_qty()
        # Approximate avg add price using broker.avg_price; in practice
        # this is the broker's running weighted average so is "good enough"
        # for §6 weighted-average recomputation. A future enhancement can
        # plumb the actual fill price via Kiwoom 체결내역.
        add_price = broker.avg_price

        target_path = self._choose_target_path(system)
        target_position = next(
            p for p in system.positions if p.path_type == target_path
        )
        async with self._atomic_session() as s:
            await self._ctx.position_manager.apply_buy(
                target_position.position_id,
                buy_price=add_price,
                buy_quantity=added_qty,
                event_type="MANUAL_PYRAMID_BUY",
                when=self._ctx.clock.now(),
                session=s,
            )
        await self._notify(
            severity="HIGH",
            event_type="MANUAL_PYRAMID_BUY",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] 수동 추가 매수 감지: "
                f"{added_qty}주 @ {add_price}원 ({target_path}에 합산, 이벤트 리셋)"
            ),
        )
        return ReconciliationResult(
            stock_code=stock_code,
            case=ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY,
            actions_taken=[
                f"apply_buy(MANUAL_PYRAMID_BUY) {added_qty} @ {add_price} "
                f"on {target_path} position {target_position.position_id}"
            ],
        )

    @staticmethod
    def _choose_target_path(system: SystemPosition) -> str:
        """Pick the larger of PATH_A vs PATH_B (ties go to PATH_A).

        MANUAL is not a target -- §7.2 attributes adds to a system path.
        If only one of PATH_A / PATH_B exists, that one wins.  If neither
        exists (only MANUAL), we attribute to MANUAL.
        """
        path_a = next(
            (p for p in system.positions if p.path_type == "PATH_A"), None
        )
        path_b = next(
            (p for p in system.positions if p.path_type == "PATH_B"), None
        )
        if path_a and not path_b:
            return "PATH_A"
        if path_b and not path_a:
            return "PATH_B"
        if path_a and path_b:
            return "PATH_A" if path_a.total_quantity >= path_b.total_quantity else "PATH_B"
        # Only MANUAL -- attribute there.
        return "MANUAL"

    # ------------------------------------------------------------------
    # Case B -- system + manual partial sell
    # ------------------------------------------------------------------

    async def _handle_b(
        self,
        stock_code: str,
        sold_qty: int,
        system: SystemPosition,
    ) -> ReconciliationResult:
        """Drain MANUAL first, then proportionally split leftover (§7.3).

        P-Wire-Box-4 (Q9): the entire allocation runs in a single
        atomic session. Inside the transaction we re-fetch active
        positions with ``SELECT ... FOR UPDATE`` so concurrent
        ExitExecutor / BuyExecutor calls cannot reduce the available
        quantity beneath the value we just split.
        """
        actions: list[str] = []
        remaining = sold_qty

        async with self._atomic_session() as s:
            # P-Wire-Box-4 trading-logic blocker: re-fetch the live
            # positions with FOR UPDATE so the proportional split sees
            # the exact same quantities it locks. The outer ``system``
            # snapshot is still used for the proportion calculation
            # (it was the basis for case classification), but mutations
            # target the locked rows.
            if s is not None:
                live = await self._ctx.position_manager.lock_active_for_stock(
                    stock_code, session=s,
                )
                live_by_id = {p.position_id: p for p in live}
            else:
                live_by_id = {p.position_id: p for p in system.positions}

            def _resolve(pos: PositionState) -> PositionState:
                """Prefer the locked snapshot when we have one."""
                return live_by_id.get(pos.position_id, pos)

            # Step 1: drain MANUAL records first (FIFO order).
            for snap in [p for p in system.positions if p.path_type == "MANUAL"]:
                if remaining <= 0:
                    break
                pos = _resolve(snap)
                take = min(remaining, pos.total_quantity)
                if take <= 0:
                    continue
                await self._ctx.position_manager.apply_sell(
                    pos.position_id,
                    sell_quantity=take,
                    sell_price=0,  # broker-side sell, no fill price known
                    event_type="MANUAL_SELL",
                    when=self._ctx.clock.now(),
                    session=s,
                )
                actions.append(
                    f"manual_sell {take} on MANUAL position {pos.position_id}"
                )
                remaining -= take

            if remaining > 0:
                # Step 2: split the leftover across PATH_A / PATH_B.
                path_a = next(
                    (p for p in system.positions if p.path_type == "PATH_A"),
                    None,
                )
                path_b = next(
                    (p for p in system.positions if p.path_type == "PATH_B"),
                    None,
                )
                path_a_qty = path_a.total_quantity if path_a else 0
                path_b_qty = path_b.total_quantity if path_b else 0

                sell_a, sell_b = compute_proportional_split(
                    remaining, path_a_qty, path_b_qty
                )
                if sell_a > 0 and path_a is not None:
                    await self._ctx.position_manager.apply_sell(
                        path_a.position_id,
                        sell_quantity=sell_a,
                        sell_price=0,
                        event_type="MANUAL_SELL",
                        when=self._ctx.clock.now(),
                        session=s,
                    )
                    actions.append(f"manual_sell {sell_a} on PATH_A")
                if sell_b > 0 and path_b is not None:
                    await self._ctx.position_manager.apply_sell(
                        path_b.position_id,
                        sell_quantity=sell_b,
                        sell_price=0,
                        event_type="MANUAL_SELL",
                        when=self._ctx.clock.now(),
                        session=s,
                    )
                    actions.append(f"manual_sell {sell_b} on PATH_B")

        await self._notify_b(stock_code, sold_qty, actions)
        return ReconciliationResult(
            stock_code=stock_code,
            case=ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL,
            actions_taken=actions,
        )

    async def _notify_b(
        self, stock_code: str, sold_qty: int, actions: list[str]
    ) -> None:
        await self._notify(
            severity="HIGH",
            event_type="MANUAL_PARTIAL_EXIT",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] 수동 부분 매도 감지: {sold_qty}주 "
                f"({'; '.join(actions)})"
            ),
        )

    # ------------------------------------------------------------------
    # Case C -- tracked but user bought
    # ------------------------------------------------------------------

    async def _handle_c(
        self,
        stock_code: str,
        broker: KiwoomBalance,
        tracked: list[TrackedInfo],
    ) -> ReconciliationResult:
        """End tracking, invalidate boxes, create MANUAL position (§7.4).

        P-Wire-Box-4 (Q9): box invalidation + MANUAL position INSERT
        commit together. ``end_tracking`` runs outside the atomic
        scope because it is the caller's callback (no shared session
        contract) — the worst-case mismatch is a TRACKING row that
        survives a crash, which the next reconcile sweep cleans up.
        """
        from src.database.models_v71 import PathType as _PathType

        ended_tracking_id: str | None = None
        invalidated_box_ids: list[str] = []
        actions: list[str] = []
        manual_position_id: str

        # Step 1: end_tracking (caller-supplied callback, no session).
        for tinfo in tracked:
            await self._ctx.end_tracking(
                tinfo.tracked_stock_id, "MANUAL_BUY_DETECTED",
            )
            actions.append(f"end_tracking {tinfo.tracked_stock_id}")
            ended_tracking_id = tinfo.tracked_stock_id

        # Step 2: atomic — box invalidation + MANUAL position INSERT.
        async with self._atomic_session() as s:
            for tinfo in tracked:
                path_a_boxes = await self._ctx.box_manager.list_waiting_for_tracked(
                    tinfo.tracked_stock_id, _PathType.PATH_A, session=s,
                )
                path_b_boxes = await self._ctx.box_manager.list_waiting_for_tracked(
                    tinfo.tracked_stock_id, _PathType.PATH_B, session=s,
                )
                for box in path_a_boxes + path_b_boxes:
                    await self._ctx.box_manager.mark_invalidated(
                        box.id, reason="MANUAL_BUY_DETECTED", session=s,
                    )
                    invalidated_box_ids.append(box.id)
                    actions.append(f"invalidate_box {box.id}")

            # MANUAL position. tracked_stock_id is None per blocker 4 —
            # the legacy "" convention crashed on UUID cast. The history
            # link survives via trade_events / box_id chain instead.
            position_state = await self._ctx.position_manager.add_position(
                stock_code=stock_code,
                tracked_stock_id=None,
                triggered_box_id=None,
                path_type="MANUAL",
                quantity=broker.quantity,
                weighted_avg_price=broker.avg_price,
                opened_at=self._ctx.clock.now(),
                session=s,
            )
            manual_position_id = position_state.position_id
        actions.append(f"add_manual_position {manual_position_id}")

        await self._notify(
            severity="HIGH",
            event_type="MANUAL_BUY_TRACKED_TERMINATED",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] 수동 매수 감지 -- 시스템 추적 종료, "
                f"{len(invalidated_box_ids)}개 박스 무효화. "
                f"MANUAL {broker.quantity}주 @ {broker.avg_price}"
            ),
        )

        return ReconciliationResult(
            stock_code=stock_code,
            case=ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY,
            actions_taken=actions,
            new_position_id=manual_position_id,
            invalidated_box_ids=tuple(invalidated_box_ids),
            ended_tracking_id=ended_tracking_id,
        )

    # ------------------------------------------------------------------
    # Case D -- untracked + user bought
    # ------------------------------------------------------------------

    async def _handle_d(
        self, stock_code: str, broker: KiwoomBalance,
    ) -> ReconciliationResult:
        """Pure MANUAL position creation (§7.5).

        P-Wire-Box-4 blocker 4: ``tracked_stock_id`` and
        ``triggered_box_id`` are ``None`` (no tracked record exists).
        The legacy "" convention crashed on UUID cast — the manager's
        repo layer rejects empty strings now.
        """
        async with self._atomic_session() as s:
            position_state = await self._ctx.position_manager.add_position(
                stock_code=stock_code,
                tracked_stock_id=None,
                triggered_box_id=None,
                path_type="MANUAL",
                quantity=broker.quantity,
                weighted_avg_price=broker.avg_price,
                opened_at=self._ctx.clock.now(),
                session=s,
            )
            manual_position_id = position_state.position_id
        await self._notify(
            severity="HIGH",
            event_type="MANUAL_BUY_UNTRACKED",
            stock_code=stock_code,
            message=(
                f"[{stock_code}] 수동 매수 감지 (미추적 종목) "
                f"{broker.quantity}주 @ {broker.avg_price}"
            ),
        )
        return ReconciliationResult(
            stock_code=stock_code,
            case=ReconciliationCase.D_UNTRACKED_MANUAL_BUY,
            actions_taken=[f"add_manual_position {manual_position_id}"],
            new_position_id=manual_position_id,
        )

    # ------------------------------------------------------------------
    # Notification helper
    # ------------------------------------------------------------------

    async def _notify(
        self, *, severity: str, event_type: str, stock_code: str, message: str
    ) -> None:
        await self._ctx.notifier.notify(
            severity=severity,
            event_type=event_type,
            stock_code=stock_code,
            message=message,
            rate_limit_key=f"reconcile:{stock_code}:{event_type}",
        )


# Re-export commonly used types so callers don't have to dig into the skill.
__all__ = [
    "EndTrackingFn",
    "ListTrackedFn",
    "ReconcilerContext",
    "TrackedInfo",
    "V71Reconciler",
]


# Suppress unused-import lint -- BoxStatus / PositionState are re-exported
# logically (referenced in docstrings / tests).
_ = (BoxStatus, PositionState, datetime)
