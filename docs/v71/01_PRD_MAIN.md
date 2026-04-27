# V7.1 PRD Main (Product Requirements Document)

> **K_stock_trading V7.1 - 박스 기반 한국 주식 자동매매 시스템**
> 
> 본 문서는 V7.1 시스템의 **단일 진입점**입니다.
> 
> 15개 문서로 구성된 PRD 패키지의 통합 요약 + 네비게이션을 제공합니다.
> 
> ⚠️ **2026-04-25 PRD Patch #2**: UI 디자인 시스템을 IBM Carbon Design System으로 전환.
> 자세한 내용은 `13_APPENDIX.md` §6.2.X 참조.
>
> ⚠️ **PRD Patch #5 (V7.1.0d, 2026-04-27)**: 키움 REST API 18개 매핑 확정 + orders 테이블 신규 +
> positions.current_price 컬럼 추가 + daily_reports 소프트 삭제 + settings/broker·trading read-only.
> 자세한 내용은 `13_APPENDIX.md` §6.2.Z 참조. 키움 API 매핑 상세는 `KIWOOM_API_ANALYSIS.md` 참조.

---

## 목차

- [§0. V7.1 시스템 개요](#0-v71-시스템-개요)
- [§1. 헌법 5원칙 (절대 기준)](#1-헌법-5원칙-절대-기준)
- [§2. PRD 문서 가이드](#2-prd-문서-가이드)
- [§3. 핵심 거래 룰 요약](#3-핵심-거래-룰-요약)
- [§4. 핵심 의사결정 요약](#4-핵심-의사결정-요약)
- [§5. 시스템 아키텍처 요약](#5-시스템-아키텍처-요약)
- [§6. 개발 Phase 로드맵](#6-개발-phase-로드맵)
- [§7. Claude Code 작업 시작 가이드](#7-claude-code-작업-시작-가이드)
- [§8. Claude Design 작업 가이드](#8-claude-design-작업-가이드)
- [§9. PRD 패키지 사용법](#9-prd-패키지-사용법)
- [§10. 다음 단계](#10-다음-단계)

---

## §0. V7.1 시스템 개요

### 0.1 한 문장 정의

> **사용자가 정의한 박스 구간을, 시스템이 인내심 있게 지키다가 정확히 포착하는 한국 주식 자동매매 시스템.**

### 0.2 시스템 본질

```yaml
사용자: 박균호 (8년 전업 트레이더)
환경:
  - 한국 주식 시장 (KOSPI, KOSDAQ)
  - 키움증권 OpenAPI
  - 1인 운영 시스템
  - 데스크톱 메인 + 모바일 보조
  - HTS와 병행 사용

전략:
  박스 기반 눌림/돌파 매매
  - 사용자가 종목 선별 (HTS 분석)
  - 사용자가 박스 정의 (가격 범위 + 비중 + 손절)
  - 시스템이 진입 타이밍 포착 (자동 매수)
  - 시스템이 룰대로 청산 (분할 익절 + TS + 손절)

차별점 (V7.0 대비):
  - 단순함: 작은 모듈 다수 (V7.0은 거대 trading_engine)
  - 명확성: 사용자 입력 박스 vs 시스템 자동 신호
  - 검증성: 룰 기반 (백테스트 불필요)
  - 안전성: 충돌 금지 + 격리 패키지
```

### 0.3 V7.0과의 관계

```yaml
V7.0 (Purple-ReAbs, 폐기 대상):
  - 시스템이 종목 자동 선별 (조건검색, 5필터)
  - Dual-Pass 신호 시스템
  - 30,000+ 줄 복잡한 코드

V7.1 (Box-Based, 신규):
  - 사용자가 종목 선별
  - 박스 정의 → 시스템 모니터링
  - 단순한 룰 (눌림/돌파)
  - 격리 패키지 (src/core/v71/)

전환:
  V7.0 인프라 보존 (api/, database/, notification/, utils/)
  V7.1 격리 추가 (src/core/v71/)
  Feature Flag로 점진 활성화
  6개월 후 V7.0 제거 검토
```

### 0.4 사용자 시나리오

```yaml
하루 일과:

09:00 (장 시작 전):
  - 텔레그램으로 일일 마감 (전날 15:30) 알림 확인
  - 웹 대시보드 접속 (2FA)
  - 추적 종목 점검

09:00~09:30:
  - HTS로 종목 분석
  - 새 박스 등록 (필요 시)
  - 매수 대기 박스 점검

09:30~15:30 (장중):
  - 텔레그램 알림 받음 (매수, 익절, 손절)
  - 진입 임박 종목 모니터링
  - 필요 시 박스 수정

15:30 (장 마감):
  - 일일 마감 알림 자동 수신
  - 오늘 손익 확인

매월 1일:
  - 월 1회 추적 리뷰 알림 자동 수신
  - 60일+ 정체 종목 검토
  - 박스 만료 처리
```

---

## §1. 헌법 5원칙 (절대 기준)

V7.1의 모든 설계 결정은 이 5원칙에 부합해야 합니다.

```yaml
원칙 1: 사용자 판단 불가침
  사용자가 정의한 박스, 비중, 손절은 절대적
  시스템은 룰대로 실행만
  자동 추천 코드 없음

원칙 2: NFR1 최우선
  박스 진입 절대 놓치지 않음
  시세 → 매수 지연 < 1초
  "진입 1번 놓치면 그 종목 끝"

원칙 3: 충돌 금지 (Coexistence Rule) ★ 핵심
  V7.0 인프라 보존
  V7.1 신규는 격리 패키지 (src/core/v71/)
  V7.0 직접 수정 최소화
  하네스 1, 2, 6이 자동 강제

원칙 4: 시스템 계속 운영
  자동 정지 코드 없음
  WebSocket 끊김에도 계속 시도
  보안 사고에도 안전 모드만

원칙 5: 단순함 우선
  복잡한 설계 회피
  필요할 때만 추상화
  명시적 흐름 우선
  Occam's Razor
```

**위반 시 차단**: 에이전트 (06_AGENTS_SPEC.md) + 하네스 (08_HARNESS_SPEC.md)

---

## §2. PRD 문서 가이드

### 2.1 15개 문서 목록

```
docs/v71/
├── README.md                              # 패키지 진입점 + 사용법
├── 00_CLAUDE_CODE_GENERATION_PROMPT.md   # Claude Code 시작 프롬프트
├── 01_PRD_MAIN.md                         # 본 문서 (통합 요약)
├── 02_TRADING_RULES.md                    # 거래 룰 (가장 중요)
├── 03_DATA_MODEL.md                       # DB 스키마
├── 04_ARCHITECTURE.md                     # 시스템 구조
├── 05_MIGRATION_PLAN.md                   # V7.0 → V7.1 전환
├── 06_AGENTS_SPEC.md                      # AI 에이전트 5개
├── 07_SKILLS_SPEC.md                      # 표준 스킬 8개
├── 08_HARNESS_SPEC.md                     # 자동 검증 7개
├── 09_API_SPEC.md                         # 백엔드 API
├── 10_UI_GUIDE.md                         # ⚠️ DEPRECATED (shadcn/ui 참고용)
├── 10_UI_GUIDE_CARBON.md                  # ★ UI 명세 (Carbon Design System, 실제 구현)
├── 11_REPORTING.md                        # 리포트 시스템 (Claude Opus 4.7)
├── 12_SECURITY.md                         # 보안 정책
└── 13_APPENDIX.md                         # 결정 이력 + 부록
```

### 2.2 문서별 역할

| 문서 | 역할 | 대상 독자 | 분량 |
|------|------|-----------|------|
| README | 진입점 | 모두 | 짧음 |
| 00 | Claude Code 시작 | Claude Code | 중간 |
| **01** | **통합 요약 (본 문서)** | **모두** | **중간** |
| **02** | **거래 룰 (단일 진실)** | **Claude Code** | **매우 김** |
| 03 | DB 스키마 | Claude Code | 김 |
| 04 | 모듈 구조 | Claude Code | 김 |
| 05 | 단계별 작업 계획 | Claude Code | 김 |
| 06 | 검증 페르소나 | Claude Code | 김 |
| 07 | 표준 함수 | Claude Code | 매우 김 |
| 08 | 자동 검증 도구 | Claude Code | 김 |
| 09 | API 명세 | Claude Code + Claude Design | 김 |
| ~~10~~ | ~~UI 명세 (shadcn/ui)~~ ⚠️ DEPRECATED | 참고용 | - |
| **10C** | **UI 명세 (Carbon)** ★ | **Claude Code (Phase 5)** | **매우 김** |
| 11 | 리포트 (AI 활용) | Claude Code | 김 |
| 12 | 보안 정책 | Claude Code | 김 |
| 13 | 결정 이력 + 용어 | 모두 (참고용) | 중간 |

### 2.3 읽기 순서

```yaml
처음 V7.1 PRD를 보는 사람:
  1. README.md (5분)
  2. 01_PRD_MAIN.md (본 문서, 15분)
  3. 02_TRADING_RULES.md §0~§5 (30분, 핵심 룰만)
  4. 04_ARCHITECTURE.md §0~§2 (15분, 구조 개요)
  5. 13_APPENDIX.md §4 (용어집, 필요 시 참조)

Claude Code 작업 시작:
  1. 00_CLAUDE_CODE_GENERATION_PROMPT.md (시작 컨텍스트)
  2. 01_PRD_MAIN.md (전체 그림)
  3. 작업 영역별 해당 문서
     - 거래 룰 작업: 02 + 07
     - DB 작업: 03
     - 새 모듈: 04 + 06
     - V7.0 정리: 05
     - 보안: 12
     - 리포트: 11

Claude Design UI 작업:
  1. 01_PRD_MAIN.md (개요)
  2. 10_UI_GUIDE.md (전체)
  3. 09_API_SPEC.md (백엔드 연결)
  4. 12_SECURITY.md (인증 화면)

Claude Code UI 작업 (Phase 5):
  1. 01_PRD_MAIN.md (개요)
  2. **10_UI_GUIDE_CARBON.md** ★ (Carbon 기준 모든 화면)
  3. 10_UI_GUIDE.md (참고용, 인터랙션 흐름만)
  4. 09_API_SPEC.md (백엔드 연결)
  5. 12_SECURITY.md (인증 화면)

거래 룰 검증:
  - 02_TRADING_RULES.md (단일 진실)
  - 06_AGENTS_SPEC.md §2 (Trading Logic Verifier)
```

---

## §3. 핵심 거래 룰 요약

자세한 내용은 02_TRADING_RULES.md 참조. 본 섹션은 빠른 참조용.

### 3.1 박스 시스템

```yaml
박스 (Box):
  사용자가 정의:
    - upper_price (상단)
    - lower_price (하단)
    - position_size_pct (비중, 종목당 30% 한도)
    - stop_loss_pct (손절폭, 기본 -5%)
    - strategy_type (PULLBACK or BREAKOUT)

다층 박스:
  같은 종목에 여러 박스 가능
  진입 순서 자유 (1차→2차 순 아님)
  각 박스 독립 트리거

자동 처리:
  박스 -20% 이탈 시 추적 종료 (모든 박스 무효화)
  거래 정지 / 상장폐지 위험 시 추적 종료
  강제 청산은 안 함 (사용자가 HTS에서)
```

### 3.2 진입 룰

```yaml
경로 A (PATH_A) - 3분봉 단타:
  눌림 (PULLBACK):
    조건:
      - 직전봉: 양봉 + 박스 내 종가
      - 현재봉: 양봉 + 박스 내 종가
    매수: 봉 완성 직후 즉시
  
  돌파 (BREAKOUT):
    조건:
      - 종가 > 박스 상단
      - 양봉
      - 시가 >= 박스 하단 (정상 돌파, 갭업 제외)
    매수: 봉 완성 직후 즉시

경로 B (PATH_B) - 일봉 중기:
  조건:
    - 일봉 양봉 + 박스 내 종가 (눌림)
    - 또는 일봉 돌파
  매수:
    익일 09:01
    갭업 5% 이상 시 매수 포기

이중 경로:
  같은 종목 PATH_A + PATH_B 동시 추적 가능
  별도 tracked_stocks 레코드
  별도 포지션
```

### 3.3 매수 실행

```yaml
주문 정책:
  지정가 1호가 위 (즉시 체결 노림)
  5초 대기 × 3회 시도
  미체결 시 시장가 전환

부분 체결:
  미체결 수량 재시도
  3회 모두 실패 시 시장가

대량 주문:
  1호가 호가 소진 시 다음 호가로 연속

VI 발동 시:
  단일가 매매 참여 시도
  VI 후 갭 3% 이상 시 매수 포기
```

### 3.4 매수 후 관리 (Stage 5 핵심)

```yaml
손절선 (단방향, 단계별 상향):
  단계 1: 평단가 -5% (매수 ~ +5% 미만)
  단계 2: 평단가 -2% (+5% 청산 후)
  단계 3: 평단가 +4% (+10% 청산 후, 본전 보장)

분할 익절:
  +5% 도달: 30% 청산 (지정가 → 시장가 폴백)
  +10% 도달: 남은 70%의 30% 청산

TS (Trailing Stop):
  +5% 도달: 활성화 (BasePrice = 매수 후 최고가)
  +10% 청산 후: 청산선 비교 유효
  
ATR 배수 (단방향 축소):
  +10~15%: 4.0
  +15~25%: 3.0
  +25~40%: 2.5
  +40%~: 2.0

유효 청산선:
  effective = max(고정 손절, TS 청산선)
  TS 청산선은 +10% 청산 후만 유효

폐기 정책:
  Trend Hold Filter 폐기
  Max Holding 무제한
  자동 청산 안 함 (룰 충족 시만)
```

### 3.5 평단가 관리 (§6 핵심)

```yaml
매수 시 (가중 평균 재계산):
  new_avg = (existing_qty × existing_avg + new_qty × new_price) / new_total_qty
  
  이벤트 리셋 (★ 핵심):
    profit_5_executed = False
    profit_10_executed = False
  
  손절선 재계산 (단계 1 복귀):
    fixed_stop = new_avg × 0.95
  
  TS BasePrice 유지 (변경 없음)
  initial_avg_price 유지

매도 시:
  weighted_avg_price 변경 없음
  total_quantity만 감소
  이벤트 이력 유지 (profit_5_executed True 유지)
```

### 3.6 수동 거래 시나리오 (§7)

```yaml
시나리오 A: 시스템 + 사용자 추가 매수
  → 해당 경로 합산
  → 평단가 재계산 + 이벤트 리셋

시나리오 B: 시스템 + 사용자 부분 매도
  단일 경로: 수량 감소
  이중 경로: 자동 비례 차감 (큰 경로 우선 반올림)
  MANUAL 우선 차감

시나리오 C: 추적 중 미진입 + 사용자 매수
  → 추적 종료 (EXITED)
  → 모든 박스 INVALIDATED
  → MANUAL 포지션 신규 생성

시나리오 D: 미추적 + 사용자 매수
  → MANUAL 포지션 신규
  → tracked_stocks 연결 없음

MANUAL 포지션:
  시스템이 자동 청산 안 함
  사용자가 HTS에서 직접 매도
  매도 감지 시 수량 감소
```

### 3.7 VI 처리 (§10)

```yaml
VI (Volatility Interruption):
  ±10% 변동 시 발동
  2분간 단일가 매매

상태 머신:
  NORMAL → VI_TRIGGERED → VI_RESUMED → NORMAL

VI 발동 중:
  손절/익절 판정 중단
  신규 매수 시 단일가 매매 참여

VI 해제 직후:
  즉시 재평가 (지연 < 1초)
  손절 조건 충족 시 즉시 시장가 매도
  당일 신규 진입 금지 플래그 (vi_recovered_today)

봉 처리:
  VI 포함 봉 그대로 판정 (단순함 우선)
```

### 3.8 시스템 재시작 복구 (§13)

```yaml
7-Step 복구 시퀀스:

Step 0: 안전 모드 진입
  신규 매수/박스 등록 차단

Step 1: 외부 시스템 연결
  DB → 키움 OAuth → WebSocket → Telegram

Step 2: 미완료 주문 모두 취소
  박스 보존 (다음 트리거 시 새 주문)

Step 3: 포지션 정합성 (Reconciler)
  Case A~E 처리

Step 4: 시세 재구독

Step 5: 박스 진입 조건 재평가
  지나간 트리거 무효 (옵션 A)

Step 6: 안전 모드 해제

Step 7: 복구 보고서
  텔레그램 CRITICAL 알림

긴급 정지: 없음 (헌법 4)
재시작 빈도 모니터링: 1시간 내 5회+ 시 CRITICAL
```

---

## §4. 핵심 의사결정 요약

13_APPENDIX.md §2 결정 매트릭스의 핵심.

### 4.1 거래 룰 핵심 숫자 (V71Constants)

```python
class V71Constants:
    # 손절선
    STOP_LOSS_INITIAL_PCT = -0.05
    STOP_LOSS_AFTER_PROFIT_5 = -0.02
    STOP_LOSS_AFTER_PROFIT_10 = 0.04
    
    # 익절
    PROFIT_TAKE_LEVEL_1 = 0.05
    PROFIT_TAKE_LEVEL_2 = 0.10
    PROFIT_TAKE_RATIO = 0.30
    
    # TS
    TS_ACTIVATION_LEVEL = 0.05
    TS_VALID_LEVEL = 0.10
    
    # ATR 배수
    ATR_MULTIPLIER_TIER_1 = 4.0  # +10~15%
    ATR_MULTIPLIER_TIER_2 = 3.0  # +15~25%
    ATR_MULTIPLIER_TIER_3 = 2.5  # +25~40%
    ATR_MULTIPLIER_TIER_4 = 2.0  # +40%~
    
    # 한도
    MAX_POSITION_PCT_PER_STOCK = 30.0
    AUTO_EXIT_BOX_DROP_PCT = -0.20
    
    # 매수
    ORDER_RETRY_COUNT = 3
    ORDER_WAIT_SECONDS = 5
    
    # 갭업 한도
    PATH_B_GAP_UP_LIMIT = 0.05
    VI_GAP_LIMIT = 0.03
    
    # 시스템
    REST_POLLING_INTERVAL_SECONDS = 5
    NOTIFICATION_RATE_LIMIT_MINUTES = 5
    BOX_EXPIRY_REMINDER_DAYS = 30
```

### 4.2 알림 시스템

```yaml
등급:
  CRITICAL: 손절, 시스템 오류 (강제 ON)
  HIGH: 매수, 익절, 수동 거래
  MEDIUM: 박스 임박, WebSocket 끊김
  LOW: 일일 마감, 헬스 체크

채널:
  텔레그램: 모든 등급 (메인)
  웹: CRITICAL/HIGH (보조 아이콘)

빈도 제한: 5분 (CRITICAL은 무시)
일일 마감: 매일 15:30 (LOW)
월 1회 리뷰: 매월 1일 (LOW)
박스 만료 알림: 30일 (자동 삭제 X)

텔레그램 명령어 13개:
  /status, /positions, /tracking, /pending,
  /today, /recent, /report,
  /stop, /resume, /cancel,
  /alerts, /settings, /help
```

### 4.3 보안

```yaml
인증:
  - JWT (Access 1h + Refresh 24h)
  - 2FA TOTP (Google Authenticator)
  - 30분 비활성 자동 로그아웃
  - 새 IP 즉시 알림 (CRITICAL)

비밀번호:
  - bcrypt cost 12
  - 최소 8자, 3종 조합
  - Rate Limit (IP당 5회/분)

통신:
  - HTTPS 강제 (Let's Encrypt + Cloudflare)
  - HSTS, CSP 등 보안 헤더
  - WebSocket WSS

감사 로그:
  - 모든 중요 액션
  - 6개월+ 보존
```

### 4.4 인프라

```yaml
배포:
  AWS Lightsail (Ubuntu 22.04)
  Python 3.11 + asyncio
  Nginx + Cloudflare
  systemd 서비스 자동 재시작

DB:
  Supabase (PostgreSQL)
  자동 백업 (PITR 7일)
  월 1회 외부 백업

외부 API:
  - 키움 OpenAPI (실거래) -- Patch #5 18개 매핑 확정
  - Anthropic Claude Opus 4.7 (리포트)
  - Telegram Bot API (알림)
  - DART OpenAPI (공시)
  - 네이버 뉴스 API (뉴스)

키움 API 18개 (PRD Patch #5, V7.1.0d, 2026-04-27):
  운영 도메인: https://api.kiwoom.com
  모의 도메인: https://mockapi.kiwoom.com (KRX 전용)
  WebSocket 운영: wss://api.kiwoom.com:10000
  WebSocket 모의: wss://mockapi.kiwoom.com:10000

  인증 (2):
    au10001 토큰 발급: POST /oauth2/token
    au10002 토큰 폐기: POST /oauth2/revoke

  종목 정보 (1):
    ka10001 주식기본정보: POST /api/dostk/stkinfo

  차트 (2) ★:
    ka10080 분봉차트: POST /api/dostk/chart (tic_scope=3, PATH_A)
    ka10081 일봉차트: POST /api/dostk/chart (PATH_B)

  주문 (4) ★:
    kt10000 매수, kt10001 매도, kt10002 정정, kt10003 취소
    공통: POST /api/dostk/ordr
    필수: dmst_stex_tp=KRX (V7.1은 KRX만)
    trde_tp: 0(지정가) / 3(시장가)
    ⚠ client_order_id 필드 없음 → orders 테이블로 자체 매핑

  계좌 (3) ★:
    ka10075 미체결, ka10076 체결내역, kt00018 잔고평가
    공통: POST /api/dostk/acnt
    kt00018 응답: cur_prc / pur_pric / rmnd_qty (포지션 동기화)

  WebSocket (5) ★:
    0B 주식체결: 실시간 시세 (필드 10=현재가, 27/28=호가, 290=장구분)
    00 주문체결: 계좌 (필드 9203=주문번호, 913=상태, 910/911=체결가/량)
    04 잔고: 계좌 (필드 930=수량, 931=매입단가)
    1h VI 발동/해제: 필드 9068=VI구분, 1224=해제시각
    0D 주식호가잔량 (선택)

  보조 (1):
    ka10004 주식호가요청 (REST): POST /api/dostk/mrkcond

  주요 오류 코드:
    1700 요청 개수 초과 → 지수 백오프 (1s → 2s → 4s)
    1902 종목 정보 없음 → 종목 등록 검증
    8005 토큰 무효 → 자동 재발급
    8010 토큰 발급 IP ≠ 사용 IP → CRITICAL 알림
    8030/8031 실전/모의 환경 불일치 → 시작 시 검증

  상세 매핑 + 구현 예시: KIWOOM_API_ANALYSIS.md 참조 (1,366라인)
```

---

## §5. 시스템 아키텍처 요약

자세한 내용은 04_ARCHITECTURE.md 참조.

### 5.1 레이어 구조

```
┌─────────────────────────────────────┐
│ Presentation                         │
│ Web Dashboard (React) + Telegram Bot │
└─────────────┬───────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ API Layer (src/web/)                 │
│ FastAPI + JWT + 2FA + WebSocket      │
└─────────────┬───────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ Business Logic                       │
│ ┌─────────────────────────────────┐ │
│ │ src/core/v71/ (★ 격리 패키지)    │ │
│ │ - box/, strategies/, exit/       │ │
│ │ - position/, vi_monitor          │ │
│ │ - skills/ (8개 표준 함수)        │ │
│ │ - report/ (Claude Opus 4.7)      │ │
│ └─────────────────────────────────┘ │
│ ┌─────────────────────────────────┐ │
│ │ src/core/ (V7.0 인프라 보존)     │ │
│ │ - candle_builder, websocket_mgr  │ │
│ │ - market_schedule, indicators    │ │
│ └─────────────────────────────────┘ │
└─────────────┬───────────────────────┘
              ↓
┌─────────────────────────────────────┐
│ Infrastructure                       │
│ src/api (키움) + src/database        │
│ src/notification + src/utils         │
└─────────────┬───────────────────────┘
              ↓
External: 키움 + Supabase + Telegram + Claude
```

### 5.2 의존성 룰 (헌법 3 강제)

```
src/web/
    ↓
src/core/v71/  (V7.1 신규 - 격리)
    ↓ (단방향만 허용)
src/core/      (V7.0 인프라)
    ↓
src/api/, src/database/, src/notification/, src/utils/

★ 절대 금지: V7.0 → V7.1 (역방향)
★ 자동 차단: 하네스 2 (Dependency Cycle Detector)
```

### 5.3 V7.1 신규 패키지 구조

```
src/core/v71/
├── box/
│   ├── box_manager.py
│   ├── box_entry_detector.py
│   └── box_state_machine.py
├── strategies/
│   ├── v71_box_pullback.py
│   └── v71_box_breakout.py
├── exit/
│   ├── exit_calculator.py
│   ├── exit_executor.py
│   └── trailing_stop.py
├── position/
│   ├── v71_position_manager.py
│   └── v71_reconciler.py
├── report/
│   ├── report_generator.py
│   ├── claude_api_client.py
│   ├── data_collector.py
│   └── exporters.py (PDF/Excel)
├── skills/
│   ├── kiwoom_api_skill.py
│   ├── box_entry_skill.py
│   ├── exit_calc_skill.py
│   ├── avg_price_skill.py
│   ├── vi_skill.py
│   ├── notification_skill.py
│   ├── reconciliation_skill.py
│   └── test_template.py
├── path_manager.py
├── vi_monitor.py
├── event_logger.py
├── restart_recovery.py
├── audit_scheduler.py
└── v71_constants.py
```

### 5.4 자동 검증 시스템

```yaml
에이전트 5개 (06_AGENTS_SPEC.md):
  1. V71 Architect (구조 검증)
  2. Trading Logic Verifier (룰 정확성)
  3. Migration Strategy (안전 전환)
  4. Security Reviewer (보안 검증)
  5. Test Strategy (테스트 가이드)

스킬 8개 (07_SKILLS_SPEC.md):
  하네스 3이 사용 강제
  매직 넘버 / raw API / 직접 수정 차단

하네스 7개 (08_HARNESS_SPEC.md):
  pre-commit + CI 자동 실행
  1. Naming Collision (BLOCK)
  2. Dependency Cycle (BLOCK)
  3. Trading Rule Enforcer (BLOCK)
  4. Schema Migration (BLOCK)
  5. Feature Flag (WARN)
  6. Dead Code (BLOCK)
  7. Test Coverage (BLOCK)
```

---

## §6. 개발 Phase 로드맵

자세한 내용은 05_MIGRATION_PLAN.md 참조.

### 6.1 전체 일정 (1~2개월, 1인 풀타임)

```
Phase 0: 사전 준비          (1일)
  ├─ 백업
  ├─ 환경 분리
  └─ Feature Flag 인프라

Phase 1: 인프라 정리         (3~5일)
  ├─ OpenClaw 정리 (외부)
  ├─ 백테스트 삭제
  ├─ V6 SNIPER_TRAP 삭제
  ├─ V7 신호 시스템 삭제
  ├─ 미완성 추상화 정리
  ├─ wave_harvest_exit 정리
  └─ trading_engine.py 정리

Phase 2: V7.1 골격           (3~5일)
  ├─ src/core/v71/ 생성
  ├─ 데이터 모델 마이그레이션
  ├─ 스킬 8개 시그니처
  └─ 핵심 클래스 시그니처

Phase 3: 거래 룰 구현 ★      (10~15일)
  ├─ 박스 시스템
  ├─ 매수 실행
  ├─ 매수 후 관리 (손절/익절/TS)
  ├─ 평단가 관리
  ├─ 수동 거래 처리
  ├─ VI 처리
  └─ 시스템 재시작 복구

Phase 4: 알림 시스템         (2~3일)
  ├─ 알림 등급 시스템
  ├─ 텔레그램 명령어 13개
  ├─ 일일 마감
  └─ 월 1회 리뷰

Phase 5: 웹 대시보드         (5~10일)
  ├─ FastAPI 백엔드
  ├─ JWT + 2FA
  ├─ Claude Design UI
  └─ 통합

Phase 6: 리포트 시스템       (3~5일)
  ├─ Claude API 통합
  ├─ 데이터 수집
  └─ PDF/Excel

Phase 7: 통합 테스트 + 배포  (5~10일)
  ├─ 페이퍼 트레이드 (1~2주)
  ├─ AWS 배포
  └─ 점진 활성화
```

### 6.2 마일스톤

```yaml
M1: Phase 1 완료
  V7.0 폐기 코드 모두 제거
  깨끗한 인프라

M2: Phase 2 완료
  V7.1 골격 + 데이터 모델

M3: Phase 3 완료 ★ 가장 중요
  거래 룰 모두 구현
  페이퍼 트레이드 가능
  단위 테스트 90%+

M4: Phase 4~6 완료
  알림 + 웹 + 리포트 완성

M5: Phase 7 완료
  실거래 운영
  V7.1 안정화
```

### 6.3 병렬 작업 가능

```yaml
순차 (의존성):
  Phase 0 → 1 → 2 → 3

Phase 3 완료 후 병렬 가능:
  Phase 4 (알림)
  Phase 5 (웹)
  Phase 6 (리포트)

→ 시간 단축 가능 (4~6주)

Phase 7은 모두 완료 후
```

---

## §7. Claude Code 작업 시작 가이드

### 7.1 첫 작업 시작 (Phase 0)

```yaml
사전 확인:
  ☐ Git 태그 v7.0-final-stable 생성됨
  ☐ 백업 완료
  ☐ V7.0 운영 환경 영향 없는 개발 환경 분리
  ☐ Supabase 개발 프로젝트 또는 로컬 PostgreSQL
  ☐ 키움 모의투자 또는 read-only 모드

읽을 문서:
  1. 00_CLAUDE_CODE_GENERATION_PROMPT.md (시작 컨텍스트)
  2. 01_PRD_MAIN.md (본 문서, 전체 그림)
  3. 05_MIGRATION_PLAN.md §0~§2 (Phase 0)

첫 작업:
  - config/feature_flags.yaml 생성
  - src/utils/feature_flags.py 모듈
  - .pre-commit-config.yaml 설정
  - 하네스 7개 스크립트 (8장 의사 코드 활용)
```

### 7.2 Phase별 시작 프롬프트 템플릿

```markdown
# Claude Code 작업 시작

## 컨텍스트
V7.1 PRD 패키지: C:\K_stock_trading\docs\v71\

## 현재 Phase
Phase [N]: [Phase 명]

## 참조 문서
- 05_MIGRATION_PLAN.md §[해당 섹션]
- 02_TRADING_RULES.md §[해당 섹션] (거래 룰)
- 04_ARCHITECTURE.md §[해당 섹션] (구조)
- 07_SKILLS_SPEC.md (스킬 사용)
- 08_HARNESS_SPEC.md (자동 검증)

## 작업
[구체적 작업 명시]

## 헌법 5원칙 준수 (절대)
1. 사용자 판단 불가침
2. NFR1 최우선
3. 충돌 금지 ★
4. 시스템 계속 운영
5. 단순함 우선

## 검증
- 하네스 통과 필수
- 에이전트 검증 (해당 영역)
- 단위 테스트 90%+ (거래 로직)
```

### 7.3 작업별 가이드

#### Phase 1 (인프라 정리)

```yaml
순서:
  P1.1 OpenClaw 정리 (외부 시스템 - 사용자 직접)
  P1.2 백테스트 삭제
  P1.3 임시 파일 정리
  P1.4 V6 SNIPER_TRAP 삭제
  P1.5 V7 신호 시스템 삭제
  P1.6 미완성 추상화 정리
  P1.7 wave_harvest_exit V7.1 룰 적용
  P1.8 trading_engine.py 정리

각 Task 시:
  1. Migration Strategy Agent 호출 (의존성 분석)
  2. 단계별 삭제 (의존성 역순)
  3. 각 단계 후 pytest 통과 확인
  4. python -c "import src.main" 정상 확인
  5. WORK_LOG.md 업데이트

검증:
  - 하네스 1 (Naming Collision) PASS
  - 하네스 2 (Dependency Cycle) PASS
  - 하네스 6 (Dead Code) PASS
  - python -c "import src.main" 정상
```

#### Phase 2 (V7.1 골격)

```yaml
순서:
  P2.1 디렉토리 구조 생성
  P2.2 데이터 모델 마이그레이션
  P2.3 스킬 8개 시그니처
  P2.4 핵심 클래스 시그니처
  P2.5 Feature Flag 통합

각 단계:
  1. V71 Architect Agent 호출 (구조 검증)
  2. 시그니처만 작성 (NotImplementedError)
  3. 타입 힌트 + Docstring 완전
  4. mypy 통과
  5. import 검증
```

#### Phase 3 (거래 룰 구현 ★)

```yaml
순서:
  P3.1 박스 시스템 (§3)
  P3.2 매수 실행 (§4)
  P3.3 매수 후 관리 (§5) ★ 가장 복잡
  P3.4 평단가 관리 (§6)
  P3.5 수동 거래 (§7)
  P3.6 VI 처리 (§10)
  P3.7 재시작 복구 (§13)

각 Task:
  1. 02_TRADING_RULES.md 해당 §정독
  2. 07_SKILLS_SPEC.md 해당 스킬 구현
  3. 단위 테스트 작성 (Test Strategy Agent)
  4. Trading Logic Verifier Agent 호출 (룰 검증)
  5. 하네스 3 (Trading Rule Enforcer) PASS
  6. 통합 테스트

★ Phase 3 완료 기준:
  - 모든 룰 02_TRADING_RULES.md와 정확히 일치
  - 단위 테스트 90%+ 통과
  - Trading Logic Verifier 모든 검증 PASS
  - 페이퍼 트레이드 24시간 안정
```

#### Phase 5 (웹 + UI)

```yaml
백엔드 (Claude Code):
  - src/web/ FastAPI 앱
  - 09_API_SPEC.md 모든 엔드포인트 구현
  - JWT + 2FA
  - WebSocket
  - Security Reviewer Agent 검증

프론트엔드 (Claude Design):
  - 10_UI_GUIDE.md 입력으로 작업
  - 사용자가 직접 진행 (Claude Design 도구)
  - 결과: React 컴포넌트

통합 (Claude Code):
  - 빌드 결과 src/web/static/ 또는 별도
  - 백엔드 API 연결
  - E2E 테스트
```

### 7.4 일상 작업 패턴

```yaml
새 함수 작성 시:
  1. PRD 해당 섹션 확인
  2. 스킬 사용 여부 확인 (07)
  3. 매직 넘버 V71Constants로 (02 부록 A.4)
  4. 타입 힌트 + Docstring
  5. Test Strategy Agent로 테스트 케이스 도출
  6. pytest 작성
  7. pre-commit hook (하네스 자동 실행)

새 모듈 추가 시:
  1. V71 Architect Agent (구조 검증)
  2. v71/ 패키지 안 또는 V71 접두사
  3. 의존성 단방향 확인
  4. 04_ARCHITECTURE.md 갱신

V7.0 코드 수정 시:
  1. Migration Strategy Agent (영향 분석)
  2. 최소한만 수정 (확장 우선)
  3. 새 기능은 v71/ 패키지로 분리

DB 변경 시:
  1. 마이그레이션 파일 작성 (UP/DOWN)
  2. 하네스 4 (Schema Validator) 통과
  3. 03_DATA_MODEL.md 갱신

거래 룰 의문 시:
  1. 02_TRADING_RULES.md 단일 진실
  2. 룰 변경하지 말고 PRD 우선
  3. PRD 변경 시 사용자 승인 필요
```

---

## §8. Claude Design 작업 가이드

### 8.1 작업 시작

```yaml
사전 확인:
  ☐ Phase 5 백엔드 API 어느 정도 완성
  ☐ 09_API_SPEC.md 안정화 (큰 변경 없음)

읽을 문서:
  1. 10_UI_GUIDE.md (★ 핵심, 전체)
  2. 09_API_SPEC.md (백엔드 연결)
  3. 12_SECURITY.md §3 (인증 화면)
  4. 01_PRD_MAIN.md (전체 그림)

작업 입력:
  10_UI_GUIDE.md 부록 B의 프롬프트 템플릿 활용
```

### 8.2 화면별 우선순위

```yaml
1. 로그인 + 2FA (10 §3)
2. 대시보드 메인 (10 §4) ★ 가장 자주 봄
3. 박스 설정 마법사 (10 §6) ★ 핵심 인터랙션
4. 추적 종목 관리 (10 §7)
5. 포지션 모니터 (10 §8)
6. 알림 센터 (10 §10)
7. 리포트 (10 §9)
8. 설정 (10 §11)
```

### 8.3 디자인 철학 (절대)

```yaml
1. 차트 없음 (HTS가 차트 담당)
2. 텍스트, 숫자, 테이블 중심
3. 정보 밀도 높게 (트레이더 환경)
4. 한국식 손익 색상 (수익=빨강, 손실=파랑)
5. 다크 모드 우선
6. 단순함 (헌법 5)
7. 반응형 (Desktop 메인, Mobile 보조)
```

### 8.4 기술 스택

```yaml
React 18 + TypeScript
Tailwind CSS
shadcn/ui (필수 컴포넌트 사전 설치)
Lucide React (아이콘)
TanStack Query (서버 상태)
React Hook Form + Zod (폼)
React Router v6 (라우팅)
```

### 8.5 검증

```yaml
디자인 완성 후:
  1. 사용자 검토 (박균호)
  2. 모바일 + 데스크톱 확인
  3. 다크 모드 확인
  4. 접근성 (키보드 네비게이션)

코드 통합 (Claude Code):
  1. Security Reviewer Agent (XSS, CSRF 검증)
  2. E2E 테스트
```

---

## §9. PRD 패키지 사용법

### 9.1 작업 흐름

```
1. 작업 시작
   └─ 01_PRD_MAIN.md (본 문서) 읽기
   
2. 작업 영역 식별
   └─ §2.3 (작업별 참조 문서) 확인
   
3. 해당 문서 정독
   └─ 02 (룰), 03 (DB), 04 (구조) 등
   
4. 코드 작성
   └─ 07 (스킬), V71Constants 활용
   
5. 검증
   └─ 06 (에이전트), 08 (하네스)
   
6. 결정 사항 기록
   └─ 13 (부록) 갱신 (필요 시)
```

### 9.2 PRD 변경 절차

```yaml
PRD는 단일 진실 원천:
  코드보다 PRD 우선
  PRD 변경 = 신중하게

변경 사유 발생 시:
  1. 사유 명시 (Slack 또는 메모)
  2. 영향 범위 분석
  3. 사용자 승인 받기 (박균호)
  4. 관련 문서 모두 갱신
  5. 13_APPENDIX.md §6 (변경 이력) 추가
  6. Git commit + tag

긴급 변경 (운영 중):
  1. 임시 패치 (코드)
  2. 텔레그램 알림
  3. 24시간 내 PRD 갱신
  4. 다음 운영에 반영
```

### 9.3 PRD 검수 체크리스트 (배포 전)

```yaml
일관성:
  ☐ 헌법 5원칙 모든 문서 반영
  ☐ V71Constants 모든 매직 넘버 정의
  ☐ 용어 일관 (13 §4)
  ☐ 결정 매트릭스 (13 §2) 일치
  ☐ 교차 참조 정확

완전성:
  ☐ 14개 문서 모두 작성
  ☐ 미정 사항 (13 §3) 모두 식별
  ☐ V71Constants 완전

실용성:
  ☐ Claude Code가 그대로 구현 가능
  ☐ Claude Design이 UI 작업 가능
  ☐ 에이전트가 검증 가능
  ☐ 하네스가 자동 강제 가능

가독성:
  ☐ 목차 명확
  ☐ 코드 예시 충분
  ☐ 용어집 갖춤
```

---

## §10. 다음 단계

### 10.1 PRD 패키지 완성 (현재)

```
✅ 14개 문서 모두 작성 완료:
  - README.md
  - 00_CLAUDE_CODE_GENERATION_PROMPT.md
  - 01_PRD_MAIN.md (본 문서)
  - 02_TRADING_RULES.md
  - 03_DATA_MODEL.md
  - 04_ARCHITECTURE.md
  - 05_MIGRATION_PLAN.md
  - 06_AGENTS_SPEC.md
  - 07_SKILLS_SPEC.md
  - 08_HARNESS_SPEC.md
  - 09_API_SPEC.md
  - 10_UI_GUIDE.md
  - 11_REPORTING.md
  - 12_SECURITY.md
  - 13_APPENDIX.md
```

### 10.2 사용자 (박균호) 다음 작업

```yaml
1. PRD 패키지 검수 (1~2일)
  - 14개 문서 정독
  - 빠진 결정 사항 확인
  - 미정 사항 (13 §3) 검토
  - 필요 시 추가 결정

2. Phase 0 시작 준비
  - V7.0 백업 (Git tag, DB dump)
  - 개발 환경 분리
  - 키움 모의투자 환경 확인

3. Claude Code에 작업 위임
  - 00_CLAUDE_CODE_GENERATION_PROMPT.md 활용
  - Phase 0부터 순차 진행
  - 매 Phase 완료 후 검수

4. Claude Design 작업 (Phase 5 시작 시)
  - 10_UI_GUIDE.md 입력
  - 사용자 직접 진행
  - React 컴포넌트 결과 받음
```

### 10.3 PRD 외 미정 사항

```yaml
사용자 결정 필요:
  1. 키움 API client_order_id 지원 확인
     → 키움 OpenAPI 문서 확인
  
  2. V7.0 → V7.1 데이터 마이그레이션 정책
     → 현재 운영 데이터 분류
     → §12.2 옵션 A/B/C 중 선택
  
  3. 자본 (total_capital) 정확한 금액
     → 박스 비중 계산 기준

운영 중 결정:
  4. 폴링 간격 튜닝 (기본 5초)
  5. 알림 빈도 제한 미세 조정
  6. 리포트 월 한도 (기본 30건)
  7. 로그 보관 정책
```

### 10.4 V7.1 정식 운영 후 (장기)

```yaml
3개월:
  - 안정성 검증
  - 사용자 피드백 수집
  - 작은 개선 (V7.1.1)

6개월:
  - V7.0 코드 완전 삭제 검토
  - 데이터 archive 정리
  - 보안 감사

1년:
  - V7.2 대규모 개선 검토
  - 다중 사용자 지원 (가족 등)
  - 추가 시장 (해외 주식)
```

---

## 부록 A: 핵심 PRD 문서별 한 줄 요약

| 문서 | 한 줄 요약 |
|------|-----------|
| README | PRD 패키지 진입점, 14개 문서 안내 |
| 00 | Claude Code가 V7.1 작업 시작할 때 읽는 컨텍스트 |
| **01** | **본 문서, 전체 PRD 통합 요약 + 가이드** |
| **02** | **거래 룰의 단일 진실 원천 (가장 중요)** |
| 03 | Supabase 스키마 (모든 테이블 정의) |
| 04 | 모듈 구조, V7.1 격리 패키지 (src/core/v71/) |
| 05 | V7.0 → V7.1 8 Phase 안전 전환 계획 |
| 06 | 5개 AI 에이전트 (검증 페르소나) |
| 07 | 8개 표준 스킬 (반복 작업 표준화) |
| 08 | 7개 자동 검증 하네스 (헌법 강제) |
| 09 | 백엔드 REST API + WebSocket 명세 |
| **10** | **웹 UI 명세 (Claude Design 입력 문서)** |
| 11 | On-Demand 종목 리포트 (Claude Opus 4.7) |
| 12 | 보안 (HTTPS + JWT + 2FA + 감사) |
| 13 | 결정 이력, 미정 사항, 용어집 |

---

## 부록 B: 헌법 5원칙 빠른 참조 카드

```
══════════════════════════════════════
   V7.1 헌법 5원칙 (절대 기준)
══════════════════════════════════════

1. 사용자 판단 불가침
   → 자동 추천 X, 사용자 입력만

2. NFR1 최우선
   → 박스 진입 절대 놓치지 않음 (<1초)

3. 충돌 금지 ★ 핵심
   → V7.0 보존, V7.1 격리 (src/core/v71/)
   → 하네스 1, 2, 6 자동 강제

4. 시스템 계속 운영
   → 자동 정지 X, 안전 모드만

5. 단순함 우선
   → 작은 모듈 다수, 명시적 흐름
══════════════════════════════════════
```

---

## 부록 C: V71Constants 빠른 참조

```python
# 손절선 (단방향 상향)
STOP_LOSS_INITIAL_PCT = -0.05      # 단계 1
STOP_LOSS_AFTER_PROFIT_5 = -0.02   # 단계 2 (+5% 청산 후)
STOP_LOSS_AFTER_PROFIT_10 = 0.04   # 단계 3 (+10% 청산 후)

# 익절
PROFIT_TAKE_LEVEL_1 = 0.05         # +5% 1차
PROFIT_TAKE_LEVEL_2 = 0.10         # +10% 2차
PROFIT_TAKE_RATIO = 0.30           # 30% 청산

# TS
TS_ACTIVATION_LEVEL = 0.05         # +5% 활성화
TS_VALID_LEVEL = 0.10              # +10% 청산선 비교 유효

# ATR 배수 (단방향 축소)
ATR_MULTIPLIER_TIER_1 = 4.0        # +10~15%
ATR_MULTIPLIER_TIER_2 = 3.0        # +15~25%
ATR_MULTIPLIER_TIER_3 = 2.5        # +25~40%
ATR_MULTIPLIER_TIER_4 = 2.0        # +40%~

# 한도
MAX_POSITION_PCT_PER_STOCK = 30.0  # 종목당 30%
AUTO_EXIT_BOX_DROP_PCT = -0.20     # -20% 자동 이탈

# 매수 주문
ORDER_RETRY_COUNT = 3              # 지정가 3회
ORDER_WAIT_SECONDS = 5             # 5초 대기

# 갭업 한도
PATH_B_GAP_UP_LIMIT = 0.05         # 경로 B: 5%
VI_GAP_LIMIT = 0.03                # VI 후: 3%

# 시스템
REST_POLLING_INTERVAL_SECONDS = 5
NOTIFICATION_RATE_LIMIT_MINUTES = 5
BOX_EXPIRY_REMINDER_DAYS = 30
```

---

## 부록 D: 작업 진입 매트릭스

| 상황 | 시작 문서 | 보조 문서 |
|------|-----------|-----------|
| V7.1 처음 본다 | README → 01 | 13 (용어) |
| Claude Code Phase 0 시작 | 00 → 01 → 05 | - |
| 거래 룰 구현 | 02 → 07 | 06 §2 |
| DB 작업 | 03 | 05 §8 |
| 새 모듈 추가 | 04 | 06 §1 |
| V7.0 정리 | 05 | 06 §3 |
| API 작업 | 09 | 12 §3 |
| UI 작업 (Claude Design) | 10 | 09, 12 §3 |
| 리포트 | 11 | 09 §8 |
| 보안 | 12 | 06 §4 |
| 테스트 | 06 §5 | 07 §8 |
| 결정 사항 확인 | 13 §2 | - |
| 용어 모름 | 13 §4 | - |

---

## 부록 E: 외부 시스템 연결 빠른 참조

```yaml
키움 OpenAPI (REST + WebSocket):
  사용: 시세, 주문, 잔고
  스킬: kiwoom_api_skill (07 §1)
  Rate Limit: 초당 4.5회 (실전)
  문서: https://apiportal.koreainvestment.com/

Supabase (PostgreSQL):
  사용: 모든 영속화
  스키마: 03_DATA_MODEL.md
  마이그레이션: src/database/migrations/v71/
  백업: 자동 (PITR 7일)

Telegram Bot API:
  사용: 알림 + 명령어
  스킬: notification_skill (07 §6)
  화이트리스트: authorized_chat_ids
  Rate Limit: 분당 20메시지

Anthropic Claude API:
  사용: 종목 리포트
  모델: claude-opus-4-7
  관리: 11_REPORTING.md
  비용: 월 ~$10 (예상)

DART OpenAPI:
  사용: 공시 (리포트)
  문서: https://opendart.fss.or.kr/

Cloudflare:
  사용: DDoS + WAF + DNS
  설정: 12_SECURITY.md §2.3

Let's Encrypt:
  사용: SSL/TLS 인증서
  자동 갱신: 90일
```

---

*본 문서는 V7.1 PRD 패키지의 통합 진입점입니다.*  
*14개 문서를 한눈에 파악하고 작업을 시작하는 가이드.*  
*PRD 변경 시 본 문서 §6 (변경 이력) 갱신 필수.*

**🎯 V7.1 시스템 철학:**  
*"사용자가 정의한 박스 구간을, 시스템이 인내심 있게 지키다가 정확히 포착한다."*

*최종 업데이트: 2026-04-25*  
*PRD 패키지 완성 (14/14 문서)*  
*다음 단계: 사용자 검수 → Phase 0 시작*
