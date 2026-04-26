"""
V6SniperTrapStrategy 어댑터 테스트 (Phase 2)

BaseStrategy 인터페이스 적합성과 V6 컴포넌트 위임을 검증합니다.
"""

import pytest
from unittest.mock import MagicMock
import pandas as pd

from src.core.strategies.base_strategy import BaseStrategy
from src.core.strategies.v6_sniper_trap import V6SniperTrapStrategy
from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit


@pytest.fixture
def mock_components():
    """V6 컴포넌트 모의 객체 생성"""
    # SignalDetector wrapper (내부 _sniper_detector를 가짐)
    sniper_detector = MagicMock(spec=BaseDetector)
    signal_detector = MagicMock()
    signal_detector._sniper_detector = sniper_detector
    signal_detector.check_sniper_trap.return_value = None

    exit_manager = MagicMock(spec=BaseExit)

    auto_screener = MagicMock()
    auto_screener.get_watchlist_size.return_value = 10

    return {
        "signal_detector": signal_detector,
        "exit_manager": exit_manager,
        "auto_screener": auto_screener,
    }


@pytest.fixture
def strategy(mock_components):
    return V6SniperTrapStrategy(**mock_components)


class TestV6StrategyABC:
    """BaseStrategy 인터페이스 적합성 검증"""

    def test_isinstance_base_strategy(self, strategy):
        assert isinstance(strategy, BaseStrategy)

    def test_name(self, strategy):
        assert strategy.name == "V6_SNIPER_TRAP"

    def test_detector_returns_sniper_detector(self, strategy, mock_components):
        """SignalDetector wrapper 사용 시 내부 _sniper_detector 반환"""
        assert strategy.detector is mock_components["signal_detector"]._sniper_detector

    def test_exit_handler_returns_exit_manager(self, strategy, mock_components):
        assert strategy.exit_handler is mock_components["exit_manager"]

    def test_str_repr(self, strategy):
        assert "V6_SNIPER_TRAP" in str(strategy)


class TestV6ConditionSignal:
    """on_condition_signal() 동작 검증"""

    def test_registers_to_watchlist(self, strategy, mock_components):
        result = strategy.on_condition_signal("005930", "삼성전자", {})
        assert result is True
        mock_components["auto_screener"].add_to_watchlist.assert_called_once()

    def test_returns_false_without_screener(self):
        strategy = V6SniperTrapStrategy(
            signal_detector=None,
            exit_manager=None,
            auto_screener=None,
        )
        result = strategy.on_condition_signal("005930", "삼성전자", {})
        assert result is False


class TestV6CandleComplete:
    """on_candle_complete() 동작 검증"""

    def test_delegates_to_signal_detector(self, strategy, mock_components):
        df = pd.DataFrame({"close": [1, 2, 3]})
        strategy.on_candle_complete("005930", df, {"stock_name": "삼성전자"})
        mock_components["signal_detector"].check_sniper_trap.assert_called_once()

    def test_returns_none_without_detector(self):
        strategy = V6SniperTrapStrategy(
            signal_detector=None,
            exit_manager=None,
            auto_screener=None,
        )
        result = strategy.on_candle_complete("005930", None, {})
        assert result is None


class TestV6Status:
    """get_status() 동작 검증"""

    def test_status_includes_watchlist_size(self, strategy):
        status = strategy.get_status()
        assert status["name"] == "V6_SNIPER_TRAP"
        assert status["watchlist_size"] == 10
