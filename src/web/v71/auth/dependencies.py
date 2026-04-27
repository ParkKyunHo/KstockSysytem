"""FastAPI deps for authenticated routes.

Use ``CurrentUserDep`` (or ``CurrentActiveUserDep``) on protected
endpoints; both yield a fully-loaded :class:`User` ORM object.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db_models import User
from ..dependencies import SessionDep, SettingsDep
from ..exceptions import V71AuthenticationError, AuthorizationError
from . import repo
from .security import decode_token

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


async def get_current_user(
    settings: SettingsDep,
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise V71AuthenticationError("Missing bearer token", error_code="UNAUTHORIZED")

    claims = decode_token(
        credentials.credentials,
        settings=settings,
        expected_kind="access",
    )
    user = await repo.get_user_by_id(session, UUID(claims["sub"]))
    if user is None:
        raise V71AuthenticationError("User not found", error_code="UNAUTHORIZED")
    if not user.is_active:
        raise AuthorizationError("User disabled", error_code="FORBIDDEN")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_access_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> str:
    """Returns the raw access token string (no validation)."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise V71AuthenticationError("Missing bearer token", error_code="UNAUTHORIZED")
    return credentials.credentials


AccessTokenDep = Annotated[str, Depends(get_access_token)]
