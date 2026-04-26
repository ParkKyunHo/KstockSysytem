(function(){
/* Positions monitor */
const { useState, useMemo } = React;
const U = window.UI;
const I = window.Icons;

function Positions({ mock, addToast }) {
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [tab, setTab] = useState('open');
  const [orderDlg, setOrderDlg] = useState(null); // { side, position }

  const open = mock.positions.filter(p => p.status === 'OPEN' || p.status === 'PARTIAL');
  const closed = mock.positions.filter(p => p.status === 'CLOSED');
  const list = tab === 'open' ? open : closed;

  const filtered = useMemo(() => list.filter(p => {
    if (search && !(p.stock_name.includes(search) || p.stock_code.includes(search))) return false;
    if (sourceFilter !== 'all' && p.source !== sourceFilter) return false;
    return true;
  }), [list, search, sourceFilter]);

  const totalPnL = open.reduce((s, p) => s + p.pnl_amount, 0);
  const totalCost = open.reduce((s, p) => s + p.weighted_avg_price * p.total_quantity, 0);
  const totalPnLPct = totalCost > 0 ? (totalPnL / totalCost) * 100 : 0;

  return React.createElement('div', null,
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '포지션'),
        React.createElement('div', { className: 'page-hd__subtitle' }, `보유 ${open.length}개 · 종료 ${closed.length}개`)),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'primary', size: 'sm', onClick: () => setOrderDlg({ side: 'BUY' }) }, '수동 주문'))),

    React.createElement('div', { className: 'grid-3', style: { marginBottom: 24 } },
      React.createElement(U.MetricTile, { label: '보유 종목', value: open.length, sub: '개' }),
      React.createElement(U.MetricTile, { label: '평가 손익', value: window.fmt.krwSigned(totalPnL) + '원', color: totalPnL >= 0 ? 'profit' : 'loss' }),
      React.createElement(U.MetricTile, { label: '수익률', value: window.fmt.pct(totalPnLPct), color: totalPnL >= 0 ? 'profit' : 'loss' })),

    React.createElement(U.Tabs, { value: tab, onChange: setTab, tabs: [
      { value: 'open', label: '보유 중', count: open.length },
      { value: 'closed', label: '종료', count: closed.length },
    ]}),

    React.createElement('div', { className: 'cds-data-table', style: { marginTop: 16 } },
      React.createElement('div', { className: 'table-toolbar' },
        React.createElement(U.SearchBox, { value: search, onChange: setSearch, placeholder: '종목명·코드' }),
        React.createElement(U.Dropdown, { value: sourceFilter, onChange: setSourceFilter, options: [
          { value: 'all', label: '출처: 전체' },
          { value: 'AUTO', label: '자동' },
          { value: 'EXTERNAL', label: 'HTS 수동' },
        ]})),
      React.createElement('div', { className: 'table-wrap' }, React.createElement('table', { className: 'cds-table' },
        React.createElement('thead', null, React.createElement('tr', null,
          React.createElement('th', null, '종목'),
          React.createElement('th', null, '출처'),
          React.createElement('th', { style: { textAlign: 'right' } }, '수량'),
          React.createElement('th', { style: { textAlign: 'right' } }, '평단가'),
          React.createElement('th', { style: { textAlign: 'right' } }, '현재가'),
          React.createElement('th', { style: { textAlign: 'right' } }, '평가손익'),
          React.createElement('th', { style: { textAlign: 'right' } }, '수익률'),
          React.createElement('th', null, '단계'),
          React.createElement('th', { style: { textAlign: 'right' } }, '손절선'),
          React.createElement('th', null, ''))),
        React.createElement('tbody', null, filtered.map(p => {
          const stock = mock.trackedStocks.find(s => s.id === p.tracked_stock_id);
          const cur = stock ? stock.current_price : p.weighted_avg_price;
          return React.createElement('tr', { key: p.id },
            React.createElement('td', null, React.createElement('strong', null, p.stock_name), ' ', React.createElement('span', { className: 'mono text-helper' }, p.stock_code)),
            React.createElement('td', null, React.createElement(U.PositionSourceTag, { source: p.source })),
            React.createElement('td', { className: 'price' }, p.total_quantity),
            React.createElement('td', { className: 'price' }, window.fmt.krw(p.weighted_avg_price)),
            React.createElement('td', { className: 'price' }, window.fmt.krw(cur)),
            React.createElement('td', { className: `price ${p.pnl_amount >= 0 ? 'pnl-profit' : 'pnl-loss'}` }, window.fmt.krwSigned(p.pnl_amount)),
            React.createElement('td', { className: `price ${p.pnl_amount >= 0 ? 'pnl-profit' : 'pnl-loss'}` }, window.fmt.pct(p.pnl_pct)),
            React.createElement('td', null, p.profit_10_executed ? '+10% 후' : p.profit_5_executed ? '+5% 후' : '초기'),
            React.createElement('td', { className: 'price pnl-loss' }, window.fmt.krw(p.fixed_stop_price)),
            React.createElement('td', null,
              p.status !== 'CLOSED' && React.createElement(U.OverflowMenu, { items: [
                { label: '추가 매수', onClick: () => setOrderDlg({ side: 'BUY', position: p }) },
                { label: '매도', onClick: () => setOrderDlg({ side: 'SELL', position: p }) },
              ]})));
        }))))),

    orderDlg && React.createElement(U.OrderDialog, {
      open: true, onClose: () => setOrderDlg(null), mock, addToast,
      defaultSide: orderDlg.side, defaultPosition: orderDlg.position,
    }));
}

window.Pages = window.Pages || {};
window.Pages.Positions = Positions;

})();
