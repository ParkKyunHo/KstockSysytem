# -*- coding: utf-8 -*-
"""
거래 시뮬레이터

분할 매수, 손절, 청산 로직 구현
- 1차 매수: 5일선 근접 시 50%
- 2차 매수: 8일선 근접 시 50% (1차 후 3영업일까지)
- 손절: 고정 5% 또는 ATR 트레일링 스탑
- 청산: 3영업일 종가 (진입일 제외)
"""

from datetime import date
from typing import List, Optional, Tuple, Dict
import pandas as pd

from .config import (
    EMASplitBuyConfig,
    SplitBuyPosition,
    SplitBuyTrade,
    SplitBuySignal,
    SplitBuyState,
    StopLossType,
    ExitReason,
    BacktestResult
)
from .indicators import (
    calculate_trailing_stop,
    is_near_ema8,
    calculate_indicators_3min,
    check_structure_warning,
    calculate_trailing_stop_3min
)


class TradeSimulator:
    """거래 시뮬레이터"""

    def __init__(self, config: EMASplitBuyConfig, logger=None):
        self.config = config
        self._logger = logger

    def simulate_trades(
        self,
        df: pd.DataFrame,
        signals: List[SplitBuySignal],
        stock_code: str,
        stock_name: str
    ) -> List[SplitBuyTrade]:
        """
        거래 시뮬레이션

        Args:
            df: 지표가 계산된 일봉 데이터
            signals: 1차 매수 신호 리스트 (EMA5 근접)
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            거래 결과 리스트
        """
        trades = []
        dates = sorted(df['date'].tolist())

        # 각 1차 신호에 대해 시뮬레이션
        for signal in signals:
            if signal.signal_type != "EMA5":
                continue  # 1차 매수는 EMA5만

            trade = self._simulate_single_trade(
                df=df,
                signal=signal,
                stock_code=stock_code,
                stock_name=stock_name,
                dates=dates
            )

            if trade and trade.is_complete:
                trades.append(trade)

        return trades

    def _simulate_single_trade(
        self,
        df: pd.DataFrame,
        signal: SplitBuySignal,
        stock_code: str,
        stock_name: str,
        dates: List[date]
    ) -> Optional[SplitBuyTrade]:
        """
        단일 거래 시뮬레이션

        Args:
            df: 지표가 계산된 일봉 데이터
            signal: 1차 매수 신호
            stock_code: 종목코드
            stock_name: 종목명
            dates: 날짜 리스트

        Returns:
            거래 결과
        """
        signal_date = signal.signal_date

        # 신호일 인덱스 찾기
        try:
            signal_idx = dates.index(signal_date)
        except ValueError:
            return None

        # 다음 영업일 (진입일) 확인
        if signal_idx + 1 >= len(dates):
            return None

        entry_date = dates[signal_idx + 1]
        entry_candle = df[df['date'] == entry_date]
        if entry_candle.empty:
            return None
        entry_candle = entry_candle.iloc[0]

        # 1차 매수: 진입일 시가 + 슬리피지
        first_entry_price = int(entry_candle['open'] * (1 + self.config.get_entry_cost_rate()))
        investment = self.config.investment_per_trade
        first_qty = int((investment * self.config.first_buy_ratio) // first_entry_price)

        if first_qty <= 0:
            return None

        # 포지션 생성
        position = SplitBuyPosition(
            stock_code=stock_code,
            stock_name=stock_name,
            first_buy_date=entry_date,
            first_buy_price=first_entry_price,
            first_buy_qty=first_qty,
            state=SplitBuyState.FIRST_ONLY
        )

        # ATR TS 모드일 경우 초기 트레일링 스탑 설정
        if self.config.stop_loss_type == StopLossType.ATR_TRAILING:
            hlc3 = entry_candle['hlc3']
            atr = entry_candle['atr14']
            initial_ts = calculate_trailing_stop(hlc3, atr, self.config.atr_mult)
            position.trailing_stop_price = initial_ts
            position.highest_price = int(entry_candle['high'])

        # 거래 객체 초기화
        trade = SplitBuyTrade(
            stock_code=stock_code,
            stock_name=stock_name,
            first_signal_date=signal_date,
            first_entry_date=entry_date,
            first_entry_price=first_entry_price,
            first_qty=first_qty
        )

        # 청산일 계산 (진입일 제외 3영업일 후)
        max_exit_date = self._get_nth_business_day_after(dates, entry_date, self.config.max_holding_days)

        # 진입일 다음날부터 시뮬레이션
        entry_idx = dates.index(entry_date)
        for i in range(entry_idx + 1, len(dates)):
            current_date = dates[i]
            candle = df[df['date'] == current_date]
            if candle.empty:
                continue
            candle = candle.iloc[0]

            # 2차 매수 체크 (1차 매수 후 3영업일까지)
            if position.state == SplitBuyState.FIRST_ONLY:
                days_since_entry = self._count_business_days(dates, entry_date, current_date)
                if days_since_entry <= self.config.max_holding_days:
                    # 8일선 근접 체크
                    close = candle['close']
                    ema8 = candle['ema8']
                    trading_value = candle.get('trading_value', 0)

                    if (trading_value >= self.config.min_trading_value and
                        is_near_ema8(close, ema8, self.config.ema8_proximity_pct)):

                        # 2차 매수 진입 (당일 종가 기준, 다음날 시가 진입)
                        if i + 1 < len(dates):
                            second_entry_date = dates[i + 1]
                            second_candle = df[df['date'] == second_entry_date]
                            if not second_candle.empty:
                                second_candle = second_candle.iloc[0]
                                second_entry_price = int(second_candle['open'] * (1 + self.config.get_entry_cost_rate()))
                                second_qty = int((investment * self.config.second_buy_ratio) // second_entry_price)

                                if second_qty > 0:
                                    position.add_second_buy(second_entry_date, second_entry_price, second_qty)
                                    trade.second_signal_date = current_date
                                    trade.second_entry_date = second_entry_date
                                    trade.second_entry_price = second_entry_price
                                    trade.second_qty = second_qty

            # 손절 체크
            exit_triggered, exit_reason = self._check_stop_loss(position, candle)
            if exit_triggered:
                exit_price = self._calculate_exit_price(candle, exit_reason)
                self._finalize_trade(trade, position, current_date, exit_price, exit_reason)
                return trade

            # ATR TS 업데이트
            if self.config.stop_loss_type == StopLossType.ATR_TRAILING:
                hlc3 = candle['hlc3']
                atr = candle['atr14']
                new_ts = calculate_trailing_stop(hlc3, atr, self.config.atr_mult)
                position.update_trailing_stop(new_ts)
                position.update_highest_price(int(candle['high']))

            # 최대 보유일 청산 (3영업일 종가)
            if max_exit_date and current_date >= max_exit_date:
                exit_price = int(candle['close'] * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade(trade, position, current_date, exit_price, ExitReason.MAX_HOLDING_3D)
                return trade

        # 데이터 끝까지 도달 (미완료)
        return None

    def _check_stop_loss(
        self,
        position: SplitBuyPosition,
        candle: pd.Series
    ) -> Tuple[bool, Optional[ExitReason]]:
        """
        손절 체크

        Args:
            position: 포지션
            candle: 현재 캔들

        Returns:
            (손절 여부, 청산 사유)
        """
        bar_low = int(candle['low'])
        current_price = int(candle['close'])

        if self.config.stop_loss_type == StopLossType.FIXED_5PCT:
            # 고정 5% 손절
            stop_price = int(position.avg_price * (1 + self.config.fixed_stop_rate / 100))
            if bar_low <= stop_price:
                return True, ExitReason.HARD_STOP_5PCT

        else:  # ATR_TRAILING
            # ATR 트레일링 스탑
            if position.trailing_stop_price and current_price <= position.trailing_stop_price:
                return True, ExitReason.ATR_TRAILING_STOP

        return False, None

    def _calculate_exit_price(
        self,
        candle: pd.Series,
        exit_reason: ExitReason
    ) -> int:
        """
        청산가 계산

        Args:
            candle: 현재 캔들
            exit_reason: 청산 사유

        Returns:
            청산가 (비용 포함)
        """
        if exit_reason == ExitReason.HARD_STOP_5PCT:
            # 손절가로 청산
            base_price = int(candle['low'])
        elif exit_reason == ExitReason.ATR_TRAILING_STOP:
            # 종가로 청산 (TS 이탈은 봉 마감 시점)
            base_price = int(candle['close'])
        else:  # MAX_HOLDING_3D
            # 종가로 청산
            base_price = int(candle['close'])

        # 청산 비용 적용
        return int(base_price * (1 - self.config.get_exit_cost_rate()))

    def _finalize_trade(
        self,
        trade: SplitBuyTrade,
        position: SplitBuyPosition,
        exit_date: date,
        exit_price: int,
        exit_reason: ExitReason
    ):
        """
        거래 완료 처리

        Args:
            trade: 거래 객체
            position: 포지션
            exit_date: 청산일
            exit_price: 청산가
            exit_reason: 청산 사유
        """
        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason

        # 총 수량 및 평균 매수가
        trade.total_qty = position.total_qty
        trade.avg_entry_price = position.avg_price

        # 보유일 계산
        trade.holding_days = (exit_date - position.first_buy_date).days

        # 손익 계산
        entry_cost = position.total_cost
        exit_value = exit_price * position.total_qty
        trade.gross_pnl = exit_value - entry_cost

        # 비용 계산
        trade.entry_cost = int(entry_cost * self.config.get_entry_cost_rate())
        trade.exit_cost = int(exit_value * self.config.get_exit_cost_rate())
        trade.total_cost = trade.entry_cost + trade.exit_cost

        trade.net_pnl = trade.gross_pnl - trade.total_cost

        # 수익률
        if entry_cost > 0:
            trade.return_rate = (trade.net_pnl / entry_cost) * 100
        else:
            trade.return_rate = 0

        # ATR TS 정보
        if self.config.stop_loss_type == StopLossType.ATR_TRAILING:
            trade.highest_ts = position.trailing_stop_price
            if position.highest_price and position.avg_price > 0:
                trade.max_profit_rate = (position.highest_price - position.avg_price) / position.avg_price * 100

    def _count_business_days(
        self,
        dates: List[date],
        start_date: date,
        end_date: date
    ) -> int:
        """
        두 날짜 사이의 영업일 수 (시작일 제외)

        Args:
            dates: 날짜 리스트
            start_date: 시작일
            end_date: 종료일

        Returns:
            영업일 수
        """
        count = 0
        for d in dates:
            if start_date < d <= end_date:
                count += 1
        return count

    def _get_nth_business_day_after(
        self,
        dates: List[date],
        start_date: date,
        n: int
    ) -> Optional[date]:
        """
        시작일로부터 n영업일 후 날짜 (시작일 제외)

        Args:
            dates: 날짜 리스트
            start_date: 시작일
            n: 영업일 수

        Returns:
            n영업일 후 날짜
        """
        count = 0
        for d in dates:
            if d > start_date:
                count += 1
                if count == n:
                    return d
        return None

    def calculate_summary(
        self,
        trades: List[SplitBuyTrade]
    ) -> Dict:
        """
        거래 통계 요약

        Args:
            trades: 거래 리스트

        Returns:
            통계 딕셔너리
        """
        if not trades:
            return {
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0,
                "total_net_pnl": 0,
                "avg_return": 0,
                "max_return": 0,
                "min_return": 0,
                "profit_factor": 0,
                "hard_stop_count": 0,
                "atr_ts_count": 0,
                "max_holding_count": 0,
                "avg_holding_days": 0
            }

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]

        total_profit = sum(t.net_pnl for t in wins)
        total_loss = abs(sum(t.net_pnl for t in losses))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        hard_stop_count = len([t for t in trades if t.exit_reason == ExitReason.HARD_STOP_5PCT])
        atr_ts_count = len([t for t in trades if t.exit_reason == ExitReason.ATR_TRAILING_STOP])
        max_holding_count = len([t for t in trades if t.exit_reason == ExitReason.MAX_HOLDING_3D])

        return {
            "trade_count": len(trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": (len(wins) / len(trades)) * 100 if trades else 0,
            "total_net_pnl": sum(t.net_pnl for t in trades),
            "avg_return": sum(t.return_rate for t in trades) / len(trades),
            "max_return": max(t.return_rate for t in trades),
            "min_return": min(t.return_rate for t in trades),
            "profit_factor": profit_factor,
            "hard_stop_count": hard_stop_count,
            "atr_ts_count": atr_ts_count,
            "max_holding_count": max_holding_count,
            "avg_holding_days": sum(t.holding_days for t in trades) / len(trades)
        }

    # =========================================================================
    # Phase 2: 3분봉 청산 시뮬레이션 (V6.2-A 로직)
    # =========================================================================

    def simulate_trades_3min(
        self,
        daily_df: pd.DataFrame,
        signals: List[SplitBuySignal],
        stock_code: str,
        stock_name: str,
        data_loader=None
    ) -> List[SplitBuyTrade]:
        """
        3분봉 청산 로직을 적용한 거래 시뮬레이션

        진입: 일봉 기준 (기존 로직)
        청산: 3분봉 기준 (V6.2-A 로직)
            1. 고정 손절 -4%
            2. ATR 트레일링 스탑 (6.0 / 4.5)
            3. 최대 보유 60일

        Args:
            daily_df: 지표가 계산된 일봉 데이터
            signals: 1차 매수 신호 리스트
            stock_code: 종목코드
            stock_name: 종목명
            data_loader: DataLoader 인스턴스 (3분봉 시뮬레이션용)

        Returns:
            거래 결과 리스트
        """
        trades = []
        dates = sorted(daily_df['date'].tolist())

        for signal in signals:
            if signal.signal_type != "EMA5":
                continue

            trade = self._simulate_single_trade_3min(
                daily_df=daily_df,
                signal=signal,
                stock_code=stock_code,
                stock_name=stock_name,
                dates=dates,
                data_loader=data_loader
            )

            if trade and trade.is_complete:
                trades.append(trade)

        return trades

    def _simulate_single_trade_3min(
        self,
        daily_df: pd.DataFrame,
        signal: SplitBuySignal,
        stock_code: str,
        stock_name: str,
        dates: List[date],
        data_loader=None
    ) -> Optional[SplitBuyTrade]:
        """
        단일 거래 3분봉 청산 시뮬레이션

        Args:
            daily_df: 일봉 데이터
            signal: 1차 매수 신호
            stock_code: 종목코드
            stock_name: 종목명
            dates: 날짜 리스트
            data_loader: DataLoader 인스턴스

        Returns:
            거래 결과
        """
        from datetime import date as date_type

        signal_date = signal.signal_date

        # 신호일 인덱스
        try:
            signal_idx = dates.index(signal_date)
        except ValueError:
            return None

        # 진입일 확인
        if signal_idx + 1 >= len(dates):
            return None

        entry_date = dates[signal_idx + 1]
        entry_candle = daily_df[daily_df['date'] == entry_date]
        if entry_candle.empty:
            return None
        entry_candle = entry_candle.iloc[0]

        # 1차 매수: 진입일 시가
        first_entry_price = int(entry_candle['open'] * (1 + self.config.get_entry_cost_rate()))
        investment = self.config.investment_per_trade
        first_qty = int((investment * self.config.first_buy_ratio) // first_entry_price)

        if first_qty <= 0:
            return None

        # 포지션 생성
        position = SplitBuyPosition(
            stock_code=stock_code,
            stock_name=stock_name,
            first_buy_date=entry_date,
            first_buy_price=first_entry_price,
            first_buy_qty=first_qty,
            state=SplitBuyState.FIRST_ONLY
        )

        # 거래 객체 초기화
        trade = SplitBuyTrade(
            stock_code=stock_code,
            stock_name=stock_name,
            first_signal_date=signal_date,
            first_entry_date=entry_date,
            first_entry_price=first_entry_price,
            first_qty=first_qty
        )

        # 3분봉 데이터 시뮬레이션 (일봉 기반)
        if data_loader is None:
            return None

        intraday_df = data_loader.simulate_multi_day_intraday(
            daily_df=daily_df,
            entry_date=entry_date,
            max_days=self.config.max_holding_days_3m
        )

        if intraday_df.empty:
            return None

        # 3분봉 지표 계산
        intraday_df = calculate_indicators_3min(intraday_df)

        # 초기 트레일링 스탑 설정
        entry_price = position.avg_price
        safety_stop_price = int(entry_price * (1 + self.config.safety_stop_rate / 100))

        # 첫 봉의 ATR/HLC3로 초기 TS 설정
        first_valid_idx = intraday_df['atr10'].first_valid_index()
        if first_valid_idx is not None:
            first_row = intraday_df.loc[first_valid_idx]
            initial_ts = calculate_trailing_stop_3min(
                hlc3=first_row['hlc3'],
                atr=first_row['atr10'],
                is_structure_warning=False,
                mult_base=self.config.atr_mult_base,
                mult_tight=self.config.atr_mult_tight
            )
            trailing_stop = max(initial_ts, safety_stop_price)
        else:
            trailing_stop = safety_stop_price

        # 2차 매수 체크 (일봉 기준, 3영업일 이내)
        entry_idx = dates.index(entry_date)
        for i in range(entry_idx + 1, min(entry_idx + 4, len(dates))):
            check_date = dates[i]
            check_candle = daily_df[daily_df['date'] == check_date]
            if check_candle.empty:
                continue
            check_candle = check_candle.iloc[0]

            close = check_candle['close']
            ema8 = check_candle['ema8']
            trading_value = check_candle.get('trading_value', 0)

            if (trading_value >= self.config.min_trading_value and
                is_near_ema8(close, ema8, self.config.ema8_proximity_pct)):

                # 2차 매수
                if i + 1 < len(dates):
                    second_entry_date = dates[i + 1]
                    second_candle = daily_df[daily_df['date'] == second_entry_date]
                    if not second_candle.empty:
                        second_candle = second_candle.iloc[0]
                        second_entry_price = int(second_candle['open'] * (1 + self.config.get_entry_cost_rate()))
                        second_qty = int((investment * self.config.second_buy_ratio) // second_entry_price)

                        if second_qty > 0:
                            position.add_second_buy(second_entry_date, second_entry_price, second_qty)
                            trade.second_signal_date = check_date
                            trade.second_entry_date = second_entry_date
                            trade.second_entry_price = second_entry_price
                            trade.second_qty = second_qty

                            # 평균가 변경으로 손절가 재계산
                            entry_price = position.avg_price
                            safety_stop_price = int(entry_price * (1 + self.config.safety_stop_rate / 100))
                break

        # 3분봉 청산 시뮬레이션
        # entry_date를 date 타입으로 통일
        if hasattr(entry_date, 'date'):
            holding_start_date = entry_date.date()
        else:
            holding_start_date = entry_date
        is_structure_warning = False

        for idx in range(len(intraday_df)):
            row = intraday_df.iloc[idx]

            # ATR/HLC3 유효 체크
            if pd.isna(row['atr10']) or pd.isna(row['hlc3']):
                continue

            bar_low = int(row['low'])
            bar_close = int(row['close'])
            bar_datetime = row['datetime']

            # 현재 날짜 추출
            if hasattr(bar_datetime, 'date'):
                current_date = bar_datetime.date()
            else:
                current_date = entry_date

            # 1. 고정 손절 체크 (-4%)
            if bar_low <= safety_stop_price:
                exit_price = int(safety_stop_price * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_3min(
                    trade, position, current_date, exit_price, ExitReason.HARD_STOP_4PCT
                )
                return trade

            # 2. Structure Warning 체크
            is_structure_warning = check_structure_warning(
                intraday_df, idx, self.config.structure_warning_bars
            )

            # 3. ATR TS 체크
            if bar_close <= trailing_stop:
                exit_reason = ExitReason.ATR_TRAILING_STOP_TIGHT if is_structure_warning else ExitReason.ATR_TRAILING_STOP
                exit_price = int(bar_close * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_3min(
                    trade, position, current_date, exit_price, exit_reason
                )
                return trade

            # 4. TS 상향 조정 (절대 하락 안 함)
            new_ts = calculate_trailing_stop_3min(
                hlc3=row['hlc3'],
                atr=row['atr10'],
                is_structure_warning=is_structure_warning,
                mult_base=self.config.atr_mult_base,
                mult_tight=self.config.atr_mult_tight
            )
            trailing_stop = max(trailing_stop, new_ts)

            # 5. 최대 보유일 체크
            if hasattr(bar_datetime, 'date'):
                holding_days = (current_date - holding_start_date).days
                if holding_days >= self.config.max_holding_days_3m:
                    exit_price = int(bar_close * (1 - self.config.get_exit_cost_rate()))
                    self._finalize_trade_3min(
                        trade, position, current_date, exit_price, ExitReason.MAX_HOLDING_60D
                    )
                    return trade

        # 데이터 끝까지 도달 (마지막 봉에서 청산)
        if len(intraday_df) > 0:
            last_row = intraday_df.iloc[-1]
            last_datetime = last_row['datetime']
            if hasattr(last_datetime, 'date'):
                last_date = last_datetime.date()
            else:
                last_date = entry_date

            exit_price = int(last_row['close'] * (1 - self.config.get_exit_cost_rate()))
            self._finalize_trade_3min(
                trade, position, last_date, exit_price, ExitReason.MAX_HOLDING_60D
            )
            return trade

        return None

    def _finalize_trade_3min(
        self,
        trade: SplitBuyTrade,
        position: SplitBuyPosition,
        exit_date,
        exit_price: int,
        exit_reason: ExitReason
    ):
        """
        3분봉 거래 완료 처리

        Args:
            trade: 거래 객체
            position: 포지션
            exit_date: 청산일
            exit_price: 청산가
            exit_reason: 청산 사유
        """
        from datetime import date as date_type

        # date 타입 확인 및 변환
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()

        first_buy_date = position.first_buy_date
        if hasattr(first_buy_date, 'date'):
            first_buy_date = first_buy_date.date()

        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason

        # 총 수량 및 평균 매수가
        trade.total_qty = position.total_qty
        trade.avg_entry_price = position.avg_price

        # 보유일 계산
        trade.holding_days = (exit_date - first_buy_date).days

        # 손익 계산
        entry_cost = position.total_cost
        exit_value = exit_price * position.total_qty
        trade.gross_pnl = exit_value - entry_cost

        # 비용 계산
        trade.entry_cost = int(entry_cost * self.config.get_entry_cost_rate())
        trade.exit_cost = int(exit_value * self.config.get_exit_cost_rate())
        trade.total_cost = trade.entry_cost + trade.exit_cost

        trade.net_pnl = trade.gross_pnl - trade.total_cost

        # 수익률
        if entry_cost > 0:
            trade.return_rate = (trade.net_pnl / entry_cost) * 100
        else:
            trade.return_rate = 0

    # =========================================================================
    # Phase 3: EMA3 이탈 청산 시뮬레이션
    # =========================================================================

    def simulate_trades_ema3(
        self,
        df: pd.DataFrame,
        signals: List[SplitBuySignal],
        stock_code: str,
        stock_name: str
    ) -> List[SplitBuyTrade]:
        """
        EMA3 이탈 청산 로직을 적용한 거래 시뮬레이션

        청산: 일봉 EMA3 하향 이탈 시
            1. 고정 손절 -5%
            2. EMA3 하향 이탈
            3. 최대 보유 60일
        """
        trades = []
        dates = sorted(df['date'].tolist())

        for signal in signals:
            if signal.signal_type != "EMA5":
                continue

            trade = self._simulate_single_trade_ema3(
                df=df,
                signal=signal,
                stock_code=stock_code,
                stock_name=stock_name,
                dates=dates
            )

            if trade and trade.is_complete:
                trades.append(trade)

        return trades

    def _simulate_single_trade_ema3(
        self,
        df: pd.DataFrame,
        signal: SplitBuySignal,
        stock_code: str,
        stock_name: str,
        dates: List[date]
    ) -> Optional[SplitBuyTrade]:
        """단일 거래 EMA3 이탈 청산 시뮬레이션"""
        signal_date = signal.signal_date

        try:
            signal_idx = dates.index(signal_date)
        except ValueError:
            return None

        if signal_idx + 1 >= len(dates):
            return None

        entry_date = dates[signal_idx + 1]
        entry_candle = df[df['date'] == entry_date]
        if entry_candle.empty:
            return None
        entry_candle = entry_candle.iloc[0]

        first_entry_price = int(entry_candle['open'] * (1 + self.config.get_entry_cost_rate()))
        investment = self.config.investment_per_trade
        first_qty = int((investment * self.config.first_buy_ratio) // first_entry_price)

        if first_qty <= 0:
            return None

        position = SplitBuyPosition(
            stock_code=stock_code,
            stock_name=stock_name,
            first_buy_date=entry_date,
            first_buy_price=first_entry_price,
            first_buy_qty=first_qty,
            state=SplitBuyState.FIRST_ONLY
        )

        trade = SplitBuyTrade(
            stock_code=stock_code,
            stock_name=stock_name,
            first_signal_date=signal_date,
            first_entry_date=entry_date,
            first_entry_price=first_entry_price,
            first_qty=first_qty
        )

        stop_price = int(position.avg_price * (1 + self.config.ema3_stop_rate / 100))

        # 2차 매수 체크
        entry_idx = dates.index(entry_date)
        for i in range(entry_idx + 1, min(entry_idx + 4, len(dates))):
            check_date = dates[i]
            check_candle = df[df['date'] == check_date]
            if check_candle.empty:
                continue
            check_candle = check_candle.iloc[0]

            close = check_candle['close']
            ema8 = check_candle['ema8']
            trading_value = check_candle.get('trading_value', 0)

            if (trading_value >= self.config.min_trading_value and
                is_near_ema8(close, ema8, self.config.ema8_proximity_pct)):
                if i + 1 < len(dates):
                    second_entry_date = dates[i + 1]
                    second_candle = df[df['date'] == second_entry_date]
                    if not second_candle.empty:
                        second_candle = second_candle.iloc[0]
                        second_entry_price = int(second_candle['open'] * (1 + self.config.get_entry_cost_rate()))
                        second_qty = int((investment * self.config.second_buy_ratio) // second_entry_price)
                        if second_qty > 0:
                            position.add_second_buy(second_entry_date, second_entry_price, second_qty)
                            trade.second_signal_date = check_date
                            trade.second_entry_date = second_entry_date
                            trade.second_entry_price = second_entry_price
                            trade.second_qty = second_qty
                            stop_price = int(position.avg_price * (1 + self.config.ema3_stop_rate / 100))
                break

        holding_start_date = entry_date
        if hasattr(holding_start_date, 'date'):
            holding_start_date = holding_start_date.date()

        for i in range(entry_idx + 1, len(dates)):
            current_date = dates[i]
            candle = df[df['date'] == current_date]
            if candle.empty:
                continue
            candle = candle.iloc[0]

            bar_low = int(candle['low'])
            bar_close = int(candle['close'])
            ema3 = candle['ema3']

            if hasattr(current_date, 'date'):
                current_date_dt = current_date.date()
            else:
                current_date_dt = current_date

            # 1. 고정 손절 체크 (-5%)
            if bar_low <= stop_price:
                exit_price = int(stop_price * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_ema3(trade, position, current_date_dt, exit_price, ExitReason.HARD_STOP_5PCT)
                return trade

            # 2. EMA3 이탈 체크 (종가 < EMA3)
            if bar_close < ema3:
                exit_price = int(bar_close * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_ema3(trade, position, current_date_dt, exit_price, ExitReason.EMA3_BREAK)
                return trade

            # 3. 최대 보유일 체크
            holding_days = (current_date_dt - holding_start_date).days
            if holding_days >= self.config.max_holding_days_ema3:
                exit_price = int(bar_close * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_ema3(trade, position, current_date_dt, exit_price, ExitReason.MAX_HOLDING_60D)
                return trade

        return None

    def _finalize_trade_ema3(self, trade, position, exit_date, exit_price, exit_reason):
        """EMA3 거래 완료 처리"""
        if hasattr(exit_date, 'date'):
            exit_date = exit_date.date()
        first_buy_date = position.first_buy_date
        if hasattr(first_buy_date, 'date'):
            first_buy_date = first_buy_date.date()

        trade.exit_date = exit_date
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.total_qty = position.total_qty
        trade.avg_entry_price = position.avg_price
        trade.holding_days = (exit_date - first_buy_date).days

        entry_cost = position.total_cost
        exit_value = exit_price * position.total_qty
        trade.gross_pnl = exit_value - entry_cost
        trade.entry_cost = int(entry_cost * self.config.get_entry_cost_rate())
        trade.exit_cost = int(exit_value * self.config.get_exit_cost_rate())
        trade.total_cost = trade.entry_cost + trade.exit_cost
        trade.net_pnl = trade.gross_pnl - trade.total_cost
        trade.return_rate = (trade.net_pnl / entry_cost) * 100 if entry_cost > 0 else 0

    # =========================================================================
    # Phase 2 Real: 실제 3분봉 데이터 청산 시뮬레이션
    # =========================================================================

    async def simulate_trades_3min_real(
        self,
        daily_df: pd.DataFrame,
        signals: List[SplitBuySignal],
        stock_code: str,
        stock_name: str,
        data_loader=None
    ) -> List[SplitBuyTrade]:
        """
        실제 3분봉 데이터를 사용한 청산 시뮬레이션

        진입: 일봉 기준 (기존 로직)
        청산: 실제 3분봉 기준 (V6.2-A 로직)
            1. 고정 손절 -4%
            2. ATR 트레일링 스탑 (6.0 / 4.5)
            3. 최대 보유 60일

        Args:
            daily_df: 지표가 계산된 일봉 데이터
            signals: 1차 매수 신호 리스트
            stock_code: 종목코드
            stock_name: 종목명
            data_loader: DataLoader 인스턴스

        Returns:
            거래 결과 리스트
        """
        trades = []
        dates = sorted(daily_df['date'].tolist())

        if data_loader is None:
            if self._logger:
                self._logger.warning(f"[{stock_code}] DataLoader 없음, 스킵")
            return trades

        # 실제 3분봉 데이터 조회 (최근 1000개 = 약 7-8거래일)
        minute_df = await data_loader.load_minute_candles(
            stock_code=stock_code,
            count=1000
        )

        if minute_df is None or minute_df.empty:
            if self._logger:
                self._logger.warning(f"[{stock_code}] 3분봉 데이터 없음, 스킵")
            return trades

        # 3분봉 지표 계산
        minute_df = calculate_indicators_3min(minute_df)

        # 3분봉 데이터의 날짜 범위 확인
        min_datetime = minute_df['datetime'].min()
        max_datetime = minute_df['datetime'].max()

        if hasattr(min_datetime, 'date'):
            min_date = min_datetime.date()
            max_date = max_datetime.date()
        else:
            min_date = min_datetime
            max_date = max_datetime

        if self._logger:
            self._logger.info(
                f"[{stock_code}] 3분봉 데이터: {min_date} ~ {max_date} "
                f"({len(minute_df)}개 봉)"
            )

        # 최근 신호만 필터링 (3분봉 데이터 범위 내)
        for signal in signals:
            if signal.signal_type != "EMA5":
                continue

            signal_date = signal.signal_date
            if hasattr(signal_date, 'date'):
                signal_date = signal_date.date()

            # 신호일이 3분봉 데이터 범위를 벗어나면 스킵
            if signal_date < min_date or signal_date > max_date:
                continue

            trade = self._simulate_single_trade_3min_real(
                daily_df=daily_df,
                minute_df=minute_df,
                signal=signal,
                stock_code=stock_code,
                stock_name=stock_name,
                dates=dates
            )

            if trade and trade.is_complete:
                trades.append(trade)
                if self._logger:
                    self._logger.info(
                        f"[{stock_code}] 거래 완료: {trade.first_entry_date} -> "
                        f"{trade.exit_date}, {trade.exit_reason.value}, "
                        f"수익률: {trade.return_rate:.2f}%"
                    )

        return trades

    def _simulate_single_trade_3min_real(
        self,
        daily_df: pd.DataFrame,
        minute_df: pd.DataFrame,
        signal: SplitBuySignal,
        stock_code: str,
        stock_name: str,
        dates: List[date]
    ) -> Optional[SplitBuyTrade]:
        """
        실제 3분봉 데이터를 사용한 단일 거래 시뮬레이션

        Args:
            daily_df: 일봉 데이터
            minute_df: 실제 3분봉 데이터 (지표 포함)
            signal: 1차 매수 신호
            stock_code: 종목코드
            stock_name: 종목명
            dates: 날짜 리스트

        Returns:
            거래 결과
        """
        from datetime import date as date_type
        import pandas as pd

        signal_date = signal.signal_date
        if hasattr(signal_date, 'date'):
            signal_date = signal_date.date()

        # dates 리스트를 date 타입으로 변환 (Timestamp vs date 비교 문제 해결)
        dates_converted = [
            d.date() if hasattr(d, 'date') else d for d in dates
        ]

        # 신호일 인덱스
        try:
            signal_idx = dates_converted.index(signal_date)
        except ValueError:
            return None

        # 진입일 확인
        if signal_idx + 1 >= len(dates_converted):
            return None

        entry_date = dates_converted[signal_idx + 1]

        # daily_df['date']가 Timestamp일 수 있으므로 date로 변환 후 비교
        entry_candle = daily_df[daily_df['date'].apply(
            lambda x: x.date() if hasattr(x, 'date') else x
        ) == entry_date]
        if entry_candle.empty:
            return None
        entry_candle = entry_candle.iloc[0]

        # 1차 매수: 진입일 시가
        first_entry_price = int(entry_candle['open'] * (1 + self.config.get_entry_cost_rate()))
        investment = self.config.investment_per_trade
        first_qty = int((investment * self.config.first_buy_ratio) // first_entry_price)

        if first_qty <= 0:
            return None

        # 포지션 생성
        position = SplitBuyPosition(
            stock_code=stock_code,
            stock_name=stock_name,
            first_buy_date=entry_date,
            first_buy_price=first_entry_price,
            first_buy_qty=first_qty,
            state=SplitBuyState.FIRST_ONLY
        )

        # 거래 객체 초기화
        trade = SplitBuyTrade(
            stock_code=stock_code,
            stock_name=stock_name,
            first_signal_date=signal_date,
            first_entry_date=entry_date,
            first_entry_price=first_entry_price,
            first_qty=first_qty
        )

        # 진입일 이후의 3분봉 데이터 필터링
        minute_df_filtered = minute_df[
            minute_df['datetime'].apply(
                lambda x: x.date() if hasattr(x, 'date') else x
            ) >= entry_date
        ].copy()

        if minute_df_filtered.empty:
            return None

        # 초기 트레일링 스탑 설정
        entry_price = position.avg_price
        safety_stop_price = int(entry_price * (1 + self.config.safety_stop_rate / 100))

        # 첫 봉의 ATR/HLC3로 초기 TS 설정
        first_valid_idx = minute_df_filtered['atr10'].first_valid_index()
        if first_valid_idx is not None:
            first_row = minute_df_filtered.loc[first_valid_idx]
            initial_ts = calculate_trailing_stop_3min(
                hlc3=first_row['hlc3'],
                atr=first_row['atr10'],
                is_structure_warning=False,
                mult_base=self.config.atr_mult_base,
                mult_tight=self.config.atr_mult_tight
            )
            trailing_stop = max(initial_ts, safety_stop_price)
        else:
            trailing_stop = safety_stop_price

        # 2차 매수 체크 (일봉 기준, 3영업일 이내)
        entry_idx = dates_converted.index(entry_date) if entry_date in dates_converted else -1
        if entry_idx >= 0:
            for i in range(entry_idx + 1, min(entry_idx + 4, len(dates_converted))):
                check_date = dates_converted[i]
                check_candle = daily_df[daily_df['date'].apply(
                    lambda x: x.date() if hasattr(x, 'date') else x
                ) == check_date]
                if check_candle.empty:
                    continue
                check_candle = check_candle.iloc[0]

                close = check_candle['close']
                ema8 = check_candle['ema8']
                trading_value = check_candle.get('trading_value', 0)

                if (trading_value >= self.config.min_trading_value and
                    is_near_ema8(close, ema8, self.config.ema8_proximity_pct)):
                    if i + 1 < len(dates_converted):
                        second_entry_date = dates_converted[i + 1]
                        second_candle = daily_df[daily_df['date'].apply(
                            lambda x: x.date() if hasattr(x, 'date') else x
                        ) == second_entry_date]
                        if not second_candle.empty:
                            second_candle = second_candle.iloc[0]
                            second_entry_price = int(second_candle['open'] * (1 + self.config.get_entry_cost_rate()))
                            second_qty = int((investment * self.config.second_buy_ratio) // second_entry_price)

                            if second_qty > 0:
                                position.add_second_buy(second_entry_date, second_entry_price, second_qty)
                                trade.second_signal_date = check_date
                                trade.second_entry_date = second_entry_date
                                trade.second_entry_price = second_entry_price
                                trade.second_qty = second_qty

                                # 평균가 변경으로 손절가 재계산
                                entry_price = position.avg_price
                                safety_stop_price = int(entry_price * (1 + self.config.safety_stop_rate / 100))
                    break

        # 실제 3분봉 청산 시뮬레이션
        holding_start_date = entry_date
        is_structure_warning = False

        for idx in range(len(minute_df_filtered)):
            row = minute_df_filtered.iloc[idx]

            # ATR/HLC3 유효 체크
            if pd.isna(row['atr10']) or pd.isna(row['hlc3']):
                continue

            bar_low = int(row['low'])
            bar_close = int(row['close'])
            bar_datetime = row['datetime']

            # 현재 날짜 추출
            if hasattr(bar_datetime, 'date'):
                current_date = bar_datetime.date()
            else:
                current_date = entry_date

            # 1. 고정 손절 체크 (-4%)
            if bar_low <= safety_stop_price:
                exit_price = int(safety_stop_price * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_3min(
                    trade, position, current_date, exit_price, ExitReason.HARD_STOP_4PCT
                )
                return trade

            # 2. Structure Warning 체크
            is_structure_warning = check_structure_warning(
                minute_df_filtered, idx, self.config.structure_warning_bars
            )

            # 3. ATR TS 체크
            if bar_close <= trailing_stop:
                exit_reason = ExitReason.ATR_TRAILING_STOP_TIGHT if is_structure_warning else ExitReason.ATR_TRAILING_STOP
                exit_price = int(bar_close * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_3min(
                    trade, position, current_date, exit_price, exit_reason
                )
                return trade

            # 4. TS 상향 조정 (절대 하락 안 함)
            new_ts = calculate_trailing_stop_3min(
                hlc3=row['hlc3'],
                atr=row['atr10'],
                is_structure_warning=is_structure_warning,
                mult_base=self.config.atr_mult_base,
                mult_tight=self.config.atr_mult_tight
            )
            trailing_stop = max(trailing_stop, new_ts)

            # 5. 최대 보유일 체크
            holding_days = (current_date - holding_start_date).days
            if holding_days >= self.config.max_holding_days_3m:
                exit_price = int(bar_close * (1 - self.config.get_exit_cost_rate()))
                self._finalize_trade_3min(
                    trade, position, current_date, exit_price, ExitReason.MAX_HOLDING_60D
                )
                return trade

        # 데이터 끝까지 도달 (마지막 봉에서 청산)
        if len(minute_df_filtered) > 0:
            last_row = minute_df_filtered.iloc[-1]
            last_datetime = last_row['datetime']
            if hasattr(last_datetime, 'date'):
                last_date = last_datetime.date()
            else:
                last_date = entry_date

            exit_price = int(last_row['close'] * (1 - self.config.get_exit_cost_rate()))
            self._finalize_trade_3min(
                trade, position, last_date, exit_price, ExitReason.MAX_HOLDING_60D
            )
            return trade

        return None
