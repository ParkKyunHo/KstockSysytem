# -*- coding: utf-8 -*-
"""
Daily Equity Curve - Main Entry Point

testday.csv 종목 대상 일봉 백테스팅 CLI
"""

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

# 프로젝트 루트를 path에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest.daily_equity_curve.config import BacktestConfig
from scripts.backtest.daily_equity_curve.data_loader import DataLoader
from scripts.backtest.daily_equity_curve.signal_detector import SignalDetector
from scripts.backtest.daily_equity_curve.trade_simulator import TradeSimulator
from scripts.backtest.daily_equity_curve.equity_curve import EquityCurve
from scripts.backtest.daily_equity_curve.exporter import ExcelExporter


def setup_logging(verbose: bool = False) -> logging.Logger:
    """로깅 설정"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    return logging.getLogger(__name__)


async def run_backtest_async(config: BacktestConfig, logger: logging.Logger):
    """비동기 백테스트 실행 (API 사용)"""
    from src.api.client import KiwoomAPIClient
    from src.api.endpoints.market import MarketAPI

    # API 클라이언트 초기화 (async with 필수)
    async with KiwoomAPIClient() as client:
        market_api = MarketAPI(client)

        # 데이터 로더
        data_loader = DataLoader(config, api_client=client, logger=logger)
        data_loader.set_market_api(market_api)

        # 종목 로드
        stocks = data_loader.load_testday()
        if not stocks:
            logger.error("종목 로드 실패")
            return

        # 일봉 데이터 조회
        logger.info("일봉 데이터 조회 중...")
        daily_data = await data_loader.load_daily_batch(stocks)

        if not daily_data:
            logger.error("일봉 데이터 조회 실패")
            return

        # 백테스트 실행
        await _execute_backtest(config, stocks, daily_data, logger)


def run_backtest_cached(config: BacktestConfig, logger: logging.Logger):
    """캐시 데이터로 백테스트 실행"""
    data_loader = DataLoader(config, logger=logger)

    # 종목 로드
    stocks = data_loader.load_testday()
    if not stocks:
        logger.error("종목 로드 실패")
        return

    # 캐시에서 데이터 로드
    logger.info("캐시 데이터 로드 중...")
    daily_data = data_loader.load_from_cache(stocks)

    if not daily_data:
        logger.error("캐시 데이터 없음. --fetch 옵션으로 API 조회 필요")
        return

    # 백테스트 실행
    asyncio.run(_execute_backtest(config, stocks, daily_data, logger))


async def _execute_backtest(
    config: BacktestConfig,
    stocks: list,
    daily_data: dict,
    logger: logging.Logger
):
    """백테스트 실행 공통 로직"""
    logger.info(f"백테스트 시작: {len(daily_data)}개 종목")

    # 신호 탐지
    logger.info("신호 탐지 중...")
    signal_detector = SignalDetector(config)

    # 지표 계산
    for stock_code, df in daily_data.items():
        daily_data[stock_code] = signal_detector.calculate_indicators(df)

    # 신호 탐지
    all_signals = signal_detector.detect_all_signals(
        daily_data,
        start_date=config.start_date,
        end_date=config.end_date
    )

    total_signals = sum(len(s) for s in all_signals.values())
    logger.info(f"신호 탐지 완료: {len(all_signals)}개 종목, {total_signals}개 신호")

    if not all_signals:
        logger.warning("탐지된 신호 없음")
        return

    # 거래 시뮬레이션
    logger.info("거래 시뮬레이션 중...")
    simulator = TradeSimulator(config, logger=logger)
    trades = simulator.simulate_all(stocks, daily_data, all_signals)

    if not trades:
        logger.warning("거래 기록 없음")
        return

    # 수익곡선 계산
    logger.info("수익곡선 계산 중...")
    equity_curve = EquityCurve()
    monthly_stats = equity_curve.calculate_monthly_stats(trades)
    summary = equity_curve.calculate_summary(trades)
    stock_stats = equity_curve.calculate_by_stock(trades)

    # 결과 출력
    _print_summary(summary, logger)

    # Excel 내보내기
    logger.info("Excel 파일 생성 중...")
    exporter = ExcelExporter(config)
    output_path = exporter.export(trades, monthly_stats, summary, stock_stats)
    logger.info(f"결과 저장: {output_path}")

    # CSV 백업
    csv_path = exporter.export_csv(trades)
    logger.info(f"CSV 백업: {csv_path}")


def _print_summary(summary: dict, logger: logging.Logger):
    """요약 출력"""
    logger.info("=" * 50)
    logger.info("백테스트 결과 요약")
    logger.info("=" * 50)
    logger.info(f"총 거래수: {summary['total_trades']}")
    logger.info(f"승/패: {summary['win_count']}/{summary['loss_count']}")
    logger.info(f"승률: {summary['win_rate']}%")
    logger.info(f"총 손익: {summary['total_pnl']:,}원")
    logger.info(f"평균 손익: {summary['avg_pnl']:,}원")
    logger.info(f"평균 수익률: {summary['avg_return_pct']}%")
    logger.info(f"Profit Factor: {summary['profit_factor']}")
    logger.info(f"MDD: {summary['mdd']}%")
    logger.info(f"평균 보유일: {summary['avg_holding_days']}일")
    logger.info("=" * 50)


def main():
    """CLI 진입점"""
    parser = argparse.ArgumentParser(
        description="Daily Equity Curve Backtest - 지저깨 신호 일봉 백테스팅"
    )

    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="캐시 데이터 사용 (API 호출 없음)"
    )

    parser.add_argument(
        "--fetch",
        action="store_true",
        help="API에서 데이터 조회 (캐시 갱신)"
    )

    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-01-01",
        help="백테스트 시작일 (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-01-24",
        help="백테스트 종료일 (YYYY-MM-DD)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="상세 로그 출력"
    )

    args = parser.parse_args()

    # 로깅 설정
    logger = setup_logging(args.verbose)

    # 설정
    config = BacktestConfig(
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date)
    )

    logger.info(f"백테스트 기간: {config.start_date} ~ {config.end_date}")

    # 실행
    if args.use_cache:
        run_backtest_cached(config, logger)
    elif args.fetch:
        asyncio.run(run_backtest_async(config, logger))
    else:
        # 기본: 캐시 시도, 없으면 안내
        logger.info("--use-cache 또는 --fetch 옵션을 지정하세요")
        logger.info("  --use-cache: 캐시된 데이터로 백테스트 실행")
        logger.info("  --fetch: API에서 데이터 조회 후 백테스트 실행")


if __name__ == "__main__":
    main()
