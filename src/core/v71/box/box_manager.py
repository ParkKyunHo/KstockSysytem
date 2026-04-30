"""V71BoxManager -- DB-backed box CRUD + overlap validation + 30-day expiry.

Spec:
  - 02_TRADING_RULES.md §3.1   (Box definition)
  - 02_TRADING_RULES.md §3.4   (Overlap rule, strict bounds)
  - 02_TRADING_RULES.md §3.6   (Modification policy + stop-loss relax guard)
  - 02_TRADING_RULES.md §3.7   (30-day reminder, no auto-delete)
  - 02_TRADING_RULES.md §3.13  (Box status lifecycle)
  - 02_TRADING_RULES.md §5.9   (Cancel WAITING after position close)
  - 03_DATA_MODEL.md §2.2      (support_boxes schema + indexes)

Phase: P-Wire-Box-1 (2026-04-30) -- DB-backed conversion of P3.1 in-memory
       dict. Single source of truth is now PostgreSQL (PRD 03 §0.1 #4).
       Caller-facing API stays compatible: methods now ``await`` and
       return frozen :class:`BoxRecord` snapshots, but field names and
       semantics are unchanged so the seven existing call sites only
       add ``await``.

Architecture (architect Q1-Q10 decisions):
  Q1: Frozen :class:`BoxRecord` DTO returned to callers. ORM rows live
      only inside this module's transaction contexts (DetachedInstance
      and lazy-load risk stays contained).
  Q2: Default ``async_sessionmaker`` injected at construction. Methods
      open ``async with sm() as s, s.begin():`` for short transactions.
      Optional ``session=`` argument lets callers (e.g. V71Reconciler
      _handle_c) bundle multiple manager calls into one transaction;
      external sessions are validated with ``in_transaction()`` so a
      caller that forgot ``begin()`` fails loud instead of silently
      losing the FOR UPDATE lock (security H1).
  Q3: ``mark_triggered`` is a single-row UPDATE only. Compensation on
      failure (orphan position rollback, alert, box INVALIDATED to
      block infinite retry) is V71BuyExecutor's responsibility -- this
      manager's job is to persist the transition and surface the error.
  Q4: No feature flag for the conversion itself. P-Wire-Box-2 land
      depends on this manager being authoritative; a dual code path
      would re-introduce the divergence we just fixed.
  Q5: 30-day reminder uses tz-aware ``now``. Naive datetime raises
      ``ValueError`` in the repo (TIMESTAMPTZ columns).
  Q6: ``create_box`` takes ``SELECT ... FOR UPDATE`` on the parent
      tracked_stocks row before the overlap query. Combined with the
      per-stock asyncio.Lock (defense in depth, security M3) this
      serialises sibling overlap checks against concurrent writes.
  Q7: Hot-path ``list_waiting_for_tracked`` measures ``perf_counter``
      and warns if > 100 ms (NFR1 1-second budget at 10% headroom).
  Q8: DB is the source of truth from the moment this module loads.
      Operational invariant: until P-Wire-Box-2 lands, automatic box
      creation paths (box_entry_detector / pullback / breakout / path_b
      / buy_executor) must stay disabled -- documented in
      ``config/feature_flags.yaml`` and verified by
      ``scripts/deploy/check_invariants.ps1``.
  Q9: Tests use ``AsyncSession`` mocks for unit coverage; a separate
      DB-integration suite under ``tests/v71/box/db/`` validates SQL
      semantics (PRD 06 §1.3 fast/slow split).
  Q10: Constitution mapping summarized in this docstring; per-decision
       rationale is in the agent transcripts under
       ``docs/v71/WORK_LOG.md``.

AUTHORIZATION INVARIANT (12_SECURITY.md §4):
    This manager performs NO authorization checks itself. Every caller
    MUST verify authorization upstream:
      * Web API (POST /api/v71/boxes etc.) via ``CurrentUserDep`` (OWNER role)
      * Telegram commands via ``authorized_chat_ids`` whitelist (§3.4)
      * Auto-entry strategies (box_breakout / box_pullback): system-only
      * V71Reconciler ``_handle_c`` invalidation: system-only
      * Restart recovery: system-only
    Adding authorization here is FORBIDDEN -- it would create a second
    source of truth for who can do what. New caller? Add an entry to
    this list and document the upstream gate in a code review.

LOG REDACT POLICY (12_SECURITY.md §6.3, security H4):
    Log records about boxes never include the price / size / stop-loss
    fields in plain text. Public values (box id, tracked_stock_id,
    stock_code, status enum, error type) only.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.v71.box import box_repository as repo
from src.core.v71.box.box_record import BoxRecord, from_orm
from src.core.v71.box.box_state_machine import (
    BoxEvent,
    BoxStatus,
    transition_box,
)
from src.core.v71.v71_constants import V71Constants
from src.database.models_v71 import PathType, StrategyType
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


_LIST_WAITING_NFR1_BUDGET_SECONDS = V71Constants.NFR1_HOT_PATH_BUDGET_SECONDS
_INVALIDATION_REASONS = frozenset(
    {"MANUAL_BUY_DETECTED", "AUTO_EXIT_BOX_DROP", "COMPENSATION_FAILED"}
)
_INVALIDATION_REASON_TO_EVENT = {
    "MANUAL_BUY_DETECTED": BoxEvent.MANUAL_BUY_DETECTED,
    "AUTO_EXIT_BOX_DROP": BoxEvent.AUTO_EXIT_BOX_DROP,
    "COMPENSATION_FAILED": BoxEvent.COMPENSATION_FAILED,
}


# ---------------------------------------------------------------------------
# Errors (preserved from P3.1 surface so call sites do not change)
# ---------------------------------------------------------------------------


class BoxValidationError(ValueError):
    """Box-level CHECK violation (price/size/stop) or external session
    misuse (no active transaction)."""


class BoxOverlapError(ValueError):
    """New box overlaps an existing WAITING box on the same (stock, path)."""


class BoxModificationError(ValueError):
    """Modification rejected (e.g., editing a TRIGGERED box, or relaxing
    stop-loss without ``force_relax_stop=True``)."""


class BoxNotFoundError(KeyError):
    """No box with the given id."""


# ---------------------------------------------------------------------------
# V71BoxManager
# ---------------------------------------------------------------------------


class V71BoxManager:
    """DB-backed manager for ``support_boxes`` rows.

    See module docstring for the architectural decisions and the
    authorization invariant. Callers see ``async`` methods that return
    frozen :class:`BoxRecord` snapshots.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        require_enabled("v71.box_system")
        if session_factory is None:
            raise ValueError("session_factory is required")
        self._sm = session_factory
        # Default clock returns tz-aware UTC. Tests override via ``clock``.
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Per-stock asyncio Lock + guard. DB FOR UPDATE serialises across
        # processes; this Lock serialises tasks within one event loop so
        # a single asyncio gather() of two create_box() calls cannot
        # interleave the validate+insert window (security M3).
        self._stock_locks: dict[str, asyncio.Lock] = {}
        self._stock_locks_guard = asyncio.Lock()

    # -- session helpers -------------------------------------------------

    async def _stock_lock(self, tracked_stock_id: str) -> asyncio.Lock:
        async with self._stock_locks_guard:
            lock = self._stock_locks.get(tracked_stock_id)
            if lock is None:
                lock = asyncio.Lock()
                self._stock_locks[tracked_stock_id] = lock
            return lock

    @staticmethod
    def _ensure_in_transaction(session: AsyncSession) -> None:
        """Security H1: external session must own a transaction.

        ``with_for_update`` is silently lost if the session has no
        active begin() -- failing loud is safer than a broken lock.
        """
        if not session.in_transaction():
            raise BoxValidationError(
                "external session must be inside a transaction "
                "(call session.begin() before passing it to V71BoxManager)"
            )

    # -- create / modify / delete ---------------------------------------

    async def create_box(
        self,
        *,
        tracked_stock_id: str,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        strategy_type: StrategyType,
        path_type: PathType,
        stop_loss_pct: float = V71Constants.STOP_LOSS_INITIAL_PCT,
        memo: str | None = None,
        session: AsyncSession | None = None,
    ) -> BoxRecord:
        """Validate + INSERT a new box. Returns a frozen :class:`BoxRecord`.

        Raises:
            BoxValidationError: CHECK violations.
            BoxOverlapError: overlap with an existing WAITING sibling
                on the same (tracked_stock_id, path_type).
        """
        self._validate_box_fields(
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
        )
        async with await self._stock_lock(tracked_stock_id):
            return await self._with_session(
                session, self._create_box_inner,
                tracked_stock_id=tracked_stock_id,
                upper_price=upper_price,
                lower_price=lower_price,
                position_size_pct=position_size_pct,
                strategy_type=strategy_type,
                path_type=path_type,
                stop_loss_pct=stop_loss_pct,
                memo=memo,
            )

    async def _create_box_inner(
        self,
        session: AsyncSession,
        *,
        tracked_stock_id: str,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        strategy_type: StrategyType,
        path_type: PathType,
        stop_loss_pct: float,
        memo: str | None,
    ) -> BoxRecord:
        from src.database.models_v71 import SupportBox

        # Q6: Lock parent tracked_stocks row to serialize sibling writes.
        await repo.fetch_tracked_for_update(session, tracked_stock_id)

        sibling = await repo.find_overlap(
            session,
            tracked_stock_id=tracked_stock_id,
            path_type=path_type,
            new_lower=lower_price,
            new_upper=upper_price,
        )
        if sibling is not None:
            # security H4: do not log the new prices, just identifiers.
            log.info(
                "v71_box_overlap",
                extra={
                    "tracked_stock_id": tracked_stock_id,
                    "path_type": path_type.value,
                    "sibling_box_id": str(sibling.id),
                },
            )
            raise BoxOverlapError(
                f"Box overlaps an existing WAITING sibling "
                f"(tracked={tracked_stock_id}, path={path_type.value}, "
                f"sibling={sibling.id})"
            )

        tier = await repo.next_box_tier(
            session,
            tracked_stock_id=tracked_stock_id,
            path_type=path_type,
        )
        new_id = uuid.uuid4()
        orm = SupportBox(
            id=new_id,
            tracked_stock_id=uuid.UUID(tracked_stock_id),
            path_type=path_type,
            box_tier=tier,
            upper_price=Decimal(upper_price),
            lower_price=Decimal(lower_price),
            position_size_pct=Decimal(str(position_size_pct)),
            stop_loss_pct=Decimal(str(stop_loss_pct)),
            strategy_type=strategy_type,
            status=BoxStatus.WAITING,
            memo=memo,
        )
        session.add(orm)
        await session.flush()
        await session.refresh(orm)
        log.info(
            "v71_box_created",
            extra={
                "box_id": str(new_id),
                "tracked_stock_id": tracked_stock_id,
                "path_type": path_type.value,
                "strategy": strategy_type.value,
                "tier": tier,
            },
        )
        return from_orm(orm)

    async def modify_box(
        self,
        box_id: str,
        *,
        upper_price: int | None = None,
        lower_price: int | None = None,
        position_size_pct: float | None = None,
        stop_loss_pct: float | None = None,
        memo: str | None = None,
        force_relax_stop: bool = False,
        session: AsyncSession | None = None,
    ) -> BoxRecord:
        """Modify a WAITING box. See §3.6 modification policy."""
        return await self._with_session(
            session, self._modify_box_inner,
            box_id=box_id,
            upper_price=upper_price,
            lower_price=lower_price,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            memo=memo,
            force_relax_stop=force_relax_stop,
        )

    async def _modify_box_inner(
        self,
        session: AsyncSession,
        *,
        box_id: str,
        upper_price: int | None,
        lower_price: int | None,
        position_size_pct: float | None,
        stop_loss_pct: float | None,
        memo: str | None,
        force_relax_stop: bool,
    ) -> BoxRecord:
        orm = await repo.fetch_box(session, box_id, for_update=True)
        if orm is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        if orm.status is not BoxStatus.WAITING:
            raise BoxModificationError(
                f"Cannot modify box {box_id} in status {orm.status.value}"
            )

        new_upper = upper_price if upper_price is not None else int(orm.upper_price)
        new_lower = lower_price if lower_price is not None else int(orm.lower_price)
        new_size = (
            position_size_pct
            if position_size_pct is not None
            else float(orm.position_size_pct)
        )
        new_stop = (
            stop_loss_pct
            if stop_loss_pct is not None
            else float(orm.stop_loss_pct)
        )

        self._validate_box_fields(
            upper_price=new_upper,
            lower_price=new_lower,
            position_size_pct=new_size,
            stop_loss_pct=new_stop,
        )

        if new_stop < float(orm.stop_loss_pct) - 1e-9 and not force_relax_stop:
            raise BoxModificationError(
                f"stop_loss_pct relaxed from {orm.stop_loss_pct} to {new_stop}; "
                "pass force_relax_stop=True to confirm (UI must show warning)."
            )

        # Q6 + H1 + trading-logic verifier: overlap re-check excludes self.
        if upper_price is not None or lower_price is not None:
            sibling = await repo.find_overlap(
                session,
                tracked_stock_id=str(orm.tracked_stock_id),
                path_type=orm.path_type,
                new_lower=new_lower,
                new_upper=new_upper,
                exclude_box_id=box_id,
            )
            if sibling is not None:
                raise BoxOverlapError(
                    f"Modified prices overlap a sibling WAITING box "
                    f"(sibling={sibling.id})"
                )

        orm.upper_price = Decimal(new_upper)
        orm.lower_price = Decimal(new_lower)
        orm.position_size_pct = Decimal(str(new_size))
        orm.stop_loss_pct = Decimal(str(new_stop))
        if memo is not None:
            orm.memo = memo
        await session.flush()
        await session.refresh(orm)
        log.info(
            "v71_box_modified",
            extra={
                "box_id": box_id,
                "tracked_stock_id": str(orm.tracked_stock_id),
                "stop_relaxed": force_relax_stop,
            },
        )
        return from_orm(orm)

    async def delete_box(
        self,
        box_id: str,
        *,
        on_orphan_cancel: Callable[[str], Awaitable[None] | None] | None = None,
        session: AsyncSession | None = None,
    ) -> BoxRecord:
        """Cancel a WAITING box (status -> CANCELLED).

        ``on_orphan_cancel`` runs *after* the DB UPDATE commits (or is
        flushed inside the external session). Callback failure logs at
        WARNING level and is otherwise isolated -- the box stays
        CANCELLED so the next reconcile sweep can pick up any leftover
        broker order (trading-logic blocker 2).
        """
        record = await self._with_session(
            session, self._delete_box_inner, box_id=box_id,
        )
        if on_orphan_cancel is not None:
            await self._invoke_orphan_callback(on_orphan_cancel, record.id)
        return record

    async def _delete_box_inner(
        self, session: AsyncSession, *, box_id: str,
    ) -> BoxRecord:
        orm = await repo.fetch_box(session, box_id, for_update=True)
        if orm is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        if orm.status is not BoxStatus.WAITING:
            raise BoxModificationError(
                f"Cannot delete box {box_id} in status {orm.status.value}"
            )
        orm.status = transition_box(orm.status, BoxEvent.USER_DELETED)
        orm.invalidation_reason = "USER_DELETED"
        await session.flush()
        await session.refresh(orm)
        log.info("v71_box_deleted", extra={"box_id": box_id})
        return from_orm(orm)

    # -- state transitions ----------------------------------------------

    async def mark_triggered(
        self,
        box_id: str,
        *,
        session: AsyncSession | None = None,
    ) -> BoxRecord:
        """WAITING -> TRIGGERED after a buy executes.

        Compensation on failure (rollback orphan position, raise alert,
        invalidate the box to block infinite retry) is the caller's
        responsibility (V71BuyExecutor). This method only persists the
        DB row transition and surfaces exceptions.
        """
        return await self._with_session(
            session, self._mark_triggered_inner, box_id=box_id,
        )

    async def _mark_triggered_inner(
        self, session: AsyncSession, *, box_id: str,
    ) -> BoxRecord:
        orm = await repo.fetch_box(session, box_id, for_update=True)
        if orm is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        orm.status = transition_box(orm.status, BoxEvent.BUY_EXECUTED)
        now = self._clock()
        orm.triggered_at = now
        await session.flush()
        await session.refresh(orm)
        log.info(
            "v71_box_triggered",
            extra={
                "box_id": box_id,
                "tracked_stock_id": str(orm.tracked_stock_id),
            },
        )
        return from_orm(orm)

    async def mark_invalidated(
        self,
        box_id: str,
        *,
        reason: str,
        session: AsyncSession | None = None,
    ) -> BoxRecord:
        """WAITING -> INVALIDATED. Reason set:

          * ``MANUAL_BUY_DETECTED`` -- §7.4 scenario C
          * ``AUTO_EXIT_BOX_DROP`` -- §3.4 -20% drop
          * ``COMPENSATION_FAILED`` -- BuyExecutor compensation path
            (P-Wire-Box-1; blocks infinite retry per trading-logic).
        """
        if reason not in _INVALIDATION_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(_INVALIDATION_REASONS)}; "
                f"got {reason!r}"
            )
        event = _INVALIDATION_REASON_TO_EVENT[reason]
        return await self._with_session(
            session, self._mark_invalidated_inner,
            box_id=box_id, event=event, reason=reason,
        )

    async def _mark_invalidated_inner(
        self,
        session: AsyncSession,
        *,
        box_id: str,
        event: BoxEvent,
        reason: str,
    ) -> BoxRecord:
        orm = await repo.fetch_box(session, box_id, for_update=True)
        if orm is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        orm.status = transition_box(orm.status, event)
        orm.invalidated_at = self._clock()
        orm.invalidation_reason = reason
        await session.flush()
        await session.refresh(orm)
        log.info(
            "v71_box_invalidated",
            extra={
                "box_id": box_id,
                "tracked_stock_id": str(orm.tracked_stock_id),
                "reason": reason,
            },
        )
        return from_orm(orm)

    async def cancel_waiting_for_tracked(
        self,
        tracked_stock_id: str,
        *,
        reason: str = "POSITION_CLOSED",
        on_orphan_cancel: Callable[[str], Awaitable[None] | None] | None = None,
        session: AsyncSession | None = None,
    ) -> list[BoxRecord]:
        """Cancel every WAITING box on this tracked_stock (§5.9).

        Callback failure for one box is isolated -- the rest still get
        called. The DB transitions are batched inside the manager's
        transaction; the callbacks run after commit (default path) or
        after flush (external session) so a flaky broker API cannot
        leave the DB and the manager out of sync (trading-logic
        blocker 2).
        """
        async with await self._stock_lock(tracked_stock_id):
            records = await self._with_session(
                session, self._cancel_waiting_inner,
                tracked_stock_id=tracked_stock_id, reason=reason,
            )
        if on_orphan_cancel is not None:
            for record in records:
                await self._invoke_orphan_callback(on_orphan_cancel, record.id)
        return records

    async def _cancel_waiting_inner(
        self,
        session: AsyncSession,
        *,
        tracked_stock_id: str,
        reason: str,
    ) -> list[BoxRecord]:
        await repo.fetch_tracked_for_update(session, tracked_stock_id)
        rows = await repo.list_for_tracked(session, tracked_stock_id)
        cancelled: list[BoxRecord] = []
        for orm in rows:
            if orm.status is not BoxStatus.WAITING:
                continue
            orm.status = transition_box(orm.status, BoxEvent.USER_DELETED)
            orm.invalidation_reason = reason
            cancelled.append(from_orm(orm))
        await session.flush()
        if cancelled:
            log.info(
                "v71_boxes_cancelled_for_tracked",
                extra={
                    "tracked_stock_id": tracked_stock_id,
                    "reason": reason,
                    "count": len(cancelled),
                },
            )
        return cancelled

    # -- queries ---------------------------------------------------------

    async def get(
        self, box_id: str, *, session: AsyncSession | None = None,
    ) -> BoxRecord:
        return await self._with_session(
            session, self._get_inner, box_id=box_id,
        )

    async def _get_inner(
        self, session: AsyncSession, *, box_id: str,
    ) -> BoxRecord:
        orm = await repo.fetch_box(session, box_id)
        if orm is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        return from_orm(orm)

    async def list_for_tracked(
        self, tracked_stock_id: str, *, session: AsyncSession | None = None,
    ) -> list[BoxRecord]:
        return await self._with_session(
            session,
            self._list_for_tracked_inner,
            tracked_stock_id=tracked_stock_id,
        )

    async def _list_for_tracked_inner(
        self, session: AsyncSession, *, tracked_stock_id: str,
    ) -> list[BoxRecord]:
        rows = await repo.list_for_tracked(session, tracked_stock_id)
        return [from_orm(o) for o in rows]

    async def list_waiting_for_tracked(
        self,
        tracked_stock_id: str,
        path_type: PathType,
        *,
        session: AsyncSession | None = None,
    ) -> list[BoxRecord]:
        """Hot path. Q7: emits a warning if the query exceeds 100ms
        (NFR1 1s budget at 10% headroom)."""
        t0 = time.perf_counter()
        try:
            return await self._with_session(
                session,
                self._list_waiting_inner,
                tracked_stock_id=tracked_stock_id,
                path_type=path_type,
            )
        finally:
            elapsed = time.perf_counter() - t0
            if elapsed > _LIST_WAITING_NFR1_BUDGET_SECONDS:
                log.warning(
                    "v71_box_query_slow",
                    extra={
                        "method": "list_waiting_for_tracked",
                        "tracked_stock_id": tracked_stock_id,
                        "path_type": path_type.value,
                        "elapsed_seconds": round(elapsed, 4),
                    },
                )

    async def _list_waiting_inner(
        self,
        session: AsyncSession,
        *,
        tracked_stock_id: str,
        path_type: PathType,
    ) -> list[BoxRecord]:
        rows = await repo.list_waiting_for_tracked(
            session, tracked_stock_id, path_type,
        )
        return [from_orm(o) for o in rows]

    async def list_all(
        self,
        *,
        status: BoxStatus | None = None,
        limit: int = 1000,
        session: AsyncSession | None = None,
    ) -> list[BoxRecord]:
        """All boxes, optionally filtered by status. Default ``limit=1000``
        guards against unbounded scans (security M4)."""
        return await self._with_session(
            session,
            self._list_all_inner,
            status=status,
            limit=limit,
        )

    async def _list_all_inner(
        self,
        session: AsyncSession,
        *,
        status: BoxStatus | None,
        limit: int,
    ) -> list[BoxRecord]:
        rows = await repo.list_all(session, status=status, limit=limit)
        return [from_orm(o) for o in rows]

    # -- 30-day expiry (§3.7) -------------------------------------------

    async def check_30day_expiry(
        self,
        *,
        now: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> list[BoxRecord]:
        """WAITING boxes due for a 30-day reminder.

        ``now`` must be tz-aware (PRD §2.2 columns are TIMESTAMPTZ).
        Default uses the manager clock.
        """
        now_value = now if now is not None else self._clock()
        if now_value.tzinfo is None:
            raise ValueError(
                "check_30day_expiry: now must be tz-aware "
                "(PRD §2.2 columns are TIMESTAMPTZ)"
            )
        return await self._with_session(
            session,
            self._check_30day_inner,
            now=now_value,
        )

    async def _check_30day_inner(
        self, session: AsyncSession, *, now: datetime,
    ) -> list[BoxRecord]:
        rows = await repo.find_30day_due(
            session,
            now=now,
            days=V71Constants.BOX_EXPIRY_REMINDER_DAYS,
        )
        return [from_orm(o) for o in rows]

    async def mark_reminded(
        self,
        box_id: str,
        *,
        when: datetime | None = None,
        session: AsyncSession | None = None,
    ) -> BoxRecord:
        when_value = when if when is not None else self._clock()
        if when_value.tzinfo is None:
            raise ValueError("mark_reminded: when must be tz-aware")
        return await self._with_session(
            session,
            self._mark_reminded_inner,
            box_id=box_id,
            when=when_value,
        )

    async def _mark_reminded_inner(
        self, session: AsyncSession, *, box_id: str, when: datetime,
    ) -> BoxRecord:
        orm = await repo.fetch_box(session, box_id, for_update=True)
        if orm is None:
            raise BoxNotFoundError(f"No box with id {box_id!r}")
        orm.last_reminder_at = when
        await session.flush()
        await session.refresh(orm)
        return from_orm(orm)

    # -- overlap helper (pure, kept for backward-compatibility) ---------

    @staticmethod
    def validate_no_overlap(
        existing: list[BoxRecord],
        new_upper: int,
        new_lower: int,
    ) -> bool:
        """True iff ``[new_lower, new_upper]`` does not intersect any
        existing box's interval. Strict bounds (PRD §3.4): boundary
        touch is NOT overlap.

        Kept for backward-compat with tests that pass in-memory lists.
        DB-backed paths use :func:`box_repository.find_overlap`.
        """
        for box in existing:
            if new_upper > box.lower_price and new_lower < box.upper_price:
                return False
        return True

    # -- internals -------------------------------------------------------

    async def _with_session(
        self,
        provided: AsyncSession | None,
        inner: Callable[..., Awaitable[object]],
        **kwargs: object,
    ) -> object:
        """Run ``inner`` either in the caller's session (if it owns a
        transaction) or in a fresh one from the manager's sessionmaker.
        """
        if provided is not None:
            self._ensure_in_transaction(provided)
            return await inner(provided, **kwargs)
        async with self._sm() as session, session.begin():
            return await inner(session, **kwargs)

    @staticmethod
    async def _invoke_orphan_callback(
        callback: Callable[[str], Awaitable[None] | None],
        box_id: str,
    ) -> None:
        try:
            result = callback(box_id)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001 - callback isolation
            # Security H4: log the error type only. Box state is already
            # CANCELLED so the next reconcile pass can pick up any
            # leftover broker order (trading-logic blocker 2).
            log.warning(
                "v71_box_orphan_callback_failed",
                extra={"box_id": box_id, "error": type(exc).__name__},
            )

    @staticmethod
    def _validate_box_fields(
        *,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        stop_loss_pct: float,
    ) -> None:
        if upper_price <= lower_price:
            raise BoxValidationError("upper_price must be > lower_price")
        if lower_price <= 0:
            raise BoxValidationError("prices must be positive")
        if not (0 < position_size_pct <= 100):
            raise BoxValidationError(
                "position_size_pct must satisfy 0 < x <= 100"
            )
        if stop_loss_pct >= 0:
            raise BoxValidationError("stop_loss_pct must be negative")


__all__ = [
    "BoxModificationError",
    "BoxNotFoundError",
    "BoxOverlapError",
    "BoxRecord",
    "BoxValidationError",
    "V71BoxManager",
]
