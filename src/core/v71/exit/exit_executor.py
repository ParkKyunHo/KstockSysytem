"""V71ExitExecutor -- order placement for stop / partial / TS exits.

Spec: docs/v71/02_TRADING_RULES.md §5.6, §5.7
Implementation: P3.3
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71ExitExecutor:
    """Translates exit decisions into Kiwoom orders via kiwoom_api_skill.

    Order policy: limit at 1-tick below for partial profits, market
    fallback after 3 retries. Stop-loss exits go straight to market on
    breach.
    """

    def __init__(self) -> None:
        require_enabled("v71.exit_v71")
        raise NotImplementedError("P3.3 -- see docs/v71/02_TRADING_RULES.md §5.6")
