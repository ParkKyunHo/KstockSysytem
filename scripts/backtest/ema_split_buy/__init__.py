# -*- coding: utf-8 -*-
"""
EMA_SPLIT_BUY 백테스트 패키지

EMA 분할매수 전략 백테스트 시스템
- 5일선/8일선 근접 시 분할 매수
- 고정 5% 손절 vs ATR 트레일링 스탑 비교
- 3영업일 종가 청산
"""

from .config import EMASplitBuyConfig, SplitBuyState, SplitBuyPosition, SplitBuyTrade
from .data_loader import DataLoader
from .indicators import calculate_indicators
from .signal_detector import SignalDetector
from .trade_simulator import TradeSimulator
from .optimizer import Optimizer
from .exporter import ExcelExporter

__all__ = [
    "EMASplitBuyConfig",
    "SplitBuyState",
    "SplitBuyPosition",
    "SplitBuyTrade",
    "DataLoader",
    "calculate_indicators",
    "SignalDetector",
    "TradeSimulator",
    "Optimizer",
    "ExcelExporter",
]
