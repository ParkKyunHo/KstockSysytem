# -*- coding: utf-8 -*-
"""
Daily Equity Curve - Data Loader

testday.csv 파싱 및 API 일봉 조회
"""

import asyncio
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd

from .config import BacktestConfig


class DataLoader:
    """데이터 로딩 및 캐싱"""

    ETF_KEYWORDS = [
        "KODEX", "TIGER", "RISE", "SOL", "HANARO", "PLUS", "KBSTAR",
        "ACE", "ARIRANG", "KOSEF", "SMART", "TREX", "FOCUS", "파워",
        "레버리지", "인버스", "ETN", "ETF"
    ]

    def __init__(self, config: BacktestConfig, api_client=None, logger=None):
        self.config = config
        self._client = api_client
        self._market_api = None
        self._semaphore = asyncio.Semaphore(config.api_concurrency)
        self.logger = logger or self._default_logger()

    def _default_logger(self):
        """기본 로거"""
        import logging
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"
            ))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def set_market_api(self, market_api):
        """MarketAPI 설정"""
        self._market_api = market_api

    # ============================================================
    # testday.csv 로딩
    # ============================================================

    def load_testday(self) -> List[Dict[str, str]]:
        """testday.csv에서 종목 목록 로드 (ETF 제외)"""
        path = self.config.testday_path

        if not path.exists():
            self.logger.error(f"testday.csv 파일 없음: {path}")
            return []

        try:
            df = pd.read_csv(path, encoding="cp949", dtype=str)
        except Exception as e:
            self.logger.error(f"testday.csv 로드 실패: {e}")
            return []

        stocks = []
        for _, row in df.iterrows():
            # 첫 컬럼: 종목코드 (앞에 ' 붙어있음)
            code_raw = str(row.iloc[0]).strip()
            if code_raw.startswith("'"):
                code_raw = code_raw[1:]

            # 6자리로 패딩
            stock_code = code_raw.zfill(6)

            # 두 번째 컬럼: 종목명
            stock_name = str(row.iloc[1]).strip() if len(row) > 1 else ""

            # ETF 제외
            if self._is_etf(stock_name):
                continue

            stocks.append({
                "stock_code": stock_code,
                "stock_name": stock_name
            })

        self.logger.info(f"testday.csv 로드: {len(stocks)}개 종목 (ETF 제외)")
        return stocks

    def _is_etf(self, stock_name: str) -> bool:
        """ETF 여부 확인"""
        for keyword in self.ETF_KEYWORDS:
            if keyword in stock_name:
                return True
        return False

    # ============================================================
    # 일봉 데이터 로딩
    # ============================================================

    async def load_daily_candles(
        self,
        stock_code: str,
        count: Optional[int] = None
    ) -> Optional[pd.DataFrame]:
        """일봉 데이터 조회 (캐싱 지원)"""
        count = count or self.config.daily_candle_count
        cache_path = self._daily_cache_path(stock_code)

        # 캐시 확인
        if self.config.use_cache and cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                self.logger.debug(f"{stock_code}: 일봉 캐시 로드 ({len(df)}봉)")
                return df
            except Exception as e:
                self.logger.warning(f"{stock_code}: 캐시 로드 실패 - {e}")

        # API 조회
        if self._market_api is None:
            self.logger.warning(f"{stock_code}: MarketAPI 미설정")
            return None

        async with self._semaphore:
            try:
                candles = await self._market_api.get_daily_chart(stock_code, count=count)
                await asyncio.sleep(self.config.api_delay_seconds)
            except Exception as e:
                self.logger.warning(f"{stock_code}: 일봉 조회 실패 - {e}")
                return None

        if not candles:
            return None

        # DataFrame 변환
        records = []
        for c in candles:
            # date 처리
            if hasattr(c, 'date'):
                c_date = c.date if isinstance(c.date, date) else c.date.date()
            else:
                continue

            # trading_value 처리
            trading_value = getattr(c, 'trading_value', 0)
            if trading_value == 0:
                trading_value = c.close_price * c.volume

            records.append({
                "date": c_date,
                "open": c.open_price,
                "high": c.high_price,
                "low": c.low_price,
                "close": c.close_price,
                "volume": c.volume,
                "trading_value": trading_value
            })

        if not records:
            return None

        df = pd.DataFrame(records)
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # 캐시 저장
        if self.config.use_cache:
            try:
                df.to_parquet(cache_path)
            except Exception as e:
                self.logger.warning(f"{stock_code}: 캐시 저장 실패 - {e}")

        return df

    def _daily_cache_path(self, stock_code: str) -> Path:
        """일봉 캐시 파일 경로"""
        return self.config.cache_dir / "daily" / f"{stock_code}.parquet"

    async def load_daily_batch(
        self,
        stocks: List[Dict[str, str]],
        count: Optional[int] = None
    ) -> Dict[str, pd.DataFrame]:
        """여러 종목의 일봉 데이터 배치 로드"""
        results = {}
        total = len(stocks)

        for i, stock in enumerate(stocks):
            stock_code = stock["stock_code"]
            df = await self.load_daily_candles(stock_code, count)

            if df is not None and len(df) > 0:
                results[stock_code] = df

            if (i + 1) % 10 == 0:
                self.logger.info(f"일봉 로드 진행: {i + 1}/{total}")

        self.logger.info(f"일봉 로드 완료: {len(results)}/{total} 종목")
        return results

    # ============================================================
    # 동기 래퍼
    # ============================================================

    def load_daily_batch_sync(
        self,
        stocks: List[Dict[str, str]],
        count: Optional[int] = None
    ) -> Dict[str, pd.DataFrame]:
        """동기 래퍼"""
        return asyncio.run(self.load_daily_batch(stocks, count))

    # ============================================================
    # 캐시 데이터 로드 (API 없이)
    # ============================================================

    def load_from_cache(
        self,
        stocks: List[Dict[str, str]]
    ) -> Dict[str, pd.DataFrame]:
        """캐시에서만 데이터 로드 (API 호출 없음)"""
        results = {}

        for stock in stocks:
            stock_code = stock["stock_code"]
            cache_path = self._daily_cache_path(stock_code)

            if cache_path.exists():
                try:
                    df = pd.read_parquet(cache_path)
                    results[stock_code] = df
                except Exception as e:
                    self.logger.warning(f"{stock_code}: 캐시 로드 실패 - {e}")

        self.logger.info(f"캐시 로드 완료: {len(results)}/{len(stocks)} 종목")
        return results
