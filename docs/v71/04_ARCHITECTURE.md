# V7.1 아키텍처 (Architecture)

> 이 문서는 V7.1 시스템의 **모듈 구조와 책임 분담**을 정의합니다.
> 
> V7.0 인프라를 유지하면서 V7.1 신규 기능을 격리된 패키지에 추가하는 방식입니다.
> 
> **충돌 금지 원칙(헌법 3)이 이 문서의 핵심 기준입니다.**

---

## 목차

- [§0. 아키텍처 원칙](#0-아키텍처-원칙)
- [§1. 시스템 전체 구조](#1-시스템-전체-구조)
- [§2. 모듈 분류 (유지/수정/삭제/신규)](#2-모듈-분류-유지수정삭제신규)
- [§3. V7.1 신규 패키지 (src/core/v71/)](#3-v71-신규-패키지-srccorev71)
- [§4. 데이터 흐름](#4-데이터-흐름)
- [§5. 의존성 그래프](#5-의존성-그래프)
- [§6. 동시성 모델](#6-동시성-모델)
- [§7. 외부 시스템 통합](#7-외부-시스템-통합)
- [§8. 배포 아키텍처](#8-배포-아키텍처)

---

## §0. 아키텍처 원칙

### 0.1 V7.1 아키텍처 5원칙

```yaml
원칙 1: 격리 (Isolation)
  V7.1 신규 모듈은 src/core/v71/ 패키지에 집중
  V7.0 인프라는 그대로 유지
  명확한 경계 (boundary)

원칙 2: 단방향 의존 (Unidirectional Dependency)
  V7.1 → V7.0 인프라 (허용)
  V7.0 인프라 → V7.1 (금지)
  순환 의존 금지

원칙 3: Feature Flag (점진적 전환)
  V7.1 기능은 Flag로 ON/OFF
  V7.0 운영 중 V7.1 점진 활성화
  문제 발생 시 즉시 비활성화

원칙 4: 책임 분리 (Single Responsibility)
  각 모듈은 명확한 단일 책임
  거대한 trading_engine.py 같은 것 지양
  
원칙 5: 테스트 가능성 (Testability)
  의존성 주입 (DI) 패턴
  Mock 가능한 인터페이스
  단위 테스트 친화적
```

### 0.2 V7.0과의 차별점

```yaml
V7.0 (제거 대상):
  - 거대 trading_engine.py (4,904줄)
  - 신호 시스템 복잡 (5조건, Dual-Pass, Pool)
  - 자동 종목 선별 (조건검색)
  - 백테스트 시스템
  - V6/V7 이중 전략 조율

V7.1 (단순화):
  - 작은 모듈 다수 (각 책임 명확)
  - 박스 기반 단순 진입 (사용자 입력)
  - 종목 선별 = 사용자 책임
  - 백테스트 없음 (페이퍼 트레이드만)
  - 단일 전략 (박스 눌림/돌파)
```

### 0.3 헌법 5원칙 적용

```yaml
원칙 1 (사용자 판단 불가침):
  → 박스 시스템 설계 (사용자 입력만)
  → 자동 추천 코드 없음

원칙 2 (NFR1 최우선):
  → 시세 모니터링 우선순위
  → 지연 측정 메트릭

원칙 3 (충돌 금지):
  → src/core/v71/ 격리 패키지
  → V71 접두사 명명

원칙 4 (시스템 계속 운영):
  → 자동 정지 코드 없음
  → 안전 모드 기반 복구

원칙 5 (단순함 우선):
  → 작은 모듈 다수
  → 명시적 흐름
```

---

## §1. 시스템 전체 구조

### 1.1 레이어 구조

```
┌─────────────────────────────────────────────────────────────┐
│                    Presentation Layer                        │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ Web Dashboard    │  │ Telegram Bot     │                 │
│  │ (React + shadcn) │  │ (명령어 + 알림)  │                 │
│  └────────┬─────────┘  └────────┬─────────┘                 │
└───────────┼──────────────────────┼──────────────────────────┘
            │                      │
            ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│                     API Layer (src/web/)                     │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ REST API         │  │ WebSocket Server │                 │
│  │ (FastAPI)        │  │ (실시간 push)    │                 │
│  └────────┬─────────┘  └────────┬─────────┘                 │
│           │                      │                           │
│  ┌────────┴──────────────────────┴────────┐                 │
│  │ Auth (JWT, 2FA)                       │                 │
│  └────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│              Business Logic Layer (src/core/)                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ src/core/v71/ (V7.1 신규 - 격리 패키지)              │   │
│  │   ┌────────────┐  ┌─────────────┐  ┌──────────────┐  │   │
│  │   │ box/       │  │ strategies/ │  │ path_manager │  │   │
│  │   │ - manager  │  │ - pullback  │  │              │  │   │
│  │   │ - detector │  │ - breakout  │  │              │  │   │
│  │   │ - state    │  │             │  │              │  │   │
│  │   └────────────┘  └─────────────┘  └──────────────┘  │   │
│  │   ┌────────────┐  ┌─────────────┐  ┌──────────────┐  │   │
│  │   │ vi_monitor │  │ exit/       │  │ position/    │  │   │
│  │   │            │  │ - calculator│  │ - manager    │  │   │
│  │   │            │  │ - executor  │  │ - reconciler │  │   │
│  │   └────────────┘  └─────────────┘  └──────────────┘  │   │
│  │   ┌────────────┐  ┌─────────────┐  ┌──────────────┐  │   │
│  │   │ report/    │  │ event_logger│  │ restart_     │  │   │
│  │   │ - generator│  │             │  │ recovery     │  │   │
│  │   │ - storage  │  │             │  │              │  │   │
│  │   └────────────┘  └─────────────┘  └──────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ V7.0 인프라 (유지)                                    │   │
│  │   - candle_builder, websocket_manager                 │   │
│  │   - market_schedule, indicator_library, constants     │   │
│  │   - order_executor (수정), risk_manager (수정)        │   │
│  │   - position_manager (확장), position_sync_manager    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│           Infrastructure Layer (V7.0 유지)                   │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ src/api/         │  │ src/database/    │                 │
│  │ (키움 REST + WS) │  │ (Supabase)       │                 │
│  └──────────────────┘  └──────────────────┘                 │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ src/notification │  │ src/utils/       │                 │
│  │ (텔레그램)       │  │ (config, logger) │                 │
│  └──────────────────┘  └──────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│                    External Systems                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │
│  │ 키움 API │ │ Supabase │ │ Telegram │ │ Claude API   │    │
│  │ REST/WS  │ │ Postgres │ │ Bot API  │ │ (Opus 4.7)   │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 디렉토리 구조 (완성 시)

```
K_stock_trading/
├── src/
│   ├── main.py                          # 엔트리포인트 (수정)
│   │
│   ├── api/                             # 키움 API (V7.0 유지)
│   │   ├── client.py                    # Rate Limiter + 재시도
│   │   ├── websocket.py                 # WebSocket 클라이언트
│   │   ├── auth.py                      # OAuth 인증
│   │   └── endpoints/
│   │       ├── order.py
│   │       ├── market.py
│   │       ├── account.py
│   │       └── condition.py             # (사용 안 함, V7.1)
│   │
│   ├── core/                            # 비즈니스 로직
│   │   │
│   │   ├── v71/                         # ★ V7.1 신규 패키지 ★
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   ├── box/                     # 박스 시스템
│   │   │   │   ├── __init__.py
│   │   │   │   ├── box_manager.py
│   │   │   │   ├── box_entry_detector.py
│   │   │   │   └── box_state_machine.py
│   │   │   │
│   │   │   ├── strategies/              # 진입 전략
│   │   │   │   ├── __init__.py
│   │   │   │   ├── v71_box_pullback.py
│   │   │   │   └── v71_box_breakout.py
│   │   │   │
│   │   │   ├── exit/                    # 청산 시스템
│   │   │   │   ├── __init__.py
│   │   │   │   ├── exit_calculator.py
│   │   │   │   ├── exit_executor.py
│   │   │   │   └── trailing_stop.py
│   │   │   │
│   │   │   ├── position/                # 포지션 관리 (V7.1 확장)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── v71_position_manager.py
│   │   │   │   └── v71_reconciler.py
│   │   │   │
│   │   │   ├── path_manager.py          # 이중 경로 (A/B)
│   │   │   ├── vi_monitor.py            # VI 처리
│   │   │   ├── event_logger.py          # 이벤트 로깅 표준
│   │   │   ├── restart_recovery.py      # 재시작 복구
│   │   │   ├── audit_scheduler.py       # 박스 진입 누락 감사
│   │   │   ├── v71_constants.py         # V7.1 상수
│   │   │   │
│   │   │   ├── report/                  # 리포트 시스템
│   │   │   │   ├── __init__.py
│   │   │   │   ├── report_generator.py
│   │   │   │   ├── report_storage.py
│   │   │   │   ├── claude_api_client.py
│   │   │   │   ├── data_collector.py
│   │   │   │   └── exporters.py         # PDF/Excel
│   │   │   │
│   │   │   └── skills/                  # 스킬 (구현)
│   │   │       ├── __init__.py
│   │   │       ├── kiwoom_api_skill.py
│   │   │       ├── box_entry_skill.py
│   │   │       ├── exit_calc_skill.py
│   │   │       ├── avg_price_skill.py
│   │   │       ├── vi_skill.py
│   │   │       ├── notification_skill.py
│   │   │       ├── reconciliation_skill.py
│   │   │       └── test_template.py
│   │   │
│   │   ├── candle_builder.py            # V7.0 유지
│   │   ├── websocket_manager.py         # V7.0 유지
│   │   ├── market_schedule.py           # V7.0 유지
│   │   ├── market_monitor.py            # V7.0 유지
│   │   ├── indicator_library.py         # V7.0 유지
│   │   ├── constants.py                 # V7.0 유지 (V7.1 별도)
│   │   ├── order_executor.py            # V7.0 + 수정
│   │   ├── risk_manager.py              # V7.0 + 수정 (V7.1 한도)
│   │   ├── position_manager.py          # V7.0 + 수정 (확장)
│   │   ├── position_sync_manager.py     # V7.0 + 수정 (시나리오)
│   │   ├── position_recovery_manager.py # V7.0 유지
│   │   ├── background_task_manager.py   # V7.0 유지
│   │   ├── system_health_monitor.py     # V7.0 유지
│   │   ├── realtime_data_manager.py     # V7.0 유지
│   │   ├── subscription_manager.py      # V7.0 유지
│   │   ├── universe.py                  # V7.0 (검토)
│   │   ├── wave_harvest_exit.py         # V7.0 + 수정 (V7.1 ATR)
│   │   │
│   │   └── trading_engine.py            # V7.0 + 대폭 수정 (V7.1 hooks)
│   │
│   ├── database/                        # V7.0 + 확장
│   │   ├── connection.py
│   │   ├── models.py                    # V7.1 모델 추가
│   │   ├── repository.py                # V7.1 레포 추가
│   │   └── migrations/
│   │       ├── v70/                     # V7.0 마이그레이션
│   │       └── v71/                     # ★ V7.1 마이그레이션 ★
│   │
│   ├── notification/                    # V7.0 + 확장
│   │   ├── telegram.py
│   │   ├── notification_queue.py        # 우선순위 큐로 확장
│   │   ├── templates.py                 # V7.1 템플릿 추가
│   │   ├── severity.py                  # V7.1 신규 (등급)
│   │   ├── circuit_breaker.py           # V7.0 유지
│   │   ├── daily_summary.py             # V7.1 신규
│   │   ├── monthly_review.py            # V7.1 신규
│   │   └── telegram_commands.py         # V7.1 신규 (13개 명령어)
│   │
│   ├── web/                             # ★ V7.1 신규 (웹 대시보드 백엔드) ★
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI 앱
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── tracked_stocks.py
│   │   │   ├── boxes.py
│   │   │   ├── positions.py
│   │   │   ├── reports.py
│   │   │   ├── notifications.py
│   │   │   ├── settings.py
│   │   │   └── system.py
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── jwt_handler.py
│   │   │   ├── totp.py                  # 2FA
│   │   │   ├── login.py
│   │   │   └── middleware.py
│   │   ├── websocket/
│   │   │   ├── __init__.py
│   │   │   └── live_feed.py             # 실시간 push
│   │   └── dependencies.py
│   │
│   └── utils/                           # V7.0 유지
│       ├── config.py
│       ├── logger.py
│       └── exceptions.py
│
├── tests/
│   ├── v71/                             # V7.1 테스트
│   │   ├── conftest.py
│   │   ├── test_box_manager.py
│   │   ├── test_box_entry_detector.py
│   │   ├── test_exit_calculator.py
│   │   ├── test_avg_price.py
│   │   ├── test_vi_monitor.py
│   │   ├── test_reconciler.py
│   │   ├── test_path_manager.py
│   │   ├── test_restart_recovery.py
│   │   ├── test_skills/
│   │   │   ├── test_kiwoom_api.py
│   │   │   ├── test_box_entry.py
│   │   │   └── ...
│   │   ├── test_strategies/
│   │   │   ├── test_pullback.py
│   │   │   └── test_breakout.py
│   │   └── test_integration/
│   │       ├── test_full_buy_flow.py
│   │       └── test_manual_trade_scenarios.py
│   │
│   └── (V7.0 테스트는 V7.0 유지 모듈만 보존)
│
├── docs/
│   ├── v71/                             # ★ 이 디렉토리 ★
│   │   ├── README.md
│   │   ├── 00_CLAUDE_CODE_GENERATION_PROMPT.md
│   │   ├── 02_TRADING_RULES.md
│   │   ├── 03_DATA_MODEL.md
│   │   ├── 04_ARCHITECTURE.md          # 이 문서
│   │   └── ...
│   ├── ARCHITECTURE.md                  # V7.0 보존
│   └── ...
│
├── scripts/
│   ├── deploy/                          # V7.0 유지
│   └── (backtest/ 삭제 예정)
│
├── config/
│   ├── feature_flags.yaml               # ★ V7.1 신규 ★
│   └── ...
│
└── (V6, V7 신호 시스템, 백테스트 캐시 모두 삭제)
```

---

## §2. 모듈 분류 (유지/수정/삭제/신규)

### 2.1 ✅ 유지 (V7.0 인프라 그대로)

```yaml
src/api/ (전체):
  - client.py: 키움 REST API 클라이언트
  - websocket.py: WebSocket 클라이언트
  - auth.py: OAuth 인증
  - endpoints/: 주문, 시세, 계좌
  
  근거:
    검증된 인프라
    Rate Limiter 등 안정적
    V7.1도 같은 키움 API 사용

src/core/ 인프라:
  - candle_builder.py: 틱→봉 변환
  - websocket_manager.py: WS 관리
  - market_schedule.py: 한국 시장 시간
  - market_monitor.py: 시장 상태
  - indicator_library.py: 지표 라이브러리
  - realtime_data_manager.py: 실시간 데이터
  - subscription_manager.py: 구독 관리
  - position_recovery_manager.py: 포지션 복구
  - background_task_manager.py: 백그라운드 태스크
  - system_health_monitor.py: 시스템 헬스
  
  근거:
    인프라성 모듈
    전략 무관
    V7.1도 동일 사용

src/database/ (스키마 확장):
  - connection.py
  - models.py (확장)
  - repository.py (확장)

src/notification/:
  - telegram.py: 텔레그램 봇
  - circuit_breaker.py: API 보호
  - 일부 확장 필요

src/utils/ (전체):
  - config.py
  - logger.py
  - exceptions.py
```

### 2.2 🔄 수정 (V7.1 룰 반영)

```yaml
src/core/position_manager.py:
  변경:
    - V7.1 평단가 관리 룰 (§6)
    - 추가 매수 시 이벤트 리셋
    - source 필드 (SYSTEM_A/B/MANUAL)
    - actual_capital_invested 추적
  
  방식:
    기존 클래스 확장 (V71PositionManager 신규 또는 메서드 추가)
    또는 src/core/v71/position/v71_position_manager.py 신규
    충돌 금지 원칙으로 신규 권장

src/core/position_sync_manager.py:
  변경:
    - 시나리오 A/B/C/D 처리 (§7)
    - MANUAL 포지션 분리
    - 이중 경로 비례 차감
  
  방식:
    핵심 메서드 신규 추가 (reconcile_v71)
    기존 V7.0 메서드는 유지 (deprecated 마킹)

src/core/order_executor.py:
  변경:
    - 지정가 1호가 위 룰
    - 5초 × 3회 → 시장가
    - 부분 체결 처리
    - 대량 주문 호가 소진
  
  방식:
    실행 정책을 V71OrderPolicy로 분리
    기존 코드는 정책 주입식으로 변경

src/core/risk_manager.py:
  변경:
    - 종목당 30% 한도 (실제 포지션 기준)
    - 손절선 단계별 (-5/-2/+4)
  
  방식:
    V71RiskPolicy 신규
    기존 V7.0 정책은 dead code로 유지 후 삭제

src/core/wave_harvest_exit.py:
  변경:
    - V7.1 ATR 배수 (4.0/3.0/2.5/2.0)
    - V7.0 6.0/4.5 제거
    - Trend Hold Filter 폐기
    - BasePrice = 매수 후 최고가 (단순화)
  
  방식:
    내부 로직 V7.1로 전환
    또는 새 모듈로 분리 (src/core/v71/exit/trailing_stop.py)

src/core/trading_engine.py:
  변경:
    - V7.0 신호 시스템 호출 모두 제거
    - V7.1 박스 시스템 hooks 추가
    - 메인 엔진 골격만 유지
  
  방식:
    대폭 정리 (4,904줄 → ~1,500줄 예상)
    V7.1 모듈 호출 코디네이터 역할만

src/core/constants.py:
  변경:
    - V7.0 PurpleConstants 등 제거
    - V7.1 V71Constants 추가
  
  방식:
    src/core/v71/v71_constants.py 분리 권장
    constants.py는 인프라 상수만 유지

src/notification/notification_queue.py:
  변경:
    - 우선순위 큐로 전환
    - CRITICAL/HIGH/MEDIUM/LOW 등급
  
src/notification/templates.py:
  변경:
    - V7.1 알림 템플릿 추가
```

### 2.3 ❌ 삭제 (V7.1 전략과 무관)

```yaml
V6 SNIPER_TRAP 전체:
  - src/core/strategies/v6_sniper_trap.py
  - src/core/signal_detector.py (V6용)
  - src/core/auto_screener.py (V6 5필터)
  - src/core/exit_manager.py (V6 청산)
  - src/core/indicator.py (V6 지표 위임)

V7 신호 시스템:
  - src/core/strategies/v7_purple_reabs.py
  - src/core/signal_detector_purple.py
  - src/core/signal_pool.py
  - src/core/signal_processor.py
  - src/core/v7_signal_coordinator.py
  - src/core/strategy_orchestrator.py
  - src/core/missed_signal_tracker.py
  - src/core/watermark_manager.py
  - src/core/atr_alert_manager.py
  - src/core/condition_search_handler.py
  - src/core/indicator_purple.py

미완성 추상화:
  - src/core/detectors/ (전체)
  - src/core/signals/ (전체)
  - src/core/exit/ (전체, base만 있음)
  - src/strategy/ (전체)
  - src/scheduler/ (전체)
  - src/strategies/ (전체)

백테스트:
  - run_backtest_ui.py
  - scripts/backtest/
  - backtest_modules/ (있다면)
  - 캐시: 3m_data/, results/, *.xlsx, *.csv

OpenClaw 관련:
  - docs/OPENCLAW_GUIDE.md
  - CLAUDE.md의 Part 0 섹션
  - ~/.openclaw/ 외부 디렉토리 (사용자가 직접)

임시 파일:
  - 루트의 *.txt 임시 파일
  - *.recovered, *.new
  - .pytest_cache, .coverage
```

### 2.4 ➕ 신규 (V7.1 전용)

전체 디렉토리 구조는 §1.2 참조. 핵심 신규:

```yaml
src/core/v71/ (전체 신규 패키지):
  - box/: 박스 관리 시스템
  - strategies/: 눌림/돌파 전략
  - exit/: 청산 시스템 (V7.1 룰)
  - position/: 포지션 관리 (V7.1)
  - path_manager.py: 이중 경로 관리
  - vi_monitor.py: VI 상태 머신
  - report/: On-Demand 리포트
  - skills/: 표준 스킬 모음
  - event_logger.py: 이벤트 로깅 표준
  - restart_recovery.py: 재시작 복구
  - audit_scheduler.py: 박스 진입 누락 감사
  - v71_constants.py: V7.1 상수

src/web/ (전체 신규):
  웹 대시보드 백엔드
  FastAPI + JWT + 2FA

config/feature_flags.yaml:
  Feature Flag 정의

scripts/v71/:
  V7.1 운영 스크립트 (이전, 마이그레이션 등)
```

---

## §3. V7.1 신규 패키지 (src/core/v71/)

### 3.1 box/ - 박스 관리

```python
# src/core/v71/box/box_manager.py
"""
박스 CRUD 및 상태 관리.

책임:
  - 박스 생성/수정/삭제
  - 박스 겹침 검증
  - 박스 만료 알림 (30일)
  - 박스 상태 변경 (TRIGGERED, INVALIDATED, CANCELLED)
"""
from typing import Optional, List
from src.core.v71.v71_constants import V71Constants
from src.database.repository import BoxRepository
from src.notification.severity import Severity

class V71BoxManager:
    def __init__(
        self,
        box_repo: BoxRepository,
        notification_queue,
    ):
        self._box_repo = box_repo
        self._notification_queue = notification_queue
    
    async def create_box(
        self,
        tracked_stock_id: UUID,
        upper_price: int,
        lower_price: int,
        position_size_pct: float,
        stop_loss_pct: float,
        strategy_type: StrategyType,
        memo: Optional[str] = None,
    ) -> Box:
        """박스 생성. 겹침 검증 포함."""
        ...
    
    async def validate_no_overlap(
        self,
        tracked_stock_id: UUID,
        upper_price: int,
        lower_price: int,
    ) -> bool:
        """같은 종목 + 같은 경로의 활성 박스와 겹침 검증."""
        ...
    
    async def mark_triggered(self, box_id: UUID, position_id: UUID):
        """매수 실행 시 박스 상태 변경."""
        ...
    
    async def mark_invalidated(
        self,
        tracked_stock_id: UUID,
        reason: str,
    ):
        """시나리오 C 또는 자동 이탈 시 모든 박스 무효화."""
        ...
```

```python
# src/core/v71/box/box_entry_detector.py
"""
박스 진입 조건 감지.

책임:
  - 매 봉 완성 시 진입 조건 체크
  - 눌림/돌파 판정
  - VI 상태 고려
  - 트리거 발생 시 콜백
"""
class V71BoxEntryDetector:
    async def check_entry(
        self,
        box: Box,
        current_candle: Candle,
        previous_candle: Optional[Candle],
        market_context: MarketContext,
    ) -> EntryDecision:
        """진입 조건 평가. 스킬 사용 강제."""
        from src.core.v71.skills.box_entry_skill import evaluate_box_entry
        return evaluate_box_entry(
            box=box,
            current_candle=current_candle,
            previous_candle=previous_candle,
            strategy_type=box.strategy_type,
            context=market_context,
        )
```

### 3.2 strategies/ - 진입 전략

```python
# src/core/v71/strategies/v71_box_pullback.py
"""
눌림 전략.

경로 A (3분봉):
  - 직전봉 양봉 + 박스 내 종가
  - 현재봉 양봉 + 박스 내 종가
  - 봉 완성 직후 매수

경로 B (일봉):
  - 일봉 양봉 + 박스 내 종가
  - 익일 09:01 매수 (갭업 5% 이상 포기)
"""
class V71PullbackStrategy:
    def evaluate(
        self,
        box: Box,
        candle: Candle,
        previous: Candle,
    ) -> bool:
        ...
```

```python
# src/core/v71/strategies/v71_box_breakout.py
"""
돌파 전략.

조건:
  - 종가 > 박스 상단 (돌파)
  - 양봉
  - 봉의 시가 >= 박스 하단 (정상 돌파, 갭업 제외)
"""
class V71BreakoutStrategy:
    def evaluate(self, box: Box, candle: Candle) -> bool:
        ...
```

### 3.3 exit/ - 청산 시스템

```python
# src/core/v71/exit/exit_calculator.py
"""
청산 조건 계산.

책임:
  - 손절선 계산 (단계별 -5/-2/+4)
  - TS 청산선 계산 (BasePrice - ATR × 배수)
  - 유효 청산선 = max(고정, TS)
"""
class V71ExitCalculator:
    def calculate_effective_stop(
        self,
        position: Position,
        current_price: int,
        base_price: int,
        atr_value: float,
    ) -> EffectiveStopResult:
        from src.core.v71.skills.exit_calc_skill import calculate_effective_stop
        return calculate_effective_stop(
            position=position,
            current_price=current_price,
            base_price=base_price,
            atr_value=atr_value,
        )
```

```python
# src/core/v71/exit/exit_executor.py
"""
청산 실행.

책임:
  - 손절 시장가 매도
  - 분할 익절 (지정가 → 시장가)
  - 자동 이탈 처리
"""
class V71ExitExecutor:
    async def execute_stop_loss(self, position: Position) -> ExitResult:
        ...
    
    async def execute_profit_take(
        self,
        position: Position,
        level: ProfitLevel,  # LEVEL_5 or LEVEL_10
    ) -> ExitResult:
        ...
    
    async def execute_ts_exit(self, position: Position) -> ExitResult:
        ...
```

### 3.4 path_manager.py

```python
# src/core/v71/path_manager.py
"""
이중 경로 (A/B) 관리.

책임:
  - 같은 종목의 두 경로 분리
  - 경로별 독립 한도 관리
  - 경로별 시세 모니터링 차등화
"""
class V71PathManager:
    async def get_path_a_stocks(self) -> List[TrackedStock]:
        """경로 A (3분봉 단타) 종목."""
        ...
    
    async def get_path_b_stocks(self) -> List[TrackedStock]:
        """경로 B (일봉 중기) 종목."""
        ...
    
    async def calculate_position_limit_used(
        self,
        stock_code: str,
    ) -> dict:
        """종목당 한도 사용률 (이중 경로 합산)."""
        ...
```

### 3.5 vi_monitor.py

```python
# src/core/v71/vi_monitor.py
"""
VI (변동성 완화 장치) 처리.

책임:
  - WebSocket type=1h 구독
  - VI 발동/해제 감지
  - VI_TRIGGERED 동안 매매 판정 중단
  - VI_RESUMED 즉시 재평가
  - 당일 신규 진입 금지 플래그
"""
class V71VIMonitor:
    async def on_vi_event(self, event: VIEvent):
        """WebSocket에서 VI 이벤트 수신."""
        from src.core.v71.skills.vi_skill import handle_vi_state
        await handle_vi_state(event, self._context)
    
    def is_buy_blocked_today(self, stock_code: str) -> bool:
        """당일 VI 후 신규 진입 금지 여부."""
        ...
```

### 3.6 report/

```python
# src/core/v71/report/report_generator.py
"""
On-Demand 리포트 생성기.

책임:
  - Claude Opus 4.7 호출
  - PART 1 (이야기) + PART 2 (객관 팩트)
  - DB 저장 + PDF/Excel 생성
"""
class V71ReportGenerator:
    async def generate(
        self,
        stock_code: str,
        requested_by: UUID,
    ) -> Report:
        # 1. 데이터 수집 (data_collector)
        data = await self._collector.collect(stock_code)
        
        # 2. Claude API 호출
        narrative = await self._claude.generate_narrative(stock_code, data)
        facts = await self._claude.generate_facts(stock_code, data)
        
        # 3. DB 저장
        report = await self._storage.save(narrative, facts, data)
        
        # 4. PDF/Excel 생성
        report.pdf_path = await self._exporter.to_pdf(report)
        report.excel_path = await self._exporter.to_excel(report)
        
        return report
```

### 3.7 skills/

각 스킬은 표준 함수 형태. 자세한 내용은 `07_SKILLS_SPEC.md` 참조.

```python
# src/core/v71/skills/exit_calc_skill.py
"""
손절/익절 계산 표준 스킬.

하네스가 강제: 매직 넘버 직접 사용 금지.
이 스킬을 통해서만 청산 계산.
"""
def calculate_effective_stop(
    position: Position,
    current_price: int,
    base_price: int,
    atr_value: float,
) -> EffectiveStopResult:
    # 단계별 손절선
    if not position.profit_5_executed:
        fixed_stop = position.weighted_avg_price * 0.95
    elif not position.profit_10_executed:
        fixed_stop = position.weighted_avg_price * 0.98
    else:
        fixed_stop = position.weighted_avg_price * 1.04
    
    # TS 청산선
    ts_stop = None
    if position.ts_activated and position.profit_10_executed:
        # +10% 청산 후만 TS 청산선 유효
        multiplier = _get_atr_multiplier(position, current_price)
        ts_stop = base_price - atr_value * multiplier
        # 단방향 (상승만)
        if position.ts_stop_price and ts_stop < position.ts_stop_price:
            ts_stop = position.ts_stop_price
    
    # 유효 청산선
    if ts_stop is not None:
        effective = max(fixed_stop, ts_stop)
    else:
        effective = fixed_stop
    
    return EffectiveStopResult(
        fixed_stop=fixed_stop,
        ts_stop=ts_stop,
        effective=effective,
        should_exit=current_price <= effective,
    )

def _get_atr_multiplier(position: Position, current_price: int) -> float:
    pnl_pct = (current_price - position.weighted_avg_price) / position.weighted_avg_price
    if pnl_pct < 0.10:
        return 4.0  # +10% 미만에서 사용 안 됨 (TS 비유효)
    elif pnl_pct < 0.15:
        return 4.0
    elif pnl_pct < 0.25:
        return 3.0
    elif pnl_pct < 0.40:
        return 2.5
    else:
        return 2.0
```

---

## §4. 데이터 흐름

### 4.1 박스 진입 → 매수 흐름

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 키움 WebSocket 시세 수신                                  │
│    ↓                                                        │
│ 2. CandleBuilder: 틱 → 3분봉 또는 일봉                       │
│    ↓                                                        │
│ 3. V71BoxEntryDetector: 봉 완성 시 박스 진입 조건 체크        │
│    │                                                        │
│    ├─ V71PullbackStrategy.evaluate() (눌림 룰)              │
│    │  또는                                                  │
│    └─ V71BreakoutStrategy.evaluate() (돌파 룰)              │
│    ↓ (조건 충족)                                            │
│ 4. V71PathManager.check_position_limit() (한도 검사)        │
│    ↓ (한도 OK)                                              │
│ 5. V71VIMonitor.is_buy_blocked_today() (VI 확인)            │
│    ↓ (차단 아님)                                            │
│ 6. KiwoomAPISkill.send_buy_order()                          │
│    │  (지정가 1호가 위 → 5초 × 3회 → 시장가)                 │
│    ↓ (체결)                                                 │
│ 7. V71PositionManager.create_or_update()                    │
│    │  - source: SYSTEM_A or SYSTEM_B                        │
│    │  - 평단가, 수량, 손절선 계산                            │
│    ↓                                                        │
│ 8. V71BoxManager.mark_triggered() (박스 상태 변경)          │
│    ↓                                                        │
│ 9. EventLogger.log(BUY_EXECUTED) (DB 기록)                  │
│    ↓                                                        │
│ 10. NotificationSkill.send(HIGH, BUY_EXECUTED)              │
│     (텔레그램 + 웹 동시 발송)                                │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 청산 흐름

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 시세 수신 (틱)                                           │
│    ↓                                                        │
│ 2. V71ExitCalculator.calculate_effective_stop()             │
│    │  - 단계별 손절선 (스킬 사용)                            │
│    │  - TS 청산선 (해당 시)                                 │
│    │  - 유효 청산선 = max(고정, TS)                          │
│    ↓                                                        │
│ 3. 분기:                                                    │
│    ├─ 손절 조건 (current <= effective_stop)                 │
│    │  └─ V71ExitExecutor.execute_stop_loss() (시장가)       │
│    │                                                        │
│    ├─ 익절 +5% 조건                                         │
│    │  └─ V71ExitExecutor.execute_profit_take(LEVEL_5)       │
│    │     (30% 청산, 지정가 → 시장가)                         │
│    │                                                        │
│    ├─ 익절 +10% 조건                                        │
│    │  └─ V71ExitExecutor.execute_profit_take(LEVEL_10)      │
│    │                                                        │
│    └─ TS 청산 조건                                          │
│       └─ V71ExitExecutor.execute_ts_exit()                  │
│    ↓                                                        │
│ 4. V71PositionManager.update_after_sell()                   │
│    │  - 평단가 유지                                         │
│    │  - 수량 감소 또는 CLOSED                               │
│    │  - 이벤트 플래그 갱신 (profit_5/10 _executed)          │
│    ↓                                                        │
│ 5. EventLogger.log(이벤트 타입)                              │
│    ↓                                                        │
│ 6. NotificationSkill.send()                                 │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 수동 거래 감지 흐름

```
┌─────────────────────────────────────────────────────────────┐
│ 주기적 (5분) 또는 이벤트 발생                                 │
│    ↓                                                        │
│ V71Reconciler.reconcile()                                   │
│    ↓                                                        │
│ 1. 키움 API: 잔고 조회                                       │
│ 2. DB: positions 조회                                       │
│ 3. 종목별 비교                                              │
│    ↓                                                        │
│ 시나리오 분기:                                              │
│ ├─ Case A (일치): 진행                                      │
│ ├─ Case B (시나리오 A): MANUAL_PYRAMID_BUY                  │
│ ├─ Case C (시나리오 B): MANUAL_PARTIAL_EXIT                 │
│ ├─ Case D (시나리오 C): 추적 종료 + 박스 무효화              │
│ └─ Case E (시나리오 D): MANUAL 신규                          │
│    ↓                                                        │
│ ReconciliationSkill.handle_case() (스킬 사용)               │
│    ↓                                                        │
│ EventLogger + NotificationSkill                             │
└─────────────────────────────────────────────────────────────┘
```

---

## §5. 의존성 그래프

### 5.1 단방향 의존 원칙

```
src/web/ (Presentation)
    ↓
src/core/v71/ (V7.1 신규)
    ↓
src/core/ (V7.0 인프라)
    ↓
src/api/, src/database/, src/notification/, src/utils/ (인프라)
    ↓
External (키움 API, Supabase, Telegram)

★ 절대 금지: V7.0 인프라가 V7.1을 import
★ 절대 금지: 인프라가 코어를 import
```

### 5.2 V7.1 내부 의존

```
v71/skills/  (가장 하위, 의존성 없음)
    ↑
v71/box/, v71/strategies/, v71/exit/, v71/position/
    ↑
v71/path_manager.py, v71/vi_monitor.py
    ↑
v71/restart_recovery.py, v71/audit_scheduler.py
    ↑
v71/report/  (별도 분기, 거래 룰과 독립)

핵심 코디네이터 (top level):
trading_engine.py (수정) → v71 모듈들 호출
```

### 5.3 하네스 2 (Dependency Cycle Detector)가 강제

```
순환 의존 발견 시 빌드 차단:
  A → B → A (직접)
  A → B → C → A (간접)

해결:
  의존성 역전 (인터페이스/콜백)
  공통 의존성 분리
```

---

## §6. 동시성 모델

### 6.1 asyncio 기반

```yaml
모든 I/O 비동기:
  - 키움 API 호출
  - WebSocket 수신
  - DB 쿼리
  - 텔레그램 발송

이유:
  - 시세 수신과 매매 동시 처리
  - I/O 대기 시간 활용
  - NFR1 (1초 이내) 보장
```

### 6.2 핵심 태스크

```python
# src/main.py
async def main():
    # 인프라 초기화
    db = await init_db()
    api = await init_kiwoom_api()
    ws = await init_websocket()
    
    # V7.1 모듈 초기화
    box_manager = V71BoxManager(...)
    entry_detector = V71BoxEntryDetector(...)
    exit_calculator = V71ExitCalculator(...)
    vi_monitor = V71VIMonitor(...)
    reconciler = V71Reconciler(...)
    
    # 백그라운드 태스크 (병렬)
    tasks = [
        asyncio.create_task(websocket_listener(ws)),
        asyncio.create_task(candle_builder_loop()),
        asyncio.create_task(entry_detection_loop()),
        asyncio.create_task(exit_monitoring_loop()),
        asyncio.create_task(vi_monitor_loop()),
        asyncio.create_task(reconciliation_loop()),
        asyncio.create_task(notification_dispatcher()),
        asyncio.create_task(daily_summary_scheduler()),
        asyncio.create_task(monthly_review_scheduler()),
        asyncio.create_task(audit_scheduler()),
    ]
    
    await asyncio.gather(*tasks)
```

### 6.3 동시성 보호

```yaml
DB 쿼리:
  PostgreSQL의 트랜잭션
  FOR UPDATE SKIP LOCKED (알림 큐 등)

상태 변경:
  asyncio.Lock (필요한 곳만)
  주로 reconciliation 등 임계 영역

키움 API:
  Rate Limiter (asyncio.Semaphore)
  초당 4.5회 제한
```

---

## §7. 외부 시스템 통합

### 7.1 키움 REST API

```yaml
용도:
  - 시세 조회 (REST 폴링 시)
  - 주문 발송
  - 잔고 조회
  - 종목 정보

인증:
  OAuth 2.0 (token 자동 갱신)

Rate Limit:
  실전: 초당 4.5회
  모의: 초당 0.33회

구현:
  src/api/client.py
  Rate Limiter + 재시도 로직
```

### 7.2 키움 WebSocket

```yaml
용도:
  - 실시간 시세 (REGSUB)
  - VI 이벤트 (type=1h)
  - 체결 알림

재연결:
  Phase 1: 5회 지수 백오프
  Phase 2: 5분 무한 재시도

구현:
  src/api/websocket.py
  src/core/websocket_manager.py
```

### 7.3 Supabase (PostgreSQL)

```yaml
용도:
  - 모든 영속화 데이터
  - 사용자, 보안
  - 거래 이력
  - 리포트 저장

연결:
  asyncpg 드라이버
  Connection Pool

마이그레이션:
  src/database/migrations/v71/
  UP/DOWN 양방향
```

### 7.4 Telegram Bot API

```yaml
용도:
  - 알림 발송
  - 명령어 응답 (13개)

제한:
  - 초당 1메시지
  - 분당 20메시지

구현:
  src/notification/telegram.py
  Circuit Breaker 통합
```

### 7.5 Claude API (Opus 4.7)

```yaml
용도:
  - On-Demand 종목 리포트

호출 시점:
  사용자 요청 시만

비용 관리:
  요청 수 추적
  월간 한도 알림 (선택)

구현:
  src/core/v71/report/claude_api_client.py
```

---

## §8. 배포 아키텍처

### 8.1 AWS Lightsail 환경

```
┌─────────────────────────────────────────────────────────┐
│ AWS Lightsail Instance (Ubuntu 22.04)                    │
│                                                         │
│  ┌────────────────────────────────────────────────┐    │
│  │ Cloudflare (DNS + DDoS + SSL)                  │    │
│  └────────────────┬───────────────────────────────┘    │
│                   ↓                                     │
│  ┌────────────────────────────────────────────────┐    │
│  │ Nginx (Reverse Proxy + SSL Termination)        │    │
│  │ - Let's Encrypt 인증서                          │    │
│  │ - HTTPS 강제                                    │    │
│  └─────┬───────────────────────────────────┬──────┘    │
│        ↓                                   ↓           │
│  ┌──────────────────────┐  ┌─────────────────────┐    │
│  │ FastAPI (Web Backend)│  │ React (Static Files)│    │
│  │ - REST API           │  │ - 빌드된 SPA         │    │
│  │ - WebSocket          │  │                     │    │
│  └──────────┬───────────┘  └─────────────────────┘    │
│             ↓                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │ V7.1 Trading Engine (Background Process)       │    │
│  │ - asyncio 기반                                  │    │
│  │ - 키움 WebSocket + REST                         │    │
│  │ - Telegram Bot                                 │    │
│  │ - systemd 서비스로 자동 재시작                   │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
                   ↓                ↓
    ┌──────────────────┐  ┌──────────────────┐
    │ Supabase Cloud   │  │ External APIs    │
    │ (PostgreSQL)     │  │ - 키움증권        │
    │                  │  │ - Telegram       │
    │                  │  │ - Anthropic      │
    └──────────────────┘  └──────────────────┘
```

### 8.2 systemd 서비스

```ini
# /etc/systemd/system/kstock-v71.service
[Unit]
Description=K_stock_trading V7.1
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/K_stock_trading
ExecStart=/usr/bin/python3.11 -m src.main
Restart=always
RestartSec=10
Environment="PATH=/home/ubuntu/.local/bin:/usr/bin"
EnvironmentFile=/home/ubuntu/K_stock_trading/.env

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/kstock-v71-web.service
[Unit]
Description=K_stock_trading V7.1 Web Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/K_stock_trading
ExecStart=/usr/bin/uvicorn src.web.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 8.3 모니터링

```yaml
시스템 레벨:
  - systemd journal (로그)
  - htop (리소스)
  - df -h (디스크)

애플리케이션 레벨:
  - 텔레그램 알림 (시스템 이벤트)
  - 웹 대시보드 헬스 체크 페이지
  - DB 쿼리 system_events 테이블

장애 대응:
  - 헌법 4: 자동 정지 없음
  - systemd 자동 재시작 (Restart=always)
  - 빈도 모니터링 (system_restarts)
```

### 8.4 배포 절차

```yaml
초기 배포:
  1. Lightsail 인스턴스 생성
  2. Ubuntu 22.04 + Python 3.11 + PostgreSQL 클라이언트
  3. 코드 배포 (git clone)
  4. .env 설정 (시크릿)
  5. Supabase 마이그레이션
  6. systemd 서비스 등록
  7. Nginx + Cloudflare 설정
  8. Let's Encrypt 인증서

업데이트 배포:
  1. Feature Flag로 신규 기능 OFF
  2. git pull
  3. DB 마이그레이션 (UP)
  4. systemd restart
  5. Feature Flag로 신규 기능 점진 활성화
  6. 모니터링
  
  롤백 시:
    1. Feature Flag OFF
    2. git revert
    3. DB 마이그레이션 (DOWN)
    4. systemd restart
```

---

## 부록 A: 모듈 간 인터페이스 예시

### A.1 박스 진입 → 매수 인터페이스

```python
# src/core/v71/box/box_entry_detector.py
class V71BoxEntryDetector:
    def __init__(
        self,
        path_manager: V71PathManager,
        vi_monitor: V71VIMonitor,
        on_entry_triggered: Callable[[Box, EntryDecision], Awaitable],
    ):
        self._path_manager = path_manager
        self._vi_monitor = vi_monitor
        self._on_entry = on_entry_triggered  # 콜백

# src/core/v71/strategies/buy_executor.py (메인 코디네이터)
class V71BuyExecutor:
    async def on_entry_triggered(self, box: Box, decision: EntryDecision):
        # 1. 한도 검사
        # 2. VI 검사
        # 3. 매수 실행 (스킬)
        # 4. 포지션 생성 (스킬)
        # 5. 박스 상태 변경
        # 6. 이벤트 로그
        # 7. 알림
        ...
```

### A.2 의존성 주입 예시

```python
# src/main.py
async def setup_v71_components(infrastructure):
    """의존성 주입으로 V7.1 컴포넌트 조립."""
    
    # Skills (의존성 없음)
    # → 직접 함수 import로 사용
    
    # Repositories
    box_repo = BoxRepository(infrastructure.db)
    position_repo = PositionRepository(infrastructure.db)
    
    # Core 컴포넌트
    box_manager = V71BoxManager(
        box_repo=box_repo,
        notification_queue=infrastructure.notification_queue,
    )
    
    path_manager = V71PathManager(
        position_repo=position_repo,
    )
    
    vi_monitor = V71VIMonitor(
        websocket=infrastructure.websocket,
    )
    
    # Strategies
    pullback_strategy = V71PullbackStrategy()
    breakout_strategy = V71BreakoutStrategy()
    
    # Detector (의존성 다수)
    entry_detector = V71BoxEntryDetector(
        path_manager=path_manager,
        vi_monitor=vi_monitor,
        pullback_strategy=pullback_strategy,
        breakout_strategy=breakout_strategy,
    )
    
    # Exit
    exit_calc = V71ExitCalculator()
    exit_executor = V71ExitExecutor(
        order_executor=infrastructure.order_executor,
        position_manager=position_manager,
    )
    
    # 코디네이터
    buy_executor = V71BuyExecutor(
        box_manager=box_manager,
        path_manager=path_manager,
        vi_monitor=vi_monitor,
        order_skill=kiwoom_api_skill,
        position_manager=position_manager,
        notification_skill=notification_skill,
    )
    
    # 콜백 연결
    entry_detector.set_callback(buy_executor.on_entry_triggered)
    
    return V71Components(
        box_manager=box_manager,
        entry_detector=entry_detector,
        exit_calc=exit_calc,
        exit_executor=exit_executor,
        vi_monitor=vi_monitor,
        # ...
    )
```

---

## 부록 B: 미정 사항

```yaml
B.1 trading_engine.py 처리 방식:
  옵션 1: 대폭 수정 (V7.1 hooks 추가)
  옵션 2: 새 파일 (v71_trading_engine.py)
  
  → 구현 시 결정
  → 충돌 금지 원칙 고려

B.2 V7.0 위임 모듈 정리 시점:
  V7.1 검증 완료 후 V7.0 코드 제거
  Feature Flag로 안전한 전환

B.3 웹 프론트엔드 빌드 위치:
  옵션 1: 별도 리포지토리
  옵션 2: 모노리포 (frontend/ 디렉토리)
  
  → Claude Design 작업 후 결정

B.4 로그 보관 정책:
  운영 데이터 분석 후 결정
  예: INFO 30일, WARNING 90일, ERROR 영구
```

---

*이 문서는 V7.1 아키텍처의 단일 진실 원천입니다.*  
*신규 모듈 추가 시 이 문서 갱신 필수.*

*최종 업데이트: 2026-04-25*
