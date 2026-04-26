# -*- coding: utf-8 -*-
"""
V7 Purple 3분봉 백테스트 - 거래 시뮬레이터

ATR 트레일링 스탑 기반 청산 시뮬레이션 (Wave Harvest 로직)
"""

from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple
import pandas as pd
import numpy as np

from .config import BacktestConfig, V7Signal, Trade


class TradeSimulator:
    """
    거래 시뮬레이터

    V7 Wave Harvest 청산 로직을 백테스트용으로 구현
    """

    def __init__(self, config: BacktestConfig, logger):
        self.config = config
        self.logger = logger

    # ============================================================
    # ATR 계산
    # ============================================================

    def calculate_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> pd.Series:
        """
        ATR 계산 (Wilder's RMA)
        """
        period = period or self.config.atr_period

        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Wilder's RMA
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        return atr

    # ============================================================
    # R-Multiple 기반 ATR 배수
    # ============================================================

    def get_atr_multiplier(
        self,
        r_multiple: float,
        has_warning: bool,
        current_mult: float
    ) -> float:
        """
        R-Multiple 기반 ATR 배수 결정 (단방향 축소)

        배수는 절대 증가하지 않음: 6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0
        """
        mult = current_mult

        if has_warning:
            mult = min(mult, self.config.atr_mult_warning)

        if r_multiple >= 5:
            mult = min(mult, self.config.atr_mult_5r)
        elif r_multiple >= 3:
            mult = min(mult, self.config.atr_mult_3r)
        elif r_multiple >= 2:
            mult = min(mult, self.config.atr_mult_2r)
        elif r_multiple >= 1:
            mult = min(mult, self.config.atr_mult_1r)

        return mult

    def calculate_r_multiple(self, current_price: int, entry_price: int) -> float:
        """R-Multiple = (현재가 - 진입가) / (진입가 × 4%)"""
        initial_risk = entry_price * self.config.stop_loss_pct
        if initial_risk == 0:
            return 0.0
        return (current_price - entry_price) / initial_risk

    # ============================================================
    # 트레일링 스탑 계산
    # ============================================================

    def calculate_trailing_stop(
        self,
        base_price: int,
        atr: float,
        multiplier: float
    ) -> int:
        """TrailingStop = BasePrice - ATR × Multiplier"""
        return int(base_price - (atr * multiplier))

    def get_fallback_stop(self, entry_price: int) -> int:
        """Fallback 손절가 (-4%)"""
        return int(entry_price * (1 - self.config.stop_loss_pct))

    # ============================================================
    # 구조 경고 확인
    # ============================================================

    def check_structure_warning(
        self,
        df: pd.DataFrame,
        idx: int,
        current_price: int
    ) -> bool:
        """구조 경고 확인 (EMA20 < EMA60 또는 현재가 < EMA20)"""
        if idx < 60:
            return False

        close = df['close']
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema60 = close.ewm(span=60, adjust=False).mean()

        current_ema20 = ema20.iloc[idx]
        current_ema60 = ema60.iloc[idx]

        return current_ema20 < current_ema60 or current_price < current_ema20

    # ============================================================
    # 단일 거래 시뮬레이션
    # ============================================================

    def simulate_trade(
        self,
        signal: V7Signal,
        df: pd.DataFrame,
        event_date: date
    ) -> Optional[Trade]:
        """
        단일 거래 시뮬레이션

        Args:
            signal: V7Signal 객체 (진입 신호)
            df: 3분봉 DataFrame (datetime index 또는 datetime column)
            event_date: 이벤트 발생일

        Returns:
            Trade 객체 또는 None
        """
        if df is None or len(df) == 0:
            return None

        # DataFrame 정규화 (datetime index -> column)
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            if 'index' in df.columns:
                df.rename(columns={'index': 'datetime'}, inplace=True)

        # 진입 시점 찾기
        entry_idx = None
        for idx, row in df.iterrows():
            dt = row['datetime']
            if isinstance(dt, str):
                dt = pd.to_datetime(dt)
            if dt >= signal.signal_datetime:
                entry_idx = idx
                break

        if entry_idx is None:
            return None

        # 진입 정보
        entry_row = df.iloc[entry_idx]
        entry_price = int(entry_row['close'])
        entry_dt = entry_row['datetime']

        # 비용 적용 진입가 (슬리피지 + 수수료)
        slippage_cost = entry_price * self.config.slippage_pct
        commission_cost = entry_price * self.config.commission_pct
        effective_entry = entry_price + slippage_cost + commission_cost

        # 초기 상태
        hard_stop = self.get_fallback_stop(entry_price)
        trailing_stop = hard_stop
        highest_high = entry_price
        atr_multiplier = self.config.atr_mult_default
        has_warning = False

        # MFE/MAE 추적
        mfe = 0.0  # Maximum Favorable Excursion
        mae = 0.0  # Maximum Adverse Excursion

        # 청산 결과
        exit_idx = None
        exit_price = None
        exit_type = None
        exit_dt = None

        current_day = event_date
        days_held = 0

        # ATR 계산
        atr_series = self.calculate_atr(df)

        # 봉 순회
        for idx in range(entry_idx + 1, len(df)):
            row = df.iloc[idx]
            bar_datetime = row['datetime']
            if isinstance(bar_datetime, str):
                bar_datetime = pd.to_datetime(bar_datetime)

            bar_date = bar_datetime.date()
            bar_time = bar_datetime.time()
            bar_high = int(row['high'])
            bar_low = int(row['low'])
            bar_close = int(row['close'])

            # 날짜 변경 체크
            if bar_date > current_day:
                # 전일 종가 기준 수익 여부 확인
                prev_close = int(df.iloc[idx - 1]['close'])
                is_profitable = prev_close > entry_price

                # 당일 손실 시 종가 청산
                if not is_profitable and not self.config.hold_if_profitable:
                    exit_idx = idx - 1
                    exit_price = prev_close
                    exit_type = "END_OF_DAY"
                    exit_dt = df.iloc[idx - 1]['datetime']
                    break

                # 익일 이월
                current_day = bar_date
                days_held += 1

                # 최대 보유일 체크
                if days_held >= self.config.max_hold_days:
                    exit_idx = idx
                    exit_price = bar_close
                    exit_type = "MAX_HOLD"
                    exit_dt = bar_datetime
                    break

            # MFE/MAE 업데이트
            current_return = (bar_close - entry_price) / entry_price * 100
            if current_return > mfe:
                mfe = current_return
            if current_return < mae:
                mae = current_return

            # 1. 고정 손절 체크 (봉 저가 기준)
            if bar_low <= hard_stop:
                exit_idx = idx
                exit_price = hard_stop
                exit_type = "HARD_STOP"
                exit_dt = bar_datetime
                break

            # 2. 고점 기준가 업데이트
            if bar_high > highest_high:
                highest_high = bar_high

            # 3. R-Multiple 계산
            r_multiple = self.calculate_r_multiple(bar_close, entry_price)

            # 4. 구조 경고 확인
            if not has_warning:
                has_warning = self.check_structure_warning(df, idx, bar_close)

            # 5. ATR 배수 업데이트 (단방향 축소)
            new_mult = self.get_atr_multiplier(r_multiple, has_warning, atr_multiplier)
            if new_mult < atr_multiplier:
                atr_multiplier = new_mult

            # 6. 트레일링 스탑 계산
            atr = atr_series.iloc[idx] if idx < len(atr_series) else atr_series.iloc[-1]
            new_stop = self.calculate_trailing_stop(highest_high, atr, atr_multiplier)

            # 상향 단방향 (하락 금지)
            trailing_stop = max(trailing_stop, new_stop)

            # Fallback보다 낮으면 Fallback 사용
            trailing_stop = max(trailing_stop, hard_stop)

            # 7. ATR TS 청산 체크 (종가 기준)
            if bar_close < trailing_stop:
                exit_idx = idx
                exit_price = bar_close
                exit_type = f"ATR_TS_{atr_multiplier:.1f}x"
                if r_multiple >= 1:
                    exit_type += f"_R{r_multiple:.1f}"
                exit_dt = bar_datetime
                break

        # 청산 없이 데이터 끝난 경우
        if exit_idx is None:
            exit_idx = len(df) - 1
            exit_row = df.iloc[exit_idx]
            exit_price = int(exit_row['close'])
            exit_type = "END_OF_DATA"
            exit_dt = exit_row['datetime']

        # 비용 계산
        investment = self.config.investment_per_trade
        shares = investment // entry_price

        exit_slippage = exit_price * self.config.slippage_pct
        exit_commission = exit_price * self.config.commission_pct
        exit_tax = exit_price * self.config.tax_pct
        effective_exit = exit_price - exit_slippage - exit_commission - exit_tax

        gross_return_pct = (exit_price - entry_price) / entry_price * 100
        net_return_pct = (effective_exit - effective_entry) / effective_entry * 100
        r_multiple = self.calculate_r_multiple(exit_price, entry_price)

        gross_pnl = int((exit_price - entry_price) * shares)
        total_cost = int((slippage_cost + commission_cost + exit_slippage + exit_commission + exit_tax) * shares)
        net_pnl = gross_pnl - total_cost

        return Trade(
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            event_date=event_date,
            entry_dt=entry_dt,
            entry_price=entry_price,
            exit_dt=exit_dt,
            exit_price=exit_price,
            exit_type=exit_type,
            gross_return_pct=round(gross_return_pct, 2),
            net_return_pct=round(net_return_pct, 2),
            r_multiple=round(r_multiple, 2),
            mfe_pct=round(mfe, 2),
            mae_pct=round(mae, 2),
            holding_bars=exit_idx - entry_idx,
            holding_days=days_held + 1,
            investment=investment,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            net_pnl=net_pnl,
            signal_score=signal.score,
            signal_rise_pct=signal.rise_pct,
            signal_convergence_pct=signal.convergence_pct,
            signal_time=signal.signal_datetime.strftime("%H:%M") if hasattr(signal.signal_datetime, 'strftime') else str(signal.signal_datetime)
        )

    # ============================================================
    # 당일 청산 시뮬레이션 (간단 버전)
    # ============================================================

    def simulate_intraday_trade(
        self,
        signal: V7Signal,
        df: pd.DataFrame,
        event_date: date
    ) -> Optional[Trade]:
        """
        당일 청산 전용 시뮬레이션 (익일 이월 없음)

        수익/손실 관계없이 장 마감 시 청산
        """
        if df is None or len(df) == 0:
            return None

        # DataFrame 정규화
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            if 'index' in df.columns:
                df.rename(columns={'index': 'datetime'}, inplace=True)

        # 진입 시점 찾기
        entry_idx = None
        for idx, row in df.iterrows():
            dt = row['datetime']
            if isinstance(dt, str):
                dt = pd.to_datetime(dt)
            if dt >= signal.signal_datetime:
                entry_idx = idx
                break

        if entry_idx is None:
            return None

        # 진입 정보
        entry_row = df.iloc[entry_idx]
        entry_price = int(entry_row['close'])
        entry_dt = entry_row['datetime']

        # 비용 적용 진입가
        slippage_cost = entry_price * self.config.slippage_pct
        commission_cost = entry_price * self.config.commission_pct
        effective_entry = entry_price + slippage_cost + commission_cost

        # 초기 상태
        hard_stop = self.get_fallback_stop(entry_price)
        trailing_stop = hard_stop
        highest_high = entry_price
        atr_multiplier = self.config.atr_mult_default
        has_warning = False

        mfe = 0.0
        mae = 0.0

        exit_idx = None
        exit_price = None
        exit_type = None
        exit_dt = None

        atr_series = self.calculate_atr(df)

        # 당일 데이터만 처리
        for idx in range(entry_idx + 1, len(df)):
            row = df.iloc[idx]
            bar_datetime = row['datetime']
            if isinstance(bar_datetime, str):
                bar_datetime = pd.to_datetime(bar_datetime)

            bar_date = bar_datetime.date()

            # 당일 데이터만
            if bar_date > event_date:
                break

            bar_high = int(row['high'])
            bar_low = int(row['low'])
            bar_close = int(row['close'])

            # MFE/MAE
            current_return = (bar_close - entry_price) / entry_price * 100
            if current_return > mfe:
                mfe = current_return
            if current_return < mae:
                mae = current_return

            # 고정 손절
            if bar_low <= hard_stop:
                exit_idx = idx
                exit_price = hard_stop
                exit_type = "HARD_STOP"
                exit_dt = bar_datetime
                break

            # 고점 업데이트
            if bar_high > highest_high:
                highest_high = bar_high

            # R-Multiple
            r_multiple = self.calculate_r_multiple(bar_close, entry_price)

            # 구조 경고
            if not has_warning:
                has_warning = self.check_structure_warning(df, idx, bar_close)

            # ATR 배수 업데이트
            new_mult = self.get_atr_multiplier(r_multiple, has_warning, atr_multiplier)
            if new_mult < atr_multiplier:
                atr_multiplier = new_mult

            # 트레일링 스탑
            atr = atr_series.iloc[idx] if idx < len(atr_series) else atr_series.iloc[-1]
            new_stop = self.calculate_trailing_stop(highest_high, atr, atr_multiplier)
            trailing_stop = max(trailing_stop, new_stop)
            trailing_stop = max(trailing_stop, hard_stop)

            # ATR TS 청산
            if bar_close < trailing_stop:
                exit_idx = idx
                exit_price = bar_close
                exit_type = f"ATR_TS_{atr_multiplier:.1f}x"
                if r_multiple >= 1:
                    exit_type += f"_R{r_multiple:.1f}"
                exit_dt = bar_datetime
                break

        # 당일 종가 청산
        if exit_idx is None:
            # 당일 마지막 봉 찾기
            for idx in range(len(df) - 1, entry_idx, -1):
                row = df.iloc[idx]
                bar_datetime = row['datetime']
                if isinstance(bar_datetime, str):
                    bar_datetime = pd.to_datetime(bar_datetime)

                if bar_datetime.date() == event_date:
                    exit_idx = idx
                    exit_price = int(row['close'])
                    exit_type = "END_OF_DAY"
                    exit_dt = bar_datetime
                    break

        if exit_idx is None:
            return None

        # 비용 계산
        investment = self.config.investment_per_trade
        shares = investment // entry_price

        exit_slippage = exit_price * self.config.slippage_pct
        exit_commission = exit_price * self.config.commission_pct
        exit_tax = exit_price * self.config.tax_pct
        effective_exit = exit_price - exit_slippage - exit_commission - exit_tax

        gross_return_pct = (exit_price - entry_price) / entry_price * 100
        net_return_pct = (effective_exit - effective_entry) / effective_entry * 100
        r_multiple = self.calculate_r_multiple(exit_price, entry_price)

        gross_pnl = int((exit_price - entry_price) * shares)
        total_cost = int((slippage_cost + commission_cost + exit_slippage + exit_commission + exit_tax) * shares)
        net_pnl = gross_pnl - total_cost

        return Trade(
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            event_date=event_date,
            entry_dt=entry_dt,
            entry_price=entry_price,
            exit_dt=exit_dt,
            exit_price=exit_price,
            exit_type=exit_type,
            gross_return_pct=round(gross_return_pct, 2),
            net_return_pct=round(net_return_pct, 2),
            r_multiple=round(r_multiple, 2),
            mfe_pct=round(mfe, 2),
            mae_pct=round(mae, 2),
            holding_bars=exit_idx - entry_idx,
            holding_days=1,
            investment=investment,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            net_pnl=net_pnl,
            signal_score=signal.score,
            signal_rise_pct=signal.rise_pct,
            signal_convergence_pct=signal.convergence_pct,
            signal_time=signal.signal_datetime.strftime("%H:%M") if hasattr(signal.signal_datetime, 'strftime') else str(signal.signal_datetime)
        )
