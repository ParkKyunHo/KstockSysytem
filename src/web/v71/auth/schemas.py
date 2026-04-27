"""Pydantic schemas for the auth router (09_API_SPEC §1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginPendingTotp(BaseModel):
    """Returned when the user has 2FA enabled (PRD §1.2 Response 200 TOTP 필요)."""

    totp_required: bool = True
    session_id: str
    message: str = "TOTP 코드를 입력해주세요"


class TokenPair(BaseModel):
    """Issued after a successful (full) login (PRD §1.2 Response 200 TOTP 비활성)."""

    totp_required: bool = False
    access_token: str
    refresh_token: str
    expires_in: int  # seconds (matches access_token lifetime)


# ---------------------------------------------------------------------
# TOTP / backup-code verify
# ---------------------------------------------------------------------


class TotpVerifyRequest(BaseModel):
    """PRD §1.2 totp/verify -- 6-digit TOTP."""

    session_id: str
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpSetupResponse(BaseModel):
    totp_secret: str
    qr_code_url: str  # ``otpauth://totp/...``
    backup_codes: list[str]


class TotpConfirmRequest(BaseModel):
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpConfirmResponse(BaseModel):
    totp_enabled: bool


# ---------------------------------------------------------------------
# Refresh / logout
# ---------------------------------------------------------------------


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int


# ---------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------


class CurrentUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: str
    totp_enabled: bool
    telegram_chat_id: str | None = None
