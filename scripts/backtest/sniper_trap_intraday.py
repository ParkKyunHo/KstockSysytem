#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SNIPER_TRAP 당일청산 백테스트

금일 거래대금 상위 N종목에 대해 SNIPER_TRAP 전략의 첫 신호로 진입 후
장 마감(15:30) 청산 시 수익을 분석합니다.

Usage:
    python scripts/backtest/sniper_trap_intraday.py --top-n 10
    python scripts/backtest/sniper_trap_intraday.py --top-n 100 --output results.xlsx
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime, time, date
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import pandas as pd

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_config, get_settings
from src.utils.logger import setup_logging, get_logger
from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI, RankingItem, MinuteCandle
from src.core.indicator import Indicator


# ============================================================
# 설정
# ============================================================

@dataclass
class BacktestConfig:
    """백테스트 설정"""
    # 대상
    top_n: int = 100

    # 시간
    signal_start_time: time = field(default_factory=lambda: time(9, 30))
    market_close_time: time = field(default_factory=lambda: time(15, 27))  # 마지막 3분봉

    # 비용
    slippage_rate: float = 0.001      # 슬리피지 0.1%
    commission_rate: float = 0.00015  # 수수료 0.015%
    tax_rate: float = 0.0018          # 거래세 0.18%

    # 신호
    min_candles: int = 205            # 최소 봉 수 (EMA200용)
    min_body_size: float = 0.3        # 최소 캔들 몸통 크기 (%)

    # 투자
    investment_per_trade: int = 1_000_000  # 1회 투자금액 (100만원)

    # 5필터 설정 (V6.2-B)
    apply_5filters: bool = False       # 5필터 적용 여부
    etf_only: bool = False             # ETF만 제외 (다른 필터 미적용)
    skip_change_rate: bool = False     # 등락률 필터 스킵
    min_market_cap: int = 100_000_000_000      # 최소 시가총액 (1,000억)
    max_market_cap: int = 20_000_000_000_000   # 최대 시가총액 (20조)
    min_change_rate: float = 2.0       # 최소 등락률 (2%)
    max_change_rate: float = 29.9      # 최대 등락률 (29.9%)
    min_trading_value: int = 20_000_000_000   # 최소 거래대금 (200억)
    min_high_ratio: float = 0.90       # 20일 고점 대비 (90%+)
    max_gap_rate: float = 15.0         # 최대 갭 (15%)


# ============================================================
# 데이터 클래스
# ============================================================

@dataclass
class BacktestSignal:
    """백테스트용 신호"""
    stock_code: str
    stock_name: str
    signal_time: datetime
    entry_price: int
    candle_index: int
    ema3: float
    ema20: float
    ema60: float
    ema200: float
    body_size_pct: float
    volume_ratio: float


@dataclass
class Trade:
    """거래 결과"""
    stock_code: str
    stock_name: str

    # 진입
    entry_time: datetime
    entry_price: int

    # 청산
    exit_time: datetime
    exit_price: int

    # 손익
    quantity: int
    gross_pnl: int          # 매매차익 (비용 전)
    entry_cost: int         # 진입 비용
    exit_cost: int          # 청산 비용
    total_cost: int         # 총 비용
    net_pnl: int            # 순손익
    return_rate: float      # 수익률 (%)

    # 메타
    holding_minutes: int
    signal: Optional[BacktestSignal] = None


@dataclass
class BacktestSummary:
    """백테스트 요약"""
    date: date
    total_stocks: int
    valid_stocks: int       # 데이터 유효 종목 수
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

    # 설정
    investment_per_trade: int


# ============================================================
# 백테스트 엔진
# ============================================================

class SniperTrapBacktester:
    """SNIPER_TRAP 당일청산 백테스터"""

    # ETF 키워드 패턴
    ETF_KEYWORDS = [
        "KODEX", "TIGER", "RISE", "SOL", "HANARO", "PLUS", "KBSTAR",
        "ACE", "ARIRANG", "KOSEF", "SMART", "TREX", "FOCUS", "파워",
        "레버리지", "인버스", "ETN", "ETF"
    ]

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.logger = get_logger(__name__)
        self._client: Optional[KiwoomAPIClient] = None
        self._market_api: Optional[MarketAPI] = None
        self._filter_stats = {"total": 0, "etf": 0, "market_cap": 0, "change_rate": 0, "trading_value": 0, "passed": 0}

    async def __aenter__(self):
        self._client = KiwoomAPIClient()
        await self._client.__aenter__()
        self._market_api = MarketAPI(self._client)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    # ----------------------------------------------------------
    # 5필터 로직
    # ----------------------------------------------------------

    def is_etf(self, stock_name: str) -> bool:
        """ETF 여부 확인"""
        for keyword in self.ETF_KEYWORDS:
            if keyword in stock_name.upper():
                return True
        return False

    async def apply_5filters(self, stocks: List[RankingItem]) -> List[RankingItem]:
        """
        5필터 적용 (V6.2-B)

        1. ETF 제외
        2. 시가총액: 1,000억 ~ 20조
        3. 등락률: 2% ~ 29.9%
        4. 거래대금: 200억+
        5. (20일고점, 갭은 분봉 데이터 로드 후 별도 체크)
        """
        if not self.config.apply_5filters:
            return stocks

        self.logger.info("5필터 적용 중...")
        filtered = []
        self._filter_stats["total"] = len(stocks)

        for stock in stocks:
            # 1. ETF 제외
            if self.is_etf(stock.stock_name):
                self._filter_stats["etf"] += 1
                self.logger.debug(f"  [ETF 제외] {stock.stock_code} {stock.stock_name}")
                continue

            # 2. 등락률 체크 (2% ~ 29.9%) - 스킵 가능
            if not self.config.skip_change_rate:
                if not (self.config.min_change_rate <= stock.change_rate <= self.config.max_change_rate):
                    self._filter_stats["change_rate"] += 1
                    self.logger.debug(f"  [등락률 제외] {stock.stock_code} {stock.stock_name}: {stock.change_rate:.1f}%")
                    continue

            # 3. 거래대금 체크 (200억+)
            if stock.trading_value < self.config.min_trading_value:
                self._filter_stats["trading_value"] += 1
                self.logger.debug(f"  [거래대금 제외] {stock.stock_code} {stock.stock_name}: {stock.trading_value/100_000_000:.0f}억")
                continue

            # 4. 시가총액 체크 (별도 API 호출 필요)
            try:
                stock_info = await self._market_api.get_stock_info(stock.stock_code)
                market_cap = stock_info.market_cap

                if not (self.config.min_market_cap <= market_cap <= self.config.max_market_cap):
                    self._filter_stats["market_cap"] += 1
                    self.logger.debug(f"  [시가총액 제외] {stock.stock_code} {stock.stock_name}: {market_cap/100_000_000:.0f}억")
                    continue

                # Rate limit 대기
                await asyncio.sleep(0.2)

            except Exception as e:
                self.logger.warning(f"  [시가총액 조회 실패] {stock.stock_code}: {e}")
                continue

            filtered.append(stock)
            self._filter_stats["passed"] += 1

        self.logger.info(f"5필터 결과: {len(filtered)}/{len(stocks)}종목 통과")
        self.logger.info(f"  - ETF 제외: {self._filter_stats['etf']}개")
        self.logger.info(f"  - 등락률 제외: {self._filter_stats['change_rate']}개")
        self.logger.info(f"  - 거래대금 제외: {self._filter_stats['trading_value']}개")
        self.logger.info(f"  - 시가총액 제외: {self._filter_stats['market_cap']}개")

        return filtered

    def filter_etf_only(self, stocks: List[RankingItem]) -> List[RankingItem]:
        """ETF만 제외"""
        filtered = []
        etf_count = 0

        for stock in stocks:
            if self.is_etf(stock.stock_name):
                etf_count += 1
                continue
            filtered.append(stock)

        self.logger.info(f"ETF 제외: {len(filtered)}/{len(stocks)}종목 (ETF {etf_count}개 제외)")
        return filtered

    # ----------------------------------------------------------
    # 데이터 수집
    # ----------------------------------------------------------

    async def get_top_stocks(self) -> List[RankingItem]:
        """거래대금 상위 종목 조회"""
        self.logger.info(f"거래대금 상위 {self.config.top_n}개 종목 조회 중...")

        stocks = await self._market_api.get_trading_volume_ranking(
            market="0",  # 전체
            top_n=self.config.top_n
        )

        self.logger.info(f"조회 완료: {len(stocks)}개 종목")
        return stocks

    async def get_candles(self, stock_code: str) -> Optional[pd.DataFrame]:
        """3분봉 데이터 조회 및 DataFrame 변환"""
        try:
            candles = await self._market_api.get_minute_chart(
                stock_code=stock_code,
                timeframe=3,
                count=400,
                use_pagination=True
            )

            if not candles:
                return None

            # DataFrame 변환
            df = pd.DataFrame([
                {
                    "timestamp": c.timestamp,
                    "open": c.open_price,
                    "high": c.high_price,
                    "low": c.low_price,
                    "close": c.close_price,
                    "volume": c.volume,
                }
                for c in candles
            ])

            df.set_index("timestamp", inplace=True)
            return df

        except Exception as e:
            self.logger.warning(f"{stock_code}: 데이터 조회 실패 - {e}")
            return None

    async def load_all_data(
        self,
        stocks: List[RankingItem],
        delay_ms: int = 500
    ) -> Dict[str, Tuple[pd.DataFrame, str]]:
        """
        모든 종목 데이터 로딩 (Rate Limit 준수)

        Returns:
            {stock_code: (DataFrame, stock_name)}
        """
        data = {}
        total = len(stocks)

        for i, stock in enumerate(stocks, 1):
            self.logger.info(f"[{i}/{total}] {stock.stock_code} {stock.stock_name} 데이터 로딩...")

            df = await self.get_candles(stock.stock_code)

            if df is not None and len(df) >= self.config.min_candles:
                data[stock.stock_code] = (df, stock.stock_name)
                self.logger.info(f"  -> {len(df)}봉 로드 완료")
            else:
                candle_count = len(df) if df is not None else 0
                self.logger.warning(f"  -> 스킵 (봉 수: {candle_count} < {self.config.min_candles})")

            # Rate Limit 대기
            if i < total:
                await asyncio.sleep(delay_ms / 1000)

        return data

    # ----------------------------------------------------------
    # 신호 탐지
    # ----------------------------------------------------------

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """지표 계산"""
        df = df.copy()

        # EMA 계산 (adjust=False 내장)
        df["ema3"] = Indicator.ema(df["close"], span=3)
        df["ema20"] = Indicator.ema(df["close"], span=20)
        df["ema60"] = Indicator.ema(df["close"], span=60)
        df["ema200"] = Indicator.ema(df["close"], span=200)

        return df

    def detect_first_signal(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str
    ) -> Optional[BacktestSignal]:
        """
        첫 번째 SNIPER_TRAP 신호 탐지

        조건:
        1. TrendFilter: close > EMA200 AND EMA60 > EMA60[5]
        2. Zone: low <= EMA20 AND close >= EMA60
        3. Meaningful: CrossUp(close, EMA3) AND close > open AND volume >= prev_volume
        4. BodySize: (close - open) / open * 100 >= 0.3
        5. TimeFilter: 09:30 이후
        """
        df = self.calculate_indicators(df)

        for i in range(205, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]

            # 시간 필터 (09:30 이후)
            curr_time = curr.name.time() if hasattr(curr.name, 'time') else curr.name
            if isinstance(curr_time, time) and curr_time < self.config.signal_start_time:
                continue

            # EMA60[5] 계산
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

            return BacktestSignal(
                stock_code=stock_code,
                stock_name=stock_name,
                signal_time=curr.name,
                entry_price=int(curr["close"]),
                candle_index=i,
                ema3=float(curr["ema3"]),
                ema20=float(curr["ema20"]),
                ema60=float(curr["ema60"]),
                ema200=float(curr["ema200"]),
                body_size_pct=body_size,
                volume_ratio=volume_ratio
            )

        return None

    # ----------------------------------------------------------
    # 손익 계산
    # ----------------------------------------------------------

    def calculate_trade(
        self,
        signal: BacktestSignal,
        df: pd.DataFrame
    ) -> Optional[Trade]:
        """거래 시뮬레이션 (당일 청산)"""
        # 마지막 봉 찾기 (15:27 또는 그 이전 마지막 봉)
        exit_candle = None
        for i in range(len(df) - 1, signal.candle_index, -1):
            candle_time = df.index[i]
            if hasattr(candle_time, 'time'):
                t = candle_time.time()
                if t <= self.config.market_close_time:
                    exit_candle = df.iloc[i]
                    exit_time = candle_time
                    break

        if exit_candle is None:
            # 마지막 봉 사용
            exit_candle = df.iloc[-1]
            exit_time = df.index[-1]

        entry_price = signal.entry_price
        exit_price = int(exit_candle["close"])

        # 수량 계산
        quantity = self.config.investment_per_trade // entry_price
        if quantity <= 0:
            return None

        # 비용 계산
        entry_cost = int(entry_price * quantity * (self.config.slippage_rate + self.config.commission_rate))
        exit_cost = int(exit_price * quantity * (self.config.slippage_rate + self.config.commission_rate + self.config.tax_rate))
        total_cost = entry_cost + exit_cost

        # 손익 계산
        gross_pnl = (exit_price - entry_price) * quantity
        net_pnl = gross_pnl - total_cost

        # 수익률
        investment = entry_price * quantity
        return_rate = (net_pnl / investment * 100) if investment > 0 else 0

        # 보유 시간
        holding_minutes = int((exit_time - signal.signal_time).total_seconds() / 60)

        return Trade(
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            entry_time=signal.signal_time,
            entry_price=entry_price,
            exit_time=exit_time,
            exit_price=exit_price,
            quantity=quantity,
            gross_pnl=gross_pnl,
            entry_cost=entry_cost,
            exit_cost=exit_cost,
            total_cost=total_cost,
            net_pnl=net_pnl,
            return_rate=return_rate,
            holding_minutes=holding_minutes,
            signal=signal
        )

    # ----------------------------------------------------------
    # 결과 출력
    # ----------------------------------------------------------

    def calculate_summary(self, trades: List[Trade], total_stocks: int, valid_stocks: int) -> BacktestSummary:
        """요약 통계 계산"""
        if not trades:
            return BacktestSummary(
                date=date.today(),
                total_stocks=total_stocks,
                valid_stocks=valid_stocks,
                signal_count=0,
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
                investment_per_trade=self.config.investment_per_trade
            )

        returns = [t.return_rate for t in trades]
        win_count = sum(1 for t in trades if t.net_pnl > 0)
        loss_count = sum(1 for t in trades if t.net_pnl <= 0)

        return BacktestSummary(
            date=date.today(),
            total_stocks=total_stocks,
            valid_stocks=valid_stocks,
            signal_count=len(trades),
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
            investment_per_trade=self.config.investment_per_trade
        )

    def print_results(self, trades: List[Trade], summary: BacktestSummary):
        """콘솔 출력"""
        print("\n" + "=" * 60)
        print("  SNIPER_TRAP 당일청산 백테스트 결과")
        print("=" * 60)
        print(f"  일자: {summary.date}")
        print(f"  대상: 거래대금 상위 {summary.total_stocks}종목")
        print(f"  유효: {summary.valid_stocks}종목 (데이터 충분)")
        print("-" * 60)
        print(f"  신호 발생: {summary.signal_count}건")
        print(f"  거래 수: {summary.trade_count}건")
        print("-" * 60)
        print(f"  승: {summary.win_count}건 / 패: {summary.loss_count}건")
        print(f"  승률: {summary.win_rate:.1f}%")
        print("-" * 60)
        print(f"  총 매매차익: {summary.total_gross_pnl:+,}원")
        print(f"  총 비용: {summary.total_cost:,}원")
        print(f"  순손익: {summary.total_net_pnl:+,}원")
        print("-" * 60)
        print(f"  평균 수익률: {summary.avg_return:+.2f}%")
        print(f"  최대 수익률: {summary.max_return:+.2f}%")
        print(f"  최대 손실률: {summary.min_return:+.2f}%")
        print("-" * 60)
        print(f"  1회 투자금: {summary.investment_per_trade:,}원")
        print(f"  비용: 슬리피지 0.1% + 수수료 0.015% + 세금 0.18%")
        print("=" * 60)

        if trades:
            print("\n[거래 내역]")
            print("-" * 100)
            print(f"{'종목':<12} {'진입시간':^10} {'진입가':>10} {'청산가':>10} {'수량':>6} {'순손익':>12} {'수익률':>8}")
            print("-" * 100)

            for t in sorted(trades, key=lambda x: x.return_rate, reverse=True):
                print(f"{t.stock_name:<12} {t.entry_time.strftime('%H:%M'):^10} "
                      f"{t.entry_price:>10,} {t.exit_price:>10,} "
                      f"{t.quantity:>6} {t.net_pnl:>+12,} {t.return_rate:>+7.2f}%")

            print("-" * 100)

    def export_to_excel(self, trades: List[Trade], summary: BacktestSummary, output_path: str):
        """엑셀 파일 출력"""
        try:
            # Sheet 1: 요약
            summary_data = {
                "항목": [
                    "백테스트 일자", "대상 종목 수", "유효 종목 수", "신호 발생 수",
                    "승", "패", "승률", "총 매매차익", "총 비용", "순손익",
                    "평균 수익률", "최대 수익률", "최대 손실률", "1회 투자금"
                ],
                "값": [
                    str(summary.date), summary.total_stocks, summary.valid_stocks, summary.signal_count,
                    summary.win_count, summary.loss_count, f"{summary.win_rate:.1f}%",
                    f"{summary.total_gross_pnl:+,}", f"{summary.total_cost:,}", f"{summary.total_net_pnl:+,}",
                    f"{summary.avg_return:+.2f}%", f"{summary.max_return:+.2f}%", f"{summary.min_return:+.2f}%",
                    f"{summary.investment_per_trade:,}"
                ]
            }
            df_summary = pd.DataFrame(summary_data)

            # Sheet 2: 거래 내역
            trades_data = []
            for t in trades:
                trades_data.append({
                    "종목코드": t.stock_code,
                    "종목명": t.stock_name,
                    "진입시간": t.entry_time.strftime("%Y-%m-%d %H:%M"),
                    "진입가": t.entry_price,
                    "청산시간": t.exit_time.strftime("%Y-%m-%d %H:%M"),
                    "청산가": t.exit_price,
                    "수량": t.quantity,
                    "매매차익": t.gross_pnl,
                    "비용": t.total_cost,
                    "순손익": t.net_pnl,
                    "수익률(%)": round(t.return_rate, 2),
                    "보유시간(분)": t.holding_minutes
                })
            df_trades = pd.DataFrame(trades_data)

            # Sheet 3: 신호 상세
            signals_data = []
            for t in trades:
                if t.signal:
                    signals_data.append({
                        "종목코드": t.signal.stock_code,
                        "종목명": t.signal.stock_name,
                        "신호시간": t.signal.signal_time.strftime("%Y-%m-%d %H:%M"),
                        "가격": t.signal.entry_price,
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

    async def run(self) -> Tuple[List[Trade], BacktestSummary]:
        """백테스트 실행"""
        # 1. 거래대금 상위 종목 조회
        stocks = await self.get_top_stocks()
        total_stocks = len(stocks)

        # 2. 필터 적용 (옵션)
        if self.config.apply_5filters:
            stocks = await self.apply_5filters(stocks)
            self.logger.info(f"5필터 통과: {len(stocks)}종목")
        elif self.config.etf_only:
            stocks = self.filter_etf_only(stocks)

        # 3. 데이터 로딩
        data = await self.load_all_data(stocks)
        valid_stocks = len(data)

        self.logger.info(f"유효 데이터: {valid_stocks}/{total_stocks}종목")

        # 3. 신호 탐지 및 거래 시뮬레이션
        trades = []
        for stock_code, (df, stock_name) in data.items():
            signal = self.detect_first_signal(df, stock_code, stock_name)

            if signal:
                self.logger.info(f"신호 발생: {stock_code} {stock_name} @ {signal.signal_time.strftime('%H:%M')} {signal.entry_price:,}원")

                trade = self.calculate_trade(signal, df)
                if trade:
                    trades.append(trade)

        # 4. 요약 계산
        summary = self.calculate_summary(trades, total_stocks, valid_stocks)

        return trades, summary


# ============================================================
# 메인 함수
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="SNIPER_TRAP 당일청산 백테스트")
    parser.add_argument("--top-n", type=int, default=10, help="거래대금 상위 N종목 (기본: 10)")
    parser.add_argument("--output", type=str, default=None, help="엑셀 출력 파일 경로")
    parser.add_argument("--filter", action="store_true", help="5필터 적용 (ETF제외, 시가총액, 등락률, 거래대금)")
    parser.add_argument("--etf-only", action="store_true", help="ETF만 제외 (다른 필터 미적용)")
    parser.add_argument("--skip-change-rate", action="store_true", help="등락률 필터 스킵")
    args = parser.parse_args()

    # 로깅 설정
    setup_logging()

    if args.filter:
        filter_text = "5필터 적용"
    elif args.etf_only:
        filter_text = "ETF만 제외"
    else:
        filter_text = "필터 없음"

    print(f"\nSNIPER_TRAP 당일청산 백테스트 시작")
    print(f"대상: 거래대금 상위 {args.top_n}종목")
    print(f"필터: {filter_text}")
    print(f"청산: 당일 15:30 장마감")
    print(f"비용: 슬리피지 0.1% + 수수료 0.015% + 세금 0.18%")
    if args.filter:
        print(f"5필터: ETF제외, 시가총액(1천억~20조), 등락률(2~29.9%), 거래대금(200억+)")
    print("-" * 50)

    config = BacktestConfig(top_n=args.top_n, apply_5filters=args.filter, etf_only=args.etf_only, skip_change_rate=args.skip_change_rate)

    async with SniperTrapBacktester(config) as backtester:
        trades, summary = await backtester.run()

        # 결과 출력
        backtester.print_results(trades, summary)

        # 엑셀 저장 (옵션)
        if args.output:
            backtester.export_to_excel(trades, summary, args.output)

    return trades, summary


if __name__ == "__main__":
    asyncio.run(main())
