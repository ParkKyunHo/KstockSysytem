"""
RealTimeDataManager 통합 테스트

테스트 항목:
1. Tier 등록/해제 동작
2. 승격/강등 로직
3. 구독자 콜백 연결
4. Rate Limiting 동작
"""

import asyncio
import sys
sys.path.insert(0, ".")

from datetime import datetime
from src.core.realtime_data_manager import RealTimeDataManager, PriceData, Tier
from src.utils.logger import setup_logging, get_logger


async def test_tier_management():
    """Tier 관리 테스트"""
    print("\n=== Tier 관리 테스트 ===")

    # RealTimeDataManager 생성 (websocket=None, market_api=None for testing)
    manager = RealTimeDataManager(websocket=None, market_api=None)

    # 1. Tier 2 등록
    manager.register_stock("005930", tier=Tier.TIER_2)
    manager.register_stock("000660", tier=Tier.TIER_2)
    print(f"Tier 2 등록: {manager._tier2_stocks}")
    assert "005930" in manager._tier2_stocks
    assert "000660" in manager._tier2_stocks
    print("  [PASS] Tier 2 등록 성공")

    # 2. Tier 1 승격
    manager.promote_to_tier1("005930")
    print(f"Tier 1 승격 후: Tier1={manager._tier1_stocks}, Tier2={manager._tier2_stocks}")
    assert "005930" in manager._tier1_stocks
    assert "005930" not in manager._tier2_stocks
    print("  [PASS] Tier 1 승격 성공")

    # 3. Tier 2 강등
    manager.demote_to_tier2("005930")
    print(f"Tier 2 강등 후: Tier1={manager._tier1_stocks}, Tier2={manager._tier2_stocks}")
    assert "005930" not in manager._tier1_stocks
    assert "005930" in manager._tier2_stocks
    print("  [PASS] Tier 2 강등 성공")

    # 4. 종목 해제
    manager.unregister_stock("005930")
    print(f"해제 후: Tier1={manager._tier1_stocks}, Tier2={manager._tier2_stocks}")
    assert "005930" not in manager._tier1_stocks
    assert "005930" not in manager._tier2_stocks
    print("  [PASS] 종목 해제 성공")

    # 5. 중복 등록 방지
    manager.register_stock("000660", tier=Tier.TIER_1)  # 기존 Tier2에서 Tier1로
    assert "000660" in manager._tier1_stocks
    assert "000660" not in manager._tier2_stocks
    print("  [PASS] 중복 등록 방지 (Tier 이동)")

    print("\n=== Tier 관리 테스트 완료 ===")


async def test_subscriber_callback():
    """구독자 콜백 테스트"""
    print("\n=== 구독자 콜백 테스트 ===")

    manager = RealTimeDataManager(websocket=None, market_api=None)
    received_data = []

    async def on_price(data: PriceData):
        received_data.append(data)
        print(f"  콜백 수신: {data.stock_code} @ {data.current_price:,}원")

    # 구독자 등록
    manager.subscribe(on_price)
    print(f"구독자 수: {len(manager._subscribers)}")
    assert len(manager._subscribers) == 1

    # 브로드캐스트 테스트
    test_data = PriceData(
        stock_code="005930",
        stock_name="삼성전자",
        current_price=72000,
        volume=100000,
        timestamp=datetime.now(),
    )
    await manager._broadcast(test_data)

    assert len(received_data) == 1
    assert received_data[0].stock_code == "005930"
    print("  [PASS] 콜백 수신 성공")

    print("\n=== 구독자 콜백 테스트 완료 ===")


async def test_price_cache():
    """시세 캐시 테스트"""
    print("\n=== 시세 캐시 테스트 ===")

    manager = RealTimeDataManager(websocket=None, market_api=None)

    # 캐시에 직접 데이터 추가
    test_data = PriceData(
        stock_code="005930",
        stock_name="삼성전자",
        current_price=72000,
        volume=100000,
        timestamp=datetime.now(),
    )
    manager._price_cache["005930"] = test_data

    # 캐시 조회 (현재가만)
    cached_price = manager.get_price("005930")
    assert cached_price is not None
    assert cached_price == 72000
    print(f"  현재가 조회: {cached_price:,}원")
    print("  [PASS] 현재가 캐시 조회 성공")

    # 캐시 조회 (전체 데이터)
    cached_data = manager.get_price_data("005930")
    assert cached_data is not None
    assert cached_data.current_price == 72000
    print(f"  전체 데이터 조회: {cached_data.stock_code} @ {cached_data.current_price:,}원")
    print("  [PASS] 시세 데이터 캐시 조회 성공")

    # 없는 종목 조회
    no_cache = manager.get_price("999999")
    assert no_cache is None
    print("  [PASS] 없는 종목 캐시 조회 (None)")

    print("\n=== 시세 캐시 테스트 완료 ===")


async def test_summary():
    """요약 정보 테스트"""
    print("\n=== 요약 정보 테스트 ===")

    manager = RealTimeDataManager(websocket=None, market_api=None)

    manager.register_stock("005930", tier=Tier.TIER_1)
    manager.register_stock("000660", tier=Tier.TIER_1)
    manager.register_stock("035720", tier=Tier.TIER_2)
    manager.register_stock("035420", tier=Tier.TIER_2)
    manager.register_stock("051910", tier=Tier.TIER_2)

    summary = manager.get_summary()
    print(summary)

    assert "Tier 1" in summary
    assert "Tier 2" in summary
    print("  [PASS] 요약 정보 생성 성공")

    print("\n=== 요약 정보 테스트 완료 ===")


async def main():
    """메인 테스트 실행"""
    setup_logging()

    print("=" * 50)
    print("RealTimeDataManager 통합 테스트 시작")
    print("=" * 50)

    try:
        await test_tier_management()
        await test_subscriber_callback()
        await test_price_cache()
        await test_summary()

        print("\n" + "=" * 50)
        print("모든 테스트 통과!")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n[FAIL] 테스트 실패: {e}")
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
