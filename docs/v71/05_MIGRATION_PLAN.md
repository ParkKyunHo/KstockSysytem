# V7.1 마이그레이션 계획 (Migration Plan)

> 이 문서는 V7.0 → V7.1 안전한 전환 전략을 정의합니다.
> 
> **충돌 금지 원칙(헌법 3)이 모든 단계의 절대 기준입니다.**
> 
> 모든 작업은 Phase 단위로 진행하며 각 Phase 완료 시 검증 통과 후 다음 단계 진행합니다.

---

## 목차

- [§0. 마이그레이션 원칙](#0-마이그레이션-원칙)
- [§1. 전체 로드맵](#1-전체-로드맵)
- [§2. Phase 0: 사전 준비](#2-phase-0-사전-준비)
- [§3. Phase 1: 인프라 정리](#3-phase-1-인프라-정리)
- [§4. Phase 2: V7.1 골격 구축](#4-phase-2-v71-골격-구축)
- [§5. Phase 3: 거래 룰 구현](#5-phase-3-거래-룰-구현)
- [§6. Phase 4: 알림 시스템](#6-phase-4-알림-시스템)
- [§7. Phase 5: 웹 대시보드](#7-phase-5-웹-대시보드)
- [§8. Phase 6: 리포트 시스템](#8-phase-6-리포트-시스템)
- [§9. Phase 7: 통합 테스트 및 배포](#9-phase-7-통합-테스트-및-배포)
- [§10. Feature Flag 전략](#10-feature-flag-전략)
- [§11. 롤백 계획](#11-롤백-계획)
- [§12. 데이터 마이그레이션](#12-데이터-마이그레이션)

---

## §0. 마이그레이션 원칙

### 0.1 5대 원칙

```yaml
원칙 1: 단계적 전환 (Gradual Migration)
  한 번에 모든 것 바꾸기 금지
  Phase별 작은 단위 진행
  각 Phase 검증 후 다음 진행
  
원칙 2: 양립 가능성 (Coexistence)
  V7.0 운영 중 V7.1 개발/테스트 가능
  Feature Flag로 점진 활성화
  V7.0 즉시 폐기 안 함

원칙 3: 의존성 추적 (Dependency Tracking)
  삭제 전 import 모두 검색
  연쇄 삭제 순서 결정
  깨지는 곳 미리 파악

원칙 4: 롤백 가능 (Reversibility)
  모든 변경은 되돌릴 수 있어야
  DB 마이그레이션 UP/DOWN
  Feature Flag로 즉시 비활성화
  Git 태그 단계별

원칙 5: 검증 우선 (Verification First)
  각 단계 검증 통과 필수
  자동 검증 (하네스)
  수동 검증 (체크리스트)
  실패 시 즉시 중단
```

### 0.2 작업 단위

```yaml
작업 단위: Phase
  큰 단계 (Phase 0~7)
  각 Phase는 독립적으로 완료 가능

작업 단위: Task
  Phase 내부의 세부 작업
  P1.1, P1.2 같은 식으로 번호

작업 단위: Step
  Task 내부의 실행 단계
  Step 1, 2, 3...

진행 기록:
  C:\K_stock_trading\docs\v71\WORK_LOG.md
  매 Task 완료 시 업데이트
```

### 0.3 검증 기준

각 Phase 완료 시 모두 통과해야 합니다.

```yaml
자동 검증 (하네스):
  - 하네스 1: Naming Collision Detector
  - 하네스 2: Dependency Cycle Detector
  - 하네스 3: Trading Rule Enforcer
  - 하네스 4: Schema Migration Validator
  - 하네스 5: Feature Flag Enforcer
  - 하네스 6: Dead Code Detector
  - 하네스 7: Test Coverage Enforcer

수동 검증:
  - 코드 리뷰 (Architect Agent)
  - 룰 검증 (Trading Logic Verifier Agent)
  - 보안 리뷰 (Security Reviewer Agent, 해당 Phase만)
  - 테스트 작성 (Test Strategy Agent)

운영 검증 (배포 후):
  - 24시간 페이퍼 트레이드
  - 시스템 안정성 (재시작 빈도)
  - 알림 정상 작동
  - DB 무결성
```

---

## §1. 전체 로드맵

### 1.1 Phase 개요

```
Phase 0: 사전 준비 (1일)
  ├─ 백업
  ├─ 환경 분리
  └─ Feature Flag 인프라

Phase 1: 인프라 정리 (3~5일)
  ├─ OpenClaw 정리
  ├─ 백테스트 삭제
  ├─ V6 SNIPER_TRAP 삭제
  ├─ V7 신호 시스템 삭제
  ├─ 미완성 추상화 정리
  ├─ wave_harvest_exit 정리
  └─ trading_engine.py 정리

Phase 2: V7.1 골격 (3~5일)
  ├─ 디렉토리 구조 생성
  ├─ 스킬 8개 골격
  ├─ 데이터 모델 마이그레이션
  └─ 핵심 클래스 시그니처

Phase 3: 거래 룰 구현 (10~15일) ★ 가장 중요
  ├─ 박스 시스템
  ├─ 매수 실행
  ├─ 매수 후 관리 (손절/익절/TS)
  ├─ 평단가 관리
  ├─ 수동 거래 처리
  ├─ VI 처리
  └─ 시스템 재시작 복구

Phase 4: 알림 시스템 (2~3일)
  ├─ 알림 등급 구조
  ├─ 텔레그램 명령어 13개
  ├─ 일일 마감 알림
  └─ 월 1회 리뷰

Phase 5: 웹 대시보드 (5~10일)
  ├─ FastAPI 백엔드
  ├─ JWT + 2FA
  ├─ Claude Design UI
  └─ 통합

Phase 6: 리포트 시스템 (3~5일)
  ├─ Claude API 통합
  ├─ 데이터 수집
  └─ PDF/Excel 생성

Phase 7: 통합 테스트 및 배포 (5~10일)
  ├─ 페이퍼 트레이드 (1~2주)
  ├─ AWS 배포
  └─ 점진 활성화

총 예상 기간: 1~2개월 (1인 풀타임 기준)
```

### 1.2 의존성 순서

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 7
                                  ↘
                                  Phase 4 → Phase 7
                                  ↘
                                  Phase 5 → Phase 7
                                  ↘
                                  Phase 6 → Phase 7

Phase 3 완료 시 Phase 4, 5, 6 병렬 가능
Phase 7은 모두 완료 후
```

### 1.3 마일스톤

```yaml
M1: Phase 1 완료
  - V7.0 시스템에서 폐기 코드 모두 제거
  - 인프라만 남은 깨끗한 상태
  - 기존 V7.0 운영 영향 없음 (코드만 정리)

M2: Phase 2 완료
  - V7.1 신규 패키지 골격
  - 컴파일 가능, 실행 안 함
  - 데이터 모델 V7.1 추가 완료

M3: Phase 3 완료 ★ 가장 중요
  - V7.1 거래 룰 모두 구현
  - 페이퍼 트레이드 가능
  - 단위 테스트 90%+ 통과

M4: Phase 4~6 완료
  - 알림, 웹, 리포트 모두 구축
  - 사용자 인터페이스 완비

M5: Phase 7 완료
  - 실거래 운영
  - V7.1 안정화
```

---

## §2. Phase 0: 사전 준비

### 2.1 P0.1: 전체 백업

```yaml
목적: 작업 시작 전 안전망

작업:
  Step 1: Git 태그 생성
    git tag v7.0-final-stable
    git push origin v7.0-final-stable
  
  Step 2: 코드 백업
    프로젝트 전체 zip 백업
    별도 저장소 (외장 SSD, 클라우드)
  
  Step 3: DB 스냅샷
    Supabase Dashboard에서 백업 다운로드
    또는 pg_dump으로 SQL 백업
    저장: backups/db_v70_final_YYYYMMDD.sql
  
  Step 4: 환경 변수 백업
    .env 파일 백업 (시크릿 분리 보관)
    
  Step 5: 운영 중인 V7.0 상태 기록
    현재 추적 중 종목 목록
    보유 포지션 상태
    미체결 주문

검증:
  - Git 태그 확인
  - 백업 파일 무결성 확인
  - 복원 시뮬레이션 (테스트 환경)
```

### 2.2 P0.2: 개발 환경 분리

```yaml
목적: V7.0 운영 영향 없이 V7.1 개발

작업:
  Step 1: 개발 브랜치 생성
    git checkout -b v71-development
    git push -u origin v71-development
  
  Step 2: 로컬 개발 환경 구성
    venv 또는 별도 Python 환경
    Supabase 별도 프로젝트 (개발용)
    또는 로컬 PostgreSQL
  
  Step 3: 모의 키움 API 사용
    실거래 영향 없도록
    또는 Read-only 모드

  Step 4: .env.development 파일
    개발용 환경 변수
    실제 키움 API 키 분리

검증:
  - V7.1 개발 환경 정상 작동
  - V7.0 운영 환경 영향 없음
```

### 2.3 P0.3: Feature Flag 인프라

```yaml
목적: V7.1 기능 점진 활성화

작업:
  Step 1: config/feature_flags.yaml 생성
    내용 (초기):
    ```yaml
    v71:
      box_system: false
      vi_monitor: false
      reconciliation_v71: false
      web_dashboard: false
      reporting: false
      monthly_review: false
      daily_summary: false
    ```
  
  Step 2: src/utils/feature_flags.py 모듈
    YAML 로딩
    환경 변수로 오버라이드 가능
    런타임 갱신 (선택)
  
  Step 3: 사용 예시 코드
    ```python
    from src.utils.feature_flags import is_enabled
    
    if is_enabled('v71.box_system'):
        # V7.1 박스 시스템
        ...
    else:
        # V7.0 동작 (또는 패스)
        ...
    ```

검증:
  - Flag 정상 로딩
  - 환경 변수 오버라이드 동작
  - 모든 V7.1 코드는 Flag 체크 통과
```

### 2.4 P0.4: 자동 검증 도구 설치

```yaml
하네스 도구 준비:
  Step 1: pre-commit 설정
    .pre-commit-config.yaml 생성
    각 하네스 hook 등록
  
  Step 2: 정적 분석 도구
    pylint, mypy, ruff 설정
    import 그래프 분석 (pydeps)
  
  Step 3: 테스트 인프라
    pytest 설정 (pytest.ini)
    pytest-cov (커버리지)
    pytest-asyncio (비동기 테스트)
  
  Step 4: CI/CD 파이프라인 (선택)
    GitHub Actions 또는 로컬 스크립트
    하네스 자동 실행

검증:
  - pre-commit hook 동작 확인
  - pytest 정상 실행
  - 하네스 1~7 모두 호출 가능
```

---

## §3. Phase 1: 인프라 정리

### 3.1 Phase 1 개요

```yaml
목적:
  V7.0 폐기 코드 모두 제거
  깨끗한 인프라만 남기기
  V7.1 안전 추가 환경 마련

원칙:
  - 의존성 순서대로 삭제 (역방향)
  - 각 Task 후 시스템 정상 동작 확인
  - 깨지는 import 즉시 처리

선후 관계:
  P1.1 (OpenClaw) → 영향 없음, 먼저
  P1.2 (백테스트) → 영향 없음, 둘째
  P1.3 (임시 파일) → 영향 없음, 셋째
  P1.4 (V6 삭제) → 의존성 추적 필요
  P1.5 (V7 신호 삭제) → 의존성 추적 필요
  P1.6 (미완성 추상화) → 위 완료 후
  P1.7 (wave_harvest_exit) → V7.1 룰 적용
  P1.8 (trading_engine) → 마지막
```

### 3.2 P1.1: OpenClaw 정리

```yaml
작업:
  Step 1: 코드 베이스 영향 확인
    grep -r "openclaw" src/
    → 영향 없음 확인 (외부 시스템)
  
  Step 2: 문서 정리
    Filesystem:write_file 사용
    docs/OPENCLAW_GUIDE.md 삭제
    CLAUDE.md의 Part 0 OpenClaw 섹션 삭제
  
  Step 3: 외부 디렉토리 정리 (사용자 직접)
    ~/.openclaw/ 디렉토리 삭제
    Scheduled Task "OpenClaw Gateway" 비활성/삭제
    Telegram 봇 (@stock_Albra_bot) 정리 (선택)
  
  Step 4: CLAUDE.md 갱신
    OpenClaw 관련 모든 언급 제거
    V7.1 부분만 남김

검증:
  - grep -r "openclaw" 결과 없음
  - grep -r "Gemini" 결과 없음 (관련 언급)
  - 외부 디렉토리 부재 확인
```

### 3.3 P1.2: 백테스트 시스템 삭제

```yaml
작업:
  Step 1: 의존성 확인
    grep -r "backtest" src/
    grep -r "from backtest_modules" src/
    → 다른 코드가 import하는지 확인
  
  Step 2: 파일 삭제
    삭제 대상:
      run_backtest_ui.py
      scripts/backtest/ (전체 디렉토리)
      backtest_modules/ (있다면)
    
  Step 3: 캐시 삭제
    삭제 대상:
      3m_data/ (시세 캐시)
      results/ (백테스트 결과)
      *.xlsx (ema_split_buy_*.xlsx 등)
      *.csv (testday.csv, past1000*.csv, 3mintest.csv 등)
      full_3min_backtest_result.xlsx
      improved_entry_backtest_result*.xlsx
  
  Step 4: 의존하던 모듈 import 정리
    백테스트 import 모두 제거
  
  Step 5: requirements.txt 정리
    백테스트 전용 라이브러리 제거 (있다면)

검증:
  - grep -r "backtest" 결과 없음
  - 디스크 공간 확보 확인
  - python -c "import src.main" 정상
```

### 3.4 P1.3: 임시 파일 정리

```yaml
작업:
  Step 1: 루트 디렉토리 임시 파일 삭제
    삭제 대상:
      CK_stock_tradingdataanalysislogs_*.txt
      CK_stock_tradingtemp_*.txt
      temp_log*.txt
      *.recovered
      *.new
  
  Step 2: 캐시 디렉토리 정리
    삭제 대상:
      .pytest_cache/
      .coverage
      htmlcov/
      __pycache__/ (전체, .gitignore 확인)
      *.pyc
  
  Step 3: 로그 디렉토리 (선택)
    오래된 로그 파일 정리
    또는 logs/archive/로 이동
  
  Step 4: .gitignore 갱신
    이런 파일들이 다시 커밋되지 않도록

검증:
  - 루트 디렉토리 깔끔함
  - du -sh 디스크 사용량 확인
```

### 3.5 P1.4: V6 SNIPER_TRAP 삭제

```yaml
작업:
  Step 1: 의존성 추적
    grep -r "v6_sniper_trap" src/
    grep -r "from src.core.signal_detector " src/
    grep -r "auto_screener" src/
    grep -r "exit_manager" src/
    grep -r "from src.core.indicator " src/
    
    Migration Strategy Agent 호출:
    "V6 모듈 삭제 안전성 검토 부탁합니다"
  
  Step 2: 의존하는 모듈 정리
    trading_engine.py에서 V6 호출 제거
    strategy_orchestrator.py에서 V6 분기 제거
    (이 두 파일은 P1.5/P1.8에서 별도 처리)
  
  Step 3: V6 파일 삭제
    삭제 대상:
      src/core/strategies/v6_sniper_trap.py
      src/core/signal_detector.py (V6용)
      src/core/auto_screener.py
      src/core/exit_manager.py
      src/core/indicator.py (V6 위임)
    
    각 파일 삭제 후:
      pytest 실행 → 깨진 곳 확인
      깨진 import 즉시 수정
  
  Step 4: V6 테스트 삭제
    tests/v6/ (있다면)
    또는 tests/test_v6_*.py
  
  Step 5: V6 관련 설정 정리
    config.yaml의 V6 섹션 제거
    V6 환경 변수 제거

검증:
  - grep -r "v6_sniper" src/ 결과 없음
  - grep -r "SNIPER_TRAP" src/ 결과 없음
  - pytest tests/ 통과 (V6 테스트 제외)
  - python -c "import src.main" 정상
  
  하네스 6 (Dead Code Detector):
    V6 import 발견 시 빌드 차단
```

### 3.6 P1.5: V7 신호 시스템 삭제

```yaml
작업:
  Step 1: 의존성 추적
    grep -r "v7_purple_reabs" src/
    grep -r "signal_detector_purple" src/
    grep -r "signal_pool" src/
    grep -r "v7_signal_coordinator" src/
    grep -r "strategy_orchestrator" src/
    grep -r "PurpleScore" src/
    grep -r "indicator_purple" src/
    grep -r "missed_signal_tracker" src/
    grep -r "watermark_manager" src/
    grep -r "atr_alert_manager" src/
    grep -r "condition_search_handler" src/
  
  Step 2: 호출하는 모듈 정리
    trading_engine.py: V7 신호 호출 모두 제거 (P1.8 처리)
    
  Step 3: 파일 삭제 (의존성 역순)
    1차 삭제 (다른 모듈에서 가장 많이 import):
      src/core/strategies/v7_purple_reabs.py
      src/core/signal_detector_purple.py
      src/core/signal_pool.py
      src/core/signal_processor.py
    
    2차 삭제:
      src/core/v7_signal_coordinator.py
      src/core/strategy_orchestrator.py
      src/core/missed_signal_tracker.py
      src/core/watermark_manager.py
    
    3차 삭제 (보조):
      src/core/atr_alert_manager.py
      src/core/condition_search_handler.py
      src/core/indicator_purple.py
    
    각 단계 후 pytest 실행
  
  Step 4: V7 테스트 삭제
    tests/v7/, tests/test_v7_*.py
    tests/test_signal_pool.py
    tests/test_purple_*.py
  
  Step 5: 관련 설정 정리
    config.yaml의 V7 신호 섹션
    PurpleConstants 등 V7 상수
    V7 환경 변수

검증:
  - grep -r "purple" src/ 결과 없음 (또는 무관한 단어만)
  - grep -r "signal_pool" src/ 결과 없음
  - grep -r "Dual-Pass" src/ 결과 없음
  - python -c "import src.main" 정상
  
  하네스 6:
    V7 신호 시스템 import 발견 시 차단
```

### 3.7 P1.6: 미완성 추상화 정리

```yaml
작업:
  Step 1: 디렉토리 확인
    src/core/detectors/
    src/core/signals/
    src/core/exit/
    src/strategy/ (다른 위치)
    src/scheduler/
    src/strategies/
    
    각 디렉토리 내용 확인
    base 클래스만 있는지 확인
  
  Step 2: 의존성 추적
    base_signal, base_detector, base_exit 등 import 확인
    구현체가 있다면 (V6/V7 외) 보존
  
  Step 3: 디렉토리 삭제
    빈 또는 base만 있는 디렉토리 제거
    
  Step 4: 관련 import 제거

검증:
  - 빈 디렉토리 없음
  - import 깨진 곳 없음
```

### 3.8 P1.7: wave_harvest_exit.py 정리

```yaml
작업 (수정, 삭제 아님):
  Step 1: V7.0 룰 부분 제거
    제거 대상 (코드 내):
      - ATR 배수 6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0 (V7.0)
      - Trend Hold Filter (TrendHold = ...)
      - Highest(High, 20) 기반 BasePrice (V7.0)
      - Max Holding 60일
  
  Step 2: V7.1 룰로 교체
    교체 대상:
      - ATR 배수 4.0 → 3.0 → 2.5 → 2.0 (V7.1)
      - BasePrice = 매수 후 최고가 (단순화)
      - Trend Hold Filter 폐기 (조건 없이 청산)
      - Max Holding 무제한
  
  Step 3: V7.1 스킬 사용
    src/core/v71/skills/exit_calc_skill.py 호출
    매직 넘버 제거
  
  Step 4: 단위 테스트 갱신
    V7.1 룰 기반 테스트 케이스
    ATR 배수 단계 검증
    BasePrice 추적 검증

대안 (권장):
  새 파일로 분리: src/core/v71/exit/trailing_stop.py
  wave_harvest_exit.py는 V7.0 deprecation 마킹
  Feature Flag로 전환

검증:
  - V7.1 ATR 배수 단계 정확
  - Trend Hold Filter 코드 없음
  - 단위 테스트 90%+ 통과
  
  하네스 3 (Trading Rule Enforcer):
    V7.0 ATR 배수 발견 시 차단
```

### 3.9 P1.8: trading_engine.py 정리

> **Phase A 완료 (2026-04-28)**: 사용자 결정에 따라 P1.8의 점진적 정리 대신 V7.0 trading_engine.py 자체를 Phase A Step D에서 일괄 삭제했습니다. 본 절은 historical reference입니다. WORK_LOG.md 의 "Phase A: V7.0 완전 폐기" entry 참조.

```yaml
주의: 이게 가장 큰 작업. 4,904줄 → ~1,500줄 예상.

작업:
  Step 1: V6 호출 모두 제거
    SNIPER_TRAP 관련 메서드 호출
    V6 신호 처리 로직
  
  Step 2: V7 신호 시스템 호출 모두 제거
    V7SignalCoordinator 초기화/호출
    Dual-Pass 관련
    SignalPool 등록/조회
    PurpleScore 계산
  
  Step 3: ExitCoordinator 호출 변경
    V7.0 ExitCoordinator는 V7.1 EXIT 시스템으로 교체
    또는 V7.1 호환 모드로 수정
  
  Step 4: V7.1 hooks 추가 (Phase 2 후 활성화)
    V71BoxEntryDetector 호출
    V71ExitCalculator 호출
    V71PathManager 호출
    
    초기에는 Feature Flag로 OFF
    Phase 3 완료 후 활성화
  
  Step 5: 메인 엔진 골격 정리
    EngineState ENUM 유지
    초기화 로직 정리
    백그라운드 태스크 V7.1로 교체
  
  Step 6: 단위 테스트 갱신
    V7.1 시나리오 기반

검증:
  - 줄 수 감소 (4,904 → ~1,500)
  - V6/V7 신호 시스템 호출 없음
  - import 깨진 곳 없음
  - 시스템 시작/종료 정상
```

### 3.10 Phase 1 완료 검증

```yaml
체크리스트:
  ☐ P1.1 OpenClaw 정리 완료
  ☐ P1.2 백테스트 시스템 삭제 완료
  ☐ P1.3 임시 파일 정리 완료
  ☐ P1.4 V6 SNIPER_TRAP 삭제 완료
  ☐ P1.5 V7 신호 시스템 삭제 완료
  ☐ P1.6 미완성 추상화 정리 완료
  ☐ P1.7 wave_harvest_exit 정리 완료
  ☐ P1.8 trading_engine 정리 완료

자동 검증:
  ☐ pytest 통과 (V7.0 인프라 테스트만)
  ☐ python -c "import src.main" 정상
  ☐ 하네스 1, 2, 6 통과
  ☐ 디스크 공간 확보 (5GB+)

수동 검증:
  ☐ 코드 줄 수 대폭 감소 (40%+ 감소)
  ☐ 디렉토리 구조 깨끗
  ☐ Architect Agent 검토 통과

기록:
  ☐ WORK_LOG.md 업데이트
  ☐ Git tag: v71-phase1-complete
  ☐ 다음 Phase 시작 가능 상태
```

---

## §4. Phase 2: V7.1 골격 구축

### 4.1 Phase 2 개요

```yaml
목적:
  V7.1 신규 패키지 디렉토리 구조 생성
  핵심 클래스 시그니처 작성 (구현 X)
  데이터 모델 마이그레이션
  스킬 8개 골격

원칙:
  - 컴파일만 가능, 실행 X
  - 타입 힌트 + Docstring 완전 작성
  - 메서드는 NotImplementedError 또는 빈 함수
  - Phase 3에서 실제 구현
```

### 4.2 P2.1: 디렉토리 구조 생성

```yaml
작업:
  Step 1: src/core/v71/ 디렉토리 생성
    필요 디렉토리 (04_ARCHITECTURE.md §1.2 참조)
    
    각 디렉토리에 __init__.py 생성
  
  Step 2: src/web/ 디렉토리 생성
    웹 대시보드 백엔드
    필요 디렉토리 (04_ARCHITECTURE.md §1.2 참조)
  
  Step 3: tests/v71/ 디렉토리 생성
    conftest.py (공통 fixture)
    각 모듈별 테스트 파일 placeholder
  
  Step 4: docs/v71/ 확인
    이미 존재 (이 문서 디렉토리)

검증:
  - 디렉토리 구조 04_ARCHITECTURE.md와 일치
  - 모든 __init__.py 존재
  - 하네스 1 (Naming Collision) 통과
```

### 4.3 P2.2: 데이터 모델 마이그레이션

```yaml
작업:
  Step 1: 마이그레이션 파일 작성
    위치: src/database/migrations/v71/
    
    파일 (03_DATA_MODEL.md §8.2 참조):
      001_create_tracked_stocks.up.sql / .down.sql
      002_create_support_boxes.up.sql / .down.sql
      003_extend_positions.up.sql / .down.sql
      004_create_trade_events.up.sql / .down.sql
      005~016 (각 테이블)
      999_indexes_and_constraints.sql
  
  Step 2: ORM 모델 작성
    위치: src/database/models/v71/
    
    각 테이블별 SQLAlchemy 또는 Pydantic 모델
    ENUM 타입 정의
    관계 정의
  
  Step 3: Repository 작성
    위치: src/database/repositories/v71/
    
    각 테이블별 CRUD
    BoxRepository
    PositionRepository
    EventRepository
    NotificationRepository
    ReportRepository
    ...
  
  Step 4: 개발 환경 마이그레이션 적용
    개발 DB에 UP 적용
    검증
    DOWN 테스트 (롤백 가능 확인)

검증:
  - 모든 테이블 생성 성공
  - 인덱스 생성 성공
  - DOWN 마이그레이션 정상 동작
  - 하네스 4 (Schema Migration Validator) 통과
```

### 4.4 P2.3: 스킬 8개 골격

```yaml
작업:
  위치: src/core/v71/skills/
  
  Step 1: kiwoom_api_skill.py
    함수 시그니처 작성
    Docstring 완전 (Args, Returns, Raises)
    구현은 placeholder
    
  Step 2: box_entry_skill.py
    evaluate_box_entry() 함수 시그니처
    
  Step 3: exit_calc_skill.py
    calculate_effective_stop() 함수 시그니처
    
  Step 4: avg_price_skill.py
    update_position_after_buy() 시그니처
    update_position_after_sell() 시그니처
    
  Step 5: vi_skill.py
    handle_vi_state() 시그니처
    
  Step 6: notification_skill.py
    send_notification() 시그니처
    
  Step 7: reconciliation_skill.py
    reconcile_positions() 시그니처
    
  Step 8: test_template.py
    테스트 작성 표준 패턴

검증:
  - 모든 스킬 모듈 import 가능
  - mypy 타입 검사 통과
  - 하네스 3 (Trading Rule Enforcer) 활성화
```

### 4.5 P2.4: 핵심 클래스 시그니처

```yaml
작업:
  src/core/v71/box/box_manager.py:
    V71BoxManager 클래스
    모든 메서드 시그니처 + Docstring
    
  src/core/v71/box/box_entry_detector.py:
    V71BoxEntryDetector 클래스
    
  src/core/v71/strategies/:
    V71PullbackStrategy
    V71BreakoutStrategy
    
  src/core/v71/exit/:
    V71ExitCalculator
    V71ExitExecutor
    V71TrailingStop
    
  src/core/v71/position/:
    V71PositionManager
    V71Reconciler
    
  src/core/v71/path_manager.py:
    V71PathManager
    
  src/core/v71/vi_monitor.py:
    V71VIMonitor
    
  src/core/v71/event_logger.py:
    V71EventLogger
    
  src/core/v71/restart_recovery.py:
    V71RestartRecovery
    
  src/core/v71/audit_scheduler.py:
    V71AuditScheduler
    
  src/core/v71/v71_constants.py:
    V71Constants 클래스
    02_TRADING_RULES.md 부록 A.4의 모든 상수

검증:
  - 모든 클래스 import 가능
  - mypy 통과
  - 하네스 1 (Naming Collision) 통과
  - 하네스 2 (Dependency Cycle) 통과
```

### 4.6 P2.5: Feature Flag 통합

```yaml
작업:
  Step 1: V7.1 모듈 모두 Flag 체크
    초기화 시 Flag 확인
    Disabled면 NotImplementedError 또는 패스
    
  Step 2: trading_engine.py에 V7.1 hooks
    if is_enabled('v71.box_system'):
        await self.v71_components.box_entry_detector.check(...)
    
  Step 3: 모든 Flag 초기 상태 OFF
    feature_flags.yaml:
      v71:
        box_system: false
        ...

검증:
  - 모든 V7.1 코드 Flag 체크
  - Flag OFF 상태에서 시스템 정상 (V7.1 코드 안 실행)
  - 하네스 5 (Feature Flag Enforcer) 통과
```

### 4.7 Phase 2 완료 검증

```yaml
체크리스트:
  ☐ 디렉토리 구조 04_ARCHITECTURE.md와 일치
  ☐ 데이터 모델 마이그레이션 UP/DOWN 완료
  ☐ 스킬 8개 시그니처 완성
  ☐ V7.1 핵심 클래스 시그니처 완성
  ☐ Feature Flag 통합 완료

자동 검증:
  ☐ python -c "import src.core.v71" 정상
  ☐ python -c "import src.web" 정상
  ☐ mypy src/ 통과 (V7.1 타입 검사)
  ☐ pytest tests/v71/ 통과 (placeholder만)
  ☐ 하네스 1, 2, 4, 5 통과

수동 검증:
  ☐ Architect Agent 구조 검토
  ☐ 의존성 그래프 단방향 확인

기록:
  ☐ WORK_LOG.md 업데이트
  ☐ Git tag: v71-phase2-complete
```

---

## §5. Phase 3: 거래 룰 구현

### 5.1 Phase 3 개요

```yaml
목적:
  02_TRADING_RULES.md의 모든 룰 정확히 구현

원칙:
  - 룰 변경 금지 (PRD가 진실)
  - 매직 넘버 금지 (V71Constants 사용)
  - 스킬 사용 강제
  - Trading Logic Verifier Agent 검증

순서 (의존성):
  P3.1 박스 시스템 (가장 기본)
    ↓
  P3.2 매수 실행 (박스 + 주문)
    ↓
  P3.3 매수 후 관리 (포지션 + 청산)
    ↓
  P3.4 평단가 관리 (위와 통합)
    ↓
  P3.5 수동 거래 처리
    ↓
  P3.6 VI 처리
    ↓
  P3.7 시스템 재시작 복구
```

### 5.2 P3.1: 박스 시스템 구현

```yaml
참조: 02_TRADING_RULES.md §3

작업:
  Step 1: V71BoxManager 구현
    create_box() - 박스 생성, 겹침 검증
    modify_box() - 박스 수정 (BOX_SET / POSITION_OPEN 차등)
    delete_box() - 박스 삭제 (미체결 주문 자동 취소)
    validate_no_overlap() - 겹침 검증
    check_30day_expiry() - 30일 만료 알림
    mark_triggered() / mark_invalidated() / mark_cancelled()
  
  Step 2: V71BoxEntryDetector 구현
    check_entry() - 봉 완성 시 진입 조건 체크
    스킬 사용: box_entry_skill.evaluate_box_entry()
  
  Step 3: V71BoxStateMachine 구현
    상태 전이 검증
    TRACKING → BOX_SET → POSITION_OPEN → POSITION_PARTIAL → EXITED
  
  Step 4: 단위 테스트 작성
    각 메서드별 테스트
    엣지 케이스:
      - 박스 겹침
      - 한도 초과
      - 잘못된 가격 (상단 < 하단)
    
    Trading Logic Verifier Agent 호출:
      "다음 박스 진입 로직이 §3.8 룰 정확히 구현하나요?"

검증:
  ☐ 단위 테스트 90%+ 통과
  ☐ 룰 검증 (Trading Logic Verifier)
  ☐ 하네스 3 통과
```

### 5.3 P3.2: 매수 실행 구현

```yaml
참조: 02_TRADING_RULES.md §4

작업:
  Step 1: V71PullbackStrategy 구현
    경로 A 눌림 (3분봉)
    경로 B 눌림 (일봉, 익일 09:01)
    
  Step 2: V71BreakoutStrategy 구현
    돌파 조건 (종가 > 박스 상단 + 양봉)
  
  Step 3: V71BuyExecutor 구현 (메인 코디네이터)
    on_entry_triggered() 콜백
    한도 검사
    VI 검사
    매수 실행 (스킬: kiwoom_api_skill)
    포지션 생성
    박스 상태 변경
    이벤트 로그
    알림
  
  Step 4: 주문 실행 정책
    지정가 1호가 위 × 5초 × 3회 → 시장가
    부분 체결 처리
    대량 주문 호가 소진 시 1호가씩
  
  Step 5: 갭업 처리 (경로 B)
    5% 이상 시 매수 포기 + 알림
  
  Step 6: 단위 테스트
    각 시나리오 테스트:
      - 정상 매수
      - 한도 초과
      - VI 중 매수
      - 갭업 5% 초과
      - 시장가 실패

검증:
  ☐ 단위 테스트 통과
  ☐ Trading Logic Verifier 통과
  ☐ Mock 주문으로 통합 테스트
```

### 5.4 P3.3: 매수 후 관리 구현

```yaml
참조: 02_TRADING_RULES.md §5

작업:
  Step 1: V71ExitCalculator 구현
    calculate_effective_stop() - 스킬 사용
    단계별 손절선 (-5/-2/+4)
    TS 청산선 (BasePrice - ATR × 배수)
    유효 청산선 = max(고정, TS)
  
  Step 2: V71TrailingStop 구현
    BasePrice 추적 (매수 후 최고가)
    ATR 배수 단계 (4.0/3.0/2.5/2.0)
    단방향 축소만
    +5% 활성화, +10% 청산선 유효화
  
  Step 3: V71ExitExecutor 구현
    execute_stop_loss() - 시장가 매도 전량
    execute_profit_take(level) - 30% 청산 (지정가 → 시장가)
    execute_ts_exit() - TS 청산
  
  Step 4: 청산 모니터링 루프
    POSITION_OPEN/PARTIAL 종목 매 틱 체크
    조건 충족 시 즉시 실행
    NFR1 보장
  
  Step 5: Trend Hold Filter 폐기 검증
    절대 청산을 막는 필터 없음
    조건 충족 즉시 청산
  
  Step 6: Max Holding 무제한
    날짜 기반 강제 청산 코드 없음
  
  Step 7: 단위 테스트
    각 단계별 손절선
    각 ATR 배수 단계
    BasePrice 갱신
    TS 단방향 (하락 안 함)

검증:
  ☐ 단위 테스트 95%+ 통과 (거래 로직)
  ☐ Trading Logic Verifier 통과
  ☐ Backtest 없이 룰 정확성만 검증
```

### 5.5 P3.4: 평단가 관리 구현

```yaml
참조: 02_TRADING_RULES.md §6

작업:
  Step 1: avg_price_skill.update_position_after_buy()
    신규 매수: weighted_avg = buy_price
    추가 매수: 가중 평균 재계산
    이벤트 리셋: profit_5/10_executed = False
    손절선 재계산: avg × 0.95 (단계 1)
    TS BasePrice 유지
  
  Step 2: avg_price_skill.update_position_after_sell()
    수량 감소만, 평단가 유지
    이벤트 이력 유지
  
  Step 3: V71PositionManager.add_buy()
    스킬 사용: update_position_after_buy()
    DB 업데이트
    이벤트 로그
  
  Step 4: V71PositionManager.add_sell()
    스킬 사용: update_position_after_sell()
    DB 업데이트
    이벤트 로그
  
  Step 5: 매직 넘버 금지 검증
    하네스 3 활성화
    직접 -0.05 사용 시 차단

검증:
  ☐ 단위 테스트 (가중 평균 정확)
  ☐ 이벤트 리셋 검증
  ☐ 매도 시 평단가 변경 없음 검증
  ☐ 하네스 3 통과
```

### 5.6 P3.5: 수동 거래 처리

```yaml
참조: 02_TRADING_RULES.md §7

작업:
  Step 1: V71Reconciler 구현
    reconcile() - 키움 ↔ DB 비교
    종목별 차이 계산
    시나리오 분기 (A/B/C/D)
  
  Step 2: 시나리오별 처리
    Scenario A (시스템 + 추가 매수):
      - 해당 경로 합산
      - 평단가 재계산
      - 이벤트 리셋
    
    Scenario B (시스템 + 부분 매도):
      - 단일 경로: 수량 감소
      - 이중 경로: 자동 비례 차감 (큰 경로 우선 반올림)
      - MANUAL 우선 차감
    
    Scenario C (추적 중 + 사용자 매수):
      - 추적 종료 (EXITED)
      - 박스 모두 INVALIDATED
      - MANUAL 포지션 신규
      - 텔레그램 + 웹 알림
    
    Scenario D (미추적 + 사용자 매수):
      - MANUAL 포지션 신규
      - tracked_stocks 연결 없음
  
  Step 3: 정기 실행
    시스템 시작 시
    매 5분
    사용자 요청 시
    의심 거래 후
  
  Step 4: 단위 테스트
    각 시나리오 정확성

검증:
  ☐ 4가지 시나리오 모두 정확
  ☐ 이중 경로 비례 차감 정확
  ☐ Trading Logic Verifier 통과
```

### 5.7 P3.6: VI 처리 구현

```yaml
참조: 02_TRADING_RULES.md §10

작업:
  Step 1: V71VIMonitor 구현
    WebSocket type=1h 구독
    VI 이벤트 수신 핸들러
  
  Step 2: VI 상태 머신
    NORMAL → VI_TRIGGERED → VI_RESUMED → NORMAL
  
  Step 3: VI 중 처리
    보유 포지션: 손절/익절 판정 중단
    신규 매수: 단일가 매매 참여
  
  Step 4: VI 해제 후 처리
    즉시 재평가 (NFR1: < 1초)
    조건 충족 시 시장가 매도
    갭 측정 (3% 기준)
  
  Step 5: 당일 신규 진입 금지 플래그
    vi_recovered_today = True
    익일 09:00 리셋
  
  Step 6: vi_skill.handle_vi_state()
    스킬로 추출
    VI 무시한 매매 차단

검증:
  ☐ VI 시뮬레이션 테스트
  ☐ 상태 머신 전이 정확
  ☐ 당일 진입 금지 플래그 동작
```

### 5.8 P3.7: 시스템 재시작 복구

```yaml
참조: 02_TRADING_RULES.md §13

작업:
  Step 1: V71RestartRecovery 구현
    7-Step 복구 시퀀스
    
    Step 0: 안전 모드 진입
    Step 1: 외부 시스템 연결 (DB, 키움, WS, Telegram)
    Step 2: 미완료 주문 모두 취소
    Step 3: 포지션 정합성 (Reconciler 호출)
    Step 4: 시세 재구독
    Step 5: 박스 진입 조건 재평가 (지나간 트리거 무효)
    Step 6: 안전 모드 해제
    Step 7: 복구 보고서 (텔레그램 CRITICAL)
  
  Step 2: 재시작 빈도 모니터링
    system_restarts 테이블 기록
    빈도별 알림 (1회/2회/3회/5회+)
    자동 정지 안 함
  
  Step 3: 안전 모드 동안 차단
    신규 매수 주문 차단
    신규 박스 등록 차단
  
  Step 4: 단위 테스트 + 통합 테스트
    각 Step 검증
    실패 케이스 (DB 연결 실패 등)

검증:
  ☐ 7-Step 정확히 동작
  ☐ 빈도 모니터링 정확
  ☐ 자동 정지 코드 없음 확인
```

### 5.9 Phase 3 완료 검증

```yaml
체크리스트:
  ☐ P3.1 박스 시스템 ✓
  ☐ P3.2 매수 실행 ✓
  ☐ P3.3 매수 후 관리 ✓
  ☐ P3.4 평단가 관리 ✓
  ☐ P3.5 수동 거래 처리 ✓
  ☐ P3.6 VI 처리 ✓
  ☐ P3.7 재시작 복구 ✓

자동 검증:
  ☐ pytest tests/v71/ 통과율 95%+ (거래 로직)
  ☐ 하네스 1, 2, 3, 6, 7 모두 통과
  ☐ mypy 통과
  ☐ 코드 커버리지 90%+ (거래 로직)

수동 검증:
  ☐ Trading Logic Verifier Agent 모든 룰 검증
  ☐ Architect Agent 구조 검토
  ☐ 02_TRADING_RULES.md 모든 §의 구현 확인

페이퍼 트레이드:
  ☐ Mock 환경에서 24시간 운영
  ☐ 박스 진입 → 매수 → 청산 flow 검증
  ☐ 알림 정상 발송

기록:
  ☐ WORK_LOG.md 업데이트
  ☐ Git tag: v71-phase3-complete
```

---

## §6. Phase 4: 알림 시스템

### 6.1 Phase 4 개요

```yaml
참조: 02_TRADING_RULES.md §9

목적:
  알림 등급 시스템 (CRITICAL/HIGH/MEDIUM/LOW)
  텔레그램 명령어 13개
  일일/월별 자동 알림

기간: 2~3일
```

### 6.2 P4.1: 알림 등급 시스템

```yaml
작업:
  Step 1: src/notification/severity.py
    Severity ENUM (CRITICAL/HIGH/MEDIUM/LOW)
    EventType ENUM (각 이벤트)
  
  Step 2: src/notification/notification_queue.py 확장
    우선순위 큐 구현
    PostgreSQL FOR UPDATE SKIP LOCKED 활용
  
  Step 3: notification_skill.send_notification()
    스킬 구현
    빈도 제한 (5분)
    Circuit Breaker 통합
    웹 알림 동시 발송 (CRITICAL/HIGH)
  
  Step 4: 단위 테스트
    우선순위 정확
    빈도 제한 동작
    CRITICAL 강화 (Circuit Breaker 무시)

검증:
  ☐ 모든 알림 스킬 통해서만
  ☐ 하네스 3 통과 (raw 호출 차단)
```

### 6.3 P4.2: 텔레그램 명령어

```yaml
작업:
  Step 1: src/notification/telegram_commands.py
    
    명령어 13개:
      /status - 시스템 상태
      /positions - 보유 포지션
      /tracking - 추적 종목
      /pending - 매수 대기 박스
      /today - 오늘 거래 내역
      /recent - 최근 7일 거래
      /report <종목> - 리포트 생성
      /stop - 시스템 일시 중지 (안전 모드)
      /resume - 시스템 재개
      /cancel <주문ID> - 주문 취소
      /alerts - 최근 알림 이력
      /settings - 설정 조회
      /help - 명령어 도움말
  
  Step 2: 명령어 핸들러 등록
    텔레그램 봇 라이브러리 (python-telegram-bot)
  
  Step 3: 보안
    authorized_chat_ids만 응답
    무권한 사용자 무시
    권한 시도 audit_logs 기록
  
  Step 4: 단위 테스트

검증:
  ☐ 13개 명령어 모두 동작
  ☐ 권한 검증 정확
  ☐ 응답 메시지 형식 일관
```

### 6.4 P4.3: 일일 마감 알림

```yaml
작업:
  Step 1: src/notification/daily_summary.py
    매일 15:30 트리거
    데이터 수집:
      - 오늘 손익
      - 거래 내역 (매수/매도)
      - 추적 종목 변화
      - 내일 주목 이벤트
    
    포맷팅
    텔레그램 발송
  
  Step 2: 스케줄러 등록
    AsyncIOScheduler 또는 cron-like
  
  Step 3: 단위 테스트
    데이터 수집 정확
    포맷 일관

검증:
  ☐ 15:30 자동 발송
  ☐ 거래 없는 날도 발송
  ☐ 데이터 정확
```

### 6.5 P4.4: 월 1회 리뷰

```yaml
작업:
  Step 1: src/notification/monthly_review.py
    매월 1일 (또는 첫 거래일) 09:00 트리거
    
    ABC 혼합 구조:
      ■ 전체 현황 (개수)
      ⚠️ 주의 필요 (이탈, 정체, 만료)
      ● 상태별 분류 (리스트)
      📋 전체 목록 (토글)
  
  Step 2: 데이터 집계
    monthly_reviews 테이블 저장
  
  Step 3: 발송 + 알림 이력

검증:
  ☐ 매월 1일 자동 발송
  ☐ ABC 구조 정확
  ☐ 60일+ 정체 강조
```

### 6.6 Phase 4 완료 검증

```yaml
체크리스트:
  ☐ P4.1 알림 등급 시스템 ✓
  ☐ P4.2 텔레그램 명령어 13개 ✓
  ☐ P4.3 일일 마감 알림 ✓
  ☐ P4.4 월 1회 리뷰 ✓

자동 검증:
  ☐ pytest tests/v71/test_notifications/ 통과
  ☐ 하네스 3, 7 통과

수동 검증:
  ☐ 24시간 운영 후 알림 정확
  ☐ 텔레그램 명령어 응답 정확

기록:
  ☐ WORK_LOG.md 업데이트
  ☐ Git tag: v71-phase4-complete
```

---

## §7. Phase 5: 웹 대시보드

### 7.1 Phase 5 개요

```yaml
목적:
  웹 백엔드 (FastAPI) + 인증 (JWT + 2FA)
  Claude Design UI 통합

기간: 5~10일

병렬 작업 가능:
  - 백엔드 API: Claude Code
  - UI 디자인: Claude Design (사용자)
  - UI 통합: Claude Code
```

### 7.2 P5.1: 백엔드 API

```yaml
작업:
  Step 1: src/web/main.py - FastAPI 앱 초기화
  
  Step 2: src/web/api/ - REST API 엔드포인트
    참조: 09_API_SPEC.md (작성 예정)
    
    주요 엔드포인트:
      POST /api/v71/auth/login
      POST /api/v71/auth/totp/verify
      POST /api/v71/auth/refresh
      
      GET /api/v71/stocks/tracked
      POST /api/v71/stocks/track
      
      GET /api/v71/boxes
      POST /api/v71/boxes
      PATCH /api/v71/boxes/{id}
      DELETE /api/v71/boxes/{id}
      
      GET /api/v71/positions
      
      POST /api/v71/reports/request
      GET /api/v71/reports/{id}
      
      GET /api/v71/notifications
      
      GET /api/v71/settings
      PATCH /api/v71/settings
  
  Step 3: src/web/websocket/live_feed.py
    실시간 데이터 push
    포지션 변동
    박스 진입 임박

검증:
  ☐ 모든 엔드포인트 동작
  ☐ OpenAPI 스키마 완전
  ☐ pytest 통과
```

### 7.3 P5.2: 인증 시스템

```yaml
작업:
  Step 1: src/web/auth/jwt_handler.py
    JWT 발급/검증
    1시간 access, 24시간 refresh
  
  Step 2: src/web/auth/totp.py
    Google Authenticator 호환
    pyotp 라이브러리
  
  Step 3: src/web/auth/login.py
    로그인 + 2FA 검증
    세션 생성 (user_sessions 테이블)
  
  Step 4: src/web/auth/middleware.py
    JWT 검증 미들웨어
    30분 비활성 자동 로그아웃
    새 IP 즉시 알림

검증:
  ☐ Security Reviewer Agent 검증
  ☐ 침투 테스트 시나리오
```

### 7.4 P5.3: Claude Design UI 작업

```yaml
작업 (사용자가 Claude Design에서 진행):
  
  Step 1: 10_UI_GUIDE.md 작성 (별도 문서)
    백엔드 PRD 기반
    화면별 명세
    인터랙션 정의
  
  Step 2: Claude Design에 입력
    사용자가 직접 진행
    프롬프트 + 가이드 첨부
  
  Step 3: Claude Design 결과물
    React 컴포넌트
    Tailwind + shadcn/ui
    인터랙션 시제품

기간: 사용자 페이스에 따라 (3~7일)
```

### 7.5 P5.4: UI 통합

```yaml
작업:
  Step 1: Claude Design 결과 받음
    React 컴포넌트 + 스타일
  
  Step 2: src/web/static/ 또는 별도 frontend/
    빌드 스크립트
    환경 변수 설정
  
  Step 3: 백엔드 API 연결
    fetch/axios 클라이언트
    인증 토큰 처리
  
  Step 4: 통합 테스트
    로그인 플로우
    박스 등록 플로우
    리포트 생성 플로우

검증:
  ☐ E2E 테스트 통과
  ☐ 보안 검증 (XSS, CSRF)
```

### 7.6 Phase 5 완료 검증

```yaml
체크리스트:
  ☐ 백엔드 API 완성
  ☐ 인증 시스템 (JWT + 2FA)
  ☐ Claude Design UI 완성
  ☐ 통합 완료

기록:
  ☐ Git tag: v71-phase5-complete
```

---

## §8. Phase 6: 리포트 시스템

### 8.1 Phase 6 개요

```yaml
참조: 11_REPORTING.md (작성 예정)

목적:
  On-Demand 종목 리포트
  Claude Opus 4.7 활용
  PDF/Excel 다운로드

기간: 3~5일
```

### 8.2 P6.1~P6.3 작업

```yaml
P6.1: src/core/v71/report/data_collector.py
  키움 API 시세, 재무
  DART API 공시
  네이버 뉴스 API
  데이터 정제

P6.2: src/core/v71/report/claude_api_client.py
  Anthropic API 클라이언트
  Claude Opus 4.7 호출
  PART 1 (이야기) + PART 2 (객관 팩트) 분리 호출
  토큰 사용량 추적

P6.3: src/core/v71/report/report_generator.py
  데이터 수집 → AI 호출 → DB 저장
  비동기 작업 (몇 분 소요)
  진행 상황 알림

P6.4: src/core/v71/report/exporters.py
  PDF 생성 (reportlab)
  Excel 생성 (openpyxl)
  스타일링

검증:
  ☐ 샘플 종목으로 리포트 생성
  ☐ PART 1/2 품질 확인
  ☐ PDF/Excel 정상

기록:
  ☐ Git tag: v71-phase6-complete
```

---

## §9. Phase 7: 통합 테스트 및 배포

### 9.1 Phase 7 개요

```yaml
목적:
  V7.1 완전 검증 후 실거래 운영

기간: 5~10일
```

### 9.2 P7.1: 페이퍼 트레이드

```yaml
작업:
  Step 1: 실시간 시장 데이터로 검증
    실제 매매 안 함 (Mock 주문)
    1~2주 운영
  
  Step 2: 시나리오 검증
    박스 진입 → 매수 (Mock)
    분할 익절 +5%, +10%
    손절
    수동 거래 시나리오 A/B/C/D
    VI 발동 처리
    WebSocket 끊김 복구
    시스템 재시작 복구
  
  Step 3: 메트릭 수집
    NFR1 (시세 지연, 매수 지연)
    알림 지연
    DB 쿼리 성능
  
  Step 4: 이슈 발견 시
    핫픽스
    재테스트

검증:
  ☐ 1~2주 안정 운영
  ☐ 모든 시나리오 정상
  ☐ NFR1 통과 (지연 < 1초/5초)
```

### 9.3 P7.2: AWS 배포

```yaml
작업:
  Step 1: AWS Lightsail 인스턴스
    Ubuntu 22.04
    적절한 사양 (vCPU 2, RAM 4GB+)
  
  Step 2: 환경 구성
    Python 3.11
    PostgreSQL 클라이언트
    Nginx + Cloudflare
    Let's Encrypt 인증서
  
  Step 3: 코드 배포
    git clone (v71-development 브랜치)
    또는 git checkout v71
  
  Step 4: 환경 변수
    .env 설정
    실제 키움 API 키 (실거래)
  
  Step 5: DB 마이그레이션
    Supabase에 V7.1 마이그레이션 UP
  
  Step 6: systemd 서비스
    kstock-v71.service
    kstock-v71-web.service
  
  Step 7: Nginx + SSL
    리버스 프록시
    HTTPS 강제

검증:
  ☐ 시스템 정상 부팅
  ☐ 웹 대시보드 접속
  ☐ 텔레그램 봇 응답
```

### 9.4 P7.3: 점진적 활성화

```yaml
작업:
  Step 1: 모든 Feature Flag OFF로 시작
    V7.1 코드 비활성
    V7.0 인프라만 (또는 안전 모드)
  
  Step 2: 단계별 활성화
    Day 1: v71.box_system ON
      - 박스 등록 가능
      - 진입 감지 모니터링
      - 매수 실행 안 함 (Mock 모드)
    
    Day 2: 매수 실행 활성화
      - 작은 비중부터 (5% 박스)
      - 1~2일 관찰
    
    Day 3~5: 박스 비중 증가
      - 사용자 판단으로
      - 문제 없으면 정상 운영
    
    Day 6: 알림 시스템 정상화
      - 모든 알림 활성화
    
    Day 7~14: 안정화 관찰
  
  Step 3: 문제 발생 시 즉시 비활성화
    Feature Flag OFF
    이슈 분석
    핫픽스 후 재활성화

검증:
  ☐ 2주 안정 운영
  ☐ 사용자 만족도
  ☐ 시스템 안정성

기록:
  ☐ Git tag: v71-production
  ☐ V7.1 정식 운영 시작
```

### 9.5 Phase 7 완료 검증

```yaml
최종 체크리스트:
  ☐ 모든 거래 룰 (02_TRADING_RULES.md) 정확
  ☐ NFR 모두 충족
  ☐ 헌법 5원칙 준수
  ☐ 에이전트 5개 검증 통과
  ☐ 스킬 8개 정상 동작
  ☐ 하네스 7개 통과
  ☐ 페이퍼 트레이드 1~2주
  ☐ 실거래 1~2주 안정
  ☐ 사용자 인수 테스트 완료

기록:
  ☐ V7.1 정식 운영
  ☐ V7.0 코드 deprecation 마킹
  ☐ 6개월 후 V7.0 코드 완전 삭제 검토
```

---

## §10. Feature Flag 전략

### 10.1 Flag 정의

```yaml
config/feature_flags.yaml:
  v71:
    # 거래 시스템
    box_system: false               # 박스 진입 감지 + 매수 실행
    exit_system: false              # 청산 (손절/익절/TS)
    reconciliation_v71: false       # 수동 거래 시나리오 처리
    vi_monitor: false               # VI 처리
    restart_recovery: false         # 시스템 재시작 복구
    
    # 알림
    notification_v71: false         # V7.1 알림 등급 시스템
    daily_summary: false            # 일일 마감 알림
    monthly_review: false           # 월 1회 리뷰
    telegram_commands_v71: false    # 13개 명령어
    
    # 웹
    web_dashboard: false            # 웹 대시보드
    
    # 리포트
    reporting: false                # On-Demand 리포트
    
    # 보안
    two_factor_auth: false          # 2FA
    audit_logging: false            # 감사 로그
```

### 10.2 활성화 순서

```yaml
초기 활성화 (Phase 7 Day 1):
  v71.box_system (Mock 모드)
  v71.exit_system (Mock 모드)
  v71.notification_v71 (모든 알림)
  v71.audit_logging

검증 후 활성화 (Day 2~3):
  v71.box_system (실거래)
  v71.exit_system (실거래)

전체 활성화 (Day 4~7):
  v71.reconciliation_v71
  v71.vi_monitor
  v71.restart_recovery
  v71.daily_summary
  v71.monthly_review
  v71.telegram_commands_v71
  v71.web_dashboard
  v71.reporting
  v71.two_factor_auth
```

### 10.3 비활성화 시나리오

```yaml
시나리오 1: 단일 모듈 문제
  예: VI 처리 오류
  Flag: v71.vi_monitor → false
  영향: VI 처리만 비활성, 다른 거래 정상

시나리오 2: 거래 룰 문제
  예: 청산 로직 버그
  Flag: v71.exit_system → false
  영향: V7.1 청산 비활성, 사용자 수동 청산

시나리오 3: 전체 비활성화 (긴급)
  방법: 모든 v71.* Flag → false
  영향: V7.1 코드 완전 비활성
  대안: 사용자 수동 운영
  결과: 시스템 다운 아님 (헌법 4)
```

---

## §11. 롤백 계획

### 11.1 Phase별 롤백

```yaml
Phase 1 (인프라 정리) 후 롤백:
  방법:
    git checkout v7.0-final-stable
    또는 git revert
  
  영향:
    삭제된 V6/V7 코드 복원
    백테스트 복원
  
  주의:
    DB 변경 없음 (마이그레이션 안 함)
    빠른 롤백 가능

Phase 2 (V7.1 골격) 후 롤백:
  방법:
    git revert
    DB 마이그레이션 DOWN 실행
  
  영향:
    V7.1 디렉토리 제거
    DB 신규 테이블 제거

Phase 3 (거래 룰) 후 롤백:
  방법:
    Feature Flag 모두 OFF
    코드는 유지 (다음 시도용)
  
  영향:
    V7.1 코드 비활성
    V7.0 인프라만 동작
  
  주의:
    이미 V6/V7 신호 시스템 삭제됨
    완전 롤백 불가 (Phase 1 영향)

Phase 7 (운영 시작) 후 롤백:
  방법:
    Feature Flag 즉시 OFF
    트러블슈팅
    필요 시 git revert
  
  영향:
    V7.1 비활성화
    실거래 영향 최소화
```

### 11.2 DB 롤백

```yaml
신규 테이블:
  마이그레이션 DOWN 실행
  DROP TABLE 안전

기존 테이블 확장:
  새 컬럼 NULL 허용 + DEFAULT
  롤백 시 컬럼 무시 (DROP 안 함)
  6개월 후 별도 마이그레이션으로 정리

데이터 손실 방지:
  positions 등 거래 데이터:
    원천 보존
    V7.0 데이터 + V7.1 데이터 모두 유지
    사용자가 어느 쪽으로 보든 가능
```

### 11.3 핫픽스 절차

```yaml
긴급 상황 발생 시:
  
  Step 1: Feature Flag 즉시 OFF
    영향 범위 최소화
    ssh로 서버 접속
    config/feature_flags.yaml 수정
    systemctl restart kstock-v71
  
  Step 2: 텔레그램으로 사용자 통보
    "긴급 비활성화: [사유]"
    "수동 운영으로 전환 필요"
  
  Step 3: 이슈 분석
    로그 확인 (system_events)
    DB 상태 확인
    재현 시도
  
  Step 4: 핫픽스
    버그 수정
    단위 테스트 추가
    개발 환경 검증
  
  Step 5: 배포
    git push
    서버 git pull
    systemctl restart
  
  Step 6: 점진 재활성화
    Feature Flag ON
    24시간 모니터링
```

---

## §12. 데이터 마이그레이션

### 12.1 V7.0 → V7.1 데이터 이전

```yaml
대상:
  현재 운영 중인 추적 종목 + 보유 포지션

전제:
  V7.0 운영 중인 시점 (Phase 7 시작)
  실거래 데이터 보존

작업:
  Step 1: V7.0 데이터 추출
    현재 추적 중 종목 (V7.0 테이블)
    현재 보유 포지션 (V7.0 테이블)
    미체결 주문
  
  Step 2: V7.1 형식으로 변환
    추적 종목:
      → tracked_stocks (path_type 기본값 결정 필요)
      → status: 기존 상태에 매핑
    
    보유 포지션:
      → positions (V7.1 확장 컬럼)
      → source: SYSTEM_A 또는 MANUAL (구분 필요)
      → 평단가 그대로
      → ts_base_price 계산 (현재 최고가 기록)
    
    박스:
      → V7.1에는 박스 개념 신규
      → V7.0 매수가 ± 5% 박스로 자동 생성? (사용자 결정)
      → 또는 사용자가 직접 박스 신규 등록
  
  Step 3: V7.1 데이터 적재
    INSERT 스크립트
    트랜잭션으로 안전하게
  
  Step 4: 검증
    수량/평단가 일치
    상태 정합성
    
  Step 5: V7.0 데이터 보존
    삭제 안 함
    archive 마킹
    6개월 후 별도 백업 후 삭제
```

### 12.2 사용자 결정 사항

```yaml
결정 1: V7.0 추적 종목 → V7.1 path_type
  옵션 A: 모두 PATH_A로 (단타)
  옵션 B: 사용자가 종목별 선택
  옵션 C: 모두 보존 (수동 박스 설정 후 매핑)
  
  → Phase 7 시작 전 사용자 결정 필요

결정 2: V7.0 포지션 → V7.1 source
  V7.0이 자동 매수한 것: SYSTEM_A
  V7.0이 인지하던 수동 매수: MANUAL
  구분 정보 부족 시: 사용자 분류

결정 3: V7.0 박스 데이터 부재
  V7.0은 박스 개념 없음
  V7.1 신규 박스 등록 필요
  보유 포지션의 경우:
    옵션 A: 박스 자동 생성 (매수가 -2% ~ +2%)
    옵션 B: 사용자 수동 설정
    → 옵션 B 권장 (사용자 의도 반영)
```

### 12.3 Big Bang vs 점진 이전

```yaml
Big Bang (한 번에):
  방식: V7.0 종료 → V7.1 시작
  장점: 명확
  단점: 다운타임, 위험

점진 이전 (권장):
  방식:
    Step 1: V7.1 신규 종목만 추적
    Step 2: V7.0 종목 자연 종료 대기 (청산되면 V7.1 재등록)
    Step 3: 1~2개월 후 모두 V7.1
  
  장점:
    다운타임 없음
    리스크 분산
    사용자 적응 시간

  단점:
    이중 운영 기간 (혼란 가능)
    
  대응:
    명확한 표시 (대시보드에 V7.0/V7.1 구분)
    사용자에게 매일 진행 상황 알림
```

---

## 부록 A: 진행 상황 추적

### A.1 WORK_LOG.md 형식

```markdown
# V7.1 작업 로그

## 2026-04-25
### 완료
- [P0.1] 전체 백업 완료 (Git tag v7.0-final-stable)
- [P0.2] 개발 환경 분리 완료
- [P0.3] Feature Flag 인프라 구축 완료

### 진행 중
- [P0.4] 자동 검증 도구 설치 (50%)

### 차단됨
- 없음

## 2026-04-26
### 완료
- [P0.4] 자동 검증 도구 설치 완료
- [P1.1] OpenClaw 정리 완료

### 진행 중
- [P1.2] 백테스트 시스템 삭제 (시작)

### 이슈
- 백테스트 모듈이 indicator_library를 import하고 있음
- → 의존성 추적 후 안전하게 제거 예정
```

### A.2 Phase 완료 시 git tag

```bash
# Phase 1 완료
git add .
git commit -m "Phase 1 complete: infrastructure cleanup"
git tag v71-phase1-complete

# Phase 2 완료
git tag v71-phase2-complete

# ... 각 Phase별

# 최종 운영 시작
git tag v71-production
```

---

## 부록 B: 미정 사항

```yaml
B.1 V7.0 → V7.1 데이터 마이그레이션 정확한 방식:
  사용자 결정 (§12.2)
  Phase 7 시작 전 확정

B.2 V7.0 코드 완전 삭제 시점:
  V7.1 안정 운영 6개월 후?
  운영 데이터로 결정

B.3 페이퍼 트레이드 환경:
  Mock 주문 라이브러리 선택
  키움 모의투자 API 활용 가능?

B.4 Phase 5 UI 작업 일정:
  사용자 페이스에 따라
  병렬 작업 vs 순차 작업

B.5 BTC 시스템 처리:
  V7.1과 별개
  완전 폐기 / 보관 / 재활용 결정 필요
```

---

*이 문서는 V7.0 → V7.1 마이그레이션의 단일 진실 원천입니다.*  
*각 Phase 완료 시 검증 통과 필수.*  
*문제 발생 시 §11 롤백 계획 즉시 실행.*

*최종 업데이트: 2026-04-25*
*충돌 금지 원칙(헌법 3) 절대 준수*
