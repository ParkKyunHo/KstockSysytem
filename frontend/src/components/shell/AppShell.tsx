// V7.1 AppShell -- direct port of frontend-prototype/src/components/shell.js.
// Header (cds-header) + SideNav (cds-side-nav) with system-status footer.

import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { I, type IconComponent } from '@/components/icons';
import { useLiveMock } from '@/hooks/useLiveMock';
import { initialMock, type MockState } from '@/mocks';
import { formatTime } from '@/lib/formatters';
import type { ThemeName } from '@/types';

interface AppShellProps {
  theme: ThemeName;
  onCycleTheme: () => ThemeName;
}

interface NavItem {
  key: string;
  label: string;
  icon: IconComponent;
  to: string;
  matchPrefix?: string;
}

const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', label: '대시보드', icon: I.Dashboard, to: '/dashboard' },
  {
    key: 'tracked-stocks',
    label: '추적 종목',
    icon: I.ListChecked,
    to: '/tracked-stocks',
    matchPrefix: '/tracked-stocks',
  },
  { key: 'positions', label: '포지션', icon: I.Chart, to: '/positions' },
  { key: 'trade-events', label: '거래 이벤트', icon: I.Receipt, to: '/trade-events' },
  { key: 'reports', label: '리포트', icon: I.Document, to: '/reports' },
  { key: 'notifications', label: '알림', icon: I.Bell, to: '/notifications' },
  { key: 'settings', label: '설정', icon: I.Settings, to: '/settings' },
];

const THEME_LABEL: Record<ThemeName, string> = {
  g100: '다크',
  g90: '딥다크',
  g10: '라이트',
  white: '라이트',
};

function ThemeIcon({ theme }: { theme: ThemeName }) {
  const Icon =
    theme === 'g10' || theme === 'white'
      ? I.Sun
      : theme === 'g90'
        ? I.Contrast
        : I.Moon;
  return <Icon className="cds-icon" size={20} />;
}

export function AppShell({ theme, onCycleTheme }: AppShellProps) {
  const [sideOpen, setSideOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const mock = useLiveMock(initialMock);
  const unread = mock.notifications.length; // P5.4 wires real "is_read"

  const close = () => setSideOpen(false);
  const goto = (to: string) => {
    navigate(to);
    close();
  };

  const isActive = (item: NavItem) => {
    if (item.matchPrefix) {
      return location.pathname.startsWith(item.matchPrefix);
    }
    return location.pathname === item.to;
  };

  return (
    <div className="app-shell">
      <AppHeader
        onToggleSide={() => setSideOpen((s) => !s)}
        unread={unread}
        theme={theme}
        onCycleTheme={onCycleTheme}
        onNav={goto}
      />
      <div className="app-body">
        <AppSideNav
          open={sideOpen}
          onClose={close}
          isActive={isActive}
          onNav={goto}
          mock={mock}
        />
        <main className="app-content">
          <Outlet context={{ mock } satisfies AppShellOutletContext} />
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------

function AppHeader({
  onToggleSide,
  unread,
  theme,
  onCycleTheme,
  onNav,
}: {
  onToggleSide: () => void;
  unread: number;
  theme: ThemeName;
  onCycleTheme: () => ThemeName;
  onNav: (to: string) => void;
}) {
  return (
    <header className="cds-header">
      <button
        type="button"
        className="cds-header__menu-btn cds-header__menu-btn--hide-desktop"
        onClick={onToggleSide}
        aria-label="메뉴"
      >
        <I.Menu className="cds-icon" size={20} />
      </button>
      <div className="cds-header__name">
        <strong>V7.1</strong>
        <span>K-Stock Trading</span>
      </div>
      <div className="cds-header__right">
        <button
          type="button"
          className="cds-header__icon-btn"
          onClick={onCycleTheme}
          title={`테마: ${THEME_LABEL[theme]} (클릭해 전환)`}
          aria-label="테마 전환"
        >
          <ThemeIcon theme={theme} />
        </button>
        <button
          type="button"
          className="cds-header__icon-btn"
          onClick={() => onNav('/notifications')}
          aria-label="알림"
        >
          <I.Bell className="cds-icon" size={20} />
          {unread > 0 ? <span className="notif-dot">{unread}</span> : null}
        </button>
        <div
          className="cds-header__user"
          onClick={() => onNav('/settings')}
        >
          <div className="cds-header__avatar">박</div>
          <span className="cds-header__name-text">박균호</span>
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------
// SideNav
// ---------------------------------------------------------------------

function AppSideNav({
  open,
  onClose,
  isActive,
  onNav,
  mock,
}: {
  open: boolean;
  onClose: () => void;
  isActive: (item: NavItem) => boolean;
  onNav: (to: string) => void;
  mock: MockState;
}) {
  const sys = mock.systemStatus;
  return (
    <>
      {open ? (
        <div className="cds-side-nav-overlay" onClick={onClose} />
      ) : null}
      <aside className={`cds-side-nav${open ? ' is-open' : ''}`}>
        <nav className="cds-side-nav__items">
          {NAV_ITEMS.map((it) => {
            const Icon = it.icon;
            return (
              <a
                key={it.key}
                className={`cds-side-nav__link${isActive(it) ? ' is-active' : ''}`}
                onClick={() => onNav(it.to)}
              >
                <Icon className="cds-icon" size={16} />
                <span>{it.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="cds-side-nav__footer">
          <div
            style={{
              fontSize: 11,
              color: 'var(--cds-text-helper)',
              textTransform: 'uppercase',
              letterSpacing: 0.32,
              marginBottom: 8,
            }}
          >
            시스템 상태
          </div>
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
              className={`sys-status-line__dot sys-status-line__dot--${sys.websocket.connected ? 'ok' : 'err'}`}
            />
            <span>WebSocket</span>
          </div>
          <div className="sys-status-line">
            <span
              className={`sys-status-line__dot sys-status-line__dot--${sys.kiwoom_api.available ? 'ok' : 'err'}`}
            />
            <span>
              키움 API {sys.kiwoom_api.rate_limit_used_per_sec}/
              {sys.kiwoom_api.rate_limit_max}
            </span>
          </div>
          <div className="sys-status-line">
            <span
              className={`sys-status-line__dot sys-status-line__dot--${sys.telegram_bot.active ? 'ok' : 'err'}`}
            />
            <span>Telegram</span>
          </div>
          <div
            style={{
              marginTop: 12,
              paddingTop: 12,
              borderTop: '1px solid var(--cds-border-subtle-00)',
              fontSize: 11,
              color: 'var(--cds-text-helper)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {sys.market.is_open ? '장 진행중' : '장 마감'} ·{' '}
            {formatTime(sys.current_time)}
          </div>
        </div>
      </aside>
    </>
  );
}

export interface AppShellOutletContext {
  mock: MockState;
}
