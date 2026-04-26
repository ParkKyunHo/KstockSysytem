"""
실시간 데이터 매니저 모듈

중앙 집중형 데이터 허브로, 모든 API 통신을 전담하고
데이터를 각 모듈에 브로드캐스팅합니다.

Tier 시스템:
    - Tier 1: 보유 포지션 + 매수 유력 후보 (고속 폴링 또는 WebSocket)
    - Tier 2: 일반 유니버스 종목 (저속 폴링)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Set, List, Optional, Callable, Awaitable
from enum import IntEnum
import asyncio

from src.api.websocket import KiwoomWebSocket, TickData
from src.api.endpoints.market import MarketAPI, MinuteCandle
from src.utils.logger import get_logger
from src.utils.config import get_settings, get_risk_settings
# Note: get_market_schedule, MarketState는 NXT 체크에서 더 이상 사용하지 않음
# (PRE_MARKET_START 재정의 버그로 인해 고정 시간으로 직접 체크)


class Tier(IntEnum):
    """종목 등급"""
    TIER_1 = 1  # 고우선순위: 보유 포지션, 매수 유력 후보
    TIER_2 = 2  # 일반: 유니버스 종목


@dataclass
class PriceData:
    """시세 데이터"""
    stock_code: str
    stock_name: str
    current_price: int
    change: int = 0
    change_rate: float = 0.0
    volume: int = 0
    total_volume: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_stock_info(cls, info) -> "PriceData":
        """StockInfo에서 변환"""
        return cls(
            stock_code=info.stock_code,
            stock_name=info.stock_name,
            current_price=info.current_price,
            change=info.change,
            change_rate=info.change_rate,
            volume=info.volume,
            total_volume=info.volume,
            timestamp=datetime.now(),
        )

    @classmethod
    def from_tick_data(cls, tick: TickData, stock_name: str = "") -> "PriceData":
        """TickData에서 변환"""
        return cls(
            stock_code=tick.stock_code,
            stock_name=stock_name or tick.stock_name,
            current_price=tick.price,
            change=tick.change,
            change_rate=tick.change_rate,
            volume=tick.volume,
            total_volume=tick.total_volume,
            timestamp=datetime.now(),
        )


# 콜백 타입 정의
PriceCallback = Callable[[PriceData], Awaitable[None]]
HistoricalCandleCallback = Callable[[str, List[MinuteCandle], List[MinuteCandle]], Awaitable[None]]


class RealTimeDataManager:
    """
    중앙 집중형 실시간 데이터 관리자

    모든 API 통신의 유일한 창구(Gateway)로,
    종목을 Tier별로 관리하고 데이터를 구독자에게 브로드캐스팅합니다.

    Features:
        - Tier 1/2 종목 분류 관리
        - 중복 제거 (Set 자료구조)
        - 시세 캐시
        - Rate Limiting 통합
        - 모의투자 Fallback (WebSocket → REST)

    Usage:
        manager = RealTimeDataManager(websocket, market_api)
        manager.subscribe(on_price_update)
        manager.register_stock("005930", Tier.TIER_2)
        await manager.start()
    """

    def __init__(
        self,
        websocket: Optional[KiwoomWebSocket] = None,
        market_api: Optional[MarketAPI] = None,
        is_paper_trading: Optional[bool] = None,
    ):
        self._logger = get_logger(__name__)
        self._settings = get_settings()

        # 외부 의존성
        self._websocket = websocket
        self._market_api = market_api

        # 모의투자 여부
        self._is_paper_trading = (
            is_paper_trading
            if is_paper_trading is not None
            else self._settings.is_paper_trading
        )

        # Tier별 종목 관리 (Set으로 중복 제거)
        self._tier1_stocks: Set[str] = set()
        self._tier2_stocks: Set[str] = set()

        # 종목별 메타데이터 (종목명 등)
        self._stock_names: Dict[str, str] = {}

        # 시세 캐시
        self._price_cache: Dict[str, PriceData] = {}

        # 구독자 콜백 리스트
        self._subscribers: List[PriceCallback] = []

        # 실행 상태
        self._running: bool = False

        # 백그라운드 태스크
        self._tier1_poll_task: Optional[asyncio.Task] = None
        # Tier 2는 폴링하지 않음 (승격 대기 목록으로만 사용)

        # 폴링 간격 설정 (Tier 1만)
        # 모의투자: 1초 간격 (429 에러 방지)
        # 실전투자: 0.3초 간격
        self._tier1_poll_interval = 1.0 if self._is_paper_trading else 0.3

        # 병렬 캔들 로딩 설정
        risk_settings = get_risk_settings()
        self._parallel_candle_loading = risk_settings.parallel_candle_loading
        # 동시 요청 수: 모의투자 3개, 실전투자 5개 (Rate Limit 고려)
        concurrency = risk_settings.candle_load_concurrency
        if not self._is_paper_trading and concurrency < 5:
            concurrency = 5  # 실전투자는 최소 5개
        self._candle_load_semaphore = asyncio.Semaphore(concurrency)
        self._logger.info(
            f"[병렬 캔들 로딩] {'활성화' if self._parallel_candle_loading else '비활성화'}, "
            f"동시 요청: {concurrency}개"
        )

        # 통계
        self._stats = {
            "tier1_polls": 0,
            "tier2_polls": 0,  # Tier 2는 현재 미사용 (향후 확장용)
            "broadcasts": 0,
            "errors": 0,
        }

        # 과거 캔들 로더 콜백 (TradingEngine에서 설정)
        self._historical_candle_callback: Optional[HistoricalCandleCallback] = None

        # PRD v3.3: 캔들 로드 완료 종목 (신호 탐지 조건 충족 여부)
        self._candle_loaded: Set[str] = set()

        # V6.2-M: WebSocket REG 모드 상태
        self._use_websocket: bool = False
        self._websocket_subscribed: Set[str] = set()

    # =========================================
    # 종목 등록/해제
    # =========================================

    def register_stock(
        self,
        stock_code: str,
        tier: Tier = Tier.TIER_2,
        stock_name: str = "",
    ) -> None:
        """
        종목 등록

        Args:
            stock_code: 종목 코드
            tier: 등급 (TIER_1 또는 TIER_2)
            stock_name: 종목명 (선택)
        """
        if stock_name:
            self._stock_names[stock_code] = stock_name

        if tier == Tier.TIER_1:
            self._tier1_stocks.add(stock_code)
            # Tier 1에 추가되면 Tier 2에서 제거 (중복 방지)
            self._tier2_stocks.discard(stock_code)
            self._logger.debug(f"[Tier 1] 등록: {stock_code}")
        else:
            # Tier 1에 없는 경우에만 Tier 2에 추가
            if stock_code not in self._tier1_stocks:
                self._tier2_stocks.add(stock_code)
                self._logger.debug(f"[Tier 2] 등록: {stock_code}")

    def unregister_stock(self, stock_code: str) -> None:
        """
        종목 해제

        Args:
            stock_code: 종목 코드
        """
        self._tier1_stocks.discard(stock_code)
        self._tier2_stocks.discard(stock_code)
        self._price_cache.pop(stock_code, None)
        self._logger.debug(f"종목 해제: {stock_code}")

    def is_tier1(self, stock_code: str) -> bool:
        """
        Tier 1 종목 여부 확인

        Args:
            stock_code: 종목 코드

        Returns:
            Tier 1 여부
        """
        return stock_code in self._tier1_stocks

    async def promote_to_tier1(self, stock_code: str) -> bool:
        """
        Tier 2 → Tier 1 승격 (PRD v3.3: 캔들 로드 완료 대기)

        승격 시 과거 분봉 데이터를 로드하여 신호 탐지 조건을 즉시 충족할 수 있게 함

        Args:
            stock_code: 종목 코드

        Returns:
            캔들 로드 성공 여부
        """
        self._tier2_stocks.discard(stock_code)
        self._tier1_stocks.add(stock_code)
        self._logger.info(f"[승격] {stock_code} → Tier 1")

        # V6.2-M: WebSocket REG 모드일 때 새 종목 구독
        if self._use_websocket and self._websocket and self._running:
            try:
                if stock_code not in self._websocket_subscribed:
                    await self._websocket.subscribe_tick([stock_code])
                    self._websocket_subscribed.add(stock_code)
                    self._logger.debug(f"[REG] 종목 추가 구독: {stock_code}")
            except Exception as e:
                self._logger.warning(f"[REG] 종목 구독 실패: {stock_code} - {e}")

        # PRD v3.3: 과거 분봉 로드 (동기적 대기)
        # 캔들 로드 완료 전에 폴링이 시작되어 신호 탐지 불가 문제 해결
        if self._market_api and self._historical_candle_callback:
            try:
                await self._load_historical_candles(stock_code)
                return True
            except Exception as e:
                self._logger.warning(f"[승격] {stock_code} 캔들 로드 실패: {e}")
                return False

        return True

    async def load_historical_candles_for_watchlist(self, stock_code: str) -> bool:
        """
        Watchlist 종목용 과거 캔들 로딩 (Tier 2)

        V6.2-B Fix: Watchlist 종목도 신호 탐지 가능하게
        - 3분봉만 로딩 (1분봉 생략으로 API 부하 절반)
        - SNIPER_TRAP 신호 탐지에 필요한 최소 데이터만

        Args:
            stock_code: 종목 코드

        Returns:
            캔들 로드 성공 여부
        """
        if not self._market_api or not self._historical_candle_callback:
            return False

        candle_count = get_risk_settings().candle_history_count
        candles_3m = []

        # 3분봉만 로드 (SNIPER_TRAP 신호 탐지용)
        try:
            candles_3m = await self._market_api.get_minute_chart(
                stock_code, timeframe=3, count=candle_count, use_pagination=True
            )
        except Exception as e:
            self._logger.warning(f"[Watchlist 3분봉 로드 실패] {stock_code}: {e}")
            return False

        if len(candles_3m) < candle_count * 0.5:
            self._logger.warning(
                f"[Watchlist 캔들 부족] {stock_code}: {len(candles_3m)}/{candle_count}개"
            )
            return False

        # 콜백 호출 (1분봉은 빈 리스트)
        if self._historical_candle_callback:
            await self._historical_candle_callback(stock_code, [], candles_3m)

        self._logger.debug(
            f"[Watchlist 캔들 로드 완료] {stock_code}: 3분봉 {len(candles_3m)}개"
        )
        return True

    async def load_candles_batch(
        self,
        stock_codes: List[str]
    ) -> Dict[str, bool]:
        """
        여러 종목의 과거 분봉 데이터를 병렬 로딩

        Semaphore를 사용하여 동시 요청 수를 제한하고,
        asyncio.gather로 병렬 처리합니다.

        Args:
            stock_codes: 캔들을 로드할 종목 코드 리스트

        Returns:
            {stock_code: success_bool} 형태의 결과 딕셔너리
        """
        from typing import Tuple

        async def load_single(stock_code: str) -> Tuple[str, bool]:
            """단일 종목 캔들 로드 (Semaphore 적용)"""
            async with self._candle_load_semaphore:
                try:
                    await self._load_historical_candles(stock_code)
                    return (stock_code, stock_code in self._candle_loaded)
                except Exception as e:
                    self._logger.warning(f"[병렬 캔들 로드 실패] {stock_code}: {e}")
                    return (stock_code, False)

        if not stock_codes:
            return {}

        # 병렬 로딩 비활성화 시 순차 처리 (롤백용)
        if not self._parallel_candle_loading:
            self._logger.info(
                f"[순차 캔들 로드] 시작: {len(stock_codes)}개 종목 (병렬화 비활성화)"
            )
            result_dict = {}
            for code in stock_codes:
                try:
                    await self._load_historical_candles(code)
                    result_dict[code] = code in self._candle_loaded
                except Exception as e:
                    self._logger.warning(f"[순차 캔들 로드 실패] {code}: {e}")
                    result_dict[code] = False
            return result_dict

        self._logger.info(
            f"[병렬 캔들 로드] 시작: {len(stock_codes)}개 종목"
        )

        start_time = datetime.now()
        results = await asyncio.gather(
            *[load_single(code) for code in stock_codes],
            return_exceptions=True
        )
        elapsed = (datetime.now() - start_time).total_seconds()

        # 결과 집계
        result_dict = {}
        for result in results:
            if isinstance(result, Exception):
                self._logger.error(f"[병렬 캔들 로드] 예외 발생: {result}")
                continue
            if isinstance(result, tuple) and len(result) == 2:
                result_dict[result[0]] = result[1]

        success = sum(1 for v in result_dict.values() if v)

        self._logger.info(
            f"[병렬 캔들 로드] 완료: {success}/{len(stock_codes)}개 성공, {elapsed:.1f}초"
        )

        return result_dict

    def set_historical_candle_callback(
        self, callback: HistoricalCandleCallback
    ) -> None:
        """
        과거 캔들 로더 콜백 설정

        Args:
            callback: (stock_code, candles_1m, candles_3m) -> None
        """
        self._historical_candle_callback = callback

    async def _load_historical_candles(self, stock_code: str) -> None:
        """
        과거 분봉 데이터 로드하여 콜백 호출

        V7: 3분봉만 로드 (1분봉 미사용으로 API 부하 절반)

        Args:
            stock_code: 종목 코드
        """
        MAX_RETRIES = 3
        RETRY_DELAYS = [0.5, 1.0, 2.0]  # exponential backoff
        MIN_CANDLES_RATIO = 0.5  # 최소 50% 로드 필요
        NEW_LISTING_THRESHOLD = 390  # 신규 상장 임계값 (약 3일 * 130봉/일)
        MIN_CANDLES_FOR_NEW_LISTING = 60  # V7 신호 탐지 최소 요구량

        candle_count = get_risk_settings().candle_history_count
        candles_1m = []  # V7: 1분봉 미사용 (호환성 유지)
        candles_3m = []

        # 3분봉만 로드 (재시도 포함)
        for attempt in range(MAX_RETRIES):
            try:
                candles_3m = await self._market_api.get_minute_chart(
                    stock_code, timeframe=3, count=candle_count, use_pagination=True
                )
                if len(candles_3m) >= candle_count * MIN_CANDLES_RATIO:
                    break
                self._logger.warning(
                    f"[캔들 부족] {stock_code} 3분봉: {len(candles_3m)}/{candle_count}개, "
                    f"재시도 {attempt+1}/{MAX_RETRIES}"
                )
            except Exception as e:
                self._logger.warning(
                    f"[3분봉 로드 실패] {stock_code}: {e}, 재시도 {attempt+1}/{MAX_RETRIES}"
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])

        # 캔들 데이터 검증 (3분봉만)
        is_valid = True
        if len(candles_3m) < candle_count * MIN_CANDLES_RATIO:
            # 신규 상장 종목 판별: 400개 미만이지만 60개 이상이면 활성화
            if len(candles_3m) < NEW_LISTING_THRESHOLD and len(candles_3m) >= MIN_CANDLES_FOR_NEW_LISTING:
                estimated_days = len(candles_3m) // 130 if candles_3m else 0
                self._logger.info(
                    f"[캔들 검증] {stock_code} 신규 상장 모드 (약 {estimated_days}일차) | "
                    f"캔들 {len(candles_3m)}개 | 신호 탐지 활성화"
                )
                is_valid = True
            else:
                self._logger.error(
                    f"[캔들 검증 실패] {stock_code} 3분봉: {len(candles_3m)}개 "
                    f"(최소 {MIN_CANDLES_FOR_NEW_LISTING}개 필요)"
                )
                is_valid = False

        # timestamp 정합성 검증 (최신 캔들이 오늘인지)
        from datetime import date
        if candles_3m:
            latest_ts = candles_3m[-1].timestamp
            if latest_ts.date() != date.today():
                self._logger.warning(
                    f"[캔들 timestamp 경고] {stock_code}: 최신 3분봉이 오늘이 아님 ({latest_ts})"
                )

        self._logger.info(f"[과거 분봉 로드] {stock_code}: 3분봉={len(candles_3m)}개")

        # 콜백 호출 (1분봉은 빈 리스트)
        if self._historical_candle_callback and candles_3m:
            await self._historical_candle_callback(stock_code, candles_1m, candles_3m)

        # 캔들 로드 완료 표시 (검증 통과 시에만)
        if is_valid:
            self._candle_loaded.add(stock_code)
            self._logger.info(f"[캔들 로드 완료] {stock_code}: 신호 탐지 준비 완료")
        else:
            self._logger.warning(
                f"[캔들 부분 로드] {stock_code}: 검증 실패, 신호 탐지 제한될 수 있음"
            )

    def is_candle_loaded(self, stock_code: str) -> bool:
        """
        캔들 데이터 로드 완료 여부 (PRD v3.3)

        신호 탐지 전에 이 메서드로 캔들 준비 상태를 확인합니다.

        Args:
            stock_code: 종목 코드

        Returns:
            캔들 로드 완료 여부
        """
        return stock_code in self._candle_loaded

    def demote_to_tier2(self, stock_code: str) -> None:
        """
        Tier 1 → Tier 2 강등

        Args:
            stock_code: 종목 코드
        """
        self._tier1_stocks.discard(stock_code)
        self._tier2_stocks.add(stock_code)
        self._candle_loaded.discard(stock_code)  # PRD v3.3: 캔들 로드 상태 초기화
        self._logger.info(f"[강등] {stock_code} → Tier 2")

        # 실전투자에서 WebSocket 구독 해제
        if not self._is_paper_trading and self._websocket and self._running:
            asyncio.create_task(self._unsubscribe_websocket([stock_code]))

    def is_registered(self, stock_code: str) -> bool:
        """종목 등록 여부 확인"""
        return stock_code in self._tier1_stocks or stock_code in self._tier2_stocks

    def get_tier(self, stock_code: str) -> Optional[Tier]:
        """종목의 현재 Tier 조회"""
        if stock_code in self._tier1_stocks:
            return Tier.TIER_1
        elif stock_code in self._tier2_stocks:
            return Tier.TIER_2
        return None

    # =========================================
    # 구독자 관리
    # =========================================

    def subscribe(self, callback: PriceCallback) -> None:
        """
        데이터 구독 등록

        Args:
            callback: 시세 수신 시 호출될 콜백 함수
        """
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            self._logger.debug(f"구독자 등록: {callback.__name__}")

    def unsubscribe(self, callback: PriceCallback) -> None:
        """
        데이터 구독 해제

        Args:
            callback: 해제할 콜백 함수
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            self._logger.debug(f"구독자 해제: {callback.__name__}")

    # =========================================
    # 시세 캐시
    # =========================================

    def get_price(self, stock_code: str) -> Optional[int]:
        """
        캐시된 현재가 조회

        Args:
            stock_code: 종목 코드

        Returns:
            현재가 또는 None
        """
        data = self._price_cache.get(stock_code)
        return data.current_price if data else None

    def get_price_data(self, stock_code: str) -> Optional[PriceData]:
        """
        캐시된 시세 데이터 전체 조회

        Args:
            stock_code: 종목 코드

        Returns:
            PriceData 또는 None
        """
        return self._price_cache.get(stock_code)

    # =========================================
    # 시작/정지
    # =========================================

    async def start(self) -> None:
        """데이터 수신 시작"""
        if self._running:
            self._logger.warning("이미 실행 중입니다")
            return

        self._running = True
        self._logger.info(
            f"RealTimeDataManager 시작 "
            f"(모의투자: {self._is_paper_trading}, "
            f"Tier1: {len(self._tier1_stocks)}개, "
            f"Tier2: {len(self._tier2_stocks)}개)"
        )

        # Tier 1 시작 (Tier 1만 폴링, Tier 2는 폴링 없음)
        await self._start_tier1()

    async def stop(self) -> None:
        """데이터 수신 정지"""
        if not self._running:
            return

        self._running = False
        self._logger.info("RealTimeDataManager 정지 중...")

        # Tier 1 폴링 태스크 취소
        if self._tier1_poll_task:
            self._tier1_poll_task.cancel()
            try:
                await self._tier1_poll_task
            except asyncio.CancelledError:
                pass
            self._tier1_poll_task = None

        # WebSocket 구독 해제 (실전투자)
        if not self._is_paper_trading and self._websocket:
            await self._websocket.unsubscribe_all_tick()

        self._logger.info("RealTimeDataManager 정지 완료")

    # =========================================
    # Tier 1 처리
    # =========================================

    async def _start_tier1(self) -> None:
        """Tier 1 데이터 수신 시작 - V6.2-M 하이브리드 모드"""
        # V6.2-M: WebSocket REG 시도 (실전투자 + WebSocket 연결 상태)
        if not self._is_paper_trading and self._websocket and self._websocket.is_connected:
            try:
                initial_stocks = list(self._tier1_stocks)
                if initial_stocks:
                    await self._websocket.subscribe_tick(initial_stocks)
                    self._websocket_subscribed.update(initial_stocks)
                self._use_websocket = True
                self._logger.info(f"Tier 1: WebSocket REG 모드 ({len(initial_stocks)}개 종목)")
                # WebSocket 모드에서도 REST 폴링 병행 (Fallback + 보완)
                self._tier1_poll_task = asyncio.create_task(self._tier1_polling_loop())
                self._logger.info("Tier 1: REST 폴링 병행 (WebSocket 보완)")
                return
            except Exception as e:
                self._logger.warning(f"WebSocket REG 실패, REST 폴링으로 전환: {e}")
                self._use_websocket = False

        # Fallback: REST 폴링 (모의투자 또는 WebSocket 실패)
        self._tier1_poll_task = asyncio.create_task(self._tier1_polling_loop())
        self._logger.info("Tier 1: REST 폴링 모드")

    async def _subscribe_websocket(self, stock_codes: List[str]) -> None:
        """WebSocket 실시간 구독"""
        if not self._websocket or not stock_codes:
            return

        # 최대 20개씩 나눠서 구독 (키움 API 제한)
        for i in range(0, len(stock_codes), 20):
            batch = stock_codes[i:i + 20]
            try:
                await self._websocket.subscribe_tick(batch)
                self._logger.debug(f"WebSocket 구독: {len(batch)}개 종목")
            except Exception as e:
                self._logger.error(f"WebSocket 구독 실패: {e}")

    async def _unsubscribe_websocket(self, stock_codes: List[str]) -> None:
        """WebSocket 실시간 구독 해제"""
        if not self._websocket or not stock_codes:
            return

        try:
            await self._websocket.unsubscribe_tick(stock_codes)
            self._logger.debug(f"WebSocket 구독 해제: {len(stock_codes)}개 종목")
        except Exception as e:
            self._logger.error(f"WebSocket 구독 해제 실패: {e}")

    async def _on_websocket_tick(self, tick_data: TickData) -> None:
        """WebSocket 틱 데이터 수신 콜백"""
        stock_name = self._stock_names.get(tick_data.stock_code, tick_data.stock_name)
        price_data = PriceData.from_tick_data(tick_data, stock_name)

        # 캐시 업데이트
        self._price_cache[tick_data.stock_code] = price_data

        # 브로드캐스트
        await self._broadcast(price_data)

    async def _tier1_polling_loop(self) -> None:
        """Tier 1 종목 고속 폴링 (모의투자용)"""
        self._logger.info(
            f"Tier 1 폴링 루프 시작 (간격: {self._tier1_poll_interval}초)"
        )

        # Heartbeat 카운터
        heartbeat_counter = 0
        empty_warning_counter = 0

        while self._running:
            try:
                # [V7.1] NXT 시간대 폴링 스킵 (고정 시간 사용)
                # REST API가 NXT 시간대에 KRX 전일 종가를 반환하므로
                # WebSocket 틱 데이터만 사용하여 정확한 NXT 시세로 봉 생성
                # Note: market_schedule의 PRE_MARKET_START가 08:30으로 재정의되는 버그가 있어
                #       고정 시간으로 직접 체크함
                from datetime import time as dt_time
                now_time = datetime.now().time()
                NXT_PRE_START = dt_time(8, 0)    # 08:00
                NXT_PRE_END = dt_time(8, 50)     # 08:50
                NXT_AFTER_START = dt_time(15, 30)  # 15:30
                NXT_AFTER_END = dt_time(20, 0)   # 20:00

                is_nxt_pre = NXT_PRE_START <= now_time < NXT_PRE_END
                is_nxt_after = NXT_AFTER_START <= now_time < NXT_AFTER_END

                if is_nxt_pre or is_nxt_after:
                    # 1분마다 상태 로그 (로그 스팸 방지)
                    if heartbeat_counter % 60 == 0:
                        nxt_type = "NXT_PRE_MARKET" if is_nxt_pre else "NXT_AFTER"
                        self._logger.info(
                            f"[Tier 1] NXT 시간대 폴링 스킵 (WebSocket만 사용): {nxt_type}"
                        )
                    heartbeat_counter += 1
                    await asyncio.sleep(1.0)
                    continue

                # 현재 Tier 1 종목 복사 (런타임 변경 대응)
                codes = list(self._tier1_stocks)

                if not codes:
                    empty_warning_counter += 1
                    # 60초마다 로그 (장외 시간 로그 스팸 방지를 위해 debug 레벨)
                    if empty_warning_counter % 60 == 1:
                        self._logger.debug(
                            f"[Tier 1] 모니터링 종목 없음 "
                            f"(대기 중... {empty_warning_counter}초)"
                        )
                    await asyncio.sleep(1.0)
                    continue

                empty_warning_counter = 0  # 종목 있으면 리셋

                for code in codes:
                    if not self._running:
                        break

                    try:
                        await self._poll_stock(code)
                        self._stats["tier1_polls"] += 1
                    except Exception as e:
                        self._logger.warning(f"Tier 1 폴링 실패: {code} - {e}")
                        self._stats["errors"] += 1

                    # Rate Limiting
                    await asyncio.sleep(self._tier1_poll_interval)

                # 사이클 완료 후 추가 대기
                await asyncio.sleep(0.5)

                # Heartbeat: 5분마다 상태 로그
                heartbeat_counter += 1
                if heartbeat_counter % 300 == 0:  # 약 5분
                    self._logger.info(
                        f"[Tier 1 Heartbeat] 폴링 {self._stats['tier1_polls']}회, "
                        f"종목 {len(codes)}개, 에러 {self._stats['errors']}회"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Tier 1 폴링 루프 에러: {e}")
                await asyncio.sleep(5.0)

        self._logger.info("Tier 1 폴링 루프 종료")

    # Tier 2는 폴링하지 않음 - 승격 대기 목록으로만 사용
    # 사용자가 텔레그램에서 "승격" 버튼을 클릭해야만 Tier 1로 이동하여 폴링 시작

    async def _poll_stock(self, stock_code: str) -> bool:
        """
        단일 종목 시세 폴링 (타임아웃 적용)

        Args:
            stock_code: 종목 코드

        Returns:
            성공 여부
        """
        if not self._market_api:
            self._logger.warning(f"[폴링] market_api 없음: {stock_code}")
            return False

        try:
            # 10초 타임아웃 적용 (API 블로킹 방지)
            stock_info = await asyncio.wait_for(
                self._market_api.get_stock_info(stock_code),
                timeout=10.0
            )

            if not stock_info:
                self._logger.warning(f"[폴링] 응답 없음: {stock_code}")
                return False

            price_data = PriceData.from_stock_info(stock_info)

            # 종목명 저장
            if stock_info.stock_name:
                self._stock_names[stock_code] = stock_info.stock_name

            # 캐시 업데이트
            self._price_cache[stock_code] = price_data

            # 브로드캐스트
            await self._broadcast(price_data)

            self._logger.debug(
                f"[폴링] {stock_code} {stock_info.stock_name}: "
                f"{price_data.current_price:,}원 (vol: {price_data.volume:,})"
            )
            return True

        except asyncio.TimeoutError:
            self._logger.warning(f"[폴링 타임아웃] {stock_code} - 10초 초과")
            self._stats["errors"] += 1
            return False

        except Exception as e:
            self._logger.error(f"[폴링 에러] {stock_code}: {e}")
            self._stats["errors"] += 1
            return False

    # =========================================
    # 브로드캐스팅
    # =========================================

    async def _broadcast(self, price_data: PriceData) -> None:
        """모든 구독자에게 데이터 전송"""
        self._stats["broadcasts"] += 1

        # 브로드캐스트 로깅 (100회마다)
        if self._stats["broadcasts"] % 100 == 1:
            self._logger.info(
                f"[브로드캐스트 #{self._stats['broadcasts']}] "
                f"{price_data.stock_code} → 구독자 {len(self._subscribers)}명"
            )

        if not self._subscribers:
            self._logger.warning(f"[브로드캐스트] 구독자 없음! {price_data.stock_code}")
            return

        for callback in self._subscribers:
            try:
                await callback(price_data)
            except Exception as e:
                self._logger.error(
                    f"브로드캐스트 콜백 에러: {callback.__name__} - {e}",
                    exc_info=True
                )

    # =========================================
    # 상태 조회
    # =========================================

    @property
    def is_running(self) -> bool:
        """실행 상태"""
        return self._running

    @property
    def tier1_count(self) -> int:
        """Tier 1 종목 수"""
        return len(self._tier1_stocks)

    @property
    def tier2_count(self) -> int:
        """Tier 2 종목 수"""
        return len(self._tier2_stocks)

    @property
    def total_count(self) -> int:
        """전체 종목 수 (중복 제외)"""
        return len(self._tier1_stocks | self._tier2_stocks)

    def get_tier1_stocks(self) -> List[str]:
        """Tier 1 종목 목록"""
        return list(self._tier1_stocks)

    def get_tier2_stocks(self) -> List[str]:
        """Tier 2 종목 목록"""
        return list(self._tier2_stocks)

    def get_all_stocks(self) -> List[str]:
        """전체 종목 목록"""
        return list(self._tier1_stocks | self._tier2_stocks)

    def get_stats(self) -> Dict:
        """통계 조회"""
        return {
            **self._stats,
            "tier1_stocks": self.tier1_count,
            "tier2_stocks": self.tier2_count,
            "cached_prices": len(self._price_cache),
            "subscribers": len(self._subscribers),
        }

    def get_summary(self) -> str:
        """상태 요약 문자열"""
        return (
            f"[RealTimeDataManager]\n"
            f"상태: {'실행 중' if self._running else '정지'}\n"
            f"모드: {'모의투자' if self._is_paper_trading else '실전투자'}\n"
            f"Tier 1: {self.tier1_count}개 (고속)\n"
            f"Tier 2: {self.tier2_count}개 (저속)\n"
            f"캐시: {len(self._price_cache)}개\n"
            f"폴링: T1={self._stats['tier1_polls']}, T2={self._stats['tier2_polls']}\n"
            f"에러: {self._stats['errors']}"
        )
