# V7.1 Frontend (Production)

> Production target: **Vite + React 18 + TypeScript + IBM Carbon Design System v11**.
>
> The vanilla-JS prototype produced by Claude Design lives at `../frontend-prototype/`
> for reference. This directory is the build artifact target consumed by Nginx
> (see `docs/v71/12_SECURITY.md §2.4`).

## Quick start

```bash
# 1. Install dependencies (one time)
npm install

# 2. Dev server with FastAPI proxy (/api -> :8000, /ws -> ws://:8000)
npm run dev
# → http://localhost:5173

# 3. Production build
npm run build

# 4. Preview the production build
npm run preview

# 5. Type-check / tests
npm run typecheck
npm test
```

## Layout

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json + tsconfig.node.json
├── index.html              # #root + Pretendard preload
├── src/
│   ├── main.tsx            # createRoot + QueryClient + Router + Theme
│   ├── App.tsx             # Routes + AppShell
│   ├── components/
│   │   └── shell/
│   │       ├── AppShell.tsx       # Carbon Header + SideNav
│   │       └── PlaceholderPage.tsx
│   ├── pages/              # 9 pages -- placeholders (P5.3 fills them)
│   ├── hooks/
│   │   └── useTheme.ts     # g100 default + localStorage cycle
│   ├── styles/
│   │   ├── main.scss       # @use carbon themes (g100 default)
│   │   ├── _pnl.scss       # 한국식 손익 색상 (수익=빨강, 손실=파랑)
│   │   └── _shell.scss     # AppShell layout
│   ├── test/setup.ts
│   └── types/index.ts      # PRD Patch #3 적용 타입 (TrackedStock 등)
└── README.md (this file)
```

## Phase 5 progress

- [x] **P5.1** -- Claude Design vanilla-JS prototype (`frontend-prototype/`)
- [x] **P5.2** -- Vite + React + TS bootstrap + AppShell + 9 placeholders
- [ ] **P5.3** -- 9 화면 실제 구현 (mock data 우선, 추후 API)
- [ ] **P5.4** -- 백엔드 (FastAPI + JWT + 2FA + REST + WebSocket)
- [ ] **P5.5** -- API/WS wiring + e2e + Phase 5 complete

## PRD Patch #3 적용

`src/types/index.ts`에 적용 완료:
- `TrackedStock`에서 `path_type` 제거. 대신 `summary.path_a_box_count`, `summary.path_b_box_count` 추가.
- `Box.path_type` 필수.
- `Position.path_type`은 트리거 박스로부터 상속 (또는 'MANUAL').

`BoxWizard.tsx`는 7-step UI (Step 1 "경로 선택" 추가) 로 P5.3에서 구현 예정.

## 사용 디자인 시스템

- `@carbon/react` v11+ 컴포넌트만 사용
- `@carbon/icons-react` 만 사용 (`Lucide` 등 금지)
- shadcn/ui / Tailwind / styled-components / MUI 등 다른 디자인 시스템 **금지**
- 차트 라이브러리 **금지** (HTS가 차트 담당)

자세한 룰: `../docs/v71/CLAUDE_DESIGN_PROMPT.md` §2, §9.
