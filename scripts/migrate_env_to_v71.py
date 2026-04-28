"""Migrate .env from V7.0 layout to V7.1 layout (idempotent).

Phase: 운영 진입 Step 1.b (사용자 위임 — Claude가 V7.0 잔재 정리 + V7.1
placeholder 추가 PR).

Safety:
  * Creates ``.env.v70.bak.YYYYMMDD`` before mutating ``.env``.
  * V7.0 retired vars are *commented out*, not deleted -- the operator
    can audit before final cleanup.
  * V7.1 placeholders are appended only if missing -- existing values
    (real production secrets) are preserved verbatim.
  * Run is idempotent: re-running on an already-migrated file leaves
    secrets and existing placeholders untouched.

Run:
    python scripts/migrate_env_to_v71.py
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
BACKUP_PATH = ROOT / f".env.v70.bak.{date.today():%Y%m%d}"

# ----- V7.1 KEEP (V7.1 코드가 직접 읽음) -----
V71_KEEP = frozenset({
    # KIWOOM keys (production + paper)
    "KIWOOM_APP_KEY",
    "KIWOOM_APP_SECRET",
    "KIWOOM_PAPER_APP_KEY",
    "KIWOOM_PAPER_APP_SECRET",
    "KIWOOM_ENV",
    "KIWOOM_ACCOUNT_NO",
    # Telegram
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    # DB
    "DATABASE_URL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    # Supabase REST (Phase 5+)
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_PROJECT_ID",
    "SUPABASE_PROJECT_NAME",
    # FastAPI auth
    "JWT_SECRET",
    "JWT_ALGORITHM",
    "JWT_EXPIRE_MINUTES",
    # V7.1 specific options
    "V71_AUTO_TRADING",
    "V71_WEB_BOOT_TRADING_ENGINE",
    "V71_RECONCILER_INTERVAL_SECONDS",
    # General
    "ENVIRONMENT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    # Anthropic (Phase 6, optional)
    "ANTHROPIC_API_KEY",
})

# ----- V7.1 placeholders (추가, 누락 시) -----
V71_PLACEHOLDERS = (
    ("KIWOOM_ENV", "SANDBOX",
     "PRODUCTION | SANDBOX (V7.1 trading_bridge fail-loud check)"),
    ("KIWOOM_ACCOUNT_NO", "",
     "8-12자 계좌번호 (kt00018 잔고 조회)"),
    ("JWT_SECRET", "",
     "32+ chars random hex -- python -c "
     "\"import secrets; print(secrets.token_hex(32))\""),
    ("V71_AUTO_TRADING", "false",
     "자동 매매 활성화 (실거래 시작)"),
    ("V71_WEB_BOOT_TRADING_ENGINE", "true",
     "FastAPI boot 시 trading_engine attach"),
)

_VAR_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")


def main() -> int:
    if not ENV_PATH.exists():
        print(f"FAIL: {ENV_PATH} not found")
        return 1

    # 1) Backup (idempotent: re-running on same day overwrites the same backup)
    shutil.copy2(ENV_PATH, BACKUP_PATH)
    print(f"OK: backup created at {BACKUP_PATH.name}")

    # 2) Read + classify
    original = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen_keys: set[str] = set()
    new_lines: list[str] = []
    retired_count = 0
    kept_count = 0

    for line in original:
        m = _VAR_RE.match(line.strip())
        if not m:
            # comment or blank line -- preserve
            new_lines.append(line)
            continue
        key = m.group(1)
        if key in V71_KEEP:
            new_lines.append(line)
            seen_keys.add(key)
            kept_count += 1
        elif line.lstrip().startswith("# V7.0 retired:"):
            # already commented out by a prior run -- preserve as-is
            new_lines.append(line)
        else:
            new_lines.append(f"# V7.0 retired: {line}")
            retired_count += 1

    # 3) Append V7.1 placeholders for missing keys
    appended: list[str] = []
    for key, default, comment in V71_PLACEHOLDERS:
        if key in seen_keys:
            continue
        appended.append(f"{key}={default}  # {comment}")

    if appended:
        new_lines.append("")
        new_lines.append("# ====== V7.1 placeholders (Step 1.b auto-add) ======")
        new_lines.extend(appended)

    # 4) Write
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    print(
        f"OK: kept {kept_count} V7.1 vars / commented {retired_count} V7.0 vars / "
        f"appended {len(appended)} placeholders",
    )
    if appended:
        print()
        print("Placeholders to fill (operator):")
        for line in appended:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
