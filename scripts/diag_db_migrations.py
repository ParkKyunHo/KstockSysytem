"""Read-only diagnostic — list V7.1 tables present in the production DB.

No secrets are emitted. Reads ``DATABASE_URL`` from .env and queries
``information_schema.tables`` to confirm migration status before V7.1
boot. Safe to run from operator workstation.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Memory note: stale DATABASE_URL in user OS env shadows .env on Windows.
# Pop first so load_dotenv wins, then load.
os.environ.pop("DATABASE_URL", None)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)


EXPECTED_V71_TABLES = (
    # 000-004: extensions + auth
    "users",
    "user_sessions",
    "user_settings",
    "audit_logs",
    # 005-006: master data
    "market_calendar",
    "stocks",
    # 007-010: trading core
    "tracked_stocks",
    "support_boxes",
    "positions",
    "trade_events",
    # 011-014: ops
    "system_events",
    "system_restarts",
    "vi_events",
    "notifications",
    # 015+: V7.1 patches
    # (016 daily_reports / 017 monthly_reviews / 018 v71_orders --
    # see migrations/v71/*_patch*.up.sql)
    "daily_reports",
    "monthly_reviews",
    "v71_orders",
)


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set (.env load failed)")
        return 1

    # Use psycopg sync -- more robust on Windows than asyncpg for one-off
    # diagnostics. Strip SQLAlchemy-style scheme prefixes.
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]

    try:
        import psycopg
    except ImportError:
        print("psycopg not installed -- run: pip install 'psycopg[binary]'")
        return 1

    try:
        with psycopg.connect(url, connect_timeout=15) as conn, \
                conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "ORDER BY table_name;",
            )
            present = {row[0] for row in cur.fetchall()}
            try:
                cur.execute("SELECT count(*) FROM market_calendar;")
                cal_count = cur.fetchone()[0]
            except psycopg.Error:
                cal_count = None
    except Exception as exc:  # noqa: BLE001
        print(f"DB connect FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"=== {len(present)} public tables present ===")
    for name in sorted(present):
        marker = " (V7.1 expected)" if name in EXPECTED_V71_TABLES else ""
        print(f"  {name}{marker}")
    print()
    missing = [t for t in EXPECTED_V71_TABLES if t not in present]
    if missing:
        print(f"=== {len(missing)} EXPECTED V7.1 TABLES MISSING ===")
        for name in missing:
            print(f"  {name}")
    else:
        print("=== ALL EXPECTED V7.1 TABLES PRESENT ===")
    if cal_count is not None:
        print(f"=== market_calendar row count: {cal_count} ===")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
