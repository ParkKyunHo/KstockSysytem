"""V7.1 trading engine stub.

V7.0 ``TradingEngine`` has been retired during Phase 1 of the V7.0 -> V7.1
migration (``docs/v71/05_MIGRATION_PLAN.md`` §3.9, P1.8). The V7.1
replacement will be assembled in Phase 3 from the V7.1 building blocks
under ``src/core/v71/`` (box system, strategies, exit, reconciler).

This stub exists so that:
  - ``import src.core.trading_engine`` does not raise;
  - mistakenly instantiating the legacy class fails fast with a clear,
    actionable message instead of silently running on stale glue code;
  - the V7.0 module name is preserved as a build target for tooling
    (Harness 1, Harness 2) while V7.1 is under construction.

Last V7.0 implementation is preserved at git tag ``v7.0-final-stable``.
"""

from __future__ import annotations

from dataclasses import dataclass


_RETIRED_MESSAGE = (
    "V7.0 TradingEngine has been retired (Phase 1 / P1.8). "
    "The V7.1 trading engine is built in Phase 3 from src/core/v71/. "
    "See docs/v71/05_MIGRATION_PLAN.md and docs/v71/WORK_LOG.md. "
    "Recover the V7.0 implementation from git tag v7.0-final-stable if "
    "absolutely needed."
)


@dataclass
class EngineConfig:
    """Placeholder so legacy imports surface a clear error at use, not import."""

    def __post_init__(self) -> None:
        raise NotImplementedError(_RETIRED_MESSAGE)


class TradingEngine:
    """Placeholder so legacy imports surface a clear error at use, not import."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(_RETIRED_MESSAGE)


__all__ = ["EngineConfig", "TradingEngine"]
