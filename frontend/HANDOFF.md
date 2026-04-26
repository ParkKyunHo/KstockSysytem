# V7.1 Frontend → Claude Code 인계 패키지

이 디렉토리는 **V7.1 한국 주식 자동매매 시스템** 의 프런트엔드 프로토타입입니다.
실제 React + Vite + Carbon 프로젝트로 옮길 때 그대로 참고하세요.

## 1. 무엇이 있나

```
frontend/
├── V7.1 Dashboard.html        ← 단일 진입점 (브라우저에서 바로 열림)
└── src/
    ├── styles/
    │   ├── carbon-tokens.css       Carbon Gray 10/90/100 토큰 + 한국식 손익 색상
    │   ├── carbon-components.css   Tag/Btn/Modal/Tabs 등 BEM 컴포넌트
    │   └── app.css                 AppShell·페이지 레이아웃
    ├── components/
    │   ├── icons.js                Carbon-스타일 SVG 아이콘 (createElement 기반)
    │   ├── ui.js                   공통 UI 라이브러리 → window.UI
    │   └── shell.js                AppHeader + AppSideNav + AppShell
    ├── pages/
    │   ├── login.js                로그인 + TOTP
    │   ├── dashboard.js            대시보드 메인
    │   ├── tracked-stocks.js       추적 종목 리스트 + 상세
    │   ├── box-wizard.js           박스 추가 6-step 마법사
    │   ├── positions.js            포지션 모니터
    │   ├── reports.js              리포트 리스트
    │   └── notifications-settings.js  알림 센터 + 5-tab 설정
    └── mocks/
        └── index.js                Mock 데이터 + WebSocket 시뮬레이터
```

## 2. 프로토타입 → Production 매핑

| 프로토타입 | Production |
|---|---|
| `window.UI`, `window.Pages` 글로벌 | ESM `export` / `import` |
| `(function(){…})()` IIFE 래퍼 | 자연스러운 모듈 격리 |
| `React.createElement(...)` | JSX (`<Tile>...</Tile>`) |
| `src/styles/carbon-tokens.css` (수동 추출) | `@carbon/react` + `@carbon/styles` 그대로 import |
| `src/components/ui.js` 의 `Btn`, `Tag`, `Modal`, `Tabs` ... | `@carbon/react` 의 `Button`, `Tag`, `Modal`, `Tabs` 직접 사용 |
| `src/components/shell.js` | `@carbon/react` 의 `Header` + `SideNav` |
| `src/mocks/index.js` 의 `setInterval` 가격 워크 | 실제 KIS WebSocket 클라이언트 (`apps/web/src/lib/ws.ts`) |

## 3. 관찰해야 할 디자인 결정

1. **테마 토글**: Carbon Gray 100(다크) 기본, Gray 10(라이트), Gray 90 도 지원. 헤더 우측 눈 모양 아이콘으로 순환. `data-cds-theme` 속성으로 전환.
2. **한국식 손익 색상**: `--cds-pnl-profit: #ee5396` (마젠타-레드 계열, 이익) / `--cds-pnl-loss: #4589ff` (블루 계열, 손실). 미국식과 반대.
3. **글꼴**: IBM Plex Sans KR + IBM Plex Mono. 숫자는 항상 `font-variant-numeric: tabular-nums`.
4. **AppShell**: 데스크톱은 SideNav 항상 표시, < 1056px 에서 햄버거 메뉴 + 오버레이.
5. **PnL 표시**: `+1,234,567` / `-12.34%` — 부호 + 천 단위 콤마 + 소수점 2자리. `window.fmt.krwSigned()` 헬퍼.
6. **상태 태그 매핑** (`ui.js` 하단 참조):
   - `TrackedStatusTag`: TRACKING/BOX_SET/POSITION_OPEN/POSITION_PARTIAL/EXITED
   - `BoxStatusTag`: WAITING/TRIGGERED/INVALIDATED/CANCELLED
   - `PositionSourceTag`: SYSTEM_A/SYSTEM_B/MANUAL
7. **6-step BoxWizard**: 가격 → 전략 → 비중 → 손절 → 확인 → 저장. 각 step 마다 검증, 30% 누적 한도 실시간 계산.
8. **라이브 가격**: `useLiveMock` 훅이 2초마다 ±0.3% 랜덤 워크 + 포지션 PnL 자동 재계산. WebSocket 자리 그대로 대체.

## 4. Carbon 컴포넌트 매핑 표

`@carbon/react` 로 마이그레이션 시:

| 프로토 | Carbon 컴포넌트 |
|---|---|
| `Btn` | `Button` (`kind`: primary / secondary / tertiary / ghost / danger) |
| `Tag` | `Tag` (`type`: red / blue / cool-gray / green / purple / magenta) |
| `Field + Input` | `TextInput` |
| `NumInput` | `NumberInput` |
| `SearchBox` | `Search` |
| `Toggle` | `Toggle` |
| `Dropdown` | `Dropdown` / `Select` |
| `OverflowMenu` | `OverflowMenu` |
| `Modal` | `Modal` |
| `Tabs` | `Tabs` + `Tab` + `TabPanel` |
| `ProgressIndicator` | `ProgressIndicator` |
| `ProgressBar` | `ProgressBar` |
| `Pagination` | `Pagination` |
| `Tile` / `KPITile` | `Tile` / `ClickableTile` (KPI 는 커스텀) |
| `ExpandableTile` | `ExpandableTile` |
| `InlineNotif` | `InlineNotification` |
| `ToastContainer` | `ToastNotification` |
| `Skeleton` | `SkeletonText` / `SkeletonPlaceholder` |
| `Checkbox` / `RadioTileGroup` / `SliderInput` | 동일명 컴포넌트 존재 |

## 5. 데이터 모델

`src/mocks/index.js` 의 모든 객체는 PRD §6.2 타입 정의 그대로입니다.
백엔드 API 와 1:1 매칭됩니다.

```ts
TrackedStock { id, stock_code, stock_name, market, path_type: 'PATH_A'|'PATH_B',
               status, current_price, summary, source, user_memo, created_at }
Box          { id, tracked_stock_id, box_tier, upper_price, lower_price,
               position_size_pct, stop_loss_pct, strategy_type, status,
               entry_proximity_pct, memo }
Position     { id, tracked_stock_id, stock_code, stock_name, source: 'AUTO'|'EXTERNAL',
               total_quantity, weighted_avg_price, fixed_stop_price,
               profit_5_executed, profit_10_executed, pnl_amount, pnl_pct, status }
TradeEvent   { id, stock_code, event_type, quantity, price, occurred_at }
Notification { id, severity: 'CRITICAL'|'WARNING'|'INFO'|'SUCCESS',
               title, body, occurred_at, is_read }
Report       { id, tracked_stock_id, stock_code, stock_name, path_type,
               outcome: 'SUCCESS'|'FAIL', realized_pnl, realized_pnl_pct,
               holding_days, created_at }
SystemStatus { status: 'RUNNING'|'SAFE_MODE'|'RECOVERING', current_time,
               websocket: { connected }, kiwoom_api: { available, rate_limit_used_per_sec, rate_limit_max },
               telegram_bot: { active }, market: { is_open } }
Settings     { general, broker, trading, notifications, security }
```

## 6. 프로토타입 한계 (Production 에서 보강)

- **라우팅**: 단일 `useState('dashboard')` — `react-router` 또는 Next.js routes 로 교체.
- **인증**: 로그인 / TOTP 화면 UI 만, 실제 토큰 처리 없음.
- **차트**: 박스 시각화 / 가격 차트 없음 (PRD 에선 `lightweight-charts` 권장).
- **API**: 모든 호출이 mock. `fetch` / TanStack Query 로 교체.
- **WebSocket**: 단순 `setInterval` 가격 워크. KIS / 키움 WS 클라이언트 필요.
- **i18n**: 한국어 하드코딩. `react-i18next` 도입 시 키 추출 필요.
- **테스트**: 없음. 핵심 BoxWizard 검증 로직은 unit test 필수.
- **접근성**: ARIA 레이블 일부만 적용. Carbon 의 native 컴포넌트 도입 시 자동 해결.

## 7. 즉시 시작하는 법

1. 새 디렉토리에 Vite + React + TS 부트스트랩
2. `@carbon/react`, `@carbon/styles`, `sass` 설치
3. `src/styles/` 의 토큰 / 한국식 손익 색상 / 글꼴만 가져옴 — 컴포넌트 CSS 는 Carbon 이 제공
4. `src/pages/*.js` 의 로직과 레이아웃을 JSX 로 옮김. 컴포넌트는 `@carbon/react` 직접 import.
5. `src/mocks/index.js` 의 데이터를 `tools/seed.ts` 로 옮겨 dev API 응답으로 사용.
6. 라우터 추가, 인증 hook, WebSocket 클라이언트 순으로 채움.

## 8. 주요 파일 우선순위

옮길 때 이 순서로:
1. `carbon-tokens.css` — 디자인 시스템 기반
2. `app.css` 의 `--cds-pnl-*` 변수 + AppShell 레이아웃
3. `tracked-stocks.js` (가장 복잡한 페이지 — 패턴 잡고 나머지 적용)
4. `box-wizard.js` (검증 로직 그대로 옮김)
5. 나머지 페이지

— Claude (V7.1 디자인 프로토타입 작성)
