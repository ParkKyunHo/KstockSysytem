"""Re-export V7.1 ORM models from the canonical location.

The actual definitions live in ``src.database.models_v71`` so they share
the legacy SQLAlchemy ``Base`` (see ``03_DATA_MODEL.md §0.1`` -- V7.0
호환). This module exists purely to keep web-layer imports short.
"""

from __future__ import annotations

from src.database.models import Base
from src.database.models_v71 import (
    AuditAction,
    AuditLog,
    User,
    UserSession,
    UserSettings,
)

__all__ = [
    "AuditAction",
    "AuditLog",
    "Base",
    "User",
    "UserSession",
    "UserSettings",
]
