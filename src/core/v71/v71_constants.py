"""V7.1 거래 룰 상수 (단일 진실 원천).

Source of truth: ``docs/v71/02_TRADING_RULES.md`` and
``docs/v71/01_PRD_MAIN.md`` Appendix C.

All V7.1 trading code MUST import from this module instead of writing
literal numbers (Harness 3 enforces). Changes here require PRD update +
user approval.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class V71Constants:
    """All numbers that govern V7.1 trading behavior.

    Grouped by 02_TRADING_RULES.md section. Edit here only after the
    corresponding PRD section is updated.
    """

    # ---- §5 Stop ladder (one-way upward) ----
    STOP_LOSS_INITIAL_PCT: Final[float] = -0.05
    """Stage 1 -- entry through < +5%."""

    STOP_LOSS_AFTER_PROFIT_5: Final[float] = -0.02
    """Stage 2 -- after +5% partial exit."""

    STOP_LOSS_AFTER_PROFIT_10: Final[float] = 0.04
    """Stage 3 -- after +10% partial exit (break-even guarantee)."""

    # ---- §5 Partial take-profit ----
    PROFIT_TAKE_LEVEL_1: Final[float] = 0.05
    """+5% threshold -> 1st partial exit."""

    PROFIT_TAKE_LEVEL_2: Final[float] = 0.10
    """+10% threshold -> 2nd partial exit."""

    PROFIT_TAKE_RATIO: Final[float] = 0.30
    """Slice 30% of remaining quantity at each level."""

    # ---- §5 Trailing stop ----
    TS_ACTIVATION_LEVEL: Final[float] = 0.05
    """+5% activates TS (BasePrice = post-buy high)."""

    TS_VALID_LEVEL: Final[float] = 0.10
    """TS exit line becomes binding only after +10% partial exit."""

    # ---- §5 ATR multiplier ladder (one-way tightening) ----
    ATR_MULTIPLIER_TIER_1: Final[float] = 4.0  # +10~15%
    ATR_MULTIPLIER_TIER_2: Final[float] = 3.0  # +15~25%
    ATR_MULTIPLIER_TIER_3: Final[float] = 2.5  # +25~40%
    ATR_MULTIPLIER_TIER_4: Final[float] = 2.0  # +40%~

    ATR_TIER_THRESHOLDS: Final[tuple[float, ...]] = (0.10, 0.15, 0.25, 0.40)
    """Profit thresholds (inclusive lower bound) for each ATR tier."""

    ATR_PERIOD: Final[int] = 10
    """ATR window length (bars)."""

    BASE_PRICE_LOOKBACK: Final[int] = 20
    """High lookback for TS BasePrice."""

    # ---- §3 Box system ----
    MAX_POSITION_PCT_PER_STOCK: Final[float] = 30.0
    """Per-stock cap as % of total capital."""

    AUTO_EXIT_BOX_DROP_PCT: Final[float] = -0.20
    """Tracking ends when price falls -20% below box."""

    BOX_EXPIRY_REMINDER_DAYS: Final[int] = 30
    """Notify after 30 days without trigger; never auto-delete."""

    # ---- §4 Buy execution ----
    ORDER_RETRY_COUNT: Final[int] = 3
    """Limit-order attempts before market-order fallback."""

    ORDER_WAIT_SECONDS: Final[int] = 5
    """Wait between limit-order attempts."""

    # ---- §10 VI / gap handling ----
    PATH_B_GAP_UP_LIMIT: Final[float] = 0.05
    """Skip PATH_B buy when next-day open gaps up >= 5%."""

    VI_GAP_LIMIT: Final[float] = 0.03
    """Skip post-VI buy when gap >= 3%."""

    # ---- System ----
    REST_POLLING_INTERVAL_SECONDS: Final[int] = 5
    """Default REST polling cadence."""

    NOTIFICATION_RATE_LIMIT_MINUTES: Final[int] = 5
    """Per-stock notification cooldown (CRITICAL severity bypasses).

    See 02_TRADING_RULES.md §9.5.
    """

    # ---- §9 Notification Circuit Breaker (P4.1) ----
    NOTIFICATION_CIRCUIT_BREAKER_FAILURE_THRESHOLD: Final[int] = 3
    """3 consecutive failures -> Circuit OPEN (02_TRADING_RULES.md §9.4)."""

    NOTIFICATION_CIRCUIT_BREAKER_TIMEOUT_SECONDS: Final[int] = 30
    """OPEN -> HALF_OPEN after 30s (02_TRADING_RULES.md §9.4)."""

    NOTIFICATION_CRITICAL_RETRY_COUNT: Final[int] = 3
    """CRITICAL send failures retried 3 times (02_TRADING_RULES.md §9.3)."""

    NOTIFICATION_CRITICAL_RETRY_DELAY_SECONDS: Final[int] = 5
    """5-second pause between CRITICAL retries (02_TRADING_RULES.md §9.3)."""

    NOTIFICATION_MEDIUM_LOW_EXPIRY_MINUTES: Final[int] = 5
    """MEDIUM/LOW notifications discarded after 5 minutes if Circuit OPEN
    blocked delivery (02_TRADING_RULES.md §9.4)."""

    NOTIFICATION_WORKER_INTERVAL_SECONDS: Final[float] = 0.5
    """Worker dequeue cadence -- balance latency vs DB load."""

    # ---- §13 Restart recovery ----
    RESTART_FREQUENCY_WARN_WINDOW_HOURS: Final[int] = 1
    RESTART_FREQUENCY_WARN_THRESHOLD: Final[int] = 5
    """5+ restarts in 1 hour -> CRITICAL alert."""

    RECOVERY_RECONNECT_MAX_RETRIES: Final[int] = 5
    """§13.1 Step 1 -- each external connection retried up to 5 times."""

    RECOVERY_RECONNECT_RETRY_INTERVAL_SECONDS: Final[float] = 1.0
    """§13.1 Step 1 -- 1-second pause between reconnection attempts."""

    # ---- Strategy paths ----
    PATH_A_TIMEFRAME_MINUTES: Final[int] = 3
    PATH_B_TIMEFRAME_MINUTES: Final[int] = 1440  # daily

    PATH_B_PRIMARY_BUY_TIME_HHMM: Final[str] = "09:01"
    """PATH_B 1st buy attempt at 09:01 the next trading day (limit -> market)."""

    PATH_B_FALLBACK_BUY_TIME_HHMM: Final[str] = "09:05"
    """PATH_B 2nd buy attempt at 09:05 if 1st failed (e.g., opening VI / single-price
    auction misfire / API outage). See 02_TRADING_RULES.md §3.10/§3.11/§10.9."""

    PATH_B_FALLBACK_USES_MARKET_ORDER: Final[bool] = True
    """Fallback uses market order (immediate fill priority over price)."""

    # ---- Kiwoom API (kiwoom_api_skill) ----
    API_MAX_RETRIES: Final[int] = 3
    API_BACKOFF_BASE_SECONDS: Final[float] = 1.0
    """Exponential backoff base: backoff = base * (2 ** attempt)."""

    API_TIMEOUT_SECONDS: Final[int] = 10
    API_RATE_LIMIT_PER_SECOND: Final[float] = 4.5  # production
    API_RATE_LIMIT_PAPER_PER_SECOND: Final[float] = 0.33  # paper trading

    AUTH_ERROR_CODES: Final[tuple[str, ...]] = ("EGW00001", "EGW00002")
    """Token-expired / auth-failed -- triggers refresh + retry."""

    RATE_LIMIT_ERROR_CODES: Final[tuple[str, ...]] = ("EGW00201",)
    """Rate-limited -- triggers exponential backoff."""

    # ---- Kiwoom WebSocket reconnect (02_TRADING_RULES.md §8.2) ----
    WS_PHASE_1_BACKOFF_SECONDS: Final[tuple[float, ...]] = (1.0, 2.0, 4.0, 8.0, 16.0)
    """Phase 1 exponential backoff -- 5 attempts, ~31 s total."""

    WS_PHASE_2_INTERVAL_SECONDS: Final[float] = 300.0
    """Phase 2 fixed interval -- infinite retries every 5 minutes."""

    # ---- Candle / Market schedule (02_TRADING_RULES.md §4 / §7) ----
    CANDLE_THREE_MINUTE_SECONDS: Final[int] = 180
    """3분봉 길이 (PATH_A 기준) -- §4.1 / §4.2."""

    CANDLE_HISTORY_PER_STOCK_MAX: Final[int] = 200
    """종목당 보관 봉 수 한도 (deque maxlen). ATR(10)+EMA(60)에 70봉이
    필요하므로 200봉이면 1회 대응 + 여유. 메모리 한계 50종목 × 200봉
    × ~200byte ≈ 2MB."""

    DAILY_CANDLE_FETCH_HHMM: Final[str] = "15:35"
    """EOD 폴링 시각 (KRX 15:30 정규장 종료 5분 후)."""

    # ---- KRX market schedule (02_TRADING_RULES.md §7 / §10) ----
    MARKET_OPEN_TIME: Final[str] = "09:00"
    """정규장 시작 (KST)."""

    MARKET_CLOSE_TIME: Final[str] = "15:30"
    """정규장 종료 (KST)."""

    SIGNAL_START_TIME: Final[str] = "09:05"
    """진입 신호 탐지 시작 (CLAUDE.md Part 3.5)."""

    # ---- NFR1 query budget (01_PRD_MAIN.md §1 헌법 2) ----
    NFR1_HOT_PATH_BUDGET_SECONDS: Final[float] = 0.1
    """V71BoxManager.list_waiting_for_tracked perf-warn threshold —
    10% of the 1-second NFR1 budget. Slow-path warning is logged when
    a single hot-path query exceeds this."""

    # ---- V71PricePublisher (P-Wire-Price-Tick) sanity (security S2 MEDIUM) ----
    PRICE_TICK_SANITY_MAX: Final[int] = 100_000_000
    """Per-share KRW upper bound. KOSPI 단일 종목 시가 1억원/주 미만 —
    이를 초과하는 PRICE_TICK은 키움 패킷 변조/오류로 판정 reject."""

    PRICE_TICK_JUMP_REJECT_PCT: Final[float] = 0.50
    """직전 받은 가격 대비 ±50% 점프 시 reject. VI 발동 갭과 별개로
    단발 변조 방어. 0.5 = 50% (e.g. 10000 → 15000 또는 5000 거부)."""

    # ---- V71PricePublisher 1Hz batch throttle ----
    PRICE_PUBLISHER_FLUSH_INTERVAL_SECONDS: Final[float] = 1.0
    """1Hz batch UPDATE + publish 간격 (PRD §11.3 명세 그대로).
    20+ active positions 시 운영 측에서 0.5Hz auto-downgrade 가능."""

    PRICE_PUBLISHER_DB_SEMAPHORE: Final[int] = 3
    """동시 DB connection 한도 (Migration M3: pool_size=5+overflow=10=15 한도).
    Semaphore(3)은 V71BuyExecutor + V71Reconciler와 경합 시 marginal headroom 확보."""


class V71Timeframe(str, Enum):
    """V7.1 candle timeframe (V71 prefix per harness 1 + 격리 원칙).

    PRD §4.1/§4.2 = PATH_A 3분봉, §4.3 = PATH_B 일봉. M1 등 다른
    타임프레임은 V7.1에서 사용하지 않음.
    """

    THREE_MINUTE = "3m"
    DAILY = "1d"


__all__ = ["V71Constants", "V71Timeframe"]
