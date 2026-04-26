"""
V7PurpleReAbsStrategy 어댑터 테스트 (Phase 2)

BaseStrategy 인터페이스 적합성과 V7 컴포넌트 위임을 검증합니다.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

from src.core.strategies.base_strategy import BaseStrategy
from src.core.strategies.v7_purple_reabs import V7PurpleReAbsStrategy
from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit


@pytest.fixture
def mock_components():
    """V7 컴포넌트 모의 객체 생성"""
    signal_pool = MagicMock()
    signal_pool.size.return_value = 5
    signal_pool.add.return_value = True

    signal_detector = MagicMock(spec=BaseDetector)
    dual_pass = MagicMock()
    watermark = MagicMock()
    exit_manager = MagicMock(spec=BaseExit)
    notification_queue = MagicMock()
    notification_queue.pending_count.return_value = 0
    missed_tracker = MagicMock()
    missed_tracker.get_stats.return_value = {}
    signal_coordinator = MagicMock()

    return {
        "signal_pool": signal_pool,
        "signal_detector": signal_detector,
        "dual_pass": dual_pass,
        "watermark": watermark,
        "exit_manager": exit_manager,
        "notification_queue": notification_queue,
        "missed_tracker": missed_tracker,
        "signal_coordinator": signal_coordinator,
    }


@pytest.fixture
def strategy(mock_components):
    return V7PurpleReAbsStrategy(**mock_components)


class TestV7StrategyABC:
    """BaseStrategy 인터페이스 적합성 검증"""

    def test_isinstance_base_strategy(self, strategy):
        assert isinstance(strategy, BaseStrategy)

    def test_name(self, strategy):
        assert strategy.name == "V7_PURPLE_REABS"

    def test_detector_returns_signal_detector(self, strategy, mock_components):
        assert strategy.detector is mock_components["signal_detector"]

    def test_exit_handler_returns_exit_manager(self, strategy, mock_components):
        assert strategy.exit_handler is mock_components["exit_manager"]

    def test_str_repr(self, strategy):
        assert "V7_PURPLE_REABS" in str(strategy)
        assert "V7_PURPLE_REABS" in repr(strategy)


class TestV7ConditionSignal:
    """on_condition_signal() 동작 검증"""

    def test_registers_to_signal_pool(self, strategy, mock_components):
        result = strategy.on_condition_signal("005930", "삼성전자", {})
        assert result is True
        mock_components["signal_pool"].add.assert_called_once()
        call_args = mock_components["signal_pool"].add.call_args
        assert call_args[0][0] == "005930"
        assert call_args[0][1] == "삼성전자"

    def test_returns_false_without_pool(self):
        strategy = V7PurpleReAbsStrategy(
            signal_pool=None,
            signal_detector=None,
            dual_pass=None,
            watermark=None,
            exit_manager=None,
            notification_queue=None,
            missed_tracker=None,
            signal_coordinator=None,
        )
        result = strategy.on_condition_signal("005930", "삼성전자", {})
        assert result is False

    def test_metadata_included(self, strategy, mock_components):
        strategy.on_condition_signal("005930", "삼성전자", {"extra": "data"})
        call_args = mock_components["signal_pool"].add.call_args
        metadata = call_args[1]["metadata"]
        assert metadata["source"] == "condition_search"
        assert metadata["extra"] == "data"


class TestV7CandleComplete:
    """on_candle_complete() 동작 검증"""

    def test_returns_none(self, strategy):
        """V7은 DualPass에서 처리하므로 None 반환"""
        result = strategy.on_candle_complete("005930", None, {})
        assert result is None


class TestV7PositionLifecycle:
    """on_position_opened/closed() 동작 검증"""

    def test_position_opened_initializes_exit_state(self, strategy):
        exit_coordinator = MagicMock()
        exit_state = MagicMock()
        exit_state.get_fallback_stop.return_value = 48000
        exit_coordinator.initialize_v7_state.return_value = exit_state

        strategy.on_position_opened(
            "005930", 50000,
            {"exit_coordinator": exit_coordinator},
        )

        exit_coordinator.initialize_v7_state.assert_called_once()

    def test_position_closed_cleans_exit_state(self, strategy):
        exit_coordinator = MagicMock()

        strategy.on_position_closed(
            "005930",
            {"exit_coordinator": exit_coordinator},
        )

        exit_coordinator.cleanup_v7_state.assert_called_once_with("005930")


class TestV7Status:
    """get_status() 동작 검증"""

    def test_status_includes_pool_size(self, strategy, mock_components):
        status = strategy.get_status()
        assert status["name"] == "V7_PURPLE_REABS"
        assert status["signal_pool_size"] == 5

    def test_status_includes_coordinator(self, strategy):
        status = strategy.get_status()
        assert status["coordinator_active"] is True


class TestV7DailyReset:
    """on_daily_reset() 동작 검증"""

    def test_clears_pool_and_tracker(self, strategy, mock_components):
        strategy.on_daily_reset()
        mock_components["signal_pool"].clear.assert_called_once()
        mock_components["missed_tracker"].clear.assert_called_once()
        mock_components["notification_queue"].clear_cooldowns.assert_called_once()


class TestV7Shutdown:
    """on_shutdown() 동작 검증"""

    def test_clears_notification_queue(self, strategy, mock_components):
        strategy.on_shutdown()
        mock_components["notification_queue"].clear.assert_called_once()
