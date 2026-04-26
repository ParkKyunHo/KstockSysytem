"""
데이터베이스 계층 모듈

PostgreSQL (메인) + SQLite (폴백) 이중 구조를 지원합니다.
"""

from src.database.models import (
    Base,
    Trade,
    Order,
    DailyStats,
    Signal,
    SystemLog,
    OrderSide,
    OrderStatus,
    TradeStatus,
)
from src.database.connection import (
    DatabaseManager,
    get_db_manager,
    init_database,
    close_database,
)
from src.database.repository import (
    TradeRepository,
    OrderRepository,
    DailyStatsRepository,
    SignalRepository,
    SystemLogRepository,
    get_trade_repository,
    get_order_repository,
    get_daily_stats_repository,
    get_signal_repository,
    get_system_log_repository,
)

__all__ = [
    # Base
    "Base",

    # Models
    "Trade",
    "Order",
    "DailyStats",
    "Signal",
    "SystemLog",

    # Enums
    "OrderSide",
    "OrderStatus",
    "TradeStatus",

    # Connection
    "DatabaseManager",
    "get_db_manager",
    "init_database",
    "close_database",

    # Repositories
    "TradeRepository",
    "OrderRepository",
    "DailyStatsRepository",
    "SignalRepository",
    "SystemLogRepository",
    "get_trade_repository",
    "get_order_repository",
    "get_daily_stats_repository",
    "get_signal_repository",
    "get_system_log_repository",
]
