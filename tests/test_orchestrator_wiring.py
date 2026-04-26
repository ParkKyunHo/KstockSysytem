"""
StrategyOrchestrator 연결 테스트 (Phase 3)

BaseStrategy 기반 디스패치와 전략 라이프사이클을 검증합니다.
"""

import pytest
from unittest.mock import MagicMock, patch
import asyncio

from src.core.strategy_orchestrator import StrategyOrchestrator, StrategyConfig, StrategyState
from src.core.strategies.base_strategy import BaseStrategy
from src.core.strategies.v6_sniper_trap import V6SniperTrapStrategy
from src.core.strategies.v7_purple_reabs import V7PurpleReAbsStrategy
from src.core.detectors.base_detector import BaseDetector
from src.core.exit.base_exit import BaseExit
from src.core.signals.base_signal import StrategyType


# ===== BaseStrategy 등록/조회 =====

class TestBaseStrategyRegistration:
    """BaseStrategy 등록 및 조회 테스트"""

    def test_register_base_strategy(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "TEST_STRATEGY"
        strategy.detector = MagicMock(spec=BaseDetector)
        strategy.exit_handler = MagicMock(spec=BaseExit)

        result = orchestrator.register_base_strategy(strategy)
        assert result is True

    def test_register_duplicate_fails(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "TEST_STRATEGY"
        strategy.detector = None
        strategy.exit_handler = None

        orchestrator.register_base_strategy(strategy)
        result = orchestrator.register_base_strategy(strategy)
        assert result is False

    def test_get_base_strategy(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "TEST_STRATEGY"
        strategy.detector = None
        strategy.exit_handler = None

        orchestrator.register_base_strategy(strategy)
        retrieved = orchestrator.get_base_strategy("TEST_STRATEGY")
        assert retrieved is strategy

    def test_get_base_strategy_not_found(self):
        orchestrator = StrategyOrchestrator()
        assert orchestrator.get_base_strategy("NONEXISTENT") is None

    def test_register_creates_strategy_config(self):
        """BaseStrategy 등록 시 StrategyConfig도 생성되는지 확인"""
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = MagicMock(spec=BaseDetector)
        strategy.exit_handler = MagicMock(spec=BaseExit)

        orchestrator.register_base_strategy(strategy, priority=10)

        config = orchestrator.get_strategy("V7_PURPLE_REABS")
        assert config is not None
        assert config.priority == 10
        assert config.state == StrategyState.ENABLED


# ===== 포지션-전략 매핑 =====

class TestPositionStrategyMapping:
    """포지션-전략 매핑 테스트"""

    def test_register_position_strategy(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None

        orchestrator.register_base_strategy(strategy)
        orchestrator.register_position_strategy("005930", "V7_PURPLE_REABS")

        found = orchestrator.get_strategy_for_stock("005930")
        assert found is strategy

    def test_unregister_position_strategy(self):
        orchestrator = StrategyOrchestrator()
        orchestrator.register_position_strategy("005930", "V7_PURPLE_REABS")
        orchestrator.unregister_position_strategy("005930")
        assert orchestrator.get_strategy_for_stock("005930") is None


# ===== 조건검색 신호 디스패치 =====

class TestConditionSignalDispatch:
    """조건검색 신호 디스패치 테스트"""

    def test_dispatch_to_first_handler(self):
        orchestrator = StrategyOrchestrator()

        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None
        strategy.on_condition_signal.return_value = True

        orchestrator.register_base_strategy(strategy)

        result = orchestrator.dispatch_condition_signal("005930", "삼성전자", {})
        assert result == "V7_PURPLE_REABS"
        strategy.on_condition_signal.assert_called_once_with("005930", "삼성전자", {})

    def test_dispatch_skips_disabled(self):
        orchestrator = StrategyOrchestrator()

        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None
        strategy.on_condition_signal.return_value = True

        orchestrator.register_base_strategy(strategy)
        orchestrator.disable_strategy("V7_PURPLE_REABS")

        result = orchestrator.dispatch_condition_signal("005930", "삼성전자", {})
        assert result is None
        strategy.on_condition_signal.assert_not_called()

    def test_dispatch_returns_none_when_unhandled(self):
        orchestrator = StrategyOrchestrator()

        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None
        strategy.on_condition_signal.return_value = False

        orchestrator.register_base_strategy(strategy)

        result = orchestrator.dispatch_condition_signal("005930", "삼성전자", {})
        assert result is None


# ===== 포지션 라이프사이클 =====

class TestPositionLifecycle:
    """포지션 라이프사이클 디스패치 테스트"""

    def test_dispatch_position_opened(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None

        orchestrator.register_base_strategy(strategy)
        orchestrator.register_position_strategy("005930", "V7_PURPLE_REABS")

        orchestrator.dispatch_position_opened("005930", 50000, {})
        strategy.on_position_opened.assert_called_once_with("005930", 50000, {})



# ===== 백그라운드 태스크 =====

class TestBackgroundTasks:
    """백그라운드 태스크 수집 테스트"""

    def test_collect_background_tasks(self):
        orchestrator = StrategyOrchestrator()
        mock_task = MagicMock()

        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None
        strategy.get_background_tasks.return_value = [mock_task]

        orchestrator.register_base_strategy(strategy)
        tasks = orchestrator.collect_background_tasks({})

        assert len(tasks) == 1
        assert tasks[0] is mock_task

    def test_collect_empty_when_disabled(self):
        orchestrator = StrategyOrchestrator()

        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None
        strategy.get_background_tasks.return_value = [MagicMock()]

        orchestrator.register_base_strategy(strategy)
        orchestrator.disable_strategy("V7_PURPLE_REABS")

        tasks = orchestrator.collect_background_tasks({})
        assert len(tasks) == 0


# ===== 종료/리셋 =====

class TestShutdownAndReset:
    """종료 및 일일 리셋 테스트"""

    def test_dispatch_daily_reset(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None

        orchestrator.register_base_strategy(strategy)
        orchestrator.dispatch_daily_reset()
        strategy.on_daily_reset.assert_called_once()

    def test_dispatch_shutdown(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None

        orchestrator.register_base_strategy(strategy)
        orchestrator.dispatch_shutdown()
        strategy.on_shutdown.assert_called_once()


# ===== 통합 상태 =====

class TestAllStrategyStatus:
    """통합 상태 조회 테스트"""

    def test_get_all_strategy_status(self):
        orchestrator = StrategyOrchestrator()
        strategy = MagicMock(spec=BaseStrategy)
        strategy.name = "V7_PURPLE_REABS"
        strategy.detector = None
        strategy.exit_handler = None
        strategy.get_status.return_value = {"name": "V7_PURPLE_REABS", "pool_size": 5}

        orchestrator.register_base_strategy(strategy)
        orchestrator.register_position_strategy("005930", "V7_PURPLE_REABS")

        status = orchestrator.get_all_strategy_status()
        assert "strategy_details" in status
        assert "V7_PURPLE_REABS" in status["strategy_details"]
        assert status["strategy_details"]["V7_PURPLE_REABS"]["pool_size"] == 5
        assert status["position_strategies"]["005930"] == "V7_PURPLE_REABS"


# ===== V6/V7 어댑터 연동 테스트 =====

class TestV6AdapterIntegration:
    """V6SniperTrapStrategy 어댑터 연동 테스트"""

    def test_v6_strategy_registration(self):
        orchestrator = StrategyOrchestrator()
        v6 = V6SniperTrapStrategy(
            signal_detector=MagicMock(),
            exit_manager=MagicMock(spec=BaseExit),
            auto_screener=MagicMock(),
        )

        result = orchestrator.register_base_strategy(v6, priority=200)
        assert result is True

        config = orchestrator.get_strategy("V6_SNIPER_TRAP")
        assert config is not None
        assert config.priority == 200


class TestV7AdapterIntegration:
    """V7PurpleReAbsStrategy 어댑터 연동 테스트"""

    def test_v7_strategy_registration(self):
        orchestrator = StrategyOrchestrator()
        v7 = V7PurpleReAbsStrategy(
            signal_pool=MagicMock(),
            signal_detector=MagicMock(spec=BaseDetector),
            dual_pass=MagicMock(),
            watermark=MagicMock(),
            exit_manager=MagicMock(spec=BaseExit),
            notification_queue=MagicMock(),
            missed_tracker=MagicMock(),
            signal_coordinator=MagicMock(),
        )

        result = orchestrator.register_base_strategy(v7, priority=10)
        assert result is True

        config = orchestrator.get_strategy("V7_PURPLE_REABS")
        assert config is not None
        assert config.priority == 10

    def test_v7_condition_signal_dispatch(self):
        orchestrator = StrategyOrchestrator()
        mock_pool = MagicMock()
        mock_pool.add.return_value = True

        v7 = V7PurpleReAbsStrategy(
            signal_pool=mock_pool,
            signal_detector=MagicMock(spec=BaseDetector),
            dual_pass=MagicMock(),
            watermark=MagicMock(),
            exit_manager=MagicMock(spec=BaseExit),
            notification_queue=MagicMock(),
            missed_tracker=MagicMock(),
            signal_coordinator=MagicMock(),
        )

        orchestrator.register_base_strategy(v7)
        result = orchestrator.dispatch_condition_signal("005930", "삼성전자", {"test": True})
        assert result == "V7_PURPLE_REABS"
        mock_pool.add.assert_called_once()
