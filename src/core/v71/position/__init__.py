"""V7.1 position management.

Spec: docs/v71/02_TRADING_RULES.md §6 (Average price), §7 (manual trades)
Modules (P3.4 / P3.5):
  - ``v71_position_manager`` Weighted-average recompute on adds, event resets
                            on +5% / +10% partial exits
  - ``v71_reconciler``      Manual-trade scenarios A/B/C/D, restart recovery
"""
