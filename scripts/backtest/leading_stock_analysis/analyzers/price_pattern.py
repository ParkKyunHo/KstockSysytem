# -*- coding: utf-8 -*-
"""
가격 패턴 분석
V6.2-Q

- 시가 대비 고가/저가 도달 시점
- 고점 → 종가 하락폭
- 갭 상승 후 패턴
- MFE/MAE 분포
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class PricePatternResult:
    """가격 패턴 분석 결과"""
    high_low_timing: pd.DataFrame     # 고가/저가 도달 시점
    high_to_close: pd.DataFrame       # 고점→종가 하락폭
    gap_patterns: pd.DataFrame        # 갭 상승 패턴
    mfe_mae: pd.DataFrame             # MFE/MAE 분포


class PricePatternAnalyzer:
    """가격 패턴 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> PricePatternResult:
        """가격 패턴 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            PricePatternResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 고가/저가 도달 시점 분석
        high_low_timing = self._analyze_high_low_timing(event_days)

        # 2. 고점 → 종가 하락폭
        high_to_close = self._analyze_high_to_close(event_days)

        # 3. 갭 상승 패턴
        gap_patterns = self._analyze_gap_patterns(event_days)

        # 4. MFE/MAE 분포
        mfe_mae = self._analyze_mfe_mae(event_days)

        return PricePatternResult(
            high_low_timing=high_low_timing,
            high_to_close=high_to_close,
            gap_patterns=gap_patterns,
            mfe_mae=mfe_mae,
        )

    def _analyze_high_low_timing(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """고가/저가 도달 시점 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            고가/저가 시점 분석 딕셔너리
        """
        timing_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # 일중 최고가/최저가 시점
            high_idx = df['high'].idxmax()
            low_idx = df['low'].idxmin()

            high_time = df.loc[high_idx, 'datetime']
            low_time = df.loc[low_idx, 'datetime']
            market_open = df['datetime'].min()

            # 장 시작 후 경과 시간 (분)
            high_minutes = (high_time - market_open).total_seconds() / 60
            low_minutes = (low_time - market_open).total_seconds() / 60

            # 시가 대비 수익률
            open_price = df.iloc[0]['open']
            high_price = df.loc[high_idx, 'high']
            low_price = df.loc[low_idx, 'low']

            timing_data.append({
                'stock_name': stock_name,
                'date': date,
                'high_time': high_time.strftime('%H:%M'),
                'high_hour': high_time.hour,
                'high_minutes_from_open': high_minutes,
                'low_time': low_time.strftime('%H:%M'),
                'low_hour': low_time.hour,
                'low_minutes_from_open': low_minutes,
                'open_to_high': (high_price - open_price) / open_price * 100,
                'open_to_low': (low_price - open_price) / open_price * 100,
                'high_first': high_minutes < low_minutes,  # 고가가 먼저 형성되었는지
            })

        if not timing_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        timing_df = pd.DataFrame(timing_data)

        # 통계 요약
        summary = {
            'high_timing': {
                'avg_minutes': timing_df['high_minutes_from_open'].mean(),
                'median_minutes': timing_df['high_minutes_from_open'].median(),
                'std_minutes': timing_df['high_minutes_from_open'].std(),
            },
            'low_timing': {
                'avg_minutes': timing_df['low_minutes_from_open'].mean(),
                'median_minutes': timing_df['low_minutes_from_open'].median(),
                'std_minutes': timing_df['low_minutes_from_open'].std(),
            },
            'high_first_ratio': timing_df['high_first'].mean() * 100,
        }

        # 시간대별 고가 형성 분포
        high_hour_dist = timing_df.groupby('high_hour').size().reset_index(name='count')
        high_hour_dist['frequency'] = high_hour_dist['count'] / len(timing_df) * 100

        return {
            'raw_data': timing_df,
            'summary': summary,
            'high_hour_distribution': high_hour_dist,
        }

    def _analyze_high_to_close(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """고점 → 종가 하락폭 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            고점→종가 분석 딕셔너리
        """
        drawdown_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # 일중 최고가
            day_high = df['high'].max()
            close_price = df.iloc[-1]['close']
            open_price = df.iloc[0]['open']

            # 고점 대비 종가 하락률
            high_to_close_drop = (close_price - day_high) / day_high * 100

            # 고점 대비 종가 유지율 (고점에서 얼마나 빠졌나)
            retention_rate = close_price / day_high * 100

            drawdown_data.append({
                'stock_name': stock_name,
                'date': date,
                'open_price': open_price,
                'day_high': day_high,
                'close_price': close_price,
                'high_to_close_drop': high_to_close_drop,
                'retention_rate': retention_rate,
                'open_to_high': (day_high - open_price) / open_price * 100,
                'open_to_close': (close_price - open_price) / open_price * 100,
            })

        if not drawdown_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        drawdown_df = pd.DataFrame(drawdown_data)

        # 통계 요약
        summary = {
            'avg_high_to_close_drop': drawdown_df['high_to_close_drop'].mean(),
            'median_high_to_close_drop': drawdown_df['high_to_close_drop'].median(),
            'std_high_to_close_drop': drawdown_df['high_to_close_drop'].std(),
            'avg_retention_rate': drawdown_df['retention_rate'].mean(),
            'avg_open_to_high': drawdown_df['open_to_high'].mean(),
            'close_above_open_ratio': (drawdown_df['open_to_close'] > 0).mean() * 100,
        }

        # 하락폭 분포
        drawdown_df['drop_bucket'] = pd.cut(
            drawdown_df['high_to_close_drop'],
            bins=[-np.inf, -10, -5, -3, -1, 0, np.inf],
            labels=['< -10%', '-10~-5%', '-5~-3%', '-3~-1%', '-1~0%', '> 0%']
        )

        bucket_dist = drawdown_df.groupby('drop_bucket', observed=True).size().reset_index(name='count')
        bucket_dist['frequency'] = bucket_dist['count'] / len(drawdown_df) * 100

        return {
            'raw_data': drawdown_df,
            'summary': summary,
            'bucket_distribution': bucket_dist,
        }

    def _analyze_gap_patterns(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """갭 상승 후 패턴 분석

        갭 상승: 시가 > 전일 종가 (3% 이상)
        패턴:
        - gap_and_go: 갭 상승 후 추가 상승
        - gap_fill: 갭 메우기 (시가 아래로 하락)
        - consolidation: 횡보

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            갭 패턴 분석 딕셔너리
        """
        gap_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            open_price = df.iloc[0]['open']
            close_price = df.iloc[-1]['close']
            day_high = df['high'].max()
            day_low = df['low'].min()

            # 갭 비율 계산 (시가 대비가 아닌, 이전 종가 필요하지만 없으므로 일단 스킵)
            # 대신 시가 대비 등락률로 패턴 분류

            open_to_close = (close_price - open_price) / open_price * 100
            open_to_low = (day_low - open_price) / open_price * 100

            # 패턴 분류
            if open_to_close > 3 and open_to_low > -2:
                pattern = 'gap_and_go'  # 추가 상승, 하락 제한적
            elif open_to_low < -3:
                pattern = 'gap_fill'    # 시가 대비 큰 하락 (갭 메우기)
            else:
                pattern = 'consolidation'  # 횡보

            gap_data.append({
                'stock_name': stock_name,
                'date': date,
                'open_price': open_price,
                'close_price': close_price,
                'day_high': day_high,
                'day_low': day_low,
                'open_to_close': open_to_close,
                'open_to_high': (day_high - open_price) / open_price * 100,
                'open_to_low': open_to_low,
                'pattern': pattern,
            })

        if not gap_data:
            return {'raw_data': pd.DataFrame(), 'pattern_stats': pd.DataFrame()}

        gap_df = pd.DataFrame(gap_data)

        # 패턴별 통계
        pattern_stats = gap_df.groupby('pattern').agg({
            'stock_name': 'count',
            'open_to_close': ['mean', 'std'],
            'open_to_high': 'mean',
            'open_to_low': 'mean',
        }).reset_index()

        pattern_stats.columns = [
            'pattern', 'count', 'avg_return', 'std_return',
            'avg_to_high', 'avg_to_low'
        ]
        pattern_stats['frequency'] = pattern_stats['count'] / len(gap_df) * 100

        return {
            'raw_data': gap_df,
            'pattern_stats': pattern_stats,
        }

    def _analyze_mfe_mae(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """MFE/MAE (Maximum Favorable/Adverse Excursion) 분석

        시가 기준:
        - MFE: 최대 유리 진행 (시가 → 고가)
        - MAE: 최대 불리 진행 (시가 → 저가)

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            MFE/MAE 분석 딕셔너리
        """
        mfe_mae_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            open_price = df.iloc[0]['open']
            close_price = df.iloc[-1]['close']

            # MFE: 시가 대비 최대 상승 (고점까지)
            mfe = (df['high'].max() - open_price) / open_price * 100

            # MAE: 시가 대비 최대 하락 (저점까지)
            mae = (df['low'].min() - open_price) / open_price * 100

            # 실현 수익률
            realized_return = (close_price - open_price) / open_price * 100

            # 효율성 (실현 수익률 / MFE)
            efficiency = realized_return / mfe * 100 if mfe > 0 else 0

            mfe_mae_data.append({
                'stock_name': stock_name,
                'date': date,
                'mfe': mfe,
                'mae': mae,
                'realized_return': realized_return,
                'efficiency': efficiency,
                'range': mfe - mae,  # 일중 진폭
            })

        if not mfe_mae_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        mfe_mae_df = pd.DataFrame(mfe_mae_data)

        # 통계 요약
        summary = {
            'mfe': {
                'mean': mfe_mae_df['mfe'].mean(),
                'median': mfe_mae_df['mfe'].median(),
                'std': mfe_mae_df['mfe'].std(),
                'max': mfe_mae_df['mfe'].max(),
            },
            'mae': {
                'mean': mfe_mae_df['mae'].mean(),
                'median': mfe_mae_df['mae'].median(),
                'std': mfe_mae_df['mae'].std(),
                'min': mfe_mae_df['mae'].min(),
            },
            'efficiency': {
                'mean': mfe_mae_df['efficiency'].mean(),
                'median': mfe_mae_df['efficiency'].median(),
            },
            'realized_return': {
                'mean': mfe_mae_df['realized_return'].mean(),
                'median': mfe_mae_df['realized_return'].median(),
                'win_rate': (mfe_mae_df['realized_return'] > 0).mean() * 100,
            },
        }

        return {
            'raw_data': mfe_mae_df,
            'summary': summary,
        }

    def _empty_result(self) -> PricePatternResult:
        """빈 결과 반환"""
        return PricePatternResult(
            high_low_timing=pd.DataFrame(),
            high_to_close=pd.DataFrame(),
            gap_patterns=pd.DataFrame(),
            mfe_mae=pd.DataFrame(),
        )
