# K_stock_trading 시스템 기술문서

> **버전**: V7.0 Purple-ReAbs (2026-01-27)
> **시스템명**: K_stock_trading - 키움증권 REST API 국내 주식 자동매매 시스템
> **전략**: V7 Purple-ReAbs (메인) + V6 SNIPER_TRAP (레거시)

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [핵심 모듈 상세](#2-핵심-모듈-상세)
3. [트레이딩 흐름](#3-트레이딩-흐름)
4. [Pool 구조](#4-pool-구조-v62-b)
5. [6단계 스크리닝 필터](#5-6단계-스크리닝-필터)
6. [지표 계산](#6-지표-계산)
7. [WebSocket 및 실시간 데이터](#7-websocket-및-실시간-데이터)
8. [데이터베이스](#8-데이터베이스)
9. [텔레그램 명령어](#9-텔레그램-명령어)
10. [환경변수](#10-환경변수)
11. [배포 및 운영](#11-배포-및-운영)
12. [V7 Purple-ReAbs 전략](#12-v7-purple-reabs-전략)

---

## 1. 시스템 개요

### 1.1 시스템 목적

K_stock_trading은 키움증권 REST API를 활용한 국내 주식 자동매매 시스템입니다.
V7 Purple-ReAbs 전략(메인)과 V6 SNIPER_TRAP 전략(레거시)을 지원하며,
조건검색 신호를 수신하고 필터링을 거쳐 자동으로 매수/매도를 실행합니다.

**이중 전략 지원 (V7.0)**:
- **V7 Purple-ReAbs**: 재응축 구간 신호 전략 (기본 활성화)
- **V6 SNIPER_TRAP**: 레거시 전략 (기본 비활성화)

```
V7_PURPLE_ENABLED=true   # V7 Purple-ReAbs 활성화 (기본값)
SNIPER_TRAP_ENABLED=false  # V6 SNIPER_TRAP 비활성화 (기본값)
```

### 1.2 아키텍처 다이어그램

```
+------------------------------------------------------------------+
|                     K_stock_trading System                        |
+------------------------------------------------------------------+
|                                                                    |
|  +------------------+     +-------------------+                    |
|  |   Telegram Bot   |<--->|  TradingEngine    |<-- 중앙 조율자    |
|  +------------------+     +-------------------+                    |
|         ^                         |                                |
|         |                         v                                |
|  +------+--------+    +-----------+-----------+                    |
|  | User Commands |    |                       |                    |
|  +---------------+    v                       v                    |
|              +----------------+    +------------------+            |
|              | SignalDetector |    |   ExitManager    |            |
|              +----------------+    +------------------+            |
|                      |                       |                     |
|                      v                       v                     |
|              +----------------+    +------------------+            |
|              |  RiskManager   |<-->| PositionManager  |            |
|              +----------------+    +------------------+            |
|                      |                       |                     |
|                      v                       v                     |
|              +----------------+    +------------------+            |
|              | OrderExecutor  |--->|   Database (PG)  |            |
|              +----------------+    +------------------+            |
|                      |                                             |
|                      v                                             |
|  +-------------------------------------------------------+        |
|  |                  Kiwoom REST API                       |        |
|  |  +-------------+  +------------+  +--------------+     |        |
|  |  | Order API   |  | Market API |  | Account API  |     |        |
|  |  +-------------+  +------------+  +--------------+     |        |
|  +-------------------------------------------------------+        |
|                      ^                                             |
|                      |                                             |
|  +-------------------------------------------------------+        |
|  |                 WebSocket (실시간)                      |        |
|  |  +-------------+  +--------------+  +-------------+    |        |
|  |  | CNSRREQ     |  | Tick Data    |  | Heartbeat   |    |        |
|  |  | (조건검색)  |  | (체결가)     |  | (PING/PONG) |    |        |
|  |  +-------------+  +--------------+  +-------------+    |        |
|  +-------------------------------------------------------+        |
+------------------------------------------------------------------+
```

### 1.3 데이터 흐름

```
실시간 틱 데이터 (WebSocket)
       |
       v
CandleBuilder (틱 -> 3분봉)
       |
       v
SignalDetector (SNIPER_TRAP 신호 탐지)
       |
       v
RiskManager (진입 가능 여부 체크)
       |
       v
OrderExecutor (주문 실행)
       |
       v
PositionManager (포지션 모니터링)
       |
       v
ExitManager (청산 조건 체크)
```

### 1.4 파일 구조

```
K_stock_trading/
+-- src/
|   +-- main.py                    # 엔트리포인트
|   +-- core/                      # 핵심 비즈니스 로직
|   |   +-- trading_engine.py      # 통합 거래 엔진 (4,904줄, Phase 3 위임)
|   |   +-- # Phase 3 위임 모듈 (V7.0)
|   |   +-- v7_signal_coordinator.py    # V7 신호 조율 (Dual-Pass)
|   |   +-- exit_coordinator.py         # 청산 조율 (V6/V7 통합)
|   |   +-- position_sync_manager.py    # 포지션 동기화
|   |   +-- signal_processor.py         # 신호 전처리
|   |   +-- strategy_orchestrator.py    # 전략 오케스트레이션
|   |   +-- # V7 전략 모듈
|   |   +-- signal_detector_purple.py   # V7 Purple-ReAbs 신호 탐지
|   |   +-- wave_harvest_exit.py        # V7 Wave Harvest 청산
|   |   +-- signal_pool.py              # V7 신호 풀 관리
|   |   +-- indicator_library.py        # 지표 라이브러리 (Phase 1)
|   |   +-- constants.py                # 상수 정의 (Phase 1)
|   |   +-- # V6 레거시 모듈
|   |   +-- signal_detector.py          # V6 SNIPER_TRAP 신호 탐지
|   |   +-- auto_screener.py            # 5필터 스크리닝 + Watchlist
|   |   +-- risk_manager.py             # 리스크 관리 + 청산 조건
|   |   +-- exit_manager.py             # 청산 실행
|   |   +-- order_executor.py           # 주문 실행 + 쿨다운
|   |   +-- position_manager.py         # 포지션 관리
|   |   +-- indicator.py                # 기술적 지표 (레거시)
|   |   +-- candle_builder.py           # 캔들 생성
|   |   +-- realtime_data_manager.py
|   |   +-- subscription_manager.py
|   |   +-- market_schedule.py
|   |   +-- universe.py
|   |   +-- atr_alert_manager.py
|   +-- api/
|   |   +-- client.py              # REST 클라이언트
|   |   +-- websocket.py           # WebSocket 클라이언트
|   |   +-- auth.py                # OAuth 인증
|   |   +-- endpoints/
|   |       +-- order.py           # 주문 API
|   |       +-- market.py          # 시세 API
|   |       +-- account.py         # 계좌 API (KRX+NXT 통합 조회)
|   |       +-- condition.py       # 조건검색 API
|   +-- database/
|   |   +-- connection.py          # DB 연결 (PostgreSQL/SQLite)
|   |   +-- models.py              # ORM 모델
|   |   +-- repository.py          # CRUD 레포지토리
|   +-- notification/
|   |   +-- telegram.py            # 텔레그램 봇
|   |   +-- templates.py           # 메시지 템플릿
|   +-- utils/
|       +-- config.py              # 환경변수 설정
|       +-- logger.py              # 구조화 로깅
|       +-- exceptions.py          # 예외 클래스
+-- scripts/
|   +-- deploy/                    # 배포 스크립트 (PowerShell)
|   +-- server/                    # 서버 설정 (Linux)
+-- docs/                          # 문서
+-- .env                           # 환경변수 (git 제외)
+-- CLAUDE.md                      # 개발 가이드
```

---

## 2. 핵심 모듈 상세

### 2.1 TradingEngine (trading_engine.py)

**역할**: 자동매매 시스템의 중앙 조율자

**핵심 클래스**: `TradingEngine` (4,904줄)

**V7.0 Phase 3 리팩토링**:
TradingEngine은 Phase 3에서 865줄의 로직을 5개 전문 모듈로 위임하여 코드량을 5,769줄에서 4,904줄로 축소:

| 위임 모듈 | 역할 |
|----------|------|
| `V7SignalCoordinator` | V7 Dual-Pass 신호 조율 |
| `ExitCoordinator` | V6/V7 통합 청산 조율 |
| `PositionSyncManager` | 포지션 동기화 |
| `SignalProcessor` | 신호 전처리 |
| `StrategyOrchestrator` | 전략 오케스트레이션 |

**주요 책임**:
- 모든 컴포넌트 통합 및 라이프사이클 관리
- WebSocket 이벤트 처리 (조건검색 신호, 틱 데이터)
- 봉 완성 시 청산 조건 체크 (ExitCoordinator 위임)
- V7 Dual-Pass 신호 탐지 (V7SignalCoordinator 위임)
- 텔레그램 명령어 핸들러 연결
- 시스템 상태 관리

**엔진 상태 (EngineState)**:
```python
class EngineState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    WAITING_MARKET = "WAITING_MARKET"    # 장 시작 대기 중
    WAITING_HOLIDAY = "WAITING_HOLIDAY"  # 휴장일 대기 중
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
```

**핵심 메서드**:
| 메서드 | 설명 |
|--------|------|
| `start()` | 엔진 시작, WebSocket 연결, 포지션 복구 |
| `stop()` | 엔진 중지, 리소스 정리 |
| `_on_condition_signal_v31()` | 조건검색 신호 수신 처리 |
| `_on_candle_complete()` | 3분봉 완성 시 청산 체크 |
| `_restore_positions_from_db()` | 재시작 시 포지션 복구 |

**상태 플래그**:
```python
self._startup_complete: bool = False    # 시작 완료 (신호 처리 차단용)
self._global_lock: bool = False         # 시장 급락 시 신규 매수 중단
self._vi_cooldown_stocks: Dict          # VI 쿨다운 종목
self._signal_queue: Dict                # 쿨다운 중 신호 저장
```

### 2.2 SignalDetector (signal_detector.py)

**역할**: SNIPER_TRAP 매수 신호 탐지

**핵심 클래스**: `SignalDetector`

**SNIPER_TRAP 진입 조건** (V6.2-A):

```python
# 1. TrendFilter: 추세 필터
# C > EMA200 AND EMA60 > EMA60(5)
trend_filter = (
    latest["close"] > latest["ema200"] and
    latest["ema60"] > ema60_5ago
)

# 2. Zone: 헌팅존 (EMA20~EMA60 사이)
# L <= M20 && C >= M60
zone_ok = (
    latest["low"] <= latest["ema20"] and
    latest["close"] >= latest["ema60"]
)

# 3. Meaningful: 의미있는 캔들
# CrossUp(C, M3) && C > O && V >= V(1)
meaningful = (
    crossup_m3 and      # 종가가 EMA3 상향돌파
    is_bullish and      # 양봉
    volume_increase     # 거래량 증가
)

# 4. BodySize: 캔들 몸통 크기
# (C - O) / O * 100 >= 0.3
body_size_ok = body_size_pct >= 0.3

# 5. TimeFilter: 시간 필터 (V6.2-D 업데이트)
# 일반 종목: 09:30 이후
# 52주 고점 근접 종목 (>= 90%): 09:03 이후 (조기 신호)
time_filter = current_time >= time(9, 30)  # override_time_filter=True 시 09:03
```

**V6.2-D 조기 신호 시스템 (52주 고점 근접 종목)**:
```python
# 52주 고점 대비 비율 계산
high_52w_ratio = current_price / high_52w_price

# 조기 신호 조건
if high_52w_ratio >= 0.90:  # NEAR_52W_HIGH_RATIO
    override_time_filter = True  # 09:03 이후 신호 허용
else:
    override_time_filter = False  # 일반 09:30 이후
```

| 시간대 | 52주 고점 90% 이상 | 일반 종목 |
|--------|-------------------|----------|
| 09:00~09:03 | X (봉 미완성) | X |
| 09:03~09:30 | **O (조기 신호)** | X |
| 09:30 이후 | O | O |

**상수 정의**:
```python
EMA_SHORT = 3      # 단기 EMA
EMA_MID = 20       # 중기 EMA
EMA_LONG = 60      # 장기 EMA
EMA_TREND = 200    # 추세 EMA
MIN_CANDLES = 205  # EMA200 정확도를 위한 최소 캔들 수
MIN_BODY_SIZE = 0.3  # 최소 캔들 몸통 (%)
```

**신호 타입**:
```python
class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"

class StrategyType(str, Enum):
    SNIPER_TRAP = "SNIPER_TRAP"      # V6.2-Q: 유일한 전략
```

### 2.3 RiskManager (risk_manager.py)

**역할**: 리스크 관리 및 청산 조건 판정

**핵심 클래스**: `RiskManager`

**V6.2-A 청산 우선순위** (3단계):

```
1. Hard Stop (고정 손절): bar_low <= entry × 0.96 (-4%)
2. TS Exit (ATR 트레일링 스탑): close <= trailing_stop
3. Max Holding (최대 보유일): 60일 초과
```

**V6.2-E NXT 시장조작 방어** (Hard Stop 적용 전):
```
Layer 1: 장 초반 보호 (09:00~09:01)
  - bar_low 손절 비활성화, current_price 손절만 유지

Layer 2: 극단값 필터
  - bar_low < entry × 0.85 (-15%) 시 손절 조건에서 제외
  - NXT 장전 조작으로 인한 허위 bar_low 무시
```

**청산 조건 체크 메서드**:
```python
def check_exit_v62a(
    self,
    stock_code: str,
    bar_low: int,
    close: int
) -> Optional[ExitReason]:
    """
    V6.2-A 청산 조건 체크

    Returns:
        ExitReason or None (청산 조건 미충족 시)
    """
```

**ExitReason Enum**:
```python
class ExitReason(str, Enum):
    HARD_STOP = "HARD_STOP"           # -4% 고정 손절
    TRAILING_STOP = "TRAILING_STOP"   # ATR TS 청산
    MAX_HOLDING = "MAX_HOLDING"       # 60일 보유
    MANUAL = "MANUAL"                 # 수동 청산
```

**Structure Warning 시스템**:
```python
@dataclass
class StructureWarning:
    """구조 경고 상태 추적"""
    below_ema9_count: int = 0    # EMA9 하회 봉 수
    below_vwap_count: int = 0    # VWAP(HLC3) 하회 봉 수

    @property
    def is_warning(self) -> bool:
        """2봉 연속 하회 시 경고"""
        return self.below_ema9_count >= 2 or self.below_vwap_count >= 2
```

**ATR 배수 선택**:
```python
def get_ts_multiplier(self, base: float = 6.0, tight: float = 4.5) -> float:
    """
    Structure Warning 시 배수 조정
    - 정상: 6.0
    - 경고: 4.5 (타이트닝)
    """
    if self.structure_warning and self.structure_warning.is_warning:
        return tight
    return base
```

**PositionRisk 데이터 클래스**:
```python
@dataclass
class PositionRisk:
    stock_code: str
    stock_name: str
    entry_price: int
    current_price: int
    quantity: int
    entry_time: datetime
    trailing_stop: int              # ATR 트레일링 스탑 가격
    structure_warning: Optional[StructureWarning]
    is_partial_exit: bool = False   # 분할 익절 완료 여부
    entry_atr: float = 0.0          # V6.2-I: 매수 시점 ATR 값 (TS 계산용)
```

**청산 후 블랙리스트 등록** (V6.2-Q Patch 2):
```python
def on_exit(self, stock_code: str, exit_reason: str) -> None:
    """청산 시 블랙리스트 등록 (당일 재매수 방지)"""
    # 손절 유형 시 블랙리스트 등록
    exit_types_for_blacklist = [
        "HARD_STOP",       # -4% 고정 손절
        "BREAKEVEN_STOP",  # 본전 손절 (레거시)
        "TECHNICAL_STOP",  # 기술적 손절 (레거시)
        "TRAILING_STOP",   # V6.2-Q Patch 2: ATR TS 청산 추가
    ]
```

### 2.4 ExitManager (exit_manager.py)

**역할**: 청산 로직 실행

**핵심 클래스**: `ExitManager`

**상수 정의**:
```python
EXECUTION_WAIT_SECONDS = 5.0   # 체결 대기 시간
EXECUTION_POLL_INTERVAL = 0.5  # 폴링 간격
```

**ATR 트레일링 스탑 계산**:
```python
def init_trailing_stop(
    self,
    stock_code: str,
    entry_price: int,
    current_atr: float,
    multiplier: float
) -> int:
    """
    진입 즉시 TS 초기화

    수식: trailing_stop = close - ATR(10) × multiplier
    """
    trailing_stop = int(entry_price - current_atr * multiplier)
    return trailing_stop

def update_trailing_stop(
    self,
    stock_code: str,
    current_price: int,
    current_atr: float,
    multiplier: float
) -> int:
    """
    3분봉 완성 시 TS 갱신 (상향만)

    수식: new_ts = max(현재값, close - ATR(10) × 배수)
    """
```

**청산 실행**:
```python
async def execute_full_sell(
    self,
    stock_code: str,
    exit_reason: ExitReason,
    current_price: int
) -> bool:
    """전량 매도 실행"""
```

### 2.5 OrderExecutor (order_executor.py)

**역할**: 매수 주문 실행 및 쿨다운 관리

**핵심 클래스**: `OrderExecutor`

**상수 정의**:
```python
class TradingConstants:
    EXECUTION_WAIT_SECONDS = 10      # 체결 대기 (호가 급변 대응)
    EXECUTION_POLL_INTERVAL = 0.5    # 폴링 간격
    PARTIAL_FILL_MAX_RETRIES = 2     # 미체결 재시도
    PARTIAL_FILL_RETRY_DELAY = 0.5   # 재시도 대기
```

**4중 Lock 구조**:
```
1. 시스템 쿨다운: 마지막 매수 후 15초
2. 종목 쿨다운: 종목별 VI 쿨다운
3. 주문 Lock: 종목별 asyncio.Lock
4. Double-Check: Lock 획득 후 포지션 재확인
```

**매수 실행 흐름**:
```python
async def execute_buy_order(self, signal: Signal) -> bool:
    stock_code = signal.stock_code
    lock = self._get_order_lock(stock_code)

    async with lock:
        # 1. Lock 획득 후 상태 재확인 (Double-Check)
        if self._position_manager.has_position(stock_code):
            return False

        # 2. 주문 가능 금액 조회
        balance = await self._account_api.get_balance()

        # 3. 매수 금액 계산 (총 평가금액 × buy_amount_ratio)
        buy_amount = int(total_eval * self._settings.buy_amount_ratio)

        # 4. 시장가 매수 주문
        result = await self._order_api.buy(
            stock_code=stock_code,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )

        # 5. 체결 대기 및 확인
        # 6. 포지션 등록 및 DB 저장
        # 7. 쿨다운 시작
```

**신호 큐 (V6.2-A, V6.2-Q Patch 2 개선)**:
```python
# 쿨다운 중 발생한 신호 저장
self._signal_queue: Dict[str, dict] = {}
self._signal_queue_max_age_seconds = 20.0  # 신호 유효 시간

# 쿨다운 해제 후 자동 처리
async def _schedule_signal_queue_processing(self):
    wait_seconds = self._settings.buy_cooldown_seconds + 0.5
    await asyncio.sleep(wait_seconds)
    await self._on_cooldown_expired_callback()
```

**V6.2-Q Patch 2 개선사항**:
- **만료 신호 정리**: 쿨다운 중에도 만료된 신호 계속 정리 (`break` -> `continue`)
- **SIGNAL_ALERT 모드 대응**: 큐 신호 처리 시 자동매수 대신 알림 발송
```python
# _execute_queued_signal() 시작 부분
if self._settings.trading_mode == TradingMode.SIGNAL_ALERT:
    await self._send_signal_alert(signal)
    return  # 자동매수 스킵
```

### 2.6 PositionManager (position_manager.py)

**역할**: 포지션 상태 추적 및 관리

**핵심 클래스**: `PositionManager`

**Position 데이터 클래스**:
```python
@dataclass
class Position:
    stock_code: str
    stock_name: str
    strategy: StrategyType
    status: PositionStatus
    entry_source: EntrySource

    # 진입 정보
    entry_price: int
    quantity: int
    entry_time: datetime
    entry_order_no: str = ""

    # 실시간 정보
    current_price: int = 0
    highest_price: int = 0
    lowest_price: int = 0

    # 청산 정보
    exit_price: int = 0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""

    # 분할 익절 상태
    is_partial_exit: bool = False
    highest_price_after_partial: int = 0
```

**PositionStatus Enum**:
```python
class PositionStatus(str, Enum):
    PENDING = "PENDING"    # 주문 대기
    OPEN = "OPEN"          # 보유 중
    CLOSING = "CLOSING"    # 청산 중
    CLOSED = "CLOSED"      # 청산 완료
```

**EntrySource Enum**:
```python
class EntrySource(str, Enum):
    MANUAL = "MANUAL"      # /buy 명령어 수동 매수
    SYSTEM = "SYSTEM"      # /add 후 신호 발생 자동 매수
    HTS = "HTS"            # HTS 직접 매수 (동기화로 감지)
    RESTORED = "RESTORED"  # 시스템 재시작 시 복구
```

**핵심 메서드**:
```python
async def open_position(...) -> Position:
    """포지션 생성 (중복 방지)"""
    if stock_code in self._positions:
        raise ValueError(f"이미 포지션이 존재합니다: {stock_code}")
    ...

async def close_position(...) -> Optional[Position]:
    """포지션 청산"""

def update_price(self, stock_code: str, price: int) -> None:
    """현재가 업데이트 (최고가/최저가 갱신)"""

async def sync_with_broker(self) -> None:
    """HTS 매매 동기화"""
```

### 2.7 AutoScreener (auto_screener.py)

**역할**: 6가지 스크리닝 필터 + Watchlist 관리

**핵심 클래스**: `AutoScreener`

**Watchlist 엔트리**:
```python
@dataclass
class WatchlistEntry:
    stock_code: str
    stock_name: str
    first_seen: datetime      # 최초 조건검색 편입 시각
    last_checked: datetime    # 마지막 5필터 체크 시각
    check_count: int = 0      # 필터 체크 횟수
    last_passed: bool = False # 마지막 필터 통과 여부
```

**Candidate 종목**:
```python
@dataclass
class CandidateStock:
    stock_code: str
    stock_name: str
    added_time: datetime
    trading_value: int = 0    # 누적 거래대금
    current_price: int = 0
    is_active: bool = False   # Active Pool 여부
```

**핵심 메서드**:
```python
async def on_condition_signal(self, stock_code, stock_name) -> FilterResult:
    """조건검색 신호 처리 -> 5필터 -> Pool 등록"""

async def revalidate_watchlist(self) -> List[str]:
    """30초마다 Watchlist 재검증 -> Candidate 승격"""

async def check_and_promote(self, stock_code) -> FilterResult:
    """신호 발생 시 즉시 필터 체크 + 승격"""
```

### 2.8 Indicator (indicator.py)

**역할**: 기술적 지표 계산

**핵심 클래스**: `Indicator` (정적 메서드)

**지표 메서드**:
```python
@staticmethod
def ema(series: pd.Series, span: int) -> pd.Series:
    """지수이동평균 (adjust=False)"""
    return series.ewm(span=span, adjust=False).mean()

@staticmethod
def atr(high, low, close, period: int = 14) -> pd.Series:
    """ATR (TradingView RMA 방식)"""
    tr = Indicator.true_range(high, low, close)
    # RMA: alpha = 1/period (Wilder's smoothing)
    return tr.ewm(alpha=1/period, adjust=False).mean()

@staticmethod
def hlc3(high, low, close) -> pd.Series:
    """HLC3 (Typical Price) - VWAP 근사값"""
    return (high + low + close) / 3
```

### 2.9 CandleBuilder (candle_builder.py)

**역할**: 실시간 틱 데이터를 분봉으로 변환

**핵심 클래스**: `CandleBuilder`

**내부 자료구조**:
```python
# 완성된 봉 히스토리 (timeframe별)
self._candles: Dict[int, List[Candle]] = {1: [], 3: []}

# 현재 진행 중인 봉 (틱 데이터로 업데이트)
self._current_candles: Dict[int, Optional[Candle]] = {1: None, 3: None}
```

**핵심 메서드**:
```python
def load_historical_candles(self, timeframe: int, candles: List[Candle]) -> None:
    """
    과거 캔들 로드 (API 조회 결과)

    V6.2-J: 마지막 캔들로 _current_candles도 초기화하여
    즉시 봉 완성 콜백이 가능하도록 함
    """
    self._candles[timeframe] = candles

    # V6.2-J: _current_candles 초기화 (봉 완성 콜백 누락 방지)
    if candles:
        last_candle = candles[-1]
        self._current_candles[timeframe] = Candle(
            stock_code=self.stock_code,
            timeframe=timeframe,
            time=last_candle.time,
            open=last_candle.open,
            high=last_candle.high,
            low=last_candle.low,
            close=last_candle.close,
            volume=last_candle.volume,
            is_complete=True,
        )

def on_tick(self, tick: Tick) -> List[Candle]:
    """
    틱 데이터 수신 시 호출

    Returns:
        완성된 봉 리스트 (새 봉 경계 도달 시)
    """

def get_candles(self, timeframe: int, count: int = None) -> List[Candle]:
    """완성된 봉 히스토리 반환"""
```

**V6.2-J 버그 수정 (2026-01-13)**:

| 수정 전 | 수정 후 |
|---------|---------|
| `load_historical_candles()` 호출 후 `_current_candles[timeframe]`이 None | 마지막 캔들로 `_current_candles[timeframe]` 초기화 |
| 조건검색 등록 후 첫 3분 경계까지 신호 탐지 불가 (최대 3분 지연) | 등록 즉시 신호 탐지 가능 |

**V7.0-Fix6 역순 틱 처리 (2026-01-29)**:

네트워크 지연으로 틱이 역순 도착 시 봉 경계 오인식 방지:

```python
# CandleBuilder 내부 상태
self._last_tick_time: Optional[datetime] = None  # 마지막 틱 시간
self._out_of_order_count: int = 0  # 역순 틱 카운터

# on_tick()에서 역순 틱 감지
if self._last_tick_time and tick.timestamp < self._last_tick_time:
    is_out_of_order = True
    # 역순 틱이 봉 완성을 잘못 트리거하지 않도록 방지

# CandleManager 틱 버퍼링
TICK_BUFFER_SIZE = 50        # 버퍼 크기
TICK_BUFFER_FLUSH_MS = 100   # 플러시 주기 (ms)

# 버퍼 플러시 시 시간순 정렬
ticks_to_process.sort(key=lambda t: t.timestamp)
```

---

## 3. 트레이딩 흐름

### 3.1 진입 흐름 (Entry Flow)

```
+--------------------+
| 조건검색 신호 수신  |  (WebSocket CNSRREQ)
+--------------------+
         |
         v
+--------------------+
| V6.2-B: Watchlist  |  (무조건 등록)
| 등록               |
+--------------------+
         |
         v
+--------------------+
| 5단계 필터 체크    |  (시가총액, 등락률, 거래대금 등)
+--------------------+
         |
    +----+----+
    |         |
 통과      미통과
    |         |
    v         v
+--------+  +------------+
|Candidate|  |Watchlist만|  (30초마다 재검증)
|Pool 등록|  |유지        |
+--------+  +------------+
    |
    v
+--------------------+
| Active Pool 갱신   |  (거래대금 상위 N개)
+--------------------+
         |
         v
+--------------------+
| SNIPER_TRAP 신호   |  (3분봉 완성 시)
| 탐지               |
+--------------------+
         |
         v
+--------------------+
| 쿨다운 체크        |  (시스템 15초, 종목별 VI)
+--------------------+
         |
    +----+----+
    |         |
 가능      불가
    |         |
    v         v
+--------+  +----------+
|매수 주문|  |신호 큐에 |  (20초 유효)
|실행     |  |저장      |
+--------+  +----------+
    |
    v
+--------------------+
| 체결 확인          |  (10초 대기)
+--------------------+
         |
         v
+--------------------+
| 포지션 등록        |
| + DB 저장          |
| + TS 초기화        |
+--------------------+
```

### 3.2 청산 흐름 (Exit Flow)

```
+--------------------+
| 3분봉 완성         |  (on_candle_complete 콜백)
+--------------------+
         |
         v
+--------------------+
| 보유 포지션 순회   |
+--------------------+
         |
         v
+-------------------------------------+
|        청산 조건 체크 (우선순위)     |
|                                     |
|  1. Hard Stop: bar_low <= entry×0.96|
|  2. TS Exit: close <= trailing_stop |
|  3. Max Holding: 60일 초과          |
+-------------------------------------+
         |
    +----+----+
    |         |
 청산      유지
    |         |
    v         v
+--------+  +----------+
|매도 주문|  |TS 갱신   |  (상향만)
|실행     |  |Structure |
+--------+  |Warning   |
    |       |체크      |
    v       +----------+
+--------------------+
| 체결 확인          |
+--------------------+
         |
         v
+--------------------+
| 포지션 청산        |
| + DB 업데이트      |
| + 알림 발송        |
+--------------------+
```

### 3.3 ATR 트레일링 스탑 동작

```
진입 시점:
  entry_atr = ATR(10)  # 매수 시점 ATR 저장 (V6.2-I)
  TS = entry_price - ATR(10) × 6.0

3분봉 완성마다:
  IF Structure Warning:
      mult = 4.5  (타이트닝)
  ELSE:
      mult = 6.0

  # V6.2-I: effective_atr 계산 (무위봉 방어)
  min_atr = entry_price × 0.005  # 매수가 0.5%
  effective_atr = max(current_atr, entry_atr, min_atr)

  new_ts = close - effective_atr × mult
  TS = max(TS, new_ts)  # 상향만

청산 조건:
  IF close <= TS:
      매도 실행
```

**V6.2-I effective_atr 계산** (무위봉/저변동성 방어):
| 구성요소 | 설명 |
|----------|------|
| current_atr | 현재 ATR(10) 값 |
| entry_atr | 매수 시점 저장된 ATR 값 |
| min_atr | 매수가 × 0.5% (최소 보장) |

**기존 포지션 복구 시**: entry_atr 없으면 `entry_price × 0.5%` fallback 적용

---

## 4. Pool 구조 (V6.2-B)

### 4.1 3계층 Pool

```
+--------------------------------------------------+
|                   Watchlist                       |
|  (당일 조건검색 포착 종목, 최대 50개)             |
|  - 필터 결과와 무관하게 등록                      |
|  - 30초마다 재검증                                |
+--------------------------------------------------+
                      |
                      | 5필터 통과 시
                      v
+--------------------------------------------------+
|                 Candidate Pool                    |
|  (5필터 통과 종목, 최대 20개)                     |
|  - 거래대금 낮은 종목 자동 교체                   |
+--------------------------------------------------+
                      |
                      | 거래대금 상위
                      v
+--------------------------------------------------+
|                  Active Pool                      |
|  (실제 매매 가능, 최대 10개)                      |
|  - 60초마다 순위 갱신                             |
|  - 포지션 보유 종목은 강등 제외                   |
+--------------------------------------------------+
```

### 4.2 Pool 설정값

| 설정 | 환경변수 | 기본값 |
|------|----------|--------|
| Watchlist 최대 | `WATCHLIST_MAX_SIZE` | 50 |
| Candidate 최대 | `CANDIDATE_POOL_MAX_STOCKS` | 20 |
| Active 최대 | `AUTO_UNIVERSE_MAX_STOCKS` | 10 |
| 재검증 주기 | `WATCHLIST_REVALIDATION_INTERVAL` | 30초 |
| 순위 갱신 주기 | `RANKING_UPDATE_INTERVAL` | 60초 |

### 4.3 V6.2-B Watchlist 핵심 동작

**시나리오 1: 장초반 필터 미통과 -> 나중에 통과**
```
09:05 조건검색 편입 -> Watchlist 등록 -> 거래대금 149억 (미통과)
09:35 재검증 -> 거래대금 160억 (통과) -> Candidate 승격
09:40 SNIPER_TRAP -> 매수
```

**시나리오 2: 신호 발생 시 즉시 승격**
```
09:05 조건검색 편입 -> Watchlist 등록 (필터 미통과)
09:34 SNIPER_TRAP 신호 발생
09:34 즉시 5필터 체크 -> 통과 -> Active Pool 승격 -> 매수
```

---

## 5. 5단계 스크리닝 필터 (V6.2-B)

### 5.1 필터 목록

| 순서 | 필터 | 조건 | 환경변수 |
|------|------|------|----------|
| 1 | 시가총액 | 1,000억 ~ 10조 | `MIN_MARKET_CAP`, `MAX_MARKET_CAP` |
| 2 | 등락률 | +2% ~ +29.9% | `MIN_CHANGE_RATE`, `MAX_CHANGE_RATE` |
| 3 | 거래대금 | >= 200억 | `MIN_MORNING_VALUE` |
| 4 | 20일 고점 위치 | >= 90% | `HIGH20_RATIO_MIN` |
| 5 | 시가 갭 | < 15% | `GAP_LIMIT_MAX` |

### 5.2 필터 상세 로직

**1. 시가총액 필터**
```python
min_cap = 100_000_000_000     # 1,000억
max_cap = 10_000_000_000_000  # 10조

if market_cap < min_cap or market_cap > max_cap:
    return FilterResult(passed=False, reason="market_cap_out_of_range")
```

**2. 등락률 필터**
```python
# 상한가 근접 종목 제외
if change_rate < 2.0 or change_rate > 29.9:
    return FilterResult(passed=False, reason="change_rate_out_of_range")
```

**3. 거래대금 필터**
```python
min_morning_value = 20_000_000_000  # 200억

if trading_value < min_morning_value:
    return FilterResult(passed=False, reason="trading_value_too_low")
```

**4. 20일 고점 위치 필터**
```python
# 현재가 >= 20일 최고가 × 0.90
high20_ratio = current_price / high_20d

if high20_ratio < 0.90:
    return FilterResult(passed=False, reason="chart_position_low")
```

**5. 시가 갭 필터**
```python
# 과도한 갭업 종목 제외
gap_rate = (open_price - prev_close) / prev_close

if gap_rate >= 0.15:  # 15% 이상
    return FilterResult(passed=False, reason="gap_too_large")
```

---

## 6. 지표 계산

### 6.1 EMA (지수이동평균)

```python
def ema(series: pd.Series, span: int) -> pd.Series:
    """
    pandas ewm 사용, adjust=False 필수

    수식: EMA_t = alpha * price_t + (1-alpha) * EMA_{t-1}
    여기서 alpha = 2 / (span + 1)
    """
    return series.ewm(span=span, adjust=False).mean()
```

**사용되는 EMA**:
- EMA3: 초단기 (CrossUp 판정)
- EMA9: 구조 경고 (Structure Warning)
- EMA20: Zone 상단
- EMA60: Zone 하단, 추세 판정
- EMA200: 메인 추세 필터

### 6.2 ATR (Average True Range)

```python
def true_range(high, low, close) -> pd.Series:
    """
    TR = max(H-L, |H-PrevClose|, |L-PrevClose|)
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

def atr(high, low, close, period: int = 10) -> pd.Series:
    """
    TradingView RMA 방식 (Wilder's smoothing)

    RMA vs EMA:
    - RMA: alpha = 1/period
    - EMA: alpha = 2/(period+1)
    """
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1/period, adjust=False).mean()
```

### 6.3 HLC3 (VWAP 근사값)

```python
def hlc3(high, low, close) -> pd.Series:
    """
    Typical Price (VWAP 근사)

    수식: (High + Low + Close) / 3

    실제 VWAP는 거래량 가중평균이지만,
    단순 평균으로 근사합니다.
    """
    return (high + low + close) / 3
```

---

## 7. WebSocket 및 실시간 데이터

### 7.1 WebSocket 클라이언트

**핵심 클래스**: `KiwoomWebSocket`

**연결 URL**:
- 실전: `wss://api.kiwoom.com:10000/api/dostk/websocket`
- 모의: `wss://mockapi.kiwoom.com:10000/api/dostk/websocket`

**메시지 타입**:
```python
class WSMessageType(str, Enum):
    LOGIN = "LOGIN"       # 로그인
    PING = "PING"         # 하트비트
    CNSRLST = "CNSRLST"   # 조건식 목록
    CNSRREQ = "CNSRREQ"   # 조건검색 (실시간)
    CNSRCLR = "CNSRCLR"   # 조건검색 해제
    REGSUB = "REGSUB"     # 시세 등록
    UNREGSUB = "UNREGSUB" # 시세 해제
```

### 7.2 재연결 전략 (2단계)

**Phase 1 (빠른 재연결)**:
- 최대 5회
- 지수 백오프: 2초 -> 3초 -> 4.5초 -> ...

**Phase 2 (느린 재연결)**:
- 무한 반복
- 5분 간격 (장시간 서버 점검 대응)

```python
FAST_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 2.0
SLOW_RECONNECT_INTERVAL = 300.0  # 5분
```

### 7.3 Heartbeat (좀비 연결 감지)

```python
HEARTBEAT_INTERVAL = 60    # 60초마다 세션 유효성 검증
HEARTBEAT_TIMEOUT = 10     # 응답 대기 10초
MAX_HEARTBEAT_FAILURES = 2 # 2회 연속 실패 시 강제 재연결
```

### 7.4 TCP Keepalive

AWS NAT Gateway 유휴 연결 타임아웃(350초) 방지:
```python
sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)   # 60초 유휴 후 시작
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # 10초 간격
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)     # 6회 시도
```

### 7.5 조건검색 신호 이벤트

```python
@dataclass
class SignalEvent:
    stock_code: str
    stock_name: str
    signal_type: str  # "I"=편입, "D"=이탈
    condition_seq: str
    timestamp: str

    @property
    def is_buy_signal(self) -> bool:
        return self.signal_type == "I"
```

### 7.6 HTS 조건검색식 설정 가이드

영웅문4 HTS에서 조건검색식(seq=0)을 설정하는 방법입니다.

#### 7.6.1 백테스트 분석 결과 (조기 탐지 조건)

| 지표 | 이벤트일 평균 | 비이벤트일 평균 | Cohen's d | HTS 구현 |
|------|-------------|----------------|-----------|----------|
| 전일대비 등락률 | 4.98% | -0.12% | **1.101** | O |
| 시가 갭 | 2.66% | 0.43% | 0.626 | O |
| 거래대금 | 288억 | 158억 | - | O |
| 양봉 비율 | 66.2% | 35.4% | - | O |

#### 7.6.2 권장 조건검색식 설정

**균형 버전 (F1 최적화)** - 권장

| 순서 | 조건 항목 | 설정값 | 비고 |
|------|----------|--------|------|
| 1 | 시가총액 | >= 1,000억 | 소형주 제외 |
| 2 | 시가총액 | <= 20조 | 대형주 제외 |
| 3 | 현재가 | >= 1,000원 | 동전주 제외 |
| 4 | 거래정지 | = 아니오 | 거래 가능 |
| 5 | **등락률** | **>= 2%** | 핵심 조건 (Cohen's d 1.101) |
| 6 | **거래량비율** | **>= 150%** | 핵심 조건 (모멘텀) |
| 7 | **거래대금** | **>= 10억** | 핵심 조건 (Recall 92%) |

예상 성능: Precision ~40%, Recall ~60%, F1 ~50

**고정밀 버전 (Precision 우선)**

```
등락률 >= 3%, 시가갭 >= 2%, 거래량비율 >= 200%, 양봉, 거래대금 >= 20억
예상: Precision ~60%, Recall ~30%
```

**고재현 버전 (Recall 우선)**

```
등락률 >= 1%, 거래대금 >= 10억, 시가총액 >= 1,000억
예상: Precision ~30%, Recall ~80%
```

#### 7.6.3 HTS 설정 방법

1. 영웅문4 HTS 실행
2. 조건검색 → 조건검색식 편집
3. 기존 조건검색식(seq=0) 수정 또는 신규 생성
4. 위 조건들을 AND로 연결
5. 저장 후 `/substatus` 명령어로 구독 상태 확인

#### 7.6.4 HTS 조건검색식 한계

| 제약 | 설명 |
|------|------|
| 시간 기반 조건 | "09:15 시점 등락률" 같은 조건 불가 |
| 복합 계산 | "첫 15분 변동성" 같은 파생 지표 불가 |
| 실시간 업데이트 | 조건 충족 시 자동 편출입 |

> **해결**: 단순 조건(등락률, 거래량)은 HTS에서, 복잡한 조건(EMA, Zone)은 코드에서 처리

---

## 8. 데이터베이스

### 8.1 연결 설정

**PostgreSQL (Supabase)** - 운영 환경:
```python
DATABASE_URL = "postgresql://user:pass@host:port/db?sslmode=require"
```

**SQLite** - 로컬 폴백:
```python
SQLITE_PATH = "data/k_stock_trading.db"
```

### 8.2 ORM 모델

**Trade (거래 내역)**:
```python
class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(100), nullable=False)
    strategy = Column(String(50), nullable=False)
    entry_source = Column(SQLEnum(EntrySource), nullable=False)

    # 매수 정보
    entry_price = Column(Integer, nullable=False)
    entry_quantity = Column(Integer, nullable=False)
    entry_amount = Column(BigInteger, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    entry_order_no = Column(String(50))

    # 매도 정보
    exit_price = Column(Integer)
    exit_quantity = Column(Integer)
    exit_amount = Column(BigInteger)
    exit_time = Column(DateTime)
    exit_order_no = Column(String(50))
    exit_reason = Column(String(100))

    # 손익
    profit_loss = Column(Integer)
    profit_loss_rate = Column(Float)
    holding_seconds = Column(Integer)

    # 상태
    status = Column(SQLEnum(TradeStatus), default=TradeStatus.OPEN)
```

**Order (주문 내역)**:
```python
class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey("trades.id"))
    stock_code = Column(String(10), nullable=False)
    side = Column(SQLEnum(OrderSide), nullable=False)
    order_type = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Integer)

    # 체결 정보
    filled_quantity = Column(Integer, default=0)
    filled_price = Column(Integer)
    filled_amount = Column(BigInteger)
    order_no = Column(String(50))
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
```

**DailyStats (일일 통계)**:
```python
class DailyStats(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True)
    trade_count = Column(Integer, default=0)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
    total_profit = Column(BigInteger, default=0)
    total_loss = Column(BigInteger, default=0)
    net_pnl = Column(BigInteger, default=0)
    win_rate = Column(Float)
```

**Signal (신호 기록)**:
```python
class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    stock_code = Column(String(10), nullable=False)
    stock_name = Column(String(100), nullable=False)
    strategy = Column(String(50), nullable=False)
    signal_type = Column(String(20), nullable=False)
    price = Column(Integer, nullable=False)
    executed = Column(Boolean, default=False)
    blocked_reason = Column(String(100))
    trade_id = Column(Integer, ForeignKey("trades.id"))
```

### 8.3 Enum 타입

```python
class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"  # 롤백된 거래

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
```

---

## 9. 텔레그램 명령어

### 9.1 기본 명령어

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/status` | 시스템 상태 조회 | `/status` |
| `/help` | 도움말 표시 | `/help` |

### 9.2 종목 관리

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/add 종목코드` | 감시 종목 추가 | `/add 005930` |
| `/remove 종목코드` | 감시 종목 제거 | `/remove 005930` |

### 9.3 거래 명령

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/buy 종목코드` | 수동 매수 | `/buy 005930` |
| `/sell 종목코드` | 수동 매도 | `/sell 005930` |

### 9.4 설정 변경

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/ratio [비중%]` | 매수 비중 조회/변경 | `/ratio 10` |

### 9.5 시스템 관리

| 명령어 | 설명 | 예시 |
|--------|------|------|
| `/ignore 종목코드` | 시스템 청산 제외 | `/ignore 005930` |
| `/unignore 종목코드` | 청산 제외 해제 | `/unignore 005930` |
| `/substatus` | 조건검색 구독 상태 | `/substatus` |
| `/subscribe` | 조건검색 수동 재구독 | `/subscribe` |
| `/wsdiag` | WebSocket 진단 | `/wsdiag` |

### 9.6 parse_mode 주의사항

**중요**: 모든 텔레그램 알림은 `parse_mode=None` (plain text)로 발송해야 합니다.
Markdown 사용 시 400 에러 발생.

```python
await telegram.send_message(text, parse_mode=None)  # 올바름
await telegram.send_message(text, parse_mode="Markdown")  # 에러!
```

---

## 10. 환경변수

### 10.1 시스템 기본 설정

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `ENVIRONMENT` | development | 환경 (development/production) |
| `IS_PAPER_TRADING` | false | 모의투자 여부 |
| `LOG_LEVEL` | INFO | 로그 레벨 |
| `TRADING_MODE` | AUTO_UNIVERSE | 거래 모드 (MANUAL_ONLY/AUTO_UNIVERSE/SIGNAL_ALERT) |

### 10.1.1 TRADING_MODE 상세 (V6.2-C)

| 모드 | 설명 |
|------|------|
| `MANUAL_ONLY` | 수동 매매만 허용, 조건검색 비활성화 |
| `AUTO_UNIVERSE` | 완전 자동매매, SNIPER_TRAP 신호 시 자동 매수 |
| `SIGNAL_ALERT` | 알림 전용, SNIPER_TRAP 신호 시 텔레그램 알림만 발송 |

**SIGNAL_ALERT 모드 특징**:
- 조건검색 구독 및 5필터 체크는 AUTO_UNIVERSE와 동일
- SNIPER_TRAP 신호 발생 시 **자동매수 대신 텔레그램 알림만 전송**
- `/buy` 수동매수 시 ATR 트레일링 스탑 자동 초기화 → 자동청산 지원
- Pool 제한 해제 (Watchlist 9999개)

**SIGNAL_ALERT 전용 환경변수**:

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `SIGNAL_ALERT_COOLDOWN_SECONDS` | 300 | 같은 종목 중복 알림 방지 (초) |
| `WATCHLIST_MAX_UNLIMITED` | 9999 | SIGNAL_ALERT 모드 Watchlist 최대 |

**모드별 동작 비교**:

| 기능 | AUTO_UNIVERSE | SIGNAL_ALERT |
|------|---------------|--------------|
| 조건검색 구독 | O | O |
| 5필터 체크 | O | O |
| SNIPER_TRAP 신호 | 자동매수 | 알림만 전송 |
| /buy 수동매수 | O | O |
| 수동매수 ATR TS | X | O (자동 초기화) |
| 포지션 자동청산 | O | O |
| Pool 제한 | 50/20/10 | 9999/9999/9999 (무제한) |

### 10.2 키움 API 인증

| 환경변수 | 설명 |
|----------|------|
| `KIWOOM_APP_KEY` | 앱 키 (실전) |
| `KIWOOM_APP_SECRET` | 앱 시크릿 (실전) |
| `KIWOOM_PAPER_APP_KEY` | 앱 키 (모의) |
| `KIWOOM_PAPER_APP_SECRET` | 앱 시크릿 (모의) |

### 10.3 텔레그램

| 환경변수 | 설명 |
|----------|------|
| `TELEGRAM_BOT_TOKEN` | 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 채팅 ID |

### 10.4 데이터베이스

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `DATABASE_URL` | - | PostgreSQL 연결 문자열 |
| `SQLITE_PATH` | data/k_stock_trading.db | SQLite 폴백 경로 |

### 10.5 리스크 관리

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `MAX_POSITIONS` | 99 | 최대 포지션 수 |
| `SAFETY_STOP_RATE` | -4.0 | 고정 손절 (%) |
| `ATR_TRAILING_PERIOD` | 10 | ATR 기간 |
| `TS_ATR_MULT_BASE` | 6.0 | ATR 기본 배수 |
| `TS_ATR_MULT_TIGHT` | 4.5 | ATR 경고 배수 |
| `MAX_HOLDING_DAYS` | 60 | 최대 보유일 |
| `BUY_AMOUNT_RATIO` | 0.10 | 매수 비중 (10%) |
| `BUY_COOLDOWN_SECONDS` | 15 | 매수 쿨다운 |

### 10.6 스크리닝 필터 (V6.2-B: 5필터)

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `MIN_MARKET_CAP` | 100,000,000,000 | 최소 시가총액 (1,000억) |
| `MAX_MARKET_CAP` | 10,000,000,000,000 | 최대 시가총액 (10조) |
| `MIN_CHANGE_RATE` | 2.0 | 최소 등락률 (%) |
| `MAX_CHANGE_RATE` | 29.9 | 최대 등락률 (%) |
| `MIN_MORNING_VALUE` | 20,000,000,000 | 최소 거래대금 (200억) |
| `HIGH20_RATIO_MIN` | 0.90 | 20일 고점 비율 |
| `GAP_LIMIT_MAX` | 0.15 | 시가 갭 한도 (15%) |

### 10.7 Pool 설정

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `AUTO_UNIVERSE_ENABLED` | true | Auto-Universe 활성화 |
| `AUTO_UNIVERSE_CONDITION_SEQ` | 0 | 조건검색식 번호 |
| `AUTO_UNIVERSE_MAX_STOCKS` | 10 | Active Pool 최대 |
| `CANDIDATE_POOL_MAX_STOCKS` | 20 | Candidate Pool 최대 |
| `WATCHLIST_MAX_SIZE` | 50 | Watchlist 최대 |
| `WATCHLIST_REVALIDATION_INTERVAL` | 30 | 재검증 주기 (초) |
| `RANKING_UPDATE_INTERVAL` | 60 | 순위 갱신 주기 (초) |

### 10.8 시간 설정 (V6.2-L 업데이트)

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `MARKET_OPEN_TIME` | 09:00 | 장 시작 시간 |
| `SIGNAL_START_TIME` | 09:20 | 신호 탐색 시작 (V6.2-L: 09:30->09:20) |
| `SIGNAL_END_TIME` | 15:20 | 신호 탐색 종료 (V6.2-L 신규) |
| `NXT_SIGNAL_ENABLED` | false | NXT 애프터마켓(15:40~20:00) 신호 허용 (V6.2-L 신규) |
| `NXT_EXIT_ENABLED` | true | NXT 시간대(08:00~20:00) 청산/손절 허용 (V6.2-L 신규) |
| `WAIT_FOR_MARKET_OPEN` | false | 장전 WebSocket 연결 |

### 10.9 조기 신호 설정 (V6.2-D)

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `EARLY_SIGNAL_TIME` | 09:00 | 52주 고점 근접 종목 조기 신호 시작 시간 |
| `NEAR_52W_HIGH_RATIO` | 0.90 | 52주 고점 대비 비율 (90% 이상 시 조기 신호) |

**동작 설명**:
- 현재가가 52주 최고가의 90% 이상인 종목은 09:03부터 신호 탐지
- 일반 종목은 기존대로 09:30부터 신호 탐지
- 09:00~09:03은 3분봉 완성 전이므로 모든 종목 신호 탐지 X

### 10.10 NXT 시장조작 방어 설정 (V6.2-E)

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `EXIT_PROTECTION_MINUTES` | 1 | 장 초반 보호 기간 (분) - bar_low 손절 비활성화 |
| `EXTREME_DROP_THRESHOLD` | -0.15 | 극단값 임계치 (-15%) - 이보다 큰 하락은 무시 |
| `EXTREME_PRICE_ALERT` | true | 극단값 감지 시 텔레그램 알림 |

**배경 (NXT 거래소 시장조작)**:
- NXT 거래소는 08:00부터 거래 시작 (정규장 09:00 이전)
- 장전에 -30% 하한가까지 의도적으로 하락시킨 후 원상복구하는 조작 발생
- 기존 시스템은 08:00~09:00 사이 조작된 bar_low가 09:00 이후 첫 체크에서 손절 트리거

**2단계 방어 메커니즘**:
```
Layer 1: 장 초반 보호 기간
  - 09:00~09:01 (EXIT_PROTECTION_MINUTES=1)
  - bar_low 기반 손절 비활성화
  - current_price 기반 손절은 유지 (실제 급락 대응)

Layer 2: 극단값 필터
  - bar_low < entry_price × (1 + EXTREME_DROP_THRESHOLD) 시 무시
  - 예: -15% 이상 급락 bar_low는 손절 조건에서 제외
  - 텔레그램으로 극단값 감지 알림 발송
```

**관련 파일**:
- `src/utils/config.py`: 환경변수 정의
- `src/core/risk_manager.py`: `check_exit_v62a()` 극단값 필터 추가
- `src/core/exit_manager.py`: `_is_opening_protection_period()` 메서드 추가

---

## 11. 배포 및 운영

### 11.1 서버 정보

**배포 환경**: AWS Lightsail

| 항목 | 값 |
|------|-----|
| 플랫폼 | AWS Lightsail |
| 리전 | ap-northeast-2 (서울) |
| RAM | 1 GB |
| vCPUs | 2 |
| SSD | 40 GB |
| OS | Ubuntu |
| 호스트 | 43.200.235.74 |
| 사용자 | ubuntu |
| SSH 키 | `%USERPROFILE%\.ssh\k-stock-trading-key.pem` |
| 경로 | `/home/ubuntu/K_stock_trading/current` |

### 11.2 배포 명령어

**핫픽스 배포**:
```powershell
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\hotfix.ps1"
```

**로그 확인**:
```powershell
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_logs.ps1" 50
```

**상태 확인**:
```powershell
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\status.ps1"
```

**DB 확인**:
```powershell
powershell -ExecutionPolicy Bypass -File "C:\K_stock_trading\scripts\deploy\check_db_server.ps1"
```

### 11.3 배포 순서

1. `hotfix.ps1` 실행 (코드 배포 + 서비스 재시작)
2. 5초 대기
3. `check_logs.ps1 30` 으로 로그 확인

### 11.4 장 테스트 체크리스트

**장 시작 전 (08:30 전)**:
- [ ] 서비스 Active 상태
- [ ] PostgreSQL 연결 성공
- [ ] Pre-flight 검증 통과
- [ ] 에러 로그 없음

**장 시작 직후 (09:00~09:05)**:
- [ ] Watchlist/Candidate/Active Pool 리셋 로그
- [ ] Watchlist 재검증 루프 시작 로그

**장 중 (09:00~15:30)**:
- [ ] 조건검색 구독 성공
- [ ] WebSocket 연결 유지
- [ ] 신호 탐지 로그 (09:30 이후)

**장 마감 후 (15:30 이후)**:
- [ ] trades 테이블 기록 확인
- [ ] orders 테이블 기록 확인

### 11.5 비상 상황 대응

| 상황 | 확인 명령 | 조치 |
|------|----------|------|
| DB 연결 실패 | `check_logs.ps1 100` | CRITICAL 알림 확인 |
| 포지션 불일치 | `/status` | 1분마다 자동 동기화 |
| 서비스 중단 | `status.ps1` | `hotfix.ps1` 재배포 |
| WebSocket 끊김 | `/wsdiag` | 2단계 자동 재연결 |

---

## 부록

### A. API 주의사항

**1. 잔고 조회 (kt00004) - KRX/NXT 통합 조회**

키움증권 kt00004 API는 거래소별 조회만 지원하며, KRX+NXT 통합 조회 옵션이 없습니다.

```python
# src/api/endpoints/account.py: get_positions()
# NXT 거래소에서 매수한 종목은 KRX 조회 시 누락됨

# 해결책: KRX와 NXT 각각 호출 후 합산
positions_krx = await self._call_kt00004(exchange="KRX")
positions_nxt = await self._call_kt00004(exchange="NXT")
all_positions = self._merge_positions(positions_krx, positions_nxt)
```

**V6.2-F 버그 수정 (2026-01-12)**: NXT 매수 종목이 누락되던 문제 해결

---

### B. 수정 금지 항목

다음 항목들은 전략 무결성 유지를 위해 수정 금지:

- **Zone 조건**: `low <= EMA20 AND close >= EMA60`
- **BodySize 기준**: `(C-O)/O*100 >= 0.3`
- **EMA adjust=False**: pandas.ewm() 설정
- **ATR 배수**: 6.0 (기본), 4.5 (Structure Warning)
- **청산 조건**: -4%, ATR TS, 60일

### C. 시간 규칙 (KST)

- 장 운영: 09:00~15:30
- 동시호가: 08:30~09:00, 15:20~15:30
- 신호 탐색 시작 (V6.2-D):
  - 52주 고점 90% 이상 종목: 09:03 (조기 신호)
  - 일반 종목: 09:30

### D. Rate Limiting

키움 API 초당 5회 제한 준수 필수.

---

## 12. V7 Purple-ReAbs 전략

### 12.1 개요

V7 Purple-ReAbs는 "재응축 구간 신호 알림" 전략으로, V6 SNIPER_TRAP의 후속 버전입니다.
급등 후 조정 구간에서 재상승 시작점을 포착하는 것이 핵심 아이디어입니다.

**활성화**:
```bash
V7_PURPLE_ENABLED=true  # .env 파일
```

### 12.2 신호 조건 (5개 모두 충족)

```python
Signal = PurpleOK AND Trend AND Zone AND ReAbsStart AND Trigger
```

| 조건 | 설명 | 수식 |
|------|------|------|
| PurpleOK | 과거 급등 + 조정 완료 | (H1/L1-1)>=4% AND (H2/L2-1)<=7% AND M>=5억 |
| Trend | 상승 추세 | EMA60 > EMA60[3] |
| Zone | EMA60 근접 | Close >= EMA60 × 0.995 |
| ReAbsStart | 재응축 시작 | Score > Score[1] |
| Trigger | 진입 트리거 | CrossUp(Close, EMA3) AND Close > Open |

**Score 계산**:
```python
Score = (Close/WMA20 - 1) * 2 + LiquidityZone * 0.8 + Recovery * 1.2
```

### 12.3 Wave Harvest 청산

ATR 기반 동적 트레일링 스탑으로 수익을 극대화하면서 손실을 제한합니다.

**ATR 배수 단계** (단방향 축소):
| 조건 | ATR 배수 |
|------|----------|
| 초기 진입 | 6.0 |
| 구조 경고 | 4.5 |
| R ≥ 1 | 4.0 |
| R ≥ 2 | 3.5 |
| R ≥ 3 | 2.5 |
| R ≥ 5 | 2.0 |

**트레일링 스탑 계산**:
```python
BasePrice = Highest(High, 20)
TrailingStop = max(prev_stop, BasePrice - ATR(10) × Multiplier)
```

**Trend Hold Filter** (청산 차단):
```python
TrendHold = EMA20 > EMA60 AND HighestHigh(20) > HighestHigh(60)
# 청산 조건: NOT TrendHold AND Close < TrailingStop
```

### 12.4 Dual-Pass 신호 탐지

V7은 정확도 향상을 위해 2단계 확인 프로세스를 사용합니다.

```
Pre-Check (봉 완성 30초 전)
    ↓
조건 사전 평가
    ↓
Confirm-Check (봉 완성 직후)
    ↓
최종 신호 확정 → 매수 실행
```

### 12.5 V7 모듈

| 모듈 | 파일 | 역할 |
|------|------|------|
| PurpleSignalDetector | `signal_detector_purple.py` | V7 신호 탐지 |
| WaveHarvestExit | `wave_harvest_exit.py` | ATR 동적 청산 |
| SignalPool | `signal_pool.py` | 신호 풀 관리 |
| V7SignalCoordinator | `v7_signal_coordinator.py` | Dual-Pass 조율 |

### 12.6 수정 불가 항목

V7 전략의 핵심 파라미터는 전략 무결성을 위해 수정이 금지됩니다:

- Score 가중치: `(C/W-1)*2, LZ*0.8, recovery*1.2`
- PurpleOK 임계값: 상승률 4%, 수렴률 7%, 거래대금 5억
- Zone 허용 범위: `EMA60 × 0.995`
- ATR 배수 단계: `6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0`
- Trend Hold Filter 조건
- EMA `adjust=False`

---

*문서 작성일: 2026-01-27*
*시스템 버전: V7.0 Purple-ReAbs*
