"""Seed a deterministic dev user into the local SQLite dev DB.

The launcher (``dev_run_local.py``) calls :func:`seed_dev_user` before
uvicorn serves traffic so login works on first boot. The seed is
idempotent: if the user already exists we just refresh password +
TOTP-disabled state. Legacy usernames listed in ``LEGACY_USERNAMES``
are deleted so the active credentials are unambiguous.

Active dev credentials: ``admin`` / ``admin`` (5 chars).

Refusing to run outside dev
---------------------------
This script *only* seeds when ``V71_WEB_ENVIRONMENT=dev``. Production
launches must never load this file's side effects, so the guard sits at
the top of :func:`seed_dev_user` and aborts with a clear message if it
sees anything else.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402  -- sys.path manipulation above

DEV_USERNAME = "admin"
DEV_PASSWORD = "admin"  # 5 chars — satisfies LoginRequest min_length=5

# Legacy username from earlier dev infra (commit 75d3bbd). Cleaned up
# below if present so the dev DB has only the active credentials.
LEGACY_USERNAMES = ("dev",)


async def seed_dev_user() -> None:
    """Idempotent seed of the dev/dev user.

    Must be called from an event loop running under
    ``WindowsSelectorEventLoopPolicy`` if the host happens to point at
    PostgreSQL, but in dev we route at SQLite so the loop choice does
    not matter.
    """
    env = os.environ.get("V71_WEB_ENVIRONMENT", "").lower()
    if env != "dev":
        raise RuntimeError(
            f"dev_seed must only run when V71_WEB_ENVIRONMENT=dev (got {env!r})"
        )

    # Imports are lazy because ``connection.py`` performs side-effects on
    # import (sets the asyncio event-loop policy on Windows).
    from src.database.connection import close_database, get_db_manager, init_database
    from src.database.models_v71 import User
    from src.web.v71.auth.security import hash_password
    from src.web.v71.config import get_settings

    settings = get_settings()
    if settings.environment != "dev":
        raise RuntimeError(
            f"WebSettings.environment must be 'dev' for seeding (got {settings.environment!r})"
        )

    ok = await init_database()
    if not ok:
        raise RuntimeError("dev_seed: DatabaseManager.initialize() returned False")

    manager = get_db_manager()
    factory = manager._session_factory  # noqa: SLF001
    if factory is None:
        raise RuntimeError("dev_seed: DB session factory not ready")

    try:
        async with factory() as session:
            # Cleanup: drop legacy usernames from earlier dev infra so
            # only the active dev credentials live in the SQLite DB.
            for legacy_name in LEGACY_USERNAMES:
                legacy = await session.execute(
                    select(User).where(User.username == legacy_name)
                )
                legacy_user = legacy.scalar_one_or_none()
                if legacy_user is not None:
                    await session.delete(legacy_user)
                    await session.commit()
                    print(f"[dev_seed] removed legacy user '{legacy_name}'")

            existing = await session.execute(
                select(User).where(User.username == DEV_USERNAME)
            )
            user = existing.scalar_one_or_none()

            password_hash = hash_password(DEV_PASSWORD, settings)

            if user is None:
                user = User(
                    username=DEV_USERNAME,
                    password_hash=password_hash,
                    role="OWNER",
                    is_active=True,
                    totp_enabled=False,
                )
                session.add(user)
                await session.commit()
                print(
                    f"[dev_seed] created user '{DEV_USERNAME}' "
                    f"(password '{DEV_PASSWORD}', TOTP off)"
                )
            else:
                user.password_hash = password_hash
                user.totp_enabled = False
                user.is_active = True
                await session.commit()
                print(
                    f"[dev_seed] refreshed user '{DEV_USERNAME}' "
                    f"(password '{DEV_PASSWORD}', TOTP off)"
                )
    finally:
        # Keep the engine open across the launcher's full lifetime —
        # uvicorn will reuse the same DatabaseManager singleton during
        # request handling. close_database() runs on shutdown via the
        # FastAPI lifespan.
        _ = close_database  # silence unused-import warning


if __name__ == "__main__":
    import asyncio

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Allow standalone invocation: assume the launcher's env was already
    # written to .env or exported. Fail loud otherwise.
    asyncio.run(seed_dev_user())
