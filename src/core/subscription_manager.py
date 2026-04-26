"""
조건검색 구독 관리자

책임:
- 조건검색 구독/해제의 단일 진입점
- 지수 백오프 재시도 (최대 5회)
- 주기적 헬스체크 (신호 수신 모니터링)
- 상태 추적 및 텔레그램 알림
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Awaitable, TYPE_CHECKING
import asyncio
import logging
import threading  # V6.2-Q FIX: 동기 메서드 동시성 보호

if TYPE_CHECKING:
    from src.api.websocket import KiwoomWebSocket
    from src.notification.telegram import TelegramBot


class SubscriptionState(Enum):
    """
    구독 상태 (Subscription Layer)

    상태 전이 규칙:
    - SUBSCRIBED + 신호 없음 → SUBSCRIBED (아무것도 안함!)
    - SUBSCRIBING + 5회 실패 → SUB_FAILED
    - SUB_FAILED + 추가 실패 → SUB_SUSPENDED (30분 회로 차단)
    - SUB_SUSPENDED + 30분 경과 → 복구 시도
    - VERIFYING: 구독 성공 후 실시간 신호 수신 검증 중 (좀비 구독 감지)
    """
    IDLE = "idle"                    # 초기 상태
    SUBSCRIBING = "subscribing"      # 구독 시도 중
    SUBSCRIBED = "subscribed"        # 정상 구독 (구 ACTIVE)
    VERIFYING = "verifying"          # 구독 검증 중 (좀비 구독 감지용)
    SUB_FAILED = "sub_failed"        # 구독 실패 (재시도 가능)
    SUB_SUSPENDED = "sub_suspended"  # 회로 차단 (30분간 자동 재시도 금지)


class SubscriptionPurpose(Enum):
    """구독 목적"""
    AUTO_UNIVERSE = "auto_universe"  # 자동 유니버스
    ATR_ALERT = "atr_alert"          # ATR 알림


@dataclass
class SubscribeResult:
    """구독 결과 (bool 대신 상세 정보 반환)"""
    success: bool
    reason_code: Optional[str] = None  # "SUCCESS", "TIMEOUT", "RETURN_CODE_ERROR", "MAX_RETRY_EXCEEDED"
    reason_msg: Optional[str] = None
    initial_stocks: List[str] = field(default_factory=list)
    raw_response: Optional[dict] = None


@dataclass
class SubscriptionInfo:
    """구독 정보"""
    seq: str
    purpose: SubscriptionPurpose
    state: SubscriptionState = SubscriptionState.IDLE

    # 신호 추적 (재구독 트리거로 사용 금지!)
    last_signal_time: Optional[datetime] = None

    # 재시도 관리
    retry_count: int = 0
    max_retries: int = 5
    consecutive_failures: int = 0  # 연속 실패 (회로 차단용)

    # 회로 차단
    suspended_until: Optional[datetime] = None

    # 구독 정보
    subscribed_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_return_code: Optional[str] = None

    # 좀비 구독 검증용
    verification_started_at: Optional[datetime] = None
    zombie_retry_count: int = 0  # 좀비 구독 재시도 횟수


@dataclass
class HealthIssue:
    """헬스체크 이슈"""
    seq: str
    issue_type: str  # "no_signal", "subscription_failed"
    details: str
    detected_at: datetime = field(default_factory=datetime.now)


class SubscriptionManager:
    """
    조건검색 구독 관리자

    사용법:
        manager = SubscriptionManager(websocket, telegram, logger)
        await manager.subscribe("0", SubscriptionPurpose.ATR_ALERT)

        # WebSocket 재연결 시
        await manager.on_websocket_reconnected()
    """

    # 설정 상수
    MAX_RETRY_COUNT = 5
    BASE_RETRY_DELAY = 1.0  # 초
    MAX_RETRY_DELAY = 30.0  # 최대 30초
    SIGNAL_TIMEOUT_MINUTES = 10  # 10분간 신호 없으면 (로그만, 재구독 안함!)
    HEALTH_CHECK_INTERVAL = 60  # 1분마다 체크
    # M-004 FIX: 재연결 대기 시간 단축 (3초→1초, 신호 손실 감소)
    WS_RECONNECT_SETTLE_DELAY = 1.0  # WebSocket 재연결 후 안정화 대기 시간

    # 회로 차단 설정 (Circuit Breaker)
    CIRCUIT_BREAK_THRESHOLD = 2  # 연속 N번 SUB_FAILED → SUB_SUSPENDED
    CIRCUIT_BREAK_DURATION = 1800  # 30분간 회로 차단

    # 알림 쿨다운
    ALERT_COOLDOWN_MINUTES = 15  # 동일 알림 최소 간격

    # 폴링 Fallback 설정
    POLLING_INTERVAL = 30.0  # 폴링 주기 (초)
    # REALTIME_RETRY_INTERVAL 제거 - 폴링 루프에서 실시간 재시도 금지!

    # 좀비 구독 검증 설정
    VERIFICATION_DELAY = 30.0  # 구독 후 검증까지 대기 시간 (초)
    MAX_ZOMBIE_RETRIES = 2     # 좀비 구독 재시도 최대 횟수

    def __init__(
        self,
        websocket: "KiwoomWebSocket",
        telegram: Optional["TelegramBot"] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._ws = websocket
        self._telegram = telegram
        self._logger = logger or logging.getLogger(__name__)

        # 구독 상태
        self._subscriptions: Dict[str, SubscriptionInfo] = {}

        # 동시성 보호 (Race Condition 방지)
        self._lock = asyncio.Lock()
        self._sync_lock = threading.Lock()  # V6.2-Q FIX: 동기 메서드용

        # 헬스체크 태스크
        self._health_check_task: Optional[asyncio.Task] = None
        self._running = False

        # 콜백 (미사용 - 향후 확장용)
        self.on_subscription_failed: Optional[Callable[[str, str], Awaitable[None]]] = None
        self.on_subscription_recovered: Optional[Callable[[str], Awaitable[None]]] = None

        # 폴링 Fallback 상태
        self._polling_fallback_enabled = False
        self._polling_task: Optional[asyncio.Task] = None
        self._last_polling_stocks: set[str] = set()
        self._polling_info: Optional[SubscriptionInfo] = None

        # 폴링에서 감지된 신호 콜백 (TradingEngine에서 설정)
        self.on_polling_signal: Optional[Callable[[str], Awaitable[None]]] = None

        # 알림 쿨다운 (동일 알림 스팸 방지)
        self._alert_cooldowns: Dict[str, datetime] = {}

    async def subscribe(
        self,
        seq: str,
        purpose: SubscriptionPurpose,
    ) -> bool:
        """
        조건검색 구독 (재시도 포함)

        Args:
            seq: 조건식 번호
            purpose: 구독 목적

        Returns:
            성공 여부
        """
        async with self._lock:
            # 이미 구독 중이면 스킵
            if seq in self._subscriptions:
                existing = self._subscriptions[seq]
                if existing.state == SubscriptionState.SUBSCRIBED:
                    self._logger.debug(f"[Subscription] 이미 구독 중: seq={seq}")
                    return True
                if existing.state == SubscriptionState.SUBSCRIBING:
                    self._logger.debug(f"[Subscription] 구독 진행 중: seq={seq}")
                    return False
                if existing.state == SubscriptionState.SUB_SUSPENDED:
                    self._logger.warning(f"[Subscription] 회로 차단 중 - 구독 거부: seq={seq}")
                    return False

            # 구독 정보 생성
            info = SubscriptionInfo(seq=seq, purpose=purpose)
            self._subscriptions[seq] = info

        # Lock 해제 후 실제 구독 시도 (긴 작업)
        return await self._subscribe_with_retry(info)

    def _calc_backoff_with_jitter(self, retry_count: int) -> float:
        """지수 백오프 + jitter 계산"""
        import random
        base_delay = min(
            self.BASE_RETRY_DELAY * (2 ** (retry_count - 1)),
            self.MAX_RETRY_DELAY
        )
        # jitter: ±20%
        jitter = base_delay * 0.2 * (random.random() * 2 - 1)
        return base_delay + jitter

    async def _subscribe_with_retry(
        self, info: SubscriptionInfo, verify_after: bool = False
    ) -> bool:
        """
        구독만 재시도 (WS 재연결 절대 금지!)

        핵심 원칙:
        - WS 문제 → WebSocket Layer에서 처리
        - 구독 문제 → 이 함수에서만 처리
        - 두 문제를 절대 섞지 않음

        Args:
            info: 구독 정보
            verify_after: 구독 성공 후 좀비 구독 검증 수행 여부 (재연결 시 True)

        Returns:
            성공 여부 (bool)
        """
        info.state = SubscriptionState.SUBSCRIBING

        while info.retry_count < self.MAX_RETRY_COUNT:
            try:
                success = await self._ws.start_condition_search(info.seq)

                if success:
                    # 성공!
                    info.state = SubscriptionState.SUBSCRIBED
                    info.subscribed_at = datetime.now()
                    info.retry_count = 0
                    info.consecutive_failures = 0  # 연속 실패 카운터 리셋
                    info.last_error = None
                    info.suspended_until = None  # 회로 차단 해제

                    purpose_name = self._get_purpose_name(info.purpose)
                    self._logger.info(
                        f"[Subscription] 구독 성공: seq={info.seq}, purpose={purpose_name}"
                    )

                    # 폴링 모드 중이면 중지
                    if self._polling_fallback_enabled:
                        await self._stop_polling_fallback()
                        self._logger.info(
                            "[Subscription] 실시간 구독 성공 - 폴링 모드 중지"
                        )
                        await self._send_alert_with_cooldown(
                            alert_key=f"recovery_{info.seq}",
                            message="[복구] 실시간 조건검색 구독 성공\n폴링 모드 종료"
                        )

                    # 재연결 후 좀비 구독 검증 (백그라운드)
                    if verify_after:
                        asyncio.create_task(self._verify_subscription(info))

                    return True
                else:
                    raise Exception("start_condition_search returned False")

            except Exception as e:
                info.retry_count += 1
                info.last_error = str(e)

                self._logger.warning(
                    f"[Subscription] 구독 실패 ({info.retry_count}/{self.MAX_RETRY_COUNT}): "
                    f"seq={info.seq}, error={e}"
                )

                if info.retry_count < self.MAX_RETRY_COUNT:
                    delay = self._calc_backoff_with_jitter(info.retry_count)
                    await asyncio.sleep(delay)

        # 5회 실패 → SUB_FAILED (WS 재연결 절대 안함!)
        info.state = SubscriptionState.SUB_FAILED
        info.consecutive_failures += 1

        self._logger.error(
            f"[Subscription] 5회 실패 → SUB_FAILED: seq={info.seq}, "
            f"consecutive_failures={info.consecutive_failures}"
        )

        # 회로 차단 체크
        if info.consecutive_failures >= self.CIRCUIT_BREAK_THRESHOLD:
            await self._activate_circuit_breaker(info)
        else:
            # 아직 회로 차단 안됨 → 폴링 모드 시작
            await self._notify_subscription_failed(info)

        return False

    # =========================================
    # 좀비 구독 검증 메서드
    # =========================================

    async def _verify_subscription(self, info: SubscriptionInfo) -> None:
        """
        구독 후 실시간 신호 수신 검증 (좀비 구독 감지)

        WebSocket 재연결 후 구독이 성공(return_code=0)해도
        실제 실시간 신호(CNSRRES)가 전송되지 않는 "좀비 구독" 상태를 감지합니다.

        검증 로직:
        1. 구독 성공 후 30초 대기
        2. 폴링으로 현재 조건에 맞는 종목 조회
        3. 폴링 종목이 있는데 실시간 신호가 없으면 → 좀비 구독 → 재구독
        4. 폴링 종목이 없으면 → 시장이 조용한 것 (정상)
        """
        info.state = SubscriptionState.VERIFYING
        info.verification_started_at = datetime.now()

        self._logger.info(
            f"[Subscription] 좀비 구독 검증 시작: seq={info.seq}, "
            f"대기={self.VERIFICATION_DELAY}초"
        )

        # 검증 대기
        await asyncio.sleep(self.VERIFICATION_DELAY)

        # 이미 상태가 변경됐으면 (해제됨, 실패 등) 스킵
        if info.state != SubscriptionState.VERIFYING:
            self._logger.debug(
                f"[Subscription] 검증 스킵 (상태 변경됨): seq={info.seq}, state={info.state}"
            )
            return

        # 폴링으로 현재 종목 조회
        try:
            poll_stocks = await self._ws.poll_condition_search(info.seq)
        except Exception as e:
            self._logger.error(
                f"[Subscription] 검증 폴링 실패: seq={info.seq}, error={e}"
            )
            # 폴링 실패 시 일단 정상으로 처리 (다음 검증에서 재시도)
            info.state = SubscriptionState.SUBSCRIBED
            return

        if not poll_stocks:
            # 폴링 종목 없음 → 시장이 조용하거나 조건에 맞는 종목 없음 (정상)
            info.state = SubscriptionState.SUBSCRIBED
            info.zombie_retry_count = 0  # 리셋
            self._logger.info(
                f"[Subscription] 검증 완료 (종목 없음 - 정상): seq={info.seq}"
            )
            return

        # 폴링 종목 있음 → 실시간 신호 수신 여부 확인
        if (
            info.last_signal_time
            and info.verification_started_at
            and info.last_signal_time > info.verification_started_at
        ):
            # 검증 시작 후 신호 수신됨 → 정상
            info.state = SubscriptionState.SUBSCRIBED
            info.zombie_retry_count = 0  # 리셋
            self._logger.info(
                f"[Subscription] 검증 완료 (실시간 신호 확인): seq={info.seq}"
            )
            return

        # ============================================
        # 좀비 구독 감지!
        # 폴링 종목은 있는데 실시간 신호가 안 옴
        # ============================================
        info.zombie_retry_count += 1
        self._logger.warning(
            f"[Subscription] 좀비 구독 감지: seq={info.seq}, "
            f"폴링종목={len(poll_stocks)}개, 실시간신호=없음, "
            f"재시도={info.zombie_retry_count}/{self.MAX_ZOMBIE_RETRIES}"
        )

        if info.zombie_retry_count >= self.MAX_ZOMBIE_RETRIES:
            # 최대 재시도 초과 → 폴링 모드 전환
            self._logger.error(
                f"[Subscription] 좀비 구독 지속 - 폴링 모드 전환: seq={info.seq}"
            )
            info.state = SubscriptionState.SUB_FAILED
            await self._notify_subscription_failed(info)

            await self._send_alert_with_cooldown(
                alert_key=f"zombie_sub_{info.seq}",
                message=(
                    f"[경고] 조건검색 좀비 구독 지속\n"
                    f"조건식: #{info.seq}\n"
                    f"폴링 종목: {len(poll_stocks)}개\n"
                    f"실시간 신호: 수신 안됨\n\n"
                    f"[대응]\n"
                    f"- 폴링 모드로 전환 (30초 주기)\n"
                    f"- 서비스 재시작 권장"
                )
            )
            return

        # 재구독 시도
        self._logger.info(
            f"[Subscription] 좀비 구독 → 재구독 시도: seq={info.seq}"
        )

        # 기존 구독 해제
        try:
            await self._ws.stop_condition_search(info.seq)
            await asyncio.sleep(2.0)  # 서버 처리 대기
        except Exception as e:
            self._logger.debug(f"[Subscription] 재구독 전 해제 실패 (무시): {e}")

        # 재구독 (검증 포함)
        info.retry_count = 0
        success = await self._subscribe_with_retry(info, verify_after=True)

        if not success:
            # 재구독 실패 → SUB_FAILED (이미 _subscribe_with_retry에서 처리됨)
            self._logger.error(
                f"[Subscription] 좀비 구독 재구독 실패: seq={info.seq}"
            )

    # =========================================
    # 회로 차단 (Circuit Breaker) 메서드
    # =========================================

    async def _activate_circuit_breaker(self, info: SubscriptionInfo) -> None:
        """
        회로 차단 활성화

        연속 N회 SUB_FAILED 상태가 되면 30분간 자동 재시도를 금지합니다.
        폴링 모드는 유지하여 종목 포착은 계속합니다.
        """
        info.state = SubscriptionState.SUB_SUSPENDED
        info.suspended_until = datetime.now() + timedelta(seconds=self.CIRCUIT_BREAK_DURATION)

        self._logger.error(
            f"[Subscription] 회로 차단 활성화: seq={info.seq}, "
            f"연속실패={info.consecutive_failures}, "
            f"복구시도={info.suspended_until.strftime('%H:%M')}"
        )

        # 알림 1회 (쿨다운 적용)
        await self._send_alert_with_cooldown(
            alert_key=f"circuit_break_{info.seq}",
            message=(
                f"[경고] 조건검색 회로 차단\n"
                f"조건식: #{info.seq}\n"
                f"연속 실패: {info.consecutive_failures}회\n\n"
                f"[대응]\n"
                f"- 폴링 모드 유지 (30초 주기)\n"
                f"- 30분 후 자동 복구 시도\n"
                f"- 실시간 구독 자동 재시도 중단"
            )
        )

        # 폴링 모드 시작 (아직 안했으면)
        if not self._polling_fallback_enabled:
            await self._start_polling_fallback(info)

    async def _attempt_recovery(self, info: SubscriptionInfo) -> None:
        """
        회로 차단 후 복구 시도 (1회만)

        헬스체크 루프에서 suspended_until 경과 후 호출됩니다.
        """
        self._logger.info(f"[Subscription] 회로 차단 해제 - 복구 시도: seq={info.seq}")

        info.retry_count = 0
        success = await self._subscribe_with_retry(info)

        if success:
            info.consecutive_failures = 0
            info.suspended_until = None
            self._logger.info(f"[Subscription] 복구 성공: seq={info.seq}")

            await self._send_alert_with_cooldown(
                alert_key=f"recovery_{info.seq}",
                message=f"[복구] 조건검색 구독 복구 성공\n조건식: #{info.seq}"
            )
        else:
            # 복구 실패 → 다시 회로 차단 (_subscribe_with_retry 내부에서 처리)
            self._logger.error(f"[Subscription] 복구 실패: seq={info.seq}")

    # =========================================
    # 알림 쿨다운 메서드
    # =========================================

    async def _send_alert_with_cooldown(self, alert_key: str, message: str) -> None:
        """
        쿨다운 적용된 알림 발송

        동일한 alert_key로 15분 이내에 재발송하지 않습니다.
        """
        last_sent = self._alert_cooldowns.get(alert_key)

        if last_sent:
            elapsed = (datetime.now() - last_sent).total_seconds() / 60
            if elapsed < self.ALERT_COOLDOWN_MINUTES:
                self._logger.debug(
                    f"[Subscription] 알림 쿨다운: {alert_key}, "
                    f"{self.ALERT_COOLDOWN_MINUTES - elapsed:.0f}분 남음"
                )
                return

        self._alert_cooldowns[alert_key] = datetime.now()

        if self._telegram:
            try:
                await self._telegram.send_message(message)
            except Exception as e:
                self._logger.warning(f"[Subscription] 알림 발송 실패: {e}")

    async def unsubscribe(self, seq: str) -> bool:
        """조건검색 해제"""
        if seq not in self._subscriptions:
            return False

        try:
            await self._ws.stop_condition_search(seq)
            del self._subscriptions[seq]
            self._logger.info(f"[Subscription] 구독 해제: seq={seq}")
            return True
        except Exception as e:
            self._logger.error(f"[Subscription] 해제 실패: seq={seq}, error={e}")
            return False

    # M-004 FIX: 재연결 후 구독 시도 전 대기 시간 단축 (5초→2초, 신호 손실 감소)
    # 주의: 너무 짧으면 서버 준비 전 구독 실패 가능
    RECONNECT_SETTLE_DELAY = 2.0  # 초

    async def on_websocket_reconnected(self) -> None:
        """
        WebSocket 재연결 시 구독 복구

        주의: SUB_SUSPENDED 상태는 복구하지 않음 (회로 차단 유지)
        """
        if not self._subscriptions:
            self._logger.info("[Subscription] 재연결 감지 - 복구할 구독 없음")
            return

        # 복구 대상 필터링 (SUB_SUSPENDED 제외)
        recovery_targets = [
            (seq, info) for seq, info in self._subscriptions.items()
            if info.state != SubscriptionState.SUB_SUSPENDED
        ]

        if not recovery_targets:
            self._logger.info("[Subscription] 재연결 감지 - 모두 회로 차단 상태")
            return

        self._logger.info(
            f"[Subscription] 재연결 감지 - {self.RECONNECT_SETTLE_DELAY}초 후 구독 복구 시작 "
            f"({len(recovery_targets)}개)"
        )

        # 서버가 연결을 정착하도록 대기 (즉시 구독 시 타임아웃 발생 방지)
        await asyncio.sleep(self.RECONNECT_SETTLE_DELAY)

        success_count = 0
        fail_count = 0

        for seq, info in recovery_targets:
            info.retry_count = 0
            info.zombie_retry_count = 0  # 좀비 재시도 카운터 리셋

            # verify_after=True: 재연결 후 좀비 구독 검증 활성화
            if await self._subscribe_with_retry(info, verify_after=True):
                success_count += 1
            else:
                fail_count += 1

        # 결과 알림 (쿨다운 적용)
        await self._send_alert_with_cooldown(
            alert_key="ws_reconnect_recovery",
            message=(
                f"[알림] WS 재연결 후 구독 복구\n"
                f"성공: {success_count}/{success_count + fail_count}개"
            )
        )

    def on_signal_received(self, seq: str) -> None:
        """신호 수신 시 호출 (헬스체크용)"""
        # V6.2-Q FIX: Lock으로 동시성 보호
        with self._sync_lock:
            if seq in self._subscriptions:
                info = self._subscriptions[seq]
                info.last_signal_time = datetime.now()

                # SUB_FAILED 상태인데 신호가 왔으면 → 실제로는 작동 중이므로 복구
                if info.state == SubscriptionState.SUB_FAILED:
                    info.state = SubscriptionState.SUBSCRIBED
                    info.last_error = None
                    info.consecutive_failures = 0  # 회로 차단 카운터 리셋
                    self._logger.info(
                        f"[Subscription] 상태 자동 복구: seq={seq} (신호 수신 확인)"
                    )

    async def check_health(self) -> List[HealthIssue]:
        """구독 상태 헬스체크 (no_signal은 이슈로 반환하지 않음!)"""
        issues = []

        for seq, info in self._subscriptions.items():
            # 구독 실패 상태
            if info.state == SubscriptionState.SUB_FAILED:
                issues.append(HealthIssue(
                    seq=seq,
                    issue_type="subscription_failed",
                    details=f"마지막 에러: {info.last_error}",
                ))

            # 회로 차단 상태
            elif info.state == SubscriptionState.SUB_SUSPENDED:
                remaining = "N/A"
                if info.suspended_until:
                    remaining_sec = (info.suspended_until - datetime.now()).total_seconds()
                    remaining = f"{int(remaining_sec / 60)}분" if remaining_sec > 0 else "곧 복구"
                issues.append(HealthIssue(
                    seq=seq,
                    issue_type="circuit_breaker",
                    details=f"회로 차단 중, 복구까지: {remaining}",
                ))

            # 검증 중 상태
            elif info.state == SubscriptionState.VERIFYING:
                elapsed = "N/A"
                if info.verification_started_at:
                    elapsed_sec = (datetime.now() - info.verification_started_at).total_seconds()
                    elapsed = f"{int(elapsed_sec)}초 경과"
                issues.append(HealthIssue(
                    seq=seq,
                    issue_type="verifying",
                    details=f"좀비 구독 검증 중: {elapsed}",
                ))

            # SUBSCRIBED 상태: 신호 없음은 정상이므로 이슈로 반환하지 않음!
            # (기존 no_signal 이슈 제거)

        return issues

    async def _health_check_loop(self) -> None:
        """
        주기적 헬스체크 루프

        핵심 원칙:
        - 신호 없음 = 정상 (시장 조용) → 아무것도 안함!
        - SUB_SUSPENDED = 회로 차단 → 30분 후 복구 시도
        - SUB_FAILED = 폴링 모드 유지 → 자동 재시도 안함
        """
        while self._running:
            try:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)

                if not self._running:
                    break

                now = datetime.now()

                for seq, info in list(self._subscriptions.items()):
                    # SUBSCRIBED 상태: 신호 없음은 정상! (아무것도 안함)
                    if info.state == SubscriptionState.SUBSCRIBED:
                        if info.last_signal_time:
                            elapsed = (now - info.last_signal_time).total_seconds() / 60
                            if elapsed > self.SIGNAL_TIMEOUT_MINUTES:
                                # 로그만 남기고 재구독 안함!
                                self._logger.debug(
                                    f"[Subscription] 신호 없음 {int(elapsed)}분 (정상 상태): seq={seq}"
                                )
                        continue  # ✅ 재구독 안함!

                    # VERIFYING 상태: 검증 중 (백그라운드 태스크가 처리)
                    if info.state == SubscriptionState.VERIFYING:
                        self._logger.debug(
                            f"[Subscription] 좀비 구독 검증 중: seq={seq}"
                        )
                        continue

                    # SUB_SUSPENDED 상태: 30분 경과 시 복구 시도
                    if info.state == SubscriptionState.SUB_SUSPENDED:
                        if info.suspended_until and now >= info.suspended_until:
                            if self._is_trading_hours():
                                await self._attempt_recovery(info)
                            else:
                                self._logger.debug(
                                    f"[Subscription] 장외 시간 - 복구 보류: seq={seq}"
                                )
                        continue

                    # SUB_FAILED 상태: 폴링 모드 유지, 자동 재시도 안함
                    if info.state == SubscriptionState.SUB_FAILED:
                        self._logger.debug(
                            f"[Subscription] SUB_FAILED 유지 (자동 재시도 안함): seq={seq}"
                        )
                        continue

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"[Subscription] 헬스체크 루프 에러: {e}")

    def _is_trading_hours(self) -> bool:
        """V6.2-L: 장 운영 시간 체크 (NXT 포함 08:00~20:00)"""
        now = datetime.now()
        # NXT 프리마켓(08:00~08:50) + 정규장(09:00~15:20) + NXT 애프터(15:30~20:00)
        # KRX_CLOSING(15:20~15:30)은 NXT 중단이지만 KRX는 운영 중이므로 포함
        nxt_start = now.replace(hour=8, minute=0, second=0, microsecond=0)
        nxt_end = now.replace(hour=20, minute=0, second=0, microsecond=0)
        return nxt_start <= now <= nxt_end

    # _try_resubscribe 함수 제거됨 (신호 없음 → 재구독 금지!)

    async def _notify_subscription_failed(self, info: SubscriptionInfo) -> None:
        """구독 실패 알림 + 폴링 Fallback 시작"""
        purpose_name = self._get_purpose_name(info.purpose)

        self._logger.error(
            f"[Subscription] 구독 실패 → SUB_FAILED: seq={info.seq}, "
            f"purpose={purpose_name}, error={info.last_error}"
        )

        # 폴링 Fallback 시작 (Auto-Universe만)
        if info.purpose == SubscriptionPurpose.AUTO_UNIVERSE and not self._polling_fallback_enabled:
            self._logger.warning(
                f"[Subscription] 폴링 Fallback 모드 활성화: seq={info.seq}"
            )
            await self._start_polling_fallback(info)

            # 알림 (쿨다운 적용)
            await self._send_alert_with_cooldown(
                alert_key=f"sub_failed_{info.seq}",
                message=(
                    f"[경고] 조건검색 실시간 구독 실패\n"
                    f"조건식: #{info.seq} ({purpose_name})\n"
                    f"에러: {info.last_error}\n\n"
                    f"[대응]\n"
                    f"- 폴링 모드 전환 (30초 주기)\n"
                    f"- 추가 실패 시 회로 차단"
                )
            )
        else:
            await self._send_alert_with_cooldown(
                alert_key=f"sub_failed_{info.seq}",
                message=(
                    f"[경고] 조건검색 구독 실패\n"
                    f"조건식: #{info.seq} ({purpose_name})\n"
                    f"에러: {info.last_error}\n\n"
                    f"조치:\n"
                    f"- HTS 조건식 확인 필요\n"
                    f"- /substatus로 상태 확인"
                )
            )

    # =========================================
    # 폴링 Fallback 메서드
    # =========================================

    async def _start_polling_fallback(self, info: SubscriptionInfo) -> None:
        """
        폴링 Fallback 모드 시작

        실시간 조건검색 구독이 실패하면 30초마다 일회성 조건검색을 수행하여
        신규 종목을 탐지합니다.
        """
        if self._polling_fallback_enabled:
            self._logger.debug("[Subscription] 폴링 이미 활성화됨")
            return

        self._polling_fallback_enabled = True
        self._polling_info = info
        self._last_polling_stocks.clear()

        self._polling_task = asyncio.create_task(self._polling_loop())
        self._logger.info(
            f"[Subscription] 폴링 Fallback 시작: seq={info.seq}, 주기={self.POLLING_INTERVAL}초"
        )

    async def _polling_loop(self) -> None:
        """
        폴링 루프 (실시간 재시도 제거!)

        핵심 원칙:
        - 폴링만 수행 (30초마다 일회성 조건검색)
        - 실시간 구독 재시도 안함 (복구는 헬스체크에서만)
        - 종목 포착은 계속 수행
        """
        while self._polling_fallback_enabled and self._polling_info:
            try:
                # 일회성 조건검색
                stocks = await self._ws.poll_condition_search(
                    seq=self._polling_info.seq,
                    exchange="K"
                )

                if stocks is not None:
                    # 성공 - 신규 종목 탐지
                    current_stocks = set(stocks)
                    new_stocks = current_stocks - self._last_polling_stocks

                    if new_stocks:
                        self._logger.info(
                            f"[Polling] 신규 종목 {len(new_stocks)}개: "
                            f"{list(new_stocks)[:5]}{'...' if len(new_stocks) > 5 else ''}"
                        )

                        # 콜백 호출 (WATCHLIST 등록)
                        for stock_code in new_stocks:
                            try:
                                if self.on_polling_signal:
                                    await self.on_polling_signal(stock_code)
                            except Exception as e:
                                self._logger.error(
                                    f"[Polling] 콜백 에러: {stock_code}, {e}"
                                )

                    self._last_polling_stocks = current_stocks
                else:
                    # 폴링도 실패 (서버 완전 장애)
                    self._logger.warning(
                        "[Polling] 조건검색 실패 - 서버 장애 추정"
                    )

                # ❌ 실시간 재시도 제거! (복구는 헬스체크의 _attempt_recovery에서만)
                await asyncio.sleep(self.POLLING_INTERVAL)

            except asyncio.CancelledError:
                self._logger.info("[Polling] 루프 취소됨")
                break
            except Exception as e:
                self._logger.error(f"[Polling] 루프 에러: {e}")
                await asyncio.sleep(self.POLLING_INTERVAL)

    async def _stop_polling_fallback(self) -> None:
        """폴링 Fallback 모드 중지"""
        if not self._polling_fallback_enabled:
            return

        self._polling_fallback_enabled = False

        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None

        self._last_polling_stocks.clear()
        self._polling_info = None

        self._logger.info("[Subscription] 폴링 Fallback 중지")

    @property
    def is_polling_mode(self) -> bool:
        """폴링 모드 활성화 여부"""
        return self._polling_fallback_enabled

    def _get_purpose_name(self, purpose: SubscriptionPurpose) -> str:
        """목적 한글명"""
        return "ATR 알림" if purpose == SubscriptionPurpose.ATR_ALERT else "Auto-Universe"

    def start_health_check(self) -> None:
        """헬스체크 시작"""
        if self._health_check_task is None:
            self._running = True
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            self._logger.info("[Subscription] 헬스체크 시작")

    def stop_health_check(self) -> None:
        """헬스체크 중지"""
        self._running = False
        if self._health_check_task:
            self._health_check_task.cancel()
            self._health_check_task = None
            self._logger.info("[Subscription] 헬스체크 중지")

    def get_status(self) -> Dict[str, SubscriptionInfo]:
        """현재 구독 상태 조회"""
        return self._subscriptions.copy()

    def get_status_text(self) -> str:
        """텔레그램용 상태 텍스트"""
        if not self._subscriptions:
            return "등록된 구독 없음"

        lines = ["조건검색 구독 상태", "-" * 20]

        # 폴링 모드 표시
        if self._polling_fallback_enabled:
            lines.append("[폴링 모드 활성화]")
            lines.append(f"  감시 종목: {len(self._last_polling_stocks)}개")
            lines.append("")

        for seq, info in self._subscriptions.items():
            purpose_name = self._get_purpose_name(info.purpose)
            state_text = {
                SubscriptionState.IDLE: "대기",
                SubscriptionState.SUBSCRIBING: "구독 중...",
                SubscriptionState.SUBSCRIBED: "활성",
                SubscriptionState.VERIFYING: "검증 중...",
                SubscriptionState.SUB_FAILED: "실패 (폴링중)" if self._polling_fallback_enabled else "실패",
                SubscriptionState.SUB_SUSPENDED: "회로차단 (30분)",
            }.get(info.state, "알 수 없음")

            last_signal = "없음"
            if info.last_signal_time:
                elapsed = (datetime.now() - info.last_signal_time).total_seconds() / 60
                last_signal = f"{int(elapsed)}분 전"

            lines.append(f"#{seq} {purpose_name}")
            lines.append(f"  상태: {state_text}")
            lines.append(f"  마지막 신호: {last_signal}")
            if info.subscribed_at:
                lines.append(f"  구독 시간: {info.subscribed_at.strftime('%H:%M:%S')}")
            lines.append("")

        return "\n".join(lines)

    async def clear_all(self) -> None:
        """모든 구독 정보 초기화 (장 종료 시) - 폴링 루프도 중지"""
        # 폴링 Fallback 중지 (stop 후에도 재구독 시도 방지)
        await self._stop_polling_fallback()

        # 구독 정보 클리어
        self._subscriptions.clear()
        self._logger.info("[Subscription] 모든 구독 정보 초기화")

    def register_existing(self, seq: str, purpose: SubscriptionPurpose) -> None:
        """
        이미 구독된 조건검색을 등록 (재연결 복구용)

        초기 구독은 validation이 필요하므로 기존 로직(_start_condition_search_with_validation)을 사용하고,
        성공 시 이 메서드로 SubscriptionManager에 등록하여 재연결 시 자동 복구되도록 합니다.

        Args:
            seq: 조건식 번호
            purpose: 구독 목적
        """
        if seq in self._subscriptions:
            return

        info = SubscriptionInfo(
            seq=seq,
            purpose=purpose,
            state=SubscriptionState.SUBSCRIBED,
            subscribed_at=datetime.now(),
        )
        self._subscriptions[seq] = info

        purpose_name = self._get_purpose_name(purpose)
        self._logger.info(
            f"[Subscription] 기존 구독 등록: seq={seq}, purpose={purpose_name}"
        )
