# V7.1 UI 가이드 - Carbon Design System 버전

> 이 문서는 V7.1 시스템의 **웹 대시보드 UI/UX**를 정의합니다.
> 
> **IBM Carbon Design System** 기준으로 작성됨.
> 
> **Claude Design 작업의 단일 입력 문서**입니다.
> 
> ※ 원본: 10_UI_GUIDE.md (shadcn/ui 기준, 참고용)

---

## 목차

- [§0. 디자인 철학](#0-디자인-철학)
- [§1. Carbon Design System](#1-carbon-design-system)
- [§2. 전체 레이아웃](#2-전체-레이아웃)
- [§3. 화면 1: 로그인 + 2FA](#3-화면-1-로그인--2fa)
- [§4. 화면 2: 대시보드 (메인)](#4-화면-2-대시보드-메인)
- [§5. 화면 3: 종목 등록](#5-화면-3-종목-등록)
- [§6. 화면 4: 박스 설정 (Step 1~6)](#6-화면-4-박스-설정-step-16)
- [§7. 화면 5: 추적 종목 관리](#7-화면-5-추적-종목-관리)
- [§8. 화면 6: 포지션 모니터](#8-화면-6-포지션-모니터)
- [§9. 화면 7: 리포트](#9-화면-7-리포트)
- [§10. 화면 8: 알림 센터](#10-화면-8-알림-센터)
- [§11. 화면 9: 설정](#11-화면-9-설정)
- [§12. 인터랙션 표준](#12-인터랙션-표준)
- [§13. 반응형 디자인](#13-반응형-디자인)
- [§14. 다크 모드 (Carbon 테마)](#14-다크-모드-carbon-테마)

---

## §0. 디자인 철학

### 0.1 5대 원칙

```yaml
원칙 1: 차트 없음
  HTS가 차트를 제공함
  웹 대시보드는 "관제 센터" 역할
  → 텍스트, 숫자, 테이블 중심
  → Carbon DataTable 적극 활용

원칙 2: 단순함 우선 (헌법 5)
  필요한 정보만 표시
  Carbon의 Tile + DataTable 조합으로 충분
  과도한 시각화 회피

원칙 3: 빠른 의사결정
  핵심 정보 즉시 파악
  3초 이내 상태 인식
  Carbon의 Tag + Notification 활용

원칙 4: 안전성 강조
  중요 액션은 Modal 확인
  손절/매도 등 위험 작업 강조
  Carbon의 danger Modal 사용

원칙 5: 일관성
  Carbon Design System 자체가 일관성 보장
  규칙 일탈 금지
```

### 0.2 사용 시나리오

```yaml
주요 사용 패턴:
  1. 아침 09:00: 전체 추적 종목 점검
  2. 장중: 알림 받고 빠르게 확인
  3. 점심: 박스 설정 추가
  4. 장 마감 후: 일일 마감 검토
  5. 주말: 추적 종목 리뷰

핵심 페이지 사용 빈도:
  대시보드: 매일 수시로 (가장 많이)
  포지션 모니터: 보유 시 자주
  추적 종목 관리: 1일 1회
  박스 설정: 신규 종목 추가 시 (주 2~3회)
  리포트: 월 1~2회 (필요 시)
  알림 센터: 알림 확인 시
  설정: 거의 안 봄
```

### 0.3 대상 사용자

```yaml
사용자: 박균호 (8년 전업 트레이더)
  - 데스크톱 메인 (모니터 다수)
  - 모바일 보조 (이동 중)
  - HTS와 병행 사용
  - 키보드 단축키 환영
  - 정보 밀도 높게 선호 (전문가)
  - 화려한 애니메이션 비선호

→ Carbon Design System의 엔터프라이즈 스타일과 정합
```

---

## §1. Carbon Design System

### 1.1 기술 스택

```yaml
프레임워크: React 18+
디자인 시스템: IBM Carbon Design System v11+
컴포넌트: @carbon/react
스타일: @carbon/styles (SCSS)
아이콘: @carbon/icons-react
그리드: @carbon/grid (16-column)
모션: @carbon/motion

상태 관리:
  - 서버 상태: TanStack Query (React Query)
  - 클라이언트 상태: Zustand 또는 useState

라우팅: React Router v6
폼: React Hook Form + Zod
차트: 사용 안 함 (필요 최소 시 @carbon/charts-react)
```

### 1.2 패키지 설치

```bash
npm install @carbon/react @carbon/styles @carbon/icons-react @carbon/grid sass
```

### 1.3 Carbon 테마

```yaml
다크 모드 우선:
  g100 (가장 어두움)  ← 권장 (트레이더 환경)
  g90 (어두움)
  
라이트 모드 (선택):
  white (가장 밝음)
  g10 (밝음)

테마 적용:
  <Theme theme="g100">
    <App />
  </Theme>
```

### 1.4 색상 토큰 (Carbon Design Tokens)

```yaml
의미별 색상:

상태 색상 (Carbon Tag 사용):
  TRACKING: gray (Tag type)
  BOX_SET: blue
  POSITION_OPEN: green
  POSITION_PARTIAL: cyan
  EXITED: cool-gray

손익 색상 (한국식 ★ 중요):
  수익 (양수): support-error (빨강 계열)
                또는 red-50/60
  손실 (음수): support-info (파랑 계열)
                또는 blue-50/60
  중립 (0): text-secondary

★ 한국 주식: 빨강=상승, 파랑=하락 (서양 표준과 반대)

알림 등급 (Notification 사용):
  CRITICAL: error notification (빨강)
  HIGH: warning notification (주황/노랑)
  MEDIUM: info notification (파랑)
  LOW: notification (회색)

Carbon Token 사용 (직접 색상 코드 사용 X):
  background, layer-01, layer-02
  text-primary, text-secondary, text-on-color
  border-subtle, border-strong
  support-error, support-warning, support-info, support-success
  interactive (액션)
```

### 1.5 타이포그래피 (Carbon Type Tokens)

```yaml
폰트 패밀리:
  본문: IBM Plex Sans (Carbon 기본)
  한글: Pretendard 또는 IBM Plex Sans KR
  숫자: IBM Plex Mono (정렬 + 가독성)

Carbon Type Tokens:
  헤딩:
    productive-heading-01 (Body Compact 01) ~ 07
    expressive-heading-01 ~ 06
  
  본문:
    body-compact-01 (14px)
    body-01 (14px regular)
    body-02 (16px)
    body-long-01 (14px, 더 긴 행간)
  
  도우미:
    helper-text-01 (12px)
    label-01 (12px)
    caption-01 (12px)

V7.1 매핑:
  페이지 제목 (H1): productive-heading-04 (28px)
  섹션 제목 (H2): productive-heading-03 (20px)
  카드 제목: productive-heading-02 (16px)
  본문: body-01
  메타 정보: helper-text-01
  핵심 숫자 (손익): expressive-heading-04 또는 05 (모노스페이스)

숫자 포맷:
  가격: 73,500 (천 단위 콤마)
  비율: +5.23% (소수점 둘째 자리)
  수량: 100주
  손익: +245,000원 (부호 표시)
```

### 1.6 간격 (Spacing Tokens)

```yaml
Carbon Spacing Tokens:
  spacing-01: 0.125rem (2px)
  spacing-02: 0.25rem (4px)
  spacing-03: 0.5rem (8px)
  spacing-04: 0.75rem (12px)
  spacing-05: 1rem (16px)
  spacing-06: 1.5rem (24px)
  spacing-07: 2rem (32px)
  spacing-08: 2.5rem (40px)
  spacing-09: 3rem (48px)
  spacing-10: 4rem (64px)
  spacing-11: 5rem (80px)
  spacing-12: 6rem (96px)
  spacing-13: 10rem (160px)

V7.1 사용:
  Tile 안 패딩: spacing-05 (16px) 또는 spacing-06 (24px)
  Tile 간 간격: spacing-05
  섹션 간 간격: spacing-07
  폼 필드 간격: spacing-05
  버튼 그룹: spacing-03
```

### 1.7 핵심 Carbon 컴포넌트

```yaml
필수 컴포넌트:

레이아웃:
  - Theme (테마 적용)
  - Grid, Column (16-column 그리드)
  - Tile, ClickableTile, ExpandableTile (카드)
  - Stack (수직 정렬)

네비게이션:
  - Header, HeaderName, HeaderGlobalBar
  - SideNav, SideNavItems, SideNavLink
  - HeaderMenuItem
  - Breadcrumb

폼:
  - Button (primary, secondary, tertiary, ghost, danger)
  - TextInput, NumberInput, PasswordInput, TextArea
  - Dropdown, ComboBox, MultiSelect
  - Checkbox, RadioButton, Toggle
  - DatePicker
  - FormGroup, FormLabel
  - InlineLoading (버튼 로딩)

데이터 표시:
  - DataTable (정렬, 필터, 페이지네이션)
  - Tag (상태)
  - Tabs, Tab, TabPanels, TabPanel
  - StructuredList
  - ProgressBar, ProgressIndicator

피드백:
  - Modal (다이얼로그)
  - Notification (Toast/Inline/Actionable)
  - InlineNotification
  - ToastNotification
  - ActionableNotification
  - Tooltip
  - Loading
  - SkeletonText, SkeletonPlaceholder

기타:
  - OverflowMenu (드롭다운 메뉴)
  - Pagination
  - Search
  - Link
  - CodeSnippet
```

### 1.8 아이콘

```yaml
라이브러리: @carbon/icons-react

크기 (필수 명시):
  - Icon16 (16x16) - 인라인 아이콘
  - Icon20 (20x20) - 일반
  - Icon24 (24x24) - 헤더
  - Icon32 (32x32) - 큰 강조

주요 아이콘 (V7.1):
  메뉴:
    Dashboard - 대시보드
    ListChecked - 추적 종목
    SquareOutline - 박스 (또는 Box32 커스텀)
    ChartLineSmooth - 포지션 (대안: TableSplit)
    Document - 리포트
    Notification - 알림
    Settings - 설정
  
  상태:
    Information, Warning, ErrorFilled, CheckmarkFilled
  
  액션:
    Add, Edit, TrashCan, Save, Close, Checkmark, ChevronRight
  
  거래:
    TrendingUp, TrendingDown
    ArrowUp, ArrowDown
  
  알림:
    Notification, NotificationFilled, NotificationOff
  
  사용자:
    User, UserAvatar, Logout, Locked, Password, ShieldCheck

import 예시:
  import { Dashboard, Notification, Settings } from '@carbon/icons-react';
  
  사용:
  <Dashboard size={20} />
```

---

## §2. 전체 레이아웃

### 2.1 데스크톱 레이아웃 (Carbon UI Shell)

```
┌────────────────────────────────────────────────────────────────────┐
│ Header (높이 48px) - Carbon Header                                  │
│ ┌─────┬───────────────────────────────────┬───────┬──────────────┐ │
│ │Logo │ HeaderName: V7.1 Trading          │ 🔔(3) │ 👤 박균호 ▼  │ │
│ │     │ HeaderGlobalBar:                  │       │              │ │
│ └─────┴───────────────────────────────────┴───────┴──────────────┘ │
├──────────┬─────────────────────────────────────────────────────────┤
│ SideNav  │                                                          │
│ (256px)  │ Main Content (Grid)                                      │
│          │                                                          │
│ 📊 대시  │  Grid sm/md/lg/xl/max (16-column)                        │
│ 📋 추적  │                                                          │
│ 🎯 박스  │  Tiles, DataTables, ...                                  │
│ 💼 포지  │                                                          │
│ 📄 리포  │                                                          │
│ 🔔 알림  │                                                          │
│ ⚙️ 설정  │                                                          │
│          │                                                          │
│ ─────    │                                                          │
│ 시스템   │                                                          │
│ 상태     │                                                          │
│ Tag:정상 │                                                          │
│          │                                                          │
└──────────┴─────────────────────────────────────────────────────────┘
                                          
                              Bottom: Footer (선택, 시스템 상태)
```

### 2.2 사이드바 메뉴 (SideNav)

```jsx
import { 
  SideNav, SideNavItems, SideNavMenu, SideNavLink, 
  SideNavDivider 
} from '@carbon/react';
import { 
  Dashboard, ListChecked, SquareOutline, 
  ChartLineSmooth, Document, Notification, Settings 
} from '@carbon/icons-react';

<SideNav aria-label="Side navigation" expanded>
  <SideNavItems>
    <SideNavLink renderIcon={Dashboard} href="/dashboard">
      대시보드
    </SideNavLink>
    <SideNavLink renderIcon={ListChecked} href="/tracked-stocks">
      추적 종목
    </SideNavLink>
    <SideNavLink renderIcon={SquareOutline} href="/boxes">
      박스 설정
    </SideNavLink>
    <SideNavLink renderIcon={ChartLineSmooth} href="/positions">
      포지션
    </SideNavLink>
    <SideNavLink renderIcon={Document} href="/reports">
      리포트
    </SideNavLink>
    <SideNavLink renderIcon={Notification} href="/notifications">
      알림
    </SideNavLink>
    <SideNavLink renderIcon={Settings} href="/settings">
      설정
    </SideNavLink>
    
    <SideNavDivider />
    
    {/* 시스템 상태 영역 */}
    <div style={{ padding: 'var(--cds-spacing-05)' }}>
      <Tag type="green" size="sm">시스템 정상</Tag>
      <Tag type="green" size="sm">WebSocket</Tag>
      <Tag type="green" size="sm">키움 API</Tag>
    </div>
  </SideNavItems>
</SideNav>
```

### 2.3 Header

```jsx
import { 
  Header, HeaderName, HeaderGlobalBar, 
  HeaderGlobalAction, HeaderMenuButton 
} from '@carbon/react';

<Header aria-label="V7.1 Trading">
  <HeaderMenuButton aria-label="메뉴 열기" onClick={toggleSideNav} />
  <HeaderName href="/dashboard" prefix="">
    V7.1 Trading
  </HeaderName>
  
  <HeaderGlobalBar>
    {/* 알림 */}
    <HeaderGlobalAction 
      aria-label="알림 (3)" 
      onClick={openNotifications}
    >
      <Notification size={20} />
      {unreadCount > 0 && (
        <Tag type="red" size="sm">{unreadCount}</Tag>
      )}
    </HeaderGlobalAction>
    
    {/* 사용자 메뉴 */}
    <HeaderGlobalAction aria-label="사용자 메뉴">
      <UserAvatar size={20} />
    </HeaderGlobalAction>
  </HeaderGlobalBar>
</Header>
```

---

## §3. 화면 1: 로그인 + 2FA

### 3.1 로그인 페이지 (/login)

```yaml
컴포넌트:
  - Theme (g100 다크)
  - Tile (중앙 정렬)
  - TextInput (사용자명)
  - PasswordInput (비밀번호)
  - Button (primary)
  - InlineNotification (에러 시)

레이아웃:
  중앙 정렬, 384px 너비 Tile
```

```jsx
import { 
  Theme, Tile, TextInput, PasswordInput, 
  Button, Stack, InlineNotification, InlineLoading 
} from '@carbon/react';

<Theme theme="g100">
  <div className="login-container">
    <Tile className="login-tile" style={{ maxWidth: '384px' }}>
      <Stack gap={6}>
        <div className="login-logo">
          <h1>V7.1</h1>
          <p>K-Stock Trading</p>
        </div>
        
        {error && (
          <InlineNotification
            kind="error"
            title="로그인 실패"
            subtitle={errorMessage}
            hideCloseButton
          />
        )}
        
        <TextInput
          id="username"
          labelText="사용자명"
          placeholder="아이디 입력"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        
        <PasswordInput
          id="password"
          labelText="비밀번호"
          placeholder="비밀번호 입력"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        
        {isLoading ? (
          <InlineLoading description="로그인 중..." />
        ) : (
          <Button 
            kind="primary" 
            size="lg" 
            onClick={handleLogin}
            disabled={!username || !password}
          >
            로그인
          </Button>
        )}
      </Stack>
    </Tile>
  </div>
</Theme>
```

### 3.2 TOTP 입력 페이지 (/login/totp)

```yaml
컴포넌트:
  - Tile
  - 6개 분리된 TextInput (또는 단일 TextInput maxLength={6})
  - Button
  - 30초 타이머 (ProgressBar)
```

```jsx
<Theme theme="g100">
  <Tile className="totp-tile">
    <Stack gap={6}>
      <div>
        <h2>2단계 인증</h2>
        <p>Google Authenticator의 6자리 코드 입력</p>
      </div>
      
      <TextInput
        id="totp"
        labelText="TOTP 코드"
        placeholder="6자리 숫자"
        maxLength={6}
        value={totpCode}
        onChange={(e) => {
          setTotpCode(e.target.value);
          if (e.target.value.length === 6) {
            handleVerify();
          }
        }}
      />
      
      <ProgressBar 
        label="다음 코드까지" 
        value={timeRemaining} 
        max={30} 
      />
      
      <Stack gap={3}>
        <Button kind="primary" onClick={handleVerify}>
          확인
        </Button>
        <Button kind="ghost" size="sm">
          백업 코드 사용
        </Button>
      </Stack>
    </Stack>
  </Tile>
</Theme>
```

---

## §4. 화면 2: 대시보드 (메인)

### 4.1 레이아웃 (16-column Grid)

```yaml
구성 (위에서 아래):
  1. KPI 4개 (각 4 columns)
  2. 시스템 상태 (전체 16)
  3. 진입 임박 박스 (전체 16)
  4. 활성 포지션 (전체 16)
  5. 오늘 거래 (전체 16)
  6. 최근 알림 (전체 16)
```

```jsx
import { Grid, Column, Tile } from '@carbon/react';

<Grid>
  {/* KPI 카드 4개 */}
  <Column sm={4} md={4} lg={4}>
    <KPITile title="추적 종목" value="12" subtitle="박스 대기 7" />
  </Column>
  <Column sm={4} md={4} lg={4}>
    <KPITile title="활성 포지션" value="5" subtitle="부분청산 2" />
  </Column>
  <Column sm={4} md={4} lg={4}>
    <KPITile title="자본 사용" value="30.5%" subtitle="가용 69.5%" 
             progress={30.5} />
  </Column>
  <Column sm={4} md={4} lg={4}>
    <KPITile title="오늘 손익" value="+245,000원" subtitle="+1.24%" 
             color="profit" />
  </Column>
</Grid>
```

### 4.2 KPI 카드 (Tile)

```jsx
import { Tile, ProgressBar } from '@carbon/react';

function KPITile({ title, value, subtitle, color, progress }) {
  return (
    <Tile>
      <h4 className="cds--type-helper-text-01">{title}</h4>
      <div 
        className={`kpi-value ${color === 'profit' ? 'profit' : color === 'loss' ? 'loss' : ''}`}
      >
        {value}
      </div>
      <p className="cds--type-helper-text-01">{subtitle}</p>
      {progress !== undefined && (
        <ProgressBar value={progress} max={100} hideLabel />
      )}
    </Tile>
  );
}

// SCSS:
// .kpi-value { 
//   font-size: 2rem; 
//   font-family: 'IBM Plex Mono';
//   font-weight: 600; 
// }
// .kpi-value.profit { color: var(--cds-support-error); }
// .kpi-value.loss { color: var(--cds-support-info); }
```

### 4.3 시스템 상태 (한 줄)

```jsx
import { Tile, Tag } from '@carbon/react';

<Column sm={4} md={8} lg={16}>
  <Tile>
    <div className="status-row">
      <Tag type="green">시스템 정상</Tag>
      <Tag type="green">WebSocket</Tag>
      <Tag type="green">키움 API</Tag>
      <span className="separator" />
      <Tag type="blue">장 진행중 14:23</Tag>
      <span className="text-helper">마감까지 1h 7m</span>
    </div>
  </Tile>
</Column>
```

### 4.4 진입 임박 박스 (DataTable)

```jsx
import { 
  DataTable, Table, TableHead, TableRow, TableHeader, 
  TableBody, TableCell, TableContainer 
} from '@carbon/react';

const headers = [
  { key: 'stock', header: '종목명' },
  { key: 'currentPrice', header: '현재가' },
  { key: 'box', header: '박스' },
  { key: 'distance', header: '거리' },
  { key: 'size', header: '비중' },
];

<Column sm={4} md={8} lg={16}>
  <DataTable rows={imminentBoxes} headers={headers}>
    {({ rows, headers, getHeaderProps, getRowProps, getTableProps }) => (
      <TableContainer 
        title="진입 임박 박스" 
        description={`${imminentBoxes.length}개`}
      >
        <Table {...getTableProps()}>
          <TableHead>
            <TableRow>
              {headers.map(header => (
                <TableHeader {...getHeaderProps({ header })}>
                  {header.header}
                </TableHeader>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map(row => (
              <TableRow {...getRowProps({ row })}>
                {row.cells.map(cell => (
                  <TableCell key={cell.id}>{cell.value}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    )}
  </DataTable>
</Column>
```

### 4.5 활성 포지션 (DataTable + Tag)

```jsx
const positionRows = positions.map(p => ({
  id: p.id,
  stock: `${p.stockName}\n${p.stockCode}`,
  source: <Tag type={getSourceTagType(p.source)}>{p.source}</Tag>,
  quantity: p.totalQuantity,
  avgPrice: formatPrice(p.weightedAvgPrice),
  currentPrice: formatPrice(p.currentPrice),
  pnl: <PnLCell amount={p.pnlAmount} pct={p.pnlPct} />,
  stopLoss: formatPrice(p.fixedStopPrice),
  ts: p.tsActivated ? <Tag type="green" size="sm">활성</Tag> : '-',
}));

// PnL 셀 컴포넌트
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

### 4.6 오늘 거래 + 최근 알림

```yaml
오늘 거래: DataTable 사용 (위 패턴)
최근 알림: InlineNotification 5개 또는 StructuredList
```

```jsx
import { 
  StructuredListWrapper, StructuredListHead, 
  StructuredListBody, StructuredListRow, StructuredListCell 
} from '@carbon/react';

// 최근 알림
<StructuredListWrapper>
  <StructuredListHead>
    <StructuredListRow head>
      <StructuredListCell head>등급</StructuredListCell>
      <StructuredListCell head>제목</StructuredListCell>
      <StructuredListCell head>시간</StructuredListCell>
    </StructuredListRow>
  </StructuredListHead>
  <StructuredListBody>
    {notifications.slice(0, 5).map(n => (
      <StructuredListRow key={n.id}>
        <StructuredListCell>
          <Tag type={getSeverityType(n.severity)}>{n.severity}</Tag>
        </StructuredListCell>
        <StructuredListCell>{n.title}</StructuredListCell>
        <StructuredListCell>{formatTime(n.createdAt)}</StructuredListCell>
      </StructuredListRow>
    ))}
  </StructuredListBody>
</StructuredListWrapper>
```

---

## §5. 화면 3: 종목 등록

> ⚠️ **PRD Patch #3 (2026-04-25)**: 경로 선택 제거.
> 경로는 박스 설정 마법사 (§6)에서 선택.

### 5.1 종목 검색 Modal

```yaml
컴포넌트:
  - Modal (size: sm 또는 md)
  - Search (검색 입력)
  - StructuredList (검색 결과)
  - TextArea (메모)
  - Dropdown (출처)
  - ⚠️ RadioButtonGroup (경로 선택) → 제거됨 (PRD Patch #3)
```

```jsx
import { 
  Modal, Search, TextArea, Dropdown, Stack 
} from '@carbon/react';

<Modal
  open={isOpen}
  modalHeading="새 종목 추적 등록"
  primaryButtonText="추적 시작"
  secondaryButtonText="취소"
  onRequestClose={handleClose}
  onRequestSubmit={handleSubmit}
  primaryButtonDisabled={!selectedStock}
>
  <Stack gap={6}>
    <Search
      labelText="종목 검색"
      placeholder="종목명 또는 코드"
      onChange={handleSearch}
      size="lg"
    />
    
    {/* 검색 결과 */}
    {searchResults.length > 0 && (
      <StructuredListWrapper selection>
        <StructuredListBody>
          {searchResults.map(stock => (
            <StructuredListRow 
              key={stock.code}
              onClick={() => setSelectedStock(stock)}
            >
              <StructuredListCell>
                <strong>{stock.name}</strong> ({stock.code})
                <div className="cds--type-helper-text-01">
                  {stock.market} · {formatPrice(stock.currentPrice)}원
                </div>
              </StructuredListCell>
            </StructuredListRow>
          ))}
        </StructuredListBody>
      </StructuredListWrapper>
    )}
    
    {/* ⚠️ RadioButtonGroup (경로 선택) 제거 — PRD Patch #3 */}
    {/* 경로는 박스 설정 마법사에서 선택 */}
    
    <TextArea
      labelText="메모 (선택)"
      placeholder="예: 반도체 사이클 회복 기대"
      rows={3}
      value={memo}
      onChange={(e) => setMemo(e.target.value)}
    />
    
    <Dropdown
      id="source"
      titleText="출처"
      label="선택"
      items={['HTS', '뉴스', '리포트', '직접 분석']}
      selectedItem={source}
      onChange={({ selectedItem }) => setSource(selectedItem)}
    />
  </Stack>
</Modal>
```

### 5.2 다음 액션 (추적 시작 클릭 후)

```yaml
처리 흐름:
  POST /api/v71/tracked_stocks
  → tracked_stocks 레코드 생성 (status=TRACKING)
  → Modal 닫기
  → 박스 설정 마법사로 자동 이동 ⭐ (§6)

대안 (선택):
  "추적만 등록" 버튼 제공
  사용자가 나중 박스 설정 가능
  TRACKING 상태로 유지
```

---

## §6. 화면 4: 박스 설정 (Step 1~7)

> ⚠️ **PRD Patch #3 (2026-04-25)**: 마법사에 **Step 1: 경로 선택** 추가.
> 기존 6단계 → 7단계로 확장.
> 경로는 박스의 속성이므로, 박스 추가 시마다 다른 경로 선택 가능.

### 6.1 ProgressIndicator (Stepper)

```jsx
import { 
  ProgressIndicator, ProgressStep 
} from '@carbon/react';

<ProgressIndicator currentIndex={currentStep}>
  <ProgressStep label="경로" />        {/* ★ PRD Patch #3 신규 */}
  <ProgressStep label="전략" />
  <ProgressStep label="가격" />
  <ProgressStep label="비중" />
  <ProgressStep label="손절" />
  <ProgressStep label="확인" />
  <ProgressStep label="저장" />
</ProgressIndicator>
```

### 6.2 Step 1: 경로 선택 (★ PRD Patch #3 신규)

```jsx
import { TileGroup, RadioTile, FormGroup, InlineNotification } from '@carbon/react';

<FormGroup legendText="경로 선택">
  <TileGroup
    legend="박스 진입 경로"
    name="path_type"
    valueSelected={pathType}
    onChange={setPathType}
  >
    <RadioTile id="path_a" value="PATH_A">
      <h4>PATH_A — 단타 (3분봉)</h4>
      <p>며칠~몇 주 단위 매매. 박스 진입 → 빠른 청산.</p>
      <p className="cds--type-helper-text-01">
        진입: 3분봉 완성 즉시 매수
      </p>
      <p className="cds--type-helper-text-01">
        이용: 주도주, 테마주, 단기 모멘텀
      </p>
    </RadioTile>
    
    <RadioTile id="path_b" value="PATH_B">
      <h4>PATH_B — 중기 (일봉)</h4>
      <p>월 단위 추세 추종. 분할 매수 + 트레일링 스탑.</p>
      <p className="cds--type-helper-text-01">
        진입: 일봉 완성 후 익일 09:01 매수
      </p>
      <p className="cds--type-helper-text-01">
        이용: 서서히 움직이는 가치주, 증권주, 장기 테마
      </p>
    </RadioTile>
  </TileGroup>
  
  {pathType === 'PATH_B' && (
    <InlineNotification
      kind="info"
      title="PATH_B 안내"
      subtitle="갑업 5% 이상 시 매수 포기"
      hideCloseButton
      lowContrast
    />
  )}
  
  {/* 기존 박스 안내 (같은 종목에 이미 있는 박스) */}
  {existingBoxes.length > 0 && (
    <InlineNotification
      kind="info"
      title="이 종목의 기존 박스"
      subtitle={existingBoxes.map(b => 
        `${b.path_type} ${b.tier}차: ${b.lower}~${b.upper}원`
      ).join(' / ')}
      hideCloseButton
      lowContrast
    />
  )}
</FormGroup>
```

### 6.3 Step 2: 전략 선택 (TileGroup, PULLBACK/BREAKOUT)

> ⚠️ 이전 §6.3에 있던 PULLBACK/BREAKOUT TileGroup 그대로 사용.
> Step 순서만 뒤로 밀린 것이므로, 기존 코드 재사용 가능.

```jsx
// PULLBACK / BREAKOUT 선택 (기존 설계 유지)
// 전략은 경로와 무관하니 이 단계는 변경 없음
```

### 6.4 Step 3: 가격 범위

```jsx
import { 
  NumberInput, Stack, FormGroup, InlineNotification 
} from '@carbon/react';

<FormGroup legendText="박스 가격 범위">
  <Stack gap={5}>
    <div className="info-row">
      <span>현재가:</span> 
      <strong>{formatPrice(currentPrice)}원</strong>
      <span className="cds--type-helper-text-01">
        1년 최고/최저: {formatPrice(yearHigh)} / {formatPrice(yearLow)}
      </span>
    </div>
    
    <NumberInput
      id="upperPrice"
      label="박스 상단 (높은 가격) *"
      value={upperPrice}
      onChange={(e, { value }) => setUpperPrice(value)}
      min={1}
      step={100}
    />
    
    <NumberInput
      id="lowerPrice"
      label="박스 하단 (낮은 가격) *"
      value={lowerPrice}
      onChange={(e, { value }) => setLowerPrice(value)}
      min={1}
      step={100}
      invalid={lowerPrice >= upperPrice}
      invalidText="하단은 상단보다 낮아야 합니다"
    />
    
    {/* 박스 폭 표시 */}
    {upperPrice > lowerPrice && (
      <div className="info-row">
        박스 폭: {formatPrice(upperPrice - lowerPrice)}원 
        ({(((upperPrice - lowerPrice) / lowerPrice) * 100).toFixed(2)}%)
      </div>
    )}
    
    {/* 기존 박스 경고 */}
    {existingBoxes.length > 0 && (
      <InlineNotification
        kind="warning"
        title="다른 활성 박스 (참고)"
        subtitle={existingBoxes.map(b => 
          `${b.tier}차: ${b.lower}~${b.upper}`
        ).join(', ')}
        hideCloseButton
        lowContrast
      />
    )}
  </Stack>
</FormGroup>
```

### 6.3 Step 2: 전략 선택 (TileGroup)

```jsx
import { TileGroup, RadioTile } from '@carbon/react';

<TileGroup
  legend="진입 전략"
  name="strategy"
  valueSelected={strategy}
  onChange={setStrategy}
>
  <RadioTile id="pullback" value="PULLBACK">
    <h4>눌림 (PULLBACK)</h4>
    <p>박스 안에서 양봉 형성 시 매수</p>
    <p className="cds--type-helper-text-01">
      경로 A: 직전봉 + 현재봉 모두 양봉 + 박스 내 종가
    </p>
    <p className="cds--type-helper-text-01">
      봉 완성 직후 즉시 매수
    </p>
  </RadioTile>
  
  <RadioTile id="breakout" value="BREAKOUT">
    <h4>돌파 (BREAKOUT)</h4>
    <p>박스 상단 돌파 시 매수</p>
    <p className="cds--type-helper-text-01">
      종가 &gt; 박스 상단 + 양봉 + 정상 시가
    </p>
  </RadioTile>
</TileGroup>
```

### 6.4 Step 3: 비중

```jsx
import { Slider, NumberInput } from '@carbon/react';

<FormGroup legendText="매수 비중">
  <Stack gap={5}>
    <NumberInput
      id="positionSize"
      label="비중 (%)"
      value={positionSize}
      onChange={(e, { value }) => setPositionSize(value)}
      min={0.1}
      max={30}
      step={0.5}
    />
    
    <Slider
      labelText="비중"
      value={positionSize}
      min={0}
      max={30}
      step={0.5}
      onChange={({ value }) => setPositionSize(value)}
      hideTextInput
    />
    
    {/* 예상 정보 */}
    <Tile light>
      <p>예상 투입 금액: {formatPrice(totalCapital * positionSize / 100)}원</p>
      <p>예상 매수 수량: 약 {Math.floor(estimatedQty)}주</p>
    </Tile>
    
    {/* 한도 검증 */}
    {totalUsage + positionSize <= 30 ? (
      <InlineNotification
        kind="success"
        title="한도 내"
        subtitle={`현재 ${totalUsage}% + 신규 ${positionSize}% = ${totalUsage + positionSize}% (한도 30%)`}
        hideCloseButton
        lowContrast
      />
    ) : (
      <InlineNotification
        kind="error"
        title="한도 초과"
        subtitle={`${totalUsage}% + ${positionSize}% = ${totalUsage + positionSize}% > 30%`}
        hideCloseButton
      />
    )}
  </Stack>
</FormGroup>
```

### 6.5 Step 4: 손절폭

```jsx
<FormGroup legendText="손절폭">
  <Stack gap={5}>
    <NumberInput
      id="stopLoss"
      label="손절폭 (%)"
      value={stopLoss}
      onChange={(e, { value }) => setStopLoss(value)}
      min={-10}
      max={-1}
      step={0.5}
    />
    
    <Slider
      labelText="손절폭"
      value={stopLoss}
      min={-10}
      max={-1}
      step={0.5}
      onChange={({ value }) => setStopLoss(value)}
      hideTextInput
    />
    
    <Tile light>
      <p>평단가 {formatPrice(estimatedAvgPrice)} → 
         손절선 {formatPrice(estimatedAvgPrice * (1 + stopLoss/100))}원</p>
    </Tile>
    
    <InlineNotification
      kind="info"
      title="V7.1 단계별 손절 (자동)"
      subtitle="매수 ~ +5% 미만: 사용자 설정 / +5% 청산 후: -2% / +10% 청산 후: +4% (본전)"
      hideCloseButton
      lowContrast
    />
  </Stack>
</FormGroup>
```

### 6.6 Step 5: 확인

```jsx
import { StructuredListWrapper, StructuredListBody, StructuredListRow, StructuredListCell } from '@carbon/react';

<Tile>
  <h3>박스 정보 확인</h3>
  
  <StructuredListWrapper>
    <StructuredListBody>
      <StructuredListRow>
        <StructuredListCell>종목</StructuredListCell>
        <StructuredListCell><strong>{stockName} ({stockCode})</strong></StructuredListCell>
      </StructuredListRow>
      <StructuredListRow>
        <StructuredListCell>경로</StructuredListCell>
        <StructuredListCell>{pathType}</StructuredListCell>
      </StructuredListRow>
      <StructuredListRow>
        <StructuredListCell>가격</StructuredListCell>
        <StructuredListCell>
          {formatPrice(lowerPrice)} ~ {formatPrice(upperPrice)}원
        </StructuredListCell>
      </StructuredListRow>
      <StructuredListRow>
        <StructuredListCell>전략</StructuredListCell>
        <StructuredListCell>{strategy}</StructuredListCell>
      </StructuredListRow>
      <StructuredListRow>
        <StructuredListCell>비중</StructuredListCell>
        <StructuredListCell>{positionSize}%</StructuredListCell>
      </StructuredListRow>
      <StructuredListRow>
        <StructuredListCell>손절폭</StructuredListCell>
        <StructuredListCell>{stopLoss}%</StructuredListCell>
      </StructuredListRow>
    </StructuredListBody>
  </StructuredListWrapper>
  
  <TextArea
    labelText="메모 (선택)"
    rows={2}
    value={memo}
    onChange={(e) => setMemo(e.target.value)}
  />
</Tile>
```

---

## §7. 화면 5: 추적 종목 관리

### 7.1 리스트 페이지 (/tracked-stocks)

```yaml
주요 컴포넌트:
  - Page header (제목 + 신규 버튼)
  - Filter (Dropdown 3개 + Search)
  - DataTable (정렬, 페이지네이션 내장)
  - OverflowMenu (행별 액션)
```

```jsx
import { 
  DataTable, Table, TableContainer, 
  TableToolbar, TableToolbarContent, TableToolbarSearch,
  TableHead, TableHeader, TableBody, TableRow, TableCell,
  Button, Dropdown, Pagination, OverflowMenu, OverflowMenuItem
} from '@carbon/react';
import { Add } from '@carbon/icons-react';

<DataTable rows={trackedStocks} headers={headers}>
  {({ 
    rows, headers, getHeaderProps, getRowProps, 
    getTableProps, getToolbarProps, onInputChange 
  }) => (
    <TableContainer 
      title="추적 종목"
      description={`총 ${trackedStocks.length}개`}
    >
      <TableToolbar {...getToolbarProps()}>
        <TableToolbarContent>
          <TableToolbarSearch onChange={onInputChange} placeholder="종목명/코드" />
          <Dropdown
            id="status-filter"
            label="상태"
            items={['전체', 'TRACKING', 'BOX_SET', 'POSITION_OPEN']}
            onChange={({ selectedItem }) => setStatusFilter(selectedItem)}
            size="sm"
          />
          <Dropdown
            id="path-filter"
            label="경로"
            items={['전체', 'PATH_A', 'PATH_B']}
            size="sm"
          />
          <Button kind="primary" renderIcon={Add} onClick={openNewModal}>
            새 종목 추적
          </Button>
        </TableToolbarContent>
      </TableToolbar>
      
      <Table {...getTableProps()}>
        <TableHead>
          <TableRow>
            {headers.map(header => (
              <TableHeader {...getHeaderProps({ header })}>
                {header.header}
              </TableHeader>
            ))}
            <TableHeader />  {/* OverflowMenu 자리 */}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map(row => (
            <TableRow {...getRowProps({ row })}>
              {row.cells.map(cell => (
                <TableCell key={cell.id}>{cell.value}</TableCell>
              ))}
              <TableCell>
                <OverflowMenu>
                  <OverflowMenuItem itemText="박스 추가" />
                  <OverflowMenuItem itemText="메모 수정" />
                  <OverflowMenuItem itemText="리포트 생성" />
                  <OverflowMenuItem 
                    itemText="추적 종료" 
                    isDelete 
                    hasDivider 
                  />
                </OverflowMenu>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      
      <Pagination
        page={page}
        totalItems={total}
        pageSize={20}
        onChange={({ page, pageSize }) => {
          setPage(page);
          setPageSize(pageSize);
        }}
      />
    </TableContainer>
  )}
</DataTable>
```

### 7.2 상세 페이지

```yaml
컴포넌트:
  - Breadcrumb
  - Tile (현재가, 메타정보)
  - Tabs (박스 / 포지션 / 이벤트)
  - DataTable (각 탭 내용)
```

### 7.3 박스 수정 Modal

```jsx
<Modal
  open={isEditOpen}
  modalHeading="박스 수정 (1차)"
  primaryButtonText="저장"
  secondaryButtonText="취소"
  onRequestSubmit={handleSave}
>
  <Stack gap={5}>
    <NumberInput id="upper" label="상단" value={upper} />
    <NumberInput id="lower" label="하단" value={lower} />
    <NumberInput id="size" label="비중 (%)" value={size} />
    <NumberInput id="stop" label="손절폭 (%)" value={stop} />
    <TextArea labelText="메모" rows={2} />
    
    {stop > originalStop && (
      <InlineNotification
        kind="warning"
        title="손절폭 완화"
        subtitle="위험이 증가합니다"
        hideCloseButton
      />
    )}
  </Stack>
</Modal>
```

### 7.4 박스 삭제 / 추적 종료 (danger Modal)

```jsx
<Modal
  open={isDeleteOpen}
  danger
  modalHeading="박스 삭제 확인"
  primaryButtonText="삭제"
  secondaryButtonText="취소"
  onRequestSubmit={handleDelete}
>
  <p>박스 1차 (73,000~74,000)을 삭제할까요?</p>
  <p>미체결 매수 주문이 있으면 자동 취소됩니다.</p>
  <p><strong>이 작업은 되돌릴 수 없습니다.</strong></p>
</Modal>
```

---

## §8. 화면 6: 포지션 모니터

### 8.1 리스트 (Tile 기반)

```yaml
선택:
  옵션 A: DataTable (정보 밀도 높음)
  옵션 B: ExpandableTile 카드 형태 (가독성)
  
권장: 옵션 B (포지션은 카드가 더 직관적)
```

```jsx
import { ExpandableTile, TileAboveTheFoldContent, TileBelowTheFoldContent } from '@carbon/react';

{positions.map(p => (
  <ExpandableTile key={p.id}>
    <TileAboveTheFoldContent>
      <div className="position-header">
        <div>
          <strong>{p.stockName}</strong> ({p.stockCode})
          <Tag type={getSourceTagType(p.source)}>{p.source}</Tag>
          <Tag type={getStatusTagType(p.status)}>{p.status}</Tag>
        </div>
        <div className="position-pnl">
          <PnLDisplay amount={p.pnlAmount} pct={p.pnlPct} />
        </div>
      </div>
      
      <Grid narrow>
        <Column sm={2}>
          <span className="cds--type-helper-text-01">평단가</span>
          <strong>{formatPrice(p.weightedAvgPrice)}</strong>
        </Column>
        <Column sm={2}>
          <span className="cds--type-helper-text-01">수량</span>
          <strong>{p.totalQuantity}주</strong>
        </Column>
        <Column sm={2}>
          <span className="cds--type-helper-text-01">현재가</span>
          <strong>{formatPrice(p.currentPrice)}</strong>
        </Column>
        <Column sm={2}>
          <span className="cds--type-helper-text-01">손절선</span>
          <strong>{formatPrice(p.fixedStopPrice)}</strong>
        </Column>
      </Grid>
    </TileAboveTheFoldContent>
    
    <TileBelowTheFoldContent>
      {/* 상세 정보 (TS, 단계, 거래 이력) */}
    </TileBelowTheFoldContent>
  </ExpandableTile>
))}
```

### 8.2 MANUAL 포지션 강조

```jsx
{p.source === 'MANUAL' && (
  <InlineNotification
    kind="warning"
    title="MANUAL 포지션"
    subtitle="시스템 자동 청산 안 함. HTS에서 직접 매도하세요."
    hideCloseButton
    lowContrast
  />
)}
```

### 8.3 정합성 확인 버튼

```jsx
import { Renew } from '@carbon/icons-react';

<Button kind="ghost" renderIcon={Renew} onClick={runReconciliation}>
  정합성 확인
</Button>
```

---

## §9. 화면 7: 리포트

### 9.1 리스트 (DataTable)

```yaml
상태별 표시:
  COMPLETED: green Tag + 액션 (읽기, PDF, Excel)
  GENERATING: blue Tag + ProgressBar
  FAILED: red Tag + 재시도 버튼
```

```jsx
<DataTable rows={reports} headers={reportHeaders}>
  {/* ... */}
  <TableCell>
    {row.status === 'COMPLETED' && (
      <>
        <Button kind="ghost" size="sm" onClick={() => readReport(row.id)}>
          읽기
        </Button>
        <Button kind="ghost" size="sm" renderIcon={Document}>
          PDF
        </Button>
      </>
    )}
    {row.status === 'GENERATING' && (
      <ProgressBar value={row.progress} max={100} size="sm" />
    )}
    {row.status === 'FAILED' && (
      <Button kind="danger--tertiary" size="sm" onClick={retry}>
        재시도
      </Button>
    )}
  </TableCell>
</DataTable>
```

### 9.2 리포트 생성 Modal

```jsx
<Modal
  open={isOpen}
  modalHeading="새 리포트 생성"
  primaryButtonText="생성 시작"
  secondaryButtonText="취소"
>
  <Stack gap={5}>
    <ComboBox
      id="stock"
      titleText="종목 *"
      placeholder="종목 검색 또는 선택"
      items={stocks}
      itemToString={(item) => item ? `${item.name} (${item.code})` : ''}
      onChange={({ selectedItem }) => setSelectedStock(selectedItem)}
    />
    
    <InlineNotification
      kind="info"
      title="리포트 내용"
      subtitle="PART 1: 종목의 이야기 / PART 2: 객관 팩트 (사업/재무/공시)"
      hideCloseButton
      lowContrast
    />
    
    <p className="cds--type-helper-text-01">
      Claude Opus 4.7 사용 · 약 3~5분 소요
    </p>
    <p className="cds--type-helper-text-01">
      이번 달 사용량: {monthUsage}/30
    </p>
  </Stack>
</Modal>
```

### 9.3 리포트 읽기 (Tabs + Markdown)

```jsx
import { Tabs, TabList, Tab, TabPanels, TabPanel } from '@carbon/react';
import ReactMarkdown from 'react-markdown';

<Tabs>
  <TabList aria-label="리포트 섹션">
    <Tab>PART 1: 이야기</Tab>
    <Tab>PART 2: 객관 팩트</Tab>
  </TabList>
  <TabPanels>
    <TabPanel>
      <div className="markdown-content">
        <ReactMarkdown>{report.narrativePart}</ReactMarkdown>
      </div>
    </TabPanel>
    <TabPanel>
      <div className="markdown-content">
        <ReactMarkdown>{report.factsPart}</ReactMarkdown>
      </div>
    </TabPanel>
  </TabPanels>
</Tabs>
```

---

## §10. 화면 8: 알림 센터

### 10.1 알림 리스트 (Notification)

```jsx
import { 
  InlineNotification, ActionableNotification 
} from '@carbon/react';

{notifications.map(n => (
  <InlineNotification
    key={n.id}
    kind={getSeverityKind(n.severity)}  // error/warning/info
    title={n.title}
    subtitle={n.message}
    caption={formatTime(n.createdAt)}
    hideCloseButton={n.severity === 'CRITICAL'}
    onClose={() => markAsRead(n.id)}
  />
))}
```

```yaml
Severity 매핑:
  CRITICAL → kind="error" (빨강)
  HIGH → kind="warning" (주황)
  MEDIUM → kind="info" (파랑)
  LOW → kind="info" lowContrast (회색)
```

### 10.2 액션 가능 알림 (Actionable)

```jsx
<ActionableNotification
  kind="warning"
  title="박스 진입 임박"
  subtitle="삼성전자 박스 1차까지 +0.27%"
  actionButtonLabel="박스 보기"
  onActionButtonClick={() => navigate(`/boxes/${n.boxId}`)}
/>
```

### 10.3 Toast 알림 (실시간)

```jsx
import { ToastNotification } from '@carbon/react';

<ToastNotification
  kind="error"
  title="[CRITICAL] 손절 실행"
  subtitle="에프알텍 (036040) 50주 매도"
  caption="14:25:32"
  timeout={0}  // CRITICAL은 자동 사라짐 X
/>
```

---

## §11. 화면 9: 설정

### 11.1 Tabs 구조

```jsx
<Tabs>
  <TabList aria-label="설정">
    <Tab>일반</Tab>
    <Tab>알림</Tab>
    <Tab>보안</Tab>
    <Tab>시스템</Tab>
    <Tab>Telegram</Tab>
  </TabList>
  <TabPanels>
    <TabPanel><GeneralSettings /></TabPanel>
    <TabPanel><NotificationSettings /></TabPanel>
    <TabPanel><SecuritySettings /></TabPanel>
    <TabPanel><SystemSettings /></TabPanel>
    <TabPanel><TelegramSettings /></TabPanel>
  </TabPanels>
</Tabs>
```

### 11.2 일반 탭

```jsx
<Stack gap={6}>
  <NumberInput
    id="totalCapital"
    label="총 자본 (원)"
    value={totalCapital}
    helperText="박스 비중 계산의 기준"
    step={1000000}
  />
  
  <Dropdown
    id="language"
    titleText="언어"
    items={[{id: 'ko', text: '한국어'}, {id: 'en', text: 'English'}]}
    itemToString={(item) => item ? item.text : ''}
  />
  
  <FormGroup legendText="테마">
    <RadioButtonGroup name="theme" valueSelected={theme}>
      <RadioButton labelText="다크 (g100)" value="g100" />
      <RadioButton labelText="다크 (g90)" value="g90" />
      <RadioButton labelText="라이트 (white)" value="white" />
      <RadioButton labelText="시스템 설정 따름" value="system" />
    </RadioButtonGroup>
  </FormGroup>
  
  <Button kind="primary" onClick={handleSave}>저장</Button>
</Stack>
```

### 11.3 알림 탭 (Toggle)

```jsx
import { Toggle } from '@carbon/react';

<Stack gap={6}>
  <Toggle 
    id="critical" 
    labelText="CRITICAL 알림" 
    toggled={true} 
    disabled  // 강제 ON
    helperText="강제 활성 (안전장치)"
  />
  <Toggle 
    id="high" 
    labelText="HIGH 알림" 
    toggled={notifyHigh} 
    onToggle={setNotifyHigh}
  />
  <Toggle 
    id="medium" 
    labelText="MEDIUM 알림" 
    toggled={notifyMedium} 
    onToggle={setNotifyMedium}
  />
  <Toggle 
    id="low" 
    labelText="LOW 알림" 
    toggled={notifyLow} 
    onToggle={setNotifyLow}
  />
  
  <Toggle
    id="quietHours"
    labelText="조용 시간"
    toggled={quietHoursEnabled}
    onToggle={setQuietHoursEnabled}
    helperText="CRITICAL은 무관"
  />
  
  {quietHoursEnabled && (
    <>
      <TimePicker id="start" labelText="시작" value="22:00" />
      <TimePicker id="end" labelText="종료" value="07:00" />
    </>
  )}
</Stack>
```

### 11.4 보안 탭

```jsx
<Stack gap={6}>
  <Tile>
    <h4>비밀번호</h4>
    <p>마지막 변경: 2026-01-15 (3개월 전)</p>
    <Button kind="tertiary">비밀번호 변경</Button>
  </Tile>
  
  <Tile>
    <h4>2단계 인증 (TOTP)</h4>
    <Tag type="green">활성화됨</Tag>
    <Stack orientation="horizontal" gap={3}>
      <Button kind="tertiary">재설정</Button>
      <Button kind="tertiary">백업 코드 새로 생성</Button>
    </Stack>
  </Tile>
  
  <Tile>
    <h4>활성 세션</h4>
    <DataTable rows={sessions} headers={sessionHeaders}>
      {/* ... 세션 리스트 */}
    </DataTable>
  </Tile>
</Stack>
```

---

## §12. 인터랙션 표준

### 12.1 폼 검증

```yaml
Carbon TextInput / NumberInput:
  invalid={true}              # 빨간 보더
  invalidText="에러 메시지"   # 아래 에러 텍스트
  
검증 시점:
  - 타이핑 중: 검증 자제 (UX)
  - blur 시: 검증 + 에러 표시
  - 제출 시: 모든 필드 검증
```

### 12.2 로딩 상태

```jsx
// 페이지 로딩
import { SkeletonText, SkeletonPlaceholder } from '@carbon/react';

{isLoading ? <SkeletonPlaceholder /> : <ActualContent />}

// 버튼 로딩
import { InlineLoading } from '@carbon/react';

{isSubmitting ? (
  <InlineLoading description="저장 중..." />
) : (
  <Button onClick={handleSave}>저장</Button>
)}

// 큰 작업 (리포트 생성)
import { ProgressBar } from '@carbon/react';

<ProgressBar 
  label="리포트 생성 중" 
  helperText="예상 5분"
  value={progress} 
  max={100} 
/>
```

### 12.3 Toast 알림

```jsx
import { ToastNotification } from '@carbon/react';

// 위치: 우측 상단 (데스크톱) - 직접 CSS positioning
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

### 12.4 확인 다이얼로그 (danger Modal)

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

---

## §13. 반응형 디자인

### 13.1 Carbon Grid Breakpoints

```yaml
Carbon Breakpoints:
  sm: 320px+ (모바일)
  md: 672px+ (태블릿)
  lg: 1056px+ (데스크톱)
  xlg: 1312px+ (와이드)
  max: 1584px+ (초와이드)

Grid Column 사용:
  <Column sm={4} md={4} lg={4}>  {/* 1/4 in lg, full in sm */}
  <Column sm={4} md={8} lg={16}> {/* full width */}
```

### 13.2 모바일 적응

```yaml
Header:
  Desktop: HeaderName 표시
  Mobile: HeaderMenuButton (햄버거) 표시

SideNav:
  Desktop: 항상 표시 (256px)
  Mobile: HeaderMenuButton 클릭 시 오버레이로

DataTable:
  Desktop: 전체 컬럼
  Mobile: stickyHeader + 가로 스크롤
  또는 ExpandableTile 카드 형태로 변환

박스 설정 마법사:
  Desktop: ProgressIndicator 가로
  Mobile: ProgressIndicator vertical
```

```jsx
<ProgressIndicator vertical={isMobile}>
  <ProgressStep label="가격" />
  ...
</ProgressIndicator>
```

---

## §14. 다크 모드 (Carbon 테마)

### 14.1 테마 설정

```jsx
import { Theme } from '@carbon/react';

// 전체 앱
<Theme theme="g100">  {/* 다크 - 가장 어두움 */}
  <App />
</Theme>

// 또는 g90 (덜 어두움)
<Theme theme="g90">

// 라이트
<Theme theme="white">  {/* 가장 밝음 */}
<Theme theme="g10">    {/* 살짝 회색 */}
```

### 14.2 SCSS 글로벌 설정

```scss
// styles.scss
@use '@carbon/react/scss/themes';
@use '@carbon/react/scss/theme' with (
  $theme: themes.$g100  // 다크 기본
);
@use '@carbon/styles';

// 폰트
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

body {
  font-family: 'Pretendard', 'IBM Plex Sans', sans-serif;
}

// 한국식 손익 색상 (커스텀)
.pnl-profit {
  color: var(--cds-support-error);  // 빨강 (수익)
  font-family: 'IBM Plex Mono';
  font-weight: 600;
}

.pnl-loss {
  color: var(--cds-support-info);   // 파랑 (손실)
  font-family: 'IBM Plex Mono';
  font-weight: 600;
}
```

### 14.3 사용자 토글

```jsx
const [theme, setTheme] = useState('g100');

<Theme theme={theme}>
  <App />
</Theme>

// 설정 화면에서 변경
<RadioButtonGroup 
  valueSelected={theme} 
  onChange={(value) => {
    setTheme(value);
    localStorage.setItem('theme', value);
  }}
>
  <RadioButton labelText="다크 (g100)" value="g100" />
  <RadioButton labelText="라이트" value="white" />
</RadioButtonGroup>
```

---

## 부록 A: 화면별 컴포넌트 빠른 참조

| 화면 | 주요 Carbon 컴포넌트 |
|------|---------------------|
| 로그인 | Theme, Tile, TextInput, PasswordInput, Button, InlineNotification |
| TOTP | Tile, TextInput, ProgressBar, Button |
| 대시보드 | Grid, Tile, DataTable, Tag, ProgressBar, StructuredList |
| 추적 종목 | DataTable, TableToolbar, OverflowMenu, Pagination |
| 종목 상세 | Breadcrumb, Tile, Tabs, DataTable |
| 박스 설정 | ProgressIndicator, NumberInput, Slider, RadioTile, FormGroup |
| 포지션 | ExpandableTile, Tag, InlineNotification |
| 리포트 | DataTable, Modal, ComboBox, Tabs, ReactMarkdown |
| 알림 | InlineNotification, ActionableNotification, ToastNotification |
| 설정 | Tabs, Toggle, RadioButtonGroup, NumberInput, Dropdown |

---

## 부록 B: 한국식 손익 색상 SCSS

```scss
// 한국 주식: 빨강=상승, 파랑=하락 (서양과 반대)

.pnl-profit {
  color: var(--cds-support-error);
  
  // 또는 더 진하게
  // color: var(--cds-red-50);
}

.pnl-loss {
  color: var(--cds-support-info);
  
  // 또는
  // color: var(--cds-blue-50);
}

.pnl-neutral {
  color: var(--cds-text-secondary);
}

// 큰 숫자 (KPI)
.kpi-value {
  font-size: 2rem;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 600;
  
  &.profit { @extend .pnl-profit; }
  &.loss { @extend .pnl-loss; }
}
```

---

## 부록 C: shadcn/ui → Carbon 매핑 표 (참고)

| shadcn/ui | Carbon |
|-----------|--------|
| Button | Button |
| Dialog | Modal |
| AlertDialog | Modal (danger) |
| Sheet | Modal (full) 또는 사이드패널 |
| Drawer | Modal (full, 모바일) |
| Card | Tile / ExpandableTile |
| Table | DataTable |
| Tabs | Tabs |
| Badge | Tag |
| Toast (Sonner) | ToastNotification |
| Input | TextInput |
| Textarea | TextArea |
| Select | Dropdown |
| Combobox | ComboBox |
| Checkbox | Checkbox |
| Switch | Toggle |
| RadioGroup | RadioButtonGroup |
| Label | FormLabel |
| Skeleton | SkeletonText / SkeletonPlaceholder |
| Separator | (CSS border) |
| DropdownMenu | OverflowMenu |
| Tooltip | Tooltip |
| Avatar | UserAvatar (icon) |
| Progress | ProgressBar |
| Slider | Slider |
| Lucide 아이콘 | @carbon/icons-react |

---

## 부록 D: 미정 사항

```yaml
D.1 차트 도입:
  현재: 없음
  추후: @carbon/charts-react 검토 가능
  → 사용자 결정

D.2 모바일 앱:
  PWA로 시작 (Carbon 자체 모바일 지원)
  React Native는 추후 검토

D.3 다국어:
  현재: 한국어만
  Carbon은 i18n 자체 지원 (영어/일본어 등)

D.4 차트 라이브러리 통합:
  필요 시 @carbon/charts-react
  또는 외부 (Recharts 등)
```

---

*이 문서는 V7.1 UI/UX의 Carbon Design System 버전입니다.*  
*Claude Design 작업의 입력 문서.*  
*프론트엔드 구현 시 기준.*

*최종 업데이트: 2026-04-25*
*원본: 10_UI_GUIDE.md (shadcn/ui 버전, 참고용)*
