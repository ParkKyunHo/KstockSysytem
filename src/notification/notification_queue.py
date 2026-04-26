"""
알림 큐 관리 모듈 (V7.0)

신호 발생 시 텔레그램 알림을 관리하는 큐 시스템.
지수 백오프 재시도, 중복 알림 방지, 실패 로깅을 제공합니다.

Features:
- FIFO 큐 기반 알림 처리
- 지수 백오프 재시도 (최대 3회)
- 종목별 알림 쿨다운 (중복 방지)
- 실패 알림 로깅
"""

import asyncio
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Callable, Awaitable
from pathlib import Path

from src.utils.logger import get_logger


# 기본 설정
MAX_RETRIES = 3                    # 최대 재시도 횟수
INITIAL_BACKOFF_SECONDS = 1.0      # 초기 백오프 시간 (초)
BACKOFF_MULTIPLIER = 2.0           # 백오프 배수
DEFAULT_COOLDOWN_SECONDS = 300     # 기본 알림 쿨다운 (5분)
MAX_QUEUE_SIZE = 100               # 최대 큐 크기
FAILED_LOG_FILE = Path("logs/notification_failures.log")
BACKUP_LOG_FILE = Path("logs/notification_backup.log")
OVERFLOW_LOG_FILE = Path("logs/notification_overflow.log")
OVERFLOW_ALERT_INTERVAL_SECONDS = 300  # 5분


@dataclass
class NotificationItem:
    """
    알림 큐 아이템

    Attributes:
        message: 알림 메시지 내용
        stock_code: 종목코드 (쿨다운용)
        stock_name: 종목명
        created_at: 생성 시간
        retry_count: 재시도 횟수
        priority: 우선순위 (낮을수록 높음)
        metadata: 추가 정보
    """
    message: str
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    retry_count: int = 0
    priority: int = 1  # 1=일반, 0=긴급
    metadata: dict = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        """생성 후 경과 시간 (초)"""
        return (datetime.now() - self.created_at).total_seconds()


class NotificationQueue:
    """
    알림 큐 관리자

    텔레그램 알림의 안정적인 전송을 위한 큐 시스템.
    실패 시 지수 백오프로 재시도하고, 종목별 쿨다운으로 중복 방지.

    Features:
    - FIFO 큐 처리
    - 지수 백오프 재시도 (1초 → 2초 → 4초)
    - 종목별 알림 쿨다운
    - 실패 기록 및 로깅
    - 비동기 백그라운드 처리

    Usage:
        queue = NotificationQueue(send_func=telegram_bot.send_message)
        queue.enqueue("신호 발생: 삼성전자", stock_code="005930")
        await queue.start_processing()
    """

    def __init__(
        self,
        send_func: Optional[Callable[[str], Awaitable[bool]]] = None,
        max_retries: int = MAX_RETRIES,
        cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    ):
        """
        NotificationQueue 초기화

        Args:
            send_func: 메시지 전송 함수 (async def func(msg) -> bool)
            max_retries: 최대 재시도 횟수
            cooldown_seconds: 종목별 알림 쿨다운 (초)
        """
        self._queue: deque[NotificationItem] = deque(maxlen=MAX_QUEUE_SIZE)
        # [C-002] 큐 접근 동기화: threading.RLock과 asyncio.Lock 모두 사용
        # - threading.RLock: sync 메서드 (enqueue 등)에서 사용
        # - asyncio.Lock: async 메서드 (process_next 등)에서 사용
        # 주의: 두 Lock이 함께 deque를 보호하므로, async 메서드에서는 threading.Lock도 획득해야 함
        self._lock = threading.RLock()  # sync 메서드용
        self._async_lock = asyncio.Lock()  # async 메서드용 (이벤트 루프 블로킹 방지)
        self._logger = get_logger(__name__)

        self._send_func = send_func
        self._max_retries = max_retries
        self._cooldown_seconds = cooldown_seconds

        # 종목별 마지막 알림 시간 (쿨다운 관리)
        self._last_notification: Dict[str, datetime] = {}

        # 처리 태스크
        self._processing = False
        self._process_task: Optional[asyncio.Task] = None

        # 실패 기록
        self._failed_count = 0
        self._success_count = 0

        # P0: 알림 손실 추적
        self._dropped_count = 0
        self._cooldown_skipped_count = 0

        # F-1: send_func None 카운터
        self._send_func_none_count: int = 0

        # F-5: 오버플로우 알림 rate-limit
        self._last_overflow_alert_time: Optional[datetime] = None

        # T-4: 성공/실패 추적
        self._last_success_time: Optional[datetime] = None
        self._consecutive_failures: int = 0

        # 로그 디렉토리 생성
        FAILED_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def set_send_func(self, send_func: Callable[[str], Awaitable[bool]]) -> None:
        """
        메시지 전송 함수 설정

        Args:
            send_func: async def send_func(message: str) -> bool
        """
        self._send_func = send_func

    def enqueue(
        self,
        message: str,
        stock_code: Optional[str] = None,
        stock_name: Optional[str] = None,
        priority: int = 1,
        force: bool = False,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        알림 큐에 추가

        Args:
            message: 알림 메시지
            stock_code: 종목코드 (쿨다운 체크용)
            stock_name: 종목명
            priority: 우선순위 (0=긴급, 1=일반)
            force: True시 쿨다운 무시
            metadata: 추가 정보

        Returns:
            True: 큐에 추가됨, False: 쿨다운 중 또는 큐 가득 참
        """
        with self._lock:
            # 쿨다운 체크 (종목코드가 있고 force가 아닐 때)
            if stock_code and not force:
                if not self._check_cooldown(stock_code):
                    self._cooldown_skipped_count += 1
                    self._logger.info(
                        f"[쿨다운] {stock_code} 신호 발생했으나 쿨다운 중 "
                        f"(총 {self._cooldown_skipped_count}건 스킵)",
                        stock_code=stock_code,
                    )
                    return False

            # 큐 크기 체크 (P0: 손실 알림 상세 기록)
            if len(self._queue) >= MAX_QUEUE_SIZE:
                removed = self._queue.popleft()
                self._dropped_count += 1
                self._logger.error(
                    f"[알림 손실] 큐 오버플로우로 알림 삭제 "
                    f"({removed.stock_code or 'SYSTEM'}): "
                    f"{removed.message[:80]}... "
                    f"(총 {self._dropped_count}건 손실)",
                    stock_code=removed.stock_code,
                )
                # F-5: 오버플로우 로그 기록
                self._log_overflow(removed)
                # F-5: rate-limited 직접 알림 (5분 간격)
                self._try_overflow_alert(removed)

            # 아이템 생성 및 추가
            item = NotificationItem(
                message=message,
                stock_code=stock_code,
                stock_name=stock_name,
                priority=priority,
                metadata=metadata or {},
            )

            # 우선순위에 따라 삽입 (priority=0은 앞에)
            if priority == 0:
                self._queue.appendleft(item)
            else:
                self._queue.append(item)

            # 마지막 알림 시간 기록
            if stock_code:
                self._last_notification[stock_code] = datetime.now()

            self._logger.info(
                f"알림 큐 추가: {stock_code or 'system'}",
                queue_size=len(self._queue),
                priority=priority,
            )

            return True

    def _check_cooldown(self, stock_code: str) -> bool:
        """
        쿨다운 경과 여부 확인

        Args:
            stock_code: 종목코드

        Returns:
            True: 알림 가능, False: 쿨다운 중
        """
        last_time = self._last_notification.get(stock_code)
        if last_time is None:
            return True

        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed >= self._cooldown_seconds

    def pending_count(self) -> int:
        """대기 중인 알림 수"""
        with self._lock:
            return len(self._queue)

    def is_empty(self) -> bool:
        """큐가 비어있는지 확인"""
        with self._lock:
            return len(self._queue) == 0

    async def process_next(self) -> Optional[bool]:
        """
        다음 알림 처리

        Returns:
            True: 전송 성공, False: 전송 실패, None: 큐 비어있음
        """
        # [V7.1-Fix3] 큐 상태 확인 (1분마다 로그)
        queue_size = len(self._queue)
        if queue_size > 0:
            self._logger.info(f"[알림 큐] 처리 시작: 대기 {queue_size}개")

        if self._send_func is None:
            self._send_func_none_count += 1
            self._logger.critical(
                f"전송 함수가 설정되지 않음 (연속 {self._send_func_none_count}회)"
            )
            if self._send_func_none_count >= 10:
                self._backup_pending_queue()
            return None

        item: Optional[NotificationItem] = None

        # [C-002] 양쪽 Lock 모두 획득하여 sync/async 동시 접근 방지
        # async lock 먼저 획득 후 threading lock 획득
        async with self._async_lock:
            with self._lock:
                if not self._queue:
                    return None
                item = self._queue.popleft()
                # [V7.1-Fix3] 디버깅: 큐에서 아이템 추출
                self._logger.info(
                    f"[알림 처리] 큐에서 추출: {item.stock_code or 'SYSTEM'}",
                    queue_remaining=len(self._queue),
                )

        if item is None:
            return None

        # 전송 시도
        success = await self._send_with_retry(item)

        if success:
            self._success_count += 1
        else:
            self._failed_count += 1
            self._log_failure(item)

        return success

    async def _send_with_retry(self, item: NotificationItem) -> bool:
        """
        지수 백오프로 재시도

        Args:
            item: 알림 아이템

        Returns:
            True: 성공, False: 최종 실패
        """
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(self._max_retries + 1):
            try:
                # [V7.1-Fix3] 디버깅: 전송 시도 로그
                self._logger.info(
                    f"[알림 발송] 시도 {attempt + 1}: {item.stock_code or 'SYSTEM'}",
                )
                success = await self._send_func(item.message)
                # [V7.1-Fix3] 디버깅: 전송 결과 로그
                self._logger.info(
                    f"[알림 발송] 결과: {item.stock_code or 'SYSTEM'} → {'성공' if success else '실패'}",
                )
                if success:
                    self._last_success_time = datetime.now()
                    self._consecutive_failures = 0
                    if attempt > 0:
                        self._logger.info(
                            f"알림 재시도 성공 (시도 {attempt + 1})",
                            stock_code=item.stock_code,
                        )
                    return True

            except Exception as e:
                self._logger.warning(
                    f"알림 전송 실패 (시도 {attempt + 1}/{self._max_retries + 1})",
                    error=str(e),
                    stock_code=item.stock_code,
                )

            # 마지막 시도가 아니면 백오프 대기
            if attempt < self._max_retries:
                self._logger.debug(f"백오프 대기: {backoff}초")
                await asyncio.sleep(backoff)
                backoff *= BACKOFF_MULTIPLIER

        self._consecutive_failures += 1
        self._logger.error(
            f"알림 전송 최종 실패 ({self._max_retries + 1}회 시도, "
            f"연속 실패 {self._consecutive_failures}회)",
            stock_code=item.stock_code,
        )
        return False

    def _log_failure(self, item: NotificationItem) -> None:
        """
        실패 기록 저장

        Args:
            item: 실패한 알림 아이템
        """
        try:
            with open(FAILED_LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                safe_message = item.message.replace("\n", " | ")[:300]
                f.write(
                    f"{timestamp} | {item.stock_code or 'SYSTEM'} | "
                    f"{item.stock_name or ''} | {safe_message}\n"
                )
        except Exception as e:
            self._logger.warning(f"실패 기록 저장 오류: {e}")

    def _log_overflow(self, removed: NotificationItem) -> None:
        """오버플로우로 삭제된 알림을 로그 파일에 기록"""
        try:
            OVERFLOW_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(OVERFLOW_LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                safe_message = removed.message.replace("\n", " | ")[:300]
                f.write(
                    f"{timestamp} | DROPPED#{self._dropped_count} | "
                    f"{removed.stock_code or 'SYSTEM'} | "
                    f"{removed.stock_name or ''} | {safe_message}\n"
                )
        except Exception as e:
            self._logger.warning(f"오버플로우 로그 저장 오류: {e}")

    def _try_overflow_alert(self, removed: NotificationItem) -> None:
        """오버플로우 발생 시 rate-limited 직접 알림 전송 (5분 간격)"""
        now = datetime.now()
        if self._last_overflow_alert_time is not None:
            elapsed = (now - self._last_overflow_alert_time).total_seconds()
            if elapsed < OVERFLOW_ALERT_INTERVAL_SECONDS:
                return

        if self._send_func is None:
            return

        self._last_overflow_alert_time = now
        alert_msg = (
            f"[ALERT] 알림 큐 오버플로우 발생\n"
            f"삭제된 알림: {removed.stock_code or 'SYSTEM'}\n"
            f"총 손실: {self._dropped_count}건\n"
            f"현재 큐: {len(self._queue)}/{MAX_QUEUE_SIZE}"
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._send_func(alert_msg))
            else:
                loop.run_until_complete(self._send_func(alert_msg))
        except RuntimeError:
            self._logger.warning("오버플로우 알림 전송 실패: 이벤트 루프 없음")

    def _backup_pending_queue(self) -> None:
        """send_func None 상태에서 대기 큐를 백업 로그에 기록"""
        try:
            BACKUP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(BACKUP_LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"\n--- Backup at {timestamp} (send_func None x{self._send_func_none_count}) ---\n")
                with self._lock:
                    for idx, item in enumerate(self._queue):
                        safe_message = item.message.replace("\n", " | ")[:300]
                        f.write(
                            f"  [{idx}] {item.stock_code or 'SYSTEM'} | "
                            f"{item.stock_name or ''} | {safe_message}\n"
                        )
            self._logger.critical(
                f"대기 큐 {len(self._queue)}건을 {BACKUP_LOG_FILE}에 백업 완료"
            )
        except Exception as e:
            self._logger.warning(f"큐 백업 저장 오류: {e}")

    async def start_processing(self, interval: float = 0.5) -> None:
        """
        백그라운드 큐 처리 시작

        Args:
            interval: 처리 간격 (초)
        """
        if self._processing:
            return

        self._processing = True
        self._process_task = asyncio.create_task(self._process_loop(interval))
        self._logger.info("알림 큐 처리 시작")

    async def stop_processing(self) -> None:
        """백그라운드 큐 처리 중지"""
        self._processing = False

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None

        self._logger.info("알림 큐 처리 중지")

    async def _process_loop(self, interval: float) -> None:
        """큐 처리 루프"""
        while self._processing:
            try:
                if not self.is_empty():
                    await self.process_next()
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"큐 처리 루프 에러: {e}")
                await asyncio.sleep(interval)

    async def flush(self) -> int:
        """
        큐의 모든 알림 즉시 처리

        Returns:
            처리된 알림 수
        """
        processed = 0
        while not self.is_empty():
            result = await self.process_next()
            if result is not None:
                processed += 1
        return processed

    def clear(self) -> int:
        """
        큐 비우기 (미전송 알림 삭제)

        Returns:
            삭제된 알림 수
        """
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def clear_cooldowns(self) -> int:
        """
        쿨다운 기록 초기화

        Returns:
            초기화된 종목 수
        """
        with self._lock:
            count = len(self._last_notification)
            self._last_notification.clear()
            return count

    def get_stats(self) -> dict:
        """
        통계 조회

        Returns:
            통계 딕셔너리
        """
        with self._lock:
            return {
                "pending": len(self._queue),
                "success_count": self._success_count,
                "failed_count": self._failed_count,
                "cooldown_stocks": len(self._last_notification),
                "is_processing": self._processing,
                # P0: 손실/스킵 추적
                "dropped_count": self._dropped_count,
                "cooldown_skipped_count": self._cooldown_skipped_count,
                # T-4: 강화 통계
                "last_success_time": self._last_success_time.isoformat() if self._last_success_time else None,
                "consecutive_failures": self._consecutive_failures,
                "send_func_none_count": self._send_func_none_count,
            }

    def get_cooldown_remaining(self, stock_code: str) -> float:
        """
        종목의 쿨다운 남은 시간 (초)

        Args:
            stock_code: 종목코드

        Returns:
            남은 시간 (초), 쿨다운 아니면 0
        """
        with self._lock:
            last_time = self._last_notification.get(stock_code)
            if last_time is None:
                return 0

            elapsed = (datetime.now() - last_time).total_seconds()
            remaining = self._cooldown_seconds - elapsed
            return max(0, remaining)


# 싱글톤 인스턴스
_notification_queue: Optional[NotificationQueue] = None


def get_notification_queue() -> NotificationQueue:
    """싱글톤 NotificationQueue 인스턴스 반환"""
    global _notification_queue
    if _notification_queue is None:
        _notification_queue = NotificationQueue()
    return _notification_queue
