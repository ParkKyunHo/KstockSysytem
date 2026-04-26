"""V7.1 box system (user-defined entry zones).

Spec: docs/v71/02_TRADING_RULES.md §3 (Box system)
Modules (P2.4 / P3.1):
  - ``box_manager``        V71BoxManager: CRUD, overlap validation, expiry
  - ``box_entry_detector`` V71BoxEntryDetector: bar-completion entry checks
  - ``box_state_machine``  TRACKING -> BOX_SET -> POSITION_OPEN -> EXITED
"""
