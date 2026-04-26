# -*- coding: utf-8 -*-
"""
V7 Purple 3분봉 데이트레이딩 백테스트 메인

실행 방법:
    # Stage A + B (API 조회)
    "C:\\Program Files\\Python311\\python.exe" -m scripts.backtest.v7_intraday.main --fetch

    # Stage B만 (캐시 사용)
    "C:\\Program Files\\Python311\\python.exe" -m scripts.backtest.v7_intraday.main --use-cache

    # 특정 종목만 테스트
    "C:\\Program Files\\Python311\\python.exe" -m scripts.backtest.v7_intraday.main --stock 005930

    # 당일 청산만
    "C:\\Program Files\\Python311\\python.exe" -m scripts.backtest.v7_intraday.main --intraday-only
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.backtest.v7_intraday.config import BacktestConfig, EventDay, Trade
from scripts.backtest.v7_intraday.data_loader import DataLoader
from scripts.backtest.v7_intraday.event_filter import EventFilter
from scripts.backtest.v7_intraday.v7_signal_detector import V7SignalDetector
from scripts.backtest.v7_intraday.trade_simulator import TradeSimulator
from scripts.backtest.v7_intraday.analyzer import BacktestAnalyzer
from scripts.backtest.v7_intraday.exporter import ExcelExporter


def setup_logging() -> logging.Logger:
    """로깅 설정"""
    logger = logging.getLogger("v7_backtest")
    logger.setLevel(logging.INFO)

    # 콘솔 핸들러
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(handler)

    return logger


class V7BacktestRunner:
    """V7 백테스트 실행기"""

    def __init__(self, config: BacktestConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger

        # API 클라이언트 초기화 (나중에 설정)
        self._client = None
        self._market_api = None

        # 모듈 초기화
        self.data_loader = DataLoader(config, None, logger)
        self.event_filter = EventFilter(config, logger)
        self.signal_detector = V7SignalDetector(config, logger)
        self.trade_simulator = TradeSimulator(config, logger)
        self.analyzer = BacktestAnalyzer(config, logger)
        self.exporter = ExcelExporter(config, logger)

    async def init_api(self):
        """API 클라이언트 초기화 (async with 진입)"""
        try:
            from src.api.client import KiwoomAPIClient
            from src.api.endpoints.market import MarketAPI

            self._client = KiwoomAPIClient()
            # async with 진입 - __aenter__ 호출
            await self._client.__aenter__()

            self._market_api = MarketAPI(self._client)

            self.data_loader._client = self._client
            self.data_loader.set_market_api(self._market_api)

            self.logger.info("API 클라이언트 초기화 완료")
            return True
        except Exception as e:
            self.logger.error(f"API 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def cleanup_api(self):
        """API 클라이언트 정리 (async with 종료)"""
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass

    async def run_stage_a(self) -> List[EventDay]:
        """Stage A: 이벤트일 필터링"""
        self.logger.info("=" * 60)
        self.logger.info("Stage A: 이벤트일 필터링 시작")
        self.logger.info("=" * 60)

        # 종목 목록 로드
        stocks = self.data_loader.load_test_stocks()
        if not stocks:
            self.logger.error("종목 목록 없음")
            return []

        # 일봉 데이터 배치 로드
        self.logger.info(f"일봉 데이터 로드 시작 ({len(stocks)}개 종목)")
        daily_data = await self.data_loader.load_daily_batch(stocks)
        self.logger.info(f"일봉 데이터 로드 완료: {len(daily_data)}개 종목")

        # 이벤트일 필터링
        events, summary_df = self.event_filter.filter_all_stocks(stocks, daily_data)

        # 저장
        self.event_filter.save_event_days(events, summary_df)

        # 통계 출력
        stats = self.event_filter.get_event_stats(events)
        self.logger.info(f"이벤트 통계:")
        self.logger.info(f"  - 총 이벤트: {stats.get('total_events', 0)}개")
        self.logger.info(f"  - 고유 날짜: {stats.get('unique_dates', 0)}일")
        self.logger.info(f"  - 고유 종목: {stats.get('unique_stocks', 0)}개")
        self.logger.info(f"  - 기간: {stats.get('date_range', 'N/A')}")

        return events

    async def run_stage_b(
        self,
        events: List[EventDay],
        intraday_only: bool = False,
        stock_filter: Optional[str] = None,
        parallel_workers: int = 10
    ) -> List[Trade]:
        """Stage B: V7 신호 탐지 및 거래 시뮬레이션 (병렬 처리)"""
        self.logger.info("=" * 60)
        self.logger.info("Stage B: V7 신호 탐지 및 거래 시뮬레이션 (병렬)")
        self.logger.info("=" * 60)

        if not events:
            self.logger.warning("이벤트 없음")
            return []

        # 종목 필터
        if stock_filter:
            events = [e for e in events if e.stock_code == stock_filter]
            self.logger.info(f"종목 필터 적용: {stock_filter} ({len(events)}개 이벤트)")

        total_events = len(events)
        self.logger.info(f"병렬 처리 시작: {total_events}개 이벤트, {parallel_workers} workers")

        # 진행 상황 추적
        progress = {"completed": 0, "signals": 0}
        progress_lock = asyncio.Lock()

        async def process_event(event: EventDay) -> Optional[Trade]:
            """단일 이벤트 처리"""
            try:
                # 분봉 데이터 로드
                if intraday_only:
                    df = await self.data_loader.load_minute_candles(
                        event.stock_code, event.date
                    )
                else:
                    df = await self.data_loader.load_minute_candles_multiday(
                        event.stock_code, event.date
                    )

                if df is None or len(df) < self.config.min_candles_for_signal:
                    return None

                # V7 신호 탐지 (첫 신호만)
                signal = self.signal_detector.get_first_signal(
                    event.stock_code, event.stock_name, df
                )

                if signal is None:
                    return None

                # 거래 시뮬레이션
                if intraday_only:
                    trade = self.trade_simulator.simulate_intraday_trade(
                        signal, df, event.date
                    )
                else:
                    trade = self.trade_simulator.simulate_trade(
                        signal, df, event.date
                    )

                return trade

            except Exception as e:
                self.logger.warning(f"{event.stock_code} @ {event.date} 처리 실패: {e}")
                return None

        async def process_with_semaphore(sem: asyncio.Semaphore, event: EventDay) -> Optional[Trade]:
            """세마포어로 동시 실행 제한"""
            async with sem:
                trade = await process_event(event)

                # 진행 상황 업데이트
                async with progress_lock:
                    progress["completed"] += 1
                    if trade:
                        progress["signals"] += 1

                    if progress["completed"] % 50 == 0:
                        self.logger.info(
                            f"진행: {progress['completed']}/{total_events} "
                            f"({progress['signals']} signals)"
                        )

                return trade

        # 병렬 실행
        semaphore = asyncio.Semaphore(parallel_workers)
        tasks = [process_with_semaphore(semaphore, event) for event in events]
        results = await asyncio.gather(*tasks)

        # 결과 필터링
        trades = [t for t in results if t is not None]

        # 중복 제거 (같은 종목, 같은 진입시간)
        # 원인: 각 event_day마다 5일치 분봉을 로드하여 동일 신호가 여러 번 카운트됨
        seen = set()
        unique_trades = []
        for trade in trades:
            key = (trade.stock_code, trade.entry_dt)
            if key not in seen:
                seen.add(key)
                unique_trades.append(trade)

        if len(trades) != len(unique_trades):
            self.logger.info(f"중복 제거: {len(trades)}건 → {len(unique_trades)}건")

        trades = unique_trades

        self.logger.info(f"Stage B 완료: {progress['signals']} signals → {len(trades)} trades")
        return trades

    def analyze_and_export(self, trades: List[Trade]):
        """결과 분석 및 출력"""
        self.logger.info("=" * 60)
        self.logger.info("결과 분석 및 출력")
        self.logger.info("=" * 60)

        if not trades:
            self.logger.warning("거래 없음")
            return

        # 분석
        report = self.analyzer.generate_full_report(trades)

        # 기본 통계 출력
        basic = report.get('basic_stats', {})
        self.logger.info(f"\n=== 백테스트 결과 요약 ===")
        self.logger.info(f"총 거래: {basic.get('total_trades', 0)}건")
        self.logger.info(f"승률: {basic.get('win_rate', 0):.1f}%")
        self.logger.info(f"평균 수익률: {basic.get('avg_return_pct', 0):+.2f}%")
        self.logger.info(f"총 수익률: {basic.get('total_return_pct', 0):+.2f}%")
        self.logger.info(f"Profit Factor: {basic.get('profit_factor', 0):.2f}")
        self.logger.info(f"MDD: {basic.get('max_drawdown_pct', 0):.2f}%")
        self.logger.info(f"순 손익: {basic.get('total_net_pnl', 0):,}원")

        # 청산 분석
        exit_analysis = report.get('exit_analysis', {})
        self.logger.info(f"\n=== 청산 유형 ===")
        for exit_type, data in exit_analysis.items():
            self.logger.info(
                f"  {exit_type}: {data.get('count', 0)}건 "
                f"({data.get('pct', 0):.1f}%) "
                f"평균 {data.get('avg_return', 0):+.2f}%"
            )

        # 저장
        self.analyzer.save_trades(trades)
        self.analyzer.save_summary(report)
        self.analyzer.save_stock_analysis(trades)

        # Excel 출력
        try:
            self.exporter.export_full_report(trades, report)
        except Exception as e:
            self.logger.warning(f"Excel 출력 실패: {e}")

    async def run(
        self,
        fetch: bool = False,
        use_cache: bool = False,
        intraday_only: bool = False,
        stock_filter: Optional[str] = None,
        parallel_workers: int = 10
    ):
        """백테스트 실행"""
        start_time = datetime.now()
        self.logger.info(f"V7 Purple 3분봉 백테스트 시작: {start_time}")
        self.logger.info(f"기간: {self.config.event_start} ~ {self.config.event_end}")
        self.logger.info(f"거래대금 필터: {self.config.min_trading_value / 1e9:.0f}억 이상")

        # API 초기화 (Stage B 분봉 조회에 필요)
        if not await self.init_api():
            self.logger.warning("API 초기화 실패 - 캐시된 데이터만 사용 가능")

        # Stage A
        if fetch:
            events = await self.run_stage_a()
        else:
            events = self.event_filter.load_event_days()
            if not events:
                self.logger.error("저장된 이벤트일 없음. --fetch 옵션 사용")
                return

        # Stage B
        trades = await self.run_stage_b(events, intraday_only, stock_filter, parallel_workers)

        # 분석 및 출력
        self.analyze_and_export(trades)

        # API 정리
        await self.cleanup_api()

        # 완료
        elapsed = datetime.now() - start_time
        self.logger.info(f"\n백테스트 완료: {elapsed}")


def parse_args():
    """CLI 인자 파싱"""
    parser = argparse.ArgumentParser(
        description="V7 Purple 3분봉 데이트레이딩 백테스트"
    )

    parser.add_argument(
        "--fetch",
        action="store_true",
        help="API에서 데이터 조회 (Stage A + B)"
    )

    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="캐시된 이벤트일 사용 (Stage B만)"
    )

    parser.add_argument(
        "--intraday-only",
        action="store_true",
        help="당일 청산만 (익일 이월 없음)"
    )

    parser.add_argument(
        "--stock",
        type=str,
        default=None,
        help="특정 종목만 테스트 (종목코드)"
    )

    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="시작일 (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="종료일 (YYYY-MM-DD)"
    )

    parser.add_argument(
        "--parallel",
        type=int,
        default=10,
        help="병렬 워커 수 (기본: 10)"
    )

    return parser.parse_args()


async def main():
    """메인 함수"""
    args = parse_args()
    logger = setup_logging()

    # 설정
    config = BacktestConfig()

    # 날짜 설정
    if args.start:
        from datetime import datetime as dt
        config.event_start = dt.strptime(args.start, "%Y-%m-%d").date()

    if args.end:
        from datetime import datetime as dt
        config.event_end = dt.strptime(args.end, "%Y-%m-%d").date()

    # 실행
    runner = V7BacktestRunner(config, logger)
    await runner.run(
        fetch=args.fetch,
        use_cache=args.use_cache,
        intraday_only=args.intraday_only,
        stock_filter=args.stock,
        parallel_workers=args.parallel
    )


if __name__ == "__main__":
    asyncio.run(main())
