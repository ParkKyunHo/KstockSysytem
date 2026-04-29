"""FastAPI application factory for the V7.1 web backend.

The factory is also exposed via ``src.web.v71.create_app`` so that
``uvicorn src.web.v71.main:app --factory`` (or
``--reload``) works during development.

Production runs ``uvicorn src.web.v71.main:app`` after binding the
``app`` module-level instance below; tests prefer ``create_app()``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

# repo root: src/web/v71/main.py -> ../../../.. -> K_stock_trading/
_FRONTEND_DIST = (
    Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
)


# ---------------------------------------------------------------------
# uvicorn access log: mask query-string secrets (?token=..., ?password=...)
# so JWT 토큰이 journalctl 평문으로 남지 않게 한다. WS 인증은 F2 로
# subprotocol 헤더로 이전했지만 backward-compat 클라이언트가 query 로
# 보낼 가능성에 대비. 서버 사이드 안전망.
# ---------------------------------------------------------------------

_SECRET_QUERY_RE = re.compile(
    r"(?P<key>token|password|access_token|refresh_token)=[^\s&\"]+",
    re.IGNORECASE,
)


class _MaskAccessLogSecrets(logging.Filter):
    """Replace ``?token=<value>`` etc. with ``?token=***`` in uvicorn
    access log records (which use args=(client, method, target, ver, ...)).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args and isinstance(record.args, tuple):
            new_args = []
            for arg in record.args:
                if isinstance(arg, str) and _SECRET_QUERY_RE.search(arg):
                    arg = _SECRET_QUERY_RE.sub(r"\g<key>=***", arg)
                new_args.append(arg)
            record.args = tuple(new_args)
        return True


def _install_access_log_secret_mask() -> None:
    """Idempotent install on the uvicorn.access logger."""
    access_log = logging.getLogger("uvicorn.access")
    # 이미 같은 클래스의 filter 가 등록되어 있으면 skip.
    if any(isinstance(f, _MaskAccessLogSecrets) for f in access_log.filters):
        return
    access_log.addFilter(_MaskAccessLogSecrets())


_install_access_log_secret_mask()


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

    # SPA static frontend. Mount AFTER api/ws routers so /api/v71/* keeps
    # precedence. dist may be missing on CI / test workers -- skip silently.
    if _FRONTEND_DIST.is_dir():
        _mount_spa(app, _FRONTEND_DIST)

    return app


def _mount_spa(app: FastAPI, dist_dir: Path) -> None:
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_dir),
            name="assets",
        )

    index_html = dist_dir / "index.html"
    dist_root = dist_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path:
            candidate = (dist_dir / full_path).resolve()
            try:
                candidate.relative_to(dist_root)
            except ValueError:
                return FileResponse(index_html)
            if candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index_html)


# Module-level instance for ``uvicorn src.web.v71.main:app``.
app = create_app()
