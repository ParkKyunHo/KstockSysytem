"""Tick + Candle frozen dataclass + WebSocket → Tick adapter.

Spec:
  - 02_TRADING_RULES.md §4 / §7
  - 04_ARCHITECTURE.md §5.3

Replaces V7.0 ``src.core.candle_builder.Tick`` + ``Candle`` with
immutable V7.1 versions. Frozen dataclass = no in-place mutation =
threading + audit trail safe (architect Q3/Q4 decision).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.core.v71.v71_constants import V71Timeframe

log = logging.getLogger(__name__)


# Common 0B (체결) WebSocket payload aliases. Mirrors
# src/core/v71/strategies/exit_orchestrator._PRICE_TICK_KEYS so both
# the ExitOrchestrator and the candle builder pull the same field
# regardless of wire-level naming variants.
_PRICE_KEYS = ("10", "stck_prpr", "cur_prc", "current_price", "cntr_pric")
_VOLUME_KEYS = ("15", "trde_qty", "volume", "cntr_qty")
_SIDE_KEYS = ("12", "tp", "side")  # Kiwoom 12 = "+" (buy) / "-" (sell)


@dataclass(frozen=True)
class V71Tick:
    """Single trade tick (체결).

    Immutable so a tick once recorded cannot be mutated later -- protects
    audit trail + thread safety. ``timestamp`` is UTC.
    """

    stock_code: str
    timestamp: datetime
    price: int
    volume: int
    side: str  # "BUY" | "SELL" | "" (unknown)


@dataclass(frozen=True)
class V71Candle:
    """OHLCV candle (3분봉 또는 일봉).

    ``timeframe`` field disambiguates downstream consumers. ``tick_count``
    is included for debugging / volume sanity checks (architect Q4).
    """

    stock_code: str
    timeframe: V71Timeframe
    timestamp: datetime  # candle bucket start, UTC
    open: int
    high: int
    low: int
    close: int
    volume: int
    tick_count: int = 0


def _coerce_int(raw: Any) -> int:
    """Robust kiwoom 0-padded numeric → int. Negatives clamped to 0
    (mirror trading_bridge._coerce_int)."""
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip().lstrip("0") or "0")
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def message_to_tick(message: Any) -> V71Tick | None:
    """Convert a V71KiwoomWebSocket PRICE_TICK message into a
    :class:`V71Tick`.

    Returns ``None`` (with WARNING) when the payload is missing the
    minimum fields (stock_code + price). Never raises -- handler
    isolation policy (헌법 §4 항상 운영).
    """
    try:
        stock_code = (getattr(message, "item", "") or "").strip().upper()
        if not stock_code:
            log.warning("v71_message_to_tick: empty stock_code")
            return None
        values = getattr(message, "values", None) or {}
        if not isinstance(values, dict):
            log.warning(
                "v71_message_to_tick: values not dict (got %s) for %s",
                type(values).__name__, stock_code,
            )
            return None
        price_raw = next(
            (values[k] for k in _PRICE_KEYS if k in values), None,
        )
        if price_raw is None:
            log.warning(
                "v71_message_to_tick: price field missing for %s "
                "(tried %s)",
                stock_code, _PRICE_KEYS,
            )
            return None
        price = _coerce_int(price_raw)
        if price <= 0:
            log.warning(
                "v71_message_to_tick: price <= 0 for %s",
                stock_code,
            )
            return None
        volume = _coerce_int(
            next((values[k] for k in _VOLUME_KEYS if k in values), 0),
        )
        side_raw = str(
            next((values[k] for k in _SIDE_KEYS if k in values), ""),
        ).strip()
        side = "BUY" if side_raw.startswith("+") else (
            "SELL" if side_raw.startswith("-") else ""
        )
        timestamp = (
            getattr(message, "received_at", None)
            or datetime.now(timezone.utc)
        )
        return V71Tick(
            stock_code=stock_code,
            timestamp=timestamp,
            price=price,
            volume=volume,
            side=side,
        )
    except BaseException:  # noqa: BLE001 -- handler must not raise
        log.exception("v71_message_to_tick: unexpected exception")
        return None


__all__ = ["V71Candle", "V71Tick", "message_to_tick"]
