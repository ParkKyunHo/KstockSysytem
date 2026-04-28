"""V7.1 market schedule + KRX calendar.

Replaces V7.0 ``src.core.market_schedule`` with a focused V7.1 surface.
The V7.0 module bundled holiday loading + status text + many helpers;
V7.1 keeps only what the trading pipeline actually consumes
(``is_holiday`` + ``is_market_open`` + ``is_trading_day``).

Spec:
  - 02_TRADING_RULES.md §7 (폴링 전략 -- 정규장 09:00-15:30)
  - 02_TRADING_RULES.md §10 (VI 처리 -- 휴장일 / 단축장 처리)
"""

from src.core.v71.market.v71_market_schedule import (
    V71MarketSchedule,
    get_v71_market_schedule,
)

__all__ = ["V71MarketSchedule", "get_v71_market_schedule"]
