# V7.1 Frontend Migration Notes

> **상태**: Phase 5 P5.1 완료 -- Claude Design 산출물(vanilla JS 프로토타입)이
> 이 디렉토리에 그대로 implement되어 있습니다.
> 
> 본 문서는 (1) 즉시 사용법, (2) PRD Patch #3 적용 사항, 그리고
> (3) production migration plan (Vite + React + TS + @carbon/react)을 정리합니다.
> 
> 작성: 2026-04-26 / 다음 단계: 사용자 지시 시 P5.2 시작

---

## 1. 즉시 사용법 (Phase 5 P5.1 산출물)

```
frontend/V7.1 Dashboard.html  ← 브라우저에서 file:// 로 바로 열림
```

CDN React 18 + Babel inline transform + 자체 Carbon CSS 토큰을 사용하므로
**별도 빌드 없이 즉시 동작**합니다.

```bash
# 권장: 로컬 정적 서버 (CORS 회피)
cd C:/K_stock_trading/frontend
python -m http.server 5173
# 브라우저: http://localhost:5173/V7.1%20Dashboard.html
```

또는 `Live Server` (VSCode 확장) 등의 도구로 directory를 호스팅.

### 1.1 산출물 구조

```
frontend/
├── V7.1 Dashboard.html               # 단일 진입점 (UMD React + Babel)
├── HANDOFF.md                        # Claude Design 측 인계 메모 (139 lines)
├── CLAUDE_DESIGN_HANDOFF_README.md   # Claude Design 번들 README (해석 가이드)
├── MIGRATION_NOTES.md                # 본 문서
└── src/
    ├── styles/
    │   ├── carbon-tokens.css         # Carbon Gray 10/90/100 토큰 + 한국식 손익 색상
    │   ├── carbon-components.css     # Tag/Btn/Modal/Tabs 등 BEM 컴포넌트
    │   └── app.css                   # AppShell + 페이지 레이아웃
    ├── components/
    │   ├── icons.js                  # Carbon-스타일 SVG 아이콘 (createElement 기반)
    │   ├── ui.js                     # 공통 UI 라이브러리 → window.UI
    │   ├── shell.js                  # AppHeader + AppSideNav + AppShell
    │   └── order-dialog.js           # 주문 Modal (수동 매도 등)
    ├── pages/
    │   ├── login.js                  # 로그인 + TOTP
    │   ├── dashboard.js              # 대시보드 메인
    │   ├── tracked-stocks.js         # 추적 종목 리스트 + 상세
    │   ├── box-wizard.js             # 박스 추가 6-step 마법사 ⚠️ Patch #3 적용 필요
    │   ├── positions.js              # 포지션 모니터
    │   ├── reports.js                # 리포트 리스트
    │   ├── trade-events.js           # 거래 이벤트 리스트
    │   └── notifications-settings.js # 알림 센터 + 5-tab 설정
    └── mocks/
        └── index.js                  # Mock 데이터 + WebSocket 시뮬레이터 (window.MOCK)
```

---

## 2. PRD Patch #3 적용 사항 (Production Migration 시 반영)

본 산출물은 **Patch #3 이전** PRD 기준으로 작성되었습니다 (사용자가 Claude Design에
입력한 `CLAUDE_DESIGN_PROMPT.md`가 Patch #3 적용 전 시점). Production 마이그레이션 시
다음을 적용해야 합니다.

### 2.1 데이터 모델

| 위치 | 현재 (Patch #3 이전) | 적용 후 (Patch #3) |
|------|---------------------|---------------------|
| `TrackedStock.path_type: 'PATH_A'\|'PATH_B'` | 종목당 1개 path | **제거** |
| `TrackedStock.summary` | `active_box_count`, `triggered_box_count`, ... | **추가**: `path_a_box_count`, `path_b_box_count` |
| `Box.path_type` | (옵션) | **필수** (NOT NULL) |
| `Position.path_type` | -- | box로부터 상속 (변경 없음) |

### 2.2 UI

| 위치 | 현재 | 적용 후 |
|------|-----|---------|
| `pages/tracked-stocks.js` (종목 등록 모달) | RadioButtonGroup "경로 선택" 포함 | **제거**, 경로는 박스 마법사로 위임 |
| `pages/box-wizard.js` (마법사) | 6-step (가격→전략→비중→손절→확인→저장) | **7-step**: Step 1 "경로 선택" RadioTile 추가 |

### 2.3 API (백엔드 통합 시)

| 엔드포인트 | 현재 | 적용 후 |
|------|-----|---------|
| `POST /api/v71/tracked_stocks` | Request에 `path_type` | **제거** |
| `POST /api/v71/boxes` | Request에 (옵션) `path_type` | **필수** |
| `GET /api/v71/tracked_stocks?path_type=...` | 필터 존재 | **필터 제거** |
| `GET /api/v71/boxes?path_type=...` | -- | **필터 추가** |

### 2.4 거래 로직 (변경 없음)

매수 후 관리(손절/익절/TS), 평단가 계산, VI 처리는 path 무관 동일 룰. Patch #3 영향 없음.

---

## 3. Production Migration Plan (HANDOFF.md §7)

사용자 지시 시 P5.2부터 진행:

### 3.1 부트스트랩 (P5.2)

```bash
cd C:/K_stock_trading
npm create vite@latest frontend-prod -- --template react-ts
cd frontend-prod
npm install @carbon/react @carbon/styles @carbon/icons-react @carbon/grid sass
npm install @tanstack/react-query react-router-dom react-hook-form zod @hookform/resolvers
npm install zustand react-markdown
```

### 3.2 핵심 마이그레이션 매핑 (HANDOFF.md §2)

| 프로토타입 | Production |
|-----------|-----------|
| `window.UI`, `window.Pages` 글로벌 | ESM `export` / `import` |
| `(function(){...})()` IIFE 래퍼 | 자연스러운 모듈 격리 |
| `React.createElement(...)` | JSX (`<Tile>...</Tile>`) |
| `src/styles/carbon-tokens.css` (수동 추출) | `@carbon/react` + `@carbon/styles` 직접 import |
| `src/components/ui.js` (자체 Btn/Tag/Modal/Tabs) | `@carbon/react` 직접 사용 |
| `src/components/shell.js` | `@carbon/react`의 `Header` + `SideNav` |
| `src/mocks/index.js`의 `setInterval` 가격 워크 | 실제 KIS WebSocket 클라이언트 |

### 3.3 작업 순서 (HANDOFF.md §8)

1. `carbon-tokens.css` -- 디자인 시스템 기반
2. `app.css`의 `--cds-pnl-*` 변수 + AppShell 레이아웃
3. `tracked-stocks.js` (가장 복잡한 페이지 -- 패턴 잡기)
4. `box-wizard.js` (검증 로직 그대로 + Patch #3 7-step 변환)
5. 나머지 페이지
6. 라우터 (React Router v6) -- 현재 `useState('dashboard')` 단일 라우팅 교체
7. 인증 hook (JWT + 2FA + 30분 자동 로그아웃)
8. WebSocket 클라이언트 (네이티브 WebSocket → FastAPI 정합)
9. TanStack Query로 mock data → 실 API 교체
10. 단위 테스트 (Vitest + React Testing Library) -- BoxWizard 검증 로직 우선

### 3.4 Production 디렉토리 구조 (목표)

```
frontend-prod/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx                  # Theme + Router + Providers
│   ├── pages/                   # 9개 화면 (1:1 wires)
│   ├── components/
│   │   ├── shell/               # AppShell (Carbon Header + SideNav)
│   │   ├── kpi/                 # KPITile
│   │   ├── pnl/                 # PnLCell
│   │   ├── tags/                # Tracked/Box/Position StatusTag
│   │   ├── modals/              # NewTrackedStock / EditBox / Confirm / NewReport
│   │   └── notifications/       # Toast / Item
│   ├── api/                     # TanStack Query hooks + REST + WS clients
│   ├── mocks/                   # MSW handlers (dev only)
│   ├── hooks/
│   ├── types/                   # PRD §6.2 TypeScript 타입 (Patch #3 적용)
│   └── styles/
│       ├── main.scss            # @use carbon + 폰트
│       └── _pnl.scss            # 한국식 손익 색상
└── public/
```

### 3.5 통합 (Phase 5 P5.5+)

백엔드 P5.1~P5.4 (FastAPI 골격, JWT/2FA, REST, WebSocket) 진행 후 frontend-prod와
wiring + e2e 테스트.

---

## 4. 작업 분기 다이어그램

```
[현재 = P5.1 완료]
  frontend/  ← Claude Design 산출물 (vanilla JS, 즉시 동작)
                          │
                          ▼
                    사용자 검토 + 디자인 승인
                          │
                          ├── 승인 → P5.2 (Production migration 시작)
                          │             │
                          │             ▼
                          │        frontend-prod/  (Vite + React + TS)
                          │             │
                          │             ▼
                          │        + Patch #3 적용
                          │        + Carbon @carbon/react 직접 사용
                          │             │
                          │             ▼
                          │        백엔드 P5.1~P5.4 (FastAPI)
                          │             │
                          │             ▼
                          │        통합 P5.5+ (e2e + 검증)
                          │             │
                          │             ▼
                          │        v71-phase5-complete (M5)
                          │
                          └── 수정 요청 → frontend/ 디자인 추가 iteration
                                          (Claude Design에 재요청 또는 직접 수정)
```

---

## 5. 변경 이력

| 날짜 | 변경 |
|------|------|
| 2026-04-26 | **P5.1 완료** -- Claude Design 산출물(vanilla JS) 복사 + 본 문서 신규 작성 |

---

*Migration trigger*: 사용자가 디자인 승인 + "P5.2 시작" 지시 시 Production migration 진행.
*담당*: Claude Code (V7.1 백엔드 빌더)
