"""TOTP (Time-based One-Time Password) helpers.

Wraps ``pyotp`` so the rest of the codebase only sees primitives that
take strings -- no ``pyotp.TOTP`` objects leak across boundaries.
"""

from __future__ import annotations

import secrets

import pyotp

from ..config import WebSettings


def generate_secret() -> str:
    """Random base32 secret suitable for TOTP."""
    return pyotp.random_base32()


def provisioning_uri(
    secret: str,
    username: str,
    settings: WebSettings,
) -> str:
    """``otpauth://totp/...`` URI for QR codes."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=settings.totp_issuer,
    )


def verify(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """Verify a 6-digit code; allow ±``valid_window`` 30s steps."""
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def generate_backup_codes(count: int = 10) -> list[str]:
    """Random backup codes formatted as ``####-####``."""
    codes: list[str] = []
    for _ in range(count):
        a = secrets.randbelow(10_000)
        b = secrets.randbelow(10_000)
        codes.append(f"{a:04d}-{b:04d}")
    return codes
