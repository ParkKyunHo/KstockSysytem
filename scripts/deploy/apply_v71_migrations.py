"""Apply a single V7.1 SQL migration by number (idempotent).

Usage:
    python scripts/deploy/apply_v71_migrations.py --apply 021
    python scripts/deploy/apply_v71_migrations.py --check 021    # dry-run + diff

Reads ``DATABASE_URL`` from .env (Windows: pops stale OS env first).
DDL must be idempotent (CREATE INDEX IF NOT EXISTS / DROP IF EXISTS).
The migration file itself is expected to declare BEGIN/COMMIT.

Rollback is intentionally NOT exposed by this script. To roll back a
DDL change, call psql directly with the matching .down.sql after
explicit operator confirmation. Destructive operations should not be
one-flag-away on a deploy-time tool.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "src" / "database" / "migrations" / "v71"
sys.path.insert(0, str(ROOT))

os.environ.pop("DATABASE_URL", None)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)


def _resolve_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set (.env load failed)")
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


def _find_migration(number: str) -> Path:
    matches = list(MIGRATIONS_DIR.glob(f"{number}_*.up.sql"))
    if not matches:
        raise SystemExit(
            f"migration {number} not found under {MIGRATIONS_DIR}"
        )
    if len(matches) > 1:
        raise SystemExit(
            f"migration {number} ambiguous: {[p.name for p in matches]}"
        )
    return matches[0]


def _apply(path: Path, *, check_only: bool) -> int:
    sql = path.read_text(encoding="utf-8")
    print(f"=== migration: {path.name} ===")
    print(f"    size: {len(sql)} bytes")
    if check_only:
        print("    --check (dry-run): not executed")
        return 0
    try:
        import psycopg
    except ImportError:
        raise SystemExit("psycopg not installed -- pip install 'psycopg[binary]'")

    url = _resolve_url()
    try:
        with psycopg.connect(url, connect_timeout=15, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    except Exception as exc:  # noqa: BLE001
        print(f"    APPLY FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"    APPLIED OK ({path.name})")
    return 0


def _verify_box_active_index() -> int:
    """Confirm idx_boxes_active matches PRD §2.2 (3-column partial index)."""
    try:
        import psycopg
    except ImportError:
        return 0
    url = _resolve_url()
    try:
        with psycopg.connect(url, connect_timeout=15) as conn, \
                conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND indexname='idx_boxes_active';"
            )
            row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        print(f"    verify FAILED: {type(exc).__name__}: {exc}")
        return 1
    if row is None:
        print("    verify FAILED: idx_boxes_active not present")
        return 1
    indexdef = row[0]
    print(f"    indexdef: {indexdef}")
    if "tracked_stock_id" in indexdef and "path_type" in indexdef and "WHERE" in indexdef.upper():
        print("    verify OK (3-column partial index, PRD §2.2 aligned)")
        return 0
    print("    verify WARN: definition differs from PRD §2.2")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", metavar="NNN", help="apply migration by number, e.g. 021")
    group.add_argument("--check", metavar="NNN", help="dry-run a migration (no execute)")
    parser.add_argument(
        "--verify-box-active-index",
        action="store_true",
        help="post-check: confirm idx_boxes_active matches PRD §2.2",
    )
    args = parser.parse_args()

    number = args.apply or args.check
    path = _find_migration(number)
    rc = _apply(path, check_only=bool(args.check))
    if rc != 0:
        return rc
    if args.verify_box_active_index:
        return _verify_box_active_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())
