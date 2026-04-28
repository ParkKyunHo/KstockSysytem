# Claude Code 작업 지시서: V7.1 시스템 구현

> 이 문서는 Claude Code가 V7.1 시스템을 구현하기 위한 **마스터 지시서**입니다.
> 
> 모든 V7.1 관련 작업은 이 문서를 시작점으로 합니다.

---

## 0. 사용 방법

### 0.1 Claude Code에 전달할 프롬프트

Claude Code 세션을 시작할 때 다음 프롬프트를 사용하세요:

```
당신은 K_stock_trading V7.1 시스템의 구현을 담당합니다.

작업 시작 전 다음 문서들을 순서대로 읽으세요:

1. C:\K_stock_trading\docs\v71\README.md
2. C:\K_stock_trading\docs\v71\00_CLAUDE_CODE_GENERATION_PROMPT.md (이 문서)
3. C:\K_stock_trading\docs\v71\01_PRD_MAIN.md
4. 작업 영역에 해당하는 추가 문서

읽은 후 다음 원칙을 절대 위반하지 마세요:

V7.1 헌법 5원칙:
1. 사용자 판단 불가침
2. NFR1 최우선 (박스 진입 절대 놓치지 않음)
3. 충돌 금지 (기존 V7.0 코드와 호환 + 안전한 삭제)
4. 시스템 계속 운영
5. 단순함 우선

준비되면 작업 명령을 받겠다고 응답하세요.
이후 사용자가 구체적 작업을 지시할 것입니다.
```

### 0.2 작업 단위

각 작업은 다음 단위 중 하나입니다:

```
작업 유형:
  TASK_GENERATE: 새 파일 생성 (에이전트, 스킬, 하네스, 코드)
  TASK_MODIFY: 기존 파일 수정 (V7.0 인프라 일부)
  TASK_DELETE: 파일 삭제 (V6, V7 신호 시스템)
  TASK_TEST: 테스트 작성/실행
  TASK_VERIFY: 룰 준수 검증
  TASK_MIGRATE: 데이터 마이그레이션
```

---

## 1. V7.1 헌법 (절대 원칙)

### 1.1 다섯 원칙

```
원칙 1: 사용자 판단 불가침
  - 사용자가 정의한 박스 구간 시스템이 임의 수정 금지
  - 박스의 가격, 비중, 손절폭 자동 변경 금지
  - 시스템은 B 수준 경고만 가능 (명백한 입력 오류만)
  - 예: 박스 상단 < 하단 → 경고
  - 금지: "이 박스는 너무 위험해 보임" 같은 판단 경고

원칙 2: NFR1 최우선 (박스 진입 절대 놓치지 않음)
  - 시세 모니터링 지연 < 1초 (박스 근접 시)
  - 봉 완성 후 매수 주문까지 < 5초
  - 안정성·부하·비용은 2순위
  - 트레이드오프 결정 시 항상 NFR1 우선

원칙 3: 충돌 금지
  - V7.1 신규 모듈은 V7.0 유지 모듈과 충돌 없어야
  - 명명 규칙: V71 접두사 또는 v71/ 패키지
  - 데이터 모델: 기존 테이블 확장만, 파괴적 변경 금지
  - 삭제 작업: 의존성 추적 후 안전한 순서로
  - Feature Flag: V7.0 운영 중 V7.1 점진 활성화

원칙 4: 시스템 계속 운영
  - 긴급정지 기능 없음
  - WebSocket 끊김 → 재연결 우선
  - 시스템 재시작 빈도 높아도 자동 정지 안 함
  - 어떤 상황에서도 시스템 가동 유지

원칙 5: 단순함 우선
  - 복잡한 예외 처리보다 단순 룰
  - 엣지 케이스 감수 > 복잡 룰
  - "있으면 좋은 것"과 "필수"를 섞지 말 것
  - 매 결정 시 "정말 필요한가?" 자문
```

### 1.2 위반 시 차단

각 원칙은 하네스로 자동 검증됩니다:

```
원칙 1 위반: Trading Logic Verifier 에이전트가 차단
원칙 2 위반: 성능 벤치마크 실패 시 차단
원칙 3 위반: Naming Collision Detector 등 하네스가 차단
원칙 4 위반: 정지 코드 발견 시 코드 리뷰 거부
원칙 5 위반: 코드 복잡도 임계치 초과 시 경고
```

---

## 2. 작업 우선순위

### 2.1 Phase 1: 인프라 정리 (먼저 해야 함)

```
이 작업이 끝나야 V7.1 신규 모듈 안전하게 추가 가능

P1.1 OpenClaw 정리
  - docs/OPENCLAW_GUIDE.md 삭제
  - CLAUDE.md의 Part 0 OpenClaw 섹션 삭제
  - ~/.openclaw/ 외부 디렉토리 정리 (사용자가 직접)
  - Scheduled Task "OpenClaw Gateway" 비활성

P1.2 백테스트 시스템 삭제
  - run_backtest_ui.py 삭제
  - scripts/backtest/ 삭제
  - backtest_modules/ 삭제 (있다면)
  - 캐시 파일 삭제:
    * 3m_data/
    * results/
    * 3mintest.csv, testday.csv
    * past1000*.csv
    * ema_split_buy_*.xlsx
    * full_3min_backtest_result.xlsx
    * improved_entry_backtest_result*.xlsx

P1.3 임시 파일 정리
  - 루트 디렉토리의 *.txt 임시 파일 모두 삭제
    (CK_stock_tradingtemp_*.txt, temp_log*.txt 등)
  - *.recovered, *.new 파일 삭제
  - .pytest_cache, .coverage 정리

P1.4 V6 SNIPER_TRAP 완전 삭제
  - src/core/strategies/v6_sniper_trap.py
  - src/core/signal_detector.py (V6용)
  - src/core/auto_screener.py (V6 5필터)
  - src/core/exit_manager.py (V6 청산)
  - src/core/indicator.py (V6 지표 위임)
  
  주의: 의존성 추적 필수
    - 다른 모듈이 V6 모듈을 import하는지 확인
    - import 모두 제거 후 삭제
    - 테스트 실행하여 깨진 곳 없는지 확인

P1.5 V7 신호 시스템 삭제
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

P1.6 미완성 추상화 정리
  - src/core/detectors/ (전체 삭제)
  - src/core/signals/ (전체 삭제)
  - src/core/exit/ (전체 삭제)
  - src/strategy/ (전체 삭제)
  - src/scheduler/ (전체 삭제)
  - src/strategies/ (전체 삭제)

P1.7 wave_harvest_exit.py 정리
  - 파일은 유지 (V7.1에서 ATR 배수만 조정)
  - V7.0 Trend Hold Filter 제거
  - V7.0 ATR 배수 (6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0) 제거
  - V7.1 ATR 배수 (4.0 → 3.0 → 2.5 → 2.0)로 교체

P1.8 trading_engine.py 정리 (historical — Phase A에서 폐기로 대체됨)
  - 사용자 결정 (2026-04-28): V7.0 Purple-ReAbs 완전 폐기.
  - Phase A Step D에서 src/core/trading_engine.py + 관련 V7.0 모듈
    (candle_builder / market_schedule / realtime_data_manager / api/* / etc.)
    전체를 일괄 git rm. 점진적 정리 X.
  - V7.1 진입은 src.web.v71.main:app + src.web.v71.trading_bridge wiring.

검증 (Phase A 완료 시점):
    python -c "import src.core.v71"                            # OK
    python -c "import src.web.v71.main"                        # OK
    python -c "from src.notification.telegram import TelegramBot"  # 보존
    pytest tests/v71/                                          # 1279/1279 PASS
    python scripts/harness/run_all.py                          # 6/6 PASS
```

### 2.2 Phase 2: V7.1 신규 모듈 골격 (인프라 정리 후)

```
P2.1 디렉토리 구조 생성
  src/core/v71/
    ├── __init__.py
    ├── box/
    │   ├── __init__.py
    │   ├── box_manager.py
    │   ├── box_entry_detector.py
    │   └── box_state_machine.py
    ├── strategies/
    │   ├── __init__.py
    │   ├── v71_box_pullback.py
    │   └── v71_box_breakout.py
    ├── path_manager.py
    ├── vi_monitor.py
    ├── report/
    │   ├── __init__.py
    │   ├── report_generator.py
    │   ├── report_storage.py
    │   └── claude_api_client.py
    ├── event_logger.py
    └── restart_recovery.py
  
  src/web/
    ├── __init__.py
    ├── api/
    ├── auth/
    └── dashboard/

P2.2 데이터 모델 생성
  - 03_DATA_MODEL.md 참조
  - 새 테이블 추가 (tracked_stocks 확장, support_boxes 확장 등)
  - Migration 파일 작성 (UP/DOWN 양방향)

P2.3 핵심 클래스 골격
  - 각 신규 모듈에 클래스 시그니처만 작성
  - 메서드 시그니처 + 타입 힌트
  - 실제 구현은 P3 단계

검증:
  - 모든 새 파일이 v71/ 패키지 안에 있음
  - 명명 충돌 없음 (V71 접두사 또는 격리 패키지)
  - import 경로 정상
```

### 2.3 Phase 3: V7.1 거래 룰 구현 (가장 중요)

```
P3.1 박스 시스템 구현
  참조: 02_TRADING_RULES.md §3 (박스 설정)
  파일: src/core/v71/box/box_manager.py
       src/core/v71/box/box_entry_detector.py
       src/core/v71/box/box_state_machine.py

P3.2 매수 실행 구현
  참조: 02_TRADING_RULES.md §4 (매수 실행)
  파일: src/core/v71/strategies/v71_box_pullback.py
       src/core/v71/strategies/v71_box_breakout.py

P3.3 매수 후 관리 구현
  참조: 02_TRADING_RULES.md §5 (매수 후 관리)
  파일: src/core/v71/exit_manager.py (신규)
       src/core/wave_harvest_exit.py (수정, V7.1 ATR 배수)

P3.4 평단가 관리 구현
  참조: 02_TRADING_RULES.md §6 (평단가 관리)
  파일: src/core/v71/position_manager.py (V7.0 position_manager.py 기반 확장)

P3.5 수동 거래 처리 구현
  참조: 02_TRADING_RULES.md §7 (수동 거래)
  파일: src/core/v71/manual_trade_handler.py
       src/core/position_sync_manager.py (수정, 시나리오 A/B/C/D)

P3.6 VI 처리 구현
  참조: 02_TRADING_RULES.md §10 (VI 처리)
  파일: src/core/v71/vi_monitor.py

P3.7 시스템 재시작 복구 구현
  참조: 02_TRADING_RULES.md §13 (재시작 복구)
  파일: src/core/v71/restart_recovery.py

검증:
  - 각 룰의 모든 엣지 케이스 테스트
  - Trading Logic Verifier 에이전트 통과
  - 단위 테스트 커버리지 90%+
```

### 2.4 Phase 4: 알림 시스템 (인프라 활용)

```
P4.1 알림 등급 시스템
  참조: 02_TRADING_RULES.md §9 (알림)
  파일: src/notification/severity.py (신규)
       src/notification/notification_queue.py (수정, 우선순위 큐)

P4.2 텔레그램 명령어
  파일: src/notification/telegram_commands.py (신규)
  /status, /positions, /tracking 등 13개 명령어

P4.3 일일 마감 알림
  파일: src/notification/daily_summary.py (신규)
  매일 15:30 자동 발송

P4.4 월 1회 리뷰 알림
  파일: src/notification/monthly_review.py (신규)
  매월 1일 자동 발송
```

### 2.5 Phase 5: 웹 대시보드

```
P5.1 백엔드 API 구현
  참조: 09_API_SPEC.md (작성 예정)
  파일: src/web/api/

P5.2 인증 시스템
  참조: 12_SECURITY.md (작성 예정)
  파일: src/web/auth/
  - JWT, 2FA, 세션 관리

P5.3 프론트엔드 (Claude Design 결과 통합)
  - Claude Design 작업 완료 후 진행
  - React + Tailwind + shadcn/ui
```

### 2.6 Phase 6: 리포트 시스템

```
P6.1 On-Demand 리포트 생성기
  참조: 11_REPORTING.md (작성 예정)
  파일: src/core/v71/report/report_generator.py
       src/core/v71/report/claude_api_client.py

P6.2 데이터 수집 파이프라인
  파일: src/core/v71/report/data_collector.py
  - 키움 API: 시세, 재무
  - DART API: 공시
  - 네이버 뉴스 API

P6.3 PDF/Excel 다운로드
  파일: src/core/v71/report/exporters.py
```

### 2.7 Phase 7: 통합 테스트 + 배포

```
P7.1 통합 테스트
  - 전체 워크플로우 시나리오
  - 페이퍼 트레이드 1~2주
  - 실시간 데이터로 검증

P7.2 배포 준비
  - AWS Lightsail 환경 구성
  - HTTPS, Cloudflare 설정
  - 모니터링 설정

P7.3 점진적 활성화
  - Feature Flag로 단계적 활성화
  - 1~2일씩 관찰
  - 문제 발생 시 즉시 비활성화
```

---

## 3. 에이전트 활용 가이드

### 3.1 V71 Architect Agent 호출 시점

```
호출:
  - 새 모듈 추가 시
  - 모듈 간 의존성 변경 시
  - 패키지 구조 결정 시

질문 형태:
  "다음 모듈을 v71/box/box_manager.py에 추가하려 합니다.
   V7.1 헌법 부합 여부와 의존성 검토 부탁합니다.
   [코드 첨부]"

응답 형태:
  PASS / FAIL
  - 헌법 부합 여부
  - 충돌 가능성
  - 개선 제안
```

### 3.2 Trading Logic Verifier Agent 호출 시점

```
호출:
  - 박스 진입 로직 작성 시
  - 손절/익절 로직 작성 시
  - 평단가 계산 로직 작성 시

질문 형태:
  "다음 로직이 02_TRADING_RULES.md §5의 룰을 정확히 구현하나요?
   [코드 첨부]"

응답 형태:
  - 룰 위반 사항
  - 누락된 엣지 케이스
  - 단위 테스트 케이스 제안
```

### 3.3 Migration Strategy Agent 호출 시점

```
호출:
  - V7.0 모듈 삭제 직전
  - 데이터 모델 변경 시
  - V7.1 모듈 활성화 시

질문 형태:
  "V7.0의 src/core/signal_pool.py 삭제 안전한가요?"

응답 형태:
  - 의존하는 다른 모듈 리스트
  - 안전한 삭제 순서
  - 롤백 계획
```

### 3.4 Security Reviewer Agent 호출 시점

```
호출:
  - 인증/인가 코드 작성 시
  - 외부 API 호출 시
  - DB 쿼리 작성 시
  - 사용자 입력 처리 시

질문 형태:
  "다음 인증 코드의 보안 취약점을 검토해주세요.
   [코드 첨부]"

응답 형태:
  - 취약점 리스트
  - 수정 방안
  - 추가 보안 권고
```

### 3.5 Test Strategy Agent 호출 시점

```
호출:
  - 새 함수/클래스 작성 후
  - 버그 수정 후
  - 마이그레이션 단계마다

질문 형태:
  "다음 클래스에 필요한 테스트 케이스를 제안해주세요.
   [코드 첨부]"

응답 형태:
  - 단위 테스트 목록
  - 엣지 케이스 테스트
  - 통합 테스트 (필요 시)
```

---

## 4. 스킬 활용 가이드

### 4.1 모든 작업에서 강제되는 스킬

```
키움 API 호출:
  raw httpx.post() 사용 금지
  반드시 src.core.api_skill.kiwoom_api_call() 사용
  
박스 진입 판정:
  직접 조건문 작성 금지
  반드시 src.core.v71.box.evaluate_box_entry() 사용

손절/익절 계산:
  매직 넘버 (0.05, -0.02 등) 직접 사용 금지
  반드시 src.core.v71.exit_skill.calculate_effective_stop() 사용

평단가 관리:
  직접 position.avg_price = ... 금지
  반드시 src.core.v71.position_skill.update_position_after_buy() 사용

알림 발송:
  raw telegram.send_message() 금지
  반드시 src.core.notification_skill.send_notification() 사용

VI 상태 처리:
  VI 무시한 거래 로직 금지
  반드시 src.core.v71.vi_skill.handle_vi_state() 사용

포지션 정합성:
  직접 잔고 비교 금지
  반드시 src.core.v71.reconciliation_skill.reconcile_positions() 사용

테스트 작성:
  ad-hoc 테스트 금지
  반드시 tests/v71/test_template.py 패턴 따름
```

### 4.2 스킬 정의 위치

각 스킬의 상세 명세는 `07_SKILLS_SPEC.md` 참조.

---

## 5. 하네스 활용 가이드

### 5.1 자동 검증 도구

```
하네스 1: Naming Collision Detector
  실행: pre-commit hook
  차단: V7.0 클래스명과 충돌 시

하네스 2: Dependency Cycle Detector
  실행: pre-commit hook
  차단: 순환 의존성 발견 시

하네스 3: Trading Rule Enforcer
  실행: pylint plugin
  차단: 매직 넘버, 직접 손절 우회 등

하네스 4: Schema Migration Validator
  실행: 마이그레이션 시
  차단: DOWN 없는 마이그레이션, 데이터 손실 위험

하네스 5: Feature Flag Enforcer
  실행: 코드 분석
  차단: Feature Flag 없는 V7.1 기능 활성화

하네스 6: Dead Code Detector
  실행: 정적 분석
  차단: 삭제 대상 모듈 import

하네스 7: Test Coverage Enforcer
  실행: pytest --cov
  차단: 거래 로직 90% 미만, 인프라 80% 미만
```

### 5.2 하네스 통과 의무

```
모든 commit:
  - 하네스 1, 2, 3, 6 통과 필수
  - 통과 못 하면 commit 차단

마이그레이션 PR:
  - 하네스 4 추가 통과 필수

V7.1 기능 활성화 PR:
  - 하네스 5 추가 통과 필수

릴리스 전:
  - 하네스 7 통과 필수
```

### 5.3 하네스 정의 위치

각 하네스의 구현 명세는 `08_HARNESS_SPEC.md` 참조.

---

## 6. 작업 흐름

### 6.1 일반 작업 흐름

```
1. 작업 시작 시
   - 이 문서 읽기
   - 해당 작업의 PRD 영역 읽기 (예: 거래 룰 작업이면 02_TRADING_RULES.md)
   - 관련 에이전트 호출 (예: Trading Logic Verifier)

2. 작업 중
   - 적용 가능한 스킬 사용 (직접 구현 금지)
   - 하네스 자동 검증 통과
   - 헌법 5원칙 위반 없음 확인

3. 작업 완료 시
   - 단위 테스트 작성 (Test Strategy Agent 도움)
   - pytest 통과
   - 하네스 모두 통과
   - 결과 보고

4. 의문 발생 시
   - PRD에서 답을 찾을 수 있는지 확인
   - 명시 안 된 결정 필요 시:
     ◦ 사용자에게 물어봄
     ◦ 절대 임의 결정 금지
```

### 6.2 충돌 발견 시

```
유형 1: 명명 충돌
  → 하네스 1이 차단
  → V71 접두사 추가 또는 v71/ 패키지로 이동

유형 2: 의존성 충돌
  → 하네스 2가 차단
  → Architect Agent에 의존성 재설계 요청

유형 3: 룰 충돌
  → Trading Logic Verifier가 차단
  → PRD 재확인 후 정확히 구현

유형 4: 데이터 모델 충돌
  → 하네스 4가 차단
  → Migration Strategy Agent에 안전한 변경 절차 요청

유형 5: PRD 자체 모순 발견
  → 즉시 사용자에게 보고
  → 임의 해석 금지
  → PRD 수정 후 작업 재개
```

### 6.3 PRD 수정이 필요한 경우

```
다음 경우 PRD 수정 요청:
  1. 명백한 모순 발견
  2. 누락된 엣지 케이스 발견
  3. 기술적으로 구현 불가능한 룰
  4. 하네스/스킬 정의 보완 필요

수정 절차:
  1. 사용자에게 보고 (구체적 사유)
  2. 사용자 승인 후 PRD 수정
  3. CHANGELOG에 변경 이력 기록
  4. 영향받는 모듈 재검토
```

---

## 7. 금지 사항

### 7.1 절대 금지

```
1. 임의 결정 금지
   PRD에 명시 안 된 사항 임의 결정 금지
   → 사용자에게 질문

2. 헌법 위반 금지
   5원칙 어기는 코드 작성 금지
   → 하네스에 의해 차단됨

3. 직접 수정 금지
   V7.0 유지 모듈을 V7.1 룰로 직접 수정 금지
   → 확장 또는 신규 모듈로 처리

4. 매직 넘버 금지
   거래 룰의 수치를 코드에 직접 입력 금지
   → constants.py 또는 V71Constants 사용

5. 스킬 우회 금지
   표준 스킬 사용 의무, 직접 구현 금지

6. 테스트 없는 PR 금지
   하네스 7이 차단

7. 보안 무시 금지
   환경변수, 시크릿 관리 표준 따를 것
```

### 7.2 OpenClaw 관련

```
OpenClaw는 V7.1과 무관한 외부 시스템:
  - V7.1 코드에서 OpenClaw 참조 금지
  - 새 OpenClaw 스킬 추가 금지
  - OpenClaw 관련 import 금지

만약 OpenClaw 관련 코드 발견 시:
  → 즉시 보고
  → 삭제 대상으로 분류
```

### 7.3 백테스트 관련

```
V7.1에서는 백테스트 시스템 사용 안 함:
  - 새 백테스트 코드 작성 금지
  - 기존 백테스트 코드 수정 금지
  - 백테스트 모듈 import 금지

페이퍼 트레이드는 별도:
  - 실시간 시장 데이터로 검증
  - 실제 거래 없이 모니터링
  - V7.1 시스템에 포함 (백테스트 아님)
```

---

## 8. 참조 문서 인덱스

### 8.1 즉시 필요

```
01_PRD_MAIN.md           - 전체 결정 사항 통합
02_TRADING_RULES.md      - §1~§13 거래 룰 (가장 중요)
03_DATA_MODEL.md         - Supabase 스키마
04_ARCHITECTURE.md       - 아키텍처, 모듈 분류
05_MIGRATION_PLAN.md     - V7.0 → V7.1 전환 계획
```

### 8.2 작업별 필요

```
에이전트 작업: 06_AGENTS_SPEC.md
스킬 작업:    07_SKILLS_SPEC.md
하네스 작업:  08_HARNESS_SPEC.md

API 작업:     09_API_SPEC.md
UI 작업:      10_UI_GUIDE.md
리포트 작업:  11_REPORTING.md
보안 작업:    12_SECURITY.md
```

### 8.3 부속

```
13_APPENDIX.md - 결정 이력, 미정 사항, 트러블슈팅
```

---

## 9. 작업 진행 상황 기록

### 9.1 진행 상황 파일

```
작업 시작 시 다음 파일 생성/업데이트:
C:\K_stock_trading\docs\v71\WORK_LOG.md

기록 형식:
## YYYY-MM-DD
### 완료
- [P1.1] OpenClaw 정리 완료
- [P1.2] 백테스트 시스템 삭제 완료

### 진행 중
- [P1.3] 임시 파일 정리 (50% 완료)

### 차단됨
- [P3.1] 박스 매니저 - PRD §3.5 모순 발견, 사용자 결정 대기
```

### 9.2 사용자 보고 시점

```
다음 시점에 사용자에게 보고:
  - Phase 완료 시
  - 헌법 위반 가능성 발견 시
  - PRD 모순 발견 시
  - 예상 외 시간 소요 시 (계획 대비 50% 초과)
  - 외부 의존성 문제 발생 시
```

---

## 10. 시작 명령

이 문서를 읽었다면, 사용자에게 다음과 같이 응답하세요:

```
V7.1 시스템 구현 작업 준비 완료.

다음 문서를 모두 읽었습니다:
- README.md
- 00_CLAUDE_CODE_GENERATION_PROMPT.md (이 문서)

V7.1 헌법 5원칙을 인지했습니다:
1. 사용자 판단 불가침
2. NFR1 최우선
3. 충돌 금지
4. 시스템 계속 운영
5. 단순함 우선

작업 명령을 받겠습니다.

먼저 시작할 작업을 지시해주세요. 권장 순서:
- Phase 1 인프라 정리 (P1.1 ~ P1.8)
- Phase 2 V7.1 신규 모듈 골격
- Phase 3 거래 룰 구현
```

---

*이 지시서는 V7.1 작업의 마스터 가이드입니다.*  
*작업 중 불명확한 점이 있으면 즉시 사용자에게 질문하세요.*

*최종 업데이트: 2026-04-25*
