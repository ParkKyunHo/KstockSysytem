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
| P3.1 박스 시스템 (+ 09:05 fallback) | ✅ 완료 |
| P3.2 매수 실행 (PATH_A/B + 09:05 fallback executor) | 다음 |
| P3.3 매수 후 관리 | 대기 |
| P3.4 평단가 관리 | 대기 |
| P3.5 수동 거래 처리 | 대기 |
| P3.6 VI 처리 | 대기 |
| P3.7 시스템 재시작 복구 | 대기 |

---

*최종 업데이트: 2026-04-26 (P3.1 완료)*
