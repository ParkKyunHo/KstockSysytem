# -*- coding: utf-8 -*-
"""
BandHigh/Low 돌파 패턴 분석
V6.2-Q

- 첫 BandHigh 돌파 시점
- 돌파 후 N분 수익률
- 돌파 후 장 마감 수익률
- BandLow 이탈 패턴
- 돌파 강도와 수익률 상관관계
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class BandBreakoutResult:
    """밴드 돌파 분석 결과"""
    first_breakout_stats: pd.DataFrame    # 첫 돌파 시점 통계
    post_breakout_returns: pd.DataFrame   # 돌파 후 수익률
    breakout_to_close: pd.DataFrame       # 돌파 → 종가 수익률
    bandlow_analysis: pd.DataFrame        # BandLow 이탈 분석
    strength_correlation: Dict            # 돌파 강도 vs 수익률 상관


class BandBreakoutAnalyzer:
    """밴드 돌파 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> BandBreakoutResult:
        """밴드 돌파 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            BandBreakoutResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 첫 BandHigh 돌파 시점 분석
        first_breakout_stats = self._analyze_first_breakout(event_days)

        # 2. 돌파 후 N분 수익률
        post_breakout_returns = self._analyze_post_breakout_returns(event_days)

        # 3. 돌파 → 종가 수익률
        breakout_to_close = self._analyze_breakout_to_close(event_days)

        # 4. BandLow 이탈 분석
        bandlow_analysis = self._analyze_bandlow_breach(event_days)

        # 5. 돌파 강도 vs 수익률 상관관계
        strength_correlation = self._analyze_strength_correlation(event_days)

        return BandBreakoutResult(
            first_breakout_stats=first_breakout_stats,
            post_breakout_returns=post_breakout_returns,
            breakout_to_close=breakout_to_close,
            bandlow_analysis=bandlow_analysis,
            strength_correlation=strength_correlation,
        )

    def _analyze_first_breakout(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """첫 BandHigh 돌파 시점 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            첫 돌파 시점 통계 DataFrame
        """
        breakout_data = []

        for stock_name, date, df in event_days:
            if 'band_high' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # BandHigh 돌파 감지 (close > band_high)
            df['breakout'] = df['close'] > df['band_high']

            # 첫 돌파 찾기
            breakout_mask = df['breakout']
            if not breakout_mask.any():
                continue

            first_breakout_idx = breakout_mask.idxmax()
            first_breakout_row = df.loc[first_breakout_idx]

            # 장 시작 시간 기준 경과 시간 (분)
            market_open = df['datetime'].min()
            breakout_time = first_breakout_row['datetime']
            minutes_from_open = (breakout_time - market_open).total_seconds() / 60

            # 돌파 강도 (돌파 가격 / BandHigh - 1)
            breakout_strength = (first_breakout_row['close'] - first_breakout_row['band_high']) / first_breakout_row['band_high'] * 100

            breakout_data.append({
                'stock_name': stock_name,
                'date': date,
                'breakout_time': breakout_time.strftime('%H:%M'),
                'breakout_hour': breakout_time.hour,
                'minutes_from_open': minutes_from_open,
                'breakout_price': first_breakout_row['close'],
                'band_high': first_breakout_row['band_high'],
                'breakout_strength': breakout_strength,
            })

        if not breakout_data:
            return pd.DataFrame()

        breakout_df = pd.DataFrame(breakout_data)

        # 통계 요약
        summary_stats = {
            'total_events': len(breakout_df),
            'avg_minutes_from_open': breakout_df['minutes_from_open'].mean(),
            'median_minutes_from_open': breakout_df['minutes_from_open'].median(),
            'std_minutes_from_open': breakout_df['minutes_from_open'].std(),
            'avg_breakout_strength': breakout_df['breakout_strength'].mean(),
        }

        # 시간대별 분포
        hourly_dist = breakout_df.groupby('breakout_hour').size().reset_index(name='count')
        hourly_dist['frequency'] = hourly_dist['count'] / len(breakout_df) * 100

        return {
            'raw_data': breakout_df,
            'summary': pd.DataFrame([summary_stats]),
            'hourly_distribution': hourly_dist,
        }

    def _analyze_post_breakout_returns(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """돌파 후 N분 수익률 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            돌파 후 수익률 DataFrame
        """
        return_periods = [5, 15, 30, 60, 120]  # 분
        returns_data = []

        for stock_name, date, df in event_days:
            if 'band_high' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # BandHigh 돌파 감지
            df['breakout'] = df['close'] > df['band_high']

            if not df['breakout'].any():
                continue

            first_breakout_idx = df['breakout'].idxmax()
            breakout_price = df.loc[first_breakout_idx, 'close']
            breakout_time = df.loc[first_breakout_idx, 'datetime']

            entry = {
                'stock_name': stock_name,
                'date': date,
                'breakout_price': breakout_price,
            }

            # 각 기간별 수익률 계산
            for minutes in return_periods:
                target_time = breakout_time + pd.Timedelta(minutes=minutes)
                future_df = df[df['datetime'] >= target_time]

                if future_df.empty:
                    entry[f'return_{minutes}m'] = np.nan
                else:
                    future_price = future_df.iloc[0]['close']
                    ret = (future_price - breakout_price) / breakout_price * 100
                    entry[f'return_{minutes}m'] = ret

            returns_data.append(entry)

        if not returns_data:
            return pd.DataFrame()

        returns_df = pd.DataFrame(returns_data)

        # 기간별 통계 요약
        summary = {}
        for minutes in return_periods:
            col = f'return_{minutes}m'
            valid = returns_df[col].dropna()
            if len(valid) > 0:
                summary[f'{minutes}m'] = {
                    'mean': valid.mean(),
                    'median': valid.median(),
                    'std': valid.std(),
                    'win_rate': (valid > 0).mean() * 100,
                    'count': len(valid),
                }

        return {
            'raw_data': returns_df,
            'summary': pd.DataFrame(summary).T,
        }

    def _analyze_breakout_to_close(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """돌파 시점 → 종가 수익률 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            돌파→종가 수익률 DataFrame
        """
        close_data = []

        for stock_name, date, df in event_days:
            if 'band_high' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # BandHigh 돌파 감지
            df['breakout'] = df['close'] > df['band_high']

            if not df['breakout'].any():
                continue

            first_breakout_idx = df['breakout'].idxmax()
            breakout_price = df.loc[first_breakout_idx, 'close']
            close_price = df.iloc[-1]['close']

            ret = (close_price - breakout_price) / breakout_price * 100

            close_data.append({
                'stock_name': stock_name,
                'date': date,
                'breakout_price': breakout_price,
                'close_price': close_price,
                'return_to_close': ret,
            })

        if not close_data:
            return pd.DataFrame()

        close_df = pd.DataFrame(close_data)

        summary = {
            'mean': close_df['return_to_close'].mean(),
            'median': close_df['return_to_close'].median(),
            'std': close_df['return_to_close'].std(),
            'win_rate': (close_df['return_to_close'] > 0).mean() * 100,
            'max': close_df['return_to_close'].max(),
            'min': close_df['return_to_close'].min(),
        }

        return {
            'raw_data': close_df,
            'summary': pd.DataFrame([summary]),
        }

    def _analyze_bandlow_breach(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """BandLow 이탈 후 패턴 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            BandLow 이탈 분석 DataFrame
        """
        breach_data = []

        for stock_name, date, df in event_days:
            if 'band_low' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # BandLow 이탈 감지 (close < band_low)
            df['breach'] = df['close'] < df['band_low']

            if not df['breach'].any():
                continue

            # 첫 이탈 이후 분석
            first_breach_idx = df['breach'].idxmax()
            breach_price = df.loc[first_breach_idx, 'close']
            close_price = df.iloc[-1]['close']

            # 이탈 후 반등 여부
            after_breach = df.iloc[first_breach_idx:]
            min_after = after_breach['low'].min()
            max_after = after_breach['high'].max()

            # 반등 vs 추가 하락 분류
            if max_after > breach_price * 1.02:  # 2% 이상 반등
                pattern = 'rebound'
            elif min_after < breach_price * 0.98:  # 2% 이상 추가 하락
                pattern = 'further_drop'
            else:
                pattern = 'consolidation'

            breach_data.append({
                'stock_name': stock_name,
                'date': date,
                'breach_price': breach_price,
                'close_price': close_price,
                'min_after_breach': min_after,
                'max_after_breach': max_after,
                'pattern': pattern,
                'return_to_close': (close_price - breach_price) / breach_price * 100,
            })

        if not breach_data:
            return pd.DataFrame()

        breach_df = pd.DataFrame(breach_data)

        # 패턴별 통계
        pattern_stats = breach_df.groupby('pattern').agg({
            'stock_name': 'count',
            'return_to_close': ['mean', 'std'],
        }).reset_index()

        pattern_stats.columns = ['pattern', 'count', 'avg_return', 'std_return']
        pattern_stats['frequency'] = pattern_stats['count'] / len(breach_df) * 100

        return {
            'raw_data': breach_df,
            'pattern_stats': pattern_stats,
        }

    def _analyze_strength_correlation(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """돌파 강도 vs 수익률 상관관계 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            상관관계 분석 딕셔너리
        """
        corr_data = []

        for stock_name, date, df in event_days:
            if 'band_high' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # BandHigh 돌파 감지
            df['breakout'] = df['close'] > df['band_high']

            if not df['breakout'].any():
                continue

            first_breakout_idx = df['breakout'].idxmax()
            breakout_row = df.loc[first_breakout_idx]
            breakout_price = breakout_row['close']
            close_price = df.iloc[-1]['close']

            # 돌파 강도 (%)
            strength = (breakout_price - breakout_row['band_high']) / breakout_row['band_high'] * 100

            # 종가 수익률
            ret = (close_price - breakout_price) / breakout_price * 100

            corr_data.append({
                'breakout_strength': strength,
                'return_to_close': ret,
            })

        if not corr_data:
            return {'correlation': np.nan, 'data': pd.DataFrame()}

        corr_df = pd.DataFrame(corr_data)

        # 상관계수 계산
        correlation = corr_df['breakout_strength'].corr(corr_df['return_to_close'])

        # 강도별 그룹 분석
        corr_df['strength_group'] = pd.cut(
            corr_df['breakout_strength'],
            bins=[-np.inf, 0.5, 1.0, 2.0, np.inf],
            labels=['weak (<0.5%)', 'medium (0.5-1%)', 'strong (1-2%)', 'very_strong (>2%)']
        )

        group_stats = corr_df.groupby('strength_group', observed=True).agg({
            'return_to_close': ['mean', 'std', 'count'],
        }).reset_index()

        group_stats.columns = ['strength_group', 'avg_return', 'std_return', 'count']

        return {
            'correlation': correlation,
            'group_stats': group_stats,
            'raw_data': corr_df,
        }

    def _empty_result(self) -> BandBreakoutResult:
        """빈 결과 반환"""
        return BandBreakoutResult(
            first_breakout_stats=pd.DataFrame(),
            post_breakout_returns=pd.DataFrame(),
            breakout_to_close=pd.DataFrame(),
            bandlow_analysis=pd.DataFrame(),
            strength_correlation={'correlation': np.nan, 'data': pd.DataFrame()},
        )
