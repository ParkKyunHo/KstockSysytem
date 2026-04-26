"""Harness 1: Naming Collision Detector.

Spec: docs/v71/08_HARNESS_SPEC.md §1
Level: BLOCK

Rules (this skeleton implements R1, R2; R3+ deferred to Phase 1):
  R1. v71 패키지 외부에서 ``V71`` 접두사 클래스 정의 금지.
  R2. v71 패키지 내부의 클래스 이름이 V7.0(src/core/* 외 v71/)과 정확히 일치하면 충돌.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import (
    HarnessResult,
    SRC_V71,
    iter_v70_core_python_files,
    iter_v71_python_files,
)


def _collect_classes(files):
    out: dict[str, list[Path]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                out.setdefault(node.name, []).append(path)
    return out


def main() -> None:
    result = HarnessResult("Harness 1: Naming Collision Detector", level="BLOCK")

    if not SRC_V71.exists():
        result.note("src/core/v71/ not yet created — Phase 2 will add modules.")
        result.report_and_exit()

    v70 = _collect_classes(iter_v70_core_python_files())
    v71 = _collect_classes(iter_v71_python_files())

    # R1: V71 접두사를 v71 외부에서 사용 금지.
    for name, paths in v70.items():
        if name.startswith("V71"):
            for p in paths:
                result.violate(f"V71-prefixed class '{name}' defined outside v71/: {p}")

    # R2: 이름 충돌 (v71 내부 vs v70 외부).
    for name, v71_paths in v71.items():
        if name in v70:
            for p in v71_paths:
                v70_paths_str = ", ".join(str(x) for x in v70[name])
                result.violate(
                    f"Class name '{name}' collides with V7.0: {p} ↔ {v70_paths_str}"
                )

    result.note(f"Inspected {sum(len(v) for v in v70.values())} V7.0 class defs.")
    result.note(f"Inspected {sum(len(v) for v in v71.values())} V7.1 class defs.")
    result.report_and_exit()


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
