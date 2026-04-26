#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SNIPER_TRAP 12월 주도주 당일 진입 백테스트

12월 거래대금 1000억+ & 10%+ 상승한 종목의 당일 09:30 이후 3분봉 신호를 탐지하여
당일 청산 시뮬레이션을 수행합니다.

Usage:
    # 기본 실행
    python scripts/backtest/sniper_trap_intraday_december.py --top-n 100

    # 옵션 지정
    python scripts/backtest/sniper_trap_intraday_december.py --top-n 200 --dec-year 2024 --min-change 10

    # 엑셀 저장
    python scripts/backtest/sniper_trap_intraday_december.py --top-n 100 --output results.xlsx
"""

import asyncio
import argparse
import sys
import json
from pathlib import Path
from datetime import datetime, date, time, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import pandas as pd

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_config, get_settings
from src.utils.logger import setup_logging, get_logger
from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI, RankingItem, DailyCandle, MinuteCandle
from src.core.indicator import Indicator


# ============================================================
# 설정
# ============================================================

@dataclass
class IntradayBacktestConfig:
    """당일 진입 백테스트 설정"""
    # 데이터
    lookback_days: int = 300           # 일봉 조회 일수
    min_candles: int = 205             # 최소 일봉 수 (EMA200용)

    # 12월 기준봉 필터
    december_year: int = 2024          # 12월 기준 연도
    trigger_trading_value: int = 100_000_000_000  # 1000억원
    min_trigger_change_rate: float = 10.0         # 최소 등락률 10%

    # 분봉 설정
    timeframe: int = 3                 # 3분봉
    min_minute_candles: int = 65       # EMA 안정화용 최소 봉 수
    signal_start_time: time = field(default_factory=lambda: time(9, 30))   # 09:30 이후
    market_close_time: time = field(default_factory=lambda: time(15, 27))  # 15:27 청산

    # SNIPER_TRAP 조건
    min_body_size: float = 0.3         # 최소 캔들 몸통 크기 (%)

    # 청산 조건
    stop_loss_rate: float = -4.0       # 고정 손절 (%)
    atr_period: int = 14               # ATR 기간
    atr_mult: float = 6.0              # ATR 배수
    max_holding_days: int = 60         # 최대 보유일

    # 비용
    slippage_rate: float = 0.001       # 슬리피지 0.1%
    commission_rate: float = 0.00015   # 수수료 0.015%
    tax_rate: float = 0.0018           # 거래세 0.18%

    # 투자
    investment_per_trade: int = 1_000_000  # 1회 투자금액 (100만원)

    # 분봉 연속조회 설정
    max_minute_pages: int = 500        # 최대 페이지 수 (약 50,000봉 = ~3개월)


@dataclass
class TriggerCandle:
    """12월 기준봉 정보"""
    stock_code: str
    stock_name: str
    trigger_date: date
    trading_value: int                 # 거래대금 (원)
    close_price: int
    change_rate: float                 # 등락률 (%)


@dataclass
class IntradaySignal:
    """분봉 신호"""
    stock_code: str
    stock_name: str
    signal_datetime: datetime          # 신호 발생 시각
    signal_price: int                  # 신호 발생가 (종가)
    ema3: float
    ema20: float
    ema60: float
    ema200: float
    body_size_pct: float
    volume_ratio: float


@dataclass
class IntradayTrade:
    """거래 결과 (진입: 분봉, 청산: 일봉)"""
    stock_code: str
    stock_name: str
    trigger_date: date                 # 기준봉 날짜

    # 진입
    entry_datetime: datetime           # 진입 시각
    entry_price: int                   # 진입가

    # 청산
    exit_date: date                    # 청산일 (일봉 기준)
    exit_price: int
    exit_type: str                     # "HARD_STOP" | "ATR_TS" | "MAX_HOLDING"

    # 손익
    quantity: int
    holding_days: int                  # 보유일수
    gross_pnl: int
    total_cost: int
    net_pnl: int
    return_rate: float                 # 수익률 (%)


@dataclass
class IntradaySummary:
    """백테스트 요약"""
    trigger_count: int                 # 기준봉 수
    signal_count: int                  # 신호 발생 수
    trade_count: int                   # 거래 체결 수

    # 손익
    total_gross_pnl: int
    total_cost: int
    total_net_pnl: int

    # 통계
    win_count: int
    loss_count: int
    win_rate: float
    avg_return: float
    max_return: float
    min_return: float
    avg_holding_days: float            # 평균 보유일수

    # 청산 유형별
    hard_stop_count: int
    atr_ts_count: int
    max_holding_count: int             # 최대보유일 청산

    # 추가 지표
    profit_factor: float               # 총이익 / 총손실


# ============================================================
# 백테스트 엔진
# ============================================================

class SniperTrapIntradayBacktester:
    """SNIPER_TRAP 당일 진입 백테스터"""

    ETF_KEYWORDS = [
        "KODEX", "TIGER", "RISE", "SOL", "HANARO", "PLUS", "KBSTAR",
        "ACE", "ARIRANG", "KOSEF", "SMART", "TREX", "FOCUS", "파워",
        "레버리지", "인버스", "ETN", "ETF"
    ]

    def __init__(self, config: IntradayBacktestConfig):
        self.config = config
        self.logger = get_logger(__name__)
        self._client: Optional[KiwoomAPIClient] = None
        self._market_api: Optional[MarketAPI] = None

    async def __aenter__(self):
        self._client = KiwoomAPIClient()
        await self._client.__aenter__()
        self._market_api = MarketAPI(self._client)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    # ----------------------------------------------------------
    # 유틸리티
    # ----------------------------------------------------------

    def is_etf(self, stock_name: str) -> bool:
        """ETF 여부 확인"""
        for keyword in self.ETF_KEYWORDS:
            if keyword in stock_name.upper():
                return True
        return False

    # ----------------------------------------------------------
    # 데이터 수집 (일봉)
    # ----------------------------------------------------------

    async def get_top_stocks(self, top_n: int) -> List[RankingItem]:
        """거래대금 상위 종목 조회 (KOSPI + KOSDAQ 각각 조회 후 병합)"""
        self.logger.info(f"거래대금 상위 {top_n}개 종목 조회 중 (KOSPI + KOSDAQ 분리)...")

        # KOSPI와 KOSDAQ 각각 조회
        kospi_stocks = await self._market_api.get_trading_volume_ranking(
            market="1",  # KOSPI
            top_n=top_n
        )
        self.logger.info(f"  KOSPI: {len(kospi_stocks)}개")

        await asyncio.sleep(0.3)

        kosdaq_stocks = await self._market_api.get_trading_volume_ranking(
            market="2",  # KOSDAQ
            top_n=top_n
        )
        self.logger.info(f"  KOSDAQ: {len(kosdaq_stocks)}개")

        # 병합 (중복 제거)
        seen = set()
        all_stocks = []
        for stock in kospi_stocks + kosdaq_stocks:
            if stock.stock_code not in seen:
                seen.add(stock.stock_code)
                all_stocks.append(stock)

        # ETF 제외
        filtered = [s for s in all_stocks if not self.is_etf(s.stock_name)]
        self.logger.info(f"조회 완료: {len(filtered)}개 종목 (ETF 제외, 병합)")

        return filtered

    def load_stocks_from_cache(self, max_stocks: int = None) -> List[RankingItem]:
        """캐시 파일에서 전체 종목 리스트 로드"""
        cache_path = project_root / "data" / "cache" / "stock_list_cache.json"

        if not cache_path.exists():
            self.logger.warning(f"캐시 파일 없음: {cache_path}")
            return []

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            stocks = []
            for item in data.get("stocks", []):
                code = item.get("code", "")
                name = item.get("name", "")

                # ETF/우선주 제외
                if self.is_etf(name) or code.endswith("K") or "우" in name:
                    continue

                stocks.append(RankingItem(
                    rank=len(stocks) + 1,
                    stock_code=code,
                    stock_name=name,
                    current_price=0,
                    change_rate=0.0,
                    volume=0,
                    trading_value=0,
                ))

            if max_stocks and len(stocks) > max_stocks:
                stocks = stocks[:max_stocks]

            self.logger.info(f"캐시에서 {len(stocks)}개 종목 로드")
            return stocks

        except Exception as e:
            self.logger.error(f"캐시 로드 실패: {e}")
            return []

    def load_stocks_from_past1000(self) -> List[RankingItem]:
        """past1000.csv에서 종목 리스트 로드"""
        csv_path = project_root / "past1000.csv"

        if not csv_path.exists():
            self.logger.warning(f"past1000.csv 없음: {csv_path}")
            return []

        try:
            # EUC-KR 또는 CP949로 읽기
            df = pd.read_csv(csv_path, encoding="cp949")

            stocks = []
            for _, row in df.iterrows():
                # 종목코드 정리 (앞의 ' 제거)
                code = str(row.iloc[0]).replace("'", "").strip()
                name = str(row.iloc[1]).strip()

                # 6자리 숫자만
                if not code.replace("A", "").isdigit():
                    continue
                code = code.replace("A", "").zfill(6)

                # ETF/우선주 제외
                if self.is_etf(name) or "우" in name:
                    continue

                stocks.append(RankingItem(
                    rank=len(stocks) + 1,
                    stock_code=code,
                    stock_name=name,
                    current_price=0,
                    change_rate=0.0,
                    volume=0,
                    trading_value=0,
                ))

            self.logger.info(f"past1000.csv에서 {len(stocks)}개 종목 로드")
            return stocks

        except Exception as e:
            self.logger.error(f"past1000.csv 로드 실패: {e}")
            return []

    async def get_daily_candles(self, stock_code: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 조회"""
        try:
            candles = await self._market_api.get_daily_chart(
                stock_code=stock_code,
                count=self.config.lookback_days
            )

            if not candles:
                return None

            df = pd.DataFrame([
                {
                    "date": c.date,
                    "open": c.open_price,
                    "high": c.high_price,
                    "low": c.low_price,
                    "close": c.close_price,
                    "volume": c.volume,
                    "trading_value": getattr(c, 'trading_value', 0),
                }
                for c in candles
            ])

            df.set_index("date", inplace=True)
            return df

        except Exception as e:
            self.logger.warning(f"{stock_code}: 일봉 조회 실패 - {e}")
            return None

    async def load_daily_data(
        self,
        stocks: List[RankingItem],
        delay_ms: int = 500
    ) -> Dict[str, Tuple[pd.DataFrame, str]]:
        """일봉 데이터 로딩"""
        data = {}
        total = len(stocks)

        for i, stock in enumerate(stocks, 1):
            self.logger.info(f"[{i}/{total}] {stock.stock_code} {stock.stock_name} 일봉 로딩...")

            df = await self.get_daily_candles(stock.stock_code)

            if df is not None and len(df) >= self.config.min_candles:
                data[stock.stock_code] = (df, stock.stock_name)
            else:
                candle_count = len(df) if df is not None else 0
                self.logger.warning(f"  -> 스킵 (일봉: {candle_count} < {self.config.min_candles})")

            if i < total:
                await asyncio.sleep(delay_ms / 1000)

        return data

    # ----------------------------------------------------------
    # 12월 기준봉 탐색
    # ----------------------------------------------------------

    def find_december_triggers(
        self,
        data: Dict[str, Tuple[pd.DataFrame, str]]
    ) -> List[TriggerCandle]:
        """12월 거래대금 1000억+ & 10%+ 상승 봉 찾기"""
        triggers = []
        target_year = self.config.december_year
        min_value = self.config.trigger_trading_value
        min_change = self.config.min_trigger_change_rate

        for stock_code, (df, stock_name) in data.items():
            for idx, row in df.iterrows():
                # datetime 처리
                if isinstance(idx, datetime):
                    candle_date = idx.date()
                    candle_month = idx.month
                    candle_year = idx.year
                elif isinstance(idx, date):
                    candle_date = idx
                    candle_month = idx.month
                    candle_year = idx.year
                else:
                    continue

                # 12월 필터
                if candle_year != target_year or candle_month != 12:
                    continue

                # 거래대금 필터
                trading_value = row.get("trading_value", 0)
                if trading_value < min_value:
                    continue

                # 등락률 계산 (시가 대비 종가)
                if row["open"] > 0:
                    change_rate = (row["close"] - row["open"]) / row["open"] * 100
                else:
                    change_rate = 0.0

                # 등락률 필터
                if change_rate < min_change:
                    continue

                triggers.append(TriggerCandle(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    trigger_date=candle_date,
                    trading_value=int(trading_value),
                    close_price=int(row["close"]),
                    change_rate=round(change_rate, 2)
                ))

                self.logger.info(
                    f"기준봉 발견: {stock_code} {stock_name} @ {candle_date} "
                    f"거래대금 {trading_value/1e8:.0f}억원, +{change_rate:.1f}%"
                )

        # 날짜순 정렬
        triggers.sort(key=lambda x: (x.trigger_date, x.stock_code))

        self.logger.info(f"12월 기준봉: 총 {len(triggers)}건 (1000억+ & {min_change}%+ 상승)")
        return triggers

    # ----------------------------------------------------------
    # 분봉 데이터 조회 (연속조회)
    # ----------------------------------------------------------

    async def get_minute_candles(
        self,
        stock_code: str,
        target_date: date,
        max_pages: int = None
    ) -> Optional[pd.DataFrame]:
        """
        특정 날짜의 분봉 데이터 조회 (연속조회 사용)

        Args:
            stock_code: 종목코드
            target_date: 조회할 날짜
            max_pages: 최대 페이지 수 (None이면 config 값 사용)

        Returns:
            해당 날짜의 분봉 DataFrame, 없으면 None
        """
        if max_pages is None:
            max_pages = self.config.max_minute_pages

        stock_code = stock_code.replace("A", "")
        CHART_URL = "/api/dostk/chart"

        body = {
            "stk_cd": stock_code,
            "tic_scope": str(self.config.timeframe),
            "upd_stkpc_tp": "0",
        }

        all_candles = []
        found_target = False

        try:
            # 연속조회로 분봉 데이터 수집
            all_responses = await self._client.paginate(
                url=CHART_URL,
                api_id="ka10080",
                body=body,
                max_pages=max_pages,
            )

            for response_data in all_responses:
                candles = self._parse_minute_data(response_data)
                for candle in candles:
                    candle_date = candle.timestamp.date()

                    # 목표 날짜 데이터만 수집
                    if candle_date == target_date:
                        all_candles.append(candle)
                        found_target = True
                    elif found_target and candle_date < target_date:
                        # 목표 날짜를 지나서 더 과거로 갔으면 중단
                        break

                # 목표 날짜를 지나갔으면 중단
                if all_candles and all_candles[-1].timestamp.date() < target_date:
                    break

        except Exception as e:
            self.logger.warning(f"{stock_code}: 분봉 조회 실패 - {e}")
            return None

        if not all_candles:
            self.logger.warning(f"{stock_code}: {target_date} 분봉 데이터 없음")
            return None

        # DataFrame 변환
        df = pd.DataFrame([
            {
                "datetime": c.timestamp,
                "open": c.open_price,
                "high": c.high_price,
                "low": c.low_price,
                "close": c.close_price,
                "volume": c.volume,
            }
            for c in all_candles
        ])

        # 시간 오름차순 정렬
        df.sort_values("datetime", inplace=True)
        df.set_index("datetime", inplace=True)

        self.logger.info(f"{stock_code} @ {target_date}: {len(df)}개 분봉 로드")

        return df

    def _parse_minute_data(self, response_data: dict) -> List[MinuteCandle]:
        """API 응답에서 분봉 데이터 파싱"""
        candles = []

        if isinstance(response_data, dict):
            data_list = response_data.get("stk_min_pole_chart_qry", [])
            if not data_list:
                data_list = response_data.get("output", response_data.get("list", []))
        else:
            data_list = response_data if isinstance(response_data, list) else []

        for item in data_list:
            try:
                time_str = str(item.get("cntr_tm", ""))

                if len(time_str) >= 14:
                    dt = datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
                else:
                    continue

                def parse_price(val):
                    if isinstance(val, str):
                        val = val.replace("+", "").replace("-", "")
                    return int(float(val)) if val else 0

                candle = MinuteCandle(
                    timestamp=dt,
                    open_price=parse_price(item.get("open_pric", 0)),
                    high_price=parse_price(item.get("high_pric", 0)),
                    low_price=parse_price(item.get("low_pric", 0)),
                    close_price=parse_price(item.get("cur_prc", 0)),
                    volume=int(float(item.get("trde_qty", 0))),
                )
                candles.append(candle)

            except (ValueError, TypeError) as e:
                continue

        return candles

    # ----------------------------------------------------------
    # 지표 계산
    # ----------------------------------------------------------

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """분봉 지표 계산"""
        df = df.copy()

        # EMA 계산 (adjust=False)
        df["ema3"] = Indicator.ema(df["close"], span=3)
        df["ema20"] = Indicator.ema(df["close"], span=20)
        df["ema60"] = Indicator.ema(df["close"], span=60)
        df["ema200"] = Indicator.ema(df["close"], span=200)

        # ATR 계산
        df["atr"] = Indicator.atr(df["high"], df["low"], df["close"], period=self.config.atr_period)

        return df

    # ----------------------------------------------------------
    # 신호 탐지
    # ----------------------------------------------------------

    def detect_intraday_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        first_only: bool = True
    ) -> List[IntradaySignal]:
        """
        09:30 이후 SNIPER_TRAP 신호 탐지

        조건:
        1. TrendFilter: close > EMA200 AND EMA60 > EMA60[5]
        2. Zone: low <= EMA20 AND close >= EMA60
        3. Meaningful: CrossUp(close, EMA3) AND 양봉 AND volume >= prev_volume
        4. BodySize: (close - open) / open * 100 >= 0.3
        """
        if len(df) < self.config.min_minute_candles:
            self.logger.warning(f"{stock_code}: 분봉 부족 ({len(df)} < {self.config.min_minute_candles})")
            return []

        df = self.calculate_indicators(df)
        signals = []

        # EMA 안정화 이후부터 탐지
        start_idx = max(self.config.min_minute_candles, 5)

        for i in range(start_idx, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]

            # 시간 확인 (09:30 이후)
            curr_time = curr.name.time() if hasattr(curr.name, 'time') else curr.name
            if isinstance(curr_time, time):
                if curr_time < self.config.signal_start_time:
                    continue

            # EMA60[5]
            ema60_5ago = df["ema60"].iloc[i - 5]

            # 1. TrendFilter
            trend_ok = (
                curr["close"] > curr["ema200"] and
                curr["ema60"] > ema60_5ago
            )
            if not trend_ok:
                continue

            # 2. Zone
            zone_ok = (
                curr["low"] <= curr["ema20"] and
                curr["close"] >= curr["ema60"]
            )
            if not zone_ok:
                continue

            # 3. Meaningful
            crossup = (
                prev["close"] < prev["ema3"] and
                curr["close"] >= curr["ema3"]
            )
            bullish = curr["close"] > curr["open"]
            volume_up = curr["volume"] >= prev["volume"]
            meaningful = crossup and bullish and volume_up
            if not meaningful:
                continue

            # 4. BodySize
            if curr["open"] == 0:
                continue
            body_size = (curr["close"] - curr["open"]) / curr["open"] * 100
            if body_size < self.config.min_body_size:
                continue

            # 신호 발생!
            volume_ratio = curr["volume"] / prev["volume"] if prev["volume"] > 0 else 0

            signals.append(IntradaySignal(
                stock_code=stock_code,
                stock_name=stock_name,
                signal_datetime=curr.name,
                signal_price=int(curr["close"]),
                ema3=float(curr["ema3"]),
                ema20=float(curr["ema20"]),
                ema60=float(curr["ema60"]),
                ema200=float(curr["ema200"]),
                body_size_pct=body_size,
                volume_ratio=volume_ratio
            ))

            self.logger.info(
                f"  신호 발생: {curr.name.strftime('%H:%M')} @ {int(curr['close']):,}원"
            )

            if first_only:
                break

        return signals

    # ----------------------------------------------------------
    # 거래 시뮬레이션 (일봉 기반 청산)
    # ----------------------------------------------------------

    def simulate_trade_with_daily(
        self,
        signal: IntradaySignal,
        daily_df: pd.DataFrame,
        trigger_date: date
    ) -> Optional[IntradayTrade]:
        """
        진입: 분봉 신호가, 청산: 일봉 기반 ATR 트레일링 스탑

        1. 진입: 신호 발생 봉의 종가
        2. 청산 조건 (일봉 기준):
           - HARD_STOP: bar_low <= entry_price * 0.96 (-4%)
           - ATR_TS: close <= trailing_stop
           - MAX_HOLDING: 60일 초과
        """
        # 진입
        entry_price = signal.signal_price
        entry_price_with_slip = int(entry_price * (1 + self.config.slippage_rate))
        entry_datetime = signal.signal_datetime
        entry_date = entry_datetime.date()

        # 투자 수량
        quantity = self.config.investment_per_trade // entry_price_with_slip
        if quantity < 1:
            return None

        # 손절가
        stop_loss_price = int(entry_price_with_slip * (1 + self.config.stop_loss_rate / 100))

        # 일봉 데이터에서 진입일 이후 인덱스 찾기
        entry_idx = None
        for i, idx in enumerate(daily_df.index):
            idx_date = idx.date() if isinstance(idx, datetime) else idx
            if idx_date >= entry_date:
                entry_idx = i
                break

        if entry_idx is None:
            self.logger.warning(f"  일봉 데이터에서 진입일 {entry_date} 찾기 실패")
            return None

        # 일봉 지표 계산
        daily_df = self.calculate_indicators(daily_df)

        # ATR 트레일링 스탑 초기화
        initial_atr = daily_df["atr"].iloc[entry_idx] if entry_idx < len(daily_df) else 0

        if initial_atr > 0:
            entry_candle = daily_df.iloc[entry_idx]
            hlc3 = (entry_candle["high"] + entry_candle["low"] + entry_candle["close"]) / 3
            trailing_stop = hlc3 - (initial_atr * self.config.atr_mult)
        else:
            trailing_stop = stop_loss_price

        # 청산 시뮬레이션 (일봉 기준)
        exit_price = None
        exit_date = None
        exit_type = None

        for i in range(entry_idx + 1, len(daily_df)):
            bar = daily_df.iloc[i]
            bar_date = bar.name.date() if isinstance(bar.name, datetime) else bar.name
            holding_days = (bar_date - entry_date).days

            # 1순위: 고정 손절
            if bar["low"] <= stop_loss_price:
                exit_price = stop_loss_price
                exit_date = bar_date
                exit_type = "HARD_STOP"
                break

            # 2순위: ATR 트레일링 스탑 (ATR 기간 이후부터)
            if i >= entry_idx + self.config.atr_period:
                atr = daily_df["atr"].iloc[i] if i < len(daily_df) else initial_atr
                if atr > 0:
                    hlc3 = (bar["high"] + bar["low"] + bar["close"]) / 3
                    new_ts = hlc3 - (atr * self.config.atr_mult)
                    if new_ts > trailing_stop:
                        trailing_stop = new_ts

                if bar["close"] <= trailing_stop:
                    exit_price = int(trailing_stop)
                    exit_date = bar_date
                    exit_type = "ATR_TS"
                    break

            # 3순위: 최대 보유일
            if holding_days > self.config.max_holding_days:
                exit_price = int(bar["close"])
                exit_date = bar_date
                exit_type = "MAX_HOLDING"
                break

        # 청산 안됐으면 마지막 일봉에서 청산
        if exit_price is None:
            last_bar = daily_df.iloc[-1]
            exit_price = int(last_bar["close"])
            exit_date = last_bar.name.date() if isinstance(last_bar.name, datetime) else last_bar.name
            exit_type = "MAX_HOLDING"

        # 보유일수 계산
        holding_days = (exit_date - entry_date).days

        # 비용 계산
        exit_price_with_slip = int(exit_price * (1 - self.config.slippage_rate))
        entry_cost = int(entry_price_with_slip * quantity * self.config.commission_rate)
        exit_cost = int(exit_price_with_slip * quantity * (self.config.commission_rate + self.config.tax_rate))
        total_cost = entry_cost + exit_cost

        # 손익 계산
        gross_pnl = (exit_price_with_slip - entry_price_with_slip) * quantity
        net_pnl = gross_pnl - total_cost
        return_rate = (exit_price_with_slip - entry_price_with_slip) / entry_price_with_slip * 100

        return IntradayTrade(
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            trigger_date=trigger_date,
            entry_datetime=entry_datetime,
            entry_price=entry_price_with_slip,
            exit_date=exit_date,
            exit_price=exit_price_with_slip,
            exit_type=exit_type,
            quantity=quantity,
            holding_days=holding_days,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            net_pnl=net_pnl,
            return_rate=return_rate
        )

    # ----------------------------------------------------------
    # 요약 통계
    # ----------------------------------------------------------

    def calculate_summary(
        self,
        triggers: List[TriggerCandle],
        signals: List[IntradaySignal],
        trades: List[IntradayTrade]
    ) -> IntradaySummary:
        """통계 계산"""
        win_count = sum(1 for t in trades if t.net_pnl > 0)
        loss_count = sum(1 for t in trades if t.net_pnl <= 0)

        # 청산 유형별
        hard_stop_count = sum(1 for t in trades if t.exit_type == "HARD_STOP")
        atr_ts_count = sum(1 for t in trades if t.exit_type == "ATR_TS")
        max_holding_count = sum(1 for t in trades if t.exit_type == "MAX_HOLDING")

        # 손익
        returns = [t.return_rate for t in trades]
        total_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        total_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))

        if total_loss > 0:
            profit_factor = total_profit / total_loss
        else:
            profit_factor = float('inf') if total_profit > 0 else 0.0

        return IntradaySummary(
            trigger_count=len(triggers),
            signal_count=len(signals),
            trade_count=len(trades),
            total_gross_pnl=sum(t.gross_pnl for t in trades),
            total_cost=sum(t.total_cost for t in trades),
            total_net_pnl=sum(t.net_pnl for t in trades),
            win_count=win_count,
            loss_count=loss_count,
            win_rate=(win_count / len(trades) * 100) if trades else 0.0,
            avg_return=sum(returns) / len(returns) if returns else 0.0,
            max_return=max(returns) if returns else 0.0,
            min_return=min(returns) if returns else 0.0,
            avg_holding_days=sum(t.holding_days for t in trades) / len(trades) if trades else 0.0,
            hard_stop_count=hard_stop_count,
            atr_ts_count=atr_ts_count,
            max_holding_count=max_holding_count,
            profit_factor=profit_factor
        )

    # ----------------------------------------------------------
    # 결과 출력
    # ----------------------------------------------------------

    def print_results(self, triggers: List[TriggerCandle], trades: List[IntradayTrade], summary: IntradaySummary):
        """콘솔 출력"""
        print("\n" + "=" * 80)
        print("  SNIPER_TRAP 12월 주도주 당일 진입 백테스트")
        print("=" * 80)
        print(f"  기준: {self.config.december_year}년 12월")
        print(f"  조건: 거래대금 {self.config.trigger_trading_value / 1e8:.0f}억+ & "
              f"+{self.config.min_trigger_change_rate:.0f}% 상승")
        print("-" * 80)
        print(f"  기준봉 수: {summary.trigger_count}건")
        print(f"  신호 발생: {summary.signal_count}건")
        print(f"  거래 체결: {summary.trade_count}건")
        print("-" * 80)

        if trades:
            print(f"  승: {summary.win_count}건 / 패: {summary.loss_count}건")
            print(f"  승률: {summary.win_rate:.1f}%")
            print("-" * 80)
            print(f"  총 매매차익: {summary.total_gross_pnl:+,}원")
            print(f"  총 비용: {summary.total_cost:,}원")
            print(f"  순손익: {summary.total_net_pnl:+,}원")
            print("-" * 80)
            print(f"  평균 수익률: {summary.avg_return:+.2f}%")
            print(f"  최대 수익률: {summary.max_return:+.2f}%")
            print(f"  최대 손실률: {summary.min_return:+.2f}%")
            print(f"  평균 보유일: {summary.avg_holding_days:.1f}일")
            print("-" * 80)
            print(f"  Profit Factor: {summary.profit_factor:.2f}")
            print("-" * 80)
            print("  [청산 유형별 분포]")
            total_exits = summary.hard_stop_count + summary.atr_ts_count + summary.max_holding_count
            if total_exits > 0:
                print(f"    HARD_STOP (-4%): {summary.hard_stop_count}건 "
                      f"({summary.hard_stop_count/total_exits*100:.1f}%)")
                print(f"    ATR_TS: {summary.atr_ts_count}건 "
                      f"({summary.atr_ts_count/total_exits*100:.1f}%)")
                print(f"    MAX_HOLDING (60일): {summary.max_holding_count}건 "
                      f"({summary.max_holding_count/total_exits*100:.1f}%)")
        else:
            print("  거래 없음")

        print("=" * 80)

        # 기준봉 목록
        if triggers:
            print("\n[기준봉 목록]")
            print("-" * 80)
            print(f"{'날짜':^12} {'종목':^15} {'거래대금':>12} {'등락률':>8}")
            print("-" * 80)
            for t in triggers[:20]:
                print(f"{str(t.trigger_date):^12} {t.stock_name[:10]:<15} "
                      f"{t.trading_value/1e8:>10.0f}억 {t.change_rate:>+7.1f}%")
            if len(triggers) > 20:
                print(f"  ... 외 {len(triggers) - 20}건")
            print("-" * 80)

        # 거래 내역
        if trades:
            print("\n[거래 내역 (수익률순)]")
            print("-" * 110)
            print(f"{'진입일':^12} {'종목':^12} {'진입시간':^8} {'진입가':>10} "
                  f"{'청산일':^12} {'청산가':>10} {'보유일':>5} {'청산유형':^12} {'수익률':>8}")
            print("-" * 110)

            for t in sorted(trades, key=lambda x: x.return_rate, reverse=True)[:20]:
                entry_time = t.entry_datetime.strftime("%H:%M")
                print(f"{str(t.entry_datetime.date()):^12} {t.stock_name[:10]:<12} "
                      f"{entry_time:^8} {t.entry_price:>10,} "
                      f"{str(t.exit_date):^12} {t.exit_price:>10,} "
                      f"{t.holding_days:>5} {t.exit_type:^12} {t.return_rate:>+7.2f}%")

            if len(trades) > 20:
                print(f"  ... 외 {len(trades) - 20}건")
            print("-" * 110)

    def export_to_excel(self, triggers: List[TriggerCandle], trades: List[IntradayTrade], summary: IntradaySummary, output_path: str):
        """엑셀 파일 출력"""
        try:
            # Sheet 1: 요약
            summary_data = {
                "항목": [
                    "기준 연월", "거래대금 기준", "등락률 기준",
                    "기준봉 수", "신호 발생 수", "거래 체결 수",
                    "승", "패", "승률",
                    "총 매매차익", "총 비용", "순손익",
                    "평균 수익률", "최대 수익률", "최대 손실률", "평균 보유일",
                    "Profit Factor",
                    "HARD_STOP", "ATR_TS", "MAX_HOLDING"
                ],
                "값": [
                    f"{self.config.december_year}년 12월",
                    f"{self.config.trigger_trading_value / 1e8:.0f}억+",
                    f"+{self.config.min_trigger_change_rate:.0f}%",
                    summary.trigger_count, summary.signal_count, summary.trade_count,
                    summary.win_count, summary.loss_count, f"{summary.win_rate:.1f}%",
                    f"{summary.total_gross_pnl:+,}", f"{summary.total_cost:,}", f"{summary.total_net_pnl:+,}",
                    f"{summary.avg_return:+.2f}%", f"{summary.max_return:+.2f}%",
                    f"{summary.min_return:+.2f}%", f"{summary.avg_holding_days:.1f}일",
                    f"{summary.profit_factor:.2f}",
                    summary.hard_stop_count, summary.atr_ts_count, summary.max_holding_count
                ]
            }
            df_summary = pd.DataFrame(summary_data)

            # Sheet 2: 기준봉
            triggers_data = [{
                "날짜": str(t.trigger_date),
                "종목코드": t.stock_code,
                "종목명": t.stock_name,
                "거래대금(억)": t.trading_value / 1e8,
                "종가": t.close_price,
                "등락률(%)": t.change_rate
            } for t in triggers]
            df_triggers = pd.DataFrame(triggers_data)

            # Sheet 3: 거래 내역
            trades_data = [{
                "기준봉날짜": str(t.trigger_date),
                "종목코드": t.stock_code,
                "종목명": t.stock_name,
                "진입시간": t.entry_datetime.strftime("%Y-%m-%d %H:%M"),
                "진입가": t.entry_price,
                "청산일": str(t.exit_date),
                "청산가": t.exit_price,
                "청산유형": t.exit_type,
                "수량": t.quantity,
                "보유일": t.holding_days,
                "매매차익": t.gross_pnl,
                "비용": t.total_cost,
                "순손익": t.net_pnl,
                "수익률(%)": round(t.return_rate, 2)
            } for t in trades]
            df_trades = pd.DataFrame(trades_data)

            # 엑셀 저장
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name='요약', index=False)
                df_triggers.to_excel(writer, sheet_name='기준봉', index=False)
                df_trades.to_excel(writer, sheet_name='거래내역', index=False)

            print(f"\n엑셀 파일 저장: {output_path}")

        except ImportError:
            print("\n[경고] openpyxl 미설치. pip install openpyxl 필요")
        except Exception as e:
            print(f"\n[오류] 엑셀 저장 실패: {e}")

    # ----------------------------------------------------------
    # 메인 실행
    # ----------------------------------------------------------

    async def run(
        self,
        top_n: int = 100,
        use_cache: bool = False,
        use_past1000: bool = False
    ) -> Tuple[List[TriggerCandle], List[IntradayTrade], IntradaySummary]:
        """백테스트 실행"""
        # 설정 (최대 보유일)
        self.config.max_holding_days = 60

        # 1. 종목 리스트 확보
        if use_past1000:
            stocks = self.load_stocks_from_past1000()
        elif use_cache:
            stocks = self.load_stocks_from_cache(max_stocks=top_n)
        else:
            stocks = await self.get_top_stocks(top_n)

        # 2. 일봉 데이터 로딩
        self.logger.info("일봉 데이터 로딩 시작...")
        daily_data = await self.load_daily_data(stocks)

        # 3. 12월 기준봉 찾기
        self.logger.info("12월 기준봉 탐색 중...")
        triggers = self.find_december_triggers(daily_data)

        if not triggers:
            self.logger.warning("12월 기준봉 없음 - 백테스트 종료")
            empty_summary = IntradaySummary(
                trigger_count=0, signal_count=0, trade_count=0,
                total_gross_pnl=0, total_cost=0, total_net_pnl=0,
                win_count=0, loss_count=0, win_rate=0.0,
                avg_return=0.0, max_return=0.0, min_return=0.0,
                avg_holding_days=0.0,
                hard_stop_count=0, atr_ts_count=0, max_holding_count=0,
                profit_factor=0.0
            )
            return triggers, [], empty_summary

        # 4. 각 기준봉에 대해 분봉 데이터 조회 및 신호 탐지
        all_signals = []
        all_trades = []

        for i, trigger in enumerate(triggers, 1):
            self.logger.info(f"[{i}/{len(triggers)}] {trigger.stock_code} {trigger.stock_name} @ {trigger.trigger_date}")

            # 일봉 데이터 가져오기
            daily_df, _ = daily_data.get(trigger.stock_code, (None, None))
            if daily_df is None:
                self.logger.warning(f"  일봉 데이터 없음 - 스킵")
                continue

            # 분봉 데이터 조회
            minute_df = await self.get_minute_candles(
                stock_code=trigger.stock_code,
                target_date=trigger.trigger_date
            )

            if minute_df is None or len(minute_df) < self.config.min_minute_candles:
                self.logger.warning(f"  분봉 데이터 부족 - 스킵")
                continue

            # 신호 탐지
            signals = self.detect_intraday_signals(
                df=minute_df,
                stock_code=trigger.stock_code,
                stock_name=trigger.stock_name,
                first_only=True
            )
            all_signals.extend(signals)

            # 거래 시뮬레이션 (일봉 기반 청산)
            for signal in signals:
                trade = self.simulate_trade_with_daily(
                    signal=signal,
                    daily_df=daily_df,
                    trigger_date=trigger.trigger_date
                )
                if trade:
                    all_trades.append(trade)
                    self.logger.info(
                        f"  -> {trade.exit_type} @ {trade.exit_date} "
                        f"{trade.exit_price:,}원 ({trade.return_rate:+.2f}%) 보유 {trade.holding_days}일"
                    )

            # Rate limit
            await asyncio.sleep(0.5)

        # 5. 통계 계산
        summary = self.calculate_summary(triggers, all_signals, all_trades)

        return triggers, all_trades, summary


# ============================================================
# 메인
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="SNIPER_TRAP 12월 주도주 당일 진입 백테스트")
    parser.add_argument("--top-n", type=int, default=500, help="종목 수 (캐시 사용 시 최대 개수)")
    parser.add_argument("--dec-year", type=int, default=2024, help="12월 기준 연도")
    parser.add_argument("--trigger-value", type=int, default=1000, help="기준 거래대금 (억원)")
    parser.add_argument("--min-change", type=float, default=10.0, help="최소 등락률 (%)")
    parser.add_argument("--output", type=str, help="엑셀 출력 경로")
    parser.add_argument("--use-cache", action="store_true", help="캐시 파일에서 전체 종목 로드")
    parser.add_argument("--past1000", action="store_true", help="past1000.csv에서 종목 로드 (권장)")
    args = parser.parse_args()

    # 로깅 설정
    setup_logging()
    logger = get_logger(__name__)

    # 설정
    config = IntradayBacktestConfig(
        december_year=args.dec_year,
        trigger_trading_value=args.trigger_value * 100_000_000,  # 억원 → 원
        min_trigger_change_rate=args.min_change,
    )

    logger.info("=" * 60)
    logger.info("SNIPER_TRAP 12월 주도주 당일 진입 백테스트")
    logger.info("=" * 60)
    if args.past1000:
        logger.info(f"대상: past1000.csv 종목")
    elif args.use_cache:
        logger.info(f"대상: 캐시 전체 종목 (최대 {args.top_n}개)")
    else:
        logger.info(f"대상: 거래대금 상위 {args.top_n}개")
    logger.info(f"기준: {config.december_year}년 12월")
    logger.info(f"조건: 거래대금 {args.trigger_value}억+ & +{args.min_change}% 상승")
    logger.info("=" * 60)

    async with SniperTrapIntradayBacktester(config) as backtester:
        triggers, trades, summary = await backtester.run(
            top_n=args.top_n,
            use_cache=args.use_cache,
            use_past1000=args.past1000
        )

        # 결과 출력
        backtester.print_results(triggers, trades, summary)

        # 엑셀 저장
        if args.output:
            backtester.export_to_excel(triggers, trades, summary, args.output)


if __name__ == "__main__":
    asyncio.run(main())
