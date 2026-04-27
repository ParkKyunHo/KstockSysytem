"""Audit log recording (PRD 12_SECURITY §7 + 09_API_SPEC §1.2 부수 효과).

A thin helper that wraps inserting into ``audit_logs`` so call sites
stay readable. The function commits its own short-lived transaction --
audit must succeed even when the parent route rolls back.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from src.database.models_v71 import AuditAction, AuditLog
from src.web.v71.db import get_manager

logger = logging.getLogger(__name__)


async def record_audit(
    *,
    action: AuditAction,
    user_id: UUID | None,
    success: bool = True,
    ip_address: str | None = None,
    user_agent: str | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """Insert one row into ``audit_logs``.

    The write happens in its own session (autocommit pattern) so that
    a failure on the *business* path -- e.g. invalid TOTP -- still
    leaves an audit trail. Errors here are logged but never re-raised
    (auditing must not mask the real error).
    """
    manager = get_manager()
    if not manager.is_initialized:
        # Should not happen at runtime (lifespan inits early); be safe.
        await manager.initialize()
    factory = manager._session_factory  # type: ignore[attr-defined]
    if factory is None:
        logger.error("audit_logs write skipped: session factory not ready")
        return

    try:
        async with factory() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    before_state=before_state,
                    after_state=after_state,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    success=success,
                    error_message=error_message,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 -- audit must not raise
        logger.error(
            "Failed to write audit_log (action=%s, user_id=%s): %s",
            action.value,
            user_id,
            exc,
        )
