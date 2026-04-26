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
  Dashboard as DashboardIcon,
  Document,
  ListChecked,
  Notification,
  Settings as SettingsIcon,
  SquareOutline,
  UserAvatar,
} from '@carbon/icons-react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';

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

const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: '대시보드', icon: DashboardIcon },
  { to: '/tracked-stocks', label: '추적 종목', icon: ListChecked, matchPrefix: '/tracked-stocks' },
  { to: '/boxes/new', label: '박스 추가', icon: SquareOutline, matchPrefix: '/boxes' },
  { to: '/positions', label: '포지션', icon: ChartLineSmooth },
  { to: '/reports', label: '리포트', icon: Document },
  { to: '/notifications', label: '알림', icon: Notification },
  { to: '/settings', label: '설정', icon: SettingsIcon },
];

export function AppShell({ onCycleTheme }: AppShellProps) {
  const location = useLocation();
  const navigate = useNavigate();

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
                aria-label="알림 센터"
                tooltipAlignment="end"
                onClick={() => navigate('/notifications')}
              >
                <Notification size={20} />
              </HeaderGlobalAction>
              <HeaderGlobalAction
                aria-label="테마 변경"
                tooltipAlignment="end"
                onClick={onCycleTheme}
              >
                <Asleep size={20} />
              </HeaderGlobalAction>
              <HeaderGlobalAction
                aria-label="사용자 메뉴"
                tooltipAlignment="end"
                onClick={() => navigate('/settings')}
              >
                <UserAvatar size={20} />
              </HeaderGlobalAction>
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
            </SideNav>
          </Header>

          <main className="app-shell__main" id="main-content">
            <div className="app-shell__content">
              <Outlet />
            </div>
          </main>
        </div>
      )}
    />
  );
}
