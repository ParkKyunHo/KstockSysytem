"""V7.1 거래 룰 상수 (단일 진실 원천).

Source of truth: ``docs/v71/02_TRADING_RULES.md`` and
``docs/v71/01_PRD_MAIN.md`` Appendix C.

All V7.1 trading code MUST import from this module instead of writing
literal numbers (Harness 3 enforces). Changes here require PRD update +
user approval.
"""

from __future__ import annotations

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
    """Per-stock notification cooldown (CRITICAL severity bypasses)."""

    # ---- §13 Restart recovery ----
    RESTART_FREQUENCY_WARN_WINDOW_HOURS: Final[int] = 1
    RESTART_FREQUENCY_WARN_THRESHOLD: Final[int] = 5
    """5+ restarts in 1 hour -> CRITICAL alert."""

    # ---- Strategy paths ----
    PATH_A_TIMEFRAME_MINUTES: Final[int] = 3
    PATH_B_TIMEFRAME_MINUTES: Final[int] = 1440  # daily
    PATH_B_BUY_TIME_HHMM: Final[str] = "09:01"
    """PATH_B buy executes at 09:01 the next trading day."""


__all__ = ["V71Constants"]
