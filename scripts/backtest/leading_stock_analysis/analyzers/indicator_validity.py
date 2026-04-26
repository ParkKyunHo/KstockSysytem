# -*- coding: utf-8 -*-
"""
지표 유효성 분석
V6.2-Q

- EMA라인 이격도 분석
- 손절선(stop_loss_line) 유효성
- Lowest 지표 활용도
- ceiling_break 신호 유효성
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class IndicatorValidityResult:
    """지표 유효성 분석 결과"""
    ema_divergence: Dict               # EMA 이격도 분석
    stop_loss_validity: Dict           # 손절선 유효성
    lowest_analysis: Dict              # Lowest 지표 분석
    ceiling_break_validity: Dict       # 천장 돌파 신호 분석


class IndicatorValidityAnalyzer:
    """지표 유효성 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> IndicatorValidityResult:
        """지표 유효성 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            IndicatorValidityResult
        """
        if not event_days:
            return self._empty_result()

        # 1. EMA 이격도 분석
        ema_divergence = self._analyze_ema_divergence(event_days)

        # 2. 손절선 유효성
        stop_loss_validity = self._analyze_stop_loss(event_days)

        # 3. Lowest 지표 분석
        lowest_analysis = self._analyze_lowest(event_days)

        # 4. 천장 돌파 신호 분석
        ceiling_break_validity = self._analyze_ceiling_break(event_days)

        return IndicatorValidityResult(
            ema_divergence=ema_divergence,
            stop_loss_validity=stop_loss_validity,
            lowest_analysis=lowest_analysis,
            ceiling_break_validity=ceiling_break_validity,
        )

    def _analyze_ema_divergence(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """EMA 이격도 분석

        현재가와 EMA라인의 거리와 이후 수익률 관계

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            EMA 이격도 분석 딕셔너리
        """
        divergence_data = []

        for stock_name, date, df in event_days:
            if 'ema_line' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # 각 봉에서의 EMA 이격도 계산
            valid_ema = df[df['ema_line'] > 0].copy()
            if valid_ema.empty:
                continue

            valid_ema['ema_divergence'] = (valid_ema['close'] - valid_ema['ema_line']) / valid_ema['ema_line'] * 100

            # 장 시작 시 이격도
            start_divergence = valid_ema.iloc[0]['ema_divergence'] if len(valid_ema) > 0 else 0

            # 종가 수익률 (시가 대비)
            open_price = df.iloc[0]['open']
            close_price = df.iloc[-1]['close']
            realized_return = (close_price - open_price) / open_price * 100

            # 이격도 최대/최소
            max_divergence = valid_ema['ema_divergence'].max()
            min_divergence = valid_ema['ema_divergence'].min()

            divergence_data.append({
                'stock_name': stock_name,
                'date': date,
                'start_divergence': start_divergence,
                'max_divergence': max_divergence,
                'min_divergence': min_divergence,
                'avg_divergence': valid_ema['ema_divergence'].mean(),
                'realized_return': realized_return,
            })

        if not divergence_data:
            return {'raw_data': pd.DataFrame(), 'correlation': np.nan}

        divergence_df = pd.DataFrame(divergence_data)

        # 이격도 vs 수익률 상관관계
        correlation = divergence_df['start_divergence'].corr(divergence_df['realized_return'])

        # 이격도 구간별 분석
        divergence_df['divergence_bucket'] = pd.cut(
            divergence_df['start_divergence'],
            bins=[-np.inf, 0, 2, 5, 10, np.inf],
            labels=['< 0%', '0~2%', '2~5%', '5~10%', '> 10%']
        )

        bucket_stats = divergence_df.groupby('divergence_bucket', observed=True).agg({
            'realized_return': ['mean', 'std', 'count'],
        }).reset_index()

        bucket_stats.columns = ['divergence_bucket', 'avg_return', 'std_return', 'count']

        return {
            'raw_data': divergence_df,
            'correlation': correlation,
            'bucket_stats': bucket_stats,
        }

    def _analyze_stop_loss(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """손절선 유효성 분석

        손절선 터치 후 반등 vs 추가 하락 비율

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            손절선 분석 딕셔너리
        """
        stop_loss_data = []

        for stock_name, date, df in event_days:
            if 'stop_loss_line' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # 손절선 터치 감지 (저가 <= 손절선)
            valid_sl = df[df['stop_loss_line'] > 0].copy()
            if valid_sl.empty:
                continue

            valid_sl['sl_touched'] = valid_sl['low'] <= valid_sl['stop_loss_line']

            if not valid_sl['sl_touched'].any():
                # 손절선 터치 안 함 → 성공적인 상승
                stop_loss_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'sl_touched': False,
                    'touch_count': 0,
                    'result': 'no_touch',
                    'return_after_touch': np.nan,
                })
                continue

            # 첫 터치 시점
            first_touch_idx = valid_sl['sl_touched'].idxmax()
            touch_price = valid_sl.loc[first_touch_idx, 'low']
            touch_time = valid_sl.loc[first_touch_idx, 'datetime']

            # 터치 후 데이터
            after_touch = df[df['datetime'] > touch_time]
            if after_touch.empty:
                continue

            # 터치 후 최고가/최저가
            max_after = after_touch['high'].max()
            min_after = after_touch['low'].min()
            close_price = df.iloc[-1]['close']

            # 반등 vs 추가 하락 판단
            rebound = (max_after - touch_price) / touch_price * 100
            further_drop = (min_after - touch_price) / touch_price * 100

            if rebound > 3 and further_drop > -2:
                result = 'strong_rebound'
            elif rebound > 1:
                result = 'weak_rebound'
            elif further_drop < -3:
                result = 'further_drop'
            else:
                result = 'sideways'

            stop_loss_data.append({
                'stock_name': stock_name,
                'date': date,
                'sl_touched': True,
                'touch_count': valid_sl['sl_touched'].sum(),
                'touch_time': touch_time.strftime('%H:%M'),
                'result': result,
                'rebound': rebound,
                'further_drop': further_drop,
                'return_to_close': (close_price - touch_price) / touch_price * 100,
            })

        if not stop_loss_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        sl_df = pd.DataFrame(stop_loss_data)

        # 결과별 통계
        result_stats = sl_df.groupby('result').size().reset_index(name='count')
        result_stats['frequency'] = result_stats['count'] / len(sl_df) * 100

        # 손절선 터치율
        touch_rate = sl_df['sl_touched'].mean() * 100

        summary = {
            'touch_rate': touch_rate,
            'no_touch_count': len(sl_df[~sl_df['sl_touched']]),
            'touched_count': len(sl_df[sl_df['sl_touched']]),
        }

        return {
            'raw_data': sl_df,
            'result_stats': result_stats,
            'summary': summary,
        }

    def _analyze_lowest(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """Lowest 지표 분석

        Lowest 근처 진입 시 수익률

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            Lowest 분석 딕셔너리
        """
        lowest_data = []

        for stock_name, date, df in event_days:
            if 'lowest' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # Lowest 값이 있는 봉
            valid_lowest = df[df['lowest'] > 0].copy()
            if valid_lowest.empty:
                continue

            # Lowest 터치 감지 (저가 <= Lowest * 1.01)
            valid_lowest['near_lowest'] = valid_lowest['low'] <= valid_lowest['lowest'] * 1.01

            if not valid_lowest['near_lowest'].any():
                continue

            # 첫 터치 시점
            first_touch_idx = valid_lowest['near_lowest'].idxmax()
            touch_price = valid_lowest.loc[first_touch_idx, 'close']
            touch_time = valid_lowest.loc[first_touch_idx, 'datetime']

            # 터치 후 수익률
            after_touch = df[df['datetime'] > touch_time]
            if after_touch.empty:
                continue

            close_price = df.iloc[-1]['close']
            max_after = after_touch['high'].max()

            # MFE 계산
            mfe = (max_after - touch_price) / touch_price * 100
            realized = (close_price - touch_price) / touch_price * 100

            lowest_data.append({
                'stock_name': stock_name,
                'date': date,
                'touch_time': touch_time.strftime('%H:%M'),
                'touch_price': touch_price,
                'lowest_value': valid_lowest.loc[first_touch_idx, 'lowest'],
                'mfe': mfe,
                'realized_return': realized,
            })

        if not lowest_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        lowest_df = pd.DataFrame(lowest_data)

        summary = {
            'avg_mfe': lowest_df['mfe'].mean(),
            'avg_realized': lowest_df['realized_return'].mean(),
            'win_rate': (lowest_df['realized_return'] > 0).mean() * 100,
            'sample_count': len(lowest_df),
        }

        return {
            'raw_data': lowest_df,
            'summary': summary,
        }

    def _analyze_ceiling_break(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """천장 돌파 신호 분석

        ceiling_break 신호 발생 후 수익률

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            천장 돌파 분석 딕셔너리
        """
        ceiling_data = []

        for stock_name, date, df in event_days:
            if 'ceiling_break' not in df.columns or df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # ceiling_break 신호 감지 (값 > 0)
            df['has_signal'] = df['ceiling_break'] > 0

            if not df['has_signal'].any():
                continue

            # 첫 신호 시점
            first_signal_idx = df['has_signal'].idxmax()
            signal_price = df.loc[first_signal_idx, 'close']
            signal_time = df.loc[first_signal_idx, 'datetime']

            # 신호 후 데이터
            after_signal = df[df['datetime'] > signal_time]
            if after_signal.empty:
                close_price = signal_price
            else:
                close_price = df.iloc[-1]['close']

            # 수익률 계산
            return_5m = np.nan
            return_15m = np.nan
            return_30m = np.nan

            for minutes, col_name in [(5, 'return_5m'), (15, 'return_15m'), (30, 'return_30m')]:
                target_time = signal_time + pd.Timedelta(minutes=minutes)
                future = df[df['datetime'] >= target_time]
                if not future.empty:
                    future_price = future.iloc[0]['close']
                    ret = (future_price - signal_price) / signal_price * 100
                    if col_name == 'return_5m':
                        return_5m = ret
                    elif col_name == 'return_15m':
                        return_15m = ret
                    else:
                        return_30m = ret

            realized = (close_price - signal_price) / signal_price * 100

            ceiling_data.append({
                'stock_name': stock_name,
                'date': date,
                'signal_time': signal_time.strftime('%H:%M'),
                'signal_hour': signal_time.hour,
                'signal_price': signal_price,
                'return_5m': return_5m,
                'return_15m': return_15m,
                'return_30m': return_30m,
                'return_to_close': realized,
            })

        if not ceiling_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        ceiling_df = pd.DataFrame(ceiling_data)

        # 각 기간별 통계
        summary = {
            '5m': {
                'mean': ceiling_df['return_5m'].mean(),
                'median': ceiling_df['return_5m'].median(),
                'win_rate': (ceiling_df['return_5m'] > 0).mean() * 100,
            },
            '15m': {
                'mean': ceiling_df['return_15m'].mean(),
                'median': ceiling_df['return_15m'].median(),
                'win_rate': (ceiling_df['return_15m'] > 0).mean() * 100,
            },
            '30m': {
                'mean': ceiling_df['return_30m'].mean(),
                'median': ceiling_df['return_30m'].median(),
                'win_rate': (ceiling_df['return_30m'] > 0).mean() * 100,
            },
            'to_close': {
                'mean': ceiling_df['return_to_close'].mean(),
                'median': ceiling_df['return_to_close'].median(),
                'win_rate': (ceiling_df['return_to_close'] > 0).mean() * 100,
            },
            'sample_count': len(ceiling_df),
        }

        return {
            'raw_data': ceiling_df,
            'summary': summary,
        }

    def _empty_result(self) -> IndicatorValidityResult:
        """빈 결과 반환"""
        return IndicatorValidityResult(
            ema_divergence={'raw_data': pd.DataFrame(), 'correlation': np.nan},
            stop_loss_validity={'raw_data': pd.DataFrame(), 'summary': {}},
            lowest_analysis={'raw_data': pd.DataFrame(), 'summary': {}},
            ceiling_break_validity={'raw_data': pd.DataFrame(), 'summary': {}},
        )
