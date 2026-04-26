#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
K-Stock Backtest Engine Launcher

백테스팅 프로그램 실행 스크립트

Usage:
    python run_backtest_ui.py

Requirements:
    pip install PyQt6 pyqtgraph pandas numpy
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtest.ui.app import main

if __name__ == "__main__":
    main()
