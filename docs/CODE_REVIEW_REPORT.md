# K_stock_trading V7.0 전체 코드 리뷰 보고서

> **리뷰 범위**: ~24,000줄, 38개 파일 (핵심 14,053줄 + 보조 8,544줄 + 베이스 1,359줄)
> **리뷰 일시**: 2026-02-04
> **리뷰 방법**: 6단계 전문 에이전트 병렬 분석 (아키텍처, 신호탐지, 청산/리스크, 주문/동기화, 리팩토링, 인프라)

---

## 목차

1. [종합 요약](#1-종합-요약)
2. [발견된 문제점 전체 목록](#2-발견된-문제점-전체-목록)
3. [Step 1: 시스템 아키텍처 리뷰](#3-step-1-시스템-아키텍처-리뷰)
4. [Step 2: V7 신호 탐지 시스템 리뷰](#4-step-2-v7-신호-탐지-시스템-리뷰)
5. [Step 3: 청산/리스크 시스템 리뷰](#5-step-3-청산리스크-시스템-리뷰)
6. [Step 4: 주문 실행 및 포지션 동기화 리뷰](#6-step-4-주문-실행-및-포지션-동기화-리뷰)
7. [Step 5: 리팩토링 품질 평가](#7-step-5-리팩토링-품질-평가)
8. [Step 6: 인프라/보조 시스템 리뷰](#8-step-6-인프라보조-시스템-리뷰)
9. [불변조건 준수 현황](#9-불변조건-준수-현황)
10. [우선순위별 개선 권고사항](#10-우선순위별-개선-권고사항)
11. [엔터프라이즈 적합성 총평](#11-엔터프라이즈-적합성-총평)

---

## 1. 종합 요약

### 전체 평가: B+ (Good)

Phase 3 리팩토링으로 의미 있는 개선이 달성되었으며, V7 모듈들(V7SignalCoordinator, ExitCoordinator, PositionSyncManager, SignalProcessor)은 깔끔한 책임 분리와 콜백 기반 DI로 독립 테스트가 가능합니다. ABC 계층(BaseSignal, BaseDetector, BaseExit)은 SOLID 원칙을 잘 따르고 있으며, 핵심 불변조건(ATR 배수 단방향, TS 상향 전용, EMA adjust=False)은 다중 방어 계층으로 보호됩니다.

그러나 **안전성에 직접 영향을 미치는 Critical 이슈 11건**이 발견되었으며, 특히 -4% Hard Stop 비교 연산자 불일치, Circuit Breaker가 Hard Stop을 차단하는 문제, 포지션 동기화와 주문 실행 간 Lock 미공유 문제는 즉시 대응이 필요합니다.

### 통계 요약

| 심각도 | 건수 | 핵심 영역 |
|--------|------|-----------|
| **Critical** | 11건 | Hard Stop 불일치, 신호 손실, Lock 부재, 시간 계산 오류 |
| **Major** | 16건 | 중복 계산, 상수 중복, Rate Limit 경합, V6 잔재 |
| **Minor** | 17건 | 네이밍, 하드코딩, 캡슐화, 테스트 용이성 |
| **합계** | **44건** | |

---

## 2. 발견된 문제점 전체 목록

### Critical (11건) -- 즉시 대응 필요

| ID | 영역 | 설명 | 위치 | 상태 |
|----|------|------|------|------|
| **C-01** | 청산 | **-4% Hard Stop 비교 연산자 불일치**: `<` → `<=` 통일 | `wave_harvest_exit.py:628` | ✅ 수정 |
| **C-02** | 청산 | **Circuit Breaker가 Hard Stop 차단**: Hard Stop을 CB 이전으로 이동 | `exit_coordinator.py:183-220` | ✅ 수정 |
| **C-03** | 청산 | **check_hard_stop() 파라미터 순서 반전**: BaseExit와 통일 (entry, current) | `wave_harvest_exit.py:618` | ✅ 수정 |
| **C-04** | 신호 | **bar_close_time=None TypeError**: None 가드 추가 | `v7_signal_coordinator.py:508-511` | ✅ 수정 |
| **C-05** | 신호 | **Confirm-Check 예외 DEBUG 레벨**: WARNING으로 상향 | `v7_signal_coordinator.py:430` | ✅ 수정 |
| **C-06** | 동기화 | **PositionSync Lock 미공유**: is_ordering_stock 콜백 추가 | `position_sync_manager.py` | ✅ 수정 |
| **C-07** | 동기화 | **HTS 매도 감지 시 실제 매도가 미확인**: 캐시된 가격 사용 | `position_sync_manager.py:494` | 미수정 (API 제한) |
| **C-08** | 인프라 | **HALF_OPEN 다중 요청 허용**: 단일 요청 제한 | `client.py:83-93` | ✅ 수정 |
| **C-09** | 인프라 | **PRE_MARKET_START 계산 오류**: 08:30→08:50 복원 | `market_schedule.py:67-68` | ✅ 수정 |
| **C-10** | 인프라 | **공휴일 하드코딩**: config/holidays.json 동적 로딩 | `market_schedule.py:367-418` | ✅ 수정 |
| **C-11** | 인프라 | **private dict 직접 접근**: get_all_position_risks() 스냅샷 | `background_task_manager.py:522` | ✅ 수정 |

### Major (16건) -- 다음 배포 전 대응 권고

| ID | 영역 | 설명 | 위치 | 상태 |
|----|------|------|------|------|
| **M-01** | 청산 | update_and_check()에 Hard Stop 선검사 추가 | `wave_harvest_exit.py:591-592` | ✅ 수정 |
| **M-02** | 청산 | Trend Hold ATR 조건 문서화 | `ARCHITECTURE.md` | ✅ 문서화 |
| **M-03** | 청산 | CB 중 V7 Exit empty → Safety Net 미도달 | `exit_coordinator.py` | ✅ C-02로 해결 |
| **M-04** | 신호 | Confirm-Check 이중 계산 제거 (5/5 시만 detect_signal) | `v7_signal_coordinator.py:403-430` | ✅ 수정 |
| **M-05** | 신호 | 상수 이중 정의 → PurpleConstants import 통일 | `indicator_purple.py:22-39` | ✅ 수정 |
| **M-06** | 신호 | asyncio.gather Semaphore(20) 동시성 제한 | `v7_signal_coordinator.py:99,265,387` | ✅ 수정 |
| **M-07** | 아키텍처 | SignalProcessor V6 구체 Signal 타입 import | `signal_processor.py:37` | 장기 |
| **M-08** | 아키텍처 | 콜백 dataclass Optional 구분 없음 | `v7_signal_coordinator.py:34-71` | 장기 |
| **M-09** | 아키텍처 | position_strategies 공유 dict 통합 | `trading_engine.py:461,1093` | ✅ 수정 |
| **M-10** | 아키텍처 | PositionSync SNIPER_TRAP 하드코딩 | `position_sync_manager.py:415` | 장기 |
| **M-11** | 동기화 | 주문 Lock 30초 타임아웃 추가 | `order_executor.py:223-229` | ✅ 수정 |
| **M-12** | 동기화 | KST-aware vs naive datetime 혼재 | `candle_builder.py:58` | 장기 |
| **M-13** | 동기화 | Rate Limit 경합 (V7 SIGNAL_ALERT에서 해당 없음) | `realtime_data_manager.py` | 해당 없음 |
| **M-14** | 인프라 | 7개 배경 루프 CancelledError 전체 처리 | `background_task_manager.py` | ✅ 수정 |
| **M-15** | 인프라 | _chunked_sleep(3600)으로 long sleep 분할 | `background_task_manager.py:148` | ✅ 수정 |
| **M-16** | 인프라 | auto_screener fire-and-forget 예외 미처리 | `auto_screener.py:421-423` | 장기 |

### Minor (17건)

| ID | 설명 | 위치 |
|----|------|------|
| m-01 | `bar_close_time` 변수명이 실제로는 bar start | `v7_signal_coordinator.py:372` |
| m-02 | IndicatorLibrary.ema()가 adjust=True 허용 | `indicator_library.py:37` |
| m-03 | indicator_purple.py 내 중복 지표 계산 (h1l1/rise_ratio 등) | `indicator_purple.py:377-427` |
| m-04 | confidence 계산 주석의 단위 불일치 | `signal_detector_purple.py:209` |
| m-05 | DualPassMixin.pre_check() 기본 True 반환 | `base_detector.py:266` |
| m-06 | HighestHigh 비교 >= vs 스펙의 > | `wave_harvest_exit.py:454` |
| m-07 | V6/V7 holding days 계산 방식 불일치 (달력일 vs 영업일) | `wave_harvest_exit.py:645` |
| m-08 | ExitReason import 출처 불일치 (risk_manager vs exit_manager) | 다수 |
| m-09 | TradingEngine의 legacy _signal_queue 잔재 | `trading_engine.py:363-365` |
| m-10 | _get_market_status()가 TradingTimeConstants 미사용 | `trading_engine.py:1800-1805` |
| m-11 | TrendHoldMixin의 lazy import | `base_exit.py:331` |
| m-12 | HTS 매수 시 StrategyType 하드코딩 | `manual_command_handler.py:338` |
| m-13 | WebSocketManager가 private _is_reconnecting 접근 | `websocket_manager.py:266` |
| m-14 | auto_screener 내 timezone aware/naive 혼재 | `auto_screener.py:846-847` vs 기타 |
| m-15 | market_schedule 싱글턴이 테스트 비친화적 | `market_schedule.py:428-437` |
| m-16 | _get_daily_data_v62a 6-element tuple 반환 | `auto_screener.py:678-730` |
| m-17 | MinuteCandle→Candle 변환 3회 중복 | `trading_engine.py:1356, 2930, 2948` |

---

## 3. Step 1: 시스템 아키텍처 리뷰

### 전체 구조 평가

시스템은 **부분적 Clean Architecture**를 따릅니다:
- 의존성 방향은 올바름 (인프라 → 코어, 역방향 없음)
- 콜백 패턴으로 순환 의존성 성공적 차단
- 그러나 명시적 Ports 계층 부재 -- 도메인이 구체 인프라에 간접 결합

### 모듈 의존성

- **순환 의존성: 없음** -- V7Callbacks, SyncCallbacks 등 dataclass 기반 콜백이 효과적으로 차단
- PositionManager ↔ RiskManager 간 양방향 참조 존재 (`set_position_manager`/`set_risk_manager`)
- TradingEngine이 40+ 모듈 import -- 변경 파급 범위 과도

### ABC 계층 설계: 우수

| ABC | 평가 | 특징 |
|-----|------|------|
| BaseSignal | Good | @dataclass + ABC, Template Method |
| BaseDetector | Good | MultiConditionMixin, DualPassMixin |
| BaseExit | Excellent | enforce_stop_direction, enforce_multiplier_direction |
| BaseStrategy | Good | 명확한 lifecycle hooks |

### 전략 패턴 확장성

V8 전략 추가 시:
- 새 detector/exit/strategy 파일 생성: **쉬움**
- StrategyOrchestrator 등록: **쉬움** (1줄)
- ExitCoordinator 라우팅: **중간** (V6/V7 하드코딩 분기 수정 필요)
- TradingEngine candle 처리: **중간** (V6 exit 로직이 인라인)

---

## 4. Step 2: V7 신호 탐지 시스템 리뷰

### Dual-Pass 구조: 우수

- Pre-Check (봉 마감 30초 전): 3/5 조건 이상 → 후보 등록
- Confirm-Check (봉 마감 5초 내): 5/5 조건 확인
- Late-arriving 종목 안전망 포함
- NearMiss (4/5) 로깅으로 사후 분석 지원

### 신호 중복 방지 (C-007 FIX): 우수

2계층 방어:
1. Layer 1 (비원자적): `can_signal_new_bar()` -- 빠른 경로 최적화
2. Layer 2 (원자적): `update_signal_bar()` -- threading.Lock 하 check-and-update

두 계층 사이에 await 지점이 없어 race condition 없음.

### Thread Safety: 양호

- threading.RLock + asyncio.Lock 혼재 사용 -- 실해 없으나 의도적 defense-in-depth로 문서화 필요
- 데드락 위험: 없음 (중첩 Lock 획득 패턴 없음)

### 불변조건 준수: 모두 PASS

| 항목 | 상태 |
|------|------|
| Score 가중치 (2.0, 0.8, 1.2) | PASS |
| PurpleOK (4%, 7%, 5억) | PASS |
| Zone (EMA60 x 0.995) | PASS |
| EMA adjust=False | PASS |

---

## 5. Step 3: 청산/리스크 시스템 리뷰

### ATR 배수 단방향 축소: PASS -- 3중 방어

1. `get_multiplier()`: 모든 분기에서 `min()` 사용
2. `update_and_check()`: `new_mult < state.current_multiplier` 일 때만 갱신
3. `BaseExit.enforce_multiplier_direction()`: `min(new, current)` 반환

R-multiple이 하락 후 재상승해도 배수는 복원되지 않음. **검증 완료.**

### 트레일링 스탑 단방향 상승: PASS

- `update_stop()`: `max(new_stop, prev_stop)`
- `enforce_stop_direction()`: `max(new_stop, current_stop)`
- 초기값: `entry_price * 0.96` (-4% 하한)
- **0이거나 보호되지 않는 구간 없음.**

### Hard Stop -4%: 조건부 PASS

ExitCoordinator에서 Hard Stop이 Trend Hold보다 먼저 검사됨 (정확한 순서). 그러나:
- **C-01**: 비교 연산자 불일치 (`<` vs `<=`)
- **C-02**: Circuit Breaker가 Hard Stop도 차단
- **M-01**: `update_and_check()` 단독 호출 시 Hard Stop 미검사

### Trend Hold Filter: DEVIATION

스펙: `EMA20 > EMA60 AND HighestHigh(20) > HighestHigh(60)`
구현: 위 조건 + **ATR 유지 조건** (미문서화)

추가 ATR 조건은 Trend Hold를 더 어렵게 만들어 (더 많이 청산) 안전한 방향이지만, "수정 불가" 항목 위반.

---

## 6. Step 4: 주문 실행 및 포지션 동기화 리뷰

### Per-stock Lock: 양호 (타임아웃 부재)

- 종목코드 기반 asyncio.Lock 생성/관리
- Lock 후 포지션 더블체크 패턴 적용
- **문제**: Lock 타임아웃 없음, 매도와의 Lock 공유 여부 불확실

### Circuit Breaker: 기본 구현

- 3-상태 (CLOSED/OPEN/HALF_OPEN) 올바른 전이
- `time.monotonic()` 사용
- **문제**: HALF_OPEN에서 모든 요청 허용, 트리거 시 로깅 부족

### HTS 매매 감지: 양호 (동시성 보호 부재)

- API vs Local set 연산으로 깔끔한 3케이스 분리
- **문제**: sync_positions()에 Lock 없음, exit_price에 캐시 가격 사용

### CandleBuilder: 우수

- C-003 역순 틱 처리 완성
- 버퍼링 + 시간순 정렬로 네트워크 지연 보상
- Queue overflow 시 최신 데이터 우선
- **문제**: KST-aware vs naive datetime 혼재

---

## 7. Step 5: 리팩토링 품질 평가

### TradingEngine: 여전히 God Class

**3,109줄**, `__init__` 475줄, 30+ 의존성 인라인 생성

| 분리 가능 영역 | 예상 줄 수 | 우선순위 |
|----------------|-----------|----------|
| VIManager | ~100줄 | 높음 |
| MarketTimeManager | ~120줄 | 높음 |
| V6 Exit Checks (CrashGuard, SafetyLock, EMA20) | ~230줄 | 높음 |
| CandleDataService | ~120줄 | 중간 |
| PendingSellOrderTracker | ~120줄 | 중간 |

Phase 4-5 완료 시 **~2,400줄로 축소** 가능 (원본 5,769줄에서 58% 감소).

### 코드 중복

| 중복 | 위치 수 | 영향 |
|------|---------|------|
| MinuteCandle→Candle 변환 | 3곳 | 중간 |
| position_strategies 매핑 | 2곳 | 높음 (데이터 일관성) |
| 시장 시간 상수 | 2곳 | 낮음 |

### 테스트 용이성

| 모듈 | 테스트 가능성 | 이유 |
|------|-------------|------|
| ExitCoordinator | Good | 콜백 DI, 순수 결정 로직 |
| SignalProcessor | Good | 콜백 DI, 상태 격리 |
| PositionSyncManager | Good | 콜백 DI |
| V7SignalCoordinator | Fair | 모듈 레벨 import 잔재 |
| TradingEngine | **Poor** | 475줄 __init__, 전역 상태, 30+ 구체 의존성 |

---

## 8. Step 6: 인프라/보조 시스템 리뷰

### WebSocket 관리: 양호

- 재연결 실패 시 엔진 일시정지: 올바른 안전 대책
- 복구 3단계 (구독 → 포지션 → 트레일링 스탑) 각각 try/except
- **문제**: private 속성 접근, heartbeat 미확인

### 백그라운드 태스크: 개선 필요

- 7개 루프 중 CancelledError 핸들링 1개뿐
- 24시간 단일 sleep 호출 -- 종료 지연
- private dict 직접 접근 (`_position_risks`)

### 시장 스케줄: 개선 필요

- 정규장/NXT 시간 정확
- **PRE_MARKET_START 계산 오류** (08:50→08:30)
- **공휴일 2026년까지만 하드코딩**
- 전체적으로 naive datetime 사용

### 텔레그램: 양호

- parse_mode 사용 시도를 자동 차단 (CLAUDE.md 규칙 준수)
- 메시지 큐잉 없음 (전송 실패 시 유실)

### V6 레거시 상태

- V6 전용 배경 태스크 제거됨 (good)
- manual_command_handler, position_sync_manager에 SNIPER_TRAP 하드코딩 잔재
- TradingEngine 내 V6 exit 로직(CrashGuard, SafetyLock, EMA20) ~230줄 잔존

---

## 9. 불변조건 준수 현황

| 불변조건 | 상태 | 비고 |
|---------|------|------|
| Score 가중치: (C/W-1)*2, LZ*0.8, recovery*1.2 | **PASS** | indicator_purple.py:31-33 |
| PurpleOK: 상승률 4%, 수렴률 7%, 거래대금 5억 | **PASS** | indicator_purple.py:36-38 |
| Zone: EMA60 x 0.995 | **PASS** | indicator_purple.py:39 |
| ATR 배수: 6.0→4.5→4.0→3.5→2.5→2.0 | **PASS** | wave_harvest_exit.py:38-43, 3중 방어 |
| Trend Hold Filter 조건 | **DEVIATION** | 미문서화 ATR 조건 추가 |
| EMA adjust=False | **PASS** | IndicatorLibrary.ema() 기본값 |
| Risk-First (-4% 무조건 작동) | **PASS** | C-01 `<=`통일 + C-02 CB우회 + C-03 파라미터순서 수정완료 |
| TS 상향 전용 | **PASS** | max() 패턴 + enforce_stop_direction |
| ATR 배수 단방향 | **PASS** | min() 패턴 + enforce_multiplier_direction |

---

## 10. 우선순위별 개선 권고사항

### Priority 1: 즉시 수정 (안전성 직결)

| # | 작업 | 대상 | 영향 |
|---|------|------|------|
| 1 | -4% Hard Stop 비교 연산자를 `<=`로 통일 (C-01) | `wave_harvest_exit.py:628` | Hard Stop 정확성 |
| 2 | Circuit Breaker 이전에 Hard Stop 검사 이동 (C-02) | `exit_coordinator.py:184-189` | Risk-First 복구 |
| 3 | bar_close_time=None 가드 추가 (C-04) | `v7_signal_coordinator.py:372-508` | Zero Signal Miss |
| 4 | Confirm-Check 예외를 WARNING으로 상향 + MissedSignalTracker 연동 (C-05) | `v7_signal_coordinator.py:429` | 감사 추적 |
| 5 | PRE_MARKET_START 계산 수정 (C-09) | `market_schedule.py:67-68` | 시장 타이밍 |
| 6 | _position_risks를 public 스냅샷으로 접근 (C-11) | `background_task_manager.py:522` | 루프 안정성 |

### Priority 2: 다음 배포 전 (정확성/안정성)

| # | 작업 | 대상 |
|---|------|------|
| 7 | PositionSync에 주문 상태 인지 추가 (C-06) | `position_sync_manager.py` |
| 8 | HALF_OPEN 단일 요청 제한 (C-08) | `client.py` |
| 9 | 공휴일 동적 로딩 구현 (C-10) | `market_schedule.py` |
| 10 | update_and_check()에 Hard Stop 추가 (M-01) | `wave_harvest_exit.py` |
| 11 | Confirm-Check 이중 계산 제거 (M-04) | `v7_signal_coordinator.py` |
| 12 | 상수 단일 소스 통합 (M-05) | `indicator_purple.py` → `constants.py` import |
| 13 | position_strategies 매핑 통합 (M-09) | `exit_coordinator.py` / `strategy_orchestrator.py` |
| 14 | datetime.now(KST) 전체 통일 (M-12, 인프라 M-04) | 시스템 전체 |

### Priority 3: 중기 리팩토링

| # | 작업 | 예상 효과 |
|---|------|-----------|
| 15 | VIManager 추출 | TradingEngine -100줄 |
| 16 | V6 Exit 로직 추출 | TradingEngine -230줄 |
| 17 | MarketTimeManager 추출 | TradingEngine -120줄 |
| 18 | Protocol 기반 콜백 인터페이스 전환 | 타입 안전성 향상 |
| 19 | asyncio.Semaphore 추가 (신호 탐지) | 메모리 안전성 |
| 20 | CancelledError 핸들링 전체 적용 | graceful shutdown |
| 21 | check_hard_stop() 파라미터 순서 통일 | 유지보수성 |
| 22 | Trend Hold ATR 조건 문서화 또는 제거 | 스펙 일치 |

### Priority 4: 장기 아키텍처 개선

| # | 작업 | 설명 |
|---|------|------|
| 23 | Ports & Adapters 계층 도입 | `src/core/ports/` Protocol 정의 |
| 24 | TradingEngine __init__ Builder 패턴 전환 | 475줄 생성자 해소 |
| 25 | 이벤트 기반 아키텍처 검토 | 콜백 폭발 해소 |

---

## 11. 엔터프라이즈 적합성 총평

### 강점

1. **다중 방어 계층**: ATR 배수(3중), 트레일링 스탑(2중), 신호 중복방지(2중)로 핵심 불변조건을 강건하게 보호
2. **Phase 3 리팩토링 성과**: V7 모듈들의 책임 분리가 명확하고 독립 테스트 가능
3. **ABC 계층 설계**: BaseExit의 `enforce_stop_direction`/`enforce_multiplier_direction`이 파생 클래스의 실수를 구조적으로 차단
4. **Dual-Pass 신호 탐지**: Pre-Check(빠른 필터) → Confirm-Check(정밀 확인) 구조가 Zero Signal Miss와 성능을 동시에 달성
5. **실전 운영 학습 반영**: C-003(역순 틱), C-007(중복 신호), Ghost Order 방지 등 실전에서 발견된 문제의 방어 코드가 충실

### 개선 영역

1. **Risk-First 원칙의 일관성**: -4% Hard Stop이 일부 경로에서 비일관적으로 동작 (C-01, C-02)
2. **동시성 안전성**: Lock 공유 부재(C-06), Lock 타임아웃 부재(M-11)
3. **God Class 잔재**: TradingEngine 3,109줄로 여전히 과도
4. **운영 안정성**: 공휴일 하드코딩(C-10), naive datetime(M-12), 단일 sleep(M-15)
5. **테스트 인프라**: TradingEngine이 사실상 테스트 불가능한 구조

### 결론

V7 Purple-ReAbs의 **핵심 트레이딩 로직**(신호 탐지, ATR 배수 관리, 트레일링 스탑)은 높은 품질을 보여줍니다. Phase 3 리팩토링으로 V7 모듈들은 엔터프라이즈 수준에 근접합니다. 그러나 **인프라 계층과 TradingEngine**은 추가 개선이 필요하며, 특히 Priority 1의 6개 항목은 실제 자금 손실 위험과 직결되므로 즉시 대응을 권고합니다.

**전체 등급**: Phase 3 모듈 A-, TradingEngine C+, 인프라 B-, **종합 B+**

---

> **수정 현황 (2026-02-04)**: Critical 11건 중 10건 수정, Major 16건 중 11건 수정/해결, Minor 17건 미수정 (장기).
> 미수정 Critical: C-07 (HTS 매도가 API 제한). 미수정 Major: M-07, M-08, M-10, M-12, M-16 (장기 리팩토링).
