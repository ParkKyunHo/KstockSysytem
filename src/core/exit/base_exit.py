"""
청산 전략 추상 기본 클래스 (Phase 2 리팩토링)

모든 전략의 청산 로직이 상속받는 기본 인터페이스를 정의합니다.

CLAUDE.md 불변 조건:
- 고정 손절 -4% 최우선 (Risk-First)
- 트레일링 스탑 상향 단방향만 (TS 상향 전용)
- ATR 배수 단방향 축소만 (복원 불가)

Usage:
    from src.core.exit import BaseExit, ExitDecision, ExitReason

    class MyExit(BaseExit):
        @property
        def strategy_name(self) -> str:
            return "MY_STRATEGY"

        def check_exit(self, df, entry_price, current_price, **kwargs):
            # 청산 조건 검사
            return ExitDecision(should_exit=True, reason=ExitReason.HARD_STOP, ...)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, Tuple
import pandas as pd


class ExitReason(str, Enum):
    """청산 사유"""
    # 손절
    HARD_STOP = "HARD_STOP"              # 고정 손절 (-4%)
    TRAILING_STOP = "TRAILING_STOP"      # 트레일링 스탑 이탈

    # 익절
    TARGET_PROFIT = "TARGET_PROFIT"      # 목표 수익 도달
    PARTIAL_PROFIT = "PARTIAL_PROFIT"    # 분할 익절

    # 시간 기반
    MAX_HOLDING_DAYS = "MAX_HOLDING_DAYS"  # 최대 보유일 초과
    END_OF_DAY = "END_OF_DAY"            # 장 마감

    # 전략 기반
    STRUCTURE_BREAK = "STRUCTURE_BREAK"  # 구조 붕괴
    TREND_REVERSAL = "TREND_REVERSAL"    # 추세 전환

    # 기타
    MANUAL = "MANUAL"                    # 수동 청산
    SYSTEM = "SYSTEM"                    # 시스템 청산


@dataclass
class ExitDecision:
    """
    청산 결정 데이터

    청산 여부와 관련 정보를 담는 데이터 클래스입니다.

    Attributes:
        should_exit: 청산 여부
        reason: 청산 사유
        exit_price: 청산 가격
        stop_price: 현재 스탑 가격
        profit_rate: 수익률 (%)
        r_multiple: R-Multiple (리스크 대비 수익)
        metadata: 추가 정보
    """
    should_exit: bool = False
    reason: Optional[ExitReason] = None
    exit_price: int = 0
    stop_price: int = 0
    profit_rate: float = 0.0
    r_multiple: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "should_exit": self.should_exit,
            "reason": self.reason.value if self.reason else None,
            "exit_price": self.exit_price,
            "stop_price": self.stop_price,
            "profit_rate": round(self.profit_rate, 2),
            "r_multiple": round(self.r_multiple, 2),
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        if self.should_exit:
            return (
                f"EXIT: {self.reason.value if self.reason else 'UNKNOWN'} "
                f"@{self.exit_price:,}원 ({self.profit_rate:+.2f}%)"
            )
        return f"HOLD (stop={self.stop_price:,}원)"


class BaseExit(ABC):
    """
    청산 전략 추상 기본 클래스

    모든 전략의 청산 로직이 상속받아야 하는 추상 클래스입니다.
    공통 인터페이스와 필수 메서드를 정의합니다.

    CLAUDE.md 불변 조건:
    - 고정 손절 -4% 항상 최우선 검사
    - 트레일링 스탑은 상향만 허용 (하락 금지)
    - ATR 배수는 축소만 허용 (복원 금지)

    필수 구현 속성:
        strategy_name: 전략 이름

    필수 구현 메서드:
        check_exit(): 청산 여부 확인
        update_trailing_stop(): 트레일링 스탑 업데이트
    """

    # 공통 상수 (CLAUDE.md 불변)
    HARD_STOP_RATE = -0.04  # -4% 고정 손절

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """
        전략 이름 반환

        Returns:
            전략 이름 문자열
        """
        pass

    @abstractmethod
    def check_exit(
        self,
        df: pd.DataFrame,
        entry_price: int,
        current_price: int,
        **kwargs
    ) -> ExitDecision:
        """
        청산 여부 확인

        현재 상황에서 청산해야 하는지 확인합니다.
        고정 손절(-4%)은 항상 최우선으로 검사합니다.

        Args:
            df: OHLCV DataFrame
            entry_price: 진입가
            current_price: 현재가
            **kwargs: 전략별 추가 파라미터
                - trailing_stop: 현재 트레일링 스탑
                - entry_date: 진입일
                - current_multiplier: 현재 ATR 배수

        Returns:
            청산 결정
        """
        pass

    @abstractmethod
    def update_trailing_stop(
        self,
        df: pd.DataFrame,
        current_stop: int,
        current_price: int,
        **kwargs
    ) -> Tuple[int, float]:
        """
        트레일링 스탑 업데이트

        새로운 트레일링 스탑을 계산합니다.
        스탑은 상향만 허용됩니다 (CLAUDE.md 불변).

        Args:
            df: OHLCV DataFrame
            current_stop: 현재 스탑 가격
            current_price: 현재가
            **kwargs: 전략별 추가 파라미터

        Returns:
            (새 스탑 가격, 새 ATR 배수) 튜플
        """
        pass

    def check_hard_stop(
        self,
        entry_price: int,
        current_price: int
    ) -> Optional[ExitDecision]:
        """
        고정 손절 확인

        -4% 손절 조건을 확인합니다.
        모든 전략에서 최우선으로 검사해야 합니다.

        Args:
            entry_price: 진입가
            current_price: 현재가

        Returns:
            손절 결정 또는 None
        """
        if entry_price <= 0:
            return None

        profit_rate = (current_price - entry_price) / entry_price

        if profit_rate <= self.HARD_STOP_RATE:
            stop_price = int(entry_price * (1 + self.HARD_STOP_RATE))
            return ExitDecision(
                should_exit=True,
                reason=ExitReason.HARD_STOP,
                exit_price=current_price,
                stop_price=stop_price,
                profit_rate=profit_rate * 100,
                r_multiple=-1.0,  # 고정 손절 = -1R
                metadata={"trigger": "hard_stop_-4%"}
            )

        return None

    def enforce_stop_direction(
        self,
        new_stop: int,
        current_stop: int
    ) -> int:
        """
        스탑 상향 단방향 강제

        스탑은 상향만 허용됩니다 (CLAUDE.md 불변).
        새 스탑이 현재보다 낮으면 현재 스탑을 유지합니다.

        Args:
            new_stop: 새 스탑 가격
            current_stop: 현재 스탑 가격

        Returns:
            적용할 스탑 가격
        """
        return max(new_stop, current_stop)

    def enforce_multiplier_direction(
        self,
        new_multiplier: float,
        current_multiplier: float
    ) -> float:
        """
        ATR 배수 축소 단방향 강제

        ATR 배수는 축소만 허용됩니다 (CLAUDE.md 불변).
        새 배수가 현재보다 크면 현재 배수를 유지합니다.

        Args:
            new_multiplier: 새 ATR 배수
            current_multiplier: 현재 ATR 배수

        Returns:
            적용할 ATR 배수
        """
        return min(new_multiplier, current_multiplier)

    def calculate_r_multiple(
        self,
        entry_price: int,
        current_price: int,
        risk_percent: float = 0.04
    ) -> float:
        """
        R-Multiple 계산

        R = (현재가 - 진입가) / (진입가 × risk_percent)

        Args:
            entry_price: 진입가
            current_price: 현재가
            risk_percent: 리스크 비율 (기본 4%)

        Returns:
            R-Multiple
        """
        if entry_price <= 0 or risk_percent <= 0:
            return 0.0

        risk_amount = entry_price * risk_percent
        profit = current_price - entry_price
        return profit / risk_amount

    def __str__(self) -> str:
        """문자열 표현"""
        return f"{self.__class__.__name__}(strategy={self.strategy_name})"


class TrendHoldMixin:
    """
    Trend Hold Filter 믹스인

    추세 지속 구간에서 청산을 차단하는 필터를 제공합니다.
    V7 Wave Harvest 전략에서 사용됩니다.

    Trend Hold 조건:
    - EMA20 > EMA60 (단기 추세 > 장기 추세)
    - Highest(High, 20) > Highest(High, 60) (고점 갱신)

    조건 충족 시 트레일링 스탑 청산을 차단합니다.
    (고정 손절 -4%는 항상 작동)
    """

    def check_trend_hold(
        self,
        df: pd.DataFrame,
        ema_short_period: int = 20,
        ema_long_period: int = 60
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Trend Hold 조건 확인

        Args:
            df: OHLCV DataFrame
            ema_short_period: 단기 EMA 기간 (기본 20)
            ema_long_period: 장기 EMA 기간 (기본 60)

        Returns:
            (Trend Hold 여부, 세부 정보 딕셔너리)
        """
        if df is None or len(df) < ema_long_period:
            return False, {"error": "insufficient_data"}

        # EMA 계산
        from src.core.indicator_library import IndicatorLibrary

        close = df["close"]
        high = df["high"]

        ema_short = IndicatorLibrary.ema(close, ema_short_period)
        ema_long = IndicatorLibrary.ema(close, ema_long_period)

        # Highest High 계산
        hh_short = IndicatorLibrary.highest_high(high, ema_short_period)
        hh_long = IndicatorLibrary.highest_high(high, ema_long_period)

        # 최신 값
        latest_ema_short = ema_short.iloc[-1]
        latest_ema_long = ema_long.iloc[-1]
        latest_hh_short = hh_short.iloc[-1]
        latest_hh_long = hh_long.iloc[-1]

        # Trend Hold 조건
        ema_condition = latest_ema_short > latest_ema_long
        hh_condition = latest_hh_short > latest_hh_long

        is_trend_hold = ema_condition and hh_condition

        details = {
            "ema_short": latest_ema_short,
            "ema_long": latest_ema_long,
            "ema_condition": ema_condition,
            "hh_short": latest_hh_short,
            "hh_long": latest_hh_long,
            "hh_condition": hh_condition,
            "is_trend_hold": is_trend_hold,
        }

        return is_trend_hold, details
