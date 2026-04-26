(function(){
/* Notifications + Settings */
const { useState } = React;
const U = window.UI;
const I = window.Icons;

function Notifications({ mock, addToast, onNav }) {
  const [tab, setTab] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [items, setItems] = useState(mock.notifications);
  const filtered = items.filter(n => {
    if (tab === 'unread') { if (!(!n.is_read || n.status !== 'READ')) return false; }
    if (tab === 'critical' && n.severity !== 'CRITICAL') return false;
    if (typeFilter !== 'all' && n.event_type !== typeFilter) return false;
    return true;
  });
  const unreadCount = items.filter(n => !n.is_read && n.status !== 'READ').length;
  const markAll = () => { setItems(items.map(n => ({ ...n, is_read: true, status: 'READ' }))); addToast({ kind: 'success', title: '모두 읽음 처리' }); };
  const markOne = (id) => setItems(items.map(x => x.id === id ? { ...x, is_read: true, status: 'READ' } : x));

  // Action mapping
  const actionFor = (n) => {
    const map = {
      STOP_LOSS:        { label: '포지션 보기', go: () => { onNav && onNav('positions'); markOne(n.id); }},
      BOX_PROXIMITY:    { label: '종목 보기', go: () => { onNav && onNav('tracked-stocks'); markOne(n.id); }},
      BOX_TRIGGERED:    { label: '포지션 보기', go: () => { onNav && onNav('positions'); markOne(n.id); }},
      PROFIT_TAKE:      { label: '포지션 보기', go: () => { onNav && onNav('positions'); markOne(n.id); }},
      PYRAMID:          { label: '포지션 보기', go: () => { onNav && onNav('positions'); markOne(n.id); }},
      REPORT_COMPLETED: { label: '리포트 열기', go: () => { onNav && onNav('reports'); markOne(n.id); }},
      BOX_INVALIDATED:  { label: '종목 보기', go: () => { onNav && onNav('tracked-stocks'); markOne(n.id); }},
      VI_TRIGGERED:     { label: '확인',      go: () => markOne(n.id) },
      TRACKING_AUTO_EXIT:{ label: '확인',     go: () => markOne(n.id) },
      WS_DISCONNECT:    { label: '시스템 상태', go: () => markOne(n.id) },
    };
    return map[n.event_type] || { label: '읽음', go: () => markOne(n.id) };
  };

  // unique event types in current items
  const types = Array.from(new Set(items.map(n => n.event_type)));

  return React.createElement('div', null,
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '알림'),
        React.createElement('div', { className: 'page-hd__subtitle' },
          `미확인 ${unreadCount}건 · 전체 ${items.length}건 · CRITICAL ${items.filter(n=>n.severity==='CRITICAL').length}건`)),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', onClick: markAll, disabled: unreadCount === 0 }, '모두 읽음'))),

    React.createElement(U.Tabs, { value: tab, onChange: setTab, tabs: [
      { value: 'all', label: '전체', count: items.length },
      { value: 'unread', label: '미확인', count: unreadCount },
      { value: 'critical', label: '긴급', count: items.filter(n=>n.severity==='CRITICAL').length },
    ]}),

    React.createElement('div', { className: 'cds-data-table', style: { marginTop: 16 } },
      React.createElement('div', { className: 'table-toolbar' },
        React.createElement('div', { className: 'table-toolbar__tools', style: { marginLeft: 'auto' } },
          React.createElement(U.Dropdown, { value: typeFilter, onChange: setTypeFilter,
            options: [{ value: 'all', label: '유형: 전체' }, ...types.map(t => ({ value: t, label: t }))]}))),

      filtered.length === 0
        ? React.createElement('div', { className: 'cds-tile', style: { padding: 32, textAlign: 'center' } },
            React.createElement('p', { className: 'text-helper' }, '알림이 없습니다.'))
        : React.createElement('div', { className: 'notif-list' }, filtered.map(n => {
            const isUnread = !n.is_read && n.status !== 'READ';
            const action = actionFor(n);
            const stock = n.stock_code ? mock.trackedStocks.find(s => s.stock_code === n.stock_code) : null;
            return React.createElement('div', { key: n.id, className: 'notif-row' + (isUnread ? ' is-unread' : '') },
              React.createElement('div', { className: 'notif-row__sev' },
                React.createElement(U.SeverityTag, { severity: n.severity, sm: true })),
              React.createElement('div', { className: 'notif-row__body' },
                React.createElement('div', { className: 'notif-row__title' },
                  isUnread && React.createElement('span', { className: 'unread-dot' }),
                  React.createElement('strong', null, n.title),
                  React.createElement('span', { className: 'notif-row__type mono' }, n.event_type)),
                React.createElement('div', { className: 'notif-row__msg' }, n.message || n.body),
                React.createElement('div', { className: 'notif-row__meta mono text-helper' },
                  window.fmt.dateTime(n.sent_at || n.occurred_at || n.created_at),
                  ' · 채널 ', n.channel || 'WEB',
                  stock ? ' · ' + stock.stock_name + ' (' + n.stock_code + ')' : (n.stock_code ? ' · ' + n.stock_code : ''))),
              React.createElement('div', { className: 'notif-row__actions' },
                React.createElement(U.Btn, { kind: 'ghost', size: 'sm', onClick: action.go }, action.label)));
          }))));
}

function Settings({ mock, addToast, setMock }) {
  const [tab, setTab] = useState('general');
  const [draft, setDraft] = useState(JSON.parse(JSON.stringify(mock.settings)));
  const dirty = JSON.stringify(draft) !== JSON.stringify(mock.settings);

  const save = () => { setMock(m => ({ ...m, settings: draft })); addToast({ kind: 'success', title: '설정 저장됨' }); };
  const reset = () => setDraft(JSON.parse(JSON.stringify(mock.settings)));

  return React.createElement('div', null,
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '설정'),
        React.createElement('div', { className: 'page-hd__subtitle' }, '시스템 전반 설정. 변경 시 저장 버튼 활성화.')),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'secondary', size: 'sm', onClick: reset, disabled: !dirty }, '되돌리기'),
        React.createElement(U.Btn, { kind: 'primary', size: 'sm', icon: I.Save, onClick: save, disabled: !dirty }, '저장'))),

    React.createElement(U.Tabs, { value: tab, onChange: setTab, tabs: [
      { value: 'general', label: '일반' },
      { value: 'broker', label: '증권사' },
      { value: 'trading', label: '매매' },
      { value: 'notifications', label: '알림' },
      { value: 'security', label: '보안' },
    ]}),

    React.createElement('div', { className: 'cds-tile', style: { marginTop: 16, padding: 24 } },

      tab === 'general' && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '계좌 / 자본'),
        React.createElement(U.Field, { label: '총 운용 자본 (원)' },
          React.createElement(U.NumInput, { value: draft.general.total_capital, onChange: v => setDraft({ ...draft, general: { ...draft.general, total_capital: v } }), step: 1000000 })),
        React.createElement(U.Field, { label: '예약 비중 (%) — 추가 진입 여력' },
          React.createElement(U.SliderInput, { value: draft.general.reserve_pct, onChange: v => setDraft({ ...draft, general: { ...draft.general, reserve_pct: v } }), min: 0, max: 50, step: 1, fmt: v => v + '%' })),
        React.createElement(U.Field, { label: '시간대' },
          React.createElement(U.Dropdown, { value: draft.general.timezone, onChange: v => setDraft({ ...draft, general: { ...draft.general, timezone: v } }), options: [
            { value: 'Asia/Seoul', label: 'Asia/Seoul (한국 표준시)' }, { value: 'UTC', label: 'UTC' }] }))),

      tab === 'broker' && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, 'KIS API 연동'),
        React.createElement(U.InlineNotif, { kind: draft.broker.connected ? 'success' : 'warning',
          title: draft.broker.connected ? `연결됨 — 계좌 ${draft.broker.account_no}` : '미연결',
          subtitle: draft.broker.connected ? '시세·잔고·주문 자동 동기화 활성' : 'API 키를 입력하고 테스트하세요', lowContrast: true }),
        React.createElement(U.Field, { label: 'App Key' }, React.createElement(U.TextInput, { value: draft.broker.app_key, onChange: v => setDraft({ ...draft, broker: { ...draft.broker, app_key: v } }), placeholder: 'KIS App Key' })),
        React.createElement(U.Field, { label: 'App Secret' }, React.createElement(U.TextInput, { type: 'password', value: draft.broker.app_secret, onChange: v => setDraft({ ...draft, broker: { ...draft.broker, app_secret: v } }) })),
        React.createElement(U.Field, { label: '계좌번호' }, React.createElement(U.TextInput, { value: draft.broker.account_no, onChange: v => setDraft({ ...draft, broker: { ...draft.broker, account_no: v } }), placeholder: '12345678-01' })),
        React.createElement('div', { className: 'row-12' },
          React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', onClick: () => addToast({ kind: 'success', title: 'API 연결 OK' }) }, '연결 테스트'),
          React.createElement(U.Btn, { kind: 'ghost', size: 'sm', onClick: () => addToast({ kind: 'info', title: '잔고 동기화 시작' }) }, '잔고 동기화'))),

      tab === 'trading' && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '매매 한도 & 전략'),
        React.createElement(U.Field, { label: '단계별 최대 비중 (%)' },
          React.createElement(U.SliderInput, { value: draft.trading.tier_max_pct, onChange: v => setDraft({ ...draft, trading: { ...draft.trading, tier_max_pct: v } }), min: 5, max: 50, step: 1, fmt: v => v + '%' })),
        React.createElement(U.Field, { label: '+5% 도달 시 청산 비중 (%)' },
          React.createElement(U.SliderInput, { value: draft.trading.profit_5_exit_pct, onChange: v => setDraft({ ...draft, trading: { ...draft.trading, profit_5_exit_pct: v } }), min: 0, max: 100, step: 5, fmt: v => v + '%' })),
        React.createElement(U.Field, { label: '+10% 도달 시 청산 비중 (%)' },
          React.createElement(U.SliderInput, { value: draft.trading.profit_10_exit_pct, onChange: v => setDraft({ ...draft, trading: { ...draft.trading, profit_10_exit_pct: v } }), min: 0, max: 100, step: 5, fmt: v => v + '%' })),
        React.createElement(U.Field, { label: '트레일링 스탑 거리 (PATH_B, %)' },
          React.createElement(U.NumInput, { value: draft.trading.trailing_stop_pct, onChange: v => setDraft({ ...draft, trading: { ...draft.trading, trailing_stop_pct: v } }), step: 0.5 })),
        React.createElement(U.Toggle, { label: '갭업 진입 차단', sub: '시가 > 박스 상단의 1.03배 시 매수 보류',
          checked: draft.trading.block_gap_up, onChange: v => setDraft({ ...draft, trading: { ...draft.trading, block_gap_up: v } }) })),

      tab === 'notifications' && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '알림 채널'),
        React.createElement(U.Toggle, { label: '브라우저 푸시', checked: draft.notifications.browser_push, onChange: v => setDraft({ ...draft, notifications: { ...draft.notifications, browser_push: v } }) }),
        React.createElement(U.Toggle, { label: '이메일', checked: draft.notifications.email, onChange: v => setDraft({ ...draft, notifications: { ...draft.notifications, email: v } }) }),
        React.createElement(U.Toggle, { label: 'Slack 웹훅', checked: draft.notifications.slack, onChange: v => setDraft({ ...draft, notifications: { ...draft.notifications, slack: v } }) }),
        React.createElement('h3', { style: { margin: '8px 0 0' } }, '알림 종류'),
        ['box_triggered','position_filled','profit_5','profit_10','stop_loss','daily_summary'].map(k =>
          React.createElement(U.Toggle, { key: k, label: ({box_triggered:'박스 진입',position_filled:'주문 체결',profit_5:'+5% 도달',profit_10:'+10% 도달',stop_loss:'손절 발동',daily_summary:'일일 요약'})[k],
            checked: draft.notifications.types[k], onChange: v => setDraft({ ...draft, notifications: { ...draft.notifications, types: { ...draft.notifications.types, [k]: v } } }) }))),

      tab === 'security' && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '보안'),
        React.createElement(U.Toggle, { label: '2단계 인증 (TOTP)', sub: 'Google Authenticator 등', checked: draft.security.totp_enabled, onChange: v => setDraft({ ...draft, security: { ...draft.security, totp_enabled: v } }) }),
        React.createElement(U.Field, { label: '세션 만료 (분)' },
          React.createElement(U.NumInput, { value: draft.security.session_minutes, onChange: v => setDraft({ ...draft, security: { ...draft.security, session_minutes: v } }), step: 5 })),
        React.createElement(U.Field, { label: '주문 PIN' },
          React.createElement(U.TextInput, { type: 'password', value: draft.security.order_pin, onChange: v => setDraft({ ...draft, security: { ...draft.security, order_pin: v } }), placeholder: '6자리' })),
        React.createElement('div', { style: { paddingTop: 8 } },
          React.createElement(U.Btn, { kind: 'danger-tertiary', size: 'sm', onClick: () => addToast({ kind: 'info', title: '활성 세션 모두 종료됨' }) }, '모든 세션 로그아웃')))
    )
  );
}

window.Pages = window.Pages || {};
window.Pages.Notifications = Notifications;
window.Pages.Settings = Settings;

})();
