#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
EMA_SPLIT_BUY 백테스트 메인 스크립트

Usage:
    # 기본 실행 (단일 설정)
    python scripts/backtest/ema_split_buy/main.py

    # 최적화 모드 (그리드 서치)
    python scripts/backtest/ema_split_buy/main.py --optimize

    # 커스텀 설정
    python scripts/backtest/ema_split_buy/main.py --ema5 1.0 --ema8 1.5 --stop fixed

    # 엑셀 출력
    python scripts/backtest/ema_split_buy/main.py --output results.xlsx
"""

import asyncio
import argparse
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_config, get_settings
from src.utils.logger import setup_logging, get_logger
from src.api.client import KiwoomAPIClient

from .config import EMASplitBuyConfig, StopLossType, PROXIMITY_GRID
from .data_loader import DataLoader
from .indicators import calculate_indicators
from .signal_detector import SignalDetector
from .trade_simulator import TradeSimulator
from .optimizer import Optimizer
from .exporter import ExcelExporter, print_console_summary, print_optimization_top_results, print_monthly_summary


async def run_backtest(args):
    """백테스트 실행"""
    # 로거 설정
    setup_logging()
    logger = get_logger("EMA_SPLIT_BUY")
    logger.info("EMA_SPLIT_BUY 백테스트 시작")

    # 설정 생성
    config = EMASplitBuyConfig(
        ema5_proximity_pct=args.ema5,
        ema8_proximity_pct=args.ema8,
        stop_loss_type=StopLossType.FIXED_5PCT if args.stop == "fixed" else StopLossType.ATR_TRAILING,
        use_3min_exit=args.use_3min,
        use_ema3_exit=args.use_ema3,
        use_3min_real=args.use_3min_real
    )

    # API 클라이언트 초기화 (context manager 사용)
    api_client = KiwoomAPIClient()

    async with api_client:
        logger.info("API 연결 성공")

        # 데이터 로더
        data_loader = DataLoader(config, api_client, logger)

        # 종목 리스트 로딩
        stocks = data_loader.load_stock_list()
        logger.info(f"종목 리스트 로딩: {len(stocks)}개")

        # 일봉 데이터 로딩
        stocks_data = await data_loader.load_all_stocks_data(stocks)
        stock_info = {s["code"]: s["name"] for s in stocks}

        if not stocks_data:
            logger.error("유효한 데이터가 없습니다")
            return

        # 지표 계산
        logger.info("지표 계산 중...")
        for code, df in stocks_data.items():
            stocks_data[code] = calculate_indicators(df)

        if args.optimize:
            # 최적화 모드
            logger.info("최적화 모드 실행")
            optimizer = Optimizer(config, logger)

            results = optimizer.run_grid_search(
                stocks_data=stocks_data,
                stock_info=stock_info,
                proximity_grid=PROXIMITY_GRID
            )

            # 손절 방식 비교
            comparison = optimizer.compare_stop_loss_types(results)

            # 최적 파라미터 찾기
            best_result = optimizer.find_best_parameters(results)
            if best_result:
                logger.info(
                    f"최적 파라미터: EMA5={best_result.ema5_proximity_pct}%, "
                    f"EMA8={best_result.ema8_proximity_pct}%, "
                    f"손절={best_result.stop_loss_type.value}, "
                    f"PF={best_result.profit_factor:.2f}"
                )

            # 결과 출력
            print_optimization_top_results(results)

            # 엑셀 저장
            if args.output:
                # 최적 설정으로 다시 실행하여 상세 결과 저장
                best_config = EMASplitBuyConfig(
                    ema5_proximity_pct=best_result.ema5_proximity_pct,
                    ema8_proximity_pct=best_result.ema8_proximity_pct,
                    stop_loss_type=best_result.stop_loss_type
                )
                detector = SignalDetector(best_config)
                simulator = TradeSimulator(best_config)

                all_trades = []
                all_signals = []
                for code, df in stocks_data.items():
                    name = stock_info.get(code, code)
                    signals = detector.detect_first_buy_signals(df, code, name)
                    trades = simulator.simulate_trades(df, signals, code, name)
                    all_trades.extend(trades)
                    all_signals.extend(signals)

                summary = simulator.calculate_summary(all_trades)

                exporter = ExcelExporter(logger)
                exporter.export(
                    output_path=args.output,
                    config=best_config,
                    trades=all_trades,
                    signals=all_signals,
                    summary=summary,
                    optimization_results=results
                )

        else:
            # 단일 설정 모드
            if config.use_3min_real:
                logger.info(f"실제 3분봉 청산 모드: EMA5={config.ema5_proximity_pct}%, EMA8={config.ema8_proximity_pct}%")
            elif config.use_ema3_exit:
                logger.info(f"EMA3 이탈 청산 모드: EMA5={config.ema5_proximity_pct}%, EMA8={config.ema8_proximity_pct}%")
            elif config.use_3min_exit:
                logger.info(f"3분봉 청산 모드: EMA5={config.ema5_proximity_pct}%, EMA8={config.ema8_proximity_pct}%")
            else:
                logger.info(f"단일 설정 모드: EMA5={config.ema5_proximity_pct}%, EMA8={config.ema8_proximity_pct}%")

            detector = SignalDetector(config, logger)
            simulator = TradeSimulator(config, logger)

            all_trades = []
            all_signals = []

            for code, df in stocks_data.items():
                name = stock_info.get(code, code)

                # 1차 매수 신호 탐지
                signals = detector.detect_first_buy_signals(df, code, name)
                all_signals.extend(signals)

                # 거래 시뮬레이션
                if config.use_3min_real:
                    # 실제 3분봉 청산 로직 (Phase 2 Real)
                    trades = await simulator.simulate_trades_3min_real(
                        daily_df=df,
                        signals=signals,
                        stock_code=code,
                        stock_name=name,
                        data_loader=data_loader
                    )
                elif config.use_ema3_exit:
                    # EMA3 이탈 청산 로직 (Phase 3)
                    trades = simulator.simulate_trades_ema3(
                        df=df,
                        signals=signals,
                        stock_code=code,
                        stock_name=name
                    )
                elif config.use_3min_exit:
                    # 3분봉 청산 로직 사용 (V6.2-A)
                    trades = simulator.simulate_trades_3min(
                        daily_df=df,
                        signals=signals,
                        stock_code=code,
                        stock_name=name,
                        data_loader=data_loader
                    )
                else:
                    # 기존 일봉 청산 로직
                    trades = simulator.simulate_trades(df, signals, code, name)
                all_trades.extend(trades)

            # 결과 집계
            summary = simulator.calculate_summary(all_trades)

            # 콘솔 출력
            print_console_summary(config, summary)

            # 월별 통계 콘솔 출력
            if args.monthly and all_trades:
                print_monthly_summary(all_trades)

            # 엑셀 저장
            if args.output:
                exporter = ExcelExporter(logger)
                exporter.export(
                    output_path=args.output,
                    config=config,
                    trades=all_trades,
                    signals=all_signals,
                    summary=summary,
                    include_monthly=args.monthly
                )

        logger.info("백테스트 완료")


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="EMA_SPLIT_BUY 백테스트")

    parser.add_argument(
        "--ema5",
        type=float,
        default=1.0,
        help="5일선 근접 기준 %% (기본: 1.0)"
    )
    parser.add_argument(
        "--ema8",
        type=float,
        default=1.0,
        help="8일선 근접 기준 %% (기본: 1.0)"
    )
    parser.add_argument(
        "--stop",
        choices=["fixed", "atr"],
        default="fixed",
        help="손절 방식: fixed (고정 5%%), atr (ATR TS) (기본: fixed)"
    )
    parser.add_argument(
        "--optimize",
        action="store_true",
        help="최적화 모드 (그리드 서치)"
    )
    parser.add_argument(
        "--3min",
        dest="use_3min",
        action="store_true",
        help="3분봉 청산 로직 사용 (V6.2-A)"
    )
    parser.add_argument(
        "--ema3",
        dest="use_ema3",
        action="store_true",
        help="EMA3 이탈 청산 로직 사용 (Phase 3)"
    )
    parser.add_argument(
        "--3min-real",
        dest="use_3min_real",
        action="store_true",
        help="실제 3분봉 데이터 청산 로직 사용 (Phase 2 Real)"
    )
    parser.add_argument(
        "--monthly",
        action="store_true",
        help="월별 수익률 분석 포함"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="엑셀 출력 파일 경로"
    )

    args = parser.parse_args()

    # 비동기 실행
    asyncio.run(run_backtest(args))


if __name__ == "__main__":
    main()
