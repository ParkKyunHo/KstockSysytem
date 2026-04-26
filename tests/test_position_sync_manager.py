"""
Phase 3 리팩토링: PositionSyncManager 단위 테스트

HTS 매수/매도 감지, 수량 동기화, Tier 1 일관성 검증을 테스트합니다.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.position_sync_manager import (
    PositionSyncManager,
    PositionInfo,
    SyncCallbacks,
    SyncResult,
)
from src.core.position_manager import Position, EntrySource
from src.core.signal_detector import StrategyType


def create_mock_position(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    quantity: int = 10,
    entry_price: int = 50000,
    current_price: int = 51000,
) -> Position:
    """테스트용 Position 객체 생성"""
    pos = MagicMock(spec=Position)
    pos.stock_code = stock_code
    pos.stock_name = stock_name
    pos.quantity = quantity
    pos.entry_price = entry_price
    pos.current_price = current_price
    pos.signal_metadata = {"trade_id": "test_trade_123"}
    return pos


def create_position_info(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    quantity: int = 10,
    average_price: int = 50000,
) -> PositionInfo:
    """테스트용 PositionInfo 객체 생성"""
    return PositionInfo(
        stock_code=stock_code,
        stock_name=stock_name,
        quantity=quantity,
        average_price=average_price,
    )


class TestPositionSyncManager:
    """PositionSyncManager 기본 테스트"""

    def test_initialization(self):
        """초기화 테스트"""
        manager = PositionSyncManager()

        assert manager._sync_interval == 60
        assert manager._stats["total_syncs"] == 0
        assert manager._running is False

    def test_initialization_with_params(self):
        """커스텀 파라미터 초기화 테스트"""
        manager = PositionSyncManager(sync_interval=30)

        assert manager._sync_interval == 30


class TestSyncCallbacks:
    """SyncCallbacks 테스트"""

    def test_callbacks_default_none(self):
        """콜백 기본값 None 테스트"""
        callbacks = SyncCallbacks()

        assert callbacks.open_position is None
        assert callbacks.close_position is None
        assert callbacks.send_telegram is None

    def test_callbacks_with_functions(self):
        """콜백 함수 설정 테스트"""
        callbacks = SyncCallbacks(
            get_position=lambda x: None,
            is_tier1=lambda x: True,
        )

        assert callbacks.get_position("005930") is None
        assert callbacks.is_tier1("005930") is True


class TestReconcileWithApiBalance:
    """reconcile_with_api_balance 테스트"""

    @pytest.mark.asyncio
    async def test_detect_hts_buy(self):
        """HTS 매수 감지 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []

        async def mock_send(msg):
            telegram_messages.append(msg)

        api_positions = [
            create_position_info("005930", "삼성전자", 10, 50000),
        ]

        callbacks = SyncCallbacks(
            get_all_positions=lambda: [],  # 로컬에 없음
            send_telegram=mock_send,
        )

        result = await manager.reconcile_with_api_balance(api_positions, callbacks)

        assert result.new_positions == 1
        assert len(telegram_messages) == 1
        assert "HTS 보유 감지" in telegram_messages[0]

    @pytest.mark.asyncio
    async def test_detect_hts_sell(self):
        """HTS 매도 감지 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []

        async def mock_send(msg):
            telegram_messages.append(msg)

        local_position = create_mock_position("005930", "삼성전자")

        callbacks = SyncCallbacks(
            get_all_positions=lambda: [local_position],
            get_position=lambda x: local_position if x == "005930" else None,
            send_telegram=mock_send,
        )

        # API에 없음
        result = await manager.reconcile_with_api_balance([], callbacks)

        assert result.closed_positions == 1
        assert len(telegram_messages) == 1
        assert "HTS 매도 감지" in telegram_messages[0]

    @pytest.mark.asyncio
    async def test_detect_quantity_mismatch(self):
        """수량 불일치 감지 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []
        synced_quantities = {}

        async def mock_send(msg):
            telegram_messages.append(msg)

        def mock_sync_quantity(code, qty):
            synced_quantities[code] = qty

        local_position = create_mock_position("005930", "삼성전자", quantity=10)

        api_positions = [
            create_position_info("005930", "삼성전자", quantity=8, average_price=50000),
        ]

        callbacks = SyncCallbacks(
            get_all_positions=lambda: [local_position],
            get_position=lambda x: local_position if x == "005930" else None,
            sync_quantity=mock_sync_quantity,
            is_partial_exited=lambda x: False,
            send_telegram=mock_send,
        )

        result = await manager.reconcile_with_api_balance(api_positions, callbacks)

        assert result.quantity_changes == 1
        assert synced_quantities.get("005930") == 8


class TestSyncPositions:
    """sync_positions 테스트"""

    @pytest.mark.asyncio
    async def test_hts_buy_full_flow(self):
        """HTS 매수 전체 흐름 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []
        opened_positions = []
        tier1_registered = []

        async def mock_send(msg):
            telegram_messages.append(msg)

        async def mock_open_position(**kwargs):
            opened_positions.append(kwargs)

        def mock_register_tier1(code, name):
            tier1_registered.append(code)

        api_positions = [
            create_position_info("005930", "삼성전자", 10, 50000),
        ]

        callbacks = SyncCallbacks(
            get_position_codes=lambda: [],  # 로컬에 없음
            open_position=mock_open_position,
            on_risk_entry=lambda *args, **kwargs: None,
            add_candle_stock=lambda x: None,
            is_in_universe=lambda x: False,
            add_universe_stock=lambda *args: None,
            register_tier1=mock_register_tier1,
            get_position=lambda x: create_mock_position(),
            send_telegram=mock_send,
        )

        result = await manager.sync_positions(api_positions, callbacks)

        assert result.new_positions == 1
        assert len(opened_positions) == 1
        assert opened_positions[0]["stock_code"] == "005930"
        assert "005930" in tier1_registered
        assert manager._stats["hts_buys_detected"] == 1

    @pytest.mark.asyncio
    async def test_hts_sell_full_flow(self):
        """HTS 매도 전체 흐름 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []
        closed_positions = []

        async def mock_send(msg):
            telegram_messages.append(msg)

        async def mock_close_position(code, price, reason):
            closed_positions.append({"code": code, "price": price, "reason": reason})

        local_position = create_mock_position("005930", "삼성전자")

        callbacks = SyncCallbacks(
            get_position_codes=lambda: ["005930"],
            get_position=lambda x: local_position if x == "005930" else None,
            close_position=mock_close_position,
            on_risk_exit=lambda *args: None,
            send_telegram=mock_send,
        )

        # API에 없음
        result = await manager.sync_positions([], callbacks)

        assert result.closed_positions == 1
        assert len(closed_positions) == 1
        assert closed_positions[0]["code"] == "005930"
        assert manager._stats["hts_sells_detected"] == 1

    @pytest.mark.asyncio
    async def test_quantity_increase(self):
        """수량 증가 (추가 매수) 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []
        updated_quantities = {}

        async def mock_send(msg):
            telegram_messages.append(msg)

        def mock_update_quantity(code, qty):
            updated_quantities[code] = qty

        local_position = create_mock_position("005930", "삼성전자", quantity=10, entry_price=50000)

        api_positions = [
            create_position_info("005930", "삼성전자", quantity=15, average_price=51000),
        ]

        callbacks = SyncCallbacks(
            get_position_codes=lambda: ["005930"],
            get_position=lambda x: local_position if x == "005930" else None,
            update_quantity=mock_update_quantity,
            update_entry_price=lambda *args: None,
            sync_entry_price=lambda *args: False,
            send_telegram=mock_send,
        )

        result = await manager.sync_positions(api_positions, callbacks)

        assert result.quantity_changes == 1
        assert updated_quantities.get("005930") == 15
        assert "추가 매수" in telegram_messages[0]

    @pytest.mark.asyncio
    async def test_quantity_decrease(self):
        """수량 감소 (부분 매도) 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []
        updated_quantities = {}

        async def mock_send(msg):
            telegram_messages.append(msg)

        def mock_update_quantity(code, qty):
            updated_quantities[code] = qty

        local_position = create_mock_position("005930", "삼성전자", quantity=10)

        api_positions = [
            create_position_info("005930", "삼성전자", quantity=5, average_price=50000),
        ]

        callbacks = SyncCallbacks(
            get_position_codes=lambda: ["005930"],
            get_position=lambda x: local_position if x == "005930" else None,
            update_quantity=mock_update_quantity,
            sync_quantity=lambda *args: None,
            is_partial_exited=lambda x: False,
            send_telegram=mock_send,
        )

        result = await manager.sync_positions(api_positions, callbacks)

        assert result.quantity_changes == 1
        assert updated_quantities.get("005930") == 5
        assert "수량 감소" in telegram_messages[0]


class TestVerifyTier1Consistency:
    """verify_tier1_consistency 테스트"""

    @pytest.mark.asyncio
    async def test_all_registered(self):
        """모든 포지션이 Tier 1에 등록된 경우"""
        manager = PositionSyncManager()

        position = create_mock_position("005930", "삼성전자")

        callbacks = SyncCallbacks(
            get_all_positions=lambda: [position],
            is_tier1=lambda x: True,  # 이미 등록됨
        )

        recovered = await manager.verify_tier1_consistency(callbacks)

        assert recovered == 0

    @pytest.mark.asyncio
    async def test_missing_tier1_registration(self):
        """Tier 1 미등록 포지션 복구 테스트"""
        manager = PositionSyncManager()
        telegram_messages = []
        tier1_registered = []

        async def mock_send(msg):
            telegram_messages.append(msg)

        def mock_register_tier1(code, name):
            tier1_registered.append(code)

        position = create_mock_position("005930", "삼성전자")

        callbacks = SyncCallbacks(
            get_all_positions=lambda: [position],
            is_tier1=lambda x: False,  # 미등록
            register_tier1=mock_register_tier1,
            send_telegram=mock_send,
        )

        recovered = await manager.verify_tier1_consistency(callbacks)

        assert recovered == 1
        assert "005930" in tier1_registered
        assert "Tier 1 미등록" in telegram_messages[0]
        assert manager._stats["tier1_recovered"] == 1


class TestStats:
    """통계 테스트"""

    def test_get_stats(self):
        """통계 조회 테스트"""
        manager = PositionSyncManager()

        stats = manager.get_stats()

        assert "total_syncs" in stats
        assert "hts_buys_detected" in stats
        assert "hts_sells_detected" in stats

    def test_get_status(self):
        """상태 조회 테스트"""
        manager = PositionSyncManager(sync_interval=45)

        status = manager.get_status()

        assert status["running"] is False
        assert status["sync_interval"] == 45
        assert "stats" in status

    def test_str_representation(self):
        """문자열 표현 테스트"""
        manager = PositionSyncManager()

        s = str(manager)

        assert "PositionSyncManager" in s
        assert "syncs=" in s


class TestErrorHandling:
    """에러 처리 테스트"""

    @pytest.mark.asyncio
    async def test_reconcile_handles_exception(self):
        """reconcile_with_api_balance 예외 처리 테스트"""
        manager = PositionSyncManager()

        def raise_error():
            raise Exception("Test error")

        callbacks = SyncCallbacks(
            get_all_positions=raise_error,
        )

        result = await manager.reconcile_with_api_balance([], callbacks)

        assert len(result.errors) > 0
        assert manager._stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_sync_handles_exception(self):
        """sync_positions 예외 처리 테스트"""
        manager = PositionSyncManager()

        def raise_error():
            raise Exception("Test error")

        callbacks = SyncCallbacks(
            get_position_codes=raise_error,
        )

        result = await manager.sync_positions([], callbacks)

        assert len(result.errors) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
