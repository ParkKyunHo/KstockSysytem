# V7.1 Project Documentation

> **K_stock_trading V7.1**: 박스 기반 한국 주식 자동매매 시스템
> 
> **Version**: 7.1 (in design)
> **Status**: Documentation Phase
> **Owner**: 박균호 (8년 전업 트레이더)
> **Predecessor**: V7.0 Purple-ReAbs

---

## 이 문서 패키지의 목적

이 디렉토리는 **V7.1 시스템의 단일 진실 원천(Single Source of Truth)**입니다.

Claude Code가 V7.1을 구현할 때 이 문서들만으로 작업이 가능하도록 작성됩니다. 모든 결정 사항, 거래 룰, 데이터 모델, 아키텍처가 이곳에 통합되어 있습니다.

---

## 문서 읽는 순서

### Claude Code 첫 작업 시

```
1. README.md (이 파일)                           # 전체 구조 파악
2. 00_CLAUDE_CODE_GENERATION_PROMPT.md           # 작업 지시서
3. 01_PRD_MAIN.md                                # 통합 PRD (모든 결정 요약)
4. 작업 영역에 따라 해당 문서 참조
```

### 인간 개발자 검토 시

```
1. 01_PRD_MAIN.md          # 전체 개요
2. 02_TRADING_RULES.md     # 거래 룰 (시스템 핵심)
3. 04_ARCHITECTURE.md      # 시스템 구조
4. 05_MIGRATION_PLAN.md    # V7.0 → V7.1 전환
```

---

## 문서 목록

### 핵심 문서 (Phase 1)

| 파일 | 내용 | 우선순위 |
|------|------|----------|
| `00_CLAUDE_CODE_GENERATION_PROMPT.md` | Claude Code 작업 지시서 | ★★★ |
| `01_PRD_MAIN.md` | 메인 PRD, 모든 결정 통합 | ★★★ |
| `02_TRADING_RULES.md` | 거래 룰 §1~§13 상세 | ★★★ |
| `03_DATA_MODEL.md` | Supabase 스키마 | ★★★ |
| `04_ARCHITECTURE.md` | 아키텍처, 모듈 분류 | ★★★ |
| `05_MIGRATION_PLAN.md` | V7.0→V7.1 전환 전략 | ★★★ |

### 인프라 문서 (Phase 2)

| 파일 | 내용 | 우선순위 |
|------|------|----------|
| `06_AGENTS_SPEC.md` | 에이전트 5개 정의 | ★★ |
| `07_SKILLS_SPEC.md` | 스킬 8개 정의 | ★★ |
| `08_HARNESS_SPEC.md` | 하네스 7개 정의 | ★★ |

### 인터페이스 문서 (Phase 3)

| 파일 | 내용 | 우선순위 |
|------|------|----------|
| `09_API_SPEC.md` | 백엔드 REST API 명세 | ★★ |
| `10_UI_GUIDE.md` | Claude Design 입력용 가이드 | ★★ |

### 보조 문서 (Phase 4)

| 파일 | 내용 | 우선순위 |
|------|------|----------|
| `11_REPORTING.md` | On-Demand 리포트 시스템 | ★ |
| `12_SECURITY.md` | 보안 레이어 | ★★ |
| `13_APPENDIX.md` | 결정 이력, 미정 사항 | ★ |

---

## V7.1 시스템 한 문장 요약

> **사용자가 정의한 박스 구간을, 시스템이 인내심 있게 지키다가 정확히 포착한다.**

---

## V7.1 헌법 (5원칙)

모든 코드와 결정은 이 5원칙을 따릅니다:

1. **사용자 판단 불가침**: 사용자가 정의한 박스 구간을 시스템이 임의 수정 안 함
2. **NFR1 최우선**: 박스 진입 절대 놓치지 않음
3. **충돌 금지**: 기존 V7.0 코드와 호환 보장 + 안전한 삭제
4. **시스템 계속 운영**: 긴급정지 없음, 어떤 상황에서도 시스템 가동
5. **단순함 우선**: 복잡한 예외 처리보다 단순 룰

---

## V7.1 핵심 변경 사항 (V7.0 대비)

### 추가
- 박스 기반 진입 시스템 (눌림 + 돌파)
- 이중 경로 지원 (경로 A 단타 / 경로 B 중기)
- VI 처리 (변동성 완화 장치)
- 시스템 재시작 복구
- On-Demand 리포트 (Claude Opus 4.7)
- 웹 대시보드
- 강화된 보안 (HTTPS + 2FA)

### 변경
- 손절: 단계별 상향 (-5% → -2% → +4%)
- 익절: 분할 (+5% 30%, +10% 30%, 나머지 TS)
- TS: ATR 배수 4.0 → 3.0 → 2.5 → 2.0 (V7.0 대비 조정)
- 평단가: 추가 매수 시 재계산 + 이벤트 리셋

### 삭제
- V6 SNIPER_TRAP 전략 전체
- V7 5조건 신호 시스템 (PurpleOK, Trend, Zone, ReAbsStart, Trigger)
- 3계층 Pool, Dual-Pass 신호 탐지
- Trend Hold Filter
- 백테스트 시스템
- OpenClaw 외부 시스템 (코드 베이스 외부, 별도 정리)

---

## 작업 진행 상태

### 설계 완료 (17세션 누적)

```
✅ 시스템 철학, 헌법 5원칙
✅ 이중 경로 (A/B) 설계
✅ 박스 시스템 전체 룰
✅ 매수/매도/관리 룰
✅ 수동 거래 시나리오 A/B/C/D
✅ VI 처리
✅ 상하한가 처리
✅ 시스템 재시작 복구
✅ 알림 시스템 (CRITICAL/HIGH/MEDIUM/LOW)
✅ 보안 레이어
✅ 데이터 모델 초안
✅ 모듈 분류 (V7.0 코드 1차 분석)
✅ 에이전트·스킬·하네스 초안 (이 패키지에서 정식 정의)
```

### 문서화 진행 중

```
🚧 PRD 문서 작성 중 (이 디렉토리)
   - Phase 1: 핵심 문서 (00~05)
   - Phase 2: 인프라 문서 (06~08)
   - Phase 3: 인터페이스 문서 (09~10)
   - Phase 4: 보조 문서 (11~13)
```

### 미진행

```
◯ Claude Code의 V7.1 구현
◯ Claude Design의 UI 작업
◯ 통합 테스트
◯ 배포
◯ BTC 시스템 최종 처리 결정
```

---

## 기술 스택

```yaml
백엔드:
  - Python 3.11
  - asyncio (비동기)
  - PostgreSQL (Supabase)
  - 키움 REST API + WebSocket
  - Telegram Bot API
  - Claude API (Opus 4.7, 리포트용)

프론트엔드:
  - React + Tailwind + shadcn/ui
  - 차트 렌더링 없음 (HTS 의존)

배포:
  - AWS Lightsail (Ubuntu)
  - Cloudflare
  - HTTPS (Let's Encrypt)
  - Nginx (리버스 프록시)
```

---

## 디렉토리 구조 (V7.1 완성 시)

```
K_stock_trading/
├── src/
│   ├── api/                        # 키움 API (V7.0에서 유지)
│   ├── core/
│   │   ├── v71/                    # V7.1 신규 모듈 (격리 패키지)
│   │   │   ├── box/                # 박스 시스템
│   │   │   ├── strategies/         # 눌림/돌파 전략
│   │   │   ├── path_manager.py     # 경로 A/B
│   │   │   ├── vi_monitor.py       # VI 처리
│   │   │   ├── report/             # 리포트 시스템
│   │   │   └── ...
│   │   ├── candle_builder.py       # V7.0 인프라 (유지)
│   │   ├── websocket_manager.py    # V7.0 인프라 (유지)
│   │   └── ... (V7.0 인프라 유지 모듈)
│   ├── database/                   # 스키마 확장
│   ├── notification/               # 알림 등급 추가
│   └── web/                        # 웹 대시보드 백엔드 (신규)
├── docs/
│   └── v71/                        # 이 디렉토리
├── tests/
│   └── v71/                        # V7.1 테스트
└── ... (기존 구조 유지)
```

---

## 라이선스 / 소유권

이 시스템은 박균호 개인 소유의 자동매매 시스템입니다. 외부 공유 금지.

---

*이 README는 V7.1 문서 패키지의 진입점입니다. 실제 작업은 다른 문서를 참조하세요.*

*최종 업데이트: 2026-04-25*
