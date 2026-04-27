"""Harness 2: Dependency Cycle Detector.

Spec: docs/v71/08_HARNESS_SPEC.md §2
Level: BLOCK

Algorithm:
  AST에서 ``from src.* import`` / ``import src.*`` 만 추출 → 디렉티드 그래프 →
  Tarjan SCC로 크기 ≥ 2 인 강한연결요소 감지.
  v71 → v70 단방향 룰 위반(역방향 import) 도 별도 검출.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

from _common import REPO_ROOT, HarnessResult, iter_python_files


def _module_name(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(tree: ast.AST) -> set[str]:
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("src."):
                seen.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    seen.add(alias.name)
    return seen


def _build_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    src_root = REPO_ROOT / "src"
    if not src_root.exists():
        return graph
    for path in iter_python_files(src_root, exclude=("__pycache__",)):
        mod = _module_name(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for target in _imports(tree):
            graph[mod].add(target)
    return graph


def _tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    sccs: list[list[str]] = []

    nodes = set(graph.keys()) | {n for deps in graph.values() for n in deps}

    def strongconnect(node: str) -> None:
        indices[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for successor in graph.get(node, ()):
            if successor not in indices:
                strongconnect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])
        if lowlinks[node] == indices[node]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == node:
                    break
            if len(scc) > 1:
                sccs.append(scc)

    sys.setrecursionlimit(max(2000, sys.getrecursionlimit()))
    for node in list(nodes):
        if node not in indices:
            strongconnect(node)
    return sccs


# V7.1 land = core engine (src.core.v71.*) + web layer (src.web.v71.*).
# Phase 5 added the FastAPI surface under src/web/v71 which is part of
# the V7.1 stack and is allowed to call into V7.1 core (single direction
# rule below). 단방향 룰: V7.0 -> V7.1 차단.
_V71_PREFIXES = ("src.core.v71", "src.web.v71")


def _is_v71(module: str) -> bool:
    return any(module == p or module.startswith(p + ".") for p in _V71_PREFIXES)


def _scc_touches_v71(scc: list[str]) -> bool:
    return any(_is_v71(m) for m in scc)


def main() -> None:
    blocking = HarnessResult("Harness 2: Dependency Cycle Detector", level="BLOCK")
    advisory = HarnessResult("Harness 2: Dependency Cycle Detector (advisory)", level="WARN")

    graph = _build_graph()
    if not graph:
        blocking.note("src/ contains no Python imports yet.")
        blocking.report_and_exit()

    sccs = _tarjan_scc(graph)
    for scc in sccs:
        msg = f"Cycle: {' -> '.join(scc)} -> {scc[0]}"
        if _scc_touches_v71(scc):
            blocking.violate(msg)  # 헌법 3: V7.1 관련 cycle 차단.
        else:
            advisory.violate(msg)  # V7.0 잔재 (P1에서 정리 대상).

    # 단방향 룰: v70 → v71 import 금지.
    for src_mod, targets in graph.items():
        if _is_v71(src_mod):
            continue
        for tgt in targets:
            if _is_v71(tgt):
                blocking.violate(
                    f"V7.0 -> V7.1 dependency forbidden: {src_mod} imports {tgt}"
                )

    blocking.note(
        f"Graph: {len(graph)} modules, {sum(len(v) for v in graph.values())} edges."
    )
    if advisory.violations:
        blocking.note(
            f"V7.0-only cycles deferred to Phase 1: {len(advisory.violations)} (WARN)."
        )
    blocking.report_and_exit()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
