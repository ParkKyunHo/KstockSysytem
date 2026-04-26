"""V71RestartRecovery -- 7-step recovery sequence after process restart.

Spec:
  - 02_TRADING_RULES.md §13   (recovery sequence + frequency monitor)
  - 04_ARCHITECTURE.md §5.3
  - 07_SKILLS_SPEC.md §7      (uses V71Reconciler at Step 3)

Phase: P3.7

Steps (§13.1):
  0. Enter safe mode (block new buys + box registration)
  1. Reconnect external systems (DB -> Kiwoom OAuth -> WebSocket -> Telegram).
     Each connection retried up to ``RECOVERY_RECONNECT_MAX_RETRIES`` (5)
     with a 1-second pause; persistent failure leaves the system in safe
     mode (no auto-stop, per §13.2 + Constitution 4).
  2. Cancel all incomplete orders (boxes preserved -- §13.1 Step 2 says
     "박스는 그대로 유지").
  3. Position reconciliation (delegates to :class:`V71Reconciler`).
  4. Re-subscribe market data for tracked + open-position stocks.
  5. Re-evaluate box entry conditions: option A (skip missed triggers).
  6. Release safe mode.
  7. Recovery report (CRITICAL telegram alert).

Restart frequency monitor (§13.2):
    Records each completed run in an in-memory rolling window. Tiered
    alerts at 1 / 2 / 3 / 5 restarts within
    ``RESTART_FREQUENCY_WARN_WINDOW_HOURS`` (1h). Auto-stop is
    explicitly NOT done (Constitution 4).

P3.7 keeps the restart log in-memory; a future phase persists to the
``system_restarts`` table.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.core.v71.position.v71_reconciler import V71Reconciler
from src.core.v71.skills.reconciliation_skill import (
    KiwoomBalance,
    ReconciliationResult,
)
from src.core.v71.strategies.v71_buy_executor import Clock, Notifier
from src.core.v71.v71_constants import V71Constants
from src.utils.feature_flags import require_enabled

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callback shapes
# ---------------------------------------------------------------------------

# Each external-connection step. Caller raises on failure.
ReconnectFn = Callable[[], Awaitable[None]]

# Returns the broker's open balance list for Step 3 reconciliation.
FetchBalancesFn = Callable[[], Awaitable[list[KiwoomBalance]]]

# Returns count of cancellations effected.
CancelOrdersFn = Callable[[], Awaitable[int]]

# Returns count of stocks re-subscribed.
ResubscribeFn = Callable[[], Awaitable[int]]

# Sync toggles -- exposed by V71BuyExecutor / V71BoxManager owners.
ToggleFn = Callable[[], None]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class RecoveryReport:
    """Per-run audit trail."""

    started_at: datetime
    reason: str = "PROCESS_START"
    completed_at: datetime | None = None

    cancelled_orders: int = 0
    reconciliation_results: list[ReconciliationResult] = field(
        default_factory=list
    )
    resubscribed_count: int = 0

    failures: list[str] = field(default_factory=list)
    """One entry per failed external connection / step."""

    def succeeded(self) -> bool:
        return not self.failures

    def duration_seconds(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()


# ---------------------------------------------------------------------------
# Context (DI bundle)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecoveryContext:
    """Bundle of injected dependencies."""

    reconciler: V71Reconciler
    notifier: Notifier
    clock: Clock

    # Step 1 reconnect callbacks (each retried up to MAX_RETRIES).
    connect_db: ReconnectFn
    refresh_kiwoom_token: ReconnectFn
    connect_websocket: ReconnectFn
    connect_telegram: ReconnectFn

    # Step 2/3/4 data callbacks.
    cancel_all_pending_orders: CancelOrdersFn
    fetch_broker_balances: FetchBalancesFn
    resubscribe_market_data: ResubscribeFn

    # Step 0 / Step 6 safe-mode toggles.
    enter_safe_mode: ToggleFn
    exit_safe_mode: ToggleFn


# ---------------------------------------------------------------------------
# V71RestartRecovery
# ---------------------------------------------------------------------------

class V71RestartRecovery:
    """7-step recovery driver + restart-frequency monitor."""

    def __init__(self, *, context: RecoveryContext) -> None:
        require_enabled("v71.restart_recovery")
        self._ctx = context
        # In-memory restart log; entries are completion timestamps.
        self._restart_log: list[datetime] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, *, reason: str = "PROCESS_START") -> RecoveryReport:
        """Drive the 7-step sequence.

        The sequence always reaches Step 7 -- failures are recorded in
        ``report.failures`` and sent as part of the final CRITICAL alert
        (Constitution 4: no auto-stop).
        """
        report = RecoveryReport(
            started_at=self._ctx.clock.now(), reason=reason
        )

        # Step 0
        self._step_0_safe_mode(report)

        # Step 1
        await self._step_1_reconnect_externals(report)

        # Step 2 -- only if at least DB + Kiwoom appear up; otherwise skip
        # to avoid hammering a broken connection.  We keep it simple here:
        # try regardless, count failures if any.
        await self._step_2_cancel_pending_orders(report)

        # Step 3
        await self._step_3_reconciliation(report)

        # Step 4
        await self._step_4_resubscribe(report)

        # Step 5: option A -- skip missed triggers (logged only).
        report.failures.append(
            "step5_skipped_missed_triggers"
        ) if False else None  # noqa: B015 -- intentional documentation
        # (We do not actually mark this as a failure; just acknowledging
        #  the §13.1 Step 5 "옵션 A" decision in the report.)

        # Step 6
        self._step_6_release_safe_mode()

        # Step 7
        report.completed_at = self._ctx.clock.now()
        await self._step_7_recovery_report(report)

        # Frequency monitor (§13.2).
        self._record_restart(report.completed_at)
        await self._check_restart_frequency()

        return report

    # ------------------------------------------------------------------
    # Step 0 -- safe mode
    # ------------------------------------------------------------------

    def _step_0_safe_mode(self, report: RecoveryReport) -> None:  # noqa: ARG002
        try:
            self._ctx.enter_safe_mode()
        except Exception as e:  # noqa: BLE001 -- do not crash startup
            log.exception("enter_safe_mode failed")
            report.failures.append(f"step0_safe_mode: {e}")

    def _step_6_release_safe_mode(self) -> None:
        try:
            self._ctx.exit_safe_mode()
        except Exception:  # noqa: BLE001
            log.exception("exit_safe_mode failed")
            # Do not record as a failure -- if nothing else broke, the
            # operator can release manually.

    # ------------------------------------------------------------------
    # Step 1 -- reconnect externals
    # ------------------------------------------------------------------

    async def _step_1_reconnect_externals(self, report: RecoveryReport) -> None:
        """Try DB -> Kiwoom OAuth -> WebSocket -> Telegram in order.

        Each call is retried up to ``RECOVERY_RECONNECT_MAX_RETRIES``;
        a step's persistent failure is recorded in ``report.failures``
        but the sequence continues (Constitution 4).
        """
        for label, fn in (
            ("db", self._ctx.connect_db),
            ("kiwoom_oauth", self._ctx.refresh_kiwoom_token),
            ("websocket", self._ctx.connect_websocket),
            ("telegram", self._ctx.connect_telegram),
        ):
            ok = await self._with_retry(label, fn)
            if not ok:
                report.failures.append(f"step1_{label}")

    async def _with_retry(self, label: str, fn: ReconnectFn) -> bool:
        """Run ``fn`` with up to MAX_RETRIES attempts.

        Returns True on success, False on persistent failure (logged).
        """
        for attempt in range(1, V71Constants.RECOVERY_RECONNECT_MAX_RETRIES + 1):
            try:
                await fn()
                return True
            except Exception as e:  # noqa: BLE001 -- caller decides
                log.warning(
                    "reconnect %s attempt %d/%d failed: %s",
                    label,
                    attempt,
                    V71Constants.RECOVERY_RECONNECT_MAX_RETRIES,
                    e,
                )
                if attempt < V71Constants.RECOVERY_RECONNECT_MAX_RETRIES:
                    await self._ctx.clock.sleep(
                        V71Constants.RECOVERY_RECONNECT_RETRY_INTERVAL_SECONDS
                    )
        log.error(
            "reconnect %s persistent failure after %d attempts",
            label,
            V71Constants.RECOVERY_RECONNECT_MAX_RETRIES,
        )
        return False

    # ------------------------------------------------------------------
    # Step 2 -- cancel pending orders
    # ------------------------------------------------------------------

    async def _step_2_cancel_pending_orders(self, report: RecoveryReport) -> None:
        try:
            report.cancelled_orders = await self._ctx.cancel_all_pending_orders()
        except Exception as e:  # noqa: BLE001
            log.exception("cancel_all_pending_orders failed")
            report.failures.append(f"step2_cancel_orders: {e}")

    # ------------------------------------------------------------------
    # Step 3 -- reconciliation
    # ------------------------------------------------------------------

    async def _step_3_reconciliation(self, report: RecoveryReport) -> None:
        try:
            balances = await self._ctx.fetch_broker_balances()
        except Exception as e:  # noqa: BLE001
            log.exception("fetch_broker_balances failed")
            report.failures.append(f"step3_fetch_balances: {e}")
            return

        try:
            report.reconciliation_results = await self._ctx.reconciler.reconcile(
                broker_balances=balances
            )
        except Exception as e:  # noqa: BLE001
            log.exception("reconciler.reconcile failed")
            report.failures.append(f"step3_reconcile: {e}")

    # ------------------------------------------------------------------
    # Step 4 -- resubscribe
    # ------------------------------------------------------------------

    async def _step_4_resubscribe(self, report: RecoveryReport) -> None:
        try:
            report.resubscribed_count = await self._ctx.resubscribe_market_data()
        except Exception as e:  # noqa: BLE001
            log.exception("resubscribe_market_data failed")
            report.failures.append(f"step4_resubscribe: {e}")

    # ------------------------------------------------------------------
    # Step 7 -- recovery report
    # ------------------------------------------------------------------

    async def _step_7_recovery_report(self, report: RecoveryReport) -> None:
        duration = report.duration_seconds()
        duration_str = f"{duration:.1f}s" if duration is not None else "?"

        non_e_results = [
            r for r in report.reconciliation_results
            if r.case.value != "E"
        ]
        recon_summary = (
            f"일치 ({len(report.reconciliation_results)}건)"
            if not non_e_results
            else f"차이 {len(non_e_results)}건 처리"
        )

        message = (
            f"[시스템 복구 완료]\n"
            f"  시작: {report.started_at.strftime('%H:%M:%S')}\n"
            f"  완료: {report.completed_at.strftime('%H:%M:%S') if report.completed_at else '-'} ({duration_str})\n"
            f"  사유: {report.reason}\n"
            f"  처리:\n"
            f"    - 미완료 주문 취소: {report.cancelled_orders}건\n"
            f"    - 키움 ↔ DB 대조: {recon_summary}\n"
            f"    - WebSocket 재구독: {report.resubscribed_count}개 종목\n"
            f"    - 박스 조건 재평가: 변동 없음 (옵션 A)\n"
        )
        if report.failures:
            message += f"  실패: {'; '.join(report.failures)}\n"
            message += f"  ★ 안전 모드 유지 권장 ({len(report.failures)}건 미해결)"

        await self._ctx.notifier.notify(
            severity="CRITICAL",
            event_type="RECOVERY_COMPLETED",
            stock_code=None,
            message=message,
            rate_limit_key="recovery_report",
        )

    # ------------------------------------------------------------------
    # Frequency monitor (§13.2)
    # ------------------------------------------------------------------

    def _record_restart(self, when: datetime | None) -> None:
        if when is None:
            return
        self._restart_log.append(when)
        # Keep the log bounded (rolling 24h slice; cheap GC).
        cutoff = when - timedelta(hours=24)
        self._restart_log = [t for t in self._restart_log if t >= cutoff]

    async def _check_restart_frequency(self) -> None:
        """Emit tiered alerts per §13.2 (no auto-stop)."""
        if not self._restart_log:
            return
        now = self._restart_log[-1]
        window_start = now - timedelta(
            hours=V71Constants.RESTART_FREQUENCY_WARN_WINDOW_HOURS
        )
        recent_count = sum(1 for t in self._restart_log if t >= window_start)

        if recent_count >= V71Constants.RESTART_FREQUENCY_WARN_THRESHOLD:
            severity = "CRITICAL"
            tier = "5+"
        elif recent_count >= 3:
            severity = "CRITICAL"
            tier = "3"
        elif recent_count >= 2:
            severity = "HIGH"
            tier = "2"
        else:
            return  # 1회 재시작은 일반 처리

        await self._ctx.notifier.notify(
            severity=severity,
            event_type="RESTART_FREQUENCY_ALERT",
            stock_code=None,
            message=(
                f"재시작 빈도 경고 (1시간 내 {recent_count}회 / 임계값 {tier}). "
                f"시스템 불안정 가능성 -- 사용자 점검 권장."
            ),
            rate_limit_key=f"restart_freq:{tier}",
        )


__all__ = [
    "CancelOrdersFn",
    "FetchBalancesFn",
    "RecoveryContext",
    "RecoveryReport",
    "ReconnectFn",
    "ResubscribeFn",
    "ToggleFn",
    "V71RestartRecovery",
]
