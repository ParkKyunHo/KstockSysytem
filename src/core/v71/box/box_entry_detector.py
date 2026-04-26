"""V71BoxEntryDetector -- bar-completion entry checks.

Spec:
  - 02_TRADING_RULES.md §3.8~§3.11 (entry conditions)
  - 02_TRADING_RULES.md §4 (buy execution)
  - 04_ARCHITECTURE.md §5.3

Phase: P3.1 (signatures only) / P3.2 (body wiring)

Boundary in P3.1:
    The detector's job is just to *route* completed candles to the box-entry
    skill and dispatch positive decisions to OrderExecutor. Entry condition
    logic lives in :mod:`src.core.v71.skills.box_entry_skill`. Anything that
    re-derives "is this a bullish bar inside the box?" outside the skill is
    a bug -- Harness 3 will eventually pin this.

P3.2 will:
    - subscribe to CandleManager bar-complete events
    - hydrate Box (box_entry_skill.Box) from BoxRecord (box_manager.BoxRecord)
    - call evaluate_box_entry() and dispatch via on_entry callback
    - propagate fallback_buy_at to OrderExecutor for the 09:05 safety net
      (§3.10/§3.11/§10.9)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from src.core.v71.box.box_manager import V71BoxManager
from src.core.v71.skills.box_entry_skill import EntryDecision
from src.utils.feature_flags import require_enabled

# Callback shape: detector -> buy executor (P3.2).
# The decision carries everything the executor needs, including PATH_B
# fallback metadata (fallback_buy_at, fallback_uses_market_order).
OnEntryCallback = Callable[[EntryDecision], None]


class CandleSource(Protocol):
    """Minimal interface the detector requires from CandleManager.

    Concrete implementation lives in V7.0 ``src.core.candle_builder``;
    keeping a Protocol here lets unit tests fake it without pulling the
    real subscription manager.
    """

    def subscribe_bar_complete(self, callback: Callable[[object], None]) -> None: ...


class V71BoxEntryDetector:
    """Subscribes to candle-completion events and runs box-entry checks
    via :func:`box_entry_skill.evaluate_box_entry`.

    Responsibilities (P3.2 -- body lands then):
      - register a bar-complete callback with the CandleSource
      - on each completed candle, look up active WAITING boxes for that
        ``(stock_code, path_type)`` from V71BoxManager
      - call :func:`evaluate_box_entry` -- never re-derives conditions
      - on a positive :class:`EntryDecision`, invoke ``on_entry`` so
        OrderExecutor (P3.2) can place the buy. PATH_B decisions carry
        ``fallback_buy_at`` so the executor can schedule the 09:05
        safety-net retry.

    P3.1 leaves the body unimplemented; the import surface is fixed so
    P3.2 can wire callers without further signature churn.
    """

    def __init__(
        self,
        *,
        candle_source: CandleSource,
        box_manager: V71BoxManager,
        on_entry: OnEntryCallback,
    ) -> None:
        require_enabled("v71.box_system")
        self._candle_source = candle_source
        self._box_manager = box_manager
        self._on_entry = on_entry

    def start(self) -> None:
        """Register the bar-complete callback with the source.

        Implementation in P3.2.
        """
        raise NotImplementedError("P3.2 -- see docs/v71/02_TRADING_RULES.md §4")

    def check_entry(self, completed_candle: object) -> None:
        """Evaluate every active WAITING box for the candle's stock+path.

        Implementation in P3.2. Must call
        :func:`box_entry_skill.evaluate_box_entry` for each candidate box;
        no in-place condition logic is allowed here.
        """
        raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §2")


__all__ = [
    "CandleSource",
    "OnEntryCallback",
    "V71BoxEntryDetector",
]
