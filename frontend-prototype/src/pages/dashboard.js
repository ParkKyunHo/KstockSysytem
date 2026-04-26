(function(){
/* Dashboard */
const { useState } = React;
const U = window.UI;
const I = window.Icons;

function Dashboard({ onNav, mock, addToast }) {
  const trackedCount = mock.trackedStocks.filter(t => t.status !== 'EXITED').length;
  const boxWaiting = mock.boxes.filter(b => b.status === 'WAITING').length;
  const positions = mock.positions.filter(p => p.status !== 'CLOSED');
  const partial = positions.filter(p => p.status === 'PARTIAL_CLOSED').length;
  const totalCapital = mock.settings.general.total_capital;
  const used = positions.reduce((s, p) => s + p.actual_capital_invested, 0);
  const usedPct = (used / totalCapital) * 100;
  const todayPnl = positions.reduce((s, p) => s + p.pnl_amount, 0);
  const todayPnlPct = totalCapital ? (todayPnl / totalCapital) * 100 : 0;

  // 진입 임박: WAITING + |proximity| < 2%
  const upcoming = mock.boxes.filter(b => b.status === 'WAITING' && b.entry_proximity_pct != null && Math.abs(b.entry_proximity_pct) < 2)
    .sort((a, b) => Math.abs(a.entry_proximity_pct) - Math.abs(b.entry_proximity_pct))
    .slice(0, 5);

  const recentNotifs = [...mock.notifications].sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 5);

  const todaysTrades = mock.tradeEvents.filter(e => new Date(e.occurred_at) > new Date(Date.now() - 86400000));

  const status = mock.systemStatus;

  return React.createElement('div', null,
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '대시보드'),
        React.createElement('div', { className: 'page-hd__subtitle' },
          status.market.is_open ? `장 진행중 · 마감까지 ${calcUntil(status.market.next_close_at)}` : '장 마감')
      ),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Renew, onClick: () => addToast({ kind: 'info', title: '데이터 새로고침' }) }, '새로고침'),
        React.createElement(U.Btn, { kind: 'primary', size: 'sm', icon: I.Add, onClick: () => onNav('tracked-stocks?new=1') }, '새 종목 추적')
      )
    ),

    // KPI
    React.createElement('div', { className: 'kpi-grid' },
      React.createElement(U.KPITile, { label: '추적 종목', value: trackedCount, sub: `박스 대기 ${boxWaiting} / 진입 완료 ${mock.boxes.filter(b=>b.status==='TRIGGERED').length}` }),
      React.createElement(U.KPITile, { label: '활성 포지션', value: positions.length, sub: `부분청산 ${partial} / 전체 보유 ${positions.length - partial}` }),
      React.createElement(U.KPITile, { label: '자본 사용', value: usedPct.toFixed(1) + '%', sub: `가용 ${(100-usedPct).toFixed(1)}% · ${window.fmt.krw(totalCapital - used)}원`, progress: usedPct }),
      React.createElement(U.KPITile, { label: '오늘 손익', value: window.fmt.krwSigned(todayPnl) + '원', sub: window.fmt.pct(todayPnlPct), color: todayPnl >= 0 ? 'profit' : 'loss' })
    ),

    // 시스템 상태 row
    React.createElement('div', { className: 'tile-row' },
      React.createElement(U.Tag, { type: status.status === 'RUNNING' ? 'green' : 'red' }, status.status === 'RUNNING' ? '시스템 정상' : '안전 모드'),
      React.createElement(U.Tag, { type: status.websocket.connected ? 'green' : 'red' }, 'WebSocket'),
      React.createElement(U.Tag, { type: status.kiwoom_api.available ? 'green' : 'red' }, `키움 API ${status.kiwoom_api.rate_limit_used_per_sec}/${status.kiwoom_api.rate_limit_max}`),
      React.createElement(U.Tag, { type: status.telegram_bot.active ? 'green' : 'red' }, 'Telegram'),
      React.createElement('div', { style: { width: 1, height: 16, background: 'var(--cds-border-subtle-00)', margin: '0 4px' } }),
      React.createElement(U.Tag, { type: 'blue' }, status.market.is_open ? `장 진행중 ${window.fmt.time(status.current_time)}` : '장 마감'),
      React.createElement('span', { className: 'text-helper' }, status.market.is_open ? `마감까지 ${calcUntil(status.market.next_close_at)}` : ''),
      React.createElement('span', { className: 'spacer' }),
      React.createElement('span', { className: 'text-helper tnum' }, 'Uptime ', formatUptime(status.uptime_seconds))
    ),

    // 진입 임박 박스
    React.createElement('div', { className: 'section-hd' },
      React.createElement('h2', null, '진입 임박 박스'),
      React.createElement(U.Btn, { kind: 'ghost', size: 'sm', onClick: () => onNav('tracked-stocks') }, '전체 보기')),
    upcoming.length === 0
      ? React.createElement('div', { className: 'cds-tile' }, React.createElement('p', { className: 'text-helper', style: { margin: 0 } }, '현재 진입 임박 박스 없음'))
      : React.createElement('div', { className: 'cds-data-table' },
        React.createElement('div', { className: 'table-wrap' },
          React.createElement('table', { className: 'cds-table' },
            React.createElement('thead', null, React.createElement('tr', null,
              React.createElement('th', null, '종목명'),
              React.createElement('th', { style: { textAlign: 'right' } }, '현재가'),
              React.createElement('th', null, '박스'),
              React.createElement('th', { style: { textAlign: 'right' } }, '거리'),
              React.createElement('th', { style: { textAlign: 'right' } }, '비중'),
              React.createElement('th', null, '전략'),
              React.createElement('th', null, ''))),
            React.createElement('tbody', null,
              upcoming.map(b => {
                const ts = mock.trackedStocks.find(t => t.id === b.tracked_stock_id);
                return React.createElement('tr', { key: b.id },
                  React.createElement('td', null, React.createElement('strong', null, b.stock_name), ' ',
                    React.createElement('span', { className: 'text-helper mono' }, b.stock_code)),
                  React.createElement('td', { className: 'price' }, window.fmt.krw(ts?.current_price), '원'),
                  React.createElement('td', { className: 'mono' }, window.fmt.krw(b.lower_price) + '~' + window.fmt.krw(b.upper_price)),
                  React.createElement('td', { className: `price ${b.entry_proximity_pct >= 0 ? 'pnl-profit' : 'pnl-loss'}` }, window.fmt.pct(b.entry_proximity_pct)),
                  React.createElement('td', { className: 'price' }, b.position_size_pct + '%'),
                  React.createElement('td', null, React.createElement(U.Tag, { type: 'cool-gray' }, b.strategy_type)),
                  React.createElement('td', { style: { textAlign: 'right' } },
                    React.createElement(U.OverflowMenu, { items: [
                      { label: '박스 수정', onClick: () => onNav(`tracked-stocks/${b.tracked_stock_id}`) },
                      { label: '종목 상세', onClick: () => onNav(`tracked-stocks/${b.tracked_stock_id}`) },
                      { divider: true },
                      { label: '박스 취소', danger: true, onClick: () => addToast({ kind: 'success', title: '박스 취소', subtitle: `${b.stock_name} ${b.box_tier}차 박스 취소됨` }) },
                    ]})
                  )
                );
              }))))),

    // 활성 포지션
    React.createElement('div', { className: 'section-hd' },
      React.createElement('h2', null, '활성 포지션'),
      React.createElement(U.Btn, { kind: 'ghost', size: 'sm', onClick: () => onNav('positions') }, '전체 보기')),
    positions.length === 0
      ? React.createElement('div', { className: 'cds-tile' }, React.createElement('p', { className: 'text-helper', style: { margin: 0 } }, '활성 포지션 없음'))
      : React.createElement('div', { className: 'cds-data-table' },
        React.createElement('div', { className: 'table-wrap' },
          React.createElement('table', { className: 'cds-table' },
            React.createElement('thead', null, React.createElement('tr', null,
              React.createElement('th', null, '종목'),
              React.createElement('th', null, '출처'),
              React.createElement('th', { style: { textAlign: 'right' } }, '수량'),
              React.createElement('th', { style: { textAlign: 'right' } }, '평단'),
              React.createElement('th', { style: { textAlign: 'right' } }, '현재가'),
              React.createElement('th', { style: { textAlign: 'right' } }, '손익'),
              React.createElement('th', { style: { textAlign: 'right' } }, '손절선'),
              React.createElement('th', null, 'TS'))),
            React.createElement('tbody', null,
              positions.map(p => React.createElement('tr', { key: p.id, style: { cursor: 'pointer' }, onClick: () => onNav('positions') },
                React.createElement('td', null, React.createElement('strong', null, p.stock_name), ' ',
                  React.createElement('span', { className: 'text-helper mono' }, p.stock_code)),
                React.createElement('td', null, React.createElement(U.PositionSourceTag, { source: p.source })),
                React.createElement('td', { className: 'price' }, p.total_quantity),
                React.createElement('td', { className: 'price' }, window.fmt.krw(p.weighted_avg_price)),
                React.createElement('td', { className: 'price' }, window.fmt.krw(p.current_price)),
                React.createElement('td', null,
                  React.createElement('div', { style: { textAlign: 'right' } }, React.createElement(U.PnLCell, { amount: p.pnl_amount, pct: p.pnl_pct }))),
                React.createElement('td', { className: 'price' }, window.fmt.krw(p.fixed_stop_price)),
                React.createElement('td', null, p.ts_activated ? React.createElement(U.Tag, { type: 'green', size: 'sm' }, 'TS 활성') : React.createElement('span', { className: 'text-helper' }, '-'))
              )))))),

    // 오늘 거래 + 최근 알림 2단
    React.createElement('div', { className: 'grid-2', style: { marginTop: 24 } },
      React.createElement('div', null,
        React.createElement('div', { className: 'section-hd' },
          React.createElement('h2', null, '오늘 거래'),
          React.createElement('span', { className: 'text-helper' }, todaysTrades.length, '건')
        ),
        React.createElement('div', { className: 'cds-data-table' }, React.createElement('table', { className: 'cds-table cds-table--compact' },
          React.createElement('thead', null, React.createElement('tr', null,
            React.createElement('th', null, '시간'), React.createElement('th', null, '종목'), React.createElement('th', null, '이벤트'),
            React.createElement('th', { style: { textAlign: 'right' } }, '수량'), React.createElement('th', { style: { textAlign: 'right' } }, '가격'))),
          React.createElement('tbody', null,
            todaysTrades.length === 0
              ? React.createElement('tr', null, React.createElement('td', { colSpan: 5, style: { color: 'var(--cds-text-helper)' } }, '오늘 거래 없음'))
              : todaysTrades.slice(0, 6).map(e => {
                const pos = mock.positions.find(p => p.id === e.position_id);
                return React.createElement('tr', { key: e.id },
                  React.createElement('td', { className: 'mono' }, window.fmt.time(e.occurred_at)),
                  React.createElement('td', null, pos?.stock_name || e.stock_code),
                  React.createElement('td', null, eventLabel(e.event_type)),
                  React.createElement('td', { className: 'price' }, e.quantity),
                  React.createElement('td', { className: 'price' }, window.fmt.krw(e.price)));
              }))))),

      React.createElement('div', null,
        React.createElement('div', { className: 'section-hd' },
          React.createElement('h2', null, '최근 알림'),
          React.createElement(U.Btn, { kind: 'ghost', size: 'sm', onClick: () => onNav('notifications') }, '전체')),
        React.createElement('div', { className: 'cds-slist' },
          recentNotifs.map(n => React.createElement('div', { key: n.id, className: 'cds-slist__row', style: { gridTemplateColumns: '88px 1fr 64px' } },
            React.createElement('div', { className: 'cds-slist__cell' }, React.createElement(U.SeverityTag, { severity: n.severity, sm: true })),
            React.createElement('div', { className: 'cds-slist__cell', style: { background: 'transparent' } },
              React.createElement('div', { style: { fontSize: 13, fontWeight: 600 } }, n.title),
              React.createElement('div', { className: 'text-helper', style: { marginTop: 2 } }, n.message)),
            React.createElement('div', { className: 'cds-slist__cell mono', style: { background: 'transparent', textAlign: 'right', fontSize: 12 } }, window.fmt.time(n.created_at))
          ))
        )
      )
    )
  );
}

function calcUntil(iso) {
  if (!iso) return '-';
  const ms = new Date(iso) - Date.now();
  if (ms <= 0) return '0m';
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  return (h ? h + 'h ' : '') + m + 'm';
}
function formatUptime(s) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return `${d}d ${h}h`;
}
function eventLabel(t) {
  const m = { BUY_EXECUTED: '매수', PYRAMID_BUY: '추가매수', MANUAL_PYRAMID_BUY: '수동매수', PROFIT_TAKE_5: '+5% 청산', PROFIT_TAKE_10: '+10% 청산', STOP_LOSS: '손절', TS_EXIT: 'TS 청산', MANUAL_SELL: '수동매도' };
  return m[t] || t;
}

window.Pages = window.Pages || {};
window.Pages.Dashboard = Dashboard;

})();
