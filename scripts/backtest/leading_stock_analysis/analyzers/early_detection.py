# -*- coding: utf-8 -*-
"""
조기 탐지 분석기
V6.2-Q

장 시작 첫 15분(09:00~09:15) 데이터로 이벤트일 예측 가능성 분석

핵심 질문:
- 첫 15분에 어떤 특성이 이벤트일을 구분하는가?
- 실시간 탐지에 사용할 수 있는 최적 규칙은?
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import logging
from datetime import time as dt_time

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class EarlyDetectionResult:
    """조기 탐지 분석 결과"""
    early_features: pd.DataFrame          # 전체 날짜별 첫 15분 지표
    event_vs_normal_stats: pd.DataFrame   # 이벤트일 vs 비이벤트일 비교
    detection_rules_accuracy: pd.DataFrame  # 각 규칙별 정확도
    optimal_rules: pd.DataFrame           # 최적 탐지 규칙
    summary: Dict = field(default_factory=dict)


class EarlyDetectionAnalyzer:
    """장 시작 첫 15분 데이터로 이벤트일 조기 탐지 분석"""

    def __init__(
        self,
        config: AnalysisConfig = None,
        detection_window_minutes: int = 15,
        min_trading_value: float = 50.0,    # 이벤트 조건: 50억+
        min_change_rate: float = 3.0,       # 이벤트 조건: 3%+
    ):
        """
        Args:
            config: 분석 설정
            detection_window_minutes: 탐지 윈도우 (기본 15분)
            min_trading_value: 이벤트 최소 거래대금 (억원)
            min_change_rate: 이벤트 최소 등락률 (%)
        """
        self.config = config or DEFAULT_CONFIG
        self.window_minutes = detection_window_minutes
        self.min_trading_value = min_trading_value
        self.min_change_rate = min_change_rate

        # 첫 15분 = 09:00~09:15 (3분봉 5개)
        self.window_start = dt_time(9, 0, 0)
        self.window_end = dt_time(9, 15, 0)

    def analyze(
        self,
        data_dict: Dict[str, pd.DataFrame],
        daily_df: pd.DataFrame,
        events_df: pd.DataFrame,
    ) -> EarlyDetectionResult:
        """전체 분석 실행

        Args:
            data_dict: {종목명: 3분봉 DataFrame} 딕셔너리
            daily_df: 전체 일봉 DataFrame
            events_df: 이벤트일 일봉 DataFrame

        Returns:
            EarlyDetectionResult
        """
        logger.info("Starting early detection analysis...")

        # 1. 모든 날짜의 첫 15분 지표 추출
        early_features = self._extract_all_early_features(data_dict, daily_df, events_df)
        if early_features.empty:
            return self._empty_result()

        logger.info(f"Extracted early features for {len(early_features)} days")

        # 2. 이벤트일 vs 비이벤트일 비교
        event_vs_normal = self._compare_event_vs_normal(early_features)

        # 3. 탐지 규칙 테스트
        rules_accuracy = self._test_detection_rules(early_features)

        # 4. 최적 규칙 탐색
        optimal_rules = self._find_optimal_rules(early_features)

        # 5. 요약 통계
        summary = self._generate_summary(early_features, event_vs_normal, rules_accuracy)

        return EarlyDetectionResult(
            early_features=early_features,
            event_vs_normal_stats=event_vs_normal,
            detection_rules_accuracy=rules_accuracy,
            optimal_rules=optimal_rules,
            summary=summary,
        )

    def _extract_all_early_features(
        self,
        data_dict: Dict[str, pd.DataFrame],
        daily_df: pd.DataFrame,
        events_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """모든 날짜의 첫 15분 지표 추출

        Args:
            data_dict: 3분봉 데이터
            daily_df: 일봉 데이터
            events_df: 이벤트 데이터

        Returns:
            첫 15분 지표 DataFrame
        """
        # 이벤트일 집합 생성
        event_set = set()
        for _, row in events_df.iterrows():
            event_set.add((row['stock_name'], str(row['date'])))

        all_features = []

        for stock_name, df in data_dict.items():
            if df.empty:
                continue

            # 해당 종목의 일봉 데이터
            stock_daily = daily_df[daily_df['stock_name'] == stock_name].copy()
            if stock_daily.empty:
                continue

            # 각 날짜별 처리
            for date_only in df['date_only'].unique():
                # 첫 15분 데이터 필터링
                day_df = df[df['date_only'] == date_only].copy()
                early_df = self._filter_early_window(day_df)

                if early_df.empty or len(early_df) < 2:
                    continue

                # 해당 날짜 일봉 정보
                daily_row = stock_daily[stock_daily['date'] == date_only]
                if daily_row.empty:
                    continue

                daily_info = daily_row.iloc[0]

                # 전일 종가 (전일 데이터에서 가져오기)
                prev_close = daily_info.get('prev_close', None)
                if pd.isna(prev_close) or prev_close is None or prev_close <= 0:
                    continue

                # 이벤트 여부 확인
                is_event = (stock_name, str(date_only)) in event_set

                # 지표 추출
                features = self._extract_features_from_window(
                    early_df=early_df,
                    day_df=day_df,
                    prev_close=prev_close,
                    daily_info=daily_info,
                )

                if features:
                    features['stock_name'] = stock_name
                    features['date'] = date_only
                    features['is_event'] = is_event
                    features['daily_change_rate'] = daily_info['change_rate']
                    features['daily_trading_value'] = daily_info['trading_value']
                    all_features.append(features)

        if not all_features:
            return pd.DataFrame()

        return pd.DataFrame(all_features)

    def _filter_early_window(self, day_df: pd.DataFrame) -> pd.DataFrame:
        """첫 15분 윈도우 데이터 필터링"""
        if 'time_only' not in day_df.columns:
            day_df = day_df.copy()
            day_df['time_only'] = day_df['datetime'].dt.time

        mask = (
            (day_df['time_only'] >= self.window_start) &
            (day_df['time_only'] < self.window_end)
        )
        return day_df[mask].copy()

    def _extract_features_from_window(
        self,
        early_df: pd.DataFrame,
        day_df: pd.DataFrame,
        prev_close: float,
        daily_info: pd.Series,
    ) -> Optional[Dict]:
        """첫 15분 데이터에서 지표 추출

        Args:
            early_df: 첫 15분 데이터
            day_df: 해당일 전체 데이터
            prev_close: 전일 종가
            daily_info: 일봉 정보

        Returns:
            지표 딕셔너리
        """
        try:
            # 기본 가격 정보
            first_bar = early_df.iloc[0]
            last_bar = early_df.iloc[-1]

            open_price = first_bar['open']
            high_price = early_df['high'].max()
            low_price = early_df['low'].min()
            close_price = last_bar['close']

            # === 핵심 지표 계산 ===

            # 1. 시가 갭 (전일 종가 대비)
            open_gap = (open_price - prev_close) / prev_close * 100

            # 2. 첫 15분 거래대금
            early_trading_value = early_df['trading_value'].sum()

            # 3. 첫 15분 등락률 (시가 대비)
            early_change_rate = (close_price - open_price) / open_price * 100

            # 4. 첫 15분 변동성
            early_volatility = (high_price - low_price) / open_price * 100

            # 5. BandHigh 돌파 여부
            band_high_break = False
            if 'band_high' in early_df.columns:
                band_high = first_bar.get('band_high', None)
                if band_high and not pd.isna(band_high) and band_high > 0:
                    band_high_break = high_price > band_high

            # 6. 거래량 급증도 (전일 평균 대비)
            # 전일 데이터로 평균 거래대금 계산 (없으면 당일 후반부 사용)
            daily_total = daily_info['trading_value']
            # 전체 봉 수 (130봉 가정, 6.5시간 * 20봉/시간)
            avg_bar_value = daily_total / 130 if daily_total > 0 else 1
            early_avg_value = early_trading_value / len(early_df)
            volume_surge_ratio = early_avg_value / avg_bar_value if avg_bar_value > 0 else 1

            # 7. 양봉 여부 (마지막 봉 기준)
            is_bullish = close_price > open_price

            # 8. 고가 위치 (첫 15분 내 고가가 몇 번째 봉에서 발생했는지)
            high_bar_idx = early_df['high'].idxmax()
            high_bar_position = (
                early_df.index.get_loc(high_bar_idx) + 1
            ) / len(early_df) * 100

            # 9. 전일 종가 대비 현재 등락률
            current_vs_prev = (close_price - prev_close) / prev_close * 100

            # 10. 첫 봉 거래대금 비중
            first_bar_ratio = (
                first_bar['trading_value'] / early_trading_value * 100
                if early_trading_value > 0 else 0
            )

            # 11. 거래대금 추세 (증가/감소)
            # 첫 3봉 vs 나머지
            if len(early_df) >= 4:
                first_half_value = early_df.iloc[:2]['trading_value'].sum()
                second_half_value = early_df.iloc[2:]['trading_value'].sum()
                value_trend = (
                    (second_half_value - first_half_value) / first_half_value * 100
                    if first_half_value > 0 else 0
                )
            else:
                value_trend = 0

            return {
                'open_gap': round(open_gap, 2),
                'early_trading_value': round(early_trading_value, 2),
                'early_change_rate': round(early_change_rate, 2),
                'early_volatility': round(early_volatility, 2),
                'band_high_break': band_high_break,
                'volume_surge_ratio': round(volume_surge_ratio, 2),
                'is_bullish': is_bullish,
                'high_bar_position': round(high_bar_position, 1),
                'current_vs_prev': round(current_vs_prev, 2),
                'first_bar_ratio': round(first_bar_ratio, 1),
                'value_trend': round(value_trend, 1),
                'open_price': open_price,
                'early_high': high_price,
                'early_low': low_price,
                'early_close': close_price,
                'bar_count': len(early_df),
            }

        except Exception as e:
            logger.warning(f"Failed to extract features: {e}")
            return None

    def _compare_event_vs_normal(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """이벤트일 vs 비이벤트일 지표 비교

        Args:
            features_df: 전체 지표 DataFrame

        Returns:
            비교 결과 DataFrame
        """
        event_days = features_df[features_df['is_event'] == True]
        normal_days = features_df[features_df['is_event'] == False]

        # 비교할 수치형 지표
        numeric_cols = [
            'open_gap', 'early_trading_value', 'early_change_rate',
            'early_volatility', 'volume_surge_ratio', 'current_vs_prev',
            'first_bar_ratio', 'value_trend', 'high_bar_position',
        ]

        results = []
        for col in numeric_cols:
            if col not in features_df.columns:
                continue

            event_vals = event_days[col].dropna()
            normal_vals = normal_days[col].dropna()

            if len(event_vals) == 0 or len(normal_vals) == 0:
                continue

            # 통계 계산
            result = {
                'feature': col,
                'event_mean': round(event_vals.mean(), 3),
                'event_median': round(event_vals.median(), 3),
                'event_std': round(event_vals.std(), 3),
                'normal_mean': round(normal_vals.mean(), 3),
                'normal_median': round(normal_vals.median(), 3),
                'normal_std': round(normal_vals.std(), 3),
                'mean_diff': round(event_vals.mean() - normal_vals.mean(), 3),
                'event_count': len(event_vals),
                'normal_count': len(normal_vals),
            }

            # 효과 크기 (Cohen's d)
            pooled_std = np.sqrt(
                ((len(event_vals) - 1) * event_vals.std()**2 +
                 (len(normal_vals) - 1) * normal_vals.std()**2) /
                (len(event_vals) + len(normal_vals) - 2)
            )
            if pooled_std > 0:
                result['cohens_d'] = round(
                    (event_vals.mean() - normal_vals.mean()) / pooled_std, 3
                )
            else:
                result['cohens_d'] = 0

            results.append(result)

        # Boolean 지표 비교 (band_high_break, is_bullish)
        for col in ['band_high_break', 'is_bullish']:
            if col not in features_df.columns:
                continue

            event_rate = event_days[col].mean() * 100 if len(event_days) > 0 else 0
            normal_rate = normal_days[col].mean() * 100 if len(normal_days) > 0 else 0

            results.append({
                'feature': col,
                'event_mean': round(event_rate, 1),
                'event_median': round(event_rate, 1),
                'event_std': 0,
                'normal_mean': round(normal_rate, 1),
                'normal_median': round(normal_rate, 1),
                'normal_std': 0,
                'mean_diff': round(event_rate - normal_rate, 1),
                'event_count': len(event_days),
                'normal_count': len(normal_days),
                'cohens_d': 0,
            })

        return pd.DataFrame(results)

    def _test_detection_rules(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """다양한 탐지 규칙 테스트

        Args:
            features_df: 전체 지표 DataFrame

        Returns:
            규칙별 정확도 DataFrame
        """
        # 정의할 탐지 규칙들
        rules = [
            # 단일 지표 규칙
            ('open_gap >= 2%', lambda df: df['open_gap'] >= 2),
            ('open_gap >= 3%', lambda df: df['open_gap'] >= 3),
            ('open_gap >= 5%', lambda df: df['open_gap'] >= 5),

            ('early_trading_value >= 10억', lambda df: df['early_trading_value'] >= 10),
            ('early_trading_value >= 20억', lambda df: df['early_trading_value'] >= 20),
            ('early_trading_value >= 50억', lambda df: df['early_trading_value'] >= 50),

            ('early_change_rate >= 2%', lambda df: df['early_change_rate'] >= 2),
            ('early_change_rate >= 3%', lambda df: df['early_change_rate'] >= 3),
            ('early_change_rate >= 5%', lambda df: df['early_change_rate'] >= 5),

            ('early_volatility >= 3%', lambda df: df['early_volatility'] >= 3),
            ('early_volatility >= 5%', lambda df: df['early_volatility'] >= 5),

            ('volume_surge_ratio >= 2', lambda df: df['volume_surge_ratio'] >= 2),
            ('volume_surge_ratio >= 3', lambda df: df['volume_surge_ratio'] >= 3),
            ('volume_surge_ratio >= 5', lambda df: df['volume_surge_ratio'] >= 5),

            ('band_high_break', lambda df: df['band_high_break'] == True),
            ('is_bullish', lambda df: df['is_bullish'] == True),

            # 조합 규칙
            ('open_gap >= 2% AND early_trading_value >= 20억',
             lambda df: (df['open_gap'] >= 2) & (df['early_trading_value'] >= 20)),

            ('open_gap >= 3% AND is_bullish',
             lambda df: (df['open_gap'] >= 3) & (df['is_bullish'])),

            ('early_change_rate >= 3% AND volume_surge_ratio >= 2',
             lambda df: (df['early_change_rate'] >= 3) & (df['volume_surge_ratio'] >= 2)),

            ('band_high_break AND early_change_rate >= 2%',
             lambda df: (df['band_high_break']) & (df['early_change_rate'] >= 2)),

            ('open_gap >= 2% AND early_volatility >= 3%',
             lambda df: (df['open_gap'] >= 2) & (df['early_volatility'] >= 3)),

            ('volume_surge_ratio >= 3 AND is_bullish',
             lambda df: (df['volume_surge_ratio'] >= 3) & (df['is_bullish'])),

            # 복합 규칙
            ('open_gap >= 2% AND early_change_rate >= 2% AND volume_surge_ratio >= 2',
             lambda df: (df['open_gap'] >= 2) & (df['early_change_rate'] >= 2) &
                       (df['volume_surge_ratio'] >= 2)),

            ('open_gap >= 3% AND is_bullish AND early_trading_value >= 10억',
             lambda df: (df['open_gap'] >= 3) & (df['is_bullish']) &
                       (df['early_trading_value'] >= 10)),
        ]

        results = []
        total_events = features_df['is_event'].sum()
        total_days = len(features_df)

        for rule_name, rule_func in rules:
            try:
                # 규칙 적용
                signals = rule_func(features_df)
                signal_count = signals.sum()

                # 실제 이벤트와 교집합
                true_positives = (signals & features_df['is_event']).sum()

                # 정밀도 (Precision): 신호 중 실제 이벤트 비율
                precision = true_positives / signal_count * 100 if signal_count > 0 else 0

                # 재현율 (Recall): 전체 이벤트 중 탐지된 비율
                recall = true_positives / total_events * 100 if total_events > 0 else 0

                # F1 Score
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                # 신호 발생 빈도
                signal_rate = signal_count / total_days * 100 if total_days > 0 else 0

                results.append({
                    'rule': rule_name,
                    'signal_count': signal_count,
                    'true_positives': true_positives,
                    'precision': round(precision, 1),
                    'recall': round(recall, 1),
                    'f1_score': round(f1, 1),
                    'signal_rate': round(signal_rate, 1),
                })

            except Exception as e:
                logger.warning(f"Failed to test rule '{rule_name}': {e}")

        return pd.DataFrame(results).sort_values('f1_score', ascending=False)

    def _find_optimal_rules(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """최적 탐지 규칙 탐색 (그리드 서치)

        Args:
            features_df: 전체 지표 DataFrame

        Returns:
            최적 규칙 DataFrame
        """
        # 탐색할 파라미터 그리드
        open_gap_thresholds = [1, 2, 3, 4, 5]
        trading_value_thresholds = [5, 10, 20, 30, 50]
        change_rate_thresholds = [1, 2, 3, 4, 5]
        volume_surge_thresholds = [1.5, 2, 3, 4, 5]

        total_events = features_df['is_event'].sum()
        total_days = len(features_df)

        best_rules = []

        # 단일 지표 최적화
        for threshold in open_gap_thresholds:
            signals = features_df['open_gap'] >= threshold
            tp = (signals & features_df['is_event']).sum()
            sc = signals.sum()
            precision = tp / sc * 100 if sc > 0 else 0
            recall = tp / total_events * 100 if total_events > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            best_rules.append({
                'rule_type': 'single',
                'rule': f'open_gap >= {threshold}%',
                'precision': round(precision, 1),
                'recall': round(recall, 1),
                'f1_score': round(f1, 1),
                'signal_count': sc,
                'true_positives': tp,
            })

        # 2개 조합 최적화 (상위 조합만)
        for gap_th in [2, 3, 4]:
            for vol_th in [2, 3, 4]:
                signals = (features_df['open_gap'] >= gap_th) & (features_df['volume_surge_ratio'] >= vol_th)
                tp = (signals & features_df['is_event']).sum()
                sc = signals.sum()
                precision = tp / sc * 100 if sc > 0 else 0
                recall = tp / total_events * 100 if total_events > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                if f1 > 10:  # F1이 10 이상인 것만
                    best_rules.append({
                        'rule_type': 'combo_2',
                        'rule': f'open_gap >= {gap_th}% AND volume_surge >= {vol_th}x',
                        'precision': round(precision, 1),
                        'recall': round(recall, 1),
                        'f1_score': round(f1, 1),
                        'signal_count': sc,
                        'true_positives': tp,
                    })

        for gap_th in [2, 3, 4]:
            for change_th in [2, 3, 4]:
                signals = (features_df['open_gap'] >= gap_th) & (features_df['early_change_rate'] >= change_th)
                tp = (signals & features_df['is_event']).sum()
                sc = signals.sum()
                precision = tp / sc * 100 if sc > 0 else 0
                recall = tp / total_events * 100 if total_events > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                if f1 > 10:
                    best_rules.append({
                        'rule_type': 'combo_2',
                        'rule': f'open_gap >= {gap_th}% AND early_change >= {change_th}%',
                        'precision': round(precision, 1),
                        'recall': round(recall, 1),
                        'f1_score': round(f1, 1),
                        'signal_count': sc,
                        'true_positives': tp,
                    })

        # 3개 조합 (핵심 조합)
        for gap_th in [2, 3]:
            for change_th in [2, 3]:
                for vol_th in [2, 3]:
                    signals = (
                        (features_df['open_gap'] >= gap_th) &
                        (features_df['early_change_rate'] >= change_th) &
                        (features_df['volume_surge_ratio'] >= vol_th)
                    )
                    tp = (signals & features_df['is_event']).sum()
                    sc = signals.sum()
                    precision = tp / sc * 100 if sc > 0 else 0
                    recall = tp / total_events * 100 if total_events > 0 else 0
                    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                    if f1 > 10:
                        best_rules.append({
                            'rule_type': 'combo_3',
                            'rule': f'gap>={gap_th}% AND change>={change_th}% AND vol>={vol_th}x',
                            'precision': round(precision, 1),
                            'recall': round(recall, 1),
                            'f1_score': round(f1, 1),
                            'signal_count': sc,
                            'true_positives': tp,
                        })

        if not best_rules:
            return pd.DataFrame()

        result_df = pd.DataFrame(best_rules)
        return result_df.sort_values('f1_score', ascending=False).head(20)

    def _generate_summary(
        self,
        features_df: pd.DataFrame,
        event_vs_normal: pd.DataFrame,
        rules_accuracy: pd.DataFrame,
    ) -> Dict:
        """분석 요약 생성"""
        total_days = len(features_df)
        event_days = features_df['is_event'].sum()
        normal_days = total_days - event_days

        # 가장 구분력 좋은 지표 (Cohen's d 기준)
        if not event_vs_normal.empty and 'cohens_d' in event_vs_normal.columns:
            best_feature = event_vs_normal.nlargest(1, 'cohens_d')
            best_feature_name = best_feature['feature'].iloc[0] if len(best_feature) > 0 else 'N/A'
            best_feature_d = best_feature['cohens_d'].iloc[0] if len(best_feature) > 0 else 0
        else:
            best_feature_name = 'N/A'
            best_feature_d = 0

        # 최고 F1 규칙
        if not rules_accuracy.empty:
            best_rule = rules_accuracy.iloc[0]
            best_rule_name = best_rule['rule']
            best_rule_f1 = best_rule['f1_score']
            best_rule_precision = best_rule['precision']
            best_rule_recall = best_rule['recall']
        else:
            best_rule_name = 'N/A'
            best_rule_f1 = 0
            best_rule_precision = 0
            best_rule_recall = 0

        return {
            'total_days': total_days,
            'event_days': int(event_days),
            'normal_days': int(normal_days),
            'event_rate': round(event_days / total_days * 100, 2) if total_days > 0 else 0,
            'best_discriminant_feature': best_feature_name,
            'best_feature_cohens_d': best_feature_d,
            'best_rule': best_rule_name,
            'best_rule_f1': best_rule_f1,
            'best_rule_precision': best_rule_precision,
            'best_rule_recall': best_rule_recall,
        }

    def _empty_result(self) -> EarlyDetectionResult:
        """빈 결과 반환"""
        return EarlyDetectionResult(
            early_features=pd.DataFrame(),
            event_vs_normal_stats=pd.DataFrame(),
            detection_rules_accuracy=pd.DataFrame(),
            optimal_rules=pd.DataFrame(),
            summary={},
        )
