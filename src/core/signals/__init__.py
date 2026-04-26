"""
신호 모듈 (Phase 2 리팩토링)

전략별 신호 클래스와 통합 추상 클래스를 제공합니다.

Usage:
    from src.core.signals import BaseSignal, SignalType, StrategyType
    from src.core.signals.sniper_signal import SniperSignal
    from src.core.signals.purple_signal import PurpleSignalV2
"""

from src.core.signals.base_signal import BaseSignal, SignalType, StrategyType

__all__ = [
    "BaseSignal",
    "SignalType",
    "StrategyType",
]
