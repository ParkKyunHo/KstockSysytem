"""
전체 시스템 통합 테스트

TradingEngine + WebSocket + 실시간 틱 데이터 통합을 테스트합니다.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.api.websocket import KiwoomWebSocket, TickData, ConditionInfo
from src.core.trading_engine import TradingEngine, EngineConfig, EngineState
from src.core.candle_builder import Tick, Timeframe
from src.core.risk_manager import RiskConfig
from src.core.universe import UniverseConfig
from src.notification.telegram import TelegramBot


class MockKiwoomWebSocket:
    """모의 WebSocket 클라이언트"""

    def __init__(self):
        self._connected = False
        self._subscribed_stocks = set()

        # 콜백
        self.on_tick = None
        self.on_connected = None
        self.on_disconnected = None
        self.on_signal = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        self._connected = True
        print("[MockWS] 연결됨")
        if self.on_connected:
            await self.on_connected()
        return True

    async def disconnect(self) -> None:
        self._connected = False
        self._subscribed_stocks.clear()
        print("[MockWS] 연결 해제")
        if self.on_disconnected:
            await self.on_disconnected()

    async def subscribe_tick(self, stock_codes: list[str]) -> None:
        self._subscribed_stocks.update(stock_codes)
        print(f"[MockWS] 틱 구독: {stock_codes}")

    async def unsubscribe_tick(self, stock_codes: list[str]) -> None:
        for code in stock_codes:
            self._subscribed_stocks.discard(code)
        print(f"[MockWS] 틱 구독 해제: {stock_codes}")

    async def unsubscribe_all_tick(self) -> None:
        self._subscribed_stocks.clear()
        print("[MockWS] 모든 틱 구독 해제")

    async def simulate_tick(self, tick_data: TickData) -> None:
        """틱 데이터 시뮬레이션"""
        if self.on_tick:
            await self.on_tick(tick_data)


class MockAPIClient:
    """모의 API 클라이언트"""

    def __init__(self):
        self.base_url = "https://mockapi.kiwoom.com"

    async def request(self, *args, **kwargs):
        return {}


class MockOrderAPI:
    """모의 주문 API"""

    async def buy(self, stock_code: str, quantity: int, **kwargs):
        result = MagicMock()
        result.success = True
        result.order_no = f"ORD-{datetime.now().strftime('%H%M%S')}"
        result.message = "주문 성공"
        print(f"[MockOrder] 매수: {stock_code}, {quantity}주")
        return result

    async def sell(self, stock_code: str, quantity: int, **kwargs):
        result = MagicMock()
        result.success = True
        result.order_no = f"ORD-{datetime.now().strftime('%H%M%S')}"
        result.message = "주문 성공"
        print(f"[MockOrder] 매도: {stock_code}, {quantity}주")
        return result


class MockAccountAPI:
    """모의 계좌 API"""

    async def get_balance(self):
        balance = MagicMock()
        balance.deposit = 10_000_000  # 1000만원
        balance.available_amount = 10_000_000
        return balance

    async def get_positions(self):
        summary = MagicMock()
        summary.positions = []  # 보유 종목 없음
        return summary


class MockMarketAPI:
    """모의 시세 API"""

    async def get_current_price(self, stock_code: str) -> int:
        # 임의의 가격 반환
        prices = {
            "005930": 72000,  # 삼성전자
            "000660": 120000,  # SK하이닉스
            "035720": 45000,  # 카카오
        }
        return prices.get(stock_code, 50000)

    async def get_condition_stocks(self) -> list:
        return []


class MockTelegram:
    """모의 텔레그램 봇"""

    def __init__(self):
        self.messages = []

    async def send_message(self, text: str, **kwargs) -> bool:
        self.messages.append(text)
        print(f"[Telegram] {text[:50]}...")
        return True

    async def send_eod_choice(self) -> bool:
        return True


async def test_websocket_tick_integration():
    """WebSocket 틱 데이터 통합 테스트"""
    print("\n" + "=" * 60)
    print("WebSocket 틱 데이터 통합 테스트")
    print("=" * 60)

    # 모의 객체 생성
    mock_ws = MockKiwoomWebSocket()
    mock_api = MockAPIClient()
    mock_telegram = MockTelegram()

    # TradingEngine 생성 (모의 컴포넌트 주입)
    engine_config = EngineConfig()
    risk_config = RiskConfig()

    # 엔진 생성 (실제 API 호출 없이 테스트)
    with patch('src.core.trading_engine.OrderAPI') as MockOrderAPIClass, \
         patch('src.core.trading_engine.MarketAPI') as MockMarketAPIClass, \
         patch('src.core.trading_engine.AccountAPI') as MockAccountAPIClass:

        MockOrderAPIClass.return_value = MockOrderAPI()
        MockMarketAPIClass.return_value = MockMarketAPI()
        MockAccountAPIClass.return_value = MockAccountAPI()

        engine = TradingEngine(
            api_client=mock_api,
            telegram=mock_telegram,
            websocket=mock_ws,
            config=engine_config,
            risk_config=risk_config,
        )

        # 유니버스에 테스트 종목 추가 (모의)
        engine._universe._stocks = {
            "005930": MagicMock(stock_code="005930", stock_name="삼성전자"),
            "000660": MagicMock(stock_code="000660", stock_name="SK하이닉스"),
        }

        print("\n1. WebSocket 연결 테스트")
        print("-" * 40)

        # WebSocket 연결 테스트
        await mock_ws.connect()
        assert mock_ws.is_connected, "WebSocket 연결 실패"
        print("[OK] WebSocket 연결 성공")

        # 틱 구독 테스트
        await mock_ws.subscribe_tick(["005930", "000660"])
        assert "005930" in mock_ws._subscribed_stocks
        assert "000660" in mock_ws._subscribed_stocks
        print("[OK] 틱 구독 성공")

        print("\n2. 틱 데이터 수신 테스트")
        print("-" * 40)

        # 틱 데이터 카운터
        tick_count = 0

        async def count_ticks(tick_data: TickData):
            nonlocal tick_count
            tick_count += 1
            print(f"  틱 수신: {tick_data.stock_code} @ {tick_data.price:,}원")

        mock_ws.on_tick = count_ticks

        # 틱 시뮬레이션
        test_ticks = [
            TickData("005930", "삼성전자", "093000", 72000, 500, 0.7, 1000, 50000, 3600000000),
            TickData("005930", "삼성전자", "093001", 72100, 600, 0.84, 500, 50500, 3642050000),
            TickData("000660", "SK하이닉스", "093002", 120000, 1000, 0.84, 200, 10000, 1200000000),
        ]

        for tick in test_ticks:
            await mock_ws.simulate_tick(tick)

        assert tick_count == 3, f"틱 수신 실패: {tick_count}/3"
        print(f"[OK] 틱 데이터 {tick_count}건 수신 완료")

        print("\n3. TradingEngine 틱 처리 테스트")
        print("-" * 40)

        # 엔진 상태를 RUNNING으로 변경
        engine._state = EngineState.RUNNING

        # 틱 처리 콜백 설정
        mock_ws.on_tick = engine._on_ws_tick

        # 틱 시뮬레이션
        for tick in test_ticks:
            await mock_ws.simulate_tick(tick)

        print(f"  수신 틱 수: {engine._stats['ticks_received']}")
        assert engine._stats['ticks_received'] == 3, "엔진 틱 수신 실패"
        print("[OK] TradingEngine 틱 처리 성공")

        # 캔들 빌더 확인
        builder_005930 = engine._candle_manager.get_builder("005930")
        builder_000660 = engine._candle_manager.get_builder("000660")

        if builder_005930:
            print(f"  005930 캔들 빌더 활성화")
        if builder_000660:
            print(f"  000660 캔들 빌더 활성화")

        print("\n4. WebSocket 연결 해제 테스트")
        print("-" * 40)

        await mock_ws.unsubscribe_all_tick()
        assert len(mock_ws._subscribed_stocks) == 0
        print("[OK] 구독 해제 성공")

        await mock_ws.disconnect()
        assert not mock_ws.is_connected
        print("[OK] 연결 해제 성공")

    print("\n[OK] WebSocket 틱 데이터 통합 테스트 완료")
    return True


async def test_tick_to_candle_flow():
    """틱 → 캔들 변환 플로우 테스트"""
    print("\n" + "=" * 60)
    print("틱 → 캔들 변환 플로우 테스트")
    print("=" * 60)

    from src.core.candle_builder import CandleBuilder, Tick
    from datetime import timedelta

    builder = CandleBuilder("005930")
    candles_completed = []

    # 봉 완성 콜백
    async def on_complete(stock_code: str, candle):
        candles_completed.append(candle)
        print(f"  [봉 완성] {candle.timeframe.value}: O={candle.open} C={candle.close} V={candle.volume}")

    builder.on_candle_complete_async = on_complete

    print("\n1. 60개 틱 생성 (1분봉 테스트)")
    print("-" * 40)

    base_time = datetime.now().replace(second=0, microsecond=0)
    base_price = 72000

    # 60개 틱 생성 (1분)
    import random
    for i in range(60):
        tick = Tick(
            stock_code="005930",
            price=base_price + random.randint(-200, 200),
            volume=random.randint(100, 1000),
            timestamp=base_time + timedelta(seconds=i),
        )
        await builder.on_tick_async(tick)

    # 1분 넘어가는 틱으로 봉 완성 트리거
    tick_next_minute = Tick(
        stock_code="005930",
        price=base_price,
        volume=100,
        timestamp=base_time + timedelta(minutes=1),
    )
    await builder.on_tick_async(tick_next_minute)

    print(f"\n  생성된 봉: {len(candles_completed)}개")

    # 현재 진행 중인 봉 확인
    current = builder.get_current_candle(Timeframe.M1)
    if current:
        print(f"  현재 1분봉: O={current.open} H={current.high} L={current.low} C={current.close}")

    print("\n[OK] 틱 → 캔들 변환 테스트 완료")
    return True


async def test_trading_engine_lifecycle():
    """TradingEngine 생명주기 테스트"""
    print("\n" + "=" * 60)
    print("TradingEngine 생명주기 테스트")
    print("=" * 60)

    mock_ws = MockKiwoomWebSocket()
    mock_api = MockAPIClient()
    mock_telegram = MockTelegram()

    with patch('src.core.trading_engine.OrderAPI') as MockOrderAPIClass, \
         patch('src.core.trading_engine.MarketAPI') as MockMarketAPIClass, \
         patch('src.core.trading_engine.AccountAPI') as MockAccountAPIClass:

        MockOrderAPIClass.return_value = MockOrderAPI()
        MockMarketAPIClass.return_value = MockMarketAPI()
        MockAccountAPIClass.return_value = MockAccountAPI()

        engine = TradingEngine(
            api_client=mock_api,
            telegram=mock_telegram,
            websocket=mock_ws,
        )

        print("\n1. 엔진 상태 확인")
        print("-" * 40)

        assert engine.state == EngineState.STOPPED
        print(f"  초기 상태: {engine.state.value}")

        print("\n2. 엔진 시작 (모의)")
        print("-" * 40)

        # 유니버스 모의 설정
        engine._universe._stocks = {
            "005930": MagicMock(stock_code="005930", stock_name="삼성전자"),
        }
        engine._universe._last_refresh = datetime.now()

        # start() 대신 직접 상태 변경 (API 호출 없이)
        engine._state = EngineState.RUNNING
        print(f"  상태 변경: {engine.state.value}")

        assert engine.is_running
        print("[OK] 엔진 RUNNING 상태")

        print("\n3. 일시 정지 테스트")
        print("-" * 40)

        await engine.pause()
        assert engine.state == EngineState.PAUSED
        print(f"  상태: {engine.state.value}")

        print("\n4. 재개 테스트")
        print("-" * 40)

        await engine.resume()
        assert engine.state == EngineState.RUNNING
        print(f"  상태: {engine.state.value}")

        print("\n5. 통계 확인")
        print("-" * 40)

        stats = engine.get_stats()
        print(f"  {stats}")

        print("\n6. 엔진 정지")
        print("-" * 40)

        engine._start_time = datetime.now()  # stop()에서 필요
        await engine.stop()
        assert engine.state == EngineState.STOPPED
        print(f"  상태: {engine.state.value}")

    print("\n[OK] TradingEngine 생명주기 테스트 완료")
    return True


async def main():
    """메인 테스트 함수"""
    print("\n" + "=" * 60)
    print("전체 시스템 통합 테스트")
    print("=" * 60)

    results = []

    try:
        results.append(("WebSocket 틱 통합", await test_websocket_tick_integration()))
    except Exception as e:
        print(f"[ERROR] WebSocket 틱 통합 테스트 실패: {e}")
        results.append(("WebSocket 틱 통합", False))

    try:
        results.append(("틱→캔들 변환", await test_tick_to_candle_flow()))
    except Exception as e:
        print(f"[ERROR] 틱→캔들 변환 테스트 실패: {e}")
        results.append(("틱→캔들 변환", False))

    try:
        results.append(("엔진 생명주기", await test_trading_engine_lifecycle()))
    except Exception as e:
        print(f"[ERROR] 엔진 생명주기 테스트 실패: {e}")
        results.append(("엔진 생명주기", False))

    # 결과 요약
    print("\n" + "=" * 60)
    print("테스트 결과")
    print("=" * 60)

    for name, success in results:
        status = "[OK]" if success else "[FAIL]"
        print(f"  {name}: {status}")

    all_passed = all(r[1] for r in results)
    print(f"\n전체 결과: {'[OK] 모두 통과' if all_passed else '[FAIL] 일부 실패'}")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
