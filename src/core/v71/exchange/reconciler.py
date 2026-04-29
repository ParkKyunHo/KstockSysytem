"""V71Reconciler -- Kiwoom balance (kt00018) ↔ V7.1 DB consistency engine.

Spec sources:
  - 02_TRADING_RULES.md §7 (manual-trade scenarios A/B/C/D + E full match)
  - 02_TRADING_RULES.md §13.1 Step 3 (post-restart reconciliation step)
  - 03_DATA_MODEL.md §2.3 (positions table) + §2.4 (v71_orders table)
  - 06_AGENTS_SPEC.md §1 (V71 Architect verified, all 10 recommendations
    absorbed) + §3 (Trading Logic) + §4 (Security)
  - 07_SKILLS_SPEC.md §7 (reconciliation_skill -- pure case classifier +
    proportional split)
  - 12_SECURITY.md §6 (PII / token never in audit; kt00018 contains
    account-level numbers, must be sanitised)
  - KIWOOM_API_ANALYSIS.md §kt00018 (acnt_evlt_remn_indv_tot schema)

Design summary (architect-approved):
  * Transport-aware wrapper around ``reconciliation_skill``: this module
    fetches kt00018, loads V7.1 DB rows, runs the pure ``classify_case``
    + ``compute_proportional_split`` from the skill, and applies the
    simple side-effects directly. Pyramid-buy (case A) and tracked-then-
    manual (case C) detections are forwarded to caller-provided callbacks
    so V71PositionManager / V71BoxManager (follow-up units) own the
    cross-table + skill-heavy logic.
  * ``V71ReconciliationApplyMode.SIMPLE_APPLY`` (default) directly applies
    cases B (partial sell -- MANUAL drained first, then proportional
    PATH_A/B split) and D (untracked manual buy -- MANUAL position
    INSERT). DETECT_ONLY skips DB writes for tests/audits.
  * Per-stock transactions with ``SELECT ... FOR UPDATE`` so concurrent
    fill events from ``V71OrderManager.on_websocket_order_event`` cannot
    race with reconciler updates on the same V71Position rows
    (architect P1.6 / N4 -- cross-module race protection).
  * ``avg_price_skill.update_position_after_sell`` is used for every
    quantity reduction so ``positions.weighted_avg_price`` is never
    written from this module (헌장; Harness 3 enforces).
  * ``TradeEventType.POSITION_RECONCILED`` single event type for audit
    trail, with payload schema standardised (architect N9):
        {case, kiwoom_qty, system_qty, diff, actions_applied}.
  * Per-stock try/except so one bad row never starves the rest (헌법 ④);
    failed codes surface in ``V71ReconciliationReport.failed_stock_codes``.
  * Callback isolation: ``on_pyramid_buy_detected`` /
    ``on_tracking_terminated`` exceptions are logged with type only and
    never propagated (Security M1, P5-Kiwoom-5 pattern).

Out of scope (architect-confirmed, follow-up units):
  * Case A weighted-average recompute + event reset (PRD §6.2 / §7.2):
    V71PositionManager via ``avg_price_skill.update_position_after_buy``.
  * Case C tracking termination + box invalidation (PRD §7.4):
    V71BoxManager (status transitions tracked_stocks → EXITED, boxes →
    INVALIDATED, MANUAL position INSERT).
  * Notifications (PRD §7.6): orchestrator consumes the report and calls
    ``notification_skill``.
  * Retry / scheduling (PRD §13.1): caller decides cadence (every 5
    minutes per §7.1 + on restart per §13.1 Step 3).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomTransportError,
)
from src.core.v71.position.state import PositionState
from src.core.v71.skills.avg_price_skill import update_position_after_sell
from src.core.v71.skills.reconciliation_skill import (
    KiwoomBalance,
    ReconciliationCase,
    SystemPosition,
    classify_case,
    compute_proportional_split,
)
from src.core.v71.v71_constants import V71Constants
from src.database.models_v71 import (
    PositionSource,
    PositionStatus,
    TrackedStatus,
    TrackedStock,
    TradeEvent,
    TradeEventType,
    V71Position,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Architect N8: whitelist of "active tracking" statuses (fail-safe).
# Adding a new status goes through PRD review; without an explicit
# whitelist hit, has_active_tracking defaults to False.
_ACTIVE_TRACKING_STATUSES: Final[tuple[TrackedStatus, ...]] = (
    TrackedStatus.TRACKING,
    TrackedStatus.BOX_SET,
    TrackedStatus.POSITION_OPEN,
    TrackedStatus.POSITION_PARTIAL,
)

# Path mapping for SystemPosition.path_type strings consumed by
# reconciliation_skill (it doesn't know V71 enum values, just literals).
_SOURCE_TO_PATH: Final[dict[PositionSource, str]] = {
    PositionSource.SYSTEM_A: "PATH_A",
    PositionSource.SYSTEM_B: "PATH_B",
    PositionSource.MANUAL: "MANUAL",
}

# Kiwoom kt00018 response top-level + per-row keys (KIWOOM_API_ANALYSIS.md
# §kt00018). Local constants -- wire-level concerns belong next to the
# consumer, not in V71Constants which is reserved for trading-rule magic
# numbers (P5-Kiwoom-5 P2.12 pattern).
_KT00018_HOLDINGS_KEY = "acnt_evlt_remn_indv_tot"
_KT00018_STOCK_CODE = "stk_cd"
_KT00018_STOCK_NAME = "stk_nm"
_KT00018_QUANTITY = "rmnd_qty"
_KT00018_AVG_PRICE = "pur_pric"
_KT00018_CURRENT_PRICE = "cur_prc"

# Single sentinel for "scenario decided to abort the run" -- the report
# is still returned so callers can inspect the partial result.
_CASE_E = ReconciliationCase.E_FULL_MATCH

# Security M2: KRX (6 digits) + NXT (5-8 alphanumeric) whitelist. Anything
# else is rejected at the boundary; the reject path logs the *length* only
# (not the value) to defeat log-injection via Kiwoom-side data corruption.
_VALID_STOCK_CODE = re.compile(r"^[A-Z0-9]{5,8}$")

# V71Position.stock_name column is VARCHAR(100). Cap before INSERT so a
# (very unlikely) long stk_nm doesn't surface as silent INSERT failure
# (Security M1).
_STOCK_NAME_MAX_LEN = 100


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V71ReconcilerError(Exception):
    """Base for V71Reconciler failures (mostly the kt00018 fetch path)."""


# ---------------------------------------------------------------------------
# Apply mode
# ---------------------------------------------------------------------------


class V71ReconciliationApplyMode(Enum):
    """Caller-controlled scope of side-effects.

    SIMPLE_APPLY (default):
      * E -> no-op
      * A -> classify only + invoke ``on_pyramid_buy_detected``; weighted
            avg recompute is V71PositionManager's job.
      * B -> direct DB UPDATE (MANUAL drained first, then PATH_A/B
            proportional split via skill).
      * C -> classify only + invoke ``on_tracking_terminated``; box
            invalidation + tracking EXITED is V71BoxManager's job.
      * D -> direct INSERT of a MANUAL V71Position.

    DETECT_ONLY:
      Pure classification with no DB writes for tests / audits. Callers
      must apply all side-effects themselves using the returned
      ``V71ReconciliationDecision`` data.
    """

    DETECT_ONLY = "DETECT_ONLY"
    SIMPLE_APPLY = "SIMPLE_APPLY"


# ---------------------------------------------------------------------------
# Callback events (pyramid + tracking-termination)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71PyramidBuyDetected:
    """Case A payload -- delegated to V71PositionManager.

    The decision of which path to merge into (single PATH_A / single
    PATH_B / dual proportional) is intentionally NOT taken here. PRD §7.2
    explicitly defers this to user policy and the position manager's
    weighted-avg recompute via ``avg_price_skill.update_position_after_buy``.
    ``candidate_path`` is a hint based on what the system already holds.
    """

    stock_code: str
    diff_qty: int
    kiwoom_avg_price: int
    candidate_path: str  # "PATH_A" | "PATH_B" | "DUAL" | "MANUAL_ONLY"
    occurred_at: datetime


@dataclass(frozen=True)
class V71TrackingTerminated:
    """Case C payload -- delegated to V71BoxManager.

    The follow-up unit is responsible for:
      * tracked_stocks UPDATE (status=EXITED, auto_exit_reason='MANUAL_BUY')
      * support_boxes batch UPDATE (status=INVALIDATED)
      * positions INSERT (source=MANUAL, weighted_avg_price=kiwoom)
      * trade_events INSERT (event_type=MANUAL_BUY).
    The reconciler only emits the detection.
    """

    stock_code: str
    tracked_stock_id: UUID
    new_manual_qty: int
    new_manual_avg_price: int
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Decision + report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71ReconciliationDecision:
    """One stock's reconciliation outcome (read-only audit record)."""

    stock_code: str
    case: ReconciliationCase
    kiwoom_qty: int
    system_qty: int
    diff: int
    has_active_tracking: bool
    actions_applied: tuple[str, ...] = ()
    pyramid_event: V71PyramidBuyDetected | None = None
    tracking_event: V71TrackingTerminated | None = None
    error: str | None = None


@dataclass(frozen=True)
class V71ReconciliationReport:
    """Aggregated outcome of a reconciliation pass."""

    started_at: datetime
    completed_at: datetime
    decisions: tuple[V71ReconciliationDecision, ...]
    matched_count: int
    discrepancy_count: int
    error_count: int
    failed_stock_codes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
PyramidCallback = Callable[[V71PyramidBuyDetected], Awaitable[None]]
TrackingTerminatedCallback = Callable[[V71TrackingTerminated], Awaitable[None]]


@dataclass(frozen=True)
class _KiwoomBalanceExt:
    """``KiwoomBalance`` + stock_name (skill enum stays minimal).

    The pure ``reconciliation_skill`` only needs (qty, avg_price) for
    classification, so ``KiwoomBalance`` deliberately doesn't carry a
    stock_name. This module DOES need the broker-supplied display name
    when materialising a Case D MANUAL position (Security H1 / Trading
    D1) -- carried alongside via this internal wrapper.
    """

    balance: KiwoomBalance
    stock_name: str

    @property
    def stock_code(self) -> str:
        return self.balance.stock_code

    @property
    def quantity(self) -> int:
        return self.balance.quantity

    @property
    def avg_price(self) -> int:
        return self.balance.avg_price


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _orm_to_position_state(row: V71Position) -> PositionState:
    """Adapt V71Position ORM to the pure ``PositionState`` consumed by
    ``avg_price_skill``. Architect N6 -- private to this module until a
    second consumer needs it.
    """
    return PositionState(
        position_id=str(row.id),
        stock_code=row.stock_code,
        tracked_stock_id=str(row.tracked_stock_id) if row.tracked_stock_id else "",
        triggered_box_id=str(row.triggered_box_id) if row.triggered_box_id else "",
        path_type=_SOURCE_TO_PATH.get(row.source, "MANUAL"),
        weighted_avg_price=int(row.weighted_avg_price),
        initial_avg_price=int(row.initial_avg_price),
        total_quantity=row.total_quantity,
        fixed_stop_price=int(row.fixed_stop_price),
        profit_5_executed=row.profit_5_executed,
        profit_10_executed=row.profit_10_executed,
        ts_activated=row.ts_activated,
        ts_base_price=int(row.ts_base_price) if row.ts_base_price is not None else None,
        ts_stop_price=int(row.ts_stop_price) if row.ts_stop_price is not None else None,
        ts_active_multiplier=(
            float(row.ts_active_multiplier)
            if row.ts_active_multiplier is not None
            else None
        ),
        status=row.status.value if row.status else "OPEN",
    )


def _coerce_int(raw: Any, *, default: int = 0) -> int:
    """Parse Kiwoom string-numeric field to int. Empty / None / invalid
    -> default. Mirrors the order_manager helper so audit + parse paths
    stay consistent.
    """
    if raw is None:
        return default
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


class V71Reconciler:
    """kt00018 vs V7.1 DB consistency engine.

    Concurrency:
      Each stock's reconciliation runs in its own session + transaction
      with ``SELECT ... FOR UPDATE`` on the candidate ``V71Position``
      rows. This prevents lost updates when the WebSocket fill loop
      (V71OrderManager.on_websocket_order_event) and the reconciler race
      on the same row.

    Failure isolation:
      A failure on one stock is captured into the decision's ``error``
      field + the report's ``failed_stock_codes``; subsequent stocks
      continue (헌법 ④). The kt00018 fetch itself is the only place
      that aborts the whole run -- if Kiwoom is unreachable there is no
      reference state to compare against.
    """

    def __init__(
        self,
        *,
        kiwoom_client: V71KiwoomClient,
        db_session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
        apply_mode: V71ReconciliationApplyMode = V71ReconciliationApplyMode.SIMPLE_APPLY,
        on_pyramid_buy_detected: PyramidCallback | None = None,
        on_tracking_terminated: TrackingTerminatedCallback | None = None,
    ) -> None:
        self._client = kiwoom_client
        self._session_factory = db_session_factory
        self._clock = clock or _utcnow
        self._apply_mode = apply_mode
        self._on_pyramid = on_pyramid_buy_detected
        self._on_tracking_terminated = on_tracking_terminated
        # #5 (2026-04-30): serialize concurrent reconcile_all callers
        # (5-min loop + on_reconnect_recovered + post-maintenance resume +
        # manual trigger). Second caller waits until first completes,
        # then runs a fresh reconciliation -- catches any drift
        # introduced in the meantime without duplicating kt00018 fetches
        # or DB writes.
        self._reconcile_lock = asyncio.Lock()

    def __repr__(self) -> str:
        # PII / lambda objects deliberately excluded.
        return (
            f"V71Reconciler(kiwoom_client={self._client!r}, "
            f"apply_mode={self._apply_mode.value})"
        )

    # ---------------------- Public API ---------------------------------

    async def reconcile_all(self) -> V71ReconciliationReport:
        """Run a full reconciliation pass. The kt00018 call happens once;
        DB reads + writes happen per stock under per-stock transactions.

        Concurrency (#5, 2026-04-30): ``self._reconcile_lock`` serializes
        callers. 두 번째 호출은 첫 번째 완료까지 대기 후 fresh 실행 --
        kt00018 중복 fetch / DB write race 방지.
        """
        async with self._reconcile_lock:
            return await self._reconcile_all_inner()

    async def _reconcile_all_inner(self) -> V71ReconciliationReport:
        started_at = self._clock()
        try:
            kiwoom_balances = await self._fetch_kiwoom_balances()
        except V71KiwoomTransportError as exc:
            logger.error(
                "v71_reconciler_kt00018_transport_error",
                error=type(exc).__name__,
            )
            raise V71ReconcilerError(
                f"kt00018 transport failure: {type(exc).__name__}"
            ) from exc
        except V71KiwoomBusinessError as exc:
            logger.error(
                "v71_reconciler_kt00018_business_error",
                api_id=exc.api_id,
                return_code=exc.return_code,
            )
            raise V71ReconcilerError(
                f"kt00018 business error code={exc.return_code}"
            ) from exc

        system_positions = await self._load_system_positions()
        active_tracking = await self._load_active_tracking()

        all_codes = sorted(set(kiwoom_balances) | set(system_positions))
        decisions: list[V71ReconciliationDecision] = []
        failed: list[str] = []

        for code in all_codes:
            try:
                decision = await self._reconcile_one(
                    stock_code=code,
                    kiwoom=kiwoom_balances.get(code),
                    system=system_positions.get(code),
                    tracking=active_tracking.get(code),
                )
            except Exception as exc:  # noqa: BLE001 - per-stock isolation
                logger.error(
                    "v71_reconciler_per_stock_failed",
                    stock_code=code,
                    error=type(exc).__name__,
                )
                decision = V71ReconciliationDecision(
                    stock_code=code,
                    case=_CASE_E,
                    kiwoom_qty=0,
                    system_qty=0,
                    diff=0,
                    has_active_tracking=False,
                    error=type(exc).__name__,
                )
            decisions.append(decision)
            if decision.error is not None:
                failed.append(code)

        completed_at = self._clock()
        matched = sum(
            1 for d in decisions
            if d.case == _CASE_E and d.error is None
        )
        errored = sum(1 for d in decisions if d.error is not None)
        discrepancy = len(decisions) - matched - errored

        return V71ReconciliationReport(
            started_at=started_at,
            completed_at=completed_at,
            decisions=tuple(decisions),
            matched_count=matched,
            discrepancy_count=discrepancy,
            error_count=errored,
            failed_stock_codes=tuple(failed),
        )

    async def reconcile_stock(self, stock_code: str) -> V71ReconciliationDecision:
        """Run reconciliation for a single stock. Useful when the orchestrator
        already knows a discrepancy exists (e.g., post-trade verification)."""
        if not stock_code:
            raise ValueError("stock_code is required")
        if not _VALID_STOCK_CODE.match(stock_code):
            # Security M2: same whitelist as broker-side parsing so the
            # public API can't be coerced into log-injection or DB
            # insertion of malformed codes.
            raise ValueError(
                f"invalid stock_code format (len={len(stock_code)})"
            )
        try:
            kiwoom_balances = await self._fetch_kiwoom_balances()
        except V71KiwoomTransportError as exc:
            raise V71ReconcilerError(
                f"kt00018 transport failure for {stock_code}: "
                f"{type(exc).__name__}"
            ) from exc
        except V71KiwoomBusinessError as exc:
            raise V71ReconcilerError(
                f"kt00018 business error code={exc.return_code}"
            ) from exc
        system_positions = await self._load_system_positions(stock_code=stock_code)
        active_tracking = await self._load_active_tracking(stock_code=stock_code)
        return await self._reconcile_one(
            stock_code=stock_code,
            kiwoom=kiwoom_balances.get(stock_code),
            system=system_positions.get(stock_code),
            tracking=active_tracking.get(stock_code),
        )

    # ---------------------- Internal: kt00018 fetch --------------------

    async def _fetch_kiwoom_balances(self) -> dict[str, _KiwoomBalanceExt]:
        """Call kt00018 + parse the holdings list.

        Rows with rmnd_qty <= 0 are skipped (Kiwoom may include them for
        same-day-flat positions which are not active holdings).

        Returned wrapper carries the broker stock_name so Case D INSERT
        can persist the display name correctly (Security H1, Trading D1).

        Each row is validated against ``_VALID_STOCK_CODE`` (Security M2);
        invalid codes are skipped with length-only logging to defeat
        log-injection via corrupt broker payloads.
        """
        response = await self._client.get_account_balance()
        items = (response.data or {}).get(_KT00018_HOLDINGS_KEY) or []
        result: dict[str, _KiwoomBalanceExt] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get(_KT00018_STOCK_CODE, "")).strip()
            if not _VALID_STOCK_CODE.match(code):
                # Security M2: never echo the raw value; len only.
                logger.warning(
                    "v71_reconciler_kt00018_invalid_stock_code",
                    code_len=len(code),
                )
                continue
            qty = _coerce_int(item.get(_KT00018_QUANTITY))
            if qty <= 0:
                continue
            avg = _coerce_int(item.get(_KT00018_AVG_PRICE))
            name = str(item.get(_KT00018_STOCK_NAME, "") or "").strip()
            name = name[:_STOCK_NAME_MAX_LEN] or code
            result[code] = _KiwoomBalanceExt(
                balance=KiwoomBalance(
                    stock_code=code, quantity=qty, avg_price=avg,
                ),
                stock_name=name,
            )
        return result

    # ---------------------- Internal: DB reads -------------------------

    async def _load_system_positions(
        self, *, stock_code: str | None = None,
    ) -> dict[str, SystemPosition]:
        """Read all active positions (or a single stock) into the
        ``SystemPosition`` view consumed by reconciliation_skill.

        Concurrency note (Security M3): rows are read WITHOUT row-level
        lock to avoid holding locks across the kt00018 RTT. A WebSocket
        00 fill event may slot in between this read and the apply step's
        ``with_for_update``. The apply methods (``_apply_partial_sell``,
        ``_apply_manual_insert``) re-read + re-lock under the per-stock
        transaction so the *write* is correct even if classification was
        made on stale state. Repeated 5-min cadence (PRD §7.1) self-heals
        false-positive classifications; the caller (orchestrator) is
        responsible for invoking reconcile_all on schedule.
        """
        async with self._session_factory() as session:
            stmt = select(V71Position).where(
                V71Position.status.in_(
                    (PositionStatus.OPEN, PositionStatus.PARTIAL_CLOSED)
                ),
            )
            if stock_code:
                stmt = stmt.where(V71Position.stock_code == stock_code)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        grouped: dict[str, list[V71Position]] = {}
        for row in rows:
            grouped.setdefault(row.stock_code, []).append(row)
        return {
            code: SystemPosition(
                stock_code=code,
                positions=[_orm_to_position_state(r) for r in rs],
            )
            for code, rs in grouped.items()
        }

    async def _load_active_tracking(
        self, *, stock_code: str | None = None,
    ) -> dict[str, TrackedStock]:
        """Read tracked_stocks rows in any active state (architect N8)."""
        async with self._session_factory() as session:
            stmt = select(TrackedStock).where(
                TrackedStock.status.in_(_ACTIVE_TRACKING_STATUSES),
            )
            if stock_code:
                stmt = stmt.where(TrackedStock.stock_code == stock_code)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
        return {row.stock_code: row for row in rows}

    # ---------------------- Internal: per-stock dispatch ---------------

    async def _reconcile_one(
        self,
        *,
        stock_code: str,
        kiwoom: _KiwoomBalanceExt | None,
        system: SystemPosition | None,
        tracking: TrackedStock | None,
    ) -> V71ReconciliationDecision:
        kiwoom_qty = kiwoom.quantity if kiwoom else 0
        system_qty = system.total_qty() if system else 0
        diff = kiwoom_qty - system_qty
        has_tracking = tracking is not None

        try:
            case = classify_case(
                kiwoom_qty,
                system_qty,
                has_active_tracking=has_tracking,
            )
        except ValueError as exc:
            logger.error(
                "v71_reconciler_classify_failed",
                stock_code=stock_code,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
            )
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=_CASE_E,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
                error=f"classify_case: {exc}",
            )

        # E always returns immediately (no event row, no callback).
        if case == ReconciliationCase.E_FULL_MATCH:
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=case,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
            )

        # DETECT_ONLY: classification only, no DB writes, no callback.
        if self._apply_mode == V71ReconciliationApplyMode.DETECT_ONLY:
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=case,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
            )

        # SIMPLE_APPLY: per-case branching.
        if case == ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY:
            event = self._build_pyramid_event(
                stock_code=stock_code,
                diff_qty=diff,
                kiwoom_avg_price=kiwoom.avg_price if kiwoom else 0,
                system=system,
            )
            await self._notify_pyramid(event)
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=case,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
                pyramid_event=event,
            )

        if case == ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL:
            actions = await self._apply_partial_sell(
                stock_code=stock_code,
                sell_qty=-diff,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
            )
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=case,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
                actions_applied=tuple(actions),
            )

        if case == ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY:
            # Security M5: classify_case guarantees tracking is not None
            # when has_active_tracking==True, but defend in production
            # (Python -O strips ``assert``).
            if tracking is None:
                logger.error(
                    "v71_reconciler_case_c_missing_tracking",
                    stock_code=stock_code,
                )
                return V71ReconciliationDecision(
                    stock_code=stock_code,
                    case=case,
                    kiwoom_qty=kiwoom_qty,
                    system_qty=system_qty,
                    diff=diff,
                    has_active_tracking=has_tracking,
                    error="case_c_missing_tracking_contract_violation",
                )
            event = V71TrackingTerminated(
                stock_code=stock_code,
                tracked_stock_id=tracking.id,
                new_manual_qty=kiwoom_qty,
                new_manual_avg_price=kiwoom.avg_price if kiwoom else 0,
                occurred_at=self._clock(),
            )
            await self._notify_tracking_terminated(event)
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=case,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
                tracking_event=event,
            )

        if case == ReconciliationCase.D_UNTRACKED_MANUAL_BUY:
            # Security H1 / Trading D1: stock_name comes from kt00018
            # ``stk_nm``, not the stock_code field.
            actions = await self._apply_manual_insert(
                stock_code=stock_code,
                stock_name=kiwoom.stock_name if kiwoom else stock_code,
                qty=kiwoom_qty,
                avg_price=kiwoom.avg_price if kiwoom else 0,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
            )
            return V71ReconciliationDecision(
                stock_code=stock_code,
                case=case,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                has_active_tracking=has_tracking,
                actions_applied=tuple(actions),
            )

        # Defensive: classify_case is exhaustive over the enum.
        return V71ReconciliationDecision(
            stock_code=stock_code,
            case=case,
            kiwoom_qty=kiwoom_qty,
            system_qty=system_qty,
            diff=diff,
            has_active_tracking=has_tracking,
            error="unhandled case",
        )

    # ---------------------- Internal: case helpers ---------------------

    def _build_pyramid_event(
        self,
        *,
        stock_code: str,
        diff_qty: int,
        kiwoom_avg_price: int,
        system: SystemPosition | None,
    ) -> V71PyramidBuyDetected:
        """Build the case-A payload, hinting at a candidate path.

        ``candidate_path`` is informational; the actual decision lives in
        V71PositionManager (PRD §7.2 explicitly defers dual-path choice
        to user policy + position manager).
        """
        if system is None:
            candidate = "PATH_A"  # default per PRD §7.2 fallback
        else:
            paths = {
                p.path_type for p in system.positions
                if p.path_type in {"PATH_A", "PATH_B"}
            }
            if len(paths) >= 2:
                candidate = "DUAL"
            elif paths:
                candidate = next(iter(paths))
            else:
                # Only MANUAL holdings + diff>0: caller decides whether
                # this is "MANUAL grew further" or "first system buy now".
                candidate = "MANUAL_ONLY"
        return V71PyramidBuyDetected(
            stock_code=stock_code,
            diff_qty=diff_qty,
            kiwoom_avg_price=kiwoom_avg_price,
            candidate_path=candidate,
            occurred_at=self._clock(),
        )

    async def _apply_partial_sell(
        self,
        *,
        stock_code: str,
        sell_qty: int,
        kiwoom_qty: int,
        system_qty: int,
        diff: int,
    ) -> list[str]:
        """Case B: drain MANUAL first, then proportional split across
        PATH_A / PATH_B. All quantity decrements go through
        ``avg_price_skill.update_position_after_sell`` so weighted_avg_price
        is never written from this module.
        """
        if sell_qty <= 0:
            return []
        actions: list[str] = []
        async with self._session_factory() as session:
            stmt = (
                select(V71Position)
                .where(V71Position.stock_code == stock_code)
                .where(
                    V71Position.status.in_(
                        (PositionStatus.OPEN, PositionStatus.PARTIAL_CLOSED)
                    )
                )
                .with_for_update()
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

            manual_rows = [r for r in rows if r.source == PositionSource.MANUAL]
            path_a_rows = [r for r in rows if r.source == PositionSource.SYSTEM_A]
            path_b_rows = [r for r in rows if r.source == PositionSource.SYSTEM_B]

            remaining = sell_qty

            # 1. MANUAL drained first (PRD §7.3 case 2).
            for row in manual_rows:
                if remaining <= 0:
                    break
                applied = min(row.total_quantity, remaining)
                if applied > 0:
                    self._reduce_quantity(row, applied)
                    actions.append(f"MANUAL[{row.id}]-{applied}")
                    remaining -= applied

            # 2. System paths -- single or dual.
            if remaining > 0:
                a_total = sum(r.total_quantity for r in path_a_rows)
                b_total = sum(r.total_quantity for r in path_b_rows)
                if a_total > 0 and b_total > 0:
                    # Dual path: skill-driven proportional split with
                    # larger-path-first rounding (PRD §7.3 case 3).
                    capped = min(remaining, a_total + b_total)
                    a_share, b_share = compute_proportional_split(
                        capped, a_total, b_total,
                    )
                    self._drain_rows(path_a_rows, a_share, "PATH_A", actions)
                    self._drain_rows(path_b_rows, b_share, "PATH_B", actions)
                    remaining -= capped
                elif a_total > 0:
                    capped = min(remaining, a_total)
                    self._drain_rows(path_a_rows, capped, "PATH_A", actions)
                    remaining -= capped
                elif b_total > 0:
                    capped = min(remaining, b_total)
                    self._drain_rows(path_b_rows, capped, "PATH_B", actions)
                    remaining -= capped

            # Security M4: any quantity left undistributed is a race-
            # induced under-application. Audit it explicitly so the
            # caller can trigger a follow-up cadence (PRD §7.1) instead
            # of silently believing this stock is reconciled.
            if remaining > 0:
                actions.append(f"UNAPPLIED_REMAINING-{remaining}")
                logger.warning(
                    "v71_reconciler_partial_sell_under_applied",
                    stock_code=stock_code,
                    sell_qty=sell_qty,
                    remaining=remaining,
                )

            await self._record_event(
                session=session,
                stock_code=stock_code,
                case=ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                actions=actions,
            )

        return actions

    def _drain_rows(
        self,
        rows: list[V71Position],
        target_qty: int,
        label: str,
        actions: list[str],
    ) -> None:
        """Apply ``target_qty`` reductions across ``rows`` in row order.

        Each row contributes up to its total_quantity; rows ordered by
        SQLAlchemy's primary-key default (reproducible across runs) so
        the audit trail is deterministic.
        """
        remaining = target_qty
        for row in rows:
            if remaining <= 0:
                break
            applied = min(row.total_quantity, remaining)
            if applied <= 0:
                continue
            self._reduce_quantity(row, applied)
            actions.append(f"{label}[{row.id}]-{applied}")
            remaining -= applied

    def _reduce_quantity(self, row: V71Position, qty: int) -> None:
        """Reduce ``total_quantity`` via avg_price_skill (헌장)."""
        if qty <= 0:
            return
        state = _orm_to_position_state(row)
        try:
            update = update_position_after_sell(state, qty)
        except ValueError:
            # qty exceeds total -- caller (drain logic) already caps via
            # ``min(total_quantity, remaining)``, but be defensive in case
            # of stale snapshots.
            logger.warning(
                "v71_reconciler_reduce_qty_invalid",
                stock_code=row.stock_code,
                qty=qty,
                row_qty=row.total_quantity,
            )
            return
        # weighted_avg_price intentionally untouched (avg_price_skill
        # contract). Only total_quantity + lifecycle change here.
        row.total_quantity = update.total_quantity
        if update.total_quantity == 0:
            row.status = PositionStatus.CLOSED
            row.closed_at = self._clock()
            row.close_reason = "MANUAL_PARTIAL_EXIT_RECONCILED"
        elif row.status == PositionStatus.OPEN:
            # Trading B1 + Migration small-issue-1: any partial decrease
            # from OPEN must transition to PARTIAL_CLOSED so reports /
            # alerts / Web filters can identify partially-closed
            # positions consistently with V71PositionManager.
            row.status = PositionStatus.PARTIAL_CLOSED

    async def _apply_manual_insert(
        self,
        *,
        stock_code: str,
        stock_name: str,
        qty: int,
        avg_price: int,
        kiwoom_qty: int,
        system_qty: int,
        diff: int,
    ) -> list[str]:
        """Case D: insert a new MANUAL position. ``fixed_stop_price`` uses
        ``V71Constants.STOP_LOSS_INITIAL_PCT`` so no magic number leaks
        into this module (Harness 3 enforces).
        """
        if qty <= 0 or avg_price <= 0:
            return []
        actions: list[str] = []
        position_id = uuid4()
        stop_price = int(round(avg_price * (1.0 + V71Constants.STOP_LOSS_INITIAL_PCT)))
        capital = qty * avg_price
        async with self._session_factory() as session:
            row = V71Position(
                id=position_id,
                source=PositionSource.MANUAL,
                stock_code=stock_code,
                stock_name=stock_name,
                tracked_stock_id=None,
                triggered_box_id=None,
                initial_avg_price=Decimal(avg_price),
                weighted_avg_price=Decimal(avg_price),
                total_quantity=qty,
                fixed_stop_price=Decimal(stop_price),
                profit_5_executed=False,
                profit_10_executed=False,
                ts_activated=False,
                status=PositionStatus.OPEN,
                actual_capital_invested=Decimal(capital),
            )
            session.add(row)
            actions.append(f"MANUAL_INSERT[{position_id}] qty={qty} avg={avg_price}")
            await self._record_event(
                session=session,
                stock_code=stock_code,
                case=ReconciliationCase.D_UNTRACKED_MANUAL_BUY,
                kiwoom_qty=kiwoom_qty,
                system_qty=system_qty,
                diff=diff,
                actions=actions,
                position_id=position_id,
            )
        return actions

    async def _record_event(
        self,
        *,
        session: AsyncSession,
        stock_code: str,
        case: ReconciliationCase,
        kiwoom_qty: int,
        system_qty: int,
        diff: int,
        actions: list[str],
        position_id: UUID | None = None,
    ) -> None:
        """Insert a POSITION_RECONCILED audit row with the standardised
        payload schema (architect N9).

        ``position_id`` is set for case D (single new MANUAL position) so
        the FK is preserved; for case B the multi-row drain spans several
        positions and the link is intentionally NULL (audit detail in
        ``payload.actions_applied``).
        """
        event = TradeEvent(
            id=uuid4(),
            stock_code=stock_code,
            position_id=position_id,
            event_type=TradeEventType.POSITION_RECONCILED,
            payload={
                "case": case.value,
                "kiwoom_qty": kiwoom_qty,
                "system_qty": system_qty,
                "diff": diff,
                "actions_applied": list(actions),
            },
            occurred_at=self._clock(),
        )
        session.add(event)

    # ---------------------- Internal: callbacks ------------------------

    async def _notify_pyramid(self, event: V71PyramidBuyDetected) -> None:
        if self._on_pyramid is None:
            logger.info(
                "v71_reconciler_pyramid_no_callback",
                stock_code=event.stock_code,
                diff_qty=event.diff_qty,
                candidate_path=event.candidate_path,
            )
            return
        try:
            await self._on_pyramid(event)
        except Exception as exc:  # noqa: BLE001 - callback isolation
            # Security M1 / P5-Kiwoom-5 pattern: log type only.
            logger.error(
                "v71_reconciler_pyramid_callback_error",
                stock_code=event.stock_code,
                error=type(exc).__name__,
            )

    async def _notify_tracking_terminated(
        self, event: V71TrackingTerminated,
    ) -> None:
        if self._on_tracking_terminated is None:
            logger.info(
                "v71_reconciler_tracking_terminated_no_callback",
                stock_code=event.stock_code,
                tracked_stock_id=str(event.tracked_stock_id),
            )
            return
        try:
            await self._on_tracking_terminated(event)
        except Exception as exc:  # noqa: BLE001 - callback isolation
            logger.error(
                "v71_reconciler_tracking_terminated_callback_error",
                stock_code=event.stock_code,
                error=type(exc).__name__,
            )


__all__ = [
    "PyramidCallback",
    "SessionFactory",
    "TrackingTerminatedCallback",
    "V71PyramidBuyDetected",
    "V71Reconciler",
    "V71ReconcilerError",
    "V71ReconciliationApplyMode",
    "V71ReconciliationDecision",
    "V71ReconciliationReport",
    "V71TrackingTerminated",
]
