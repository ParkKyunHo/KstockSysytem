# -*- coding: utf-8 -*-
"""
주도주 조기 탐지 분석 스크립트
V6.2-Q

장 시작 첫 15분(09:00~09:15) 데이터만으로 이벤트일 예측 가능성 분석

실행:
    "C:\Program Files\Python311\python.exe" -m scripts.backtest.leading_stock_analysis.early_detection_analysis

출력:
    data/backtest/leading_stock_analysis/
    ├── early_features.csv           # 전체 날짜별 첫 15분 지표
    ├── event_vs_normal_stats.csv    # 이벤트일 vs 비이벤트일 비교
    ├── detection_rules_accuracy.csv # 각 규칙별 정확도
    └── optimal_rules.csv            # 최적 탐지 규칙 권장
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest.leading_stock_analysis.data_loader import load_all_data
from scripts.backtest.leading_stock_analysis.daily_aggregator import (
    aggregate_all_to_daily,
    filter_event_days,
)
from scripts.backtest.leading_stock_analysis.config import OUTPUT_DIR, AnalysisConfig
from scripts.backtest.leading_stock_analysis.analyzers.early_detection import (
    EarlyDetectionAnalyzer,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_analysis(
    min_trading_value: float = 50.0,
    min_change_rate: float = 3.0,
    detection_window_minutes: int = 15,
):
    """조기 탐지 분석 실행

    Args:
        min_trading_value: 이벤트 최소 거래대금 (억원)
        min_change_rate: 이벤트 최소 등락률 (%)
        detection_window_minutes: 탐지 윈도우 (분)
    """
    print("=" * 70)
    print("주도주 조기 탐지 분석")
    print(f"분석 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 데이터 로드
    print("\n[1/5] 3분봉 데이터 로딩...")
    data_dict = load_all_data()
    if not data_dict:
        print("ERROR: 데이터 로드 실패")
        return

    stock_count = len(data_dict)
    total_bars = sum(len(df) for df in data_dict.values())
    print(f"  - 종목 수: {stock_count}")
    print(f"  - 전체 봉 수: {total_bars:,}")

    # 2. 일봉 집계
    print("\n[2/5] 일봉 집계...")
    daily_df = aggregate_all_to_daily(data_dict)
    if daily_df.empty:
        print("ERROR: 일봉 집계 실패")
        return

    total_days = len(daily_df)
    unique_dates = daily_df['date'].nunique()
    print(f"  - 전체 일봉: {total_days:,}")
    print(f"  - 고유 날짜: {unique_dates:,}")

    # 3. 이벤트일 필터링
    print("\n[3/5] 이벤트일 필터링...")
    print(f"  - 조건: 거래대금 >= {min_trading_value}억원, 등락률 >= {min_change_rate}%")

    events_df = filter_event_days(
        daily_df,
        min_trading_value=min_trading_value,
        min_change_rate=min_change_rate,
    )
    event_count = len(events_df)
    event_stocks = events_df['stock_name'].nunique() if not events_df.empty else 0
    print(f"  - 이벤트 수: {event_count}")
    print(f"  - 이벤트 종목: {event_stocks}")

    # 4. 조기 탐지 분석
    print(f"\n[4/5] 조기 탐지 분석 (첫 {detection_window_minutes}분)...")
    analyzer = EarlyDetectionAnalyzer(
        detection_window_minutes=detection_window_minutes,
        min_trading_value=min_trading_value,
        min_change_rate=min_change_rate,
    )

    result = analyzer.analyze(data_dict, daily_df, events_df)

    if result.early_features.empty:
        print("ERROR: 분석 결과 없음")
        return

    # 5. 결과 저장
    print("\n[5/5] 결과 저장...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # early_features.csv
    features_path = OUTPUT_DIR / "early_features.csv"
    result.early_features.to_csv(features_path, index=False, encoding='utf-8-sig')
    print(f"  - {features_path.name}: {len(result.early_features)} rows")

    # event_vs_normal_stats.csv
    stats_path = OUTPUT_DIR / "event_vs_normal_stats.csv"
    result.event_vs_normal_stats.to_csv(stats_path, index=False, encoding='utf-8-sig')
    print(f"  - {stats_path.name}: {len(result.event_vs_normal_stats)} rows")

    # detection_rules_accuracy.csv
    rules_path = OUTPUT_DIR / "detection_rules_accuracy.csv"
    result.detection_rules_accuracy.to_csv(rules_path, index=False, encoding='utf-8-sig')
    print(f"  - {rules_path.name}: {len(result.detection_rules_accuracy)} rows")

    # optimal_rules.csv
    optimal_path = OUTPUT_DIR / "optimal_rules.csv"
    result.optimal_rules.to_csv(optimal_path, index=False, encoding='utf-8-sig')
    print(f"  - {optimal_path.name}: {len(result.optimal_rules)} rows")

    # 6. 결과 출력
    print("\n" + "=" * 70)
    print("분석 결과 요약")
    print("=" * 70)

    summary = result.summary
    print(f"\n[데이터 현황]")
    print(f"  - 분석 일수: {summary.get('total_days', 0):,}")
    print(f"  - 이벤트일: {summary.get('event_days', 0):,} ({summary.get('event_rate', 0):.1f}%)")
    print(f"  - 비이벤트일: {summary.get('normal_days', 0):,}")

    print(f"\n[가장 구분력 좋은 지표]")
    print(f"  - 지표: {summary.get('best_discriminant_feature', 'N/A')}")
    print(f"  - Cohen's d: {summary.get('best_feature_cohens_d', 0):.3f}")

    print(f"\n[최고 성능 규칙]")
    print(f"  - 규칙: {summary.get('best_rule', 'N/A')}")
    print(f"  - F1 Score: {summary.get('best_rule_f1', 0):.1f}")
    print(f"  - Precision: {summary.get('best_rule_precision', 0):.1f}%")
    print(f"  - Recall: {summary.get('best_rule_recall', 0):.1f}%")

    # 상위 5개 규칙 출력
    if not result.detection_rules_accuracy.empty:
        print(f"\n[상위 5개 탐지 규칙]")
        print("-" * 70)
        top_rules = result.detection_rules_accuracy.head(5)
        for idx, row in top_rules.iterrows():
            print(f"  {row['rule']}")
            print(f"    → Precision: {row['precision']:.1f}%, Recall: {row['recall']:.1f}%, F1: {row['f1_score']:.1f}")

    # 이벤트 vs 비이벤트 주요 차이
    if not result.event_vs_normal_stats.empty:
        print(f"\n[이벤트일 vs 비이벤트일 주요 차이]")
        print("-" * 70)
        stats_df = result.event_vs_normal_stats.copy()
        # Cohen's d가 있는 행만 정렬
        numeric_stats = stats_df[stats_df['cohens_d'] != 0].nlargest(5, 'cohens_d')
        for _, row in numeric_stats.iterrows():
            feature = row['feature']
            event_mean = row['event_mean']
            normal_mean = row['normal_mean']
            cohens_d = row['cohens_d']
            print(f"  {feature}:")
            print(f"    이벤트: {event_mean:.2f}, 비이벤트: {normal_mean:.2f}, Cohen's d: {cohens_d:.3f}")

    print("\n" + "=" * 70)
    print(f"분석 완료: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"결과 저장 위치: {OUTPUT_DIR}")
    print("=" * 70)


def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description='주도주 조기 탐지 분석')
    parser.add_argument(
        '--min-trading-value',
        type=float,
        default=50.0,
        help='이벤트 최소 거래대금 (억원, 기본: 50)'
    )
    parser.add_argument(
        '--min-change-rate',
        type=float,
        default=3.0,
        help='이벤트 최소 등락률 (%%, 기본: 3)'
    )
    parser.add_argument(
        '--window',
        type=int,
        default=15,
        help='탐지 윈도우 (분, 기본: 15)'
    )

    args = parser.parse_args()

    run_analysis(
        min_trading_value=args.min_trading_value,
        min_change_rate=args.min_change_rate,
        detection_window_minutes=args.window,
    )


if __name__ == '__main__':
    main()
