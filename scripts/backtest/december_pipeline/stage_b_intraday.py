# -*- coding: utf-8 -*-
"""
December Pipeline - Stage B: Intraday Strategy Test

이벤트 당일 3분봉에서 SNIPER_TRAP 신호 탐지 및 청산 시뮬레이션
"""

from datetime import date
from typing import List, Dict, Tuple
import pandas as pd

from .config import PipelineConfig, Trade, TradeSummary
from .data_loader import DataLoader
from .strategy import SniperTrapStrategy


class StageBProcessor:
    """Stage B: 3분봉 전략 테스트"""

    def __init__(
        self,
        config: PipelineConfig,
        data_loader: DataLoader,
        strategy: SniperTrapStrategy,
        logger
    ):
        self.config = config
        self.loader = data_loader
        self.strategy = strategy
        self.logger = logger

    async def run(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Stage B 실행"""
        self.logger.info("=" * 60)
        self.logger.info("[Stage B] 3분봉 전략 테스트 시작")
        self.logger.info("=" * 60)

        # 1. Stage A 결과 로드
        event_days_df, event_summary_df = self._load_stage_a_results()

        if event_days_df.empty:
            self.logger.error("Stage A 결과 없음. 먼저 Stage A를 실행하세요.")
            return pd.DataFrame(), pd.DataFrame()

        # 2. 이벤트 종목 목록 추출
        event_tickers = self._get_event_tickers(event_summary_df)
        self.logger.info(f"이벤트 종목 수: {len(event_tickers)}")

        # 3. 종목/일자별 처리
        all_trades = []
        processed = 0
        failed = []

        # 종목-날짜 쌍 생성
        ticker_dates = self._get_ticker_date_pairs(event_days_df)
        total = len(ticker_dates)

        # hold_if_profitable 모드 확인
        use_extended = self.config.hold_if_profitable
        if use_extended:
            self.logger.info(f"[확장 모드] 수익 시 익일 이월 (최대 {self.config.max_hold_days}일)")

        for ticker, event_date, stock_name in ticker_dates:
            try:
                if use_extended:
                    trades = await self._process_ticker_date_extended(ticker, event_date, stock_name)
                else:
                    trades = await self._process_ticker_date(ticker, event_date, stock_name)
                all_trades.extend(trades)
                processed += 1
            except Exception as e:
                self.logger.warning(f"{ticker} @ {event_date}: 처리 실패 - {e}")
                failed.append((ticker, event_date, str(e)))

            if processed % 10 == 0:
                self.logger.info(f"진행: {processed}/{total}")

        # 4. 거래 DataFrame 생성
        if all_trades:
            trades_df = pd.DataFrame([{
                "ticker": t.ticker,
                "stock_name": t.stock_name,
                "event_date": t.event_date,
                "entry_dt": t.entry_dt,
                "entry_px": t.entry_px,
                "exit_dt": t.exit_dt,
                "exit_px": t.exit_px,
                "return": t.return_pct,
                "mfe": t.mfe,
                "mae": t.mae,
                "holding_bars": t.holding_bars,
                "exit_type": t.exit_type,
                "gross_pnl": t.gross_pnl,
                "total_cost": t.total_cost,
                "net_pnl": t.net_pnl
            } for t in all_trades])
            trades_df.sort_values(["event_date", "ticker"], inplace=True)
        else:
            trades_df = pd.DataFrame(columns=[
                "ticker", "stock_name", "event_date", "entry_dt", "entry_px",
                "exit_dt", "exit_px", "return", "mfe", "mae", "holding_bars",
                "exit_type", "gross_pnl", "total_cost", "net_pnl"
            ])

        # 5. 요약 생성
        summary_df = self._create_summary(trades_df)

        # 6. 검증 로그
        self._print_validation_log(ticker_dates, trades_df, failed)

        # 7. CSV 저장
        trades_df.to_csv(self.config.trades_path, index=False, encoding="utf-8-sig")
        summary_df.to_csv(self.config.summary_path, index=False, encoding="utf-8-sig")

        self.logger.info(f"trades.csv 저장: {self.config.trades_path}")
        self.logger.info(f"summary.csv 저장: {self.config.summary_path}")

        return trades_df, summary_df

    def _load_stage_a_results(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Stage A 결과 로드"""
        event_days_path = self.config.event_days_path
        event_summary_path = self.config.event_summary_path

        if not event_days_path.exists():
            return pd.DataFrame(), pd.DataFrame()

        try:
            event_days_df = pd.read_csv(event_days_path, encoding="utf-8-sig")
            event_summary_df = pd.read_csv(event_summary_path, encoding="utf-8-sig")
            return event_days_df, event_summary_df
        except Exception as e:
            self.logger.error(f"Stage A 결과 로드 실패: {e}")
            return pd.DataFrame(), pd.DataFrame()

    def _get_event_tickers(self, event_summary_df: pd.DataFrame) -> List[str]:
        """이벤트 종목 목록 추출 (hit_count >= 1)"""
        if event_summary_df.empty:
            return []

        filtered = event_summary_df[event_summary_df["hit_count"] >= 1]
        return filtered["ticker"].tolist()

    def _get_ticker_date_pairs(
        self,
        event_days_df: pd.DataFrame
    ) -> List[Tuple[str, date, str]]:
        """종목-날짜 쌍 생성"""
        pairs = []
        for _, row in event_days_df.iterrows():
            ticker = str(row["ticker"]).zfill(6)
            event_date = pd.to_datetime(row["date"]).date()
            stock_name = row.get("stock_name", "")
            pairs.append((ticker, event_date, stock_name))
        return pairs

    async def _process_ticker_date(
        self,
        ticker: str,
        event_date: date,
        stock_name: str
    ) -> List[Trade]:
        """단일 종목/날짜 처리"""
        # 3분봉 데이터 로드
        minute_df = await self.loader.load_minute_candles(ticker, event_date)

        if minute_df is None or len(minute_df) < self.config.min_minute_candles:
            self.logger.debug(f"{ticker} @ {event_date}: 분봉 부족")
            return []

        # 신호 탐지
        signals = self.strategy.detect_signals(
            minute_df, ticker, stock_name, first_only=True
        )

        if not signals:
            self.logger.debug(f"{ticker} @ {event_date}: 신호 없음")
            return []

        # 거래 시뮬레이션
        trades = []
        for signal in signals:
            trade = self.strategy.simulate_trade(signal, minute_df, event_date)
            if trade:
                trades.append(trade)
                self.logger.debug(
                    f"{ticker} @ {event_date}: "
                    f"진입 {signal.signal_price:,} → 청산 {trade.exit_px:,} "
                    f"({trade.return_pct:+.1f}%) [{trade.exit_type}]"
                )

        return trades

    async def _process_ticker_date_extended(
        self,
        ticker: str,
        event_date: date,
        stock_name: str
    ) -> List[Trade]:
        """
        단일 종목/날짜 처리 (확장 모드: 수익 시 익일 이월)

        로직:
        1. 당일 분봉에서 신호 탐지 + 시뮬레이션
        2. END_OF_DATA로 종료 + 수익 중이면 → 다일 분봉 로드하여 확장 시뮬레이션
        3. 그 외 청산 유형은 그대로 반환
        """
        # 1. 당일 분봉 로드 및 신호 탐지
        minute_df = await self.loader.load_minute_candles(ticker, event_date)

        if minute_df is None or len(minute_df) < self.config.min_minute_candles:
            self.logger.debug(f"{ticker} @ {event_date}: 분봉 부족")
            return []

        signals = self.strategy.detect_signals(
            minute_df, ticker, stock_name, first_only=True
        )

        if not signals:
            self.logger.debug(f"{ticker} @ {event_date}: 신호 없음")
            return []

        # 2. 당일 시뮬레이션
        trades = []
        for signal in signals:
            trade = self.strategy.simulate_trade(signal, minute_df, event_date)

            if trade is None:
                continue

            # 3. END_OF_DATA + 수익 중 → 확장 시뮬레이션
            if trade.exit_type == "END_OF_DATA" and trade.return_pct > 0:
                self.logger.debug(
                    f"{ticker} @ {event_date}: 수익 중 ({trade.return_pct:+.1f}%) → 익일 이월"
                )

                # 다일 분봉 로드
                multiday_df = await self.loader.load_minute_candles_multiday(
                    ticker, event_date, self.config.max_hold_days
                )

                if multiday_df is not None and len(multiday_df) > len(minute_df):
                    # 확장 시뮬레이션
                    extended_trade = self.strategy.simulate_trade_extended(
                        signal, multiday_df, event_date
                    )

                    if extended_trade:
                        self.logger.debug(
                            f"{ticker} @ {event_date}: 확장 시뮬레이션 완료 "
                            f"→ {extended_trade.exit_px:,} ({extended_trade.return_pct:+.1f}%) "
                            f"[{extended_trade.exit_type}] 보유 {extended_trade.holding_bars}봉"
                        )
                        trades.append(extended_trade)
                        continue

            # 그 외 (HARD_STOP, ATR_TS, 손실 중 END_OF_DATA)
            trades.append(trade)
            self.logger.debug(
                f"{ticker} @ {event_date}: "
                f"진입 {signal.signal_price:,} → 청산 {trade.exit_px:,} "
                f"({trade.return_pct:+.1f}%) [{trade.exit_type}]"
            )

        return trades

    def _create_summary(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """종목별 거래 요약 생성"""
        if trades_df.empty:
            return pd.DataFrame(columns=[
                "ticker", "stock_name", "trades", "winrate", "avg_return",
                "total_return", "max_dd", "expectancy"
            ])

        summaries = []
        for (ticker, stock_name), group in trades_df.groupby(["ticker", "stock_name"]):
            trades_count = len(group)
            wins = len(group[group["return"] > 0])
            winrate = (wins / trades_count * 100) if trades_count > 0 else 0

            avg_return = group["return"].mean()
            total_return = group["return"].sum()

            # 최대 낙폭 (누적 수익 기준)
            cumsum = group["return"].cumsum()
            max_dd = (cumsum - cumsum.cummax()).min()

            # 기대값: 평균 수익률
            expectancy = avg_return

            summaries.append({
                "ticker": ticker,
                "stock_name": stock_name,
                "trades": trades_count,
                "winrate": round(winrate, 1),
                "avg_return": round(avg_return, 2),
                "total_return": round(total_return, 2),
                "max_dd": round(max_dd, 2),
                "expectancy": round(expectancy, 2)
            })

        summary_df = pd.DataFrame(summaries)
        summary_df.sort_values("total_return", ascending=False, inplace=True)

        return summary_df

    def _print_validation_log(
        self,
        ticker_dates: List[Tuple],
        trades_df: pd.DataFrame,
        failed: List[Tuple]
    ):
        """검증 로그 출력"""
        print("\n" + "=" * 60)
        print("[Stage B] 검증 로그")
        print("=" * 60)

        print(f"이벤트 종목-날짜 쌍: {len(ticker_dates)}")

        if trades_df.empty:
            print("거래 수: 0")
        else:
            print(f"거래 수: {len(trades_df)}")

            unique_tickers = trades_df["ticker"].nunique()
            print(f"거래 발생 종목: {unique_tickers}")

            # 전체 통계
            wins = len(trades_df[trades_df["return"] > 0])
            total = len(trades_df)
            winrate = (wins / total * 100) if total > 0 else 0

            avg_return = trades_df["return"].mean()
            total_return = trades_df["return"].sum()

            print(f"\n[전체 통계]")
            print(f"  승률: {winrate:.1f}% ({wins}/{total})")
            print(f"  평균 수익률: {avg_return:.2f}%")
            print(f"  총 수익률: {total_return:.2f}%")

            # 청산 유형별
            print(f"\n[청산 유형]")
            for exit_type in ["HARD_STOP", "ATR_TS", "MAX_HOLDING", "END_OF_DATA"]:
                count = len(trades_df[trades_df["exit_type"] == exit_type])
                pct = (count / total * 100) if total > 0 else 0
                print(f"  {exit_type}: {count} ({pct:.1f}%)")

            # TOP 10 수익 거래
            print(f"\n[TOP 10 수익 거래]")
            top10 = trades_df.nlargest(10, "return")
            for _, row in top10.iterrows():
                print(f"  {row['ticker']} @ {row['event_date']}: {row['return']:+.2f}% [{row['exit_type']}]")

        # 실패 목록
        if failed:
            print(f"\n[실패 종목] ({len(failed)}건)")
            for ticker, event_date, reason in failed[:10]:
                print(f"  {ticker} @ {event_date}: {reason}")

        print("=" * 60)
