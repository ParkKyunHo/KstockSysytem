"""
키움증권 REST API Wrapper

모의투자/실전투자 전환: IS_PAPER_TRADING 환경 변수로 제어

Usage:
    from src.api import KiwoomAPIClient, TokenManager, KiwoomWebSocket

    # HTTP API
    async with KiwoomAPIClient() as client:
        account_api = AccountAPI(client)
        balance = await account_api.get_balance()

    # WebSocket (Condition Search)
    ws = KiwoomWebSocket()
    await ws.connect()
    await ws.start_condition_search("000")
"""

from src.api.auth import TokenManager, TokenInfo, get_token_manager
from src.api.client import KiwoomAPIClient, APIResponse, RateLimiter, get_api_client
from src.api.websocket import KiwoomWebSocket, SignalEvent, ConditionInfo

from src.api.endpoints.account import AccountAPI, Balance, Position, AccountSummary
from src.api.endpoints.order import OrderAPI, OrderResult, OrderType, Exchange
from src.api.endpoints.market import MarketAPI, Quote, StockInfo
from src.api.endpoints.condition import ConditionAPI

__all__ = [
    # Auth
    "TokenManager",
    "TokenInfo",
    "get_token_manager",

    # HTTP Client
    "KiwoomAPIClient",
    "APIResponse",
    "RateLimiter",
    "get_api_client",

    # WebSocket
    "KiwoomWebSocket",
    "SignalEvent",
    "ConditionInfo",

    # Account
    "AccountAPI",
    "Balance",
    "Position",
    "AccountSummary",

    # Order
    "OrderAPI",
    "OrderResult",
    "OrderType",
    "Exchange",

    # Market
    "MarketAPI",
    "Quote",
    "StockInfo",

    # Condition
    "ConditionAPI",
]
