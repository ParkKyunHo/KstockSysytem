"""
거래 엔진 모듈

Ju-Do-Ju Sniper 시스템의 핵심 거래 엔진입니다.
모든 컴포넌트를 통합하여 자동매매를 수행합니다.

데이터 흐름:
    실시간 틱 데이터 (WebSocket)
           ↓
    CandleBuilder (틱 → 1분봉/3분봉)
           ↓
    SignalDetector (매수 신호 탐지)
           ↓
    RiskManager (진입 가능 여부 체크)
           ↓
    OrderAPI (주문 실행)
           ↓
    PositionManager (포지션 모니터링)
           ↓
    RiskManager (손절/익절 체크)
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Callable, Awaitable, Tuple, Set
from enum import Enum
import asyncio
import json
import math
import os
import threading

import pandas as pd
import numpy as np

from src.core.candle_builder import CandleManager, CandleBuilder, Candle, Tick, Timeframe
from src.core.signal_detector import SignalDetector, Signal, SignalType, StrategyType
from src.core.indicator import Indicator
from src.core.risk_manager import RiskManager, RiskConfig, ExitReason, PROFIT_RATE_EPSILON
from src.core.position_manager import PositionManager, Position, PositionStatus, EntrySource
from src.core.universe import Universe, UniverseConfig, UniverseStock
from src.core.realtime_data_manager import RealTimeDataManager, PriceData, Tier
from src.core.market_schedule import MarketScheduleManager, MarketState, get_market_schedule
from src.core.auto_screener import AutoScreener, FilterResult  # PRD v3.1
from src.core.exit_manager import ExitManager  # Phase 1: 청산 로직 분리
from src.core.order_executor import OrderExecutor  # Phase 2: 주문 실행 분리
from src.core.atr_alert_manager import AtrAlertManager  # PRD v3.2.4: ATR 지저깨 알림
from src.core.subscription_manager import SubscriptionManager, SubscriptionPurpose  # 조건검색 구독 관리

# V7.0 Purple-ReAbs 모듈 (알림 전용 시스템)
from src.core.indicator_purple import PurpleIndicator, calculate_purple_indicators
from src.core.signal_pool import SignalPool
from src.core.signal_detector_purple import PurpleSignalDetector, DualPassDetector
from src.core.watermark_manager import WatermarkManager
from src.core.missed_signal_tracker import MissedSignalTracker
from src.core.wave_harvest_exit import WaveHarvestExit
from src.notification.notification_queue import NotificationQueue

# Phase 3: 리팩토링 모듈
from src.core.signal_processor import SignalProcessor, SignalProcessCallbacks, SignalProcessResult
from src.core.exit_coordinator import ExitCoordinator, ExitCoordinatorCallbacks, ExitCheckResult
from src.core.position_sync_manager import PositionSyncManager, SyncCallbacks, PositionInfo
from src.core.v7_signal_coordinator import V7SignalCoordinator, V7Callbacks
from src.core.system_health_monitor import SystemHealthMonitor, HealthCallbacks
from src.core.strategy_orchestrator import StrategyOrchestrator
from src.core.strategies.v7_purple_reabs import V7PurpleReAbsStrategy
from src.core.strategies.v6_sniper_trap import V6SniperTrapStrategy
from src.core.websocket_manager import WebSocketManager, WebSocketCallbacks
from src.core.position_recovery_manager import PositionRecoveryManager, RecoveryCallbacks
from src.core.market_monitor import MarketMonitor, MarketMonitorCallbacks
from src.core.background_task_manager import BackgroundTaskManager, BackgroundTaskCallbacks

from src.api.client import KiwoomAPIClient
from src.api.websocket import KiwoomWebSocket, TickData, SignalEvent
from src.api.endpoints.order import OrderAPI, OrderType
from src.api.endpoints.market import MarketAPI, MinuteCandle
from src.api.endpoints.account import AccountAPI
from src.notification.telegram import TelegramBot
from src.notification.templates import (
    format_buy_notification,
    format_sell_notification,
    format_signal_notification,
)
from src.utils.logger import get_logger, KST
from src.utils.config import get_settings, get_config, get_risk_settings
from src.database.connection import get_db_manager
from src.database.repository import (
    get_trade_repository,
    get_order_repository,
    get_signal_repository,
    TradeRepository,
    OrderRepository,
    SignalRepository,
)
from src.database.models import OrderSide, OrderStatus


# =========================================
# PRD v3.2.1: 트레이딩 상수 (Magic Number 제거)
# =========================================
class TradingConstants:
    """
    트레이딩 시스템 상수 정의

    모든 Magic Number를 한 곳에서 관리하여 유지보수성을 높입니다.
    """
    # 주문 체결 대기
    EXECUTION_WAIT_SECONDS: float = 5.0      # 체결 대기 최대 시간 (초)
    EXECUTION_POLL_INTERVAL: float = 0.5     # 체결 확인 폴링 간격 (초)

    # 백그라운드 태스크 간격
    STATUS_MONITOR_INTERVAL: int = 60        # 상태 모니터링 간격 (초)
    HIGHEST_PRICE_PERSIST_INTERVAL: int = 30 # 최고가 저장 간격 (초)
    MARKET_WATCHER_INTERVAL: int = 10        # 시장 감시 간격 (초)

    # 갭 처리 임계값
    GAP_SIGNIFICANT_THRESHOLD: float = 5.0   # 갭 알림 임계값 (%)

    # 텔레그램 알림 임계값
    EMPTY_UNIVERSE_ALERT_INTERVAL: int = 5   # 빈 유니버스 알림 간격 (분)
    STATUS_REPORT_INTERVAL: int = 30         # 상태 보고 간격 (분)

    # VI 관련 (config에서 가져오지만 기본값 정의)
    VI_COOLDOWN_DEFAULT: int = 60            # VI 쿨다운 기본값 (초)

    # 분할 매도 대기
    PARTIAL_SELL_WAIT_SECONDS: float = 5.0   # 분할 매도 체결 대기 (초)


class EngineState(str, Enum):
    """엔진 상태"""
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    WAITING_MARKET = "WAITING_MARKET"    # 장 시작 대기 중 (PRD REQ-001)
    WAITING_HOLIDAY = "WAITING_HOLIDAY"  # 휴장일 대기 중 (PRD REQ-002)
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"


class MarketStatus(str, Enum):
    """시장 상태 (V6.2-L NXT 확장)"""
    CLOSED = "CLOSED"                   # ~08:00 (장 시작 전)
    NXT_PRE_MARKET = "NXT_PRE_MARKET"   # 08:00~08:50 (NXT 프리마켓, 시가결정)
    PRE_MARKET = "PRE_MARKET"           # 08:50~09:00 (동시호가)
    REGULAR = "REGULAR"                 # 09:00~15:20 (정규장)
    KRX_CLOSING = "KRX_CLOSING"         # 15:20~15:30 (KRX 단일가, NXT 중단!)
    NXT_AFTER = "NXT_AFTER"             # 15:30~20:00 (NXT 애프터마켓)
    AFTER_HOURS = "AFTER_HOURS"         # 20:00~ (장 종료)


# Phase 6D: StockMode, ManualStockConfig는 manual_command_handler로 이동
from src.core.manual_command_handler import (
    StockMode, ManualStockConfig, ManualCommandHandler, ManualCommandCallbacks,
)

# Phase 6E: ConditionSearchHandler (조건검색 신호 처리)
from src.core.condition_search_handler import (
    ConditionSearchHandler, ConditionSearchCallbacks,
)


@dataclass
class EngineConfig:
    """엔진 설정"""
    # 유니버스 갱신 주기 (분)
    universe_refresh_interval: int = 5

    # 포지션 체크 주기 (초)
    position_check_interval: int = 1

    # 장 시간 (UTC+9)
    market_open: time = time(9, 0)
    market_close: time = time(15, 30)

    # 장 종료 알림 시간
    eod_alert_time: time = time(15, 15)

    # PRD v3.2.1: 미체결 주문 정리 시간 (장 마감 5분 전)
    eod_pending_cleanup_time: time = time(15, 25)


class TradingEngine:
    """
    거래 엔진

    자동매매 시스템의 중앙 조율자입니다.
    WebSocket에서 실시간 데이터를 수신하고, 신호 탐지, 리스크 관리,
    주문 실행을 자동으로 처리합니다.

    Usage:
        engine = TradingEngine(api_client, telegram_bot)
        await engine.start()
        ...
        await engine.stop()
    """

    def __init__(
        self,
        api_client: KiwoomAPIClient,
        telegram: TelegramBot,
        websocket: Optional[KiwoomWebSocket] = None,
        config: Optional[EngineConfig] = None,
        risk_config: Optional[RiskConfig] = None,
        universe_config: Optional[UniverseConfig] = None,
    ):
        self._logger = get_logger(__name__)
        self._settings = get_settings()

        # 설정
        self._config = config or EngineConfig()
        self._risk_config = risk_config or RiskConfig.from_settings()
        self._universe_config = universe_config or UniverseConfig()

        # API 클라이언트
        self._api_client = api_client
        self._order_api = OrderAPI(api_client)
        self._market_api = MarketAPI(api_client)
        self._account_api = AccountAPI(api_client)

        # WebSocket
        self._websocket = websocket

        # 텔레그램
        self._telegram = telegram

        # 컴포넌트
        self._candle_manager = CandleManager()
        self._signal_detector = SignalDetector()
        self._position_manager = PositionManager()
        self._risk_manager = RiskManager(self._risk_config)
        # 양방향 참조 설정 (수량 동기화를 위해)
        self._risk_manager.set_position_manager(self._position_manager)  # Single Source of Truth
        self._position_manager.set_risk_manager(self._risk_manager)  # 수량 동기화용
        self._universe = Universe(self._market_api, self._universe_config)

        # 상태
        self._state = EngineState.STOPPED
        self._start_time: Optional[datetime] = None

        # 포지션 동기화 상태
        self._empty_api_position_count = 0  # 연속 빈 리스트 카운터
        self._EMPTY_API_THRESHOLD = 3       # N번 연속 빈 리스트면 실제 청산으로 판단

        # 백그라운드 태스크
        self._tasks: List[asyncio.Task] = []

        # RealTimeDataManager (중앙 집중형 데이터 허브)
        self._data_manager = RealTimeDataManager(
            websocket=websocket,
            market_api=self._market_api,
        )
        # 데이터 구독
        self._data_manager.subscribe(self._on_market_data)
        # 과거 캔들 로더 콜백 설정 (승격 시 과거 분봉 로드용)
        self._data_manager.set_historical_candle_callback(self._on_historical_candles)

        # 상태 플래그
        self._running: bool = False

        # PRD v3.0: 시장 상태 및 안전장치
        self._market_status: MarketStatus = MarketStatus.PRE_MARKET
        self._market_open_handled: bool = False  # 장 시작 갭 대응 완료 여부
        self._condition_resubscribed_today: bool = False  # V6.2-K: 장 시작 시 조건검색 재구독 완료
        self._daily_reset_done: bool = False  # V6.2-B: 당일 Pool 리셋 완료 여부
        self._last_reset_date: Optional[date] = None  # V6.2-B: 마지막 리셋 날짜
        self._vi_cooldown_stocks: Dict[str, datetime] = {}  # PRD v3.2: VI 쿨다운 종목 (종목코드 -> 해제시간)
        self._vi_active: Dict[str, datetime] = {}  # PRD v3.2: VI 활성 종목 (종목코드 -> 발동시간)
        # C-009 FIX: asyncio.Lock으로 변경 (Event Loop 블록 방지)
        # threading.RLock → asyncio.Lock 변경으로 async 콜백에서 안전하게 사용
        self._vi_lock = asyncio.Lock()

        # PRD v3.2: 매수 후 쿨다운 (시스템 자동매수만 적용)
        self._last_system_buy_time: Optional[datetime] = None  # 마지막 시스템 매수 시간

        # Phase 4-B: BackgroundTaskManager (비동기 루프 태스크 관리)
        self._bg_task_manager: Optional[BackgroundTaskManager] = None

        # PRD v3.1: RiskSettings (MarketMonitor 등에서 필요하므로 여기서 초기화)
        self._risk_settings = get_risk_settings()

        # Phase 4-D: MarketMonitor (KOSDAQ 감시 + Global_Lock)
        self._market_monitor = MarketMonitor(
            risk_settings=self._risk_settings,
            logger=self._logger,
            callbacks=MarketMonitorCallbacks(
                get_engine_state=lambda: self._state.value,
                is_regular_trading_hours=self._is_regular_trading_hours,
                send_telegram=lambda msg: self._telegram.send_message(msg) if self._telegram else asyncio.sleep(0),
                get_kosdaq_index=self._get_kosdaq_index,
            ),
        )

        # 통계
        self._stats = {
            "signals_detected": 0,
            "signals_blocked": 0,
            "signals_queued": 0,        # V6.2-A: 큐에 저장된 신호
            "signals_expired": 0,       # V6.2-A: 만료되어 폐기된 신호
            "signals_from_queue": 0,    # V6.2-A: 큐에서 처리된 신호
            "orders_placed": 0,
            "trades_completed": 0,
            "ticks_received": 0,
        }

        # 종목별 주문 Lock (Race Condition 방지)
        self._order_locks: Dict[str, asyncio.Lock] = {}

        # Critical Fix: 미체결 매도 주문 추적 (중복 주문 방지)
        # stock_code → order_no
        self._pending_sell_orders: Dict[str, str] = {}
        self._pending_sell_lock = asyncio.Lock()  # P0: 미체결 매도 주문 동시 접근 보호

        # Phase 6D: ManualCommandHandler (수동 매매/종목 관리/ignore)
        _ignore_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            ".claude", "state", "ignore_stocks.json"
        )
        self._manual_handler = ManualCommandHandler(
            callbacks=ManualCommandCallbacks(
                get_stock_name=lambda code: self._market_api.get_stock_name(code),
                get_current_price=lambda code: self._market_api.get_current_price(code),
                is_in_universe=lambda code: self._universe.is_in_universe(code),
                add_to_universe=lambda **kw: self._universe.add_stock(**kw),
                remove_from_universe=lambda code: self._universe.remove_stock(code),
                get_universe_stock=lambda code: self._universe.get_stock(code),
                get_universe_stocks=lambda: list(self._universe.stocks),
                add_candle_stock=lambda code: self._candle_manager.add_stock(code),
                get_candle_builder=lambda code: self._candle_manager.get_builder(code),
                remove_candle_stock=lambda code: self._candle_manager.remove_stock(code),
                register_stock=lambda code, tier, name: self._data_manager.register_stock(code, tier, name),
                unregister_stock=lambda code: self._data_manager.unregister_stock(code),
                promote_to_tier1=lambda code: self._data_manager.promote_to_tier1(code),
                is_tier1=lambda code: self._data_manager.is_tier1(code),
                get_price_data=lambda code: self._data_manager.get_price_data(code),
                has_position=lambda code: self._position_manager.has_position(code),
                get_position=lambda code: self._position_manager.get_position(code),
                get_all_positions=lambda: self._position_manager.get_all_positions(),
                get_balance=lambda: self._account_api.get_balance(),
                buy_order=lambda **kw: self._order_api.buy(**kw),
                wait_for_execution=lambda **kw: self._account_api.wait_for_execution(**kw),
                on_entry=lambda *a, **kw: self._risk_manager.on_entry(*a, **kw),
                open_position=lambda **kw: self._position_manager.open_position(**kw),
                set_trailing_stop_price=lambda code, price: self._risk_manager.set_trailing_stop_price(code, price),
                set_ts_fallback=lambda code, flag: self._risk_manager.set_ts_fallback(code, flag),
                execute_manual_sell=lambda code, qty: self._exit_manager.execute_manual_sell(code, qty) if self._exit_manager else None,
                initialize_trailing_stop=lambda code, price: self._exit_manager.initialize_trailing_stop_on_entry_v62a(code, price) if self._exit_manager else None,
                unregister_atr_alert=lambda code: self._atr_alert_manager.unregister_stock(code),
                is_regular_trading_hours=lambda: self._is_nxt_trading_hours(),
                get_engine_state=lambda: self._state.value,
            ),
            ignore_file_path=_ignore_file,
        )
        # Backward-compatible references
        self._manual_stocks = self._manual_handler.manual_stocks
        self._ignore_stocks = self._manual_handler.ignore_stocks

        # V6.2-A 코드리뷰 A1: 시작 완료 플래그
        # - 재시작 시 DB 복구 완료 전까지 신호 처리 차단
        # - Race Condition 방지
        self._startup_complete: bool = False

        # V6.2-A: SNIPER_TRAP 신호 큐 (쿨다운 중 신호 저장)
        # - 쿨다운 중 발생한 신호를 저장했다가 쿨다운 해제 후 처리
        # - Dict[stock_code, {stock_name, signal, price, timestamp}]
        # - 종목당 최신 신호 1개만 유지
        self._signal_queue: Dict[str, dict] = {}
        self._signal_queue_lock: asyncio.Lock = asyncio.Lock()  # 동시성 보호
        self._signal_queue_max_age_seconds: float = 20.0  # 신호 유효 시간 (쿨다운 15초 + 여유 5초)

        # V6.2-C: SIGNAL_ALERT 모드 중복 알림 방지
        self._signal_alert_cooldown: Dict[str, datetime] = {}

        # 데이터베이스 리포지토리 (초기화 후 사용 가능)
        self._trade_repo: Optional[TradeRepository] = None
        self._order_repo: Optional[OrderRepository] = None
        self._signal_repo: Optional[SignalRepository] = None

        # MarketScheduleManager (PRD REQ-001, REQ-002)
        self._market_schedule = get_market_schedule()

        # PRD v3.1: Auto-Universe Screener
        self._auto_screener = AutoScreener(
            market_api=self._market_api,
            settings=self._risk_settings,
            position_manager=self._position_manager,  # 강등 예외 처리용
        )
        # V6.2-R: Active Pool 변경 시 Tier 승격/강등 콜백 등록
        self._auto_screener.set_active_pool_callback(self._on_active_pool_changed)

        # 마지막 순위 갱신 시간
        self._last_ranking_update: Optional[datetime] = None

        # Phase 1: ExitManager 초기화 (청산 로직 분리)
        # Note: trade_repo, order_repo는 나중에 set_repositories()에서 설정됨
        self._exit_manager: Optional[ExitManager] = None  # 나중에 초기화
        self._order_executor: Optional[OrderExecutor] = None  # Phase 2: 나중에 초기화

        # 조건검색 구독 관리자 (start()에서 초기화)
        self._subscription_manager: Optional[SubscriptionManager] = None

        # Grand Trend V6: 지저깨 알림 관리자
        self._atr_alert_manager = AtrAlertManager(
            market_api=self._market_api,
            telegram=self._telegram,
            logger=self._logger,
            data_manager=self._data_manager,
            candle_manager=self._candle_manager,
            period=self._risk_settings.atr_trailing_period,  # ATR(10)
            cooldown_seconds=self._risk_settings.atr_alert_cooldown_seconds if hasattr(self._risk_settings, 'atr_alert_cooldown_seconds') else 300,
            max_alerts_per_day=self._risk_settings.atr_alert_max_per_day if hasattr(self._risk_settings, 'atr_alert_max_per_day') else 3,
        )

        # =========================================
        # V7.0 Purple-ReAbs 컴포넌트 → V7Strategy로 캡슐화
        # =========================================
        v7_enabled: bool = os.getenv("V7_PURPLE_ENABLED", "false").lower() == "true"

        # V7 컴포넌트를 로컬 변수로 생성 후 V7Strategy에 주입
        _v7_exit_manager = None
        self._v7_strategy: Optional[V7PurpleReAbsStrategy] = None

        if v7_enabled:
            self._logger.info("[V7.0] Purple-ReAbs 모드 활성화")

            _v7_pool = SignalPool()
            _v7_detector = PurpleSignalDetector()
            _v7_dual = DualPassDetector()
            _v7_wm = WatermarkManager()
            _v7_exit_manager = WaveHarvestExit()
            _v7_notif = NotificationQueue(
                cooldown_seconds=self._risk_settings.signal_alert_cooldown_seconds
                if hasattr(self._risk_settings, 'signal_alert_cooldown_seconds') else 300
            )
            _v7_missed = MissedSignalTracker()
            _v7_coordinator = V7SignalCoordinator(logger=self._logger)

            self._v7_strategy = V7PurpleReAbsStrategy(
                signal_pool=_v7_pool,
                signal_detector=_v7_detector,
                dual_pass=_v7_dual,
                watermark=_v7_wm,
                exit_manager=_v7_exit_manager,
                notification_queue=_v7_notif,
                missed_tracker=_v7_missed,
                signal_coordinator=_v7_coordinator,
            )

        # =========================================
        # Phase 3: 리팩토링 모듈 초기화
        # =========================================
        # SignalProcessor: 신호 큐/알림 처리 (SIGNAL_ALERT 모드용)
        self._signal_processor = SignalProcessor(
            telegram=self._telegram,
            risk_settings=self._risk_settings,
            signal_queue_max_age_seconds=int(self._signal_queue_max_age_seconds),
            signal_alert_cooldown_seconds=self._risk_settings.signal_alert_cooldown_seconds
            if hasattr(self._risk_settings, 'signal_alert_cooldown_seconds') else 300,
        )

        # M-09: 포지션-전략 매핑 공유 dict (ExitCoordinator + StrategyOrchestrator)
        self._shared_position_strategies: Dict[str, str] = {}

        # ExitCoordinator: V6/V7 청산 조율
        self._exit_coordinator = ExitCoordinator(
            exit_manager=None,  # set_repositories()에서 설정
            v7_exit_manager=_v7_exit_manager,
            risk_settings=self._risk_settings,
            position_strategies=self._shared_position_strategies,
        )

        # PositionSyncManager: HTS 매수/매도 감지 및 포지션 동기화
        sync_interval = self._risk_settings.position_sync_interval if hasattr(
            self._risk_settings, 'position_sync_interval'
        ) else 60
        self._position_sync_manager = PositionSyncManager(
            logger=self._logger,
            sync_interval=sync_interval,
        )

        # Phase 3-1: StrategyOrchestrator (initialize()에서 생성)
        self._strategy_orchestrator: Optional[StrategyOrchestrator] = None

        # V7.1: SystemHealthMonitor (start()에서 초기화)
        self._health_monitor: Optional[SystemHealthMonitor] = None

        # Phase 6E: ConditionSearchHandler (조건검색 신호 처리)
        self._condition_handler = ConditionSearchHandler(
            callbacks=ConditionSearchCallbacks(
                is_startup_complete=lambda: self._startup_complete,
                get_engine_state=lambda: self._state.value,
                get_market_status=lambda: self._get_market_status().value,
                on_signal_received=lambda seq: self._subscription_manager.on_signal_received(seq) if self._subscription_manager else None,
                get_stock_name=lambda code: self._market_api.get_stock_name(code),
                register_atr_stock=lambda code, name: self._atr_alert_manager.register_stock(code, name),
                get_atr_state=lambda code: self._atr_alert_manager.get_state(code),
                get_risk_settings=lambda: self._risk_settings,
                is_in_universe=lambda code: self._universe.is_in_universe(code),
                add_to_universe=lambda **kw: self._universe.add_stock(**kw),
                get_candle_builder=lambda code: self._candle_manager.get_builder(code),
                add_candle_stock=lambda code: self._candle_manager.add_stock(code),
                register_stock=lambda code, tier, name: self._data_manager.register_stock(code, tier, name),
                is_candle_loaded=lambda code: self._data_manager.is_candle_loaded(code),
                load_historical_candles=lambda code: self._data_manager.load_historical_candles_for_watchlist(code),
                promote_to_tier1=lambda code: self._data_manager.promote_to_tier1(code),
                has_position=lambda code: self._position_manager.has_position(code),
                dispatch_condition_signal=lambda code, name, meta: self._strategy_orchestrator.dispatch_condition_signal(code, name, meta) if self._strategy_orchestrator else None,
                on_condition_signal_filter=lambda code, name: self._auto_screener.on_condition_signal(code, name),
                send_telegram=lambda msg: self._telegram.send_message(msg) if self._telegram else asyncio.sleep(0),
                get_manual_stocks=lambda: self._manual_stocks,
            ),
        )

        # Phase 4-A: WebSocketManager (연결/구독/이벤트 관리)
        self._ws_manager = WebSocketManager(
            websocket=self._websocket,
            logger=self._logger,
            telegram=self._telegram,
            risk_settings=self._risk_settings,
            subscription_manager=self._subscription_manager,
            callbacks=self._build_ws_callbacks(),
        )

        # Phase 4-C: PositionRecoveryManager (start()에서 완전 초기화)
        self._recovery_manager: Optional[PositionRecoveryManager] = None

        # 콜백 설정
        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        """내부 콜백 설정"""
        # 봉 완성 시 신호 탐지
        self._candle_manager.on_candle_complete = self._on_candle_complete
        self._logger.info(
            f"[콜백설정] CandleManager.on_candle_complete = {self._on_candle_complete.__name__}"
        )

        # 포지션 이벤트
        self._position_manager.on_position_opened = self._on_position_opened
        self._position_manager.on_position_closed = self._on_position_closed

        # WebSocket 콜백 (Phase 4-A: 이벤트 핸들러는 WebSocketManager로 이동)
        if self._websocket:
            self._websocket.on_signal = self._condition_handler.on_condition_signal_v31
            self._websocket.on_tick = self._ws_manager.on_tick
            self._websocket.on_connected = self._ws_manager.on_connected
            self._websocket.on_disconnected = self._ws_manager.on_disconnected
            self._websocket.on_reconnected = self._ws_manager.on_reconnected
            self._websocket.on_reconnect_failed = self._ws_manager.on_reconnect_failed

    def set_websocket(self, websocket: KiwoomWebSocket) -> None:
        """WebSocket 클라이언트 설정 (지연 주입용)"""
        self._websocket = websocket
        # Phase 4-A: WebSocketManager에도 전달
        self._ws_manager._websocket = websocket
        # 조건검색 신호 콜백은 ConditionSearchHandler로 위임
        self._websocket.on_signal = self._condition_handler.on_condition_signal_v31
        # 이벤트 핸들러는 WebSocketManager로 위임
        self._websocket.on_tick = self._ws_manager.on_tick
        self._websocket.on_connected = self._ws_manager.on_connected
        self._websocket.on_disconnected = self._ws_manager.on_disconnected
        self._websocket.on_reconnected = self._ws_manager.on_reconnected
        self._websocket.on_reconnect_failed = self._ws_manager.on_reconnect_failed
        # RealTimeDataManager에도 WebSocket 전달
        self._data_manager._websocket = websocket

    # =========================================
    # Phase 3: 콜백 인터페이스 빌더
    # =========================================

    def _build_ws_callbacks(self) -> WebSocketCallbacks:
        """Phase 4-A: WebSocketManager용 콜백 인터페이스 생성"""
        async def _ws_on_tick(tick: Tick) -> None:
            self._stats["ticks_received"] += 1
            await self.on_tick(tick)

        return WebSocketCallbacks(
            on_tick=_ws_on_tick,
            sync_positions=self._sync_positions,
            initialize_trailing_stops=lambda: (
                self._recovery_manager.initialize_trailing_stops_after_recovery()
                if self._recovery_manager
                else None
            ),
            get_universe_codes=lambda: set(self._universe.stock_codes),
            get_all_position_codes=lambda: {
                p.stock_code for p in self._position_manager.get_all_positions()
            },
            get_position_count=self._position_manager.get_position_count,
            get_engine_state=lambda: self._state.value,
            set_engine_paused=lambda: setattr(self, '_state', EngineState.PAUSED),
        )

    def _build_signal_processor_callbacks(self) -> SignalProcessCallbacks:
        """
        SignalProcessor용 콜백 인터페이스 생성

        TradingEngine의 기능을 콜백으로 전달하여
        SignalProcessor가 독립적으로 동작할 수 있게 합니다.
        """
        return SignalProcessCallbacks(
            can_execute_trade=self._can_execute_trade,
            has_position=self._position_manager.has_position,
            is_in_cooldown=lambda: (
                self._order_executor and self._order_executor.is_in_system_buy_cooldown()
            ) if self._order_executor else False,
            get_cooldown_remaining=lambda: (
                self._order_executor.get_cooldown_remaining()
                if self._order_executor else 0
            ),
            can_enter_risk=self._risk_manager.can_enter,
            execute_buy=self._execute_buy_from_signal,
            send_telegram=self._telegram.send_message if self._telegram else None,
            on_risk_block=self._on_risk_block,
        )

    def _build_exit_coordinator_callbacks(self, stock_code: str) -> ExitCoordinatorCallbacks:
        """
        ExitCoordinator용 콜백 인터페이스 생성

        Args:
            stock_code: 청산 체크 대상 종목 코드
        """
        return ExitCoordinatorCallbacks(
            has_position=self._position_manager.has_position,
            get_position_risk=self._risk_manager.get_position_risk,
            get_candle_data=self._get_candle_data_for_exit,
            execute_sell=self._execute_sell_order,
            get_market_state=lambda: self._market_schedule.get_state(),
            is_ignore_stock=lambda code: code in self._ignore_stocks,
        )

    def _get_candle_data_for_exit(self, stock_code: str):
        """ExitCoordinator용 캔들 데이터 조회"""
        builder = self._candle_manager.get_builder(stock_code)
        if builder is None:
            return None
        candles = builder.get_candles(Timeframe.M3)
        if candles is None or len(candles) < 20:
            return None
        return candles

    def _build_sync_callbacks(self) -> SyncCallbacks:
        """
        PositionSyncManager용 콜백 인터페이스 생성

        TradingEngine의 기능을 콜백으로 전달하여
        PositionSyncManager가 독립적으로 동작할 수 있게 합니다.
        """
        return SyncCallbacks(
            # 포지션 관리
            open_position=self._position_manager.open_position,
            close_position=self._position_manager.close_position,
            get_position=self._position_manager.get_position,
            get_all_positions=self._position_manager.get_all_positions,
            get_position_codes=self._position_manager.get_position_codes,
            update_quantity=self._position_manager.update_quantity,
            update_entry_price=self._position_manager.update_entry_price,
            # Risk 관리
            on_risk_entry=self._risk_manager.on_entry,
            on_risk_exit=self._risk_manager.on_exit,
            sync_quantity=self._risk_manager.sync_quantity,
            sync_entry_price=self._risk_manager.sync_entry_price,
            is_partial_exited=self._risk_manager.is_partial_exited,
            get_position_risk=self._risk_manager.get_position_risk,
            # 인프라
            add_candle_stock=self._candle_manager.add_stock,
            add_universe_stock=self._universe.add_stock,
            is_in_universe=self._universe.is_in_universe,
            register_tier1=lambda code, name: self._data_manager.register_stock(code, Tier.TIER_1, name),
            is_tier1=self._data_manager.is_tier1,
            # 주문 상태 (C-06: 주문 진행 중 동기화 스킵)
            is_ordering_stock=lambda code: (
                code in self._order_locks and self._order_locks[code].locked()
            ),
            # V7 Exit State
            initialize_v7_state=self._exit_coordinator.initialize_v7_state,
            register_position_strategy=self._exit_coordinator.register_position_strategy,
            # 트레일링 스탑 (Phase 4-C: PositionRecoveryManager로 이동)
            init_ts_fallback=lambda code, pos: (
                self._recovery_manager.init_ts_fallback(code, pos)
                if self._recovery_manager else None
            ),
            init_trailing_stop_partial=lambda code: (
                self._recovery_manager.init_trailing_stop_for_recovered_partial(code)
                if self._recovery_manager else None
            ),
            # DB
            close_trade=self._close_trade_in_db,
            update_partial_exit=self._update_partial_exit_in_db,
            # 알림
            send_telegram=self._telegram.send_message if self._telegram else None,
        )

    async def _close_trade_in_db(
        self, trade_id: str, exit_price: int, exit_order_no: str, exit_reason: str
    ) -> None:
        """DB에서 거래 청산 처리 (PositionSyncManager 콜백용)"""
        if self._trade_repo:
            await self._trade_repo.close(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_order_no=exit_order_no,
                exit_reason=exit_reason,
            )

    async def _update_partial_exit_in_db(
        self, trade_id: str, new_stop_loss_price: int, highest_price: int
    ) -> None:
        """DB에서 분할 익절 상태 업데이트 (PositionSyncManager 콜백용)"""
        if self._trade_repo:
            await self._trade_repo.update_partial_exit(
                trade_id=trade_id,
                new_stop_loss_price=new_stop_loss_price,
                highest_price=highest_price,
            )

    def _build_v7_callbacks(self) -> V7Callbacks:
        """V7SignalCoordinator용 콜백 인터페이스 생성 (V7Strategy에 위임)"""
        if self._v7_strategy is None:
            return V7Callbacks()

        from src.core.strategies.v7_purple_reabs import V7InfraCallbacks
        return self._v7_strategy.build_v7_callbacks(V7InfraCallbacks(
            get_candles=lambda code, tf: self._candle_manager.get_candles(code, tf),
            is_candle_loaded=self._data_manager.is_candle_loaded,
            promote_to_tier1=self._data_manager.promote_to_tier1,
            send_telegram=self._send_telegram_alert,
            is_engine_running=lambda: self._state in [EngineState.RUNNING, EngineState.PAUSED],
        ))

    async def _execute_buy_from_signal(self, signal: Signal) -> None:
        """SignalProcessor에서 호출되는 매수 실행 콜백"""
        await self._execute_buy_order(signal)

    async def _on_risk_block(self, stock_code: str, block_reason, message: str) -> None:
        """
        SignalProcessor에서 리스크 차단 시 호출되는 콜백

        MAX_POSITIONS, DAILY_LOSS_LIMIT 등 중요한 차단 사유는
        텔레그램으로 알림을 전송합니다.
        """
        # 중요한 차단 사유만 알림
        if block_reason and hasattr(block_reason, 'value'):
            if block_reason.value in ("MAX_POSITIONS", "DAILY_LOSS_LIMIT"):
                if self._telegram:
                    # 종목명 조회
                    stock_name = stock_code
                    if self._universe and stock_code in self._universe.stock_codes:
                        stock_info = self._universe.get_stock_info(stock_code)
                        if stock_info:
                            stock_name = stock_info.get("name", stock_code)

                    await self._telegram.send_message(
                        f"[진입 차단]\n\n"
                        f"{stock_name} ({stock_code})\n"
                        f"사유: {message}"
                    )

    # =========================================
    # WebSocket 이벤트 핸들러
    # =========================================

    # Phase 4-A: _connect_websocket, _start_condition_search_with_validation
    # → WebSocketManager.connect(), WebSocketManager._start_condition_search_with_validation()

    async def _send_telegram_alert(self, message: str) -> None:
        """텔레그램 알림 전송 (에러 무시)"""
        try:
            if self._telegram:
                await self._telegram.send_message(message)
        except Exception as e:
            self._logger.warning(f"텔레그램 알림 전송 실패: {e}")

    # Phase 4-A: _on_ws_tick, _on_ws_connected, _on_ws_disconnected,
    # _on_ws_reconnected, _on_ws_reconnect_failed
    # → WebSocketManager.on_tick/on_connected/on_disconnected/on_reconnected/on_reconnect_failed

    # =========================================
    # Phase 6E: ConditionSearchHandler 위임
    # =========================================

    async def _on_condition_signal_v31(self, signal: SignalEvent) -> None:
        """조건검색 신호 처리 (ConditionSearchHandler 위임)"""
        await self._condition_handler.on_condition_signal_v31(signal)

    async def _on_polling_signal(self, stock_code: str) -> None:
        """폴링 Fallback 신호 처리 (ConditionSearchHandler 위임)"""
        await self._condition_handler.on_polling_signal(stock_code)

    async def _on_condition_exit_signal(self, signal: SignalEvent) -> None:
        """
        조건식 이탈 신호 처리
        Phase 1: 청산 실행은 ExitManager로 위임

        - 보유 중인 종목: 자동 청산
        - 미보유 종목: 유니버스/Tier에서 제거하지 않음 (계속 모니터링)

        Args:
            signal: SignalEvent
        """
        stock_code = signal.stock_code
        stock_name = signal.stock_name or stock_code

        # 유니버스에 없는 종목이면 복구 (편입 신호를 놓친 경우)
        if not self._universe.is_in_universe(stock_code):
            self._logger.warning(
                f"[복구] 조건식 이탈 신호 받았으나 유니버스에 없음: "
                f"{stock_name}({stock_code}) - Tier 2로 추가"
            )
            # 종목명 조회
            if stock_name == stock_code:
                try:
                    stock_name = await self._market_api.get_stock_name(stock_code)
                except Exception as e:
                    # 종목명 조회 실패 시 코드 그대로 사용
                    self._logger.debug(f"종목명 조회 실패 (코드 사용): {stock_code}, error={e}")

            # 유니버스에 추가
            self._universe.add_stock(stock_code, stock_name)
            # DataManager Tier 2 등록
            self._data_manager.register_stock(stock_code, tier=Tier.TIER_2, stock_name=stock_name)

        # Phase 1: ExitManager로 청산 실행 위임
        if self._exit_manager:
            await self._exit_manager.handle_condition_exit_signal(
                stock_code=stock_code,
                stock_name=stock_name,
                condition_seq=signal.condition_seq or 0,
            )
        else:
            self._logger.warning(f"ExitManager 미초기화 - 조건식 이탈 처리 스킵: {stock_code}")

    # =========================================
    # 엔진 제어
    # =========================================

    async def start(self) -> bool:
        """
        엔진 시작 (장 스케줄 통합)

        PRD REQ-001, REQ-002 구현:
        - 장 전 실행 시 자동 대기
        - 휴장일 자동 감지
        - 장 시작 시 자동 거래 시작

        Returns:
            시작 성공 여부
        """
        if self._state != EngineState.STOPPED:
            self._logger.warning(f"엔진이 이미 실행 중: {self._state}")
            return False

        self._state = EngineState.STARTING
        self._start_time = datetime.now()
        self._logger.info("거래 엔진 시작 중...")

        try:
            # 0. MarketScheduleManager 초기화
            await self._market_schedule.initialize()
            self._logger.info("장 스케줄 매니저 초기화 완료")

            # 1. 장 상태 확인 및 대기 (PRD REQ-001, REQ-002)
            market_state = self._market_schedule.get_state()
            self._logger.info(f"현재 장 상태: {market_state.value}")

            if market_state == MarketState.HOLIDAY:
                # 휴장일 - 항상 대기 (API 서버도 휴무)
                next_open = self._market_schedule.get_next_market_open()
                self._state = EngineState.WAITING_HOLIDAY
                await self._telegram.send_message(
                    f"[휴장일]\n"
                    f"다음 거래일: {next_open.strftime('%Y-%m-%d %H:%M')}\n"
                    f"자동 시작 예약됨"
                )
                self._logger.info(f"휴장일 - 다음 장 시작까지 대기: {next_open}")
                await self._market_schedule.wait_for_market_open()

            elif self._risk_settings.wait_for_market_open:
                # WAIT_FOR_MARKET_OPEN=true (기본값): 장 시작까지 대기
                if market_state == MarketState.CLOSED:
                    # 장 시작 전 또는 장 종료 후
                    next_open = self._market_schedule.get_next_market_open()
                    self._state = EngineState.WAITING_MARKET

                    if datetime.now().time() < self._market_schedule.MARKET_OPEN:
                        # 오늘 장 시작 전
                        await self._telegram.send_message(
                            f"[장 시작 대기]\n"
                            f"시작 시간: {next_open.strftime('%H:%M')}\n"
                            f"자동으로 시작됩니다"
                        )
                    else:
                        # 오늘 장 종료 후
                        await self._telegram.send_message(
                            f"[장 마감]\n"
                            f"다음 장 시작: {next_open.strftime('%Y-%m-%d %H:%M')}\n"
                            f"자동 시작 예약됨"
                        )

                    self._logger.info(f"장 시작 대기 중: {next_open}")
                    await self._market_schedule.wait_for_market_open()

                elif market_state == MarketState.PRE_MARKET:
                    # 동시호가 중
                    self._state = EngineState.WAITING_MARKET
                    await self._telegram.send_message(
                        f"[동시호가 진행 중]\n"
                        f"정규장 시작: 09:00\n"
                        f"잠시 후 자동 시작됩니다"
                    )
                    self._logger.info("동시호가 중 - 정규장 시작까지 대기")
                    await self._market_schedule.wait_for_market_open()

            else:
                # WAIT_FOR_MARKET_OPEN=false: 장전/장후도 즉시 연결
                if market_state in (MarketState.CLOSED, MarketState.PRE_MARKET):
                    self._logger.info(
                        f"[설정] WAIT_FOR_MARKET_OPEN=false - "
                        f"장 상태({market_state.value})와 무관하게 즉시 연결"
                    )
                    await self._telegram.send_message(
                        f"[장외 연결]\n"
                        f"현재 상태: {market_state.value}\n"
                        f"WebSocket/조건검색 연결 시작"
                    )

            # 거래 시작 (장 상태 무관하게 진행)
            if market_state in (MarketState.OPEN, MarketState.KRX_CLOSING):
                await self._telegram.send_message("[장 시작] 거래를 시작합니다...")
            else:
                await self._telegram.send_message("[연결 완료] WebSocket/조건검색 구독 시작...")
            self._logger.info("장 시작 확인 - 거래 시작")

            # 2. 데이터베이스 리포지토리 초기화
            db_manager = get_db_manager()
            if db_manager.is_initialized:
                self._trade_repo = get_trade_repository()
                self._order_repo = get_order_repository()
                self._signal_repo = get_signal_repository()
                self._logger.info("데이터베이스 리포지토리 초기화 완료")
            else:
                self._logger.warning("데이터베이스 미초기화 - 거래 기록이 저장되지 않습니다")

            # 2-1. Phase 1: ExitManager 초기화 (청산 로직 분리)
            # P0: 공유 Lock 전달 (Race Condition 방지)
            self._exit_manager = ExitManager(
                risk_manager=self._risk_manager,
                position_manager=self._position_manager,
                candle_manager=self._candle_manager,
                order_api=self._order_api,
                account_api=self._account_api,
                market_api=self._market_api,
                trade_repo=self._trade_repo,
                order_repo=self._order_repo,
                telegram=self._telegram,
                logger=self._logger,
                is_vi_active_fn=self._is_vi_active,
                is_regular_trading_hours_fn=self._is_nxt_exit_hours,  # V6.2-L: NXT 청산 시간대
                is_market_open_fn=self._market_schedule.is_market_open,
                order_locks=self._order_locks,  # P0: 공유 Lock
                pending_sell_orders=self._pending_sell_orders,  # P0: 공유 미체결 매도 주문
                pending_sell_lock=self._pending_sell_lock,  # P0: 공유 pending_sell_lock
            )
            self._logger.info("[Phase 1] ExitManager 초기화 완료 (공유 Lock/미체결 주문 적용)")

            # Phase 3: ExitCoordinator에 ExitManager 설정
            self._exit_coordinator._exit_manager = self._exit_manager
            self._logger.info("[Phase 3] ExitCoordinator에 ExitManager 연결 완료")

            # 2-2. Phase 2: OrderExecutor 초기화 (주문 실행 분리)
            # P0: 공유 Lock 전달 (Race Condition 방지)
            # V6.2-A: 진입 시 TS 즉시 초기화 콜백 전달
            # V6.2-A: 신호 큐 처리 콜백 전달 (쿨다운 해제 후)
            self._order_executor = OrderExecutor(
                position_manager=self._position_manager,
                risk_manager=self._risk_manager,
                order_api=self._order_api,
                account_api=self._account_api,
                trade_repo=self._trade_repo,
                order_repo=self._order_repo,
                telegram=self._telegram,
                risk_settings=self._risk_settings,
                logger=self._logger,
                is_regular_trading_hours_fn=self._is_nxt_trading_hours,  # V6.2-L: NXT 매수 가능 시간
                is_market_open_fn=self._market_schedule.is_market_open,
                order_locks=self._order_locks,  # P0: 공유 Lock
                on_buy_filled_callback=self._on_buy_filled_with_v7,  # V7.0: V6 TS + V7 State 통합
                on_cooldown_expired_callback=self._process_signal_queue,  # V6.2-A 신호 큐
            )
            self._logger.info("[Phase 2] OrderExecutor 초기화 완료 (공유 Lock, V6.2-A TS/신호큐 콜백 적용)")

            # 2-3. SubscriptionManager 초기화 (조건검색 구독 관리)
            self._subscription_manager = SubscriptionManager(
                websocket=self._websocket,
                telegram=self._telegram,
                logger=self._logger,
            )
            self._subscription_manager.start_health_check()
            # 폴링 Fallback 콜백 설정 (실시간 구독 실패 시 사용)
            self._subscription_manager.on_polling_signal = self._condition_handler.on_polling_signal
            self._logger.info("[SubscriptionManager] 초기화 완료 (헬스체크 + 폴링 콜백 설정)")

            # 3. 일일 리셋
            self._risk_manager.reset_daily()
            self._position_manager.reset_daily()
            self._atr_alert_manager.reset_daily_counts()  # PRD v3.2.4: ATR 알림 일일 카운트 리셋
            if self._auto_screener:
                self._auto_screener.reset_daily()  # V6.2-B: Watchlist/Candidate/Active Pool 리셋
            async with self._pending_sell_lock:
                self._pending_sell_orders.clear()  # V6.2-A: 미체결 매도 주문 초기화 (메모리 누수 방지)
            self._market_open_handled = False  # PRD v3.0: 장 시작 갭 대응 플래그 리셋
            self._condition_resubscribed_today = False  # V6.2-K: 조건검색 재구독 플래그 리셋
            self._market_monitor.reset_daily()  # PRD v3.0: Global_Lock + KOSDAQ 리셋

            # 4. 잔고 확인 (balance 명령어로만 조회 가능)
            balance = await self._account_api.get_balance()

            # Phase 4-C: PositionRecoveryManager 초기화 (trade_repo, exit_manager 초기화 후)
            self._recovery_manager = PositionRecoveryManager(
                trade_repo=self._trade_repo,
                position_manager=self._position_manager,
                risk_manager=self._risk_manager,
                candle_manager=self._candle_manager,
                account_api=self._account_api,
                position_sync_manager=self._position_sync_manager,
                exit_manager=self._exit_manager,
                market_api=self._market_api,
                risk_settings=self._risk_settings,
                telegram=self._telegram,
                logger=self._logger,
                callbacks=RecoveryCallbacks(
                    build_sync_callbacks=self._build_sync_callbacks,
                ),
            )

            # 3. DB에서 열린 거래 복구
            await self._recovery_manager.restore_positions_from_db()

            # 4. 기존 보유종목 동기화 (API 잔고와 비교)
            # V6.2-J: 예외 발생해도 백업 Tier 1 등록이 실행되도록 try-catch 추가
            try:
                await self._sync_positions()
            except Exception as e:
                self._logger.error(f"초기 포지션 동기화 실패 (백업 등록으로 진행): {e}")

            # V6.2-A 코드리뷰 A4: 쿨다운/블랙리스트 복구
            # - 재시작 시 당일 손절 종목 재진입 방지
            if self._trade_repo:
                await self._risk_manager.restore_from_db(self._trade_repo)

            # =========================================
            # V7.0 Purple-ReAbs 초기화
            # =========================================
            if self._v7_strategy is not None:
                self._logger.info("[V7.0] Purple-ReAbs 초기화 시작")
                pool = self._v7_strategy.signal_pool

                # V7 SignalPool 초기화 (기존 보유 종목 등록)
                for position in self._position_manager.get_all_positions():
                    pool.add(
                        position.stock_code,
                        position.stock_name if hasattr(position, 'stock_name') else "Unknown"
                    )

                # V7 WaveHarvestExit 상태 초기화 (보유 포지션용) - Phase 3: ExitCoordinator 사용
                for position in self._position_manager.get_all_positions():
                    # Phase 3-3: 포지션-전략 매핑 등록
                    self._exit_coordinator.register_position_strategy(
                        position.stock_code, "V7_PURPLE_REABS"
                    )
                    exit_state = self._exit_coordinator.initialize_v7_state(
                        stock_code=position.stock_code,
                        entry_price=position.entry_price,
                        entry_date=position.entry_time if hasattr(position, 'entry_time') else datetime.now(),
                    )
                    if exit_state:
                        self._logger.debug(f"[V7] Exit State 생성 (via ExitCoordinator): {position.stock_code}")

                # V7 NotificationQueue 전송 함수 설정
                async def v7_send_notification(message: str) -> bool:
                    try:
                        await self._send_telegram_alert(message)
                        return True
                    except Exception:
                        return False

                self._v7_strategy.notification_queue.set_send_func(v7_send_notification)

                self._logger.info(
                    f"[V7.0] Purple-ReAbs 초기화 완료 | "
                    f"SignalPool={pool.size()}개, "
                    f"ExitStates={len(self._exit_coordinator.get_all_v7_states())}개"
                )

            # =========================================
            # Phase 3-1: StrategyOrchestrator 초기화
            # =========================================
            self._strategy_orchestrator = StrategyOrchestrator(
                position_strategies=self._shared_position_strategies,
            )

            # V7 전략 등록
            if self._v7_strategy is not None:
                self._strategy_orchestrator.register_base_strategy(self._v7_strategy, priority=10)

            # V6 전략 등록
            if self._auto_screener:
                v6_strategy = V6SniperTrapStrategy(
                    signal_detector=self._signal_detector,
                    exit_manager=self._exit_manager,
                    auto_screener=self._auto_screener,
                )
                self._strategy_orchestrator.register_base_strategy(v6_strategy, priority=200)

            self._logger.info(
                f"[Phase 3-1] StrategyOrchestrator 초기화 완료: "
                f"{self._strategy_orchestrator}"
            )

            # 5. 유니버스 초기화 (V6.2-G: refresh() 제거 - Auto-Universe 기반으로 전환)
            # 이전: 거래대금 상위 100종목 조회 → 조건검색 신호와 충돌
            # 현재: 빈 상태로 시작, 조건검색 신호로 종목 추가
            self._logger.info("유니버스: 빈 상태 시작 (조건검색 기반 등록)")

            # 5. RealTimeDataManager에 종목 등록
            # 보유 포지션 → Tier 1 (고속)
            for position in self._position_manager.get_all_positions():
                self._data_manager.register_stock(
                    position.stock_code,
                    Tier.TIER_1,
                    position.stock_name,
                )
                # V6.2-G: 보유 포지션은 Universe에도 추가
                if not self._universe.is_in_universe(position.stock_code):
                    self._universe.add_stock(position.stock_code, position.stock_name, {"source": "position"})
            # 유니버스 종목 → Tier 2 (저속)
            for stock in self._universe.stocks:
                self._data_manager.register_stock(
                    stock.stock_code,
                    Tier.TIER_2,
                    stock.stock_name,
                )
            self._logger.info(
                f"DataManager 등록: Tier1={self._data_manager.tier1_count}, "
                f"Tier2={self._data_manager.tier2_count}"
            )

            # 6. 엔진 상태를 RUNNING으로 먼저 설정 (조건검색 콜백이 처리되도록)
            # Bug Fix: 초기 종목 콜백이 무시되지 않도록 WebSocket 연결 전에 설정
            self._state = EngineState.RUNNING

            # 7. WebSocket 연결 (조건검색용) - Phase 4-A: WebSocketManager
            # SubscriptionManager가 start()에서 초기화되므로 여기서 업데이트
            self._ws_manager._subscription_manager = self._subscription_manager
            await self._ws_manager.connect()

            # 8. 백그라운드 태스크 시작 - Phase 4-B: BackgroundTaskManager
            self._bg_task_manager = BackgroundTaskManager(
                config=self._config,
                risk_settings=self._risk_settings,
                position_manager=self._position_manager,
                risk_manager=self._risk_manager,
                trade_repo=self._trade_repo,
                data_manager=self._data_manager,
                market_schedule=self._market_schedule,
                auto_screener=self._auto_screener,
                strategy_orchestrator=self._strategy_orchestrator,
                universe=self._universe,
                market_api=self._market_api,
                candle_manager=self._candle_manager,
                telegram=self._telegram,
                logger=self._logger,
                callbacks=BackgroundTaskCallbacks(
                    get_engine_state=lambda: self._state.value,
                    check_and_handle_market_open=self._check_and_handle_market_open,
                    check_daily_reset=self._check_daily_reset,
                    sync_positions=self._sync_positions,
                    verify_tier1_consistency=self._verify_tier1_consistency,
                    cancel_pending_orders_at_eod=self._cancel_pending_orders_at_eod,
                    get_market_status=lambda: self._get_market_status().value,
                    build_v7_callbacks=self._build_v7_callbacks,
                    collect_strategy_tasks=lambda ctx: (
                        self._strategy_orchestrator.collect_background_tasks(ctx)
                        if self._strategy_orchestrator else []
                    ),
                ),
            )
            self._bg_task_manager.start_all(self._tasks)

            # 9. RealTimeDataManager 시작 (시세 폴링/WebSocket)
            self._running = True
            await self._data_manager.start()
            self._logger.info("RealTimeDataManager 시작 완료")

            # C1 Fix: 모든 연결 완료 후 시작 플래그 설정
            # - WebSocket 연결, 백그라운드 태스크, DataManager 모두 시작 후
            # - 이 시점부터 신호 처리 허용
            self._startup_complete = True
            self._logger.info("[V6.2-A] 시작 완료 - 신호 처리 시작")

            # V7.1: Health Monitor 초기화
            self._health_monitor = SystemHealthMonitor(logger=self._logger)
            await self._health_monitor.start(HealthCallbacks(
                get_notification_queue_stats=lambda: (
                    self._v7_strategy.notification_queue.get_stats()
                    if self._v7_strategy else None
                ),
                get_telegram_stats=lambda: (
                    self._telegram.get_stats() if self._telegram else None
                ),
                get_v7_coordinator_status=lambda: (
                    self._v7_strategy.signal_coordinator.get_status()
                    if self._v7_strategy and self._v7_strategy.signal_coordinator
                    else None
                ),
                get_signal_processor_stats=lambda: (
                    self._signal_processor.get_stats()
                    if self._signal_processor else None
                ),
                get_exit_coordinator_stats=lambda: (
                    self._exit_coordinator.get_stats()
                    if self._exit_coordinator else None
                ),
                send_telegram=self._send_telegram_alert,
                is_engine_running=lambda: self._state in [EngineState.RUNNING, EngineState.PAUSED],
            ))
            self._logger.info("[V7.1] SystemHealthMonitor 시작")

            self._logger.info("거래 엔진 시작 완료")

            # 텔레그램 알림
            await self._telegram.send_message(
                f"[시스템 시작]\n"
                f"모드: {'모의투자' if self._settings.is_paper_trading else '실전투자'}\n"
                f"유니버스: {self._universe.count}개 종목"
            )

            return True

        except Exception as e:
            self._logger.error(f"엔진 시작 실패: {e}")
            self._state = EngineState.STOPPED
            return False

    async def stop(self) -> None:
        """엔진 정지"""
        if self._state == EngineState.STOPPED:
            return

        self._state = EngineState.STOPPING
        self._logger.info("거래 엔진 정지 중...")

        # 폴링 루프 플래그 해제
        self._running = False

        # RealTimeDataManager 정지
        await self._data_manager.stop()
        self._logger.info("RealTimeDataManager 정지됨")

        # 백그라운드 태스크 취소
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()

        # V7.1: Health Monitor 정지
        if self._health_monitor:
            await self._health_monitor.stop()

        # =========================================
        # V7.0 Purple-ReAbs 정리
        # =========================================
        if self._strategy_orchestrator:
            self._logger.info("[Phase 3-1] StrategyOrchestrator 종료 정리 시작")

            # V7 비동기 종료: Strategy를 통해 접근
            v7_strategy = self._strategy_orchestrator.get_base_strategy("V7_PURPLE_REABS")
            if v7_strategy and hasattr(v7_strategy, 'async_shutdown'):
                await v7_strategy.async_shutdown()

            # 모든 전략의 동기 정리 (on_shutdown)
            self._strategy_orchestrator.dispatch_shutdown()

            # ExitCoordinator V7 Exit States 정리
            self._exit_coordinator.clear_all_v7_states()

            self._logger.info("[Phase 3-1] StrategyOrchestrator 종료 정리 완료")

        # SubscriptionManager 정리
        if self._subscription_manager:
            self._subscription_manager.stop_health_check()
            await self._subscription_manager.clear_all()

        # WebSocket 연결 종료 (조건검색용)
        if self._websocket:
            await self._websocket.disconnect()

        # 상태 초기화
        self._candle_manager.remove_all()
        self._atr_alert_manager.clear_all()  # PRD v3.2.4: ATR 알림 감시 종목 정리

        self._state = EngineState.STOPPED
        self._logger.info("거래 엔진 정지 완료")

        # 텔레그램 알림
        await self._telegram.send_message(
            f"[시스템 정지]\n"
            f"포지션: {self._position_manager.get_position_count()}개\n"
            f"일일 손익: {self._risk_manager.get_daily_pnl():+,}원"
        )

    async def pause(self) -> None:
        """매매 일시 중지 (포지션 모니터링은 계속)"""
        if self._state == EngineState.RUNNING:
            self._state = EngineState.PAUSED
            self._logger.info("매매 일시 중지")
            await self._telegram.send_message("[매매 일시 중지] 신규 진입 차단됨")

    async def resume(self) -> None:
        """매매 재개"""
        if self._state == EngineState.PAUSED:
            self._state = EngineState.RUNNING
            self._logger.info("매매 재개")
            await self._telegram.send_message("[매매 재개] 신규 진입 허용됨")

    # =========================================
    # 실시간 데이터 처리
    # =========================================

    async def on_tick(self, tick: Tick) -> None:
        """
        실시간 틱 데이터 수신 처리

        WebSocket에서 틱 데이터 수신 시 호출됩니다.

        Args:
            tick: 체결 틱 데이터
        """
        if self._state not in [EngineState.RUNNING, EngineState.PAUSED]:
            return

        stock_code = tick.stock_code

        # 1. CandleBuilder에 틱 전달
        builder = self._candle_manager.get_builder(stock_code)
        if builder is None:
            # 유니버스에 있으면 빌더 추가
            is_in_universe = self._universe.is_in_universe(stock_code)
            if is_in_universe:
                builder = self._candle_manager.add_stock(stock_code)
                self._logger.info(f"[on_tick] CandleBuilder 동적 생성: {stock_code}")
            else:
                # 디버그: 왜 유니버스에 없는지 확인 (100회마다 로깅)
                if self._stats["ticks_received"] % 100 == 0:
                    universe_codes = list(self._universe._stocks.keys()) if hasattr(self._universe, '_stocks') else []
                    self._logger.debug(
                        f"[on_tick] {stock_code} 유니버스 없음 (등록된 종목: {universe_codes[:5]}...)"
                    )

        if builder:
            await builder.on_tick_async(tick)

        # 2. 보유 종목이면 가격 업데이트 및 청산 체크
        if self._position_manager.has_position(stock_code):
            await self._check_position_exit(stock_code, tick.price)

    async def _update_candles_from_api(self, stock_code: str, timeframe: Timeframe) -> None:
        """
        분봉 API를 조회하여 CandleBuilder의 캔들 데이터를 정확한 값으로 업데이트

        REST 폴링으로 생성된 캔들은 폴링 시점의 스냅샷 가격을 사용하므로
        실제 봉 종가와 다를 수 있습니다. 봉 완성 시 API를 조회하여
        정확한 OHLCV 데이터로 업데이트합니다.

        Args:
            stock_code: 종목코드
            timeframe: 타임프레임 (1분봉 또는 3분봉)
        """
        try:
            # 타임프레임에 따른 API 파라미터 설정
            if timeframe == Timeframe.M1:
                api_timeframe = 1
            elif timeframe == Timeframe.M3:
                api_timeframe = 3
            else:
                return

            # 분봉 API 조회 (최근 20개 충분)
            minute_candles = await self._market_api.get_minute_chart(
                stock_code=stock_code,
                timeframe=api_timeframe,
                count=20,
            )

            if not minute_candles:
                self._logger.warning(f"[API 조회] {stock_code} 분봉 데이터 없음")
                return

            # MinuteCandle → Candle 변환
            candles = []
            for mc in minute_candles:
                candle = Candle(
                    stock_code=stock_code,
                    timeframe=timeframe,
                    time=mc.timestamp.replace(second=0, microsecond=0),  # 초/마이크로초 제거
                    open=mc.open_price,
                    high=mc.high_price,
                    low=mc.low_price,
                    close=mc.close_price,
                    volume=mc.volume,
                    is_complete=True,
                )
                candles.append(candle)

            # CandleBuilder 업데이트
            builder = self._candle_manager.get_builder(stock_code)
            if builder:
                updated = builder.update_candles_from_api(candles, timeframe)

                # 최신 캔들 로깅 (정확한 값)
                if candles:
                    latest = candles[-1]
                    self._logger.info(
                        f"[API 업데이트] {stock_code} {timeframe.value}: "
                        f"O={latest.open:,} H={latest.high:,} L={latest.low:,} C={latest.close:,} "
                        f"(총 {updated}개 업데이트)"
                    )

        except Exception as e:
            self._logger.error(
                f"[API 조회 실패] {stock_code} {timeframe.value}: {e}"
            )

    async def _on_candle_complete(self, stock_code: str, candle) -> None:
        """봉 완성 시 신호 탐지 및 청산 체크 (V6.2-L NXT 확장)"""
        # V6.2-L: NXT 청산 가능 시간 체크 (08:00~15:20, 15:30~20:00)
        # - 08:00~08:50: NXT 프리마켓 (청산 가능)
        # - 09:00~15:20: 정규장 (신호 + 청산)
        # - 15:20~15:30: NXT 중단 (스킵)
        # - 15:30~20:00: NXT 애프터마켓 (청산만)
        if not self._is_nxt_exit_hours():
            self._logger.debug(
                f"[봉완성] {stock_code} - NXT 중단/장외 시간대 스킵"
            )
            return

        # 봉 완성 로깅 (REST 폴링 기반 - 부정확할 수 있음)
        self._logger.info(
            f"[봉완성] {stock_code} {candle.timeframe.value}: "
            f"O={candle.open:,} H={candle.high:,} L={candle.low:,} C={candle.close:,} (폴링)"
        )

        if self._state != EngineState.RUNNING:
            self._logger.debug(f"[봉완성] 엔진 상태가 RUNNING이 아님: {self._state.value}")
            return

        # 유니버스에 없으면 무시
        if not self._universe.is_in_universe(stock_code):
            self._logger.debug(f"[봉완성] 유니버스에 없음: {stock_code}")
            return

        # [V7.1-Fix13] 이벤트 기반 ConfirmCheck: 3m 봉 완성 시 V7SignalCoordinator로 전달
        if (candle.timeframe == Timeframe.M3
                and self._v7_strategy
                and self._v7_strategy.signal_coordinator
                and not self._position_manager.has_position(stock_code)):
            try:
                coordinator = self._v7_strategy.signal_coordinator
                if hasattr(coordinator, '_callbacks') and coordinator._callbacks:
                    await coordinator._on_candle_complete_confirm(
                        stock_code, candle, coordinator._callbacks
                    )
            except Exception as e:
                self._logger.warning(f"[V7 EventConfirm] {stock_code} 오류: {e}")

        # Grand Trend V6/V6.2-A: 보유 중이면 3분봉 완성 시 트레일링 스탑 업데이트 + 청산 체크
        if self._position_manager.has_position(stock_code):
            if candle.timeframe == Timeframe.M3 and self._exit_manager:
                # ATR 트레일링 스탑 업데이트
                # V6: 분할 익절 후에만 작동
                # V6.2-A: 진입 즉시 활성화 + Structure Warning 업데이트
                await self._exit_manager.update_trailing_stop_on_candle_complete(stock_code, candle)

                # V6.2-A: 3분봉 완성 시 청산 체크 (bar_low 사용)
                if not self._risk_settings.use_partial_exit:
                    await self._check_position_exit(stock_code, candle.close, bar_low=candle.low)

            self._logger.debug(f"[봉완성] 이미 보유 중: {stock_code}")
            return

        # ============================================================
        # Phase 3-2: 분봉 API 조회 조건부 실행
        # CandleBuilder가 실시간 틱으로 충분한 데이터를 가지고 있으면 스킵
        # REST 폴링은 스냅샷 가격을 사용하므로 실제 봉 종가와 다를 수 있음
        # ============================================================
        builder = self._candle_manager.get_builder(stock_code)
        needs_api_update = True

        if builder:
            candle_count = builder.get_candle_count(candle.timeframe)
            # Phase 3-2: CandleBuilder에 60개 이상 봉이 있으면 API 호출 스킵
            # 실시간 틱 데이터가 충분히 축적된 경우 API 호출 불필요
            if candle_count >= 60:
                needs_api_update = False
                self._logger.debug(
                    f"[Phase 3-2] {stock_code} {candle.timeframe.value}: "
                    f"API 조회 스킵 (캔들 {candle_count}개 보유)"
                )

        if needs_api_update:
            await self._update_candles_from_api(stock_code, candle.timeframe)

        # 봉 데이터 가져오기 (API로 업데이트된 정확한 데이터)
        candles_1m = self._candle_manager.get_candles(stock_code, Timeframe.M1)
        candles_3m = self._candle_manager.get_candles(stock_code, Timeframe.M3)

        self._logger.debug(
            f"[신호탐지] {stock_code} 봉 데이터: 1분봉={len(candles_1m)}개, 3분봉={len(candles_3m)}개"
        )

        # 종목명 조회
        stock = self._universe.get_stock(stock_code)
        stock_name = stock.stock_name if stock else ""

        # V6.2-D: 52주 고점 근접 종목 조기 신호 허용 판별
        override_time_filter = False
        if self._auto_screener:
            entry = self._auto_screener.get_watchlist_entry(stock_code)
            if entry and entry.high_52w_ratio >= self._risk_settings.near_52w_high_ratio:
                override_time_filter = True

        # V6.2-P: current_time 1회 계산 (datetime.now() 중복 호출 방지)
        current_time = datetime.now(KST).time()

        # V7.0: V6 SNIPER_TRAP 신호 탐지 (비활성화 시 빈 리스트)
        if self._risk_settings.sniper_trap_enabled and self._signal_detector:
            signals = self._signal_detector.check_all_signals(
                candles_1m, candles_3m, stock_code, stock_name,
                override_time_filter=override_time_filter,
                current_time=current_time
            )
        else:
            signals = []  # V7: V6 신호 비활성화 (Purple-ReAbs만 사용)

        if signals:
            self._logger.info(
                f"[신호감지!] {stock_code} {stock_name}: "
                f"{[s.strategy.value for s in signals]}"
            )

        for signal in signals:
            await self._process_signal(signal)

    async def _process_signal(self, signal: Signal) -> None:
        """
        Phase 3: 신호 처리 및 주문 실행

        TradingEngine 특화 로직은 유지하고, 핵심 처리는 SignalProcessor에 위임합니다.

        TradingEngine 특화:
        - startup_complete 체크
        - Watchlist 즉시 승격
        - WATCH 모드

        SignalProcessor 위임:
        - can_execute_trade 체크
        - SIGNAL_ALERT 모드 알림
        - 쿨다운 큐 관리
        - 리스크 체크
        - 매수 실행
        """
        stock_code = signal.stock_code

        # V6.2-A 코드리뷰 A1: 시작 완료 전 신호 무시
        # - DB 복구 중 신호 처리 시 entry_source 불일치 가능
        # - 복구 완료 후에만 신호 처리 허용
        if not self._startup_complete:
            self._logger.debug(
                f"[신호처리 스킵] {stock_code} - 시스템 시작 진행 중 (startup_complete=False)"
            )
            return

        # V6.2-B: Watchlist 종목 즉시 승격 (Active Pool 아닌 경우)
        # - Watchlist에만 있는 종목에서 신호 발생 시 즉시 6필터 체크
        # - 통과하면 Candidate → Active Pool로 승격 후 매수 진행
        if self._auto_screener and not self._auto_screener.is_active(stock_code):
            if self._auto_screener.is_in_watchlist(stock_code):
                self._logger.info(
                    f"[V6.2-B] Watchlist 종목 신호 감지: {stock_code} {signal.stock_name}"
                )
                try:
                    promote_result = await self._auto_screener.check_and_promote(stock_code)
                    if not promote_result.passed:
                        self._logger.info(
                            f"[V6.2-B] 즉시 승격 실패 - 매수 안함: {stock_code} "
                            f"({promote_result.reason})"
                        )
                        return  # 필터 미통과 → 매수 안함
                    # 필터 통과 → Universe 등록 후 매수 진행
                    await self._register_promoted_watchlist_stock(stock_code)
                    self._logger.info(
                        f"[V6.2-B] 즉시 승격 성공 - 매수 진행: {stock_code}"
                    )
                except Exception as e:
                    self._logger.error(f"[V6.2-B] 즉시 승격 에러: {stock_code} - {e}")
                    return

        self._stats["signals_detected"] += 1

        self._logger.info(
            f"[신호처리 시작] {stock_code} {signal.stock_name} "
            f"전략={signal.strategy.value} 가격={signal.price:,}원"
        )

        # PRD v2.0: WATCH 모드 체크 (자동매수 안 함, 알림만)
        # SignalProcessor 위임 전에 체크 - WATCH는 별도 처리
        manual_config = self._manual_stocks.get(stock_code)
        if manual_config and manual_config.mode == StockMode.WATCH:
            self._logger.info(
                f"[WATCH 모드] {stock_code} - 신호 알림만 발송 (자동매수 안 함)"
            )
            if self._telegram:
                await self._telegram.send_message(
                    f"[WATCH] 신호 감지\n\n"
                    f"{signal.stock_name}({stock_code})\n"
                    f"전략: {signal.strategy.value}\n"
                    f"가격: {signal.price:,}원\n"
                    f"{signal.reason}\n\n"
                    f"WATCH 모드: 자동매수 안 함\n"
                    f"수동 매수: /buy {stock_code} <금액>"
                )
            return  # 자동매수 안 함

        # Phase 3: SignalProcessor에 핵심 로직 위임
        from src.utils.config import TradingMode
        trading_mode = "SIGNAL_ALERT" if self._risk_settings.trading_mode == TradingMode.SIGNAL_ALERT else "AUTO_TRADE"

        callbacks = self._build_signal_processor_callbacks()
        result = await self._signal_processor.process_signal(signal, callbacks, trading_mode)

        # 결과 처리
        if result == SignalProcessResult.BLOCKED:
            self._stats["signals_blocked"] += 1
        elif result == SignalProcessResult.QUEUED:
            self._logger.debug(f"[Phase 3] 신호 큐에 저장됨: {stock_code}")
        elif result == SignalProcessResult.EXECUTED:
            self._logger.info(f"[Phase 3] 매수 실행 완료: {stock_code}")
        elif result == SignalProcessResult.ALERT_SENT:
            self._stats["signal_alerts_sent"] = self._stats.get("signal_alerts_sent", 0) + 1

    # ========== V6.2-P: 텔레그램 비동기 전송 ==========

    async def _send_telegram_fire_and_forget(self, message: str, context: str = "") -> None:
        """
        V6.2-P: 텔레그램 메시지 비동기 전송 (Fire-and-Forget)

        매수 주문과 병렬로 텔레그램 알림을 전송합니다.
        전송 실패 시에도 매수 주문에 영향을 주지 않습니다.

        Args:
            message: 전송할 메시지
            context: 로그용 컨텍스트 (예: 종목코드)
        """
        try:
            if self._telegram:
                await self._telegram.send_message(message)
        except Exception as e:
            # 텔레그램 실패는 매수에 영향을 주지 않음 - 로그만 남김
            self._logger.warning(
                f"[텔레그램] 전송 실패 (무시됨): {context} - {e}"
            )

    # ========== Phase 3: 신호 큐 관련 메서드 (SignalProcessor 위임) ==========

    async def _process_signal_queue(self) -> None:
        """
        Phase 3: SignalProcessor 큐 처리 위임

        쿨다운 해제 후 호출되어 대기 중인 신호를 처리합니다.
        SignalProcessor.process_queue()에 위임합니다.
        """
        callbacks = self._build_signal_processor_callbacks()
        processed = await self._signal_processor.process_queue(callbacks)

        if processed:
            self._stats["signals_from_queue"] += 1
            self._logger.info(f"[Phase 3] 큐 신호 처리 완료: {processed}")

    def _get_order_lock(self, stock_code: str) -> asyncio.Lock:
        """
        종목별 Lock 반환 (없으면 생성)

        동일 종목에 대한 동시 주문 방지:
        - 매수 중 추가 매수 방지
        - 매도 중 추가 매도 방지
        - 매수/매도 동시 실행 방지
        """
        if stock_code not in self._order_locks:
            self._order_locks[stock_code] = asyncio.Lock()
        return self._order_locks[stock_code]

    async def _check_pending_sell_order(
        self,
        stock_code: str,
        position: "Position",
    ) -> Optional[bool]:
        """
        미체결 매도 주문 확인 및 처리

        Critical Fix: 매도 타임아웃 후 중복 주문 방지

        Args:
            stock_code: 종목 코드
            position: 현재 포지션

        Returns:
            None: 미체결 주문 없음 → 새 주문 진행
            True: 체결 완료 → 청산 처리됨
            False: 미체결/부분체결 → 대기 필요
        """
        # P0: Lock으로 pending_sell_orders 접근 보호
        async with self._pending_sell_lock:
            if stock_code not in self._pending_sell_orders:
                return None
            pending_order_no = self._pending_sell_orders[stock_code]

        self._logger.info(f"미체결 매도 주문 확인: {stock_code}, 주문번호={pending_order_no}")

        try:
            # 주문 체결 상태 조회
            execution = await self._account_api.get_execution_info(
                order_no=pending_order_no,
                stock_code=stock_code,
            )

            if execution is None:
                # 주문 정보 없음 - 취소되었거나 오류
                self._logger.warning(f"미체결 주문 정보 없음, 추적 제거: {pending_order_no}")
                async with self._pending_sell_lock:
                    del self._pending_sell_orders[stock_code]
                return None

            if execution.filled_qty > 0 and execution.unfilled_qty == 0:
                # 전량 체결됨 → 청산 처리
                self._logger.info(
                    f"미체결 주문 전량 체결 확인: {pending_order_no}",
                    filled_qty=execution.filled_qty,
                    filled_price=execution.filled_price,
                )

                # 청산 처리 (RiskManager, PositionManager, DB)
                actual_exit_price = execution.filled_price

                # RiskManager 청산
                pnl = self._risk_manager.on_exit(
                    stock_code,
                    actual_exit_price,
                    ExitReason.MANUAL,  # 지연 체결
                )

                # DB 기록
                trade_id = position.signal_metadata.get("trade_id") if position.signal_metadata else None
                if self._trade_repo and trade_id:
                    try:
                        await self._trade_repo.close(
                            trade_id=trade_id,
                            exit_price=actual_exit_price,
                            exit_order_no=pending_order_no,
                            exit_reason="DELAYED_FILL",
                        )
                    except Exception as db_err:
                        self._logger.error(f"지연 체결 DB 기록 실패: {db_err}")

                # PositionManager 청산
                await self._position_manager.close_position(
                    stock_code=stock_code,
                    exit_price=actual_exit_price,
                    reason="DELAYED_FILL",
                    order_no=pending_order_no,
                )

                # 추적 제거
                async with self._pending_sell_lock:
                    del self._pending_sell_orders[stock_code]
                self._stats["trades_completed"] += 1

                # 알림
                if self._telegram:
                    profit_rate = ((actual_exit_price - position.entry_price) / position.entry_price) * 100
                    await self._telegram.send_message(
                        f"✅ **지연 체결 확인**\n"
                        f"• 종목: {position.stock_name} ({stock_code})\n"
                        f"• 체결가: {actual_exit_price:,}원\n"
                        f"• 수익률: {profit_rate:+.2f}%\n"
                        f"• 주문번호: {pending_order_no}"
                    )

                return True

            elif execution.unfilled_qty > 0:
                # 미체결/부분체결 → 대기
                self._logger.info(
                    f"미체결 주문 대기 중: {pending_order_no}",
                    filled_qty=execution.filled_qty,
                    unfilled_qty=execution.unfilled_qty,
                )
                return False

        except Exception as e:
            self._logger.error(f"미체결 주문 확인 에러: {e}")
            # 에러 시에도 추적 유지 (안전)

        return False

    async def _execute_buy_order(self, signal: Signal) -> None:
        """
        매수 주문 실행
        Phase 2: OrderExecutor로 위임

        P0 이슈 수정:
        1. 종목별 Lock으로 동시 주문 방지
        2. 체결 확인 후 포지션 등록
        3. 체결가 기반 포지션 등록
        4. 미체결 시 주문 취소
        """
        if self._order_executor:
            success = await self._order_executor.execute_buy_order(signal)
            if success:
                # 성공 시 TradingEngine stats도 업데이트
                self._stats["orders_placed"] += 1
        else:
            self._logger.warning(f"OrderExecutor 미초기화 - 매수 주문 스킵: {signal.stock_code}")

    # =========================================
    # PRD v3.0: EOD (End of Day) 처리
    # =========================================

    async def _cancel_pending_orders_at_eod(self) -> None:
        """
        장 마감 시 미체결 매도 주문 취소 (15:25 실행)

        PRD v3.0: 장 마감 전 미체결 주문 정리
        현재는 빈 구현 - 향후 ExitManager에 cancel_pending_orders 구현 필요
        """
        self._logger.info("[EOD] 미체결 주문 취소 - 현재 구현되지 않음 (향후 추가 예정)")

    # =========================================
    # PRD v3.0: 시장 상태 체크
    # =========================================

    def _get_market_status(self) -> MarketStatus:
        """
        현재 시장 상태 조회 (V6.2-L NXT 확장)

        시간대 구분:
        - ~08:00: CLOSED (장 시작 전)
        - 08:00~08:50: NXT_PRE_MARKET (NXT 프리마켓, 시가결정)
        - 08:50~09:00: PRE_MARKET (동시호가)
        - 09:00~15:20: REGULAR (정규장)
        - 15:20~15:30: KRX_CLOSING (KRX 단일가, NXT 중단!)
        - 15:30~20:00: NXT_AFTER (NXT 애프터마켓)
        - 20:00~: AFTER_HOURS (장 종료)

        Returns:
            MarketStatus: 현재 시장 상태
        """
        now = datetime.now()
        current_time = now.time()

        # V6.2-L NXT 시간대 정의
        NXT_PRE_START = time(8, 0, 0)       # NXT 프리마켓 시작
        SIMULTANEOUS_START = time(8, 50, 0)  # 동시호가 시작
        MARKET_OPEN = time(9, 0, 0)          # 정규장 시작
        KRX_CLOSING_START = time(15, 20, 0)  # KRX 단일가 시작 (NXT 중단)
        KRX_CLOSING_END = time(15, 30, 0)    # KRX 단일가 종료
        NXT_AFTER_END = time(20, 0, 0)       # NXT 애프터마켓 종료

        if current_time < NXT_PRE_START:
            return MarketStatus.CLOSED
        elif current_time < SIMULTANEOUS_START:
            return MarketStatus.NXT_PRE_MARKET
        elif current_time < MARKET_OPEN:
            return MarketStatus.PRE_MARKET
        elif current_time < KRX_CLOSING_START:
            return MarketStatus.REGULAR
        elif current_time < KRX_CLOSING_END:
            return MarketStatus.KRX_CLOSING  # NXT 중단!
        elif current_time < NXT_AFTER_END:
            return MarketStatus.NXT_AFTER
        else:
            return MarketStatus.AFTER_HOURS

    def _is_regular_trading_hours(self) -> bool:
        """
        장중 여부 확인 (PRD v3.0 6-1)

        [CRITICAL] 08:30~09:00 예상 체결가로 매매 주문을 내면 안됨!
        09:00~15:30 사이에만 True 반환

        Returns:
            bool: 장중 여부
        """
        return self._get_market_status() == MarketStatus.REGULAR

    def _is_nxt_trading_hours(self) -> bool:
        """
        V6.2-L: NXT 거래 가능 시간 여부 (매수 가능)

        거래 가능:
        - REGULAR (09:00~15:20): KRX + NXT 정규장

        거래 불가:
        - KRX_CLOSING (15:20~15:30): NXT 중단
        - NXT_AFTER (15:30~20:00): 청산만 가능, 신규 매수 불가
        - 기타 시간대

        Returns:
            bool: NXT 거래 가능 여부
        """
        return self._get_market_status() == MarketStatus.REGULAR

    def _is_nxt_exit_hours(self) -> bool:
        """
        V6.2-L: NXT 청산/손절 가능 시간 여부

        청산 가능:
        - NXT_PRE_MARKET (08:00~08:50): 프리마켓 청산 허용
        - REGULAR (09:00~15:20): 정규장
        - NXT_AFTER (15:30~20:00): NXT 애프터마켓 청산/손절

        청산 불가:
        - KRX_CLOSING (15:20~15:30): NXT 중단

        Returns:
            bool: 청산/손절 가능 여부
        """
        status = self._get_market_status()
        return status in (
            MarketStatus.NXT_PRE_MARKET,
            MarketStatus.REGULAR,
            MarketStatus.NXT_AFTER
        )

    def _is_nxt_suspended(self) -> bool:
        """
        V6.2-L: NXT 중단 구간 (15:20~15:30) 여부

        KRX 종가 단일가 시간 동안 NXT는 거래 중단.

        Returns:
            bool: NXT 중단 여부
        """
        return self._get_market_status() == MarketStatus.KRX_CLOSING

    async def _can_execute_trade(self, stock_code: str = "") -> bool:
        """
        매매 실행 가능 여부 체크 (PRD v3.0)

        체크 항목:
        1. 장중 여부 (09:00~15:30)
        2. Global_Lock 여부 (시장 급락)
        3. VI 쿨다운 여부 (종목별)

        C-009 FIX: async 메서드로 변경 (VI 쿨다운 체크가 async)

        Args:
            stock_code: 종목코드 (VI 체크용, 빈 문자열이면 스킵)

        Returns:
            bool: 매매 가능 여부
        """
        # 1. 장중 여부
        if not self._is_regular_trading_hours():
            return False

        # 2. Global_Lock 체크 (Phase 4-D: MarketMonitor)
        if self._market_monitor.global_lock:
            return False

        # 3. VI 쿨다운 체크 (C-009 FIX: await 추가)
        if stock_code and not await self._is_vi_cooled(stock_code):
            return False

        return True

    async def _is_vi_cooled(self, stock_code: str) -> bool:
        """
        VI 쿨다운 체크 (PRD v3.0 6-3)

        VI 해제 후 60초간 진입 금지

        C-009 FIX: async 메서드로 변경 (asyncio.Lock 사용)

        Args:
            stock_code: 종목코드

        Returns:
            bool: VI 쿨다운 완료 여부
        """
        # C-009 FIX: asyncio.Lock으로 VI 상태 보호
        async with self._vi_lock:
            if stock_code not in self._vi_cooldown_stocks:
                return True

            elapsed = (datetime.now() - self._vi_cooldown_stocks[stock_code]).total_seconds()
            if elapsed >= 60:
                # 쿨다운 완료 → 제거
                del self._vi_cooldown_stocks[stock_code]
                return True

            return False

    async def on_vi_triggered(self, stock_code: str) -> None:
        """
        VI 발동 시 호출 (외부에서 호출)

        PRD v3.2: VI 발동 시 매도 로직 일시 정지
        - 진입 금지 (기존)
        - 매도 로직 정지 (EMA20 이탈, Crash Guard, Floor Line 등)
        - Safety Net(-4%)은 계속 작동

        C-009 FIX: async 메서드로 변경 (asyncio.Lock 사용)
        """
        # C-009 FIX: asyncio.Lock으로 VI 상태 보호
        async with self._vi_lock:
            self._vi_active[stock_code] = datetime.now()  # PRD v3.2: VI 활성 상태 추적
        self._logger.warning(f"VI 발동: {stock_code} - 진입 금지 + 매도 로직 일시 정지")

    async def on_vi_released(self, stock_code: str) -> None:
        """
        VI 해제 시 호출 (외부에서 호출)

        PRD v3.2: VI 해제 후 쿨다운 시작

        C-009 FIX: async 메서드로 변경 (asyncio.Lock 사용)
        """
        # C-009 FIX: asyncio.Lock으로 VI 상태 보호
        async with self._vi_lock:
            # VI 활성 상태 해제
            if stock_code in self._vi_active:
                del self._vi_active[stock_code]

            # 쿨다운 시작 (60초 후 진입 가능)
            self._vi_cooldown_stocks[stock_code] = datetime.now()
        self._logger.info(f"VI 해제: {stock_code} - 60초 쿨다운 시작, 매도 로직 재개")

    async def _is_vi_active(self, stock_code: str) -> bool:
        """
        VI 활성 상태 확인 (PRD v3.2)

        VI가 발동되어 아직 해제되지 않은 상태인지 확인합니다.
        VI 활성 중에는 매도 로직(EMA20 이탈, Crash Guard 등)이 정지됩니다.

        PRD v3.2 개선: 타임아웃 기반 자동 해제
        - VI 발동 후 vi_timeout_seconds(기본 5분) 경과 시 자동 해제
        - WebSocket VI 해제 이벤트가 누락되어도 영구 활성 상태 방지

        C-009 FIX: async 메서드로 변경 (asyncio.Lock 사용)

        Args:
            stock_code: 종목코드

        Returns:
            bool: VI 활성 상태 여부
        """
        # C-009 FIX: asyncio.Lock으로 VI 상태 보호
        async with self._vi_lock:
            if stock_code not in self._vi_active:
                return False

            # 타임아웃 기반 자동 해제 체크
            vi_triggered_time = self._vi_active[stock_code]
            elapsed = (datetime.now() - vi_triggered_time).total_seconds()
            vi_timeout = self._risk_settings.vi_timeout_seconds  # 기본 300초 (5분)

            if elapsed >= vi_timeout:
                # 타임아웃 자동 해제 - Lock 안에서 직접 수행
                self._logger.warning(
                    f"VI 타임아웃 자동 해제: {stock_code} "
                    f"(발동 후 {elapsed:.0f}초 경과, 임계치: {vi_timeout}초)"
                )
                # VI 활성 상태 해제
                del self._vi_active[stock_code]
                # 쿨다운 시작
                self._vi_cooldown_stocks[stock_code] = datetime.now()
                return False

            return True

    async def _check_crash_guard(self, stock_code: str, current_price: int) -> bool:
        """
        Crash Guard 체크 (PRD v3.2)

        현재가 < EMA20 * 0.98 (Crash Guard Rate) → 즉시 전량 매도
        봉 완성을 기다리지 않고 실시간으로 체크합니다.

        분할 익절이 완료된 포지션에만 적용됩니다.

        Args:
            stock_code: 종목코드
            current_price: 현재가

        Returns:
            True if Crash Guard 발동 (매도 완료), False otherwise
        """
        # Crash Guard 비활성화 체크
        if not self._risk_settings.crash_guard_enabled:
            return False

        # 분할 익절 후만 체크 (PRD v3.2)
        if not self._risk_manager.is_partial_exited(stock_code):
            return False

        # VI 발동 중이면 스킵 (PRD v3.2: VI 시 매도 로직 일시 정지)
        # C-009 FIX: await 추가
        if await self._is_vi_active(stock_code):
            self._logger.debug(f"VI 활성 중 - Crash Guard 스킵: {stock_code}")
            return False

        try:
            # 설정된 타임프레임 (기본 3분봉)
            target_timeframe = Timeframe.M3 if self._risk_settings.exit_ema_timeframe == "M3" else Timeframe.M1

            # CandleBuilder에서 봉 데이터 가져오기
            builder = self._candle_manager.get_builder(stock_code)
            if builder is None:
                return False

            candles = builder.get_candles(target_timeframe)
            if candles is None or len(candles) < self._risk_settings.exit_ema_period:
                # PRD v3.2: 캔들 데이터 부족 시 경고 로깅
                # Safety Net(-4%)은 항상 작동하므로 대손실 방지됨
                self._logger.debug(
                    f"Crash Guard 스킵 - 캔들 부족: {stock_code} "
                    f"(현재 {len(candles) if candles is not None else 0}개 < 필요 {self._risk_settings.exit_ema_period}개)"
                )
                return False

            # EMA20 계산 (Indicator 정적 메서드 사용)
            ema20 = Indicator.ema(candles['close'], self._risk_settings.exit_ema_period).iloc[-1]
            if ema20 is None or ema20 == 0:
                self._logger.warning(f"Crash Guard EMA20 계산 실패: {stock_code}")
                return False

            # Crash Guard 임계값 계산
            crash_threshold = ema20 * self._risk_settings.crash_guard_rate  # 기본 0.98

            # 현재가 < EMA20 * 0.98 → Crash Guard 발동!
            if current_price < crash_threshold:
                timeframe_str = "3분봉" if target_timeframe == Timeframe.M3 else "1분봉"
                self._logger.warning(
                    f"[PRD v3.2] Crash Guard 발동: {stock_code}",
                    current_price=current_price,
                    ema20=int(ema20),
                    crash_threshold=int(crash_threshold),
                    crash_guard_rate=self._risk_settings.crash_guard_rate,
                )

                await self._execute_sell_order(
                    stock_code,
                    ExitReason.TREND_BREAK,
                    f"Crash Guard 발동! (현재가 {current_price:,} < {timeframe_str} EMA20×{self._risk_settings.crash_guard_rate} = {int(crash_threshold):,})"
                )
                return True

            return False

        except Exception as e:
            self._logger.warning(f"Crash Guard 체크 에러: {stock_code} - {e}")
            return False

    async def _handle_market_open_gap(self) -> None:
        """
        장 시작 갭 대응 (PRD v3.0 6-2)

        09:00 장 시작 시 호출되어 보유 포지션의 갭 상황을 처리합니다:
        1. 갭 하락으로 손절가 이탈 → 즉시 청산
        2. 갭 상승으로 익절가 도달 → 분할 익절 체크
        3. 갭 상황 알림 발송
        """
        if self._market_open_handled:
            return

        self._market_open_handled = True
        positions = self._position_manager.get_all_positions()

        if not positions:
            self._logger.info("[장 시작] 보유 포지션 없음 - 갭 대응 건너뜀")
            return

        self._logger.info(f"[장 시작] {len(positions)}개 포지션 갭 체크 중...")

        for position in positions:
            try:
                stock_code = position.stock_code

                # 현재가 조회 (get_current_price는 int 반환)
                current_price = await self._market_api.get_current_price(stock_code)
                if current_price <= 0:
                    self._logger.warning(f"[갭 체크] {stock_code} 현재가 조회 실패")
                    continue

                # 수익률 계산
                profit_rate = (current_price - position.entry_price) / position.entry_price * 100
                gap_pct = profit_rate  # 갭 = 시작가 대비 수익률

                self._logger.info(
                    f"[갭 체크] {position.stock_name}({stock_code}): "
                    f"시가={current_price:,}원, 매수가={position.entry_price:,}원, "
                    f"갭={gap_pct:+.1f}%"
                )

                # V6.2-Q: 갭 손절은 Floor Line 기반이었으나 삭제됨
                # Safety Net(-4%)은 check_exit()에서 bar_low/current_price 기반으로 처리

                position_risk = self._risk_manager._position_risks.get(stock_code)

                # 갭 상승: 분할 익절 체크 (+3% 이상, PRD v3.2)
                if profit_rate >= self._risk_settings.partial_take_profit_rate:
                    if position_risk and not position_risk.is_partial_exit:
                        self._logger.info(
                            f"[갭 익절] {stock_code} 시가={current_price:,} - "
                            f"분할 익절 조건 도달 ({profit_rate:+.1f}%)"
                        )
                        # 분할 익절 체크는 _check_position_exit에서 처리
                        # 여기서는 알림만
                        await self._telegram.send_message(
                            f"🔺 장 시작 갭 상승!\n\n"
                            f"📌 {position.stock_name}({stock_code})\n"
                            f"📈 시가: {current_price:,}원 (갭 {gap_pct:+.1f}%)\n"
                            f"🎯 분할 익절 조건 도달\n\n"
                            f"실시간 체크 후 50% 매도 예정"
                        )

                # 일반 갭 알림 (5% 이상)
                elif abs(gap_pct) >= TradingConstants.GAP_SIGNIFICANT_THRESHOLD:
                    emoji = "📈" if gap_pct > 0 else "📉"
                    await self._telegram.send_message(
                        f"{emoji} 장 시작 갭 알림\n\n"
                        f"📌 {position.stock_name}({stock_code})\n"
                        f"💰 시가: {current_price:,}원 (갭 {gap_pct:+.1f}%)\n"
                        f"📊 매수가: {position.entry_price:,}원"
                    )

            except Exception as e:
                self._logger.error(f"[갭 체크] {position.stock_code} 에러: {e}")

        self._logger.info("[장 시작] 갭 대응 완료")

    async def _resubscribe_condition_search_at_market_open(self) -> None:
        """
        V6.2-K: 장 시작 시 조건검색 재구독

        문제: 장 시작 전(05:08 등)에 조건검색 초기 편입 종목이 수신되지만
              "장중 아님"으로 무시됨 → Watchlist 0개
        해결: 09:00:05에 조건검색을 재구독하여 초기 종목을 다시 받음
        """
        self._condition_resubscribed_today = True

        from src.utils.config import TradingMode
        trading_mode = self._risk_settings.trading_mode

        # MANUAL_ONLY가 아닌 경우에만 Auto-Universe 재구독
        if trading_mode == TradingMode.MANUAL_ONLY:
            self._logger.info("[V6.2-K] MANUAL_ONLY 모드 - Auto-Universe 재구독 건너뜀")
            return

        if not self._websocket or not self._websocket.is_connected:
            self._logger.warning("[V6.2-K] WebSocket 미연결 - 조건검색 재구독 건너뜀")
            return

        condition_seq = str(self._risk_settings.auto_universe_condition_seq)
        self._logger.info(f"[V6.2-K] 장 시작 조건검색 재구독 시작: seq={condition_seq}")

        try:
            # 재구독 시도 (start_condition_search 내부에서 기존 구독 해제 후 재구독)
            success = await self._websocket.start_condition_search(seq=condition_seq)

            if success:
                self._logger.info(
                    f"[V6.2-K] 장 시작 조건검색 재구독 성공: seq={condition_seq} "
                    f"- 초기 종목이 Watchlist에 등록됩니다"
                )
            else:
                self._logger.warning(f"[V6.2-K] 장 시작 조건검색 재구독 실패: seq={condition_seq}")

        except Exception as e:
            self._logger.error(f"[V6.2-K] 장 시작 조건검색 재구독 에러: {e}")

    async def _check_and_handle_market_open(self) -> None:
        """
        장 시작 체크 및 갭 대응 트리거 (PRD v3.0)

        09:00:00 ~ 09:00:10 사이에 호출되면 갭 대응 실행
        V6.2-K: 조건검색 재구독 추가 (장 시작 전 초기 편입 → 장중 재수신)
        """
        now = datetime.now()

        # 09:00:00 ~ 09:00:10 사이이고 아직 처리 안됨
        if (now.hour == 9 and now.minute == 0 and now.second < 10
                and not self._market_open_handled):
            await self._handle_market_open_gap()

        # V6.2-K: 09:00:05 ~ 09:00:30 사이에 조건검색 재구독 (갭 대응 후 실행)
        # - 장 시작 전 초기 편입 종목이 "장중 아님"으로 무시되는 문제 해결
        # - 재구독 시 초기 종목을 새로 받아 Watchlist에 등록
        if (now.hour == 9 and now.minute == 0 and 5 <= now.second < 30
                and not self._condition_resubscribed_today):
            await self._resubscribe_condition_search_at_market_open()

    async def _check_daily_reset(self) -> None:
        """
        V6.2-B: 24시간 운영 대응 - 일일 Pool 리셋 (07:40~07:50)

        - Pool만 리셋 (Watchlist, Candidate, Active)
        - 포지션 데이터는 유지됨 (ATR TS, 구조경고 등)
        - 날짜 체크로 중복 리셋 방지 (서버 점검 후에도 안전)
        """
        now = datetime.now()
        today = now.date()

        # 이미 오늘 리셋했으면 스킵
        if self._daily_reset_done and self._last_reset_date == today:
            return

        # 07:40 ~ 07:50 사이에만 리셋
        if now.hour == 7 and 40 <= now.minute < 50:
            self._logger.info("[V6.2-B] 일일 리셋 시작 (07:40~07:50)")

            # Pool 리셋 (포지션은 유지됨)
            if self._auto_screener:
                self._auto_screener.reset_daily()

            self._risk_manager.reset_daily()
            self._position_manager.reset_daily()
            self._signal_alert_cooldown.clear()  # V6.2-Q Patch 3: 일일 쿨다운 리셋

            self._daily_reset_done = True
            self._last_reset_date = today

            self._logger.info("[V6.2-B] 일일 리셋 완료 - Pool 초기화, 포지션 유지")

    # =========================================
    # 포지션 관리
    # =========================================

    async def _check_position_exit(
        self,
        stock_code: str,
        current_price: int,
        bar_low: Optional[int] = None,
    ) -> None:
        """
        포지션 청산 조건 체크

        Phase 3 리팩토링: ExitCoordinator로 위임

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            bar_low: 3분봉 저가 (V6.2-A 고정손절 체크용, 틱 데이터에서는 None)
        """
        # Phase 3: ExitCoordinator로 위임
        callbacks = self._build_exit_coordinator_callbacks(stock_code)
        result = await self._exit_coordinator.check_exit(
            stock_code=stock_code,
            current_price=current_price,
            callbacks=callbacks,
            bar_low=bar_low,
        )

        # 청산 조건 충족 시 매도 실행
        if result.should_exit:
            self._logger.info(
                f"[ExitCoordinator] 청산 실행: {stock_code} | "
                f"reason={result.reason.value if result.reason else 'UNKNOWN'} | "
                f"source={result.source.value if result.source else 'UNKNOWN'} | "
                f"profit={result.profit_rate:+.2f}%"
            )
            await self._execute_sell_order(
                stock_code,
                result.reason or ExitReason.MANUAL,  # fallback: MANUAL (reason should always be set)
                result.message,
            )

    async def _fallback_hard_stop_check(
        self,
        stock_code: str,
        current_price: int,
    ) -> None:
        """
        [Critical] Fallback 손절 체크 - V7 State 기반 긴급 손절

        PositionManager에 포지션이 없지만 V7 Exit State가 존재하는 경우
        (예: HTS 매수 후 API 동기화 지연) -4% 손절만 독립적으로 체크합니다.

        Args:
            stock_code: 종목 코드
            current_price: 현재가
        """
        should_exit = self._exit_coordinator.check_emergency_hard_stop(
            stock_code, current_price
        )

        if should_exit:
            state = self._exit_coordinator.get_v7_state(stock_code)
            entry_price = state.entry_price if state else 0
            stop_price = int(entry_price * 0.96) if entry_price else 0

            self._logger.warning(
                f"[Fallback 손절] {stock_code} | "
                f"V7 State 기반 긴급 손절 발동 | "
                f"entry={entry_price:,} | current={current_price:,} | stop={stop_price:,}"
            )

            # 매도 실행
            await self._execute_sell_order(
                stock_code,
                ExitReason.HARD_STOP,
                f"[Fallback] V7 Hard Stop (-4%): {current_price:,} < {stop_price:,}",
            )

    async def _on_buy_filled_with_v7(
        self,
        stock_code: str,
        entry_price: int,
    ) -> int:
        """
        V7.0: 매수 체결 시 콜백 - V6 TS + V7 Exit State 동시 초기화

        Phase 3 리팩토링: ExitCoordinator.initialize_v7_state() 사용

        V7 활성화 시:
        1. V6 ExitManager의 TS 초기화 (기존 로직 유지)
        2. V7 ExitCoordinator를 통해 Exit State 생성

        Args:
            stock_code: 종목코드
            entry_price: 진입가

        Returns:
            초기 트레일링 스탑 가격 (원), 실패 시 0
        """
        # 1. 기존 V6 TS 초기화 (항상 실행)
        initial_ts = 0
        if self._exit_manager:
            initial_ts = await self._exit_manager.initialize_trailing_stop_on_entry_v62a(
                stock_code, entry_price
            )

        # 2. Phase 3: V7 Exit State 생성은 ExitCoordinator로 위임
        exit_state = self._exit_coordinator.initialize_v7_state(
            stock_code=stock_code,
            entry_price=entry_price,
            entry_date=datetime.now(),
        )

        if exit_state:
            self._logger.info(
                f"[V7] Exit State 생성 (via ExitCoordinator): {stock_code} | "
                f"entry={entry_price:,} | "
                f"fallback_stop={exit_state.get_fallback_stop():,} (-4%)"
            )

        return initial_ts

    def _cleanup_v7_state(self, stock_code: str) -> None:
        """
        V7.0: Exit State 정리

        Phase 3 리팩토링: ExitCoordinator.cleanup_v7_state()로 위임

        포지션 청산 완료 후 V7 상태 딕셔너리에서 제거합니다.

        Args:
            stock_code: 종목 코드
        """
        # Phase 3: ExitCoordinator로 위임
        self._exit_coordinator.cleanup_v7_state(stock_code)

    def _check_safety_lock(self, stock_code: str, current_price: int) -> Optional[str]:
        """
        PRD v3.1: Safety Lock 체크 (급등 시 선제 매도)

        조건:
        1. 분할 익절 완료 (is_partial_exit = True)
        2. 이격도 >= 110% (current_price >= EMA20 * 1.10)
        3. 고점 대비 -5% 하락 (current_price <= highest_price * 0.95)

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            청산 메시지 (조건 충족 시) 또는 None
        """
        # 분할 익절 후만 체크
        if not self._risk_manager.is_partial_exited(stock_code):
            return None

        try:
            # PRD v3.2: 3분봉 데이터 가져오기 (exit_ema_timeframe 설정 참조)
            builder = self._candle_manager.get_builder(stock_code)
            if builder is None:
                return None

            # 설정된 타임프레임 사용 (기본값 M3)
            target_timeframe = Timeframe.M3 if self._risk_settings.exit_ema_timeframe == "M3" else Timeframe.M1
            candles = builder.get_candles(target_timeframe)
            if candles is None or len(candles) < self._risk_settings.exit_ema_period:
                return None

            # EMA20 계산 (Indicator 정적 메서드 사용)
            ema20 = Indicator.ema(candles['close'], self._risk_settings.exit_ema_period).iloc[-1]
            if ema20 is None or ema20 == 0:
                return None

            # 이격도 체크 (EPSILON 적용: 부동소수점 비교 오차 방지)
            disparity = current_price / ema20
            min_disparity = self._risk_settings.safety_lock_disparity  # 1.10 (110%)
            disparity_epsilon = PROFIT_RATE_EPSILON / 100  # 0.0001 (0.01%)

            if disparity < min_disparity - disparity_epsilon:
                return None  # 이격도 부족

            # 고점 대비 하락률 체크 (EPSILON 적용)
            highest = self._risk_manager.get_highest_price(stock_code)
            if highest is None or highest == 0:
                return None

            drop_rate = (current_price - highest) / highest
            max_drop = self._risk_settings.safety_lock_drop_rate  # -0.05 (-5%)

            if drop_rate > max_drop + disparity_epsilon:
                return None  # 아직 충분히 하락하지 않음

            # Safety Lock 트리거!
            self._logger.info(
                f"[V7.0] Safety Lock 트리거: {stock_code}",
                disparity=f"{disparity*100:.1f}%",
                drop_rate=f"{drop_rate*100:.1f}%",
                current_price=current_price,
                highest=highest,
                ema20=int(ema20),
            )

            return (
                f"Safety Lock: 이격도 {disparity*100:.1f}% + "
                f"고점 대비 {drop_rate*100:.1f}% 하락"
            )

        except Exception as e:
            self._logger.warning(f"Safety Lock 체크 에러: {stock_code} - {e}")
            return None

    async def _check_ema20_exit_on_candle_complete(
        self,
        stock_code: str,
        candle,
    ) -> bool:
        """
        PRD v3.2: 3분봉 EMA20 이탈 체크 (Wick Protection)

        분봉 완성 시점에 종가 기준으로만 체크하여
        장중 휩소(whipsaw)를 방지합니다.

        조건:
        1. 분할 익절 완료 (is_partial_exit = True)
        2. 3분봉 완성 (exit_ema_timeframe 설정에 따름)
        3. candle.close < EMA20 (종가 기준!)

        Args:
            stock_code: 종목 코드
            candle: 완성된 캔들

        Returns:
            청산 실행 여부
        """
        # 분할 익절 후만 체크
        if not self._risk_manager.is_partial_exited(stock_code):
            return False

        # PRD v3.2: VI 활성 시 스킵 (매도 로직 일시 정지)
        # C-009 FIX: await 추가
        if await self._is_vi_active(stock_code):
            self._logger.debug(f"VI 활성 중 - EMA20 이탈 체크 스킵: {stock_code}")
            return False

        # 설정된 타임프레임 체크 (기본값 3분봉)
        target_timeframe = Timeframe.M3 if self._risk_settings.exit_ema_timeframe == "M3" else Timeframe.M1
        if candle.timeframe != target_timeframe:
            return False

        try:
            # 해당 타임프레임 데이터 가져오기
            builder = self._candle_manager.get_builder(stock_code)
            if builder is None:
                return False

            candles = builder.get_candles(target_timeframe)
            if candles is None or len(candles) < self._risk_settings.exit_ema_period:
                return False

            # EMA20 계산 (Indicator 정적 메서드 사용)
            ema20 = Indicator.ema(candles['close'], self._risk_settings.exit_ema_period).iloc[-1]
            if ema20 is None or ema20 == 0:
                return False

            # Wick Protection: 종가 기준 체크 (저가 아님!)
            timeframe_str = "3분봉" if target_timeframe == Timeframe.M3 else "1분봉"
            if candle.close < ema20:
                self._logger.info(
                    f"[PRD v3.2] {timeframe_str} EMA20 이탈: {stock_code}",
                    candle_close=candle.close,
                    ema20=int(ema20),
                )

                await self._execute_sell_order(
                    stock_code,
                    ExitReason.TREND_BREAK,
                    f"{timeframe_str} EMA20 이탈 (종가 {candle.close:,} < EMA20 {int(ema20):,})"
                )
                return True

            return False

        except Exception as e:
            self._logger.warning(f"EMA20 이탈 체크 에러: {stock_code} - {e}")
            return False

    # M-1 리팩토링: _execute_partial_sell_order 삭제됨
    # 분할 매도 로직은 ExitManager.execute_partial_sell()에서 처리

    async def _execute_sell_order(
        self,
        stock_code: str,
        exit_reason: ExitReason,
        message: str,
    ) -> None:
        """
        매도 주문 실행 (ExitManager 위임)

        M-1 리팩토링: 중복 코드 제거
        - 실제 매도 로직은 ExitManager.execute_full_sell()에서 처리
        - TradingEngine은 얇은 래퍼 역할만 수행
        - 공유 Lock과 pending_sell_orders로 Race Condition 방지

        V7.1: Circuit Breaker 연동
        - 매도 실패 시 ExitCoordinator.block_exit() 호출
        - 10분간 해당 종목 청산 재시도 방지
        """
        success = await self._exit_manager.execute_full_sell(stock_code, exit_reason, message)

        # V7.1: 매도 실패 시 Circuit Breaker 활성화
        if not success and self._exit_coordinator:
            self._exit_coordinator.block_exit(stock_code)
            self._logger.warning(
                f"[V7.1] 매도 실패 → Circuit Breaker 활성화: {stock_code} | "
                f"10분간 재시도 중단"
            )

    # Phase 4-C: _restore_positions_from_db, _reconcile_with_api_balance,
    # _initialize_trailing_stops_after_recovery, _init_ts_fallback,
    # _init_trailing_stop_for_recovered_partial
    # → PositionRecoveryManager

    async def _sync_positions(self) -> None:
        """
        API와 포지션 동기화 (PRD v2.0: HTS 매매 감지)

        Phase 3: PositionSyncManager에 위임

        - HTS 매수 감지: 로컬에 없지만 API에 있음 → 포지션 등록 + 알림
        - HTS 매도 감지: 로컬에 있지만 API에 없음 → 포지션 청산 + 알림
        - 수량 변동 감지: 수량이 다르면 동기화
        """
        try:
            # API 잔고 조회
            summary = await self._account_api.get_positions()

            # PositionInfo 목록으로 변환
            api_positions = [
                PositionInfo(
                    stock_code=pos.stock_code,
                    stock_name=pos.stock_name,
                    quantity=pos.quantity,
                    average_price=pos.average_price,
                )
                for pos in summary.positions
                if pos.stock_code
            ]

            # [BugFix] API 조회 실패 vs 실제 청산 구분
            # API 에러(502 등)로 빈 결과가 반환되면 로컬 포지션이 "HTS 매도 감지"로 오판됨
            # 연속 N번 빈 리스트면 실제 청산으로 판단 (HTS 수동 매도 대응)
            local_position_count = len(self._position_manager.get_all_positions())
            if not api_positions and local_position_count > 0:
                self._empty_api_position_count += 1

                if self._empty_api_position_count < self._EMPTY_API_THRESHOLD:
                    self._logger.warning(
                        f"[포지션 동기화] API 빈 리스트 ({self._empty_api_position_count}/{self._EMPTY_API_THRESHOLD}) - "
                        f"로컬 포지션 {local_position_count}개 유지 (API 에러 의심)"
                    )
                    return
                else:
                    # 연속 N번 빈 리스트 → 실제 청산으로 판단
                    self._logger.info(
                        f"[포지션 동기화] API 빈 리스트 {self._empty_api_position_count}회 연속 → "
                        f"실제 청산으로 판단 (로컬 포지션 {local_position_count}개 정리)"
                    )
                    # 카운터 리셋하고 동기화 진행
                    self._empty_api_position_count = 0
            else:
                # API가 포지션을 반환하거나, 로컬 포지션이 없으면 카운터 리셋
                self._empty_api_position_count = 0

            # PositionSyncManager에 위임
            callbacks = self._build_sync_callbacks()
            result = await self._position_sync_manager.sync_positions(
                api_positions, callbacks
            )

            if result.errors:
                for error in result.errors:
                    self._logger.warning(f"[포지션 동기화] 오류: {error}")

            self._logger.debug(
                f"포지션 동기화 완료: 신규={result.new_positions}, "
                f"청산={result.closed_positions}, 수량변동={result.quantity_changes}"
            )

        except Exception as e:
            self._logger.error(f"포지션 동기화 실패: {e}")

    async def _verify_tier1_consistency(self) -> int:
        """
        V6.2-J: 포지션과 Tier 1 등록 일관성 검증

        Phase 3: PositionSyncManager에 위임

        PositionManager에 있는 모든 포지션이 Tier 1에 등록되어 있는지 확인하고,
        미등록된 포지션은 즉시 Tier 1에 등록합니다.

        Returns:
            복구된 종목 수
        """
        callbacks = self._build_sync_callbacks()
        return await self._position_sync_manager.verify_tier1_consistency(callbacks)

    # =========================================
    # 콜백
    # =========================================

    async def _on_position_opened(self, position: Position) -> None:
        """포지션 오픈 콜백"""
        # 캔들 빌더 추가
        self._candle_manager.add_stock(position.stock_code)

        # DataManager에 Tier 1로 승격 (고속 폴링)
        # PRD v3.3: async로 변경되어 await 필요
        await self._data_manager.promote_to_tier1(position.stock_code)
        self._logger.info(f"포지션 오픈 → Tier 1 승격: {position.stock_code}")

        # Phase 3-3: 포지션-전략 매핑 등록 (ExitCoordinator + StrategyOrchestrator)
        strategy_name = position.strategy.value if position.strategy else "V6_SNIPER_TRAP"
        # StrategyType enum → ExitCoordinator strategy name 변환
        if strategy_name == "PURPLE_REABS":
            strategy_name = "V7_PURPLE_REABS"
        elif strategy_name == "SNIPER_TRAP":
            strategy_name = "V6_SNIPER_TRAP"
        self._exit_coordinator.register_position_strategy(position.stock_code, strategy_name)
        if self._strategy_orchestrator:
            self._strategy_orchestrator.register_position_strategy(position.stock_code, strategy_name)

        # signal_metadata에서 매수 근거 추출
        reason = position.signal_metadata.get("reason", "")

        # 텔레그램 알림
        await self._telegram.send_message(format_buy_notification(
            stock_code=position.stock_code,
            stock_name=position.stock_name,
            quantity=position.quantity,
            price=position.entry_price,
            amount=position.invested_amount,
            strategy=position.strategy.value,
            reason=reason,
        ))

    async def _on_position_closed(self, position: Position) -> None:
        """포지션 청산 콜백"""
        stock_code = position.stock_code

        # V7.0: Exit State 정리 (cleanup_v7_state 내부에서 position_strategies 매핑도 해제)
        self._cleanup_v7_state(stock_code)
        if self._strategy_orchestrator:
            self._strategy_orchestrator.unregister_position_strategy(stock_code)

        # DataManager Tier 관리
        if self._universe.is_in_universe(stock_code):
            # 유니버스에 있으면 Tier 2로 강등 (계속 모니터링)
            self._data_manager.demote_to_tier2(stock_code)
            self._logger.info(f"포지션 청산 → Tier 2 강등: {stock_code}")
        else:
            # 유니버스에 없으면 완전 해제
            self._data_manager.unregister_stock(stock_code)
            self._logger.info(f"포지션 청산 → 모니터링 해제: {stock_code}")

        # 텔레그램 알림
        await self._telegram.send_message(format_sell_notification(
            stock_code=stock_code,
            stock_name=position.stock_name,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=position.exit_price,
            pnl=position.profit_loss,
            pnl_rate=position.profit_loss_rate,
            reason=position.exit_reason,
        ))

    async def _on_active_pool_changed(
        self,
        promoted: Set[str],
        demoted: Set[str]
    ) -> None:
        """
        V6.2-R: Active Pool 변경 콜백 - 병렬 Tier 승격/강등 처리

        Active Pool에 진입한 종목은 Tier 1로 승격 (고속 폴링 시작)
        Active Pool에서 제외된 종목은 Tier 2로 강등 (폴링 중단)

        병렬화:
        - 승격 대상 수집 후 load_candles_batch()로 병렬 캔들 로딩
        - 강등은 순차 처리 (가벼운 작업)

        Args:
            promoted: Active Pool에 새로 진입한 종목코드들
            demoted: Active Pool에서 제외된 종목코드들
        """
        # === 승격 대상 수집 (캔들 로딩 없이 Tier 1 등록만) ===
        codes_to_load = []
        for stock_code in promoted:
            try:
                # 이미 Tier 1이면 스킵
                if self._data_manager.is_tier1(stock_code):
                    continue

                # 종목명 조회
                stock_name = ""
                if self._auto_screener.is_candidate(stock_code):
                    candidate = self._auto_screener._candidate_pool.get(stock_code)
                    if candidate:
                        stock_name = candidate.stock_name

                if not stock_name:
                    stock_name = stock_code

                # Tier 1 등록 (캔들 로딩 없이)
                self._data_manager.register_stock(stock_code, Tier.TIER_1, stock_name)
                codes_to_load.append(stock_code)
                self._logger.info(
                    f"[V6.2-R] Active Pool 진입 → Tier 1 등록: {stock_name}({stock_code})"
                )
            except Exception as e:
                self._logger.error(f"[V6.2-R] Tier 1 등록 실패: {stock_code} - {e}")

        # === 병렬 캔들 로딩 ===
        if codes_to_load:
            results = await self._data_manager.load_candles_batch(codes_to_load)
            success = sum(1 for v in results.values() if v)
            self._logger.info(
                f"[V6.2-R 병렬 승격] 캔들 로드 완료: {success}/{len(codes_to_load)}개"
            )

        # === 강등 처리 (순차 - 가벼운 작업) ===
        for stock_code in demoted:
            try:
                # 1. 포지션 보유 중이면 Tier 1 유지
                if self._position_manager.has_position(stock_code):
                    self._logger.debug(
                        f"[V6.2-R] Active 강등 스킵 (포지션 보유): {stock_code}"
                    )
                    continue

                # 2. V7 Exit State 있으면 Tier 1 유지 (HTS 매수 포함)
                # Phase 3-1: orchestrator에서 position_strategies 매핑 확인
                has_exit_state = (
                    self._strategy_orchestrator.get_strategy_for_stock(stock_code) is not None
                    or self._exit_coordinator.has_v7_state(stock_code)
                ) if self._strategy_orchestrator else False
                if has_exit_state:
                    self._logger.debug(
                        f"[V6.2-R] Active 강등 스킵 (Exit State): {stock_code}"
                    )
                    continue

                # 3. Tier 2로 강등
                self._data_manager.demote_to_tier2(stock_code)
                self._logger.info(f"[V6.2-R] Active Pool 이탈 → Tier 2 강등: {stock_code}")
            except Exception as e:
                self._logger.error(f"[V6.2-R] Tier 2 강등 실패: {stock_code} - {e}")

        if promoted or demoted:
            self._logger.info(
                f"[V6.2-R] Tier 변경 완료: 승격 {len(promoted)}개, 강등 {len(demoted)}개 | "
                f"Tier1={self._data_manager.tier1_count}개"
            )

    # Phase 4-B: 백그라운드 태스크 → BackgroundTaskManager.start_all()
    # Phase 4-D: _market_watcher_loop → MarketMonitor.market_watcher_loop()

    async def _get_kosdaq_index(self) -> float:
        """
        KOSDAQ 지수 조회 (PRD v3.0)

        Returns:
            KOSDAQ 지수 (실패 시 0)
        """
        try:
            # KOSDAQ 종합 지수 코드: 101 (코스피: 001)
            result = await self._market_api.get_index_price("101")
            if result.success:
                return float(result.data.get("bstp_nmix_prpr", 0))
            return 0
        except Exception as e:
            self._logger.debug(f"KOSDAQ 지수 조회 실패: {e}")
            return 0

    # =========================================
    # 시세 폴링 (REST API)
    # =========================================

    # =========================================
    # RealTimeDataManager 콜백
    # =========================================

    async def _on_market_data(self, price_data: PriceData) -> None:
        """
        RealTimeDataManager로부터 시세 수신

        Args:
            price_data: 시세 데이터
        """
        # PRD v3.0: 장 시작 갭 대응 체크 (09:00:00~09:00:10)
        await self._check_and_handle_market_open()

        code = price_data.stock_code
        self._stats["ticks_received"] += 1

        # 100회마다 수신 현황 로깅
        if self._stats["ticks_received"] % 100 == 1:
            self._logger.info(
                f"[시세수신 #{self._stats['ticks_received']}] "
                f"{code} {price_data.stock_name}: {price_data.current_price:,}원"
            )

        # 1. CandleBuilder 업데이트 (신호 탐지용)
        tick = Tick(
            stock_code=code,
            price=price_data.current_price,
            volume=price_data.volume,
            timestamp=price_data.timestamp,
        )
        await self.on_tick(tick)

        # 2. 포지션 현재가 업데이트 및 손절/익절 체크
        has_position = self._position_manager.has_position(code)
        has_v7_state = self._exit_coordinator and self._exit_coordinator.has_v7_state(code)

        if has_position:
            self._position_manager.update_price(code, price_data.current_price)
            await self._check_position_exit(code, price_data.current_price)
        elif has_v7_state:
            # [Critical] Fallback 손절 체크: V7 State는 있지만 PositionManager에 없는 경우
            # (HTS 매수 후 API 동기화 지연 시 발생 가능)
            await self._fallback_hard_stop_check(code, price_data.current_price)

    async def _on_historical_candles(
        self,
        stock_code: str,
        candles_1m: List[MinuteCandle],
        candles_3m: List[MinuteCandle],
    ) -> None:
        """
        Tier 1 승격 시 과거 분봉 데이터 수신 콜백

        RealTimeDataManager가 promote_to_tier1() 시 ka10080 API로 조회한
        과거 분봉을 CandleBuilder에 주입합니다.

        Args:
            stock_code: 종목코드
            candles_1m: 1분봉 리스트 (MinuteCandle)
            candles_3m: 3분봉 리스트 (MinuteCandle)
        """
        # CandleBuilder 가져오기 (없으면 생성)
        builder = self._candle_manager.get_builder(stock_code)
        if builder is None:
            builder = self._candle_manager.add_stock(stock_code)

        # MinuteCandle → Candle 변환 후 주입 (1분봉)
        candles_1m_converted: List[Candle] = []
        for mc in candles_1m:
            candle = Candle(
                stock_code=stock_code,
                timeframe=Timeframe.M1,
                time=mc.timestamp,
                open=mc.open_price,
                high=mc.high_price,
                low=mc.low_price,
                close=mc.close_price,
                volume=mc.volume,
                is_complete=True,
            )
            candles_1m_converted.append(candle)

        count_1m = builder.load_historical_candles(candles_1m_converted, Timeframe.M1)

        # MinuteCandle → Candle 변환 후 주입 (3분봉)
        candles_3m_converted: List[Candle] = []
        for mc in candles_3m:
            candle = Candle(
                stock_code=stock_code,
                timeframe=Timeframe.M3,
                time=mc.timestamp,
                open=mc.open_price,
                high=mc.high_price,
                low=mc.low_price,
                close=mc.close_price,
                volume=mc.volume,
                is_complete=True,
            )
            candles_3m_converted.append(candle)

        count_3m = builder.load_historical_candles(candles_3m_converted, Timeframe.M3)

        self._logger.info(
            f"[과거 캔들 로드 완료] {stock_code}: "
            f"1m={count_1m}개, 3m={count_3m}개 추가 "
            f"(총 1m={builder.get_candle_count(Timeframe.M1)}개, "
            f"3m={builder.get_candle_count(Timeframe.M3)}개)"
        )

    # =========================================
    # 상태 조회
    # =========================================

    @property
    def state(self) -> EngineState:
        """엔진 상태"""
        return self._state

    @property
    def is_running(self) -> bool:
        """실행 중 여부"""
        return self._state == EngineState.RUNNING

    def get_stats(self) -> dict:
        """통계"""
        return {
            **self._stats,
            "state": self._state.value,
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds()
            if self._start_time
            else 0,
            "universe_count": self._universe.count,
            "position_count": self._position_manager.get_position_count(),
            "daily_pnl": self._risk_manager.get_daily_pnl(),
        }

    def get_status_text(self) -> str:
        """상태 텍스트 (V7 Purple-ReAbs)"""
        stats = self.get_stats()

        # 시장 상태
        market_state = self._market_schedule.get_state() if self._market_schedule else None
        market_status = market_state.value if market_state else "UNKNOWN"

        # WebSocket 상태
        ws_status = "ON" if self._websocket and self._websocket.is_connected else "OFF"

        # V7 SignalPool 현황
        pool_total = 0
        signaled = 0
        total_signals = 0
        pending_candidates = 0

        if self._strategy_orchestrator:
            # Phase 3-1: StrategyOrchestrator에서 V7 상태 조회
            v7_strategy = self._strategy_orchestrator.get_base_strategy("V7_PURPLE_REABS")
            if v7_strategy:
                v7_status = v7_strategy.get_status()
                pool_total = v7_status.get("signal_pool_size", 0)
                # SignalPool 상세 stats 조회
                if hasattr(v7_strategy, '_signal_pool') and v7_strategy._signal_pool is not None:
                    pool_stats = v7_strategy._signal_pool.get_stats()
                    signaled = pool_stats.get("signaled", 0)
                    total_signals = pool_stats.get("total_signals", 0)
                if hasattr(v7_strategy, '_dual_pass') and v7_strategy._dual_pass:
                    dual_stats = v7_strategy._dual_pass.get_stats()
                    pending_candidates = dual_stats.get("pending_candidates", 0)

        # 데이터 모니터링 (Tier)
        tier1 = self._data_manager.tier1_count if self._data_manager else 0
        tier2 = self._data_manager.tier2_count if self._data_manager else 0

        return (
            f"[시스템 상태]\n"
            f"엔진: {stats['state']}\n"
            f"시장: {market_status}\n"
            f"웹소켓: {ws_status} / 가동: {int(stats['uptime_seconds'] // 60)}분\n"
            f"\n"
            f"[V7 SignalPool]\n"
            f"Pool: {pool_total}개 / 신호: {signaled}개 / 누적: {total_signals}회\n"
            f"Pre-Check: {pending_candidates}개\n"
            f"\n"
            f"[데이터 모니터링]\n"
            f"포지션: {stats['position_count']}개\n"
            f"Tier1(실시간): {tier1}개 / Tier2(폴링): {tier2}개\n"
            f"\n"
            f"[거래 통계]\n"
            f"탐지: {stats['signals_detected']} / 차단: {stats['signals_blocked']}\n"
            f"큐: {stats.get('signals_queued', 0)} / 체결: {stats['orders_placed']}회"
        )

    # =========================================
    # Phase 6D: ManualCommandHandler 위임
    # =========================================

    async def add_manual_stock(self, stock_code: str, mode: str = "auto") -> tuple:
        """수동 종목 추가 (ManualCommandHandler 위임)"""
        return await self._manual_handler.add_manual_stock(stock_code, mode)

    async def remove_manual_stock(self, stock_code: str, force: bool = False) -> tuple:
        """종목 제거 (ManualCommandHandler 위임)"""
        return await self._manual_handler.remove_manual_stock(stock_code, force)

    def get_watched_stocks_text(self, filter_type: str = "all") -> str:
        """감시 종목 목록 텍스트 (ManualCommandHandler 위임)"""
        return self._manual_handler.get_watched_stocks_text(filter_type)

    async def execute_manual_buy(self, stock_code: str, amount: int) -> tuple:
        """수동 매수 실행 (ManualCommandHandler 위임)"""
        return await self._manual_handler.execute_manual_buy(stock_code, amount)

    async def execute_manual_sell(self, stock_code: str, quantity: int) -> tuple:
        """수동 매도 실행 (ManualCommandHandler 위임)"""
        return await self._manual_handler.execute_manual_sell(stock_code, quantity)

    async def update_stop_loss(self, stock_code: str, rate: float) -> tuple:
        """손절가 변경 (ManualCommandHandler 위임)"""
        return await self._manual_handler.update_stop_loss(stock_code, rate)

    async def update_take_profit(self, stock_code: str, rate: float) -> tuple:
        """익절가 변경 (ManualCommandHandler 위임)"""
        return await self._manual_handler.update_take_profit(stock_code, rate)

    async def update_stock_mode(self, stock_code: str, mode: str) -> tuple:
        """종목 모드 변경 (ManualCommandHandler 위임)"""
        return await self._manual_handler.update_stock_mode(stock_code, mode)

    def get_stock_mode(self, stock_code: str) -> StockMode:
        """종목의 현재 모드 반환 (ManualCommandHandler 위임)"""
        return self._manual_handler.get_stock_mode(stock_code)

    def add_ignore_stock(self, stock_code: str) -> bool:
        """ignore 목록에 종목 추가 (ManualCommandHandler 위임)"""
        return self._manual_handler.add_ignore_stock(stock_code)

    def remove_ignore_stock(self, stock_code: str) -> bool:
        """ignore 목록에서 종목 제거 (ManualCommandHandler 위임)"""
        return self._manual_handler.remove_ignore_stock(stock_code)

    # NOTE: 다음 메서드들은 V7SignalCoordinator로 이동됨:
    # - _v7_dual_pass_loop
    # - _v7_run_pre_check
    # - _v7_run_confirm_check
    # - _v7_send_purple_signal
    # - _v7_notification_loop
    # V7SignalCoordinator는 _build_v7_callbacks()을 통해 이 기능들을 처리합니다.
