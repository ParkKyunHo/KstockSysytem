"""
V6 SNIPER_TRAP 전략 어댑터

기존 V6 컴포넌트들(SniperTrapDetector, ExitManager, AutoScreener)을
BaseStrategy 인터페이스로 래핑합니다.

TradingEngine의 V6 조건 분기를 제거하기 위한 어댑터 계층입니다.
기존 컴포넌트의 동작은 변경하지 않습니다.
"""

from typing import Optional, List, Dict, Any
import asyncio

from src.core.strategies.base_strategy import BaseStrategy
from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit
from src.core.signals.base_signal import BaseSignal
from src.utils.logger import get_logger


class V6SniperTrapStrategy(BaseStrategy):
    """
    V6 SNIPER_TRAP 전략 어댑터

    기존 V6 컴포넌트들을 래핑하여 BaseStrategy 인터페이스를 제공합니다.

    Usage:
        strategy = V6SniperTrapStrategy(
            signal_detector=sniper_detector,
            exit_manager=exit_manager,
            auto_screener=auto_screener,
        )
    """

    def __init__(
        self,
        signal_detector=None,
        exit_manager=None,
        auto_screener=None,
    ):
        """
        V6SniperTrapStrategy 초기화

        Args:
            signal_detector: SniperTrapDetector 또는 SignalDetector 인스턴스
            exit_manager: ExitManager 인스턴스
            auto_screener: AutoScreener 인스턴스 (V6 전용 풀 관리)
        """
        self._signal_detector = signal_detector
        self._exit_manager = exit_manager
        self._auto_screener = auto_screener
        self._logger = get_logger(__name__)

    @property
    def name(self) -> str:
        return "V6_SNIPER_TRAP"

    @property
    def detector(self) -> Optional[BaseDetector]:
        """
        V6 SniperTrapDetector 반환

        SniperTrapDetector가 BaseDetector를 상속하므로 직접 반환 가능.
        SignalDetector (wrapper) 사용 시 내부 _sniper_detector를 반환.
        """
        if self._signal_detector is None:
            return None
        # SignalDetector wrapper인 경우 내부 detector 반환
        if hasattr(self._signal_detector, '_sniper_detector'):
            return self._signal_detector._sniper_detector
        return self._signal_detector

    @property
    def exit_handler(self) -> Optional[BaseExit]:
        return self._exit_manager

    def on_condition_signal(
        self,
        stock_code: str,
        stock_name: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """
        조건검색 신호 수신 시 Watchlist 등록

        TradingEngine._on_condition_signal()의 V6 경로 로직을 캡슐화합니다.
        AutoScreener의 Watchlist에 종목을 등록합니다.
        """
        if self._auto_screener is None:
            return False

        try:
            self._auto_screener.add_to_watchlist(
                stock_code=stock_code,
                stock_name=stock_name,
                metadata=metadata or {},
            )
            self._logger.info(
                f"[V6-Strategy] Watchlist 등록: {stock_name}({stock_code})"
            )
            return True
        except Exception as e:
            self._logger.error(
                f"[V6-Strategy] Watchlist 등록 실패: {stock_code}: {e}"
            )
            return False

    def get_background_tasks(
        self,
        callbacks: Dict[str, Any],
    ) -> List[asyncio.Task]:
        """
        V6 전용 백그라운드 태스크 반환

        V6에서는 ranking_update, watchlist_revalidation 등이 TradingEngine에서
        직접 관리됩니다. Phase 3에서 이 태스크들을 여기로 이동할 수 있습니다.
        """
        # Phase 3에서 구현: V6 전용 태스크 이동
        return []

    def on_candle_complete(
        self,
        stock_code: str,
        df: Any,
        callbacks: Dict[str, Any],
    ) -> Optional[BaseSignal]:
        """
        캔들 완성 시 SNIPER_TRAP 신호 탐지

        V6 SniperTrapDetector.check_signal()에 위임합니다.
        """
        if self._signal_detector is None:
            return None

        try:
            if hasattr(self._signal_detector, 'check_sniper_trap'):
                # SignalDetector wrapper 사용
                return self._signal_detector.check_sniper_trap(
                    df, stock_code,
                    stock_name=callbacks.get("stock_name", ""),
                )
            elif hasattr(self._signal_detector, 'check_signal'):
                # SniperTrapDetector 직접 사용
                return self._signal_detector.check_signal(
                    df, stock_code,
                    stock_name=callbacks.get("stock_name", ""),
                )
            elif hasattr(self._signal_detector, 'detect'):
                # BaseDetector 인터페이스 사용
                return self._signal_detector.detect(
                    df, stock_code,
                    stock_name=callbacks.get("stock_name", ""),
                )
        except Exception as e:
            self._logger.error(
                f"[V6-Strategy] 신호 탐지 실패: {stock_code}: {e}"
            )

        return None

    def on_position_opened(
        self,
        stock_code: str,
        entry_price: int,
        callbacks: Dict[str, Any],
    ) -> None:
        """
        포지션 진입 시 V6 TS 초기화

        ExitManager.initialize_trailing_stop_on_entry_v62a()는
        TradingEngine에서 직접 호출됩니다.
        """
        pass

    def on_position_closed(
        self,
        stock_code: str,
        callbacks: Dict[str, Any],
    ) -> None:
        """
        포지션 청산 시 Watchlist 정리
        """
        if self._auto_screener is not None:
            try:
                if hasattr(self._auto_screener, 'remove_from_watchlist'):
                    self._auto_screener.remove_from_watchlist(stock_code)
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        status = {
            "name": self.name,
            "enabled": True,
        }

        if self._auto_screener is not None:
            if hasattr(self._auto_screener, 'get_watchlist_size'):
                status["watchlist_size"] = self._auto_screener.get_watchlist_size()

        return status

    def on_shutdown(self) -> None:
        """종료 시 정리"""
        self._logger.info("[V6-Strategy] 종료 정리 완료")
