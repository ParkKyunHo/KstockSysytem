"""
전략 오케스트레이터 (Phase 3 리팩토링)

다중 전략의 신호 탐지, 조건 검증, 청산 조율을 통합 관리합니다.
TradingEngine의 전략 관련 로직을 분리하여 단일 책임 원칙을 준수합니다.

주요 기능:
- 전략 등록 및 관리 (V6 SNIPER_TRAP, V7 Purple-ReAbs)
- 신호 탐지 조율 (Dual-Pass 지원)
- 청산 조건 검사 조율
- 전략별 설정 관리

CLAUDE.md 불변 조건:
- V7 수정 불가 항목 (Score 가중치, PurpleOK 임계값 등)
- 고정 손절 -4% 최우선
- 트레일링 스탑 상향 단방향

Usage:
    from src.core.strategy_orchestrator import StrategyOrchestrator

    orchestrator = StrategyOrchestrator()
    orchestrator.register_strategy(purple_config)

    signals = orchestrator.detect_signals(stock_code, stock_name, df)
    exit_decision = orchestrator.check_exit(strategy_name, df, entry_price, current_price)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
import asyncio
import pandas as pd

from src.core.signals.base_signal import BaseSignal, SignalType, StrategyType
from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit, ExitDecision, ExitReason
from src.core.strategies.base_strategy import BaseStrategy
from src.utils.logger import get_logger


class StrategyState(str, Enum):
    """전략 상태"""
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    PAUSED = "PAUSED"


@dataclass
class StrategyConfig:
    """
    전략 설정

    각 전략의 구성 정보를 담는 데이터 클래스입니다.

    Attributes:
        name: 전략 이름
        strategy_type: 전략 타입
        detector: 신호 탐지기
        exit_strategy: 청산 전략
        state: 전략 상태
        priority: 우선순위 (낮을수록 높음)
        settings: 전략별 추가 설정
    """
    name: str
    strategy_type: StrategyType
    detector: Optional[BaseDetector] = None
    exit_strategy: Optional[BaseExit] = None
    state: StrategyState = StrategyState.ENABLED
    priority: int = 100
    settings: Dict[str, Any] = field(default_factory=dict)


class StrategyOrchestrator:
    """
    전략 오케스트레이터

    다중 전략을 통합 관리하며, 신호 탐지와 청산 조율을 담당합니다.
    TradingEngine에서 전략 관련 로직을 분리하여 단일 책임 원칙을 준수합니다.

    Features:
    - 다중 전략 동시 운영 지원
    - 전략별 활성화/비활성화
    - 우선순위 기반 신호 처리
    - 통합 청산 조율

    Example:
        orchestrator = StrategyOrchestrator()

        # 전략 등록
        orchestrator.register_strategy(StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
            detector=PurpleDetector(),
            exit_strategy=WaveHarvestStrategy(),
        ))

        # 신호 탐지
        signals = orchestrator.detect_signals("005930", "삼성전자", df)

        # 청산 검사
        decision = orchestrator.check_exit("V7_PURPLE", df, entry_price, current_price)
    """

    def __init__(self, position_strategies: Optional[Dict[str, str]] = None):
        self._logger = get_logger(__name__)
        self._strategies: Dict[str, StrategyConfig] = {}
        self._base_strategies: Dict[str, BaseStrategy] = {}
        # M-09: 외부에서 공유 dict 주입 가능 (ExitCoordinator와 동일 객체)
        self._position_strategies: Dict[str, str] = position_strategies if position_strategies is not None else {}
        self._signal_history: List[BaseSignal] = []
        self._max_history_size = 1000

    # =========================================
    # 전략 등록/관리
    # =========================================

    def register_strategy(self, config: StrategyConfig) -> bool:
        """
        전략 등록

        Args:
            config: 전략 설정

        Returns:
            등록 성공 여부
        """
        if config.name in self._strategies:
            self._logger.warning(f"[Orchestrator] 전략 이미 존재: {config.name}")
            return False

        self._strategies[config.name] = config
        self._logger.info(
            f"[Orchestrator] 전략 등록: {config.name} "
            f"(type={config.strategy_type.value}, priority={config.priority})"
        )
        return True

    def unregister_strategy(self, name: str) -> bool:
        """
        전략 해제

        Args:
            name: 전략 이름

        Returns:
            해제 성공 여부
        """
        if name not in self._strategies:
            return False

        del self._strategies[name]
        self._logger.info(f"[Orchestrator] 전략 해제: {name}")
        return True

    def enable_strategy(self, name: str) -> bool:
        """전략 활성화"""
        if name not in self._strategies:
            return False
        self._strategies[name].state = StrategyState.ENABLED
        self._logger.info(f"[Orchestrator] 전략 활성화: {name}")
        return True

    def disable_strategy(self, name: str) -> bool:
        """전략 비활성화"""
        if name not in self._strategies:
            return False
        self._strategies[name].state = StrategyState.DISABLED
        self._logger.info(f"[Orchestrator] 전략 비활성화: {name}")
        return True

    def pause_strategy(self, name: str) -> bool:
        """전략 일시 정지"""
        if name not in self._strategies:
            return False
        self._strategies[name].state = StrategyState.PAUSED
        self._logger.info(f"[Orchestrator] 전략 일시정지: {name}")
        return True

    def get_strategy(self, name: str) -> Optional[StrategyConfig]:
        """전략 설정 조회"""
        return self._strategies.get(name)

    def get_enabled_strategies(self) -> List[StrategyConfig]:
        """활성화된 전략 목록"""
        strategies = [
            s for s in self._strategies.values()
            if s.state == StrategyState.ENABLED
        ]
        return sorted(strategies, key=lambda x: x.priority)

    # =========================================
    # 신호 탐지
    # =========================================

    def detect_signals(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        strategy_filter: Optional[List[str]] = None
    ) -> List[BaseSignal]:
        """
        신호 탐지 (모든 활성 전략)

        모든 활성화된 전략에서 신호를 탐지합니다.
        우선순위 순으로 처리됩니다.

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame
            strategy_filter: 특정 전략만 실행 (None이면 모든 활성 전략)

        Returns:
            탐지된 신호 목록
        """
        signals: List[BaseSignal] = []

        for strategy in self.get_enabled_strategies():
            # 필터 적용
            if strategy_filter and strategy.name not in strategy_filter:
                continue

            # 탐지기 확인
            if strategy.detector is None:
                continue

            # 데이터 충분성 확인
            if not strategy.detector.is_ready(df):
                continue

            try:
                signal = strategy.detector.detect(df, stock_code, stock_name)
                if signal:
                    signals.append(signal)
                    self._add_to_history(signal)
                    self._logger.info(
                        f"[Orchestrator] 신호 탐지: {strategy.name} - "
                        f"{stock_name}({stock_code}) @{signal.price:,}원"
                    )
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 신호 탐지 오류: {strategy.name} - "
                    f"{stock_code}: {e}"
                )

        return signals

    def detect_signal_single(
        self,
        strategy_name: str,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> Optional[BaseSignal]:
        """
        신호 탐지 (단일 전략)

        특정 전략에서만 신호를 탐지합니다.

        Args:
            strategy_name: 전략 이름
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame

        Returns:
            탐지된 신호 또는 None
        """
        strategy = self._strategies.get(strategy_name)
        if not strategy:
            return None

        if strategy.state != StrategyState.ENABLED:
            return None

        if strategy.detector is None:
            return None

        if not strategy.detector.is_ready(df):
            return None

        try:
            return strategy.detector.detect(df, stock_code, stock_name)
        except Exception as e:
            self._logger.error(
                f"[Orchestrator] 신호 탐지 오류: {strategy_name} - {stock_code}: {e}"
            )
            return None

    # =========================================
    # 청산 조율
    # =========================================

    def check_exit(
        self,
        strategy_name: str,
        df: pd.DataFrame,
        entry_price: int,
        current_price: int,
        **kwargs
    ) -> ExitDecision:
        """
        청산 조건 검사

        특정 전략의 청산 조건을 검사합니다.
        고정 손절(-4%)은 항상 최우선으로 검사됩니다.

        Args:
            strategy_name: 전략 이름
            df: OHLCV DataFrame
            entry_price: 진입가
            current_price: 현재가
            **kwargs: 전략별 추가 파라미터

        Returns:
            청산 결정
        """
        strategy = self._strategies.get(strategy_name)
        if not strategy or strategy.exit_strategy is None:
            return ExitDecision(should_exit=False)

        try:
            # 고정 손절 최우선 검사 (CLAUDE.md 불변)
            hard_stop = strategy.exit_strategy.check_hard_stop(entry_price, current_price)
            if hard_stop and hard_stop.should_exit:
                self._logger.warning(
                    f"[Orchestrator] 고정 손절: {strategy_name} - "
                    f"{kwargs.get('stock_code', 'UNKNOWN')} "
                    f"@{current_price:,}원 ({hard_stop.profit_rate:+.2f}%)"
                )
                return hard_stop

            # 전략별 청산 검사
            return strategy.exit_strategy.check_exit(
                df, entry_price, current_price, **kwargs
            )
        except Exception as e:
            self._logger.error(
                f"[Orchestrator] 청산 검사 오류: {strategy_name}: {e}"
            )
            return ExitDecision(should_exit=False)

    def update_trailing_stop(
        self,
        strategy_name: str,
        df: pd.DataFrame,
        current_stop: int,
        current_price: int,
        **kwargs
    ) -> tuple:
        """
        트레일링 스탑 업데이트

        Args:
            strategy_name: 전략 이름
            df: OHLCV DataFrame
            current_stop: 현재 스탑
            current_price: 현재가
            **kwargs: 전략별 추가 파라미터

        Returns:
            (새 스탑, 새 ATR 배수)
        """
        strategy = self._strategies.get(strategy_name)
        if not strategy or strategy.exit_strategy is None:
            return current_stop, kwargs.get("current_multiplier", 6.0)

        try:
            return strategy.exit_strategy.update_trailing_stop(
                df, current_stop, current_price, **kwargs
            )
        except Exception as e:
            self._logger.error(
                f"[Orchestrator] TS 업데이트 오류: {strategy_name}: {e}"
            )
            return current_stop, kwargs.get("current_multiplier", 6.0)

    # =========================================
    # 히스토리 관리
    # =========================================

    def _add_to_history(self, signal: BaseSignal) -> None:
        """신호 히스토리 추가"""
        self._signal_history.append(signal)
        if len(self._signal_history) > self._max_history_size:
            self._signal_history = self._signal_history[-self._max_history_size:]

    def get_signal_history(
        self,
        stock_code: Optional[str] = None,
        strategy_type: Optional[StrategyType] = None,
        limit: int = 100
    ) -> List[BaseSignal]:
        """
        신호 히스토리 조회

        Args:
            stock_code: 종목 코드 필터
            strategy_type: 전략 타입 필터
            limit: 최대 개수

        Returns:
            신호 목록
        """
        history = self._signal_history

        if stock_code:
            history = [s for s in history if s.stock_code == stock_code]

        if strategy_type:
            history = [s for s in history if s.strategy == strategy_type]

        return history[-limit:]

    # =========================================
    # 상태 조회
    # =========================================

    def get_status(self) -> Dict[str, Any]:
        """
        오케스트레이터 상태 조회

        Returns:
            상태 정보 딕셔너리
        """
        return {
            "total_strategies": len(self._strategies),
            "enabled_strategies": len(self.get_enabled_strategies()),
            "strategies": {
                name: {
                    "type": config.strategy_type.value,
                    "state": config.state.value,
                    "priority": config.priority,
                    "has_detector": config.detector is not None,
                    "has_exit": config.exit_strategy is not None,
                }
                for name, config in self._strategies.items()
            },
            "signal_history_size": len(self._signal_history),
        }

    def __str__(self) -> str:
        enabled = len(self.get_enabled_strategies())
        total = len(self._strategies)
        return f"StrategyOrchestrator({enabled}/{total} enabled)"

    # =========================================
    # BaseStrategy 기반 디스패치 (Phase 3)
    # =========================================

    def register_base_strategy(self, strategy: BaseStrategy, priority: int = 100) -> bool:
        """
        BaseStrategy 객체 등록

        BaseStrategy를 StrategyConfig로 래핑하여 기존 인프라와 호환됩니다.

        Args:
            strategy: BaseStrategy 구현체
            priority: 우선순위 (낮을수록 높음)

        Returns:
            등록 성공 여부
        """
        name = strategy.name
        if name in self._strategies:
            self._logger.warning(f"[Orchestrator] 전략 이미 존재: {name}")
            return False

        if name in self._base_strategies:
            self._logger.warning(f"[Orchestrator] BaseStrategy 이미 존재: {name}")
            return False

        # BaseStrategy 전용 저장소에 등록
        self._base_strategies[name] = strategy

        # 기존 StrategyConfig 인프라와 호환하기 위해 래핑 등록
        # detector/exit_strategy는 BaseStrategy에서 추출
        detector = strategy.detector
        exit_handler = strategy.exit_handler

        # StrategyType 결정
        strategy_type = StrategyType.PURPLE_REABS  # 기본값
        if "SNIPER" in name.upper() or "V6" in name.upper():
            strategy_type = StrategyType.SNIPER_TRAP

        config = StrategyConfig(
            name=name,
            strategy_type=strategy_type,
            detector=detector,
            exit_strategy=exit_handler,
            priority=priority,
        )
        self._strategies[name] = config

        self._logger.info(
            f"[Orchestrator] BaseStrategy 등록: {name} "
            f"(detector={'O' if detector else 'X'}, "
            f"exit={'O' if exit_handler else 'X'}, "
            f"priority={priority})"
        )
        return True

    def get_base_strategy(self, name: str) -> Optional[BaseStrategy]:
        """BaseStrategy 객체 조회"""
        return self._base_strategies.get(name)

    def get_strategy_for_stock(self, stock_code: str) -> Optional[BaseStrategy]:
        """
        종목의 전략 조회 (position_strategies 매핑 기반)

        Args:
            stock_code: 종목코드

        Returns:
            해당 종목의 BaseStrategy 또는 None
        """
        strategy_name = self._position_strategies.get(stock_code)
        if strategy_name:
            return self._base_strategies.get(strategy_name)
        return None

    def register_position_strategy(self, stock_code: str, strategy_name: str) -> None:
        """
        포지션-전략 매핑 등록

        포지션 진입 시 호출하여 종목코드와 전략을 연결합니다.
        청산 시 이 매핑을 통해 올바른 전략의 exit_handler를 사용합니다.

        Args:
            stock_code: 종목코드
            strategy_name: 전략 이름
        """
        self._position_strategies[stock_code] = strategy_name
        self._logger.debug(
            f"[Orchestrator] 포지션-전략 매핑: {stock_code} → {strategy_name}"
        )

    def unregister_position_strategy(self, stock_code: str) -> None:
        """포지션-전략 매핑 해제"""
        if stock_code in self._position_strategies:
            del self._position_strategies[stock_code]

    def dispatch_condition_signal(
        self,
        stock_code: str,
        stock_name: str,
        metadata: Dict[str, Any],
    ) -> Optional[str]:
        """
        조건검색 신호를 적절한 전략에 디스패치

        등록된 모든 활성 BaseStrategy에 순차적으로 전달하고,
        처리한 전략의 이름을 반환합니다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            metadata: 신호 메타데이터

        Returns:
            처리한 전략 이름 또는 None (미처리)
        """
        for name, strategy in self._base_strategies.items():
            config = self._strategies.get(name)
            if config and config.state != StrategyState.ENABLED:
                continue

            try:
                handled = strategy.on_condition_signal(stock_code, stock_name, metadata)
                if handled:
                    self._logger.info(
                        f"[Orchestrator] 조건검색 신호 처리: {name} - "
                        f"{stock_name}({stock_code})"
                    )
                    return name
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 조건검색 신호 처리 오류: {name} - {stock_code}: {e}"
                )

        return None

    def dispatch_candle_complete(
        self,
        stock_code: str,
        df: Any,
        callbacks: Dict[str, Any],
    ) -> Optional[BaseSignal]:
        """
        캔들 완성 이벤트를 적절한 전략에 디스패치

        Args:
            stock_code: 종목코드
            df: 캔들 데이터
            callbacks: 전략별 콜백

        Returns:
            탐지된 신호 또는 None
        """
        for name, strategy in self._base_strategies.items():
            config = self._strategies.get(name)
            if config and config.state != StrategyState.ENABLED:
                continue

            try:
                signal = strategy.on_candle_complete(stock_code, df, callbacks)
                if signal:
                    self._add_to_history(signal)
                    return signal
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 캔들 완성 처리 오류: {name} - {stock_code}: {e}"
                )

        return None

    def dispatch_position_opened(
        self,
        stock_code: str,
        entry_price: int,
        callbacks: Dict[str, Any],
    ) -> None:
        """포지션 진입 시 적절한 전략에 알림"""
        strategy = self.get_strategy_for_stock(stock_code)
        if strategy:
            try:
                strategy.on_position_opened(stock_code, entry_price, callbacks)
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 포지션 진입 처리 오류: {stock_code}: {e}"
                )

    def collect_background_tasks(
        self,
        callbacks: Dict[str, Any],
    ) -> List[asyncio.Task]:
        """
        모든 전략의 백그라운드 태스크 수집

        Args:
            callbacks: 전략별 콜백

        Returns:
            생성된 태스크 목록
        """
        tasks = []
        for name, strategy in self._base_strategies.items():
            config = self._strategies.get(name)
            if config and config.state != StrategyState.ENABLED:
                continue

            try:
                strategy_tasks = strategy.get_background_tasks(callbacks)
                tasks.extend(strategy_tasks)
                if strategy_tasks:
                    self._logger.info(
                        f"[Orchestrator] 백그라운드 태스크 수집: {name} → "
                        f"{len(strategy_tasks)}개"
                    )
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 백그라운드 태스크 수집 오류: {name}: {e}"
                )

        return tasks

    def dispatch_daily_reset(self) -> None:
        """모든 전략의 일일 리셋"""
        for name, strategy in self._base_strategies.items():
            try:
                strategy.on_daily_reset()
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 일일 리셋 오류: {name}: {e}"
                )

    def dispatch_shutdown(self) -> None:
        """모든 전략의 종료 정리"""
        for name, strategy in self._base_strategies.items():
            try:
                strategy.on_shutdown()
            except Exception as e:
                self._logger.error(
                    f"[Orchestrator] 종료 정리 오류: {name}: {e}"
                )

    def get_all_strategy_status(self) -> Dict[str, Any]:
        """
        모든 전략의 통합 상태

        기존 get_status()에 BaseStrategy 상태를 추가합니다.

        Returns:
            통합 상태 정보
        """
        base_status = self.get_status()

        # BaseStrategy 상세 상태 추가
        strategy_details = {}
        for name, strategy in self._base_strategies.items():
            try:
                strategy_details[name] = strategy.get_status()
            except Exception as e:
                strategy_details[name] = {"error": str(e)}

        base_status["strategy_details"] = strategy_details
        base_status["position_strategies"] = dict(self._position_strategies)
        return base_status
