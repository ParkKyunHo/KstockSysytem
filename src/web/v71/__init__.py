"""V7.1 Web Backend (FastAPI).

Implements the REST + WebSocket surface defined in
``docs/v71/09_API_SPEC.md``. The package is intentionally isolated from
the legacy ``src.web`` namespace to keep V7 / V7.1 separation explicit
(see Phase 2 Harness 1 — Naming Collision rules).

Public entry points::

    from src.web.v71 import create_app
    app = create_app()

    from src.web.v71 import trading_bridge
    await trading_bridge.publish_position_price_update(...)

The :mod:`trading_bridge` module is the only surface the V7.1 trading
engine should import to push events into the web layer (PRD §9 status,
§11 WebSocket).
"""

from __future__ import annotations

__all__ = ["create_app"]


def create_app():  # type: ignore[no-untyped-def]
    """Lazy import to avoid pulling FastAPI when unused."""
    from .main import create_app as _factory

    return _factory()


# Trading-engine integration entry point: ``from src.web.v71 import
# trading_bridge`` (keeps the heavy FastAPI app out of the import graph).
