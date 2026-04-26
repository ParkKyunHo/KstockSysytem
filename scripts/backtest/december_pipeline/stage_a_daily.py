# -*- coding: utf-8 -*-
"""
December Pipeline - Stage A: Daily Event Capture

past1000.csv 종목에서 12월 이벤트 포착
- 거래대금 >= 1000억
- 등락률 >= 10% (전일 대비)
"""

from datetime import date
from typing import List, Dict, Tuple
import pandas as pd

from .config import PipelineConfig, EventDay, EventSummary
from .data_loader import DataLoader


class StageAProcessor:
    """Stage A: 일봉 이벤트 포착"""

    def __init__(self, config: PipelineConfig, data_loader: DataLoader, logger):
        self.config = config
        self.loader = data_loader
        self.logger = logger

    async def run(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Stage A 실행"""
        self.logger.info("=" * 60)
        self.logger.info("[Stage A] 일봉 이벤트 포착 시작")
        self.logger.info("=" * 60)

        # 1. 종목 목록 로드
        stocks = self.loader.load_past1000()
        if not stocks:
            self.logger.error("종목 목록 없음")
            return pd.DataFrame(), pd.DataFrame()

        self.logger.info(f"후보 종목 수: {len(stocks)}")

        # 2. 일봉 데이터 배치 로드
        daily_data = await self.loader.load_daily_batch(stocks, count=300)
        self.logger.info(f"일봉 로드 성공: {len(daily_data)}/{len(stocks)}")

        # 3. 이벤트 포착
        all_events = []
        failed_stocks = []

        for stock in stocks:
            stock_code = stock["stock_code"]
            stock_name = stock["stock_name"]

            df = daily_data.get(stock_code)
            if df is None or len(df) == 0:
                failed_stocks.append(stock_code)
                continue

            # prev_close 및 등락률 계산
            df = self._calculate_returns(df)

            # 12월 이벤트 필터링
            events = self._filter_december_events(df, stock_code, stock_name)
            all_events.extend(events)

        # 4. 이벤트 DataFrame 생성
        if all_events:
            events_df = pd.DataFrame([{
                "date": e.date,
                "ticker": e.ticker,
                "stock_name": e.stock_name,
                "close": e.close,
                "prev_close": e.prev_close,
                "ret": round(e.ret, 2),
                "value": e.value
            } for e in all_events])
            events_df.sort_values(["date", "ticker"], inplace=True)
        else:
            events_df = pd.DataFrame(columns=[
                "date", "ticker", "stock_name", "close", "prev_close", "ret", "value"
            ])

        # 5. 요약 생성
        summary_df = self._create_summary(events_df)

        # 6. 검증 로그
        self._print_validation_log(stocks, daily_data, failed_stocks, events_df)

        # 7. CSV 저장
        events_df.to_csv(self.config.event_days_path, index=False, encoding="utf-8-sig")
        summary_df.to_csv(self.config.event_summary_path, index=False, encoding="utf-8-sig")

        self.logger.info(f"event_days.csv 저장: {self.config.event_days_path}")
        self.logger.info(f"event_summary.csv 저장: {self.config.event_summary_path}")

        return events_df, summary_df

    def _calculate_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """prev_close 및 등락률 계산"""
        df = df.copy()
        df["prev_close"] = df["close"].shift(1)
        df["ret"] = (df["close"] - df["prev_close"]) / df["prev_close"] * 100
        return df

    def _filter_december_events(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str
    ) -> List[EventDay]:
        """12월 이벤트 필터링"""
        events = []

        for _, row in df.iterrows():
            row_date = row["date"]
            if isinstance(row_date, str):
                row_date = pd.to_datetime(row_date).date()
            elif hasattr(row_date, 'date'):
                row_date = row_date.date()

            # 12월 기간 필터
            if row_date < self.config.event_start or row_date > self.config.event_end:
                continue

            # prev_close 없으면 스킵
            if pd.isna(row["prev_close"]) or pd.isna(row["ret"]):
                continue

            # 거래대금 조건
            trading_value = row.get("trading_value", 0)
            if trading_value == 0:
                trading_value = row["close"] * row["volume"]

            if trading_value < self.config.min_trading_value:
                continue

            # 등락률 조건
            if row["ret"] < self.config.min_change_rate:
                continue

            # 이벤트 추가
            events.append(EventDay(
                date=row_date,
                ticker=stock_code,
                stock_name=stock_name,
                close=int(row["close"]),
                prev_close=int(row["prev_close"]),
                ret=float(row["ret"]),
                value=int(trading_value)
            ))

        return events

    def _create_summary(self, events_df: pd.DataFrame) -> pd.DataFrame:
        """종목별 이벤트 요약 생성"""
        if events_df.empty:
            return pd.DataFrame(columns=[
                "ticker", "stock_name", "hit_count", "first_hit_date", "max_value", "max_ret"
            ])

        summary = events_df.groupby(["ticker", "stock_name"]).agg({
            "date": ["count", "min"],
            "value": "max",
            "ret": "max"
        }).reset_index()

        summary.columns = ["ticker", "stock_name", "hit_count", "first_hit_date", "max_value", "max_ret"]
        summary.sort_values("hit_count", ascending=False, inplace=True)

        return summary

    def _print_validation_log(
        self,
        stocks: List[Dict],
        daily_data: Dict[str, pd.DataFrame],
        failed_stocks: List[str],
        events_df: pd.DataFrame
    ):
        """검증 로그 출력"""
        print("\n" + "=" * 60)
        print("[Stage A] 검증 로그")
        print("=" * 60)

        print(f"후보 종목 수: {len(stocks)}")
        print(f"일봉 로드 성공: {len(daily_data)}")
        print(f"일봉 로드 실패: {len(failed_stocks)}")

        if events_df.empty:
            print("12월 이벤트: 0건")
        else:
            unique_tickers = events_df["ticker"].nunique()
            print(f"12월 이벤트: {len(events_df)}건 ({unique_tickers}개 종목)")

            # 일자별 이벤트 수 TOP 10
            print("\n[일자별 이벤트 TOP 10]")
            date_counts = events_df.groupby("date").size().sort_values(ascending=False).head(10)
            for dt, cnt in date_counts.items():
                print(f"  {dt}: {cnt}건")

            # 샘플 10건
            print(f"\n[샘플 이벤트 (최대 10건)]")
            sample = events_df.head(10)
            for _, row in sample.iterrows():
                value_str = f"{row['value'] / 1e8:.0f}억"
                print(f"  {row['date']} | {row['ticker']} | "
                      f"close={row['close']:,} | prev={row['prev_close']:,} | "
                      f"ret=+{row['ret']:.1f}% | value={value_str}")

        print("=" * 60)
