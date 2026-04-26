"""Harness 4: Schema Migration Validator.

Spec: docs/v71/08_HARNESS_SPEC.md §4
Level: BLOCK

Skeleton (Phase 0):
  - src/database/migrations/v71/ 내 *.up.sql 파일은 동일 prefix .down.sql 짝 필수.
  - 디렉토리 미존재 시 PASS (Phase 2에서 도입).

Phase 2에서 강화:
  - DROP TABLE / DROP COLUMN 등 파괴적 변경 차단 (단, ALTER ... 추가만 허용).
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import REPO_ROOT, HarnessResult

MIGRATIONS_DIR = REPO_ROOT / "src" / "database" / "migrations" / "v71"


def main() -> None:
    result = HarnessResult("Harness 4: Schema Migration Validator", level="BLOCK")
    if not MIGRATIONS_DIR.exists():
        result.note(f"{MIGRATIONS_DIR.relative_to(REPO_ROOT)} not yet created.")
        result.report_and_exit()

    ups = sorted(MIGRATIONS_DIR.glob("*.up.sql"))
    downs = {p.stem.removesuffix(".up") for p in ups}
    actual_downs = {p.stem.removesuffix(".down") for p in MIGRATIONS_DIR.glob("*.down.sql")}

    missing = downs - actual_downs
    for stem in sorted(missing):
        result.violate(f"Missing DOWN migration for {stem}.up.sql")

    orphan = actual_downs - downs
    for stem in sorted(orphan):
        result.violate(f"Orphan DOWN migration {stem}.down.sql (no UP pair)")

    result.note(f"Inspected {len(ups)} UP migrations.")
    result.report_and_exit()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
