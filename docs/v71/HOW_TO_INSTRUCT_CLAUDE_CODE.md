# Claude Code 작업 지시 가이드

> 이 문서는 박균호님이 **Claude Code에 V7.1 작업을 어떻게 위임할지** 알려주는 실전 가이드입니다.
> 
> PRD 패키지 검토가 끝났으므로, 이제 Claude Code에 단계별로 작업을 지시합니다.

---

## §0. 핵심 원칙

### 0.1 Claude Code의 특성

```yaml
Claude Code는:
  - 강력한 코딩 능력
  - 파일시스템 직접 접근
  - 그러나 "큰 그림"은 잊을 수 있음
  - 매 세션마다 컨텍스트 다시 로드 필요

따라서:
  - PRD를 매 세션 시작 시 읽도록 명시
  - 작업 단위를 작게 나누기 (Phase의 Task 단위)
  - 검증 단계 명시 (하네스 통과 확인 등)
  - 결정 사항은 PRD 우선 (Claude Code가 임의로 변경 X)
```

### 0.2 작업 위임의 3가지 모드

```yaml
모드 1: 단일 Task (가장 안전, 권장)
  예: "Phase 1.4: V6 SNIPER_TRAP 삭제만 진행"
  → 한 Task 끝나면 검수 → 다음 Task

모드 2: Phase 전체 (효율적, 검증 필요)
  예: "Phase 1 전체 진행"
  → Phase 끝나면 종합 검수
  
모드 3: 자율 진행 (위험, 권장 안 함)
  예: "Phase 1~3 알아서"
  → 추적 어려움
```

**권장: 모드 1 (Task 단위)로 시작 → 익숙해지면 모드 2**

---

## §1. Claude Code 첫 세션 (Phase 0)

### 1.1 초기 컨텍스트 설정 프롬프트

Claude Code 새 세션 시작 시 가장 처음 보내는 메시지:

```markdown
# V7.1 시스템 구현 작업 시작

당신은 K_stock_trading V7.1 시스템의 구현을 담당하는 Claude Code입니다.

## 사전 학습 (필수, 순서대로)

다음 문서를 정독하세요:

1. C:\K_stock_trading\docs\v71\README.md
2. C:\K_stock_trading\docs\v71\01_PRD_MAIN.md (전체 그림)
3. C:\K_stock_trading\docs\v71\00_CLAUDE_CODE_GENERATION_PROMPT.md (작업 지침)
4. C:\K_stock_trading\docs\v71\05_MIGRATION_PLAN.md §0~§2 (Phase 0)

## 헌법 5원칙 (절대 위반 금지)

1. 사용자 판단 불가침 (자동 추천 X)
2. NFR1 최우선 (박스 진입 < 1초)
3. 충돌 금지 ★ (V7.0 인프라 보존, V7.1은 src/core/v71/ 격리)
4. 시스템 계속 운영 (자동 정지 X)
5. 단순함 우선

## 작업 위임 방식

- 나(박균호)가 Task 단위로 지시합니다
- 임의 진행 금지, 매 Task마다 확인 받기
- 룰 변경 금지 (PRD가 단일 진실)
- 의문 발생 시 즉시 질문

## 응답 요청

위 문서를 모두 읽었다면 다음을 응답하세요:

1. PRD 패키지의 14개 문서 중 핵심 3개 (가장 중요한)
2. 헌법 5원칙 중 가장 강조되는 원칙
3. 첫 작업 (Phase 0) 시작 준비 상태

준비되면 시작 신호를 기다리세요.
```

### 1.2 응답 검증

Claude Code가 위 프롬프트에 답하면 다음을 확인:

```yaml
체크리스트:
  ☐ 14개 문서 모두 인지 (특히 02, 04, 10이 핵심)
  ☐ 헌법 3원칙 (충돌 금지)을 핵심으로 인식
  ☐ V7.1 격리 패키지 (src/core/v71/) 개념 이해
  ☐ Phase 0의 4가지 Task 인식 (P0.1~P0.4)
  ☐ 작업 위임 방식 (Task 단위) 이해

문제 있으면:
  "PRD 다시 읽고 정확히 답하세요"
  특히 02_TRADING_RULES.md와 04_ARCHITECTURE.md 강조
```

### 1.3 Phase 0 첫 Task 지시

```markdown
# Task: P0.1 - 전체 백업

## 참조 문서
05_MIGRATION_PLAN.md §2.1

## 작업 내용

1. Git 태그 생성:
   git tag v7.0-final-stable
   git push origin v7.0-final-stable

2. 코드 백업:
   프로젝트 전체 zip 파일로 백업
   위치: C:\backups\K_stock_trading_v70_final_20260425.zip

3. DB 스냅샷 안내:
   Supabase Dashboard에서 백업 다운로드 절차를 알려주세요
   (실제 다운로드는 사용자가 직접)

4. .env 파일 백업:
   .env 파일을 별도 위치에 복사 (시크릿 분리)
   위치: C:\backups\.env_v70_final_20260425

5. 현재 V7.0 운영 상태 기록:
   다음을 텍스트 파일로 정리:
   - 현재 추적 중 종목 (DB 조회)
   - 현재 보유 포지션
   - 미체결 주문
   
   파일: C:\K_stock_trading\docs\v71\WORK_LOG.md (신규 또는 추가)

## 완료 기준

- 모든 백업 완료 확인
- WORK_LOG.md에 P0.1 완료 기록
- 다음 Task (P0.2) 진행 준비

## 주의

- 코드 변경 없음 (백업만)
- 운영 중인 V7.0에 영향 X
- 진행 중 의문 시 즉시 질문
```

---

## §2. Phase별 작업 지시 패턴

### 2.1 Phase 1: 인프라 정리

각 Task별 프롬프트 템플릿. **순서대로 진행 필수.**

#### P1.1: OpenClaw 정리 (외부 시스템)

```markdown
# Task: P1.1 - OpenClaw 정리

## 참조
05_MIGRATION_PLAN.md §3.2

## 작업

1. 코드 베이스 영향 확인:
   grep -r "openclaw" C:\K_stock_trading\src
   grep -r "Gemini" C:\K_stock_trading\src
   grep -r "kiwoom_ranking" C:\K_stock_trading\src
   
   결과 보고

2. 문서 정리:
   - C:\K_stock_trading\docs\OPENCLAW_GUIDE.md 삭제
   - C:\K_stock_trading\CLAUDE.md에서 OpenClaw Part 0 섹션 삭제
   
3. 외부 시스템 정리는 사용자가 직접:
   ~/.openclaw/ 디렉토리
   Scheduled Task "OpenClaw Gateway"
   → 안내만 출력하고 종료

## 완료 기준

- grep 결과 0건 (코드 베이스 영향 없음)
- 문서 2개 정리 완료
- WORK_LOG.md 갱신
```

#### P1.2: 백테스트 시스템 삭제

```markdown
# Task: P1.2 - 백테스트 시스템 삭제

## 참조
05_MIGRATION_PLAN.md §3.3

## 사전 의존성 분석 (필수)

먼저 다음을 실행하고 결과 보고:

grep -r "backtest" C:\K_stock_trading\src
grep -r "from backtest_modules" C:\K_stock_trading\src
grep -r "import.*backtest" C:\K_stock_trading\src

→ 다른 코드가 백테스트를 import하는지 확인
→ 영향이 있으면 멈추고 사용자에게 보고

## 작업 (영향 없을 시만)

1. 파일 삭제:
   - C:\K_stock_trading\run_backtest_ui.py
   - C:\K_stock_trading\scripts\backtest\ (전체)
   - C:\K_stock_trading\backtest_modules\ (있다면)

2. 캐시 삭제:
   - C:\K_stock_trading\3m_data\
   - C:\K_stock_trading\results\
   - 루트의 *.xlsx (ema_split_buy_*, full_3min_backtest_*, improved_entry_*)
   - 루트의 *.csv (testday, past1000*, 3mintest)

3. 검증:
   pytest 실행 (V7.0 인프라 테스트)
   python -c "import src.main" 정상 확인

4. .gitignore 갱신:
   백테스트 캐시 패턴 추가 (재발 방지)

## 완료 기준

- grep "backtest" 결과 0건
- pytest 통과
- 디스크 공간 확보 확인 (du -sh 보고)
- WORK_LOG.md 갱신
```

#### P1.3 ~ P1.8 (반복 패턴)

```markdown
# Task: P1.[N] - [작업명]

## 참조
05_MIGRATION_PLAN.md §[해당 섹션]

## 사전 의존성 분석 (필수)

[grep 패턴 명시]
→ 결과 보고 후 사용자 승인 받고 진행

## 작업

[순서대로 단계 명시]

## 검증

- pytest 통과
- python -c "import src.main" 정상
- 하네스 1, 2, 6 통과
- WORK_LOG.md 갱신
```

### 2.2 Phase 2: V7.1 골격

```markdown
# Task: P2.1 - 디렉토리 구조 생성

## 참조
04_ARCHITECTURE.md §1.2 (정확한 디렉토리 구조)

## 작업

1. 04_ARCHITECTURE.md §1.2의 디렉토리 구조 그대로 생성:
   - src/core/v71/box/
   - src/core/v71/strategies/
   - src/core/v71/exit/
   - src/core/v71/position/
   - src/core/v71/skills/
   - src/core/v71/report/
   - src/web/api/, auth/, websocket/
   - tests/v71/

2. 각 디렉토리에 __init__.py 생성 (빈 파일)

3. 디렉토리 트리 출력 (확인용):
   tree C:\K_stock_trading\src\core\v71

## 완료 기준

- 04_ARCHITECTURE.md §1.2와 정확히 일치
- 하네스 1 (Naming Collision) PASS
- WORK_LOG.md 갱신
```

```markdown
# Task: P2.2 - 데이터 모델 마이그레이션

## 참조
03_DATA_MODEL.md §2~§7 (테이블 정의)
05_MIGRATION_PLAN.md §4.3

## 작업

1. 디렉토리 생성:
   src/database/migrations/v71/

2. 마이그레이션 파일 작성:
   각 테이블별 .up.sql + .down.sql
   
   001_create_tracked_stocks.up.sql
   001_create_tracked_stocks.down.sql
   002_create_support_boxes.up.sql
   002_create_support_boxes.down.sql
   ... (03_DATA_MODEL.md §2~§6의 모든 테이블)
   999_indexes_and_constraints.sql

3. 03_DATA_MODEL.md의 SQL 정확히 사용:
   - ENUM 타입 정의
   - CHECK 제약
   - 인덱스
   - 외래 키

4. 개발 환경에 적용:
   UP 실행 → 테이블 생성 확인
   DOWN 실행 → 롤백 가능 확인
   다시 UP → 정상

## 완료 기준

- 03_DATA_MODEL.md 모든 테이블 생성
- UP/DOWN 정상 동작
- 하네스 4 (Schema Migration Validator) PASS
- WORK_LOG.md 갱신
```

### 2.3 Phase 3: 거래 룰 구현 (★ 가장 중요)

거래 룰은 **Trading Logic Verifier Agent 검증 필수**. 매 Task마다 검증 절차 명시.

```markdown
# Task: P3.1 - 박스 시스템 구현

## 참조 (필독)
- 02_TRADING_RULES.md §3 (박스 시스템) 정독
- 07_SKILLS_SPEC.md §2 (box_entry_skill)
- 03_DATA_MODEL.md §2.2 (support_boxes 테이블)
- 04_ARCHITECTURE.md §3.1 (박스 모듈)
- 06_AGENTS_SPEC.md §1 (Architect)
- 06_AGENTS_SPEC.md §2 (Trading Logic Verifier)

## 작업

1. src/core/v71/box/box_manager.py 구현
   - V71BoxManager 클래스
   - create_box() - 박스 생성, 겹침 검증
   - validate_no_overlap()
   - mark_triggered() / mark_invalidated() / mark_cancelled()
   - check_30day_expiry()

2. src/core/v71/box/box_entry_detector.py 구현
   - V71BoxEntryDetector 클래스
   - check_entry() - 봉 완성 시 진입 조건
   - 스킬 사용: box_entry_skill.evaluate_box_entry()

3. src/core/v71/box/box_state_machine.py 구현
   - 상태 전이 검증
   - TRACKING → BOX_SET → POSITION_OPEN → POSITION_PARTIAL → EXITED

## 검증 (필수)

1. 단위 테스트 작성:
   tests/v71/test_box_manager.py
   tests/v71/test_box_entry_detector.py
   
   - 정상 케이스
   - 박스 겹침
   - 한도 초과
   - 잘못된 가격
   - 상태 전이
   
   목표: 90%+ 커버리지

2. Trading Logic Verifier 호출 (페르소나):
   "다음 박스 진입 로직이 02_TRADING_RULES.md §3.8 룰을 정확히 구현하나요?"
   [코드 첨부]
   → PASS 받을 때까지 수정

3. 하네스 실행:
   python scripts/harness/run_all.py
   → 1, 2, 3, 7 모두 PASS

4. pytest:
   pytest tests/v71/test_box_*.py -v --cov

## 완료 기준

- Trading Logic Verifier PASS
- 모든 하네스 PASS
- pytest 90%+ 커버리지
- 02_TRADING_RULES.md §3 모든 룰 구현 확인
- WORK_LOG.md 갱신

## 주의

- 매직 넘버 금지 (V71Constants 사용)
- raw API 호출 금지 (kiwoom_api_skill 사용)
- 룰 변경 금지 (PRD 우선)
- 의문 시 즉시 질문 (룰 임의 해석 금지)
```

P3.2 ~ P3.7도 같은 패턴. 매 Task마다:
1. 참조 문서 명시
2. 작업 내용 (PRD에서 그대로)
3. 검증 (테스트 + 에이전트 + 하네스)
4. 완료 기준
5. 주의사항

### 2.4 Phase 4~7

비슷한 패턴. 주요 차이:

```yaml
Phase 4 (알림):
  주 참조: 02_TRADING_RULES.md §9, 07_SKILLS_SPEC.md §6
  검증: 빈도 제한, 우선순위 큐 동작

Phase 5 (웹):
  주 참조: 09_API_SPEC.md, 12_SECURITY.md
  검증: Security Reviewer Agent (필수)
  병렬: Claude Design 작업 (별도)

Phase 6 (리포트):
  주 참조: 11_REPORTING.md
  검증: 샘플 리포트 1건 생성 후 사용자 검수

Phase 7 (통합 + 배포):
  주 참조: 05_MIGRATION_PLAN.md §9
  검증: 페이퍼 트레이드 1~2주
```

---

## §3. 일상 작업 패턴

### 3.1 새 세션 시작 시

```markdown
이전 세션 이어서 진행합니다.

## 진행 상황 확인

C:\K_stock_trading\docs\v71\WORK_LOG.md를 읽고
어디까지 진행됐는지 보고하세요.

## 현재 작업

[다음 Task 명시]

## 컨텍스트 재로드 (필요 시)

작업 영역에 따라 다음 문서 다시 읽기:
- 거래 룰: 02_TRADING_RULES.md
- 데이터: 03_DATA_MODEL.md
- 구조: 04_ARCHITECTURE.md
```

### 3.2 의문 발생 시 사용자에게 질문하는 패턴

Claude Code가 다음 같이 질문하도록 유도:

```markdown
# Claude Code → 사용자 (예시)

## 질문 발생

작업 중 다음 의문이 발생했습니다:

[구체적 상황]
- 현재 코드: ...
- PRD 해당 부분: 02_TRADING_RULES.md §5.6
- 의문: [구체적 의문]

## 옵션

A: [옵션 A 설명]
   장점: ...
   단점: ...

B: [옵션 B 설명]
   장점: ...
   단점: ...

## 권장

[Claude Code의 권장]

사용자 결정 부탁드립니다.
```

### 3.3 룰 위반 의심 시

만약 Claude Code가 PRD를 임의 해석하려 하면:

```
PRD가 단일 진실 원천입니다.
임의 해석 금지.
02_TRADING_RULES.md §[해당 섹션]을 정확히 인용하고
그대로 구현하세요.

해석에 의문이 있으면 사용자에게 질문하세요.
```

---

## §4. 검증 절차

각 Task 완료 후 **사용자가 직접 검증**하는 절차:

### 4.1 Task 완료 검수

```yaml
체크리스트:
  ☐ 작업 내용 PRD와 일치
  ☐ 코드 품질 (타입 힌트, 독스트링)
  ☐ 단위 테스트 작성 + 통과
  ☐ 하네스 모두 PASS
  ☐ git diff 확인 (의도하지 않은 변경 없음)
  ☐ WORK_LOG.md 정확히 갱신

문제 발견 시:
  Claude Code에 수정 요청
  "X 부분이 PRD §Y와 다릅니다. 다시 작성하세요."
```

### 4.2 Phase 완료 검수

```yaml
Phase 끝나면 추가 확인:
  ☐ 05_MIGRATION_PLAN.md의 해당 Phase 체크리스트 모두 ✓
  ☐ Git tag 생성 (v71-phase[N]-complete)
  ☐ 운영 시뮬레이션 (Phase 3 이후)
  ☐ 다음 Phase 준비 상태
```

### 4.3 의심스러운 경우

```yaml
Claude Code 작업물 의심 시:

1. 코드 정독 (직접 읽기)
2. PRD와 대조
3. 다른 세션의 Claude Desktop에 검증 요청:
   "다음 코드가 02_TRADING_RULES.md §5.6을 정확히 구현하나요?"
4. 이상하면 즉시 롤백 (git revert)
```

---

## §5. 자주 사용하는 프롬프트 모음

### 5.1 단일 Task 위임

```markdown
# Task: [P_.X] [Task 명]

## 참조
[관련 PRD 섹션]

## 작업
[구체적 단계]

## 검증
- 단위 테스트
- 하네스
- 에이전트 (해당 시)

## 완료 기준
[명확한 종료 조건]
```

### 5.2 검증만 요청

```markdown
다음 코드를 검증해주세요.

## 코드
[파일 경로 또는 코드]

## 검증 항목
1. 02_TRADING_RULES.md §X 룰 정확성
2. 매직 넘버 사용 여부
3. 스킬 사용 여부
4. 타입 힌트 + 독스트링
5. 테스트 커버리지

## 응답 형식

각 항목별 PASS/FAIL + 이유
```

### 5.3 진행 상황 점검

```markdown
현재 V7.1 작업 진행 상황을 보고하세요.

다음을 포함:
1. 완료된 Phase / Task
2. 진행 중인 Phase / Task
3. 막혀있는 부분 (있다면)
4. 다음 단계 제안

C:\K_stock_trading\docs\v71\WORK_LOG.md 참조.
```

### 5.4 PRD 변경 요청 (긴급)

```markdown
# 긴급 PRD 변경 검토

## 발견된 문제
[구체적 상황]

## 영향
- 영향 받는 Phase: [N]
- 영향 받는 코드: [파일]
- 영향 받는 PRD: [문서 §섹션]

## 검토 요청
다음을 분석하세요:
1. PRD 변경이 정말 필요한가?
2. 변경 시 영향 범위
3. 대안 (PRD 변경 없이 해결 가능한지)

판단 후 사용자(박균호) 승인 요청.
임의 변경 금지.
```

---

## §6. 비상 상황 대응

### 6.1 Claude Code가 잘못된 방향으로 진행 중

```
즉시 중단하고 다음을 답하세요:

1. 현재 어떤 작업 중?
2. PRD 어느 섹션 참조?
3. PRD와 어떤 점이 다른지

사용자 승인 없이 더 이상 진행 X.
```

### 6.2 V7.0 운영 영향 발견

```
즉시 중단.
V7.0 운영에 영향이 있는지 확인:
1. python -c "import src.main" 정상?
2. pytest 통과?
3. 어떤 모듈 깨졌는지?

영향 있으면:
git status 확인
git diff 확인
필요 시 git revert (사용자 승인 후)
```

### 6.3 충돌 금지 원칙 위반

```
헌법 3 (충돌 금지) 위반 발견.

확인:
1. V7.1 코드가 src/core/v71/ 안에 있나?
2. V71 접두사 사용?
3. 하네스 1 (Naming Collision) 통과?

위반 시 즉시 수정.
의문 시 사용자에게 질문.
```

---

## §7. 작업 시작 체크리스트 (오늘 박균호님이 할 일)

### 7.1 환경 준비 (Phase 0 시작 전)

```yaml
☐ V7.0 운영 환경 확인:
  - 현재 추적 중 종목 메모
  - 보유 포지션 메모
  - 미체결 주문 메모

☐ 백업:
  - Git tag 안 했으면 지금 (v7.0-final-stable)
  - DB 백업 (Supabase Dashboard)
  - .env 백업

☐ 개발 환경 분리:
  - 별도 브랜치 (v71-development)
  - 또는 별도 디렉토리 복사
  - 키움 모의투자 또는 Read-only 모드

☐ Claude Code 준비:
  - VS Code + Claude Code 확장 또는
  - Claude Code CLI 설치
  - C:\K_stock_trading 디렉토리 접근 권한

☐ 에이전트 활용 계획:
  - Architect Agent
  - Trading Logic Verifier Agent
  - Migration Strategy Agent
  - Security Reviewer Agent
  - Test Strategy Agent
  
  → Claude Code 내장 페르소나로 활용 가능
```

### 7.2 첫 세션 진행

```yaml
순서:
  1. Claude Code 새 세션 시작
  2. §1.1의 초기 컨텍스트 프롬프트 전송
  3. Claude Code 응답 검증 (§1.2)
  4. P0.1 Task 지시 (§1.3)
  5. 완료 후 검수
  6. P0.2, P0.3, P0.4 순차 진행
  7. Phase 0 완료 → Git tag

진행 속도:
  Phase 0: 1일 (간단)
  Phase 1: 3~5일 (의존성 추적 신중)
  Phase 2: 3~5일 (골격, 빠름)
  Phase 3: 10~15일 ★ (가장 중요, 신중하게)
  ...
```

### 7.3 매일 일과

```yaml
오전:
  1. 어제 작업 검수
  2. WORK_LOG.md 확인
  3. 오늘 작업 계획

작업 중:
  1. Task 단위 진행
  2. 의문 발생 시 즉시 질문
  3. 매 Task 검증

저녁:
  1. 작업 종료 시 git commit
  2. WORK_LOG.md 업데이트
  3. 내일 계획 메모

주말:
  1. 주간 진행 검수
  2. 다음 주 계획
```

---

## §8. 권장 사항

### 8.1 시작은 천천히

```yaml
첫 1주일:
  Phase 0 + Phase 1.1~1.3만
  Claude Code의 작업 패턴 파악
  검수 루틴 정착

이후:
  속도 조절
  익숙해지면 모드 2 (Phase 단위) 가능

조심스럽게:
  Phase 3 (거래 룰)은 절대 서두르지 말 것
  매 Task 검증 + Trading Logic Verifier
```

### 8.2 PRD가 진실

```yaml
원칙:
  Claude Code의 의견 < PRD
  Claude Code가 "이렇게 하는 게 좋겠다" 해도
  PRD에 명시된 대로 구현

PRD 변경:
  사용자(박균호) 승인 필수
  세션 시작 (Claude Desktop)에서 결정
  Claude Code는 PRD 변경 권한 없음
```

### 8.3 완벽 추구

```yaml
거래 룰 (Phase 3):
  완벽 추구
  애매한 부분 100% 명확히
  단위 테스트 90%+
  Trading Logic Verifier PASS

웹 UI (Phase 5):
  사용자 만족 추구
  점진 개선 OK

리포트 (Phase 6):
  품질 검증 (샘플 1건)
  비용 모니터링
```

---

## §9. 첫 메시지 템플릿 (즉시 사용 가능)

지금 당장 Claude Code에 보낼 메시지:

```markdown
# V7.1 시스템 구현 작업 시작

당신은 K_stock_trading V7.1 시스템의 구현을 담당하는 Claude Code입니다.

## 환경

- 프로젝트: C:\K_stock_trading\
- PRD 패키지: C:\K_stock_trading\docs\v71\
- 사용자: 박균호 (8년 전업 트레이더)
- 시스템: 한국 주식 자동매매 (키움 OpenAPI)

## 사전 학습 (필수, 순서대로)

다음 문서를 정독하세요:

1. C:\K_stock_trading\docs\v71\README.md
2. C:\K_stock_trading\docs\v71\01_PRD_MAIN.md (전체 그림)
3. C:\K_stock_trading\docs\v71\00_CLAUDE_CODE_GENERATION_PROMPT.md (작업 지침)
4. C:\K_stock_trading\docs\v71\HOW_TO_INSTRUCT_CLAUDE_CODE.md (작업 위임 방식)
5. C:\K_stock_trading\docs\v71\05_MIGRATION_PLAN.md §0~§2 (Phase 0)

## 헌법 5원칙 (절대 위반 금지)

1. 사용자 판단 불가침 (자동 추천 X)
2. NFR1 최우선 (박스 진입 < 1초)
3. 충돌 금지 ★ (V7.0 보존, V7.1 src/core/v71/ 격리)
4. 시스템 계속 운영 (자동 정지 X)
5. 단순함 우선

## 작업 위임 방식

- Task 단위로 지시합니다
- 임의 진행 금지
- 매 Task마다 결과 보고 + 검수
- PRD가 단일 진실 (임의 해석 금지)
- 의문 시 즉시 질문

## 응답 요청

위 5개 문서를 모두 읽었으면 다음을 응답하세요:

1. PRD 패키지 14개 문서 중 가장 핵심인 3개와 그 이유
2. 헌법 5원칙 중 "충돌 금지"가 의미하는 것 (구체적으로)
3. Phase 0의 4가지 Task (P0.1~P0.4) 요약
4. V7.1 격리 패키지 (src/core/v71/) 디렉토리 구조 (간략히)
5. 작업 시작 준비 상태

응답 후 첫 Task 지시를 기다리세요.
```

---

## §10. 작업 시작 후 첫 Task 메시지

위 응답 검증 후 보낼 메시지:

```markdown
# Task: P0.1 - 전체 백업

## 참조
05_MIGRATION_PLAN.md §2.1

## 작업

1. Git 상태 확인:
   cd C:\K_stock_trading
   git status
   결과 보고

2. Git 태그 생성 (Git 상태 깨끗할 시):
   git tag v7.0-final-stable
   git tag (확인)
   
   참고: push는 사용자가 직접 (원격 저장소 사용 시)

3. 코드 백업:
   - 백업 디렉토리: C:\backups\
   - 파일명: K_stock_trading_v70_final_[YYYYMMDD].zip
   - PowerShell 스크립트로 zip 생성
   - 백업 파일 크기 보고

4. .env 파일 별도 백업:
   - 위치: C:\backups\.env_v70_final_[YYYYMMDD]
   - 권한 확인 (다른 사용자 접근 차단)

5. WORK_LOG.md 생성/업데이트:
   - 위치: C:\K_stock_trading\docs\v71\WORK_LOG.md
   - 형식: 05_MIGRATION_PLAN.md 부록 A.1 참조
   - 내용: P0.1 완료 기록

6. DB 백업 안내:
   - Supabase Dashboard 백업 다운로드 절차 안내
   - 사용자가 직접 다운로드
   - 백업 파일 위치 권장

## 완료 기준

- ☐ Git tag 생성됨
- ☐ 코드 zip 백업
- ☐ .env 백업
- ☐ WORK_LOG.md 갱신
- ☐ DB 백업 안내 출력

## 주의

- 코드 변경 없음 (백업만)
- V7.0 운영 영향 X
- 의문 시 즉시 질문

준비되면 시작하세요.
```

---

## 부록 A: 빠른 명령어 사전

| 상황 | 메시지 |
|------|--------|
| 진행 상황 확인 | "현재 V7.1 작업 진행 상황 보고. WORK_LOG.md 참조." |
| 다음 Task 지시 | "다음 Task: P_.X [작업명]. 참조: §[섹션]. 작업: ..." |
| 검증만 요청 | "다음 코드가 02_TRADING_RULES.md §X 룰 정확한가요?" |
| 의문 발생 | "[상황 설명]. PRD와 충돌하는지 분석. 사용자 결정 필요한 옵션 제시." |
| 즉시 중단 | "중단. 현재 작업 보고. PRD 어느 섹션 참조? PRD와 어떤 점 다른지?" |
| 수정 요청 | "X 부분이 PRD §Y와 다릅니다. 다시 작성." |
| Phase 완료 | "Phase N 완료 검수. 체크리스트 모두 확인. Git tag v71-phaseN-complete." |

---

## 부록 B: Claude Code 활용 팁

```yaml
효율적 활용:
  - 컨텍스트 리셋 자주 (긴 세션은 모드 잃음)
  - PRD 매 세션 재확인 요청
  - 작업 단위 작게 (한 Task에 한 시간 이내)
  - 검수 루틴 일관 (매번 같은 체크리스트)

피해야 할 것:
  - "알아서 해" 류 모호한 지시
  - 여러 Task 동시 진행
  - PRD 임의 해석 허용
  - 검수 건너뛰기

비용 절감:
  - 큰 PRD 문서 매번 읽기보다 핵심만
  - 캐시된 컨텍스트 활용 (같은 세션 유지)
  - 단순 작업은 sonnet 모델 (가능 시)
  - 거래 룰 같은 중요 작업은 opus
```

---

*이 문서는 박균호님이 Claude Code에 V7.1 작업을 위임할 때 사용하는 실전 가이드입니다.*  
*PRD 패키지 검토 완료 후 즉시 사용 가능.*

*최종 업데이트: 2026-04-25*  
*다음 단계: §9의 첫 메시지로 Claude Code 세션 시작*
