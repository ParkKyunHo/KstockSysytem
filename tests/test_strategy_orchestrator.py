"""
Phase 3 리팩토링: StrategyOrchestrator 단위 테스트

전략 오케스트레이터의 전략 등록/관리, 신호 탐지 조율, 청산 조율을 검증합니다.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.strategy_orchestrator import (
    StrategyOrchestrator,
    StrategyConfig,
    StrategyState,
)
from src.core.signals.base_signal import StrategyType
from src.core.exit.base_exit import ExitDecision, ExitReason


def create_sample_ohlcv(n_bars: int = 60) -> pd.DataFrame:
    """테스트용 OHLCV 데이터 생성"""
    np.random.seed(42)
    prices = 10000 + np.cumsum(np.random.randn(n_bars) * 50)

    data = []
    for close in prices:
        data.append({
            'open': close + np.random.uniform(-30, 30),
            'high': close + np.random.uniform(0, 50),
            'low': close - np.random.uniform(0, 50),
            'close': close,
            'volume': int(np.random.uniform(50000, 150000)),
        })

    return pd.DataFrame(data)


class MockDetector:
    """테스트용 Detector Mock"""
    def __init__(self, strategy_name: str = "TEST", min_candles: int = 30, signal=None):
        self._strategy_name = strategy_name
        self._min_candles = min_candles
        self._signal = signal

    @property
    def strategy_name(self) -> str:
        return self._strategy_name

    @property
    def min_candles_required(self) -> int:
        return self._min_candles

    def is_ready(self, df: pd.DataFrame) -> bool:
        return df is not None and len(df) >= self._min_candles

    def detect(self, df, stock_code, stock_name, **kwargs):
        return self._signal


class MockExitStrategy:
    """테스트용 Exit Strategy Mock"""
    def __init__(self, should_exit: bool = False, hard_stop: bool = False):
        self._should_exit = should_exit
        self._hard_stop = hard_stop

    @property
    def strategy_name(self) -> str:
        return "MOCK_EXIT"

    def check_hard_stop(self, entry_price: int, current_price: int):
        if self._hard_stop:
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.HARD_STOP,
                exit_price=current_price,
                profit_rate=-4.0,
            )
        return None

    def check_exit(self, df, entry_price, current_price, **kwargs):
        if self._should_exit:
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.TRAILING_STOP,
                exit_price=current_price,
            )
        return ExitDecision(should_exit=False)

    def update_trailing_stop(self, df, current_stop, current_price, **kwargs):
        return current_stop, 6.0


class TestStrategyOrchestrator:
    """StrategyOrchestrator 테스트"""

    def test_initialization(self):
        """초기화 테스트"""
        orchestrator = StrategyOrchestrator()

        assert len(orchestrator._strategies) == 0
        assert len(orchestrator._signal_history) == 0

    def test_register_strategy(self):
        """전략 등록 테스트"""
        orchestrator = StrategyOrchestrator()
        config = StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
            priority=10,
        )

        result = orchestrator.register_strategy(config)

        assert result is True
        assert "V7_PURPLE" in orchestrator._strategies
        assert orchestrator._strategies["V7_PURPLE"].priority == 10

    def test_register_duplicate_strategy(self):
        """중복 전략 등록 실패 테스트"""
        orchestrator = StrategyOrchestrator()
        config = StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
        )

        orchestrator.register_strategy(config)
        result = orchestrator.register_strategy(config)

        assert result is False

    def test_unregister_strategy(self):
        """전략 해제 테스트"""
        orchestrator = StrategyOrchestrator()
        config = StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
        )
        orchestrator.register_strategy(config)

        result = orchestrator.unregister_strategy("V7_PURPLE")

        assert result is True
        assert "V7_PURPLE" not in orchestrator._strategies

    def test_unregister_nonexistent_strategy(self):
        """존재하지 않는 전략 해제 테스트"""
        orchestrator = StrategyOrchestrator()

        result = orchestrator.unregister_strategy("NONEXISTENT")

        assert result is False


class TestStrategyState:
    """전략 상태 관리 테스트"""

    def test_enable_strategy(self):
        """전략 활성화 테스트"""
        orchestrator = StrategyOrchestrator()
        config = StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
            state=StrategyState.DISABLED,
        )
        orchestrator.register_strategy(config)

        result = orchestrator.enable_strategy("V7_PURPLE")

        assert result is True
        assert orchestrator._strategies["V7_PURPLE"].state == StrategyState.ENABLED

    def test_disable_strategy(self):
        """전략 비활성화 테스트"""
        orchestrator = StrategyOrchestrator()
        config = StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
            state=StrategyState.ENABLED,
        )
        orchestrator.register_strategy(config)

        result = orchestrator.disable_strategy("V7_PURPLE")

        assert result is True
        assert orchestrator._strategies["V7_PURPLE"].state == StrategyState.DISABLED

    def test_pause_strategy(self):
        """전략 일시정지 테스트"""
        orchestrator = StrategyOrchestrator()
        config = StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
        )
        orchestrator.register_strategy(config)

        result = orchestrator.pause_strategy("V7_PURPLE")

        assert result is True
        assert orchestrator._strategies["V7_PURPLE"].state == StrategyState.PAUSED

    def test_get_enabled_strategies(self):
        """활성화된 전략 조회 테스트"""
        orchestrator = StrategyOrchestrator()

        # 활성화 전략
        orchestrator.register_strategy(StrategyConfig(
            name="ENABLED_1",
            strategy_type=StrategyType.PURPLE_REABS,
            state=StrategyState.ENABLED,
            priority=20,
        ))
        # 비활성화 전략
        orchestrator.register_strategy(StrategyConfig(
            name="DISABLED_1",
            strategy_type=StrategyType.SNIPER_TRAP,
            state=StrategyState.DISABLED,
        ))
        # 또 다른 활성화 전략
        orchestrator.register_strategy(StrategyConfig(
            name="ENABLED_2",
            strategy_type=StrategyType.SNIPER_TRAP,
            state=StrategyState.ENABLED,
            priority=10,  # 더 높은 우선순위
        ))

        enabled = orchestrator.get_enabled_strategies()

        assert len(enabled) == 2
        assert enabled[0].name == "ENABLED_2"  # 우선순위 10 (먼저)
        assert enabled[1].name == "ENABLED_1"  # 우선순위 20 (나중)


class TestSignalDetection:
    """신호 탐지 테스트"""

    def test_detect_signals_no_strategies(self):
        """전략 없을 때 신호 탐지 테스트"""
        orchestrator = StrategyOrchestrator()
        df = create_sample_ohlcv()

        signals = orchestrator.detect_signals("005930", "삼성전자", df)

        assert len(signals) == 0

    def test_detect_signals_no_detector(self):
        """탐지기 없을 때 신호 탐지 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="NO_DETECTOR",
            strategy_type=StrategyType.PURPLE_REABS,
            detector=None,  # 탐지기 없음
        ))
        df = create_sample_ohlcv()

        signals = orchestrator.detect_signals("005930", "삼성전자", df)

        assert len(signals) == 0

    def test_detect_signals_insufficient_data(self):
        """데이터 부족 시 신호 탐지 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="WITH_DETECTOR",
            strategy_type=StrategyType.PURPLE_REABS,
            detector=MockDetector(min_candles=100),  # 100개 필요
        ))
        df = create_sample_ohlcv(n_bars=50)  # 50개만 제공

        signals = orchestrator.detect_signals("005930", "삼성전자", df)

        assert len(signals) == 0

    def test_detect_signals_with_signal(self):
        """신호 탐지 성공 테스트"""
        mock_signal = MagicMock()
        mock_signal.stock_code = "005930"
        mock_signal.price = 10000

        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="WITH_SIGNAL",
            strategy_type=StrategyType.PURPLE_REABS,
            detector=MockDetector(signal=mock_signal),
        ))
        df = create_sample_ohlcv()

        signals = orchestrator.detect_signals("005930", "삼성전자", df)

        assert len(signals) == 1
        assert signals[0] is mock_signal
        assert len(orchestrator._signal_history) == 1

    def test_detect_signals_with_filter(self):
        """전략 필터로 신호 탐지 테스트"""
        mock_signal = MagicMock()
        mock_signal.stock_code = "005930"
        mock_signal.price = 10000

        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="STRATEGY_A",
            strategy_type=StrategyType.PURPLE_REABS,
            detector=MockDetector(signal=mock_signal),
        ))
        orchestrator.register_strategy(StrategyConfig(
            name="STRATEGY_B",
            strategy_type=StrategyType.SNIPER_TRAP,
            detector=MockDetector(signal=mock_signal),
        ))
        df = create_sample_ohlcv()

        # STRATEGY_A만 실행
        signals = orchestrator.detect_signals(
            "005930", "삼성전자", df,
            strategy_filter=["STRATEGY_A"]
        )

        assert len(signals) == 1

    def test_detect_signal_single(self):
        """단일 전략 신호 탐지 테스트"""
        mock_signal = MagicMock()
        mock_signal.stock_code = "005930"

        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
            detector=MockDetector(signal=mock_signal),
        ))
        df = create_sample_ohlcv()

        signal = orchestrator.detect_signal_single(
            "V7_PURPLE", "005930", "삼성전자", df
        )

        assert signal is mock_signal


class TestExitCheck:
    """청산 체크 테스트"""

    def test_check_exit_no_strategy(self):
        """존재하지 않는 전략 청산 체크 테스트"""
        orchestrator = StrategyOrchestrator()
        df = create_sample_ohlcv()

        decision = orchestrator.check_exit(
            "NONEXISTENT", df, 10000, 9500
        )

        assert decision.should_exit is False

    def test_check_exit_no_exit_strategy(self):
        """청산 전략 없을 때 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="NO_EXIT",
            strategy_type=StrategyType.PURPLE_REABS,
            exit_strategy=None,
        ))
        df = create_sample_ohlcv()

        decision = orchestrator.check_exit(
            "NO_EXIT", df, 10000, 9500
        )

        assert decision.should_exit is False

    def test_check_exit_hard_stop(self):
        """고정 손절 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="WITH_EXIT",
            strategy_type=StrategyType.PURPLE_REABS,
            exit_strategy=MockExitStrategy(hard_stop=True),
        ))
        df = create_sample_ohlcv()

        decision = orchestrator.check_exit(
            "WITH_EXIT", df, 10000, 9500
        )

        assert decision.should_exit is True
        assert decision.reason == ExitReason.HARD_STOP

    def test_check_exit_trailing_stop(self):
        """트레일링 스탑 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="WITH_EXIT",
            strategy_type=StrategyType.PURPLE_REABS,
            exit_strategy=MockExitStrategy(should_exit=True, hard_stop=False),
        ))
        df = create_sample_ohlcv()

        decision = orchestrator.check_exit(
            "WITH_EXIT", df, 10000, 10500
        )

        assert decision.should_exit is True
        assert decision.reason == ExitReason.TRAILING_STOP


class TestTrailingStopUpdate:
    """트레일링 스탑 업데이트 테스트"""

    def test_update_trailing_stop(self):
        """트레일링 스탑 업데이트 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="WITH_EXIT",
            strategy_type=StrategyType.PURPLE_REABS,
            exit_strategy=MockExitStrategy(),
        ))
        df = create_sample_ohlcv()

        new_stop, new_mult = orchestrator.update_trailing_stop(
            "WITH_EXIT", df, 9000, 10500
        )

        assert new_stop == 9000
        assert new_mult == 6.0

    def test_update_trailing_stop_no_strategy(self):
        """존재하지 않는 전략 TS 업데이트 테스트"""
        orchestrator = StrategyOrchestrator()
        df = create_sample_ohlcv()

        new_stop, new_mult = orchestrator.update_trailing_stop(
            "NONEXISTENT", df, 9000, 10500, current_multiplier=5.0
        )

        assert new_stop == 9000
        assert new_mult == 5.0


class TestSignalHistory:
    """신호 히스토리 테스트"""

    def test_signal_history_limit(self):
        """신호 히스토리 제한 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator._max_history_size = 5  # 테스트용으로 작게 설정

        # 10개 신호 추가
        for i in range(10):
            mock_signal = MagicMock()
            mock_signal.stock_code = f"00593{i}"
            orchestrator._add_to_history(mock_signal)

        # 최대 5개만 유지
        assert len(orchestrator._signal_history) == 5

    def test_get_signal_history_with_filter(self):
        """신호 히스토리 필터 조회 테스트"""
        orchestrator = StrategyOrchestrator()

        signal1 = MagicMock()
        signal1.stock_code = "005930"
        signal1.strategy = StrategyType.PURPLE_REABS

        signal2 = MagicMock()
        signal2.stock_code = "000660"
        signal2.strategy = StrategyType.SNIPER_TRAP

        orchestrator._add_to_history(signal1)
        orchestrator._add_to_history(signal2)

        # stock_code 필터
        filtered = orchestrator.get_signal_history(stock_code="005930")
        assert len(filtered) == 1
        assert filtered[0].stock_code == "005930"

        # strategy_type 필터
        filtered = orchestrator.get_signal_history(strategy_type=StrategyType.PURPLE_REABS)
        assert len(filtered) == 1


class TestStatus:
    """상태 조회 테스트"""

    def test_get_status(self):
        """상태 조회 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
            priority=10,
        ))
        orchestrator.register_strategy(StrategyConfig(
            name="V6_SNIPER",
            strategy_type=StrategyType.SNIPER_TRAP,
            state=StrategyState.DISABLED,
        ))

        status = orchestrator.get_status()

        assert status["total_strategies"] == 2
        assert status["enabled_strategies"] == 1
        assert "V7_PURPLE" in status["strategies"]
        assert status["strategies"]["V7_PURPLE"]["priority"] == 10

    def test_str_representation(self):
        """문자열 표현 테스트"""
        orchestrator = StrategyOrchestrator()
        orchestrator.register_strategy(StrategyConfig(
            name="V7_PURPLE",
            strategy_type=StrategyType.PURPLE_REABS,
        ))

        s = str(orchestrator)

        assert "StrategyOrchestrator" in s
        assert "1/1" in s


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
