import {
  Header,
  HeaderContainer,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderMenuButton,
  HeaderName,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
} from '@carbon/react';
import {
  Asleep,
  ChartLineSmooth,
  Contrast,
  Dashboard as DashboardIcon,
  Document,
  ListChecked,
  Notification,
  Receipt,
  Settings as SettingsIcon,
  Sun,
} from '@carbon/icons-react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useLiveMock } from '@/hooks/useLiveMock';
import { initialMock, type MockState } from '@/mocks';
import { formatTime } from '@/lib/formatters';
import type { ThemeName } from '@/types';

interface AppShellProps {
  theme: ThemeName;
  onCycleTheme: () => ThemeName;
}

interface NavItem {
  to: string;
  label: string;
  icon: typeof DashboardIcon;
  matchPrefix?: string;
}

// Mirrors `frontend-prototype/src/components/shell.js NAV_ITEMS`.
const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: '대시보드', icon: DashboardIcon },
  {
    to: '/tracked-stocks',
    label: '추적 종목',
    icon: ListChecked,
    matchPrefix: '/tracked-stocks',
  },
  { to: '/positions', label: '포지션', icon: ChartLineSmooth },
  { to: '/trade-events', label: '거래 이벤트', icon: Receipt },
  { to: '/reports', label: '리포트', icon: Document },
  { to: '/notifications', label: '알림', icon: Notification },
  { to: '/settings', label: '설정', icon: SettingsIcon },
];

const THEME_LABEL: Record<ThemeName, string> = {
  g100: '다크',
  g90: '딥다크',
  g10: '라이트',
  white: '라이트',
};

function ThemeIcon({ theme, size = 20 }: { theme: ThemeName; size?: number }) {
  if (theme === 'g10' || theme === 'white') return <Sun size={size} />;
  if (theme === 'g90') return <Contrast size={size} />;
  return <Asleep size={size} />;
}

export function AppShell({ theme, onCycleTheme }: AppShellProps) {
  const location = useLocation();
  const navigate = useNavigate();
  // Single point of truth for live mock + system status; pages read it
  // from Outlet context.
  const mock = useLiveMock(initialMock);
  const unread = mock.notifications.filter(
    (n) => n.status !== 'EXPIRED' && n.status !== 'SUPPRESSED',
  ).length;

  const isActive = (item: NavItem) => {
    if (item.matchPrefix) {
      return location.pathname.startsWith(item.matchPrefix);
    }
    return location.pathname === item.to;
  };

  return (
    <HeaderContainer
      render={({
        isSideNavExpanded,
        onClickSideNavExpand,
      }: {
        isSideNavExpanded: boolean;
        onClickSideNavExpand: () => void;
      }) => (
        <div className="app-shell">
          <Header aria-label="V7.1 K-Stock Trading">
            <SkipToContent />
            <HeaderMenuButton
              aria-label={isSideNavExpanded ? '메뉴 닫기' : '메뉴 열기'}
              onClick={onClickSideNavExpand}
              isActive={isSideNavExpanded}
              aria-expanded={isSideNavExpanded}
            />
            <HeaderName as={Link} to="/dashboard" prefix="V7.1">
              K-Stock Trading
            </HeaderName>
            <HeaderGlobalBar>
              <HeaderGlobalAction
                aria-label={`테마: ${THEME_LABEL[theme]} (클릭해 전환)`}
                tooltipAlignment="end"
                onClick={onCycleTheme}
              >
                <ThemeIcon theme={theme} />
              </HeaderGlobalAction>
              <HeaderGlobalAction
                aria-label={`알림 (${unread}건 미확인)`}
                tooltipAlignment="end"
                onClick={() => navigate('/notifications')}
              >
                <Notification size={20} />
                {unread > 0 ? (
                  <span className="app-shell__notif-dot">{unread}</span>
                ) : null}
              </HeaderGlobalAction>
              <button
                type="button"
                className="app-shell__user"
                onClick={() => navigate('/settings')}
                aria-label="사용자 설정"
              >
                <span className="app-shell__avatar">박</span>
                <span className="app-shell__user-name">박균호</span>
              </button>
            </HeaderGlobalBar>

            <SideNav
              aria-label="주 메뉴"
              expanded={isSideNavExpanded}
              isPersistent
              onSideNavBlur={onClickSideNavExpand}
            >
              <SideNavItems>
                {NAV_ITEMS.map((item) => (
                  <SideNavLink
                    key={item.to}
                    as={Link}
                    to={item.to}
                    renderIcon={item.icon}
                    isActive={isActive(item)}
                  >
                    {item.label}
                  </SideNavLink>
                ))}
              </SideNavItems>
              <SideNavSystemStatus mock={mock} />
            </SideNav>
          </Header>

          <main className="app-shell__main" id="main-content">
            <div className="app-shell__content">
              <Outlet context={{ mock } satisfies AppShellOutletContext} />
            </div>
          </main>
        </div>
      )}
    />
  );
}

// ---------------------------------------------------------------------
// SideNav system-status footer
// ---------------------------------------------------------------------

function SideNavSystemStatus({ mock }: { mock: MockState }) {
  const sys = mock.systemStatus;
  return (
    <div className="sys-status">
      <div className="sys-status__label">시스템 상태</div>
      <div className="sys-status-line">
        <span
          className={`sys-status-line__dot sys-status-line__dot--${
            sys.status === 'RUNNING'
              ? 'ok'
              : sys.status === 'SAFE_MODE'
                ? 'err'
                : 'warn'
          }`}
        />
        <span>
          {sys.status === 'RUNNING'
            ? '시스템 정상'
            : sys.status === 'SAFE_MODE'
              ? '안전 모드'
              : '복구 중'}
        </span>
      </div>
      <div className="sys-status-line">
        <span
          className={`sys-status-line__dot sys-status-line__dot--${
            sys.websocket.connected ? 'ok' : 'err'
          }`}
        />
        <span>WebSocket</span>
      </div>
      <div className="sys-status-line">
        <span
          className={`sys-status-line__dot sys-status-line__dot--${
            sys.kiwoom_api.available ? 'ok' : 'err'
          }`}
        />
        <span>
          키움 API {sys.kiwoom_api.rate_limit_used_per_sec}/
          {sys.kiwoom_api.rate_limit_max}
        </span>
      </div>
      <div className="sys-status-line">
        <span
          className={`sys-status-line__dot sys-status-line__dot--${
            sys.telegram_bot.active ? 'ok' : 'err'
          }`}
        />
        <span>Telegram</span>
      </div>
      <div className="sys-status__time">
        {sys.market.is_open ? '장 진행중' : '장 마감'} ·{' '}
        {formatTime(sys.current_time)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Outlet context type
// ---------------------------------------------------------------------

export interface AppShellOutletContext {
  mock: MockState;
}
