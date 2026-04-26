"""
Phase 3 리팩토링: ExitCoordinator 단위 테스트

청산 조율기의 V6/V7 라우팅, V7 State 관리, Safety Net을 검증합니다.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.exit_coordinator import (
    ExitCoordinator,
    ExitCheckResult,
    ExitCoordinatorCallbacks,
    ExitSource,
)
from src.core.risk_manager import ExitReason
from src.core.wave_harvest_exit import PositionExitState


class MockPositionRisk:
    """테스트용 PositionRisk Mock"""
    def __init__(self, entry_price: int):
        self.entry_price = entry_price


class TestExitCoordinator:
    """ExitCoordinator 테스트"""

    def test_initialization(self):
        """초기화 테스트"""
        coordinator = ExitCoordinator()

        assert len(coordinator._v7_exit_states) == 0
        assert coordinator._stats["total_exits"] == 0

    def test_initialization_with_v7(self):
        """V7 컴포넌트 초기화 테스트"""
        mock_exit_manager = MagicMock()
        mock_v7_exit_manager = MagicMock()

        coordinator = ExitCoordinator(
            exit_manager=mock_exit_manager,
            v7_exit_manager=mock_v7_exit_manager,
        )

        assert coordinator._exit_manager is mock_exit_manager
        assert coordinator._v7_exit_manager is mock_v7_exit_manager


class TestExitCheckResult:
    """ExitCheckResult 테스트"""

    def test_default_values(self):
        """기본값 테스트"""
        result = ExitCheckResult()

        assert result.should_exit is False
        assert result.reason is None
        assert result.source is None
        assert result.profit_rate == 0.0

    def test_exit_result(self):
        """청산 결과 테스트"""
        result = ExitCheckResult(
            should_exit=True,
            reason=ExitReason.HARD_STOP,
            source=ExitSource.SAFETY_NET,
            profit_rate=-4.0,
        )

        assert result.should_exit is True
        assert result.reason == ExitReason.HARD_STOP
        assert result.source == ExitSource.SAFETY_NET

    def test_str_representation_exit(self):
        """문자열 표현 테스트 (청산)"""
        result = ExitCheckResult(
            should_exit=True,
            reason=ExitReason.HARD_STOP,
            source=ExitSource.SAFETY_NET,
            profit_rate=-4.0,
        )

        s = str(result)
        assert "EXIT" in s
        assert "HARD_STOP" in s
        assert "SAFETY_NET" in s

    def test_str_representation_hold(self):
        """문자열 표현 테스트 (보유)"""
        result = ExitCheckResult()

        s = str(result)
        assert "HOLD" in s


class TestSafetyNet:
    """Safety Net 테스트 (/ignore 종목)"""

    @pytest.mark.asyncio
    async def test_safety_net_triggers_at_minus_4_percent(self):
        """Safety Net -4% 손절 트리거 테스트"""
        coordinator = ExitCoordinator()

        callbacks = ExitCoordinatorCallbacks(
            get_position_risk=lambda x: MockPositionRisk(entry_price=10000),
            is_ignore_stock=lambda x: True,
        )

        # bar_low가 -4% 이하
        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=9700,
            callbacks=callbacks,
            bar_low=9500,  # -5%
        )

        assert result.should_exit is True
        assert result.reason == ExitReason.HARD_STOP
        # Risk-First: Hard Stop은 /ignore 라우팅 이전에 범용 검사에서 발동
        assert result.source == ExitSource.V6_EXIT_MANAGER
        assert coordinator._stats["hard_stop_exits"] == 1

    @pytest.mark.asyncio
    async def test_safety_net_holds_above_minus_4_percent(self):
        """Safety Net -4% 이상 시 보유 테스트"""
        coordinator = ExitCoordinator()

        callbacks = ExitCoordinatorCallbacks(
            get_position_risk=lambda x: MockPositionRisk(entry_price=10000),
            is_ignore_stock=lambda x: True,
        )

        # bar_low가 -4% 초과
        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=9700,
            callbacks=callbacks,
            bar_low=9700,  # -3%
        )

        assert result.should_exit is False


class TestV7ExitState:
    """V7 Exit State 관리 테스트"""

    def test_initialize_v7_state(self):
        """V7 State 초기화 테스트 (position_strategies 매핑 필요)"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")

        state = coordinator.initialize_v7_state("005930", 10000)

        assert state is not None
        assert coordinator.has_v7_state("005930") is True
        mock_v7_exit_manager.create_state.assert_called_once()

    def test_initialize_v7_state_no_mapping(self):
        """매핑 없으면 State 초기화 무시"""
        coordinator = ExitCoordinator()

        state = coordinator.initialize_v7_state("005930", 10000)

        assert state is None
        assert coordinator.has_v7_state("005930") is False

    def test_initialize_v7_state_already_exists(self):
        """V7 State 이미 존재 시 기존 반환"""
        mock_v7_exit_manager = MagicMock()
        existing_state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )
        mock_v7_exit_manager.create_state.return_value = existing_state

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")

        # 첫 번째 초기화
        coordinator.initialize_v7_state("005930", 10000)
        # 두 번째 초기화 (이미 존재)
        state = coordinator.initialize_v7_state("005930", 10000)

        assert state is existing_state
        assert mock_v7_exit_manager.create_state.call_count == 1

    def test_get_v7_state(self):
        """V7 State 조회 테스트"""
        mock_v7_exit_manager = MagicMock()
        mock_state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )
        mock_v7_exit_manager.create_state.return_value = mock_state

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)

        state = coordinator.get_v7_state("005930")

        assert state is mock_state

    def test_cleanup_v7_state(self):
        """V7 State 정리 테스트"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)

        coordinator.cleanup_v7_state("005930")

        assert coordinator.has_v7_state("005930") is False

    def test_get_all_v7_states(self):
        """모든 V7 State 조회 테스트"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.side_effect = [
            PositionExitState(stock_code="005930", entry_price=10000, entry_date=datetime.now()),
            PositionExitState(stock_code="000660", entry_price=20000, entry_date=datetime.now()),
        ]

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.register_position_strategy("000660", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)
        coordinator.initialize_v7_state("000660", 20000)

        states = coordinator.get_all_v7_states()

        assert len(states) == 2
        assert "005930" in states
        assert "000660" in states


class TestCheckExitRouting:
    """청산 체크 라우팅 테스트"""

    @pytest.mark.asyncio
    async def test_routes_to_safety_net_for_ignore_stocks(self):
        """ignore 종목은 Safety Net으로 라우팅"""
        coordinator = ExitCoordinator()

        callbacks = ExitCoordinatorCallbacks(
            is_ignore_stock=lambda x: True,
            get_position_risk=lambda x: MockPositionRisk(entry_price=10000),
        )

        # Safety Net 범위 내
        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=9700,
            callbacks=callbacks,
            bar_low=9700,
        )

        # Safety Net이 호출됨 (손절 미발동)
        assert result.should_exit is False

    @pytest.mark.asyncio
    async def test_routes_to_v7_for_v7_state(self):
        """V7 State + 매핑 존재 시 V7로 라우팅"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )
        mock_v7_exit_manager.check_hard_stop.return_value = False
        mock_v7_exit_manager.check_max_holding_days.return_value = False

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)

        callbacks = ExitCoordinatorCallbacks(
            is_ignore_stock=lambda x: False,
            has_position=lambda x: True,
            get_candle_data=lambda x: None,  # 캔들 데이터 없음
        )

        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=10500,
            callbacks=callbacks,
        )

        # V7 로직이 호출됨 (캔들 없어서 HOLD)
        assert result.should_exit is False

    @pytest.mark.asyncio
    async def test_routes_to_v6_without_mapping(self):
        """매핑 없으면 V6로 라우팅"""
        mock_exit_manager = AsyncMock()

        coordinator = ExitCoordinator(
            exit_manager=mock_exit_manager,
        )

        callbacks = ExitCoordinatorCallbacks(
            is_ignore_stock=lambda x: False,
        )

        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=10500,
            callbacks=callbacks,
        )

        mock_exit_manager.check_position_exit.assert_called_once()


class TestV7HardStop:
    """V7 Hard Stop 테스트"""

    @pytest.mark.asyncio
    async def test_v7_hard_stop_triggers(self):
        """V7 Hard Stop 트리거 테스트"""
        mock_v7_exit_manager = MagicMock()
        mock_state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )
        mock_v7_exit_manager.create_state.return_value = mock_state
        mock_v7_exit_manager.check_hard_stop.return_value = True

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)

        callbacks = ExitCoordinatorCallbacks(
            is_ignore_stock=lambda x: False,
            has_position=lambda x: True,
        )

        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=9500,
            callbacks=callbacks,
            bar_low=9500,
        )

        assert result.should_exit is True
        assert result.reason == ExitReason.HARD_STOP
        assert result.source == ExitSource.V7_WAVE_HARVEST
        assert coordinator._stats["hard_stop_exits"] == 1
        assert coordinator._stats["v7_exits"] == 1


class TestStatus:
    """상태 조회 테스트"""

    def test_get_status(self):
        """상태 조회 테스트"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)

        status = coordinator.get_status()

        assert status["v7_states_count"] == 1
        assert "005930" in status["v7_states"]
        assert "stats" in status

    def test_get_stats(self):
        """통계 조회 테스트"""
        coordinator = ExitCoordinator()

        stats = coordinator.get_stats()

        assert "total_exits" in stats
        assert "hard_stop_exits" in stats
        assert "v7_exits" in stats

    def test_str_representation(self):
        """문자열 표현 테스트"""
        coordinator = ExitCoordinator()

        s = str(coordinator)

        assert "ExitCoordinator" in s
        assert "states=" in s


# ===== Phase 3-3: 포지션-전략 매핑 테스트 =====

class TestPositionStrategyMapping:
    """Phase 3-3: 포지션-전략 매핑 기반 라우팅 테스트"""

    def test_register_position_strategy(self):
        """포지션-전략 매핑 등록"""
        coordinator = ExitCoordinator()
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")

        assert coordinator.get_position_strategy("005930") == "V7_PURPLE_REABS"

    def test_unregister_position_strategy(self):
        """포지션-전략 매핑 해제"""
        coordinator = ExitCoordinator()
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.unregister_position_strategy("005930")

        assert coordinator.get_position_strategy("005930") is None

    def test_get_all_position_strategies(self):
        """모든 포지션-전략 매핑 조회"""
        coordinator = ExitCoordinator()
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.register_position_strategy("000660", "V6_SNIPER_TRAP")

        strategies = coordinator.get_all_position_strategies()
        assert len(strategies) == 2
        assert strategies["005930"] == "V7_PURPLE_REABS"
        assert strategies["000660"] == "V6_SNIPER_TRAP"

    @pytest.mark.asyncio
    async def test_routes_v7_by_position_strategy(self):
        """포지션-전략 매핑으로 V7 라우팅"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )
        mock_v7_exit_manager.check_hard_stop.return_value = False
        mock_v7_exit_manager.check_max_holding_days.return_value = False

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        # 포지션-전략 매핑 등록
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        # V7 Exit State 초기화
        coordinator.initialize_v7_state("005930", 10000)

        callbacks = ExitCoordinatorCallbacks(
            is_ignore_stock=lambda x: False,
            has_position=lambda x: True,
            get_candle_data=lambda x: None,
        )

        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=10500,
            callbacks=callbacks,
        )

        # V7 로직이 호출됨 (캔들 없어서 HOLD)
        assert result.should_exit is False
        # check_hard_stop이 호출됨 = V7 경로 실행
        mock_v7_exit_manager.check_hard_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_v6_by_position_strategy(self):
        """포지션-전략 매핑으로 V6 라우팅"""
        mock_exit_manager = AsyncMock()

        coordinator = ExitCoordinator(
            exit_manager=mock_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V6_SNIPER_TRAP")

        callbacks = ExitCoordinatorCallbacks(
            is_ignore_stock=lambda x: False,
        )

        result = await coordinator.check_exit(
            stock_code="005930",
            current_price=10500,
            callbacks=callbacks,
        )

        # V6 ExitManager로 라우팅
        mock_exit_manager.check_position_exit.assert_called_once()

    def test_initialize_v7_state_with_position_strategy(self):
        """포지션-전략 매핑으로 V7 State 초기화"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        # 포지션-전략 매핑으로 V7 허용
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")

        state = coordinator.initialize_v7_state("005930", 10000)
        assert state is not None
        assert state.stock_code == "005930"

    def test_cleanup_v7_state_clears_mapping(self):
        """V7 State 정리 시 매핑도 해제됨"""
        mock_v7_exit_manager = MagicMock()
        mock_v7_exit_manager.create_state.return_value = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            entry_date=datetime.now(),
        )

        coordinator = ExitCoordinator(
            v7_exit_manager=mock_v7_exit_manager,
        )
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")
        coordinator.initialize_v7_state("005930", 10000)

        # cleanup V7 state
        coordinator.cleanup_v7_state("005930")

        # exit state는 정리됨
        assert coordinator.has_v7_state("005930") is False
        # 매핑도 해제됨
        assert coordinator.get_position_strategy("005930") is None

    def test_status_includes_position_strategies(self):
        """상태 조회에 position_strategies 포함"""
        coordinator = ExitCoordinator()
        coordinator.register_position_strategy("005930", "V7_PURPLE_REABS")

        status = coordinator.get_status()
        assert "position_strategies" in status
        assert status["position_strategies"]["005930"] == "V7_PURPLE_REABS"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
