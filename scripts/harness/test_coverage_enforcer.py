"""Harness 7: Test Coverage Enforcer.

Spec: docs/v71/08_HARNESS_SPEC.md §7
Level: BLOCK (CI), Phase 0에서는 INFO only.

Threshold:
  - src/core/v71/        ≥ 90%  (거래 로직)
  - src/database/, src/utils/  ≥ 80% (인프라)

Phase 0 동작:
  - pytest --cov 호출 → coverage.json 생성 → 임계치 비교.
  - tests/v71/ 디렉토리만 대상으로 빠르게 측정 (전체는 CI에서).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _common import REPO_ROOT, HarnessResult

# Coverage thresholds. v71 modules in skeleton state (NotImplementedError
# bodies) cannot reach 90% until they get implemented, so we add prefixes
# only as each Phase 3 sub-task lands.
#
# Phase 3 graduation log:
#   P3.1: box_state_machine.py, box_manager.py, skills/box_entry_skill.py
#         (box_entry_detector.py stays out -- still NotImplementedError
#          until P3.2)
THRESHOLDS = {
    "src/utils/feature_flags.py": 90.0,
    "src/core/v71/v71_constants.py": 90.0,
    # P3.1: box system.
    "src/core/v71/box/box_state_machine.py": 90.0,
    "src/core/v71/box/box_manager.py": 90.0,
    "src/core/v71/skills/box_entry_skill.py": 90.0,
    # P3.2: buy executor + entry detector + strategy wrappers.
    "src/core/v71/box/box_entry_detector.py": 90.0,
    "src/core/v71/strategies/v71_buy_executor.py": 90.0,
    "src/core/v71/strategies/v71_box_pullback.py": 90.0,
    "src/core/v71/strategies/v71_box_breakout.py": 90.0,
    # P3.3: post-buy management (stop ladder + partial profit-take + TS).
    "src/core/v71/skills/exit_calc_skill.py": 90.0,
    "src/core/v71/exit/exit_calculator.py": 90.0,
    "src/core/v71/exit/exit_executor.py": 90.0,
    "src/core/v71/exit/trailing_stop.py": 90.0,
    "src/core/v71/position/state.py": 90.0,
    # P3.4: avg-price skill body + V71PositionManager (in-memory).
    "src/core/v71/skills/avg_price_skill.py": 90.0,
    "src/core/v71/position/v71_position_manager.py": 90.0,
    # P3.5: reconciliation skill + V71Reconciler.
    "src/core/v71/skills/reconciliation_skill.py": 90.0,
    "src/core/v71/position/v71_reconciler.py": 90.0,
    # P3.6: vi_skill + V71ViMonitor.
    "src/core/v71/skills/vi_skill.py": 90.0,
    "src/core/v71/vi_monitor.py": 90.0,
    # P3.7: V71RestartRecovery (7-step recovery).
    "src/core/v71/restart_recovery.py": 90.0,
}
# Phase 3 (trading-rule implementation) thresholds complete.
# Next: notification skill (P4.1), report generator (P6).


def _run_pytest() -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/v71/",
        "--cov=src",
        "--cov-report=json",
        "-q",
    ]
    return subprocess.call(cmd, cwd=REPO_ROOT)


def main() -> None:
    result = HarnessResult("Harness 7: Test Coverage Enforcer", level="BLOCK")

    tests_v71 = REPO_ROOT / "tests" / "v71"
    if not tests_v71.exists() or not any(tests_v71.glob("test_*.py")):
        result.note("tests/v71/ has no tests yet — coverage check deferred.")
        result.report_and_exit()

    rc = _run_pytest()
    if rc != 0:
        result.violate(f"pytest returned non-zero exit code {rc}.")
        result.report_and_exit()

    coverage_file = REPO_ROOT / "coverage.json"
    if not coverage_file.is_file():
        result.violate("coverage.json not generated.")
        result.report_and_exit()

    data = json.loads(coverage_file.read_text(encoding="utf-8"))
    files = data.get("files", {})

    for prefix, min_pct in THRESHOLDS.items():
        relevant = {
            f: stats for f, stats in files.items() if f.replace("\\", "/").startswith(prefix)
        }
        if not relevant:
            result.note(f"No files match '{prefix}' yet (skipped).")
            continue
        total_stmts = sum(stats["summary"]["num_statements"] for stats in relevant.values())
        covered = sum(stats["summary"]["covered_lines"] for stats in relevant.values())
        pct = (covered / total_stmts * 100) if total_stmts else 100.0
        status = "OK" if pct >= min_pct else "FAIL"
        msg = f"{prefix}: {pct:.1f}% (threshold {min_pct:.0f}%) [{status}]"
        if pct < min_pct:
            result.violate(msg)
        else:
            result.note(msg)

    result.report_and_exit()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
