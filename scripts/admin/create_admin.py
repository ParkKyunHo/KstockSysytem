"""Create the first V7.1 dashboard admin user.

Username comes via argv (not PII). Password is read via
``getpass.getpass`` so it never echoes to the terminal, never lands in
argv / env / shell history, and never travels through a PowerShell pipe
(PowerShell 5.1 stdin object pipe is unreliable for native exes).

Steps:
  1. Validate username (3-32 chars, [A-Za-z0-9_-])
  2. Prompt password twice (hidden) -- abort if mismatch
  3. Generate bcrypt hash via the V7.1 ``hash_password`` (rounds=12)
  4. INSERT into ``users`` (role=OWNER, is_active=true, totp_enabled=false)
  5. Print the new user's UUID

Re-runnable: if username already exists, prints message and exits.
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Memory note: stale OS env DATABASE_URL on Windows shadows .env. Pop first.
os.environ.pop("DATABASE_URL", None)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def _prompt_inputs() -> tuple[str, str]:
    if len(sys.argv) < 2:
        print(
            "ERROR: username missing -- run via create_admin.ps1 or "
            "pass username as first argument",
            file=sys.stderr,
        )
        sys.exit(1)
    username = sys.argv[1].strip()
    if not _USERNAME_RE.match(username):
        print(
            f"ERROR: username must be 3-32 chars [A-Za-z0-9_-], got "
            f"{len(username)} chars",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        password = getpass.getpass("password (hidden): ")
        password2 = getpass.getpass("password (re-enter): ")
    except (EOFError, KeyboardInterrupt):
        print("\nERROR: input aborted", file=sys.stderr)
        sys.exit(1)

    if password != password2:
        print("ERROR: passwords do not match", file=sys.stderr)
        sys.exit(1)
    if len(password) < 8:
        print(
            f"ERROR: password must be at least 8 chars (got {len(password)})",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(password.encode("utf-8")) > 72:
        print(
            "WARN: password longer than 72 bytes -- bcrypt only hashes the "
            "first 72 bytes",
            file=sys.stderr,
        )
    return username, password


def main() -> int:
    username, password = _prompt_inputs()

    # Build a minimal WebSettings stub for hash_password (rounds only).
    class _StubSettings:
        bcrypt_rounds = int(os.getenv("BCRYPT_ROUNDS", "12"))

    from src.web.v71.auth.security import hash_password

    pw_hash = hash_password(password, _StubSettings())  # type: ignore[arg-type]
    # Wipe plaintext from memory ASAP (defence in depth -- Python doesn't
    # zero strings but at least drop the reference).
    password = ""  # noqa: F841

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
        return 1
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]

    try:
        import psycopg
    except ImportError:
        print(
            "ERROR: psycopg not installed -- run 'pip install psycopg[binary]'",
            file=sys.stderr,
        )
        return 1

    try:
        with psycopg.connect(url, connect_timeout=15) as conn, \
                conn.cursor() as cur:
            cur.execute(
                "SELECT id, role, is_active FROM users WHERE username = %s",
                (username,),
            )
            existing = cur.fetchone()
            if existing:
                print(
                    f"NOOP: username '{username}' already exists "
                    f"(id={existing[0]}, role={existing[1]}, "
                    f"is_active={existing[2]})",
                )
                print("To reset the password, contact the operator or use")
                print("a separate password-reset tool (not yet provided).")
                return 0
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active,
                                   totp_enabled)
                VALUES (%s, %s, 'OWNER', TRUE, FALSE)
                RETURNING id
                """,
                (username, pw_hash),
            )
            new_id = cur.fetchone()[0]
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: DB insert failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    print(f"OK: admin user '{username}' created (id={new_id}, role=OWNER)")
    print("Login at http://43.200.235.74:8080/api/v71/auth/login (POST)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
