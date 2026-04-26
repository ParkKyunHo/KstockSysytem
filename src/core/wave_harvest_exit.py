"""
Wave Harvest 청산 시스템 (V7.0)

추세 추종용 파동 수확 시스템으로, 단기 변동성 노이즈에 조기 청산되지 않고
주도주의 주 추세 파동(20~40%+)을 최대한 보유하며 구조 붕괴 시에만 청산합니다.

핵심 원칙:
- BasePrice = Highest(High, N) - 현재가 기준 금지
- TrailingStop = BasePrice - ATR × Multiplier
- 스탑은 상향 단방향만 (하락 금지)
- ATR 배수는 단방향 축소만 (재증가 금지)
- Trend Hold 구간에서는 청산 신호 무시

절대 금지:
- 현재가 기준 ATR trailing (stop = close - ATR × k)
- 가격 하락 시 스탑 하락
- ATR 배수 재증가 (6 → 4 → 6 불가)
- EMA 단순 이탈 전량 청산
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple
import pandas as pd
import numpy as np

from src.core.indicator_purple import PurpleIndicator
from src.core.exit.base_exit import BaseExit, TrendHoldMixin, ExitDecision, ExitReason
from src.utils.logger import get_logger


# ===== Wave Harvest 설정 =====
FIXED_STOP_PERCENT = 0.04     # -4% 고정 손절 (Fallback)
ATR_PERIOD = 10               # ATR 계산 기간
BASE_PRICE_PERIOD = 20        # 고점 기준가 기간 (Highest High)

# ATR 배수 단계 (단방향 축소만)
ATR_MULT_DEFAULT = 6.0        # 초기 진입
ATR_MULT_WARNING = 4.5        # 구조 경고
ATR_MULT_1R = 4.0             # R >= 1
ATR_MULT_2R = 3.5             # R >= 2
ATR_MULT_3R = 2.5             # R >= 3
ATR_MULT_5R = 2.0             # R >= 5

# Trend Hold Filter 기간
TREND_HOLD_EMA_SHORT = 20
TREND_HOLD_EMA_LONG = 60
TREND_HOLD_ATR_LOOKBACK = 5


@dataclass
class PositionExitState:
    """
    포지션 청산 상태

    각 포지션의 청산 관련 상태를 추적합니다.
    ATR 배수의 단방향 축소와 스탑의 상향 단방향을 보장합니다.

    Attributes:
        stock_code: 종목코드
        entry_price: 진입가
        entry_date: 진입일
        highest_high: 고점 기준가 (BasePrice)
        current_multiplier: 현재 ATR 배수 (6.0 → 2.0 단방향)
        trailing_stop: 트레일링 스탑
        initial_risk: 초기 리스크 (entry × 4%)
        r_multiple: 현재 R-Multiple
        has_structure_warning: 구조 경고 발생 여부
    """
    stock_code: str
    entry_price: int
    entry_date: datetime = field(default_factory=datetime.now)
    highest_high: int = 0             # 고점 기준가
    current_multiplier: float = ATR_MULT_DEFAULT  # ATR 배수
    trailing_stop: int = 0            # 트레일링 스탑
    initial_risk: float = 0           # 초기 리스크
    r_multiple: float = 0.0           # 현재 R
    has_structure_warning: bool = False  # 구조 경고 발생 여부

    def __post_init__(self):
        """초기화 후 처리"""
        if self.initial_risk == 0:
            self.initial_risk = self.entry_price * FIXED_STOP_PERCENT
        if self.highest_high == 0:
            self.highest_high = self.entry_price
        if self.trailing_stop == 0:
            self.trailing_stop = self.get_fallback_stop()

    def get_fallback_stop(self) -> int:
        """Fallback 손절가 (-4%)"""
        return int(self.entry_price * (1 - FIXED_STOP_PERCENT))


class WaveHarvestExit(BaseExit, TrendHoldMixin):
    """
    Wave Harvest 청산 시스템

    BaseExit ABC를 상속하여 전략 플러그인 아키텍처와 호환됩니다.
    TrendHoldMixin: Trend Hold Filter 기능 제공

    추세 추종용 파동 수확 시스템으로, R-Multiple 기반 ATR 배수 축소와
    Trend Hold Filter를 통해 주 추세 파동을 최대한 보유합니다.

    Features:
    - 고점 기준가 (Highest High) 기반 트레일링
    - R-Multiple 기반 ATR 배수 단방향 축소
    - 구조 경고 시 배수 축소
    - Trend Hold Filter로 청산 신호 차단
    - Fallback 정책 (-4% 고정 손절)

    Usage:
        exit_mgr = WaveHarvestExit()
        state = exit_mgr.create_state(stock_code="005930", entry_price=50000)
        should_exit = exit_mgr.update_and_check(state, df, current_price=52000)
    """

    def __init__(self, atr_period: int = ATR_PERIOD, base_price_period: int = BASE_PRICE_PERIOD):
        """
        WaveHarvestExit 초기화

        Args:
            atr_period: ATR 계산 기간
            base_price_period: 고점 기준가 기간
        """
        self.atr_period = atr_period
        self.base_price_period = base_price_period
        self._logger = get_logger(__name__)

    # ===== BaseExit ABC 구현 =====

    @property
    def strategy_name(self) -> str:
        return "WAVE_HARVEST"

    def check_exit(
        self,
        df: pd.DataFrame,
        entry_price: int,
        current_price: int,
        **kwargs
    ) -> ExitDecision:
        """
        BaseExit ABC 구현: 청산 여부 확인

        기존 update_and_check() 로직에 위임합니다.
        kwargs에서 state를 전달받거나 필요한 정보로 임시 state를 생성합니다.
        """
        # 고정 손절 최우선 (BaseExit 헬퍼 사용)
        hard_stop = BaseExit.check_hard_stop(self, entry_price, current_price)
        if hard_stop and hard_stop.should_exit:
            return hard_stop

        # state가 전달된 경우 사용
        state = kwargs.get('state')
        if state is None:
            return ExitDecision(should_exit=False)

        bar_low = kwargs.get('bar_low')
        should_exit, reason = self.update_and_check(state, df, current_price, bar_low)

        if should_exit:
            profit_rate = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
            r_multiple = self.calculate_r_multiple(current_price, entry_price)
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.TRAILING_STOP,
                exit_price=current_price,
                stop_price=state.trailing_stop,
                profit_rate=profit_rate,
                r_multiple=r_multiple,
                metadata={"detail": reason, "multiplier": state.current_multiplier},
            )

        return ExitDecision(
            should_exit=False,
            stop_price=state.trailing_stop,
        )

    def update_trailing_stop(
        self,
        df: pd.DataFrame,
        current_stop: int,
        current_price: int,
        **kwargs
    ) -> Tuple[int, float]:
        """
        BaseExit ABC 구현: 트레일링 스탑 업데이트

        스탑은 상향만 허용 (enforce_stop_direction 사용).
        ATR 배수는 축소만 허용 (enforce_multiplier_direction 사용).
        """
        current_multiplier = kwargs.get('current_multiplier', ATR_MULT_DEFAULT)
        entry_price = kwargs.get('entry_price', 0)
        has_structure_warning = kwargs.get('has_structure_warning', False)

        if df is None or len(df) < self.base_price_period:
            return current_stop, current_multiplier

        # 고점 기준가
        base_price = self.calculate_base_price(df)

        # R-Multiple
        r_multiple = self.calculate_r_multiple(current_price, entry_price) if entry_price > 0 else 0.0

        # 구조 경고 확인
        if not has_structure_warning:
            has_structure_warning = self.check_structure_warning(df, current_price, entry_price)

        # ATR 배수 결정 (단방향 축소 - enforce_multiplier_direction 사용)
        new_mult = self.get_multiplier(r_multiple, has_structure_warning, current_multiplier)
        new_mult = self.enforce_multiplier_direction(new_mult, current_multiplier)

        # ATR 계산
        atr = self.calculate_atr(df)
        if pd.isna(atr) or atr <= 0:
            return current_stop, new_mult

        # 트레일링 스탑 계산 (상향 단방향 - enforce_stop_direction 사용)
        new_stop = self.calculate_trailing_stop(base_price, atr, new_mult)
        new_stop = self.enforce_stop_direction(new_stop, current_stop)

        return new_stop, new_mult

    def create_state(
        self,
        stock_code: str,
        entry_price: int,
        entry_date: Optional[datetime] = None
    ) -> PositionExitState:
        """
        새 포지션 청산 상태 생성

        Args:
            stock_code: 종목코드
            entry_price: 진입가
            entry_date: 진입일

        Returns:
            PositionExitState
        """
        return PositionExitState(
            stock_code=stock_code,
            entry_price=entry_price,
            entry_date=entry_date or datetime.now(),
        )

    def calculate_base_price(self, df: pd.DataFrame, period: Optional[int] = None) -> int:
        """
        고점 기준가 계산 (BasePrice)

        BasePrice = Highest(High, N)
        절대 현재가 사용 금지!

        Args:
            df: OHLCV DataFrame
            period: 기간 (기본: base_price_period)

        Returns:
            고점 기준가
        """
        period = period or self.base_price_period
        if len(df) < period:
            return int(df['high'].max())
        return int(df['high'].rolling(window=period).max().iloc[-1])

    def calculate_atr(self, df: pd.DataFrame, period: Optional[int] = None) -> float:
        """
        ATR (Average True Range) 계산

        Wilder's RMA 방식 (alpha = 1/period)

        Args:
            df: OHLCV DataFrame
            period: 기간

        Returns:
            ATR 값
        """
        period = period or self.atr_period

        if len(df) < period:
            # 데이터 부족 시 단순 계산
            return float((df['high'] - df['low']).mean())

        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - prev_close)
        tr3 = abs(df['low'] - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Wilder's RMA
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
        return float(atr.iloc[-1])

    def calculate_trailing_stop(
        self,
        base_price: int,
        atr: float,
        multiplier: float
    ) -> int:
        """
        트레일링 스탑 계산

        TrailingStop = BasePrice - ATR × Multiplier

        Args:
            base_price: 고점 기준가
            atr: ATR 값
            multiplier: ATR 배수

        Returns:
            트레일링 스탑 가격
        """
        return int(base_price - (atr * multiplier))

    def update_stop(self, new_stop: int, prev_stop: int) -> int:
        """
        스탑 업데이트 (상향 단방향)

        스탑은 절대 하락하지 않습니다.

        Args:
            new_stop: 새 스탑
            prev_stop: 이전 스탑

        Returns:
            업데이트된 스탑 (max(new, prev))
        """
        return max(new_stop, prev_stop)

    def calculate_r_multiple(self, current_price: int, entry_price: int) -> float:
        """
        R-Multiple 계산

        R = (CurrentPrice - EntryPrice) / InitialRisk
        InitialRisk = entry_price × 4%

        Args:
            current_price: 현재가
            entry_price: 진입가

        Returns:
            R-Multiple
        """
        initial_risk = entry_price * FIXED_STOP_PERCENT
        if initial_risk == 0:
            return 0.0
        return (current_price - entry_price) / initial_risk

    def get_multiplier(
        self,
        r_multiple: float,
        structure_warning: bool,
        current_mult: float
    ) -> float:
        """
        ATR 배수 결정 (단방향 축소)

        배수는 절대 증가하지 않습니다.
        6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0

        Args:
            r_multiple: 현재 R-Multiple
            structure_warning: 구조 경고 여부
            current_mult: 현재 배수

        Returns:
            새 배수 (min 적용)
        """
        mult = current_mult  # 현재 값에서 시작

        # 구조 경고 시 축소
        if structure_warning:
            mult = min(mult, ATR_MULT_WARNING)

        # R-Multiple에 따른 축소
        if r_multiple >= 5:
            mult = min(mult, ATR_MULT_5R)
        elif r_multiple >= 3:
            mult = min(mult, ATR_MULT_3R)
        elif r_multiple >= 2:
            mult = min(mult, ATR_MULT_2R)
        elif r_multiple >= 1:
            mult = min(mult, ATR_MULT_1R)

        return mult

    def check_structure_warning(
        self,
        df: pd.DataFrame,
        current_price: int,
        entry_price: int
    ) -> bool:
        """
        구조 경고 확인

        EMA, VWAP, 고저 이탈 등 구조적 약화 신호 확인.

        Args:
            df: OHLCV DataFrame
            current_price: 현재가
            entry_price: 진입가

        Returns:
            True: 구조 경고, False: 정상
        """
        if len(df) < max(TREND_HOLD_EMA_SHORT, TREND_HOLD_EMA_LONG):
            return False

        close = df['close']
        ema20 = PurpleIndicator.ema(close, TREND_HOLD_EMA_SHORT)
        ema60 = PurpleIndicator.ema(close, TREND_HOLD_EMA_LONG)

        current_ema20 = float(ema20.iloc[-1])
        current_ema60 = float(ema60.iloc[-1])

        # 구조 경고 조건:
        # 1. EMA20 < EMA60 (단기선 장기선 하회)
        # 2. 현재가 < EMA20 (단기선 이탈)
        ema_warning = current_ema20 < current_ema60 or current_price < current_ema20

        return ema_warning

    def check_trend_hold(self, df: pd.DataFrame) -> bool:
        """
        Trend Hold Filter

        다음 조건이 모두 충족되면 청산 신호 무시:
        - EMA20 > EMA60
        - HighestHigh(20) > HighestHigh(60)
        - ATR(10) >= ATR(10)[5]

        Args:
            df: OHLCV DataFrame

        Returns:
            True: Trend Hold (청산 차단), False: 청산 허용
        """
        if len(df) < max(TREND_HOLD_EMA_LONG, TREND_HOLD_ATR_LOOKBACK + self.atr_period):
            return False

        close = df['close']
        high = df['high']

        # EMA 조건
        ema20 = PurpleIndicator.ema(close, TREND_HOLD_EMA_SHORT)
        ema60 = PurpleIndicator.ema(close, TREND_HOLD_EMA_LONG)
        ema_condition = float(ema20.iloc[-1]) > float(ema60.iloc[-1])

        # 고점 조건
        hh20 = high.rolling(window=TREND_HOLD_EMA_SHORT).max().iloc[-1]
        hh60 = high.rolling(window=TREND_HOLD_EMA_LONG).max().iloc[-1]
        hh_condition = hh20 >= hh60  # 최근 고점이 장기 고점 이상

        # ATR 조건 (변동성 유지)
        atr_current = self.calculate_atr(df, self.atr_period)
        if len(df) > TREND_HOLD_ATR_LOOKBACK:
            atr_past = self.calculate_atr(df.iloc[:-TREND_HOLD_ATR_LOOKBACK], self.atr_period)
            atr_condition = atr_current >= atr_past * 0.8  # 20% 감소까지 허용
        else:
            atr_condition = True

        return ema_condition and hh_condition and atr_condition

    def should_exit(
        self,
        close: int,
        trailing_stop: int,
        trend_hold: bool
    ) -> bool:
        """
        청산 실행 조건

        ExitConfirm = (TrendHold == False) AND (Close < TrailingStop)

        Args:
            close: 현재 종가
            trailing_stop: 트레일링 스탑
            trend_hold: Trend Hold 상태

        Returns:
            True: 청산, False: 보유
        """
        # Trend Hold 중이면 청산 차단
        if trend_hold:
            return False

        # 스탑 이탈 확인
        return close < trailing_stop

    def get_fallback_stop(self, entry_price: int) -> int:
        """
        Fallback 손절가

        ATR 계산 실패, TS 값 NaN 등의 경우 사용.

        Args:
            entry_price: 진입가

        Returns:
            Fallback 스탑 (entry × 0.96)
        """
        return int(entry_price * (1 - FIXED_STOP_PERCENT))

    def update_and_check(
        self,
        state: PositionExitState,
        df: pd.DataFrame,
        current_price: int,
        bar_low: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        상태 업데이트 및 청산 체크 (통합 메서드)

        1. 고점 기준가 업데이트
        2. R-Multiple 계산
        3. 구조 경고 확인
        4. ATR 배수 결정 (단방향 축소)
        5. 트레일링 스탑 계산 (상향 단방향)
        6. Trend Hold 확인
        7. 청산 조건 확인

        Args:
            state: 포지션 청산 상태
            df: OHLCV DataFrame
            current_price: 현재가
            bar_low: 봉 저가 (손절 체크용)

        Returns:
            (should_exit, reason) 튜플
        """
        reason = ""

        # 1. Fallback 체크 (데이터 부족)
        if df is None or len(df) < self.base_price_period:
            # 데이터 부족 시 고정 손절만 확인
            fallback_stop = self.get_fallback_stop(state.entry_price)
            if current_price < fallback_stop:
                return True, "FALLBACK_STOP"
            return False, ""

        try:
            # 2. 고점 기준가 업데이트
            new_highest = self.calculate_base_price(df)
            if new_highest > state.highest_high:
                state.highest_high = new_highest

            # 3. R-Multiple 계산
            state.r_multiple = self.calculate_r_multiple(current_price, state.entry_price)

            # 4. 구조 경고 확인
            structure_warning = self.check_structure_warning(df, current_price, state.entry_price)
            if structure_warning and not state.has_structure_warning:
                state.has_structure_warning = True

            # 5. ATR 배수 결정 (단방향 축소)
            new_mult = self.get_multiplier(
                state.r_multiple,
                state.has_structure_warning,
                state.current_multiplier
            )
            if new_mult < state.current_multiplier:
                state.current_multiplier = new_mult

            # 6. ATR 계산
            atr = self.calculate_atr(df)
            if pd.isna(atr) or atr <= 0:
                # ATR 계산 실패 시 Fallback
                fallback_stop = self.get_fallback_stop(state.entry_price)
                if current_price < fallback_stop:
                    return True, "ATR_FALLBACK_STOP"
                return False, ""

            # 7. 트레일링 스탑 계산 (상향 단방향)
            new_stop = self.calculate_trailing_stop(
                state.highest_high,
                atr,
                state.current_multiplier
            )
            state.trailing_stop = self.update_stop(new_stop, state.trailing_stop)

            # 8. Fallback 스탑보다 낮으면 Fallback 사용
            fallback_stop = self.get_fallback_stop(state.entry_price)
            if state.trailing_stop < fallback_stop:
                state.trailing_stop = fallback_stop

            # 9. Hard Stop (-4%) - Trend Hold보다 먼저 확인 (Risk-First)
            check_price = bar_low if bar_low is not None else current_price
            if check_price <= fallback_stop:
                return True, "HARD_STOP_-4%"

            # 10. Trend Hold 확인
            trend_hold = self.check_trend_hold(df)

            # 11. 봉 저가 손절 확인 (bar_low < trailing_stop)
            if self.should_exit(check_price, state.trailing_stop, trend_hold):
                reason = f"ATR_TS_{state.current_multiplier:.1f}x"
                if state.r_multiple >= 1:
                    reason += f"_R{state.r_multiple:.1f}"
                return True, reason

            return False, ""

        except Exception as e:
            # [C-004] 예외 발생 시 로깅 후 Fallback
            self._logger.error(
                f"[WaveHarvestExit] update_and_check 예외 발생: {state.stock_code} | "
                f"error={type(e).__name__}: {str(e)} | "
                f"entry={state.entry_price:,} | current={current_price:,}",
                exc_info=True
            )
            fallback_stop = self.get_fallback_stop(state.entry_price)
            if current_price < fallback_stop:
                return True, f"EXCEPTION_FALLBACK: {str(e)}"
            return False, f"EXCEPTION_NOEXIT: {type(e).__name__}: {str(e)}"

    def check_hard_stop(self, entry_price: int, current_price: int) -> bool:
        """
        고정 손절 (-4%) 확인

        ATR TS와 별개로 항상 확인하는 최종 안전장치.
        파라미터 순서는 BaseExit와 동일 (entry_price, current_price).

        Args:
            entry_price: 진입가
            current_price: 현재가

        Returns:
            True: 손절, False: 유지
        """
        stop_price = self.get_fallback_stop(entry_price)
        return current_price <= stop_price

    def check_max_holding_days(
        self,
        entry_date: datetime,
        max_days: int = 60
    ) -> bool:
        """
        최대 보유일 확인

        Args:
            entry_date: 진입일
            max_days: 최대 보유일 (기본 60일)

        Returns:
            True: 초과, False: 유지
        """
        holding_days = (datetime.now() - entry_date).days
        return holding_days > max_days

    def get_exit_summary(self, state: PositionExitState, current_price: int) -> dict:
        """
        청산 상태 요약

        Args:
            state: 포지션 청산 상태
            current_price: 현재가

        Returns:
            상태 요약 딕셔너리
        """
        profit_pct = ((current_price - state.entry_price) / state.entry_price) * 100

        return {
            "stock_code": state.stock_code,
            "entry_price": state.entry_price,
            "current_price": current_price,
            "profit_pct": round(profit_pct, 2),
            "r_multiple": round(state.r_multiple, 2),
            "highest_high": state.highest_high,
            "trailing_stop": state.trailing_stop,
            "atr_multiplier": state.current_multiplier,
            "has_structure_warning": state.has_structure_warning,
            "holding_days": (datetime.now() - state.entry_date).days,
        }
