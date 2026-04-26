# -*- coding: utf-8 -*-
"""
주도주 3분봉 심층 분석 - CLI 진입점
V6.2-Q

사용법:
    python -m scripts.backtest.leading_stock_analysis.main [옵션]

옵션:
    --min-trading-value: 최소 거래대금 (억원, 기본 1000)
    --min-change-rate: 최소 등락률 (%, 기본 10)
    --output-dir: 결과 출력 디렉토리
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

from .config import DATA_DIR, OUTPUT_DIR, AnalysisConfig
from .data_loader import load_all_data, get_stock_summary
from .daily_aggregator import (
    aggregate_all_to_daily,
    filter_event_days,
    get_event_days_list,
    get_event_summary,
)
from .analyzers import (
    TimeDistributionAnalyzer,
    BandBreakoutAnalyzer,
    PricePatternAnalyzer,
    IndicatorValidityAnalyzer,
    VolumePatternAnalyzer,
    HoldingPeriodAnalyzer,
    EntryTimingAnalyzer,
)
from .exporter import ResultExporter


def setup_logging(verbose: bool = False):
    """로깅 설정"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )


def parse_args():
    """커맨드라인 인자 파싱"""
    parser = argparse.ArgumentParser(
        description='주도주 3분봉 데이터 심층 분석',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--min-trading-value',
        type=float,
        default=1000,
        help='최소 거래대금 (억원, 기본 1000)',
    )

    parser.add_argument(
        '--min-change-rate',
        type=float,
        default=10.0,
        help='최소 등락률 (%%, 기본 10)',
    )

    parser.add_argument(
        '--data-dir',
        type=str,
        default=None,
        help='3분봉 데이터 디렉토리 (기본: 3m_data)',
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        help='결과 출력 디렉토리',
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='상세 로깅 출력',
    )

    return parser.parse_args()


def print_banner():
    """배너 출력"""
    print("=" * 60)
    print("  주도주 3분봉 데이터 심층 분석")
    print("  V6.2-Q Leading Stock Analysis")
    print("=" * 60)
    print()


def print_section(title: str):
    """섹션 구분선 출력"""
    print()
    print("-" * 50)
    print(f"  {title}")
    print("-" * 50)


def main():
    """메인 함수"""
    args = parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)

    print_banner()

    # 설정
    config = AnalysisConfig(
        min_trading_value=args.min_trading_value,  # 억원 단위 그대로 사용
        min_change_rate=args.min_change_rate,
    )

    data_dir = Path(args.data_dir) if args.data_dir else DATA_DIR
    output_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR

    print(f"데이터 디렉토리: {data_dir}")
    print(f"출력 디렉토리: {output_dir}")
    print(f"이벤트 조건: 거래대금 >= {args.min_trading_value}억원, 등락률 >= {args.min_change_rate}%")
    print()

    # Phase 1: 데이터 로딩
    print_section("Phase 1: 데이터 로딩")

    print("3분봉 데이터 로딩 중...")
    data_dict = load_all_data(data_dir)

    if not data_dict:
        print("ERROR: 데이터를 찾을 수 없습니다.")
        sys.exit(1)

    print(f"  로드된 종목 수: {len(data_dict)}")

    # 종목 요약
    stock_summary = get_stock_summary(data_dict)
    total_bars = stock_summary['total_bars'].sum()
    total_days = stock_summary['trading_days'].sum()
    print(f"  총 봉 수: {total_bars:,}")
    print(f"  총 거래일 수: {total_days:,}")

    # Phase 1.1: 일봉 재구성
    print_section("Phase 1.1: 일봉 재구성")

    print("3분봉 → 일봉 집계 중...")
    daily_df = aggregate_all_to_daily(data_dict)
    print(f"  일봉 레코드 수: {len(daily_df):,}")

    # Phase 1.2: 이벤트 필터링
    print_section("Phase 1.2: 이벤트 필터링")

    events_df = filter_event_days(daily_df, config=config)
    print(f"  이벤트 발생일 수: {len(events_df)}")

    if events_df.empty:
        print("WARNING: 조건을 만족하는 이벤트가 없습니다. 조건을 완화해 보세요.")
        sys.exit(0)

    # 이벤트 요약
    event_summary = get_event_summary(events_df)
    print(f"  이벤트 발생 종목 수: {len(event_summary)}")
    print(f"  평균 이벤트 수 (종목당): {event_summary['event_count'].mean():.1f}")

    # 이벤트 일자의 3분봉 데이터 추출
    event_days_list = get_event_days_list(events_df, data_dict)
    print(f"  분석 대상 이벤트: {len(event_days_list)}")

    # Phase 2: 심층 분석
    print_section("Phase 2: 심층 분석")

    # 2.1 시간대별 거래대금 분석
    print("  [1/7] 시간대별 거래대금 분석...")
    time_analyzer = TimeDistributionAnalyzer(config)
    time_result = time_analyzer.analyze(event_days_list)

    # 2.2 밴드 돌파 분석
    print("  [2/7] BandHigh/Low 돌파 분석...")
    band_analyzer = BandBreakoutAnalyzer(config)
    band_result = band_analyzer.analyze(event_days_list)

    # 2.3 가격 패턴 분석
    print("  [3/7] 가격 패턴 분석...")
    price_analyzer = PricePatternAnalyzer(config)
    price_result = price_analyzer.analyze(event_days_list)

    # 2.4 지표 유효성 분석
    print("  [4/7] 지표 유효성 분석...")
    indicator_analyzer = IndicatorValidityAnalyzer(config)
    indicator_result = indicator_analyzer.analyze(event_days_list)

    # 2.5 거래량 패턴 분석
    print("  [5/7] 거래량 패턴 분석...")
    volume_analyzer = VolumePatternAnalyzer(config)
    volume_result = volume_analyzer.analyze(event_days_list)

    # 2.6 보유 시간 분석
    print("  [6/7] 보유 시간별 수익률 분석...")
    holding_analyzer = HoldingPeriodAnalyzer(config)
    holding_result = holding_analyzer.analyze(event_days_list)

    # 2.7 진입 타이밍 분석
    print("  [7/7] 진입 타이밍 분석...")
    entry_analyzer = EntryTimingAnalyzer(config)
    entry_result = entry_analyzer.analyze(event_days_list)

    # Phase 3: 결과 저장
    print_section("Phase 3: 결과 저장")

    exporter = ResultExporter(output_dir)
    exported_files = exporter.export_all(
        daily_events=events_df,
        event_summary=event_summary,
        time_distribution_result=time_result,
        band_breakout_result=band_result,
        price_pattern_result=price_result,
        indicator_validity_result=indicator_result,
        volume_pattern_result=volume_result,
        holding_period_result=holding_result,
        entry_timing_result=entry_result,
    )

    print(f"  생성된 파일 수: {len(exported_files)}")
    for name, path in exported_files.items():
        print(f"    - {path.name}")

    # Phase 4: 핵심 인사이트 출력
    print_section("Phase 4: 핵심 인사이트")

    _print_insights(
        events_df, event_summary,
        time_result, band_result, price_result,
        holding_result, entry_result
    )

    print()
    print("=" * 60)
    print(f"  분석 완료! 결과: {output_dir}")
    print("=" * 60)


def _print_insights(events_df, event_summary, time_result, band_result, price_result, holding_result, entry_result):
    """핵심 인사이트 출력"""

    print()
    print("1. 이벤트 통계")
    print(f"   - 총 이벤트 수: {len(events_df)}")
    print(f"   - 이벤트 종목 수: {len(event_summary)}")
    if not event_summary.empty:
        top_stock = event_summary.iloc[0]
        print(f"   - 최다 이벤트 종목: {top_stock['stock_name']} ({top_stock['event_count']}회)")

    # 시간대별 분석
    print()
    print("2. 거래대금 분포")
    if time_result and hasattr(time_result, 'pattern_classification'):
        patterns = time_result.pattern_classification.get('frequencies', {})
        if patterns:
            dominant = max(patterns.items(), key=lambda x: x[1])
            print(f"   - 주요 패턴: {dominant[0]} ({dominant[1]:.1f}%)")

    # 밴드 돌파 분석
    print()
    print("3. BandHigh 돌파 성과")
    if band_result and hasattr(band_result, 'post_breakout_returns'):
        if isinstance(band_result.post_breakout_returns, dict) and 'summary' in band_result.post_breakout_returns:
            summary = band_result.post_breakout_returns['summary']
            if isinstance(summary, pd.DataFrame) and not summary.empty:
                for _, row in summary.iterrows():
                    print(f"   - {row.name}: 평균 {row['mean']:.2f}%, 승률 {row['win_rate']:.1f}%")

    # MFE/MAE
    print()
    print("4. MFE/MAE (시가 기준)")
    if price_result and hasattr(price_result, 'mfe_mae'):
        if isinstance(price_result.mfe_mae, dict) and 'summary' in price_result.mfe_mae:
            mfe_mae = price_result.mfe_mae['summary']
            if 'mfe' in mfe_mae:
                print(f"   - 평균 MFE: {mfe_mae['mfe']['mean']:.2f}%")
            if 'mae' in mfe_mae:
                print(f"   - 평균 MAE: {mfe_mae['mae']['mean']:.2f}%")
            if 'efficiency' in mfe_mae:
                print(f"   - 평균 효율: {mfe_mae['efficiency']['mean']:.1f}%")

    # 최적 보유 시간
    print()
    print("5. 최적 보유 시간")
    if holding_result and hasattr(holding_result, 'optimal_period'):
        optimal = holding_result.optimal_period
        if optimal:
            print(f"   - 평균 수익률 기준: {optimal.get('optimal_by_mean', 'N/A')}")
            print(f"   - Sharpe 기준: {optimal.get('optimal_by_sharpe', 'N/A')}")
            print(f"   - 승률 기준: {optimal.get('optimal_by_winrate', 'N/A')}")

    # 최적 진입 시점
    print()
    print("6. 최적 진입 시점")
    if entry_result and hasattr(entry_result, 'optimal_entry_time'):
        optimal = entry_result.optimal_entry_time
        if optimal:
            print(f"   - 최적 대기 시간 (수익률): {optimal.get('optimal_by_return', 'N/A')}분")
            print(f"   - 최적 대기 시간 (Sharpe): {optimal.get('optimal_by_sharpe', 'N/A')}분")

    # 손절 효과
    print()
    print("7. 손절 효과")
    if entry_result and hasattr(entry_result, 'stop_loss_effectiveness'):
        sl_result = entry_result.stop_loss_effectiveness
        if isinstance(sl_result, dict) and 'best_stop_loss' in sl_result:
            print(f"   - 최적 손절선: {sl_result['best_stop_loss']}%")


if __name__ == '__main__':
    # pandas 임포트 (인사이트 출력용)
    import pandas as pd
    main()
