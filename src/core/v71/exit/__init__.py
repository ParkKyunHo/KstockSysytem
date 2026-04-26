"""V7.1 exit subsystem (stop-loss, take-profit, trailing stop).

Spec: docs/v71/02_TRADING_RULES.md §5 (Post-buy management)
Modules (P3.3):
  - ``exit_calculator`` V7.1 stop ladder (-5% -> -2% -> +4%) and
                       partial take-profit (+5% / +10%, 30% slice each)
  - ``trailing_stop``   ATR multipliers 4.0 -> 3.0 -> 2.5 -> 2.0
  - ``exit_executor``   Order placement glue
"""
