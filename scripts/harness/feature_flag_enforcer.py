"""Harness 5: Feature Flag Enforcer.

Spec: docs/v71/08_HARNESS_SPEC.md §5
Level: WARN (Phase 0~2), BLOCK (Phase 3+)

Skeleton:
  - v71/ 내 모듈에 진입 함수가 있으면, 모듈 어딘가에서
    ``feature_flags.is_enabled(`` 또는 ``require_enabled(`` 호출이 있어야 한다.
  - 스킬/유틸리티 모듈 (skills/, _common.py 등)은 면제.

Heuristic (Phase 0): 단순 텍스트 검색. 거짓 양성은 WARN으로만 표시.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import SRC_V71, HarnessResult, iter_v71_python_files

EXEMPT_PARTS = (
    "__init__.py",
    "/skills/",
    "constants",
    "v71_constants",
    # Building blocks composed by V71NotificationQueue / V71NotificationService
    # (which themselves carry require_enabled guards). Adding the gate to a
    # plain repository / state machine module would be redundant and
    # complicate test setup.
    "v71_circuit_breaker",
    "v71_notification_repository",
    "v71_postgres_notification_repository",
)
GUARD_TOKENS = ("feature_flags.is_enabled", "is_enabled(", "require_enabled(")


def main() -> None:
    result = HarnessResult("Harness 5: Feature Flag Enforcer", level="WARN")
    if not SRC_V71.exists():
        result.note("src/core/v71/ not yet created — nothing to guard.")
        result.report_and_exit()

    inspected = 0
    for path in iter_v71_python_files():
        rel = path.as_posix().split("K_stock_trading/")[-1]
        if any(part in rel for part in EXEMPT_PARTS):
            continue
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            continue
        inspected += 1
        if not any(token in text for token in GUARD_TOKENS):
            result.violate(f"Missing feature flag guard in {rel}")

    result.note(f"Inspected {inspected} V7.1 entry-point modules.")
    result.report_and_exit()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
