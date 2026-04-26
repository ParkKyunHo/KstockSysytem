# Trading System Framework

> **코드 작성 및 수정 시 반드시 참조**
>
> 새로운 전략 구현, 기존 코드 수정, 코드 리뷰 시 이 문서의 표준을 따를 것.

---

## 1. 필수 안전장치 (Safety Mechanisms)

### 1.1 4중 Lock 구조 (진입 시)

```
시스템 쿨다운 → 종목 쿨다운 → 주문 Lock → Double-Check
```

```python
# 1. 시스템 쿨다운 (매수 후 30초)
if self._order_executor.is_in_system_buy_cooldown():
    return

# 2. 종목 쿨다운 (청산 후 15분)
if self._risk_manager.is_in_cooldown(stock_code):
    return

# 3. 주문 Lock (종목별 asyncio.Lock)
async with self._get_order_lock(stock_code):
    # 4. Double-Check (Lock 후 상태 재확인)
    if self._position_manager.has_position(stock_code):
        return
    # 실제 주문 실행
```

### 1.2 Safety Net (고정 손절)

```python
# 어떤 상황에서도 작동하는 절대 손절
# /ignore 명령어로도 우회 불가
if bar_low <= entry_price * (1 + SAFETY_STOP_RATE / 100):
    execute_emergency_exit()  # 강제 청산
```

### 1.3 DB 트랜잭션 원자성

```python
# 실패 시 롤백 패턴
trade_id = None
try:
    trade = await trade_repo.create(...)
    trade_id = trade.id
    try:
        order = await order_repo.create(trade_id=trade_id, ...)
    except Exception:
        # Order 실패 → Trade 롤백
        await trade_repo.update_status(trade_id, TradeStatus.CANCELLED)
        raise
except Exception as db_err:
    # 텔레그램 알림 필수
    await telegram.send_message(f"⚠️ [CRITICAL] DB 저장 실패: {db_err}")
```

### 1.4 상태 복구 (재시작 시)

```python
async def start(self):
    try:
        await self._restore_positions_from_db()
        await self._risk_manager.restore_from_db(trade_repo)  # 쿨다운/블랙리스트
        await self._load_ignore_stocks()  # /ignore 영속성
    finally:
        self._startup_complete = True  # 복구 완료 전 신호 무시
```

---

## 2. 표준 아키텍처 패턴

### 2.1 모듈 책임 분리

| 모듈 | 책임 | 절대 금지 |
|------|------|----------|
| `TradingEngine` | 흐름 제어, 신호 라우팅 | 직접 주문 실행 |
| `SignalDetector` | 진입 신호 탐지 | 청산 로직 포함 |
| `OrderExecutor` | 매수 주문 실행 | 청산 로직 포함 |
| `ExitManager` | 청산 주문 실행, TS 업데이트 | 진입 로직 포함 |
| `RiskManager` | 리스크 계산, 청산 조건 판정 | 주문 실행 |
| `PositionManager` | 포지션 CRUD | 리스크 계산 |

### 2.2 데이터 흐름

```
[WebSocket] → TradingEngine._on_condition_match()
                    ↓
           SignalDetector.check_signal()
                    ↓
           RiskManager.can_enter() ← 4중 Lock
                    ↓
           OrderExecutor.execute_buy()
                    ↓
           PositionManager.open_position()
           RiskManager.on_entry()
                    ↓
           ExitManager.init_trailing_stop()

[3분봉 완성] → ExitManager.update_trailing_stop()
                    ↓
           RiskManager.check_exit_v62a()
                    ↓
           ExitManager.execute_full_sell()
                    ↓
           RiskManager.on_exit()
           PositionManager.close_position()
```

### 2.3 correlation_id 사용

```python
from src.utils.logger import generate_correlation_id, bind_context, unbind_context

# 매수/매도 시작 시
correlation_id = generate_correlation_id(stock_code, trade_id)
bind_context(correlation_id=correlation_id)

try:
    # 모든 로그에 자동으로 correlation_id 포함
    self._logger.info("주문 실행", price=price, qty=qty)
finally:
    unbind_context("correlation_id")
```

---

## 3. 새 전략 추가 체크리스트

### 3.1 구현 전 (설계)

- [ ] PRD 문서 작성 완료
- [ ] 백테스트 검증 완료 (승률, 손익비, MDD)
- [ ] 진입/청산 조건 수식 정의
- [ ] 필요 지표 목록 정의 (EMA, ATR 등)
- [ ] 포지션 사이징 규칙 정의

### 3.2 구현 (코드)

- [ ] SignalDetector에 새 전략 클래스 추가
- [ ] RiskManager에 청산 조건 메서드 추가
- [ ] ExitManager에 TS/청산 로직 추가 (필요시)
- [ ] config.py에 새 설정 필드 추가
- [ ] .env에 기본값 설정

### 3.3 안전장치 확인

- [ ] 4중 Lock 구조 적용
- [ ] Safety Net (고정 손절) 우회 불가 확인
- [ ] DB 원자성 보장 (롤백 로직)
- [ ] 재시작 시 상태 복구 구현
- [ ] startup_complete 플래그 체크
- [ ] correlation_id 적용

### 3.4 검증 (테스트)

- [ ] 진입 조건 단위 테스트
- [ ] 청산 조건 단위 테스트
- [ ] 4중 Lock 통합 테스트
- [ ] 모의투자 E2E 테스트
- [ ] 재시작 복구 테스트

### 3.5 로깅 (관측가능성)

- [ ] 진입 시점 핵심 지표 로깅 `[D2]`
- [ ] 청산 시점 핵심 지표 로깅 `[D2]`
- [ ] 실패 시 텔레그램 알림

---

## 4. 코드 수정 체크리스트

새로운 기능 추가 또는 버그 수정 시 확인할 사항:

### 4.1 진입 로직 수정 시

- [ ] RiskManager.can_enter() 체크 유지
- [ ] 중복 포지션 체크 (has_position)
- [ ] 쿨다운/블랙리스트 체크 유지
- [ ] startup_complete 플래그 확인

### 4.2 청산 로직 수정 시

- [ ] 고정 손절(-4%) 우회 불가능한지 확인
- [ ] /ignore 시에도 Safety Net 작동
- [ ] TS 상향 전용 원칙 유지
- [ ] pending_sell_orders 중복 체크

### 4.3 DB 관련 수정 시

- [ ] 트랜잭션 원자성 보장 (실패 시 롤백)
- [ ] 실패 시 텔레그램 알림
- [ ] Trade/Order 불일치 방지

### 4.4 포지션 관련 수정 시

- [ ] PositionManager ↔ RiskManager 동기화
- [ ] 수량 변경 시 sync_quantity() 호출
- [ ] 포지션 등록 실패 시 롤백

---

## 5. 표준 설정 구조

### 5.1 config.py 필수 필드

```python
class RiskSettings(BaseSettings):
    # === 필수: 리스크 관리 ===
    safety_stop_rate: float      # 고정 손절 (예: -4.0)
    max_positions: int           # 최대 동시 포지션
    max_holding_days: int        # 최대 보유일

    # === 필수: 포지션 사이징 ===
    buy_amount_ratio: float      # 매수 비중 (예: 0.10 = 10%)

    # === 필수: 쿨다운 ===
    buy_cooldown_seconds: int    # 시스템 매수 쿨다운
    cooldown_minutes: int        # 종목 청산 후 쿨다운

    # === 전략별: 진입 조건 ===
    signal_start_time: str       # 신호 탐색 시작 시간

    # === 전략별: 청산 조건 ===
    ts_atr_mult_base: float      # ATR TS 기본 배수
    ts_atr_mult_tight: float     # ATR TS 타이트 배수 (옵션)
    atr_trailing_period: int     # ATR 기간
```

### 5.2 .env 명명 규칙

```bash
# 대문자 + 언더스코어
# 접두어로 용도 구분

# 리스크 관리
SAFETY_STOP_RATE=-4.0
MAX_POSITIONS=99

# ATR 관련
ATR_TRAILING_PERIOD=10
TS_ATR_MULT_BASE=6.0
TS_ATR_MULT_TIGHT=4.5

# 스크리닝
MIN_MARKET_CAP=100000000000
MIN_VOLUME_RATIO=200
```

---

## 6. 로깅 표준

### 6.1 로그 레벨 사용

| 레벨 | 용도 | 예시 |
|------|------|------|
| DEBUG | 지표 계산, 조건 체크 상세 | EMA 값, ATR 값 |
| INFO | 신호, 주문, 체결 | 매수/매도 완료 |
| WARNING | 스킵, 경고 | 잔고 부족, 쿨다운 |
| ERROR | 주문 실패, API 오류 | 체결 실패 |
| CRITICAL | 시스템 중단, 치명적 오류 | DB 연결 실패 |

### 6.2 구조화 로깅 필수 필드

```python
# 진입 시 (order_executor.py)
self._logger.info(
    f"[D2] 진입 지표: {stock_code}",
    ema3=..., ema20=..., ema60=..., ema200=...,
    body_size_pct=..., volume_ratio=..., floor_line=...,
)

# 청산 시 (exit_manager.py)
self._logger.info(
    f"[D2] 청산 지표: {stock_code}",
    exit_reason=..., entry_price=..., trailing_stop=...,
    highest_price=..., is_ts_fallback=...,
    ema9_below_count=..., vwap_below_count=...,
)
```

---

## 7. 코드 리뷰 필수 항목

새 코드 또는 수정 코드에 대한 리뷰 시 확인할 항목:

### 7.1 데이터 무결성

- [ ] Position/PositionRisk 동기화 유지
- [ ] 트랜잭션 원자성 보장
- [ ] 중복 포지션 방지

### 7.2 상태 관리

- [ ] startup_complete 체크
- [ ] 4중 Lock 구조 유지
- [ ] 재시작 시 상태 복구

### 7.3 리스크 관리

- [ ] Safety Net 우회 불가
- [ ] TS 상향 전용 원칙
- [ ] 쿨다운/블랙리스트 적용

### 7.4 실패 처리

- [ ] 롤백 로직 구현
- [ ] 텔레그램 알림
- [ ] Ghost Order 방지

---

## 8. 전략 간 공유 컴포넌트

여러 전략에서 공통으로 사용하는 컴포넌트:

| 컴포넌트 | 위치 | 용도 |
|----------|------|------|
| `Indicator.ema()` | indicator.py | EMA 계산 |
| `Indicator.atr()` | indicator.py | ATR 계산 (RMA) |
| `Indicator.hlc3()` | indicator.py | VWAP 근사값 |
| `RiskManager.can_enter()` | risk_manager.py | 진입 가능 여부 |
| `RiskManager.check_exit_*()` | risk_manager.py | 청산 조건 체크 |
| `OrderExecutor.execute_buy()` | order_executor.py | 매수 실행 |
| `ExitManager.execute_full_sell()` | exit_manager.py | 매도 실행 |
| `generate_correlation_id()` | logger.py | 거래 추적 ID |

---

## 9. 버전 관리 규칙

### 9.1 버전 형식

```
V{major}.{minor}-{suffix}

예: V6.2-A
- major: 전략 대폭 변경
- minor: 파라미터 조정, 버그 수정
- suffix: 세부 버전 (A, B, C...)
```

### 9.2 변경 로그

- `docs/CHANGELOG.md`: 버전별 변경 내역
- `.claude/state/work-context.json`: 일일 작업 기록

---

## 10. 배포 전 검증 프로세스

1. **PRD 일치 확인**: 모든 진입/청산 조건이 PRD와 일치
2. **설정 검증**: .env 값이 PRD 요구사항과 일치
3. **안전장치 확인**: 4중 Lock, Safety Net, DB 원자성
4. **로깅 확인**: correlation_id, D2 지표 로깅
5. **모의투자 테스트**: 최소 1일 실행 후 로그 검토
