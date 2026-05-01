# CLAUDE.md

> **K_stock_trading** -- 키움증권 REST API 국내 주식 자동매매 시스템 (V7.1 단독 운영)
> **버전**: V7.1 Box-Based Trading System
> **현재 작업**: Phase 5 (V7.1 단독 운영 + auth sliding session land 2026-05-01) -- Phase 4 (알림) 일부 진행 중
> **PRD**: `docs/v71/01_PRD_MAIN.md` / **진행 로그**: `docs/v71/WORK_LOG.md` / **마지막 tag**: `v71-phase3-complete`

> **V7.0 (Purple-ReAbs)는 2026-04-28 commit 33ee3ee에서 완전 폐기 + 2026-05-01 잔재 일괄 정리됨**.
> 참조 필요 시 git tag `v7.0-final-stable`로만 접근.

---

> **V7.1 작업 시 필독**: [`docs/v71/01_PRD_MAIN.md`](docs/v71/01_PRD_MAIN.md) -- 통합 PRD 진입점
> **헌법 5원칙** (V7.1 PRD §1): 사용자 판단 불가침 / NFR1 우선 / 충돌 금지 / 항상 운영 / 단순함

---

# Part 1: 절대 규칙

## 1.1 금지 사항

| 분류 | 금지 행동 | 대체 방법 |
|------|----------|----------|
| **코드** | 읽지 않은 파일 수정 | Read 도구로 먼저 읽기 |
| **인코딩** | PowerShell로 파일 저장 | Write/Edit 도구 사용 |
| **배포** | SSH 직접 실행 | `search_logs.ps1 -cmd "명령어"` |
| **텔레그램** | parse_mode 사용 | plain text만 사용 (P-Wire-3 fail-secure) |
| **컨텍스트** | 업데이트 없이 완료 선언 | Part 3.4 절차 완료 후 응답 |
| **.env** | 인라인 주석 사용 | 별도 라인에 주석 작성 (Part 4 참조) |
| **V7.1 격리** | V7.0 잔재 import / 의존 추가 | V7.1은 자체 완결 — `src/core/v71/` + `src/web/v71/` |

---

# Part 2: 운영 명령어

## 2.1 배포 (V7.1 hotfix)

```powershell
# 배포 (파일 전송 + v71.service 재시작)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\hotfix.ps1"

# 배포 (파일만 전송, 서비스 재시작 안 함)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\hotfix.ps1" -NoRestart

# 로그 확인 (배포 후)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_logs.ps1" 50

# 상태 확인
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\status.ps1"

# 부팅 smoke (V7.1 systemd active + /health + DB + V71MarketSchedule seeded)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\boot_smoke_v71.ps1"

# V7.1 invariant 체크 (5 flag false 유지 + storage SSoT)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_invariants.ps1"
```

## 2.2 서버 정보

| 항목 | 값 |
|------|-----|
| 호스트 | 43.200.235.74 (AWS Lightsail) |
| 도메인 | albra.net (Cloudflare Tunnel) |
| 경로 | `/home/ubuntu/K_stock_trading/current` |
| systemd unit | `v71.service` (uvicorn `src.web.v71.main:app` :8080) |

## 2.3 자주 쓰는 명령어

```powershell
# 서버 로그 검색
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\search_logs.ps1" -pattern "keyword"

# 서버 명령어 실행 (SSH 직접 금지의 대체)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\search_logs.ps1" -cmd "your_command"

# DB 확인
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_db_server.ps1"
```

## 2.4 로컬 개발 환경 (dev)

```powershell
# backend + frontend 한 번에 시작 (V7.1 dev launcher)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\start_dev.ps1"

# 또는 backend 단독
& "C:\Program Files\Python311\python.exe" scripts\dev_run_local.py
```

| 항목 | 값 |
|------|-----|
| URL | `http://localhost:5173` (vite) → proxy → `127.0.0.1:8080` (backend) |
| 사용자 | `admin` / `admin` |
| DB | `data/dev.db` (SQLite, 격리) |
| TOTP | OFF (V71_WEB_ENVIRONMENT=dev 분기) |
| 거래 엔진 | OFF (V71_WEB_BOOT_TRADING_ENGINE=false) |

## 2.5 Python 실행

```bash
"C:\Program Files\Python311\python.exe" -m pytest tests/v71/ -v
```

## 2.6 시간 규칙

| 구분 | 시간 |
|------|------|
| 정규장 | 09:00~15:20 KST |
| 박스 진입 탐지 | 09:05~15:20 KST |
| EOD 알림 / 일봉 마감 | 15:30 KST (V71MarketSchedule + KR_HOLIDAYS_2026) |
| NXT 청산 (애프터마켓) | 08:00~20:00 KST |

## 2.7 백테스트 (V7.1에서 폐기)

V7.1은 룰 기반 시스템(02_TRADING_RULES.md). 검증은 페이퍼 트레이드(Phase 7) +
단위 테스트 (`tests/v71/`, ≥90% 커버리지) + 8 harness (G1 SSoT 등)로 수행.

---

# Part 3: 참조

## 3.1 문서

| 문서 | 용도 |
|------|------|
| `docs/v71/01_PRD_MAIN.md` | **V7.1 PRD 진입점** (단일 진실 원천) |
| `docs/v71/02_TRADING_RULES.md` | 박스 진입 / 손절 / 익절 / TS / 평단가 / VI 룰 |
| `docs/v71/03_DATA_MODEL.md` | DB 스키마 + ORM 모델 |
| `docs/v71/04_ARCHITECTURE.md` | 모듈 구조 + 의존성 + 격리 정책 |
| `docs/v71/05_MIGRATION_PLAN.md` | Phase별 마이그레이션 계획 |
| `docs/v71/06_AGENTS_SPEC.md` | 5 sub-agent (architect/security/test/migration/trading-logic) |
| `docs/v71/07_SKILLS_SPEC.md` | 8 표준 스킬 (kiwoom_api / box_entry / exit_calc 등) |
| `docs/v71/08_HARNESS_SPEC.md` | 8 harness (네이밍 충돌 / G1 SSoT / 거래 룰 enforcer 등) |
| `docs/v71/09_API_SPEC.md` | REST API 엔드포인트 명세 |
| `docs/v71/10_UI_GUIDE.md` | Carbon Design System 기반 frontend |
| `docs/v71/12_SECURITY.md` | JWT/TOTP/Audit/Rate-limit 보안 정책 |
| `docs/v71/13_APPENDIX.md` | 부록 (환경 변수, 운영 정책 등) |
| `docs/v71/WORK_LOG.md` | Phase별 진행 상황 |
| `docs/CHANGELOG.md` | 시스템 전체 버전 히스토리 |

## 3.2 V7.1 핵심 모듈 (상세: docs/v71/04_ARCHITECTURE.md)

| 분류 | 모듈 | 위치 |
|------|------|------|
| **Box** | V71BoxManager / Repository | `src/core/v71/box/` |
| **Box** | V71BoxEntryDetector (PATH_A/B) | `src/core/v71/box/box_entry_detector.py` |
| **Exchange** | V71KiwoomClient / WebSocket / Reconciler | `src/core/v71/exchange/` |
| **Exit** | V71ExitCalculator / TrailingStop / Executor | `src/core/v71/exit/` |
| **Position** | V71PositionManager (DB-backed atomic) | `src/core/v71/position/` |
| **Notification** | V71NotificationService / DailySummary / MonthlyReview / TelegramCommands | `src/core/v71/notification/` |
| **Skills** | kiwoom_api / box_entry / exit_calc / avg_price / vi / notification / reconciliation | `src/core/v71/skills/` |
| **Pricing** | V71PricePublisher (PRICE_TICK → DB + WS) | `src/core/v71/pricing/` |
| **Web** | FastAPI app (auth / boxes / positions / etc.) | `src/web/v71/` |
| **Bridge** | TradingBridge (lifespan wiring 13 P-Wire 단위) | `src/web/v71/trading_bridge.py` |

## 3.3 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 시스템 상태 (RUNNING/SAFE_MODE + 박스/포지션/자본 요약) |
| `/buy 종목코드 [수량]` | 수동 매수 (V71OrderManager + 알림 wire) |
| `/sell 종목코드 [수량]` | 수동 매도 |
| `/positions` | 활성 포지션 목록 |
| `/pending` | 진입 대기 박스 목록 |
| `/help` | 명령어 도움말 |

## 3.4 컨텍스트 관리 (필수)

### 세션 시작 시
`.claude/state/work-context.json` 확인 (또는 `/context-loader`).

### 작업 완료 전 필수 단계

| 순서 | 파일 | 조건 | 방법 |
|------|------|------|------|
| 1 | `work-context.json` | **모든 코드/설정 변경** | `/work-log` 또는 직접 수정 |
| 2 | `CHANGELOG.md` | 기능 추가 / 버그 수정 / 배포 | 기존 포맷 따라 추가 |
| 3 | `docs/v71/WORK_LOG.md` | Phase 진행 / 큰 단위 land | Phase별 섹션에 추가 |
| 4 | 체크리스트 | 후속 확인 필요 시 | `.claude/checklists/` |

### 강제 규칙

> **작업 완료 보고 전:**
> 1. `/work-log` 스킬 실행 또는
> 2. work-context.json 직접 업데이트
>
> **컨텍스트 업데이트 없이 "완료" 응답 금지** (Part 1.1 참조)

### 자기 점검

작업 완료 전 확인:
1. work-context.json 업데이트했는가?
2. CHANGELOG.md / WORK_LOG.md 업데이트 필요한 변경인가?
3. 다음 세션 작업을 기록했는가?

---

# Part 4: 과거 오류 기록

> 같은 실수를 반복하지 않기 위한 기록.

## 4.1 .env 인라인 주석 오류 (2026-01-22)

### 증상

```
초기화 실패: validation error
KIWOOM_APP_KEY
  Input should be a valid string, unable to interpret input
  [input_value='abc123  # production key']
```

### 원인

```bash
# 잘못된 .env 작성
KIWOOM_APP_KEY=abc123  # production key

# systemd EnvironmentFile이 읽은 값
KIWOOM_APP_KEY="abc123  # production key"
```

**python-dotenv**는 `#` 이후를 주석으로 처리하지만, **systemd EnvironmentFile**은
값의 일부로 해석.

### 배포 구조 문제

```
/home/ubuntu/K_stock_trading/
├── current/.env      ← hotfix.ps1이 복사하는 위치
├── shared/.env       ← systemd EnvironmentFile이 로드하는 위치
```

`hotfix.ps1`은 `current/.env` + `shared/.env` 양쪽 모두 갱신하지만,
인라인 주석이 있으면 양쪽 모두에 같은 결함이 복제됨.

### 해결책

```bash
# 올바른 .env 작성 — 주석은 별도 라인
# production 키
KIWOOM_APP_KEY=abc123
```

### 교훈

| 규칙 | 설명 |
|------|------|
| .env 인라인 주석 금지 | systemd 호환성 문제 |
| shared/.env 확인 | 배포 시 양쪽 .env 모두 검증 |
| 전체 구조 파악 | current vs shared 차이 인지 |
