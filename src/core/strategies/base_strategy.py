"""
전략 추상 기본 클래스 (Strategy ABC)

모든 전략이 상속받는 기본 인터페이스를 정의합니다.
TradingEngine은 이 인터페이스를 통해 전략과 상호작용하며,
전략별 분기 없이 통일된 방식으로 전략을 실행합니다.

CLAUDE.md 불변 조건:
- 고정 손절 -4% 최우선 (Risk-First)
- 트레일링 스탑 상향 전용
- ATR 배수 단방향 축소
- EMA adjust=False

Usage:
    from src.core.strategies import BaseStrategy

    class MyStrategy(BaseStrategy):
        @property
        def name(self) -> str:
            return "MY_STRATEGY"
        ...
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import asyncio

from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit
from src.core.signals.base_signal import BaseSignal


class BaseStrategy(ABC):
    """
    전략 추상 기본 클래스

    모든 전략이 상속받아야 하는 추상 클래스입니다.
    StrategyOrchestrator가 이 인터페이스를 통해 전략을 실행합니다.

    필수 구현:
        name: 전략 고유 이름
        detector: 신호 탐지기 (없으면 None)
        exit_handler: 청산 핸들러 (없으면 None)
        on_condition_signal(): 조건검색 신호 처리
        get_background_tasks(): 전략 전용 백그라운드 태스크
        on_candle_complete(): 캔들 완성 시 신호 탐지

    선택적 구현 (기본값 제공):
        on_position_opened(): 포지션 진입 후처리
        on_position_closed(): 포지션 청산 후처리
        get_status(): 상태 조회
        on_daily_reset(): 일일 리셋
        on_shutdown(): 종료 시 정리
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """전략 고유 이름 (예: 'V7_PURPLE_REABS', 'V6_SNIPER_TRAP')"""

    @property
    @abstractmethod
    def detector(self) -> Optional[BaseDetector]:
        """신호 탐지기 (없으면 None)"""

    @property
    @abstractmethod
    def exit_handler(self) -> Optional[BaseExit]:
        """청산 핸들러 (없으면 None)"""

    @abstractmethod
    def on_condition_signal(
        self,
        stock_code: str,
        stock_name: str,
        metadata: Dict[str, Any],
    ) -> bool:
        """
        조건검색 신호 수신 시 처리

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            metadata: 신호 메타데이터

        Returns:
            True=처리됨, False=미처리
        """

    @abstractmethod
    def get_background_tasks(
        self,
        callbacks: Dict[str, Any],
    ) -> List[asyncio.Task]:
        """
        전략 전용 백그라운드 태스크 정의

        Args:
            callbacks: TradingEngine 콜백 딕셔너리

        Returns:
            asyncio.Task 리스트
        """

    @abstractmethod
    def on_candle_complete(
        self,
        stock_code: str,
        df: Any,
        callbacks: Dict[str, Any],
    ) -> Optional[BaseSignal]:
        """
        캔들 완성 시 신호 탐지

        Args:
            stock_code: 종목 코드
            df: OHLCV DataFrame
            callbacks: TradingEngine 콜백 딕셔너리

        Returns:
            탐지된 신호 또는 None
        """

    # ===== 선택적 메서드 (기본값 제공) =====

    def on_position_opened(
        self,
        stock_code: str,
        entry_price: int,
        callbacks: Dict[str, Any],
    ) -> None:
        """포지션 진입 시 후처리 (기본: no-op)"""
        pass

    def on_position_closed(
        self,
        stock_code: str,
        callbacks: Dict[str, Any],
    ) -> None:
        """포지션 청산 시 후처리 (기본: no-op)"""
        pass

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        return {"name": self.name, "enabled": True}

    def on_daily_reset(self) -> None:
        """일일 리셋 (기본: no-op)"""
        pass

    def on_shutdown(self) -> None:
        """종료 시 정리 (기본: no-op)"""
        pass

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"has_detector={self.detector is not None}, "
            f"has_exit={self.exit_handler is not None})"
        )
