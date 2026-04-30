"""Harness 8 (G1): Storage Single-Source-of-Truth Enforcer.

Spec: docs/v71/08_HARNESS_SPEC.md (G1, added by P-Wire-Box-1)
Level: BLOCK

Detects in-memory storage that mirrors a DB-persisted table:

    self._<plural>: dict[..., <Mirror>] = {}
    self._<plural>: list[<Mirror>] = []

where ``<Mirror>`` is a dataclass that shadows an ORM model in
``src/database/models_v71.py``. Storing the same logical row in two
places (memory + DB) is a divergence-by-construction risk that violates
PRD 03_DATA_MODEL §0.1 #4 (Single Source of Truth) and Constitution 1
(user actions must not be silently lost).

KNOWN_PERSISTENT_TYPES is the explicit gate. Adding a new mirror here
forces architect (PRD §6.1) review at PR time -- the harness does not
infer mirrors heuristically, because false negatives (missed mirror)
are the failure mode that hurt us in box_manager / position_manager.

KNOWN_VIOLATIONS_TO_RESOLVE is a transitional list of pre-existing
mirrors slated for removal. Each entry names the unit (P-Wire-Box-N)
that fixes it. As units land, entries are removed; the file becomes
empty when single-source-of-truth is restored. NEW violations outside
this list BLOCK immediately.

Inline override (for genuinely-bounded caches, never DB mirrors):

    self._cache: dict[str, BoxRecord] = {}  # harness-g1: ok (cache, ttl=60s)
"""

from __future__ import annotations

import ast

from _common import HarnessResult, iter_v71_python_files

# In-memory mirror dataclass -> ORM table the data is also persisted in.
# Each entry is a deliberate decision -- adding one means two storages
# of the same row, which only makes sense for read-through caches and
# even then must be justified to v71-architect.
KNOWN_PERSISTENT_TYPES: dict[str, str] = {
    "BoxRecord": "SupportBox",
    "PositionState": "V71Position",
    # NOTE: TradeEvent dataclass mirrors TradeEvent ORM -- same name,
    # disambiguated only by import path. Add explicit detection if a
    # third name-collision case appears.
}

# Pre-existing mirrors with a scheduled fix. Format:
#     "<repo-relative-path>:<lineno>": "<unit-label>"
# Removed as each unit lands. New violations not on this list BLOCK.
KNOWN_VIOLATIONS_TO_RESOLVE: dict[str, str] = {
    # box_manager.py:99 was resolved by P-Wire-Box-1 (DB-backed conversion).
    # v71_position_manager.py:96 was resolved by P-Wire-Box-4 (DB-backed
    # conversion + atomic transactions Q3/Q9).
}

# Files exempt entirely (e.g. ORM definitions themselves).
ALLOWED_FILES: tuple[str, ...] = (
    "src/database/models_v71.py",
)

INLINE_OVERRIDE_MARKER = "# harness-g1: ok"


def _name_of(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mirror_in_annotation(node: ast.expr) -> str | None:
    """Return the mirror type name if the annotation references one.

    Matches:
      dict[K, Mirror]     (slice = Tuple)
      list[Mirror]        (slice = single Name)
      Mapping[K, Mirror]  (best-effort; same shape)
    """
    if not isinstance(node, ast.Subscript):
        return None
    slice_node = node.slice
    candidates: list[ast.expr] = []
    if isinstance(slice_node, ast.Tuple):
        candidates.extend(slice_node.elts)
    else:
        candidates.append(slice_node)
    for elt in candidates:
        name = _name_of(elt)
        if name in KNOWN_PERSISTENT_TYPES:
            return name
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.violations: list[tuple[int, str, str]] = []

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        target = node.target
        if not isinstance(target, ast.Attribute):
            self.generic_visit(node)
            return
        if not (
            isinstance(target.value, ast.Name) and target.value.id == "self"
        ):
            self.generic_visit(node)
            return
        mirror = _mirror_in_annotation(node.annotation)
        if mirror is None:
            self.generic_visit(node)
            return
        idx = node.lineno - 1
        line = self.source_lines[idx] if 0 <= idx < len(self.source_lines) else ""
        if INLINE_OVERRIDE_MARKER in line:
            self.generic_visit(node)
            return
        self.violations.append((node.lineno, target.attr, mirror))
        self.generic_visit(node)


def main() -> None:
    result = HarnessResult(
        "Harness 8 (G1): Storage Single-Source-of-Truth Enforcer",
        level="BLOCK",
    )

    # Resolved entries are tracked so the list stays accurate as units land:
    # if KNOWN_VIOLATIONS_TO_RESOLVE references a location that no longer
    # has a violation, that's a stale entry and we WARN the maintainer.
    seen_known: set[str] = set()

    file_count = 0
    for path in iter_v71_python_files():
        file_count += 1
        rel = path.as_posix().split("K_stock_trading/")[-1]
        if rel in ALLOWED_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError):
            continue
        visitor = _Visitor(text.splitlines())
        visitor.visit(tree)

        for lineno, attr, mirror in visitor.violations:
            key = f"{rel}:{lineno}"
            orm = KNOWN_PERSISTENT_TYPES[mirror]
            if key in KNOWN_VIOLATIONS_TO_RESOLVE:
                seen_known.add(key)
                result.note(
                    f"GRACE  {key} -- self.{attr}: ...[{mirror}] mirrors "
                    f"{orm}. Scheduled fix: "
                    f"{KNOWN_VIOLATIONS_TO_RESOLVE[key]}"
                )
                continue
            result.violate(
                f"{key} -- self.{attr}: ...[{mirror}] mirrors {orm} "
                f"(DB table). Two storages of the same logical row "
                f"violates PRD 03 §0.1 #4 (Single Source of Truth). "
                f"Either go DB-backed via the manager API, or add "
                f"`{INLINE_OVERRIDE_MARKER}` with cache justification."
            )

    # Stale entries in KNOWN_VIOLATIONS_TO_RESOLVE -- list got out of sync
    # with reality. Surface as a violation so maintainers prune it.
    stale = set(KNOWN_VIOLATIONS_TO_RESOLVE) - seen_known
    for key in sorted(stale):
        result.violate(
            f"STALE  KNOWN_VIOLATIONS_TO_RESOLVE entry {key} no longer "
            f"matches a live violation. Remove it from "
            f"storage_invariant_enforcer.py."
        )

    result.note(f"Scanned {file_count} V7.1 .py files.")
    result.note(
        f"{len(KNOWN_PERSISTENT_TYPES)} known mirror types: "
        f"{', '.join(sorted(KNOWN_PERSISTENT_TYPES))}"
    )
    result.note(
        f"{len(KNOWN_VIOLATIONS_TO_RESOLVE) - len(stale)} pre-existing "
        f"violations under scheduled fix (grace)."
    )
    result.report_and_exit()


if __name__ == "__main__":
    main()
