"""
TradingEngine 통합 테스트

테스트 항목:
1. TradingEngine 초기화 (DataManager 포함)
2. 종목 등록 흐름
3. 콜백 핸들러 연결
"""

import asyncio
import sys
sys.path.insert(0, ".")

from unittest.mock import AsyncMock, MagicMock, patch

from src.utils.logger import setup_logging, get_logger


async def test_engine_initialization():
    """TradingEngine 초기화 테스트"""
    print("\n=== TradingEngine 초기화 테스트 ===")

    # Mock 객체 생성
    mock_api_client = MagicMock()
    mock_api_client._rate_limiter = MagicMock()

    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()
    mock_telegram.send_promotion_choice = AsyncMock()

    mock_websocket = MagicMock()

    # TradingEngine import 및 생성
    from src.core.trading_engine import TradingEngine, EngineConfig
    from src.core.risk_manager import RiskConfig
    from src.core.universe import UniverseConfig

    engine_config = EngineConfig()
    risk_config = RiskConfig()
    universe_config = UniverseConfig()

    engine = TradingEngine(
        api_client=mock_api_client,
        telegram=mock_telegram,
        websocket=mock_websocket,
        config=engine_config,
        risk_config=risk_config,
        universe_config=universe_config,
    )

    print(f"  엔진 상태: {engine.state.value}")
    print(f"  DataManager 존재: {engine._data_manager is not None}")
    print(f"  구독자 수: {len(engine._data_manager._subscribers)}")

    assert engine._data_manager is not None
    assert len(engine._data_manager._subscribers) == 1
    print("  [PASS] TradingEngine 초기화 성공")

    print("\n=== TradingEngine 초기화 테스트 완료 ===")
    return engine


async def test_data_manager_subscription():
    """DataManager 구독 테스트"""
    print("\n=== DataManager 구독 테스트 ===")

    # Mock 객체 생성
    mock_api_client = MagicMock()
    mock_api_client._rate_limiter = MagicMock()

    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()

    mock_websocket = MagicMock()

    from src.core.trading_engine import TradingEngine, EngineConfig
    from src.core.risk_manager import RiskConfig
    from src.core.universe import UniverseConfig
    from src.core.realtime_data_manager import PriceData, Tier

    engine_config = EngineConfig()
    risk_config = RiskConfig()
    universe_config = UniverseConfig()

    engine = TradingEngine(
        api_client=mock_api_client,
        telegram=mock_telegram,
        websocket=mock_websocket,
        config=engine_config,
        risk_config=risk_config,
        universe_config=universe_config,
    )

    # DataManager에 종목 등록
    engine._data_manager.register_stock("005930", tier=Tier.TIER_2)
    engine._data_manager.register_stock("000660", tier=Tier.TIER_2)

    print(f"  Tier 2 종목: {engine._data_manager._tier2_stocks}")
    assert "005930" in engine._data_manager._tier2_stocks
    assert "000660" in engine._data_manager._tier2_stocks
    print("  [PASS] DataManager 종목 등록 성공")

    # Tier 1 승격 테스트
    await engine._data_manager.promote_to_tier1("005930")
    print(f"  승격 후 Tier 1: {engine._data_manager._tier1_stocks}")
    assert "005930" in engine._data_manager._tier1_stocks
    print("  [PASS] Tier 1 승격 성공")

    print("\n=== DataManager 구독 테스트 완료 ===")


async def test_telegram_callback_handlers():
    """텔레그램 콜백 핸들러 테스트"""
    print("\n=== 텔레그램 콜백 핸들러 테스트 ===")

    from src.notification.telegram import TelegramBot

    bot = TelegramBot()
    handler_called = []

    # 콜백 핸들러 등록
    async def on_promote(chat_id: str, args: list):
        handler_called.append(("promote", args[0] if args else None))
        print(f"  promote 핸들러 호출: {args}")

    async def on_hold(chat_id: str, args: list):
        handler_called.append(("hold", args[0] if args else None))
        print(f"  hold 핸들러 호출: {args}")

    bot.register_prefix_callback("promote", on_promote)
    bot.register_prefix_callback("hold", on_hold)

    print(f"  등록된 콜백: {list(bot._callback_handlers.keys())}")
    assert "promote:" in bot._callback_handlers
    assert "hold:" in bot._callback_handlers
    print("  [PASS] 프리픽스 콜백 등록 성공")

    # 콜백 직접 호출 테스트
    await bot._callback_handlers["promote:"]("chat_123", ["005930"])
    await bot._callback_handlers["hold:"]("chat_123", ["000660"])

    assert len(handler_called) == 2
    assert handler_called[0] == ("promote", "005930")
    assert handler_called[1] == ("hold", "000660")
    print("  [PASS] 콜백 핸들러 호출 성공")

    print("\n=== 텔레그램 콜백 핸들러 테스트 완료 ===")


async def test_status_text():
    """상태 텍스트 생성 테스트"""
    print("\n=== 상태 텍스트 생성 테스트 ===")

    mock_api_client = MagicMock()
    mock_api_client._rate_limiter = MagicMock()

    mock_telegram = MagicMock()
    mock_telegram.send_message = AsyncMock()

    mock_websocket = MagicMock()

    from src.core.trading_engine import TradingEngine, EngineConfig
    from src.core.risk_manager import RiskConfig
    from src.core.universe import UniverseConfig

    engine_config = EngineConfig()
    risk_config = RiskConfig()
    universe_config = UniverseConfig()

    engine = TradingEngine(
        api_client=mock_api_client,
        telegram=mock_telegram,
        websocket=mock_websocket,
        config=engine_config,
        risk_config=risk_config,
        universe_config=universe_config,
    )

    status = engine.get_status_text()
    print(status)

    assert "상태" in status
    print("  [PASS] 상태 텍스트 생성 성공")

    # DataManager 요약
    dm_summary = engine._data_manager.get_summary()
    print(dm_summary)
    assert "RealTimeDataManager" in dm_summary
    print("  [PASS] DataManager 요약 생성 성공")

    print("\n=== 상태 텍스트 생성 테스트 완료 ===")


async def main():
    """메인 테스트 실행"""
    setup_logging()

    print("=" * 50)
    print("TradingEngine 통합 테스트 시작")
    print("=" * 50)

    try:
        await test_engine_initialization()
        await test_data_manager_subscription()
        await test_telegram_callback_handlers()
        await test_status_text()

        print("\n" + "=" * 50)
        print("모든 테스트 통과!")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n[FAIL] 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n[ERROR] 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    import platform
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
