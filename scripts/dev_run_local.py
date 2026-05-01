"""Dev launcher for the V7.1 web backend (option A — fully isolated dev mode).

What it does
------------
1. Forces ``V71_WEB_ENVIRONMENT=dev`` so the rest of the stack treats this
   process as development (TOTP skip, debug logs, etc.).
2. Strips PostgreSQL env vars so ``DatabaseManager`` skips Supabase and
   goes straight to SQLite at ``data/dev.db``. This sidesteps the Windows
   ``ProactorEventLoop`` ↔ psycopg async incompatibility entirely.
3. Forces ``V71_WEB_BOOT_TRADING_ENGINE=false`` so the launcher cannot
   call the Kiwoom REST API. Real money only ever flows through the AWS
   Lightsail systemd unit.
4. Seeds a deterministic dev user (``dev`` / ``devpass1``) into the local
   SQLite DB so the login screen works on first boot.
5. Drives uvicorn via ``asyncio.run(server.serve())`` so the Windows
   ``WindowsSelectorEventLoopPolicy`` patch survives uvicorn 0.46's
   internal ``asyncio_run`` (which would otherwise force a new
   ``ProactorEventLoop``).

Usage
-----
    "C:\\Program Files\\Python311\\python.exe" scripts\\dev_run_local.py

Pair with ``frontend/.env.development.local`` pointing the vite proxy at
``http://127.0.0.1:8080`` and run ``npm run dev`` in another shell. Login
with ``dev`` / ``devpass1`` (no TOTP).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV_SQLITE_PATH = "data/dev.db"


def _patch_windows_event_loop() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _load_dotenv_secrets_only() -> None:
    """Load .env then strip everything that would route us at production.

    We still want secrets like ``KIWOOM_*`` (for token-loading code paths
    that import lazily) and ``JWT_SECRET`` so the JWT signing key stays
    consistent if the user later inspects a production token. But we
    discard anything that could push the launcher onto the production
    PostgreSQL or the live trading engine.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        sys.stderr.write(
            "[dev_run_local] python-dotenv not installed.\n"
            '  Run: "C:\\Program Files\\Python311\\python.exe" -m pip install python-dotenv\n'
        )
        sys.exit(1)

    dotenv_path = REPO_ROOT / ".env"
    if dotenv_path.exists():
        # Pop stale OS-level vars so .env wins, then load it.
        for key in (
            "DATABASE_URL",
            "JWT_SECRET",
            "V71_WEB_DATABASE_URL",
            "V71_WEB_JWT_SECRET",
        ):
            os.environ.pop(key, None)
        load_dotenv(dotenv_path, override=True)


def _force_dev_isolation() -> None:
    """Strip PG vars + force dev flags. Idempotent + safe to call twice.

    pydantic-settings reads ``.env`` files directly during ``BaseSettings``
    init — popping ``os.environ`` is not enough because the .env path
    overrides come back. We therefore set the PostgreSQL vars to empty
    strings, which pydantic-settings sees as set-but-empty (env wins
    over .env), and the property guards (``if self.database_url:``)
    treat as falsy so the connection falls through to SQLite.
    """
    # ``DATABASE_URL`` empty string overrides the .env value and makes
    # ``DatabaseSettings.postgres_url`` falsy → SQLite fallback.
    # POSTGRES_HOST/USER are not in .env so we leave them unset.
    # POSTGRES_PORT keeps its default int (don't blank it — pydantic
    # int parsing rejects empty strings).
    os.environ["DATABASE_URL"] = ""
    os.environ["V71_WEB_DATABASE_URL"] = ""

    os.environ["V71_WEB_ENVIRONMENT"] = "dev"
    os.environ["V71_WEB_BOOT_TRADING_ENGINE"] = "false"
    os.environ["V71_WEB_DEBUG"] = "true"
    os.environ["SQLITE_PATH"] = DEV_SQLITE_PATH


def _ensure_pythonpath() -> None:
    repo_root_str = str(REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    os.environ["PYTHONPATH"] = (
        repo_root_str + os.pathsep + os.environ.get("PYTHONPATH", "")
    ).rstrip(os.pathsep)


async def _seed_dev_user() -> None:
    from scripts.dev_seed import seed_dev_user

    await seed_dev_user()


async def _seed_then_serve(server) -> None:
    await _seed_dev_user()
    await server.serve()


def main() -> None:
    _patch_windows_event_loop()
    _load_dotenv_secrets_only()
    _force_dev_isolation()
    _ensure_pythonpath()

    print("=" * 64)
    print("V7.1 dev backend - http://127.0.0.1:8080")
    print(f"  - SQLite (isolated): {DEV_SQLITE_PATH}")
    print("  - Trading engine: OFF (Kiwoom API never called)")
    print("  - TOTP: OFF (V71_WEB_ENVIRONMENT=dev)")
    print("  - Login: dev / devpass1")
    print("  - Pair with vite dev: http://localhost:5173")
    print("  - Restart this launcher after backend code changes")
    print("    (reload=False because uvicorn subprocesses lose the")
    print("     Windows asyncio-policy patch).")
    print("=" * 64)

    import uvicorn

    config = uvicorn.Config(
        app="src.web.v71.main:app",
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_level="info",
    )
    server = uvicorn.Server(config)
    asyncio.run(_seed_then_serve(server))


if __name__ == "__main__":
    main()
