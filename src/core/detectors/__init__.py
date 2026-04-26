"""
신호 탐지기 모듈 (Phase 2 리팩토링)

전략별 신호 탐지기와 통합 추상 클래스를 제공합니다.

Usage:
    from src.core.detectors import BaseDetector
    from src.core.detectors.sniper_detector import SniperDetectorV2
    from src.core.detectors.purple_detector import PurpleDetectorV2
"""

from src.core.detectors.base_detector import BaseDetector

__all__ = [
    "BaseDetector",
]
