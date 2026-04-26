"""
전략 플러그인 패키지 (V7 리팩토링)

BaseStrategy ABC와 전략 어댑터를 제공합니다.

Usage:
    from src.core.strategies import BaseStrategy
    from src.core.strategies.v7_purple_reabs import V7PurpleReAbsStrategy
    from src.core.strategies.v6_sniper_trap import V6SniperTrapStrategy
"""

from src.core.strategies.base_strategy import BaseStrategy

__all__ = [
    "BaseStrategy",
]
