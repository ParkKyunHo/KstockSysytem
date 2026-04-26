"""V7.1 Box-Based Trading System (isolation package).

All V7.1 trading code lives under this package per Constitution rule 3
(Coexistence). Modules outside ``src.core.v71.*`` must not be modified
to call into V7.1; the dependency arrow is one-way:

    src.web -> src.core.v71 -> src.core (V7.0 infrastructure)

Subpackages:
  - ``box``        Box system (user-defined entry zones)
  - ``strategies`` Pullback / breakout entry strategies
  - ``exit``       Stop-loss, partial take-profit, trailing stop
  - ``position``   Average price, reconciliation
  - ``skills``     8 standardized skills (07_SKILLS_SPEC.md)
  - ``report``     On-demand reports (Claude Opus 4.7)

Top-level modules (created in P2.4):
  - ``v71_constants``   All magic numbers (V71Constants)
  - ``path_manager``    PATH_A / PATH_B routing
  - ``vi_monitor``      Volatility Interruption state machine
  - ``event_logger``    Audit trail
  - ``restart_recovery`` 7-step recovery sequence
  - ``audit_scheduler`` Monthly review scheduler

Spec: docs/v71/01_PRD_MAIN.md, docs/v71/04_ARCHITECTURE.md §5.3
"""
