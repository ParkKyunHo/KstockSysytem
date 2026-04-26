# -*- coding: utf-8 -*-
"""
Daily Equity Curve - Trade Simulator

거래 시뮬레이션 (추가매수, ATR 트레일링 청산)
"""

from datetime import date
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .config import BacktestConfig, Trade, ExitType


class TradeSimulator:
    """
    거래 시뮬레이터

    - 진입: 신호 발생일 종가 매수
    - 추가매수: 평균단가 -6% 도달 시 동일비중
    - 청산:
      1순위: 평균단가 -10% 손절 (장중 저가 기준)
      2순위: ATR 트레일링 스탑 (종가 기준)
    """

    def __init__(self, config: BacktestConfig, logger=None):
        self.config = config
        self.logger = logger or self._default_logger()

    def _default_logger(self):
        import logging
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"
            ))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def simulate(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame,
        signals: List[Tuple[date, int]]
    ) -> List[Trade]:
        """
        종목별 거래 시뮬레이션

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            df: 지표가 계산된 일봉 DataFrame
            signals: [(신호일, 종가), ...] 리스트

        Returns:
            거래 기록 리스트
        """
        trades = []
        current_trade: Optional[Trade] = None

        # 날짜 인덱스 매핑
        df = df.sort_values("date").reset_index(drop=True)
        date_to_idx = {
            (row["date"].date() if isinstance(row["date"], pd.Timestamp) else row["date"]): idx
            for idx, row in df.iterrows()
        }

        # 신호 날짜 집합
        signal_dates = {s[0] for s in signals}

        for idx, row in df.iterrows():
            current_date = row["date"]
            if isinstance(current_date, pd.Timestamp):
                current_date = current_date.date()

            # 포지션이 없을 때: 신호 확인
            if current_trade is None:
                if current_date in signal_dates:
                    # 신호 발생 → 종가 매수
                    entry_price = int(row["close"])
                    entry_quantity = self._calculate_quantity(
                        entry_price,
                        self.config.investment_per_trade
                    )

                    if entry_quantity > 0:
                        current_trade = Trade(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            entry_date=current_date,
                            entry_price=entry_price,
                            entry_quantity=entry_quantity,
                            avg_price=entry_price,
                            highest_high=int(row["high"]),
                            trailing_stop=self._calc_initial_stop(entry_price),
                            current_multiplier=self.config.atr_mult_default
                        )
                continue

            # 포지션 보유 중
            # 1. 고정 손절 확인 (-10%, 장중 저가 기준)
            hard_stop_price = int(current_trade.avg_price * (1 + self.config.hard_stop_rate))
            if row["low"] <= hard_stop_price:
                # 손절 체결
                current_trade.exit_date = current_date
                current_trade.exit_price = hard_stop_price
                current_trade.exit_type = ExitType.HARD_STOP
                self._finalize_trade(current_trade, df, idx)
                trades.append(current_trade)
                current_trade = None
                continue

            # 2. 추가매수 확인 (장중 저가 기준)
            if current_trade.addon_count < self.config.max_addon_count:
                addon_trigger_price = int(
                    current_trade.avg_price * (1 + self.config.addon_trigger)
                )
                if row["low"] <= addon_trigger_price:
                    # 추가매수 체결
                    addon_price = addon_trigger_price
                    addon_quantity = self._calculate_quantity(
                        addon_price,
                        self.config.investment_per_trade
                    )

                    if addon_quantity > 0:
                        current_trade.addon_date = current_date
                        current_trade.addon_price = addon_price
                        current_trade.addon_quantity = addon_quantity
                        current_trade.addon_count += 1

                        # 평균단가 재계산
                        total_cost = (
                            current_trade.entry_price * current_trade.entry_quantity +
                            addon_price * addon_quantity
                        )
                        total_qty = current_trade.entry_quantity + addon_quantity
                        current_trade.avg_price = int(total_cost / total_qty)

                        # 손절가 재조정 (신규 평균단가 기준)
                        hard_stop_price = int(
                            current_trade.avg_price * (1 + self.config.hard_stop_rate)
                        )

                        self.logger.debug(
                            f"{stock_code} 추가매수: {addon_price:,}원 x {addon_quantity}주, "
                            f"평균단가: {current_trade.avg_price:,}원"
                        )

            # 3. ATR 트레일링 스탑 업데이트 및 청산 확인
            current_trade = self._update_trailing_stop(current_trade, df, idx)

            # 종가 기준 ATR TS 이탈 확인
            if row["close"] < current_trade.trailing_stop:
                current_trade.exit_date = current_date
                current_trade.exit_price = int(row["close"])
                current_trade.exit_type = ExitType.ATR_TS
                self._finalize_trade(current_trade, df, idx)
                trades.append(current_trade)
                current_trade = None
                continue

        # 데이터 종료 시 미청산 포지션 처리
        if current_trade is not None:
            last_row = df.iloc[-1]
            last_date = last_row["date"]
            if isinstance(last_date, pd.Timestamp):
                last_date = last_date.date()

            current_trade.exit_date = last_date
            current_trade.exit_price = int(last_row["close"])
            current_trade.exit_type = ExitType.END_OF_DATA
            self._finalize_trade(current_trade, df, len(df) - 1)
            trades.append(current_trade)

        return trades

    def _calculate_quantity(self, price: int, investment: int) -> int:
        """매수 수량 계산"""
        if price <= 0:
            return 0
        return investment // price

    def _calc_initial_stop(self, entry_price: int) -> int:
        """초기 트레일링 스탑 (진입가 기준)"""
        return int(entry_price * (1 + self.config.hard_stop_rate))

    def _update_trailing_stop(
        self,
        trade: Trade,
        df: pd.DataFrame,
        current_idx: int
    ) -> Trade:
        """
        ATR 트레일링 스탑 업데이트

        - BasePrice = Highest(high, 20)
        - R-Multiple에 따라 배수 축소
        - TrailingStop = max(prev_stop, BasePrice - ATR × Multiplier)
        """
        row = df.iloc[current_idx]

        # 고점 갱신
        if row["high"] > trade.highest_high:
            trade.highest_high = int(row["high"])

        # R-Multiple 계산 (리스크 10% 기준)
        current_price = int(row["close"])
        initial_risk = trade.avg_price * self.config.risk_rate
        if initial_risk > 0:
            trade.r_multiple = (current_price - trade.avg_price) / initial_risk
        else:
            trade.r_multiple = 0.0

        # ATR 배수 결정 (단방향 축소)
        new_mult = self._get_multiplier(trade.r_multiple, trade.current_multiplier)
        if new_mult < trade.current_multiplier:
            trade.current_multiplier = new_mult

        # ATR 값
        atr = row.get("atr", 0)
        if pd.isna(atr) or atr <= 0:
            return trade

        # BasePrice 계산 (rolling max 사용)
        start_idx = max(0, current_idx - self.config.base_price_period + 1)
        base_price = int(df.iloc[start_idx:current_idx + 1]["high"].max())

        # 새 트레일링 스탑
        new_stop = int(base_price - (atr * trade.current_multiplier))

        # 상향 단방향 (절대 하락 금지)
        trade.trailing_stop = max(trade.trailing_stop, new_stop)

        # 고정 손절가보다 낮으면 고정 손절가 사용
        hard_stop = int(trade.avg_price * (1 + self.config.hard_stop_rate))
        if trade.trailing_stop < hard_stop:
            trade.trailing_stop = hard_stop

        return trade

    def _get_multiplier(self, r_multiple: float, current_mult: float) -> float:
        """R-Multiple에 따른 ATR 배수 결정 (단방향 축소)"""
        mult = current_mult

        if r_multiple >= 5:
            mult = min(mult, self.config.atr_mult_5r)
        elif r_multiple >= 3:
            mult = min(mult, self.config.atr_mult_3r)
        elif r_multiple >= 2:
            mult = min(mult, self.config.atr_mult_2r)
        elif r_multiple >= 1:
            mult = min(mult, self.config.atr_mult_1r)

        return mult

    def _finalize_trade(self, trade: Trade, df: pd.DataFrame, exit_idx: int) -> None:
        """거래 완료 처리 (비용 계산)"""
        # 보유일
        entry_idx = None
        for idx, row in df.iterrows():
            row_date = row["date"]
            if isinstance(row_date, pd.Timestamp):
                row_date = row_date.date()
            if row_date == trade.entry_date:
                entry_idx = idx
                break

        if entry_idx is not None:
            trade.holding_days = exit_idx - entry_idx
        else:
            trade.holding_days = 0

        # 총 투자금
        entry_cost = trade.entry_price * trade.entry_quantity
        addon_cost = (trade.addon_price or 0) * trade.addon_quantity
        total_investment = entry_cost + addon_cost

        # 총 수량
        total_qty = trade.total_quantity

        # 매도 금액
        exit_amount = trade.exit_price * total_qty

        # 세전 손익
        trade.gross_pnl = exit_amount - total_investment

        # 비용 계산
        # 매수 슬리피지 (진입 + 추가매수)
        buy_slippage = int(total_investment * self.config.slippage_rate)

        # 매수 수수료
        buy_commission = int(total_investment * self.config.commission_rate)

        # 매도 슬리피지
        sell_slippage = int(exit_amount * self.config.slippage_rate)

        # 매도 수수료
        sell_commission = int(exit_amount * self.config.commission_rate)

        # 거래세
        tax = int(exit_amount * self.config.tax_rate)

        trade.total_cost = buy_slippage + buy_commission + sell_slippage + sell_commission + tax

        # 순손익
        trade.net_pnl = trade.gross_pnl - trade.total_cost

        # 수익률 (%)
        if total_investment > 0:
            trade.return_pct = (trade.net_pnl / total_investment) * 100
        else:
            trade.return_pct = 0.0

    def simulate_all(
        self,
        stocks: List[Dict[str, str]],
        daily_data: Dict[str, pd.DataFrame],
        all_signals: Dict[str, List[Tuple[date, int]]]
    ) -> List[Trade]:
        """
        모든 종목 시뮬레이션

        Args:
            stocks: 종목 정보 리스트
            daily_data: {stock_code: DataFrame}
            all_signals: {stock_code: [(신호일, 종가), ...]}

        Returns:
            전체 거래 기록 리스트
        """
        all_trades = []
        stock_name_map = {s["stock_code"]: s["stock_name"] for s in stocks}

        for stock_code, signals in all_signals.items():
            if stock_code not in daily_data:
                continue

            df = daily_data[stock_code]
            stock_name = stock_name_map.get(stock_code, "")

            trades = self.simulate(stock_code, stock_name, df, signals)
            all_trades.extend(trades)

            if trades:
                self.logger.debug(f"{stock_code} {stock_name}: {len(trades)}건 거래")

        # 청산일 기준 정렬
        all_trades.sort(key=lambda t: t.exit_date or t.entry_date)

        self.logger.info(f"전체 시뮬레이션 완료: {len(all_trades)}건 거래")
        return all_trades
