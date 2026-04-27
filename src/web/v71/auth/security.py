"""Auth primitives -- bcrypt password hashing + JWT encode/decode.

The two pieces are intentionally narrow so the rest of the auth module
can be tested without spinning up a database.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from ..config import WebSettings
from ..exceptions import V71AuthenticationError

TokenKind = Literal["access", "refresh", "totp_session"]


# ---------------------------------------------------------------------
# Password (bcrypt -- 12_SECURITY § auth)
# ---------------------------------------------------------------------


# bcrypt only hashes the first 72 bytes of input; longer passwords are
# truncated by the algorithm itself. We pre-encode and bound the input
# so verification stays deterministic.
_BCRYPT_MAX_BYTES = 72


def _to_bytes(plain: str) -> bytes:
    raw = plain.encode("utf-8")
    return raw[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str, settings: WebSettings) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(_to_bytes(plain), salt).decode("ascii")


def verify_password(plain: str, hashed: str, settings: WebSettings) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("ascii"))
    except ValueError:
        return False


# ---------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    *,
    user_id: UUID | str,
    kind: TokenKind,
    settings: WebSettings,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    """Returns ``(jwt, expires_at)``."""
    if kind == "access":
        delta = timedelta(minutes=settings.access_token_minutes)
    elif kind == "refresh":
        delta = timedelta(hours=settings.refresh_token_hours)
    elif kind == "totp_session":
        delta = timedelta(minutes=settings.totp_session_minutes)
    else:
        raise ValueError(f"Unknown token kind: {kind}")

    issued_at = _now()
    expires_at = issued_at + delta
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "type": kind,
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_token(
    token: str,
    *,
    settings: WebSettings,
    expected_kind: TokenKind | None = None,
) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise V71AuthenticationError(
            "Invalid or expired token",
            error_code="UNAUTHORIZED",
        ) from exc

    if expected_kind and claims.get("type") != expected_kind:
        raise V71AuthenticationError(
            f"Wrong token type (expected {expected_kind})",
            error_code="UNAUTHORIZED",
        )
    return claims


# ---------------------------------------------------------------------
# Token storage hashes
# ---------------------------------------------------------------------


def hash_token(token: str) -> str:
    """Stable, constant-time-comparable token fingerprint for DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)
