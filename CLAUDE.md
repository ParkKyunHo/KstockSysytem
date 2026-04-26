# CLAUDE.md

> **K_stock_trading** - 키움증권 REST API 국내 주식 자동매매 시스템
> **버전**: V7.0 Purple-ReAbs (Phase 3 리팩토링 완료)

---

> **코드 수정 시 필독**: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - 시스템 구조, 모듈 역할, 데이터 흐름
> **OpenClaw 작업 시 필독**: [`docs/OPENCLAW_GUIDE.md`](docs/OPENCLAW_GUIDE.md) - 스킬 구조, API 연동, 트러블슈팅

---

# Part 0: OpenClaw 텔레그램 AI 어시스턴트

> 키움증권 REST API를 OpenClaw(Gemini 2.5 Pro) 텔레그램 봇으로 연동하여
> 자연어로 시장 데이터를 조회하는 시스템

## 0.1 시스템 구성

```
[사용자] ←→ [Telegram] ←→ [OpenClaw Gateway :19000] ←→ [Gemini 2.5 Pro]
                                    ↓
                            [exec: kiwoom_ranking.sh]
                                    ↓
                            [키움 REST API (api.kiwoom.com)]
```

| 구성요소 | 설명 |
|----------|------|
| OpenClaw v2026.2.23 | 로컬 AI 에이전트 프레임워크 |
| Gateway | `localhost:19000` (Scheduled Task로 자동시작) |
| 모델 | `google/gemini-2.5-pro` |
| 채널 | Telegram (`@stock_Albra_bot`) |
| 스킬 경로 | `~/.openclaw/skills/` |
| 워크스페이스 | `~/.openclaw/workspace/` |

## 0.2 구현 완료 스킬

| 스킬 | 설명 | 스크립트 |
|------|------|----------|
| `kiwoom-market-ranking` | 거래대금 상위 종목 조회 | `scripts/kiwoom_ranking.sh` |

## 0.3 향후 구축 로드맵

| 우선순위 | 스킬 | 기능 | 키움 API |
|----------|------|------|----------|
| **P1** | `kiwoom-stock-price` | 개별 종목 현재가/일봉 조회 | ka10001, ka10081 |
| **P1** | `kiwoom-portfolio` | 보유 종목 현황 + 수익률 | ka10072 |
| **P2** | `kiwoom-signal-status` | V7 매매 신호 현황 (DB 조회) | Supabase signals 테이블 |
| **P2** | `kiwoom-trade-history` | 금일/최근 체결 내역 | ka10073 |
| **P3** | `kiwoom-market-index` | 코스피/코스닥 지수 현황 | ka80003 |
| **P3** | `kiwoom-sector-ranking` | 업종별 등락률 순위 | ka10031 |

## 0.4 OpenClaw 운영 명령어

```powershell
# Gateway 시작 (bash에서 실행 — cmd.exe 한글 경로 깨짐 문제)
# Scheduled Task "OpenClaw Gateway"로 자동시작 설정됨
# 수동 시작이 필요한 경우:
openclaw gateway restart

# 스킬 목록 확인
openclaw skills list

# 스킬 상세 정보
openclaw skills info kiwoom-market-ranking

# 텔레그램으로 메시지 전송 테스트
openclaw agent -m "거래대금 상위 10종목" --agent main --channel telegram --deliver --json --timeout 120

# Gateway 로그 확인
type %TEMP%\openclaw\openclaw-YYYY-MM-DD.log
```

## 0.5 스킬 개발 규칙

| 규칙 | 설명 |
|------|------|
| **SKILL.md 필수** | YAML frontmatter + When to Use/NOT to Use + 스크립트 사용법 |
| **TOOLS.md 등록 필수** | managed 스킬은 자동 주입 안 됨 → `~/.openclaw/workspace/TOOLS.md`에 사용법 추가 |
| **환경변수** | `~/.openclaw/openclaw.json`의 `env` 섹션에 등록 |
| **requires** | `bins`, `env` 명시 — 미충족 시 스킬이 "missing" 상태 |
| **경로 주의** | `~` 대신 절대경로 사용 (PowerShell 호환성) |
| **상세 가이드** | [`docs/OPENCLAW_GUIDE.md`](docs/OPENCLAW_GUIDE.md) 참조 |

## 0.6 알려진 이슈

| 이슈 | 원인 | 해결 |
|------|------|------|
| `gateway.cmd` 한글 경로 깨짐 | cmd.exe 코드페이지 + UTF-8 경로 | bash에서 직접 실행 또는 `chcp 65001` |
| managed 스킬 프롬프트 미주입 | OpenClaw이 bundled 스킬만 자동 주입 | `TOOLS.md`에 수동 등록 |
| Scheduled Task "Ready" 즉시 종료 | gateway.cmd 인코딩 오류 | bash 기반 시작 스크립트 사용 |

## 0.7 모델 전환 (Gemini <-> Claude)

| 별칭 | 모델 ID |
|------|---------|
| gemini | `google/gemini-2.5-pro` |
| claude | `anthropic/claude-opus-4-6` |

```powershell
# Claude Opus로 전환
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\openclaw\switch-model.ps1" -Model claude

# Gemini로 전환
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\openclaw\switch-model.ps1" -Model gemini
```

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

## 1.2 시스템 불변조건

| 원칙 | 설명 |
|------|------|
| Risk-First | 고정 손절(-4%)은 어떤 상황에서도 작동 |
| TS 상향 전용 | 트레일링 스탑은 절대 하락 안 함 |
| ATR 배수 단방향 | 6.0→4.5→4.0→3.5→2.5→2.0 (복원 불가) |
| EMA adjust=False | 모든 EMA 계산에 적용 |

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

## 2.3 수정 불가 항목

```
- Score 가중치: (C/W-1)*2, LZ*0.8, recovery*1.2
- PurpleOK 임계값: 상승률 4%, 수렴률 7%, 거래대금 5억
- Zone 허용 범위: EMA60 × 0.995
- ATR 배수 단계: 6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0
- Trend Hold Filter 조건 (EMA20>EMA60 AND HH20>HH60 AND ATR유지)
- EMA adjust=False
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

## 3.6 백테스트

> **필독**: 백테스트 작업 전 반드시 `docs/BACKTEST_GUIDE.md` 참조

| 핵심 설정 | 값 |
|----------|-----|
| API 속도 | 초당 4.5회 (실전), 0.33회 (모의) |
| 병렬 워커 | 10~15개 권장 |
| 캐시 경로 | `data/backtest/v7_purple_3min/cache/` |

```powershell
# 기본 실행 (캐시 사용)
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --use-cache --parallel 15

# 데이터 수집 포함
"C:\Program Files\Python311\python.exe" -m scripts.backtest.v7_intraday.main --fetch --start 2025-12-01 --parallel 15
```

---

# Part 4: 참조

## 4.1 문서

| 문서 | 용도 |
|------|------|
| `docs/ARCHITECTURE.md` | **시스템 아키텍처** (모듈 구조, 데이터 흐름, 리팩토링 현황) |
| `docs/TECHNICAL_DOCUMENTATION.md` | 시스템 전체 상세 |
| `docs/BACKTEST_GUIDE.md` | **백테스트 필독** (API 제한, 병렬처리, 오류해결) |
| `docs/CHANGELOG.md` | 버전 히스토리 |
| `docs/DEPLOYMENT_GUIDE.md` | 배포 가이드 |
| `docs/OPENCLAW_GUIDE.md` | **OpenClaw 스킬 개발** (API 연동, 트러블슈팅) |

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
