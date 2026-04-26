"""
실시간 틱 데이터를 봉(캔들)으로 변환하는 모듈

키움증권 WebSocket에서 수신하는 실시간 체결 데이터를 사용하여
1분봉, 3분봉을 로컬에서 직접 생성합니다.

이 방식은 TR API의 조회 제한(초당 제한)을 회피하면서
다수의 종목을 동시에 모니터링할 수 있게 합니다.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Callable, Awaitable
from enum import Enum
import asyncio
import pandas as pd

from src.utils.logger import get_logger
from src.utils.config import get_risk_settings


# C-006: 명시적 KST 타임존 정의 (AWS UTC 서버 호환)
KST = timezone(timedelta(hours=9))


class Timeframe(str, Enum):
    """봉 타임프레임"""
    M1 = "1m"   # 1분봉
    M3 = "3m"   # 3분봉


@dataclass
class Tick:
    """실시간 체결 틱 데이터"""
    stock_code: str
    price: int              # 현재가
    volume: int             # 체결량
    timestamp: datetime     # 체결 시간
    change_rate: float = 0.0  # 등락률

    @classmethod
    def from_ws_data(cls, data: dict) -> "Tick":
        """WebSocket 데이터에서 Tick 생성"""
        # 키움 실시간 체결 데이터 필드
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        raw_code = data.get("9001", "")
        stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
        price = abs(int(data.get("10", 0)))  # 현재가 (부호 제거)
        volume = int(data.get("15", 0))      # 체결량

        # 체결 시간 파싱 (HHMMSS)
        # C-006: 명시적 KST 사용 (AWS UTC 서버 호환)
        time_str = data.get("20", "")
        if len(time_str) >= 6:
            hour = int(time_str[:2])
            minute = int(time_str[2:4])
            second = int(time_str[4:6])
            now = datetime.now(KST)
            timestamp = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        else:
            timestamp = datetime.now(KST)

        change_rate = float(data.get("12", 0)) / 100  # 등락률 (%)

        return cls(
            stock_code=stock_code,
            price=price,
            volume=volume,
            timestamp=timestamp,
            change_rate=change_rate,
        )


@dataclass
class Candle:
    """봉(캔들) 데이터"""
    stock_code: str
    timeframe: Timeframe
    time: datetime          # 봉 시작 시간
    open: int               # 시가
    high: int               # 고가
    low: int                # 저가
    close: int              # 종가
    volume: int             # 거래량
    is_complete: bool = False  # 봉 완성 여부

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


# 콜백 타입
CandleCallback = Callable[[str, Candle], Awaitable[None]]


class CandleBuilder:
    """
    실시간 틱 데이터를 봉(캔들)으로 변환

    기능:
    - 틱 데이터 수신 시 실시간으로 봉 갱신
    - 1분봉, 3분봉 동시 생성
    - 봉 완성 시 콜백 호출
    - DataFrame 형태로 과거 봉 데이터 제공
    - C-003: 역순 틱 감지 및 처리

    Usage:
        builder = CandleBuilder("005930")
        builder.on_candle_complete = my_callback
        builder.on_tick(tick)
        candles = builder.get_candles(Timeframe.M1)
    """

    def __init__(self, stock_code: str):
        self.stock_code = stock_code
        self._logger = get_logger(__name__)

        # Grand Trend V6: 설정에서 캔들 유지 개수 로드 (EMA200 정확도용)
        self._max_candles = get_risk_settings().candle_history_count

        # 현재 진행 중인 봉
        self._current_candles: Dict[Timeframe, Candle] = {}

        # 완성된 봉 데이터
        self._candles: Dict[Timeframe, List[Candle]] = {
            Timeframe.M1: [],
            Timeframe.M3: [],
        }

        # 캐시된 DataFrame (성능 최적화)
        self._df_cache: Dict[Timeframe, pd.DataFrame] = {}
        self._df_dirty: Dict[Timeframe, bool] = {
            Timeframe.M1: True,
            Timeframe.M3: True,
        }

        # 콜백
        self.on_candle_complete: Optional[CandleCallback] = None

        # C-003 FIX: 역순 틱 감지를 위한 마지막 처리 틱 시간
        self._last_tick_time: Optional[datetime] = None
        self._out_of_order_count: int = 0  # 역순 틱 카운터 (모니터링용)

    def _get_candle_start_time(self, timestamp: datetime, timeframe: Timeframe) -> datetime:
        """봉의 시작 시간 계산"""
        if timeframe == Timeframe.M1:
            # 1분봉: 초를 0으로
            return timestamp.replace(second=0, microsecond=0)
        elif timeframe == Timeframe.M3:
            # 3분봉: 3분 단위로 내림
            minute = (timestamp.minute // 3) * 3
            return timestamp.replace(minute=minute, second=0, microsecond=0)
        return timestamp

    def _get_candle_end_time(self, start_time: datetime, timeframe: Timeframe) -> datetime:
        """봉의 종료 시간 계산"""
        if timeframe == Timeframe.M1:
            return start_time + timedelta(minutes=1)
        elif timeframe == Timeframe.M3:
            return start_time + timedelta(minutes=3)
        return start_time

    def on_tick(self, tick: Tick) -> Optional[List[Candle]]:
        """
        틱 데이터 수신 처리

        C-003 FIX: 역순 틱 감지 및 안전 처리
        - 네트워크 지연으로 틱이 시간 역순으로 도착할 수 있음
        - 역순 틱이 봉 완성을 잘못 트리거하지 않도록 방지

        Args:
            tick: 체결 틱 데이터

        Returns:
            완성된 봉 목록 (없으면 None)
        """
        if tick.stock_code != self.stock_code:
            return None

        # C-003 FIX: 역순 틱 감지
        is_out_of_order = False
        if self._last_tick_time is not None and tick.timestamp < self._last_tick_time:
            is_out_of_order = True
            self._out_of_order_count += 1
            # 100번마다 로그 (과도한 로깅 방지)
            if self._out_of_order_count % 100 == 1:
                self._logger.warning(
                    f"[C-003] {self.stock_code} 역순 틱 감지 #{self._out_of_order_count}: "
                    f"tick={tick.timestamp.strftime('%H:%M:%S')} < last={self._last_tick_time.strftime('%H:%M:%S')}"
                )

        completed_candles = []

        for timeframe in [Timeframe.M1, Timeframe.M3]:
            candle_start = self._get_candle_start_time(tick.timestamp, timeframe)
            candle_end = self._get_candle_end_time(candle_start, timeframe)

            current = self._current_candles.get(timeframe)

            # C-003 FIX: 역순 틱이 봉 완성을 트리거하면 안 됨
            # - 역순 틱의 candle_start가 current.time보다 클 수 없어야 함 (정상적으로는)
            # - 만약 역순 틱이 미래 봉 시작을 암시하면 무시 (비정상 상황)
            if is_out_of_order and current is not None and candle_start > current.time:
                self._logger.warning(
                    f"[C-003] {self.stock_code} {timeframe.value}: "
                    f"역순 틱이 봉 완성 트리거 시도 - 무시 (tick_time={tick.timestamp.strftime('%H:%M:%S')})"
                )
                continue

            # 새로운 봉 시작 확인
            if current is None or candle_start > current.time:
                # 기존 봉 완성 처리
                if current is not None:
                    current.is_complete = True
                    self._candles[timeframe].append(current)
                    completed_candles.append(current)

                    # 캐시 무효화
                    self._df_dirty[timeframe] = True

                    # 최대 개수 유지
                    if len(self._candles[timeframe]) > self._max_candles:
                        self._candles[timeframe] = self._candles[timeframe][-self._max_candles:]

                # 새 봉 생성
                self._current_candles[timeframe] = Candle(
                    stock_code=self.stock_code,
                    timeframe=timeframe,
                    time=candle_start,
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=tick.volume,
                )
            else:
                # V7.0-Fix4: 과거 API 데이터로 초기화된 캔들 처리
                # is_complete=True인 캔들은 load_historical_candles에서 생성된 것
                # [V7.1-Fix2] High/Low도 현재 틱으로 리셋
                # - Open: 유지 (ATR 계산용)
                # - High/Low: 현재 틱으로 리셋 (과거 API의 잘못된 범위로 Hard Stop 오작동 방지)
                # - Close: 현재 틱으로 갱신
                # - Volume: 현재 틱으로 리셋
                # - 이유: 과거 API 캔들의 Low가 실제보다 낮으면 잘못된 Hard Stop 발동
                if current.is_complete:
                    old_ohlc = (current.open, current.high, current.low, current.close)
                    # High/Low를 현재 틱으로 리셋 (범위 확장 아님!)
                    current.high = tick.price
                    current.low = tick.price
                    current.close = tick.price
                    current.volume = tick.volume  # 리셋
                    current.is_complete = False  # 이제 실시간 캔들
                    self._logger.info(
                        f"[V7.1-Fix2] {self.stock_code} {timeframe.value}: "
                        f"과거 캔들 → 실시간 전환 (O={old_ohlc[0]} 유지, H/L={tick.price}로 리셋)"
                    )
                else:
                    # 기존 봉 업데이트
                    current.high = max(current.high, tick.price)
                    current.low = min(current.low, tick.price)
                    current.close = tick.price
                    current.volume += tick.volume

            # C-003 FIX: 역순 틱이 이미 완성된 과거 봉에 해당하는 경우
            # - 완성된 봉은 수정할 수 없으므로 로그만 남기고 스킵
            if is_out_of_order and current is not None and candle_start < current.time:
                # 100번마다 로그 (과도한 로깅 방지)
                if self._out_of_order_count % 100 == 1:
                    self._logger.debug(
                        f"[C-003] {self.stock_code} {timeframe.value}: "
                        f"역순 틱이 과거 봉에 해당 - 스킵 (candle_start={candle_start}, current={current.time})"
                    )

        # C-003 FIX: 마지막 처리 틱 시간 업데이트 (역순 틱이 아닐 때만)
        if not is_out_of_order:
            self._last_tick_time = tick.timestamp

        return completed_candles if completed_candles else None

    async def on_tick_async(self, tick: Tick) -> None:
        """
        비동기 틱 처리 (콜백 포함)

        Args:
            tick: 체결 틱 데이터
        """
        completed = self.on_tick(tick)

        # 봉 완성 로깅
        if completed:
            timeframes = [c.timeframe.value for c in completed]
            self._logger.info(
                f"[CandleBuilder] 봉완성: {self.stock_code} {timeframes} "
                f"콜백={self.on_candle_complete is not None}"
            )

        if completed and self.on_candle_complete:
            for candle in completed:
                try:
                    await self.on_candle_complete(self.stock_code, candle)
                except Exception as e:
                    self._logger.error(
                        "봉 완성 콜백 에러",
                        stock_code=self.stock_code,
                        error=str(e),
                    )
        elif completed and not self.on_candle_complete:
            self._logger.warning(
                f"[CandleBuilder] 봉완성됐으나 콜백 없음: {self.stock_code}"
            )

    def get_candles(self, timeframe: Timeframe, include_current: bool = False) -> pd.DataFrame:
        """
        지정 타임프레임의 봉 데이터를 DataFrame으로 반환

        Args:
            timeframe: 타임프레임 (M1, M3)
            include_current: 현재 진행 중인 봉 포함 여부

        Returns:
            봉 데이터 DataFrame (columns: time, open, high, low, close, volume)
        """
        # 캐시 유효 시 반환
        if not self._df_dirty[timeframe] and timeframe in self._df_cache:
            df = self._df_cache[timeframe].copy()
            if include_current and timeframe in self._current_candles:
                current = self._current_candles[timeframe]
                current_df = pd.DataFrame([current.to_dict()])
                df = pd.concat([df, current_df], ignore_index=True)
            return df

        # DataFrame 생성
        candles = self._candles[timeframe]
        if not candles:
            df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        else:
            df = pd.DataFrame([c.to_dict() for c in candles])

        # 캐시 저장
        self._df_cache[timeframe] = df.copy()
        self._df_dirty[timeframe] = False

        # 현재 봉 추가
        if include_current and timeframe in self._current_candles:
            current = self._current_candles[timeframe]
            current_df = pd.DataFrame([current.to_dict()])
            df = pd.concat([df, current_df], ignore_index=True)

        return df

    def get_current_candle(self, timeframe: Timeframe) -> Optional[Candle]:
        """현재 진행 중인 봉 반환"""
        return self._current_candles.get(timeframe)

    def get_latest_candles(self, timeframe: Timeframe, count: int = 1) -> List[Candle]:
        """최근 완성된 봉 N개 반환"""
        candles = self._candles.get(timeframe, [])
        return candles[-count:] if candles else []

    def get_candle_count(self, timeframe: Timeframe) -> int:
        """완성된 봉 개수"""
        return len(self._candles.get(timeframe, []))

    def update_candles_from_api(
        self,
        api_candles: List["Candle"],
        timeframe: Timeframe,
    ) -> int:
        """
        API에서 조회한 정확한 캔들 데이터로 기존 캔들 업데이트

        REST 폴링으로 생성된 캔들의 OHLCV가 부정확할 수 있으므로,
        API에서 조회한 정확한 데이터로 덮어씁니다.

        Args:
            api_candles: API에서 조회한 캔들 리스트 (정확한 OHLCV)
            timeframe: 타임프레임

        Returns:
            업데이트된 캔들 수
        """
        if not api_candles:
            return 0

        # 기존 캔들을 시간 기준으로 맵핑
        existing = self._candles[timeframe]
        existing_map = {c.time: c for c in existing}

        updated_count = 0
        added_count = 0

        for api_candle in api_candles:
            if api_candle.time in existing_map:
                # 기존 캔들 업데이트
                old = existing_map[api_candle.time]
                old.open = api_candle.open
                old.high = api_candle.high
                old.low = api_candle.low
                old.close = api_candle.close
                old.volume = api_candle.volume
                old.is_complete = True
                updated_count += 1
            else:
                # 새 캔들 추가
                existing.append(api_candle)
                existing_map[api_candle.time] = api_candle
                added_count += 1

        # 시간순 재정렬
        self._candles[timeframe] = sorted(existing, key=lambda c: c.time)

        # 최대 개수 유지
        if len(self._candles[timeframe]) > self._max_candles:
            self._candles[timeframe] = self._candles[timeframe][-self._max_candles:]

        # 캐시 무효화
        self._df_dirty[timeframe] = True

        if updated_count > 0 or added_count > 0:
            self._logger.debug(
                f"[API 업데이트] {self.stock_code} {timeframe.value}: "
                f"업데이트={updated_count}개, 추가={added_count}개"
            )

        return updated_count + added_count

    def clear(self) -> None:
        """모든 봉 데이터 초기화"""
        self._current_candles.clear()
        for tf in self._candles:
            self._candles[tf].clear()
        self._df_cache.clear()
        for tf in self._df_dirty:
            self._df_dirty[tf] = True
        # C-003 FIX: 역순 틱 추적 초기화
        self._last_tick_time = None
        self._out_of_order_count = 0

    def get_out_of_order_stats(self) -> dict:
        """C-003: 역순 틱 통계 반환"""
        return {
            "stock_code": self.stock_code,
            "out_of_order_count": self._out_of_order_count,
            "last_tick_time": self._last_tick_time.isoformat() if self._last_tick_time else None,
        }

    def load_historical_candles(
        self,
        candles: List["Candle"],
        timeframe: Timeframe,
    ) -> int:
        """
        과거 캔들 데이터를 빌더에 주입

        Args:
            candles: 과거 캔들 리스트 (시간순 정렬 필요 없음)
            timeframe: 타임프레임

        Returns:
            로드된 캔들 수
        """
        if not candles:
            return 0

        # 시간순 정렬 (과거 → 최신)
        sorted_candles = sorted(candles, key=lambda c: c.time)

        # 기존 캔들과 병합 (과거 캔들 우선)
        existing = self._candles[timeframe]

        # 중복 제거를 위해 시간 기준 set
        existing_times = {c.time for c in existing}

        added_count = 0
        for candle in sorted_candles:
            if candle.time not in existing_times:
                existing.append(candle)
                existing_times.add(candle.time)
                added_count += 1

        # 시간순 재정렬
        self._candles[timeframe] = sorted(existing, key=lambda c: c.time)

        # 최대 개수 유지
        if len(self._candles[timeframe]) > self._max_candles:
            self._candles[timeframe] = self._candles[timeframe][-self._max_candles:]

        # 캐시 무효화
        self._df_dirty[timeframe] = True

        self._logger.info(
            f"[과거 로드] {self.stock_code} {timeframe.value}: {added_count}개 추가 "
            f"(총 {len(self._candles[timeframe])}개)"
        )

        # V6.2-J: 마지막 캔들로 _current_candles 초기화
        # 이렇게 해야 첫 번째 틱에서 새 봉 경계 시 완성 이벤트 발생
        if self._candles[timeframe]:
            last_candle = self._candles[timeframe][-1]
            self._current_candles[timeframe] = Candle(
                stock_code=self.stock_code,
                timeframe=timeframe,
                time=last_candle.time,
                open=last_candle.open,
                high=last_candle.high,
                low=last_candle.low,
                close=last_candle.close,
                volume=last_candle.volume,
                is_complete=True,
            )
            self._logger.debug(
                f"[V6.2-J] {self.stock_code} {timeframe.value}: "
                f"_current_candles 초기화 (time={last_candle.time})"
            )

        return added_count


class CandleManager:
    """
    다중 종목 CandleBuilder 관리자

    PRD v2.5: asyncio.Queue 기반 비동기 파이프라인 추가
    - 틱 데이터를 Queue에 넣으면 백그라운드에서 처리
    - 0.1초의 지연도 없이 처리

    C-003 FIX: 틱 버퍼링 + 시간순 정렬
    - 네트워크 지연으로 역순 도착하는 틱을 버퍼링
    - 주기적으로 시간순 정렬 후 처리

    Usage:
        manager = CandleManager()
        manager.add_stock("005930")
        await manager.start()  # Queue 처리 시작
        await manager.enqueue_tick(tick)  # 틱을 Queue에 추가
        await manager.stop()  # 정지
    """

    # C-003: 틱 버퍼 설정
    TICK_BUFFER_SIZE = 50        # 버퍼 크기 (틱 개수)
    TICK_BUFFER_FLUSH_MS = 100   # 버퍼 플러시 주기 (ms)

    def __init__(self):
        self._builders: Dict[str, CandleBuilder] = {}
        self._logger = get_logger(__name__)

        # 전역 콜백
        self.on_candle_complete: Optional[CandleCallback] = None

        # PRD v2.5: asyncio.Queue 기반 파이프라인
        # PRD v3.2.1: maxsize 설정으로 메모리 누수 방지
        self._tick_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._queue_task: Optional[asyncio.Task] = None
        self._running: bool = False

        # C-003 FIX: 틱 버퍼 (시간순 정렬용)
        self._tick_buffer: List[Tick] = []
        self._last_flush_time: datetime = datetime.now(KST)
        self._buffer_flush_task: Optional[asyncio.Task] = None

        # Phase 3-1: Queue Full 카운터 (모니터링용)
        self._queue_full_count: int = 0
        self._queue_full_log_threshold: int = 100  # N번마다 로그

    def add_stock(self, stock_code: str) -> CandleBuilder:
        """종목 추가"""
        if stock_code not in self._builders:
            builder = CandleBuilder(stock_code)
            builder.on_candle_complete = self._forward_callback
            self._builders[stock_code] = builder
            self._logger.info(f"CandleBuilder 추가: {stock_code}")
        return self._builders[stock_code]

    def remove_stock(self, stock_code: str) -> None:
        """종목 제거"""
        if stock_code in self._builders:
            del self._builders[stock_code]
            self._logger.info(f"CandleBuilder 제거: {stock_code}")

    def get_builder(self, stock_code: str) -> Optional[CandleBuilder]:
        """종목별 CandleBuilder 반환"""
        return self._builders.get(stock_code)

    def get_all_stock_codes(self) -> List[str]:
        """등록된 모든 종목 코드"""
        return list(self._builders.keys())

    async def on_tick(self, tick: Tick) -> None:
        """틱 데이터 처리"""
        builder = self._builders.get(tick.stock_code)
        if builder:
            await builder.on_tick_async(tick)

    async def _forward_callback(self, stock_code: str, candle: Candle) -> None:
        """개별 Builder 콜백을 전역 콜백으로 전달"""
        if self.on_candle_complete:
            await self.on_candle_complete(stock_code, candle)

    def get_candles(self, stock_code: str, timeframe: Timeframe) -> Optional[pd.DataFrame]:
        """특정 종목의 봉 데이터 반환"""
        builder = self._builders.get(stock_code)
        if builder:
            return builder.get_candles(timeframe)
        return None

    def clear_all(self) -> None:
        """모든 종목 데이터 초기화"""
        for builder in self._builders.values():
            builder.clear()

    def remove_all(self) -> None:
        """모든 종목 제거"""
        self._builders.clear()

    # =========================================
    # PRD v2.5: asyncio.Queue 기반 파이프라인
    # =========================================

    async def start(self) -> None:
        """Queue 처리 태스크 시작"""
        if self._running:
            return

        self._running = True
        self._queue_task = asyncio.create_task(self._process_queue())
        # C-003 FIX: 버퍼 플러시 태스크 시작
        self._buffer_flush_task = asyncio.create_task(self._flush_buffer_periodically())
        self._logger.info("CandleManager Queue 처리 시작 (C-003 버퍼링 활성화)")

    async def stop(self) -> None:
        """Queue 처리 태스크 정지"""
        self._running = False

        # C-003 FIX: 버퍼 플러시 태스크 정지
        if self._buffer_flush_task:
            self._buffer_flush_task.cancel()
            try:
                await self._buffer_flush_task
            except asyncio.CancelledError:
                pass
            self._buffer_flush_task = None

        if self._queue_task:
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass
            self._queue_task = None

        # C-003 FIX: 남은 버퍼 처리
        if self._tick_buffer:
            await self._flush_buffer()

        self._logger.info("CandleManager Queue 처리 정지")

    async def enqueue_tick(self, tick: Tick) -> None:
        """
        틱 데이터를 Queue에 추가 (non-blocking)

        PRD v2.5: 0.1초의 지연도 없이 처리
        PRD v3.2.1: Queue가 가득 차면 오래된 데이터 제거
        Phase 3-1: Queue Full 경고 배치 로깅 (과도한 로깅 방지)
        """
        try:
            self._tick_queue.put_nowait(tick)
        except asyncio.QueueFull:
            # Queue가 가득 참 - 오래된 데이터 제거 후 재시도
            try:
                self._tick_queue.get_nowait()  # 가장 오래된 틱 제거
                self._tick_queue.put_nowait(tick)

                # Phase 3-1: 카운터 증가 및 배치 로깅
                self._queue_full_count += 1
                if self._queue_full_count % self._queue_full_log_threshold == 1:
                    self._logger.warning(
                        f"[Phase 3-1] Queue 가득 참: {tick.stock_code} "
                        f"(총 {self._queue_full_count}회, 최신 데이터 우선)"
                    )
            except asyncio.QueueEmpty:
                pass

    async def _process_queue(self) -> None:
        """Queue에서 틱 데이터를 꺼내 버퍼에 추가 (백그라운드)"""
        while self._running:
            try:
                # 타임아웃으로 주기적 체크
                tick = await asyncio.wait_for(
                    self._tick_queue.get(),
                    timeout=0.05  # C-003: 50ms로 단축 (버퍼 플러시와 협력)
                )

                # C-003 FIX: 틱을 버퍼에 추가 (즉시 처리하지 않음)
                self._tick_buffer.append(tick)
                self._tick_queue.task_done()

                # 버퍼가 가득 차면 즉시 플러시
                if len(self._tick_buffer) >= self.TICK_BUFFER_SIZE:
                    await self._flush_buffer()

            except asyncio.TimeoutError:
                # 타임아웃 - 계속 대기
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Queue 처리 에러: {e}")

    async def _flush_buffer_periodically(self) -> None:
        """C-003 FIX: 주기적으로 버퍼 플러시 (시간순 정렬 후 처리)"""
        while self._running:
            try:
                await asyncio.sleep(self.TICK_BUFFER_FLUSH_MS / 1000.0)
                if self._tick_buffer:
                    await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"버퍼 플러시 에러: {e}")

    async def _flush_buffer(self) -> None:
        """C-003 FIX: 버퍼의 틱을 시간순 정렬 후 처리"""
        if not self._tick_buffer:
            return

        # 버퍼 스왑 (처리 중 새 틱 수신 허용)
        ticks_to_process = self._tick_buffer
        self._tick_buffer = []

        # 시간순 정렬 (역순 도착 틱 정렬)
        ticks_to_process.sort(key=lambda t: t.timestamp)

        # 정렬된 순서로 처리
        for tick in ticks_to_process:
            try:
                await self.on_tick(tick)
            except Exception as e:
                self._logger.error(f"틱 처리 에러 ({tick.stock_code}): {e}")

        self._last_flush_time = datetime.now(KST)

    @property
    def queue_size(self) -> int:
        """현재 Queue 크기"""
        return self._tick_queue.qsize()

    @property
    def buffer_size(self) -> int:
        """C-003: 현재 버퍼 크기"""
        return len(self._tick_buffer)

    def get_out_of_order_stats(self) -> dict:
        """C-003 + Phase 3-1: 전체 틱 처리 통계 반환"""
        total_out_of_order = 0
        builder_stats = []
        for code, builder in self._builders.items():
            stats = builder.get_out_of_order_stats()
            total_out_of_order += stats["out_of_order_count"]
            if stats["out_of_order_count"] > 0:
                builder_stats.append(stats)

        return {
            "total_out_of_order_ticks": total_out_of_order,
            "buffer_size": self.buffer_size,
            "queue_size": self.queue_size,
            # Phase 3-1: Queue Full 통계 추가
            "queue_full_count": self._queue_full_count,
            "builders_with_out_of_order": builder_stats,
        }
