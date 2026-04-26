#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
December Pipeline - Main Entry Point

2단계 백테스트 파이프라인:
- Stage A: 일봉 이벤트 포착 (거래대금 >= 1000억, 등락률 >= 10%)
- Stage B: 이벤트 당일 3분봉 SNIPER_TRAP 전략 테스트

Usage:
    # Stage A만 실행
    python -m scripts.backtest.december_pipeline.main --stage a

    # Stage B만 실행 (Stage A 완료 필요)
    python -m scripts.backtest.december_pipeline.main --stage b

    # 전체 파이프라인
    python -m scripts.backtest.december_pipeline.main --stage all

    # 옵션 지정
    python -m scripts.backtest.december_pipeline.main --stage all --min-value 1000 --min-change 10 --use-cache
"""

import asyncio
import argparse
import sys
import logging
from pathlib import Path
from datetime import date
import pandas as pd

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_config, get_settings
from src.utils.logger import setup_logging, get_logger
from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI

from .config import PipelineConfig
from .data_loader import DataLoader
from .stage_a_daily import StageAProcessor
from .stage_b_intraday import StageBProcessor
from .strategy import SniperTrapStrategy
from .exporter import export_to_excel, print_final_summary


def parse_args():
    """명령줄 인자 파싱"""
    parser = argparse.ArgumentParser(
        description="December Pipeline - 12월 백테스트 파이프라인"
    )

    parser.add_argument(
        "--stage",
        choices=["a", "b", "all"],
        default="all",
        help="실행할 단계 (a: 일봉 이벤트, b: 3분봉 전략, all: 전체)"
    )

    parser.add_argument(
        "--min-value",
        type=int,
        default=1000,
        help="최소 거래대금 (억원, 기본: 1000)"
    )

    parser.add_argument(
        "--min-change",
        type=float,
        default=10.0,
        help="최소 등락률 (%%, 기본: 10)"
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="API 동시 요청 수 (기본: 3)"
    )

    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="캐시 사용"
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="캐시 사용 안함"
    )

    parser.add_argument(
        "--output",
        type=str,
        help="결과 Excel 파일 경로"
    )

    parser.add_argument(
        "--year",
        type=int,
        default=2025,
        help="대상 연도 (기본: 2025, --event-start 미지정 시 12월 사용)"
    )

    # V6.2-P: 커스텀 날짜 범위 지원
    parser.add_argument(
        "--event-start",
        type=str,
        help="이벤트 시작일 (YYYY-MM-DD, 예: 2026-01-12)"
    )

    parser.add_argument(
        "--event-end",
        type=str,
        help="이벤트 종료일 (YYYY-MM-DD, 예: 2026-01-15)"
    )

    parser.add_argument(
        "--buffer-start",
        type=str,
        help="버퍼 시작일 (YYYY-MM-DD, 예: 2026-01-06)"
    )

    parser.add_argument(
        "--hold-profit",
        action="store_true",
        help="수익 시 익일 이월 모드 (END_OF_DATA에서 수익 중이면 ATR_TS까지 보유)"
    )

    parser.add_argument(
        "--max-hold-days",
        type=int,
        default=5,
        help="익일 이월 시 최대 보유 일수 (기본: 5)"
    )

    parser.add_argument(
        "--past1000-path",
        type=str,
        help="past1000 종목 리스트 파일 경로 (기본: C:/K_stock_trading/past1000.csv)"
    )

    return parser.parse_args()


async def main():
    """메인 실행"""
    args = parse_args()

    # 로깅 설정
    setup_logging()
    logger = get_logger(__name__)
    logger.setLevel(logging.INFO)

    # 콘솔 핸들러 추가
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s - %(message)s", "%H:%M:%S"))
    logger.addHandler(console)

    # V6.2-P: 날짜 파싱 (커스텀 날짜 또는 연도 기반)
    if args.event_start:
        event_start = date.fromisoformat(args.event_start)
    else:
        event_start = date(args.year, 12, 1)

    if args.event_end:
        event_end = date.fromisoformat(args.event_end)
    else:
        event_end = date(args.year, 12, 31)

    if args.buffer_start:
        buffer_start = date.fromisoformat(args.buffer_start)
    else:
        # 버퍼: 이벤트 시작일 기준 6일 전 (주말 포함)
        buffer_start = date(event_start.year, event_start.month, max(1, event_start.day - 6))

    # V6.2-P: 출력 디렉토리 동적 생성
    output_dir_name = f"{event_start.strftime('%Y%m%d')}_{event_end.strftime('%Y%m%d')}"
    output_dir = Path(f"C:/K_stock_trading/data/backtest/{output_dir_name}")
    cache_dir = output_dir / "cache"

    # past1000 파일 경로 설정
    past1000_path = Path(args.past1000_path) if args.past1000_path else Path("C:/K_stock_trading/past1000.csv")

    # 설정 생성
    config = PipelineConfig(
        min_trading_value=args.min_value * 100_000_000,  # 억원 -> 원
        min_change_rate=args.min_change,
        api_concurrency=args.concurrency,
        use_cache=not args.no_cache if args.no_cache else args.use_cache,
        event_start=event_start,
        event_end=event_end,
        buffer_start=buffer_start,
        hold_if_profitable=args.hold_profit,
        max_hold_days=args.max_hold_days,
        output_dir=output_dir,
        cache_dir=cache_dir,
        past1000_path=past1000_path,
    )

    print("\n" + "=" * 60)
    print("SNIPER_TRAP Backtest Pipeline")
    print("=" * 60)
    print(f"단계: {args.stage.upper()}")
    print(f"대상 기간: {config.event_start} ~ {config.event_end}")
    print(f"최소 거래대금: {args.min_value:,}억원")
    print(f"최소 등락률: +{args.min_change:.1f}%")
    print(f"캐시 사용: {config.use_cache}")
    if config.hold_if_profitable:
        print(f"익일 이월: 활성화 (최대 {config.max_hold_days}일)")
    print("=" * 60 + "\n")

    # 결과 저장용
    event_days_df = None
    event_summary_df = None
    trades_df = None
    summary_df = None

    async with KiwoomAPIClient() as client:
        market_api = MarketAPI(client)

        # DataLoader 설정
        data_loader = DataLoader(config, client, logger)
        data_loader.set_market_api(market_api)

        # Stage A 실행
        if args.stage in ["a", "all"]:
            stage_a = StageAProcessor(config, data_loader, logger)
            event_days_df, event_summary_df = await stage_a.run()

        # Stage B 실행
        if args.stage in ["b", "all"]:
            strategy = SniperTrapStrategy(config, logger)
            stage_b = StageBProcessor(config, data_loader, strategy, logger)
            trades_df, summary_df = await stage_b.run()

    # Stage B만 실행했을 경우 Stage A 결과 로드
    if args.stage == "b":
        try:
            event_days_df = pd.read_csv(config.event_days_path, encoding="utf-8-sig")
            event_summary_df = pd.read_csv(config.event_summary_path, encoding="utf-8-sig")
        except Exception:
            event_days_df = pd.DataFrame()
            event_summary_df = pd.DataFrame()

    # 최종 요약 출력
    if event_days_df is not None or trades_df is not None:
        print_final_summary(
            event_days_df if event_days_df is not None else pd.DataFrame(),
            event_summary_df if event_summary_df is not None else pd.DataFrame(),
            trades_df if trades_df is not None else pd.DataFrame(),
            summary_df if summary_df is not None else pd.DataFrame()
        )

    # Excel 내보내기
    if args.output and (event_days_df is not None or trades_df is not None):
        export_to_excel(
            event_days_df if event_days_df is not None else pd.DataFrame(),
            event_summary_df if event_summary_df is not None else pd.DataFrame(),
            trades_df if trades_df is not None else pd.DataFrame(),
            summary_df if summary_df is not None else pd.DataFrame(),
            Path(args.output)
        )

    print("\n파이프라인 완료!")


if __name__ == "__main__":
    asyncio.run(main())
