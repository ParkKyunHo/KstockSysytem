"""
V7 Purple-ReAbs 전략 어댑터

기존 V7 컴포넌트들(SignalPool, PurpleSignalDetector, DualPassDetector,
WatermarkManager, WaveHarvestExit 등)을 BaseStrategy 인터페이스로 래핑합니다.

TradingEngine의 V7 조건 분기를 제거하기 위한 어댑터 계층입니다.
기존 컴포넌트의 동작은 변경하지 않습니다.

CLAUDE.md 불변 조건:
- Score 가중치, PurpleOK 임계값, Zone 허용범위 수정 불가
- ATR 배수 단방향 축소 (6.0→4.5→4.0→3.5→2.5→2.0)
- 트레일링 스탑 상향 전용
- EMA adjust=False
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable, Awaitable
import asyncio
from datetime import datetime

from src.core.strategies.base_strategy import BaseStrategy
from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit
from src.core.signals.base_signal import BaseSignal
from src.core.v7_signal_coordinator import V7Callbacks
from src.core.missed_signal_tracker import SignalAttempt
from src.utils.logger import get_logger


@dataclass
class V7InfraCallbacks:
    """TradingEngine이 제공하는 인프라 콜백 (V7 컴포넌트 외부 의존성)"""
    get_candles: Callable
    is_candle_loaded: Callable
    promote_to_tier1: Callable
    send_telegram: Callable
    is_engine_running: Callable


class V7PurpleReAbsStrategy(BaseStrategy):
    """
    V7 Purple-ReAbs 전략 어댑터

    기존 V7 컴포넌트들을 래핑하여 BaseStrategy 인터페이스를 제공합니다.
    V7SignalCoordinator가 실질적인 신호 탐지 루프를 실행하며,
    이 어댑터는 TradingEngine과의 인터페이스 역할을 합니다.

    Usage:
        strategy = V7PurpleReAbsStrategy(
            signal_pool=signal_pool,
            signal_detector=signal_detector,
            dual_pass=dual_pass,
            watermark=watermark,
            exit_manager=exit_manager,
            notification_queue=notification_queue,
            missed_tracker=missed_tracker,
            signal_coordinator=signal_coordinator,
        )
    """

    def __init__(
        self,
        signal_pool,
        signal_detector,
        dual_pass,
        watermark,
        exit_manager,
        notification_queue,
        missed_tracker,
        signal_coordinator,
    ):
        """
        V7PurpleReAbsStrategy 초기화

        Args:
            signal_pool: SignalPool 인스턴스
            signal_detector: PurpleSignalDetector 인스턴스
            dual_pass: DualPassDetector 인스턴스
            watermark: WatermarkManager 인스턴스
            exit_manager: WaveHarvestExit 인스턴스
            notification_queue: NotificationQueue 인스턴스
            missed_tracker: MissedSignalTracker 인스턴스
            signal_coordinator: V7SignalCoordinator 인스턴스
        """
        self._signal_pool = signal_pool
        self._signal_detector = signal_detector
        self._dual_pass = dual_pass
        self._watermark = watermark
        self._exit_manager = exit_manager
        self._notification_queue = notification_queue
        self._missed_tracker = missed_tracker
        self._signal_coordinator = signal_coordinator
        self._logger = get_logger(__name__)

    @property
    def name(self) -> str:
        return "V7_PURPLE_REABS"

    @property
    def detector(self) -> Optional[BaseDetector]:
        return self._signal_detector

    @property
    def exit_handler(self) -> Optional[BaseExit]:
        return self._exit_manager

    @property
    def signal_pool(self):
        return self._signal_pool

    @property
    def notification_queue(self):
        return self._notification_queue

    @property
    def signal_coordinator(self):
        return self._signal_coordinator

    def build_v7_callbacks(self, infra: V7InfraCallbacks) -> V7Callbacks:
        """V7SignalCoordinator용 콜백 인터페이스 생성 (V7 컴포넌트는 self에서 직접 접근)"""
        return V7Callbacks(
            # 인프라 콜백 (TradingEngine 제공)
            get_candles=infra.get_candles,
            is_candle_loaded=infra.is_candle_loaded,
            promote_to_tier1=infra.promote_to_tier1,
            send_telegram=infra.send_telegram,
            is_engine_running=infra.is_engine_running,
            # SignalPool
            get_signal_pool=lambda: self._signal_pool,
            get_pool_stock=lambda code: self._signal_pool.get(code) if self._signal_pool is not None else None,
            get_all_pool_stocks=lambda: list(self._signal_pool.get_all()) if self._signal_pool is not None else [],
            get_recent_pool_stocks=lambda age: list(
                self._signal_pool.get_recent_stocks(age)
            ) if self._signal_pool is not None else [],
            # DualPass
            get_dual_pass=lambda: self._dual_pass,
            get_candidates=lambda: self._dual_pass.get_candidates() if self._dual_pass else set(),
            clear_candidates=lambda: self._dual_pass.clear_candidates() if self._dual_pass else None,
            # Watermark
            is_market_open=lambda now: self._watermark.is_market_open(now) if self._watermark else False,
            is_signal_time=lambda now: self._watermark.is_signal_time(now) if self._watermark else False,
            is_pre_check_time=lambda now, sec: self._watermark.is_pre_check_time(now, sec) if self._watermark else False,
            is_confirm_check_time=lambda now, sec: self._watermark.is_confirm_check_time(now, sec) if self._watermark else False,
            get_current_bar_start=lambda: self._watermark.get_current_bar_start(datetime.now()) if self._watermark else None,
            # MissedSignalTracker
            log_missed_attempt=lambda attempt: self._missed_tracker.log_attempt(attempt) if self._missed_tracker else None,
            # NotificationQueue
            enqueue_notification=lambda **kwargs: self._notification_queue.enqueue(**kwargs) if self._notification_queue else False,
            process_next_notification=self._notification_queue.process_next if self._notification_queue else None,
        )

    def on_condition_signal(
        self,
        stock_code: str,
        stock_name: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """
        조건검색 신호 수신 시 SignalPool에 등록

        TradingEngine._on_condition_signal()의 V7 경로 로직을 캡슐화합니다.
        """
        if self._signal_pool is None:
            return False

        self._signal_pool.add(stock_code, stock_name, metadata={
            "source": "condition_search",
            **(metadata or {}),
        })

        self._logger.info(
            f"[V7-Strategy] SignalPool 등록: {stock_name}({stock_code}) "
            f"(Pool: {self._signal_pool.size()}개)"
        )
        return True

    def get_background_tasks(
        self,
        callbacks: Dict[str, Any],
    ) -> List[asyncio.Task]:
        """
        V7SignalCoordinator 백그라운드 태스크 반환

        V7SignalCoordinator가 DualPass 루프를 실행하며,
        SignalPool → Pre-Check → Confirm-Check → Notification 흐름을 관리합니다.
        """
        tasks = []

        if self._signal_coordinator is not None:
            v7_callbacks = callbacks.get("v7_callbacks")
            if v7_callbacks is not None:
                tasks.append(asyncio.create_task(
                    self._signal_coordinator.start(v7_callbacks)
                ))
                self._logger.info("[V7-Strategy] V7SignalCoordinator 태스크 생성")

        return tasks

    def on_candle_complete(
        self,
        stock_code: str,
        df: Any,
        callbacks: Dict[str, Any],
    ) -> Optional[BaseSignal]:
        """
        캔들 완성 시 신호 탐지

        V7은 DualPass에서 처리하므로 여기서는 None 반환.
        V7SignalCoordinator가 자체적으로 캔들 완성을 감지하여 처리합니다.
        """
        return None

    def on_position_opened(
        self,
        stock_code: str,
        entry_price: int,
        callbacks: Dict[str, Any],
    ) -> None:
        """
        포지션 진입 시 WaveHarvest Exit State 초기화

        ExitCoordinator.initialize_v7_state()를 통해 초기화됩니다.
        """
        exit_coordinator = callbacks.get("exit_coordinator")
        if exit_coordinator is not None:
            exit_state = exit_coordinator.initialize_v7_state(
                stock_code=stock_code,
                entry_price=entry_price,
                entry_date=datetime.now(),
            )
            if exit_state:
                self._logger.info(
                    f"[V7-Strategy] Exit State 초기화: {stock_code} | "
                    f"entry={entry_price:,} | "
                    f"fallback_stop={exit_state.get_fallback_stop():,}"
                )

    def on_position_closed(
        self,
        stock_code: str,
        callbacks: Dict[str, Any],
    ) -> None:
        """
        포지션 청산 시 Exit State 정리

        ExitCoordinator.cleanup_v7_state()를 통해 정리됩니다.
        """
        exit_coordinator = callbacks.get("exit_coordinator")
        if exit_coordinator is not None:
            exit_coordinator.cleanup_v7_state(stock_code)

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        status = {
            "name": self.name,
            "enabled": True,
        }

        if self._signal_pool is not None:
            status["signal_pool_size"] = self._signal_pool.size()

        if self._signal_coordinator is not None:
            status["coordinator_active"] = True

        if self._notification_queue is not None:
            status["notification_pending"] = self._notification_queue.pending_count()

        if self._missed_tracker is not None:
            status["missed_tracker"] = self._missed_tracker.get_stats()

        return status

    def on_daily_reset(self) -> None:
        """일일 리셋: SignalPool, MissedTracker 초기화"""
        if self._signal_pool is not None:
            self._signal_pool.clear()
            self._logger.info("[V7-Strategy] SignalPool 일일 리셋")

        if self._missed_tracker is not None:
            self._missed_tracker.clear()

        if self._notification_queue is not None:
            self._notification_queue.clear_cooldowns()

    async def async_shutdown(self) -> None:
        """비동기 종료 정리 (V7SignalCoordinator stop, NotificationQueue flush)"""
        if self._signal_coordinator is not None:
            try:
                await self._signal_coordinator.stop()
            except Exception as e:
                self._logger.warning(f"[V7-Strategy] SignalCoordinator 정지 실패: {e}")

        if self._notification_queue is not None:
            try:
                await self._notification_queue.flush()
            except Exception as e:
                self._logger.warning(f"[V7-Strategy] 알림 큐 정리 실패: {e}")

        # SignalPool 정리
        if self._signal_pool is not None:
            self._signal_pool.clear()

        self._logger.info("[V7-Strategy] 비동기 종료 정리 완료")

    def on_shutdown(self) -> None:
        """종료 시 동기 정리"""
        if self._notification_queue is not None:
            self._notification_queue.clear()
        self._logger.info("[V7-Strategy] 종료 정리 완료")
