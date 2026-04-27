"""Domain exceptions + FastAPI exception handlers.

The error envelope mirrors ``09_API_SPEC.md §2.2``:

.. code-block:: json

   {
     "error_code": "VALIDATION_FAILED",
     "message": "...",
     "details": { ... },
     "meta": { "request_id": "...", "timestamp": "..." }
   }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .schemas.common import build_meta


class V71Error(Exception):
    """Base class for V7.1 domain errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code


class NotFoundError(V71Error):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class ConflictError(V71Error):
    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"


class BusinessRuleError(V71Error):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "BUSINESS_RULE_VIOLATION"


class V71AuthenticationError(V71Error):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "AUTHENTICATION_FAILED"


class AuthorizationError(V71Error):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "AUTHORIZATION_FAILED"


class V71RateLimitError(V71Error):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"


# ---------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _envelope(
    *,
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "meta": build_meta(_request_id(request)),
    }
    if details is not None:
        payload["details"] = details
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


async def v71_error_handler(request: Request, exc: V71Error) -> JSONResponse:
    return _envelope(
        request=request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return _envelope(
        request=request,
        status_code=exc.status_code,
        error_code=str(exc.status_code),
        message=str(exc.detail),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _envelope(
        request=request,
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error_code="VALIDATION_FAILED",
        message="Request validation failed",
        details={"errors": exc.errors()},
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Production should hide details; dev surfaces the message.
    from .config import get_settings  # local import to avoid cycle

    settings = get_settings()
    message = str(exc) if not settings.is_prod else "Internal server error"
    return _envelope(
        request=request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="INTERNAL_ERROR",
        message=message,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(V71Error, v71_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
