"""V7.1 core package.

V7.1 box-based trading code lives under ``src.core.v71``. The legacy V7.0
re-exports were removed during Phase 1 of the V7.0 -> V7.1 migration.

Surviving V7.0 infrastructure (preserved per Constitution rule 3):
  - ``candle_builder``, ``websocket_manager``, ``market_schedule``
    (referenced by V7.1 modules in Phase 3)

V7.1 entry points (added in later phases):
  - ``src.core.v71.box``
  - ``src.core.v71.strategies``
  - ``src.core.v71.exit``
  - ``src.core.v71.position``
"""
