# -*- coding: utf-8 -*-
"""
Daily Equity Curve Backtest

testday.csv 종목 대상 일봉 백테스팅 시스템
지저깨 신호 기반 매수 + ATR 트레일링 스탑 청산
"""

from .config import BacktestConfig, Trade, MonthlyStats, ExitType
from .data_loader import DataLoader
from .signal_detector import SignalDetector
from .trade_simulator import TradeSimulator
from .equity_curve import EquityCurve
from .exporter import ExcelExporter

__all__ = [
    "BacktestConfig",
    "Trade",
    "MonthlyStats",
    "ExitType",
    "DataLoader",
    "SignalDetector",
    "TradeSimulator",
    "EquityCurve",
    "ExcelExporter",
]
