"""V71ViMonitor -- VI event subscription + state machine driver.

Spec: docs/v71/02_TRADING_RULES.md §10
Implementation: P3.6
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71ViMonitor:
    """Subscribes to Kiwoom VI events (TRIGGERED/RESUMED) and drives
    vi_skill.handle_vi_state().

    Side effects on state transitions:
      - TRIGGERED: pause stop checks for the stock; cancel in-flight
        non-VI buy orders; allow single-price-auction participation
      - RESUMED: re-evaluate within 1s; market-sell on breached stop;
        set tracked_stocks.vi_recovered_today = TRUE for the rest of day
    """

    def __init__(self, websocket_manager: object, db_context: object) -> None:
        require_enabled("v71.vi_monitor")
        raise NotImplementedError("P3.6 -- see docs/v71/02_TRADING_RULES.md §10")
