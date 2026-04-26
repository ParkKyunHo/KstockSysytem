# V7.1 K-Stock Trading -- Claude Design Prototype Prompt

> 이 문서는 **Claude Design (claude.ai/design 또는 동급 도구)** 에 단일 입력으로 붙여넣어
> V7.1 시스템의 React + TypeScript 프로토타입을 생성하기 위한 종합 프롬프트입니다.
> 
> 작성자: Claude Code (V7.1 백엔드 빌더)
> 사용자: 박균호 (8년 전업 트레이더, 시스템 소유자)
> 사용 디자인 시스템: **IBM Carbon Design System v11+**

---

## 0. 프롬프트 사용법

```
1. 이 문서 전체를 복사하여 Claude Design에 붙여넣기
2. (선택) Figma 파일 "(v11) Carbon Design System (Community).fig" 업로드 또는 링크
3. Claude Design이 9개 화면 React 프로토타입 + mock data + SCSS를 생성
4. 산출물을 K_stock_trading 프로젝트로 가져와 백엔드 (FastAPI) 와 통합
```

산출물 기대:
- React 18+ + TypeScript 프로젝트 (Vite 기반)
- @carbon/react v11+ 컴포넌트만 사용
- Mock data로 모든 화면이 인터랙티브하게 동작 (실제 API 미연결)
- 9개 화면 모두 구현 (로그인/TOTP/대시보드/종목 등록/박스 설정/추적 종목/포지션/리포트/알림/설정)
- SCSS 기반 한국식 손익 색상 + 다크 모드 (g100) 우선
- 디렉토리 구조: `frontend/src/{pages,components,mocks,hooks,types,styles}/`

---

## 1. 시스템 한 문장 정의

> **사용자가 정의한 박스 구간을, 시스템이 인내심 있게 지키다가 정확히 포착하는 한국 주식 자동매매 시스템의 웹 관제 대시보드.**

### 1.1 사용자 / 환경

```yaml
사용자: 박균호 (8년 전업 트레이더)
시장: 한국 (KOSPI / KOSDAQ)
사용 환경:
  - 데스크톱 메인 (모니터 다수)
  - 모바일 보조 (이동 중 알림 확인)
  - HTS와 병행 사용 (웹 대시보드는 "관제 센터"; 차트는 HTS가 담당)
  - 키보드 단축키 환영 (Carbon 기본 a11y)

핵심 개념:
  박스: 사용자가 정의한 가격 구간 (상단/하단/비중/손절/전략)
  추적 종목: 사용자가 등록한 모니터링 대상 (PATH_A 단타 / PATH_B 중기)
  포지션: 매수 체결된 상태 (시스템 매수 SYSTEM_A/B 또는 사용자 수동 MANUAL)
  알림: 4-등급 (CRITICAL/HIGH/MEDIUM/LOW)
```

---

## 2. 디자인 시스템 절대 룰 (절대 준수)

### 2.1 사용 패키지 (다른 라이브러리 사용 금지)

```bash
npm install @carbon/react @carbon/styles @carbon/icons-react @carbon/grid sass
```

| 카테고리 | 사용해야 할 것 | 절대 금지 |
|----------|---------------|-----------|
| 컴포넌트 | `@carbon/react` v11+ | shadcn/ui, MUI, Ant Design, Chakra UI |
| 스타일 | `@carbon/styles` SCSS + 디자인 토큰 | Tailwind CSS, styled-components, emotion, CSS-in-JS |
| 아이콘 | `@carbon/icons-react` (Icon16/20/24) | Lucide, Heroicons, react-icons, Feather |
| 그리드 | `@carbon/grid` 16-column | CSS Grid 직접, Bootstrap |
| 모션 | `@carbon/motion` (필요 시) | framer-motion, react-spring |
| 차트 | **사용 안 함** (HTS가 담당) | recharts, chart.js, @carbon/charts-react, d3 |

### 2.2 한국식 손익 색상 ★ (절대 핵심)

한국 주식 시장 관례 (서양과 반대):

```scss
// frontend/src/styles/_pnl.scss
.pnl-profit {
  color: var(--cds-support-error);  // 빨강 = 수익 (한국식)
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 600;
  font-feature-settings: "tnum"; // tabular numbers
}

.pnl-loss {
  color: var(--cds-support-info);   // 파랑 = 손실 (한국식)
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 600;
  font-feature-settings: "tnum";
}

.pnl-neutral {
  color: var(--cds-text-secondary);
}
```

**자동으로 서양식(녹색=상승)으로 가지 말 것**. 모든 PnL/등락 표시에서 항상 빨강=수익, 파랑=손실.

### 2.3 다크 모드 (g100) 우선

```jsx
import { Theme } from '@carbon/react';

// App 루트
<Theme theme="g100">  {/* 가장 어두움 -- 트레이더 환경 기본 */}
  <App />
</Theme>
```

토글 옵션: `g100` (다크 강), `g90` (다크 약), `white` (라이트 강), `g10` (라이트 약).
사용자 설정은 localStorage에 persist.

### 2.4 SCSS 글로벌 설정

```scss
// frontend/src/styles/main.scss
@use '@carbon/react/scss/themes';
@use '@carbon/react/scss/theme' with (
  $theme: themes.$g100  // 다크 기본
);
@use '@carbon/styles';

// 폰트: 한글은 Pretendard, 본문은 IBM Plex, 숫자는 IBM Plex Mono
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

body {
  font-family: 'Pretendard', 'IBM Plex Sans KR', 'IBM Plex Sans', sans-serif;
}

.numeric, .price, .pnl, .kpi-value {
  font-family: 'IBM Plex Mono', monospace;
  font-feature-settings: "tnum";
}

@import './pnl';
```

### 2.5 디자인 토큰 사용 (직접 색상 코드 사용 금지)

```scss
// 좋은 예 (Carbon 토큰)
background: var(--cds-layer);
color: var(--cds-text-primary);
border: 1px solid var(--cds-border-subtle);

// 나쁜 예 (직접 색상 -- 금지)
background: #161616;
color: #f4f4f4;
```

### 2.6 5대 디자인 원칙

```yaml
원칙 1: 차트 없음
  HTS가 차트 담당. 텍스트, 숫자, 테이블 중심.
  Carbon DataTable 적극 활용.

원칙 2: 단순함 우선
  필요한 정보만 표시. 화려한 애니메이션 회피.
  Tile + DataTable 조합으로 충분.

원칙 3: 빠른 의사결정
  핵심 정보 즉시 파악 (3초 이내).
  Tag + Notification 활용.

원칙 4: 안전성 강조
  중요 액션 (삭제, 추적 종료, 안전 모드 진입)은 danger Modal로 확인.

원칙 5: 정보 밀도
  전문 트레이더 사용. UI 여백 과다 X. DataTable 컴팩트 모드.
```

---

## 3. 9개 화면 명세

### 3.1 전체 레이아웃 (Carbon UI Shell)

```
┌────────────────────────────────────────────────────────────────────┐
│ Header (48px) -- Carbon Header                                      │
│ ┌─────┬───────────────────────────────────┬───────┬──────────────┐ │
│ │로고 │ HeaderName: V7.1 Trading          │ 🔔(3) │ 👤 박균호 ▼  │ │
│ └─────┴───────────────────────────────────┴───────┴──────────────┘ │
├──────────┬─────────────────────────────────────────────────────────┤
│ SideNav  │                                                          │
│ (256px)  │ Main Content (Carbon Grid 16-column)                     │
│          │                                                          │
│ 📊 대시보드│  Tiles, DataTables, Forms, ...                          │
│ 📋 추적종목│                                                          │
│ 🎯 박스   │                                                          │
│ 💼 포지션 │                                                          │
│ 📄 리포트 │                                                          │
│ 🔔 알림   │                                                          │
│ ⚙️ 설정   │                                                          │
│          │                                                          │
│ 시스템 상태│                                                          │
│ Tag:정상  │                                                          │
└──────────┴─────────────────────────────────────────────────────────┘
```

```jsx
// 사용 컴포넌트
import {
  Theme, Header, HeaderName, HeaderGlobalBar, HeaderGlobalAction,
  HeaderMenuButton, SideNav, SideNavItems, SideNavLink, SideNavDivider,
  Content, Tag, UserAvatar
} from '@carbon/react';
import {
  Dashboard, ListChecked, SquareOutline, ChartLineSmooth,
  Document, Notification, Settings
} from '@carbon/icons-react';
```

라우팅 (React Router v6):

```
/login
/login/totp
/dashboard       → 대시보드 메인
/tracked-stocks  → 추적 종목 리스트
/tracked-stocks/:id → 종목 상세
/boxes/new?stock_id=...  → 박스 설정 마법사 (Step 1~6)
/boxes/:id/edit  → 박스 수정 Modal (overlay)
/positions       → 포지션 모니터
/positions/:id   → 포지션 상세
/reports         → 리포트 리스트
/reports/:id     → 리포트 읽기 (Tabs PART1/PART2)
/notifications   → 알림 센터
/settings        → 설정 (Tabs)
```

---

### 3.2 화면 1: 로그인 (`/login`)

```yaml
목적: ID/PW 1단계 인증
레이아웃: 중앙 정렬 Tile (max-width 384px), 다크 모드 g100
주요 컴포넌트:
  - Theme (g100)
  - Tile
  - Stack (gap 6)
  - TextInput (사용자명)
  - PasswordInput
  - Button (kind="primary", size="lg", full width)
  - InlineNotification (kind="error", 로그인 실패 시)
  - InlineLoading (로그인 중)

상태 (mock):
  idle: 빈 폼
  invalid: 빈 필드 → Button disabled
  loading: 로그인 중 → InlineLoading "로그인 중..."
  error: 실패 → InlineNotification "로그인 실패: 잘못된 ID/PW"
  success: TOTP 페이지로 이동

검증:
  사용자명: 비어있지 않음
  비밀번호: 8자 이상

mock 동작:
  username="admin", password="password" → success → /login/totp
  그 외 → error
```

### 3.3 화면 1-B: TOTP 입력 (`/login/totp`)

```yaml
목적: 6자리 OTP 코드 검증 (Google Authenticator)
주요 컴포넌트:
  - Tile (max-width 384px)
  - 큰 헤더 "2단계 인증" + 설명문
  - TextInput (maxLength=6, 숫자만, 자동 포커스)
  - ProgressBar (다음 코드까지 30초 카운트다운)
  - Button "확인"
  - Button "백업 코드 사용" (kind="ghost", size="sm")

자동 동작:
  6자리 입력 시 자동 verify
  30초 ProgressBar 매초 -1, 0 도달 시 max로 리셋

mock:
  totpCode="123456" → success → /dashboard
  그 외 → "잘못된 코드" InlineNotification
```

---

### 3.4 화면 2: 대시보드 메인 (`/dashboard`)

```yaml
목적: 시스템 전체 상태 한눈에 (가장 자주 보는 화면)
구성 (위에서 아래, Carbon Grid 16-column):
  1. KPI 4개 (각 4 columns)
  2. 시스템 상태 (전체 16)
  3. 진입 임박 박스 (전체 16, DataTable)
  4. 활성 포지션 (전체 16, DataTable)
  5. 오늘 거래 (전체 16, DataTable)
  6. 최근 알림 5건 (전체 16, StructuredList)
```

#### KPI 4개 (Tile)

```jsx
// KPITile 자체 컴포넌트 (Tile + 큰 숫자 + 부제 + ProgressBar 옵션)
<Tile>
  <h4 className="cds--type-helper-text-01">{title}</h4>
  <div className={`kpi-value ${color === 'profit' ? 'pnl-profit' : color === 'loss' ? 'pnl-loss' : ''}`}>
    {value}
  </div>
  <p className="cds--type-helper-text-01">{subtitle}</p>
  {progress !== undefined && <ProgressBar value={progress} max={100} hideLabel />}
</Tile>
```

KPI 항목:
1. **추적 종목**: "12" (subtitle "박스 대기 7")
2. **활성 포지션**: "5" (subtitle "부분청산 2")
3. **자본 사용**: "30.5%" (subtitle "가용 69.5%", ProgressBar)
4. **오늘 손익**: "+245,000원" (subtitle "+1.24%", color=profit → 빨강)

#### 시스템 상태 (Tile + Tag 5개)

```jsx
<Tile>
  <Tag type="green">시스템 정상</Tag>
  <Tag type="green">WebSocket</Tag>
  <Tag type="green">키움 API</Tag>
  <span className="separator" />
  <Tag type="blue">장 진행중 14:23</Tag>
  <span className="cds--type-helper-text-01">마감까지 1h 7m</span>
</Tile>
```

#### 진입 임박 박스 (DataTable)

컬럼: 종목명 / 현재가 / 박스 / 거리 (proximity_pct) / 비중 / 액션 (OverflowMenu)
거리는 +0.27% 같은 형식. 양수면 빨강 클래스, 음수면 파랑.

#### 활성 포지션 (DataTable + Tag)

컬럼: 종목 / 출처 (Tag SYSTEM_A/B/MANUAL) / 수량 / 평단가 / 현재가 / 손익 (PnLCell) / 손절선 / TS (Tag 활성/-)

```jsx
function PnLCell({ amount, pct }) {
  const isProfit = amount > 0;
  return (
    <div className={isProfit ? 'pnl-profit' : 'pnl-loss'}>
      <strong>{isProfit ? '+' : ''}{pct.toFixed(2)}%</strong>
      <div className="cds--type-helper-text-01">
        {isProfit ? '+' : ''}{formatPrice(amount)}원
      </div>
    </div>
  );
}
```

#### 최근 알림 (StructuredList, 5건)

컬럼: 등급 (Tag, severity별 색상) / 제목 / 시간 (HH:MM)

severity → Tag type 매핑:
- CRITICAL → `red`
- HIGH → `magenta` 또는 `warning` 톤
- MEDIUM → `blue`
- LOW → `cool-gray`

---

### 3.5 화면 3: 종목 등록 Modal

```yaml
트리거: 추적 종목 페이지의 "새 종목 추적" 버튼
컴포넌트:
  - Modal (size="md", primary "추적 시작" / secondary "취소")
  - Stack (gap 6)
  - Search (size="lg", "종목명 또는 코드")
  - StructuredList selection (검색 결과, 클릭 시 선택)
  - RadioButtonGroup (경로 선택 PATH_A/PATH_B, vertical)
  - TextArea (메모, rows 3)
  - Dropdown (출처: HTS/뉴스/리포트/직접 분석)

검증:
  selectedStock 필수 + pathType 필수 → primaryButtonDisabled

mock 검색 결과 예시:
  [
    { code: "005930", name: "삼성전자", market: "KOSPI", currentPrice: 73500 },
    { code: "036040", name: "에프알텍", market: "KOSDAQ", currentPrice: 18100 }
  ]
```

---

### 3.6 화면 4: 박스 설정 마법사 (`/boxes/new`)

```yaml
6-Step 마법사:
  Step 1: 가격 범위 (상단/하단)
  Step 2: 진입 전략 (PULLBACK / BREAKOUT)
  Step 3: 비중 (0~30%)
  Step 4: 손절폭 (-10%~-1%)
  Step 5: 확인
  Step 6: 저장 (성공 화면)
```

#### 마법사 헤더

```jsx
<ProgressIndicator currentIndex={currentStep}>
  <ProgressStep label="가격" />
  <ProgressStep label="전략" />
  <ProgressStep label="비중" />
  <ProgressStep label="손절" />
  <ProgressStep label="확인" />
  <ProgressStep label="저장" />
</ProgressIndicator>
```

모바일에서는 `vertical` prop. 하단 네비게이션 버튼: "이전" (kind="secondary") / "다음" 또는 "저장" (kind="primary").

#### Step 1: 가격 범위

```yaml
컴포넌트:
  - 정보 행: 현재가 + 1년 최고/최저
  - NumberInput "박스 상단" (필수)
  - NumberInput "박스 하단" (필수)
  - 박스 폭 표시: "1,000원 (1.37%)"
  - 기존 박스 경고: 같은 종목에 다른 활성 박스가 있으면 InlineNotification (warning)

검증:
  upper > lower (위반 시 invalidText="하단은 상단보다 낮아야 합니다")
  upper, lower > 0
```

#### Step 2: 전략 선택 (TileGroup + RadioTile)

```jsx
<TileGroup legend="진입 전략" name="strategy" valueSelected={strategy} onChange={setStrategy}>
  <RadioTile value="PULLBACK">
    <h4>눌림 (PULLBACK)</h4>
    <p>박스 안에서 양봉 형성 시 매수</p>
    <p className="cds--type-helper-text-01">
      경로 A: 직전봉 + 현재봉 모두 양봉 + 박스 내 종가
    </p>
    <p className="cds--type-helper-text-01">봉 완성 직후 즉시 매수</p>
  </RadioTile>
  <RadioTile value="BREAKOUT">
    <h4>돌파 (BREAKOUT)</h4>
    <p>박스 상단 돌파 시 매수</p>
    <p className="cds--type-helper-text-01">
      종가 &gt; 박스 상단 + 양봉 + 정상 시가 (갭업 제외)
    </p>
  </RadioTile>
</TileGroup>
```

#### Step 3: 비중

- NumberInput "%" (0.1~30, step 0.5) + Slider (시각화)
- Tile 안에 예상 정보: "예상 투입: 30,000,000원 / 예상 수량: 약 408주"
- 한도 검증: 기존 사용 + 신규 합이 30% 이내인지
  - 이내: InlineNotification (success) "한도 내"
  - 초과: InlineNotification (error) "한도 초과"

#### Step 4: 손절폭

- NumberInput (-10~-1%, step 0.5) + Slider
- Tile 안에 예상 손절선: "평단가 73,500 → 손절선 69,825원"
- InlineNotification (info, lowContrast) 단계별 손절 안내:
  - "매수 ~ +5% 미만: 사용자 설정"
  - "+5% 청산 후: -2%"
  - "+10% 청산 후: +4% (본전)"

#### Step 5: 확인 (StructuredList)

```jsx
<StructuredListWrapper>
  <StructuredListBody>
    <StructuredListRow><StructuredListCell>종목</StructuredListCell><StructuredListCell><strong>삼성전자 (005930)</strong></StructuredListCell></StructuredListRow>
    <StructuredListRow><StructuredListCell>경로</StructuredListCell><StructuredListCell>PATH_A</StructuredListCell></StructuredListRow>
    <StructuredListRow><StructuredListCell>가격</StructuredListCell><StructuredListCell>73,000 ~ 74,000원</StructuredListCell></StructuredListRow>
    <StructuredListRow><StructuredListCell>전략</StructuredListCell><StructuredListCell>PULLBACK</StructuredListCell></StructuredListRow>
    <StructuredListRow><StructuredListCell>비중</StructuredListCell><StructuredListCell>10%</StructuredListCell></StructuredListRow>
    <StructuredListRow><StructuredListCell>손절폭</StructuredListCell><StructuredListCell>-5%</StructuredListCell></StructuredListRow>
  </StructuredListBody>
</StructuredListWrapper>
<TextArea labelText="메모 (선택)" rows={2} />
```

#### Step 6: 저장 성공

ToastNotification으로 "박스 저장 완료" 표시 + 추적 종목 페이지로 redirect.

---

### 3.7 화면 5: 추적 종목 관리 (`/tracked-stocks`)

```yaml
구성:
  Page header: 제목 "추적 종목" + 신규 버튼
  TableToolbar: TableToolbarSearch + Dropdown 2개 (status, path) + Button "새 종목 추적"
  DataTable:
    컬럼: 종목명 / 코드 / 경로 / 상태 (Tag) / 박스 / 포지션 / 등록일 / 액션 (OverflowMenu)
  Pagination

상태별 Tag 색상:
  TRACKING: gray
  BOX_SET: blue
  POSITION_OPEN: green
  POSITION_PARTIAL: cyan
  EXITED: cool-gray

OverflowMenu 항목:
  - 박스 추가
  - 메모 수정
  - 리포트 생성
  - 추적 종료 (isDelete + hasDivider)
```

#### 종목 상세 (`/tracked-stocks/:id`)

```yaml
구성:
  Breadcrumb: 추적 종목 > 삼성전자 (005930)
  Tile 헤더: 종목명, 현재가, 등락 (한국식 색상), 메타 (등록일/경로/메모)
  Tabs:
    - 박스 (DataTable: tier, 가격대, 비중, 손절, 전략, 상태)
    - 포지션 (ExpandableTile)
    - 거래 이벤트 (DataTable, 시간순)
```

---

### 3.8 화면 6: 포지션 모니터 (`/positions`)

```yaml
권장: ExpandableTile 카드 형태 (DataTable보다 가독성)

ExpandableTile 위 (above the fold):
  - 종목명 (강조) + 코드 + Tag (source: SYSTEM_A/B/MANUAL) + Tag (status: OPEN/PARTIAL_CLOSED)
  - 우측: 큰 손익 표시 (PnLCell, 한국식 색상)
  - Grid (4 columns): 평단가 / 수량 / 현재가 / 손절선

ExpandableTile 아래 (below the fold):
  - TS 정보 (활성 여부, ts_base_price, ts_stop_price, multiplier)
  - 단계 (profit_5_executed, profit_10_executed)
  - 거래 이벤트 (StructuredList, 시간순)
  - 액션: "수동 매도" (Modal 확인), "정합성 확인" (단일 trigger)

MANUAL 포지션 강조:
  source === 'MANUAL'인 경우 InlineNotification (warning, lowContrast):
  "MANUAL 포지션 -- 시스템 자동 청산 안 함. HTS에서 직접 매도하세요."
```

페이지 헤더에 "정합성 확인" Button (renderIcon={Renew}) -- 클릭 시 ToastNotification "정합성 확인 시작 (예상 30초)".

---

### 3.9 화면 7: 리포트 (`/reports`)

```yaml
리스트 (DataTable):
  컬럼: 종목 / 요청일 / 상태 (Tag) / 모델 / 토큰 / 액션

상태별 표시:
  COMPLETED: 
    Tag(green) "완료" + Button(ghost,sm) "읽기" + Button(ghost,sm,Document icon) "PDF" + Button(ghost,sm) "Excel"
  GENERATING:
    Tag(blue) "생성중" + ProgressBar(value=row.progress, max=100, size="sm")
  FAILED:
    Tag(red) "실패" + Button(danger--tertiary,sm) "재시도"
  PENDING:
    Tag(gray) "대기" + 비활성 액션

상단 "새 리포트 생성" Button:
  Modal:
    - ComboBox (종목 검색)
    - InlineNotification (info, lowContrast) "PART 1: 종목의 이야기 / PART 2: 객관 팩트 (사업/재무/공시)"
    - 사용량 표시: "이번 달 사용량: 5/30"
```

#### 리포트 읽기 (`/reports/:id`)

```yaml
구성:
  Breadcrumb
  Tile 헤더: 종목명, 생성일, 모델, 토큰
  Tabs:
    Tab "PART 1: 이야기" → ReactMarkdown (narrative_part)
    Tab "PART 2: 객관 팩트" → ReactMarkdown (facts_part)
  
  하단:
    TextArea "사용자 메모" (PATCH /api/v71/reports/{id})
    Button "PDF 다운로드" / "Excel 다운로드"
```

---

### 3.10 화면 8: 알림 센터 (`/notifications`)

```yaml
구성:
  Page header: 제목 + 미확인 카운트 Tag
  Filter: Dropdown (severity), Dropdown (status), DatePicker range
  알림 리스트 (InlineNotification 또는 ActionableNotification 다수)
  Pagination

InlineNotification kind 매핑:
  CRITICAL → kind="error" (빨강) + hideCloseButton (자동 닫힘 안 됨)
  HIGH → kind="warning" (주황)
  MEDIUM → kind="info" (파랑)
  LOW → kind="info" + lowContrast (회색)

각 알림:
  title: "[CRITICAL] 손절 실행"
  subtitle: 메시지 본문 (multiline OK)
  caption: "14:23:45" (한국 시간 KST)
  onClose: markAsRead 호출

ActionableNotification (박스 진입 임박 등):
  actionButtonLabel: "박스 보기"
  onActionButtonClick: navigate to box

Toast 알림 (실시간 -- WebSocket):
  ToastNotification 컴포넌트, 우측 상단 fixed position
  CRITICAL: timeout={0} (수동 닫기)
  그 외: timeout={4000} (4초)
```

---

### 3.11 화면 9: 설정 (`/settings`)

```yaml
Tabs (5개):
  - 일반
  - 알림
  - 보안
  - 시스템
  - Telegram
```

#### 일반 탭

```yaml
컴포넌트:
  - NumberInput "총 자본 (원)" + helperText
  - Dropdown "언어" (한국어/English)
  - RadioButtonGroup "테마" (g100/g90/white/system)
  - Button "저장"
```

#### 알림 탭

```yaml
Toggle 4개:
  - CRITICAL 알림 (toggled=true, disabled, helperText="강제 활성")
  - HIGH 알림 (toggled, on/off)
  - MEDIUM 알림 (toggled, on/off)
  - LOW 알림 (toggled, on/off)

Toggle "조용 시간":
  helperText="CRITICAL은 무관"
  활성 시 TimePicker 2개 (시작/종료)
```

#### 보안 탭

```yaml
구성:
  Tile "비밀번호":
    - "마지막 변경: 2026-01-15 (3개월 전)"
    - Button "비밀번호 변경"
  
  Tile "2단계 인증 (TOTP)":
    - Tag(green) "활성화됨"
    - Button "재설정" + Button "백업 코드 새로 생성"
  
  Tile "활성 세션":
    - DataTable: IP, User Agent, 마지막 활동, 액션 "종료"
```

#### 시스템 탭

```yaml
구성:
  Tile "안전 모드":
    - 현재 상태 Tag(blue) "정상 운영" 또는 Tag(red) "안전 모드"
    - Button kind="danger" "안전 모드 진입" (Modal danger 확인)
    - Button kind="secondary" "안전 모드 해제"
  
  Tile "재시작 이력" (DataTable):
    - 시각, 사유, 소요 시간, 상태
  
  Tile "Feature Flags":
    - Toggle 다수 (v71.box_system / v71.exit_v71 / etc.)
    - 일반 사용자에겐 read-only
```

#### Telegram 탭

```yaml
구성:
  Tile "봇 연결":
    - Tag(green) "연결됨" + Bot 이름
    - Button "테스트 메시지 전송"
  
  Tile "Authorized Chat IDs":
    - DataTable: chat_id, 등록일, 액션 "삭제"
    - 입력 + Button "추가"
```

---

## 4. 인터랙션 표준

### 4.1 폼 검증

```yaml
Carbon TextInput / NumberInput:
  invalid={true}              # 빨간 보더
  invalidText="에러 메시지"   # 아래 에러 텍스트

검증 시점:
  - 타이핑 중: 검증 자제 (UX)
  - blur 시: 검증 + 에러 표시
  - 제출 시: 모든 필드 검증
```

### 4.2 로딩 상태

```jsx
// 페이지 로딩
{isLoading ? <SkeletonPlaceholder /> : <ActualContent />}

// 버튼 로딩
{isSubmitting ? <InlineLoading description="저장 중..." /> : <Button onClick={handleSave}>저장</Button>}

// 큰 작업 (리포트 생성)
<ProgressBar label="리포트 생성 중" helperText="예상 5분" value={progress} max={100} />
```

### 4.3 Toast 알림

```jsx
// 우측 상단 fixed position
<div className="toast-container">
  {toasts.map(toast => (
    <ToastNotification
      key={toast.id}
      kind={toast.kind}
      title={toast.title}
      subtitle={toast.subtitle}
      timeout={toast.kind === 'error' ? 0 : 4000}
      onClose={() => dismissToast(toast.id)}
    />
  ))}
</div>
```

### 4.4 확인 다이얼로그 (danger Modal)

```jsx
<Modal
  open={isOpen}
  danger  // 빨간 primary 버튼
  modalHeading="추적 종료"
  primaryButtonText="추적 종료"
  secondaryButtonText="취소"
  onRequestSubmit={handleConfirm}
>
  <p>삼성전자 (005930) 추적을 종료할까요?</p>
  <ul>
    <li>활성 박스 3개 모두 취소됩니다</li>
    <li>시세 모니터링 중지</li>
    <li>이 작업은 되돌릴 수 없습니다</li>
  </ul>
</Modal>
```

### 4.5 키보드 단축키 (제안)

```yaml
전역:
  Cmd/Ctrl + K: 종목 검색 빠른 열기 (Search Modal)
  Cmd/Ctrl + /: 단축키 도움말
  Esc: Modal 닫기 (Carbon 기본)

페이지별:
  대시보드 1~6: 각 KPI 빠르게 포커스
  추적 종목 N: "새 종목 추적" Modal 열기
```

---

## 5. 반응형 (Carbon Grid)

```yaml
Breakpoints:
  sm: 320px+ (모바일)
  md: 672px+ (태블릿)
  lg: 1056px+ (데스크톱)
  xlg: 1312px+ (와이드)
  max: 1584px+ (초와이드)

Grid 사용:
  <Column sm={4} md={4} lg={4}>  → KPI 카드 (md 이상에서 4 columns)
  <Column sm={4} md={8} lg={16}> → 전체 width

모바일 적응:
  Header: HeaderMenuButton (햄버거)
  SideNav: 오버레이로 (overlay prop)
  DataTable: 가로 스크롤 + stickyHeader
  ProgressIndicator: vertical 모드
```

---

## 6. Mock Data 명세 (api spec 형식 그대로)

모든 응답은 다음 wrapper 사용:

```typescript
// 단일 리소스
{ data: T, meta: { request_id: string, timestamp: string } }

// 리스트
{ data: T[], meta: { total: number, limit: number, next_cursor: string | null, request_id: string, timestamp: string } }

// 에러
{ error_code: string, message: string, details?: object, meta: {...} }
```

### 6.1 Mock Data 파일 구조

```
frontend/src/mocks/
├── index.ts            # 통합 export
├── trackedStocks.ts    # 추적 종목 (~12건)
├── boxes.ts            # 박스 (~20건)
├── positions.ts        # 포지션 (~5건)
├── tradeEvents.ts      # 거래 이벤트 (~30건)
├── notifications.ts    # 알림 (~50건)
├── reports.ts          # 리포트 (~10건)
├── system.ts           # 시스템 상태
├── settings.ts         # 설정
└── handlers.ts         # MSW handlers (TanStack Query 통합)
```

### 6.2 핵심 타입 (TypeScript)

```typescript
// frontend/src/types/index.ts

export type PathType = 'PATH_A' | 'PATH_B';
export type StrategyType = 'PULLBACK' | 'BREAKOUT';
export type TrackedStatus = 'TRACKING' | 'BOX_SET' | 'POSITION_OPEN' | 'POSITION_PARTIAL' | 'EXITED';
export type BoxStatus = 'WAITING' | 'TRIGGERED' | 'INVALIDATED' | 'CANCELLED';
export type PositionSource = 'SYSTEM_A' | 'SYSTEM_B' | 'MANUAL';
export type PositionStatus = 'OPEN' | 'PARTIAL_CLOSED' | 'CLOSED';
export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type NotificationStatus = 'PENDING' | 'SENT' | 'FAILED' | 'SUPPRESSED' | 'EXPIRED';
export type NotificationChannel = 'TELEGRAM' | 'WEB' | 'BOTH';
export type ReportStatus = 'PENDING' | 'GENERATING' | 'COMPLETED' | 'FAILED';
export type SystemStatus = 'RUNNING' | 'SAFE_MODE' | 'RECOVERING';

export interface TrackedStock {
  id: string;
  stock_code: string;
  stock_name: string;
  market: 'KOSPI' | 'KOSDAQ';
  path_type: PathType;
  status: TrackedStatus;
  user_memo: string | null;
  source: string | null;
  vi_recovered_today: boolean;
  auto_exit_reason: string | null;
  created_at: string;  // ISO 8601
  last_status_changed_at: string;
  summary: {
    active_box_count: number;
    triggered_box_count: number;
    current_position_qty: number;
    current_position_avg_price: number | null;
  };
}

export interface Box {
  id: string;
  tracked_stock_id: string;
  stock_code: string;
  stock_name: string;
  path_type: PathType;
  box_tier: number;
  upper_price: number;
  lower_price: number;
  position_size_pct: number;  // 0~30
  stop_loss_pct: number;       // -1~-0.01
  strategy_type: StrategyType;
  status: BoxStatus;
  memo: string | null;
  created_at: string;
  triggered_at: string | null;
  invalidated_at: string | null;
  invalidation_reason: string | null;
  next_reminder_at: string | null;
  entry_proximity_pct: number | null;  // 현재가 기준
}

export interface Position {
  id: string;
  source: PositionSource;
  stock_code: string;
  stock_name: string;
  tracked_stock_id: string | null;
  triggered_box_id: string | null;
  initial_avg_price: number;
  weighted_avg_price: number;
  total_quantity: number;
  fixed_stop_price: number;
  profit_5_executed: boolean;
  profit_10_executed: boolean;
  ts_activated: boolean;
  ts_base_price: number | null;
  ts_stop_price: number | null;
  ts_active_multiplier: number | null;
  actual_capital_invested: number;
  status: PositionStatus;
  current_price: number;
  pnl_amount: number;
  pnl_pct: number;
  closed_at: string | null;
  final_pnl: number | null;
  close_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface TradeEvent {
  id: string;
  event_type:
    | 'BUY_EXECUTED' | 'PYRAMID_BUY' | 'MANUAL_PYRAMID_BUY'
    | 'PROFIT_TAKE_5' | 'PROFIT_TAKE_10'
    | 'STOP_LOSS' | 'TS_EXIT' | 'MANUAL_SELL';
  position_id: string;
  stock_code: string;
  quantity: number;
  price: number;
  occurred_at: string;
  events_reset?: boolean;
}

export interface NotificationRecord {
  id: string;
  severity: Severity;
  channel: NotificationChannel;
  event_type: string;
  stock_code: string | null;
  title: string;
  message: string;
  payload: Record<string, unknown> | null;
  status: NotificationStatus;
  priority: 1 | 2 | 3 | 4;
  rate_limit_key: string | null;
  retry_count: number;
  sent_at: string | null;
  failed_at: string | null;
  failure_reason: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface Report {
  id: string;
  stock_code: string;
  stock_name: string;
  status: ReportStatus;
  model_version: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  narrative_part: string | null;  // Markdown
  facts_part: string | null;      // Markdown
  pdf_path: string | null;
  excel_path: string | null;
  user_notes: string | null;
  progress?: number;  // GENERATING 시 0~100
  generation_started_at: string | null;
  generation_completed_at: string | null;
  generation_duration_seconds: number | null;
  error_message?: string;
  created_at: string;
}

export interface SystemStatusData {
  status: SystemStatus;
  uptime_seconds: number;
  websocket: { connected: boolean; last_disconnect_at: string | null; reconnect_count_today: number };
  kiwoom_api: { available: boolean; rate_limit_used_per_sec: number; rate_limit_max: number };
  telegram_bot: { active: boolean; circuit_breaker_state: 'CLOSED' | 'OPEN' | 'HALF_OPEN' };
  database: { connected: boolean; latency_ms: number };
  feature_flags: Record<string, boolean>;
  market: { is_open: boolean; session: 'PRE' | 'REGULAR' | 'POST' | null; next_open_at: string | null; next_close_at: string | null };
  current_time: string;
}
```

### 6.3 Mock Data 예시 (TrackedStock)

```typescript
// frontend/src/mocks/trackedStocks.ts
import { TrackedStock } from '../types';

export const mockTrackedStocks: TrackedStock[] = [
  {
    id: 'ts-001',
    stock_code: '005930',
    stock_name: '삼성전자',
    market: 'KOSPI',
    path_type: 'PATH_A',
    status: 'BOX_SET',
    user_memo: '반도체 사이클 회복 기대',
    source: 'HTS',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: '2026-04-25T01:00:00Z',
    last_status_changed_at: '2026-04-25T03:30:00Z',
    summary: {
      active_box_count: 3,
      triggered_box_count: 0,
      current_position_qty: 0,
      current_position_avg_price: null,
    },
  },
  {
    id: 'ts-002',
    stock_code: '036040',
    stock_name: '에프알텍',
    market: 'KOSDAQ',
    path_type: 'PATH_A',
    status: 'POSITION_OPEN',
    user_memo: null,
    source: '뉴스',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: '2026-04-22T05:00:00Z',
    last_status_changed_at: '2026-04-26T01:30:00Z',
    summary: {
      active_box_count: 1,
      triggered_box_count: 1,
      current_position_qty: 100,
      current_position_avg_price: 18100,
    },
  },
  // ... ~10건 더
];
```

### 6.4 Mock 시나리오 (실시간 시뮬레이션)

WebSocket 연결을 mock하기 위해 setInterval로 시뮬레이트:

```typescript
// frontend/src/mocks/wsSimulator.ts
import { useEffect } from 'react';

export function useMockWebSocket(handlers: { onPriceUpdate: (data) => void; onNewNotification: (data) => void; }) {
  useEffect(() => {
    const interval = setInterval(() => {
      // 매 1초: 활성 포지션 가격 ±0.1% 변동 (랜덤)
      handlers.onPriceUpdate({
        position_id: 'pos-001',
        current_price: Math.round(74000 + Math.random() * 200 - 100),
        pnl_amount: Math.round(Math.random() * 100000 - 50000),
        pnl_pct: (Math.random() * 0.04 - 0.02),
      });
    }, 1000);

    const notifInterval = setInterval(() => {
      // 매 30초: 새 알림
      const severities: Severity[] = ['HIGH', 'MEDIUM', 'LOW'];
      handlers.onNewNotification({
        id: `n-${Date.now()}`,
        severity: severities[Math.floor(Math.random() * 3)],
        title: '박스 진입 임박',
        message: '...',
        created_at: new Date().toISOString(),
      });
    }, 30000);

    return () => { clearInterval(interval); clearInterval(notifInterval); };
  }, [handlers]);
}
```

---

## 7. 산출물 디렉토리 구조

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx                  # Theme + Router + Providers
│   ├── pages/
│   │   ├── Login.tsx
│   │   ├── LoginTotp.tsx
│   │   ├── Dashboard.tsx
│   │   ├── TrackedStocks.tsx
│   │   ├── TrackedStockDetail.tsx
│   │   ├── BoxWizard.tsx        # 6-step
│   │   ├── Positions.tsx
│   │   ├── PositionDetail.tsx
│   │   ├── Reports.tsx
│   │   ├── ReportDetail.tsx
│   │   ├── Notifications.tsx
│   │   └── Settings.tsx
│   ├── components/
│   │   ├── shell/                # AppShell (Header + SideNav)
│   │   │   ├── AppShell.tsx
│   │   │   ├── AppHeader.tsx
│   │   │   └── AppSideNav.tsx
│   │   ├── kpi/
│   │   │   └── KPITile.tsx
│   │   ├── pnl/
│   │   │   └── PnLCell.tsx
│   │   ├── tags/
│   │   │   └── StatusTag.tsx     # severity / box / position 통합
│   │   ├── modals/
│   │   │   ├── NewTrackedStockModal.tsx
│   │   │   ├── EditBoxModal.tsx
│   │   │   ├── ConfirmDangerModal.tsx
│   │   │   └── NewReportModal.tsx
│   │   └── notifications/
│   │       ├── NotificationToast.tsx
│   │       └── NotificationItem.tsx
│   ├── mocks/                    # 위 §6.1 구조
│   ├── hooks/
│   │   ├── useTheme.ts
│   │   ├── useMockWebSocket.ts
│   │   └── useFormatters.ts      # formatPrice / formatPct / formatTime
│   ├── types/
│   │   └── index.ts              # 위 §6.2 타입
│   └── styles/
│       ├── main.scss             # @use carbon + 폰트
│       ├── _pnl.scss             # 한국식 손익 색상
│       └── _shell.scss
└── public/
```

---

## 8. 헌법 5원칙 (절대)

```yaml
원칙 1: 사용자 판단 불가침
  - 자동 추천 UI 없음 (예: "이 종목 어때요?" X)
  - 검색만 (사용자가 직접 결정)
  - 손절선 PATCH 직접 수정 금지 (시스템이 단계별 룰로 자동 계산)

원칙 2: NFR1 최우선 (박스 진입 절대 놓치지 않음)
  - 가격 표시 latency < 1초
  - WebSocket 끊김 즉시 시각적 피드백 (시스템 상태 영역)

원칙 3: 충돌 금지
  - V7.0 인프라와 분리 (격리)
  - shadcn/ui / Tailwind 등 다른 디자인 시스템 절대 혼용 금지
  - Carbon 디자인 토큰만 사용

원칙 4: 시스템 계속 운영
  - 자동 정지 UI 없음 (모든 stop은 사용자 명시 액션)
  - 안전 모드 진입은 danger Modal로 사용자 확인
  - 폴백 UI: 데이터 로딩 실패 시 InlineNotification + 재시도 버튼

원칙 5: 단순함 우선
  - 화려한 애니메이션 회피 (Carbon 기본 motion만)
  - 차트 없음 (HTS 의존)
  - 폼은 React Hook Form + Zod로 단순하게
  - 상태 관리는 TanStack Query (서버) + useState (로컬) 또는 Zustand (글로벌)
```

---

## 9. 절대 금지 사항 (재확인)

```yaml
디자인:
  ❌ shadcn/ui (참고 자료가 있어도 Carbon으로 변환)
  ❌ Tailwind CSS (Carbon SCSS와 충돌)
  ❌ Material-UI / Ant Design / Chakra UI / Mantine
  ❌ styled-components / emotion / linaria 등 CSS-in-JS

아이콘:
  ❌ Lucide React, Heroicons, react-icons, Feather
  ✅ @carbon/icons-react (Icon16/20/24/32만)

차트:
  ❌ recharts, chart.js, victory, plotly
  ❌ @carbon/charts-react (Phase 5 시점에는 사용 안 함)
  ✅ 차트 자체를 그리지 않음 -- 텍스트, 숫자, 테이블

색상:
  ❌ 직접 hex / rgb 색상 코드
  ❌ 서양식 손익 (녹색=상승)
  ✅ Carbon 디자인 토큰 (var(--cds-*))
  ✅ 한국식 손익 (빨강=수익, 파랑=손실)

폰트:
  ❌ 임의 웹폰트 (Inter, Roboto, Noto Sans 등)
  ✅ Pretendard (한글) + IBM Plex Sans / Mono (Carbon 기본)

상태 관리:
  ❌ Redux (Carbon 환경엔 과함)
  ❌ MobX
  ✅ TanStack Query (서버 상태) + Zustand (필요 시 글로벌) + useState (로컬)

폼:
  ✅ React Hook Form + Zod
  ❌ Formik (가능하지만 헌법 5 위반 -- 더 무거움)
```

---

## 10. 변환 매핑 (혹시 shadcn/ui 인지가 있을 경우)

| shadcn/ui | Carbon (사용해야 함) |
|-----------|---------------------|
| Button | Button (kind: primary/secondary/tertiary/ghost/danger) |
| Dialog | Modal |
| AlertDialog | Modal (danger prop) |
| Sheet | Modal (passiveModal, full size) |
| Drawer | Modal (full, 모바일) |
| Card | Tile / ExpandableTile / ClickableTile |
| Table | DataTable |
| Tabs | Tabs (TabList, Tab, TabPanels, TabPanel) |
| Badge | Tag |
| Toast (Sonner) | ToastNotification |
| Input | TextInput |
| NumberInput (커스텀) | NumberInput |
| Textarea | TextArea |
| Select | Dropdown |
| Combobox | ComboBox |
| Checkbox | Checkbox |
| Switch | Toggle |
| RadioGroup | RadioButtonGroup (RadioButton) |
| Skeleton | SkeletonText / SkeletonPlaceholder |
| DropdownMenu | OverflowMenu (OverflowMenuItem) |
| Tooltip | Tooltip |
| Avatar | UserAvatar (icon) |
| Progress | ProgressBar |
| Slider | Slider |
| Lucide 아이콘 | @carbon/icons-react |

---

## 11. 빌드 + 의존성

```jsonc
// package.json
{
  "name": "k-stock-trading-frontend",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext ts,tsx",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@carbon/react": "^1.71.0",
    "@carbon/styles": "^1.71.0",
    "@carbon/icons-react": "^11.55.0",
    "@carbon/grid": "^11.31.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.27.0",
    "@tanstack/react-query": "^5.59.0",
    "react-hook-form": "^7.53.0",
    "zod": "^3.23.0",
    "@hookform/resolvers": "^3.9.0",
    "react-markdown": "^9.0.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "sass": "^1.80.0",
    "eslint": "^9.12.0",
    "@typescript-eslint/parser": "^8.8.0",
    "@typescript-eslint/eslint-plugin": "^8.8.0",
    "vitest": "^2.1.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/jest-dom": "^6.5.0"
  }
}
```

```ts
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',  // FastAPI dev server
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
});
```

---

## 12. 산출물 검증 체크리스트

Claude Design 산출물이 다음 항목을 모두 만족해야 합니다:

```yaml
디자인 시스템:
  ☐ @carbon/react v11+ 만 사용 (다른 UI lib 0건)
  ☐ shadcn/ui / Tailwind / Lucide 흔적 0건 (package.json + 코드)
  ☐ SCSS 빌드 성공 (sass 컴파일)
  ☐ Theme g100 기본 적용

색상:
  ☐ 한국식 손익 색상 적용 (수익 = var(--cds-support-error), 손실 = var(--cds-support-info))
  ☐ 직접 hex 색상 코드 0건 (Carbon 토큰만)
  ☐ 다크/라이트 모드 토글 동작

화면:
  ☐ 9개 화면 모두 라우팅 동작
  ☐ Mock data로 실제 사용자 시나리오 시뮬레이트
  ☐ DataTable 정렬/필터/페이지네이션 정상
  ☐ Modal (일반 / danger) 동작
  ☐ Notification (Inline / Toast / Actionable) 표시

타입:
  ☐ TypeScript strict 모드
  ☐ 모든 mock data가 §6.2 타입 인터페이스를 만족
  ☐ tsc --noEmit 통과

반응형:
  ☐ Carbon Grid (sm/md/lg/xlg/max) 사용
  ☐ 모바일 (sm) 에서도 메뉴/테이블 동작
  ☐ Header 햄버거 (HeaderMenuButton) 모바일 표시

WebSocket:
  ☐ useMockWebSocket으로 실시간 시뮬레이션
  ☐ 가격 업데이트 1초 간격
  ☐ 새 알림 30초 간격 (Toast 표시)

폼:
  ☐ React Hook Form + Zod 사용
  ☐ Carbon TextInput invalid + invalidText 적용

빌드:
  ☐ `npm run build` 성공
  ☐ `npm run typecheck` 통과
```

---

## 13. 작업 시작 명령

Claude Design에 다음 형식으로 요청:

> 위 명세에 따라 **V7.1 K-Stock Trading 웹 대시보드**의 React + TypeScript + Vite 프로토타입을
> @carbon/react v11+ 기반으로 생성해주세요.
> 9개 화면 (로그인 / TOTP / 대시보드 / 종목 등록 / 박스 설정 / 추적 종목 / 포지션 / 리포트 / 알림 / 설정)
> 모두 mock data로 인터랙티브하게 동작해야 하며, 한국식 손익 색상 (수익=빨강 / 손실=파랑) 과
> 다크 모드 (g100) 를 우선 적용합니다.
>
> 산출물은 `frontend/` 디렉토리 구조로, 위 §7의 구조와 §11의 package.json을 따라 작성해주세요.
> shadcn/ui, Tailwind, Lucide 등 Carbon 외 디자인 라이브러리는 절대 사용하지 마세요.

---

*이 프롬프트는 V7.1 시스템 백엔드 (Phase 0~4 완료) 와 통합되는 프론트엔드 프로토타입을 생성하기 위한 입력입니다.*
*최종 업데이트: 2026-04-26*
*프로토타입 생성 완료 후 Claude Code (백엔드 빌더) 에게 산출물을 인계하면 Phase 5+ 통합을 진행합니다.*
