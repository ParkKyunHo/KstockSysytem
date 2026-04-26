"""Per-position mutable state for V7.1 exit logic.

Spec:
  - 02_TRADING_RULES.md §5  (post-buy management)
  - 02_TRADING_RULES.md §6  (average-price management)
  - 03_DATA_MODEL.md §2.3   (positions table)

Phase: P3.3 (in-memory) / P3.4 (DB-backed via V71PositionManager)

This module owns the `PositionState` dataclass that V71BuyExecutor
populates and V71ExitCalculator / V71ExitExecutor mutate. Keeping it
separate from the ``positions`` table model lets P3.3 ship without
the DB layer; P3.4 will hydrate / persist this struct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PositionState:
    """Mutable position state used by exit pipeline (§5).

    Fields mirror the future ``positions`` row but stay Python-only for
    P3.3 testability.
    """

    position_id: str
    stock_code: str
    tracked_stock_id: str
    triggered_box_id: str
    path_type: str  # "PATH_A" | "PATH_B" | "MANUAL"

    # Average-price state (§6).
    weighted_avg_price: int
    initial_avg_price: int
    total_quantity: int

    # Stop ladder (§5.1, §5.4).
    fixed_stop_price: int

    # Partial profit-take flags (§5.2 / §5.3).
    profit_5_executed: bool = False
    profit_10_executed: bool = False

    # Trailing stop bookkeeping (§5.5).
    ts_activated: bool = False
    ts_base_price: int | None = None
    ts_stop_price: int | None = None
    ts_active_multiplier: float | None = None

    # Lifecycle.
    status: str = "OPEN"  # "OPEN" | "PARTIAL_CLOSED" | "CLOSED"
    opened_at: datetime | None = None
    closed_at: datetime | None = None


__all__ = ["PositionState"]
