"""
신호 처리기 (Phase 3 리팩토링)

TradingEngine의 신호 처리 로직을 분리하여 단일 책임 원칙을 준수합니다.

주요 기능:
- 신호 큐 관리 (쿨다운 중 신호 저장)
- SIGNAL_ALERT 모드 알림 전송
- 신호 유효성 검증
- 중복 신호 필터링

CLAUDE.md 불변 조건:
- 고정 손절 -4%는 별도 모듈에서 처리 (ExitManager)
- TradingMode별 분기 로직 유지

Usage:
    from src.core.signal_processor import SignalProcessor

    processor = SignalProcessor(
        telegram=telegram_bot,
        risk_settings=risk_settings,
    )

    # 신호 처리
    await processor.process_signal(signal, callbacks)

    # 큐 처리
    await processor.process_queue(callbacks)
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Awaitable, List
from enum import Enum
import asyncio

from src.core.signal_detector import Signal, StrategyType
from src.utils.logger import get_logger


class SignalProcessResult(str, Enum):
    """신호 처리 결과"""
    EXECUTED = "EXECUTED"              # 매수 실행됨
    ALERT_SENT = "ALERT_SENT"          # 알림 전송됨
    QUEUED = "QUEUED"                  # 큐에 저장됨
    BLOCKED = "BLOCKED"                # 차단됨
    SKIPPED = "SKIPPED"                # 스킵됨
    ERROR = "ERROR"                    # 오류 발생


@dataclass
class QueuedSignal:
    """큐에 저장된 신호"""
    stock_code: str
    stock_name: str
    signal: Signal
    price: int
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def age_seconds(self) -> float:
        """신호 대기 시간 (초)"""
        return (datetime.now() - self.timestamp).total_seconds()


@dataclass
class SignalProcessCallbacks:
    """
    신호 처리 콜백 인터페이스

    SignalProcessor가 TradingEngine에 의존하지 않도록
    필요한 기능을 콜백으로 전달받습니다.

    Attributes:
        can_execute_trade: 매매 실행 가능 여부 체크 (C-009: async로 변경)
        has_position: 포지션 보유 여부 체크
        is_in_cooldown: 쿨다운 상태 체크
        get_cooldown_remaining: 남은 쿨다운 시간
        can_enter_risk: 리스크 진입 가능 여부 체크
        execute_buy: 매수 실행
        send_telegram: 텔레그램 전송
        on_risk_block: 리스크 차단 시 콜백 (알림 전송 등)
    """
    # C-009 FIX: async 콜백으로 변경 (VI Lock이 asyncio.Lock으로 변경됨)
    can_execute_trade: Optional[Callable[[str], Awaitable[bool]]] = None
    has_position: Optional[Callable[[str], bool]] = None
    is_in_cooldown: Optional[Callable[[], bool]] = None
    get_cooldown_remaining: Optional[Callable[[], float]] = None
    can_enter_risk: Optional[Callable[[str], tuple]] = None
    execute_buy: Optional[Callable[[Signal], Awaitable[None]]] = None
    send_telegram: Optional[Callable[[str], Awaitable[None]]] = None
    on_risk_block: Optional[Callable[[str, Any, str], Awaitable[None]]] = None


class SignalProcessor:
    """
    신호 처리기

    신호 큐 관리와 SIGNAL_ALERT 모드 알림을 담당합니다.
    TradingEngine에서 신호 처리 관련 로직을 분리합니다.

    Features:
    - 신호 큐 관리 (쿨다운 중 신호 저장)
    - SIGNAL_ALERT 모드 알림 전송
    - 중복 알림 방지 (쿨다운)
    - 신호 유효성 검증

    Example:
        processor = SignalProcessor(telegram=bot, risk_settings=settings)

        # 신호 처리
        result = await processor.process_signal(signal, callbacks)

        # 큐 처리 (쿨다운 해제 후)
        await processor.process_queue(callbacks)
    """

    def __init__(
        self,
        telegram=None,
        risk_settings=None,
        signal_queue_max_age_seconds: int = 30,
        signal_alert_cooldown_seconds: int = 300,
    ):
        """
        Args:
            telegram: TelegramBot 인스턴스
            risk_settings: RiskSettings 인스턴스
            signal_queue_max_age_seconds: 큐 신호 최대 유효 시간 (기본 30초)
            signal_alert_cooldown_seconds: SIGNAL_ALERT 중복 방지 쿨다운 (기본 300초)
        """
        self._logger = get_logger(__name__)
        self._telegram = telegram
        self._risk_settings = risk_settings

        # 신호 큐
        self._signal_queue: Dict[str, QueuedSignal] = {}
        self._signal_queue_lock = asyncio.Lock()
        self._signal_queue_max_age_seconds = signal_queue_max_age_seconds

        # SIGNAL_ALERT 중복 방지
        self._signal_alert_cooldown: Dict[str, datetime] = {}
        self._signal_alert_cooldown_seconds = signal_alert_cooldown_seconds

        # 통계
        self._stats = {
            "signals_processed": 0,
            "signals_queued": 0,
            "signals_from_queue": 0,
            "signals_expired": 0,
            "signal_alerts_sent": 0,
            "signals_blocked": 0,
        }

    # =========================================
    # 신호 처리
    # =========================================

    async def process_signal(
        self,
        signal: Signal,
        callbacks: SignalProcessCallbacks,
        trading_mode: str = "AUTO_TRADE",
    ) -> SignalProcessResult:
        """
        신호 처리

        Args:
            signal: 신호 객체
            callbacks: 콜백 인터페이스
            trading_mode: 매매 모드

        Returns:
            처리 결과
        """
        stock_code = signal.stock_code
        self._stats["signals_processed"] += 1

        self._logger.info(
            f"[SignalProcessor] 신호 처리 시작: {stock_code} {signal.stock_name} "
            f"전략={signal.strategy.value} 가격={signal.price:,}원"
        )

        # 1. 매매 실행 가능 여부 체크
        # C-009 FIX: await 추가 (can_execute_trade가 async로 변경됨)
        if callbacks.can_execute_trade and not await callbacks.can_execute_trade(stock_code):
            self._logger.warning(f"[SignalProcessor] 매매 불가 - 차단: {stock_code}")
            self._stats["signals_blocked"] += 1
            return SignalProcessResult.BLOCKED

        # 2. SIGNAL_ALERT 모드 - 알림만 전송
        if trading_mode == "SIGNAL_ALERT":
            # 이미 보유 중이면 스킵
            if callbacks.has_position and callbacks.has_position(stock_code):
                self._logger.debug(f"[SignalProcessor] 이미 보유 중: {stock_code}")
                return SignalProcessResult.SKIPPED

            # 알림 전송
            await self._send_signal_alert(signal, callbacks)
            return SignalProcessResult.ALERT_SENT

        # 3. 쿨다운 체크
        if callbacks.is_in_cooldown and callbacks.is_in_cooldown():
            remaining = callbacks.get_cooldown_remaining() if callbacks.get_cooldown_remaining else 0
            await self._enqueue_signal(stock_code, signal.stock_name, signal, signal.price)
            self._logger.info(
                f"[SignalProcessor] 신호 큐 저장: {stock_code} - "
                f"쿨다운 중 ({remaining:.0f}초 남음), 큐 크기: {len(self._signal_queue)}"
            )
            return SignalProcessResult.QUEUED

        # 4. 리스크 체크
        if callbacks.can_enter_risk:
            can_enter, block_reason, message = callbacks.can_enter_risk(stock_code)
            if not can_enter:
                self._stats["signals_blocked"] += 1
                self._logger.warning(
                    f"[SignalProcessor] 진입 차단: {stock_code} - {message}"
                )
                # 리스크 차단 콜백 호출 (MAX_POSITIONS, DAILY_LOSS_LIMIT 등 알림용)
                if callbacks.on_risk_block:
                    await callbacks.on_risk_block(stock_code, block_reason, message)
                return SignalProcessResult.BLOCKED

        # 5. 매수 실행
        if callbacks.execute_buy:
            await callbacks.execute_buy(signal)
            return SignalProcessResult.EXECUTED

        return SignalProcessResult.ERROR

    # =========================================
    # SIGNAL_ALERT 알림
    # =========================================

    async def _send_signal_alert(
        self,
        signal: Signal,
        callbacks: SignalProcessCallbacks,
    ) -> None:
        """
        SIGNAL_ALERT 모드 매수 추천 알림

        같은 종목에 대해 쿨다운 적용으로 중복 알림을 방지합니다.

        Args:
            signal: 신호 객체
            callbacks: 콜백 인터페이스
        """
        stock_code = signal.stock_code

        # 중복 알림 방지 (쿨다운 체크)
        if stock_code in self._signal_alert_cooldown:
            last_alert = self._signal_alert_cooldown[stock_code]
            elapsed = (datetime.now() - last_alert).total_seconds()
            if elapsed < self._signal_alert_cooldown_seconds:
                self._logger.debug(
                    f"[SignalProcessor] 중복 알림 방지: {stock_code} "
                    f"({elapsed:.0f}초 전 알림, 쿨다운 {self._signal_alert_cooldown_seconds}초)"
                )
                return

        # 알림 시간 기록
        self._signal_alert_cooldown[stock_code] = datetime.now()

        # 알림 텍스트 생성
        try:
            from src.notification.templates import format_signal_alert_notification
            alert_text = format_signal_alert_notification(
                stock_code=stock_code,
                stock_name=signal.stock_name,
                current_price=signal.price,
                signal_metadata=signal.metadata or {},
            )
        except ImportError:
            alert_text = (
                f"[SIGNAL_ALERT] 매수 추천\n\n"
                f"{signal.stock_name}({stock_code})\n"
                f"가격: {signal.price:,}원\n"
                f"전략: {signal.strategy.value}"
            )

        # 텔레그램 전송
        if callbacks.send_telegram:
            await callbacks.send_telegram(alert_text)
            self._logger.info(
                f"[SignalProcessor] 매수 추천 알림 전송: {signal.stock_name}({stock_code}) "
                f"@ {signal.price:,}원"
            )
            self._stats["signal_alerts_sent"] += 1
        elif self._telegram:
            await self._telegram.send_message(alert_text)
            self._logger.info(
                f"[SignalProcessor] 매수 추천 알림 전송: {signal.stock_name}({stock_code}) "
                f"@ {signal.price:,}원"
            )
            self._stats["signal_alerts_sent"] += 1
        else:
            self._logger.critical(
                f"[SignalProcessor] 텔레그램 미초기화 - 알림 전송 불가: "
                f"{signal.stock_name}({stock_code}) @ {signal.price:,}원"
            )
            self._log_missed_signal_from_signal(signal)

    # =========================================
    # 신호 큐 관리
    # =========================================

    async def _enqueue_signal(
        self,
        stock_code: str,
        stock_name: str,
        signal: Signal,
        price: int,
    ) -> None:
        """
        쿨다운 중 신호를 큐에 저장

        - 같은 종목 신호가 이미 있으면 최신 신호로 교체
        - 종목당 1개만 저장 (중복 방지)
        - Lock으로 동시성 보호

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            signal: 신호 객체
            price: 현재가
        """
        async with self._signal_queue_lock:
            # 이미 같은 종목 신호가 있으면 최신으로 교체
            if stock_code in self._signal_queue:
                old_ts = self._signal_queue[stock_code].timestamp
                self._logger.debug(
                    f"[SignalProcessor] {stock_code} 기존 신호 교체: {old_ts} -> {datetime.now()}"
                )

            self._signal_queue[stock_code] = QueuedSignal(
                stock_code=stock_code,
                stock_name=stock_name,
                signal=signal,
                price=price,
                timestamp=datetime.now(),
            )
            self._stats["signals_queued"] += 1

    async def process_queue(
        self,
        callbacks: SignalProcessCallbacks,
    ) -> Optional[str]:
        """
        큐에 저장된 신호 처리

        쿨다운 해제 후 호출되어 대기 중인 신호를 순차 처리합니다.

        처리 규칙:
        1. 오래된 신호 폐기
        2. 이미 보유 중인 종목 신호 폐기
        3. 유효한 신호만 처리 (한 번에 1개만)
        4. Lock으로 동시성 보호

        Args:
            callbacks: 콜백 인터페이스

        Returns:
            처리된 종목 코드 또는 None
        """
        now = datetime.now()
        expired_list = []
        skipped_list = []
        signal_to_process = None

        # Lock 획득하여 큐 상태 확인 및 스냅샷 생성
        async with self._signal_queue_lock:
            if not self._signal_queue:
                return None

            # 큐 복사 후 처리 (순회 중 변경 방지)
            queue_snapshot = list(self._signal_queue.items())

            self._logger.info(
                f"[SignalProcessor] 큐 처리 시작: 대기 신호 {len(queue_snapshot)}개"
            )

            # 쿨다운 상태 미리 확인
            in_cooldown = callbacks.is_in_cooldown and callbacks.is_in_cooldown()

            for stock_code, queued in queue_snapshot:
                # 1. 신호 유효 시간 체크
                age = queued.age_seconds()
                if age > self._signal_queue_max_age_seconds:
                    expired_list.append((stock_code, age))
                    # T-3: Alert for confirmed signals that expired
                    conditions_met = 0
                    if queued.signal.metadata:
                        conditions_met = queued.signal.metadata.get('conditions_met', 0)
                    if conditions_met == 5:
                        self._logger.warning(
                            f"[SignalProcessor] 확정 신호 큐 만료: {stock_code} "
                            f"{queued.stock_name} - {age:.1f}초 초과"
                        )
                        self._log_missed_signal(queued)
                    del self._signal_queue[stock_code]
                    self._stats["signals_expired"] += 1
                    continue

                # 2. 이미 보유 중인지 체크
                if callbacks.has_position and callbacks.has_position(stock_code):
                    skipped_list.append(stock_code)
                    del self._signal_queue[stock_code]
                    continue

                # 3. 쿨다운 중이면 유효한 신호 처리 스킵
                if in_cooldown:
                    continue

                # 4. 유효한 신호 찾음 - 큐에서 제거하고 처리 대상으로 저장
                del self._signal_queue[stock_code]
                signal_to_process = queued
                break  # 1개만 처리

        # Lock 해제 후 실제 신호 처리
        if signal_to_process:
            stock_code = signal_to_process.stock_code
            age = signal_to_process.age_seconds()
            self._logger.info(
                f"[SignalProcessor] 큐 신호 처리: {stock_code} "
                f"{signal_to_process.stock_name} - 대기 시간: {age:.1f}초"
            )

            # 리스크 체크
            if callbacks.can_enter_risk:
                can_enter, block_reason, message = callbacks.can_enter_risk(stock_code)
                if not can_enter:
                    self._logger.warning(
                        f"[SignalProcessor] 큐 신호 진입 차단: {stock_code} - {message}"
                    )
                    return None

            # 매수 실행
            if callbacks.execute_buy:
                await callbacks.execute_buy(signal_to_process.signal)
                self._stats["signals_from_queue"] += 1
                return stock_code

        # 로깅
        if expired_list:
            self._logger.info(
                f"[SignalProcessor] 만료 폐기: "
                f"{[(code, f'{age:.1f}초') for code, age in expired_list]}"
            )
        if skipped_list:
            self._logger.info(f"[SignalProcessor] 보유 중 스킵: {skipped_list}")

        return None

    # =========================================
    # 미전송 신호 기록
    # =========================================

    def _log_missed_signal(self, queued: 'QueuedSignal') -> None:
        """만료된 확정 신호 기록"""
        try:
            log_file = Path("logs/missed_signal_alerts.log")
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(
                    f"{timestamp} | EXPIRED | {queued.stock_code} | "
                    f"{queued.stock_name} | age={queued.age_seconds():.1f}s | "
                    f"price={queued.price:,}\n"
                )
        except Exception as e:
            self._logger.warning(f"missed signal log 기록 실패: {e}")

    def _log_missed_signal_from_signal(self, signal: Signal) -> None:
        """텔레그램 미초기화로 인한 미전송 신호 기록"""
        try:
            log_file = Path("logs/missed_signal_alerts.log")
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(
                    f"{timestamp} | NO_TELEGRAM | {signal.stock_code} | "
                    f"{signal.stock_name} | price={signal.price:,}\n"
                )
        except Exception as e:
            self._logger.warning(f"missed signal log 기록 실패: {e}")

    # =========================================
    # 유틸리티
    # =========================================

    def clear_alert_cooldown(self, stock_code: Optional[str] = None) -> None:
        """
        SIGNAL_ALERT 쿨다운 초기화

        Args:
            stock_code: 특정 종목 (None이면 전체)
        """
        if stock_code:
            self._signal_alert_cooldown.pop(stock_code, None)
        else:
            self._signal_alert_cooldown.clear()

    def get_queue_size(self) -> int:
        """큐 크기 반환"""
        return len(self._signal_queue)

    def get_stats(self) -> Dict[str, int]:
        """통계 반환"""
        return self._stats.copy()

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        return {
            "queue_size": len(self._signal_queue),
            "alert_cooldown_count": len(self._signal_alert_cooldown),
            "stats": self._stats.copy(),
            "max_queue_age_seconds": self._signal_queue_max_age_seconds,
            "alert_cooldown_seconds": self._signal_alert_cooldown_seconds,
        }

    def __str__(self) -> str:
        return (
            f"SignalProcessor(queue={len(self._signal_queue)}, "
            f"alerts={self._stats['signal_alerts_sent']})"
        )
