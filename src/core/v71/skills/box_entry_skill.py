"""Skill 2: Box entry condition evaluator.

Spec: docs/v71/07_SKILLS_SPEC.md §2, docs/v71/02_TRADING_RULES.md §3-§4
Constitution: any V7.1 box-entry decision MUST go through
:func:`evaluate_box_entry`. Hand-written if/elif chains over candle data
are forbidden (Harness 3 will pin this when the rule set lands).

Design (P3.1 / P3.2):
  PATH_A pullback:    prev candle bullish AND closes inside box
                      AND current candle bullish AND closes inside box
                      AND not crossing above box.upper
  PATH_A breakout:    close > box.upper AND bullish
                      AND open >= box.lower (excludes gap-ups)
  PATH_B daily:       same logic on daily bars; entry submitted next
                      trading day at 09:01 unless gap >= 5%.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Reuse V7.0 Candle so the codebase keeps a single bar definition
# (Constitution 3 -- preserve V7.0 infrastructure; Harness 1 enforces
# the no-collision rule).
from src.core.candle_builder import Candle


class EntryDecision(Enum):
    NO_ENTRY = "NO_ENTRY"
    PULLBACK = "PULLBACK"
    BREAKOUT = "BREAKOUT"


def is_bullish(candle: Candle) -> bool:
    """V7.0 Candle has no convenience method; provided here for callers."""
    return candle.close > candle.open


@dataclass(frozen=True)
class Box:
    upper_price: int
    lower_price: int
    strategy_type: str  # "PULLBACK" | "BREAKOUT"


@dataclass(frozen=True)
class MarketContext:
    """Side info needed for entry decisions (VI flag, gap, etc.)."""

    vi_recovered_today: bool
    gap_pct_from_prev_close: float | None  # PATH_B only


@dataclass(frozen=True)
class EntryEvaluation:
    decision: EntryDecision
    box_id: str | None
    reason: str
    """Human-readable explanation; logged on every decision."""


def evaluate_box_entry(
    *,
    prev_candle: Candle,
    current_candle: Candle,
    box: Box,
    context: MarketContext,
) -> EntryEvaluation:
    """Single point where box-entry decisions are made (PATH_A and PATH_B).

    All decisions return :class:`EntryEvaluation`. Callers must NOT
    re-derive entry conditions from candle/box fields directly.
    """
    raise NotImplementedError("P3.1 -- see docs/v71/07_SKILLS_SPEC.md §2")


def is_pullback_setup(
    *, prev_candle: Candle, current_candle: Candle, box: Box
) -> bool:
    """Pure helper -- callers should prefer :func:`evaluate_box_entry`."""
    raise NotImplementedError("P3.1 -- see docs/v71/07_SKILLS_SPEC.md §2")


def is_breakout_setup(*, current_candle: Candle, box: Box) -> bool:
    """Pure helper -- callers should prefer :func:`evaluate_box_entry`."""
    raise NotImplementedError("P3.1 -- see docs/v71/07_SKILLS_SPEC.md §2")


__all__ = [
    "EntryDecision",
    "Box",
    "MarketContext",
    "EntryEvaluation",
    "evaluate_box_entry",
    "is_pullback_setup",
    "is_breakout_setup",
    "is_bullish",
]
