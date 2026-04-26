# -*- coding: utf-8 -*-
"""
December Pipeline - Strategy

SNIPER_TRAP 신호 탐지 및 3분봉 기반 청산 시뮬레이션
"""

import sys
from pathlib import Path
from datetime import datetime, date, time
from typing import List, Optional
import pandas as pd

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.indicator import Indicator

from .config import PipelineConfig, Signal, Trade


class SniperTrapStrategy:
    """SNIPER_TRAP 전략 (3분봉 기반)"""

    def __init__(self, config: PipelineConfig, logger):
        self.config = config
        self.logger = logger

    # ============================================================
    # 지표 계산
    # ============================================================

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """3분봉 지표 계산"""
        df = df.copy()

        # EMA 계산 (adjust=False)
        df["ema3"] = Indicator.ema(df["close"], span=3)
        df["ema20"] = Indicator.ema(df["close"], span=20)
        df["ema60"] = Indicator.ema(df["close"], span=60)
        df["ema200"] = Indicator.ema(df["close"], span=200)

        # ATR 계산
        df["atr"] = Indicator.atr(
            df["high"], df["low"], df["close"],
            period=self.config.atr_period
        )

        return df

    # ============================================================
    # 신호 탐지
    # ============================================================

    def detect_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        first_only: bool = True
    ) -> List[Signal]:
        """
        SNIPER_TRAP 신호 탐지 (09:30 이후)

        조건:
        1. TrendFilter: close > EMA200 AND EMA60 > EMA60[5]
        2. Zone: low <= EMA20 AND close >= EMA60
        3. Meaningful: CrossUp(close, EMA3) AND 양봉 AND volume >= prev_volume
        4. BodySize: (close - open) / open * 100 >= 0.3%
        """
        if len(df) < self.config.min_minute_candles:
            self.logger.warning(f"{stock_code}: 분봉 부족 ({len(df)} < {self.config.min_minute_candles})")
            return []

        df = self.calculate_indicators(df)
        signals = []

        # EMA 안정화 이후부터 탐지
        start_idx = max(self.config.min_minute_candles, 5)

        for i in range(start_idx, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]

            # 시간 확인 (09:30 이후)
            curr_time = self._get_time(curr)
            if curr_time is None:
                continue
            if curr_time < self.config.signal_start_time:
                continue

            # 장 마감 이후는 제외
            if curr_time >= self.config.market_close_time:
                continue

            # EMA60[5]
            if i < 5:
                continue
            ema60_5ago = df["ema60"].iloc[i - 5]

            # 1. TrendFilter
            trend_ok = (
                curr["close"] > curr["ema200"] and
                curr["ema60"] > ema60_5ago
            )
            if not trend_ok:
                continue

            # 2. Zone
            zone_ok = (
                curr["low"] <= curr["ema20"] and
                curr["close"] >= curr["ema60"]
            )
            if not zone_ok:
                continue

            # 3. Meaningful
            crossup = (
                prev["close"] < prev["ema3"] and
                curr["close"] >= curr["ema3"]
            )
            bullish = curr["close"] > curr["open"]
            volume_up = curr["volume"] >= prev["volume"]
            meaningful = crossup and bullish and volume_up
            if not meaningful:
                continue

            # 4. BodySize
            if curr["open"] == 0:
                continue
            body_size = (curr["close"] - curr["open"]) / curr["open"] * 100
            if body_size < self.config.min_body_size:
                continue

            # 신호 발생!
            volume_ratio = curr["volume"] / prev["volume"] if prev["volume"] > 0 else 0
            signal_dt = self._get_datetime(curr)

            signals.append(Signal(
                ticker=stock_code,
                stock_name=stock_name,
                signal_datetime=signal_dt,
                signal_price=int(curr["close"]),
                ema3=float(curr["ema3"]),
                ema20=float(curr["ema20"]),
                ema60=float(curr["ema60"]),
                ema200=float(curr["ema200"]),
                body_size_pct=body_size,
                volume_ratio=volume_ratio
            ))

            self.logger.debug(
                f"  신호: {signal_dt.strftime('%H:%M') if signal_dt else 'N/A'} @ {int(curr['close']):,}원"
            )

            if first_only:
                break

        return signals

    def _get_time(self, row) -> Optional[time]:
        """행에서 시간 추출"""
        idx = row.name
        if isinstance(idx, datetime):
            return idx.time()
        elif hasattr(idx, 'time'):
            return idx.time()
        return None

    def _get_datetime(self, row) -> Optional[datetime]:
        """행에서 datetime 추출"""
        idx = row.name
        if isinstance(idx, datetime):
            return idx
        return None

    # ============================================================
    # 3분봉 기반 청산 시뮬레이션
    # ============================================================

    def simulate_trade(
        self,
        signal: Signal,
        minute_df: pd.DataFrame,
        event_date: date
    ) -> Optional[Trade]:
        """
        3분봉 기반 청산 시뮬레이션

        청산 조건 (우선순위):
        1. HARD_STOP: bar_low <= entry * 0.96 (-4%)
        2. ATR_TS: close <= trailing_stop
        3. MAX_HOLDING: 보유 봉 수 초과

        MFE/MAE 계산 포함
        """
        # 지표가 없으면 계산
        if "ema3" not in minute_df.columns:
            minute_df = self.calculate_indicators(minute_df)

        # 진입 설정
        entry_price = signal.signal_price
        entry_price_with_slip = int(entry_price * (1 + self.config.slippage_rate))
        entry_dt = signal.signal_datetime

        # 수량 계산
        quantity = self.config.investment_per_trade // entry_price_with_slip
        if quantity < 1:
            return None

        # 손절가
        stop_loss_price = int(entry_price_with_slip * (1 + self.config.stop_loss_rate / 100))

        # 진입 인덱스 찾기
        entry_idx = None
        for i, idx in enumerate(minute_df.index):
            if idx >= entry_dt:
                entry_idx = i
                break

        if entry_idx is None:
            self.logger.warning(f"진입 시점 찾기 실패: {entry_dt}")
            return None

        # 초기 ATR 트레일링 스탑
        initial_atr = minute_df["atr"].iloc[entry_idx] if entry_idx < len(minute_df) else 0
        if initial_atr > 0 and pd.notna(initial_atr):
            trailing_stop = entry_price_with_slip - (initial_atr * self.config.atr_mult)
        else:
            trailing_stop = float(stop_loss_price)

        # 청산 시뮬레이션
        exit_price = None
        exit_dt = None
        exit_type = None

        mfe = 0.0  # Maximum Favorable Excursion
        mae = 0.0  # Maximum Adverse Excursion
        holding_bars = 0

        for i in range(entry_idx + 1, len(minute_df)):
            bar = minute_df.iloc[i]
            bar_dt = bar.name
            holding_bars = i - entry_idx

            # MFE/MAE 업데이트
            high_return = (bar["high"] - entry_price_with_slip) / entry_price_with_slip * 100
            low_return = (bar["low"] - entry_price_with_slip) / entry_price_with_slip * 100

            if high_return > mfe:
                mfe = high_return
            if low_return < mae:
                mae = low_return

            # 1순위: 고정 손절 (-4%)
            if bar["low"] <= stop_loss_price:
                exit_price = stop_loss_price
                exit_dt = bar_dt
                exit_type = "HARD_STOP"
                break

            # 2순위: ATR 트레일링 스탑
            atr = minute_df["atr"].iloc[i] if pd.notna(minute_df["atr"].iloc[i]) else initial_atr
            if atr > 0:
                hlc3 = (bar["high"] + bar["low"] + bar["close"]) / 3
                new_ts = hlc3 - (atr * self.config.atr_mult)
                if new_ts > trailing_stop:
                    trailing_stop = new_ts

            if bar["close"] <= trailing_stop:
                exit_price = int(trailing_stop)
                exit_dt = bar_dt
                exit_type = "ATR_TS"
                break

            # 3순위: 최대 보유 봉 수
            if holding_bars >= self.config.max_holding_bars:
                exit_price = int(bar["close"])
                exit_dt = bar_dt
                exit_type = "MAX_HOLDING"
                break

        # 청산 안됐으면 마지막 봉에서 청산
        if exit_price is None:
            last_bar = minute_df.iloc[-1]
            exit_price = int(last_bar["close"])
            exit_dt = last_bar.name
            exit_type = "END_OF_DATA"

        # 비용 계산
        exit_price_with_slip = int(exit_price * (1 - self.config.slippage_rate))
        entry_cost = int(entry_price_with_slip * quantity * self.config.commission_rate)
        exit_cost = int(exit_price_with_slip * quantity * (self.config.commission_rate + self.config.tax_rate))
        total_cost = entry_cost + exit_cost

        # 손익 계산
        gross_pnl = (exit_price_with_slip - entry_price_with_slip) * quantity
        net_pnl = gross_pnl - total_cost
        return_pct = (exit_price_with_slip - entry_price_with_slip) / entry_price_with_slip * 100

        return Trade(
            ticker=signal.ticker,
            stock_name=signal.stock_name,
            event_date=event_date,
            entry_dt=entry_dt,
            entry_px=entry_price_with_slip,
            exit_dt=exit_dt,
            exit_px=exit_price_with_slip,
            exit_type=exit_type,
            return_pct=round(return_pct, 2),
            mfe=round(mfe, 2),
            mae=round(mae, 2),
            holding_bars=holding_bars,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            net_pnl=net_pnl
        )

    # ============================================================
    # 확장 청산 시뮬레이션 (수익 시 익일 이월)
    # ============================================================

    def simulate_trade_extended(
        self,
        signal: Signal,
        minute_df: pd.DataFrame,
        event_date: date
    ) -> Optional[Trade]:
        """
        확장 청산 시뮬레이션 (수익 시 익일 이월)

        청산 조건 (우선순위):
        1. HARD_STOP: bar_low <= entry * 0.96 (-4%) → 즉시 청산
        2. ATR_TS: close <= trailing_stop → 즉시 청산
        3. MAX_HOLDING: 보유 봉 수 초과 → 청산
        4. END_OF_DATA (다일 데이터 끝) → 청산

        수익 시 익일 이월되어 ATR_TS까지 보유
        """
        # 지표가 없으면 계산
        if "ema3" not in minute_df.columns:
            minute_df = self.calculate_indicators(minute_df)

        # 진입 설정
        entry_price = signal.signal_price
        entry_price_with_slip = int(entry_price * (1 + self.config.slippage_rate))
        entry_dt = signal.signal_datetime

        # 수량 계산
        quantity = self.config.investment_per_trade // entry_price_with_slip
        if quantity < 1:
            return None

        # 손절가
        stop_loss_price = int(entry_price_with_slip * (1 + self.config.stop_loss_rate / 100))

        # 진입 인덱스 찾기
        entry_idx = None
        for i, idx in enumerate(minute_df.index):
            if idx >= entry_dt:
                entry_idx = i
                break

        if entry_idx is None:
            self.logger.warning(f"진입 시점 찾기 실패: {entry_dt}")
            return None

        # 초기 ATR 트레일링 스탑
        initial_atr = minute_df["atr"].iloc[entry_idx] if entry_idx < len(minute_df) else 0
        if initial_atr > 0 and pd.notna(initial_atr):
            trailing_stop = entry_price_with_slip - (initial_atr * self.config.atr_mult)
        else:
            trailing_stop = float(stop_loss_price)

        # 청산 시뮬레이션
        exit_price = None
        exit_dt = None
        exit_type = None

        mfe = 0.0  # Maximum Favorable Excursion
        mae = 0.0  # Maximum Adverse Excursion
        holding_bars = 0

        for i in range(entry_idx + 1, len(minute_df)):
            bar = minute_df.iloc[i]
            bar_dt = bar.name
            holding_bars = i - entry_idx

            # MFE/MAE 업데이트
            high_return = (bar["high"] - entry_price_with_slip) / entry_price_with_slip * 100
            low_return = (bar["low"] - entry_price_with_slip) / entry_price_with_slip * 100

            if high_return > mfe:
                mfe = high_return
            if low_return < mae:
                mae = low_return

            # 1순위: 고정 손절 (-4%)
            if bar["low"] <= stop_loss_price:
                exit_price = stop_loss_price
                exit_dt = bar_dt
                exit_type = "HARD_STOP"
                break

            # ATR 트레일링 스탑 업데이트
            atr = minute_df["atr"].iloc[i] if pd.notna(minute_df["atr"].iloc[i]) else initial_atr
            if atr > 0:
                hlc3 = (bar["high"] + bar["low"] + bar["close"]) / 3
                new_ts = hlc3 - (atr * self.config.atr_mult)
                if new_ts > trailing_stop:
                    trailing_stop = new_ts

            # 2순위: ATR 트레일링 스탑
            if bar["close"] <= trailing_stop:
                exit_price = int(trailing_stop)
                exit_dt = bar_dt
                exit_type = "ATR_TS"
                break

            # 3순위: 최대 보유 봉 수
            if holding_bars >= self.config.max_holding_bars:
                exit_price = int(bar["close"])
                exit_dt = bar_dt
                exit_type = "MAX_HOLDING"
                break

        # 청산 안됐으면 마지막 봉에서 청산 (다일 데이터 끝)
        if exit_price is None:
            last_bar = minute_df.iloc[-1]
            exit_price = int(last_bar["close"])
            exit_dt = last_bar.name
            exit_type = "END_OF_DATA"

        # 비용 계산
        exit_price_with_slip = int(exit_price * (1 - self.config.slippage_rate))
        entry_cost = int(entry_price_with_slip * quantity * self.config.commission_rate)
        exit_cost = int(exit_price_with_slip * quantity * (self.config.commission_rate + self.config.tax_rate))
        total_cost = entry_cost + exit_cost

        # 손익 계산
        gross_pnl = (exit_price_with_slip - entry_price_with_slip) * quantity
        net_pnl = gross_pnl - total_cost
        return_pct = (exit_price_with_slip - entry_price_with_slip) / entry_price_with_slip * 100

        return Trade(
            ticker=signal.ticker,
            stock_name=signal.stock_name,
            event_date=event_date,
            entry_dt=entry_dt,
            entry_px=entry_price_with_slip,
            exit_dt=exit_dt,
            exit_px=exit_price_with_slip,
            exit_type=exit_type,
            return_pct=round(return_pct, 2),
            mfe=round(mfe, 2),
            mae=round(mae, 2),
            holding_bars=holding_bars,
            gross_pnl=gross_pnl,
            total_cost=total_cost,
            net_pnl=net_pnl
        )
