"""V7.1 standardized skills.

Spec: docs/v71/07_SKILLS_SPEC.md
Modules (P2.3):
  - ``kiwoom_api_skill``     Kiwoom REST + WebSocket wrapper (raw httpx
                            forbidden elsewhere; Harness 3 enforces)
  - ``box_entry_skill``      ``evaluate_box_entry()`` -- the only place
                            box entry condition logic may live
  - ``exit_calc_skill``      ``calculate_effective_stop()`` -- combines
                            fixed stop and TS, single source of truth
  - ``avg_price_skill``      ``update_position_after_buy()`` -- weighted
                            average + event reset
  - ``vi_skill``             ``handle_vi_state()`` -- VI state machine
  - ``notification_skill``   ``send_notification()`` -- enforces severity
                            grading and rate limits
  - ``reconciliation_skill`` ``reconcile_positions()`` -- balance vs DB
  - ``test_template``        Reference test scaffolding for V7.1 modules
"""
