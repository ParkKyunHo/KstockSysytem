// V7.1 AppShell -- direct port of frontend-prototype/src/components/shell.js.
// Header (cds-header) + SideNav (cds-side-nav) with system-status footer.
//
// P5.5: ``system status`` footer + header unread counter are wired to
// the real REST API. Mock data still flows through the Outlet context
// for the pages that have not been migrated yet.

import { useCallback, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';

import { I, type IconComponent } from '@/components/icons';
import { SessionExpiryWatcher } from '@/components/shell/SessionExpiryWatcher';
import { SessionExtendButton } from '@/components/shell/SessionExtendButton';
import { UserMenu } from '@/components/shell/UserMenu';
import { ToastContainer, useToasts } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { useLiveMock } from '@/hooks/useLiveMock';
import { useSystemStatus, useUnreadNotifications } from '@/hooks/useApi';
import { useWsBootstrap } from '@/hooks/useWebSocket';
import { usePriceTickSubscription } from '@/hooks/usePriceTickSubscription';
import { initialMock, type MockState } from '@/mocks';
import { formatTime } from '@/lib/formatters';
import type { SystemStatusOut } from '@/api/system';
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
  const { user } = useAuth();

  // P5.5: real API state.
  useWsBootstrap();
  // P-Wire-Price-Tick (2026-04-30): WS POSITION_PRICE_UPDATE → priceStore.
  // Subscribes to "positions" channel and forwards live ticks to the
  // Zustand store consumed by Positions / Dashboard / etc. Backend gates
  // publishing on ``v71.price_publisher`` flag — when OFF the store
  // simply stays empty + pages fall back to PositionOut.current_price
  // (DB Patch #5 column) or mock (dev only).
  usePriceTickSubscription();
  const { data: systemStatus } = useSystemStatus();
  const { data: unreadData } = useUnreadNotifications();

  // Mock context kept for the pages that have not yet been migrated.
  const mock = useLiveMock(initialMock);

  // Session-expiry warning + expired toast (PRD §3.5 + Phase 4 UX).
  // 5min before access token expires → warning toast (persistent).
  // At expiry → error toast (the api.ts auto-refresh will normally
  // mint a fresh access via the rotated refresh token, so the user
  // rarely sees this; it appears only when refresh is also gone).
  const { toasts, addToast, closeToast } = useToasts();
  const handleSessionWarn = useCallback(() => {
    addToast({
      kind: 'warning',
      title: '세션이 곧 만료됩니다',
      subtitle: '5분 이내 자동 로그아웃됩니다.',
      caption: '헤더의 [로그인 연장] 버튼을 눌러 1시간 연장하세요.',
      ttl: 0, // persistent — user must dismiss or extend
    });
  }, [addToast]);
  const handleSessionExpired = useCallback(() => {
    addToast({
      kind: 'error',
      title: '세션이 만료되었습니다',
      subtitle: '다음 활동 시 자동 갱신을 시도합니다.',
      caption: '실패하면 다시 로그인해주세요.',
      ttl: 0,
    });
  }, [addToast]);

  // Merge: prefer real status but fall back to mock until the API
  // responds (e.g. brand-new page load). Mock notifications are still
  // surfaced when the unread API has not yet returned.
  const liveSystemStatus = systemStatus ?? mock.systemStatus;
  const unread = unreadData?.unread_count ?? mock.notifications.length;

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

  const userInitial = useMemo(() => {
    const name = user?.username ?? '';
    return name.length > 0 ? name.charAt(0).toUpperCase() : '?';
  }, [user]);

  return (
    <div className="app-shell">
      <SessionExpiryWatcher
        warnAtSeconds={300}
        onWarn={handleSessionWarn}
        onExpired={handleSessionExpired}
      />
      <ToastContainer toasts={toasts} onClose={closeToast} />
      <AppHeader
        onToggleSide={() => setSideOpen((s) => !s)}
        unread={unread}
        theme={theme}
        onCycleTheme={onCycleTheme}
        onNav={goto}
        userInitial={userInitial}
        userName={user?.username ?? ''}
        userRole={user?.role ?? null}
      />
      <div className="app-body">
        <AppSideNav
          open={sideOpen}
          onClose={close}
          isActive={isActive}
          onNav={goto}
          systemStatus={liveSystemStatus}
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
  userInitial,
  userName,
  userRole,
}: {
  onToggleSide: () => void;
  unread: number;
  theme: ThemeName;
  onCycleTheme: () => ThemeName;
  onNav: (to: string) => void;
  userInitial: string;
  userName: string;
  userRole: string | null;
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
        {import.meta.env.DEV ? (
          <span
            title="Vite dev mode (local SQLite, TOTP off, trading engine OFF)"
            style={{
              marginLeft: 8,
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.5,
              background: 'var(--cds-support-warning, #f1c21b)',
              color: '#000',
            }}
          >
            DEV
          </span>
        ) : null}
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
        {/* Session extend button — POST /auth/refresh, mints a fresh
            access token (1-hour lifetime). Sits between the bell and
            the user menu so it's right where the eye lands when the
            user wants to keep working. */}
        <SessionExtendButton />
        <UserMenu
          userInitial={userInitial}
          userName={userName}
          userRole={userRole}
        />
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
  systemStatus,
}: {
  open: boolean;
  onClose: () => void;
  isActive: (item: NavItem) => boolean;
  onNav: (to: string) => void;
  systemStatus: SystemStatusOut | MockState['systemStatus'];
}) {
  const sys = systemStatus;
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
