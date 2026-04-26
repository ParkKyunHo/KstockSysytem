#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SNIPER_TRAP 일봉 백테스트 (V6.2-A 청산 조건 적용)

일봉 데이터 기반으로 SNIPER_TRAP 전략을 시뮬레이션합니다.
청산 조건: 고정 손절 -4% / ATR 트레일링 스탑 / 최대 보유일 60일

Usage:
    # 기본 모드 (거래대금 상위 종목)
    python scripts/backtest/sniper_trap_daily.py --top-n 50
    python scripts/backtest/sniper_trap_daily.py --codes 005930,000660 --output results.xlsx

    # 12월 1000억 봉 필터 모드
    python scripts/backtest/sniper_trap_daily.py --december-1000 --top-n 300
    python scripts/backtest/sniper_trap_daily.py --december-1000 --top-n 300 --output dec_results.xlsx
    python scripts/backtest/sniper_trap_daily.py --december-1000 --dec-year 2024 --trigger-value 500
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import pandas as pd

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_config, get_settings
from src.utils.logger import setup_logging, get_logger
from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI, RankingItem, DailyCandle
from src.core.indicator import Indicator


# ============================================================
# 설정
# ============================================================

@dataclass
class DailyBacktestConfig:
    """일봉 백테스트 설정"""
    # 데이터
    lookback_days: int = 300           # 조회 일수 (1년 + 여유)
    min_candles: int = 205             # 최소 봉 수 (EMA200용)

    # 청산 조건 (V6.2-A)
    stop_loss_rate: float = -4.0       # 고정 손절 (%)
    atr_period: int = 10               # ATR 기간 (프로덕션과 일치)
    atr_mult_base: float = 6.0         # ATR 배수 (기본)
    max_holding_days: int = 60         # 최대 보유일

    # 신호
    min_body_size: float = 0.3         # 최소 캔들 몸통 크기 (%)

    # 비용
    slippage_rate: float = 0.001       # 슬리피지 0.1%
    commission_rate: float = 0.00015   # 수수료 0.015%
    tax_rate: float = 0.0018           # 거래세 0.18%

    # 투자
    investment_per_trade: int = 1_000_000  # 1회 투자금액 (100만원)

    # 5필터 설정
    apply_5filters: bool = False
    min_market_cap: int = 100_000_000_000      # 1,000억
    max_market_cap: int = 20_000_000_000_000   # 20조
    min_change_rate: float = 2.0
    max_change_rate: float = 29.9
    min_trading_value: int = 20_000_000_000    # 200억

    # 12월 1000억 봉 필터 설정
    december_1000_filter: bool = False
    december_year: int = 2024          # 12월 기준 연도
    trigger_trading_value: int = 100_000_000_000  # 1000억원
    min_trigger_change_rate: float = 0.0  # 기준봉 최소 등락률 (%, 0=필터 없음)
    same_day_entry: bool = False       # True: 당일 진입, False: 다음날 진입


@dataclass
class TriggerCandle:
    """12월 1000억 기준봉 정보"""
    stock_code: str
    stock_name: str
    trigger_date: date
    trading_value: int                 # 거래대금 (원)
    close_price: int
    change_rate: float                 # 등락률 (%)


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class DailySignal:
    """일봉 백테스트용 신호"""
    stock_code: str
    stock_name: str
    signal_date: date              # 신호 발생일
    signal_price: int              # 신호 발생가 (종가)
    candle_index: int
    ema3: float
    ema20: float
    ema60: float
    ema200: float
    body_size_pct: float
    volume_ratio: float


@dataclass
class DailyTrade:
    """일봉 거래 결과"""
    stock_code: str
    stock_name: str

    # 진입
    signal_date: date              # 신호 발생일
    entry_date: date               # 진입일 (신호 다음날)
    entry_price: int               # 진입가 (시가)

    # 청산
    exit_date: date
    exit_price: int
    exit_type: str                 # "HARD_STOP" | "ATR_TS" | "MAX_HOLDING"

    # 손익
    quantity: int
    holding_days: int
    gross_pnl: int                 # 매매차익
    entry_cost: int
    exit_cost: int
    total_cost: int
    net_pnl: int                   # 순손익
    return_rate: float             # 수익률 (%)

    # 트레일링 스탑 정보
    highest_ts: Optional[int] = None
    max_profit_rate: Optional[float] = None

    # 원본 신호
    signal: Optional[DailySignal] = None


@dataclass
class DailyBacktestSummary:
    """백테스트 요약"""
    start_date: date
    end_date: date
    total_stocks: int
    valid_stocks: int

    # 거래
    signal_count: int
    trade_count: int

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
    avg_holding_days: float

    # 청산 유형별
    hard_stop_count: int
    atr_ts_count: int
    max_holding_count: int

    # 추가 지표
    profit_factor: float           # 총이익 / 총손실
    max_drawdown: float            # 최대 낙폭 (%)

    # 설정
    investment_per_trade: int


# ============================================================
# 백테스트 엔진
# ============================================================

class SniperTrapDailyBacktester:
    """SNIPER_TRAP 일봉 백테스터"""

    ETF_KEYWORDS = [
        "KODEX", "TIGER", "RISE", "SOL", "HANARO", "PLUS", "KBSTAR",
        "ACE", "ARIRANG", "KOSEF", "SMART", "TREX", "FOCUS", "파워",
        "레버리지", "인버스", "ETN", "ETF"
    ]

    def __init__(self, config: DailyBacktestConfig):
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
    # 데이터 수집
    # ----------------------------------------------------------

    async def get_top_stocks(self, top_n: int) -> List[RankingItem]:
        """거래대금 상위 종목 조회"""
        self.logger.info(f"거래대금 상위 {top_n}개 종목 조회 중...")

        stocks = await self._market_api.get_trading_volume_ranking(
            market="0",
            top_n=top_n
        )

        # ETF 제외
        filtered = [s for s in stocks if not self.is_etf(s.stock_name)]
        self.logger.info(f"조회 완료: {len(filtered)}개 종목 (ETF 제외)")

        return filtered

    async def get_daily_candles(self, stock_code: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 조회 (거래대금 포함)"""
        try:
            candles = await self._market_api.get_daily_chart(
                stock_code=stock_code,
                count=self.config.lookback_days
            )

            if not candles:
                return None

            # DataFrame 변환 (거래대금 포함)
            df = pd.DataFrame([
                {
                    "date": c.date,
                    "open": c.open_price,
                    "high": c.high_price,
                    "low": c.low_price,
                    "close": c.close_price,
                    "volume": c.volume,
                    "trading_value": getattr(c, 'trading_value', 0),  # 거래대금
                }
                for c in candles
            ])

            df.set_index("date", inplace=True)
            return df

        except Exception as e:
            self.logger.warning(f"{stock_code}: 데이터 조회 실패 - {e}")
            return None

    async def load_all_data(
        self,
        stocks: List[RankingItem],
        delay_ms: int = 500
    ) -> Dict[str, Tuple[pd.DataFrame, str]]:
        """모든 종목 데이터 로딩"""
        data = {}
        total = len(stocks)

        for i, stock in enumerate(stocks, 1):
            self.logger.info(f"[{i}/{total}] {stock.stock_code} {stock.stock_name} 데이터 로딩...")

            df = await self.get_daily_candles(stock.stock_code)

            if df is not None and len(df) >= self.config.min_candles:
                data[stock.stock_code] = (df, stock.stock_name)
                self.logger.info(f"  -> {len(df)}일 로드 완료")
            else:
                candle_count = len(df) if df is not None else 0
                self.logger.warning(f"  -> 스킵 (일봉: {candle_count} < {self.config.min_candles})")

            if i < total:
                await asyncio.sleep(delay_ms / 1000)

        return data

    # ----------------------------------------------------------
    # 12월 1000억 봉 탐색
    # ----------------------------------------------------------

    def find_december_triggers(
        self,
        data: Dict[str, Tuple[pd.DataFrame, str]]
    ) -> List[TriggerCandle]:
        """
        12월 일봉 중 거래대금 1000억+ 발생한 종목 찾기

        Returns:
            TriggerCandle 리스트 (기준봉 정보)
        """
        triggers = []
        target_year = self.config.december_year
        min_value = self.config.trigger_trading_value

        for stock_code, (df, stock_name) in data.items():
            # 12월 데이터만 필터
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

                # 12월인지 확인
                if candle_year == target_year and candle_month == 12:
                    trading_value = row.get("trading_value", 0)

                    if trading_value >= min_value:
                        # 등락률 계산 (시가 대비 종가 상승률)
                        prev_close = row.get("open", 0)  # 시가 기준
                        change_rate = 0.0
                        if prev_close > 0:
                            change_rate = (row["close"] - prev_close) / prev_close * 100

                        # 등락률 필터 (설정값 이상만)
                        if self.config.min_trigger_change_rate > 0:
                            if change_rate < self.config.min_trigger_change_rate:
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
                            f"거래대금 {trading_value/1e8:.0f}억원"
                        )

        # 날짜순 정렬
        triggers.sort(key=lambda x: (x.trigger_date, x.stock_code))

        self.logger.info(f"12월 1000억+ 기준봉: 총 {len(triggers)}건 발견")
        return triggers

    # ----------------------------------------------------------
    # 지표 계산
    # ----------------------------------------------------------

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """지표 계산"""
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

    def detect_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        start_date: Optional[date] = None,
        first_only: bool = False,
        same_day: bool = False
    ) -> List[DailySignal]:
        """
        일봉 기준 SNIPER_TRAP 신호 탐지

        조건:
        1. TrendFilter: close > EMA200 AND EMA60 > EMA60[5]
        2. Zone: low <= EMA20 AND close >= EMA60
        3. Meaningful: CrossUp(close, EMA3) AND 양봉 AND volume >= prev_volume
        4. BodySize: (close - open) / open * 100 >= 0.3

        Args:
            df: 일봉 데이터 (지표 미계산)
            stock_code: 종목코드
            stock_name: 종목명
            start_date: 신호 탐지 시작일
            first_only: True면 첫 신호만 반환 (기본: False)
            same_day: True면 기준봉 당일부터 탐지 (기본: False=다음날부터)
        """
        df = self.calculate_indicators(df)
        signals = []

        # 시작 인덱스 결정
        start_idx = 205  # EMA200 안정화 이후 (기본값)

        if start_date:
            # 기준봉의 인덱스 찾기
            trigger_idx = None
            for i, idx in enumerate(df.index):
                idx_date = idx.date() if isinstance(idx, datetime) else idx
                if idx_date == start_date:
                    trigger_idx = i
                    break

            if trigger_idx is not None:
                if same_day:
                    # 당일 진입: 기준봉 당일부터 탐지
                    start_idx = max(205, trigger_idx)
                else:
                    # 기존: 기준봉 다음날부터 탐지
                    start_idx = max(205, trigger_idx + 1)
            else:
                # 기준봉 날짜가 정확히 없으면, start_date 이후 첫 봉 찾기
                for i, idx in enumerate(df.index):
                    idx_date = idx.date() if isinstance(idx, datetime) else idx
                    if idx_date > start_date:
                        start_idx = max(205, i)
                        break
                else:
                    # start_date 이후 데이터 없음
                    return signals

        for i in range(start_idx, len(df) - 1):  # 다음날 진입 필요하므로 -1
            curr = df.iloc[i]
            prev = df.iloc[i - 1]

            # EMA60[5]
            if i < 5:
                continue
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
            signal_date = curr.name if isinstance(curr.name, date) else curr.name.date()

            signals.append(DailySignal(
                stock_code=stock_code,
                stock_name=stock_name,
                signal_date=signal_date,
                signal_price=int(curr["close"]),
                candle_index=i,
                ema3=float(curr["ema3"]),
                ema20=float(curr["ema20"]),
                ema60=float(curr["ema60"]),
                ema200=float(curr["ema200"]),
                body_size_pct=body_size,
                volume_ratio=volume_ratio
            ))

            # first_only 모드: 첫 신호만 반환
            if first_only:
                break

        return signals

    # ----------------------------------------------------------
    # 청산 시뮬레이션
    # ----------------------------------------------------------

    def simulate_trade(
        self,
        signal: DailySignal,
        df: pd.DataFrame
    ) -> Optional[DailyTrade]:
        """
        거래 시뮬레이션 (V6.2-A 청산 조건)

        1. 진입: 신호 다음날 시가
        2. 청산 우선순위:
           - HARD_STOP: bar_low <= entry_price * 0.96 (-4%)
           - ATR_TS: close <= trailing_stop
           - MAX_HOLDING: 60일 초과
        """
        entry_idx = signal.candle_index + 1  # 다음날 진입

        if entry_idx >= len(df):
            return None

        entry_candle = df.iloc[entry_idx]
        entry_price = int(entry_candle["open"])  # 시가 진입
        entry_price_with_slip = int(entry_price * (1 + self.config.slippage_rate))

        entry_date = entry_candle.name if isinstance(entry_candle.name, date) else entry_candle.name.date()

        # 수량 계산
        quantity = self.config.investment_per_trade // entry_price_with_slip
        if quantity <= 0:
            return None

        # 손절가 계산 (-4%)
        stop_price = int(entry_price_with_slip * (1 + self.config.stop_loss_rate / 100))

        # 청산 시뮬레이션
        trailing_stop = None
        highest_ts = None
        max_profit_rate = 0.0
        exit_type = None
        exit_price = None
        exit_date = None
        exit_idx = None

        max_exit_idx = min(entry_idx + self.config.max_holding_days, len(df))

        for i in range(entry_idx + 1, max_exit_idx):
            curr = df.iloc[i]
            curr_date = curr.name if isinstance(curr.name, date) else curr.name.date()

            # 최대 수익률 추적
            curr_profit_rate = (curr["high"] - entry_price_with_slip) / entry_price_with_slip * 100
            max_profit_rate = max(max_profit_rate, curr_profit_rate)

            # 1. 고정 손절 체크 (당일 저가 기준)
            if curr["low"] <= stop_price:
                exit_type = "HARD_STOP"
                exit_price = stop_price
                exit_date = curr_date
                exit_idx = i
                break

            # 2. ATR 트레일링 스탑 (ATR 기간 이후부터)
            if i >= entry_idx + self.config.atr_period:
                atr = curr["atr"] if "atr" in curr.index and curr["atr"] > 0 else None

                if atr:
                    # HLC3 기준 트레일링 스탑
                    hlc3 = (curr["high"] + curr["low"] + curr["close"]) / 3
                    new_ts = int(hlc3 - (atr * self.config.atr_mult_base))

                    # 트레일링 스탑은 상향만 (하락 안 함)
                    if trailing_stop is None or new_ts > trailing_stop:
                        trailing_stop = new_ts
                        highest_ts = new_ts

                    # TS 촉발 체크 (종가 기준)
                    if trailing_stop and curr["close"] <= trailing_stop:
                        exit_type = "ATR_TS"
                        exit_price = trailing_stop
                        exit_date = curr_date
                        exit_idx = i
                        break

        # 3. 최대 보유일 초과 (청산 안 된 경우)
        if exit_type is None:
            if max_exit_idx <= len(df):
                last_idx = max_exit_idx - 1
                last_candle = df.iloc[last_idx]
                exit_type = "MAX_HOLDING"
                exit_price = int(last_candle["close"])
                exit_date = last_candle.name if isinstance(last_candle.name, date) else last_candle.name.date()
                exit_idx = last_idx
            else:
                # 데이터 부족
                return None

        if exit_price is None:
            return None

        exit_price_with_slip = int(exit_price * (1 - self.config.slippage_rate))

        # 비용 계산
        entry_cost = int(entry_price_with_slip * quantity * self.config.commission_rate)
        exit_cost = int(exit_price_with_slip * quantity * (self.config.commission_rate + self.config.tax_rate))
        total_cost = entry_cost + exit_cost

        # 손익 계산
        gross_pnl = (exit_price_with_slip - entry_price_with_slip) * quantity
        net_pnl = gross_pnl - total_cost

        # 수익률
        investment = entry_price_with_slip * quantity
        return_rate = (net_pnl / investment * 100) if investment > 0 else 0

        # 보유일
        holding_days = exit_idx - entry_idx if exit_idx else 0

        return DailyTrade(
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            signal_date=signal.signal_date,
            entry_date=entry_date,
            entry_price=entry_price_with_slip,
            exit_date=exit_date,
            exit_price=exit_price_with_slip,
            exit_type=exit_type,
            quantity=quantity,
            holding_days=holding_days,
            gross_pnl=gross_pnl,
            entry_cost=entry_cost,
            exit_cost=exit_cost,
            total_cost=total_cost,
            net_pnl=net_pnl,
            return_rate=return_rate,
            highest_ts=highest_ts,
            max_profit_rate=max_profit_rate,
            signal=signal
        )

    # ----------------------------------------------------------
    # 통계 계산
    # ----------------------------------------------------------

    def calculate_summary(
        self,
        trades: List[DailyTrade],
        total_stocks: int,
        valid_stocks: int,
        signal_count: int
    ) -> DailyBacktestSummary:
        """요약 통계 계산"""
        if not trades:
            return DailyBacktestSummary(
                start_date=date.today(),
                end_date=date.today(),
                total_stocks=total_stocks,
                valid_stocks=valid_stocks,
                signal_count=signal_count,
                trade_count=0,
                total_gross_pnl=0,
                total_cost=0,
                total_net_pnl=0,
                win_count=0,
                loss_count=0,
                win_rate=0.0,
                avg_return=0.0,
                max_return=0.0,
                min_return=0.0,
                avg_holding_days=0.0,
                hard_stop_count=0,
                atr_ts_count=0,
                max_holding_count=0,
                profit_factor=0.0,
                max_drawdown=0.0,
                investment_per_trade=self.config.investment_per_trade
            )

        returns = [t.return_rate for t in trades]
        win_count = sum(1 for t in trades if t.net_pnl > 0)
        loss_count = sum(1 for t in trades if t.net_pnl <= 0)

        # 청산 유형별 집계
        hard_stop_count = sum(1 for t in trades if t.exit_type == "HARD_STOP")
        atr_ts_count = sum(1 for t in trades if t.exit_type == "ATR_TS")
        max_holding_count = sum(1 for t in trades if t.exit_type == "MAX_HOLDING")

        # Profit Factor
        total_profit = sum(t.net_pnl for t in trades if t.net_pnl > 0)
        total_loss = abs(sum(t.net_pnl for t in trades if t.net_pnl < 0))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # 날짜 범위
        all_dates = [t.entry_date for t in trades] + [t.exit_date for t in trades]
        start_date = min(all_dates)
        end_date = max(all_dates)

        # MDD 계산 (누적 손익 기준)
        cumulative_pnl = 0
        peak_pnl = 0
        max_drawdown = 0.0
        sorted_trades = sorted(trades, key=lambda x: x.exit_date)

        for t in sorted_trades:
            cumulative_pnl += t.net_pnl
            if cumulative_pnl > peak_pnl:
                peak_pnl = cumulative_pnl
            drawdown = (peak_pnl - cumulative_pnl) / self.config.investment_per_trade * 100 if peak_pnl > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        return DailyBacktestSummary(
            start_date=start_date,
            end_date=end_date,
            total_stocks=total_stocks,
            valid_stocks=valid_stocks,
            signal_count=signal_count,
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
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            investment_per_trade=self.config.investment_per_trade
        )

    # ----------------------------------------------------------
    # 결과 출력
    # ----------------------------------------------------------

    def print_results(self, trades: List[DailyTrade], summary: DailyBacktestSummary):
        """콘솔 출력"""
        print("\n" + "=" * 70)
        print("  SNIPER_TRAP 일봉 백테스트 결과 (V6.2-A 청산 조건)")
        print("=" * 70)
        print(f"  기간: {summary.start_date} ~ {summary.end_date}")
        print(f"  대상: {summary.total_stocks}종목 (유효: {summary.valid_stocks})")
        print("-" * 70)
        print(f"  신호 발생: {summary.signal_count}건")
        print(f"  거래 체결: {summary.trade_count}건")
        print("-" * 70)
        print(f"  승: {summary.win_count}건 / 패: {summary.loss_count}건")
        print(f"  승률: {summary.win_rate:.1f}%")
        print("-" * 70)
        print(f"  총 매매차익: {summary.total_gross_pnl:+,}원")
        print(f"  총 비용: {summary.total_cost:,}원")
        print(f"  순손익: {summary.total_net_pnl:+,}원")
        print("-" * 70)
        print(f"  평균 수익률: {summary.avg_return:+.2f}%")
        print(f"  최대 수익률: {summary.max_return:+.2f}%")
        print(f"  최대 손실률: {summary.min_return:+.2f}%")
        print(f"  평균 보유일: {summary.avg_holding_days:.1f}일")
        print("-" * 70)
        print(f"  Profit Factor: {summary.profit_factor:.2f}")
        print(f"  최대 낙폭 (MDD): {summary.max_drawdown:.2f}%")
        print("-" * 70)
        print("  [청산 유형별 분포]")
        total_exits = summary.hard_stop_count + summary.atr_ts_count + summary.max_holding_count
        if total_exits > 0:
            print(f"    HARD_STOP (-4%): {summary.hard_stop_count}건 ({summary.hard_stop_count/total_exits*100:.1f}%)")
            print(f"    ATR_TS: {summary.atr_ts_count}건 ({summary.atr_ts_count/total_exits*100:.1f}%)")
            print(f"    MAX_HOLDING (60일): {summary.max_holding_count}건 ({summary.max_holding_count/total_exits*100:.1f}%)")
        print("-" * 70)
        print(f"  1회 투자금: {summary.investment_per_trade:,}원")
        print(f"  비용: 슬리피지 0.1% + 수수료 0.015% + 세금 0.18%")
        print("=" * 70)

        if trades:
            print("\n[거래 내역 (수익률순)]")
            print("-" * 110)
            print(f"{'종목':<12} {'진입일':^12} {'진입가':>10} {'청산일':^12} {'청산가':>10} {'청산유형':^12} {'보유일':>5} {'순손익':>12} {'수익률':>8}")
            print("-" * 110)

            for t in sorted(trades, key=lambda x: x.return_rate, reverse=True)[:30]:
                print(f"{t.stock_name:<12} {str(t.entry_date):^12} "
                      f"{t.entry_price:>10,} {str(t.exit_date):^12} "
                      f"{t.exit_price:>10,} {t.exit_type:^12} "
                      f"{t.holding_days:>5} {t.net_pnl:>+12,} {t.return_rate:>+7.2f}%")

            if len(trades) > 30:
                print(f"  ... 외 {len(trades) - 30}건")

            print("-" * 110)

    def export_to_excel(self, trades: List[DailyTrade], summary: DailyBacktestSummary, output_path: str):
        """엑셀 파일 출력"""
        try:
            # Sheet 1: 요약
            summary_data = {
                "항목": [
                    "백테스트 기간", "대상 종목 수", "유효 종목 수", "신호 발생 수", "거래 체결 수",
                    "승", "패", "승률", "총 매매차익", "총 비용", "순손익",
                    "평균 수익률", "최대 수익률", "최대 손실률", "평균 보유일",
                    "Profit Factor", "최대 낙폭 (MDD)",
                    "HARD_STOP 횟수", "ATR_TS 횟수", "MAX_HOLDING 횟수",
                    "1회 투자금"
                ],
                "값": [
                    f"{summary.start_date} ~ {summary.end_date}",
                    summary.total_stocks, summary.valid_stocks, summary.signal_count, summary.trade_count,
                    summary.win_count, summary.loss_count, f"{summary.win_rate:.1f}%",
                    f"{summary.total_gross_pnl:+,}", f"{summary.total_cost:,}", f"{summary.total_net_pnl:+,}",
                    f"{summary.avg_return:+.2f}%", f"{summary.max_return:+.2f}%", f"{summary.min_return:+.2f}%",
                    f"{summary.avg_holding_days:.1f}일",
                    f"{summary.profit_factor:.2f}", f"{summary.max_drawdown:.2f}%",
                    summary.hard_stop_count, summary.atr_ts_count, summary.max_holding_count,
                    f"{summary.investment_per_trade:,}"
                ]
            }
            df_summary = pd.DataFrame(summary_data)

            # Sheet 2: 거래 내역
            trades_data = []
            for t in sorted(trades, key=lambda x: x.entry_date):
                trades_data.append({
                    "종목코드": t.stock_code,
                    "종목명": t.stock_name,
                    "신호일": str(t.signal_date),
                    "진입일": str(t.entry_date),
                    "진입가": t.entry_price,
                    "청산일": str(t.exit_date),
                    "청산가": t.exit_price,
                    "청산유형": t.exit_type,
                    "수량": t.quantity,
                    "보유일": t.holding_days,
                    "매매차익": t.gross_pnl,
                    "비용": t.total_cost,
                    "순손익": t.net_pnl,
                    "수익률(%)": round(t.return_rate, 2),
                    "최대TS": t.highest_ts if t.highest_ts else "",
                    "최대수익률(%)": round(t.max_profit_rate, 2) if t.max_profit_rate else ""
                })
            df_trades = pd.DataFrame(trades_data)

            # Sheet 3: 신호 상세
            signals_data = []
            for t in trades:
                if t.signal:
                    signals_data.append({
                        "종목코드": t.signal.stock_code,
                        "종목명": t.signal.stock_name,
                        "신호일": str(t.signal.signal_date),
                        "신호가": t.signal.signal_price,
                        "EMA3": round(t.signal.ema3, 0),
                        "EMA20": round(t.signal.ema20, 0),
                        "EMA60": round(t.signal.ema60, 0),
                        "EMA200": round(t.signal.ema200, 0),
                        "캔들크기(%)": round(t.signal.body_size_pct, 2),
                        "거래량비": round(t.signal.volume_ratio, 2)
                    })
            df_signals = pd.DataFrame(signals_data)

            # 엑셀 저장
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name='요약', index=False)
                df_trades.to_excel(writer, sheet_name='거래내역', index=False)
                df_signals.to_excel(writer, sheet_name='신호상세', index=False)

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
        top_n: int = 50,
        stock_codes: Optional[List[str]] = None
    ) -> Tuple[List[DailyTrade], DailyBacktestSummary]:
        """백테스트 실행"""
        # 1. 종목 리스트 확보
        if stock_codes:
            # 지정된 종목 사용
            stocks = []
            for code in stock_codes:
                stocks.append(RankingItem(
                    rank=0,
                    stock_code=code,
                    stock_name=code,  # 이름은 나중에 업데이트
                    current_price=0,
                    change_rate=0.0,
                    volume=0,
                    trading_value=0
                ))
            total_stocks = len(stocks)
        else:
            # 거래대금 상위 종목
            stocks = await self.get_top_stocks(top_n)
            total_stocks = len(stocks)

        # 2. 데이터 로딩
        data = await self.load_all_data(stocks)
        valid_stocks = len(data)

        self.logger.info(f"유효 데이터: {valid_stocks}/{total_stocks}종목")

        # 3. 신호 탐지 및 거래 시뮬레이션
        all_signals = []
        all_trades = []

        for stock_code, (df, stock_name) in data.items():
            signals = self.detect_signals(df, stock_code, stock_name)
            all_signals.extend(signals)

            for signal in signals:
                self.logger.info(f"신호: {stock_code} {stock_name} @ {signal.signal_date} {signal.signal_price:,}원")

                trade = self.simulate_trade(signal, df)
                if trade:
                    all_trades.append(trade)
                    self.logger.info(f"  -> {trade.exit_type} @ {trade.exit_date} {trade.exit_price:,}원 ({trade.return_rate:+.2f}%)")

        # 4. 요약 계산
        summary = self.calculate_summary(all_trades, total_stocks, valid_stocks, len(all_signals))

        return all_trades, summary

    async def run_december_1000(
        self,
        top_n: int = 300
    ) -> Tuple[List[DailyTrade], DailyBacktestSummary, List[TriggerCandle]]:
        """
        12월 1000억 봉 기준 백테스트 실행

        1. 거래대금 상위 종목 데이터 로딩
        2. 12월 1000억+ 봉 발생 종목 찾기
        3. 기준봉 다음날부터 SNIPER_TRAP 조건 체크 (첫 신호만)
        4. 신호 발생 시 거래 시뮬레이션

        Returns:
            (trades, summary, triggers): 거래 결과, 요약, 기준봉 리스트
        """
        # 1. 종목 리스트 확보
        stocks = await self.get_top_stocks(top_n)
        total_stocks = len(stocks)

        # 2. 데이터 로딩
        data = await self.load_all_data(stocks)
        valid_stocks = len(data)

        self.logger.info(f"유효 데이터: {valid_stocks}/{total_stocks}종목")

        # 3. 12월 1000억 봉 찾기
        triggers = self.find_december_triggers(data)

        if not triggers:
            self.logger.warning("12월 1000억+ 기준봉 없음")
            summary = self.calculate_summary([], total_stocks, valid_stocks, 0)
            return [], summary, triggers

        # 4. 각 기준봉에 대해 신호 탐지 및 거래 시뮬레이션
        all_signals = []
        all_trades = []
        processed_stocks = set()  # 중복 방지

        for trigger in triggers:
            # 같은 종목의 첫 번째 기준봉만 처리
            if trigger.stock_code in processed_stocks:
                continue
            processed_stocks.add(trigger.stock_code)

            stock_code = trigger.stock_code
            if stock_code not in data:
                continue

            df, stock_name = data[stock_code]

            # 기준봉 다음날부터 신호 탐지 (첫 신호만)
            signals = self.detect_signals(
                df,
                stock_code,
                stock_name,
                start_date=trigger.trigger_date,
                first_only=True
            )

            if signals:
                signal = signals[0]
                all_signals.append(signal)

                self.logger.info(
                    f"신호: {stock_code} {stock_name} "
                    f"기준봉 {trigger.trigger_date} → 신호일 {signal.signal_date} "
                    f"{signal.signal_price:,}원"
                )

                trade = self.simulate_trade(signal, df)
                if trade:
                    all_trades.append(trade)
                    self.logger.info(
                        f"  -> {trade.exit_type} @ {trade.exit_date} "
                        f"{trade.exit_price:,}원 ({trade.return_rate:+.2f}%)"
                    )
            else:
                self.logger.info(
                    f"신호 없음: {stock_code} {stock_name} "
                    f"(기준봉 {trigger.trigger_date} 이후)"
                )

        # 5. 요약 계산
        summary = self.calculate_summary(all_trades, total_stocks, valid_stocks, len(all_signals))

        return all_trades, summary, triggers

    def print_december_results(
        self,
        trades: List[DailyTrade],
        summary: DailyBacktestSummary,
        triggers: List[TriggerCandle]
    ):
        """12월 1000억 봉 결과 출력"""
        print("\n" + "=" * 80)
        print("  12월 거래대금 1000억+ 봉 기준 SNIPER_TRAP 백테스트 결과")
        print("=" * 80)
        print(f"  기간: {summary.start_date} ~ {summary.end_date}")
        print(f"  대상: {summary.total_stocks}종목 (유효: {summary.valid_stocks})")
        print("-" * 80)
        print(f"  12월 1000억+ 기준봉: {len(triggers)}건")
        print(f"  신호 발생: {summary.signal_count}건")
        print(f"  거래 체결: {summary.trade_count}건")
        print("-" * 80)

        if summary.trade_count > 0:
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
            print(f"  최대 낙폭 (MDD): {summary.max_drawdown:.2f}%")
            print("-" * 80)
            print("  [청산 유형별 분포]")
            total_exits = summary.hard_stop_count + summary.atr_ts_count + summary.max_holding_count
            if total_exits > 0:
                print(f"    HARD_STOP (-4%): {summary.hard_stop_count}건 ({summary.hard_stop_count/total_exits*100:.1f}%)")
                print(f"    ATR_TS: {summary.atr_ts_count}건 ({summary.atr_ts_count/total_exits*100:.1f}%)")
                print(f"    MAX_HOLDING (60일): {summary.max_holding_count}건 ({summary.max_holding_count/total_exits*100:.1f}%)")

        print("=" * 80)

        # 기준봉 목록
        print("\n[12월 1000억+ 기준봉 목록]")
        print("-" * 90)
        print(f"{'종목코드':<10} {'종목명':<15} {'기준봉일':^12} {'거래대금':>15} {'종가':>12} {'신호여부':^10}")
        print("-" * 90)

        # 신호 발생 여부 맵
        signal_map = {t.stock_code: t for t in trades}

        for trig in triggers[:50]:  # 상위 50개만
            has_signal = "O" if trig.stock_code in signal_map else "X"
            print(
                f"{trig.stock_code:<10} {trig.stock_name:<15} "
                f"{str(trig.trigger_date):^12} "
                f"{trig.trading_value/1e8:>12,.0f}억원 "
                f"{trig.close_price:>10,}원 "
                f"{has_signal:^10}"
            )

        if len(triggers) > 50:
            print(f"  ... 외 {len(triggers) - 50}건")

        print("-" * 90)

        # 거래 내역
        if trades:
            print("\n[거래 내역 (수익률순)]")
            print("-" * 120)
            print(f"{'종목':<12} {'기준봉일':^12} {'신호일':^12} {'진입가':>10} {'청산일':^12} {'청산가':>10} {'유형':^12} {'보유':>5} {'수익률':>8}")
            print("-" * 120)

            # 기준봉 날짜 맵
            trigger_map = {t.stock_code: t.trigger_date for t in triggers}

            for t in sorted(trades, key=lambda x: x.return_rate, reverse=True):
                trig_date = trigger_map.get(t.stock_code, "")
                print(
                    f"{t.stock_name:<12} {str(trig_date):^12} "
                    f"{str(t.signal_date):^12} {t.entry_price:>10,} "
                    f"{str(t.exit_date):^12} {t.exit_price:>10,} "
                    f"{t.exit_type:^12} {t.holding_days:>5} {t.return_rate:>+7.2f}%"
                )

            print("-" * 120)

    def export_december_to_excel(
        self,
        trades: List[DailyTrade],
        summary: DailyBacktestSummary,
        triggers: List[TriggerCandle],
        output_path: str
    ):
        """12월 1000억 봉 결과 엑셀 출력"""
        try:
            # Sheet 1: 요약
            summary_data = {
                "항목": [
                    "백테스트 유형", "기준봉 조건", "백테스트 기간",
                    "대상 종목 수", "유효 종목 수", "12월 기준봉 수",
                    "신호 발생 수", "거래 체결 수",
                    "승", "패", "승률",
                    "총 매매차익", "총 비용", "순손익",
                    "평균 수익률", "최대 수익률", "최대 손실률", "평균 보유일",
                    "Profit Factor", "최대 낙폭 (MDD)",
                    "HARD_STOP 횟수", "ATR_TS 횟수", "MAX_HOLDING 횟수",
                    "1회 투자금"
                ],
                "값": [
                    "12월 거래대금 1000억+ 기준봉",
                    f"거래대금 >= {self.config.trigger_trading_value/1e8:.0f}억원",
                    f"{summary.start_date} ~ {summary.end_date}",
                    summary.total_stocks, summary.valid_stocks, len(triggers),
                    summary.signal_count, summary.trade_count,
                    summary.win_count, summary.loss_count, f"{summary.win_rate:.1f}%",
                    f"{summary.total_gross_pnl:+,}", f"{summary.total_cost:,}", f"{summary.total_net_pnl:+,}",
                    f"{summary.avg_return:+.2f}%", f"{summary.max_return:+.2f}%", f"{summary.min_return:+.2f}%",
                    f"{summary.avg_holding_days:.1f}일",
                    f"{summary.profit_factor:.2f}", f"{summary.max_drawdown:.2f}%",
                    summary.hard_stop_count, summary.atr_ts_count, summary.max_holding_count,
                    f"{summary.investment_per_trade:,}"
                ]
            }
            df_summary = pd.DataFrame(summary_data)

            # Sheet 2: 기준봉 목록
            trigger_map = {t.stock_code: t for t in trades}
            triggers_data = []
            for trig in triggers:
                trade = trigger_map.get(trig.stock_code)
                triggers_data.append({
                    "종목코드": trig.stock_code,
                    "종목명": trig.stock_name,
                    "기준봉일": str(trig.trigger_date),
                    "거래대금(억)": round(trig.trading_value / 1e8, 0),
                    "종가": trig.close_price,
                    "등락률(%)": trig.change_rate,
                    "신호발생": "O" if trade else "X",
                    "신호일": str(trade.signal_date) if trade else "",
                    "수익률(%)": round(trade.return_rate, 2) if trade else "",
                    "청산유형": trade.exit_type if trade else ""
                })
            df_triggers = pd.DataFrame(triggers_data)

            # Sheet 3: 거래 내역
            trades_data = []
            trigger_date_map = {t.stock_code: t.trigger_date for t in triggers}
            for t in sorted(trades, key=lambda x: x.entry_date):
                trades_data.append({
                    "종목코드": t.stock_code,
                    "종목명": t.stock_name,
                    "기준봉일": str(trigger_date_map.get(t.stock_code, "")),
                    "신호일": str(t.signal_date),
                    "진입일": str(t.entry_date),
                    "진입가": t.entry_price,
                    "청산일": str(t.exit_date),
                    "청산가": t.exit_price,
                    "청산유형": t.exit_type,
                    "수량": t.quantity,
                    "보유일": t.holding_days,
                    "매매차익": t.gross_pnl,
                    "비용": t.total_cost,
                    "순손익": t.net_pnl,
                    "수익률(%)": round(t.return_rate, 2),
                    "최대TS": t.highest_ts if t.highest_ts else "",
                    "최대수익률(%)": round(t.max_profit_rate, 2) if t.max_profit_rate else ""
                })
            df_trades = pd.DataFrame(trades_data)

            # 엑셀 저장
            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name='요약', index=False)
                df_triggers.to_excel(writer, sheet_name='기준봉목록', index=False)
                df_trades.to_excel(writer, sheet_name='거래내역', index=False)

            print(f"\n엑셀 파일 저장: {output_path}")

        except ImportError:
            print("\n[경고] openpyxl 미설치. pip install openpyxl 필요")
        except Exception as e:
            print(f"\n[오류] 엑셀 저장 실패: {e}")


# ============================================================
# 메인 함수
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="SNIPER_TRAP 일봉 백테스트 (V6.2-A 청산 조건)")
    parser.add_argument("--top-n", type=int, default=50, help="거래대금 상위 N종목 (기본: 50)")
    parser.add_argument("--codes", type=str, default=None, help="특정 종목코드 (콤마 구분, 예: 005930,000660)")
    parser.add_argument("--output", type=str, default=None, help="엑셀 출력 파일 경로")
    parser.add_argument("--days", type=int, default=300, help="조회 일수 (기본: 300)")

    # 12월 1000억 봉 필터 옵션
    parser.add_argument(
        "--december-1000",
        action="store_true",
        help="12월 거래대금 1000억+ 봉 기준 백테스트"
    )
    parser.add_argument(
        "--dec-year",
        type=int,
        default=2024,
        help="12월 기준 연도 (기본: 2024)"
    )
    parser.add_argument(
        "--trigger-value",
        type=int,
        default=1000,
        help="기준봉 최소 거래대금 (억원, 기본: 1000)"
    )

    args = parser.parse_args()

    # 로깅 설정
    setup_logging()

    # 12월 1000억 봉 모드
    if args.december_1000:
        # December 2024 기준 테스트를 위해 충분한 데이터 필요
        # EMA200 안정화(205봉) + 12월~현재(~270봉) = 최소 475봉
        # 명시적으로 --days 지정 안 했으면 600일 사용
        lookback = args.days if args.days != 300 else 600

        print(f"\n12월 거래대금 {args.trigger_value}억+ 봉 기준 SNIPER_TRAP 백테스트")
        print(f"대상: 거래대금 상위 {args.top_n}종목")
        print(f"기준: {args.dec_year}년 12월 거래대금 >= {args.trigger_value}억원")
        print(f"조회 일수: {lookback}일 (EMA200 안정화 필요)")
        print(f"청산: 고정손절 -4% / ATR TS (6.0배) / 최대 60일")
        print(f"비용: 슬리피지 0.1% + 수수료 0.015% + 세금 0.18%")
        print("-" * 60)

        config = DailyBacktestConfig(
            lookback_days=lookback,
            december_1000_filter=True,
            december_year=args.dec_year,
            trigger_trading_value=args.trigger_value * 100_000_000  # 억원 → 원
        )

        async with SniperTrapDailyBacktester(config) as backtester:
            trades, summary, triggers = await backtester.run_december_1000(
                top_n=args.top_n
            )

            # 결과 출력
            backtester.print_december_results(trades, summary, triggers)

            # 엑셀 저장 (옵션)
            if args.output:
                backtester.export_december_to_excel(trades, summary, triggers, args.output)

        return trades, summary

    # 기본 모드
    stock_codes = None
    if args.codes:
        stock_codes = [c.strip() for c in args.codes.split(",")]

    print(f"\nSNIPER_TRAP 일봉 백테스트 (V6.2-A)")
    print(f"대상: {'지정 종목 ' + str(len(stock_codes)) + '개' if stock_codes else f'거래대금 상위 {args.top_n}종목'}")
    print(f"기간: 최근 {args.days}일")
    print(f"청산: 고정손절 -4% / ATR TS (6.0배) / 최대 60일")
    print(f"비용: 슬리피지 0.1% + 수수료 0.015% + 세금 0.18%")
    print("-" * 50)

    config = DailyBacktestConfig(lookback_days=args.days)

    async with SniperTrapDailyBacktester(config) as backtester:
        trades, summary = await backtester.run(
            top_n=args.top_n,
            stock_codes=stock_codes
        )

        # 결과 출력
        backtester.print_results(trades, summary)

        # 엑셀 저장 (옵션)
        if args.output:
            backtester.export_to_excel(trades, summary, args.output)

    return trades, summary


if __name__ == "__main__":
    asyncio.run(main())
