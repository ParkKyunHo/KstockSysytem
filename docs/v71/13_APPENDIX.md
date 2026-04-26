# V7.1 부록 (Appendix)

> 이 문서는 V7.1 PRD 작성 과정의 **결정 이력, 미정 사항, 용어집**을 정리합니다.
> 
> 작업 진행 중 참고하는 보조 문서입니다.

---

## 목차

- [§0. 결정 이력 요약](#0-결정-이력-요약)
- [§1. 헌법 5원칙 출처](#1-헌법-5원칙-출처)
- [§2. 핵심 결정 매트릭스](#2-핵심-결정-매트릭스)
- [§3. 미정 사항 통합](#3-미정-사항-통합)
- [§4. 용어집](#4-용어집)
- [§5. PRD 문서 매핑](#5-prd-문서-매핑)
- [§6. 변경 이력](#6-변경-이력)

---

## §0. 결정 이력 요약

### 0.1 V7.1 시작 배경

```yaml
시점: 2026-03 ~ 2026-04
배경:
  - V7.0 (Purple-ReAbs) 8년 운영 후
  - 사용자 박균호의 매매 스타일 변화
  - 돌파 데이트레이딩 → 박스 기반 눌림/돌파
  - 자동 종목 선별의 한계
  - 신호 시스템 복잡도 증가

핵심 통찰:
  "사용자가 정의한 박스 구간을, 시스템이 인내심 있게 지키다가 정확히 포착한다"
  → V7.1 철학으로 승화
```

### 0.2 V7.0 vs V7.1

```yaml
V7.0 (Purple-ReAbs):
  - 시스템이 종목 선별 (조건검색, 5필터)
  - 신호 기반 자동 매수 (Dual-Pass)
  - 복잡한 코드 베이스 (30,000+ 줄)
  - 테스트 어려움
  - 백테스트 의존

V7.1 (Box-Based):
  - 사용자가 종목 선별 (HTS)
  - 박스 정의 → 시스템 모니터링
  - 단순한 룰 (눌림/돌파)
  - 작은 모듈 다수
  - 페이퍼 트레이드 + 실거래 검증
```

### 0.3 17세션+ 누적 결정

```yaml
세션 1~5: 거래 룰 기본 정립
  - 박스 시스템 정의
  - 손절/익절/TS 구조
  - 평단가 관리

세션 6~10: 거래 룰 심화
  - 수동 거래 시나리오 A/B/C/D
  - VI 처리
  - 시스템 재시작 복구

세션 11~13: 운영 시스템
  - 알림 시스템 (CRITICAL/HIGH/MEDIUM/LOW)
  - 텔레그램 명령어 13개
  - 일일/월별 리포트

세션 14~17: 보안 + UI
  - 2FA, JWT, 자동 로그아웃
  - 웹 대시보드 설계
  - 리포트 시스템 (Claude Opus 4.7)

세션 18+: PRD 통합
  - 13개 문서 작성
  - 단일 진실 원천 구축
```

---

## §1. 헌법 5원칙 출처

V7.1의 모든 설계 결정의 절대 기준입니다.

### 원칙 1: 사용자 판단 불가침

```yaml
정의:
  사용자가 정의한 박스, 비중, 손절은 절대적
  시스템은 룰대로 실행만
  자동 추천 코드 없음

출처:
  세션 5에서 사용자가 명시적으로 제시
  "내가 결정하면 시스템은 그대로 실행. 추천 안 함"

적용 위치:
  - 02_TRADING_RULES.md §3 (박스 설정)
  - 04_ARCHITECTURE.md §2.2
  - 09_API_SPEC.md (자동 추천 API 없음)
  - 10_UI_GUIDE.md §0.1

위반 신호:
  - "AI가 추천하는 박스" 같은 기능
  - 자동 손절선 변경
  - 종목 자동 선별

위반 시 차단: V71 Architect Agent
```

### 원칙 2: NFR1 최우선

```yaml
정의:
  Non-Functional Requirement 1
  박스 진입 절대 놓치지 않음
  시세 → 매수 지연 < 1초

출처:
  세션 8 사용자 강조
  "진입 1번 놓치면 그 종목 끝"

적용 위치:
  - 02_TRADING_RULES.md §2.4 (시세 모니터링)
  - 02_TRADING_RULES.md §8 (WebSocket 끊김)
  - 04_ARCHITECTURE.md §6 (동시성)

구현:
  - WebSocket 우선
  - REST 폴링 보조 (5초)
  - 봉 완성 즉시 판정
  - 매수 즉시 발송

위반 신호:
  - 큐에 쌓이는 매수 (지연)
  - 동기 처리 (블로킹)
  - 폴링만 사용
```

### 원칙 3: 충돌 금지 (Coexistence Rule)

```yaml
정의:
  V7.0 인프라 보존
  V7.1 신규는 격리 패키지 (src/core/v71/)
  V7.0 직접 수정 최소화
  → 안전한 점진 전환

출처:
  세션 11 사용자 강력 강조
  "V7.0 망가뜨리면 안 됨"
  "둘이 양립 가능해야 함"

적용 위치:
  - 04_ARCHITECTURE.md §0.1 (격리 원칙)
  - 05_MIGRATION_PLAN.md §0.1
  - 08_HARNESS_SPEC.md §1, §2

자동 강제:
  - 하네스 1: Naming Collision
  - 하네스 2: Dependency Cycle
  - 하네스 6: Dead Code

핵심 룰:
  - V7.1 → V7.0 인프라 (단방향, OK)
  - V7.0 → V7.1 (금지)
  - V71 접두사 또는 v71/ 패키지
```

### 원칙 4: 시스템 계속 운영

```yaml
정의:
  자동 정지 코드 없음
  WebSocket 끊김에도 계속 시도
  보안 사고에도 안전 모드만

출처:
  세션 13 사용자 결정
  "자동 정지하면 사용자 자리 비울 때 위험"
  "복구 가능한 문제는 알림으로"

적용 위치:
  - 02_TRADING_RULES.md §8.4 (긴급정지 없음)
  - 02_TRADING_RULES.md §13.2 (자동 정지 안 함)
  - 12_SECURITY.md §10 (안전 모드)

원칙적 예외:
  - 사용자 명시적 안전 모드 (POST /safe_mode)
  - 또는 텔레그램 /stop 명령

위반 신호:
  - sys.exit() 자동 호출
  - 무한 루프 escape
  - 자동 종료 트리거
```

### 원칙 5: 단순함 우선

```yaml
정의:
  복잡한 설계 회피
  필요할 때만 추상화
  명시적 흐름 우선
  Occam's Razor

출처:
  세션 15 V7.0 코드 분석 후
  "V7.0 너무 복잡해서 디버깅 어려움"
  "V7.1은 단순하게"

적용 위치:
  - 04_ARCHITECTURE.md §0.1
  - 02_TRADING_RULES.md §3.7 (VI 봉 그대로)
  - 02_TRADING_RULES.md §11 (블랙스완 감수)

좋은 신호:
  - 작은 모듈 다수
  - 명확한 함수 시그니처
  - 짧은 메서드 (50줄 이내)
  - DRY (스킬 사용)

나쁜 신호:
  - 거대 클래스 (1000줄+)
  - 깊은 상속 (3단 이상)
  - 과도한 디자인 패턴
  - 미래 위한 추상화
```

---

## §2. 핵심 결정 매트릭스

작업 진행 중 가장 자주 참조하는 결정들.

### 2.1 거래 룰 핵심

| 항목 | 결정 | 출처 (PRD) |
|------|------|-----------|
| 손절 단계 1 | 평단가 -5% | §5.1, §5.4 |
| 손절 단계 2 | 평단가 -2% (+5% 청산 후) | §5.1 |
| 손절 단계 3 | 평단가 +4% (+10% 청산 후) | §5.1 |
| 익절 1차 | +5% 도달 시 30% 청산 | §5.2 |
| 익절 2차 | +10% 도달 시 30% 청산 | §5.2 |
| TS 활성화 | +5% 도달 시 | §5.5 |
| TS 청산선 유효 | +10% 청산 후만 | §5.5 |
| ATR 배수 (+10~15%) | 4.0 | §5.6 |
| ATR 배수 (+15~25%) | 3.0 | §5.6 |
| ATR 배수 (+25~40%) | 2.5 | §5.6 |
| ATR 배수 (+40%~) | 2.0 | §5.6 |
| 자동 이탈 (박스 -20%) | EXITED | §2.3 |
| 종목당 한도 | 30% (실제 포지션 기준) | §3.4 |
| 매수 대기 박스 | 한도에서 제외 | §3.4 |
| 경로 B 갭업 한도 | 5% 이상 시 매수 포기 | §4.4 |
| VI 후 갭 한도 | 3% 이상 시 매수 포기 | §10.4 |
| Trend Hold Filter | 폐기 | §5 |
| Max Holding | 무제한 | §5 |
| BasePrice | 매수 후 최고가 (단순화) | §5.5 |

### 2.2 알림 룰 핵심

| 항목 | 결정 | 출처 |
|------|------|------|
| 등급 | CRITICAL/HIGH/MEDIUM/LOW | §9.1 |
| 채널 | 텔레그램 + 웹 (CRITICAL/HIGH) | §9.2 |
| 빈도 제한 | 5분 (CRITICAL은 무시) | §9.5 |
| 일일 마감 | 매일 15:30 | §9.7 |
| 월 1회 리뷰 | 매월 1일 | §9.8 |
| 박스 만료 알림 | 30일 (자동 삭제 X) | §3.6 |
| 텔레그램 명령어 | 13개 | §9 |

### 2.3 시스템 룰 핵심

| 항목 | 결정 | 출처 |
|------|------|------|
| WebSocket Phase 1 재연결 | 5회 지수 백오프 | §8.2 |
| WebSocket Phase 2 재연결 | 5분 고정 무한 | §8.2 |
| REST 폴링 (보조) | 5초 간격 | §8.3 |
| 긴급 정지 | 없음 (헌법 4) | §8.4 |
| 재시작 복구 | 7-Step | §13.1 |
| 미완료 주문 처리 | 모두 취소 (박스 보존) | §13.1 Step 2 |
| 박스 진입 누락 감사 | 매일 자동 | §13.1 Step 5 |

### 2.4 보안 핵심

| 항목 | 결정 | 출처 |
|------|------|------|
| HTTPS | Let's Encrypt 강제 | §2.1 |
| 인증 | JWT + 2FA TOTP | §3.1 |
| Access 토큰 | 1시간 | §3.1 |
| Refresh 토큰 | 24시간 | §3.1 |
| 자동 로그아웃 | 30분 비활성 | §3.5 |
| 새 IP 알림 | 즉시 (CRITICAL) | §3.4 |
| 비밀번호 해시 | bcrypt cost 12 | §3.2 |
| 감사 로그 | 모든 중요 액션 | §7 |
| 텔레그램 chat_id | 화이트리스트만 | §4.3 |
| Cloudflare | DDoS + WAF | §2.3 |

### 2.5 데이터 모델 핵심

| 테이블 | 핵심 결정 | 출처 |
|--------|-----------|------|
| tracked_stocks | path_type 분리 (이중 경로) | §2.1 |
| support_boxes | tracked_stock에 종속 | §2.2 |
| positions | source ENUM (SYSTEM_A/B/MANUAL) | §2.3 |
| trade_events | 모든 이벤트 영구 보존 | §2.4 |
| daily_reports | Claude Opus 4.7 출력 영구 | §4.1 |
| user_sessions | revoked + last_activity_at | §5.2 |
| audit_logs | 6개월+ 보존 | §5.3 |

---

## §3. 미정 사항 통합

각 PRD 문서의 미정 사항을 한곳에 모았습니다. 구현 시 결정 필요.

### 3.1 거래 룰 (02_TRADING_RULES.md)

```yaml
B.1 키움 API client_order_id 지원:
  - 지원 여부 키움 OpenAPI 문서 확인
  - 미지원 시 대안: 시간 + 수량 매핑

B.2 폴링 간격 튜닝:
  - 기본 5초
  - 운영하며 최적화

B.3 차감 수량 소수점 처리:
  - 큰 경로 우선 반올림 (확정)
  - 정확한 알고리즘 코드로 명시

B.4 슬리피지 임계치:
  - 대량 주문 알림 기준
  - 운영 데이터로 결정

B.5 디스크/메모리 임계치:
  - AWS Lightsail 사양에 맞춤
  - 모니터링 후 조정
```

### 3.2 데이터 모델 (03_DATA_MODEL.md)

```yaml
C.1 V7.0 테이블 정확한 이름:
  - V7.0 코드 분석 시 확정
  - 마이그레이션 시 1:1 매핑

C.2 RLS 정책:
  - 1인 시스템이라 단순화
  - 다중 사용자 확장 시 추가

C.3 알림 큐 vs Redis:
  - PostgreSQL 시작
  - 부하 시 Redis 전환

C.4 시세 봉 데이터:
  - DB 미저장 (메모리 캐시)
  - 필요 시 TimescaleDB 검토

C.5 백업 자동화:
  - Supabase 기능 활용
  - 별도 스크립트 필요 시 추가
```

### 3.3 아키텍처 (04_ARCHITECTURE.md)

```yaml
B.1 trading_engine.py 처리:
  - 옵션 1: 대폭 수정
  - 옵션 2: 새 파일 (v71_trading_engine.py)
  - 충돌 금지 원칙으로 결정

B.2 V7.0 위임 모듈 정리 시점:
  - V7.1 검증 후 제거
  - Feature Flag로 안전 전환

B.3 웹 프론트엔드 위치:
  - 별도 리포지토리 vs 모노리포
  - Claude Design 작업 후 결정

B.4 로그 보관 정책:
  - 운영 분석 후 결정
```

### 3.4 마이그레이션 (05_MIGRATION_PLAN.md)

```yaml
B.1 V7.0 → V7.1 데이터 마이그레이션:
  - 정확한 방식 사용자 결정
  - Phase 7 시작 전 확정

B.2 V7.0 코드 완전 삭제 시점:
  - V7.1 안정 운영 6개월 후?
  - 운영 데이터로 결정

B.3 페이퍼 트레이드 환경:
  - Mock 라이브러리 선택
  - 키움 모의투자 활용 가능?

B.4 Phase 5 UI 일정:
  - 사용자 페이스
  - 병렬 vs 순차

B.5 BTC 시스템 처리:
  - 폐기 / 보관 / 재활용 결정
```

### 3.5 에이전트 (06_AGENTS_SPEC.md)

```yaml
B.1 에이전트 구현 방식:
  - sub-agent vs MCP vs 페르소나 프롬프트
  - 가장 단순한 옵션부터 시작

B.2 에이전트 학습 데이터:
  - PRD 전체 컨텍스트
  - 동적 참조 vs 하드코딩

B.3 에이전트 응답 검증:
  - 에이전트도 틀릴 수 있음
  - 최종 결정은 사용자

B.4 에이전트 추가/제거:
  - 운영하며 결정
```

### 3.6 스킬 (07_SKILLS_SPEC.md)

```yaml
B.1 키움 API 정확한 엔드포인트:
  - 구현 시 키움 OpenAPI 문서 참조

B.2 ATR 계산 위치:
  - exit_calc_skill 외부 vs 내부

B.3 시간 모킹:
  - freezegun 사용

B.4 reconciliation 호출 빈도:
  - 5분 vs 사용자 요청
  - 운영 데이터로 결정
```

### 3.7 하네스 (08_HARNESS_SPEC.md)

```yaml
B.1 하네스 도구 선택:
  - 직접 구현 vs 기존 도구
  - pylint/ruff/mypy/vulture/pydeps

B.2 화이트리스트:
  - # noqa 주석 vs 별도 파일

B.3 성능 최적화:
  - 변경 파일만 검사
  - 캐싱
  - 병렬 실행

B.4 하네스 자체 테스트:
  - 메타 테스트 작성
```

### 3.8 API (09_API_SPEC.md)

```yaml
B.1 OpenAPI 스키마:
  - YAML/JSON 자동 생성
  - Swagger UI 통합

B.2 Rate Limit 정확한 값:
  - 운영 데이터로 결정

B.3 캐시 정책:
  - ETag, Last-Modified
  - 종목 검색 캐싱

B.4 GraphQL 검토:
  - REST 충분?
  - 복잡 쿼리 시 검토

B.5 WebSocket 인증 갱신:
  - 연결 중 토큰 만료
```

### 3.9 UI (10_UI_GUIDE.md)

```yaml
C.1 차트 도입:
  - 미니 sparkline 추가?
  - 사용자 결정

C.2 모바일 앱 vs PWA:
  - PWA로 시작

C.3 실시간 업데이트 빈도:
  - 1초 vs 변동 시만

C.4 다국어:
  - 한국어만 시작

C.5 접근성:
  - WCAG AA 목표
```

### 3.10 리포트 (11_REPORTING.md)

```yaml
B.1 Claude API 모델/가격:
  - 사용 시 최신 확인

B.2 DART API 사용법:
  - OpenDART 활용

B.3 네이버 뉴스 API:
  - Rate Limit 확인

B.4 PDF/Excel 디자인:
  - 초안 후 사용자 피드백

B.5 리포트 비교 기능:
  - Phase 2 기능

B.6 다국어:
  - 영어 옵션 (선택)
```

### 3.11 보안 (12_SECURITY.md)

```yaml
B.1 RLS 정책:
  - 다중 사용자 시 추가

B.2 침입 탐지:
  - fail2ban 도입 여부

B.3 로그 중앙화:
  - ELK 또는 CloudWatch

B.4 사용자 행동 분석:
  - 머신러닝 기반

B.5 사이버 보험:
  - 가입 검토
```

---

## §4. 용어집

V7.1 시스템에서 사용하는 핵심 용어 정의.

### 4.1 거래 용어

```yaml
박스 (Box):
  사용자가 정의한 매수 가격 범위
  upper_price (상단) / lower_price (하단)
  position_size_pct (비중) / stop_loss_pct (손절폭)
  strategy_type (PULLBACK or BREAKOUT)

다층 박스 (Multi-Tier Box):
  같은 종목에 여러 개의 박스
  각 박스 독립 (1차, 2차, 3차)
  진입 순서 자유

눌림 (PULLBACK):
  박스 안에서 양봉 형성 시 매수
  경로 A: 직전봉 + 현재봉 모두 양봉 + 박스 내
  경로 B: 일봉 양봉 + 박스 내

돌파 (BREAKOUT):
  박스 상단 돌파 매수
  종가 > 박스 상단 + 양봉 + 정상 시가

이중 경로 (Dual Path):
  같은 종목의 PATH_A + PATH_B 동시 추적
  별도 tracked_stocks 레코드
  별도 포지션

평단가 (Weighted Average Price):
  매수 가중 평균
  매수 시 재계산
  매도 시 변경 없음

손절 단계 (Stop Loss Stages):
  단계 1: 평단가 -5% (매수 ~ +5% 미만)
  단계 2: 평단가 -2% (+5% 청산 후)
  단계 3: 평단가 +4% (+10% 청산 후, 본전 보장)

분할 익절 (Partial Profit Taking):
  +5% 도달: 30% 청산 (1차)
  +10% 도달: 남은 70%의 30% 청산 (2차)
  남은: TS 청산까지

TS (Trailing Stop):
  매수 후 최고가 추적
  청산선: BasePrice - ATR × 배수
  +5% 활성화 (BasePrice 시작)
  +10% 청산 후 청산선 비교 유효

ATR 배수 (ATR Multiplier):
  TS 청산선 계산용
  4.0 → 3.0 → 2.5 → 2.0 (수익률 증가 시 축소)
  단방향 (커지지 않음)

자동 이탈 (Auto Exit):
  박스 -20% 이탈 시 추적 종료
  거래 정지 시 추적 종료
  강제 청산 X (추적만 종료)

VI (Volatility Interruption):
  변동성 완화 장치
  ±10% 가격 변동 시 발동
  2분간 단일가 매매
  V7.1: 발동 중 매매 판정 중단, 해제 후 즉시 재평가

수동 거래 시나리오 (Manual Trade Scenarios):
  A: 시스템 포지션 + 사용자 추가 매수
  B: 시스템 포지션 + 사용자 부분 매도
  C: 추적 중 미진입 + 사용자 매수
  D: 미추적 + 사용자 매수
```

### 4.2 시스템 용어

```yaml
NFR1:
  Non-Functional Requirement 1
  박스 진입 절대 놓치지 않음
  지연 < 1초

NFR3:
  Non-Functional Requirement 3
  시스템 포지션과 수동 포지션 명확 분리
  positions.source 필드

헌법 5원칙:
  1. 사용자 판단 불가침
  2. NFR1 최우선
  3. 충돌 금지
  4. 시스템 계속 운영
  5. 단순함 우선

PRD:
  Product Requirements Document
  본 문서 패키지 (13개 문서)

스킬 (Skill):
  반복 작업의 표준 프로시저
  src/core/v71/skills/ 디렉토리
  하네스가 사용 강제

하네스 (Harness):
  자동 검증 시스템
  pre-commit + CI
  7개 하네스 (충돌, 의존성, 룰, 스키마, Flag, Dead Code, Coverage)

에이전트 (Agent):
  AI 페르소나
  특정 영역 검증 + 가이드
  5개 에이전트 (Architect, Trading Logic, Migration, Security, Test)

Feature Flag:
  V7.1 기능 ON/OFF 스위치
  config/feature_flags.yaml
  점진적 활성화

격리 패키지 (Isolated Package):
  src/core/v71/
  V7.0과 충돌 없이 격리
  V71 접두사 또는 v71/ 패키지

페이퍼 트레이드 (Paper Trade):
  실제 거래 안 하는 시뮬레이션
  Mock 주문
  실거래 전 검증
```

### 4.3 인프라 용어

```yaml
JWT:
  JSON Web Token
  Access (1h) + Refresh (24h)

TOTP:
  Time-based One-Time Password
  Google Authenticator 호환
  RFC 6238

bcrypt:
  비밀번호 해싱 알고리즘
  cost 12 사용

Cloudflare:
  CDN + DDoS 방어 + WAF

Let's Encrypt:
  무료 SSL/TLS 인증서
  90일 자동 갱신

Supabase:
  PostgreSQL 호스팅 서비스
  실시간 + 인증 + 스토리지

키움 OpenAPI:
  키움증권 REST + WebSocket API
  실거래 + 모의투자

DART:
  Data Analysis, Retrieval and Transfer System
  금융감독원 전자공시
  OpenDART API 사용

asyncio:
  Python 비동기 I/O 라이브러리
  V7.1 핵심
```

### 4.4 경로 (Path) 용어

```yaml
PATH_A (경로 A):
  주도주 단타
  3분봉 기준
  눌림: 직전봉 + 현재봉 양봉 + 박스 내
  돌파: 종가 > 박스 상단 + 양봉
  매수: 봉 완성 직후 즉시

PATH_B (경로 B):
  수동 중기
  일봉 기준
  사용자 직접 등록 (HTS 분석 후)
  매수: 익일 09:01
  갭업 5% 이상 시 포기

상태 머신:
  TRACKING (추적만)
    ↓ 박스 추가
  BOX_SET (박스 설정됨, 진입 대기)
    ↓ 매수 실행
  POSITION_OPEN (포지션 보유)
    ↓ 부분 익절
  POSITION_PARTIAL (부분 청산됨)
    ↓ 전량 청산 또는 자동 이탈
  EXITED (청산 완료)
```

### 4.5 알림 용어

```yaml
알림 등급:
  CRITICAL: 즉시 확인 필수 (손절, 시스템 오류)
  HIGH: 중요, 빠른 확인 (매수, 익절, 수동 거래)
  MEDIUM: 정보성 (박스 임박, WebSocket 끊김)
  LOW: 참고 (일일 마감, 헬스 체크)

이벤트 타입:
  BUY_EXECUTED, PROFIT_TAKE_5, PROFIT_TAKE_10
  STOP_LOSS, TS_EXIT, AUTO_EXIT
  MANUAL_BUY_DETECTED, MANUAL_SELL_DETECTED
  VI_TRIGGERED, VI_RESUMED
  WEBSOCKET_DISCONNECTED, SYSTEM_RESTARTED
  NEW_IP_LOGIN

채널:
  TELEGRAM: 메인 (모든 등급)
  WEB: 보조 (CRITICAL/HIGH만, 아이콘)
  BOTH: 둘 다 (CRITICAL/HIGH)
```

---

## §5. PRD 문서 매핑

작업 시 어디를 봐야 하는지 빠른 참조.

### 5.1 작업별 참조 문서

```yaml
거래 룰 구현:
  주: 02_TRADING_RULES.md
  보조: 07_SKILLS_SPEC.md (스킬 사용)
  검증: 06_AGENTS_SPEC.md §2 (Trading Logic Verifier)

데이터베이스 작업:
  주: 03_DATA_MODEL.md
  보조: 05_MIGRATION_PLAN.md §8 (마이그레이션)
  검증: 08_HARNESS_SPEC.md §4 (Schema Validator)

새 모듈 추가:
  주: 04_ARCHITECTURE.md
  보조: 06_AGENTS_SPEC.md §1 (Architect Agent)
  검증: 08_HARNESS_SPEC.md §1, §2

V7.0 코드 정리:
  주: 05_MIGRATION_PLAN.md (Phase 1)
  보조: 06_AGENTS_SPEC.md §3 (Migration Agent)
  검증: 08_HARNESS_SPEC.md §6 (Dead Code)

API 작업:
  주: 09_API_SPEC.md
  보조: 12_SECURITY.md (인증)

UI 작업:
  주: 10_UI_GUIDE.md
  보조: 09_API_SPEC.md (백엔드 연결)

리포트 시스템:
  주: 11_REPORTING.md
  보조: 09_API_SPEC.md §8

보안 코드:
  주: 12_SECURITY.md
  보조: 06_AGENTS_SPEC.md §4 (Security Reviewer)

테스트 작성:
  주: 06_AGENTS_SPEC.md §5 (Test Strategy)
  보조: 07_SKILLS_SPEC.md §8 (test_template)
  검증: 08_HARNESS_SPEC.md §7 (Coverage)
```

### 5.2 결정 사항 빠른 찾기

```yaml
"손절 룰?" → 02_TRADING_RULES.md §5.1
"평단가 계산?" → 02_TRADING_RULES.md §6, 07_SKILLS_SPEC.md §4
"수동 거래?" → 02_TRADING_RULES.md §7
"VI 처리?" → 02_TRADING_RULES.md §10, 07_SKILLS_SPEC.md §5
"재시작 복구?" → 02_TRADING_RULES.md §13
"테이블 구조?" → 03_DATA_MODEL.md
"모듈 위치?" → 04_ARCHITECTURE.md §1.2
"V7.0 어떻게?" → 05_MIGRATION_PLAN.md
"에이전트 호출?" → 06_AGENTS_SPEC.md
"스킬 사용?" → 07_SKILLS_SPEC.md
"하네스 통과?" → 08_HARNESS_SPEC.md
"API 명세?" → 09_API_SPEC.md
"UI 어떻게?" → 10_UI_GUIDE.md
"리포트 작성?" → 11_REPORTING.md
"보안 정책?" → 12_SECURITY.md
"용어?" → 13_APPENDIX.md §4
"미정?" → 13_APPENDIX.md §3
```

### 5.3 의존성

```yaml
독립적 (먼저 읽어도 OK):
  02_TRADING_RULES.md  ← 핵심 룰
  04_ARCHITECTURE.md   ← 구조
  03_DATA_MODEL.md     ← 데이터

거래 룰 의존:
  07_SKILLS_SPEC.md  ← 02 참조
  09_API_SPEC.md      ← 02, 03 참조

아키텍처 의존:
  04_ARCHITECTURE.md  ← 03 참조
  05_MIGRATION_PLAN.md ← 04 참조

UI 의존:
  10_UI_GUIDE.md  ← 09 (API), 02 (룰) 참조

검증 도구:
  06_AGENTS_SPEC.md   ← 모든 PRD 참조
  08_HARNESS_SPEC.md  ← 02, 04 참조

부록:
  13_APPENDIX.md      ← 모든 PRD 통합 정리

통합:
  01_PRD_MAIN.md      ← 모든 PRD 요약 (마지막 작성)
```

---

## §6. 변경 이력

### 6.1 PRD 작성 일지

```yaml
2026-04-23:
  세션 18: PRD 통합 작업 시작
  작성: README.md, 00_CLAUDE_CODE_GENERATION_PROMPT.md

2026-04-24:
  세션 19: 거래 룰 정리
  작성: 02_TRADING_RULES.md §0~§5

2026-04-25 (오전):
  세션 20: 거래 룰 완성
  작성: 02_TRADING_RULES.md §6~§13 + 부록
  
  세션 21: 데이터 + 아키텍처
  작성: 03_DATA_MODEL.md, 04_ARCHITECTURE.md

2026-04-25 (오후):
  세션 22: 마이그레이션 + 에이전트
  작성: 05_MIGRATION_PLAN.md, 06_AGENTS_SPEC.md
  
  세션 23: 스킬 + 하네스
  작성: 07_SKILLS_SPEC.md, 08_HARNESS_SPEC.md
  
  세션 24: API + UI
  작성: 09_API_SPEC.md, 10_UI_GUIDE.md
  
  세션 25 (현재): 리포트 + 보안 + 부록
  작성: 11_REPORTING.md, 12_SECURITY.md, 13_APPENDIX.md

다음 세션:
  세션 26: PRD 메인 통합
  작성: 01_PRD_MAIN.md (마지막)
  
  + 마무리:
    - 개발 Phase 로드맵 확인
    - BTC 시스템 처리 결정
    - PRD 패키지 최종 검수
```

### 6.2 PRD 변경 이력 (Post-Initial)

> PRD 패키지 작성 완료(2026-04-25) 후 발생한 모든 변경 사항.
> 변경 시 §6.3 절차 준수 필수.

```yaml
변경 #1: 2026-04-26 (Phase 3 P3.1 시작 시점)
  사유:
    경로 B (일봉) 익일 09:01 매수가 시초 VI / 단일가 매매 / API 장애로
    미체결될 가능성. 사용자가 정의한 박스 진입을 1회의 09:01 실패만으로
    영구 포기하는 것은 헌법 1 (사용자 판단 불가침) + NFR1 (진입 놓치지 않음)
    원칙에 부합하지 않음.
  
  결정:
    경로 B 매수에 09:05 시장가 fallback 안전장치 추가.
    
  영향 문서:
    - 02_TRADING_RULES.md §3.10 (PATH_B PULLBACK 룰)
    - 02_TRADING_RULES.md §3.11 (PATH_B BREAKOUT 룰)
    - 02_TRADING_RULES.md §10.9 (시초 VI 시나리오, 신규)
    - 07_SKILLS_SPEC.md §2 (box_entry_skill EntryDecision에 fallback 메타데이터)
    - V71Constants (PATH_B_PRIMARY_BUY_TIME_HHMM, PATH_B_FALLBACK_BUY_TIME_HHMM,
      PATH_B_FALLBACK_USES_MARKET_ORDER 신규)
  
  영향 안 받는 영역 (보존):
    - 갭업 5% 초과 시 매수 포기 룰 (1차 시점에 그대로 적용)
    - VI 후 일반 갭 3% 룰 (§10.4)
    - 경로 A (3분봉 즉시 매수)는 변경 없음
  
  헌법 5원칙 적합성:
    1. 사용자 판단 불가침: ✓ (사용자 박스 결정 존중, 안전장치는 마무리만)
    2. NFR1: ✓ (진입 1회 더 시도, 4분 지연 허용 범위)
    3. 충돌 금지: ✓ (V7.0 영향 없음, V7.1만 변경)
    4. 시스템 계속 운영: ✓ (기존 동작 보강, 정지 코드 추가 없음)
    5. 단순함: ✓ (5분 한 번만 재시도, 무한 재시도 아님)
  
  버전:
    V7.1.0 (initial) → V7.1.0a (PRD patch, 코드 미구현)
    Phase 3 P3.1 commit 시 V7.1.0a 본격 적용
  
  Git tag (예정): v71-prd-patch-1
```

### 6.3 향후 변경 관리

```yaml
PRD 변경 절차:
  1. 변경 사유 명시
  2. 영향 범위 분석
  3. 관련 문서 모두 갱신
  4. 본 부록 §6.2 (변경 이력) 업데이트
  5. Git commit + tag

버전 관리:
  현재: V7.1.0a (initial + PRD patch #1)
  향후:
    V7.1.1: 룰 미세 조정
    V7.1.2: ...
    V7.2: 큰 변경

문서 동기화:
  교차 참조 갱신
  용어 일관성
  결정 매트릭스 (§2) 업데이트
```

---

## 부록 A: PRD 검수 체크리스트

배포 전 PRD 패키지 최종 검수.

```yaml
일관성:
  ☐ 헌법 5원칙 모든 문서에 반영
  ☐ 용어 일관 (§4 용어집 기준)
  ☐ 결정 사항 매트릭스 (§2) 일치
  ☐ 교차 참조 정확

완전성:
  ☐ 13개 문서 모두 작성 완료
  ☐ README + 00_CLAUDE_CODE_GENERATION_PROMPT 포함
  ☐ 미정 사항 (§3) 모두 식별
  ☐ 향후 결정 시점 명시

가독성:
  ☐ 목차 명확
  ☐ 적절한 헤딩 계층
  ☐ 코드 예시 충분
  ☐ 다이어그램 (텍스트)

실용성:
  ☐ Claude Code가 그대로 구현 가능
  ☐ Claude Design이 UI 작업 가능
  ☐ 에이전트가 검증 가능
  ☐ 하네스가 자동 강제 가능
```

---

## 부록 B: 작업 단위 추정

```yaml
PRD 작성 (완료):
  총 25 세션 (Claude Desktop)
  세션당 30~120분
  총 약 50~80시간

V7.1 구현 (예상):
  Phase 0~7 총 1~2개월 (1인 풀타임)
  
  Phase 1 (인프라 정리): 3~5일
  Phase 2 (V7.1 골격): 3~5일
  Phase 3 (거래 룰): 10~15일 ★ 가장 큼
  Phase 4 (알림): 2~3일
  Phase 5 (웹): 5~10일
  Phase 6 (리포트): 3~5일
  Phase 7 (테스트+배포): 5~10일

총: 31~53일 (1~2개월)

병렬 작업 가능:
  Phase 3 완료 후
  Phase 4, 5, 6 병렬 → 시간 단축 가능
```

---

*이 문서는 V7.1 PRD의 부록입니다.*  
*결정 이력 + 미정 사항 + 용어집을 한곳에 모음.*  
*PRD 작업 진행 중 자주 참조.*

*최종 업데이트: 2026-04-25*
