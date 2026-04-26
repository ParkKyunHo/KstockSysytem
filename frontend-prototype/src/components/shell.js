(function(){
/* AppShell — Header + SideNav (responsive) */
/* Globals: window.AppShell */
const I = window.Icons;
const { useState, useEffect } = React;

const NAV_ITEMS = [
  { key: 'dashboard',       label: '대시보드',  icon: I.Dashboard },
  { key: 'tracked-stocks',  label: '추적 종목',  icon: I.ListChecked },
  { key: 'positions',       label: '포지션',     icon: I.Chart },
  { key: 'trade-events',    label: '거래 이벤트', icon: I.Receipt },
  { key: 'reports',         label: '리포트',     icon: I.Document },
  { key: 'notifications',   label: '알림',       icon: I.Bell },
  { key: 'settings',        label: '설정',       icon: I.Settings },
];

function AppHeader({ onToggleSide, notifCount, onNav, themeName, onToggleTheme, currentRoute }) {
  return React.createElement('header', { className: 'cds-header' },
    React.createElement('button', { className: 'cds-header__menu-btn cds-header__menu-btn--hide-desktop', onClick: onToggleSide, type: 'button', 'aria-label': '메뉴' },
      React.createElement(I.Menu, { className: 'cds-icon', size: 20 })),
    React.createElement('div', { className: 'cds-header__name' },
      React.createElement('strong', null, 'V7.1'),
      React.createElement('span', null, 'K-Stock Trading')
    ),
    React.createElement('div', { className: 'cds-header__right' },
      React.createElement('button', { className: 'cds-header__icon-btn', onClick: onToggleTheme, type: 'button', title: `테마: ${themeName === 'g100' ? '다크' : themeName === 'g90' ? '딥다크' : '라이트'} (클릭해 전환)`, 'aria-label': '테마 전환' },
        React.createElement(themeName === 'g10' ? I.Sun : themeName === 'g90' ? I.Contrast : I.Moon, { className: 'cds-icon', size: 20 })),
      React.createElement('button', {
        className: 'cds-header__icon-btn', onClick: () => onNav('notifications'), type: 'button', 'aria-label': '알림'
      },
        React.createElement(I.Bell, { className: 'cds-icon', size: 20 }),
        notifCount > 0 && React.createElement('span', { className: 'notif-dot' }, notifCount)
      ),
      React.createElement('div', { className: 'cds-header__user', onClick: () => onNav('settings') },
        React.createElement('div', { className: 'cds-header__avatar' }, '박'),
        React.createElement('span', { className: 'cds-header__name-text' }, '박균호')
      )
    )
  );
}

function AppSideNav({ open, onClose, currentRoute, onNav, systemStatus }) {
  return React.createElement(React.Fragment, null,
    open && React.createElement('div', { className: 'cds-side-nav-overlay', onClick: onClose }),
    React.createElement('aside', { className: `cds-side-nav${open?' is-open':''}` },
      React.createElement('nav', { className: 'cds-side-nav__items' },
        NAV_ITEMS.map(it => React.createElement('a', {
          key: it.key,
          className: `cds-side-nav__link${currentRoute === it.key || currentRoute.startsWith(it.key + '/') ? ' is-active' : ''}`,
          onClick: () => { onNav(it.key); onClose(); },
        },
          React.createElement(it.icon, { className: 'cds-icon', size: 16 }),
          React.createElement('span', null, it.label)
        ))
      ),
      React.createElement('div', { className: 'cds-side-nav__footer' },
        React.createElement('div', { style: { fontSize: 11, color: 'var(--cds-text-helper)', textTransform: 'uppercase', letterSpacing: 0.32, marginBottom: 8 } }, '시스템 상태'),
        React.createElement('div', { className: 'sys-status-line' },
          React.createElement('span', { className: `sys-status-line__dot sys-status-line__dot--${systemStatus.status === 'RUNNING' ? 'ok' : systemStatus.status === 'SAFE_MODE' ? 'err' : 'warn'}` }),
          React.createElement('span', null, systemStatus.status === 'RUNNING' ? '시스템 정상' : systemStatus.status === 'SAFE_MODE' ? '안전 모드' : '복구 중')),
        React.createElement('div', { className: 'sys-status-line' },
          React.createElement('span', { className: `sys-status-line__dot sys-status-line__dot--${systemStatus.websocket.connected ? 'ok' : 'err'}` }),
          React.createElement('span', null, 'WebSocket')),
        React.createElement('div', { className: 'sys-status-line' },
          React.createElement('span', { className: `sys-status-line__dot sys-status-line__dot--${systemStatus.kiwoom_api.available ? 'ok' : 'err'}` }),
          React.createElement('span', null, '키움 API ', systemStatus.kiwoom_api.rate_limit_used_per_sec, '/', systemStatus.kiwoom_api.rate_limit_max)),
        React.createElement('div', { className: 'sys-status-line' },
          React.createElement('span', { className: `sys-status-line__dot sys-status-line__dot--${systemStatus.telegram_bot.active ? 'ok' : 'err'}` }),
          React.createElement('span', null, 'Telegram')),
        React.createElement('div', { style: { marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--cds-border-subtle-00)', fontSize: 11, color: 'var(--cds-text-helper)', fontFamily: 'var(--font-mono)' } },
          systemStatus.market.is_open ? '장 진행중' : '장 마감',
          ' · ',
          new Date(systemStatus.current_time).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })
        )
      )
    )
  );
}

function AppShell({ currentRoute, onNav, children, notifCount, systemStatus, themeName, onToggleTheme }) {
  const [sideOpen, setSideOpen] = useState(false);
  return React.createElement('div', { className: 'app-shell' },
    React.createElement(AppHeader, {
      onToggleSide: () => setSideOpen(!sideOpen),
      notifCount, onNav, themeName, onToggleTheme, currentRoute
    }),
    React.createElement('div', { className: 'app-body' },
      React.createElement(AppSideNav, {
        open: sideOpen, onClose: () => setSideOpen(false),
        currentRoute, onNav, systemStatus
      }),
      React.createElement('main', { className: 'app-content' }, children)
    )
  );
}

window.AppShell = AppShell;

})();
