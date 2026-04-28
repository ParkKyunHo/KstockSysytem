"""V7.1 candle data + builder package.

Spec:
  - 02_TRADING_RULES.md §4.1/§4.2 (PATH_A 3분봉)
  - 02_TRADING_RULES.md §4.3 (PATH_B 일봉)
  - 02_TRADING_RULES.md §7 (폴링 전략)
  - 04_ARCHITECTURE.md §5.3 (P3.1 candle builder)

Replaces V7.0 ``src.core.candle_builder`` with full V7.1 isolation
(Constitution §3 / §1.5 / harness 1 -- V71 prefix on every class).

Sub-modules (Phase A Step A-1 ~ A-4):
  * ``types``                       — V71Tick / V71Candle frozen dataclass (A-1)
  * ``v71_candle_builder``          — V71BaseCandleBuilder Protocol (A-2)
  * ``v71_three_minute_builder``    — PATH_A 3분봉 (A-2)
  * ``v71_daily_builder``           — PATH_B 일봉 + ka10081 (A-3)
  * ``v71_candle_manager``          — 다중 종목 + WS wiring (A-4)
"""

from src.core.v71.candle.types import V71Candle, V71Tick, message_to_tick

__all__ = ["V71Candle", "V71Tick", "message_to_tick"]
