# -*- coding: utf-8 -*-
"""
V7 Purple 3분봉 백테스트 - Stage A: 이벤트일 필터

거래대금 1000억 이상 날짜 선별
"""

from datetime import date
from typing import List, Dict, Tuple
import pandas as pd

from .config import BacktestConfig, EventDay


class EventFilter:
    """Stage A: 거래대금 기반 이벤트일 필터"""

    def __init__(self, config: BacktestConfig, logger):
        self.config = config
        self.logger = logger

    def filter_event_days(
        self,
        stock_code: str,
        stock_name: str,
        daily_df: pd.DataFrame
    ) -> List[EventDay]:
        """
        단일 종목의 거래대금 이벤트일 필터링

        조건: 거래대금 >= 1000억

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            daily_df: 일봉 DataFrame (date, open, high, low, close, volume, trading_value)

        Returns:
            EventDay 리스트
        """
        if daily_df is None or len(daily_df) == 0:
            return []

        events = []

        for _, row in daily_df.iterrows():
            row_date = row['date']

            # date 타입 확인
            if isinstance(row_date, str):
                row_date = pd.to_datetime(row_date).date()
            elif hasattr(row_date, 'date'):
                row_date = row_date.date()

            # 기간 필터
            if row_date < self.config.event_start or row_date > self.config.event_end:
                continue

            # 거래대금 필터 (1000억 이상)
            trading_value = row.get('trading_value', 0)
            if trading_value < self.config.min_trading_value:
                continue

            events.append(EventDay(
                date=row_date,
                stock_code=stock_code,
                stock_name=stock_name,
                close=int(row['close']),
                trading_value=int(trading_value)
            ))

        return events

    def filter_all_stocks(
        self,
        stocks: List[Dict[str, str]],
        daily_data: Dict[str, pd.DataFrame]
    ) -> Tuple[List[EventDay], pd.DataFrame]:
        """
        전체 종목 이벤트일 필터링

        Args:
            stocks: 종목 목록 [{"stock_code": "...", "stock_name": "..."}, ...]
            daily_data: 종목코드 -> 일봉 DataFrame 매핑

        Returns:
            (EventDay 리스트, 요약 DataFrame)
        """
        all_events = []
        summary_records = []

        for stock in stocks:
            stock_code = stock["stock_code"]
            stock_name = stock["stock_name"]

            if stock_code not in daily_data:
                continue

            daily_df = daily_data[stock_code]
            events = self.filter_event_days(stock_code, stock_name, daily_df)

            if events:
                all_events.extend(events)

                # 종목별 요약
                values = [e.trading_value for e in events]
                summary_records.append({
                    "stock_code": stock_code,
                    "stock_name": stock_name,
                    "event_count": len(events),
                    "first_event": min(e.date for e in events),
                    "last_event": max(e.date for e in events),
                    "max_value_billion": max(values) / 1_000_000_000,
                    "avg_value_billion": sum(values) / len(values) / 1_000_000_000,
                })

        # 날짜순 정렬
        all_events.sort(key=lambda e: (e.date, e.stock_code))

        # 요약 DataFrame
        summary_df = pd.DataFrame(summary_records)
        if len(summary_df) > 0:
            summary_df.sort_values("event_count", ascending=False, inplace=True)

        self.logger.info(
            f"Stage A 완료: {len(all_events)}개 이벤트일 "
            f"({len(summary_df)}개 종목, 거래대금 {self.config.min_trading_value/1e9:.0f}억 이상)"
        )

        return all_events, summary_df

    def save_event_days(self, events: List[EventDay], summary_df: pd.DataFrame):
        """이벤트일 CSV 저장"""
        # 이벤트 상세
        event_records = []
        for e in events:
            event_records.append({
                "date": e.date,
                "stock_code": e.stock_code,
                "stock_name": e.stock_name,
                "close": e.close,
                "trading_value": e.trading_value,
                "trading_value_billion": e.trading_value / 1_000_000_000
            })

        events_df = pd.DataFrame(event_records)
        events_df.to_csv(self.config.event_days_path, index=False, encoding="utf-8-sig")
        self.logger.info(f"이벤트일 저장: {self.config.event_days_path}")

        # 종목별 요약
        summary_path = self.config.output_dir / "event_summary.csv"
        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
        self.logger.info(f"이벤트 요약 저장: {summary_path}")

    def load_event_days(self) -> List[EventDay]:
        """저장된 이벤트일 로드"""
        if not self.config.event_days_path.exists():
            self.logger.warning(f"이벤트일 파일 없음: {self.config.event_days_path}")
            return []

        df = pd.read_csv(self.config.event_days_path, dtype={"stock_code": str})

        events = []
        for _, row in df.iterrows():
            events.append(EventDay(
                date=pd.to_datetime(row['date']).date(),
                stock_code=str(row['stock_code']).zfill(6),
                stock_name=row['stock_name'],
                close=int(row['close']),
                trading_value=int(row['trading_value'])
            ))

        self.logger.info(f"이벤트일 로드: {len(events)}개")
        return events

    def get_event_stats(self, events: List[EventDay]) -> Dict:
        """이벤트 통계 반환"""
        if not events:
            return {}

        # 날짜별 집계
        dates = set(e.date for e in events)
        stocks = set(e.stock_code for e in events)

        # 월별 분포
        monthly = {}
        for e in events:
            month_key = e.date.strftime("%Y-%m")
            monthly[month_key] = monthly.get(month_key, 0) + 1

        return {
            "total_events": len(events),
            "unique_dates": len(dates),
            "unique_stocks": len(stocks),
            "avg_events_per_date": len(events) / len(dates) if dates else 0,
            "monthly_distribution": monthly,
            "date_range": f"{min(dates)} ~ {max(dates)}" if dates else "N/A"
        }
