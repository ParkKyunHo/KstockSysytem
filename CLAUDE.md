# CLAUDE.md

> **K_stock_trading** - 키움증권 REST API 국내 주식 자동매매 시스템
> **버전**: V7.1 (Box-Based Trading System) -- V7.0 Purple-ReAbs is legacy
> **현재 작업**: Phase 3 (거래 룰) 100% 완료 (M3, 2026-04-26) → **Phase 4 (알림 시스템)** 다음
> **PRD**: `docs/v71/` / **진행 로그**: `docs/v71/WORK_LOG.md` / **마지막 tag**: `v71-phase3-complete`

---

> **V7.1 구축 시 필독**: [`docs/v71/01_PRD_MAIN.md`](docs/v71/01_PRD_MAIN.md) -- 통합 PRD 진입점
> **V7.0 (legacy) 참조**: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) -- 폐기 전까지 운영용
> **헌법 5원칙**: V7.1 PRD §1 -- 사용자 판단 불가침 / NFR1 우선 / 충돌 금지 / 항상 운영 / 단순함

---

# Part 1: 절대 규칙

## 1.1 금지 사항

| 분류 | 금지 행동 | 대체 방법 |
|------|----------|----------|
| **코드** | 읽지 않은 파일 수정 | Read 도구로 먼저 읽기 |
| **코드** | V7 수정 불가 항목 변경 | 섹션 2.3 확인 |
| **인코딩** | PowerShell로 파일 저장 | Write/Edit 도구 사용 |
| **배포** | SSH 직접 실행 | `search_logs.ps1 -cmd "명령어"` |
| **텔레그램** | parse_mode 사용 | plain text만 사용 |
| **컨텍스트** | 업데이트 없이 완료 선언 | 4.4 절차 완료 후 응답 |
| **.env** | 인라인 주석 사용 | 별도 라인에 주석 작성 (Part 5 참조) |


---

# Part 2: V7 Purple-ReAbs

## 2.1 신호 조건 (5개 모두 충족)

```python
Signal = PurpleOK AND Trend AND Zone AND ReAbsStart AND Trigger

# PurpleOK: (H1/L1-1)>=4% AND (H2/L2-1)<=7% AND M>=5억
# Trend: EMA60 > EMA60[3]
# Zone: Close >= EMA60 × 0.995
# ReAbsStart: Score > Score[1]
# Trigger: CrossUp(Close, EMA3) AND Close > Open
```

## 2.2 Wave Harvest 청산

| 조건 | ATR 배수 |
|------|----------|
| 초기 진입 | 6.0 |
| 구조 경고 | 4.5 |
| R ≥ 1 | 4.0 |
| R ≥ 2 | 3.5 |
| R ≥ 3 | 2.5 |
| R ≥ 5 | 2.0 |

```python
# R-Multiple
R = (현재가 - 진입가) / (진입가 × 0.04)

# 트레일링 스탑
BasePrice = Highest(High, 20)
TrailingStop = max(prev_stop, BasePrice - ATR(10) × Multiplier)

# Trend Hold Filter (청산 차단)
TrendHold = EMA20 > EMA60 AND HighestHigh(20) > HighestHigh(60) AND ATR >= ATR_5ago * 0.8

# 청산: NOT TrendHold AND Close < TrailingStop
```


```

## 2.4 V7 활성화

```bash
# .env 파일
V7_PURPLE_ENABLED=true
```

---

# Part 3: 운영 명령어

## 3.1 배포

```powershell
# 배포 (파일 전송 + 서비스 재시작)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\hotfix.ps1"

# 배포 (파일만 전송, 서비스 재시작 안 함)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\hotfix.ps1" -NoRestart

# 로그 확인 (배포 후)
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_logs.ps1" 50

# 상태 확인
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\status.ps1"
```

## 3.2 서버 정보

| 항목 | 값 |
|------|-----|
| 호스트 | 43.200.235.74 |
| 경로 | `/home/ubuntu/K_stock_trading/current` |

## 3.3 자주 쓰는 명령어

```powershell
# 서버 로그 검색
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\search_logs.ps1" -pattern "keyword"

# 서버 명령어 실행
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\search_logs.ps1" -cmd "your_command"

# DB 확인
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_db_server.ps1"
```

## 3.4 Python 실행

```bash
"C:\Program Files\Python311\python.exe" -m pytest tests/ -v
```

## 3.5 시간 규칙

| 구분 | 시간 |
|------|------|
| 정규장 | 09:00~15:20 |
| 신호 탐지 | 09:05~15:20 |
| NXT 청산 | 08:00~20:00 |

## 3.6 백테스트 (V7.1에서 폐기)

V7.1은 룰 기반 시스템(02_TRADING_RULES.md)으로, 별도의 백테스트 인프라를 사용하지 않습니다. 검증은 페이퍼 트레이드(Phase 7)와 단위 테스트(>=90% 커버리지)로 수행합니다. 기존 백테스트 코드는 P1.2에서 제거되었습니다.

---

# Part 4: 참조

## 4.1 문서

| 문서 | 용도 |
|------|------|
| `docs/ARCHITECTURE.md` | **시스템 아키텍처** (모듈 구조, 데이터 흐름, 리팩토링 현황) |
| `docs/TECHNICAL_DOCUMENTATION.md` | 시스템 전체 상세 |
| `docs/CHANGELOG.md` | 버전 히스토리 |
| `docs/DEPLOYMENT_GUIDE.md` | 배포 가이드 |
| `docs/v71/01_PRD_MAIN.md` | **V7.1 신규 시스템 PRD** (현재 작업의 단일 진실 원천) |
| `docs/v71/WORK_LOG.md` | **V7.1 작업 로그** (Phase별 진행 상황) |

## 4.2 핵심 모듈 (상세: ARCHITECTURE.md 참조)

| 분류 | 모듈 | 파일 |
|------|------|------|
| **Phase 3** | V7SignalCoordinator | `src/core/v7_signal_coordinator.py` |
| **Phase 3** | ExitCoordinator | `src/core/exit_coordinator.py` |
| **Phase 3** | PositionSyncManager | `src/core/position_sync_manager.py` |
| **Phase 3** | SignalProcessor | `src/core/signal_processor.py` |
| **Phase 1** | IndicatorLibrary | `src/core/indicator_library.py` |
| **Phase 1** | Constants | `src/core/constants.py` |
| **V7** | PurpleSignalDetector | `src/core/signal_detector_purple.py` |
| **V7** | WaveHarvestExit | `src/core/wave_harvest_exit.py` |
| **V7** | SignalPool | `src/core/signal_pool.py` |

## 4.3 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 시스템 상태 |
| `/buy 종목코드` | 수동 매수 |
| `/sell 종목코드` | 수동 매도 |

---

## 4.4 컨텍스트 관리 (필수)

### 세션 시작 시
`.claude/state/work-context.json` 확인 (또는 `/context-loader`)

### 작업 완료 전 필수 단계

| 순서 | 파일 | 조건 | 방법 |
|------|------|------|------|
| 1 | `work-context.json` | **모든 코드/설정 변경** | `/work-log` 또는 직접 수정 |
| 2 | `CHANGELOG.md` | 기능 추가/버그 수정/배포 | 기존 포맷 따라 추가 |
| 3 | 체크리스트 | 후속 확인 필요 시 | `.claude/checklists/` |

### 업데이트 트리거

**work-context.json 필수:**
- `src/`, `scripts/` 코드 수정
- 설정 파일 수정 (`.env`, `config/`)
- 서버 배포
- 버그 수정

**CHANGELOG.md 필수:**
- 버전 변경
- 기능 추가/삭제
- 아키텍처 변경
- 중요 버그 수정

### 강제 규칙

> **작업 완료 보고 전:**
> 1. `/work-log` 스킬 실행 또는
> 2. work-context.json 직접 업데이트
>
> **컨텍스트 업데이트 없이 "완료" 응답 금지** (Part 1.1 참조)

### 자기 점검

작업 완료 전 확인:
1. work-context.json 업데이트했는가?
2. CHANGELOG.md 업데이트 필요한 변경인가?
3. 다음 세션 작업을 기록했는가?

---

# Part 5: 과거 오류 기록

> 같은 실수를 반복하지 않기 위한 기록

## 5.1 .env 인라인 주석 오류 (2026-01-22)

### 증상

```
초기화 실패: 2 validation errors for RiskSettings
ATR_ALERT_ENABLED
  Input should be a valid boolean, unable to interpret input
  [input_value='false  # V6 SNIPER_TRAP 신호 비활성화']
```

### 원인

```bash
# 잘못된 .env 작성
SNIPER_TRAP_ENABLED=false  # V6 SNIPER_TRAP 신호 비활성화

# systemd EnvironmentFile이 읽은 값
SNIPER_TRAP_ENABLED="false  # V6 SNIPER_TRAP 신호 비활성화"
```

**python-dotenv**는 `#` 이후를 주석으로 처리하지만, **systemd EnvironmentFile**은 값의 일부로 해석.

### 배포 구조 문제

```
/home/ubuntu/K_stock_trading/
├── current/.env      ← hotfix.ps1이 복사하는 위치
├── shared/.env       ← systemd EnvironmentFile이 로드하는 위치
```

`hotfix.ps1`은 `current/.env`만 업데이트하므로, `shared/.env`의 인라인 주석이 남아있었음.

### 해결책

```bash
# 올바른 .env 작성
# V6 레거시 전략 비활성화
SNIPER_TRAP_ENABLED=false
ATR_ALERT_ENABLED=false
```

### 교훈

| 규칙 | 설명 |
|------|------|
| .env 인라인 주석 금지 | systemd 호환성 문제 |
| shared/.env 확인 | 배포 시 양쪽 .env 모두 확인 |
| 전체 구조 파악 | current vs shared 차이 인지 |
