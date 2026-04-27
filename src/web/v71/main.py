"""FastAPI application factory for the V7.1 web backend.

The factory is also exposed via ``src.web.v71.create_app`` so that
``uvicorn src.web.v71.main:app --factory`` (or
``--reload``) works during development.

Production runs ``uvicorn src.web.v71.main:app`` after binding the
``app`` module-level instance below; tests prefer ``create_app()``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.middleware import RequestIdMiddleware
from .api.router import api_router
from .config import WebSettings, get_settings
from .exceptions import register_exception_handlers
from .lifespan import lifespan
from .rate_limit import (
    RateLimitExceeded,
    limiter,
    rate_limit_exceeded_handler,
)
from .ws.router import router as ws_router


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """Build a fresh FastAPI app -- safe to call from tests."""
    settings = settings or get_settings()

    app = FastAPI(
        title="K-Stock Trading API",
        version="7.1.0",
        description="V7.1 box-based trading system REST + WebSocket surface.",
        debug=settings.debug,
        lifespan=lifespan,
        # OpenAPI is exposed in dev only; flip the flag in prod.
        openapi_url="/api/v71/openapi.json" if not settings.is_prod else None,
        docs_url="/api/v71/docs" if not settings.is_prod else None,
        redoc_url="/api/v71/redoc" if not settings.is_prod else None,
    )

    # CORS (frontend dev server)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[settings.request_id_header],
    )

    # Request id (must be before the routers so handlers see request.state)
    app.add_middleware(RequestIdMiddleware, settings=settings)

    # Rate limit (PRD §1.2 -- IP당 5회/분 등)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # type: ignore[arg-type]

    register_exception_handlers(app)
    app.include_router(api_router)
    app.include_router(ws_router)

    return app


# Module-level instance for ``uvicorn src.web.v71.main:app``.
app = create_app()
