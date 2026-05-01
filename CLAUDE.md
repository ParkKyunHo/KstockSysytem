# CLAUDE.md

> **K_stock_trading V7.1** — 키움증권 REST API 국내 주식 자동매매 (V7.1 단독 운영)
> **PRD**: `docs/v71/01_PRD_MAIN.md` / **로그**: `docs/v71/WORK_LOG.md` / **마지막 tag**: `v71-phase3-complete`
> **V7.0 (Purple-ReAbs)는 commit 33ee3ee + fbee149에서 일괄 폐기**. git tag `v7.0-final-stable` 참조용.

---

# Part 0: 행동 가이드라인 (Behavioral)

> 자금 시스템이라 **caution > speed**. (참고: Karpathy CLAUDE.md 패턴 흡수)

### 0.1 Think Before Coding
가정 명시 / 다중 해석 시 옵션 제시 / 더 단순한 접근 있으면 푸시백 / 혼란 시 멈추고 질문.

### 0.2 Simplicity First
필요 최소 코드. 추측 features + 단일 사용 abstractions X. **"200줄 가능한 50줄?" / "senior engineer가 overcomplicated라 할까?"** 자가 점검.

### 0.3 Surgical Changes
변경 요청한 것만. 인접 코드 "개선" X. 기존 스타일 따름. **V7.1 격리** (V7.0 잔재 import X). 변경으로 만든 orphan만 제거 — 사전 dead code 발견 시 **삭제 X, 보고만**.

### 0.4 Goal-Driven Execution
매 작업 = **verifiable goal**. Multi-step = plan + step별 verify. "검증 추가" → "invalid input 테스트 작성 후 PASS" / "버그 fix" → "재현 테스트 후 PASS" / "리팩토링" → "tests pass before AND after".

---

# Part 1: 시스템 정체성 + 헌법 5원칙

V7.1 = **Box-Based** (사용자 박스 등록 → 자동 진입/청산).
V7.0 = 폐기 (Purple-ReAbs 자동 신호).

**헌법** (PRD §1):
1. **사용자 판단 불가침** — 자동 자금 결정 금지
2. **NFR1 우선** — hot-path 1초 budget
3. **충돌 금지** — V7.1 격리, V7.0 잔재 import 0
4. **항상 운영** — DB 실패해도 trade
5. **단순함** — 복잡도 < 기능

---

# Part 2: 절대 규칙

| 분류 | 금지 | 대체 |
|------|------|------|
| 코드 | 읽지 않은 파일 수정 | Read 먼저 |
| 인코딩 | PowerShell로 파일 저장 | Write/Edit 도구 |
| 배포 | SSH 직접 실행 | `search_logs.ps1 -cmd` |
| 텔레그램 | parse_mode 사용 | plain text (P-Wire-3 fail-secure) |
| 컨텍스트 | 갱신 없이 완료 선언 | Part 6.4 절차 후 응답 |
| .env | 인라인 주석 | 별도 라인 (Part 7) |
| 격리 | V7.0 잔재 import 추가 | V7.1만 사용 |

---

# Part 3: V7.1 12단계 표준 워크플로우 (매 코드 작업)

```
1. PRD 로드               → verify: 관련 docs/v71/* Read 완료
2. v71-architect          → verify: 결정 트리 답변 반영
3. 구현                   → verify: type 체크 + import OK
4. security + test 병렬   → verify: CRITICAL/HIGH 0
5. 보안 패치              → verify: 검토자 권고 반영
6. 테스트 작성            → verify: test-strategy 가이드
7. 실행 + 디버그          → verify: 신규 테스트 PASS
8. 8 harness              → verify: 모두 PASS (pre-commit 자동)
9. ruff                   → verify: 변경 파일 clean
10. V7.1 회귀             → verify: pytest tests/v71/ 1225+ 유지
11. commit (사용자 승인)   → verify: 사용자 명시 OK
12. WORK_LOG + memory     → verify: workflow_trunk_based.md 갱신
```

거래 룰 영향 → **+trading-logic-verifier** / DB 변경 → **+migration-strategy**

---

# Part 4: Sub-agents + Skills + 신규 생성 절차

> **원칙**: 매 작업에서 적합한 agent/skill **적극 활용**. 부족하면 신규 제안 (사용자 승인). 사용자 명시 (2026-04-27): "회사처럼 팀이 의견 제시 + 검토".

### 4.1 10 Sub-agents 호출 결정 트리 (PRD §6 + ECC §4 벤치마크)

**도메인 검증 (5)**:
```
신규 V7.1 모듈/의존성?    → v71-architect (필수)
거래 룰 영향?              → trading-logic-verifier (필수)
DB schema/marker 변경?     → migration-strategy (필수)
외부 API/시크릿/DB 쿼리?   → security-reviewer (필수)
새 함수/클래스?            → test-strategy (필수)
```

**오케스트레이션 (5, ECC land 2026-05-02)**:
```
새 작업 시작 (모호/multi-step)     → planner (PRD 로드 + 분해 + verify)
큰 단위 land → commit 직전         → doc-updater (work-context + WORK_LOG + memory)
다단계 마이그레이션 / 반복 작업    → loop-operator (사용자 승인 게이트 강제)
신규 V7.1 land / harness 변경      → harness-audit (V71_PATHS / H3 / G1 정합)
큰 리팩토링 / 모듈 폐기 후         → refactor-cleaner (Karpathy §3 surgical)
```

### 4.2 10 Skills 사용 정책 (raw call 차단 — harness H3)

| 도메인 | Skill | raw 차단 대상 |
|-------|-------|------------|
| Kiwoom REST | `v71-kiwoom-api` | httpx / requests / aiohttp |
| 박스 진입 | `v71-box-entry` | 직접 PATH_A/B |
| 손절/익절/TS | `v71-exit-calc` | 직접 계산 |
| 평단가 | `v71-avg-price` | weighted_avg_price 직접 변경 |
| VI 처리 | `v71-vi` | 직접 VI flag |
| 알림 | `v71-notification` | telegram.send_message 직접 |
| 정합성 | `v71-reconciliation` | 직접 DB sync |
| 테스트 | `v71-test-template` | (가이드만) |
| 모듈 추가 | `v71-add-module` | 12단계 자동 |
| **병렬 검토** | **`v71-multi-execute`** (ECC land) | **step 4 (security+test 동시) round-trip 1/2** |

### 4.3 신규 에이전트/스킬 생성 절차 (사용자 승인 필수)

**신규 에이전트 "고용"**: 필요성 식별 → 사용자 제안 (이름/역할/trigger/도구) → **승인 후** `.claude/agents/<name>.md` + Memory + Part 4.1 갱신.

**신규 스킬 생성**: 필요성 식별 → 사용자 제안 (이름/영역/trigger/raw 차단) → **승인 후** `.claude/skills/<name>/SKILL.md` + `src/core/v71/skills/<name>_skill.py` + `tests/v71/test_<name>_skill.py` + 필요 시 harness H3 갱신 + `docs/v71/07_SKILLS_SPEC.md` + Memory + Part 4.2 갱신.

> 기존 5+9로 우선 시도. 진짜 커버 X 영역만 신규 제안.

---

# Part 5: 운영 명령어

```powershell
# 배포
hotfix.ps1                   # 파일 전송 + v71.service 재시작
hotfix.ps1 -NoRestart        # 파일만

# 점검
boot_smoke_v71.ps1           # systemd + /health + DB
check_invariants.ps1         # 5 flag false + G1 SSoT
check_logs.ps1 50 / status.ps1

# SSH 대체 / DB
search_logs.ps1 -cmd "X"     # SSH 직접 금지 대체
check_db_server.ps1

# 로컬 dev (admin/admin)
start_dev.ps1                # backend + frontend 한 번에
```

| 항목 | 값 |
|------|-----|
| Production | 43.200.235.74 / albra.net (Cloudflare Tunnel) |
| systemd | v71.service (uvicorn :8080) |
| Dev | localhost:5173 (admin/admin, SQLite, TOTP off) |
| 정규장 KST | 09:00~15:20 / EOD KST 15:30 |

Python: `"C:\Program Files\Python311\python.exe" -m pytest tests/v71/ -v`

---

# Part 6: 컨텍스트 + 문서 인덱스

### 6.1 Sub-CLAUDE.md (영역 작업 시 자동 합쳐짐)

| 디렉터리 | 영역 | 상태 |
|---------|-----|-----|
| `src/core/v71/CLAUDE.md` | 거래 룰 + 9 skills + trading-logic | ✓ Phase 1 |
| `src/web/v71/CLAUDE.md` | FastAPI + auth + DB | Phase 2 |
| `frontend/CLAUDE.md` | vite + React + tokenStore | Phase 3 |
| `tests/v71/CLAUDE.md` | pytest + v71-test-template | Phase 3 |
| `scripts/CLAUDE.md` | PowerShell 표준 | Phase 4 |
| `docs/v71/CLAUDE.md` | PRD 갱신 trigger | Phase 4 |

### 6.2 PRD `docs/v71/`

01_PRD_MAIN / 02_TRADING_RULES / 03_DATA_MODEL / 04_ARCHITECTURE / 05_MIGRATION_PLAN / 06_AGENTS_SPEC / 07_SKILLS_SPEC / 08_HARNESS_SPEC / 09_API_SPEC / 10_UI_GUIDE / 12_SECURITY / 13_APPENDIX / WORK_LOG. **시스템 history**: `docs/CHANGELOG.md`.

### 6.3 Memory (`.claude/projects/.../memory/`)

`MEMORY.md` (인덱스) / `workflow_trunk_based.md` (git + dev/prod) / `auth_sliding_session.md` / `aws_deployment_policy.md` / `production_domain_cloudflare.md` / `session_*.md` (작업 단위).

### 6.4 작업 완료 전 절차 (필수)

1. `.claude/state/work-context.json` 갱신 (`/work-log` 또는 직접)
2. `docs/CHANGELOG.md` 갱신 (기능/버그/배포)
3. `docs/v71/WORK_LOG.md` 갱신 (Phase 진행)
4. Memory 갱신 (큰 단위는 별도 파일)

> **컨텍스트 갱신 없이 "완료" 응답 금지** (Part 2 절대 규칙).
> **자동 hook** (ECC land): SessionStart에서 `work-context.json` 자동 표시 + Stop에서 `git status` 변경 시 reminder. 갱신 자체는 수동 (자금 시스템 안전).

---

# Part 7: 과거 오류

### 7.1 .env 인라인 주석 (2026-01-22)

`KIWOOM_APP_KEY=abc # production` → systemd가 `"abc # production"`로 파싱.
**해결**: 주석은 별도 라인. shared/.env + current/.env 양쪽 갱신.
```bash
# production 키
KIWOOM_APP_KEY=abc
```
