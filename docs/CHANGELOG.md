# CHANGELOG

> K_stock_trading 버전 히스토리 및 변경 기록
> 최신 버전: V7.1-Fix14 (2026-02-12)

---

## 2026-02-12 - V7.1-Fix14 PurpleOK 거래대금 0.0억 버그 수정

### 배경
2026-02-11 장중 ConfirmCheck에서 거래대금이 0.0억으로 표시되어 PurpleOK(M>=5억)가 항상 실패.
PreCheck(API 3분봉)에서는 55.1억으로 정상이나, ConfirmCheck(실시간 캔들)로 전환 시 volume 스케일 차이(100배+)로 인해 발생.

### 근본 원인
- API 3분봉 volume = 전체 시장 거래량 (정상)
- 실시간 캔들 volume = WebSocket으로 수신된 틱만의 합계 (극소량)
- money = close × volume 계산에서 실시간 캔들 기준 거래대금이 0.0억으로 산출

### 수정 내용

| 파일 | 변경 내용 |
|------|----------|
| `signal_pool.py` | `StockInfo`에 `purple_ok_cached`, `purple_ok_cached_at` 필드 추가 |
| `v7_signal_coordinator.py` | PreCheck 후보 등록 시 PurpleOK 결과 캐시 저장 |
| `v7_signal_coordinator.py` | 배치 ConfirmCheck에서 PurpleOK 캐시 적용 (30분 유효) |
| `v7_signal_coordinator.py` | 이벤트 ConfirmCheck에서 PurpleOK 캐시 적용 (30분 유효) |

### 설계 근거
PurpleOK는 구조적 조건(40봉 상승률, 20봉 수렴률, 거래대금)으로 3분마다 급변하지 않음.
PreCheck에서 API 캔들 기반으로 정확히 판정된 결과를 30분간 캐시하여 재사용.
PurpleOK 임계값(4%, 7%, 5억) 자체는 변경하지 않음.

### V7 Immutables 검증
PASS - Score 가중치, PurpleOK 임계값, ATR 배수, EMA adjust=False 변경 없음

---

## 2026-02-11 - V7.1-Fix13b 조건 수치 INFO 로깅 추가

### 배경
2026-02-10 유진로봇(056080) HTS 차트에 V7 신호 화살표가 있었으나, 시스템은 3/5만 충족으로 판단.
프로덕션 로그가 INFO 레벨이라 조건 미달 사유(DEBUG)가 기록되지 않아 원인 진단 불가.

### 수정 내용

| 파일 | 변경 내용 |
|------|----------|
| `signal_detector_purple.py` | `format_condition_log()` 함수 추가 - 5개 조건 O/X + 수치 한줄 요약 |
| `signal_detector_purple.py` | `PreCheckResult`에 `condition_values` 필드 추가 |
| `signal_detector_purple.py` | `_get_condition_values()` 메서드 추가 - 진단용 수치 추출 |
| `v7_signal_coordinator.py` | PreCheck 후보 등록 시 조건 수치 INFO 로깅 |
| `v7_signal_coordinator.py` | ConfirmCheck NearMiss(4/5) + 미달(3/5) 조건 수치 INFO 로깅 |

### 로그 형식 예시
```
[V7 PreCheck] 후보 등록: 유진로봇(056080) 조건 3/5 충족 | P:O(↑5.2%/↔4.1%/8.3억) T:O(12000/11950) Z:X(C:12050/Th:11940) R:X(0.289→0.324) Tr:X(음,12010/12030)
```

### V7 Immutables 검증
PASS - Score 가중치, PurpleOK 임계값, ATR 배수, EMA adjust=False 변경 없음

---

## 2026-02-09 - V7.1-Fix13 신호 탐지 0건 버그 수정

### 배경
2026-02-09 장중 SignalPool 40개 종목을 113회 ConfirmCheck했으나 신호 0건 발생.
HTS 차트에는 V7 Purple-ReAbs 신호가 보이는 종목이 있었음에도 시스템이 감지 실패.

### 근본 원인
1. **ConfirmCheck 타이밍 레이스 컨디션**: WatermarkManager는 벽시계로 봉 경계 계산하지만,
   CandleBuilder는 다음 봉의 첫 틱 도착 시에만 이전 봉 완성. ConfirmCheck가 봉 경계 후
   0~5초에 실행되어 항상 1봉 뒤 데이터로 조건 체크 → DualPass 무력화
2. **PurpleOK NaN 무방비**: `check_purple_ok()`에 NaN 검증 없음.
   `bool(NaN >= 0.04)` → `False`로 조건 미달 오판

### 수정 내용

| Fix | 파일 | 변경 내용 |
|-----|------|----------|
| Fix 1 (PRIMARY) | `v7_signal_coordinator.py` | 이벤트 기반 ConfirmCheck: `_on_candle_complete_confirm()` 추가, `start()`에 `_callbacks` 저장 |
| Fix 1 | `trading_engine.py` | `_on_candle_complete`에서 3m 봉 완성 시 V7 이벤트 전달 |
| Fix 2 (SAFETY NET) | `v7_signal_coordinator.py` | 벽시계 ConfirmCheck tolerance 5초 → 15초 확대 |
| Fix 3 (DEFENSIVE) | `signal_detector_purple.py` | `check_purple_ok()` NaN 검증 추가 (`pd.isna()` 체크) |

### V7 Immutables 검증
- Score 가중치: PASS (변경 없음)
- PurpleOK 임계값: PASS (NaN 검증만 추가, 임계값 변경 없음)
- ATR 배수: PASS (변경 없음)
- EMA adjust=False: PASS (변경 없음)

---

## 2026-02-06 - V7.1-Fix12 신호 분석 및 알림 시스템 종합 개선

### 배경
SIGNAL_ALERT 모드에서 신호 감지 및 알림이 정상 전송되지 않는 문제 분석.
알림 파이프라인의 Silent Failure 5곳, 에러 핸들링 공백 4곳, 타이밍 이슈 2곳 발견 후 수정.

### P0 수정 (즉시 - 알림 전송 직접 차단)

| ID | 파일 | 변경 내용 |
|----|------|----------|
| F-1 | `notification_queue.py` | `send_func` None 시 CRITICAL 로그 + 카운터 + 10회 이상 큐 백업 |
| F-2 | `telegram.py` | `send_message()` 1회 재시도 (2초 딜레이, 총 2회 시도) |
| F-3 | `telegram.py` | Circuit Breaker OPEN 이벤트 파일 로깅 + `opens_today` 카운터 |
| F-4 | `position_sync_manager.py` | HTS 매수 시 `V7_PURPLE_REABS` 전략 매핑 (`register_position_strategy` 콜백) |

### P1 수정 (높은 우선순위 - 시스템 안정성)

| ID | 파일 | 변경 내용 |
|----|------|----------|
| F-5 | `notification_queue.py` | 큐 오버플로우 시 rate-limited 알림 (5분 간격) + 파일 로깅 |
| F-6 | `wave_harvest_exit.py` | 예외 시 `EXCEPTION_NOEXIT` reason 반환 (에러 정보 포함) |
| F-7 | `exit_coordinator.py` | `EXCEPTION_` 감지 시 CRITICAL 로그 + `exception_fallback` metadata |
| F-8 | `signal_processor.py` | 텔레그램 미초기화 시 CRITICAL 로그 + `logs/missed_signal_alerts.log` 기록 |

### 타이밍 수정

| ID | 파일 | 변경 내용 |
|----|------|----------|
| T-1 | `v7_signal_coordinator.py` | Pre-Check/Confirm-Check `if`/`if` → `if`/`elif` 상호배제 |
| T-2 | `signal_processor.py` | `signal_queue_max_age` 15초 → 30초 (설정 가능) |
| T-3 | `signal_processor.py` | 큐 만료 시 `conditions_met==5` 신호 파일 기록 |

### 통계 강화 (T-4)

- `notification_queue.py`: `get_stats()`에 `last_success_time`, `consecutive_failures`, `send_func_none_count` 추가
- `telegram.py`: `get_stats()` 신규 (CB 상태, `opens_today`, `failed_alerts_count`)

### 헬스 모니터링 (H-1~H-5)

- `system_health_monitor.py` 신규: 60초 주기 헬스 체크 (send_func, CB, DualPass, 알림루프, 큐 오버플로우)
- 15:30 일일 요약 리포트 자동 전송
- `/health` 텔레그램 명령어 추가
- `trading_engine.py`에 HealthCallbacks 연동

### 텔레그램 템플릿 정합성 수정 (templates.py)

| 항목 | 변경 내용 |
|----|----------|
| `format_help_message()` | ATR 배수 `6.0→4.0→...` → `6.0→4.5→4.0→...` (4.5 누락 수정) |
| `format_buy_notification()` | `PURPLE_REABS` → "Purple-ReAbs" 한글 매핑 추가 |
| `format_sell_notification()` | `EOD_CLOSE` → `END_OF_DAY`로 수정, `TARGET_PROFIT`/`MAX_HOLDING_DAYS`/`STRUCTURE_BREAK`/`MANUAL` 매핑 추가 |
| `format_signal_notification()` | `PURPLE_REABS` 전략명 처리 추가 |

### 신규 파일

- `src/core/system_health_monitor.py`: 시스템 헬스 모니터
- `tests/test_notification_fixes.py`: 수정사항 테스트 23개 (전체 PASS)

### V7 Immutables 검증

- Score 가중치: PASS
- PurpleOK 임계값: PASS
- Zone 허용 범위: PASS
- ATR 배수 단계: PASS
- Trend Hold Filter: PASS
- EMA adjust=False: PASS
- -4% 고정 손절: PASS
- TS 상향 전용: PASS
- parse_mode 금지: PASS

---

## 2026-02-05 - V7.1-Fix10 배포 (코드 리뷰 17건 + 초기화 순서 핫픽스)

### 배포 내용
- 코드 리뷰 Priority 1-3 수정 17건 프로덕션 배포
- `_risk_settings` 초기화 순서 버그 수정 (`trading_engine.py:279`)
  - `MarketMonitor` 생성(line 280)이 `get_risk_settings()`(line 379) 이전에 참조하여 `AttributeError` 발생
  - `get_risk_settings()` 호출을 line 279로 이동, 중복 호출 제거

---

## 2026-02-04 - 코드 리뷰 Priority 1+2+3 수정 (17건)

### 개요

6단계 전문 에이전트 코드 리뷰 (24,000줄, 38파일) 결과 44건 발견. Priority 1-3 총 17건 수정 완료.

### Priority 1 (Critical 6건) - 안전성 직결

| ID | 파일 | 수정 내용 |
|----|------|----------|
| C-01 | `wave_harvest_exit.py:628` | Hard Stop 비교 연산자 `<` → `<=` 통일 |
| C-02 | `exit_coordinator.py:183-220` | Hard Stop을 Circuit Breaker 이전으로 이동 (Risk-First) |
| C-03 | `wave_harvest_exit.py:618` | check_hard_stop() 파라미터 순서 BaseExit와 통일 (entry, current) |
| C-04 | `v7_signal_coordinator.py:508-511` | bar_close_time=None 가드 추가 |
| C-05 | `v7_signal_coordinator.py:430` | Confirm-Check 예외 로그 DEBUG → WARNING |
| C-09 | `market_schedule.py:67-68` | PRE_MARKET_START 계산 수정 (08:30→08:50) |
| C-11 | `background_task_manager.py:522` | _position_risks 스냅샷 접근 (RuntimeError 방지) |

### Priority 2 (5건) - 정확성/안정성

| ID | 파일 | 수정 내용 |
|----|------|----------|
| C-06 | `position_sync_manager.py`, `trading_engine.py` | PositionSync에 is_ordering_stock 콜백 추가 |
| C-08 | `client.py:83-93` | HALF_OPEN 단일 요청 제한 |
| M-01 | `wave_harvest_exit.py:591-592` | update_and_check()에 Hard Stop 선검사 추가 |
| M-05 | `indicator_purple.py:22-39` | PurpleConstants import로 상수 단일 소스화 |
| M-09 | `exit_coordinator.py`, `strategy_orchestrator.py`, `trading_engine.py` | position_strategies 공유 dict 통합 |

### Priority 3 (6건) - 성능/안정성/유지보수

| ID | 파일 | 수정 내용 |
|----|------|----------|
| C-10 | `market_schedule.py`, `config/holidays.json` (신규) | 공휴일 JSON 동적 로딩 + 현재 연도 미포함 경고 |
| M-02 | `ARCHITECTURE.md` | Trend Hold ATR 조건 문서화 |
| M-04 | `v7_signal_coordinator.py:403-430` | Confirm-Check 이중 계산 제거 (5/5 시만 detect_signal) |
| M-06 | `v7_signal_coordinator.py:99,265,387` | asyncio.gather Semaphore(20) 동시성 제한 |
| M-11 | `order_executor.py:223-229` | 주문 Lock 30초 타임아웃 추가 |
| M-14/15 | `background_task_manager.py` | 7개 배경 루프 CancelledError 처리 + _chunked_sleep 분할 |

### 신규 파일

- `config/holidays.json`: KRX 휴장일 데이터 (2025-2026)

### 테스트

- 381 passed, 0 failed

---

## 2026-02-04 - Phase 6 완료: TradingEngine 엔터프라이즈급 리팩토링

### 개요

TradingEngine god-class 리팩토링 Phase 6 완료. 버그 수정, 캡슐화, V7 변수 이동, 대형 핸들러 추출을 통해 3,975줄 → 3,108줄로 축소 (867줄 절감).

### 변경 내역

| 단계 | 파일 | 변경 내용 |
|------|------|----------|
| 6A | `strategy_orchestrator.py`, `trading_engine.py`, `watermark_manager.py` | 데드 코드 삭제, double-pop 수정, is_signal_time 기본값 09:05, 테스트 7건 수정 |
| 6B | `exit_coordinator.py`, `trading_engine.py` | `_v7_exit_states` 직접 접근 → `clear_all_v7_states()` 등 API 경유 |
| 6C | `trading_engine.py`, `v7_purple_reabs.py` | V7 인스턴스 변수 8개 → V7Strategy 캡슐화, `build_v7_callbacks` 이동 |
| 6D | `manual_command_handler.py` (신규), `trading_engine.py` | 수동 매매 13개 메서드 → ManualCommandHandler 추출 (~500줄) |
| 6E | `condition_search_handler.py` (신규), `trading_engine.py` | 조건검색 5개 메서드 → ConditionSearchHandler 추출 (~270줄) |

### 신규 파일

- `src/core/manual_command_handler.py`: StockMode, ManualStockConfig, ManualCommandCallbacks, ManualCommandHandler
- `src/core/condition_search_handler.py`: ConditionSearchCallbacks, ConditionSearchHandler

### TradingEngine 줄 수

- Phase 5 완료 후: 3,975줄
- Phase 6 완료 후: 3,108줄 (867줄 절감)
- 원본 대비: 5,078줄 → 3,108줄 (38.8% 축소)

### 테스트

- 381 passed, 0 failed (기존 7건 실패 모두 수정)

---

## 2026-02-04 - Phase 5 완료: Feature Flag 제거 + V7 레거시 정리

### 개요

V6/V7 전략 분리 리팩토링 Phase 5 완료. `_v7_enabled` 분기와 `USE_STRATEGY_ORCHESTRATOR` feature flag를 전부 제거하여 StrategyOrchestrator 경로를 유일한 경로로 확정.

### 변경 내역

| 단계 | 파일 | 변경 내용 |
|------|------|----------|
| 5-A | `trading_engine.py` | `_use_strategy_orchestrator` 변수 및 env var 삭제 |
| 5-B | `trading_engine.py` | 레거시 조건검색 경로 삭제 (~85줄) |
| 5-C | `trading_engine.py`, `v7_purple_reabs.py` | 레거시 shutdown 삭제, `async_shutdown()` 추가 |
| 5-D | `trading_engine.py` | stats/tier 이중 경로 삭제 |
| 5-E | `background_task_manager.py`, `trading_engine.py` | `set_v7_legacy()` 및 V7 레거시 경로 삭제 |
| 5-F | `exit_coordinator.py`, `trading_engine.py` | `_v7_enabled` 파라미터/변수/메서드/fallback 전부 삭제 |
| 5-G | `trading_engine.py` | `_v7_enabled` → 로컬 변수 전환 |
| 5-I | `trading_engine.py` | shutdown에서 `strategy.async_shutdown()` 사용 |

### 제거된 API

- `ExitCoordinator`: `v7_enabled` 파라미터, `set_v7_enabled()`, `is_v7_enabled()`, fallback 라우팅
- `BackgroundTaskManager`: `set_v7_legacy()`, `_v7_enabled`, `_v7_signal_coordinator`
- `TradingEngine`: `_v7_enabled` (인스턴스 변수), `_use_strategy_orchestrator`, `USE_STRATEGY_ORCHESTRATOR` env var

### TradingEngine 줄 수

- Phase 4 완료 후: 4,120줄
- Phase 5 완료 후: 3,975줄 (145줄 절감)
- 원본 대비: 5,078줄 → 3,975줄 (21.7% 축소)

### 테스트

- 375 passed, 7 failed (pre-existing)
- 영향받은 테스트 파일 수정 완료: `test_exit_coordinator.py`, `test_background_task_manager.py`

---

## 2026-02-03 - V7.1-Fix9: SignalPool `__len__` truthiness 버그 수정

### 개요

재시작 후 V7 Purple-ReAbs 신호 탐지가 전혀 실행되지 않는 치명적 버그 수정.
- 빈 SignalPool이 Python truthiness 체크에서 `False`로 평가되어 V7 경로 및 V6 Fallback 경로 모두 차단
- DualPass Pre-Check가 항상 pool_size == 0으로 즉시 반환, Purple 평가 실행 불가

### 근본 원인

`SignalPool.__len__()` (signal_pool.py:432) 구현으로 인해, 빈 Pool 객체가 `bool()` 평가 시 `False` 반환.
`trading_engine.py`에서 `if self._v7_signal_pool:` 형태의 truthiness 체크 7곳이 모두 실패하여:
1. 조건검색 신호 → SignalPool 등록 경로 차단
2. Pool이 영구적으로 비어있는 데드락 상태 발생

### 수정 내역

| 파일 | 변경 내용 | 위험도 |
|------|----------|--------|
| `trading_engine.py:626` | `get_pool_stock` 콜백 truthiness → `is not None` | 낮음 |
| `trading_engine.py:627` | `get_all_pool_stocks` 콜백 truthiness → `is not None` | 낮음 |
| `trading_engine.py:630` | `get_recent_pool_stocks` 콜백 truthiness → `is not None` | 낮음 |
| `trading_engine.py:1098` | V7 경로 판단 truthiness → `is not None` | **높음** |
| `trading_engine.py:1164` | V6 Fallback SignalPool 등록 truthiness → `is not None` | **높음** |
| `trading_engine.py:1694` | SignalPool cleanup truthiness → `is not None` | 낮음 |
| `trading_engine.py:4418` | Stats 보고 truthiness → `is not None` | 낮음 |

### 영향

- 2026-02-03 장중 재시작 후 약 5시간 동안 V7 Purple 신호 탐지 완전 무력화
- Active Pool에 13+ 종목이 있었음에도 SignalPool 등록 실패 → 알림 0건

---

## 2026-02-03 - V7.1-Fix8: 좀비 구독 감지 기능

### 개요

WebSocket 재연결 후 조건검색 실시간 구독이 성공(return_code=0)해도 실시간 신호가 오지 않는 '좀비 구독' 감지 및 자동 복구 기능 추가.

### 수정 내역

| 파일 | 변경 내용 |
|------|----------|
| `subscription_manager.py` | SubscriptionState.VERIFYING 상태, 좀비 구독 감지 로직, 자동 재구독 |

---

## 2026-02-02 - V7.1-Fix7: 손절(-4%) 미작동 문제 해결

### 개요

덕양에너젠(0001A0) 등 NXT 종목에서 -4% 이하로 하락해도 자동 손절이 작동하지 않는 문제 해결.
- 종목코드 정규화 버그 수정: NXT 코드 중간의 'A' 보존
- Fallback 손절 체크: V7 State 기반 긴급 손절 독립 실행
- Circuit Breaker 시간 단축: 10분 → 5분

### 근본 원인

1. **종목코드 정규화 버그**: `replace("A", "")`가 `0001A0` → `00010`으로 잘못 변환
2. **청산 체크 의존성**: PositionManager에 포지션이 없으면 청산 체크 스킵

### 수정 내역

| 파일 | 변경 내용 | 위험도 |
|------|----------|--------|
| `trading_engine.py` | Fallback 손절 체크 추가 | 중간 |
| `exit_coordinator.py` | 긴급 Hard Stop 메서드, CB 시간 단축 | 중간 |
| `market.py` | 종목코드 정규화 수정 | 중간 |
| `account.py` | 종목코드 정규화 수정 | 중간 |
| `order.py` | 종목코드 정규화 수정 | 중간 |
| `websocket.py` | 종목코드 정규화 수정 | 중간 |
| `candle_builder.py` | 종목코드 정규화 수정 | 중간 |

### Phase 0: 종목코드 정규화 수정

**문제:**
```python
# 기존: 모든 'A' 제거
stock_code = stock_code.replace("A", "")
# A0001A0 → 00010 (잘못된 코드!)
```

**수정:**
```python
# 수정: 앞의 'A'만 제거
if stock_code.startswith("A"):
    stock_code = stock_code[1:]
# A0001A0 → 0001A0 (올바른 코드)
```

**적용 파일:**
- `src/api/endpoints/market.py`: get_stock_info, get_quote, get_minute_chart, get_daily_chart
- `src/api/endpoints/account.py`: has_position, get_position, get_execution_info
- `src/api/endpoints/order.py`: buy, sell, modify, cancel
- `src/api/websocket.py`: TickData.from_ws_data, subscribe_tick, unsubscribe_tick
- `src/core/candle_builder.py`: Tick.from_ws_data

### Phase 1: Fallback 손절 체크

**파일:** `src/core/trading_engine.py:4242-4254`

```python
# 2. 포지션 현재가 업데이트 및 손절/익절 체크
has_position = self._position_manager.has_position(code)
has_v7_state = self._exit_coordinator and self._exit_coordinator.has_v7_state(code)

if has_position:
    self._position_manager.update_price(code, price_data.current_price)
    await self._check_position_exit(code, price_data.current_price)
elif has_v7_state:
    # [Critical] Fallback 손절 체크: V7 State는 있지만 PositionManager에 없는 경우
    await self._fallback_hard_stop_check(code, price_data.current_price)
```

**파일:** `src/core/exit_coordinator.py:537-567`

```python
def check_emergency_hard_stop(self, stock_code: str, current_price: int) -> bool:
    """V7 State 기반 긴급 손절 체크 (PositionManager 독립)"""
    state = self._v7_exit_states.get(stock_code)
    if not state:
        return False

    stop_price = state.get_fallback_stop()  # -4%
    return current_price <= stop_price
```

### Phase 2: Circuit Breaker 시간 단축

**파일:** `src/core/exit_coordinator.py:144`

```python
# 변경 전
self._block_duration_minutes: int = 10  # 10분간 재시도 방지

# 변경 후
self._block_duration_minutes: int = 5  # 5분간 재시도 방지 (10분→5분 단축)
```

### 테스트 결과

- 종목코드 정규화 테스트: 통과
- exit_coordinator 테스트: 22개 전부 통과

---

## 2026-02-02 - V7.1-Fix6: 신규 상장 종목 캔들 안전장치

### 개요

신규 상장 종목(예: 덕양에너젠 0001A0)의 캔들 데이터 부족 문제에 대한 안전장치 구현.
- 캔들 400개 미달 시에도 60개 이상이면 신호 탐지 활성화
- Hard Stop(-4%)은 캔들 수와 무관하게 항상 작동 (Risk-First 준수)

### 수정 내역

| 파일 | 변경 내용 | 위험도 |
|------|----------|--------|
| `exit_coordinator.py` | 로깅 레벨 debug→info, 메시지 개선 | 낮음 |
| `realtime_data_manager.py` | 동적 캔들 검증 로직 추가 | 중간 |

### Phase 1: 로깅 강화

**파일:** `src/core/exit_coordinator.py:430-436`

```python
# 기존: debug 레벨, 불명확한 메시지
self._logger.debug(f"[ExitCoordinator] 캔들 데이터 부족: {stock_code}")

# 수정: info 레벨, 상태 명확화
candle_count = len(candles) if candles is not None else 0
self._logger.info(
    f"[ExitCoordinator] 신규 상장 모드: {stock_code} | "
    f"캔들 {candle_count}개 | ATR TS 비활성화, Hard Stop (-4%) 보호 중"
)
```

### Phase 2: 동적 캔들 검증

**파일:** `src/core/realtime_data_manager.py:407-453`

```python
# 상수 추가
NEW_LISTING_THRESHOLD = 390   # 신규 상장 임계값 (약 3일 * 130봉/일)
MIN_CANDLES_FOR_NEW_LISTING = 60  # V7 신호 탐지 최소 요구량

# 검증 로직
if len(candles_3m) < candle_count * MIN_CANDLES_RATIO:
    # 신규 상장 종목 판별: 400개 미만이지만 60개 이상이면 활성화
    if len(candles_3m) < NEW_LISTING_THRESHOLD and len(candles_3m) >= MIN_CANDLES_FOR_NEW_LISTING:
        estimated_days = len(candles_3m) // 130 if candles_3m else 0
        self._logger.info(
            f"[캔들 검증] {stock_code} 신규 상장 모드 (약 {estimated_days}일차) | "
            f"캔들 {len(candles_3m)}개 | 신호 탐지 활성화"
        )
        is_valid = True
```

### 캔들 요구사항 정리

| 항목 | 최소 캔들 | 비고 |
|------|----------|------|
| Config 기본값 | 800 | candle_history_count |
| 캔들 로딩 검증 | 400 (50%) → **60개 신규 상장 모드** | 동적 완화 |
| V7 신호 탐지 | 60 | signal_detector_purple.py |
| V7 Score 계산 | 70 | signal_detector_purple.py |
| ATR TS 계산 | 20 | exit_coordinator.py |

---

## 2026-01-29 - V7.0-Fix6: Critical/Major 버그 수정 (코드 리뷰 Phase 1-2, 2, 3)

### 개요

V7.0 종합 코드 리뷰 보고서 기반 추가 버그 수정 (6건)
- Phase 1-2: C-003 역순 Tick 처리
- Phase 1-6: C-009 VI Lock
- Phase 2: M-001, M-002
- Phase 3-1, 3-2: 성능 개선

### 수정 내역

| ID | 우선순위 | 이슈 | 수정 내용 |
|----|----------|------|----------|
| C-003 | Critical | 역순 Tick 처리 오류 | 틱 버퍼링 + 시간순 정렬 |
| C-009 | Critical | VI Lock과 async 혼용 | `threading.RLock` → `asyncio.Lock` |
| M-001 | Major | 토큰 갱신 실패 처리 | 3회 재시도 + Exception 전파 |
| M-002 | Major | REG 응답 검증 부재 | pending/subscribed 상태 분리 |
| - | Improve | Queue Full 로깅 과다 | 배치 로깅 (100회마다) |
| M-007 | Major | API 호출 중복 | 캔들 60개↑ 시 API 스킵 |

### C-003: 역순 Tick 버퍼링

**문제:** 네트워크 지연으로 틱이 역순 도착 시 봉 경계 오인식

**수정:**
```python
# src/core/candle_builder.py
class CandleBuilder:
    def __init__(self):
        self._last_tick_time: Optional[datetime] = None
        self._out_of_order_count: int = 0

    def on_tick(self, tick: Tick):
        # 역순 틱 감지
        if self._last_tick_time and tick.timestamp < self._last_tick_time:
            is_out_of_order = True
            # 역순 틱이 봉 완성 트리거 방지

class CandleManager:
    TICK_BUFFER_SIZE = 50
    TICK_BUFFER_FLUSH_MS = 100

    async def _flush_buffer(self):
        # 시간순 정렬 후 처리
        ticks_to_process.sort(key=lambda t: t.timestamp)
```

### C-009: VI Lock → asyncio.Lock

**문제:** `threading.RLock`을 async 콜백에서 사용 시 Event Loop 블록

**수정:**
```python
# src/core/trading_engine.py
self._vi_lock = asyncio.Lock()  # 기존: threading.RLock()

async def _is_vi_active(self, stock_code: str) -> bool:
    async with self._vi_lock:
        ...

# src/core/exit_manager.py, signal_processor.py
# 관련 콜백 타입 Callable[[str], Awaitable[bool]]로 변경
```

### M-001: 토큰 갱신 재시도

**문제:** 토큰 갱신 실패 시 warning 로깅 후 계속 진행 → 무한 실패

**수정:**
```python
# src/api/websocket.py
TOKEN_REFRESH_RETRIES = 3
for retry in range(TOKEN_REFRESH_RETRIES):
    try:
        await self._token_manager.invalidate_and_refresh()
        break
    except Exception as e:
        if retry < TOKEN_REFRESH_RETRIES - 1:
            await asyncio.sleep(2.0)  # 재시도
        else:
            raise RuntimeError("토큰 갱신 실패") from e
```

### M-002: REG 응답 검증

**문제:** REG 요청 후 바로 성공 처리, 실제 응답 기반 상태 업데이트 없음

**수정:**
```python
# src/api/websocket.py
self._pending_reg_stocks: Set[str] = set()

async def subscribe_tick(self, stock_codes):
    await self._send(msg)
    self._pending_reg_stocks.update(codes)  # pending으로 추가

# REG 응답 처리
if return_code == 0:
    self._subscribed_stocks.update(self._pending_reg_stocks)
    self._pending_reg_stocks.clear()
```

### Files Modified

| 파일 | 변경 내용 |
|------|----------|
| src/core/candle_builder.py | 역순 틱 감지, 버퍼링, Queue Full 배치 로깅 |
| src/core/trading_engine.py | VI Lock asyncio 변환, API 호출 조건부 실행 |
| src/core/exit_manager.py | is_vi_active_fn async 타입 변경 |
| src/core/signal_processor.py | can_execute_trade async 타입 변경 |
| src/api/websocket.py | 토큰 갱신 재시도, REG 응답 검증 |

---

## 2026-01-28 - V7.0-Fix5: Critical 버그 수정 (코드 리뷰 Phase 1)

### 개요

V7.0 종합 코드 리뷰 보고서 기반 Critical/Major 버그 수정 (6건)

### 수정 내역

| ID | 우선순위 | 이슈 | 수정 내용 |
|----|----------|------|----------|
| C-006 | Critical | 타임존 혼재 (KST/UTC) | `datetime.now()` → `datetime.now(KST)` |
| C-001 | Critical | WebSocket 동시 재연결 Race Condition | Lock 내에서 즉시 `_is_reconnecting=True` |
| C-002 | Critical | Score NaN 신호 누락 | `MIN_CANDLES_FOR_SCORE=70` + NaN 검증 |
| C-007 | Critical | 동일 봉 중복 신호 | `StockInfo._signal_lock` + 원자적 업데이트 |
| M-003 | Major | Enqueue 실패 시 알림 손실 | Direct send fallback 추가 |
| M-004 | Major | 재연결 대기 시간 과다 | 3초→1초, 5초→2초 단축 |

### C-006: 타임존 혼재 수정

**문제:** AWS UTC 서버에서 `datetime.now()`가 UTC 반환 → 봉 경계 9시간 어긋남

**수정:**
```python
# src/core/candle_builder.py
from datetime import timezone, timedelta
KST = timezone(timedelta(hours=9))

# Tick 시간 파싱
now = datetime.now(KST)  # 기존: datetime.now()
```

### C-001: WebSocket 동시 재연결 방지

**문제:** Heartbeat + receive_loop 동시 재연결 감지 시 Race Condition

**수정:**
```python
# src/api/websocket.py:600-612
async def _reconnect(self) -> None:
    # C-001 FIX: Lock 획득 후 즉시 플래그 설정
    async with self._reconnect_lock:
        if self._is_reconnecting:
            return
        self._is_reconnecting = True  # Lock 내에서 즉시 설정
```

### C-002: Score NaN 신호 누락 방지

**문제:** 캔들 70봉 미만에서 Score 계산 시 NaN → `NaN > NaN = False`로 False Negative

**수정:**
```python
# src/core/signal_detector_purple.py
MIN_CANDLES_FOR_SCORE = 70  # 기존: 20

def check_reabs_start(self, df, stock_code=""):
    if len(df) < MIN_CANDLES_FOR_SCORE:
        return False
    # NaN 검증 추가
    if pd.isna(curr_score) or pd.isna(prev_score):
        return False
```

### C-007: 동일 봉 중복 신호 방지

**문제:** 병렬 Confirm-Check에서 동일 봉에 중복 신호 발생 가능

**수정:**
```python
# src/core/signal_pool.py
@dataclass
class StockInfo:
    _signal_lock: threading.Lock = field(default_factory=threading.Lock)

    def update_signal_bar(self, bar_close_time) -> bool:
        with self._signal_lock:
            if bar_close_time <= self.last_signal_bar:
                return False  # 이미 같은 봉에서 신호
            self.last_signal_bar = bar_close_time
            return True
```

### Files Modified

| 파일 | 변경 위치 | 내용 |
|------|----------|------|
| src/core/candle_builder.py | line 11, 21-22, 51-54 | KST 타임존 명시적 사용 |
| src/api/websocket.py | line 600-612 | 동시 재연결 Race Condition 수정 |
| src/core/signal_detector_purple.py | line 37, 454-476 | Score NaN 검증 추가 |
| src/core/signal_pool.py | line 45, 67-90 | update_signal_bar Lock 추가 |
| src/core/v7_signal_coordinator.py | line 505-517, 548-554 | 중복 신호 차단, Enqueue fallback |
| src/core/subscription_manager.py | line 108, 389 | 재연결 대기 시간 단축 |

---

## 2026-01-27 - V7.0-Fix4: CandleBuilder False Hard Stop 수정

### 이슈: 켄코아에어로스페이스(274090) 잘못된 손절

**증상:**
- 진입가: 25,150원, 손절가: 24,144원 (-4%)
- 3분봉: O=23,800 H=25,900 L=23,800 C=25,400
- Hard Stop 트리거: check_price(23,800) < stop(24,144)
- 실제 매도가: 25,262원 (+0.45% **수익**)

**문제:**
1분봉 Low 값들 (25,050, 24,700, 25,200) 중 23,800원인 봉이 없음. 3분봉의 Open/Low가 API 과거 데이터에서 오염됨.

**원인 분석:**
```
09:51:48  HTS 매수 감지 → Tier 1 승격
09:51:54  800개 캔들 API 로드
          └─ 마지막 3분봉(09:51:00)이 _current_candles로 설정
          └─ 이 캔들의 O=23,800, L=23,800은 stale 데이터
09:52:XX  첫 틱 도착 (25,100원)
          └─ candle_start(09:51) == current.time(09:51)
          └─ OHLC 업데이트만 수행 (Open 유지)
09:54:06  3분봉 완성: O=23,800, L=23,800 (잘못된 값!)
          └─ Hard Stop 트리거
```

**수정 (V7.0-Fix4):**
```python
# src/core/candle_builder.py:205-226
def on_tick(self, tick: Tick) -> Optional[List[Candle]]:
    ...
    else:
        # V7.0-Fix4: 과거 API 데이터로 초기화된 캔들이면 OHLC 리셋
        if current.is_complete:  # 과거 API 데이터
            current.open = tick.price   # 첫 실시간 틱으로 리셋
            current.high = tick.price
            current.low = tick.price
            current.close = tick.price
            current.volume = tick.volume
            current.is_complete = False
        else:
            # 기존 봉 업데이트
            current.high = max(current.high, tick.price)
            ...
```

### Files Modified

| 파일 | 변경 위치 | 내용 |
|------|----------|------|
| src/core/candle_builder.py | line 205-226 | 과거 캔들 OHLC 리셋 로직 |

### Verification

예상 로그:
```
[V7.0-Fix4] 274090 3m: 과거 캔들 OHLC 리셋 (old=23800 → new=25100)
```

---

## 2026-01-26 - V7 버그 수정: 6필터 스킵 + Tier 강등 조건 강화

### 이슈 1: SIGNAL_ALERT 모드 6필터 스킵

**문제:** V7 SIGNAL_ALERT 모드에서 SignalPool 등록 후 불필요한 AutoScreener 6필터 실행으로 혼란스러운 로그 출력

**수정:**
```python
# src/core/trading_engine.py:898-902
if self._risk_settings.trading_mode == TradingMode.SIGNAL_ALERT:
    return  # SignalPool 등록만 하고 6필터 스킵
```

### 이슈 2: HTS 매수 종목 Tier 2 조기 강등 버그

**증상:** 064260 다날 캔들 완성 11:00:53 이후 중단, ATR 트레일링 스탑 배수 미조정

**원인:** AutoScreener ranking update(60초)와 Position sync(60초) 간 race condition
- HTS 매수 → Active Pool 이탈 → Position sync 전 Tier 2 강등 → 캔들 완성 중단

**수정:**
```python
# src/core/trading_engine.py:3941-3946
# V7 Exit State 있으면 Tier 1 유지 (HTS 매수 포함)
if self._v7_enabled and stock_code in self._v7_exit_states:
    self._logger.debug(f"[V6.2-R] Active 강등 스킵 (V7 Exit State): {stock_code}")
    continue
```

### Files Modified

| 파일 | 변경 위치 | 내용 |
|------|----------|------|
| src/core/trading_engine.py | line 898-902 | V7 SIGNAL_ALERT 조기 반환 |
| src/core/trading_engine.py | line 3941-3946 | V7 Exit State 체크 추가 |

### Verification

예상 로그:
```
[V6.2-R] Active 강등 스킵 (V7 Exit State): 064260
[봉완성] 064260 - 캔들 완성
```

---

## 2026-01-25 - V7 장 초반 신호 처리 개선

### Background (배경)

첫 봉(09:00~09:03) 신호가 100% 유실되는 Critical 이슈 해결. Throttle 로직이 신호를 큐에만 저장하고 SignalPool에 등록하지 않아 Dual-Pass 탐지 대상에서 누락되는 문제 수정.

### Phase 1: Throttle 제거 [Critical]

| 삭제 항목 | 설명 |
|----------|------|
| `_opening_signal_queue` | 장 시작 신호 저장 큐 |
| `_opening_queue_task` | 큐 처리 태스크 |
| `_is_market_opening_period()` | 09:00~09:05 판별 메서드 |
| `_queue_opening_signal()` | 큐 저장 메서드 |
| `_process_opening_queue()` | 큐 순차 처리 메서드 |

**이유:** `KiwoomAPIClient.RateLimiter`가 이미 API 부하 관리 중이므로 별도 Throttle 불필요

### Phase 2: 신호 탐지 시작 시간 09:00

| 파일 | 변경 |
|------|------|
| config.py | `signal_start_time` 기본값 "09:05" → "09:00" |
| watermark_manager.py | `is_signal_time()` 기본값 time(9, 5) → time(9, 0) |

### Phase 3: 캔들 로딩 보장

| 추가 항목 | 설명 |
|----------|------|
| `_ensure_candle_loaded_v7()` | SignalPool 등록 후 즉시 캔들 로딩 (5초 타임아웃) |

SignalPool 등록 시 캔들이 없으면 Pre-Check/Confirm-Check에서 무음 스킵되는 문제 해결

### Phase 4: Late-Arriving Signal 처리

| 추가 항목 | 설명 |
|----------|------|
| `get_recent_stocks()` | SignalPool에서 최근 30초 내 등록 종목 조회 |
| Confirm-Check 확장 | Pre-Check 후보 + Late-Arriving 종목 통합 검사 |

봉 완성 직전(예: 09:02:50) 도착 신호도 다음 Confirm-Check에서 처리 가능

### Expected Impact (예상 효과)

| 시나리오 | Before | After |
|----------|--------|-------|
| 09:00:30 신호 → 첫 Confirm | 09:06:00 (5.5분) | 09:03:00 (2.5분) |
| 첫 봉 신호 탐지율 | 0% | ~100% |

### Files Modified (수정된 파일)

| 파일 | 변경량 | 주요 변경 |
|------|--------|----------|
| src/core/trading_engine.py | -50줄 | Throttle 제거, 캔들 로딩 보장, Late-Arriving |
| src/utils/config.py | 0줄 | signal_start_time 기본값 변경 |
| src/core/watermark_manager.py | 0줄 | is_signal_time() 기본값 변경 |
| src/core/signal_pool.py | +20줄 | get_recent_stocks() 추가 |

### Verification (검증)

배포 후 예상 로그:
```
[V7.0] SignalPool 등록: 삼성전자(005930) (Pool: 1개, 캔들: OK)
[V7.0] Pre-Check 시작 (SignalPool: 15개)
[V7.0] Confirm-Check 시작 (Pre-Check: 5개, Late: 2개)
```

### Rollback (롤백)

```bash
# .env에 추가하여 기존 동작 복원
SIGNAL_START_TIME=09:05
```

---

## 2026-01-25 - V7.0 코드 품질 점검 P0/P1 수정

### Background (배경)

전문 에이전트 코드 리뷰에서 V7 Purple-ReAbs 시스템의 동시성 문제, 알림 손실 추적 불가, 메모리 관리 미흡 등의 이슈 발견. 총 8개의 수정 사항(P0: 4개, P1: 4개)과 문서 수정 1건 적용.

### Critical Fixes - P0 (즉시 수정)

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| P0-1 | notification_queue.py | threading.RLock이 async context에서 이벤트 루프 블로킹 | asyncio.Lock 추가 (듀얼 Lock 구조) |
| P0-2 | notification_queue.py | 큐 오버플로우 시 알림 손실 추적 불가 | 손실 기록 및 _dropped_count 추가 |
| P0-3 | signal_detector_purple.py | _pending_candidates Race Condition | threading.RLock 추가 |
| P0-4 | trading_engine.py | VI 상태, pending_sell_orders 동시 접근 | _vi_lock, _pending_sell_lock 추가 |

### Major Fixes - P1 (중기 개선)

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| P1-1 | notification_queue.py | 쿨다운 스킵 DEBUG 로깅 | INFO 레벨 변경, _cooldown_skipped_count 추가 |
| P1-2 | trading_engine.py | Pre-Check 에러가 DEBUG 레벨 | WARNING 레벨 변경 |
| P1-3 | telegram.py | 연속 실패 시 Circuit Breaker 미구현 | Circuit Breaker 패턴 추가 (5회 실패 시 300초 차단) |
| P1-4 | signal_pool.py | TTL/크기 제한 없음 | 24시간 TTL, 10,000개 최대 크기 제한, 자동 eviction |

### Documentation (문서)

| 파일 | 수정 내용 |
|------|----------|
| signal_detector_purple.py | Pre-Check 조건 "4개 중 3개" → "5개 중 3개" 수정 |

### Files Modified (수정된 파일)

| 파일 | 주요 변경 |
|------|----------|
| src/notification/notification_queue.py | 듀얼 Lock, 손실/쿨다운 카운터 |
| src/core/signal_detector_purple.py | _candidates_lock, _results_lock, 문서 수정 |
| src/core/trading_engine.py | _vi_lock, _pending_sell_lock, 로깅 레벨 |
| src/core/exit_manager.py | pending_sell_lock 파라미터화 |
| src/notification/telegram.py | Circuit Breaker 상태 및 메서드 |
| src/core/signal_pool.py | MAX_POOL_SIZE, POOL_TTL_HOURS, eviction |

### Verification (검증)

- 배포 후 `/status` 명령어로 Circuit Breaker 상태 확인
- 알림 큐 오버플로우 로그: `[알림 손실]` 패턴
- SignalPool 통계에 evicted_count, expired_count 추가

---

## 2026-01-23 - P0 버그 수정: DataFrame 타입 불일치

### Background (배경)

전문 에이전트 코드 리뷰에서 V7.0 신호 탐지가 전혀 작동하지 않는 치명적 버그 발견.
`CandleManager.get_candles()`가 `pd.DataFrame`을 반환하는데, 코드에서 이를 `Candle` 객체 리스트처럼 iterate하여 `AttributeError` 발생.

### Fixed (수정)

| Issue | 문제 | 수정 |
|-------|------|------|
| P0 | `_v7_run_pre_check()` DataFrame을 Candle 리스트로 잘못 처리 | DataFrame 직접 사용으로 변경 |
| P0 | `_v7_run_confirm_check()` 동일한 버그 | DataFrame 직접 사용으로 변경 |

### Files Modified (수정된 파일)

| 파일 | 라인 | 변경 내용 |
|------|------|----------|
| src/core/trading_engine.py | 5420-5429 | Pre-Check DataFrame 변환 코드 제거 |
| src/core/trading_engine.py | 5505-5508 | Confirm-Check DataFrame 변환 코드 제거 |

### 수정 전/후

```python
# 수정 전 (버그)
candles = self._candle_manager.get_candles(stock_code, Timeframe.M3)
if not candles or len(candles) < 60:
    continue
df = pd.DataFrame([{
    'open': c.open,  # c가 컬럼명 문자열이라 AttributeError
    'high': c.high,
    ...
} for c in candles])

# 수정 후 (정상)
df = self._candle_manager.get_candles(stock_code, Timeframe.M3)
if df is None or len(df) < 60:
    continue
# df 바로 사용
```

### Verification (검증)

- 로컬 테스트: 87개 중 86개 통과 (1개 무관한 실패)
- 서버 배포: 정상 재시작 확인
- 장중 검증 필요: `[V7 PreCheck] 검사 N개, 후보 M개 | 샘플(P/T/Z/R/Tr): ...` 로그 확인

---

## 2026-01-22 - 컨텍스트 관리 자동화 시스템

### Background (배경)

Claude 세션 간 메모리가 없어 작업 컨텍스트가 유실되는 문제. CLAUDE.md에 강제 규칙을 추가하고, 관련 스킬/명령어를 정비하여 작업 완료 시 항상 컨텍스트가 업데이트되도록 시스템화.

### Added (추가)

| 파일 | 추가 항목 | 설명 |
|------|----------|------|
| `.claude/skills/task-complete/SKILL.md` | 신규 스킬 | 작업 완료 시 체계적 컨텍스트 업데이트 |
| `CLAUDE.md` Part 1.1 | 금지사항 | "업데이트 없이 완료 선언 금지" |
| `CLAUDE.md` Part 4.4 | 컨텍스트 관리 섹션 | 필수 단계, 트리거, 자기 점검 |

### Changed (변경)

| 파일 | 변경 내용 |
|------|----------|
| `.claude/commands/work-log.md` | 템플릿 강화, 절차 명시, 참조 추가 |
| `.claude/skills/core-workflow.md` | "작업 후" 섹션 전면 개편 (체크리스트, 금지 규칙, 완료 보고 형식) |
| `.claude/skills/context-loader/SKILL.md` | 날짜 검증 추가 (3일 이상 경고) |

### Files Modified (수정된 파일)

| 파일 | 라인 | 변경 내용 |
|------|------|----------|
| CLAUDE.md | 19 | 금지사항 테이블에 컨텍스트 규칙 추가 |
| CLAUDE.md | 174-214 | Part 4.4 전면 개편 |
| .claude/skills/task-complete/SKILL.md | (신규) | 작업 완료 스킬 |
| .claude/commands/work-log.md | 전체 | 템플릿/절차 강화 |
| .claude/skills/core-workflow.md | 55-116 | 작업 후 섹션 강화 |
| .claude/skills/context-loader/SKILL.md | 21-33 | 날짜 검증 추가 |

---

## 2026-01-20 - V6.2-R: Active Pool = Tier 1 자동 승격

### Background (배경)

1/19 로그 분석 중 CandleBuilder 콜백 누락 발견. 117730(티로보틱스)이 Active Pool에 있음에도 불구하고 Tier 2로 유지되어 16분 간격으로만 봉완성 발생.

**근본 원인:**
- Active Pool 등록 시 Tier 1 자동 승격 로직 누락
- `_setup_stock_data()` 메서드 호출하지만 메서드 정의 없음 (AttributeError 무시)
- Tier 2 종목은 폴링 없음 → API 주기적 호출 시에만 데이터 갱신

### Added (추가)

| 파일 | 추가 항목 | 설명 |
|------|----------|------|
| auto_screener.py | `_on_active_pool_changed` 콜백 속성 | Active Pool 변경 시 호출될 콜백 |
| auto_screener.py | `set_active_pool_callback()` 메서드 | 콜백 등록용 setter |
| trading_engine.py | `_on_active_pool_changed()` 메서드 | Tier 승격/강등 처리 핸들러 |

### Changed (변경)

| 파일 | 변경 내용 |
|------|----------|
| auto_screener.py | `_update_active_pool()`에서 콜백 호출 추가 |
| trading_engine.py | init에서 `set_active_pool_callback()` 등록 |
| trading_engine.py | `_register_promoted_watchlist_stock()` 버그 수정 - 실제 로직 구현 |

### Fixed (수정)

| Issue | 문제 | 수정 |
|-------|------|------|
| BUG-1 | `_setup_stock_data()` 메서드 누락 (AttributeError 무시) | CandleBuilder 생성 + Tier 등록 로직으로 교체 |
| BUG-2 | Active Pool 변경 시 Tier 변경 안 됨 | 콜백 메커니즘으로 자동 승격/강등 |
| BUG-3 | Tier 2 종목 16분 간격 봉완성 | Active Pool = Tier 1 보장 |

### Tier 동작 (변경 후)

```
Active Pool 진입 → Tier 1 자동 승격 (0.3초 폴링)
Active Pool 이탈 → Tier 2 강등 (포지션 보유 시 Tier 1 유지)
포지션 오픈 → Tier 1 유지
```

### 성능 분석

| 항목 | 값 |
|------|-----|
| 최대 Tier 1 종목 수 | 60~70개 (SIGNAL_ALERT 모드) |
| 폴링 사이클 | 21.5초 (70개 × 0.3초 + 0.5초) |
| 최대 감지 지연 | 21초 |
| 3분봉 대비 지연율 | 12% |
| 슬리피지 추정 | 0.04~0.12% (최악의 경우) |

### 향후 개선 가능 (미구현)

| ID | 개선 항목 | 효과 | 복잡도 |
|----|----------|------|--------|
| IMP-1 | WebSocket 실시간 틱 활용 | 21초 → <1초 | 중간 |
| IMP-2 | 폴링 간격 0.3초→0.2초 | 21초 → 14.5초 | 낮음 |
| IMP-3 | 우선순위 폴링 | 중요 종목 먼저 | 높음 |
| IMP-4 | 배치 API 호출 | 70개→1~2개 | 높음 |

### Files Modified (수정된 파일)

| 파일 | 변경 내용 |
|------|----------|
| src/core/auto_screener.py | Active Pool 변경 콜백 메커니즘 추가 |
| src/core/trading_engine.py | Tier 승격/강등 핸들러, 버그 수정 |

---

## 2026-01-16 - V6.2-Q: Floor Line / Ceiling Break 코드 삭제

### Background (배경)

Floor Line과 Ceiling Break 전략은 V6.2-A에서 비활성화되어 사용되지 않음.
코드베이스 정리 및 신호 처리 로직 단순화를 위해 관련 코드 전체 삭제.

### Deleted (삭제)

| 파일 | 삭제 항목 | 설명 |
|------|----------|------|
| signal_detector.py | `CeilingBreakDetector` 클래스 | 천장 파괴 전략 (~113줄) |
| signal_detector.py | `CEILING_BREAK` enum | StrategyType에서 제거 |
| indicator.py | `ceiling()` 함수 | N봉 중 최고가 |
| indicator.py | `floor()` 함수 | N봉 중 최저가 |
| indicator.py | `floor_line()` 함수 | Lowest(L, period) |
| trading_engine.py | `_calculate_floor_line_for_hts()` | HTS 매수 Floor Line 계산 (~83줄) |
| trading_engine.py | 갭 손절 로직 | Floor Line 기반 장 시작 갭 손절 |
| risk_manager.py | `stop_loss_price` 필드 | PositionRisk에서 제거 |
| risk_manager.py | `entry_floor_line` 필드 | PositionRisk에서 제거 |
| risk_manager.py | `update_stop_loss_price()` | Floor Line 업데이트 함수 |

### Changed (변경)

- **risk_manager.py** - `on_entry()` 시그니처 수정
  - 제거: `stop_loss_price`, `floor_line` 파라미터
  - 유지: `entry_price`, `quantity`, `is_partial_exit`, `highest_price`, `entry_source`

- **risk_manager.py** - `rollback_partial_exit()` 시그니처 수정
  - 제거: `original_stop_loss` 파라미터

- **order_executor.py** - Signal metadata에서 `floor_line`, `stop_loss_price` 제거

- **repository.py** - `create()` 파라미터 수정
  - 제거: `stop_loss_price`, `entry_floor_line` 파라미터
  - DB 컬럼은 유지 (추후 마이그레이션 예정)

- **__init__.py** - `CeilingBreakDetector` export 제거

### Exit Logic (청산 로직 - 변경 후)

```
1. Safety Net: bar_low <= entry_price × 0.96 (-4%)
2. ATR Trailing Stop: close <= trailing_stop_price
3. Max Holding: 60일 초과
```

> Floor Line 기반 기술적 손절이 제거되고, Safety Net(-4%)이 기본 손절 역할 수행

### Files Modified (수정된 파일)

| 파일 | 변경 내용 |
|------|----------|
| src/core/signal_detector.py | CeilingBreakDetector 삭제, metadata 정리 |
| src/core/indicator.py | ceiling, floor, floor_line 함수 삭제 |
| src/core/risk_manager.py | on_entry 시그니처, PositionRisk 필드 정리 |
| src/core/order_executor.py | floor_line 코드 삭제 |
| src/core/trading_engine.py | _calculate_floor_line_for_hts 삭제, 갭 손절 삭제 |
| src/database/repository.py | create() 파라미터 삭제 |
| src/core/__init__.py | CeilingBreakDetector export 제거 |

### Notes

- DB 컬럼 (`stop_loss_price`, `entry_floor_line`)은 유지하여 기존 데이터 호환성 보장
- HTS/수동 매수 시 Safety Net(-4%)만 사용하도록 단순화
- 텔레그램 알림에서 손절가 표시: "🛡️ 손절가: X원 (-4%)"

### Patch 1 (2026-01-17 00:18 KST)

V6.2-Q 초기 배포 후 코드 리뷰에서 발견된 Critical Issues 긴급 수정.

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| C1 | exit_manager.py:321 | `position_risk.stop_loss_price` 참조 (삭제된 필드) | 해당 라인 삭제 |
| C2 | exit_manager.py:370-375 | `rollback_partial_exit()` 5개 인자 전달 (새 시그니처: 4개) | `original_stop_loss` 인자 제거 |
| C3 | risk_manager.py | `check_breakeven_protection()` 함수가 `breakeven_activated` 필드 참조 (미정의) | 함수 전체 삭제 (미사용 기능) |

**삭제된 코드:**
- `check_breakeven_protection()` 함수 (~80줄) - 정의만 존재하고 호출되지 않는 미사용 코드
- `config.py` - `breakeven_enabled`, `breakeven_trigger_rate` 설정 삭제
- `risk_manager.py RiskConfig` - `breakeven_enabled`, `breakeven_exit_rate`, `breakeven_trigger_rate` 필드 삭제

### Patch 2 (2026-01-17 KST)

V6.2-Q Floor Line/Ceiling Break 삭제 후 잔존 참조 및 런타임 버그 수정.

#### Critical Issues (5건)

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| C1 | repository.py, exit_manager.py | `update_partial_exit()`에서 `new_stop_loss_price` 파라미터 참조 (삭제된 기능) | 파라미터 완전 제거 |
| C2 | trading_engine.py:503 | `condition_list` NoneType 순회 시 TypeError | `condition_list and any(...)` short-circuit 평가 적용 |
| C3 | trading_engine.py:677 | `atr_alert_seq` 타입 불일치 (str "0" vs int 비교) | int 0으로 통일, `int(signal.condition_seq)` 비교 |
| C4 | trading_engine.py:1947 | `_telegram` None 상태에서 send_message 호출 | None 체크 후 호출 |
| C5 | trading_engine.py:1872-1898 | 신호 큐 만료 처리 중 쿨다운 break로 메모리 누수 | `break` -> `continue`로 만료 신호 정리 계속 |

#### Warning Issues (2건)

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| W4 | risk_manager.py:829 | `on_exit()` 블랙리스트에 `TRAILING_STOP` 누락 | 블랙리스트에 `TRAILING_STOP` 추가 |
| W5 | trading_engine.py:1931-1935 | SIGNAL_ALERT 모드에서 큐 신호 자동매수 실행 | 모드 체크 후 `_send_signal_alert()` 호출로 변경 |

#### 수정 상세

**C1: new_stop_loss_price 파라미터 제거**
- `repository.py`: `update_partial_exit()` 메서드에서 파라미터 삭제
- `exit_manager.py`: 호출부에서 인자 제거
- 배경: V6.2-Q에서 breakeven 기능 삭제로 분할 매도 시 stop_loss_price 업데이트 불필요

**C5: 신호 큐 만료 처리 개선**
```python
# 변경 전 (버그)
if is_cooldown:
    break  # 만료된 신호도 처리 안 됨 -> 메모리 누수

# 변경 후
if is_cooldown:
    continue  # 현재 신호 스킵, 만료된 신호 정리는 계속
```

**W4: TRAILING_STOP 블랙리스트 추가**
```python
# 변경 전
exit_types_for_blacklist = ["HARD_STOP", "BREAKEVEN_STOP", "TECHNICAL_STOP"]

# 변경 후
exit_types_for_blacklist = ["HARD_STOP", "BREAKEVEN_STOP", "TECHNICAL_STOP", "TRAILING_STOP"]
```

**W5: SIGNAL_ALERT 모드 큐 신호 처리**
```python
# _execute_queued_signal() 시작 부분에 추가
if self._settings.trading_mode == TradingMode.SIGNAL_ALERT:
    await self._send_signal_alert(signal)
    return
```

#### Files Modified

| 파일 | 변경 내용 |
|------|----------|
| src/database/repository.py | `update_partial_exit()` new_stop_loss_price 파라미터 제거 |
| src/core/exit_manager.py | `update_partial_exit()` 호출 시 인자 제거 |
| src/core/trading_engine.py | C2, C3, C4, C5, W5 수정 |
| src/core/risk_manager.py | W4: `on_exit()` 블랙리스트 TRAILING_STOP 추가 |

### Patch 3 (2026-01-18 KST)

전체 코드 분석 (12,731줄) 후 발견된 논리적 결함 및 Race Condition 수정.

#### P0 Critical Issues (6건)

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| P0-1 | risk_manager.py:574 | `entry_date` 미초기화 → MAX_HOLDING 60일 청산 미작동 | `entry_date=date.today()` 추가 |
| P0-2 | trading_engine.py:1932 | `TradingMode` import 누락 → NameError 크래시 | 로컬 import 추가 |
| P0-3 | repository.py:78-99 | 중복 OPEN Trade 생성 가능 → Double-Buy | 중복 체크 + ValueError raise |
| P0-4 | order_executor.py:467-503 | Trade-Order 비원자적 생성 → 불일치 가능 | `atomic_session()` 적용 |
| P0-5 | trading_engine.py:671-674 | `_on_condition_signal_v31` Startup Guard 누락 | `_startup_complete` 체크 추가 |
| P0-6 | signal_detector.py:262-264 | `prev["ema3"]` NaN 체크 누락 → 비교 실패 | `pd.isna()` 체크 추가 |

#### P1 Important Issues (6건)

| Issue | 파일 | 문제 | 수정 |
|-------|------|------|------|
| P1-1 | exit_manager.py:647-656 | `execute_manual_sell()` Lock 미사용 → Race Condition | `_get_order_lock()` 래퍼 적용 |
| P1-2 | risk_manager.py | `_daily_pnl` 동시 접근 가능 → 값 손상 | `threading.Lock` 추가 (4곳) |
| P1-3 | subscription_manager.py:441-454 | `on_signal_received()` Lock 미사용 | `threading.Lock` 추가 |
| P1-4 | repository.py:151-164 | `close()` 동시 호출 시 Double-Close | `with_for_update()` + 상태 체크 |
| P1-5 | telegram.py:95-100,204-209 | `parse_mode` 사용 → 400 에러 | 경고 로그 + 무시 처리 |
| P1-6 | trading_engine.py:3266-3291 | HTS 매수 시 ATR TS 미초기화 | `_init_ts_fallback()` 호출 추가 |

#### 추가 수정

| 파일 | 변경 내용 |
|------|----------|
| repository.py:463-500 | `OrderRepository.update_status()`에 session 파라미터 지원 추가 |

#### 수정 상세

**P0-1: entry_date 초기화**
```python
# risk_manager.py on_entry()
self._position_risks[stock_code] = PositionRisk(
    ...
    entry_date=date.today(),  # V6.2-Q FIX 추가
)
```

**P0-3: 중복 Trade 방지**
```python
# repository.py create()
async def _check_duplicate(check_session):
    result = await check_session.execute(
        select(Trade).where(and_(
            Trade.stock_code == stock_code,
            Trade.status == TradeStatus.OPEN
        ))
    )
    return result.scalar_one_or_none() is not None

if await _check_duplicate(session):
    raise ValueError(f"이미 {stock_code}에 대한 OPEN 상태 거래가 존재합니다")
```

**P0-4: atomic_session 적용**
```python
# order_executor.py execute_buy_order()
async with atomic_session() as session:
    trade = await self._trade_repo.create(..., session=session)
    order = await self._order_repo.create(..., session=session)
    await self._order_repo.update_status(..., session=session)
# 블록 종료 시 자동 commit, 실패 시 자동 rollback
```

**P1-2: daily_pnl Lock 보호**
```python
# risk_manager.py
self._pnl_lock = threading.Lock()

with self._pnl_lock:
    self._daily_pnl += pnl  # 4곳에 적용
```

#### Files Modified

| 파일 | 변경 내용 |
|------|----------|
| src/core/risk_manager.py | P0-1, P1-2: entry_date, threading.Lock |
| src/core/trading_engine.py | P0-2, P0-5, P1-6: TradingMode import, Startup Guard, HTS ATR |
| src/core/signal_detector.py | P0-6: NaN 체크 |
| src/database/repository.py | P0-3, P1-4: 중복 체크, SELECT FOR UPDATE, session 지원 |
| src/core/order_executor.py | P0-4: atomic_session |
| src/core/exit_manager.py | P1-1: execute_manual_sell Lock |
| src/core/subscription_manager.py | P1-3: on_signal_received Lock |
| src/notification/telegram.py | P1-5: parse_mode 무시 |

### Patch 4 (2026-01-18 23:14 KST)

P2 코드 정리 작업 - 문서화 및 캡슐화 개선.

| Task | 파일 | 내용 |
|------|------|------|
| W1 | risk_manager.py | Docstring 수정 - 'Hard Stop 제거됨' → V6.2-Q 청산 로직 반영 |
| W2 | risk_manager.py | ExitReason enum 정리 - BREAKEVEN_STOP, TECHNICAL_STOP에 레거시 주석 추가 |
| W6 | trading_engine.py | `_signal_alert_cooldown.clear()` 일일 리셋 추가 (07:40~07:50) |
| W7 | exit_manager.py | `_risk_manager._position_risks.get()` → `get_position_risk()` public getter 사용 |
| W3 | config.py, risk_manager.py, main.py, trading_engine.py | 레거시 필드 삭제 (buy_ratio, stop_loss_rate, cooldown_seconds 등 9개) |

#### W3 삭제된 레거시 필드

| 파일 | 삭제 필드 |
|------|----------|
| config.py RiskSettings | max_position_ratio, buy_ratio, take_profit_rate, stop_loss_rate, backup_stop_loss_rate, cooldown_seconds, cooldown_minutes(property) |
| config.py validator | stop_loss_rate 참조 제거 |
| risk_manager.py RiskConfig | hard_stop_rate, trailing_start_rate, backup_stop_loss_rate |
| risk_manager.py from_settings() | cooldown_minutes → 고정값 15분 |
| main.py | buy_ratio 전달 제거 |
| trading_engine.py EngineConfig | buy_ratio 필드 삭제 |

#### Files Modified

| 파일 | 변경 내용 |
|------|----------|
| src/core/risk_manager.py | W1, W2, W3: Docstring, ExitReason, 레거시 필드 정리 |
| src/core/trading_engine.py | W6, W3: _signal_alert_cooldown 리셋, buy_ratio 삭제 |
| src/core/exit_manager.py | W7: private → public getter |
| src/utils/config.py | W3: 레거시 필드 7개 삭제 |
| src/main.py | W3: buy_ratio 전달 제거 |

---

## 2026-01-16 - V6.2-P: NXT 거래소 자동 탐지

### Fixed

- **exit_manager.py** - 매도 시 거래소 자동 탐지
  - 문제: NXT 프리마켓 수동 매수 후 매도 시 '0주 매도가능' 에러
  - 원인: execute_full_sell()에서 exchange 파라미터 미전달 → KRX 기본값 사용
  - 수정: KRX/NXT 각각 조회하여 종목이 있는 거래소 자동 탐지

---

## 2026-01-15 - V6.2-L Hotfix #3: Phase 3 코드 검증 완료

### Fixed

- **subscription_manager.py:535** - `_is_trading_hours()` NXT 시간대 지원
  - 변경 전: 09:00~15:30만 "장 운영 중"으로 판정
  - 변경 후: 08:00~20:00 전체 NXT 시간대 지원
  - 영향: 헬스체크 루프에서 NXT 시간대 회로차단 복구 가능

### Verified (Phase 3 분석 결과)

| 파일 | 상태 | 비고 |
|------|------|------|
| subscription_manager.py | ✅ 수정됨 | NXT 시간 지원 추가 |
| order_executor.py | ✅ 호환 | 콜백 기반 설계 |
| risk_manager.py | ✅ 호환 | V6.2-E 보호 로직 정상 |
| auto_screener.py | ✅ 호환 | MarketState 무관 |
| realtime_data_manager.py | ✅ 호환 | 데이터 계층 |
| position_manager.py | ✅ 호환 | 기능 정상 |
| candle_builder.py | ✅ 호환 | 캔들 생성 정상 |
| indicator.py | ✅ 호환 | EMA/ATR 불변조건 준수 |

---

## 2026-01-15 - V6.2-L Hotfix #2: Phase 1-2 코드 검증 및 Critical 버그 수정

### Fixed (Critical)

- **trading_engine.py:4587** - `execute_manual_buy()` NXT_AFTER 매수 차단
  - 변경 전: `is_market_open()` 사용 → NXT_AFTER(15:30~20:00)에 `/buy` 명령 허용
  - 변경 후: `_is_nxt_trading_hours()` 사용 → 정규장(09:00~15:20)만 매수 가능
  - V6.2-L 설계: NXT 애프터마켓에서는 청산만 허용, 신규 매수 금지

- **trading_engine.py:2856** - entry_time None 처리 추가
  - 문제: entry_time이 None일 때 entry_date 미설정 → 60일 보유일 체크 실패
  - 수정: else 절 추가하여 오늘 날짜로 fallback + 경고 로그

### Fixed (Important)

- **signal_detector.py:225** - fallback 시간 09:30→09:20 수정
  - V6.2-L에서 SIGNAL_START_TIME을 09:20으로 변경했으나 fallback 값 미수정
  - 환경변수 파싱 실패 시에도 09:20부터 신호 탐지 시작

### Verified (Phase 1-2 분석 결과)

- ✅ NXT 시간 함수들 (`_is_nxt_trading_hours`, `_is_nxt_exit_hours`, `_is_nxt_suspended`) 정상
- ✅ exit_manager.py V6.2-L 변경사항 정상 (3개 보호구간, 극단값 필터)
- ✅ signal_detector.py 시간 조건 정상
- ✅ Zone/TrendFilter/Meaningful 조건 CLAUDE.md 명세와 일치
- ✅ EMA adjust=False 정확히 사용

---

## 2026-01-15 - V6.2-L Hotfix #1: MarketState.CLOSING 레거시 참조 버그 수정

### Background (문제 상황)

`/start` 명령 후 "거래 시작 중..." 메시지만 출력되고 시스템 무응답.
`AttributeError: type object 'MarketState' has no attribute 'CLOSING'` 발생.

### Root Cause

V6.2-L에서 `MarketState.CLOSING`을 `MarketState.KRX_CLOSING`으로 변경했으나,
2곳에서 레거시 참조가 남아있었음:
- `market_schedule.py:333` - state_names 딕셔너리
- `trading_engine.py:1171` - 장 상태 체크 조건문

### Fixed

- **market_schedule.py:333** - state_names 딕셔너리에 새 상태 추가
  ```python
  state_names = {
      MarketState.CLOSED: "폐장",
      MarketState.NXT_PRE_MARKET: "NXT 프리마켓",  # V6.2-L 추가
      MarketState.PRE_MARKET: "동시호가",
      MarketState.OPEN: "정규장",
      MarketState.KRX_CLOSING: "KRX 단일가",      # CLOSING → KRX_CLOSING
      MarketState.NXT_AFTER: "NXT 애프터마켓",     # V6.2-L 추가
      MarketState.AFTER_HOURS: "장외",            # V6.2-L 추가
      MarketState.HOLIDAY: "휴장",
  }
  ```

- **trading_engine.py:1171** - MarketState.CLOSING → KRX_CLOSING 변경

---

## 2026-01-14 - V6.2-L: NXT 거래시간 확장 (08:00~20:00)

### Background (배경)

NXT(넥스트레이드) 대체거래소가 2025년 출범하여 08:00~20:00 거래 가능.
기존 시스템은 KRX 정규장(09:00~15:30)만 지원하여 NXT 시간대에 청산/손절 불가.

### Added (신규 기능)

- **MarketStatus 7단계 상태 시스템** (`market_schedule.py`)
  - `NXT_PRE_MARKET` (08:00~08:50): NXT 프리마켓
  - `NXT_OPENING_AUCTION` (08:50~09:00): NXT 동시호가
  - `REGULAR_HOURS` (09:00~15:20): KRX+NXT 정규장
  - `CLOSING_AUCTION` (15:20~15:30): KRX 종가 단일가 (NXT 중단)
  - `NXT_ORDER_ACCEPT` (15:30~15:40): NXT 호가접수
  - `NXT_AFTER_MARKET` (15:40~20:00): NXT 애프터마켓
  - `CLOSED` (20:00~08:00): 장 종료

- **NXT 시간대 청산/손절 허용 함수 3개** (`market_schedule.py`)
  - `is_exit_allowed()`: 청산 가능 시간대 판정 (08:00~20:00, 15:20~15:30 제외)
  - `is_signal_allowed()`: 신호 탐색 가능 시간대 판정 (09:20~15:20, NXT 애프터 옵션)
  - `get_market_status()`: 현재 시장 상태 반환

- **장 초반 보호 구간 확장** (`exit_manager.py`)
  - 08:00~08:01 (NXT 프리마켓 첫 1분): bar_low 손절 비활성화
  - 09:00~09:01 (정규장 첫 1분): 기존 유지
  - current_price 기반 손절은 항상 활성화 (실제 급락 대응)

- **신규 환경변수 4개** (`config.py`)

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `SIGNAL_START_TIME` | 09:20 | 신호 탐색 시작 (09:30->09:20) |
| `SIGNAL_END_TIME` | 15:20 | 신호 탐색 종료 |
| `NXT_SIGNAL_ENABLED` | false | NXT 애프터마켓 신호 허용 |
| `NXT_EXIT_ENABLED` | true | NXT 시간대 청산/손절 허용 |

### Changed (변경)

- **ExitManager 청산 체크 로직 개선** (`exit_manager.py`)
  - `is_exit_allowed()` 호출하여 NXT 시간대 청산 지원
  - 15:20~15:30 중단 구간 자동 제외

- **CLAUDE.md 시간 규칙 테이블 업데이트**
  - KRX 정규장: 09:00~15:20 (기존 15:30 -> 15:20)
  - NXT 거래시간 상세 테이블 추가
  - 신호 시작 시간: 09:30 -> 09:20

### Technical Details

**MarketStatus 상태 다이어그램**:
```
08:00 ─┬─ NXT_PRE_MARKET ─┬─ 08:50 ─┬─ NXT_OPENING_AUCTION ─┬─ 09:00
       │   (청산 가능)    │         │   (호가 접수만)       │
       │                  │         │                       │
09:00 ─┼─ REGULAR_HOURS ──┼─────────┼───────────────────────┼─ 15:20
       │   (신호+청산)    │         │                       │
       │                  │         │                       │
15:20 ─┼─ CLOSING_AUCTION ┼─────────┼─ 15:30 ───────────────┤
       │   (NXT 중단)     │         │                       │
       │                  │         │                       │
15:30 ─┼─ NXT_ORDER_ACCEPT┼─ 15:40 ─┼─ NXT_AFTER_MARKET ────┼─ 20:00
       │   (호가 접수)    │         │   (청산 가능)         │
       │                  │         │                       │
20:00 ─┴─ CLOSED ─────────┴─────────┴───────────────────────┴─ 08:00
```

**시간대별 동작 요약**:
| 시간대 | 상태 | 신호 탐지 | 청산/손절 | 비고 |
|--------|------|----------|----------|------|
| 08:00~08:50 | NXT_PRE_MARKET | X | O | 프리마켓 |
| 08:50~09:00 | NXT_OPENING_AUCTION | X | X | 동시호가 |
| 09:00~09:20 | REGULAR_HOURS | X | O | 장 초반 |
| 09:20~15:20 | REGULAR_HOURS | **O** | O | 정규장 |
| 15:20~15:30 | CLOSING_AUCTION | X | X | **NXT 중단** |
| 15:30~15:40 | NXT_ORDER_ACCEPT | X | X | 호가 접수 |
| 15:40~20:00 | NXT_AFTER_MARKET | 설정 | O | 애프터마켓 |

### Files Modified

- `src/core/market_schedule.py`: MarketStatus enum, 시간 판정 함수
- `src/core/exit_manager.py`: NXT 시간대 청산 로직
- `src/utils/config.py`: 환경변수 4개 추가
- `CLAUDE.md`: 시간 규칙 테이블 업데이트
- `docs/TECHNICAL_DOCUMENTATION.md`: 섹션 10.8 환경변수 추가

### Notes

**키움 API NXT 지원 현황**:
- 실전투자: KRX + NXT + SOR(스마트주문라우팅) 지원
- 모의투자: KRX만 지원 (NXT 미지원)

**검증 필요 사항**: `docs/V6.2-L_VERIFICATION_CHECKLIST.md` 참조

---

## 2026-01-13 - V6.2-J: CandleBuilder 봉 완성 콜백 누락 버그 수정

### Background (문제 상황)

298830 (슈어소프트테크) 10:15 HTS 신호 발생 → 시스템 알림 미수신.
조건검색으로 Active Pool에 등록된 종목의 `[봉완성]` 로그가 없었으며, SNIPER_TRAP 신호 탐지 자체가 되지 않았음.

### Root Cause

- **파일**: `src/core/candle_builder.py`
- **메서드**: `load_historical_candles()` (라인 370-419)
- **문제**: 과거 캔들을 `_candles[timeframe]`에만 저장하고 `_current_candles[timeframe]`은 초기화하지 않음
- **영향**: 조건검색으로 새로 등록된 종목이 첫 3분 경계까지 SNIPER_TRAP 신호 탐지 불가 (최대 3분 지연)

### Fixed

- **`load_historical_candles()` 끝에 `_current_candles` 초기화 로직 추가**

```python
# V6.2-J: 마지막 캔들로 _current_candles 초기화
if self._candles[timeframe]:
    last_candle = self._candles[timeframe][-1]
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
```

### Technical Details

**CandleBuilder 내부 구조**:
```
_candles[timeframe]: List[Candle]      # 완성된 봉 히스토리
_current_candles[timeframe]: Candle    # 현재 진행 중인 봉 (틱 데이터로 업데이트)
```

**수정 전 동작** (버그):
1. `load_historical_candles()` 호출 → `_candles[3]`에 과거 봉 저장
2. `_current_candles[3]`은 None 상태
3. 틱 데이터 수신 → `_current_candles[3]`이 None이므로 새 봉 생성
4. 3분 경계 도달 시 봉 완성 콜백 발생 (최대 3분 지연)

**수정 후 동작**:
1. `load_historical_candles()` 호출 → `_candles[3]`에 과거 봉 저장
2. 마지막 캔들로 `_current_candles[3]` 초기화 (is_complete=True)
3. 틱 데이터 수신 → 기존 봉 업데이트 또는 새 봉 생성
4. 즉시 SNIPER_TRAP 신호 탐지 가능

### Files Modified

- `src/core/candle_builder.py`: `load_historical_candles()` 메서드

### Deployment

- **배포 시각**: 2026-01-13 10:38 KST
- **방법**: hotfix.ps1

---

## 2026-01-13 - V6.2-I: ATR TS 매수시점 기준 개선

### Background

- 테라뷰(950250) 무위봉(O=H=L=C) 상황에서 ATR≈0 → TS가 현재가에 너무 근접
- 장 시작 직후 약간의 하락에도 TS 청산 발생

### Changed

- **PositionRisk에 `entry_atr` 필드 추가** (`risk_manager.py`)
  - 매수 시점 ATR 값 저장
  - TS 계산 시 참조하여 최소 ATR 보장

- **TS 계산 시 effective_atr 적용** (`exit_manager.py`)
  - `effective_atr = max(current_atr, entry_atr, min_atr)`
  - current_atr: 현재 ATR(10) 값
  - entry_atr: 매수 시점 저장된 ATR 값
  - min_atr: 매수가 × 0.5% (최소 보장)

- **기존 포지션 복구 시 fallback** (`trading_engine.py`)
  - entry_atr 없는 기존 포지션: `entry_price × 0.5%` 적용

### Files Modified

- `src/core/risk_manager.py` - PositionRisk 데이터클래스
- `src/core/exit_manager.py` - TS 초기화/갱신 로직
- `src/core/trading_engine.py` - 포지션 복구 fallback

---

## 2026-01-12 - V6.2-H: SNIPER_TRAP 디버그 로그 + SIGNAL_ALERT 재시도 허용

### Background (문제 상황)

모베이스전자(012860) 신호 미발송 분석 결과:
- 09:03 거래대금 121억 부족으로 탈락 → `processed_today` 등록됨
- 13:38 거래대금 1,098억 증가 → Active Pool 등록 성공 (서버 재시작으로 우연히 통과)
- 14:04 재신호 → `already_processed`로 차단됨

### Changed

- **SIGNAL_ALERT 모드 already_processed 로직 개선** (`auto_screener.py`)
  - 기존: 필터 체크 전에 `processed_today` 등록 → 실패해도 재시도 불가
  - 변경: 필터 성공 시에만 `processed_today` 등록 → 실패 후 재시도 가능
  - Active Pool에 이미 있으면 `already_in_active_pool`로 차단 (중복 처리 방지)

### Added

- **SNIPER_TRAP 조건 미충족 디버그 로그** (`signal_detector.py`)
  - TrendFilter 미충족: `C > EMA200`, `EMA60 상승` 조건 상세 출력
  - Zone/Meaningful/BodySize 미충족: 각 조건 충족 여부 및 값 출력
  - 예: `[SNIPER_TRAP] 012860 Zone 미충족: L(2,700) <= M20(2,650)? True, C(2,680) >= M60(2,720)? False`

---

## 2026-01-12 - V6.2-G: 레거시 정리 + 메시지 개선

### Removed

- **Universe.refresh() 레거시 로직 제거** (`trading_engine.py`)
  - 거래대금 상위 100 조회 → 조건검색 기반으로 전환
  - `_universe_refresh_loop()` 태스크 비활성화
  - 보유 포지션은 시작 시 자동 Universe 등록

- **레거시 문서 8개 삭제**
  - `docs/PRD_V3.1.md`, `docs/PRD_V3.2.md`
  - `docs/CHECKLIST_2025-12-30.md`, `docs/V62A_TEST_CHECKLIST.md`
  - `PRD_JIJEOGGAE_LIVE.md`
  - `docs/SYSTEM_ARCHITECTURE.md`, `docs/BACKTEST_DESIGN.md`, `docs/BACKTEST_SPEC.md`

- **미사용 설정 제거** (`config.py`)
  - `liquidity_threshold_0930/1030/1530` (시간대별 유동성 임계값)

### Changed

- **/status 명령어 출력 개선** (`trading_engine.py`)
  - Candidate: 수량만 표시 (종목명 제거)
  - "감시/대기" → "Tier1(신호탐지)/Tier2(대기)"

- **매도체결 메시지 금액 숨김** (`templates.py`)
  - `손익: +50,000원 (+2.50%)` → `손익: +2.50%`
  - 심리 흔들림 방지

- **auto_screener.py docstring V6.2-G 반영**
  - 3단계 Pool 구조 명시 (Watchlist → Candidate → Active)

### Added

- **CLAUDE.md 레거시 예방 규칙**
  - PRD/체크리스트 문서 생성 금지
  - DEPRECATED 주석 1버전 후 완전 삭제
  - `PRD vX.X` 대신 `V6.X-X` 형식 사용

---

## 2026-01-12 - V6.2-F: SIGNAL_ALERT Pool 무제한 + 로깅 버그 수정

### Changed

- **SIGNAL_ALERT 모드 Pool 완전 무제한** (`auto_screener.py`)
  - Watchlist: 50 -> 9999
  - Candidate: 20 -> 9999
  - Active: 10 -> 9999
  - 모든 조건검색 종목 SNIPER_TRAP 신호 감시 가능

### Fixed

- **로깅 버그 4건** (`auto_screener.py`)
  - 클래스 변수 대신 인스턴스 변수 사용하도록 수정

---

## 2026-01-12 - V6.2-E: NXT 시장조작 방어 메커니즘

### Background (문제 상황)

NXT 거래소(08:00 시작)에서 장전에 -30% 하한가를 고의로 만들었다가 원상복구하는 시장 조작 발생.
기존 시스템은 08:00~09:00 사이 조작된 bar_low가 09:00 이후 첫 체크에서 손절을 트리거할 수 있었음.

### Added

- **2단계 방어 메커니즘** (`risk_manager.py`, `exit_manager.py`)

| 방어층 | 메커니즘 | 조건 |
|--------|----------|------|
| Layer 1 | 장 초반 보호 기간 | 09:00~09:01 (1분간) bar_low 손절 비활성화 |
| Layer 2 | 극단값 필터 | bar_low < 진입가 x 0.85 (-15%) 무시 |

- **새 환경변수 3개** (`config.py`)
  - `EXIT_PROTECTION_MINUTES=1`: 장 초반 보호 기간 (분)
  - `EXTREME_DROP_THRESHOLD=-0.15`: 극단값 임계치 (-15%)
  - `EXTREME_PRICE_ALERT=true`: 극단값 감지 시 텔레그램 알림

- **ExitManager 메서드 추가** (`exit_manager.py`)
  - `_is_opening_protection_period()`: 장 초반 보호 기간 판정

### Technical Details

**핵심 원칙**: 보호 상태에서도 current_price 기반 손절은 유지 (실제 급락 대응)

```python
# Layer 1: 장 초반 보호 (09:00~09:01)
if _is_opening_protection_period():
    # bar_low 손절 스킵, current_price 손절만 체크

# Layer 2: 극단값 필터
if bar_low < entry_price * 0.85:  # -15% 이상 급락
    # 조작된 bar_low로 간주, 손절 조건에서 제외
    # 텔레그램 알림 발송
```

**관련 파일**:
- `src/utils/config.py`: 환경변수 추가
- `src/core/risk_manager.py`: `check_exit_v62a()` 수정 (극단값 필터 + 보호 모드)
- `src/core/exit_manager.py`: `_is_opening_protection_period()` 메서드 추가

---

## 2026-01-12 - Critical Bug Fixes (V6.2-E 이전)

### Fixed

- **NXT 거래소 통합 조회** (`account.py`) - Critical
  - kt00004 API가 거래소별 조회만 지원하는 문제 해결
  - KRX + NXT 각각 호출 후 결과 합산
  - 한화시스템(272210) 등 NXT 매수 종목 감지 성공

- **갭 체크 반환 타입 수정** (`trading_engine.py`) - Critical
  - `get_current_price()` 반환값 직접 사용하도록 수정

---

## 2026-01-11 - V6.2-E: 백테스팅 가이드라인 문서화

### Added

- **백테스팅 가이드라인 문서** (`docs/BACKTEST_GUIDELINES.md`)
  - 실행 전 체크리스트 (토큰, API, Python 환경)
  - 토큰 관리 규칙 (로컬/AWS 격리 구조)
  - API 조회 규칙 (Rate Limit, 필수 파라미터)
  - 네이밍 규칙 (`snake_case`, `PascalCase`, `UPPER_SNAKE_CASE`)
  - 함수명 통일성 (`get_*`, `calculate_*`, `detect_*`, `simulate_*`)
  - 지표 계산 불변조건 (EMA `adjust=False`, ATR Wilder's RMA)
  - 청산 로직 우선순위 (고정손절 > ATR TS > 최대보유일)
  - 비용 모델 (KOSDAQ 왕복 0.31%)
  - 실행 명령어 레퍼런스
  - 오류 대응 가이드 (401, Rate Limit, 데이터 누락)

### Changed

- **CLAUDE.md 구조 개선**
  - Part 1.2 "백테스팅/전략 설계 규칙" 섹션 추가
  - 백테스팅 작업 시 `docs/BACKTEST_GUIDELINES.md` 필수 참조 규칙
  - 기존 섹션 번호 재조정 (1.2->1.3, 1.3->1.4, 1.4->1.5, 1.5->1.6)
  - Part 4.1 상세 문서 목록에 BACKTEST_GUIDELINES.md 추가

### Technical Details

**문서 역할 분리**:
```
+----------------------------+--------------------------------+
| 문서                       | 역할                           |
+----------------------------+--------------------------------+
| BACKTEST_DESIGN.md         | 프레임워크 설계, 모듈 구조     |
| BACKTEST_SPEC.md           | 진입/청산 로직 스펙            |
| BACKTEST_GUIDELINES.md     | 실행 가이드, 토큰/API/네이밍   |
+----------------------------+--------------------------------+
```

**CLAUDE.md 용량 관리**:
- 이전: 297줄
- 이후: ~305줄 (+8줄)
- 상세 내용은 별도 문서로 위임하여 간결성 유지

---

## 2026-01-10 - V6.2-D: 52주 고점 근접 종목 조기 신호

### Removed (삭제된 기능)

- **12시 이후 1분봉 거래대금 50억 조건 완전 삭제** (`auto_screener.py`)
  - `WatchlistEntry`에서 `is_afternoon_entry`, `volume_condition_met`, `volume_met_time` 필드 삭제
  - `AFTERNOON_VOLUME_THRESHOLD` 상수 삭제
  - `_check_afternoon_volume_from_api()` 메서드 삭제
  - `on_condition_signal()`, `revalidate_watchlist()`, `check_and_promote()` 내 12시 조건 체크 로직 삭제

### Added (추가된 기능)

- **52주 고점 -10% 이내 종목 조기 신호 허용 (09:00부터)** (`config.py`, `auto_screener.py`, `signal_detector.py`, `trading_engine.py`)
  - `EARLY_SIGNAL_TIME` (기본값: "09:00") - 조기 신호 시작 시간
  - `NEAR_52W_HIGH_RATIO` (기본값: 0.90) - 52주 고점 대비 비율 (90% 이상이면 조기 신호)
  - `WatchlistEntry.high_52w_ratio` 필드 추가
  - `auto_screener.py`: `get_watchlist_entry()` 메서드 추가, 52주 고점 비율 계산 및 저장
  - `signal_detector.py`: `override_time_filter` 파라미터 추가 (09:00~09:30 시간대 조기 신호 허용)
  - `trading_engine.py`: 52주 고점 근접 종목 판별 후 `override_time_filter` 전달

### Technical Details

**조기 신호 동작 비교**:
```
+------------+---------------------+------------+
| 시간대     | 52주 고점 90% 이상  | 일반 종목  |
+------------+---------------------+------------+
| 09:00~09:03| 신호 탐지 X (봉 미완성)| 신호 탐지 X|
| 09:03~09:30| 신호 탐지 O (조기)   | 신호 탐지 X|
| 09:30 이후 | 신호 탐지 O         | 신호 탐지 O|
+------------+---------------------+------------+
```

**조기 신호 흐름**:
```
조건검색 편입 (09:00~)
        │
        v
52주 고점 비율 계산 (high_52w_ratio = 현재가 / 52주최고가)
        │
        v
    high_52w_ratio >= 0.90?
        │
    +---+---+
    |       |
   Yes      No
    │       │
    v       v
조기신호   일반신호
(09:03~)  (09:30~)
```

**관련 파일**:
- `src/utils/config.py`: 환경변수 2개 추가
- `src/core/auto_screener.py`: 12시 조건 삭제, high_52w_ratio 추가, get_watchlist_entry() 추가
- `src/core/signal_detector.py`: override_time_filter 파라미터 추가
- `src/core/trading_engine.py`: 52주 고점 판별 및 override 전달

---

## 2026-01-09 - V6.2-C: SIGNAL_ALERT 모드 추가

### Added

- **SIGNAL_ALERT 모드** (`config.py`, `trading_engine.py`)
  - `TradingMode.SIGNAL_ALERT` enum 추가
  - SNIPER_TRAP 신호 발생 시 자동매수 대신 텔레그램 알림만 전송
  - 사용자가 `/buy` 명령어로 수동 판단 후 매수 가능

- **수동매수 ATR TS 자동 초기화** (`trading_engine.py:execute_manual_buy()`)
  - SIGNAL_ALERT 모드에서 `/buy` 수동매수 시 ATR 트레일링 스탑 자동 초기화
  - 수동 매수 후에도 자동 청산 (TS Exit, Hard Stop) 지원

- **신호 알림 메시지 템플릿** (`templates.py`)
  - `format_signal_alert_notification()`: SIGNAL_ALERT 전용 알림 포맷
  - 종목명, 현재가, 신호 시간 포함

- **환경변수 2개 추가** (`.env`)
  - `SIGNAL_ALERT_COOLDOWN_SECONDS=300`: 같은 종목 중복 알림 방지 (기본 5분)
  - `WATCHLIST_MAX_UNLIMITED=9999`: SIGNAL_ALERT 모드 Watchlist 무제한

### Changed

- **Pool 제한 동적 설정** (`auto_screener.py:__init__()`)
  - SIGNAL_ALERT 모드: Watchlist 최대 9999개 (사실상 무제한)
  - AUTO_UNIVERSE 모드: 기존 50개 유지

### Technical Details

**모드별 동작 비교**:
```
+------------------+---------------+--------------+
| 기능             | AUTO_UNIVERSE | SIGNAL_ALERT |
+------------------+---------------+--------------+
| 조건검색 구독    | O             | O            |
| 5필터 체크       | O             | O            |
| SNIPER_TRAP 신호 | 자동매수      | 알림만 전송  |
| /buy 수동매수    | O             | O            |
| 수동매수 ATR TS  | X             | O (자동)     |
| 포지션 자동청산  | O             | O            |
| Pool 제한        | 50/20/10      | 9999 (무제한)|
+------------------+---------------+--------------+
```

**SIGNAL_ALERT 흐름**:
```
조건검색 편입 → Watchlist 등록 → 5필터 체크 → Active Pool
                                                    │
                                        SNIPER_TRAP 신호 발생
                                                    │
                                                    v
                                    텔레그램 알림 발송 (쿨다운 300초)
                                                    │
                                          사용자 판단
                                                    │
                                    /buy 종목코드 → ATR TS 초기화 → 자동청산
```

**관련 파일**:
- `src/utils/config.py`: TradingMode enum, 환경변수
- `src/core/trading_engine.py`: `_process_signal()`, `_send_signal_alert_notification()`, `execute_manual_buy()`
- `src/notification/templates.py`: `format_signal_alert_notification()`
- `src/core/auto_screener.py`: Pool 무제한 설정

---

## 2026-01-05 - V6.2-B: Watchlist 3계층 Pool 구조

### Added

- **Watchlist 계층** (`auto_screener.py`)
  - 조건검색 편입 시 무조건 Watchlist 등록 (최대 50개)
  - `add_to_watchlist()`: Watchlist 등록
  - `is_in_watchlist()`: Watchlist 포함 여부 체크
  - `revalidate_watchlist()`: 30초마다 전체 재검증
  - `check_and_promote()`: 신호 발생 시 즉시 6필터 체크 + 승격

- **Watchlist 재검증 루프** (`trading_engine.py`)
  - `_watchlist_revalidation_loop()`: 30초 주기 재검증
  - 필터 통과 시 Candidate → Active Pool 승격
  - SNIPER_TRAP 신호 시 즉시 승격 로직 통합

- **환경변수 2개 추가** (`.env`)
  - `WATCHLIST_MAX_SIZE=50`: Watchlist 최대 종목수
  - `WATCHLIST_REVALIDATION_INTERVAL=30`: 재검증 주기(초)

### Fixed (코드 리뷰 버그 수정)

| # | 심각도 | 파일 | 버그 | 수정 |
|---|--------|------|------|------|
| B1 | **CRITICAL** | `trading_engine.py:1056-1057` | `reset_daily()` 미호출 → Pool 누적 | `start()`에서 호출 추가 |
| B2 | **CRITICAL** | `auto_screener.py:815-820` | `datetime.min` 사용 → 연산 오류 | `datetime.now()` 사용 |
| B3 | **HIGH** | `auto_screener.py:956-968` | Active Pool 직접 수정 → max 우회 | `_update_active_pool()` 호출 |
| B4 | **MEDIUM** | `trading_engine.py:1398-1421` | `check_and_promote()` 미호출 | `_process_signal()` 통합 |

### Technical Details

**3계층 Pool 구조**:
```
Watchlist (50) → Candidate (20) → Active (10)
      │               │               │
      │               │               └── SNIPER_TRAP 신호 감시
      │               └── 거래대금 순위 기반 Active 선정
      └── 30초마다 6필터 재검증 → Candidate 승격
```

**즉시 승격 로직** (`_process_signal()`):
```python
# Watchlist에만 있는 종목에서 신호 발생 시
if not is_active(stock) and is_in_watchlist(stock):
    result = check_and_promote(stock)  # 즉시 6필터 체크
    if result.passed:
        execute_buy()  # 매수 진행
```

**관련 파일**:
- `src/core/auto_screener.py`: Watchlist 자료구조 + 재검증 메서드
- `src/core/trading_engine.py`: 재검증 루프 + 즉시 승격 통합

---

## 2026-01-05 - V6.2-A: 신호 큐 + Active Pool 확장

### Added

- **신호 큐 (Signal Queue)** (`trading_engine.py`)
  - 쿨다운 중 발생한 SNIPER_TRAP 신호 유실 방지
  - `_enqueue_signal()`: 큐에 신호 저장 (종목당 1개)
  - `_process_signal_queue()`: 쿨다운 해제 후 대기 신호 처리
  - `_execute_queued_signal()`: 큐 신호 실행
  - 신호 유효시간: 15초 (초과 시 만료 폐기)

- **콜백 기반 큐 처리** (`order_executor.py`)
  - `on_cooldown_expired_callback` 파라미터 추가
  - `_schedule_signal_queue_processing()`: 쿨다운 해제 후 자동 스케줄링

- **통계 확장** (`/status`)
  - `signals_queued`: 큐에 저장된 신호 수
  - `signals_expired`: 만료되어 폐기된 신호 수
  - `signals_from_queue`: 큐에서 처리된 신호 수

### Changed

- **Active Pool 확장**: 5개 → **10개**
  - 백테스트 결과 반영: 저거래대금 종목 포함 가능성 증가

- **시스템 쿨다운 단축**: 30초 → **15초**
  - 신호 큐와 조합하여 매수 기회 손실 최소화

- **CLAUDE.md 업데이트**
  - PowerShell 인코딩 경고 섹션 추가 (UTF-16 문제 방지)
  - 신호 큐 흐름도 추가
  - 환경변수 테이블 업데이트

### Technical Details

**신호 큐 흐름**:
```
SNIPER_TRAP 신호 → 쿨다운 체크
  ├─ 쿨다운 아님 → 즉시 매수 → 쿨다운 시작
  │                              │
  │                    15.5초 후 큐 처리
  │
  └─ 쿨다운 중 → 큐 저장 → 쿨다운 해제 시 처리
```

**관련 파일**:
- `src/core/trading_engine.py`: 신호 큐 로직 (3개 메서드)
- `src/core/order_executor.py`: 콜백 연동

---

## 2025-12-30 - 전체 시스템 코드 리뷰 및 Dead Code 정리

### Code Review Summary

- **5개 병렬 에이전트**로 전체 코드베이스 리뷰
  - 분석 범위: 27개 파일, 12,400줄
  - 발견 이슈: Critical 19개, Important 54개, Recommendation 32개

### Removed (Dead Code ~300줄)

- **trading_engine.py**
  - `_on_condition_signal()`: 호출되지 않는 메서드
  - `_on_condition_entry_signal()`: 미사용, `_pending_promotions` 참조
  - 함수 내 반복 import 제거 (pandas, numpy, math)

- **exit_manager.py** (220줄 감소)
  - `_check_safety_lock()`: trading_engine.py에 중복 구현
  - `_check_crash_guard()`: trading_engine.py에 중복 구현
  - `_check_m20_break()`: trading_engine.py에 중복 구현
  - `check_ema20_exit_on_candle_complete()`: 미호출

- **main.py**
  - `_on_tick_data()`: 어디서도 호출되지 않음
  - 미사용 `Tick` import 제거

- **signal_detector.py**
  - 미사용 `calculate_all_indicators` import 제거

- **risk_manager.py**
  - 함수 내 `import math` 제거 (파일 상단으로 이동)

### Changed

- **config.py**: Grand Trend V6 기본값 문서화
  - `PARTIAL_TAKE_PROFIT_RATE`: 10.0% (분할 익절)
  - `SAFETY_STOP_RATE`: -4.0% (고정 손절)
  - 레거시 필드 주석 추가 (3% 익절, -3.5% 손절 등)

- **risk_manager.py**: 레거시 필드 주석 정리
  - `breakeven_activated`, `trailing_activated`, `stop_loss_price`, `entry_floor_line`
  - 모두 `[레거시 - 미사용]` 주석 추가

- **CLAUDE.md**: 문서 동기화
  - RiskManager 설명: "6단계 청산 로직" → "Grand Trend V6 청산 로직"
  - 미구현 `/floor` 명령어 제거

### Preserved (변경 없음)

- ATR 계산 방식 (EMA 기반) - 정상 작동 중
- Grand Trend V6 청산 로직 (+10% 분할익절, ATR×6.0 트레일링, -4% 손절)
- 캔들 로드 (800개)
- WebSocket/API 연동
- 텔레그램 명령어 처리

### Deployment

- **배포 시각**: 2025-12-30 00:53:46 KST
- **방법**: hotfix.ps1
- **결과**: Pre-flight 6/6 통과, 정상 기동
- **검증 체크리스트**: `docs/CHECKLIST_2025-12-30.md`

---

## 2025-12-30 - PRD v3.2.5: 수량 기반 분할 익절 검증 시스템

### Added

- **PositionRisk.entry_quantity 필드** (`risk_manager.py:140-141`)
  - 최초 매수 수량 저장 (분할 매도 후에도 변하지 않음)
  - DB 크래시/재시작 후에도 분할 익절 완료 여부 판단 가능

- **수량 기반 분할 익절 검증** (`risk_manager.py:494-505`)
  - 현재 수량 < 원래 수량 × 90% → 분할 익절 완료로 자동 전환
  - API 잔고를 Single Source of Truth로 사용

- **트레일링 스탑 자동 복구** (`trading_engine.py:2464-2532`)
  - `_init_trailing_stop_for_recovered_partial()`: 분할 익절 포지션 복구 시 즉시 ATR 트레일링 초기화

### Fixed

- **SubscriptionManager 상태 자동 복구** (`subscription_manager.py:240-252`)
  - 신호 수신 시 FAILED→ACTIVE 자동 전환

---

## 2025-12-28 - 백테스트 시스템 분리 + SubscriptionManager 도입

### Project Separation

- **백테스트 시스템 독립 프로젝트로 분리**
  - 새 위치: `C:\K_backtest`
  - 이유: 실시간 트레이딩 시스템에 영향 없이 백테스트 개발 가능
  - 포함 모듈: BacktestEngine, SniperTrapAdapter, KiwoomDataService, UI
  - 문서: `K_backtest\CLAUDE.md`, `requirements.txt`, `run.py`

- **K_stock_trading 정리**
  - 삭제: `src/backtest/` 폴더
  - 삭제: `build/`, `dist/`, `backtest.spec` (PyInstaller 아티팩트)

### New Features

- **SubscriptionManager 도입** (`src/core/subscription_manager.py`)
  - 지수 백오프 재시도: 1s→2s→4s→8s→16s (최대 5회)
  - 헬스체크: 1분 주기, 10분 무신호 시 자동 재구독
  - asyncio.Lock: Race Condition 방지
  - `/substatus` 명령어: 조건검색 구독 상태 확인

### Fixed

- **MANUAL_ONLY 모드 ATR 알림 미작동** (`trading_engine.py:324-344`)
  - 문제: on_signal 콜백이 AUTO_UNIVERSE일 때만 등록
  - 수정: on_signal 항상 등록, MANUAL_ONLY 필터링은 콜백 내부에서 처리

- **WebSocket 중복 재구독 제거** (`websocket.py:473-493`)
  - SubscriptionManager가 단일 책임으로 구독 관리

---

## PRD v3.2.4 Hotfix2 (2025-12-26) - 조건검색 편출 시 ATR 감시 유지

### Changed

- **조건검색 편출(D) 시에도 ATR 감시 유지** (`trading_engine.py:669-676`)
  - 이전: 편출 시 `unregister_stock()` 호출하여 감시 해제
  - 변경: 편출되어도 장 종료까지 계속 감시하여 지저깨 신호 누락 방지
  - 로그: `[ATR Alert] 조건검색 편출 - 감시 유지: {stock_name}({stock_code})`

### Technical Details

**변경 이유**:
- 조건검색 신호는 변동성이 높아 편입(I)/편출(D)이 빈번하게 발생
- 편출 시 즉시 감시 해제하면 이후 지저깨 신호를 놓칠 수 있음
- 한 번 포착된 종목은 600개 1분봉 + 400개 3분봉을 로드하여 HTS와 거의 동일한 정확도로 신호 계산

**배포 확인**:
```
[ATR Alert] 조건검색 편출 - 감시 유지: 원익홀딩스(030530)
[ATR Alert] 조건검색 편출 - 감시 유지: 비츠로넥스텍(488900)
[ATR Alert] 030530 필터: ATR=True Angle=True Zone=False Mean=False Body=True
```

---

## PRD v3.2.4 Hotfix (2025-12-23) - ATR 알림 타이밍 버그 수정

### Fixed

- **[CRITICAL] 조건검색 편출(D) 신호 미처리** (`trading_engine.py:605-624`)
  - 문제: 종목이 조건검색에서 빠져도 ATR 감시 목록에 남아있어 불필요한 알림 발송
  - 수정: 편출 신호 시 `unregister_stock()` 호출하여 즉시 감시 해제

- **[HIGH] 일일 알림 카운트 미리셋** (`trading_engine.py:1039`)
  - 문제: `reset_daily_counts()` 미호출로 일일 알림 제한 미작동
  - 수정: 장 시작(09:00) 시 `reset_daily_counts()` 호출 추가

- **[HIGH] 장 종료 시 ATR 감시 종목 미정리** (`trading_engine.py:1138`)
  - 문제: 장 종료 후에도 감시 상태 유지
  - 수정: `stop()` 메서드에서 `clear_all()` 호출 추가

- **[MEDIUM] 수동 제거 시 ATR 알림 미해제** (`trading_engine.py:3333-3334`)
  - 문제: `/remove` 명령어 사용 시 ATR 감시 해제 안 됨
  - 수정: `_remove_stock()`에서 `unregister_stock()` 호출 추가

### Known Issues (내일 테스트 후 확인)

- **ATR 계산 방식 차이**: HTS는 SMA, 시스템은 EMA 사용
  - 키움 HTS: `ATR = avg(TR, Period)` (단순이동평균)
  - 현재 시스템: `ATR = ewm(TR, Period)` (지수이동평균)
  - 영향: ATR Stop 값 차이 → 신호 발생 시점 차이 가능
  - 수정 예정: `indicator.py:383`에서 `ewm()` → `rolling().mean()`

---

## PRD v3.2.4 (2025-12-23) - ATR 지저깨 실시간 알림 시스템

### Added

- **ATR 지저깨 알림 시스템** (조건검색 0번 전용)
  - 3분봉 기준 지저깨 신호 발생 시 텔레그램 알림 발송
  - ATR Trailing Stop 상태 관리 (종목별)
  - 5분 쿨다운 + 같은 종목 당 하루 최대 3회 제한

- **ATR 지표 추가** (`indicator.py`)
  - `true_range()`: True Range 계산 (갭 처리 포함)
  - `atr()`: Average True Range (EMA 방식, 기본값 period=14)
  - `atr_stop()`: ATR Stop Line (기본값 period=14)

- **신규 파일**: `src/core/atr_alert_manager.py`
  - `AtrAlertState`: 종목별 ATR 알림 상태 데이터클래스
  - `AtrAlertManager`: ATR 지저깨 알림 관리 클래스

- **Manual Buy Floor Line** (`trading_engine.py`)
  - `/buy` 명령어에 Floor Line 계산 추가 (HTS 매수와 동일)
  - 텔레그램 알림에 손절가 정보 표시

### Changed

- **config.py**: ATR 알림 설정 6개 추가
  - `ATR_ALERT_CONDITION_SEQ`: 조건검색식 번호 (기본 "0")
  - `ATR_ALERT_PERIOD`: ATR/Floor 기간 (기본 14, HTS 기본값)
  - `ATR_ALERT_MULTIPLIER`: ATR 배수 (기본 2.5)
  - `ATR_ALERT_VOLUME_THRESHOLD`: 거래량 배수 (기본 1.5)
  - `ATR_ALERT_COOLDOWN_SECONDS`: 알림 쿨다운 (기본 300초)
  - `ATR_ALERT_MAX_PER_DAY`: 같은 종목 당 일일 최대 알림 (기본 3)

- **trading_engine.py**: AtrAlertManager 통합
  - 조건검색 0번 신호 → ATR 알림 전용 (Auto-Universe와 분리)
  - 3분봉 완성 시 `check_on_candle_complete()` 호출

### Technical Details

**ATR Stop 계산 (HTS 기본 설정)**:
```
ATR_Stop = Highest(H, 14) - ATR(14) × 2.5
```

**탐지 조건** (3가지 모두 충족):
```
필터1 (추세): Close > ATR_Trailing_Stop
필터2 (지저깨): Low ≤ Floor_Line AND Close > Floor_Line
필터3 (수급): Close > Open AND Volume > 이전봉 Volume × 1.5
```

**데이터 로드**:
- 3분봉 600개 (`use_pagination=True`)
- 전일 종가 포함으로 갭 구간 TR 계산 정확도 보장

**성능 개선** (2025-12-23):
- CandleManager 캐시 활용으로 신호 체크 시 API 호출 제거
- 등록 시: RealTimeDataManager.promote_to_tier1()로 1회 캔들 로드
- 3분봉 완성 시: CandleManager.get_candles()로 캐시 사용 (API 호출 0회)
- 50개 종목 3분봉 완성 시: ~150 API 호출 → 0 API 호출

---

## PRD v3.2.3 (2025-12-22) - 트레일링 본전컷 + HTS Floor Line

### Added

- **트레일링 본전컷** (MANUAL/HTS 매수 종목)
  - +2.5% 도달 시 본전 보호 활성화 (`breakeven_activated = True`)
  - 0% 이하 도달 시 자동 본전컷 매도 (`ExitReason.BREAKEVEN_STOP`)
  - 청산 우선순위 0번 (분할익절보다 먼저 체크)

- **HTS 매수 Floor Line 자동 설정**
  - `_calculate_floor_line_for_hts()` 메서드 추가
  - Lowest(L,20) 기반 손절가 계산 (1분봉/3분봉 중 낮은 값)
  - 범위 검증: Floor Line >= 매수가 또는 < Safety Net → Safety Net 적용

### Fixed

- **Floor Line 계산 버그** (trading_engine.py:2319,2327)
  - `.low` → `.low_price` (MinuteCandle 속성명 오류)

### Changed

- 청산 우선순위: 본전컷(0번) > 분할익절(1번) > Safety Lock(2번) ...
- HTS 매수 종목: 분할익절 제외, Floor Line/Safety Net 적용

---

## PRD v3.2.1 Hotfix5 (2025-12-17) - Auto-Universe 신호 탐지 버그 수정

### Critical 수정

#### [CRITICAL] Auto-Universe 과거 캔들 로드 누락

**문제**: Auto-Universe에 종목 등록 후 SNIPER_TRAP 신호가 탐지되지 않음

| 증상 | 원인 |
|------|------|
| 현대무벡스(319400) 11:34:58 등록, 12시쯤 HTS 신호 감지됨 | `_register_auto_universe_stock()`에서 `promote_to_tier1()` 미호출 |
| 등록 후 25분 동안 8개 봉만 생성 | 과거 캔들 로드 없이 신규 봉만 생성 |
| SNIPER_TRAP 미감지 (MIN_CANDLES=65 필요) | 8개 봉으로는 EMA60 계산 불가 |

**비교 분석**:

| 함수 | `promote_to_tier1()` | 과거 캔들 |
|------|---------------------|----------|
| `add_manual_stock()` (3076줄) | ✅ 호출 | ✅ 로드 |
| 포지션 오픈 (2383줄) | ✅ 호출 | ✅ 로드 |
| `_register_auto_universe_stock()` (705줄) | ❌ **누락** | ❌ 미로드 |

**수정**: `trading_engine.py:705-710`

```python
# 4. RealTimeDataManager에 Tier 1로 등록 (고속 폴링)
self._data_manager.register_stock(stock_code, Tier.TIER_1, stock_name)
self._logger.info(f"[Auto-Universe] Step 4/5: Tier 1 폴링 등록 - {stock_code}")

# 5. 과거 캔들 로드 (SNIPER_TRAP 신호 탐지에 필요한 65개 3분봉)
await self._data_manager.promote_to_tier1(stock_code)
self._logger.info(f"[Auto-Universe] Step 5/5: 과거 캔들 로드 완료 - {stock_code}")
```

### High 수정

#### [HIGH] 2~3일치 캔들 전량 로드 (HTS 완벽 일치)

**문제**: 100개 캔들로는 EMA 초기 수렴 오차로 HTS와 미세한 차이 발생

| 항목 | 이전 | 이후 |
|------|------|------|
| 1분봉 | 200개 | **600개** (2~3일치) |
| 3분봉 | 100개 | **400개** (2~3일치) |
| API 방식 | 단일 요청 | **연속조회 (pagination)** |

**수정 1**: `market.py:281-400` - 연속조회 지원 추가

```python
async def get_minute_chart(
    self,
    stock_code: str,
    timeframe: int = 1,
    count: int = 400,
    use_pagination: bool = True,  # 신규
) -> List[MinuteCandle]:
    if use_pagination:
        # 연속조회로 모든 데이터 수집
        all_responses = await self._client.paginate(...)
```

**수정 2**: `realtime_data_manager.py:262-272` - 캔들 개수 증가

```python
candles_1m = await self._market_api.get_minute_chart(
    stock_code, timeframe=1, count=600, use_pagination=True
)
candles_3m = await self._market_api.get_minute_chart(
    stock_code, timeframe=3, count=400, use_pagination=True
)
```

**HTS 완벽 일치 보장**:
- 2~3일치 캔들로 EMA 초기 수렴 오차 제거
- 연속조회로 API 한계 극복
- HTS와 동일한 타이밍에 신호 감지

### 테스트 방법

1. 서버 배포 후 로그 확인:
   - `[Auto-Universe] Step 5/5: 과거 캔들 로드 완료`
2. 봉 완성 후 로그 확인:
   - `[신호탐지] {stock_code} 봉 데이터: 1분봉=XXX개, 3분봉=XXX개` (65개 이상)
3. SNIPER_TRAP 조건 충족 시:
   - `[신호감지!] {stock_code} {stock_name}: ['SNIPER_TRAP']`

---

## PRD v3.2.1 Hotfix4 (2025-12-17) - 코드 리팩토링 + 중복 제거

### [M-1] TradingEngine 청산 로직 중복 제거

**문제**: TradingEngine과 ExitManager에 동일한 매도 로직이 중복 존재

| 중복 코드 | 위치 | 줄 수 |
|----------|------|-------|
| `_execute_sell_order` | TradingEngine | 135줄 |
| `_execute_partial_sell_order` | TradingEngine | 150줄 (죽은 코드) |

**수정 내용**:

| 파일 | 변경 | 효과 |
|------|------|------|
| `exit_manager.py` | `pending_sell_orders` 공유 파라미터 추가 | 중복 주문 방지 |
| `trading_engine.py:945` | ExitManager에 `pending_sell_orders` 전달 | 상태 공유 |
| `trading_engine.py:2056-2070` | `_execute_sell_order` → ExitManager 위임 | 135줄 → 5줄 |
| `trading_engine.py:2053-2054` | `_execute_partial_sell_order` 삭제 | 150줄 삭제 |

**총 ~270줄 중복 코드 제거**

```python
# After (ExitManager 위임):
async def _execute_sell_order(self, stock_code, exit_reason, message):
    """매도 주문 실행 (ExitManager 위임) - M-1 리팩토링"""
    await self._exit_manager.execute_full_sell(stock_code, exit_reason, message)
```

### [M-2] Crash Guard 캔들 부족 시나리오 분석

**결론**: 캔들 부족(3분봉 < 20개) 시에도 Safety Net(-3.5%)과 Floor Line 손절로 대손실 방지됨

| 시나리오 | Crash Guard | 보호 장치 |
|---------|-------------|----------|
| 장 시작 직후 (09:00~10:00) | 스킵 | Safety Net (-3.5%) |
| 신규 Auto-Universe 종목 | 스킵 | Safety Net (-3.5%) |
| 시스템 재시작 후 | 스킵 | Floor Line + Safety Net |
| 분할 익절 직후 (1시간+) | 정상 발동 | - |

---

## PRD v3.2.1 Hotfix3 (2025-12-17) - 409 Conflict 해결 + Race Condition 수정

### Critical 수정

#### [P0] 텔레그램 409 Conflict / 명령어 중복 응답

| 증상 | 원인 | 해결 |
|------|------|------|
| `/help` 명령 두 번 응답 | `test_server.ps1`이 SSH로 실행한 고아 프로세스 | 고아 프로세스 종료 |
| 로그에 `409 Conflict` 반복 | systemd 서비스 + 고아 프로세스 동시 폴링 | `kill_orphan.ps1` 스크립트 추가 |

**진단 명령어**: `powershell -ExecutionPolicy Bypass -File "scripts\deploy\check_processes.ps1"`

#### [P0] 공유 Lock 인스턴스 적용 (Race Condition 방지)

| 파일 | 변경 |
|------|------|
| `exit_manager.py` | `order_locks` 파라미터 추가, 공유 Lock 사용 |
| `order_executor.py` | `order_locks` 파라미터 추가, 공유 Lock 사용 |
| `trading_engine.py` | ExitManager, OrderExecutor에 `self._order_locks` 전달 |

**문제**: TradingEngine, ExitManager, OrderExecutor가 각각 독립적인 `_order_locks` 딕셔너리를 가지면 같은 종목에 대해 매수/매도 주문이 동시에 실행될 수 있음

**수정**: TradingEngine의 `_order_locks`를 ExitManager, OrderExecutor에 공유하여 종목별 Lock 일관성 보장

### 추가된 스크립트

| 스크립트 | 용도 |
|---------|------|
| `scripts/deploy/check_processes.ps1` | 서버 Python 프로세스 확인 및 고아 프로세스 감지 |
| `scripts/deploy/kill_orphan.ps1` | 고아 프로세스 자동 종료 |
| `scripts/deploy/stop_service.ps1` | systemd 서비스 중지 |
| `scripts/deploy/start_service.ps1` | systemd 서비스 시작 |

### 문서 업데이트

- `CLAUDE.md`: 2025-12-17 작업 기록 추가, 409 Conflict 진단/해결 방법
- `docs/TROUBLESHOOTING.md`: 텔레그램 409 Conflict 문제 해결 가이드 추가

---

## PRD v3.2.1 Hotfix2 (2025-12-15 23:30) - Auto-Universe 진단 로깅

### 문제: Auto-Universe 조건검색 미동작 (버그 5)

**증상**:
- 조건식에 여러 종목(0126Z0, 0009K0 등)이 포착되었으나 자동 매수 안 됨
- 텔레그램에 조건검색 관련 메시지 전혀 없음
- 서버 로그에 `[PRD v3.1]` 관련 메시지 없음

**추가된 진단 로깅**:

| 파일 | 위치 | 로그 메시지 |
|------|------|------------|
| `trading_engine.py` | 331-333 | `[WS] WebSocket 연결 시도/결과` |
| `trading_engine.py` | 351-354 | `[PRD v3.1] Auto-Universe 설정 확인` |
| `websocket.py` | 609 | `[조건검색] 구독 요청 시작` |
| `websocket.py` | 622-625 | `[조건검색] CNSRREQ 메시지 전송/구독 완료` |

**2025-12-16 장 시작 후 확인 필요**:
```
[WS] WebSocket 연결 결과: {result}
[PRD v3.1] Auto-Universe 설정 확인: enabled={}, seq={}
[조건검색] 구독 완료: seq={}, active_conditions={}
```

---

## PRD v3.2.1 Hotfix (2025-12-15) - Critical 버그 수정

### Critical 수정 (2건)

| # | 문제 | 파일 | 수정 내용 |
|---|------|------|----------|
| 1 | `_indicator` 속성 없음 | `trading_engine.py` | `Indicator.ema()` 정적 메서드로 직접 호출 |
| 2 | DB `entry_source` 컬럼 누락 | `trades` 테이블 | 서버에서 직접 `ALTER TABLE` 실행 |

### Safety Lock/Crash Guard 수정

**문제**: `'SignalDetector' object has no attribute '_indicator'`

**원인**: `Indicator` 클래스는 정적 메서드만 가진 유틸리티 클래스인데, `self._signal_detector._indicator`로 접근 시도

**수정**: 4개 위치에서 직접 `Indicator.ema()` 호출

```python
# Before (잘못됨):
ema20 = self._signal_detector._indicator.ema(closes, period)

# After (올바름):
ema20 = Indicator.ema(candles['close'], period).iloc[-1]
```

**수정 파일**: `src/core/trading_engine.py` (1737, 2048, 2104, 2195번 줄)

### DB 마이그레이션

**문제**: `column trades.entry_source does not exist`

**원인**: SQLAlchemy `create_all()`은 기존 테이블에 새 컬럼을 추가하지 않음

**수정**: 서버에서 직접 `ALTER TABLE` 실행

```sql
ALTER TABLE trades ADD COLUMN entry_source VARCHAR(20) NOT NULL DEFAULT 'SYSTEM';
ALTER TABLE trades ADD COLUMN stop_loss_price INTEGER;
ALTER TABLE trades ADD COLUMN is_partial_exit BOOLEAN DEFAULT FALSE;
ALTER TABLE trades ADD COLUMN entry_floor_line INTEGER;
ALTER TABLE trades ADD COLUMN highest_price_after_partial INTEGER;
```

**주의**: MCP와 서버가 다른 DB 연결을 사용할 수 있음. 항상 서버에서 직접 마이그레이션 필요.

### 기타 수정

| 파일 | 문제 | 해결 |
|------|------|------|
| `auth.py` | 토큰 캐시 Read-only 에러 | 홈 디렉토리 우선, `.resolve()` 사용 |
| `telegram.py` | 400 에러 | `parse_mode` 기본값 `None` |

---

## PRD v3.2.1 (2025-12-14) - 코드 리뷰 패치

### 종합 코드 평가: 4.0/5 (프로덕션 레벨)

| 영역 | 점수 |
|------|------|
| 시스템 설계 구조 | 4.2/5 |
| 코드 일관성 | 4.0/5 |
| 금융 시스템 적합성 | 4.5/5 |
| 에러 핸들링 | 3.8/5 |

### Critical 수정 (3건)

| # | 문제 | 파일 | 수정 내용 |
|---|------|------|----------|
| 1 | 장 종료 미체결 주문 | `trading_engine.py` | 15:25 자동 취소 로직 추가 |
| 2 | 429 Rate Limit 재시도 | `client.py` | tenacity에 `RateLimitError` 추가 |
| 3 | datetime 타임존 | `signal_detector.py` | `datetime.now(KST)` 명시화 |

### High 수정 (3건)

| # | 문제 | 파일 | 수정 내용 |
|---|------|------|----------|
| 4 | 포지션 복구 수량 검증 | `trading_engine.py` | DB-API 수량 비교 로직 추가 |
| 5 | Queue 크기 제한 | `candle_builder.py` | `maxsize=10000` 설정 |
| 6 | DB 격리 수준 | `connection.py` | `REPEATABLE READ` 설정 |

### 신규 환경변수

```bash
VI_TIMEOUT_SECONDS=300  # VI 발동 후 자동 해제 타임아웃 (5분)
```

---

## PRD v3.2 (2025-12-14)

### 주요 변경

| 기능 | 변경 내용 |
|------|----------|
| MAX_POSITIONS | 5 → 3개 제한 |
| 매수 쿨다운 | 시스템 매수 후 30초 전체 매수 금지 |
| EMA20 청산 | 1분봉 → 3분봉 변경 |
| Crash Guard | 현재가 < EMA20 × 0.98 즉시 매도 |
| VI 매도 정지 | VI 발동 시 일부 매도 로직 정지 |

### 환경변수 (신규)

```bash
MAX_POSITIONS=3
BUY_COOLDOWN_SECONDS=30
EXIT_EMA_TIMEFRAME=M3
CRASH_GUARD_ENABLED=true
CRASH_GUARD_RATE=0.98
```

---

## PRD v3.1 (2025-12-12)

### 주요 기능

| 기능 | 설명 |
|------|------|
| Auto-Universe Screener | 조건검색 3단계 필터링 |
| Money Management | 총 평가금액의 5% 베팅 |
| Safety Lock | 이격도 10%+ && 고점 -5% 청산 |
| 1분봉 EMA20 청산 | Wick Protection (종가 기준) |

### 환경변수

```bash
AUTO_UNIVERSE_ENABLED=true
AUTO_UNIVERSE_CONDITION_SEQ=0
AUTO_UNIVERSE_MAX_STOCKS=5
BUY_AMOUNT_RATIO=0.05
EXIT_EMA_ENABLED=true
SAFETY_LOCK_DISPARITY=1.10
```

---

## PRD v3.0 (2025-12-07) - 시스템 안전장치

### 주요 기능

| 기능 | 설명 |
|------|------|
| 장전 데이터 필터링 | 08:30~09:00 예상 체결가 무시 |
| VI 쿨다운 | VI 해제 후 60초간 진입 금지 |
| Global_Lock | KOSDAQ 3분 내 -0.8% → 5분간 매수 중단 |
| 장 시작 갭 대응 | 09:00 갭 손절/익절 즉시 처리 |
| Persistence | highest_price 30초마다 DB 저장 |

---

## PRD v2.5 (2025-12-07) - 리스크 관리 고도화

### 주요 기능

| 기능 | 설명 |
|------|------|
| 기술적 손절 | Floor Line (Lowest 20) 이탈 시 청산 |
| 분할 익절 | +3% → 50% 매도 → 본전컷 |
| Safety Net | -3.5% 하드스탑 |
| 트레일링 스탑 | 최고점 대비 -2.5% 하락 |

### DB 컬럼 추가

```sql
stop_loss_price INTEGER
is_partial_exit BOOLEAN
entry_floor_line INTEGER
highest_price_after_partial INTEGER
```

---

## PRD v2.0 (2025-12-06) - 보조 시스템 전환

### 주요 변경

- "완전 자동매매" → "사용자 보조 시스템" 전환
- EntrySource Enum 추가 (MANUAL, SYSTEM, HTS, RESTORED)
- 포지션 동기화 루프 (1분 간격)
- 조건식 비활성화, 수동 추가 종목만 감시
- SNIPER_TRAP 전략만 활성화

---

## Supabase 마이그레이션 (2025-12-07)

### 생성된 테이블

| 테이블 | 설명 |
|--------|------|
| trades | 거래 내역 |
| orders | 주문 내역 |
| daily_stats | 일일 통계 |
| system_logs | 시스템 로그 |
| signals | 신호 기록 |

### Enum 타입

- `entry_source`: MANUAL, SYSTEM, HTS, RESTORED
- `trade_status`: OPEN, CLOSED
- `order_side`: BUY, SELL
- `order_status`: PENDING, SUBMITTED, PARTIAL, FILLED, CANCELLED, REJECTED

---

## 배포 버전

### v2025.12.14.001 (2025-12-14) - 첫 프로덕션 배포

**배포 정보:**
- 서버: AWS Lightsail (Ubuntu 22.04)
- Python: 3.11.14
- 데이터베이스: PostgreSQL (Supabase)

**수정된 이슈:**
| 이슈 | 원인 | 해결 |
|------|------|------|
| CRLF 줄바꿈 에러 | Windows → Linux 전송 시 CRLF 유지 | `dos2unix` 변환 |
| 버전 형식 오류 | 한국어 로케일 날짜 파싱 | PowerShell `Get-Date` 사용 |
| python3-venv 에러 | python3 → python3.10 참조 | `install.sh`에서 python3.11 명시 |
| ssh.bat 무한 루프 | ssh.exe보다 ssh.bat 우선 실행 | `connect.bat`로 이름 변경 |

---

## 작업 기록 (Work Log)

### 2026-01-05
- **V6.2-A: 신호 큐 + Active Pool 확장**
- 신호 큐 구현: 쿨다운 중 SNIPER_TRAP 신호 유실 방지
- Active Pool 5개 → 10개 확장
- 시스템 쿨다운 30초 → 15초 단축
- CLAUDE.md PowerShell 인코딩 경고 섹션 추가
- .env UTF-16 인코딩 사고 해결 및 문서화

### 2025-12-23
- **PRD v3.2.4: ATR 지저깨 실시간 알림 시스템**
- 신규 파일: `atr_alert_manager.py`
- `indicator.py`: ATR 메서드 3개 추가, 기본값 period=14 (HTS 기본값)
- `trading_engine.py`: AtrAlertManager 통합 + Manual Buy Floor Line 추가
- `config.py`: ATR 알림 설정 6개 추가

### 2025-12-22
- **PRD v3.2.3: 트레일링 본전컷 + HTS Floor Line**
- 트레일링 본전컷: +2.5% 도달 후 0% 이하 시 본전컷 매도
- HTS 매수 Floor Line 자동 설정 (Lowest L20 기반)
- Floor Line 계산 버그 수정 (.low → .low_price)

### 2025-12-18
- **PRD v3.2.2: 거래 모드 시스템 (MANUAL_ONLY / AUTO_UNIVERSE)**
- HTS 매수 종목 분할익절 제외
- 매직넘버 상수화, 미사용 텔레그램 명령어 제거

### 2025-12-17
- **[CRITICAL] Auto-Universe 과거 캔들 로드 누락 수정**
- **[CRITICAL] 텔레그램 409 Conflict 해결** (고아 프로세스 종료)
- 2~3일치 캔들 전량 로드 (600개 1분봉, 400개 3분봉)
- 공유 Lock 인스턴스 적용 (Race Condition 방지)
- TradingEngine 청산 로직 중복 제거 (~270줄)

### 2025-12-16
- Auto-Universe 조건검색 미동작 버그 수정
- CNSRREQ 응답 대기 패턴 적용

### 2025-12-15
- **[CRITICAL] Safety Lock/Crash Guard `_indicator` 속성 에러 수정**
- **[CRITICAL] DB `entry_source` 컬럼 누락 수정** (ALTER TABLE 직접 실행)
- 토큰 캐시 경로 문제 수정 (홈 디렉토리 우선)
- 텔레그램 parse_mode 에러 수정

### 2025-12-14
- **AWS Lightsail 첫 프로덕션 배포 완료** (v2025.12.14.001)
- 배포 스크립트 버그 수정 (날짜 파싱, CRLF, python3.11)
- `ssh.bat` → `connect.bat` 이름 변경 (무한 루프 해결)
- 서버 배포 스크립트 생성 (deploy.bat, connect.bat, status.bat 등)
- launcher.py 생성 (PreFlight Check 포함)
- k-stock-trading.service 생성 (systemd)
- /start 핸들러 블로킹 버그 수정 (asyncio.create_task)

### 2025-12-11
- 코드 리뷰 및 Critical 이슈 수정
- 분할 익절 기준 2.5% → 3%
- 포지션 동기화 간격 60초 → 5초

### 2025-12-10
- 종합 코드 리뷰 (financial-system-code-reviewer)
- PositionManager/RiskManager 수량 동기화 구현
- position.signal_metadata 오타 수정

### 2025-12-08
- 분할 익절 중복 실행 버그 수정
- on_partial_exit() 인자 오류 수정

### 2025-12-07
- PRD v3.0 시스템 안전장치 구현
- PRD v2.5 트레일링 스탑 구현
- Supabase 마이그레이션 완료

### 2025-12-06
- PRD v2.0 보조 시스템 리팩토링

### 2025-12-04
- 신호 탐지 수식 수정
- 분봉 API 정확도 개선

### 2025-12-03
- Supabase PostgreSQL 연동
- Trade/Order 거래 기록 자동화
- Circuit Breaker 구현

### 2025-12-02
- REST 폴링 구현
- WebSocket 안정화
