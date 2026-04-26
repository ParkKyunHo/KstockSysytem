# -*- coding: utf-8 -*-
"""
V7 Purple 3분봉 백테스트 - 데이터 로더

3mintest.csv 로딩, 일봉/분봉 API 조회, parquet 캐싱
"""

import asyncio
from datetime import datetime, date, timedelta
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

    def __init__(self, config: BacktestConfig, api_client, logger):
        self.config = config
        self._client = api_client
        self._market_api = None
        self._semaphore = asyncio.Semaphore(config.api_concurrency)
        self.logger = logger

    def set_market_api(self, market_api):
        """MarketAPI 설정"""
        self._market_api = market_api

    # ============================================================
    # 3mintest.csv 로딩
    # ============================================================

    def load_test_stocks(self) -> List[Dict[str, str]]:
        """3mintest.csv에서 종목 목록 로드 (ETF 제외)"""
        path = self.config.test_stocks_path

        if not path.exists():
            self.logger.error(f"3mintest.csv 파일 없음: {path}")
            return []

        try:
            df = pd.read_csv(path, encoding="cp949", dtype=str)
        except Exception as e:
            self.logger.error(f"3mintest.csv 로드 실패: {e}")
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

        self.logger.info(f"3mintest.csv 로드: {len(stocks)}개 종목 (ETF 제외)")
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
            if hasattr(c, 'date'):
                c_date = c.date if isinstance(c.date, date) else c.date.date()
            else:
                continue

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
        count = count or self.config.daily_candle_count
        results = {}
        total = len(stocks)

        for i, stock in enumerate(stocks):
            stock_code = stock["stock_code"]
            df = await self.load_daily_candles(stock_code, count)

            if df is not None and len(df) > 0:
                results[stock_code] = df

            if (i + 1) % 10 == 0:
                self.logger.info(f"일봉 로드 진행: {i + 1}/{total}")

        return results

    # ============================================================
    # 분봉 데이터 로딩
    # ============================================================

    async def load_minute_candles(
        self,
        stock_code: str,
        target_date: date
    ) -> Optional[pd.DataFrame]:
        """특정 날짜의 3분봉 데이터 조회 (캐싱 지원)"""
        cache_path = self._minute_cache_path(stock_code, target_date)

        # 캐시 확인
        if self.config.use_cache and cache_path.exists():
            try:
                df = pd.read_parquet(cache_path)
                self.logger.debug(f"{stock_code} @ {target_date}: 분봉 캐시 로드 ({len(df)}봉)")
                return df
            except Exception as e:
                self.logger.warning(f"{stock_code}: 분봉 캐시 로드 실패 - {e}")

        # API 조회
        async with self._semaphore:
            df = await self._fetch_minute_candles(stock_code, target_date)
            await asyncio.sleep(self.config.api_delay_seconds)

        if df is None or len(df) == 0:
            return None

        # 캐시 저장
        if self.config.use_cache:
            try:
                df.to_parquet(cache_path)
            except Exception as e:
                self.logger.warning(f"{stock_code}: 분봉 캐시 저장 실패 - {e}")

        return df

    async def _fetch_minute_candles(
        self,
        stock_code: str,
        target_date: date
    ) -> Optional[pd.DataFrame]:
        """API로 분봉 데이터 조회"""
        stock_code = stock_code.replace("A", "")
        CHART_URL = "/api/dostk/chart"

        body = {
            "stk_cd": stock_code,
            "tic_scope": str(self.config.timeframe),
            "upd_stkpc_tp": "0",
        }

        all_records = []
        found_target = False

        try:
            all_responses = await self._client.paginate(
                url=CHART_URL,
                api_id="ka10080",
                body=body,
                max_pages=self.config.max_minute_pages,
            )

            for response_data in all_responses:
                candles = self._parse_minute_data(response_data)
                for candle in candles:
                    candle_date = candle["datetime"].date()

                    if candle_date == target_date:
                        all_records.append(candle)
                        found_target = True
                    elif found_target and candle_date < target_date:
                        break

                if all_records and all_records[-1]["datetime"].date() < target_date:
                    break

        except Exception as e:
            self.logger.warning(f"{stock_code}: 분봉 조회 실패 - {e}")
            return None

        if not all_records:
            self.logger.warning(f"{stock_code}: {target_date} 분봉 데이터 없음")
            return None

        df = pd.DataFrame(all_records)
        df.sort_values("datetime", inplace=True)
        df.set_index("datetime", inplace=True)

        self.logger.info(f"{stock_code} @ {target_date}: {len(df)}개 분봉 로드")
        return df

    def _parse_minute_data(self, response_data: dict) -> List[Dict]:
        """API 응답에서 분봉 데이터 파싱"""
        records = []

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

                records.append({
                    "datetime": dt,
                    "open": parse_price(item.get("open_pric", 0)),
                    "high": parse_price(item.get("high_pric", 0)),
                    "low": parse_price(item.get("low_pric", 0)),
                    "close": parse_price(item.get("cur_prc", 0)),
                    "volume": int(float(item.get("trde_qty", 0))),
                })

            except (ValueError, TypeError):
                continue

        return records

    def _minute_cache_path(self, stock_code: str, target_date: date) -> Path:
        """분봉 캐시 파일 경로"""
        date_str = target_date.strftime("%Y%m%d")
        return self.config.cache_dir / "minute" / f"{stock_code}_{date_str}.parquet"

    # ============================================================
    # 멀티데이 분봉 로딩 (익일 이월용)
    # ============================================================

    async def load_minute_candles_multiday(
        self,
        stock_code: str,
        start_date: date,
        max_days: Optional[int] = None
    ) -> Optional[pd.DataFrame]:
        """
        여러 날짜의 3분봉 데이터 연결 (수익 시 익일 이월용)

        Args:
            stock_code: 종목코드
            start_date: 시작 날짜 (이벤트 발생일)
            max_days: 최대 로드 일수

        Returns:
            여러 날 분봉 데이터 연결된 DataFrame (datetime index)
        """
        max_days = max_days or self.config.max_hold_days

        all_dfs = []
        current_date = start_date
        days_loaded = 0

        while days_loaded < max_days:
            df = await self.load_minute_candles(stock_code, current_date)
            if df is not None and len(df) > 0:
                all_dfs.append(df)
                days_loaded += 1

            # 다음 영업일 (주말 제외)
            current_date += timedelta(days=1)
            while current_date.weekday() >= 5:  # 토, 일
                current_date += timedelta(days=1)

            # 범위 체크
            if current_date > self.config.event_end:
                break

        if not all_dfs:
            return None

        combined = pd.concat(all_dfs)
        combined.sort_index(inplace=True)

        self.logger.info(
            f"{stock_code}: {days_loaded}일 분봉 연결 ({len(combined)}봉, "
            f"{start_date} ~ {combined.index[-1].date()})"
        )
        return combined

    # ============================================================
    # 영업일 유틸리티
    # ============================================================

    def get_next_business_day(self, current: date) -> date:
        """다음 영업일 반환 (주말 제외)"""
        next_day = current + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        return next_day

    def get_business_days(self, start: date, end: date) -> List[date]:
        """기간 내 영업일 목록 반환"""
        days = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
        return days
