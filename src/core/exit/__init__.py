"""
청산 전략 모듈 (Phase 2 리팩토링)

전략별 청산 로직과 통합 추상 클래스를 제공합니다.

Usage:
    from src.core.exit import BaseExit, ExitDecision, ExitReason
    from src.core.exit.v6_exit import V6ExitStrategy
    from src.core.exit.wave_harvest import WaveHarvestStrategy
"""

from src.core.exit.base_exit import BaseExit, ExitDecision, ExitReason

__all__ = [
    "BaseExit",
    "ExitDecision",
    "ExitReason",
]
