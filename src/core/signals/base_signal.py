"""
신호 추상 기본 클래스 (Phase 2 리팩토링)

모든 전략의 신호 클래스가 상속받는 기본 인터페이스를 정의합니다.

CLAUDE.md 불변 조건:
- 기존 Signal, PurpleSignal 클래스 API 호환성 유지
- to_dict() 메서드 필수 구현

Usage:
    from src.core.signals import BaseSignal, SignalType, StrategyType

    class MySignal(BaseSignal):
        def get_strength(self) -> float:
            return self._calculate_strength()

        def get_summary(self) -> str:
            return f"My signal for {self.stock_name}"
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional


class SignalType(str, Enum):
    """신호 타입"""
    BUY = "BUY"
    SELL = "SELL"


class StrategyType(str, Enum):
    """전략 타입"""
    SNIPER_TRAP = "SNIPER_TRAP"      # V6 스나이퍼
    PURPLE_REABS = "PURPLE_REABS"    # V7 Purple-ReAbs


@dataclass
class BaseSignal(ABC):
    """
    신호 추상 기본 클래스

    모든 전략의 신호 클래스가 상속받아야 하는 추상 클래스입니다.
    공통 필드와 필수 메서드를 정의합니다.

    공통 필드:
        stock_code: 종목 코드
        stock_name: 종목명
        price: 신호 발생 가격
        timestamp: 신호 발생 시간
        metadata: 추가 정보

    필수 구현 메서드:
        get_strength(): 신호 강도 반환 (0~1)
        get_summary(): 신호 요약 문자열 반환
        to_dict(): 딕셔너리 변환

    Attributes:
        stock_code: 종목 코드 (6자리)
        stock_name: 종목명
        signal_type: 신호 타입 (BUY/SELL)
        strategy: 전략 타입 (SNIPER_TRAP/PURPLE_REABS)
        price: 신호 발생 가격
        timestamp: 신호 발생 시간
        metadata: 추가 정보 딕셔너리
    """

    stock_code: str
    stock_name: str
    signal_type: SignalType
    strategy: StrategyType
    price: int
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def get_strength(self) -> float:
        """
        신호 강도 반환

        신호의 품질/확신도를 0~1 사이 값으로 반환합니다.
        - 0.0: 최저 강도
        - 1.0: 최고 강도

        Returns:
            신호 강도 (0~1)
        """
        pass

    @abstractmethod
    def get_summary(self) -> str:
        """
        신호 요약 문자열 반환

        트레이더가 빠르게 신호를 판단할 수 있는 한 줄 요약입니다.

        Returns:
            신호 요약 문자열
        """
        pass

    def to_dict(self) -> Dict[str, Any]:
        """
        딕셔너리로 변환

        DB 저장, API 응답, 로깅 등에 사용됩니다.

        Returns:
            신호 정보 딕셔너리
        """
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "signal_type": self.signal_type.value,
            "strategy": self.strategy.value,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "strength": self.get_strength(),
            "summary": self.get_summary(),
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        """문자열 표현"""
        return (
            f"[{self.strategy.value}] {self.stock_name}({self.stock_code}) "
            f"{self.signal_type.value} @{self.price:,}원"
        )

    def __repr__(self) -> str:
        """개발자용 표현"""
        return (
            f"{self.__class__.__name__}("
            f"stock_code='{self.stock_code}', "
            f"stock_name='{self.stock_name}', "
            f"signal_type={self.signal_type}, "
            f"strategy={self.strategy}, "
            f"price={self.price})"
        )


# =============================================
# 유틸리티 함수
# =============================================

def is_valid_signal(signal: Optional[BaseSignal]) -> bool:
    """
    유효한 신호인지 검증

    Args:
        signal: 검증할 신호

    Returns:
        유효 여부
    """
    if signal is None:
        return False

    if not signal.stock_code or len(signal.stock_code) != 6:
        return False

    if signal.price <= 0:
        return False

    return True


def compare_signals(signal1: BaseSignal, signal2: BaseSignal) -> int:
    """
    두 신호 비교 (강도 기준)

    Args:
        signal1: 첫 번째 신호
        signal2: 두 번째 신호

    Returns:
        - 양수: signal1이 더 강함
        - 음수: signal2가 더 강함
        - 0: 동일
    """
    strength1 = signal1.get_strength()
    strength2 = signal2.get_strength()

    if strength1 > strength2:
        return 1
    elif strength1 < strength2:
        return -1
    else:
        return 0
