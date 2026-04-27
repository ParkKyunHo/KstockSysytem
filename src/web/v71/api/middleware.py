"""Request-id middleware -- stamps an id on every request and response.

The id is taken from the ``X-Request-ID`` header when present, otherwise
a UUID4 hex is generated. Routers can read it via ``request.state.request_id``
or the :data:`RequestIdDep` dependency.
"""

from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ..config import WebSettings


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: WebSettings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._header = settings.request_id_header

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        rid = request.headers.get(self._header) or uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers[self._header] = rid
        return response
