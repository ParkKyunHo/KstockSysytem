"""V71RestartRecovery -- 7-step recovery sequence after process restart.

Spec: docs/v71/02_TRADING_RULES.md §13
Implementation: P3.7

Steps:
  0. Enter safe mode (block new buys + box registration)
  1. Reconnect external systems (DB -> Kiwoom OAuth -> WebSocket -> Telegram)
  2. Cancel all incomplete orders (boxes preserved)
  3. Position reconciliation (delegated to V71Reconciler)
  4. Re-subscribe market data
  5. Re-evaluate box entry conditions (option A: missed triggers void)
  6. Release safe mode
  7. Recovery report (CRITICAL telegram)
"""

from __future__ import annotations

from src.utils.feature_flags import require_enabled


class V71RestartRecovery:
    """Single entry point invoked by main on start-up to drive the
    7-step sequence. Records system_restarts row at completion."""

    def __init__(self, db_context: object, kiwoom_context: object) -> None:
        require_enabled("v71.restart_recovery")
        raise NotImplementedError("P3.7 -- see docs/v71/02_TRADING_RULES.md §13")
