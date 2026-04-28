# V7.1 하네스 명세 (Harness Spec)

> 이 문서는 V7.1 시스템의 **7개 자동 검증 하네스**를 정의합니다.
> 
> 하네스는 코드 작성 시 **자동으로 검증·차단·강제**하는 도구입니다.
> 
> **충돌 금지 원칙(헌법 3)을 자동으로 강제하는 핵심 인프라입니다.**

---

## 목차

- [§0. 하네스 개요](#0-하네스-개요)
- [§1. 하네스 1: Naming Collision Detector](#1-하네스-1-naming-collision-detector)
- [§2. 하네스 2: Dependency Cycle Detector](#2-하네스-2-dependency-cycle-detector)
- [§3. 하네스 3: Trading Rule Enforcer](#3-하네스-3-trading-rule-enforcer)
- [§4. 하네스 4: Schema Migration Validator](#4-하네스-4-schema-migration-validator)
- [§5. 하네스 5: Feature Flag Enforcer](#5-하네스-5-feature-flag-enforcer)
- [§6. 하네스 6: Dead Code Detector](#6-하네스-6-dead-code-detector)
- [§7. 하네스 7: Test Coverage Enforcer](#7-하네스-7-test-coverage-enforcer)
- [§8. 통합 실행](#8-통합-실행)
- [§9. CI/CD 파이프라인](#9-cicd-파이프라인)

---

## §0. 하네스 개요

### 0.1 하네스란

```yaml
정의:
  자동 검증 시스템
  코드 작성/커밋/배포 시점에서 자동 검사
  위반 시 차단 또는 경고

목적:
  - 일관성 강제 (모든 코드 같은 룰)
  - 충돌 방지 (자동 검출)
  - 헌법 준수 (인간 검토 없이도)
  - 1인 개발 부담 감소

특징:
  - 기계적 검증 (사람 판단 X)
  - 명확한 통과/실패 기준
  - 빠른 피드백 (커밋 시점)
  - 우회 어려움 (--no-verify 사용 자제)
```

### 0.2 V7.1 하네스 7개

```yaml
1. Naming Collision Detector
   목적: V7.0 / V7.1 모듈 명명 충돌 차단
   실행: pre-commit
   수준: BLOCK

2. Dependency Cycle Detector
   목적: 순환 의존 차단
   실행: pre-commit + CI
   수준: BLOCK

3. Trading Rule Enforcer
   목적: 거래 룰 위반 차단 (매직 넘버, 스킬 우회)
   실행: pre-commit + CI
   수준: BLOCK

4. Schema Migration Validator
   목적: 안전하지 않은 DB 변경 차단
   실행: pre-commit + CI
   수준: BLOCK

5. Feature Flag Enforcer
   목적: V7.1 기능 Flag 보호 강제
   실행: pre-commit + CI
   수준: WARN (WARN으로 시작, BLOCK으로 강화 가능)

6. Dead Code Detector
   목적: 삭제 대상 모듈 잔존 import 감지
   실행: pre-commit + CI
   수준: BLOCK (Phase 1 완료 후)

7. Test Coverage Enforcer
   목적: 테스트 커버리지 강제
   실행: CI (pytest --cov)
   수준: BLOCK
```

### 0.3 실행 시점

```yaml
Pre-commit (로컬, 커밋 직전):
  하네스 1, 2, 3, 4, 5, 6
  - 빠른 피드백
  - 잘못된 코드 커밋 방지

CI/CD (서버, push 시):
  하네스 1~7 모두
  - 강제 검증
  - 머지 차단

수동 실행:
  python -m harness.run_all
  - 개발 중 즉시 검증
```

### 0.4 하네스 우회 방지

```yaml
원칙:
  --no-verify 사용 금지
  하네스 무시 PR 머지 금지
  
예외 (사유 명시 필수):
  긴급 핫픽스 (단, 다음 PR에서 보정)
  하네스 자체 버그 (별도 이슈)

기록:
  하네스 우회 시 audit_log 또는 Git commit message에 사유 명시
```

---

## §1. 하네스 1: Naming Collision Detector

### 1.1 목적

```yaml
V7.0 / V7.1 모듈/클래스/함수의 명명 충돌 자동 감지.

검사 대상:
  - 새 클래스가 V7.0에 같은 이름 존재?
  - 새 모듈 경로가 V7.0과 겹치는지?
  - V71 접두사 또는 v71/ 패키지 격리?

이유:
  - 충돌 금지 원칙 (헌법 3)
  - V7.0 운영 영향 방지
  - import 혼동 방지
```

### 1.2 검출 룰

```yaml
규칙 1: V7.1 클래스는 V71 접두사 또는 v71/ 패키지 안에
  V7.0과 겹치는 클래스명 발견 시 BLOCK
  
  예시 BLOCK:
    src/core/position_manager.py: PositionManager (V7.0)
    src/core/v71/position/position_manager.py: PositionManager  ← 충돌!
  
  예시 PASS:
    src/core/v71/position/v71_position_manager.py: V71PositionManager
    또는
    src/core/v71/position/manager.py: PositionManager  
      ← v71/ 패키지 안이므로 OK

규칙 2: V7.0 모듈 직접 수정 최소화
  V7.0 파일의 클래스/함수에 큰 변경 시 경고
  단, 인프라 모듈 (api/, database/) 의 점진 확장은 허용

규칙 3: V7.1 신규 모듈은 src/core/v71/ 또는 src/web/ 에만
  외부 위치에 V7.1 코드 배치 시 BLOCK

규칙 4: 데이터베이스 테이블/컬럼 명명
  ENUM 값 V7.1 추가는 자유 (V71_ 접두사 불필요)
  새 테이블도 자연스러운 이름 (V71_ 접두사 불필요)
  단, 기존 컬럼과 의미 충돌 안 되게
```

### 1.3 구현

```python
# scripts/harness/naming_collision_detector.py

"""
하네스 1: Naming Collision Detector

AST 분석으로 V7.0 / V7.1 명명 충돌 검출.
pre-commit hook으로 실행.
"""

import ast
import sys
from pathlib import Path
from typing import Set, Tuple, List
from dataclasses import dataclass


@dataclass
class ClassDefinition:
    """발견된 클래스 정의."""
    name: str
    file_path: Path
    line: int
    is_v71_namespace: bool  # v71/ 패키지 안인지


def collect_class_definitions(directory: Path) -> List[ClassDefinition]:
    """디렉토리 내 모든 클래스 정의 수집."""
    definitions = []
    
    for py_file in directory.rglob("*.py"):
        # 무시 패턴
        if any(part in py_file.parts for part in ["__pycache__", ".pytest_cache", "tests"]):
            continue
        
        try:
            tree = ast.parse(py_file.read_text(encoding='utf-8'))
        except SyntaxError:
            continue  # 파싱 불가 파일은 다른 도구가 잡음
        
        is_v71 = "v71" in py_file.parts
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                definitions.append(ClassDefinition(
                    name=node.name,
                    file_path=py_file,
                    line=node.lineno,
                    is_v71_namespace=is_v71,
                ))
    
    return definitions


def detect_collisions(definitions: List[ClassDefinition]) -> List[Tuple[ClassDefinition, ClassDefinition]]:
    """클래스명 충돌 검출."""
    collisions = []
    
    # 클래스명별 그룹
    by_name = {}
    for d in definitions:
        by_name.setdefault(d.name, []).append(d)
    
    for name, defs in by_name.items():
        if len(defs) <= 1:
            continue
        
        # V7.0 + V7.1 (v71 패키지 외부) 충돌 검사
        v70_defs = [d for d in defs if not d.is_v71_namespace]
        v71_outside_defs = [d for d in defs if d.is_v71_namespace]
        
        # v71 패키지 내부의 같은 이름은 OK (격리됨)
        # v71 패키지 외부 + V7.0 같은 이름이면 충돌
        if len(v70_defs) > 0:
            for v71_def in v71_outside_defs:
                # v71_outside_defs는 v71 패키지 안이므로 격리됨
                # 그러나 V71 접두사 있으면 더 명확
                if not v71_def.name.startswith("V71"):
                    # 격리됐으나 명명 모호
                    pass  # 경고만 (v71/ 패키지 격리로 해결)
        
        # 같은 이름이 v71 외부 + V7.0 (또는 둘 다 v71 외부)
        outside_v71 = [d for d in defs if not d.is_v71_namespace]
        if len(outside_v71) > 1:
            # v71 외부에 같은 이름 둘 이상
            for i in range(len(outside_v71)):
                for j in range(i + 1, len(outside_v71)):
                    collisions.append((outside_v71[i], outside_v71[j]))
    
    return collisions


def main():
    """하네스 1 실행."""
    src_dir = Path("src")
    
    if not src_dir.exists():
        print("ERROR: src/ directory not found")
        sys.exit(1)
    
    definitions = collect_class_definitions(src_dir)
    collisions = detect_collisions(definitions)
    
    if not collisions:
        print(f"✅ Naming Collision Detector: PASS ({len(definitions)} classes scanned)")
        sys.exit(0)
    
    print("=" * 70)
    print("HARNESS 1: NAMING COLLISION DETECTED")
    print("=" * 70)
    
    for d1, d2 in collisions:
        print(f"\n❌ Class '{d1.name}' defined in multiple locations:")
        print(f"   - {d1.file_path}:{d1.line}")
        print(f"   - {d2.file_path}:{d2.line}")
        print(f"\n   FIX:")
        if "v71" in str(d1.file_path) or "v71" in str(d2.file_path):
            print(f"   Add V71 prefix or move into src/core/v71/ package")
        else:
            print(f"   Rename one of them to avoid collision")
    
    print("\n" + "=" * 70)
    print(f"BUILD STATUS: BLOCKED ({len(collisions)} collisions)")
    print("REFERENCE: 04_ARCHITECTURE.md §0.1 (격리 원칙)")
    print("=" * 70)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

### 1.4 pre-commit hook 설정

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: naming-collision-detector
        name: Naming Collision Detector (Harness 1)
        entry: python scripts/harness/naming_collision_detector.py
        language: system
        pass_filenames: false
        always_run: true
```

### 1.5 차단 예시

```
입력 코드:
  src/core/position_manager.py:
    class PositionManager:
        ...
  
  src/core/v71/position/manager.py:
    class PositionManager:  # ← 충돌!
        ...

하네스 출력:
======================================================================
HARNESS 1: NAMING COLLISION DETECTED
======================================================================

❌ Class 'PositionManager' defined in multiple locations:
   - src/core/position_manager.py:15
   - src/core/v71/position/manager.py:23
   
   FIX:
   v71/ 패키지 격리는 됐으나 import 혼동 가능성.
   권장:
     class V71PositionManager:  # V71 접두사
   또는
     # 명시적 import 사용
     from src.core.v71.position.manager import PositionManager as V71PositionManager

BUILD STATUS: BLOCKED (1 collisions)
REFERENCE: 04_ARCHITECTURE.md §0.1 (격리 원칙)
======================================================================
```

---

## §2. 하네스 2: Dependency Cycle Detector

### 2.1 목적

```yaml
순환 의존성 자동 검출.

검사 대상:
  - 모듈 간 import 그래프
  - 직접 순환 (A → B → A)
  - 간접 순환 (A → B → C → A)
  - V7.0 ↔ V7.1 의존 방향

이유:
  - 의존성 단방향 보장 (V7.1 → V7.0)
  - 순환 방지 (테스트 어려움)
  - 격리 검증
```

### 2.2 검출 룰

```yaml
규칙 1: 순환 의존 금지
  A → B → A (직접): BLOCK
  A → B → C → A (간접): BLOCK

규칙 2: V7.0 → V7.1 의존 금지
  V7.0 인프라 모듈이 V7.1 모듈 import 시 BLOCK
  
  예외:
    main.py에서는 V7.1 import OK (코디네이터)

규칙 3: 코어 모듈 외부 의존 최소화
  src/core/v71/skills/ 는 외부 의존 없음 (가장 하위)
  단, src/utils/, src/database/ 등 인프라는 OK

규칙 4: 외부 라이브러리 의존
  검사 안 함 (외부 패키지)
```

### 2.3 구현

```python
# scripts/harness/dependency_cycle_detector.py

"""
하네스 2: Dependency Cycle Detector

import 그래프 분석.
pydeps 또는 직접 AST 분석.
"""

import ast
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, List


def extract_imports(file_path: Path) -> Set[str]:
    """파일에서 import된 내부 모듈 추출."""
    imports = set()
    
    try:
        tree = ast.parse(file_path.read_text(encoding='utf-8'))
    except SyntaxError:
        return imports
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src."):
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("src."):
                imports.add(node.module)
    
    return imports


def file_to_module(file_path: Path) -> str:
    """파일 경로 → 모듈 경로."""
    parts = file_path.with_suffix("").parts
    return ".".join(parts)


def build_dependency_graph(directory: Path) -> Dict[str, Set[str]]:
    """의존성 그래프 구축."""
    graph = defaultdict(set)
    
    for py_file in directory.rglob("*.py"):
        if any(p in py_file.parts for p in ["__pycache__", "tests"]):
            continue
        
        module_name = file_to_module(py_file)
        imports = extract_imports(py_file)
        graph[module_name] = imports
    
    return graph


def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """순환 의존 검출 (DFS)."""
    cycles = []
    
    def dfs(node: str, visited: Set[str], stack: List[str]):
        if node in stack:
            cycle_start = stack.index(node)
            cycle = stack[cycle_start:] + [node]
            cycles.append(cycle)
            return
        
        if node in visited:
            return
        
        visited.add(node)
        stack.append(node)
        
        for neighbor in graph.get(node, set()):
            dfs(neighbor, visited, stack)
        
        stack.pop()
    
    visited = set()
    for node in graph:
        dfs(node, visited, [])
    
    # 중복 제거 (회전된 같은 사이클)
    unique_cycles = []
    seen = set()
    for cycle in cycles:
        # canonical form: 가장 작은 노드를 시작으로
        if not cycle:
            continue
        min_idx = cycle.index(min(cycle[:-1]))  # 마지막은 시작과 같음
        canonical = tuple(cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]])
        if canonical not in seen:
            seen.add(canonical)
            unique_cycles.append(list(canonical))
    
    return unique_cycles


def check_v70_to_v71_dependency(graph: Dict[str, Set[str]]) -> List[tuple]:
    """V7.0 → V7.1 의존 검출."""
    violations = []
    
    for module, deps in graph.items():
        # V7.0 인프라 모듈 (v71 안 아님 + main 아님)
        if "v71" in module or module.endswith(".main"):
            continue
        
        # V7.1 모듈에 의존?
        for dep in deps:
            if "v71" in dep:
                violations.append((module, dep))
    
    return violations


def main():
    src_dir = Path("src")
    
    graph = build_dependency_graph(src_dir)
    cycles = find_cycles(graph)
    v70_to_v71 = check_v70_to_v71_dependency(graph)
    
    if not cycles and not v70_to_v71:
        print(f"✅ Dependency Cycle Detector: PASS ({len(graph)} modules)")
        sys.exit(0)
    
    print("=" * 70)
    print("HARNESS 2: DEPENDENCY VIOLATIONS")
    print("=" * 70)
    
    if cycles:
        print(f"\n❌ {len(cycles)} circular dependencies found:\n")
        for cycle in cycles:
            print("   " + " → ".join(cycle))
    
    if v70_to_v71:
        print(f"\n❌ {len(v70_to_v71)} V7.0 → V7.1 dependencies (forbidden):\n")
        for v70, v71 in v70_to_v71:
            print(f"   {v70} → {v71}")
        print("\n   V7.0 인프라는 V7.1을 import할 수 없습니다.")
        print("   허용: V7.1 → V7.0 인프라 (단방향)")
    
    print("\n" + "=" * 70)
    print("BUILD STATUS: BLOCKED")
    print("REFERENCE: 04_ARCHITECTURE.md §5 (의존성 그래프)")
    print("=" * 70)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

### 2.4 차단 예시 (historical — V7.0 폐기 전 시점)

> **Phase A 완료 (2026-04-28)**: V7.0은 완전 폐기되었으므로 V7.0 → V7.1 import 패턴 자체가 발생할 수 없습니다. 본 예시는 마이그레이션 기간 중 의존성 단방향 보장이 필요했던 historical reference입니다. 현재는 V7.1 내부 순환 의존만 검사합니다.

```
[과거 마이그레이션 시점] 입력:
  src/core/candle_builder.py:                      # V7.0 (이제 폐기됨)
    from src.core.v71.box.box_manager import V71BoxManager  # V7.0 → V7.1!

  src/core/v71/box/box_manager.py:
    from src.core.candle_builder import CandleBuilder

하네스 출력:
======================================================================
HARNESS 2: DEPENDENCY VIOLATIONS
======================================================================

❌ 1 V7.0 → V7.1 dependencies (forbidden):

   src.core.candle_builder → src.core.v71.box.box_manager

   V7.0 인프라는 V7.1을 import할 수 없습니다.
   허용: V7.1 → V7.0 인프라 (단방향)

BUILD STATUS: BLOCKED
REFERENCE: 04_ARCHITECTURE.md §5 (의존성 그래프)
======================================================================
```

---

## §3. 하네스 3: Trading Rule Enforcer

### 3.1 목적

```yaml
거래 룰 위반 자동 차단.

검사 대상:
  - 매직 넘버 (-0.05, 0.30 등)
  - raw API 호출 (httpx.post)
  - raw telegram 호출
  - 평단가 직접 수정
  - 스킬 우회

이유:
  - 룰 일관성
  - 휴먼 에러 방지
  - 스킬 사용 강제
```

### 3.2 검출 룰

```yaml
규칙 1: 거래 매직 넘버 금지
  거래 관련 코드에 다음 패턴 발견 시 BLOCK:
    -0.05, -0.02, 0.04 (손절선)
    0.05, 0.10 (익절)
    0.30 (청산 비율)
    0.20 (자동 이탈)
    4.0, 3.0, 2.5, 2.0 (ATR 배수)
    30 (한도 비중)
    5 (갭업 한도)
    3 (VI 갭 한도)
  
  허용:
    V71Constants.* 사용
    또는 문자열 (메시지 등)
    또는 docstring
    또는 주석

규칙 2: Raw API 호출 금지
  거래 모듈에서:
    - import httpx (단, src/api/ 외부에서)
    - requests.post / requests.get (직접)
    - 키움 API URL 직접 사용
  
  허용:
    from src.core.v71.skills.kiwoom_api_skill import ...

규칙 3: Raw 알림 금지
  거래 모듈에서:
    - telegram.send_message() 직접
    - bot.send() 직접
  
  허용:
    from src.core.v71.skills.notification_skill import send_notification

규칙 4: 평단가 직접 수정 금지
  - position.weighted_avg_price = ...
  - position.fixed_stop_price = ...
  
  허용:
    from src.core.v71.skills.avg_price_skill import update_position_after_buy

규칙 5: 손절 우회 금지
  - 강제 매도 코드 (조건 검증 없이)
  - calculate_effective_stop() 호출 없이 매도
```

### 3.3 구현

```python
# scripts/harness/trading_rule_enforcer.py

"""
하네스 3: Trading Rule Enforcer

거래 룰 위반 정적 분석.
"""

import ast
import sys
import re
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass


# 차단할 매직 넘버 (거래 관련)
TRADING_MAGIC_NUMBERS = {
    -0.05, -0.02, 0.04,
    0.05, 0.10,
    0.30,
    0.20,
    4.0, 3.0, 2.5, 2.0,
    30, 5, 3,
}

# 거래 모듈 패턴 (이 모듈들에서 매직 넘버 검사)
TRADING_MODULE_PATTERNS = [
    "src/core/v71/box/",
    "src/core/v71/strategies/",
    "src/core/v71/exit/",
    "src/core/v71/position/",
    "src/core/v71/path_manager.py",
    "src/core/v71/vi_monitor.py",
    "src/core/wave_harvest_exit.py",
]


@dataclass
class Violation:
    file_path: Path
    line: int
    rule: str
    detail: str


def is_trading_module(file_path: Path) -> bool:
    """거래 관련 모듈인가?"""
    path_str = str(file_path)
    return any(pattern in path_str for pattern in TRADING_MODULE_PATTERNS)


def check_magic_numbers(file_path: Path, tree: ast.AST) -> List[Violation]:
    """매직 넘버 검출."""
    if not is_trading_module(file_path):
        return []  # 거래 모듈에서만 검사
    
    violations = []
    
    for node in ast.walk(tree):
        # 숫자 리터럴
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value in TRADING_MAGIC_NUMBERS:
                # 부모 컨텍스트 확인 (V71Constants 정의면 OK)
                violations.append(Violation(
                    file_path=file_path,
                    line=node.lineno,
                    rule="MAGIC_NUMBER",
                    detail=f"Trading magic number: {node.value} (use V71Constants)",
                ))
    
    return violations


def check_raw_api_calls(file_path: Path, source: str) -> List[Violation]:
    """Raw API 호출 검출."""
    violations = []
    
    # src/api/ 내부는 허용 (인프라)
    if "src/api/" in str(file_path):
        return []
    
    # 거래 모듈에서만
    if not is_trading_module(file_path):
        return []
    
    # 패턴 검색
    patterns = [
        (r"import\s+httpx", "Raw httpx import"),
        (r"import\s+requests", "Raw requests import"),
        (r"httpx\.(post|get|put|delete)", "Raw httpx call"),
        (r"requests\.(post|get|put|delete)", "Raw requests call"),
        (r"api\.kiwoom\.com", "Direct kiwoom URL"),
    ]
    
    for line_no, line in enumerate(source.splitlines(), 1):
        # 주석 제외
        code_part = line.split('#')[0]
        for pattern, desc in patterns:
            if re.search(pattern, code_part):
                violations.append(Violation(
                    file_path=file_path,
                    line=line_no,
                    rule="RAW_API_CALL",
                    detail=f"{desc} (use kiwoom_api_skill)",
                ))
    
    return violations


def check_raw_notification(file_path: Path, source: str) -> List[Violation]:
    """Raw 알림 호출 검출."""
    violations = []
    
    # src/notification/ 내부는 허용
    if "src/notification/" in str(file_path):
        return []
    
    if not is_trading_module(file_path):
        return []
    
    patterns = [
        (r"telegram\.send_message", "Raw telegram call"),
        (r"bot\.send_message", "Raw bot call"),
        (r"\.send_message\(.*chat_id", "Direct chat_id usage"),
    ]
    
    for line_no, line in enumerate(source.splitlines(), 1):
        code_part = line.split('#')[0]
        for pattern, desc in patterns:
            if re.search(pattern, code_part):
                violations.append(Violation(
                    file_path=file_path,
                    line=line_no,
                    rule="RAW_NOTIFICATION",
                    detail=f"{desc} (use notification_skill)",
                ))
    
    return violations


def check_direct_position_modification(file_path: Path, source: str) -> List[Violation]:
    """평단가/손절선 직접 수정 검출."""
    if not is_trading_module(file_path):
        return []
    
    # avg_price_skill.py 자체는 예외
    if "avg_price_skill" in str(file_path):
        return []
    if "exit_calc_skill" in str(file_path):
        return []
    
    violations = []
    patterns = [
        (r"\.weighted_avg_price\s*=", "Direct weighted_avg_price modification"),
        (r"\.fixed_stop_price\s*=", "Direct fixed_stop_price modification"),
        (r"\.ts_stop_price\s*=", "Direct ts_stop_price modification"),
        (r"\.ts_base_price\s*=", "Direct ts_base_price modification"),
    ]
    
    for line_no, line in enumerate(source.splitlines(), 1):
        code_part = line.split('#')[0]
        for pattern, desc in patterns:
            if re.search(pattern, code_part):
                violations.append(Violation(
                    file_path=file_path,
                    line=line_no,
                    rule="DIRECT_POSITION_MOD",
                    detail=f"{desc} (use avg_price_skill)",
                ))
    
    return violations


def main():
    src_dir = Path("src")
    all_violations = []
    
    for py_file in src_dir.rglob("*.py"):
        if any(p in py_file.parts for p in ["__pycache__", "tests"]):
            continue
        
        try:
            source = py_file.read_text(encoding='utf-8')
            tree = ast.parse(source)
        except SyntaxError:
            continue
        
        all_violations.extend(check_magic_numbers(py_file, tree))
        all_violations.extend(check_raw_api_calls(py_file, source))
        all_violations.extend(check_raw_notification(py_file, source))
        all_violations.extend(check_direct_position_modification(py_file, source))
    
    if not all_violations:
        print("✅ Trading Rule Enforcer: PASS")
        sys.exit(0)
    
    print("=" * 70)
    print(f"HARNESS 3: TRADING RULE VIOLATIONS ({len(all_violations)})")
    print("=" * 70)
    
    for v in all_violations:
        print(f"\n❌ [{v.rule}] {v.file_path}:{v.line}")
        print(f"   {v.detail}")
    
    print("\n" + "=" * 70)
    print("BUILD STATUS: BLOCKED")
    print("REFERENCE:")
    print("  - 02_TRADING_RULES.md §5, §6 (룰)")
    print("  - 07_SKILLS_SPEC.md (스킬 사용)")
    print("  - 02_TRADING_RULES.md 부록 A.4 (V71Constants)")
    print("=" * 70)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

### 3.4 화이트리스트 메커니즘

```python
# 일부 라인은 의도적으로 매직 넘버 사용 가능
# 주석으로 명시:
#   # noqa: HARNESS3
# 또는 V71Constants 정의 파일은 자동 제외:
#   src/core/v71/v71_constants.py
```

---

## §4. 하네스 4: Schema Migration Validator

### 4.1 목적

```yaml
DB 스키마 변경 안전성 자동 검증.

검사 대상:
  - 마이그레이션 파일 (src/database/migrations/v71/)
  - DOWN 마이그레이션 존재
  - 데이터 손실 위험 변경
  - 호환 가능 변경

이유:
  - 데이터 안전
  - 롤백 가능성
  - 운영 무중단
```

### 4.2 검출 룰

```yaml
규칙 1: UP/DOWN 양방향 필수
  001_create_xxx.up.sql 있으면
  001_create_xxx.down.sql 도 필요
  
  없으면 BLOCK

규칙 2: 위험한 SQL 차단
  ALTER TABLE ... DROP COLUMN: BLOCK (deprecation 절차 필요)
  DROP TABLE: BLOCK
  TRUNCATE: BLOCK
  컬럼 타입 호환 안 되는 변경: BLOCK
  
  허용:
    ADD COLUMN with NULL or DEFAULT
    CREATE TABLE
    CREATE INDEX
    새 ENUM 값 추가

규칙 3: NOT NULL 추가 시 검증
  기존 데이터에 NULL 있을 가능성
  마이그레이션에 UPDATE 포함되어야 함:
    ALTER TABLE ... ADD COLUMN xxx;
    UPDATE table SET xxx = default WHERE xxx IS NULL;
    ALTER TABLE ... ALTER COLUMN xxx SET NOT NULL;

규칙 4: 명명 규칙
  파일명: NNN_action_description.up.sql / .down.sql
  순번 충돌 안 되게
```

### 4.3 구현

```python
# scripts/harness/schema_migration_validator.py

"""
하네스 4: Schema Migration Validator

DB 마이그레이션 파일 검증.
"""

import re
import sys
from pathlib import Path
from typing import List


def check_up_down_pairs(migration_dir: Path) -> List[str]:
    """UP/DOWN 페어 체크."""
    violations = []
    
    if not migration_dir.exists():
        return []
    
    up_files = sorted(migration_dir.glob("*.up.sql"))
    down_files = sorted(migration_dir.glob("*.down.sql"))
    
    up_names = {f.stem.replace(".up", "") for f in up_files}
    down_names = {f.stem.replace(".down", "") for f in down_files}
    
    missing_down = up_names - down_names
    missing_up = down_names - up_names
    
    for name in missing_down:
        violations.append(f"Missing DOWN migration: {name}.down.sql")
    for name in missing_up:
        violations.append(f"Missing UP migration: {name}.up.sql")
    
    return violations


def check_dangerous_sql(migration_dir: Path) -> List[str]:
    """위험한 SQL 검출."""
    violations = []
    
    DANGEROUS_PATTERNS = [
        (r"DROP\s+TABLE\s+(?!IF\s+EXISTS)", "DROP TABLE without IF EXISTS"),
        # DROP TABLE IF EXISTS는 DOWN에서 OK
    ]
    
    UP_DANGEROUS = [
        (r"ALTER\s+TABLE\s+\w+\s+DROP\s+COLUMN", 
         "DROP COLUMN in UP migration (use deprecation)"),
        (r"^\s*DROP\s+TABLE\b", "DROP TABLE in UP migration"),
        (r"TRUNCATE", "TRUNCATE detected"),
    ]
    
    for sql_file in migration_dir.glob("*.sql"):
        is_up = ".up.sql" in sql_file.name
        
        try:
            content = sql_file.read_text(encoding='utf-8')
        except Exception:
            continue
        
        # 주석 제거 (단순)
        content_no_comments = re.sub(r"--[^\n]*", "", content)
        
        if is_up:
            for pattern, desc in UP_DANGEROUS:
                if re.search(pattern, content_no_comments, re.IGNORECASE):
                    violations.append(f"{sql_file}: {desc}")
        
        for pattern, desc in DANGEROUS_PATTERNS:
            if re.search(pattern, content_no_comments, re.IGNORECASE):
                violations.append(f"{sql_file}: {desc}")
    
    return violations


def check_not_null_safety(migration_dir: Path) -> List[str]:
    """NOT NULL 추가 시 안전성 검증."""
    violations = []
    
    for sql_file in migration_dir.glob("*.up.sql"):
        try:
            content = sql_file.read_text(encoding='utf-8')
        except Exception:
            continue
        
        # ADD COLUMN ... NOT NULL 패턴
        add_not_null = re.findall(
            r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)\s+[\w\(\)\,]*\s+NOT\s+NULL\s*(?!\s+DEFAULT)",
            content,
            re.IGNORECASE,
        )
        
        for table, column in add_not_null:
            # DEFAULT 값 없이 NOT NULL이면 위험
            violations.append(
                f"{sql_file}: ADD COLUMN {table}.{column} NOT NULL without DEFAULT "
                f"(existing rows will fail)"
            )
    
    return violations


def main():
    migration_dir = Path("src/database/migrations/v71")
    
    if not migration_dir.exists():
        print("⏭️  Schema Migration Validator: SKIP (no v71 migrations yet)")
        sys.exit(0)
    
    violations = []
    violations.extend(check_up_down_pairs(migration_dir))
    violations.extend(check_dangerous_sql(migration_dir))
    violations.extend(check_not_null_safety(migration_dir))
    
    if not violations:
        print("✅ Schema Migration Validator: PASS")
        sys.exit(0)
    
    print("=" * 70)
    print(f"HARNESS 4: SCHEMA MIGRATION VIOLATIONS ({len(violations)})")
    print("=" * 70)
    
    for v in violations:
        print(f"\n❌ {v}")
    
    print("\n" + "=" * 70)
    print("BUILD STATUS: BLOCKED")
    print("REFERENCE: 03_DATA_MODEL.md §8 (마이그레이션 안전 룰)")
    print("=" * 70)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## §5. 하네스 5: Feature Flag Enforcer

### 5.1 목적

```yaml
V7.1 신규 기능이 Feature Flag로 보호되는지 검증.

검사 대상:
  - V7.1 모듈의 진입점 함수
  - is_enabled() 호출 패턴
  - Flag 정의 (config/feature_flags.yaml)

이유:
  - 점진적 활성화 보장
  - 문제 발생 시 즉시 비활성화
  - V7.0 운영 안전
```

### 5.2 검출 룰

```yaml
규칙 1: V7.1 진입점은 Flag 보호
  src/core/v71/ 의 public 함수 (밑줄 안 시작)
  처음 호출되는 곳에서 is_enabled() 체크 권장
  
  단, 모든 함수가 보호 필요한 건 아님:
    - skills/ 는 순수 함수 (불필요)
    - utility 함수도 불필요
    - 진입점 (이벤트 핸들러, 메인 루프)만 보호

규칙 2: Flag 정의 일치
  코드의 is_enabled('v71.xxx') 호출
  config/feature_flags.yaml에 'v71.xxx' 정의되어야

규칙 3: WARN 수준 (초기)
  너무 엄격하면 개발 방해
  WARN으로 시작하여 정착 후 BLOCK
```

### 5.3 구현

```python
# scripts/harness/feature_flag_enforcer.py

"""
하네스 5: Feature Flag Enforcer

V7.1 기능의 Flag 보호 검증.
WARN 수준으로 운영 (정착 후 BLOCK 전환).
"""

import ast
import yaml
import sys
from pathlib import Path
from typing import Set, List


def load_defined_flags() -> Set[str]:
    """config/feature_flags.yaml에서 정의된 Flag 로드."""
    flag_file = Path("config/feature_flags.yaml")
    if not flag_file.exists():
        return set()
    
    with open(flag_file) as f:
        config = yaml.safe_load(f)
    
    flags = set()
    
    def extract(prefix: str, d: dict):
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                extract(full_key, value)
            else:
                flags.add(full_key)
    
    extract("", config)
    return flags


def find_flag_calls(file_path: Path) -> List[tuple]:
    """is_enabled() 호출에서 사용된 Flag 추출."""
    flags_used = []
    
    try:
        tree = ast.parse(file_path.read_text(encoding='utf-8'))
    except SyntaxError:
        return []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # is_enabled('xxx') 패턴
            func = node.func
            if isinstance(func, ast.Name) and func.id == "is_enabled":
                if node.args and isinstance(node.args[0], ast.Constant):
                    flags_used.append((node.args[0].value, node.lineno))
    
    return flags_used


def main():
    src_dir = Path("src")
    
    defined_flags = load_defined_flags()
    
    if not defined_flags:
        print("⏭️  Feature Flag Enforcer: SKIP (no flags defined yet)")
        sys.exit(0)
    
    warnings = []
    
    for py_file in src_dir.rglob("*.py"):
        if any(p in py_file.parts for p in ["__pycache__", "tests"]):
            continue
        
        flags_used = find_flag_calls(py_file)
        
        for flag, line in flags_used:
            if flag not in defined_flags:
                warnings.append(
                    f"{py_file}:{line}: Flag '{flag}' not defined in feature_flags.yaml"
                )
    
    if not warnings:
        print(f"✅ Feature Flag Enforcer: PASS ({len(defined_flags)} flags defined)")
        sys.exit(0)
    
    print("=" * 70)
    print(f"HARNESS 5: FEATURE FLAG WARNINGS ({len(warnings)})")
    print("=" * 70)
    
    for w in warnings:
        print(f"\n⚠️  {w}")
    
    print("\n" + "=" * 70)
    print("BUILD STATUS: WARN (not blocking)")
    print("REFERENCE: 05_MIGRATION_PLAN.md §10 (Feature Flag 전략)")
    print("=" * 70)
    sys.exit(0)  # WARN이므로 통과


if __name__ == "__main__":
    main()
```

---

## §6. 하네스 6: Dead Code Detector

### 6.1 목적

```yaml
삭제 대상 모듈의 잔존 import 감지.

검사 대상:
  - 삭제 예정 V6 모듈 import
  - 폐기된 V7 신호 시스템 import
  - 백테스트 모듈 import
  - OpenClaw 관련 코드

이유:
  - 의존성 추적
  - 안전한 삭제 보장
  - 코드 베이스 정리
```

### 6.2 검출 룰

```yaml
규칙 1: 삭제 대상 import 차단
  다음 모듈 import 시 BLOCK:
    - src.core.signal_pool
    - src.core.signal_detector_purple
    - src.core.v7_signal_coordinator
    - src.core.indicator_purple
    - src.core.strategies.v6_sniper_trap
    - src.core.strategies.v7_purple_reabs
    - src.core.exit_manager
    - src.core.auto_screener
    - src.core.atr_alert_manager
    - src.core.condition_search_handler
    - src.core.missed_signal_tracker
    - src.core.watermark_manager
    - src.core.strategy_orchestrator
    - src.core.signal_processor
    - src.core.signal_detector
    - src.core.indicator
    - backtest_modules
  
  Phase 1 완료 후 활성화 (그 전엔 WARN)

규칙 2: V7 관련 키워드 감지
  - PurpleScore, PurpleOK
  - Dual-Pass, dual_pass
  - SNIPER_TRAP
  - 백테스트 함수명

규칙 3: OpenClaw 관련
  - openclaw 키워드
  - kiwoom_ranking.sh 참조
  - ~/.openclaw/ 경로
```

### 6.3 구현

```python
# scripts/harness/dead_code_detector.py

"""
하네스 6: Dead Code Detector

삭제 대상 모듈의 잔존 import 감지.
Phase 1 진행 후 BLOCK으로 강화.
"""

import re
import sys
from pathlib import Path
from typing import List


# Phase 1 삭제 대상
DEAD_MODULES = [
    "src.core.signal_pool",
    "src.core.signal_detector_purple",
    "src.core.v7_signal_coordinator",
    "src.core.indicator_purple",
    "src.core.strategies.v6_sniper_trap",
    "src.core.strategies.v7_purple_reabs",
    "src.core.exit_manager",
    "src.core.auto_screener",
    "src.core.atr_alert_manager",
    "src.core.condition_search_handler",
    "src.core.missed_signal_tracker",
    "src.core.watermark_manager",
    "src.core.strategy_orchestrator",
    "src.core.signal_processor",
    "src.core.signal_detector",
    "src.core.indicator",
]

DEAD_KEYWORDS = [
    "PurpleScore",
    "PurpleOK",
    "SNIPER_TRAP",
    "openclaw",
    "kiwoom_ranking",
    "Dual-Pass",
    "DualPass",
]


def check_dead_imports(file_path: Path) -> List[str]:
    """삭제 대상 모듈 import 검출."""
    violations = []
    
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception:
        return []
    
    for line_no, line in enumerate(content.splitlines(), 1):
        # 주석 제외
        if line.strip().startswith("#"):
            continue
        
        # import 패턴
        for module in DEAD_MODULES:
            patterns = [
                f"from {module} import",
                f"import {module}",
                f"from {module}.",
            ]
            for pat in patterns:
                if pat in line:
                    violations.append(
                        f"{file_path}:{line_no}: Dead module import: {module}"
                    )
        
        # 키워드 검사
        for keyword in DEAD_KEYWORDS:
            if keyword in line and not line.strip().startswith(("#", '"""', "'''")):
                violations.append(
                    f"{file_path}:{line_no}: Dead code keyword: '{keyword}'"
                )
    
    return violations


def main():
    src_dir = Path("src")
    
    # Phase 1 진행 상태 확인 (간단)
    # 실제로는 .phase 파일 또는 git tag 체크
    is_phase1_complete = Path(".phase1_complete").exists()
    
    all_violations = []
    
    for py_file in src_dir.rglob("*.py"):
        if any(p in py_file.parts for p in ["__pycache__"]):
            continue
        
        violations = check_dead_imports(py_file)
        all_violations.extend(violations)
    
    if not all_violations:
        print("✅ Dead Code Detector: PASS")
        sys.exit(0)
    
    level = "BLOCK" if is_phase1_complete else "WARN"
    
    print("=" * 70)
    print(f"HARNESS 6: DEAD CODE DETECTED ({len(all_violations)})")
    print(f"LEVEL: {level}")
    print("=" * 70)
    
    for v in all_violations:
        print(f"\n❌ {v}")
    
    print("\n" + "=" * 70)
    print(f"BUILD STATUS: {level}")
    print("REFERENCE: 05_MIGRATION_PLAN.md §3 (Phase 1 인프라 정리)")
    print("=" * 70)
    
    if level == "BLOCK":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
```

---

## §7. 하네스 7: Test Coverage Enforcer

### 7.1 목적

```yaml
테스트 커버리지 강제.

검사 대상:
  - 거래 로직: 90%+
  - 인프라: 80%+
  - 유틸: 70%+
  - 전체: 80%+

이유:
  - 코드 신뢰성
  - 회귀 방지
  - 리팩토링 안전
```

### 7.2 검출 룰

```yaml
거래 로직 (90%+ 필수):
  src/core/v71/box/
  src/core/v71/strategies/
  src/core/v71/exit/
  src/core/v71/position/
  src/core/v71/skills/
  src/core/wave_harvest_exit.py

인프라 (80%+ 필수):
  src/api/
  src/database/
  src/notification/
  src/core/v71/path_manager.py
  src/core/v71/vi_monitor.py

유틸리티 (70%+ 권장):
  src/utils/
  src/web/

면제:
  src/main.py (E2E 테스트로)
  __init__.py
  scripts/
```

### 7.3 구현

```python
# scripts/harness/test_coverage_enforcer.py

"""
하네스 7: Test Coverage Enforcer

pytest --cov 결과 분석.
"""

import sys
import json
import subprocess
from pathlib import Path


# 커버리지 임계치
THRESHOLDS = {
    "trading": {
        "patterns": [
            "src/core/v71/box/",
            "src/core/v71/strategies/",
            "src/core/v71/exit/",
            "src/core/v71/position/",
            "src/core/v71/skills/",
            "src/core/wave_harvest_exit.py",
        ],
        "min_coverage": 90.0,
    },
    "infrastructure": {
        "patterns": [
            "src/api/",
            "src/database/",
            "src/notification/",
            "src/core/v71/path_manager.py",
            "src/core/v71/vi_monitor.py",
        ],
        "min_coverage": 80.0,
    },
    "utility": {
        "patterns": [
            "src/utils/",
            "src/web/",
        ],
        "min_coverage": 70.0,
    },
}


def run_pytest_coverage() -> dict:
    """pytest --cov 실행, JSON 결과 파싱."""
    try:
        result = subprocess.run(
            ["pytest", "--cov=src", "--cov-report=json", "tests/v71/"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("❌ pytest not found")
        sys.exit(1)
    
    coverage_file = Path("coverage.json")
    if not coverage_file.exists():
        print("❌ coverage.json not generated")
        sys.exit(1)
    
    with open(coverage_file) as f:
        return json.load(f)


def check_thresholds(coverage_data: dict) -> list:
    """카테고리별 커버리지 검증."""
    violations = []
    
    files_data = coverage_data.get("files", {})
    
    for category, config in THRESHOLDS.items():
        # 해당 카테고리 파일들
        matching_files = {
            file_path: data
            for file_path, data in files_data.items()
            if any(pattern in file_path for pattern in config["patterns"])
        }
        
        if not matching_files:
            continue
        
        # 카테고리 평균 커버리지
        total_statements = sum(d["summary"]["num_statements"] for d in matching_files.values())
        total_covered = sum(d["summary"]["covered_lines"] for d in matching_files.values())
        
        if total_statements == 0:
            continue
        
        coverage_pct = (total_covered / total_statements) * 100
        
        if coverage_pct < config["min_coverage"]:
            violations.append({
                "category": category,
                "actual": coverage_pct,
                "required": config["min_coverage"],
                "files": list(matching_files.keys()),
            })
    
    return violations


def main():
    print("Running pytest --cov...")
    coverage_data = run_pytest_coverage()
    
    violations = check_thresholds(coverage_data)
    
    if not violations:
        print("✅ Test Coverage Enforcer: PASS")
        sys.exit(0)
    
    print("=" * 70)
    print(f"HARNESS 7: TEST COVERAGE BELOW THRESHOLD ({len(violations)} categories)")
    print("=" * 70)
    
    for v in violations:
        print(f"\n❌ Category: {v['category']}")
        print(f"   Required: {v['required']:.1f}%")
        print(f"   Actual:   {v['actual']:.1f}%")
        print(f"   Files: {len(v['files'])}")
    
    print("\n" + "=" * 70)
    print("BUILD STATUS: BLOCKED")
    print("REFERENCE: 06_AGENTS_SPEC.md §5 (Test Strategy)")
    print("=" * 70)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## §8. 통합 실행

### 8.1 통합 스크립트

```python
# scripts/harness/run_all.py

"""
모든 하네스 통합 실행.
"""

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
    # 하네스 7은 시간 오래 걸려 별도 실행 (CI에서)
]


def main():
    failed = []
    
    print("=" * 70)
    print("V7.1 HARNESS RUNNER")
    print("=" * 70)
    
    for name, script in HARNESSES:
        print(f"\n▶ {name}")
        print("-" * 70)
        
        result = subprocess.run(
            ["python", f"scripts/harness/{script}"],
            check=False,
        )
        
        if result.returncode != 0:
            failed.append(name)
    
    print("\n" + "=" * 70)
    
    if not failed:
        print(f"✅ ALL HARNESSES PASSED ({len(HARNESSES)})")
        sys.exit(0)
    else:
        print(f"❌ {len(failed)} HARNESSES FAILED:")
        for name in failed:
            print(f"   - {name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 8.2 pre-commit 통합

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: harness-1-naming
        name: Harness 1 - Naming Collision
        entry: python scripts/harness/naming_collision_detector.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
      
      - id: harness-2-dependency
        name: Harness 2 - Dependency Cycle
        entry: python scripts/harness/dependency_cycle_detector.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
      
      - id: harness-3-trading-rule
        name: Harness 3 - Trading Rule Enforcer
        entry: python scripts/harness/trading_rule_enforcer.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
      
      - id: harness-4-schema
        name: Harness 4 - Schema Migration
        entry: python scripts/harness/schema_migration_validator.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
      
      - id: harness-5-feature-flag
        name: Harness 5 - Feature Flag (WARN)
        entry: python scripts/harness/feature_flag_enforcer.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
      
      - id: harness-6-dead-code
        name: Harness 6 - Dead Code Detector
        entry: python scripts/harness/dead_code_detector.py
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
```

### 8.3 사용법

```bash
# 설치
pip install pre-commit
pre-commit install

# 모든 하네스 수동 실행
python scripts/harness/run_all.py

# 개별 하네스
python scripts/harness/trading_rule_enforcer.py

# pre-commit 우회 (비상 시만, 사유 기록)
git commit --no-verify -m "..."

# pre-commit 강제 실행
pre-commit run --all-files
```

---

## §9. CI/CD 파이프라인

### 9.1 GitHub Actions 예시

```yaml
# .github/workflows/harnesses.yml

name: V7.1 Harnesses

on:
  push:
    branches: [v71-development, main]
  pull_request:
    branches: [v71-development, main]

jobs:
  harnesses:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-asyncio
      
      - name: Harness 1 - Naming Collision
        run: python scripts/harness/naming_collision_detector.py
      
      - name: Harness 2 - Dependency Cycle
        run: python scripts/harness/dependency_cycle_detector.py
      
      - name: Harness 3 - Trading Rule
        run: python scripts/harness/trading_rule_enforcer.py
      
      - name: Harness 4 - Schema Migration
        run: python scripts/harness/schema_migration_validator.py
      
      - name: Harness 5 - Feature Flag (WARN)
        run: python scripts/harness/feature_flag_enforcer.py
      
      - name: Harness 6 - Dead Code
        run: python scripts/harness/dead_code_detector.py
      
      - name: Harness 7 - Test Coverage
        run: python scripts/harness/test_coverage_enforcer.py
      
      - name: Upload coverage
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: coverage-report
          path: coverage.json
```

### 9.2 머지 차단 조건

```yaml
GitHub branch protection:
  v71-development 브랜치:
    - Require status checks to pass
    - Required: Harnesses 1, 2, 3, 4, 6, 7
    - Optional (WARN): Harness 5
  
  main 브랜치:
    - 모든 하네스 통과 필수
    - 코드 리뷰 1명 이상
```

---

## 부록 A: 하네스 빠른 참조

| # | 이름 | 위치 | 수준 | 실행 |
|---|------|------|------|------|
| 1 | Naming Collision | `naming_collision_detector.py` | BLOCK | pre-commit |
| 2 | Dependency Cycle | `dependency_cycle_detector.py` | BLOCK | pre-commit |
| 3 | Trading Rule | `trading_rule_enforcer.py` | BLOCK | pre-commit |
| 4 | Schema Migration | `schema_migration_validator.py` | BLOCK | pre-commit |
| 5 | Feature Flag | `feature_flag_enforcer.py` | WARN | pre-commit |
| 6 | Dead Code | `dead_code_detector.py` | WARN→BLOCK | pre-commit |
| 7 | Test Coverage | `test_coverage_enforcer.py` | BLOCK | CI |

---

## 부록 B: 미정 사항

```yaml
B.1 하네스 도구 선택:
  - 직접 구현 (예시 코드)
  - 또는 기존 도구 활용:
    - pylint plugin
    - ruff
    - mypy
    - vulture (dead code)
    - pydeps (dependency graph)
  
  → 구현 시 선택

B.2 화이트리스트 메커니즘:
  - # noqa: HARNESS3 같은 주석으로 우회
  - 또는 별도 whitelist 파일

B.3 하네스 성능 최적화:
  - 변경 파일만 검사
  - 캐싱
  - 병렬 실행

B.4 하네스 자체의 테스트:
  - 메타 테스트
  - 실제 위반 코드로 검증
```

---

*이 문서는 V7.1 하네스의 단일 진실 원천입니다.*  
*하네스 추가/수정 시 이 문서 갱신 필수.*  
*하네스는 V7.1 헌법 5원칙을 자동으로 강제합니다.*

*최종 업데이트: 2026-04-25*
