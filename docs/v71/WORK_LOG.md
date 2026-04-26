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

## Phase 2: V7.1 골격 구축 (진행 중)

### P2.1: 디렉토리 구조 생성 (완료)

**참조**: 04_ARCHITECTURE.md §5.3, 05_MIGRATION_PLAN.md §4.1

**생성 디렉토리** (모두 `__init__.py` 도크스트링 포함, V7.1 격리 패키지)

```
src/core/v71/                    -- 진입점 패키지 docstring
├── box/                         -- §3 박스 시스템
├── strategies/                  -- §4 진입 전략 (PATH_A 눌림/돌파)
├── exit/                        -- §5 청산 (-5%/-2%/+4%, +5%/+10% 30%, ATR 4/3/2.5/2)
├── position/                    -- §6 평단가, §7 reconciler
├── skills/                      -- 8 표준 스킬 (07_SKILLS_SPEC.md)
└── report/                      -- Phase 6 Claude Opus 4.7 리포트

src/web/                         -- Phase 5 웹 대시보드
├── api/                         -- FastAPI REST
├── auth/                        -- JWT + 2FA
└── dashboard/                   -- React 정적

src/database/migrations/v71/     -- UP/DOWN SQL pair 룰 (Harness 4)
```

**검증**

- import 검증: 12개 패키지 모두 import OK
- 하네스: 6/6 PASS
- Harness 1 (Naming Collision): V7.1 패키지가 v71/ 격리 또는 V71 접두사 룰 준수
- Harness 5 (Feature Flag Enforcer): 빈 패키지에 진입 함수 없음 → 면제 (EXEMPT_PARTS = `__init__.py`)

### P2.2: 데이터 모델 마이그레이션 (완료)

**참조**: 03_DATA_MODEL.md §0~§9, 05_MIGRATION_PLAN.md §4.3

**산출물**: 17개 UP + 17개 DOWN + README + `__init__.py` (총 36 파일)

| 순번 | 마이그레이션 | 비고 |
|------|--------------|------|
| 000 | extensions | uuid-ossp, pgcrypto, pg_trgm, btree_gist |
| 001 | users | bcrypt password, TOTP 2FA, telegram_chat_id UNIQUE |
| 002 | user_sessions | FK→users CASCADE. JWT 1h+24h |
| 003 | user_settings | FK→users CASCADE. notify_critical 강제 ON (앱 레벨) |
| 004 | audit_logs | FK→users. ENUM 15종 (LOGIN, BOX_*, TRACKING_*, REPORT_REQUESTED 등) |
| 005 | market_calendar | TRADING/HOLIDAY/HALF_DAY/EMERGENCY_CLOSED |
| 006 | stocks | gin trigram name search, 관리/위험 종목 플래그 |
| 007 | tracked_stocks | **gist EXCLUDE**: (stock_code, path_type) 활성 1건 강제 (EXITED 제외 → 이력 보존) |
| 008 | support_boxes | FK→tracked_stocks CASCADE. CHECK: upper>lower, 0<size≤100, stop<0 |
| 009 | positions | source ENUM (SYSTEM_A/B/MANUAL) + status ENUM. CHECK: closed↔qty=0 |
| 010 | trade_events | event_type ENUM 21종 (BUY/PROFIT_TAKE_5/10/STOP_LOSS/TS_EXIT/AUTO_EXIT 등) |
| 011 | system_events | severity INFO/WARNING/ERROR/CRITICAL |
| 012 | system_restarts | reason ENUM, reconciliation_summary JSONB |
| 013 | vi_events | actions_taken JSONB |
| 014 | notifications | priority queue (1=CRITICAL ~ 4=LOW) + rate_limit_key |
| 015 | daily_reports | FK→tracked_stocks, users. PART 1/2 narrative + facts |
| 016 | monthly_reviews | UNIQUE (review_month) |

**FK 의존성 순서로 재배치**: PRD §8.2 예시는 자연 묶음(거래→이벤트→리포트→사용자→마스터)이지만 daily_reports.requested_by → users FK 위반 → users(001) 먼저, daily_reports(015) 나중으로 배치.

**멱등성**: 모든 UP은 `IF NOT EXISTS` (테이블/인덱스) 또는 `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object`(ENUM, PostgreSQL CREATE TYPE IF NOT EXISTS 미지원). 모든 DOWN은 `IF EXISTS`.

**적용 방식**: P2.5/Phase 5에서 결정 (Alembic raw vs Supabase CLI). 현재는 raw SQL 파일로만 보존.

**검증**

```
$ python scripts/harness/schema_migration_validator.py
Inspected 17 UP migrations.  RESULT: PASS

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
```

### P2.3: 8 표준 스킬 시그니처 (완료)

**참조**: 07_SKILLS_SPEC.md §1~§8

8 스킬 모두 인터페이스 (dataclass, Enum, Exception) + 함수 시그니처 + Docstring 작성. 본문은 `NotImplementedError` (Phase 3에서 구현).

| 스킬 | 모듈 | 핵심 인터페이스 | 구현 Phase |
|------|------|-----------------|-----------|
| 1. kiwoom_api_skill | `skills/kiwoom_api_skill.py` | `KiwoomAPI{Request,Response,Context,Error}` + `call_kiwoom_api`, `send_buy_order`, `send_sell_order`, `cancel_order`, `get_balance`, `get_position`, `get_order_status` | P3.2 |
| 2. box_entry_skill | `skills/box_entry_skill.py` | `EntryDecision`, `Box`, `MarketContext`, `EntryEvaluation`, `evaluate_box_entry`, `is_pullback_setup`, `is_breakout_setup`, `is_bullish` | P3.1 |
| 3. exit_calc_skill | `skills/exit_calc_skill.py` | `PositionSnapshot`, `EffectiveStopResult`, `ProfitTakeResult`, `TSUpdateResult`, `calculate_effective_stop`, `evaluate_profit_take`, `update_trailing_stop`, `select_atr_multiplier`, `stage_after_partial_exit` | P3.3 |
| 4. avg_price_skill | `skills/avg_price_skill.py` | `PositionState`, `PositionUpdate`, `update_position_after_buy`, `update_position_after_sell`, `compute_weighted_average` | P3.4 |
| 5. vi_skill | `skills/vi_skill.py` | `VIState`, `VIStateContext`, `VIDecision`, `handle_vi_state`, `check_post_vi_gap`, `transition_vi_state` | P3.6 |
| 6. notification_skill | `skills/notification_skill.py` | `Severity`, `EventType`, `NotificationRequest`, `NotificationResult`, `send_notification`, `severity_to_priority`, `make_rate_limit_key`, `format_stop_loss_message` | P4.1 |
| 7. reconciliation_skill | `skills/reconciliation_skill.py` | `ReconciliationCase`, `KiwoomBalance`, `SystemPosition`, `ReconciliationResult`, `reconcile_positions`, `classify_case` | P3.5 |
| 8. test_template | `skills/test_template.py` | `TEMPLATE` 상수 (테스트 작성 패턴) | (참고용) |

**Candle 충돌 해결**: box_entry_skill의 자체 `Candle` 정의는 V7.0 `src.core.candle_builder.Candle`과 Harness 1 충돌 → V7.0 Candle을 import하여 재사용 (헌법 3 단일 정의 + 인프라 보존). `is_bullish()`는 별도 helper 함수로 분리.

**V71Constants 보강**: API 관련 상수 추가
- `API_MAX_RETRIES = 3`
- `API_BACKOFF_BASE_SECONDS = 1.0` (지수 백오프)
- `API_TIMEOUT_SECONDS = 10`
- `API_RATE_LIMIT_PER_SECOND = 4.5` / `API_RATE_LIMIT_PAPER_PER_SECOND = 0.33`
- `AUTH_ERROR_CODES = ("EGW00001", "EGW00002")`
- `RATE_LIMIT_ERROR_CODES = ("EGW00201",)`

**Harness 7 임계값 단계화**: Phase 2의 NotImplementedError stub은 본질적으로 0% coverage → 90% 임계값을 모든 v71/에 적용 시 의미 없는 차단. THRESHOLDS를 실제 로직 있는 모듈만 (`v71_constants.py`, `feature_flags.py`)으로 좁힘. Phase 3 commit에서 구현 + 테스트가 들어올 때 box/, exit/ 등을 임계값에 추가.

### P2.4 (일부): V71Constants 중앙화 (완료)

**참조**: 02_TRADING_RULES.md, 01_PRD_MAIN.md 부록 C

**산출물**

| 파일 | 내용 |
|------|------|
| `src/core/v71/v71_constants.py` | `V71Constants` 클래스. `Final[...]` 어노테이션. PRD §5/§3/§4/§10/§13 기준 모든 매직 넘버 (손절 -5/-2/+4, 익절 +5/+10/30%, ATR 4.0/3.0/2.5/2.0, 박스 30%/-20%, 매수 3회/5초, 갭 5%/3%, 폴링 5초, 알림 5분 등) |
| `tests/v71/test_v71_constants.py` | 25 PASS. 손절 단방향 상향, ATR 단방향 축소, 임계값 일관성, Final 어노테이션 등 룰 핀(pin) 검증 |

**Harness 3 보강**: `MAGIC_LITERAL_EXEMPT = {"src/core/v71/v71_constants.py"}` 추가. v71_constants가 매직 넘버 단일 정의 영역임을 명시 (다른 모든 V7.1 코드는 이 모듈 통해서만 참조 가능, 그것이 Harness 3의 본 의도).

**검증**: pytest 25/25 PASS, harnesses 7/7 PASS.

### P2.4 (잔여) + P2.5: 핵심 클래스 시그니처 + Feature Flag 가드 (완료)

**참조**: 04_ARCHITECTURE.md §5.3, 02_TRADING_RULES.md §3~§13

15개 V7.1 핵심 클래스/모듈 시그니처. 각 클래스의 `__init__`은 (1) 해당 Feature Flag로 `require_enabled()` 가드 호출, (2) `NotImplementedError` 발생. Phase 3에서 본문 채움.

| 모듈 | 클래스 | Feature Flag | 구현 Phase |
|------|--------|--------------|-----------|
| `box/box_manager.py` | `V71BoxManager` | `v71.box_system` | P3.1 |
| `box/box_entry_detector.py` | `V71BoxEntryDetector` | `v71.box_system` | P3.2 |
| `box/box_state_machine.py` | `TrackedStatus`, `BoxStatus`, transitions | `v71.box_system` | P3.1 |
| `strategies/v71_box_pullback.py` | `V71BoxPullbackStrategy` | `v71.pullback_strategy` | P3.2 |
| `strategies/v71_box_breakout.py` | `V71BoxBreakoutStrategy` | `v71.breakout_strategy` | P3.2 |
| `exit/exit_calculator.py` | `V71ExitCalculator` | `v71.exit_v71` | P3.3 |
| `exit/trailing_stop.py` | `V71TrailingStop` | `v71.exit_v71` | P3.3 |
| `exit/exit_executor.py` | `V71ExitExecutor` | `v71.exit_v71` | P3.3 |
| `position/v71_position_manager.py` | `V71PositionManager` | `v71.position_v71` | P3.4 |
| `position/v71_reconciler.py` | `V71Reconciler` | `v71.reconciliation_v71` | P3.5 |
| `path_manager.py` | `PathManager` | `v71.box_system` | P3.2 |
| `vi_monitor.py` | `V71ViMonitor` | `v71.vi_monitor` | P3.6 |
| `event_logger.py` | `EventLogger` | (인프라, 가드 없음) | Phase 3 |
| `restart_recovery.py` | `V71RestartRecovery` | `v71.restart_recovery` | P3.7 |
| `audit_scheduler.py` | `AuditScheduler` | `v71.monthly_review` | Phase 4 |

**Feature Flag 동작 검증**:

```
$ python -c "from src.core.v71.box.box_manager import V71BoxManager; V71BoxManager(db_context=None)"
RuntimeError: Feature flag 'v71.box_system' is disabled.
Enable in config/feature_flags.yaml or set V71_FF__V71__BOX_SYSTEM=true.
```

→ 모든 V7.1 신규 모듈은 import OK + Flag 가드가 `__init__` 시점에 차단. Phase 3 통합 시점에 플래그 활성화.

### 헌법 5원칙 자체 검증 (Phase 2 종료 시점)

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 자동 추천 0, 시그니처 모두 사용자가 PRD에서 명시 |
| 2. NFR1 최우선 | ✅ N/A (시그니처 단계) |
| 3. **충돌 금지 ★** | ✅ 모든 v71 클래스에 V71 접두사. Harness 1 PASS. V7.0 인프라(candle_builder.Candle 등) 그대로 import. V7.0 → V7.1 import 0 |
| 4. 시스템 계속 운영 | ✅ stub은 fail-fast로 안내, Flag 가드도 명확한 RuntimeError |
| 5. 단순함 우선 | ✅ Phase 2는 시그니처만, 본문은 Phase 3 |

### Phase 2 완료 (M2 마일스톤)

```
$ pytest tests/v71/ --no-cov -q
49 passed (test_feature_flags 24 + test_v71_constants 25)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)

$ python -c "import src.core.v71; ..."
all V7.1 packages + 15 modules + 8 skills import OK
```

산출물 (Phase 2 누적):
- 23 모듈 (8 skills + 15 core classes + v71_constants)
- 17 DB migrations (UP+DOWN paired, FK-ordered)
- 49 단위 테스트
- 모든 신규 클래스에 Feature Flag 가드

다음: **Phase 3 (거래 룰 구현)**. 가장 중요한 단계 (10~15일 예상).

---

## Phase 3 진입 직전 핸드오프 (2026-04-26 세션 종료 시점)

이 섹션은 **새 세션이 작업을 이어서 받기 위해 반드시 알아야 할 것들**을 정리합니다.

### 현재 상태 스냅샷

| 항목 | 값 |
|------|-----|
| 브랜치 | `v71-development` |
| 최신 commit | `27de823` (P2.4+P2.5 core classes + feature-flag gating) |
| 최신 tag | `v71-phase2-complete` |
| GitHub | https://github.com/ParkKyunHo/KstockSysytem |
| pytest | 49 PASS (`tests/v71/`) |
| 하네스 | 7/7 PASS (Harness 6 dead-code WARN 0건) |
| `python -m src.main` | V7.1 stub 메시지 + exit 1 (의도) |
| 로컬 디스크 | 35 MB (V7.0 백업 시점 316 MB → 89% 감소) |

### 사용자 정책 (반드시 준수)

1. **V7.0 = 레거시** (곧 폐기), **V7.1 = 완전 구축**. V7.0 코드는 보호 대상이 아니라 폐기 대상. 단 헌법 3 "충돌 금지"는 *운영 영향* 0이라는 의미 (별도 서버에서 V7.0이 운영 중일 수 있음).
2. **Python 호출**: 항상 `"C:\Program Files\Python311\python.exe"` 명시. `pip install` 시 32비트 Python 3.10이 PATH에서 우선 호출되어 pandas source build 무한 재귀 발생 → 명시 호출로 회피.
3. **`.env` 직접 read 금지**: 시스템 권한 정책으로 차단됨. 시크릿 노출 사고 2회 발생 (DB 비밀번호 회전 권고 미완 — 사용자에게 다시 권고할 것).
4. **Push 자동 권한**: 사용자가 권한 위임. 매 commit마다 push OK. 단 위험 작업(force push, branch 삭제 등)은 보고.
5. **Task 단위 진행**: 매 Task별 commit 분리. PRD 단일 진실 (임의 해석 금지). 의문 시 즉시 사용자 질문.
6. **statusline**: `~/.claude/statusline.sh` 단순화 1라인 (모델 / effort / ctx 사용량 / 5h 남은량 + 리셋 / 7d 남은량 + 리셋). 사용자가 고정 요청 → 변경 금지.

### Phase 3 시작 가이드 (P3.1부터)

**참조 문서 우선순위**:
1. `02_TRADING_RULES.md` §3 (박스 시스템 단일 진실)
2. `07_SKILLS_SPEC.md` §2 (`box_entry_skill` 구현 명세)
3. `03_DATA_MODEL.md` §2.1, §2.2 (`tracked_stocks`, `support_boxes`)
4. `06_AGENTS_SPEC.md` §1 (V71 Architect), §2 (Trading Logic Verifier) — Task별 페르소나 호출
5. `08_HARNESS_SPEC.md` §3 (Trading Rule Enforcer 룰 — 매직 넘버 차단)

**P3.1 산출물 예상**:
- `src/core/v71/box/box_manager.py` 본문 (V71BoxManager 메서드 구현)
- `src/core/v71/box/box_entry_detector.py` (구조 정리; 본문은 P3.2)
- `src/core/v71/box/box_state_machine.py` (transition 함수 구현)
- `src/core/v71/skills/box_entry_skill.py` 본문 (`evaluate_box_entry`, `is_pullback_setup`, `is_breakout_setup`)
- `tests/v71/test_box_manager.py` (90%+ 커버리지)
- `tests/v71/test_box_entry_skill.py`
- `tests/v71/test_box_state_machine.py`
- `scripts/harness/test_coverage_enforcer.py`의 THRESHOLDS에 `src/core/v71/box/`, `src/core/v71/skills/box_entry_skill.py` 추가 (90%)

**P3.1 완료 기준**:
- Trading Logic Verifier 페르소나 PASS (PRD §3 인용 + 룰 정확성 검증)
- 단위 테스트 90%+ 커버리지
- 7/7 하네스 PASS (Harness 7 임계값 강화 후에도)
- WORK_LOG.md 갱신
- commit 메시지에 "P3.1" 명시
- 다음 P3.2 진행 여부 사용자 확인

### 새 세션 첫 메시지 (사용자가 그대로 붙여넣기)

```
# V7.1 Phase 3 작업 이어서 진행

## 환경
- 프로젝트: C:\K_stock_trading\
- 브랜치: v71-development
- 최신 tag: v71-phase2-complete
- GitHub: https://github.com/ParkKyunHo/KstockSysytem

## 사전 학습 (필수, 순서대로)
1. C:\K_stock_trading\CLAUDE.md
2. C:\K_stock_trading\docs\v71\WORK_LOG.md  ← 가장 중요 (Phase 0~2 모든 결정 + 정책 + Phase 3 가이드)
3. C:\K_stock_trading\docs\v71\01_PRD_MAIN.md  (전체 그림)
4. C:\K_stock_trading\docs\v71\05_MIGRATION_PLAN.md §5 (Phase 3 계획)
5. C:\K_stock_trading\docs\v71\02_TRADING_RULES.md §3 (P3.1 박스 시스템 룰)
6. C:\K_stock_trading\docs\v71\07_SKILLS_SPEC.md §2 (box_entry_skill)

## 헌법 5원칙 (절대 위반 금지)
1. 사용자 판단 불가침
2. NFR1 최우선 (박스 진입 < 1초)
3. 충돌 금지 ★ (V7.0 인프라 14모듈 보존, V7.1은 src/core/v71/ 격리)
4. 시스템 계속 운영
5. 단순함 우선

## 응답 요청
위 6개 문서 정독 후:
1. Phase 0~2 누적 산출물 요약 (WORK_LOG 기준)
2. Phase 3 P3.1 (박스 시스템) 작업 계획
3. 시작 준비 상태

응답 후 P3.1 시작 지시 대기.
```

### 권고 사항 (사용자 확인 필요)

- DB 비밀번호 회전 (보안 사고 #1, #2 대응) — Supabase Dashboard
- Phase 3 진입 일정

### Phase 0 후속: pre-commit 활성화 시 발견 사항

| 이슈 | 원인 | 조치 |
|------|------|------|
| `pip install ".[dev]"` 실패 (pandas 메타데이터 생성 RecursionError) | 32비트 Python 3.10 (`C:\Python310-32`) pip이 PATH에서 우선 호출되어 source build 시도 | `"C:\Program Files\Python311\python.exe" -m pip install pre-commit ruff mypy pytest-asyncio pytest-cov alembic aiosqlite`로 명시 설치 |
| 첫 pre-commit 실행이 V7.0 60파일 자동 수정 | ruff scope 패턴 `^(src/\|...)`이 V7.0까지 포함 | scope 축소: `^(src/core/v71/\|src/utils/feature_flags\.py$\|scripts/harness/\|tests/v71/)`. V7.0 lint 정리는 Phase 1 폐기로 자연 해소 |

**Phase 0 최종 검증 (모두 PASS)**:
```
$ python -m pre_commit run --all-files
V71 Harness 1~6  Passed
ruff             Passed
```

---

## Phase 1: 인프라 정리 (진행 중)

### P1.1: OpenClaw 정리 (완료)

**참조**: 05_MIGRATION_PLAN.md §3.2

**영향 분석**: `grep -ri "openclaw|OpenClaw|kiwoom_ranking|@stock_Albra_bot|Maltbot|gemini" src/` → **0건** (OpenClaw은 외부 시스템이었음 — 코드 베이스 격리 양호)

**삭제 항목**

| 항목 | 종류 | 비고 |
|------|------|------|
| `docs/OPENCLAW_GUIDE.md` | 8.7 KB 문서 | 제거 |
| `scripts/openclaw/switch-model.ps1` | 모델 전환 스크립트 | 제거 |
| `scripts/openclaw/` | 디렉토리 | 빈 디렉토리도 제거 |
| `CLAUDE.md` Part 0 (OpenClaw 텔레그램 AI 어시스턴트, 0.1~0.7) | ~97 라인 섹션 | 제거 |
| `CLAUDE.md` 라인 9 (OpenClaw 필독 안내) | 1 라인 | 제거 |
| `CLAUDE.md` 라인 278 (문서 참조표) | 1 라인 | V7.1 PRD 참조로 교체 |

**CLAUDE.md 헤더 업데이트**: 버전 표기를 `V7.0 Purple-ReAbs (Phase 3 리팩토링 완료)` → `V7.1 (Box-Based Trading System, in development) -- V7.0 Purple-ReAbs is legacy`. V7.1 PRD 진입점 명시.

**사용자 직접 정리 (외부 시스템, 코드 베이스 외)**:
- `~/.openclaw/` 디렉토리 삭제
- Windows Scheduled Task "OpenClaw Gateway" 비활성/삭제
- Telegram 봇 (`@stock_Albra_bot`) 정리 (선택)

### P1.2: 백테스트 시스템 삭제 (완료)

**참조**: 05_MIGRATION_PLAN.md §3.3

**영향 분석**: `grep -ri "backtest|backtest_modules" src/` → **0건** (백테스트는 항상 src/ 외부에 있음)

**삭제 항목** (git + 디스크)

| 항목 | 종류 | 비고 |
|------|------|------|
| `scripts/backtest/` | 디렉토리 (113 파일, 11 서브 디렉토리) | daily_equity_curve, december_pipeline, ema_split_buy, leading_stock_analysis, sniper_trap_*.py, v7_intraday |
| `run_backtest_ui.py` | 루트 진입 스크립트 | 제거 |
| `docs/BACKTEST_GUIDE.md` | 가이드 문서 | 제거 |
| `data/backtest/`, `data/cache/` | V7.0 백테스트 캐시 | 디스크 정리 (이미 .gitignored) |
| `3m_data/` | 3분봉 .xls 캐시 (57 파일, 128 MB) | 디스크 정리 (이미 .gitignored) |
| `results/` | 백테스트 결과 디렉토리 | 디스크 정리 (이미 .gitignored) |
| 루트 `*.csv` (3mintest, testday, past1000*) | 백테스트 입력 캐시 | 디스크 정리 |
| 루트 `*.xlsx` (ema_split_buy_*, full_3min_backtest_*, improved_entry_backtest_*) | 백테스트 결과 | 디스크 정리 |
| `__pycache__/` (scripts/backtest 내) | 컴파일 캐시 | 디스크 정리 |

**git 영향**: 56개 파일 삭제 (트래킹 파일 기준)

**CLAUDE.md 변경**:
- Part 3.6 "백테스트" 섹션을 V7.1에서 폐기됨 안내로 축약
- Part 4.1 "문서" 표에서 `docs/BACKTEST_GUIDE.md` 행 제거

**보존 (V7.1 검증 방식)**: 페이퍼 트레이드 (Phase 7) + 단위 테스트 (>=90% coverage). 별도 백테스트 인프라 불요.

### P1.4 + P1.5 + P1.6 + P1.7 + P1.8: V7.0 거래 로직 일괄 폐기 (완료)

사용자 지침 "V7.0=레거시, V7.1=완전 구축"에 따라, V7.0 trading_engine부터 V6/V7 신호 시스템 + 의존 V7.0 거래 로직 + 미완성 추상화까지 한 번에 정리. 인프라(candle_builder, websocket, market_*, db, api, notification, utils, risk_manager, universe, system_health_monitor, subscription_manager, realtime_data_manager, background_task_manager, market_monitor, indicator_library, constants)는 보존하여 Phase 2/3에서 V7.1과 통합 결정.

**P1.8 (이미 commit `3a69b09`)**: trading_engine.py + main.py + src/core/__init__.py V7.1 stub 전환, condition_search_handler/manual_command_handler 삭제 (4817 lines deleted).

**P1.4 + P1.5 + P1.6 + P1.7 (이번 commit)**:

| 분류 | 삭제 항목 | 출처 |
|------|----------|------|
| V7 신호 시스템 (P1.5) | `signal_pool`, `signal_processor`, `signal_detector_purple`, `v7_signal_coordinator`, `strategy_orchestrator`, `missed_signal_tracker`, `watermark_manager`, `atr_alert_manager`, `indicator_purple` | PRD §2.1.5 |
| V6 SNIPER_TRAP (P1.4) | `signal_detector` (V6용), `auto_screener`, `exit_manager`, `indicator` (V6 위임) | PRD §2.1.4 |
| V7.0 거래 인프라 (V7.1에서 새로) | `order_executor`, `position_manager`, `position_recovery_manager`, `position_sync_manager` | 사용자 지침 |
| V7.0 청산 (P1.7) | `wave_harvest_exit`, `exit_coordinator` | V7.1에서 신규 (`src/core/v71/exit/`) |
| 폐기 strategies | `strategies/v6_sniper_trap`, `strategies/v7_purple_reabs`, `strategies/base_strategy`, `strategies/__init__` | PRD §2.1.4-§2.1.5 |
| 미완성 추상화 (P1.6) | `src/core/detectors/`, `src/core/signals/`, `src/core/exit/`, `src/strategy/`, 루트 `strategies/` | PRD §2.1.6 |
| 폐기 테스트 | `test_wave_harvest_exit`, `test_exit_coordinator`, `test_abc_conformance` | 폐기 모듈 의존 |

**잔존 V7.0 인프라 (Phase 2/3 통합 결정)**

`src/core/`: 14개 모듈
```
__init__.py, trading_engine.py (stub), candle_builder.py, websocket_manager.py,
market_schedule.py, market_monitor.py, background_task_manager.py,
realtime_data_manager.py, risk_manager.py, universe.py,
subscription_manager.py, system_health_monitor.py, indicator_library.py,
constants.py
```

**검증 (모두 PASS)**

```
$ pytest tests/ --no-cov -q
82 passed in 7.03s
  - tests/test_background_task_manager  18
  - tests/test_notification_queue       25
  - tests/test_websocket_manager        15
  - tests/v71/test_feature_flags        24

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - Harness 6 (Dead Code) WARN count: 32 -> 0  (자동 해소)

$ python -c "import src.core; import src.api; import src.database; ..."
all import OK
```

### P1.3: 임시 파일 정리 (완료)

**참조**: 05_MIGRATION_PLAN.md §3.4

**삭제 대상** (모두 디스크에서, 이미 `.gitignore`에 차단되어 있어 git 영향 0)

| 분류 | 파일/디렉토리 | 크기 |
|------|---------------|------|
| Unix→Windows 셸 호출 오인식 잔재 | `C:K_stock_trading*.txt` 12개 (콜론 위치에 U+F03A 비가시 문자) | ~80 MB |
| 위와 동일 | `C:Users박균호temp_log.txt`, `C:templogs.txt`, `C:K_stock_trading.env.{new,recovered}`, `C:K_stock_tradingtemp_check.ps1` | ~5 KB |
| 일반 임시 로그 | `temp_full.txt`, `temp_logs.txt`, `temp_logs2.txt` | ~2.5 MB |
| Windows 예약어 | `nul` (잘못된 SSH known_hosts 파편) | 169 B |
| 분석 산출물 | `data/analysis/` (큰 `.txt` 로그 파일 포함) | ~30 MB |
| 캐시 | `__pycache__/` 14개 디렉토리 | ~수 MB |
| 캐시 | `.pytest_cache/`, `.coverage`, `coverage.json` | ~수십 KB |

**디스크 사용량 변화**:

| 시점 | 크기 | 감소 |
|------|------|------|
| P0.1 (초기) | 316 MB | -- |
| P1.2 후 (백테스트 캐시 정리) | 92 MB | 71% |
| P1.3 후 (임시 + analysis 정리) | **35 MB** | **89%** |

**잔존 (의도)**:
- `node_modules/` (13 MB) — 외부 npm 의존성, 추후 별도 결정
- `logs/` (29 KB) — 운영 로그, 보존
- `k_stock_trading.egg-info/` — pip editable install 부산물

**git 영향 0** (.gitignore 패턴이 이미 모두 차단). commit 대상은 WORK_LOG.md만.

---

## 다음 작업 (Phase 1 잔여)

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

## Phase 3: 거래 룰 구현 (진행 중)

### P3.1: 박스 시스템 + 09:01→09:05 fallback 안전장치 (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §3, §10.9, 07_SKILLS_SPEC.md §2, 05_MIGRATION_PLAN.md §5.2

**사용자 요구로 추가된 안전장치 (PRD patch #1)**

> 추적종목이 장 시작 시초가 VI에 걸리면 09:01 매수 단일가 영역에서 미체결될 가능성. 1차 실패 시 09:05 시장가 fallback을 추가해야 함.

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| PRD | `02_TRADING_RULES.md §3.10`, `§3.11` | 1차 09:01 + 2차 09:05 fallback 룰 추가 |
| PRD | `02_TRADING_RULES.md §10.9` (신규) | 시초 VI 시나리오 설명, 일반 VI 갭 3% vs 시초 VI 갭 5% 차이 명시 |
| PRD | `07_SKILLS_SPEC.md §2.3` | `EntryDecision` dataclass에 `fallback_buy_at`, `fallback_uses_market_order`, `fallback_gap_recheck_required` 필드 추가 |
| PRD | `07_SKILLS_SPEC.md §2.4` | `check_gap_up_for_path_b`를 1차/2차 공통 함수로 명시 |
| PRD | `13_APPENDIX.md §6.2` (신규) | PRD 변경 이력 #1 기록 |
| 코드 | `src/core/v71/v71_constants.py` | `PATH_B_PRIMARY_BUY_TIME_HHMM = "09:01"`, `PATH_B_FALLBACK_BUY_TIME_HHMM = "09:05"`, `PATH_B_FALLBACK_USES_MARKET_ORDER = True` (기존 `PATH_B_BUY_TIME_HHMM`은 rename) |
| 코드 | `src/core/v71/box/box_state_machine.py` | `TrackedStatus`/`BoxStatus` Enum + `TrackedEvent`/`BoxEvent` Enum + 전이 검증 함수 (`transition_tracked_stock`, `transition_box`, `is_*_terminal`, `allowed_*_events`). `IllegalTransitionError`. 100% 커버리지 |
| 코드 | `src/core/v71/skills/box_entry_skill.py` | `evaluate_box_entry` (PATH_A/B × PULLBACK/BREAKOUT 4 분기), `is_pullback_setup`/`is_breakout_setup`/`is_bullish` 헬퍼, `check_gap_up_for_path_b` (1차/2차 공통), PATH_B 결과에 fallback 메타데이터 자동 채움. V7.0 `Candle` 재사용 (헌법 3). 94.1% 커버리지 |
| 코드 | `src/core/v71/box/box_manager.py` | `V71BoxManager` (in-memory) + `BoxRecord` dataclass + 4종 예외 (Validation/Overlap/Modification/NotFound). `create_box`/`modify_box`/`delete_box`/`mark_triggered`/`mark_invalidated`/`check_30day_expiry`/`mark_reminded`/`validate_no_overlap`. 98.6% 커버리지 |
| 코드 | `src/core/v71/box/box_entry_detector.py` | 시그니처 정리 (P3.2 wiring 인터페이스 명시: `CandleSource` Protocol, `OnEntryCallback` TypeAlias, `start`/`check_entry` 시그니처). 본문은 P3.2 |
| 테스트 | `tests/v71/test_v71_constants.py` | fallback 상수 PIN 테스트 4개 추가 (29 PASS) |
| 테스트 | `tests/v71/test_box_state_machine.py` (신규) | 49 PASS |
| 테스트 | `tests/v71/test_box_entry_skill.py` (신규) | 35 PASS (fallback 메타데이터 검증 포함) |
| 테스트 | `tests/v71/test_box_manager.py` (신규) | 38 PASS |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 P3.1 모듈 3개 추가 (모두 90% 임계값) |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
175 passed in 0.65s
  - test_feature_flags         24
  - test_v71_constants         29
  - test_box_state_machine     49
  - test_box_entry_skill       35
  - test_box_manager           38

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - Harness 7 임계값:
    feature_flags.py             96.8%
    v71_constants.py            100.0%
    box/box_state_machine.py    100.0%
    box/box_manager.py           98.6%
    skills/box_entry_skill.py    94.1%
```

**fallback 안전장치 핵심 룰 핀 (테스트 강제)**

| 핀 | 출처 | 테스트 |
|----|------|--------|
| 09:01 / 09:05 시각 정확성 | §3.10/§3.11 | `test_path_b_*_buy_at_*` |
| fallback이 1차보다 뒤 | §10.9 | `test_path_b_fallback_is_after_primary` |
| fallback은 시장가 강제 | §10.9 | `test_path_b_fallback_uses_market_order` |
| fallback 시점 갭업 5% 재검증 | §10.9 | `test_pullback_b_triggered_with_fallback`, `check_gap_up_for_path_b` 테스트 5개 |
| PATH_A 결과는 fallback 미적용 | §3.8/§3.9 | `test_normal_breakout`, `test_both_candles_meet_conditions` (fallback_* = None/False) |
| 1차 갭업 5% 초과는 안전장치 미발동 | §3.10 | `test_gap_at_exact_5pct_does_not_proceed` (PATH_B 매수 자체 거부) |

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자가 등록한 박스를 안전장치로 보호 (1회 매수 실패로 영구 포기 안 함) |
| 2. NFR1 최우선 | ✅ 박스 진입 1회 더 시도, 4분 지연 허용 범위 내. `evaluate_box_entry`는 동기 함수 + DB 호출 없음 |
| 3. 충돌 금지 ★ | ✅ 모든 신규 클래스 `V71*` 또는 `v71/` 격리. V7.0 `Candle`/`market_schedule` 단방향 import만. Harness 1/2/6 PASS |
| 4. 시스템 계속 운영 | ✅ ValueError/RuntimeError로 fail-fast하되 시스템 정지 코드 0. 안전장치 자체가 운영 지속의 일부 |
| 5. 단순함 | ✅ 5분 1회 fallback (무한 재시도 X). state machine은 transition table 1개. 박스 manager는 in-memory dict |

**P3.2 핸드오프 항목**

- `V71BoxEntryDetector.check_entry`/`start` 본문 구현 (`box_entry_skill.evaluate_box_entry` 호출)
- `V71BuyExecutor` 신규 모듈: `EntryDecision` 받아 매수 실행
  - PATH_A: 즉시 지정가 매수 (1호가 위) × 5초 × 3회 → 시장가
  - PATH_B 1차 09:01: 동일 시퀀스
  - PATH_B 2차 09:05: `fallback_buy_at` 도달 + 1차 미체결 시 `check_gap_up_for_path_b(prev_close, 09:05_current)` 통과하면 시장가 매수, 통과 못하면 포기 + HIGH 알림
- `V71BoxEntryDetector` 임계값을 Harness 7에 추가
- `vi_recovered_today` 플래그가 fallback에는 적용되지 않는 룰 (§10.9 마지막 조항) 명시적 테스트

### Phase 3 진행 현황

| Task | 상태 |
|------|------|
| P3.1 박스 시스템 (+ 09:05 fallback 메타데이터) | ✅ 완료 |
| P3.2 매수 실행 (PATH_A/B + 09:05 fallback executor + entry detector) | ✅ 완료 |
| P3.3 매수 후 관리 (단계별 손절 + 분할 익절 + TS) | ✅ 완료 |
| P3.4 평단가 관리 + V71PositionManager (in-memory) | ✅ 완료 |
| P3.5 수동 거래 처리 (Reconciler) | ✅ 완료 |
| P3.6 VI 처리 (V71ViMonitor + vi_skill) | ✅ 완료 |
| **P3.7 시스템 재시작 복구 (V71RestartRecovery)** | ✅ 완료 |

**Phase 3 = 거래 룰 구현 = 100% 완료** -- 마일스톤 M3 달성

---

### P3.2: 매수 실행 + 09:05 fallback executor + entry detector (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §4 (매수 실행), §3.10/§3.11 (PATH_B), §10.9 (시초 VI 안전장치), 04_ARCHITECTURE.md §5.3, 05_MIGRATION_PLAN.md §5.3, 07_SKILLS_SPEC.md §1

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/skills/kiwoom_api_skill.py` | `V71OrderType`, `V71OrderSide`, `V71Orderbook`, `V71OrderResult`, `V71OrderStatus` 추가 (V7.0 충돌 회피, V71 접두사). `OrderRejectedError` 추가. `ExchangeAdapter` Protocol (P3.2의 매수/청산 executor 진입점). 실제 HTTP 본문은 V7.0 통합 단계에서 |
| 코드 | `src/core/v71/strategies/v71_buy_executor.py` (신규) | `V71BuyExecutor` 메인 코디네이터. PATH_A 즉시 매수 + PATH_B 09:01 1차 + PATH_B 09:05 2차 fallback. 매수 시퀀스 (limit × 3, 5s wait + market). 30% per-stock cap (§3.4). VI 가드 (PATH_A 차단, PATH_B 1차/2차 정책 차등). `BuyExecutorContext` (5개 의존성 + 4개 callable). `BuyOutcome` (FILLED/PARTIAL_FILLED/ABANDONED_*/REJECTED/FAILED). 91.3% 커버리지 |
| 코드 | `src/core/v71/box/box_entry_detector.py` | P3.1 시그니처 → P3.2 본문. one-detector-per-path 정책. `start()` idempotent. `check_entry()`: prev candle 캐시 + box_entry_skill 호출 + on_entry callback. `_on_bar_complete_sync`: V7.0 candle pipeline에 sync 콜백 등록 + asyncio.create_task로 스케줄 + 예외 swallow. 93.1% 커버리지 |
| 코드 | `src/core/v71/strategies/v71_box_pullback.py` / `v71_box_breakout.py` | thin factory wrappers (PRD §5.3 명시). `create_box`가 `strategy_type` 자동 pinning. dedicated feature flag (`v71.pullback_strategy` / `v71.breakout_strategy`) 가드. 100% 커버리지 |
| 테스트 | `tests/v71/test_v71_buy_executor.py` (신규) | 18 PASS. PATH_A 즉시(4) + 매수 시퀀스(2) + PATH_B 1차/2차(5) + negative-decision(1) + broker errors(2) + fallback edge cases(4: rejected short-circuit, transport→fallback defer, fallback transport, fallback cap during window) |
| 테스트 | `tests/v71/test_v71_box_entry_detector.py` (신규) | 8 PASS. start idempotent + 라우팅 (unresolved/empty/pullback dispatch/path mismatch/callback exception isolation) + sync hook (no loop / running loop schedule) |
| 테스트 | `tests/v71/test_v71_box_strategies.py` (신규) | 5 PASS. PULLBACK/BREAKOUT 전략 type pinning + feature flag gate |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 P3.2 모듈 4개 추가 (모두 90% 임계값) |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
206 passed in 0.84s
  - test_feature_flags                24
  - test_v71_constants                29
  - test_box_state_machine            49
  - test_box_entry_skill              35
  - test_box_manager                  38
  - test_v71_buy_executor             18  (P3.2 신규)
  - test_v71_box_entry_detector        8  (P3.2 신규)
  - test_v71_box_strategies            5  (P3.2 신규)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - Harness 1 (Naming Collision):  Order* → V71Order* rename으로 V7.0 충돌 0건
  - Harness 7 임계값 (P3.1 + P3.2):
    box/box_state_machine.py        100.0%
    box/box_manager.py               99.3%
    skills/box_entry_skill.py        94.1%
    box/box_entry_detector.py        93.1%
    strategies/v71_buy_executor.py   91.3%
    strategies/v71_box_pullback.py  100.0%
    strategies/v71_box_breakout.py  100.0%
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| 매수 시퀀스: 지정가(매도1호가) × 3 + 시장가 | §4.1, §4.2 | `test_three_unfilled_limits_then_market_fills` |
| 매수 시퀀스 모두 미체결 → FAILED | §4.8 | `test_all_attempts_fail` |
| PATH_A VI active → 즉시 차단 | §4 | `test_vi_active_blocks_path_a` |
| 30% per-stock cap | §3.4 | `test_cap_exceeded_blocks_buy` |
| target_qty=0 (cap/가격 부적합) → ABANDONED_CAP | §3.3 | `test_target_quantity_zero_blocks_buy` |
| **PATH_B 1차 09:01 시점에 sleep_until** | §3.10 | `test_primary_normal_fill` (sleep_untils=[09:01]) |
| **갭업 5%(1차) → fallback 미발동, 매수 영구 포기** | §3.10/§3.11 | `test_primary_gap_up_5pct_blocks_buy_no_fallback` (sleep_untils=[09:01]만, 09:05 미진입) |
| **PATH_B 1차 미체결 → 09:05 fallback 시장가 진입** | §10.9 | `test_primary_unfilled_triggers_905_fallback_and_fills` (sleep_untils=[09:01, 09:05]) |
| **fallback 시점 갭업 재검증 5% 초과 → 안전장치 무력화** | §10.9 | `test_fallback_gap_recheck_invalidates_safety_net` |
| **부분 체결 + fallback 잔량 시장가 → 가중평균 평단가** | §4.3, §10.9 | `test_fallback_after_partial_fill_uses_weighted_average` (200@18200 + 349@18500) |
| **PATH_B 1차 broker reject → fallback 미발동, REJECTED** | §4.8 | `test_path_b_primary_rejected_short_circuits` |
| **PATH_B 1차 transport error → fallback 자동 진입** | §10.9 | `test_path_b_primary_transport_error_defers_to_fallback` |
| **fallback transport error → FAILED** | §4.8 | `test_fallback_transport_error_returns_failed` |
| **fallback 시점 cap 재검증** (09:01~09:05 사이 사용자 수동 매수 감지) | §3.4 | `test_fallback_cap_exceeded_during_window` |
| Box marked TRIGGERED + position 생성 + HIGH 알림 (성공 시) | §4.9 | `test_normal_full_fill` |
| Box WAITING 유지 + 알림만 (포기 시) | §3.13 | 모든 ABANDONED_* 테스트 |

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ `BoxRecord` 그대로 실행, 자동 추천 0. 09:05 fallback도 사용자 박스 결정의 마무리 |
| 2. NFR1 최우선 | ✅ PATH_A는 동기 cap/VI 검증 후 즉시 매수. DB 호출 없음. PATH_B 09:01/09:05만 의도적 sleep |
| 3. 충돌 금지 ★ | ✅ Order* → V71Order* rename으로 V7.0 (`src/api/endpoints/order.py`, `src/database/models.py`) 충돌 해소. `v71/strategies/`, `v71/box/` 격리. V7.0 → V7.1 import 0. Harness 1/2/6 PASS |
| 4. 시스템 계속 운영 | ✅ Broker reject/transport error는 typed exception + HIGH 알림으로 surface, 시스템 정지 0. detector callback exception은 isolation (한 box 실패가 다른 box 차단 안 함) |
| 5. 단순함 | ✅ 매수 시퀀스 4단계 + fallback 1회. 의존성은 5개 Protocol/Callable로 명시. detector one-per-path |

**P3.3 핸드오프 항목**

- `BoxRecord`에 `stock_code` 필드 추가 검토 (현재 `tracked_stock_resolver` callback hop 사용 중)
- `PositionStore` Protocol 구현체: P3.4 V71PositionManager가 정식 DB 연결 (Supabase `positions` 테이블)
- `Notifier` Protocol 구현체: P4.1 V71NotificationService
- `Clock` Protocol 구현체: 운영용 RealClock (asyncio.sleep + datetime.now wrapper) — 현재 테스트만 FakeClock 사용
- `is_vi_active` callable: P3.6 V71ViMonitor가 wires
- `_buy_sequence`의 호가 소진(§4.4) 처리는 별도 구현 필요 — 현재는 limit 가격 ask_1 한 번만 사용
- 부분 체결 시 §4.3에 따른 "재시도 시 시도 카운트 1회 증가" 룰 — 현재 구현은 한 attempt에서 partial fill되면 다음 attempt가 잔량 처리 (정확)
- 슬리피지 알림 (§4.4): 향후 결정 (PRD에 임계치 미정)

---

*최종 업데이트: 2026-04-26 (P3.2 완료)*

---

### P3.3: 매수 후 관리 -- 단계별 손절 + 분할 익절 + Trailing Stop (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §5 (post-buy management), 07_SKILLS_SPEC.md §3, 04_ARCHITECTURE.md §5.3, 05_MIGRATION_PLAN.md §5.4

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/skills/exit_calc_skill.py` | 시그니처 → 본문. `calculate_effective_stop` (FIXED vs TS-if-binding), `evaluate_profit_take` (+5/+10 30% 분할), `update_trailing_stop` (BasePrice + ATR 배수, 단방향), `select_atr_multiplier` (4.0/3.0/2.5/2.0 단방향 축소), `stage_after_partial_exit` (-5/-2/+4 단방향 상향). 99.1% 커버리지 |
| 코드 | `src/core/v71/position/state.py` (신규) | `PositionState` mutable dataclass -- 매수/매도 시 in-place mutation. P3.4에서 V71PositionManager가 DB hydration. 100% 커버리지 |
| 코드 | `src/core/v71/exit/trailing_stop.py` | 시그니처 → 본문. `V71TrailingStop.on_bar_complete(position, current, atr)` -- `update_trailing_stop` 호출 + position에 in-place 반영. 100% 커버리지 |
| 코드 | `src/core/v71/exit/exit_calculator.py` | 시그니처 → 본문. `V71ExitCalculator.on_tick(position, current, atr) -> ExitDecision`. effective_stop + profit_take 통합. mutation 없음 (decision-only). 100% 커버리지 |
| 코드 | `src/core/v71/exit/exit_executor.py` | 시그니처 → 본문. `V71ExitExecutor` (execute_stop_loss/ts_exit/profit_take). 매도 시퀀스 (지정가 매수1호가 × 3 + 시장가). 청산 후 PositionState mutate (수량/플래그/손절선/status). §5.9 cleanup: `V71BoxManager.cancel_waiting_for_tracked` + `on_position_closed` 콜백. CRITICAL/HIGH 알림. 92.6% 커버리지 |
| 코드 | `src/core/v71/box/box_manager.py` | `cancel_waiting_for_tracked(tracked_id, reason)` 메소드 추가 (§5.9 전량 청산 시 미진입 박스 정리) |
| 테스트 | `tests/v71/test_exit_calc_skill.py` (신규) | 36 PASS. 단계별 손절선 (3) + ATR 배수 매트릭스 (9) + 단방향 축소 (2) + TS 활성화/BasePrice/Stop 단방향 (5) + ATR warmup (1) + effective_stop 단계별 (5) + profit_take 8개 시나리오 |
| 테스트 | `tests/v71/test_v71_trailing_stop.py` (신규) | 5 PASS. 활성화 임계값, BasePrice 단방향, multiplier tighten-and-lock, ATR warmup |
| 테스트 | `tests/v71/test_v71_exit_calculator.py` (신규) | 6 PASS. tick 판정, stop trigger, profit_5/10 라우팅, TS binding gate (only after profit_10) |
| 테스트 | `tests/v71/test_v71_exit_executor.py` (신규) | 12 PASS. 손절 (4: full sell + sibling cancel + callback + market 실패) + TS exit (1) + 분할 익절 (5: profit_5/10 staging + cap + reject + transport) + 매도 시퀀스 (1) |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 P3.3 모듈 5개 추가 (모두 90% 임계값) |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
265 passed in 0.93s
  - test_feature_flags                24
  - test_v71_constants                29
  - test_box_state_machine            49
  - test_box_entry_skill              35
  - test_box_manager                  38
  - test_v71_buy_executor             18
  - test_v71_box_entry_detector        8
  - test_v71_box_strategies            5
  - test_exit_calc_skill              36   (P3.3 신규)
  - test_v71_trailing_stop             5   (P3.3 신규)
  - test_v71_exit_calculator           6   (P3.3 신규)
  - test_v71_exit_executor            12   (P3.3 신규)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - Harness 7 임계값 (P3.1 + P3.2 + P3.3):
    skills/exit_calc_skill.py        99.1%
    exit/exit_calculator.py         100.0%
    exit/exit_executor.py            92.6%
    exit/trailing_stop.py           100.0%
    position/state.py               100.0%
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| 손절선 단계별 상향: -5% → -2% (after +5%) → +4% (after +10%) | §5.4 | `test_stage_after_partial_exit::test_strictly_upward` |
| 손절 단방향만 (하향 안 함) | §5.4 | `test_stage_*` (수학적으로 a<b<c 순서 보장) |
| 분할 익절 +5% 30% 청산 1회만 | §5.2 | `test_5pct_idempotent_after_executed` |
| 분할 익절 +10% 30% 청산 (1차 후만) | §5.3 | `test_at_10pct_after_5_exits`, `test_10pct_blocked_until_5_first` |
| ATR 배수 단계: 4.0/3.0/2.5/2.0 (수익률별) | §5.5 | `test_tier_assignment[*]` (9 케이스) |
| ATR 배수 **단방향 축소만** (다시 안 넓어짐) | §5.5 | `test_one_way_tightening_does_not_widen`, `test_multiplier_tightens_then_locks` |
| TS BasePrice 단방향 상승 (매수 후 최고가) | §5.5 | `test_base_price_one_way_when_price_drops`, `test_base_price_one_way_upward` |
| TS 청산선 단방향 상승 (낮아지지 않음) | §5.5 | `test_stop_one_way_upward` |
| TS 활성화: +5% / 청산선 유효: +10% 청산 후 | §5.5 | `test_ts_binding_only_after_profit_10`, `test_stage_2_uses_fixed_only_even_if_ts_higher` |
| 유효 청산선 = max(고정, TS-if-binding) | §5.6 | `test_stage_3_max_of_fixed_and_ts`, `test_stage_3_falls_back_to_fixed_when_higher` |
| Trend Hold Filter 폐기 (조건 충족 즉시 청산) | §5.7 | implicit (calculator는 trigger=true이면 stop_triggered=true 반환) |
| 손절 시 시장가 매도 전량 (limit phase 스킵) | §5.1 | `test_full_market_sell_closes_position` (orders_sent[0].order_type==MARKET) |
| 분할 익절: 매수1호가 × 3 + 시장가 | §5.2/§5.3 + §4.2 | `test_three_unfilled_limits_then_market` (4 orders, 3 cancels, last=MARKET) |
| 전량 청산 시 미진입 박스 CANCELLED | §5.9 | `test_full_exit_cancels_sibling_waiting_boxes` |
| 전량 청산 시 시세 구독 해제 콜백 | §5.9 | `test_on_position_closed_callback_fires` |
| 손절 알림 CRITICAL / 익절 알림 HIGH | §5.9 | `test_full_market_sell_closes_position` (severity assertion) |

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 단계 후퇴 없음 (한 번 +4%로 올라간 손절선은 다시 -2% 안 됨), Trend Hold Filter 폐기로 사용자 룰 그대로 실행 |
| 2. NFR1 최우선 | ✅ 손절은 시장가 즉시 (limit phase 스킵), 매 틱 sync 판정 (DB 호출 없음) |
| 3. 충돌 금지 ★ | ✅ V71 접두사 (V71ExitExecutor/Calculator/TrailingStop), v71/exit/ + v71/position/ 격리. V7.0 → V7.1 import 0. Harness 1/2/6 PASS |
| 4. 시스템 계속 운영 | ✅ Broker reject/transport error는 typed exception + CRITICAL/HIGH 알림으로 surface. position state는 mutation 보수적 (실패 시 미변경) |
| 5. 단순함 | ✅ exit_calc_skill 5개 함수가 모든 룰 표현. V7.0 "Highest(High,20)" → V7.1 "post-buy 단순 최고가". Trend Hold Filter 폐기. Max Holding 무제한 |

**P3.4 핸드오프 항목**

- `PositionState` → DB 영속화: P3.4 `V71PositionManager`가 in-memory mutation을 Supabase `positions` 테이블 + `trade_events`에 동기화
- `PositionStore` Protocol 확장: P3.2 `add_position` 외에 `update_after_partial_exit`, `close_position` 추가 (현재 ExitExecutor는 직접 mutate 중)
- `avg_price_skill` 본문 구현: 추가 매수 가중평균 + 이벤트 리셋 (`profit_5/10_executed = False`) + 손절선 stage 1 복귀
- `V71BuyExecutor`/`V71ExitExecutor`의 PositionStore 사용을 `V71PositionManager`로 이관
- ATR 데이터 공급: 현재 `atr_value` float을 외부 주입; P3.4/P3.7에서 V7.0 `indicator_library` 호출 wiring
- 시세 구독 해제 콜백 (`on_position_closed`): P3.6 V71ViMonitor / P3.7 RestartRecovery에서 wires
- `Notifier` Protocol 구현체: P4.1 V71NotificationService

---

*최종 업데이트: 2026-04-26 (P3.3 완료)*

---

### P3.4: 평단가 관리 + V71PositionManager (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §6, 07_SKILLS_SPEC.md §4, 03_DATA_MODEL.md §2.3, 05_MIGRATION_PLAN.md §5.5

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/skills/avg_price_skill.py` | 시그니처 → 본문. 자체 PositionState 제거 + P3.3 PositionState (`src/core/v71/position/state.py`) 재사용. `compute_weighted_average` (pure helper), `update_position_after_buy` (신규/추가 분기 + 이벤트 리셋 + 손절선 stage 1 복귀 + ts_base/initial_avg 보존), `update_position_after_sell` (avg 유지, 수량만 감소). 100% 커버리지 |
| 코드 | `src/core/v71/position/v71_position_manager.py` | 시그니처 → 본문. `PositionStore` Protocol 구현 (`add_position` async). `apply_buy` (신규/PYRAMID/MANUAL_PYRAMID 이벤트 분기 + avg_price_skill 호출), `apply_sell` (PROFIT_TAKE_5/10에서 stage_after_partial_exit으로 손절선 advance, STOP_LOSS/TS_EXIT는 ladder 유지), `close_position` (idempotent), 쿼리 (`get_by_stock`, `list_open`, `list_for_stock`, `list_events`). `TradeEvent` dataclass + in-memory log. 97.3% 커버리지 |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 `avg_price_skill.py` + `v71_position_manager.py` 추가 |
| 테스트 | `tests/v71/test_avg_price_skill.py` (신규) | 20 PASS. 신규 매수 (2) + 추가 매수 가중평균 + 이벤트 리셋 + ladder fallback + ts_base 보존 (5) + 매도 (6) + PRD §6.3 canonical 시나리오 (1) + compute_weighted_average pure helper (6) |
| 테스트 | `tests/v71/test_v71_position_manager.py` (신규) | 21 PASS. add_position (3) + apply_buy 분기 + 이벤트 로그 + 잘못된 event_type (5) + apply_sell 분기 (PROFIT_5/10/STOP_LOSS/TS_EXIT 별 ladder + status 전이) (6) + close_position (2) + 쿼리 (4) + Feature Flag (1) |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
306 passed in ~1s
  - test_feature_flags                24
  - test_v71_constants                29
  - test_box_state_machine            49
  - test_box_entry_skill              35
  - test_box_manager                  38
  - test_v71_buy_executor             18
  - test_v71_box_entry_detector        8
  - test_v71_box_strategies            5
  - test_exit_calc_skill              36
  - test_v71_trailing_stop             5
  - test_v71_exit_calculator           6
  - test_v71_exit_executor            12
  - test_avg_price_skill              20  (P3.4 신규)
  - test_v71_position_manager         21  (P3.4 신규)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - skills/avg_price_skill.py             100.0%
  - position/v71_position_manager.py       97.3%
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| 첫 매수: avg = buy_price, initial_avg = buy_price | §6.2 | `test_first_buy_sets_initial_and_avg` |
| 추가 매수: 가중평균 (qty*avg + new_qty*new_price)/total | §6.2 | `test_pyramid_buy_recomputes_weighted_avg`, PRD §6.3 example |
| **추가 매수 시 이벤트 리셋** (profit_5/10 → False) | §6.2 ★ | `test_pyramid_resets_event_flags`, `test_pyramid_buy_recomputes_average_and_resets_events` |
| 추가 매수 시 손절선 stage 1로 복귀 (-5%) | §6.2 | `test_pyramid_falls_back_to_stage_1_stop` |
| 추가 매수 시 ts_base_price 보존 (최고가 이력) | §6.2 | `test_pyramid_preserves_ts_base` |
| 추가 매수 시 initial_avg_price 보존 | §6.2 | `test_pyramid_preserves_initial_avg` |
| 매도 시 weighted_avg_price 변경 없음 | §6.4 | `test_sell_keeps_avg_unchanged` |
| 매도 시 이벤트 플래그 유지 (profit_5_executed True 유지) | §6.4 | `test_sell_preserves_event_flags` |
| PROFIT_TAKE_5 → profit_5_executed=True + 손절선 stage 2 (-2%) | §5.4 + §6 | `test_profit_5_advances_stop_and_sets_flag` |
| PROFIT_TAKE_10 → profit_10_executed=True + 손절선 stage 3 (+4%) | §5.4 + §6 | `test_profit_10_advances_to_stage_3` |
| STOP_LOSS / TS_EXIT는 ladder 유지 | §5.9 | `test_stop_loss_does_not_advance_ladder`, `test_ts_exit_does_not_advance_ladder` |
| OPEN → PARTIAL_CLOSED → CLOSED 상태 전이 | §5.9 | `test_partial_to_open_status_progression` |
| 전량 매도 시 closed_at 기록 | §5.9 | `test_stop_loss_does_not_advance_ladder` (assert closed_at != None) |
| event_type 화이트리스트 (BUY_EVENT_TYPES vs SELL_EVENT_TYPES) | §6.6 (스킬 사용 강제) | `test_apply_buy_rejects_unknown_event_type`, `test_apply_sell_rejects_unknown_event_type` |
| 같은 (stock, path) active 1개 보장 (CLOSED는 EXCLUDE) | §3.13 + §2.1 (DB 제약) | `test_get_by_stock_returns_active_only`, `test_get_by_stock_skips_closed` |

**PRD §6.3 canonical scenario 검증**

`test_full_scenario` (avg_price_skill 테스트):

```
Step 1: 첫 매수 100 @ 180_000        → avg=180_000, initial=180_000
Step 2: +5% 청산 30주 매도            → 70주, avg=180_000 유지, profit_5_executed=True
Step 3: 2차 박스 매수 100 @ 175_000  → 170주, avg=177_059
                                        profit_5_executed=False (RESET) ★
                                        fixed_stop=avg*0.95 (stage 1 fallback)
                                        initial_avg=180_000 (preserved)
```

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자 매수/매도 모두 동일 avg_price_skill 통과. PYRAMID_BUY (시스템) vs MANUAL_PYRAMID_BUY (수동) 이벤트만 구분 |
| 2. NFR1 최우선 | ✅ 모든 함수 동기 (in-memory). DB 호출 0. P3.4의 in-memory store는 NFR1을 깨뜨리지 않음 |
| 3. 충돌 금지 ★ | ✅ `V71PositionManager`, `PositionState`, `PositionUpdate`, `TradeEvent` 모두 v71/ 격리. avg_price_skill의 자체 PositionState 제거 후 P3.3 것 재사용 (헌법 5 단순함도) |
| 4. 시스템 계속 운영 | ✅ `PositionNotFoundError`, `InvalidEventTypeError` typed exceptions. 잘못된 호출은 예외만 발생, 정지 코드 0 |
| 5. 단순함 | ✅ avg_price_skill 3개 pure 함수. V71PositionManager는 in-memory dict + apply 메소드. event 화이트리스트로 caller 실수 차단 |

**P3.5 핸드오프 항목**

- `V71BuyExecutor` / `V71ExitExecutor`의 PositionState 직접 mutation을 `V71PositionManager.apply_buy/apply_sell`로 점진 이관 (P3.5 수동 거래 처리에서 Reconciler가 PositionManager API 통해서 통일 호출)
- `Scenario A` (시스템 + 사용자 추가 매수): Reconciler가 키움 잔고 비교 후 차이 감지 → `apply_buy(event_type="MANUAL_PYRAMID_BUY")` 호출
- `Scenario B` (시스템 + 사용자 부분 매도): Reconciler가 차이 감지 → `apply_sell(event_type="MANUAL_SELL")` 호출
- `Scenario C` (추적 중 + 사용자 매수): Reconciler가 박스 INVALIDATED + MANUAL 포지션 신규 생성 (`add_position(path_type="MANUAL")`)
- `Scenario D` (미추적 + 사용자 매수): MANUAL 포지션 신규 (tracked_stock 없음)
- 이중 경로 비례 차감 (큰 경로 우선 반올림): P3.5에서 결정
- DB hydration: P3.4의 in-memory dict + TradeEvent list를 Supabase `positions` + `trade_events` 테이블로 wiring (P3.5 또는 후속 통합 단계)

---

*최종 업데이트: 2026-04-26 (P3.4 완료)*

---

### P3.5: 수동 거래 처리 -- V71Reconciler + 5 Case Dispatcher (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §7 (Scenarios A/B/C/D), 07_SKILLS_SPEC.md §7

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/skills/reconciliation_skill.py` | 시그니처 → 본문. Pure 분류 + 헬퍼: `classify_case` (broker_qty, system_qty, has_active_tracking → A/B/C/D/E), `compute_proportional_split` (이중 경로 비례 차감, 큰 경로 우선 반올림). PRD `reconcile_positions`은 V71Reconciler.reconcile로 이관 (skill은 stateless). 97.3% 커버리지 |
| 코드 | `src/core/v71/position/v71_reconciler.py` | 시그니처 → 본문. `ReconcilerContext` (V71PositionManager + V71BoxManager + Notifier + Clock + tracked store callbacks). `reconcile()` 메인 + 5 case handlers (A/B/C/D/E). MANUAL 우선 차감 + 이중 경로 비례 차감 + 큰 경로 attribution. `TrackedInfo` dataclass. 95.8% 커버리지 |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 P3.5 모듈 2개 추가 |
| 테스트 | `tests/v71/test_reconciliation_skill.py` (신규) | 23 PASS. classify_case 5 케이스 (5) + 음수/엣지 (2) + compute_proportional_split (10: 0/단일경로/PRD 예제/큰경로/타이/sum-property/엣지) + SystemPosition 집계 (4) + KiwoomBalance smoke (1) |
| 테스트 | `tests/v71/test_v71_reconciler.py` (신규) | 12 PASS. 5 케이스 통합 시나리오 (E full match, A 단일/이중/타이, B 단일/MANUAL drained/비례/full-sell, C 추적종료+박스 invalidate+MANUAL 신규, D 미추적 MANUAL 신규) + multi-stock walk + flag gate |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
341 passed in ~1s
  - test_feature_flags                24
  - test_v71_constants                29
  - test_box_state_machine            49
  - test_box_entry_skill              35
  - test_box_manager                  38
  - test_v71_buy_executor             18
  - test_v71_box_entry_detector        8
  - test_v71_box_strategies            5
  - test_exit_calc_skill              36
  - test_v71_trailing_stop             5
  - test_v71_exit_calculator           6
  - test_v71_exit_executor            12
  - test_avg_price_skill              20
  - test_v71_position_manager         21
  - test_reconciliation_skill         23  (P3.5 신규)
  - test_v71_reconciler               12  (P3.5 신규)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - skills/reconciliation_skill.py   97.3%
  - position/v71_reconciler.py       95.8%
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| Case A: 시스템 + 사용자 추가 매수 → MANUAL_PYRAMID_BUY (이벤트 리셋 포함) | §7.2 | `test_single_path_a_apply_buy_with_event_reset` (profit_5_executed=True → False, weighted avg 재계산) |
| Case A 단일 경로: 그 경로에 합산 | §7.2 경우 1 | `test_single_path_a_apply_buy_with_event_reset` |
| Case A 이중 경로: 큰 경로 우선 attribution | §7.2 (디폴트) | `test_dual_path_attributes_to_larger` |
| Case A 이중 경로 타이: PATH_A 우선 | §7.2 (구현 결정) | `test_dual_path_tie_attributes_to_path_a` |
| Case B: MANUAL 먼저 차감 | §7.3 경우 2 | `test_manual_drained_first` |
| Case B 이중 경로: 비례 차감 (큰 경로 우선 반올림) | §7.3 경우 3 | `test_dual_path_proportional_split` + `test_prd_example_larger_first_rounding` |
| Case B 매도 시 평단가 유지 | §6.4 | `test_single_path_a_qty_decreases` |
| Case B full sell → CLOSED | §5.9 | `test_full_sell_closes_positions` |
| Case C: end_tracking + 박스 INVALIDATED + MANUAL 포지션 신규 | §7.4 | `test_ends_tracking_invalidates_boxes_creates_manual` |
| Case D: MANUAL 포지션만 신규 (tracked 없음) | §7.5 | `test_creates_manual_position_only` |
| Case E: no-op + 알림 없음 | §7.1 | `test_full_match_no_op` |
| classify_case truth table | §7 | 5 케이스 매트릭스 |
| compute_proportional_split sum invariant: a+b == sell_quantity | §7.3 | `test_sum_equals_sell_quantity_property` |
| 알림 발송 (E 제외 모두 HIGH) | §7.6 | 케이스별 alert assertion |

**§7.3 PRD canonical 예제 (`test_prd_example_larger_first_rounding`)**

```
보유: PATH_A 100주, PATH_B 50주
매도: 10주
비례: 6.67 / 3.33
반올림: 큰 경로 우선 → PATH_A 7주, PATH_B 3주 (합 10)
```

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자 수동 거래를 룰대로 시스템에 동기화. SYSTEM/MANUAL 분리로 사용자 거래는 시스템 자동 청산 안 함 (§7.6) |
| 2. NFR1 최우선 | ✅ classify_case + compute_proportional_split 모두 sync pure. V71Reconciler reconcile()도 in-memory 호출 (DB hop 0) |
| 3. 충돌 금지 ★ | ✅ V71Reconciler, ReconcilerContext, TrackedInfo 모두 v71/ 격리. V7.0 → V7.1 import 0. avg_price_skill / V71PositionManager 재사용 |
| 4. 시스템 계속 운영 | ✅ Case 실패 시 typed exception (ValueError) + per-stock isolation (한 stock 처리 실패가 다른 stock 차단 안 함). 자동 정지 코드 0 |
| 5. 단순함 | ✅ skill은 2개 pure 함수. V71Reconciler는 5개 handler 메소드. tracked store는 callback 기반 (별도 manager 안 만듦) |

**P3.6 핸드오프 항목**

- `V71ViMonitor`: WebSocket type=1h 구독, NORMAL → VI_TRIGGERED → VI_RESUMED → NORMAL 상태 머신. `is_vi_active(stock_code)` 콜백 (V71BuyExecutor.context.is_vi_active로 wires)
- VI 해제 후 갭 측정 (3% 한도)
- `vi_recovered_today` 플래그: 익일 09:00 리셋
- vi_skill 본문 구현
- VI 포함 봉 처리는 V7.1에서 그대로 판정 (별도 처리 없음, §10.7)
- V71Reconciler.reconcile()은 P3.7 RestartRecovery에서 Step 3로 호출됨

---

*최종 업데이트: 2026-04-26 (P3.5 완료)*

---

### P3.6: VI 처리 -- V71ViMonitor + vi_skill (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §10 (VI handling), 07_SKILLS_SPEC.md §5

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/skills/vi_skill.py` | 시그니처 → 본문. Pure 함수 3개: `transition_vi_state` (4 events: VI_DETECTED/RESOLVED/RESETTLED/DAILY_RESET, NORMAL→TRIGGERED→RESUMED→NORMAL), `check_post_vi_gap` (절대값 3% 한도, gap-up/down 모두), `handle_vi_state` (state machine + decision). 100% 커버리지 |
| 코드 | `src/core/v71/vi_monitor.py` | 시그니처 → 본문. `V71ViMonitor` (per-stock state dict + recovered_today set). `on_vi_triggered`/`on_vi_resolved` (idempotent). `is_vi_active`/`is_vi_recovered_today` 쿼리 (BuyExecutorContext와 MarketContext.is_vi_recovered_today wires). `_auto_resettle` (RESUMED→NORMAL + recovered_today 플래그). `reset_daily` (09:00 일괄 리셋). `make_sync_dispatcher` (V7.0 WebSocket 브리지). 94.5% 커버리지 |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 P3.6 모듈 2개 추가 |
| 테스트 | `tests/v71/test_vi_skill.py` (신규) | 25 PASS. transition 합법/불법 매트릭스 + DAILY_RESET 모든 상태 + 갭 검증 (under/at/over/down/invalid) + handle (4 events) + public surface |
| 테스트 | `tests/v71/test_v71_vi_monitor.py` (신규) | 14 PASS. 상태 쿼리 + trigger 알림 + idempotent + full cycle (recovered_today set) + on_vi_resumed callback + callback exception isolation + drop unmatched + reset_daily + sync dispatcher + flag gate |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
380 passed in ~1s
  - test_feature_flags                24
  - test_v71_constants                29
  - test_box_state_machine            49
  - test_box_entry_skill              35
  - test_box_manager                  38
  - test_v71_buy_executor             18
  - test_v71_box_entry_detector        8
  - test_v71_box_strategies            5
  - test_exit_calc_skill              36
  - test_v71_trailing_stop             5
  - test_v71_exit_calculator           6
  - test_v71_exit_executor            12
  - test_avg_price_skill              20
  - test_v71_position_manager         21
  - test_reconciliation_skill         23
  - test_v71_reconciler               12
  - test_vi_skill                     25  (P3.6 신규)
  - test_v71_vi_monitor               14  (P3.6 신규)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - skills/vi_skill.py     100.0%
  - vi_monitor.py           94.5%
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| 상태 머신: NORMAL → TRIGGERED → RESUMED → NORMAL | §10.3 | `test_normal_to_triggered`, `test_triggered_to_resumed`, `test_resumed_to_normal_on_resettle` |
| 불법 전이는 ValueError | §10.3 | `test_illegal_raises` (6 케이스) |
| DAILY_RESET 모든 상태 → NORMAL | §10.6 (익일 09:00) | `test_daily_reset_returns_normal_from_any_state` (3 케이스) |
| 갭 3% 한도 (절대값 양/음 모두 abort) | §10.4 Step 3 | `test_gap_at_3pct_aborts`, `test_gap_down_3pct_also_aborts` |
| RESETTLED만 block_new_entries_today=True | §10.6 | `test_resettled_sets_block_flag` |
| DAILY_RESET은 block flag 안 set | §10.6 | `test_daily_reset_does_not_set_block_flag` |
| VI 발동 시 손절/익절 일시 정지 (`is_vi_active`) | §10.5 | `test_state_after_trigger` (BuyExecutorContext.is_vi_active wires) |
| VI 발동 idempotent (중복 알림 차단) | §10.2 | `test_idempotent_when_already_triggered` |
| Full cycle 후 `vi_recovered_today=True` (당일 신규 진입 금지) | §10.6 | `test_full_cycle_sets_recovered_today` |
| `on_vi_resumed` callback (즉시 재평가, NFR1 < 1초) | §10.5 | `test_resume_fires_on_vi_resumed_callback` |
| Callback exception은 auto_resettle 차단 안 함 | 헌법 4 | `test_callback_exception_does_not_block_auto_resettle` |
| Resolved without trigger는 무시 | §10.2 (defensive) | `test_resume_without_prior_trigger_is_dropped` |
| `reset_daily` 모든 플래그 리셋 | §10.6 (익일 09:00) | `test_reset_clears_recovered_today` |
| Sync dispatcher (V7.0 WebSocket 브리지) | §10.2 | `test_dispatcher_routes_flag_*` |
| No running loop은 swallow (V7.0 pipeline crash 방지) | 헌법 4 | `test_dispatcher_no_running_loop_logs_only` |

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ VI 룰 그대로 (사용자 결정 §10.7 봉 그대로 판정 + §10.6 당일 진입 금지). 09:05 fallback에서만 vi_recovered_today 무시 (§10.9 PRD patch #1) |
| 2. NFR1 최우선 | ✅ vi_skill pure 동기. on_vi_resumed callback이 즉시 재평가 트리거 (NFR1 < 1초 보장 wiring) |
| 3. 충돌 금지 ★ | ✅ V71ViMonitor + ViMonitorContext + OnViResumedFn 모두 v71/ 격리. Notifier/Clock는 P3.2 BuyExecutor와 동일 Protocol 재사용 |
| 4. 시스템 계속 운영 | ✅ idempotent handlers (중복 이벤트 무시) + callback exception isolation + sync dispatcher가 loop 없을 때 swallow. 자동 정지 코드 0 |
| 5. 단순함 | ✅ skill 3개 pure 함수. monitor는 dict 기반 in-memory + 명확한 lifecycle (trigger → resolve → auto_resettle → reset_daily) |

**P3.7 핸드오프 항목**

- `V71RestartRecovery`: 7-Step 복구 시퀀스 (§13)
  - Step 0: 안전 모드 진입 (신규 매수/박스 등록 차단)
  - Step 1: 외부 시스템 연결 (DB, Kiwoom OAuth, WebSocket, Telegram)
  - Step 2: 미완료 주문 모두 취소
  - Step 3: V71Reconciler.reconcile() 호출 (포지션 정합성)
  - Step 4: 시세 재구독
  - Step 5: 박스 진입 조건 재평가 (지나간 트리거 무효, 옵션 A)
  - Step 6: 안전 모드 해제
  - Step 7: 복구 보고서 (텔레그램 CRITICAL)
- `V71ViMonitor.reset_daily()` 09:00 호출 wiring (RestartRecovery 또는 별도 스케줄러)
- 재시작 빈도 모니터링 (1시간 5회+ 시 CRITICAL)
- 안전 모드 동안 BuyExecutor 차단 wiring

---

*최종 업데이트: 2026-04-26 (P3.6 완료)*

---

### P3.7: 시스템 재시작 복구 -- V71RestartRecovery (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §13 (recovery sequence + frequency monitor)

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/v71_constants.py` | `RECOVERY_RECONNECT_MAX_RETRIES = 5`, `RECOVERY_RECONNECT_RETRY_INTERVAL_SECONDS = 1.0` 추가 + PIN 테스트 |
| 코드 | `src/core/v71/restart_recovery.py` | 시그니처 → 본문. `RecoveryContext` (V71Reconciler + Notifier + Clock + 4 reconnect callbacks + 3 데이터 callbacks + 2 토글). `RecoveryReport` (started_at/completed_at/cancelled_orders/reconciliation_results/resubscribed_count/failures). `run()` 7-step + `_with_retry` (5회 재시도, 1초 간격). `_record_restart` + `_check_restart_frequency` (1/2/3/5+ 단계별 알림, 자동 정지 0). 92.7% 커버리지 |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 `restart_recovery.py` 추가 |
| 테스트 | `tests/v71/test_v71_constants.py` | fallback 상수 PIN 테스트 +2 (총 31 PASS) |
| 테스트 | `tests/v71/test_v71_restart_recovery.py` (신규) | 16 PASS. 7-step 통합 (2) + Step 1 재시도 (3: 3회째 성공 / 5회 모두 실패 / 다른 step 영향 없음) + Step 2/3/4 실패 (3) + reconciliation 실 호출 (1) + 빈도 모니터 (5: 1회 무알림 / 2회 HIGH / 3회 CRITICAL / 5+ tier / 윈도우 외 무카운트) + Constitution-4 (1: 모든 callback 실패에도 run 완료) + flag gate (1) |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
398 passed in ~1s
  - test_feature_flags                24
  - test_v71_constants                31  (P3.7 +2)
  - test_box_state_machine            49
  - test_box_entry_skill              35
  - test_box_manager                  38
  - test_v71_buy_executor             18
  - test_v71_box_entry_detector        8
  - test_v71_box_strategies            5
  - test_exit_calc_skill              36
  - test_v71_trailing_stop             5
  - test_v71_exit_calculator           6
  - test_v71_exit_executor            12
  - test_avg_price_skill              20
  - test_v71_position_manager         21
  - test_reconciliation_skill         23
  - test_v71_reconciler               12
  - test_vi_skill                     25
  - test_v71_vi_monitor               14
  - test_v71_restart_recovery         16  (P3.7 신규)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - restart_recovery.py    92.7%
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| 7-step 시퀀스 (0~7) 항상 완주 | §13.1 | `test_full_recovery_success` (failures==[]), `test_run_always_returns_report_even_on_total_meltdown` |
| Step 0: 안전 모드 진입 | §13.1 | `test_full_recovery_success` (safe_mode entered=1) |
| Step 1: DB→Kiwoom→WS→Telegram 순서 + 5회 재시도 + 1초 간격 | §13.1 | `test_db_succeeds_on_third_attempt` (3 attempts + sleeps) |
| Step 1 5회 모두 실패 → failures 기록 + 시퀀스 계속 | §13.1 + 헌법 4 | `test_db_persistent_failure_records_but_continues` |
| Step 1 한 connection 실패가 다른 connections 차단 안 함 | 헌법 4 | `test_websocket_failure_does_not_block_others` |
| Step 2: 미완료 주문 모두 취소 (박스 보존) | §13.1 Step 2 | `test_report_records_counts` (cancelled_orders=3) |
| Step 3: V71Reconciler.reconcile 호출 | §13.1 Step 3 | `test_reconcile_called_with_balances` (Case A 결과) |
| Step 4: 시세 재구독 | §13.1 Step 4 | `test_report_records_counts` (resubscribed_count=12) |
| Step 5: 옵션 A (지나간 트리거 무효, no-op) | §13.1 Step 5 | implicit (시퀀스에 추가 처리 없음) |
| Step 6: 안전 모드 해제 | §13.1 Step 6 | `test_full_recovery_success` (safe_mode exited=1), 모든 failure 케이스에서도 |
| Step 7: CRITICAL 복구 보고서 | §13.1 Step 7 | `test_full_recovery_success` (RECOVERY_COMPLETED + CRITICAL) |
| 빈도 1회: 알림 없음 | §13.2 | `test_first_restart_no_alert` |
| 빈도 2회 (1시간): HIGH | §13.2 | `test_two_restarts_within_hour_emits_high` |
| 빈도 3회 (1시간): CRITICAL | §13.2 | `test_three_restarts_within_hour_emits_critical` |
| 빈도 5+ (1시간): CRITICAL + 5 tier | §13.2 | `test_five_plus_restarts_critical_with_5plus_tier` |
| 1시간 윈도우 외 재시작 무카운트 | §13.2 | `test_restart_outside_window_does_not_count` |
| **자동 정지 0 (헌법 4)** -- 모든 callback 실패에도 run 완료 | 헌법 4 | `test_run_always_returns_report_even_on_total_meltdown` |

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 박스/포지션/추적 데이터는 손대지 않음 (DB 보존). Step 5 "지나간 트리거 무효"는 사용자 손실 회피 |
| 2. NFR1 최우선 | ✅ 7-step 순차 실행 + Step 5는 no-op (재평가 skip). 평균 실행 < 30초~2분 |
| 3. 충돌 금지 ★ | ✅ V71RestartRecovery + RecoveryContext + RecoveryReport 모두 v71/ 격리. V71Reconciler / Notifier / Clock 재사용 |
| 4. 시스템 계속 운영 ★ | ✅ **explicit no-auto-stop**. 모든 callback 실패에도 run() 완료 + safe_mode 해제 + CRITICAL 보고서. 빈도 모니터링도 알림만 (정지 X) |
| 5. 단순함 | ✅ 7개 step 메소드 + 1 retry helper. in-memory 재시작 로그. Step 5는 no-op (옵션 A) |

---

## Phase 3 완료 (마일스톤 M3 달성, 2026-04-26)

```
$ pytest tests/v71/ --no-cov -q
398 passed in ~1s

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
```

### Phase 3 누적 산출물 (P3.1 ~ P3.7)

| Phase | 모듈 (코드) | 모듈 (테스트) | 커버리지 |
|-------|-------------|---------------|---------|
| P3.1 | box/box_state_machine, box/box_manager, skills/box_entry_skill | 3 | 94~100% |
| P3.2 | strategies/v71_buy_executor, strategies/v71_box_pullback/breakout, box/box_entry_detector + skills/kiwoom_api_skill 확장 | 3 | 92~100% |
| P3.3 | exit/exit_calculator, exit/exit_executor, exit/trailing_stop, position/state, skills/exit_calc_skill | 4 | 92~100% |
| P3.4 | skills/avg_price_skill, position/v71_position_manager | 2 | 97~100% |
| P3.5 | skills/reconciliation_skill, position/v71_reconciler | 2 | 95~97% |
| P3.6 | skills/vi_skill, vi_monitor | 2 | 94~100% |
| P3.7 | restart_recovery + V71Constants 확장 | 1 | 92.7% |

**합계**: 21개 V7.1 모듈 + 21개 신규 테스트 파일, 모두 90%+ 커버리지

### V7.1 거래 룰 구현 완료 매트릭스

| §/룰 | P3.x | 모듈 |
|------|------|------|
| §3 박스 시스템 | P3.1 | box_state_machine, box_manager, box_entry_skill |
| §3.10/§3.11 PATH_B 09:05 fallback (사용자 patch #1) | P3.2 | v71_buy_executor |
| §4 매수 실행 (limit×3 + market) | P3.2 | v71_buy_executor |
| §5.1 손절 (시장가 전량) | P3.3 | exit_executor |
| §5.2/§5.3 분할 익절 (+5/+10 30%) | P3.3 | exit_executor + exit_calc_skill |
| §5.4 손절선 단방향 상향 (-5/-2/+4) | P3.3 | exit_calc_skill.stage_after_partial_exit |
| §5.5 TS (BasePrice + ATR 단방향 4.0/3.0/2.5/2.0) | P3.3 | trailing_stop + exit_calc_skill |
| §5.6 유효 청산선 max(고정, TS) | P3.3 | exit_calc_skill.calculate_effective_stop |
| §5.7 Trend Hold Filter 폐기 | P3.3 | (implicit -- exit_calculator는 trigger 즉시 청산) |
| §5.8 Max Holding 무제한 | P3.3 | (implicit -- 강제 청산 코드 없음) |
| §6.2 추가 매수 시 가중평균 + 이벤트 리셋 | P3.4 | avg_price_skill + v71_position_manager |
| §6.4 매도 시 평단가 유지 | P3.4 | avg_price_skill |
| §7 수동 거래 5 시나리오 (A/B/C/D/E) | P3.5 | reconciliation_skill + v71_reconciler |
| §10 VI 처리 + vi_recovered_today | P3.6 | vi_skill + vi_monitor |
| §10.9 시초 VI 안전장치 (PATH_B 09:05) | P3.2 | v71_buy_executor (fallback meta from box_entry_skill) |
| §13.1 7-step 재시작 복구 | P3.7 | restart_recovery |
| §13.2 빈도 모니터 (자동 정지 X) | P3.7 | restart_recovery |

### Phase 3 헌법 5원칙 자체 검증 (전체)

| 원칙 | 검증 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 박스 결정 그대로 실행. 09:05 fallback도 결정된 진입의 마무리 (§10.9). MANUAL/SYSTEM 분리 (§7.6) |
| 2. NFR1 최우선 | ✅ 핵심 경로 모두 sync (PATH_A 매수, exit calculation, VI 판정). DB hop 0. PATH_B 09:01/09:05 + 매수 시퀀스 sleep만 의도적 |
| 3. 충돌 금지 ★ | ✅ 21개 신규 모듈 모두 v71/ 격리 + V71 접두사. V7.0 → V7.1 import 0. Harness 1/2/6 PASS |
| 4. 시스템 계속 운영 | ✅ typed exceptions로 surface, 자동 정지 코드 0. 콜백 실패 isolation. 재시작 복구도 모든 step 실패에도 완료 |
| 5. 단순함 | ✅ pure skill 함수 다수, in-memory store, callback DI, 명확한 lifecycle. 헬퍼 클래스 거대화 없음 |

### 다음 단계

| Phase | 내용 | 예상 |
|-------|------|------|
| **Phase 4** | 알림 시스템 (V71NotificationService 구현 -- 현재 Notifier Protocol만) | 2~3일 |
| **Phase 5** | 웹 대시보드 (FastAPI + JWT + 2FA + React UI) | 5~10일 |
| **Phase 6** | 리포트 (Claude Opus 4.7 통합) | 3~5일 |
| **Phase 7** | 통합 테스트 + 페이퍼 트레이드 + AWS 배포 | 5~10일 |

V7.0 인프라 통합도 별도 트랙으로 진행 (kiwoom_api_skill 본문 + ExchangeAdapter 실 구현).

---

*최종 업데이트: 2026-04-26 (P3.7 + Phase 3 100% 완료)*

---

## Phase 4 진입 직전 핸드오프 (2026-04-26 세션 종료 시점)

이 섹션은 **새 세션이 Phase 4를 이어서 받기 위해 반드시 알아야 할 것들**을 정리합니다.

### 현재 상태 스냅샷

| 항목 | 값 |
|------|-----|
| 브랜치 | `v71-development` |
| 최신 commit | `68d65e5` (P3.7 + Phase 3 complete) |
| 최신 tag | `v71-phase3-complete` (M3 마일스톤) |
| GitHub | https://github.com/ParkKyunHo/KstockSysytem |
| pytest (tests/v71/) | **398 PASS** in ~1s |
| 하네스 | 7/7 PASS |
| Phase 3 모듈 수 | 21 코드 + 21 테스트, 모두 90%+ 커버리지 |
| PRD 변경 이력 | patch #1 적용 (PATH_B 09:01→09:05 fallback, §10.9) |

### 누적 tag 목록

```
v7.0-final-stable             V7.0 백업
v71-phase0-complete           Phase 0 (사전 준비)
v71-phase1-complete           Phase 1 (인프라 정리)
v71-phase2-complete           Phase 2 (V7.1 골격)
v71-prd-patch-1               사용자 patch #1 (PATH_B 09:05 안전장치)
v71-p31-complete .. v71-p37-complete   Phase 3 sub-task별
v71-phase3-complete           ★ M3 마일스톤
```

### Phase 3 완료 요약 (한눈에)

| 룰 (PRD §) | 구현 모듈 | 커버리지 |
|-----------|-----------|----------|
| §3 박스 시스템 + §10.9 09:05 fallback meta | box/* + skills/box_entry_skill | 94~100% |
| §4 매수 실행 + 09:05 fallback executor | strategies/v71_buy_executor | 92.5% |
| §5 매수 후 관리 (손절/익절/TS) | exit/* + skills/exit_calc_skill | 92~100% |
| §6 평단가 + 이벤트 리셋 | skills/avg_price_skill + position/v71_position_manager | 97~100% |
| §7 수동 거래 5 시나리오 | skills/reconciliation_skill + position/v71_reconciler | 95~97% |
| §10 VI 처리 | skills/vi_skill + vi_monitor | 94~100% |
| §13 7-step 재시작 복구 | restart_recovery | 92.7% |

### 사용자 정책 (반드시 준수, Phase 0~3 동안 변경 없음)

1. **V7.0 = 레거시** (곧 폐기), **V7.1 = 완전 구축**. 헌법 3 "충돌 금지"는 *운영 영향* 0이라는 의미
2. **Python 호출**: 항상 `"C:\Program Files\Python311\python.exe"` 명시
3. **`.env` 직접 read 금지**: 시스템 권한 정책으로 차단됨
4. **Push 자동 권한**: 사용자가 권한 위임. 매 commit마다 push OK
5. **Task 단위 진행**: 매 Task별 commit 분리. PRD 단일 진실
6. **statusline**: 1라인 (모델 / effort / ctx 사용량 / 5h / 7d). 변경 금지

### Phase 4 시작 가이드

**참조 문서 우선순위**:
1. `02_TRADING_RULES.md §9` (알림 시스템 -- CRITICAL/HIGH/MEDIUM/LOW 등급, 빈도 제한, 채널)
2. `05_MIGRATION_PLAN.md §6` (Phase 4 작업 분해)
3. `07_SKILLS_SPEC.md §6` (notification_skill 시그니처)
4. `12_SECURITY.md` (텔레그램 권한 검증)

**Phase 4 sub-tasks** (05 §6 기준):

| Task | 산출물 | 의존성 |
|------|--------|--------|
| **P4.1** 알림 등급 시스템 | `src/notification/severity.py`, `notification_skill.py` 본문, 우선순위 큐 (PostgreSQL FOR UPDATE SKIP LOCKED), 빈도 제한 (5분), Circuit Breaker | V71PositionManager, V71BoxManager 보유 데이터 사용 |
| **P4.2** 텔레그램 명령어 13개 | `src/notification/telegram_commands.py` (status/positions/tracking/pending/today/recent/report/stop/resume/cancel/alerts/settings/help). authorized_chat_ids 검증 | python-telegram-bot |
| **P4.3** 일일 마감 알림 | `src/notification/daily_summary.py` -- 매일 15:30 자동 발송 | AsyncIOScheduler |
| **P4.4** 월 1회 리뷰 | `src/notification/monthly_review.py` -- 매월 1일 09:00, ABC 구조, 60일+ 정체 강조 | monthly_reviews 테이블 |

**Phase 4 핵심 의존성**:
- 현재 P3.2~P3.7에서 정의된 `Notifier` Protocol (in `src/core/v71/strategies/v71_buy_executor.py`)을 V71NotificationService가 구현
- `notification_skill` (P2.3에서 시그니처만, 본문 미구현)이 V71NotificationService의 entry point
- 모든 알림은 `notification_skill.send_notification()`을 통해서만 (Harness 3 강제)

**Phase 4 완료 기준**:
- P4.1~P4.4 모두 ✓
- pytest tests/v71/ + tests/notification/ PASS, 90%+ 커버리지
- 7/7 하네스 PASS
- WORK_LOG.md 갱신
- Git tag: `v71-phase4-complete`

### 새 세션 첫 메시지 (사용자가 그대로 붙여넣기)

```
# V7.1 Phase 4 작업 시작 (알림 시스템)

## 환경
- 프로젝트: C:\K_stock_trading\
- 브랜치: v71-development
- 최신 tag: v71-phase3-complete
- GitHub: https://github.com/ParkKyunHo/KstockSysytem

## 사전 학습 (필수, 순서대로)
1. C:\K_stock_trading\CLAUDE.md
2. C:\K_stock_trading\docs\v71\WORK_LOG.md  ← Phase 0~3 누적 + Phase 4 가이드
3. C:\K_stock_trading\docs\v71\01_PRD_MAIN.md  (전체 그림)
4. C:\K_stock_trading\docs\v71\02_TRADING_RULES.md §9 (알림 시스템 룰)
5. C:\K_stock_trading\docs\v71\05_MIGRATION_PLAN.md §6 (Phase 4 계획)
6. C:\K_stock_trading\docs\v71\07_SKILLS_SPEC.md §6 (notification_skill 시그니처)
7. C:\K_stock_trading\docs\v71\12_SECURITY.md (텔레그램 권한)

## 헌법 5원칙 (절대 위반 금지)
1. 사용자 판단 불가침
2. NFR1 최우선
3. 충돌 금지 ★ (V7.0 인프라 보존, V7.1은 src/core/v71/ 격리)
4. 시스템 계속 운영
5. 단순함 우선

## 응답 요청
위 7개 문서 정독 후:
1. Phase 0~3 누적 산출물 요약 (WORK_LOG 기준)
2. Phase 4 P4.1 (알림 등급 시스템) 작업 계획
3. 시작 준비 상태

응답 후 P4.1 시작 지시 대기.
```

### 권고 사항 (사용자 확인 필요)

- DB 비밀번호 회전 (Phase 0 보안 사고 #1, #2 -- 사용자가 "큰 문제 없을듯"으로 dismiss했으나 운영 시작 전 한 번은 회전 권장)
- V7.0 인프라 통합 (`kiwoom_api_skill` 본문 + ExchangeAdapter 실 구현)은 별도 트랙으로 진행 가능 -- Phase 4와 병렬 가능

### Phase 3 → Phase 4 핸드오프 항목 (재정리)

이전 phase 종료 시 기록한 핸드오프 항목들이 Phase 4의 작업 범위에 정확히 들어갑니다:
- `Notifier` Protocol 구현체 → P4.1 V71NotificationService
- 빈도 제한 + Circuit Breaker → P4.1
- `notification_skill` 본문 → P4.1
- `make_sync_dispatcher` (V7.0 WebSocket 브리지) → 이미 P3.6에서 작성, Phase 4와 무관

V7.1 거래 룰 코어가 모두 테스트로 핀(pin)되어 있으므로, Phase 4 변경이 Phase 3 룰을 위반할 가능성은 낮음 (테스트 fail로 즉시 surface).

---

## Phase 4: 알림 시스템 (진행 중)

### P4.1: 알림 등급 시스템 -- V71NotificationService + V71NotificationQueue + V71CircuitBreaker (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §9 (4 등급 + 우선순위 큐 + Circuit Breaker + 빈도 제한 + 표준 메시지), 07_SKILLS_SPEC.md §6 (notification_skill), 03_DATA_MODEL.md §3.4 (notifications 테이블), 12_SECURITY.md §3.4 (텔레그램 권한)

**PRD 변경 사항 (patch #2)**

PRD 05_MIGRATION_PLAN.md §6.2은 P4.1 산출물을 `src/notification/severity.py` 등 V7.0 위치에 두는 것으로 명시. 사용자 권고안 + 헌법 3 (격리) 정합을 위해 모든 P4.1 신규 모듈을 `src/core/v71/notification/`으로 이동. PRD §6.2와 13_APPENDIX 변경 이력은 후속 작업으로 갱신 예정 (PRD patch #2).

**위치 결정 매트릭스 (사용자 권고안 4건 채택)**

| 항목 | 결정 | 이유 |
|------|------|------|
| V7.1 알림 패키지 위치 | `src/core/v71/notification/` (신규) | P3 패턴(`v71/box/`, `v71/exit/`, `v71/position/`) + 헌법 3 격리. PRD patch #2 |
| DB 영속화 시점 | 즉시 PostgreSQL wiring (마이그레이션 014) | §9.3 CRITICAL 큐 영구 보관 + §13.1 재시작 복구 wiring |
| V7.0 TelegramBot 재사용 | 단방향 import (callable로 주입) | parse_mode 가드 자동 상속 + 헌법 5 (단순함) |
| Web dispatcher Phase 4 범위 | P4.1: deferred queue (channel="BOTH" enqueue만), Phase 5: WebSocket push wiring | §9.2 (CRITICAL/HIGH 동시 표시) 정합 |

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/v71_constants.py` | `NOTIFICATION_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3`, `NOTIFICATION_CIRCUIT_BREAKER_TIMEOUT_SECONDS = 30`, `NOTIFICATION_CRITICAL_RETRY_COUNT = 3`, `NOTIFICATION_CRITICAL_RETRY_DELAY_SECONDS = 5`, `NOTIFICATION_MEDIUM_LOW_EXPIRY_MINUTES = 5`, `NOTIFICATION_WORKER_INTERVAL_SECONDS = 0.5` 추가 |
| 코드 | `src/core/v71/notification/__init__.py` (신규) | 패키지 entry + export 8개 |
| 코드 | `src/core/v71/notification/v71_notification_repository.py` (신규) | `NotificationRepository` Protocol + `InMemoryNotificationRepository` (단위 테스트 + bootstrap impl) + `NotificationRecord`/`NotificationStatus` dataclass + `new_notification_id()`. 94.2% 커버리지 |
| 코드 | `src/core/v71/notification/v71_postgres_notification_repository.py` (신규) | `PostgresNotificationRepository` -- thin SQL adapter (Phase 5 통합 테스트로 검증). `# pragma: no cover` 마킹 + Harness 7 THRESHOLDS 제외 |
| 코드 | `src/core/v71/notification/v71_circuit_breaker.py` (신규) | `V71CircuitBreaker` + `V71CircuitState` (CLOSED/OPEN/HALF_OPEN). 3회 실패 → OPEN, 30초 후 → HALF_OPEN, probe 성공 → CLOSED. CircuitState 명칭은 V7.0 `src/api/client.py`와 충돌 → `V71CircuitState`로 prefix (Harness 1). 98.1% 커버리지 |
| 코드 | `src/core/v71/notification/v71_notification_queue.py` (신규) | `V71NotificationQueue` + `EnqueueOutcome` -- Repository 위에 우선순위/만료/빈도 제한 추가. CRITICAL은 빈도 제한 우회. CRITICAL/HIGH는 channel="BOTH" + expires_at=None, MEDIUM/LOW는 channel="TELEGRAM" + 5분 만료. Feature flag: `v71.notification_v71`. 98.5% 커버리지 |
| 코드 | `src/core/v71/notification/v71_notification_service.py` (신규) | `V71NotificationService` -- Notifier Protocol 구현체 (P3 14곳 호출 wires). async worker (`start`/`stop`/`run_once`/`_worker_loop`). `_dispatch_standard` (HIGH/MEDIUM/LOW) + `_dispatch_critical` (5초 x 3회 재시도, 모두 실패 시 PENDING 영구 보관). `_maybe_dispatch_web` (channel="BOTH" 팬아웃, 실패 시 텔레그램 메인 path 영향 없음). 96.7% 커버리지 |
| 코드 | `src/core/v71/skills/notification_skill.py` | 시그니처 → 본문. `Severity`/`EventType` Enum 확장 (CRITICAL/HIGH/MEDIUM/LOW 매핑), `NotificationRequest`/`NotificationResult`, `severity_to_priority` (1~4), `make_rate_limit_key` (`{event}:{stock or '_'}`), 8개 표준 메시지 포맷터 (stop_loss/buy/profit_take/manual_trade/vi_triggered/box_entry_imminent/system_restart/websocket_disconnected -- 02 §9.6), `send_notification` (NotificationRequest → queue.enqueue thin wrapper). 100% 커버리지 |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 P4.1 5개 모듈 추가 (PostgresNotificationRepository는 제외) |
| 검증 | `scripts/harness/feature_flag_enforcer.py` | `EXEMPT_PARTS`에 `v71_circuit_breaker`/`v71_notification_repository`/`v71_postgres_notification_repository` 추가 (V71NotificationQueue + Service가 entry-point 역할이므로 building blocks는 면제) |
| 테스트 | `tests/v71/test_notification_skill.py` (신규) | 24 PASS. severity_to_priority (7) + make_rate_limit_key (4) + 8개 formatter (9) + send_notification 큐 통합 (4) |
| 테스트 | `tests/v71/test_v71_notification_repository.py` (신규) | 19 PASS. insert (2) + fetch_next_pending priority/FIFO/skip-expired/critical-never-expire/skip-non-pending (6) + mark_sent/mark_failed (4) + find_recent_by_rate_limit_key (4) + expire_stale (2) + snapshot (1) |
| 테스트 | `tests/v71/test_v71_circuit_breaker.py` (신규) | 12 PASS. construction (3) + CLOSED→OPEN (3) + OPEN→HALF_OPEN→CLOSED/OPEN (5) + CLOSED+success (1) |
| 테스트 | `tests/v71/test_v71_notification_queue.py` (신규) | 19 PASS. feature flag gate (2) + enqueue shape (5) + rate limit (7) + consumer side (5) |
| 테스트 | `tests/v71/test_v71_notification_service.py` (신규) | 22 PASS. construction (2) + Notifier Protocol surface (3) + run_once standard (4) + CRITICAL retry (4) + Circuit integration (2) + web dispatch (3) + worker lifecycle (3 + 1 fault tolerance) |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
494 passed in ~1.3s
  - 기존 P3 테스트 398 PASS
  - 신규 P4.1 테스트 96 PASS (24 + 19 + 12 + 19 + 22)

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - skills/notification_skill.py                      100.0%
  - notification/v71_notification_repository.py        94.2%
  - notification/v71_circuit_breaker.py                98.1%
  - notification/v71_notification_queue.py             98.5%
  - notification/v71_notification_service.py           96.7%
  - notification/v71_postgres_notification_repository.py  (excluded; integration test)
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| Severity → priority: CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4 | §9.3 | `test_critical_is_one`, `test_strict_ordering` |
| Channel 결정: CRITICAL/HIGH → BOTH, MEDIUM/LOW → TELEGRAM | §9.2 | `test_critical_channel_both_no_expiry`, `test_medium_channel_telegram_with_expiry` |
| Expires_at: CRITICAL/HIGH None, MEDIUM/LOW now+5min | §9.4 | `test_critical_channel_both_no_expiry`, `test_medium_channel_telegram_with_expiry` |
| 우선순위 큐 ORDER BY priority ASC, FIFO within priority | §9.3 | `test_priority_order`, `test_fifo_within_priority`, `test_next_pending_priority_order` |
| CRITICAL/HIGH는 만료 없음 (`expires_at` 무시) | §9.4 | `test_critical_never_expires`, `test_expires_only_medium_low` |
| MEDIUM/LOW만 expire_stale로 EXPIRED 전이 | §9.4 | `test_expires_only_medium_low`, `test_idempotent` |
| 5분 빈도 제한 윈도 (CRITICAL 우회) | §9.5 | `test_high_within_window_suppressed`, `test_window_expiry_lets_through`, `test_critical_bypasses_rate_limit` |
| 빈도 제한 키 분리: 다른 키는 독립 | §9.5 | `test_distinct_keys_independent`, `test_distinct_per_stock` |
| Circuit Breaker 3회 실패 → OPEN | §9.4 | `test_threshold_trips_open` |
| Circuit OPEN 30초 후 → HALF_OPEN | §9.4 | `test_open_to_half_open_after_timeout` |
| HALF_OPEN probe 성공 → CLOSED | §9.4 | `test_half_open_success_returns_to_closed` |
| HALF_OPEN probe 실패 → OPEN (timer 재시작) | §9.4 | `test_half_open_failure_returns_to_open_with_new_timer` |
| Circuit OPEN 시 dispatch 차단 (CRITICAL 포함) | §9.4 | `test_circuit_open_skips_dispatch` |
| CRITICAL 발송 실패 시 5초 후 3회 재시도 | §9.3 | `test_critical_third_attempt_succeeds`, `test_critical_all_retries_fail_stays_pending` |
| CRITICAL 모든 재시도 실패 후 PENDING 영구 보관 | §9.4 | `test_critical_all_retries_fail_stays_pending` (revert_to_pending=True) |
| HIGH 실패는 PENDING 복귀 (재시도) | §9.4 | `test_high_failure_reverts_to_pending` |
| MEDIUM/LOW 실패는 FAILED 종결 (5분 후 폐기) | §9.4 | `test_medium_failure_terminal` |
| Web dispatcher 실패는 텔레그램 메인 path 영향 없음 | §9.2 | `test_web_exception_does_not_block_telegram` |
| Worker는 step 예외 swallow + 계속 polling | 헌법 4 | `test_worker_swallows_step_exceptions` |
| parse_mode 사용 안 함 (plain text) | CLAUDE.md 1.1 | (V7.0 TelegramBot 가드 + V71NotificationService._render_text는 plain string 합성) |

**§9.3 / §9.5 빈도 제한 정밀 검증**

`test_critical_bypasses_rate_limit`: CRITICAL은 같은 (event_type, stock_code) + 같은 rate_limit_key를 5초 내 5번 연속 enqueue해도 5건 모두 accepted (빈도 제한 우회).

`test_high_within_window_suppressed`: HIGH는 1차 enqueue 후 5분 내 같은 키로 다시 enqueue → SUPPRESSED + reason="RATE_LIMIT".

`test_window_expiry_lets_through`: 같은 키라도 6분 후 다시 enqueue → ACCEPTED.

**Notifier Protocol wiring 검증**

P3 14곳에서 `await self._ctx.notifier.notify(severity=..., event_type=..., stock_code=..., message=..., rate_limit_key=...)` 호출 패턴이 V71NotificationService.notify와 정합. P4.1 단위 테스트 `test_notify_enqueues` + `test_notify_with_explicit_key` + `test_notify_silently_swallows_suppression`로 확인.

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자 박스/거래 룰에서 발생한 이벤트를 그대로 알림으로 전환. 자동 추천 0. CRITICAL/HIGH는 우선 보장, MEDIUM/LOW는 빈도 제한으로 노이즈 차단 |
| 2. NFR1 최우선 | ✅ Notifier.notify는 enqueue만 (DB INSERT 1번). 실제 텔레그램 발송은 worker가 비동기. 거래 path latency 영향 < 1ms |
| 3. 충돌 금지 ★ | ✅ V71 접두사 (V71CircuitBreaker, V71CircuitState, V71NotificationQueue, V71NotificationService). V71CircuitState는 V7.0 `src/api/client.py`의 CircuitState와 충돌 회피. v71/notification/ 패키지 격리. V7.0 → V7.1 import 0. Harness 1/2/6 PASS |
| 4. 시스템 계속 운영 | ✅ Circuit OPEN 시에도 큐는 작동 (CRITICAL/HIGH 영구 보관). Worker는 step 예외 swallow + 계속 polling. CRITICAL retry 실패도 PENDING 보존. 자동 정지 코드 0 |
| 5. 단순함 | ✅ Repository Protocol + 2 구현체 (in-memory + Postgres). CB는 1개 FSM. Service는 enqueue + worker + dispatch. CRITICAL/standard 분기는 명시적. dependency cycle 없음 (Harness 2 PASS) |

**P4.2 핸드오프 항목**

- `V71NotificationService` instance를 운영 bootstrap에서 생성하고 P3 14개 호출지점의 `Notifier`로 wire (BuyExecutorContext.notifier, ExitExecutorContext.notifier, ViMonitorContext.notifier, ReconcilerContext.notifier, RecoveryContext.notifier)
- `PostgresNotificationRepository` 통합: bootstrap 시 SQLAlchemy AsyncSession 어댑터로 `execute(sql, *params) -> rows` callable 작성 (asyncpg/SQLAlchemy 둘 다 지원)
- `telegram_send`: V7.0 `TelegramBot.send_message`를 lambda로 wrap하여 주입 (parse_mode 가드 자동 상속)
- Phase 5 wiring: Web dispatcher (`web_dispatch`) -- 대시보드 WebSocket push로 channel="BOTH" 레코드 fan-out
- P4.2 텔레그램 명령어 13개: V71NotificationQueue + V71PositionManager + V71BoxManager 사용한 read-only 응답 + `/stop`/`/resume`/`/cancel` 안전 모드 토글
- `audit_scheduler.py` (P2.5에서 시그니처 작성됨) 본문: 매월 1일 09:00 트리거 → P4.4 monthly_review

**관찰: PRD 시그니처와 실제 구현 차이**

`07_SKILLS_SPEC.md §6.2`의 `send_notification(request, *, db_context, telegram_client, web_dispatcher)` 시그니처는 P2.3 시점 stub. 실제 P4.1 구현은 V71NotificationService가 owner이므로 `send_notification`은 thin wrapper로 단순화 (queue 인자 1개). 의미는 동등 (큐 enqueue → worker가 telegram + web 라우팅). PRD §6.2 후속 갱신 권장 (P4.2 시작 전 patch #2).

---

*최종 업데이트: 2026-04-26 (P4.1 완료)*

---

### P4.2: 텔레그램 명령어 13개 -- V71TelegramCommands + CommandContext (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §9 (notification surface), 05_MIGRATION_PLAN.md §6.3 (P4.2), 12_SECURITY.md §3.4 (chat_id 화이트리스트) + §8.3 (audit_logs)

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/notification/v71_telegram_commands.py` (신규) | `V71TelegramCommands` + `CommandContext` + `TrackedSummary` + 9개 pure formatter + 13 명령어 핸들러. 권한 검증 wrapper (`_wrap_handler`) + audit. Feature flag 가드: `v71.telegram_commands_v71`. 98.7% 커버리지 |
| 코드 | `src/core/v71/box/box_manager.py` | `list_all(*, status=None)` 메서드 추가 (P4.2 /pending /tracking 지원) |
| 코드 | `src/core/v71/notification/v71_notification_repository.py` | `NotificationRepository` Protocol + `InMemory` 구현에 `list_recent(*, limit, since=None)` 메서드 추가 (P4.2 /alerts 지원). 93.0% 커버리지 (변경 후) |
| 코드 | `src/core/v71/notification/v71_postgres_notification_repository.py` | `list_recent` Postgres 본문 추가 (since=None / since 분기). Phase 5 통합 테스트 |
| 코드 | `src/core/v71/notification/__init__.py` | export 확장 (`V71TelegramCommands`, `CommandContext`, `TrackedSummary`, `COMMANDS`) |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 v71_telegram_commands.py 추가 (90%) |
| 테스트 | `tests/v71/test_v71_telegram_commands.py` (신규) | 38 PASS. construction (3) + 권한 게이트 (4) + 명령어별 테스트 (29: status/positions/tracking/pending/today/recent/stop/resume/cancel/report/alerts/settings/help) + pure formatter (6) |

**13 명령어 매트릭스**

| 명령 | 데이터 소스 | 대표 응답 | 인자 |
|------|-------------|-----------|------|
| `/status` | V71BoxManager + V71PositionManager + V71CircuitBreaker + repository.list_recent | `[STATUS]` 안전 모드 / 박스 (전체/대기/체결) / OPEN 포지션 / 알림 큐 PENDING / Telegram Circuit | -- |
| `/positions` | V71PositionManager.list_open() | `[POSITIONS]` 종목별 보유 | -- |
| `/tracking` | `list_tracked` callback (TrackedSummary list) | `[TRACKING]` 종목 / 경로 / 박스 수 / 포지션 마커 | -- |
| `/pending` | V71BoxManager.list_all(status=WAITING) | `[PENDING]` 박스 가격대 + 비중 + id | -- |
| `/today` | V71PositionManager.list_events() filter today | `[TODAY]` 시각 + event_type + 종목 + 수량 | -- |
| `/recent` | list_events filter 7일 (configurable) | `[RECENT] 최근 7일` 거래 | -- |
| `/report <종목>` | report_handler callback (Phase 6 wires) | Phase 6 stub (`Phase 6에서 활성화`) | 종목코드 1개 |
| `/stop` | safe_mode_set(True) | `[STOP] 안전 모드 ON` | -- |
| `/resume` | safe_mode_set(False) | `[RESUME] 안전 모드 OFF` | -- |
| `/cancel <id>` | cancel_order callback | 성공/실패 메시지 | order_id 1개 |
| `/alerts [건수]` | repository.list_recent(limit, since=24h) | `[ALERTS]` 등급 + event + 메시지 첫 줄 | 선택 (기본 10) |
| `/settings` | feature_flags.all_flags() + V71Constants | `[SETTINGS]` 빈도 제한 / CB / retry / Feature flags 전체 | -- |
| `/help` | static | `[HELP]` 13개 명령어 도움말 | -- |

**권한 검증 (12 §3.4 + §8.3)**

`_wrap_handler` 가 모든 명령에 적용:
1. `chat_id` ∈ `authorized_chat_ids` 검증. 무권한이면 silent ignore + `audit_log(authorised=False, reason="UNAUTHORIZED_TELEGRAM_ACCESS")`. 12 §8.3 정합 (응답 자체 없음 = 봇 토큰 노출 시에도 인증된 chat_id 정보 비공개).
2. 권한 통과 시 `audit_log(authorised=True)`.
3. 핸들러 예외는 swallow + 사용자에게 "명령 처리 중 오류" 응답 (헌법 4 -- 폴링 루프 정지 X).
4. `audit_log` 자체가 raise해도 명령 처리 영향 없음 (`_safe_audit`로 wrap).

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
532 passed in ~1.3s
  - 기존 P3 + P4.1 누적                   494
  - test_v71_telegram_commands (P4.2 신규)  38

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - notification/v71_telegram_commands.py     98.7%
  - notification/v71_notification_repository.py 93.0% (list_recent 추가 후)
```

**핵심 룰 핀 (테스트 강제)**

| 룰 | 출처 | 테스트 |
|----|------|--------|
| 13 명령어 모두 register됨 | 05 §6.3 | `test_register_binds_all_thirteen` |
| 무권한 chat_id silent ignore + audit (UNAUTHORIZED_TELEGRAM_ACCESS) | 12 §3.4/§8.3 | `test_unauthorised_silently_ignored` |
| 권한 통과 시 audit (authorised=True) | 12 §8.3 | `test_authorised_audit_records_command` |
| 핸들러 예외 swallow + 오류 메시지 응답 (폴링 정지 X) | 헌법 4 | `test_handler_exception_is_swallowed_and_reported` |
| audit_log 자체 실패도 명령 처리 영향 없음 | 헌법 4 | `test_audit_failure_does_not_break_command` |
| `/status` 안전 모드 / 박스 통계 / CB 상태 포함 | 02 §9 | `test_status_includes_safe_mode_and_cb` |
| `/positions` empty / open 분기 | -- | `test_positions_empty`, `test_positions_lists_open` |
| `/tracking` TrackedSummary 렌더링 | -- | `test_tracking_renders_summaries` |
| `/pending` WAITING 박스만 | 02 §3.13 | `test_pending_filters_waiting` |
| `/today` start_of_today() 이후만 | -- | `test_today_only_today` |
| `/recent` 기본 7일 윈도 | 02 §9.7 | `test_recent_seven_day_window` |
| `/stop` 첫 호출만 toggle, 이미 on이면 no-op | -- | `test_stop_toggles_safe_mode`, `test_stop_when_already_safe_no_toggle` |
| `/resume` 첫 호출만 toggle | -- | `test_resume_toggles_off`, `test_resume_when_already_running` |
| `/cancel` 인자 누락 / 성공 / False / 예외 | -- | 4개 (TestCancel) |
| `/report` 인자 누락 / Phase 6 stub / handler 호출 / handler 실패 | 11_REPORTING.md (Phase 6) | 4개 (TestReport) |
| `/alerts` empty / window filter / 명시 limit / 잘못된 limit 인자 | -- | 4개 (TestAlerts) |
| `/settings` Feature flags + 빈도 제한 / CB / retry 표기 | 02 §9 + Feature flag enforcer | `test_settings_includes_flags_and_constants` |
| `/help` 13 명령어 모두 노출 | 05 §6.3 | `test_help_lists_all_commands` |
| Pure formatter들 empty edge case | -- | 6개 (TestFormatters) |

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ `/stop` `/resume` `/cancel` 모두 사용자 명시 명령으로만 동작. `/report`도 종목 명시 필수 |
| 2. NFR1 최우선 | ✅ 명령어 핸들러는 모두 read-only 또는 thin wrapper (DB INSERT 0). 거래 path 영향 없음 |
| 3. 충돌 금지 ★ | ✅ V71TelegramCommands + CommandContext + TrackedSummary 모두 `src/core/v71/notification/` 격리. V7.0 TelegramBot은 Protocol(`CommandRegistrar`)로만 의존, 단방향 |
| 4. 시스템 계속 운영 | ✅ 핸들러 예외 swallow / audit_log 실패 isolation / telegram_send 실패 isolation. 자동 정지 코드 0 |
| 5. 단순함 | ✅ pure formatter 분리 + 명령어별 thin handler + 단일 권한 wrapper. 의존성은 frozen dataclass 1개로 묶음 |

**P4.3 핸드오프 항목**

- 운영 bootstrap에서 `V71TelegramCommands` 인스턴스 생성 + `bot.register_command` wiring (V7.0 TelegramBot.start_polling 활용)
- `safe_mode_get`/`set`은 운영 단계 글로벌 상태로 wires. P3.7 `V71RestartRecovery`의 safe_mode 토글과 통합
- `cancel_order`: V71BuyExecutor의 미체결 주문 추적 + 키움 cancel API 호출 callback
- `list_tracked`: 향후 tracked_stocks 테이블 query 또는 in-memory tracker (P3.5 reconciler가 이미 list_tracked_for_stock 사용 중 - 전체 list 제공자 추가 필요)
- `audit_log`: 운영 시 V7.0 logger + 향후 audit_logs 테이블 INSERT
- `report_handler`: Phase 6 Claude Opus 4.7 리포트 생성기 wires
- P4.3 일일 마감 알림 (15:30 cron) + P4.4 월 1회 리뷰 (매월 1일 09:00 cron)

---

*최종 업데이트: 2026-04-26 (P4.2 완료)*

---

### P4.3: 일일 마감 알림 -- V71DailySummary + V71DailySummaryScheduler (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §9.7 (일일 마감, LOW severity), 05_MIGRATION_PLAN.md §6.4 (P4.3), 07_SKILLS_SPEC.md §6 (DAILY_SUMMARY event)

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/notification/v71_daily_summary.py` (신규) | `V71DailySummary` (compose + send) + `V71DailySummaryScheduler` (15:30 cron loop) + `DailySummaryContext` + `ScheduledTime` + 5개 module-level pure helper (`compose_daily_summary_body`, `compute_event_pnl`, `_filter_events_today`, `_start_of_day`, formatters). Feature flag: `v71.daily_summary`. 96.6% 커버리지 |
| 코드 | `src/core/v71/notification/__init__.py` | export 확장 (V71DailySummary, V71DailySummaryScheduler, DailySummaryContext, ScheduledTime) |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 v71_daily_summary.py 추가 (90%) |
| 테스트 | `tests/v71/test_v71_daily_summary.py` (신규) | 29 PASS. compose_daily_summary_body (6) + compute_event_pnl (5) + send (8) + ScheduledTime (2) + scheduler.next_target (4) + run_once (2) + lifecycle (2) |

**룰 매트릭스 (02 §9.7)**

| 룰 | 구현 | 테스트 |
|----|------|--------|
| 매일 15:30 발송 | `V71DailySummaryScheduler(target=ScheduledTime(15, 30))` + `next_target` | `test_before_target_today`, `test_after_target_rolls_to_tomorrow` |
| 거래 없는 날도 발송 ("오늘 거래 없음") | `compose_daily_summary_body` 분기 | `test_no_trades_today`, `test_send_no_trades_renders_placeholder` |
| 손익 절대값 + 자본 있으면 % | `total_capital` 옵션 분기 | `test_pnl_with_capital`, `test_pnl_without_capital_no_percent` |
| 거래 내역 (매수/매도 분리) | buy/sell 이벤트 분리 + 카운트 + 종목/수량/가격 | `test_send_includes_today_events_only` |
| 추적 변화 (자동 이탈 / 진입 임박) | TrackedSummary status=EXITED + (TRACKING + box>0 + no position) | `test_tracked_changes`, `test_tracked_more_than_three_summarised` |
| 내일 주목 (있다면) | `get_tomorrow_events` 옵션 callback, 비어있으면 섹션 생략 | `test_tomorrow_events_listed` |
| Severity LOW + event=DAILY_SUMMARY | `notify(severity="LOW", event_type="DAILY_SUMMARY", ...)` | `test_send_uses_low_severity_and_daily_summary_event` |
| rate_limit_key=`daily_summary:{date}` (날짜별 1건) | `_fmt_date(now)` | 동일 테스트 |
| 오늘 이벤트만 (어제 제외) | `_filter_events_today` start_of_day 기준 | `test_send_includes_today_events_only` |

**PnL 계산 (compute_event_pnl)**

| 이벤트 타입 | 처리 | 테스트 |
|-------------|------|--------|
| BUY_EXECUTED / PYRAMID_BUY / MANUAL_PYRAMID_BUY | None 반환 (PnL 없음) | `test_buy_returns_none` |
| PROFIT_TAKE_5 / PROFIT_TAKE_10 | (price - avg) * qty (양수 일반적) | `test_profit_take_pnl` |
| STOP_LOSS / TS_EXIT / MANUAL_SELL | (price - avg) * qty (음수 일반적) | `test_stop_loss_pnl_negative` |
| 알 수 없는 event_type / 없는 position_id | None 반환 (defensive) | `test_unknown_event_type_returns_none`, `test_unknown_position_returns_none` |

avg_price_index는 V71PositionManager.get(position_id).weighted_avg_price 조회. §6 이벤트 리셋 후 avg가 변경되어도 *현재* avg를 사용 (사용자 멘탈 모델에 부합).

**스케줄러 (V71DailySummaryScheduler)**

| 동작 | 구현 | 테스트 |
|------|------|--------|
| `next_target(now)` 미래 시각만 반환 | now <= target이면 today, 초과면 tomorrow | 4개 (TestSchedulerNextTarget) |
| `run_once()` sleep_until + send | Clock.sleep_until(target) 후 daily_summary.send() | `test_run_once_sleeps_until_target_then_sends` |
| send 실패 시 None 반환 + 로그 (loop 안 죽음) | try/except in run_once | `test_run_once_returns_none_on_summary_failure` |
| start/stop idempotent | task is None / done 체크 | `test_start_stop_idempotent` |
| 매일 1회만 발송 (60초 advance로 다음 target = 내일) | run_once 후 sleep(60) | `test_loop_fires_summary_at_least_once` |
| Custom HHMM (테스트용) | `target` 인자 | `test_custom_target` |
| 잘못된 HHMM 거부 | `ScheduledTime.from_hhmm` ValueError | `test_invalid_format` |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
561 passed in ~1.2s
  - 기존 P3 + P4.1 + P4.2 누적                532
  - test_v71_daily_summary (P4.3 신규)         29

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - notification/v71_daily_summary.py    96.6%
```

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자 거래/박스 데이터를 그대로 요약 (자동 추천 0). 내일 주목 이벤트는 사용자가 등록한 캘린더만 |
| 2. NFR1 최우선 | ✅ send()는 daily 한 번만 실행 (15:30). 거래 path latency 영향 0 |
| 3. 충돌 금지 ★ | ✅ V71 prefix (V71DailySummary, V71DailySummaryScheduler). v71/notification/ 격리. V71PositionManager / V71BoxManager / TrackedSummary 단방향 의존. V7.0 → V7.1 import 0 |
| 4. 시스템 계속 운영 | ✅ get_total_capital / get_tomorrow_events / list_tracked 실패는 swallow (해당 섹션만 생략). send 실패도 scheduler가 swallow + 다음 날 재시도. `_loop`는 step 예외도 swallow + 60초 sleep으로 다음 target |
| 5. 단순함 | ✅ pure compose_daily_summary_body 함수 + thin send wrapper + 단순 cron loop (AsyncIOScheduler 미도입 -- Constitution 5). 의존성은 frozen dataclass 1개 |

**P4.4 핸드오프 항목**

- `V71DailySummary` + scheduler 패턴을 그대로 monthly review에 적용:
  - `V71MonthlyReview` (compose + send) + `V71MonthlyReviewScheduler` (매월 1일 09:00 트리거)
  - LOW severity + event=MONTHLY_REVIEW
  - 02 §9.8 ABC 구조 (전체 현황 / 주의 필요 / 상태별 분류 / 전체 목록)
- 운영 bootstrap에서 `V71DailySummaryScheduler.start()` 호출 wiring (이미 P3.7 RestartRecovery의 Step 6/7 후속에서 시작 가능)
- `get_total_capital`: V7.0 RiskManager에서 wires (Phase 5 통합 트랙)
- `get_tomorrow_events`: 사용자 별도 캘린더 source (외부 calendar feed 또는 사용자 등록 입력)
- P3.4 `V71PositionManager.list_events()`는 in-memory; Phase 5 DB hydration 시 trade_events 테이블 query로 wires

---

*최종 업데이트: 2026-04-26 (P4.3 완료)*

---

### P4.4: 월 1회 리뷰 -- V71MonthlyReview + V71MonthlyReviewScheduler (완료, 2026-04-26)

**참조**: 02_TRADING_RULES.md §9.8 (월 1회 추적 리뷰, ABC 구조), 05_MIGRATION_PLAN.md §6.5 (P4.4), 03_DATA_MODEL.md §4 (monthly_reviews -- migration 016)

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 코드 | `src/core/v71/notification/v71_monthly_review.py` (신규) | `V71MonthlyReview` (compose + send) + `V71MonthlyReviewScheduler` (월 1일 09:00 cron) + `MonthlyReviewContext` + `MonthlyReviewItem` (per-stock snapshot) + `MonthlyCounts` (집계) + `compose_monthly_review_body` pure 함수. `DEFAULT_STALE_DAYS=60` (02 §9.8 "장기 정체"). Feature flag: `v71.monthly_review`. 96.8% 커버리지 |
| 코드 | `src/core/v71/notification/__init__.py` | export 확장 (V71MonthlyReview, V71MonthlyReviewScheduler, MonthlyReviewItem, MonthlyReviewContext, MonthlyCounts) |
| 검증 | `scripts/harness/test_coverage_enforcer.py` | THRESHOLDS에 v71_monthly_review.py 추가 (90%) |
| 테스트 | `tests/v71/test_v71_monthly_review.py` (신규) | 24 PASS. MonthlyCounts (1) + compose_monthly_review_body (8: header/전체 현황/장기 정체/holders 면제/만료 임박/상태별 분류/long list 절단/top5 stale 절단) + send (6: feature flag/severity/items 실패/expiring 실패/expiring 값/notifier 실패) + ScheduledTime 검증 (5: 1일 전/1일 후/중순/12월→1월 carry/잘못된 시간) + run_once (2) + lifecycle (2) |

**룰 매트릭스 (02 §9.8 ABC 구조)**

| 섹션 | 구현 | 테스트 |
|------|------|--------|
| `[월간 리뷰] {YYYY-MM}` 헤더 | `_fmt_year_month(now)` | `test_header_includes_year_month` |
| ■ 전체 현황 (추적/박스 대기/포지션 보유/부분 청산) | `MonthlyCounts.from_items` 집계 | `test_full_status_block`, `test_aggregates` |
| ⚠️ 주의 필요 -- 장기 정체 (60일+ 박스 미체결) | `_is_stale`: TRACKING + has_position=False + age >= 60일 | `test_stale_listed`, `test_stale_excludes_holders` |
| ⚠️ 주의 필요 -- 박스 만료 임박 (30일) | `list_expiring_boxes` callback 정수 | `test_expiring_boxes_count`, `test_expiring_callback_value` |
| ● 상태별 분류 (박스 대기 / 포지션 보유) | TRACKING + waiting_box>0 + no position 분류 | `test_status_breakdown_sections` |
| 부분 청산 marker | `has_partial_exit` 플래그 | `test_status_breakdown_sections` |
| 📋 전체 목록 | 모든 items 렌더 | `test_status_breakdown_sections`, `test_header_includes_year_month` |
| 긴 리스트 절단 (10개+ → "외 N개") | sample[:10] + suffix | `test_full_roster_truncates_long_lists` |
| 정체 종목 5개+ → "외 N개" | sample[:5] + suffix | `test_top5_stale_truncates` |
| Severity LOW + event=MONTHLY_REVIEW | `notify(severity="LOW", event_type="MONTHLY_REVIEW")` | `test_send_uses_low_severity_and_event` |
| rate_limit_key=`monthly_review:{YYYY-MM}` (월별 1건) | `_fmt_year_month(now)` | 동일 테스트 |
| Callback 실패 swallow + 섹션 생략 | items_raises / expiring_raises | `test_items_callback_failure_renders_empty`, `test_expiring_callback_failure_skips_line` |

**스케줄러 (V71MonthlyReviewScheduler)**

| 동작 | 구현 | 테스트 |
|------|------|--------|
| `next_target(now)` 미래 시각 | now <= 1일 09:00이면 이번 달, 초과면 다음 달 | `test_before_target_today_first_of_month`, `test_after_target_rolls_to_next_month`, `test_mid_month_rolls_to_first_of_next` |
| 12월 → 1월 carry (year+1) | `_first_of_next_month` helper | `test_december_rolls_to_january` |
| `run_once()` sleep_until + send | 동일 패턴 (P4.3과 일관) | `test_run_once_sleeps_until_target_then_sends` |
| send 실패 시 None + log (loop 안 죽음) | try/except in run_once | `test_run_once_send_failure_swallowed` |
| start/stop idempotent | `task is None / done` 체크 | `test_start_stop_idempotent` |
| 매월 1회만 발송 (60초 advance + next_target carry) | run_once 후 sleep(60) | `test_loop_fires_review_at_least_once` |
| 잘못된 시간 거부 | `0 <= hour <= 23 and 0 <= minute <= 59` | `test_invalid_time_raises` |

**검증 결과**

```
$ pytest tests/v71/ --no-cov -q
585 passed in ~1.4s
  - 기존 P3 + P4.1 + P4.2 + P4.3 누적         561
  - test_v71_monthly_review (P4.4 신규)         24

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
  - notification/v71_monthly_review.py    96.8%
```

**헌법 5원칙 자체 검증**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자 박스 결정 후 진행되지 않은 종목을 정체로 표시할 뿐, 자동 박스 만료/삭제 없음 (02 §3.7과 정합) |
| 2. NFR1 최우선 | ✅ 월 1회 발송, 거래 path latency 영향 0. compose는 pure 함수 + DB hop 0 |
| 3. 충돌 금지 ★ | ✅ V71 prefix (V71MonthlyReview, V71MonthlyReviewScheduler). v71/notification/ 격리. Notifier Protocol 단방향 의존 |
| 4. 시스템 계속 운영 | ✅ items / expiring callback 실패는 swallow + 섹션만 생략. send 실패는 scheduler 안에서 swallow + 다음 달 재시도 |
| 5. 단순함 | ✅ pure compose 함수 + thin send wrapper + 단순 cron loop (P4.3 V71DailySummaryScheduler와 동일 패턴, AsyncIOScheduler 미도입) |

---

## Phase 4 완료 (마일스톤 M4 진입, 2026-04-26)

```
$ pytest tests/v71/ --no-cov -q
585 passed in ~1.4s

$ python scripts/harness/run_all.py --with-7
PASS 7/7 harness(es)
```

### Phase 4 누적 산출물 (P4.1 ~ P4.4)

| Phase | 모듈 (코드) | 테스트 | 커버리지 |
|-------|-------------|--------|----------|
| P4.1 | skills/notification_skill (본문) + notification/v71_notification_repository + v71_postgres_notification_repository + v71_circuit_breaker + v71_notification_queue + v71_notification_service | 5 | 93~100% |
| P4.2 | notification/v71_telegram_commands (13 명령어) + box_manager.list_all + repository.list_recent | 1 | 98.7% |
| P4.3 | notification/v71_daily_summary | 1 | 96.6% |
| P4.4 | notification/v71_monthly_review | 1 | 96.8% |

**합계**: 8개 V7.1 신규 모듈 (notification/ 패키지 + 1 Postgres adapter) + 8개 신규 테스트 파일, 모두 90%+ 커버리지

### V7.1 알림 시스템 구현 완료 매트릭스

| §/룰 | P4.x | 모듈 |
|------|------|------|
| §9.1 4-등급 시스템 (CRITICAL/HIGH/MEDIUM/LOW) | P4.1 | notification_skill, v71_notification_queue |
| §9.2 채널 (CRITICAL/HIGH→BOTH, MEDIUM/LOW→TELEGRAM) | P4.1 | v71_notification_queue._resolve_channel |
| §9.3 우선순위 큐 (priority + FIFO) | P4.1 | v71_notification_repository.fetch_next_pending |
| §9.4 Circuit Breaker (3-fail / 30s / probe) | P4.1 | v71_circuit_breaker |
| §9.4 CRITICAL/HIGH 영구 보관 + MEDIUM/LOW 5분 만료 | P4.1 | repository._is_expired + expire_stale |
| §9.5 빈도 제한 (5분, CRITICAL 우회) | P4.1 | v71_notification_queue.is_rate_limited |
| §9.6 표준 메시지 포맷터 (8개) | P4.1 | notification_skill.format_* |
| §9.7 일일 마감 (15:30, LOW) | P4.3 | v71_daily_summary |
| §9.8 월 1회 리뷰 (1일 09:00, ABC 구조) | P4.4 | v71_monthly_review |
| §9.9 raw telegram 호출 차단 | P4.1 + Harness 3 | trading_rule_enforcer enforce |
| 텔레그램 명령어 13개 + 권한 검증 + audit | P4.2 | v71_telegram_commands |
| `/stop` `/resume` 안전 모드 토글 | P4.2 | v71_telegram_commands._cmd_stop/resume |
| 12 §3.4 + §8.3 chat_id 화이트리스트 + 무권한 silent ignore | P4.2 | _wrap_handler |

### Phase 4 헌법 5원칙 자체 검증 (전체)

| 원칙 | 검증 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자 거래/박스/추적 데이터를 그대로 알림으로 전환. 자동 추천 0. /stop /resume /cancel만 액션 명령 (모두 사용자 명시 입력) |
| 2. NFR1 최우선 | ✅ Notifier.notify는 enqueue만 (DB INSERT 1번). 모든 P3 14개 호출지점에서 거래 path latency < 1ms |
| 3. 충돌 금지 ★ | ✅ 8개 신규 모듈 모두 `src/core/v71/notification/` 격리 + V71 접두사. `V71CircuitState`는 V7.0 `src/api/client.py`의 `CircuitState`와 충돌 회피. V7.0 → V7.1 import 0. Harness 1/2/6 PASS |
| 4. 시스템 계속 운영 | ✅ Circuit OPEN 시에도 큐 작동 + CRITICAL/HIGH 영구 보관. Worker step 예외 swallow. 명령어 핸들러 예외 swallow. 모든 callback 실패 isolation. 자동 정지 코드 0 |
| 5. 단순함 | ✅ pure helper 다수, in-memory + DB-backed 분리, callback DI, 단순한 cron loop (AsyncIOScheduler 미도입). 전체 알림 surface = 8개 모듈, P3.x와 같은 비율 |

### 다음 단계

| Phase | 내용 | 예상 |
|-------|------|------|
| **Phase 5** | 웹 대시보드 (FastAPI + JWT + 2FA + React UI) | 5~10일 |
| **Phase 6** | 리포트 (Claude Opus 4.7 통합) | 3~5일 |
| **Phase 7** | 통합 테스트 + 페이퍼 트레이드 + AWS 배포 | 5~10일 |

V7.0 인프라 통합도 별도 트랙으로 진행:
- `kiwoom_api_skill` 본문 (실 HTTP 호출)
- `PostgresNotificationRepository` 통합 테스트 (Phase 5 또는 별도 시점)
- 운영 bootstrap에서 V71NotificationService + V71TelegramCommands + V71DailySummaryScheduler + V71MonthlyReviewScheduler wiring

---

*최종 업데이트: 2026-04-26 (P4.4 + Phase 4 100% 완료)*

---

## Phase 5: 웹 대시보드 (진행 중 -- 프론트엔드 트랙 분리)

### 사용자 결정 사항 (2026-04-26)

| 항목 | 결정 |
|------|------|
| 빌드 도구 | **Vite** |
| 패키지 매니저 | **npm** |
| 빌드 출력 위치 | **`frontend/`** 신규 디렉토리 (12 §2.4 Nginx 정합) |
| WebSocket | 네이티브 (FastAPI 정합) |
| 테마 초기값 | **g100 (다크)** + localStorage 토글 |
| 시작 위치 | 백엔드(FastAPI) 먼저 (P5.1) → 프론트엔드(Carbon) 나중 |
| 첫 화면 (백엔드) | health/status + 인증 골격 (B3 결정 보류) |
| Figma | `(v11) Carbon Design System (Community).fig` 프로젝트 루트에 배치 |

### Phase 5 트랙 분리 (사용자 워크플로우 변경, 2026-04-26)

원래 계획: Claude Code가 백엔드 (FastAPI) → 프론트엔드 (Carbon UI) 순차 작업.

변경: **사용자가 Claude Design으로 프론트엔드 프로토타입 먼저 작업** → Claude Code가 백엔드 동시 진행 → 프로토타입 산출물 갖고 와서 백엔드와 통합.

```
[사용자 트랙]                        [Claude Code 트랙]
Claude Design 프롬프트 인계  ─────►  CLAUDE_DESIGN_PROMPT.md 작성 (P5.0)
       │                                      │
       ▼                                      ▼
Claude Design에서 React +              백엔드 P5.1+ 진행 가능
Carbon 프로토타입 생성                  (FastAPI 골격, V71AppContext, 인증)
       │                                      │
       ▼                                      │
산출물 (frontend/ 디렉토리)                    │
       │                                      │
       └────────────► 통합 ◄──────────────────┘
                        │
                        ▼
              Phase 5 P5.5+ (Carbon 컴포넌트 wires + WebSocket + e2e)
```

### P5.0: Claude Design 프로토타입 프롬프트 (완료, 2026-04-26)

**참조**: 10_UI_GUIDE_CARBON.md (전체 1620 라인 정독), 09_API_SPEC.md (응답 wrapper + 9개 리소스 스키마), 12_SECURITY.md §3 (인증)

**산출물**

| 분류 | 파일 | 비고 |
|------|------|------|
| 문서 | `docs/v71/CLAUDE_DESIGN_PROMPT.md` (신규) | 1400 라인 종합 프롬프트. Claude Design (claude.ai/design 또는 동급) 단일 입력으로 V7.1 React + TypeScript + Vite + @carbon/react 프로토타입을 생성하기 위한 명세 |

**프롬프트 구성 (13개 섹션)**

| § | 내용 |
|---|------|
| 0 | 프롬프트 사용법 + 산출물 기대 |
| 1 | 시스템 한 문장 정의 + 사용자/환경/핵심 개념 (박스/추적/포지션/알림) |
| 2 | 디자인 시스템 절대 룰 (패키지 / 한국식 손익 색상 / g100 다크 / SCSS / 디자인 토큰 / 5대 원칙) |
| 3 | 9개 화면 명세 (전체 레이아웃 + 라우팅 + 화면 1~9) |
| 4 | 인터랙션 표준 (폼 검증 / 로딩 / Toast / danger Modal / 키보드 단축키) |
| 5 | 반응형 (Carbon Grid sm/md/lg/xlg/max + 모바일 적응) |
| 6 | Mock Data 명세 (응답 wrapper / 디렉토리 구조 / TypeScript 타입 13개 / 시나리오 시뮬레이션) |
| 7 | 산출물 디렉토리 구조 (`frontend/src/{pages,components,mocks,hooks,types,styles}/`) |
| 8 | 헌법 5원칙 (UI 적용) |
| 9 | 절대 금지 사항 (재확인) |
| 10 | 변환 매핑 (shadcn/ui → Carbon) |
| 11 | 빌드 + 의존성 (package.json + vite.config.ts) |
| 12 | 산출물 검증 체크리스트 |
| 13 | 작업 시작 명령 |

**TypeScript 타입 정의 포함 (§6.2)**

`TrackedStock`, `Box`, `Position`, `TradeEvent`, `NotificationRecord`, `Report`, `SystemStatusData` + 11개 enum (`PathType`, `StrategyType`, `TrackedStatus`, `BoxStatus`, `PositionSource`, `PositionStatus`, `Severity`, `NotificationStatus`, `NotificationChannel`, `ReportStatus`, `SystemStatus`).

**다음 단계 (사용자 측)**

1. 사용자가 `CLAUDE_DESIGN_PROMPT.md` 전체를 Claude Design에 단일 입력으로 붙여넣기
2. (선택) `(v11) Carbon Design System (Community).fig` 업로드
3. Claude Design이 9개 화면 React 프로토타입 + mock data + SCSS 생성
4. 사용자가 산출물 (frontend/ 디렉토리) Claude Code (이 트랙)에게 인계
5. Claude Code가 백엔드 P5.1+ (FastAPI / 인증 / API 엔드포인트 / WebSocket) 진행하여 통합

**Claude Code 측 다음 단계 (대기)**

- 사용자가 frontend/ 산출물을 갖고 올 때까지 백엔드 P5.1 보류
- 사용자 결정 시 P5.1 (FastAPI 골격) → P5.2 (JWT + 2FA) → P5.3 (REST API) → P5.4 (WebSocket) → P5.5 (frontend 통합) → P5.6 (e2e + 검증)
- 또는 사용자 지시에 따라 백엔드를 먼저 진행할 수도 있음 (사용자가 메시지로 결정)

**헌법 5원칙 자체 검증 (P5.0)**

| 원칙 | 준수 |
|------|------|
| 1. 사용자 판단 불가침 | ✅ 사용자가 박균호 결정한 Carbon Design System 그대로 prompt에 명시. 자동 추천 UI 금지 명시 (§8 원칙 1) |
| 2. NFR1 최우선 | ✅ N/A (UI 명세 단계) |
| 3. 충돌 금지 ★ | ✅ shadcn/ui / Tailwind / Lucide 등 절대 금지 명시 (§9). frontend/ 디렉토리로 격리. V7.0 인프라와 분리. PRD Patch #2 정합 |
| 4. 시스템 계속 운영 | ✅ N/A (문서 작성) |
| 5. 단순함 우선 | ✅ pure dataclass + Mock simulator + 단순 컴포넌트 패턴. 화려한 애니메이션 회피 명시 |

---

*최종 업데이트: 2026-04-26 (P5.0 -- Claude Design 프롬프트 완료, 사용자 작업 대기)*
