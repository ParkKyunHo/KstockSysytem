"""모든 V7.1 하네스 통합 실행기.

Spec: docs/v71/08_HARNESS_SPEC.md §8

Usage:
  python scripts/harness/run_all.py            # 1~6 (pre-commit set)
  python scripts/harness/run_all.py --with-7   # CI 모드 (1~7)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HARNESSES = [
    ("Harness 1: Naming Collision", "naming_collision_detector.py"),
    ("Harness 2: Dependency Cycle", "dependency_cycle_detector.py"),
    ("Harness 3: Trading Rule", "trading_rule_enforcer.py"),
    ("Harness 4: Schema Migration", "schema_migration_validator.py"),
    ("Harness 5: Feature Flag", "feature_flag_enforcer.py"),
    ("Harness 6: Dead Code", "dead_code_detector.py"),
    ("Harness 8 (G1): Storage SSoT", "storage_invariant_enforcer.py"),
]
HARNESS_7 = ("Harness 7: Test Coverage", "test_coverage_enforcer.py")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-7", action="store_true", help="Include slow Harness 7.")
    args = parser.parse_args()

    targets = list(HARNESSES)
    if args.with_7:
        targets.append(HARNESS_7)

    here = Path(__file__).resolve().parent
    failed: list[str] = []
    print("=" * 70)
    print(" V7.1 HARNESS RUNNER")
    print("=" * 70)

    for name, script in targets:
        print(f"\n>>> {name}")
        print("-" * 70)
        rc = subprocess.call([sys.executable, str(here / script)])
        if rc != 0:
            failed.append(name)

    print("\n" + "=" * 70)
    if failed:
        print(f"FAIL  {len(failed)} / {len(targets)} harness(es):")
        for name in failed:
            print(f"   - {name}")
        return 1
    print(f"PASS  {len(targets)} / {len(targets)} harness(es)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
