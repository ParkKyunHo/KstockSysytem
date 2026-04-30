"""V71 pricing package — PRICE_TICK → DB UPDATE + WebSocket publish.

Phase: P-Wire-Price-Tick (2026-04-30)

Single module: :class:`V71PricePublisher`. Owns the read-only side of the
PRICE_TICK fan-out — it never executes trades, never mutates avg-price /
quantity / status / events, never owns subscribe lifecycle. The exit
pipeline (V71ExitOrchestrator) keeps that responsibility.

PRD references:
  - 09_API_SPEC.md §11.3 (POSITION_PRICE_UPDATE envelope, 1Hz)
  - 03_DATA_MODEL.md §2.3 (V71Position.current_price/at/pnl_amount/pnl_pct
    columns, PRD Patch #5 land 2026-04-27)
  - 02_TRADING_RULES.md §5/§6/§10/§11 (격리: PricePublisher는 어떤 거래
    룰도 위반하면 안 됨 — display-only)

Constitution (5 CRITICAL constraints, see V71PricePublisher docstring):
  P1, P2, P3, P4 (recommended), P5.
"""

from src.core.v71.pricing.v71_price_publisher import V71PricePublisher

__all__ = ["V71PricePublisher"]
