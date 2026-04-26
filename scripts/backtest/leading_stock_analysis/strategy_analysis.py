# -*- coding: utf-8 -*-
"""
SNIPER_TRAP 전략 백테스트 분석 스크립트
V6.2-Q

3분봉 데이터에 SNIPER_TRAP 전략을 적용하여
최적 시간대, 조건을 분석합니다.

사용법:
    python -m scripts.backtest.leading_stock_analysis.strategy_analysis
"""

import logging
import sys
from pathlib import Path

from .config import DATA_DIR, OUTPUT_DIR, AnalysisConfig
from .data_loader import load_all_data
from .daily_aggregator import (
    aggregate_all_to_daily,
    filter_event_days,
    get_event_days_list,
)
from .analyzers.strategy_backtest import StrategyBacktestAnalyzer


def setup_logging():
    """로깅 설정"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )


def main():
    """메인 함수"""
    setup_logging()
    logger = logging.getLogger(__name__)

    print("=" * 70)
    print("  SNIPER_TRAP 전략 백테스트 분석")
    print("  V6.2-Q Strategy Backtest Analysis")
    print("=" * 70)
    print()

    # 설정 - 조건 완화하여 더 많은 데이터 확보
    config = AnalysisConfig(
        min_trading_value=50.0,    # 50억원 이상
        min_change_rate=3.0,       # 3% 이상
    )

    print(f"데이터 디렉토리: {DATA_DIR}")
    print(f"분석 조건: 거래대금 >= {config.min_trading_value}억원, 등락률 >= {config.min_change_rate}%")
    print()

    # 1. 데이터 로딩
    print("[1/4] 데이터 로딩 중...")
    data_dict = load_all_data(DATA_DIR)
    if not data_dict:
        print("ERROR: 데이터를 찾을 수 없습니다.")
        sys.exit(1)
    print(f"  로드된 종목 수: {len(data_dict)}")

    # 2. 일봉 집계 및 이벤트 필터링
    print("[2/4] 이벤트 필터링 중...")
    daily_df = aggregate_all_to_daily(data_dict)
    events_df = filter_event_days(daily_df, config=config)
    print(f"  이벤트 발생일 수: {len(events_df)}")

    if events_df.empty:
        print("WARNING: 조건을 만족하는 이벤트가 없습니다.")
        sys.exit(0)

    event_days_list = get_event_days_list(events_df, data_dict)
    print(f"  분석 대상: {len(event_days_list)} 이벤트")

    # 3. SNIPER_TRAP 전략 백테스트
    print("[3/4] SNIPER_TRAP 전략 백테스트 중...")
    analyzer = StrategyBacktestAnalyzer(config)
    # 전체 히스토리 전달 (EMA200 계산용)
    result = analyzer.analyze(event_days_list, full_data_dict=data_dict)

    if result.signals.empty:
        print("WARNING: SNIPER_TRAP 신호가 발생하지 않았습니다.")
        sys.exit(0)

    print(f"  발생한 신호 수: {len(result.signals)}")

    # 4. 결과 출력
    print("[4/4] 결과 분석 중...")
    print()

    _print_results(result)

    # 결과 저장
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    result.signals.to_csv(output_dir / 'strategy_signals.csv', index=False, encoding='utf-8-sig')
    result.time_analysis.to_csv(output_dir / 'strategy_time_analysis.csv', index=False, encoding='utf-8-sig')

    if 'body_size_sensitivity' in result.parameter_sensitivity:
        result.parameter_sensitivity['body_size_sensitivity'].to_csv(
            output_dir / 'strategy_body_sensitivity.csv', index=False, encoding='utf-8-sig'
        )

    print()
    print(f"결과 저장: {output_dir}")
    print("=" * 70)


def _print_results(result):
    """결과 출력"""

    print("=" * 70)
    print("  SNIPER_TRAP 전략 분석 결과")
    print("=" * 70)
    print()

    # 1. 전체 성과
    signals = result.signals
    print("■ 전체 성과")
    print(f"  - 총 신호 수: {len(signals)}")
    print(f"  - 평균 수익률: {signals['return_to_close'].mean():.2f}%")
    print(f"  - 중앙값 수익률: {signals['return_to_close'].median():.2f}%")
    print(f"  - 승률: {(signals['return_to_close'] > 0).mean() * 100:.1f}%")
    print(f"  - 평균 MFE: {signals['mfe'].mean():.2f}%")
    print(f"  - 평균 MAE: {signals['mae'].mean():.2f}%")
    print()

    # 2. 시간대별 성과
    print("■ 시간대별 성과")
    time_analysis = result.time_analysis
    if not time_analysis.empty:
        for _, row in time_analysis.iterrows():
            print(f"  {int(row['entry_hour']):02d}시: "
                  f"수익률 {row['avg_return']:+.2f}% | "
                  f"승률 {row['win_rate']:.1f}% | "
                  f"신호 {int(row['signal_count'])}개")
    print()

    # 3. 조건별 성과
    print("■ 조건별 성과")

    if 'body_size' in result.condition_analysis:
        print("  [캔들 크기별]")
        for _, row in result.condition_analysis['body_size'].iterrows():
            print(f"    {row['body_size_group']}: "
                  f"수익률 {row['avg_return']:+.2f}% ({int(row['count'])}건)")

    if 'volume_ratio' in result.condition_analysis:
        print("  [거래량 비율별]")
        for _, row in result.condition_analysis['volume_ratio'].iterrows():
            print(f"    {row['volume_group']}: "
                  f"수익률 {row['avg_return']:+.2f}% ({int(row['count'])}건)")
    print()

    # 4. 파라미터 민감도
    print("■ 파라미터 민감도")

    if 'body_size_sensitivity' in result.parameter_sensitivity:
        print("  [캔들 크기 임계값]")
        for _, row in result.parameter_sensitivity['body_size_sensitivity'].iterrows():
            print(f"    >= {row['min_body_size']:.1f}%: "
                  f"신호 {int(row['signal_count'])}개 | "
                  f"수익률 {row['avg_return']:+.2f}% | "
                  f"승률 {row['win_rate']:.1f}%")

    if 'time_filter_sensitivity' in result.parameter_sensitivity:
        print("  [시간 필터]")
        for _, row in result.parameter_sensitivity['time_filter_sensitivity'].iterrows():
            print(f"    {row['start_time']} 이후: "
                  f"신호 {int(row['signal_count'])}개 | "
                  f"수익률 {row['avg_return']:+.2f}% | "
                  f"승률 {row['win_rate']:.1f}%")
    print()

    # 5. 최적 조건
    print("■ 최적 조건 권장")
    optimal = result.optimal_conditions

    if 'best_entry_hour' in optimal:
        best = optimal['best_entry_hour']
        print(f"  - 최적 진입 시간: {best['hour']}시 "
              f"(수익률 {best['avg_return']:.2f}%, 승률 {best['win_rate']:.1f}%)")

    if 'recommended_hours' in optimal:
        hours = sorted(optimal['recommended_hours'])
        print(f"  - 권장 시간대: {', '.join(f'{int(h)}시' for h in hours)}")

    if 'recommended_filters' in optimal:
        print("  - 권장 필터:")
        for f in optimal['recommended_filters']:
            print(f"    - {f}")

    if 'top_performers' in optimal:
        top = optimal['top_performers']
        print(f"  - 상위 20% 신호 특성:")
        print(f"    -평균 진입 시간: {top['avg_entry_hour']:.1f}시")
        print(f"    -평균 캔들 크기: {top['avg_body_size']:.2f}%")
        print(f"    -평균 거래량 비율: {top['avg_volume_ratio']:.1f}배")

    print()


if __name__ == '__main__':
    main()
