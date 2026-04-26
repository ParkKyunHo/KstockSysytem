"""
BackgroundTaskManager 단위 테스트 (Phase 4-B)

백그라운드 태스크 시작, 루프 동작, 콜백 호출을 검증합니다.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, time, timedelta

from src.core.background_task_manager import BackgroundTaskManager, BackgroundTaskCallbacks

# 모든 루프 테스트에서 asyncio.sleep을 패치
SLEEP_PATCH = "src.core.background_task_manager.asyncio.sleep"


def _make_callbacks(**overrides) -> BackgroundTaskCallbacks:
    """테스트용 BackgroundTaskCallbacks 생성"""
    defaults = dict(
        get_engine_state=MagicMock(return_value="RUNNING"),
        check_and_handle_market_open=AsyncMock(),
        check_daily_reset=AsyncMock(),
        sync_positions=AsyncMock(),
        verify_tier1_consistency=AsyncMock(return_value=0),
        cancel_pending_orders_at_eod=AsyncMock(),
        get_market_status=MagicMock(return_value="REGULAR"),
        build_v7_callbacks=MagicMock(return_value=MagicMock()),
        collect_strategy_tasks=MagicMock(return_value=[]),
    )
    defaults.update(overrides)
    return BackgroundTaskCallbacks(**defaults)


def _engine_state_counter(run_count: int = 1):
    """run_count번 RUNNING 반환 후 STOPPED"""
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count > run_count:
            return "STOPPED"
        return "RUNNING"

    return side_effect


def _make_manager(**kwargs) -> BackgroundTaskManager:
    """테스트용 BackgroundTaskManager 생성"""
    callbacks = kwargs.pop("callbacks", _make_callbacks())
    risk_settings = kwargs.pop("risk_settings", MagicMock(
        auto_universe_enabled=False,
        ranking_update_interval=60,
    ))
    return BackgroundTaskManager(
        config=MagicMock(),
        risk_settings=risk_settings,
        position_manager=MagicMock(),
        risk_manager=MagicMock(),
        trade_repo=MagicMock(),
        data_manager=MagicMock(),
        market_schedule=MagicMock(),
        auto_screener=MagicMock(),
        strategy_orchestrator=None,
        universe=MagicMock(),
        market_api=AsyncMock(),
        candle_manager=MagicMock(),
        telegram=AsyncMock(),
        logger=MagicMock(),
        callbacks=callbacks,
    )


class TestBackgroundTaskManagerStartAll:
    """start_all() 태스크 생성 테스트"""

    @pytest.mark.asyncio
    async def test_start_all_creates_core_tasks(self):
        """핵심 태스크들이 생성되는지 확인"""
        mgr = _make_manager()
        mgr._callbacks.get_engine_state = MagicMock(return_value="STOPPED")

        tasks = []
        mgr.start_all(tasks)

        # 최소 6개 태스크 (eod_alert, eod_cleanup, status_monitor,
        # position_sync, highest_price, market_open_scheduler)
        assert len(tasks) >= 6

        for t in tasks:
            t.cancel()

    @pytest.mark.asyncio
    async def test_start_all_adds_ranking_when_auto_universe(self):
        """auto_universe 활성화 시 ranking/watchlist 태스크 추가"""
        risk_settings = MagicMock(
            auto_universe_enabled=True,
            ranking_update_interval=60,
        )
        mgr = _make_manager(risk_settings=risk_settings)
        mgr._callbacks.get_engine_state = MagicMock(return_value="STOPPED")

        tasks = []
        mgr.start_all(tasks)

        # auto_universe 활성화 시 ranking + watchlist 추가로 2개 더
        assert len(tasks) >= 8

        for t in tasks:
            t.cancel()

    @pytest.mark.asyncio
    async def test_start_all_adds_strategy_tasks(self):
        """StrategyOrchestrator가 있으면 전략 태스크 추가"""
        mock_task = asyncio.ensure_future(asyncio.sleep(0))

        callbacks = _make_callbacks(
            collect_strategy_tasks=MagicMock(return_value=[mock_task]),
        )
        mgr = _make_manager(callbacks=callbacks)
        mgr._strategy_orchestrator = MagicMock()
        mgr._callbacks.get_engine_state = MagicMock(return_value="STOPPED")

        tasks = []
        mgr.start_all(tasks)

        assert mock_task in tasks

        for t in tasks:
            t.cancel()

    @pytest.mark.asyncio
    async def test_start_all_with_orchestrator_strategy_tasks(self):
        """StrategyOrchestrator 경로: 전략 태스크가 추가됨 (V7 레거시 대체)"""
        mock_task = asyncio.ensure_future(asyncio.sleep(0))

        callbacks = _make_callbacks(
            collect_strategy_tasks=MagicMock(return_value=[mock_task]),
        )
        mgr = _make_manager(callbacks=callbacks)
        mgr._strategy_orchestrator = MagicMock()
        mgr._callbacks.get_engine_state = MagicMock(return_value="STOPPED")

        tasks = []
        mgr.start_all(tasks)

        # 전략 태스크가 포함되어야 함
        assert mock_task in tasks

        for t in tasks:
            t.cancel()


class TestPositionSyncLoop:
    """포지션 동기화 루프 테스트"""

    @pytest.mark.asyncio
    async def test_position_sync_calls_callbacks(self):
        """동기화 루프가 sync_positions + verify_tier1_consistency 호출"""
        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(2))
        mgr = _make_manager(callbacks=callbacks)

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            with patch("src.utils.config.get_risk_settings") as mock_settings:
                mock_settings.return_value.position_sync_interval = 1
                await mgr._position_sync_loop()

        callbacks.sync_positions.assert_called()
        callbacks.verify_tier1_consistency.assert_called()

    @pytest.mark.asyncio
    async def test_position_sync_skips_when_paused(self):
        """PAUSED 상태일 때 동기화 스킵"""
        call_count = 0

        def state_fn():
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                return "STOPPED"
            return "PAUSED"

        callbacks = _make_callbacks(get_engine_state=state_fn)
        mgr = _make_manager(callbacks=callbacks)

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            with patch("src.utils.config.get_risk_settings") as mock_settings:
                mock_settings.return_value.position_sync_interval = 1
                await mgr._position_sync_loop()

        callbacks.sync_positions.assert_not_called()


class TestHighestPricePersistLoop:
    """highest_price 저장 루프 테스트"""

    @pytest.mark.asyncio
    async def test_highest_price_skips_when_not_running(self):
        """RUNNING이 아닐 때 스킵"""
        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(0))

        # PAUSED만 반환하다 종료
        call_count = 0

        def state_fn():
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                return "STOPPED"
            return "PAUSED"

        callbacks.get_engine_state = state_fn

        mgr = _make_manager(callbacks=callbacks)

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            await mgr._highest_price_persist_loop()

        mgr._trade_repo.update_highest_price.assert_not_called()

    @pytest.mark.asyncio
    async def test_highest_price_persists_partial_exit(self):
        """분할 익절 포지션의 highest_price 저장"""
        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(2))
        mgr = _make_manager(callbacks=callbacks)

        # 분할 익절 포지션 설정
        mock_risk = MagicMock()
        mock_risk.is_partial_exit = True
        mock_risk.highest_price = 55000
        mgr._risk_manager.get_all_position_risks = MagicMock(
            return_value={"005930": mock_risk}
        )

        mock_position = MagicMock()
        mock_position.signal_metadata = {"trade_id": 42}
        mgr._position_manager.get_position = MagicMock(return_value=mock_position)

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            await mgr._highest_price_persist_loop()

        mgr._trade_repo.update_highest_price.assert_called_with(
            trade_id=42,
            highest_price=55000,
        )

    @pytest.mark.asyncio
    async def test_highest_price_skips_no_trade_repo(self):
        """trade_repo 없을 때 스킵"""
        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(2))
        mgr = _make_manager(callbacks=callbacks)
        mgr._trade_repo = None

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            await mgr._highest_price_persist_loop()

        # No error raised


class TestStatusMonitorLoop:
    """상태 모니터링 루프 테스트"""

    @pytest.mark.asyncio
    async def test_status_monitor_calls_daily_reset(self):
        """상태 모니터가 일일 리셋 체크를 호출"""
        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(2))
        mgr = _make_manager(callbacks=callbacks)
        mgr._data_manager.total_count = 5
        mgr._data_manager.tier1_count = 3
        mgr._data_manager.tier2_count = 2

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            await mgr._status_monitor_loop()

        callbacks.check_daily_reset.assert_called()

    @pytest.mark.asyncio
    async def test_status_monitor_alerts_empty_universe(self):
        """종목 0개일 때 경고 알림 전송"""
        from src.core.market_schedule import MarketState

        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(2))
        mgr = _make_manager(callbacks=callbacks)
        mgr._data_manager.total_count = 0
        mgr._data_manager.tier1_count = 0
        mgr._data_manager.tier2_count = 0
        mgr._market_schedule.get_state = MagicMock(return_value=MarketState.OPEN)

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            await mgr._status_monitor_loop()

        # 장중 + 종목 없음 → 텔레그램 경고
        mgr._telegram.send_message.assert_called()


class TestEodPendingOrderCleanupLoop:
    """미체결 주문 정리 루프 테스트"""

    @pytest.mark.asyncio
    async def test_eod_cleanup_calls_cancel_callback(self):
        """cleanup 시간 도달 시 cancel_pending_orders_at_eod 호출"""
        callbacks = _make_callbacks(get_engine_state=_engine_state_counter(1))
        mgr = _make_manager(callbacks=callbacks)

        # cleanup 시간을 현재 직후로 설정
        now = datetime.now()
        # 현재 시간 + 0.001초로 설정하면 sleep(wait_seconds)가 거의 즉시 완료
        future_time = (now + timedelta(seconds=1)).time()
        mgr._config.eod_pending_cleanup_time = future_time

        with patch(SLEEP_PATCH, new_callable=AsyncMock):
            await mgr._eod_pending_order_cleanup_loop()

        callbacks.cancel_pending_orders_at_eod.assert_called_once()


class TestRegisterPromotedWatchlistStock:
    """Watchlist 승격 종목 등록 테스트"""

    @pytest.mark.asyncio
    async def test_skip_if_already_in_universe(self):
        """이미 Universe에 있으면 스킵"""
        mgr = _make_manager()
        mgr._universe.is_in_universe = MagicMock(return_value=True)

        await mgr._register_promoted_watchlist_stock("005930")

        mgr._universe.add_stock.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_new_stock(self):
        """새 종목 Universe 등록"""
        mgr = _make_manager()
        mgr._universe.is_in_universe = MagicMock(return_value=False)
        mgr._auto_screener.is_in_watchlist = MagicMock(return_value=False)
        mgr._market_api.get_stock_name = AsyncMock(return_value="삼성전자")
        mgr._auto_screener.is_active = MagicMock(return_value=False)
        mgr._candle_manager.get_builder = MagicMock(return_value=None)

        await mgr._register_promoted_watchlist_stock("005930")

        mgr._universe.add_stock.assert_called_once()
        call_kwargs = mgr._universe.add_stock.call_args[1]
        assert call_kwargs["stock_code"] == "005930"
        assert call_kwargs["stock_name"] == "삼성전자"

    @pytest.mark.asyncio
    async def test_register_active_stock_tier1(self):
        """Active Pool 종목은 Tier 1로 승격"""
        mgr = _make_manager()
        mgr._universe.is_in_universe = MagicMock(return_value=False)
        mgr._auto_screener.is_in_watchlist = MagicMock(return_value=False)
        mgr._market_api.get_stock_name = AsyncMock(return_value="삼성전자")
        mgr._auto_screener.is_active = MagicMock(return_value=True)
        mgr._candle_manager.get_builder = MagicMock(return_value=None)

        await mgr._register_promoted_watchlist_stock("005930")

        from src.core.realtime_data_manager import Tier
        mgr._data_manager.register_stock.assert_called_with("005930", Tier.TIER_1, "삼성전자")
        mgr._data_manager.promote_to_tier1.assert_called_with("005930")


class TestMarketOpenSchedulerLoop:
    """장 시작 스케줄러 루프 테스트"""

    @pytest.mark.asyncio
    async def test_scheduler_exits_when_stopped(self):
        """STOPPED 상태일 때 루프 종료"""
        callbacks = _make_callbacks(
            get_engine_state=MagicMock(return_value="STOPPED")
        )
        mgr = _make_manager(callbacks=callbacks)

        # 즉시 종료되어야 함
        await mgr._market_open_scheduler_loop()

        # STOPPED이므로 check_and_handle_market_open 호출 없음
        callbacks.check_and_handle_market_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_scheduler_handles_cancelled_error(self):
        """CancelledError 처리"""
        callbacks = _make_callbacks(get_engine_state=MagicMock(return_value="RUNNING"))
        mgr = _make_manager(callbacks=callbacks)

        with patch(SLEEP_PATCH, side_effect=asyncio.CancelledError):
            await mgr._market_open_scheduler_loop()

        # CancelledError로 종료됨 - 에러 없이 정상 종료


class TestOrchestratorIntegration:
    """StrategyOrchestrator 통합 테스트"""

    def test_no_v7_legacy_attributes(self):
        """V7 레거시 속성이 제거됨을 확인"""
        mgr = _make_manager()

        assert not hasattr(mgr, '_v7_enabled')
        assert not hasattr(mgr, '_v7_signal_coordinator')
