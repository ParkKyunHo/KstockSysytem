# V7.1 작업 로그 (Work Log)

> V7.0 → V7.1 마이그레이션 작업 일지
> 매 Task 완료 시 즉시 갱신
> 형식: 05_MIGRATION_PLAN.md §0.2 참조

---

## 2026-04-26

### Phase 0: 사전 준비 (진행 중)

#### P0.1: 전체 백업 (완료)

**참조**: 05_MIGRATION_PLAN.md §2.1

**완료 항목**

| Step | 작업 | 결과 |
|------|------|------|
| 1 | Git 저장소 초기화 | `git init -b main` 완료. `.git/` 생성 |
| 1 | 원격 저장소 연결 | `origin = https://github.com/ParkKyunHo/KstockSysytem.git` |
| 1 | git user.email / user.name | `pgh9307@gmail.com` / `ParkKyunHo` |
| 1 | safe.directory 글로벌 등록 | Windows Administrators 권한 충돌 해결 |
| 2 | 코드 백업 (tar.gz) | `C:\backups\K_stock_trading_v70_final_20260426.tar.gz` (16 MB, 619 파일) |
| 2 | 데이터 백업 (tar.gz) | `C:\backups\K_stock_trading_v70_data_20260426.tar.gz` (43 MB, `3m_data/` + `data/`) |
| 4 | `.env` 별도 백업 | `C:\backups\.env_v70_final_20260426` (MD5 일치 검증 완료) |
| - | `.gitignore` 보강 | 시크릿/임시파일 차단 패턴 추가 |
| - | git 첫 커밋 | (아래 커밋 ID 참조) |
| - | git tag `v7.0-final-stable` | 생성 완료 |

**미완료 / 사용자 직접 수행 필요**

| Step | 작업 | 비고 |
|------|------|------|
| 3 | DB 스냅샷 (Supabase) | 사용자가 Supabase Dashboard에서 직접 다운로드 권장 (자동 쿼리는 보안상 미실행) |
| 5 | V7.0 운영 상태 (추적 종목 / 포지션 / 미체결) | DB 백업과 함께 사용자가 직접 캡처 |
| - | GitHub `git push origin main --tags` | **사용자 승인 후 실행 예정** |

**검증**

- [x] git ls-files: 294개 파일 트래킹 (코드/문서/설정만)
- [x] 시크릿 트래킹 0건 (`.env`, `.token_cache.json`, `.mcp.json` 등 제외 확인)
- [x] 임시파일 트래킹 0건 (Windows 콜론 U+F03A 변종 포함 차단)
- [x] tar 백업 무결성 확인 (핵심 파일 포함 검증)
- [x] `.env` MD5 체크섬 일치

**발견된 이슈 (P1.3 정리 대상으로 분류)**

| 파일 | 종류 | 처리 시점 |
|------|------|----------|
| `nul` (169 B) | 잘못된 SSH known_hosts 파편 (`>` 리다이렉트 오타) | P1.3 |
| `C:K_stock_trading*.txt` (~80 MB) | Unix 셸 PowerShell 호출 시 경로 오인식 흔적 | P1.3 |
| `C:Users박균호temp_log.txt` | 위와 동일 | P1.3 |
| `*.recovered`, `*.new` | 텍스트 편집기 백업/복구 잔재 | P1.3 |
| `C:K_stock_trading.env.new`, `*.env.recovered` | `.env` 편집 잔재 | P1.3 |

**보안 사고 (작업 중 발생)**

- 작업 중 `grep DATABASE_URL .env | sed`로 도메인만 마스킹 시도 시 **sed 패턴 결함으로 DB 비밀번호 일부가 터미널 출력에 노출됨**.
- 노출 범위: 본 작업 세션의 터미널 출력만. Git/외부 시스템 전송 없음.
- **권장 조치**: Supabase 콘솔에서 DB 비밀번호 회전 (rotate) 후 `.env` 갱신 + 운영 서버 재배포.
- 재발 방지: 시크릿 포함 가능성 있는 파일은 grep 출력 자체를 회피. 마스킹 필요 시 사전에 패턴 검증.

#### P0.1 추가 보강: .env Supabase 키 정정

| 변경 전 | 변경 후 |
|---------|---------|
| `Subabase API=...` (오타 + 공백 포함, dotenv 파싱 실패 위험) | `SUPABASE_PUBLISHABLE_KEY=...` |
| `subabase secret api=...` (오타 + 공백) | `SUPABASE_SECRET_KEY=...` |
| (없음) | `SUPABASE_URL=https://wlkcuqfflmdshpzbfndz.supabase.co` 추가 |

V7.0은 `SUPABASE_*` 변수 미사용 (`DATABASE_URL` 단독), V7.1이 REST/Auth/Storage용으로 사용. 헌법 3 부합.

#### P0.1 추가 보강: 보안 사고 #2

`.env` 라인 35-44 직접 read 시 DATABASE_URL 비밀번호 재노출. 작업 종료 후 권한 정책으로 read 차단되어 재발 방지. **권장**: Supabase 콘솔 비밀번호 회전.

#### P0.2: 개발 환경 분리 (완료)

| Step | 작업 | 결과 |
|------|------|------|
| 1 | 브랜치 생성 | `git checkout -b v71-development` 완료 |
| 2 | .gitignore 보강 | `.env.development`, `.env.staging`, `.env.testing`, `.env.production`, `.env.backup`, `.env.*.backup` 추가 차단 |

미수행 (사용자 직접 결정 필요):
- Supabase 별도 프로젝트 분리 vs 단일 프로젝트 (현재 사용자가 새 키 등록한 것은 단일 프로젝트로 추정)
- 키움 모의투자 환경 사용 여부 (`IS_PAPER_TRADING` 토글)
- 로컬 PostgreSQL 옵션

#### P0.3: Feature Flag 인프라 (완료)

| 산출물 | 위치 | 비고 |
|--------|------|------|
| 플래그 정의 | `config/feature_flags.yaml` | 20개 플래그 (Phase 3~6 매핑) + 안전 fallback 1개 |
| 로더 모듈 | `src/utils/feature_flags.py` | YAML + ENV 오버라이드 (`V71_FF__<DOTTED>`), `is_enabled()`, `require_enabled()`, `all_flags()`, `reload()` |
| 단위 테스트 | `tests/v71/test_feature_flags.py` | 24 PASS, 모듈 커버리지 96.8% |

ENV 오버라이드 예: `V71_FF__V71__BOX_SYSTEM=true`. 6종 truthy/falsy 토큰 모두 지원.

#### P0.4: 자동 검증 도구 설치 (완료)

| 산출물 | 위치 | 수준 | Phase 0 결과 |
|--------|------|------|-------------|
| Harness 1 (Naming Collision) | `scripts/harness/naming_collision_detector.py` | BLOCK | PASS |
| Harness 2 (Dependency Cycle) | `scripts/harness/dependency_cycle_detector.py` | BLOCK | PASS (V7.0 자체 cycle 1개는 advisory WARN, P1에서 자동 해소) |
| Harness 3 (Trading Rule Enforcer) | `scripts/harness/trading_rule_enforcer.py` | BLOCK | PASS (v71/ 비어있음) |
| Harness 4 (Schema Migration Validator) | `scripts/harness/schema_migration_validator.py` | BLOCK | PASS (마이그레이션 디렉토리 미존재) |
| Harness 5 (Feature Flag Enforcer) | `scripts/harness/feature_flag_enforcer.py` | WARN | PASS |
| Harness 6 (Dead Code Detector) | `scripts/harness/dead_code_detector.py` | WARN→BLOCK(Phase 1+) | WARN 32건 (V7.0 trading_engine.py 등의 폐기 대상 import, P1.4~P1.8에서 0으로 감소) |
| Harness 7 (Test Coverage Enforcer) | `scripts/harness/test_coverage_enforcer.py` | BLOCK (CI) | PASS (`src/utils/feature_flags.py`: 96.8% > 90%) |
| 통합 실행기 | `scripts/harness/run_all.py` | - | `python scripts/harness/run_all.py [--with-7]` |
| 공통 헬퍼 | `scripts/harness/_common.py` | - | UTF-8 콘솔 강제 (Windows cp949 호환) |
| pre-commit 훅 | `.pre-commit-config.yaml` | - | 1~6 자동 실행 + ruff 포맷 |
| dev deps 추가 | `pyproject.toml [project.optional-dependencies].dev` | - | `pre-commit>=3.5.0`, `pyyaml>=6.0` |

**활성화 명령** (사용자 1회 수행):
```bash
pip install -e ".[dev]"
pre-commit install
```

---

### Phase 0 완료 검증 (모두 통과)

```
$ python scripts/harness/run_all.py
PASS  6 / 6 harness(es)

$ python scripts/harness/test_coverage_enforcer.py
RESULT: PASS (Harness 7: Test Coverage Enforcer)

$ python -m pytest tests/v71/ -v
24 passed in 1.07s
```

| 마일스톤 | 상태 |
|----------|------|
| M0: Phase 0 완료 | (이번 세션 종료 시) |
| Tag `v71-phase0-complete` | 다음 commit에서 생성 |

---

## 다음 작업 (Phase 1)

**전제**: V7.0 운영에 영향 없음 (현재 모든 작업이 폐기 대상 코드의 *추가/검증*만이며 V7.0 코드 삭제 미진행).

순서 (05_MIGRATION_PLAN.md §3):
1. **P1.1** OpenClaw 정리 (외부 시스템 + docs/OPENCLAW_GUIDE.md 삭제 + CLAUDE.md Part 0 제거)
2. **P1.2** 백테스트 시스템 삭제 (run_backtest_ui.py, scripts/backtest/, 캐시)
3. **P1.3** 임시 파일 정리 (`nul`, `C:K_stock_trading*.txt`, `*.recovered`, `*.new`)
4. **P1.4** V6 SNIPER_TRAP 완전 삭제 (의존성 추적 필수)
5. **P1.5** V7 신호 시스템 삭제 (Harness 6 WARN 32건 자동 해소 시점)
6. **P1.6** 미완성 추상화 정리
7. **P1.7** wave_harvest_exit V7.1 ATR 배수 적용 (단, 이는 Phase 3로 이연 가능)
8. **P1.8** trading_engine.py 정리

각 Task 후 `python scripts/harness/run_all.py` 통과 + pytest 정상 확인.

## 권장/대기

- DB 비밀번호 회전 (보안 사고 #1, #2 대응)
- `pip install -e ".[dev]" && pre-commit install` (1회 수행)
- Phase 0 commit 시 tag `v71-phase0-complete` 생성 + push

---

*최종 업데이트: 2026-04-26*
