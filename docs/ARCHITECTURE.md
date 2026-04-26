# K_stock_trading 시스템 아키텍처

> **버전**: V7.0 Purple-ReAbs (2026-01-27)
> **Phase 3 리팩토링 완료** | TradingEngine: 5,769줄 -> 4,904줄 (865줄 감소)

---

## 문서 목적

이 문서는 **시스템 전체 구조를 상세히 설명**합니다.

| 이 문서에서 다루는 내용 | CLAUDE.md에서 다루는 내용 |
|------------------------|---------------------------|
| 모듈별 역할과 책임 | 절대 규칙 / 금지 사항 |
| 데이터 흐름 다이어그램 | 운영 명령어 (배포, 테스트) |
| 리팩토링 현황 상세 | V7 신호/청산 조건 요약 |
| 클래스/메서드 설명 | 컨텍스트 관리 절차 |

**새 세션 시작 시**: `CLAUDE.md` -> 규칙 확인 후 -> 이 문서에서 구조 파악

---

**관련 문서**:
- [`CLAUDE.md`](../CLAUDE.md) - 개발 필수 규칙, 운영 명령어
- [`docs/TECHNICAL_DOCUMENTATION.md`](TECHNICAL_DOCUMENTATION.md) - 기술 상세

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [디렉토리 구조](#2-디렉토리-구조)
3. [핵심 모듈 설명](#3-핵심-모듈-설명)
4. [데이터 흐름](#4-데이터-흐름)
5. [전략별 아키텍처](#5-전략별-아키텍처)
6. [공통 인프라](#6-공통-인프라)
7. [리팩토링 진행 상황](#7-리팩토링-진행-상황)
8. [CLAUDE.md 불변 조건](#8-claudemd-불변-조건)

---

## 1. 시스템 개요

### 1.1 시스템 목적

K_stock_trading은 **키움증권 REST API**를 활용한 국내 주식 자동매매 시스템입니다.

| 항목 | 설명 |
|------|------|
| 플랫폼 | AWS Lightsail (Ubuntu) |
| 언어 | Python 3.11 |
| DB | PostgreSQL (Supabase) / SQLite (로컬) |
| 실시간 데이터 | 키움 WebSocket |
| 알림 | Telegram Bot |

### 1.2 이중 전략 지원

```
+-------------------+     +--------------------+
|  V6 SNIPER_TRAP   |     | V7 Purple-ReAbs    |
|  (레거시 전략)     |     | (신규 알림 전략)    |
+-------------------+     +--------------------+
         |                         |
         +-----------+-------------+
                     |
              TradingEngine
              (중앙 조율자)
```

| 전략 | 상태 | 용도 |
|------|------|------|
| V6 SNIPER_TRAP | 기본 비활성화 | 추세 추종 자동매매 |
| V7 Purple-ReAbs | 기본 활성화 | 재응축 구간 신호 알림 |

---

## 2. 디렉토리 구조

```
K_stock_trading/
├── src/
│   ├── main.py                    # 엔트리포인트
│   ├── api/                       # 키움 REST API 클라이언트
│   │   ├── client.py              # API 클라이언트 (Rate Limiter 포함)
│   │   ├── websocket.py           # WebSocket 클라이언트
│   │   ├── auth.py                # OAuth 인증
│   │   └── endpoints/
│   │       ├── order.py           # 주문 API
│   │       ├── market.py          # 시세 API
│   │       ├── account.py         # 계좌 API (KRX+NXT 통합)
│   │       └── condition.py       # 조건검색 API
│   │
│   ├── core/                      # 핵심 트레이딩 로직
│   │   ├── trading_engine.py      # 통합 거래 엔진 (4,904줄)
│   │   │
│   │   │   # Phase 1: 공용 라이브러리
│   │   ├── indicator_library.py   # 공용 지표 라이브러리
│   │   ├── constants.py           # 상수 중앙화
│   │   │
│   │   │   # Phase 2: 추상 클래스
│   │   ├── signals/
│   │   │   └── base_signal.py     # Signal 공통 인터페이스
│   │   ├── detectors/
│   │   │   └── base_detector.py   # Detector 공통 인터페이스
│   │   ├── exit/
│   │   │   └── base_exit.py       # Exit 공통 인터페이스
│   │   │
│   │   │   # Phase 3: TradingEngine 분리 모듈
│   │   ├── strategy_orchestrator.py   # 전략 조율자 (443줄)
│   │   ├── signal_processor.py        # 신호 큐/알림 처리 (420줄)
│   │   ├── exit_coordinator.py        # V6/V7 청산 조율 (572줄)
│   │   ├── position_sync_manager.py   # HTS 매매 감지 (650줄)
│   │   ├── v7_signal_coordinator.py   # V7 Dual-Pass 조율 (550줄)
│   │   │
│   │   │   # V6 모듈
│   │   ├── indicator.py           # V6 지표 (위임 패턴)
│   │   ├── signal_detector.py     # V6 SNIPER_TRAP 신호 탐지
│   │   ├── auto_screener.py       # V6 5필터 + Watchlist
│   │   ├── exit_manager.py        # 청산 실행
│   │   │
│   │   │   # V7 모듈
│   │   ├── indicator_purple.py    # V7 Purple 지표 (위임 패턴)
│   │   ├── signal_detector_purple.py  # V7 Dual-Pass 신호 탐지
│   │   ├── signal_pool.py         # V7 신호 Pool (TTL 관리)
│   │   ├── wave_harvest_exit.py   # V7 청산 전략
│   │   ├── watermark_manager.py   # V7 워터마크 관리
│   │   ├── missed_signal_tracker.py  # V7 놓친 신호 추적
│   │   │
│   │   │   # 공통 모듈
│   │   ├── risk_manager.py        # 리스크 관리
│   │   ├── order_executor.py      # 주문 실행
│   │   ├── position_manager.py    # 포지션 관리
│   │   ├── candle_builder.py      # 틱 → 분봉 변환
│   │   ├── realtime_data_manager.py
│   │   ├── subscription_manager.py
│   │   └── market_schedule.py
│   │
│   ├── database/                  # PostgreSQL/Supabase 연동
│   │   ├── connection.py          # DB 연결
│   │   ├── models.py              # ORM 모델
│   │   └── repository.py          # CRUD 레포지토리
│   │
│   ├── notification/              # 텔레그램 알림
│   │   ├── telegram.py            # 봇 클라이언트 (Circuit Breaker)
│   │   ├── notification_queue.py  # 비동기 알림 큐
│   │   └── templates.py           # 메시지 템플릿
│   │
│   └── utils/                     # 공용 유틸리티
│       ├── config.py              # 환경변수 설정
│       ├── logger.py              # 구조화 로깅
│       └── exceptions.py          # 예외 클래스
│
├── scripts/
│   ├── deploy/                    # 배포 스크립트 (PowerShell)
│   │   ├── hotfix.ps1
│   │   ├── check_logs.ps1
│   │   └── status.ps1
│   └── backtest/                  # 백테스트 스크립트
│
├── tests/                         # 단위 테스트 (266개)
│
├── docs/                          # 문서
│   ├── TECHNICAL_DOCUMENTATION.md # 기술 상세
│   ├── BACKTEST_GUIDE.md          # 백테스트 가이드
│   ├── ARCHITECTURE.md            # 이 문서
│   └── CHANGELOG.md               # 버전 히스토리
│
├── .claude/                       # Claude 컨텍스트
│   └── state/
│       └── work-context.json
│
└── CLAUDE.md                      # 개발 가이드 (필수 규칙)
```

---

## 3. 핵심 모듈 설명

### 3.1 TradingEngine (trading_engine.py)

**역할**: 자동매매 시스템의 **중앙 조율자**

**현재 규모**: 4,904줄 (Phase 3 리팩토링 후 865줄 감소)

```
+------------------------------------------------------------------+
|                        TradingEngine                              |
+------------------------------------------------------------------+
|  책임:                                                            |
|  - 컴포넌트 초기화 및 라이프사이클 관리                             |
|  - WebSocket 이벤트 핸들링                                         |
|  - 배경 태스크 조율 (V7SignalCoordinator, PositionSyncManager)     |
|  - 텔레그램 명령어 처리                                            |
+------------------------------------------------------------------+
|  위임 모듈:              |  담당 책임:                             |
|  - V7SignalCoordinator   |  V7 Dual-Pass 신호 탐지                |
|  - ExitCoordinator       |  V6/V7 청산 조건 체크                   |
|  - SignalProcessor       |  신호 큐 및 알림 처리                   |
|  - PositionSyncManager   |  HTS 매매 감지 및 동기화                |
+------------------------------------------------------------------+
```

**핵심 상태**:
```python
class EngineState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    WAITING_MARKET = "WAITING_MARKET"    # 장 시작 대기
    WAITING_HOLIDAY = "WAITING_HOLIDAY"  # 휴장일 대기
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
```

### 3.2 Phase 3 분리 모듈

#### 3.2.1 V7SignalCoordinator (v7_signal_coordinator.py)

**역할**: V7 Dual-Pass 신호 탐지 루프 관리

```python
@dataclass
class V7Callbacks:
    """TradingEngine과의 의존성을 콜백으로 분리"""
    get_candles: Callable[[str, Any], Any]
    is_candle_loaded: Callable[[str], bool]
    get_all_pool_stocks: Callable[[], List[Any]]
    is_market_open: Callable[[datetime], bool]
    enqueue_notification: Callable[..., bool]
    send_telegram: Callable[[str], Awaitable]
    # ... 기타 콜백

class V7SignalCoordinator:
    async def start(self, callbacks: V7Callbacks) -> None
    async def stop(self) -> None
    async def ensure_candle_loaded(self, stock_code: str) -> bool
```

**주요 기능**:
- Pre-Check / Confirm-Check 타이밍 관리
- 병렬 조건 체크 (asyncio.gather)
- 신호 알림 큐 처리
- 봉 단위 쿨다운 관리

#### 3.2.2 ExitCoordinator (exit_coordinator.py)

**역할**: V6/V7 청산 조건 통합 체크

```python
class ExitCoordinator:
    def check_v6_exit(self, stock_code: str, ...) -> ExitCheckResult
    def check_v7_exit(self, stock_code: str, df: pd.DataFrame) -> ExitCheckResult
    def initialize_v7_state(self, stock_code: str, entry_price: int) -> None
```

**주요 기능**:
- V7 Exit State 중앙 관리
- Hard Stop / ATR TS / Max Holding 체크
- Trend Hold Filter 적용

#### 3.2.3 PositionSyncManager (position_sync_manager.py)

**역할**: HTS 매매 감지 및 포지션 동기화

```python
class PositionSyncManager:
    async def reconcile_with_api(self, callbacks: SyncCallbacks) -> None
    async def sync_positions(self, callbacks: SyncCallbacks) -> None
    async def verify_tier1_consistency(self, callbacks: SyncCallbacks) -> None
```

**주요 기능**:
- API 잔고와 내부 상태 비교
- HTS 매수 자동 감지 및 등록
- HTS 매도 자동 감지 및 청산
- Tier 1 일관성 검증

#### 3.2.4 SignalProcessor (signal_processor.py)

**역할**: SNIPER_TRAP 신호 큐 및 알림 처리

```python
class SignalProcessor:
    async def process_signal(self, signal: Signal, callbacks: SignalProcessCallbacks) -> SignalProcessResult
    async def process_queued_signals(self, callbacks: SignalProcessCallbacks) -> None
```

### 3.3 IndicatorLibrary (indicator_library.py)

**역할**: 모든 전략에서 공통 사용하는 **기술적 지표 라이브러리**

```python
from src.core.indicator_library import IndicatorLibrary

# EMA (adjust=False 강제)
ema3 = IndicatorLibrary.ema(df['close'], span=3)

# ATR (Wilder's RMA)
atr = IndicatorLibrary.atr(df['high'], df['low'], df['close'], period=10)

# 상향 돌파
crossup = IndicatorLibrary.crossup(df['close'], ema3)
```

**주요 메서드**:

| 카테고리 | 메서드 | 설명 |
|----------|--------|------|
| 이동평균 | `ema()`, `sma()`, `rma()` | EMA, SMA, Wilder's RMA |
| 변동성 | `true_range()`, `atr()` | TR, ATR |
| 최고/최저 | `highest_high()`, `lowest_low()`, `h1l1()`, `h2l2()` | N봉 극값 |
| 돌파 | `crossup()`, `crossdown()` | 상향/하향 돌파 |
| 캔들 | `is_bullish()`, `candle_body()` | 양봉/음봉, 몸통 크기 |

### 3.4 constants.py

**역할**: 모든 전략 상수의 **중앙 관리**

```python
from src.core.constants import (
    EMAConstants,      # EMA 기간 (3, 20, 60, 200)
    ATRConstants,      # ATR 배수 (6.0 → 2.0)
    PurpleConstants,   # V7 Purple 가중치/임계값
    WaveHarvestConstants,  # V7 청산 설정
)

# 사용 예시
span = EMAConstants.LONG  # 60
multiplier = ATRConstants.MULT_INITIAL  # 6.0
min_rise = PurpleConstants.MIN_RISE_PCT  # 0.04 (4%)
```

### 3.5 SignalPool (signal_pool.py)

**역할**: V7 신호 탐지 대상 종목 관리

```
+--------------------------------------------------+
|                   SignalPool                      |
|  (V6의 3단계 Pool → 1단계 통합)                    |
+--------------------------------------------------+
|  - TTL 기반 자동 만료 (24시간)                     |
|  - 크기 제한 (10,000개)                           |
|  - Thread-safe (RLock)                            |
|  - 신호 쿨다운 관리 (봉 단위)                      |
+--------------------------------------------------+
```

### 3.6 WaveHarvestExit (wave_harvest_exit.py)

**역할**: V7 추세 추종용 파동 수확 청산 시스템

**핵심 원칙**:
- BasePrice = `Highest(High, 20)` - 현재가 기준 금지
- TrailingStop = `BasePrice - ATR x Multiplier`
- 스탑은 **상향 단방향만** (하락 금지)
- ATR 배수는 **단방향 축소만** (재증가 금지)

**ATR 배수 단계**:
```
6.0 (초기) → 4.5 (구조 경고) → 4.0 (R>=1) → 3.5 (R>=2) → 2.5 (R>=3) → 2.0 (R>=5)
```

---

## 4. 데이터 흐름

### 4.1 전체 흐름

```
+------------------+     +------------------+     +------------------+
|   조건검색 신호   | --> |    SignalPool    | --> |   Dual-Pass      |
|   (WebSocket)    |     |    등록          |     |   신호 탐지      |
+------------------+     +------------------+     +------------------+
                                                          |
                              +----------------------------+
                              |
                    +---------v---------+
                    |   신호 발생?       |
                    +---------+---------+
                              |
              +---------------+---------------+
              | AUTO_UNIVERSE                 | SIGNAL_ALERT
              v                               v
     +------------------+            +------------------+
     |   자동 매수       |            |   알림 발송       |
     +------------------+            +------------------+
              |
              v
     +------------------+
     |   WaveHarvest    |
     |   청산 관리       |
     +------------------+
```

### 4.2 V7 Dual-Pass 신호 탐지

```
+------------------------------------------------------------------+
|                V7SignalCoordinator (Dual-Pass)                    |
+------------------------------------------------------------------+
|                                                                    |
|  [1. Pre-Check] 봉 완성 30초 전                                   |
|  +---------------------------------------------------------+      |
|  | SignalPool 전체 종목 병렬 체크                            |      |
|  | PurpleOK + Trend + Zone + ReAbsStart (4/5 통과)          |      |
|  | → 후보 종목 선별                                         |      |
|  +---------------------------------------------------------+      |
|                                                                    |
|  [2. Confirm-Check] 봉 완성 직후 5초 이내                          |
|  +---------------------------------------------------------+      |
|  | Pre-Check 후보 + Late-Arriving 종목 (최근 30초)           |      |
|  | 5개 조건 모두 충족 + Trigger 확인                         |      |
|  | 봉 단위 쿨다운 체크                                       |      |
|  | → 신호 확정 및 알림                                       |      |
|  +---------------------------------------------------------+      |
|                                                                    |
+------------------------------------------------------------------+
```

### 4.3 청산 흐름

```
+------------------+
| 3분봉 완성        |
+------------------+
         |
         v
+------------------+
| ExitCoordinator  |
| 보유 포지션 순회   |
+------------------+
         |
         v
+----------------------------------+
|      청산 조건 체크 (우선순위)     |
|                                  |
|  1. Hard Stop: bar_low <= -4%    |
|  2. ATR TS: close <= trailing    |
|  3. Max Holding: 60일 초과        |
+----------------------------------+
         |
    +----+----+
    |         |
 청산      유지
    |         |
    v         v
+--------+  +----------+
|매도 주문|  |TS 갱신    |
+--------+  |(상향만)   |
            +----------+
```

---

## 5. 전략별 아키텍처

### 5.1 V6 SNIPER_TRAP vs V7 Purple-ReAbs

| 항목 | V6 SNIPER_TRAP | V7 Purple-ReAbs |
|------|----------------|-----------------|
| **신호 탐지** | `SignalDetector` | `PurpleSignalDetector` |
| **청산 전략** | `ExitManager` | `WaveHarvestExit` |
| **데이터 구조** | `Watchlist → Candidate → Active` | `SignalPool` (1단계) |
| **신호 조건** | TrendFilter + Zone + Meaningful | PurpleOK + Trend + Zone + ReAbsStart + Trigger |
| **ATR 배수** | 6.0 / 4.5 (고정) | 6.0 → 2.0 (R-Multiple 기반) |
| **Trend Hold** | 미적용 | EMA20>EMA60 AND HH20>=HH60 AND ATR유지 |

### 5.2 V7 신호 조건 상세

```python
Signal = PurpleOK AND Trend AND Zone AND ReAbsStart AND Trigger

# 각 조건 정의
PurpleOK = (H1/L1-1) >= 4% AND (H2/L2-1) <= 7% AND M >= 5억
Trend    = EMA60 > EMA60[3]
Zone     = Close >= EMA60 x 0.995
ReAbsStart = Score > Score[1]
Trigger  = CrossUp(Close, EMA3) AND Close > Open
```

### 5.3 V7 청산 조건

```python
# R-Multiple
R = (현재가 - 진입가) / (진입가 x 0.04)

# 트레일링 스탑
BasePrice = Highest(High, 20)
TrailingStop = max(prev_stop, BasePrice - ATR(10) x Multiplier)

# Trend Hold Filter (청산 차단)
TrendHold = EMA20 > EMA60 AND HighestHigh(20) >= HighestHigh(60) AND ATR >= ATR_5ago * 0.8

# 청산 조건
Exit = NOT TrendHold AND Close < TrailingStop
```

---

## 6. 공통 인프라

### 6.1 API 클라이언트

```
+------------------+
|  KiwoomAPIClient |
+------------------+
        |
        +-- Rate Limiter (초당 4.5회/실전, 0.33회/모의)
        |
        +-- OAuth 인증 (자동 갱신)
        |
        +-- 재시도 로직 (3회)
```

### 6.2 WebSocket

```
+------------------+
| KiwoomWebSocket  |
+------------------+
        |
        +-- 조건검색 (CNSRREQ)
        |
        +-- 실시간 시세 (REGSUB)
        |
        +-- 재연결 전략:
            - Phase 1: 빠른 재연결 (5회, 지수 백오프)
            - Phase 2: 느린 재연결 (5분 간격, 무한)
```

### 6.3 알림 시스템

```
+------------------+     +------------------+     +------------------+
| NotificationQueue| --> | TelegramBot      | --> | 사용자           |
| (비동기 큐)       |     | (Circuit Breaker)|     |                  |
+------------------+     +------------------+     +------------------+

- 큐 크기: 1,000개
- 쿨다운: 300초 (같은 종목)
- Circuit Breaker: 5회 실패 시 300초 차단
```

### 6.4 데이터베이스

```
+------------------+
|   PostgreSQL     |
|   (Supabase)     |
+------------------+
        |
        +-- trades (거래 내역)
        +-- orders (주문 내역)
        +-- signals (신호 기록)
        +-- daily_stats (일일 통계)
```

---

## 7. 리팩토링 진행 상황

### 7.1 Phase 1 완료 (2026-01-26)

| 작업 | 파일 | 줄 수 |
|------|------|------|
| 공용 지표 라이브러리 | `indicator_library.py` | 496줄 |
| 상수 중앙화 | `constants.py` | 164줄 |
| V6 Indicator 위임 | `indicator.py` | 수정 |
| V7 PurpleIndicator 위임 | `indicator_purple.py` | 수정 |

### 7.2 Phase 2 완료 (2026-01-26)

| 작업 | 파일 | 줄 수 |
|------|------|------|
| Signal 공통 인터페이스 | `signals/base_signal.py` | 191줄 |
| Detector 공통 인터페이스 | `detectors/base_detector.py` | 288줄 |
| Exit 공통 인터페이스 | `exit/base_exit.py` | 365줄 |

### 7.3 Phase 3 완료 (2026-01-27)

| 작업 | 파일 | 줄 수 | TradingEngine 감소 |
|------|------|------|------------------|
| 전략 조율자 | `strategy_orchestrator.py` | 443줄 | - (위임 미적용) |
| 신호 처리기 | `signal_processor.py` | 420줄 | ~100줄 |
| 청산 조율자 | `exit_coordinator.py` | 572줄 | ~100줄 |
| 포지션 동기화 | `position_sync_manager.py` | 650줄 | 262줄 |
| V7 신호 조율자 | `v7_signal_coordinator.py` | 550줄 | 322줄 |
| deprecated 정리 | - | - | 180줄 |
| **합계** | - | **2,635줄** | **865줄** |

### 7.4 TradingEngine 줄 수 변화

```
초기:              5,769줄
Phase 3 완료 후:   4,904줄
────────────────────────────
총 감소:            865줄 (15.0%)
```

### 7.5 테스트 현황

| 항목 | 수치 |
|------|------|
| 총 테스트 | 266개 |
| 통과 | 265개 (99.6%) |
| 실패 | 1개 (기존 watermark_manager) |

### 7.6 Phase 3에서 제거된 메서드

| 메서드 | 줄 수 | 대체 |
|--------|------|------|
| `_check_position_exit_v7` | 140줄 | ExitCoordinator |
| `_send_signal_alert_notification` | 10줄 | SignalProcessor |
| `_enqueue_signal` | 15줄 | SignalProcessor |
| `_execute_queued_signal` | 11줄 | SignalProcessor |
| `_v7_dual_pass_loop` | 46줄 | V7SignalCoordinator |
| `_v7_run_pre_check` | 92줄 | V7SignalCoordinator |
| `_v7_run_confirm_check` | 171줄 | V7SignalCoordinator |
| `_v7_send_purple_signal` | 36줄 | V7SignalCoordinator |
| `_v7_notification_loop` | 28줄 | V7SignalCoordinator |
| `_reconcile_with_api_balance` | 100줄 | PositionSyncManager |
| `_sync_positions` | 287줄 | PositionSyncManager |

---

## 8. CLAUDE.md 불변 조건

> 다음 항목들은 전략 무결성 유지를 위해 **수정 금지**

### 8.1 EMA 계산

```python
# 모든 EMA 계산에 adjust=False 필수
series.ewm(span=span, adjust=False).mean()
```

### 8.2 V7 Score 가중치

```python
PRICE_VWAP_MULT = 2.0   # (C/W - 1) x 2
FUND_LZ_MULT = 0.8      # LZ x 0.8
RECOVERY_MULT = 1.2     # recovery x 1.2
```

### 8.3 V7 PurpleOK 임계값

```python
MIN_RISE_PCT = 0.04          # H1/L1 - 1 >= 4%
MAX_CONVERGENCE_PCT = 0.07   # H2/L2 - 1 <= 7%
MIN_BAR_VALUE = 500_000_000  # M >= 5억
```

### 8.4 V7 Zone 허용 범위

```python
ZONE_EMA60_TOLERANCE = 0.005  # C >= EMA60 x 0.995
```

### 8.5 V7 ATR 배수 단계

```python
# 단방향 축소만 (복원 불가)
6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0
```

### 8.6 고정 손절

```python
SAFETY_STOP_RATE = -0.04  # -4% 고정 손절
```

### 8.7 Trend Hold Filter 조건

```python
TrendHold = EMA20 > EMA60 AND HighestHigh(20) >= HighestHigh(60) AND ATR_current >= ATR_past * 0.8

# ATR 조건: 현재 ATR(10)이 5봉 전 ATR(10)의 80% 이상 (변동성 유지 확인)
# - 안전한 방향: Trend Hold가 더 어려워짐 → 더 많이 청산 (Risk-First)
# - wave_harvest_exit.py:455-461 참조
```

---

*문서 업데이트: 2026-02-04*
*시스템 버전: V7.0 Purple-ReAbs (Phase 6 + 코드 리뷰 P1-P3 수정)*
*Phase 6 리팩토링 완료, 코드 리뷰 17건 수정*
