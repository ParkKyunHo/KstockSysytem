"""Harness 6: Dead Code Detector.

Spec: docs/v71/08_HARNESS_SPEC.md §6
Level: WARN (Phase 0), BLOCK (Phase 1 완료 후)

Detects lingering imports of V7.0 modules slated for deletion in Phase 1
(00_CLAUDE_CODE_GENERATION_PROMPT.md §2.1):
  - src.core.signal_pool, signal_processor, signal_detector_purple
  - src.core.v7_signal_coordinator, strategy_orchestrator
  - src.core.strategies.v6_sniper_trap, v7_purple_reabs
  - src.core.exit_manager, auto_screener, indicator (V6)
"""

from __future__ import annotations

import sys
from pathlib import Path

from _common import REPO_ROOT, HarnessResult, iter_python_files

DEAD_MODULES = {
    "src.core.signal_pool",
    "src.core.signal_processor",
    "src.core.signal_detector",
    "src.core.signal_detector_purple",
    "src.core.v7_signal_coordinator",
    "src.core.strategy_orchestrator",
    "src.core.missed_signal_tracker",
    "src.core.watermark_manager",
    "src.core.atr_alert_manager",
    "src.core.condition_search_handler",
    "src.core.indicator_purple",
    "src.core.auto_screener",
    "src.core.exit_manager",
    "src.core.strategies.v6_sniper_trap",
    "src.core.strategies.v7_purple_reabs",
}


def main() -> None:
    result = HarnessResult("Harness 6: Dead Code Detector", level="WARN")
    src_root = REPO_ROOT / "src"
    if not src_root.exists():
        result.note("src/ not present.")
        result.report_and_exit()

    inspected = 0
    for path in iter_python_files(src_root, exclude=("__pycache__",)):
        rel = path.as_posix().split("K_stock_trading/")[-1]
        # 자기 자신은 제외.
        text = path.read_text(encoding="utf-8")
        inspected += 1
        for dead in DEAD_MODULES:
            if dead in rel.replace("/", ".").removesuffix(".py"):
                continue
            if (
                f"from {dead}" in text
                or f"import {dead}" in text
                or f'"{dead}"' in text
            ):
                # 해당 모듈 자체에 본인 이름이 들어있는 경우 제외 (도크스트링 등).
                if rel.replace("/", ".").removesuffix(".py").endswith(dead):
                    continue
                result.violate(f"Dead-code import: {rel} references {dead}")

    result.note(f"Inspected {inspected} files for {len(DEAD_MODULES)} dead modules.")
    result.report_and_exit()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
