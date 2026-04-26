"""
신호 탐지기 추상 기본 클래스 (Phase 2 리팩토링)

모든 전략의 신호 탐지기가 상속받는 기본 인터페이스를 정의합니다.

CLAUDE.md 불변 조건:
- 기존 SniperTrapDetector, PurpleSignalDetector API 호환성 유지
- detect() 메서드 필수 구현

Usage:
    from src.core.detectors import BaseDetector

    class MyDetector(BaseDetector):
        @property
        def strategy_name(self) -> str:
            return "MY_STRATEGY"

        @property
        def min_candles_required(self) -> int:
            return 60

        def detect(self, df, stock_code, stock_name, **kwargs):
            # 신호 탐지 로직
            return MySignal(...) if condition else None
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import pandas as pd

from src.core.signals.base_signal import BaseSignal


class BaseDetector(ABC):
    """
    신호 탐지기 추상 기본 클래스

    모든 전략의 신호 탐지기가 상속받아야 하는 추상 클래스입니다.
    공통 인터페이스와 필수 메서드를 정의합니다.

    필수 구현 속성:
        strategy_name: 전략 이름
        min_candles_required: 신호 탐지에 필요한 최소 캔들 수

    필수 구현 메서드:
        detect(): 신호 탐지 실행
    """

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """
        전략 이름 반환

        Returns:
            전략 이름 문자열 (예: "SNIPER_TRAP", "PURPLE_REABS")
        """
        pass

    @property
    @abstractmethod
    def min_candles_required(self) -> int:
        """
        신호 탐지에 필요한 최소 캔들 수

        지표 계산 warm-up 기간을 고려한 최소 캔들 수입니다.
        예: EMA200 → 최소 205개, EMA60 → 최소 65개

        Returns:
            최소 필요 캔들 수
        """
        pass

    @abstractmethod
    def detect(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        **kwargs
    ) -> Optional[BaseSignal]:
        """
        신호 탐지 실행

        OHLCV DataFrame을 분석하여 매수/매도 신호를 탐지합니다.
        신호가 없으면 None을 반환합니다.

        Args:
            df: OHLCV DataFrame (columns: open, high, low, close, volume)
            stock_code: 종목 코드
            stock_name: 종목명
            **kwargs: 전략별 추가 파라미터

        Returns:
            탐지된 신호 또는 None
        """
        pass

    def is_ready(self, df: pd.DataFrame) -> bool:
        """
        신호 탐지 준비 여부 확인

        데이터가 충분한지 확인합니다.

        Args:
            df: OHLCV DataFrame

        Returns:
            준비 여부
        """
        if df is None or df.empty:
            return False
        return len(df) >= self.min_candles_required

    def validate_dataframe(self, df: pd.DataFrame) -> bool:
        """
        DataFrame 유효성 검증

        필수 컬럼이 모두 있는지 확인합니다.

        Args:
            df: OHLCV DataFrame

        Returns:
            유효 여부
        """
        required_columns = {"open", "high", "low", "close", "volume"}
        if df is None:
            return False
        return required_columns.issubset(df.columns)

    def get_latest_bar(self, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        최신 봉 데이터 반환

        Args:
            df: OHLCV DataFrame

        Returns:
            최신 봉 딕셔너리 또는 None
        """
        if df is None or df.empty:
            return None

        latest = df.iloc[-1]
        return {
            "open": latest["open"],
            "high": latest["high"],
            "low": latest["low"],
            "close": latest["close"],
            "volume": latest["volume"],
        }

    def __str__(self) -> str:
        """문자열 표현"""
        return f"{self.__class__.__name__}(strategy={self.strategy_name})"

    def __repr__(self) -> str:
        """개발자용 표현"""
        return (
            f"{self.__class__.__name__}("
            f"strategy_name='{self.strategy_name}', "
            f"min_candles={self.min_candles_required})"
        )


class MultiConditionMixin:
    """
    다중 조건 탐지 믹스인

    여러 조건을 순차/병렬로 검증하는 헬퍼 메서드를 제공합니다.
    BaseDetector와 함께 사용됩니다.

    Usage:
        class MyDetector(BaseDetector, MultiConditionMixin):
            def detect(self, df, stock_code, stock_name, **kwargs):
                conditions = self.check_all_conditions(df)
                if conditions["all_met"]:
                    return MySignal(...)
    """

    def check_condition(
        self,
        name: str,
        value: bool,
        details: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        단일 조건 검증 결과 생성

        Args:
            name: 조건 이름
            value: 충족 여부
            details: 세부 정보

        Returns:
            조건 결과 딕셔너리
        """
        return {
            "name": name,
            "met": value,
            "details": details or "",
        }

    def aggregate_conditions(
        self,
        conditions: List[Dict[str, Any]],
        required_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        조건 결과 집계

        Args:
            conditions: 개별 조건 결과 리스트
            required_count: 필요 충족 수 (None이면 전체)

        Returns:
            집계 결과 딕셔너리
        """
        met_count = sum(1 for c in conditions if c["met"])
        total_count = len(conditions)
        required = required_count if required_count else total_count

        return {
            "conditions": conditions,
            "met_count": met_count,
            "total_count": total_count,
            "required_count": required,
            "all_met": met_count >= required,
            "met_names": [c["name"] for c in conditions if c["met"]],
            "unmet_names": [c["name"] for c in conditions if not c["met"]],
        }


class DualPassMixin:
    """
    Dual-Pass 탐지 믹스인

    Pre-Check → Confirm-Check 2단계 탐지를 지원합니다.
    V7 Purple-ReAbs 전략에서 사용됩니다.

    Pre-Check: 빠른 필터링 (3/5 조건 충족)
    Confirm-Check: 최종 확인 (5/5 조건 충족)
    """

    def pre_check(
        self,
        df: pd.DataFrame,
        stock_code: str,
        **kwargs
    ) -> bool:
        """
        Pre-Check (사전 검사)

        빠른 필터링을 위한 느슨한 조건 검사입니다.
        구현은 하위 클래스에서 오버라이드합니다.

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드
            **kwargs: 추가 파라미터

        Returns:
            Pre-Check 통과 여부
        """
        return True  # 기본값: 항상 통과

    def confirm_check(
        self,
        df: pd.DataFrame,
        stock_code: str,
        **kwargs
    ) -> bool:
        """
        Confirm-Check (최종 확인)

        엄격한 조건으로 최종 신호를 확인합니다.
        구현은 하위 클래스에서 오버라이드합니다.

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드
            **kwargs: 추가 파라미터

        Returns:
            Confirm-Check 통과 여부
        """
        return True  # 기본값: 항상 통과
