"""Harness 3: Trading Rule Enforcer.

Spec: docs/v71/08_HARNESS_SPEC.md §3
Level: BLOCK

Skeleton scope (Phase 0):
  - V71Constants 미존재 시 통과 (Phase 2에서 정의됨).
  - v71/ 내 .py 파일에서 표 매직 넘버 (-0.05, -0.02, 0.04, 0.05, 0.10, 4.0, 3.0, 2.5, 2.0)
    리터럴 사용 시 WARN.
  - raw httpx/requests 호출 (kiwoom_api_skill 우회) 검출 → BLOCK.

Phase 3에서 강화될 항목:
  - 손절 단계별 상향 룰 위반.
  - 평단가 직접 변경 검출.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from _common import SRC_V71, HarnessResult, iter_v71_python_files

MAGIC_FLOATS = {-0.05, -0.02, 0.04, 0.05, 0.10, 4.0, 3.0, 2.5, 2.0}
RAW_HTTP_MODULES = {"httpx", "requests", "aiohttp"}
# Transport-layer modules that own the wire-level Kiwoom conversation. Anything
# above them (services, executors, skills) must go through this seam instead
# of pulling in httpx directly.
ALLOWED_RAW_HTTP_PREFIXES = (
    "src/core/v71/skills/kiwoom_api_skill.py",
    "src/core/v71/exchange/",
)
# Files allowed to literal magic floats. v71_constants is the single
# definition site for all magic numbers (Harness 3's whole point is to
# force everyone else to import from it).
MAGIC_LITERAL_EXEMPT = {"src/core/v71/v71_constants.py"}


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.magic_hits: list[tuple[int, float]] = []
        self.raw_http_hits: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, float) and node.value in MAGIC_FLOATS:
            self.magic_hits.append((node.lineno, node.value))
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name in RAW_HTTP_MODULES:
                self.raw_http_hits.append((node.lineno, alias.name))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module in RAW_HTTP_MODULES:
            self.raw_http_hits.append((node.lineno, node.module))
        self.generic_visit(node)


def main() -> None:
    result = HarnessResult("Harness 3: Trading Rule Enforcer", level="BLOCK")

    if not SRC_V71.exists():
        result.note("src/core/v71/ not yet created — no rules to check.")
        result.report_and_exit()

    file_count = 0
    for path in iter_v71_python_files():
        file_count += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor = _Visitor(path)
        visitor.visit(tree)

        rel = path.as_posix().split("K_stock_trading/")[-1]
        if rel not in MAGIC_LITERAL_EXEMPT:
            for lineno, value in visitor.magic_hits:
                result.violate(
                    f"Magic literal {value!r} at {rel}:{lineno} -- use V71Constants instead."
                )
        for lineno, mod in visitor.raw_http_hits:
            if any(rel == p or rel.startswith(p) for p in ALLOWED_RAW_HTTP_PREFIXES):
                continue
            result.violate(
                f"Raw HTTP module {mod!r} imported at {rel}:{lineno} — "
                f"use the V7.1 exchange transport layer (src/core/v71/exchange/) "
                f"or the existing kiwoom_api_skill facade."
            )

    result.note(f"Inspected {file_count} V7.1 Python files.")
    result.report_and_exit()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
