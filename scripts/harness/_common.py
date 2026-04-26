"""하네스 공통 헬퍼.

각 하네스 스크립트는 이 모듈을 통해 일관된 출력 + 종료 코드를 얻는다.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Iterable
from pathlib import Path

# Windows 콘솔 (cp949) 호환을 위한 UTF-8 강제.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, io.UnsupportedOperation):
        pass

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
SRC_V71 = SRC / "core" / "v71"
TESTS = REPO_ROOT / "tests"
DOCS_V71 = REPO_ROOT / "docs" / "v71"


class HarnessResult:
    """하네스 실행 결과 누적기."""

    def __init__(self, name: str, level: str = "BLOCK") -> None:
        self.name = name
        self.level = level  # "BLOCK" | "WARN"
        self.violations: list[str] = []
        self.notes: list[str] = []

    def violate(self, message: str) -> None:
        self.violations.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def report_and_exit(self) -> None:
        sep = "=" * 70
        print(sep)
        print(f"  {self.name}  [level={self.level}]")
        print(sep)
        for note in self.notes:
            print(f"  - {note}")
        if self.violations:
            print(f"\n  Violations ({len(self.violations)}):")
            for idx, v in enumerate(self.violations, 1):
                print(f"    {idx}. {v}")
            print()
            if self.level == "BLOCK":
                print(f"  RESULT: FAIL ({self.name})")
                sys.exit(1)
            else:
                print(f"  RESULT: WARN ({self.name}) -- non-blocking")
                sys.exit(0)
        else:
            print(f"\n  RESULT: PASS ({self.name})")
            sys.exit(0)


def iter_python_files(root: Path, *, exclude: Iterable[str] = ()) -> Iterable[Path]:
    excluded = tuple(exclude)
    for path in root.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(part in rel for part in excluded):
            continue
        yield path


def iter_v71_python_files() -> Iterable[Path]:
    if not SRC_V71.is_dir():
        return iter(())
    return iter_python_files(SRC_V71, exclude=("__pycache__",))


def iter_v70_core_python_files() -> Iterable[Path]:
    if not SRC.is_dir():
        return iter(())
    return iter_python_files(SRC, exclude=("__pycache__", "core/v71/"))
