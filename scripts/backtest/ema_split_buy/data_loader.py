# -*- coding: utf-8 -*-
"""
데이터 로더

past1000.csv 파일 파싱 및 키움 REST API 일봉 데이터 조회
"""

import asyncio
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import pandas as pd

from .config import EMASplitBuyConfig


class DataLoader:
    """데이터 로더"""

    ETF_KEYWORDS = [
        "KODEX", "TIGER", "RISE", "SOL", "HANARO", "PLUS", "KBSTAR",
        "ACE", "ARIRANG", "KOSEF", "SMART", "TREX", "FOCUS", "파워",
        "레버리지", "인버스", "ETN", "ETF"
    ]

    def __init__(self, config: EMASplitBuyConfig, api_client=None, logger=None):
        self.config = config
        self._api_client = api_client
        self._logger = logger

    def load_stock_list(self, csv_path: str = None) -> List[Dict[str, str]]:
        """
        past1000.csv에서 종목 리스트 로딩

        Returns:
            List[Dict]: [{"code": "005930", "name": "삼성전자"}, ...]
        """
        if csv_path is None:
            # 프로젝트 루트의 past1000.csv
            project_root = Path(__file__).parent.parent.parent.parent
            csv_path = project_root / "past1000.csv"

        try:
            # CP949 인코딩으로 읽기 (한글 포함)
            df = pd.read_csv(csv_path, encoding='cp949', dtype=str)
        except UnicodeDecodeError:
            # UTF-8 시도
            df = pd.read_csv(csv_path, encoding='utf-8', dtype=str)

        stocks = []
        for _, row in df.iterrows():
            # 첫 번째 컬럼: 종목코드 (앞에 ' 붙어있음)
            code = str(row.iloc[0]).replace("'", "").strip()
            # 두 번째 컬럼: 종목명
            name = str(row.iloc[1]).strip()

            # 6자리 코드만 허용
            if len(code) != 6:
                continue

            # ETF 제외
            if self._is_etf(name):
                continue

            stocks.append({"code": code, "name": name})

        if self._logger:
            self._logger.info(f"past1000.csv에서 {len(stocks)}개 종목 로딩 완료")

        return stocks

    def _is_etf(self, name: str) -> bool:
        """ETF 여부 판단"""
        return any(keyword in name for keyword in self.ETF_KEYWORDS)

    async def load_daily_candles(
        self,
        stock_code: str,
        days: int = None
    ) -> Optional[pd.DataFrame]:
        """
        키움 REST API로 일봉 데이터 조회

        Args:
            stock_code: 종목코드
            days: 조회 일수 (기본: config.lookback_days)

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, trading_value
        """
        if self._api_client is None:
            if self._logger:
                self._logger.error("API 클라이언트가 설정되지 않음")
            return None

        if days is None:
            days = self.config.lookback_days

        try:
            # 키움 API: MarketAPI.get_daily_candles()
            from src.api.endpoints.market import MarketAPI
            market_api = MarketAPI(self._api_client)

            candles = await market_api.get_daily_chart(
                stock_code=stock_code,
                count=days
            )

            if not candles:
                return None

            # DataFrame 변환
            data = []
            for c in candles:
                candle_date = c.date if isinstance(c.date, date) else (
                    c.date.date() if isinstance(c.date, datetime) else datetime.strptime(str(c.date), '%Y%m%d').date()
                )
                data.append({
                    'date': candle_date,
                    'open': c.open_price,
                    'high': c.high_price,
                    'low': c.low_price,
                    'close': c.close_price,
                    'volume': c.volume,
                    'trading_value': c.trading_value if hasattr(c, 'trading_value') else c.volume * c.close_price
                })

            df = pd.DataFrame(data)
            df = df.sort_values('date').reset_index(drop=True)

            return df

        except Exception as e:
            if self._logger:
                self._logger.error(f"일봉 데이터 조회 실패 [{stock_code}]: {e}")
            return None

    async def load_all_stocks_data(
        self,
        stocks: List[Dict[str, str]],
        delay: float = 0.1
    ) -> Dict[str, pd.DataFrame]:
        """
        모든 종목의 일봉 데이터 조회

        Args:
            stocks: 종목 리스트 [{"code": ..., "name": ...}, ...]
            delay: API 호출 간 지연 (초)

        Returns:
            Dict[stock_code, DataFrame]
        """
        result = {}
        total = len(stocks)

        for i, stock in enumerate(stocks):
            code = stock["code"]
            name = stock["name"]

            if self._logger and (i + 1) % 10 == 0:
                self._logger.info(f"일봉 데이터 로딩 중... {i + 1}/{total}")

            df = await self.load_daily_candles(code)
            if df is not None and len(df) >= self.config.min_candles:
                result[code] = df

            # Rate limit
            await asyncio.sleep(delay)

        if self._logger:
            self._logger.info(f"총 {len(result)}개 종목 데이터 로딩 완료 (유효: {len(result)}/{total})")

        return result

    def filter_by_trading_value(
        self,
        df: pd.DataFrame,
        min_value: int = None
    ) -> pd.DataFrame:
        """
        거래대금 기준 필터링

        Args:
            df: 일봉 데이터
            min_value: 최소 거래대금 (기본: config.min_trading_value)

        Returns:
            필터링된 DataFrame
        """
        if min_value is None:
            min_value = self.config.min_trading_value

        return df[df['trading_value'] >= min_value].copy()

    def get_business_days(self, df: pd.DataFrame) -> List[date]:
        """
        데이터에서 영업일 목록 추출

        Args:
            df: 일봉 데이터

        Returns:
            영업일 리스트
        """
        return df['date'].tolist()

    def count_business_days_between(
        self,
        df: pd.DataFrame,
        start_date: date,
        end_date: date
    ) -> int:
        """
        두 날짜 사이의 영업일 수 계산 (시작일 제외)

        Args:
            df: 일봉 데이터
            start_date: 시작일 (포함 안 함)
            end_date: 종료일 (포함)

        Returns:
            영업일 수
        """
        dates = df['date'].tolist()
        count = 0
        for d in dates:
            if start_date < d <= end_date:
                count += 1
        return count

    def get_next_business_day(
        self,
        df: pd.DataFrame,
        current_date: date
    ) -> Optional[date]:
        """
        다음 영업일 반환

        Args:
            df: 일봉 데이터
            current_date: 현재 날짜

        Returns:
            다음 영업일 또는 None
        """
        dates = sorted(df['date'].tolist())
        for d in dates:
            if d > current_date:
                return d
        return None

    def get_candle_by_date(
        self,
        df: pd.DataFrame,
        target_date: date
    ) -> Optional[pd.Series]:
        """
        특정 날짜의 캔들 데이터 반환

        Args:
            df: 일봉 데이터
            target_date: 대상 날짜

        Returns:
            캔들 데이터 (Series) 또는 None
        """
        mask = df['date'] == target_date
        if mask.sum() == 0:
            return None
        return df[mask].iloc[0]

    def get_nth_business_day_after(
        self,
        df: pd.DataFrame,
        start_date: date,
        n: int
    ) -> Optional[date]:
        """
        시작일로부터 n영업일 후의 날짜 반환 (시작일 제외)

        Args:
            df: 일봉 데이터
            start_date: 시작일
            n: 영업일 수

        Returns:
            n영업일 후 날짜 또는 None
        """
        dates = sorted(df['date'].tolist())
        count = 0
        for d in dates:
            if d > start_date:
                count += 1
                if count == n:
                    return d
        return None

    # =========================================================================
    # Phase 2: 3분봉 데이터 로더
    # =========================================================================

    async def load_minute_candles(
        self,
        stock_code: str,
        count: int = 400
    ) -> Optional[pd.DataFrame]:
        """
        키움 REST API로 3분봉 데이터 조회

        Note: 백테스트에서는 과거 특정 기간의 3분봉을 조회하기 어려움.
              최근 데이터만 조회 가능.

        Args:
            stock_code: 종목코드
            count: 조회 봉 수 (기본: 400)

        Returns:
            DataFrame with columns: datetime, open, high, low, close, volume
        """
        if self._api_client is None:
            if self._logger:
                self._logger.error("API 클라이언트가 설정되지 않음")
            return None

        try:
            from src.api.endpoints.market import MarketAPI
            market_api = MarketAPI(self._api_client)

            candles = await market_api.get_minute_chart(
                stock_code=stock_code,
                timeframe=3,  # 3분봉
                count=count,
                use_pagination=True
            )

            if not candles:
                return None

            # DataFrame 변환
            data = []
            for c in candles:
                data.append({
                    'datetime': c.timestamp,  # MinuteCandle uses 'timestamp' not 'datetime'
                    'open': c.open_price,
                    'high': c.high_price,
                    'low': c.low_price,
                    'close': c.close_price,
                    'volume': c.volume
                })

            df = pd.DataFrame(data)
            df = df.sort_values('datetime').reset_index(drop=True)

            return df

        except Exception as e:
            if self._logger:
                self._logger.error(f"3분봉 데이터 조회 실패 [{stock_code}]: {e}")
            return None

    def simulate_intraday_from_daily(
        self,
        daily_row: pd.Series,
        bars_per_day: int = 130
    ) -> pd.DataFrame:
        """
        일봉 데이터에서 장중 움직임 시뮬레이션

        Note: 실제 3분봉 API 조회가 불가능한 과거 데이터의 경우
              일봉의 OHLC를 기반으로 장중 움직임을 시뮬레이션

        가정:
        - 시가에서 시작
        - 고가와 저가 사이를 랜덤하게 움직임
        - 종가에서 마감

        Args:
            daily_row: 일봉 데이터 (date, open, high, low, close)
            bars_per_day: 하루 3분봉 개수 (기본: 130)

        Returns:
            시뮬레이션된 3분봉 DataFrame
        """
        import numpy as np

        open_price = daily_row['open']
        high_price = daily_row['high']
        low_price = daily_row['low']
        close_price = daily_row['close']
        trade_date = daily_row['date']

        # 시뮬레이션 가격 생성
        prices = []
        current = open_price

        # 고가/저가 도달 시점 랜덤 결정
        high_bar = np.random.randint(1, bars_per_day - 1)
        low_bar = np.random.randint(1, bars_per_day - 1)

        for i in range(bars_per_day):
            if i == 0:
                price = open_price
            elif i == high_bar:
                price = high_price
            elif i == low_bar:
                price = low_price
            elif i == bars_per_day - 1:
                price = close_price
            else:
                # 랜덤 가격 (low ~ high 사이)
                price = np.random.uniform(low_price, high_price)

            prices.append(price)

        # DataFrame 생성
        data = []
        base_time = datetime.combine(trade_date, datetime.min.time()).replace(hour=9, minute=0)

        for i, price in enumerate(prices):
            bar_time = base_time + pd.Timedelta(minutes=i * 3)
            # 간단한 OHLC 생성 (시뮬레이션이므로 동일하게)
            data.append({
                'datetime': bar_time,
                'open': int(price),
                'high': int(price * 1.001),
                'low': int(price * 0.999),
                'close': int(price),
                'volume': 1000  # 더미
            })

        return pd.DataFrame(data)

    def simulate_multi_day_intraday(
        self,
        daily_df: pd.DataFrame,
        entry_date: date,
        max_days: int = 60
    ) -> pd.DataFrame:
        """
        여러 일의 장중 데이터 시뮬레이션

        Args:
            daily_df: 일봉 데이터
            entry_date: 진입일
            max_days: 최대 일수

        Returns:
            시뮬레이션된 3분봉 DataFrame
        """
        all_data = []

        # 진입일 이후 데이터 필터
        mask = daily_df['date'] >= entry_date
        future_df = daily_df[mask].head(max_days)

        for _, row in future_df.iterrows():
            day_df = self.simulate_intraday_from_daily(row)
            all_data.append(day_df)

        if not all_data:
            return pd.DataFrame()

        return pd.concat(all_data, ignore_index=True)
