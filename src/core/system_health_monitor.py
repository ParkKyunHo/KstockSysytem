"""
시스템 헬스 모니터 (V7.1)

60초 주기로 시스템 내부 상태를 점검하고,
장애 발생 시 텔레그램 알림을 전송합니다.
15:30에 일일 요약 리포트를 생성합니다.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, Callable, Awaitable
import asyncio

from src.utils.logger import get_logger


HEALTH_CHECK_INTERVAL = 60  # 60초
DAILY_REPORT_TIME = time(15, 30)  # 15:30


@dataclass
class HealthCallbacks:
    """헬스 모니터 콜백 인터페이스"""
    get_notification_queue_stats: Optional[Callable[[], dict]] = None
    get_telegram_stats: Optional[Callable[[], dict]] = None
    get_v7_coordinator_status: Optional[Callable[[], dict]] = None
    get_signal_processor_stats: Optional[Callable[[], dict]] = None
    get_exit_coordinator_stats: Optional[Callable[[], dict]] = None
    send_telegram: Optional[Callable[[str], Awaitable]] = None
    is_engine_running: Optional[Callable[[], bool]] = None


class SystemHealthMonitor:
    """60초 주기 시스템 헬스 모니터"""

    def __init__(self, logger=None):
        self._logger = logger or get_logger(__name__)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: Optional[HealthCallbacks] = None

        # 체크 통계
        self._checks_performed = 0
        self._alerts_sent = 0
        self._last_check_time: Optional[datetime] = None

        # 일일 통계
        self._daily_report_sent_today = False
        self._health_issues: list = []

    async def start(self, callbacks: HealthCallbacks) -> None:
        """헬스 모니터 시작"""
        self._callbacks = callbacks
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        self._logger.info("[HealthMonitor] 시작됨 (60초 주기)")

    async def stop(self) -> None:
        """헬스 모니터 중지"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._logger.info("[HealthMonitor] 중지됨")

    async def _monitor_loop(self) -> None:
        """메인 모니터링 루프"""
        while self._running:
            try:
                if self._callbacks and self._callbacks.is_engine_running:
                    if self._callbacks.is_engine_running():
                        await self._perform_health_check()
                        await self._check_daily_report()

                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"[HealthMonitor] 모니터링 루프 오류: {e}")
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    async def _perform_health_check(self) -> None:
        """헬스 체크 수행"""
        self._checks_performed += 1
        self._last_check_time = datetime.now()
        issues = []

        try:
            # 1. 알림 큐 상태 확인
            if self._callbacks.get_notification_queue_stats:
                try:
                    nq_stats = self._callbacks.get_notification_queue_stats()
                    if nq_stats:
                        if nq_stats.get('send_func_none_count', 0) > 0:
                            issues.append("CRITICAL: 알림 전송 함수 미설정")
                        if nq_stats.get('dropped_count', 0) > 0:
                            issues.append(f"WARNING: 알림 손실 {nq_stats['dropped_count']}건")
                        if nq_stats.get('consecutive_failures', 0) >= 3:
                            issues.append(f"WARNING: 연속 전송 실패 {nq_stats['consecutive_failures']}회")
                except Exception as e:
                    self._logger.warning(f"[HealthMonitor] 알림 큐 체크 오류: {e}")

            # 2. 텔레그램 Circuit Breaker 상태
            if self._callbacks.get_telegram_stats:
                try:
                    tg_stats = self._callbacks.get_telegram_stats()
                    if tg_stats:
                        cb = tg_stats.get('circuit_breaker', {})
                        if cb.get('is_open'):
                            issues.append(f"CRITICAL: 텔레그램 Circuit Breaker 열림 ({cb.get('remaining_seconds', 0)}초)")
                except Exception as e:
                    self._logger.warning(f"[HealthMonitor] 텔레그램 체크 오류: {e}")

            # 3. V7 Coordinator 상태
            if self._callbacks.get_v7_coordinator_status:
                try:
                    v7_status = self._callbacks.get_v7_coordinator_status()
                    if v7_status:
                        if not v7_status.get('dual_pass_task_active'):
                            issues.append("CRITICAL: DualPass 루프 중단됨")
                        if not v7_status.get('notification_task_active'):
                            issues.append("CRITICAL: 알림 처리 루프 중단됨")
                except Exception as e:
                    self._logger.warning(f"[HealthMonitor] V7 Coordinator 체크 오류: {e}")

            # 4. 이슈 발견 시 알림
            if issues:
                self._health_issues.extend(issues)
                alert_msg = "[시스템 헬스 경고]\n\n" + "\n".join(f"- {i}" for i in issues)
                self._logger.warning(f"[HealthMonitor] 이슈 감지: {issues}")

                if self._callbacks.send_telegram:
                    try:
                        await self._callbacks.send_telegram(alert_msg)
                        self._alerts_sent += 1
                    except Exception:
                        pass

        except Exception as e:
            self._logger.error(f"[HealthMonitor] 헬스 체크 오류: {e}")

    async def _check_daily_report(self) -> None:
        """15:30 일일 리포트 발송 확인"""
        now = datetime.now()

        # 날짜 변경 시 리셋
        if now.hour < 9:
            self._daily_report_sent_today = False
            return

        if self._daily_report_sent_today:
            return

        if now.hour == DAILY_REPORT_TIME.hour and now.minute >= DAILY_REPORT_TIME.minute:
            await self._send_daily_report()
            self._daily_report_sent_today = True

    async def _send_daily_report(self) -> None:
        """일일 요약 리포트 전송"""
        try:
            lines = ["[일일 시스템 리포트]", ""]

            # 알림 큐 통계
            if self._callbacks.get_notification_queue_stats:
                try:
                    nq = self._callbacks.get_notification_queue_stats()
                    if nq:
                        lines.append(f"알림 전송 성공: {nq.get('success_count', 0)}건")
                        lines.append(f"알림 전송 실패: {nq.get('failed_count', 0)}건")
                        lines.append(f"알림 손실: {nq.get('dropped_count', 0)}건")
                except Exception:
                    pass

            # 텔레그램 통계
            if self._callbacks.get_telegram_stats:
                try:
                    tg = self._callbacks.get_telegram_stats()
                    if tg:
                        lines.append(f"CB 발동: {tg.get('circuit_breaker_opens_today', 0)}회")
                except Exception:
                    pass

            # 신호 처리 통계
            if self._callbacks.get_signal_processor_stats:
                try:
                    sp = self._callbacks.get_signal_processor_stats()
                    if sp:
                        lines.append(f"신호 처리: {sp.get('signals_processed', 0)}건")
                        lines.append(f"알림 전송: {sp.get('signal_alerts_sent', 0)}건")
                        lines.append(f"큐 만료: {sp.get('signals_expired', 0)}건")
                except Exception:
                    pass

            # 청산 통계
            if self._callbacks.get_exit_coordinator_stats:
                try:
                    ec = self._callbacks.get_exit_coordinator_stats()
                    if ec:
                        lines.append(f"청산: {ec.get('total_exits', 0)}건")
                except Exception:
                    pass

            # 헬스 체크 통계
            lines.append(f"\n헬스 체크: {self._checks_performed}회")
            lines.append(f"경고 알림: {self._alerts_sent}건")

            if self._health_issues:
                lines.append(f"\n발생 이슈 ({len(self._health_issues)}건):")
                # 최근 5개만 표시
                for issue in self._health_issues[-5:]:
                    lines.append(f"  - {issue}")

            report = "\n".join(lines)

            if self._callbacks.send_telegram:
                await self._callbacks.send_telegram(report)
                self._logger.info("[HealthMonitor] 일일 리포트 전송 완료")

        except Exception as e:
            self._logger.error(f"[HealthMonitor] 일일 리포트 전송 실패: {e}")

    def get_health_report(self) -> str:
        """현재 헬스 상태 리포트 (텔레그램 /health 명령어용)"""
        lines = ["[시스템 헬스 리포트]", ""]

        try:
            lines.append(f"마지막 체크: {self._last_check_time.strftime('%H:%M:%S') if self._last_check_time else 'N/A'}")
            lines.append(f"총 체크: {self._checks_performed}회")
            lines.append(f"경고 알림: {self._alerts_sent}건")

            # 알림 큐 상태
            if self._callbacks and self._callbacks.get_notification_queue_stats:
                try:
                    nq = self._callbacks.get_notification_queue_stats()
                    if nq:
                        lines.append(f"\n[알림 큐]")
                        lines.append(f"대기: {nq.get('pending', 0)}건")
                        lines.append(f"성공: {nq.get('success_count', 0)}건")
                        lines.append(f"실패: {nq.get('failed_count', 0)}건")
                        lines.append(f"손실: {nq.get('dropped_count', 0)}건")
                        lines.append(f"처리 중: {'예' if nq.get('is_processing') else '아니오'}")

                        last_success = nq.get('last_success_time')
                        if last_success:
                            lines.append(f"마지막 성공: {last_success}")
                except Exception:
                    lines.append(f"\n[알림 큐] 조회 오류")

            # CB 상태
            if self._callbacks and self._callbacks.get_telegram_stats:
                try:
                    tg = self._callbacks.get_telegram_stats()
                    if tg:
                        cb = tg.get('circuit_breaker', {})
                        cb_status = "열림" if cb.get('is_open') else "닫힘"
                        lines.append(f"\n[Circuit Breaker]")
                        lines.append(f"상태: {cb_status}")
                        lines.append(f"실패: {cb.get('failures', 0)}/{cb.get('threshold', 5)}")
                        lines.append(f"오늘 발동: {tg.get('circuit_breaker_opens_today', 0)}회")
                except Exception:
                    lines.append(f"\n[Circuit Breaker] 조회 오류")

            # V7 상태
            if self._callbacks and self._callbacks.get_v7_coordinator_status:
                try:
                    v7 = self._callbacks.get_v7_coordinator_status()
                    if v7:
                        lines.append(f"\n[V7 Coordinator]")
                        lines.append(f"DualPass: {'활성' if v7.get('dual_pass_task_active') else '중단!'}")
                        lines.append(f"알림루프: {'활성' if v7.get('notification_task_active') else '중단!'}")
                        stats = v7.get('stats', {})
                        lines.append(f"신호: {stats.get('signals_sent', 0)}건")
                except Exception:
                    lines.append(f"\n[V7 Coordinator] 조회 오류")

            # 최근 이슈
            if self._health_issues:
                lines.append(f"\n[최근 이슈] ({len(self._health_issues)}건)")
                for issue in self._health_issues[-3:]:
                    lines.append(f"  - {issue}")

        except Exception as e:
            lines.append(f"\n오류: {e}")

        return "\n".join(lines)
