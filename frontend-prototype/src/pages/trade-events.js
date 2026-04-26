(function(){
/* Trade Events — vertical timeline of executions + system events.
   Globals: window.Pages.TradeEvents */
const { useState, useMemo } = React;
const U = window.UI;
const I = window.Icons;

/* -------- Event taxonomy -------- */
// category drives the dot color, icon, and timeline accent.
//   buy     → 매수/추가매수            (blue)
//   profit  → 수익실현 / 수동매도        (green)
//   loss    → 손절                       (red)
//   ts      → 트레일링 스탑 (활성/청산)  (purple)
//   system  → 거부, 포지션 청산 마감 등 (gray)
const EVENT_META = {
  BUY_EXECUTED:        { cat: 'buy',    label: '매수 체결',     icon: 'ArrowDown', tag: 'blue'      },
  PYRAMID_BUY:         { cat: 'buy',    label: '추가매수',       icon: 'ArrowDown', tag: 'blue'      },
  MANUAL_PYRAMID_BUY:  { cat: 'buy',    label: '수동 추가매수',  icon: 'ArrowDown', tag: 'cyan'      },
  PROFIT_TAKE_5:       { cat: 'profit', label: '+5% 청산',       icon: 'ArrowUp',   tag: 'green'     },
  PROFIT_TAKE_10:      { cat: 'profit', label: '+10% 청산',      icon: 'ArrowUp',   tag: 'green'     },
  MANUAL_SELL:         { cat: 'profit', label: '수동 매도',      icon: 'ArrowUp',   tag: 'cyan'      },
  TS_ACTIVATED:        { cat: 'ts',     label: '트레일링 활성',  icon: 'Lock',      tag: 'purple'    },
  TS_EXIT:             { cat: 'ts',     label: 'TS 청산',         icon: 'ArrowUp',   tag: 'purple'    },
  STOP_LOSS:           { cat: 'loss',   label: '손절',           icon: 'ArrowUp',   tag: 'red'       },
  BUY_REJECTED:        { cat: 'system', label: '매수 거부',      icon: 'Close',     tag: 'cool-gray' },
  POSITION_CLOSED:     { cat: 'system', label: '포지션 종료',    icon: 'View',      tag: 'cool-gray' },
};

const CAT_LABEL = { buy: '매수', profit: '수익실현', loss: '손절', ts: '트레일링', system: '시스템' };
const CAT_ORDER = ['buy', 'profit', 'ts', 'loss', 'system'];

const SOURCE_OF = (eventType) => {
  if (eventType.startsWith('MANUAL_')) return 'MANUAL';
  if (eventType === 'BUY_REJECTED' || eventType === 'POSITION_CLOSED' || eventType === 'TS_ACTIVATED') return 'SYSTEM';
  return 'AUTO';
};

/* group events by day key (YYYY-MM-DD in user TZ) */
function groupByDay(events) {
  const map = new Map();
  events.forEach(e => {
    const d = new Date(e.occurred_at);
    const key = d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
    if (!map.has(key)) map.set(key, { key, date: d, items: [] });
    map.get(key).items.push(e);
  });
  return Array.from(map.values()).sort((a, b) => b.date - a.date);
}

function dayHeading(d) {
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  const isYday  = d.toDateString() === new Date(today.getTime() - 86400000).toDateString();
  const datePart = d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
  if (isToday) return `오늘 · ${datePart}`;
  if (isYday)  return `어제 · ${datePart}`;
  return datePart;
}

/* -------- Page -------- */
function TradeEvents({ mock, onNav, addToast }) {
  const events = mock.tradeEvents;
  const [view, setView] = useState('timeline');   // 'timeline' | 'table'
  const [catFilter, setCatFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all'); // all | AUTO | MANUAL | SYSTEM
  const [stockFilter, setStockFilter] = useState('all');
  const [range, setRange] = useState('7d');       // 24h | 7d | 30d | all

  const enriched = useMemo(() => events.map(e => {
    const meta = EVENT_META[e.event_type] || { cat: 'system', label: e.event_type, icon: 'View', tag: 'gray' };
    const pos = mock.positions.find(p => p.id === e.position_id);
    const stock = mock.trackedStocks.find(s => s.stock_code === e.stock_code);
    return { ...e, meta, pos, stock, source: SOURCE_OF(e.event_type), amount: (e.quantity || 0) * (e.price || 0) };
  }), [events, mock.positions, mock.trackedStocks]);

  const filtered = useMemo(() => {
    const now = Date.now();
    const horizons = { '24h': 86_400_000, '7d': 7 * 86_400_000, '30d': 30 * 86_400_000 };
    return enriched.filter(e => {
      if (catFilter !== 'all' && e.meta.cat !== catFilter) return false;
      if (sourceFilter !== 'all' && e.source !== sourceFilter) return false;
      if (stockFilter !== 'all' && e.stock_code !== stockFilter) return false;
      if (range !== 'all') {
        const h = horizons[range];
        if (now - new Date(e.occurred_at).getTime() > h) return false;
      }
      return true;
    }).sort((a, b) => new Date(b.occurred_at) - new Date(a.occurred_at));
  }, [enriched, catFilter, sourceFilter, stockFilter, range]);

  /* ----- aggregates for KPI strip (over filtered) ----- */
  const kpi = useMemo(() => {
    let buyVol = 0, sellVol = 0, realized = 0;
    filtered.forEach(e => {
      if (e.meta.cat === 'buy') buyVol += e.amount;
      if (e.meta.cat === 'profit' || e.meta.cat === 'ts' || e.meta.cat === 'loss') sellVol += e.amount;
      // crude realized: revenue - (qty * weighted_avg_price) when known
      if (['profit', 'ts', 'loss'].includes(e.meta.cat) && e.pos && e.quantity > 0) {
        realized += (e.price - e.pos.weighted_avg_price) * e.quantity;
      }
    });
    return {
      total: filtered.length,
      buys: filtered.filter(e => e.meta.cat === 'buy').length,
      sells: filtered.filter(e => ['profit','ts','loss'].includes(e.meta.cat)).length,
      buyVol, sellVol, realized
    };
  }, [filtered]);

  /* unique stocks present in events */
  const stockOpts = useMemo(() => {
    const codes = Array.from(new Set(events.map(e => e.stock_code)));
    return [{ value: 'all', label: '종목: 전체' },
      ...codes.map(c => {
        const s = mock.trackedStocks.find(x => x.stock_code === c);
        return { value: c, label: (s ? s.stock_name : c) + ' (' + c + ')' };
      })];
  }, [events, mock.trackedStocks]);

  /* category counts (for filter chips) */
  const catCounts = useMemo(() => {
    const base = { all: enriched.length };
    CAT_ORDER.forEach(c => base[c] = enriched.filter(e => e.meta.cat === c).length);
    return base;
  }, [enriched]);

  const exportCsv = () => {
    addToast({ kind: 'success', title: 'CSV 내보내기 완료', subtitle: `${filtered.length}건 다운로드` });
  };

  return React.createElement('div', null,
    /* ===== Header ===== */
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '거래 이벤트'),
        React.createElement('div', { className: 'page-hd__subtitle' },
          `전체 ${enriched.length}건 · 표시 ${filtered.length}건 · 자동 ${enriched.filter(e=>e.source==='AUTO').length}건 / 수동 ${enriched.filter(e=>e.source==='MANUAL').length}건`)),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Download, onClick: exportCsv }, 'CSV'),
        React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Renew,
          onClick: () => addToast({ kind: 'info', title: '이벤트 동기화' }) }, '동기화'))),

    /* ===== KPI strip — compact, monospace numbers, no fluff ===== */
    React.createElement('div', { className: 'tev-kpi' },
      React.createElement(KpiCell, { label: '체결 이벤트',     value: kpi.total, sub: `매수 ${kpi.buys} · 매도 ${kpi.sells}` }),
      React.createElement(KpiCell, { label: '매수 금액',       value: window.fmt.krw(kpi.buyVol),  sub: '원', mono: true, accent: 'blue' }),
      React.createElement(KpiCell, { label: '매도 금액',       value: window.fmt.krw(kpi.sellVol), sub: '원', mono: true, accent: 'green' }),
      React.createElement(KpiCell, { label: '실현 손익(추정)', value: window.fmt.krwSigned(kpi.realized), sub: '원', mono: true,
        accent: kpi.realized >= 0 ? 'green' : 'red' })),

    /* ===== Filter bar ===== */
    React.createElement('div', { className: 'tev-filter' },
      React.createElement('div', { className: 'tev-chips' },
        ['all', ...CAT_ORDER].map(c => React.createElement(Chip, {
          key: c, active: catFilter === c, onClick: () => setCatFilter(c),
          dotCat: c === 'all' ? null : c
        }, c === 'all' ? '전체' : CAT_LABEL[c],
           React.createElement('span', { className: 'tev-chip__count' }, catCounts[c] || 0)))),

      React.createElement('div', { className: 'tev-filter__rhs' },
        React.createElement('div', { className: 'tev-segmented', role: 'tablist', 'aria-label': '기간' },
          [['24h','24h'],['7d','7일'],['30d','30일'],['all','전체']].map(([v,l]) =>
            React.createElement('button', {
              key: v, type: 'button', className: 'tev-seg' + (range === v ? ' is-active' : ''),
              onClick: () => setRange(v)
            }, l))),
        React.createElement(U.Dropdown, { value: sourceFilter, onChange: setSourceFilter, options: [
          { value: 'all', label: '소스: 전체' },
          { value: 'AUTO', label: '시스템 자동' },
          { value: 'MANUAL', label: '수동' },
          { value: 'SYSTEM', label: '내부 이벤트' },
        ]}),
        React.createElement(U.Dropdown, { value: stockFilter, onChange: setStockFilter, options: stockOpts }),
        React.createElement('div', { className: 'tev-segmented' },
          React.createElement('button', { type: 'button', className: 'tev-seg' + (view === 'timeline' ? ' is-active' : ''), onClick: () => setView('timeline'), 'aria-label': '타임라인' },
            '타임라인'),
          React.createElement('button', { type: 'button', className: 'tev-seg' + (view === 'table' ? ' is-active' : ''), onClick: () => setView('table'), 'aria-label': '테이블' },
            '테이블')))),

    /* ===== Body ===== */
    filtered.length === 0
      ? React.createElement('div', { className: 'cds-tile', style: { padding: 48, textAlign: 'center', marginTop: 16 } },
          React.createElement('p', { className: 'text-helper', style: { margin: 0 } }, '조건에 해당하는 이벤트가 없습니다.'))
      : view === 'timeline'
        ? React.createElement(Timeline, { groups: groupByDay(filtered), onNav })
        : React.createElement(EventTable, { items: filtered, onNav })
  );
}

/* -------- KPI cell -------- */
function KpiCell({ label, value, sub, mono, accent }) {
  return React.createElement('div', { className: 'tev-kpi__cell' + (accent ? ' tev-kpi__cell--' + accent : '') },
    React.createElement('div', { className: 'tev-kpi__label' }, label),
    React.createElement('div', { className: 'tev-kpi__val' + (mono ? ' mono' : '') }, value),
    sub && React.createElement('div', { className: 'tev-kpi__sub mono' }, sub));
}

/* -------- Chip -------- */
function Chip({ active, onClick, dotCat, children }) {
  return React.createElement('button', {
    type: 'button',
    className: 'tev-chip' + (active ? ' is-active' : ''),
    onClick
  },
    dotCat && React.createElement('span', { className: 'tev-dot tev-dot--' + dotCat }),
    children);
}

/* -------- Timeline view -------- */
function Timeline({ groups, onNav }) {
  return React.createElement('div', { className: 'tev-timeline' },
    groups.map(g => React.createElement('section', { key: g.key, className: 'tev-tl-day' },
      React.createElement('div', { className: 'tev-tl-day__hd' },
        React.createElement('span', { className: 'tev-tl-day__title' }, dayHeading(g.date)),
        React.createElement('span', { className: 'tev-tl-day__count mono text-helper' }, g.items.length, '건')),
      React.createElement('div', { className: 'tev-tl-list' },
        g.items.map(e => React.createElement(TimelineRow, { key: e.id, e, onNav }))))));
}

function TimelineRow({ e, onNav }) {
  const Icon = I[e.meta.icon] || I.View;
  const hasQty = e.quantity > 0;
  const stockName = e.stock ? e.stock.stock_name : e.stock_code;
  const sourceLabel = { AUTO: '자동', MANUAL: '수동', SYSTEM: '시스템' }[e.source];
  return React.createElement('article', { className: 'tev-tl-row' },
    /* gutter: time + axis dot */
    React.createElement('div', { className: 'tev-tl-row__gutter' },
      React.createElement('time', { className: 'tev-tl-row__time mono' }, window.fmt.timeS(e.occurred_at)),
      React.createElement('span', { className: 'tev-tl-row__axis' },
        React.createElement('span', { className: 'tev-tl-dot tev-dot--' + e.meta.cat },
          React.createElement(Icon, { size: 12 })))),

    /* card */
    React.createElement('div', { className: 'tev-tl-row__card', onClick: () => e.stock && onNav('tracked-stocks/' + e.stock.id) },
      React.createElement('header', { className: 'tev-tl-row__hd' },
        React.createElement(U.Tag, { type: e.meta.tag, size: 'sm' }, e.meta.label),
        React.createElement('span', { className: 'tev-tl-row__stock' },
          React.createElement('strong', null, stockName),
          React.createElement('span', { className: 'mono text-helper' }, e.stock_code)),
        React.createElement('span', { className: 'tev-tl-row__src ' + 'tev-src--' + e.source.toLowerCase() }, sourceLabel)),

      React.createElement('div', { className: 'tev-tl-row__body' },
        hasQty
          ? React.createElement(React.Fragment, null,
              React.createElement('span', { className: 'tev-tl-row__qty mono' }, e.quantity, '주'),
              React.createElement('span', { className: 'tev-tl-row__sep' }, '×'),
              React.createElement('span', { className: 'tev-tl-row__price mono' }, window.fmt.krw(e.price), '원'),
              React.createElement('span', { className: 'tev-tl-row__sep' }, '='),
              React.createElement('span', { className: 'tev-tl-row__amt mono' + (e.meta.cat === 'buy' ? '' : ' is-credit') },
                (e.meta.cat === 'buy' ? '−' : '+'), window.fmt.krw(e.amount), '원'))
          : /* zero-quantity events: TS_ACTIVATED, BUY_REJECTED, POSITION_CLOSED — show context */
            React.createElement('span', { className: 'tev-tl-row__note text-helper' },
              e.event_type === 'TS_ACTIVATED'    ? `기준가 ${window.fmt.krw(e.price)}원 — 트레일링 스탑 추적 시작` :
              e.event_type === 'BUY_REJECTED'    ? `참조가 ${window.fmt.krw(e.price)}원 — 갭업 차단 / 비중 초과` :
              e.event_type === 'POSITION_CLOSED' ? `청산가 ${window.fmt.krw(e.price)}원 — 전량 매도 완료` :
              `${window.fmt.krw(e.price)}원`)),

      e.pos && React.createElement('footer', { className: 'tev-tl-row__ft text-helper' },
        '포지션 ', React.createElement('span', { className: 'mono' }, e.pos.id),
        ' · 평단 ', React.createElement('span', { className: 'mono' }, window.fmt.krw(e.pos.weighted_avg_price), '원'),
        ' · 보유 ', React.createElement('span', { className: 'mono' }, e.pos.total_quantity, '주')))
  );
}

/* -------- Table view (compact) -------- */
function EventTable({ items, onNav }) {
  return React.createElement('div', { className: 'cds-data-table', style: { marginTop: 16 } },
    React.createElement('div', { className: 'table-wrap' },
      React.createElement('table', { className: 'cds-table cds-table--compact' },
        React.createElement('thead', null, React.createElement('tr', null,
          React.createElement('th', null, '시각'),
          React.createElement('th', null, '이벤트'),
          React.createElement('th', null, '종목'),
          React.createElement('th', { style: { textAlign: 'right' } }, '수량'),
          React.createElement('th', { style: { textAlign: 'right' } }, '가격'),
          React.createElement('th', { style: { textAlign: 'right' } }, '체결금액'),
          React.createElement('th', null, '소스'),
          React.createElement('th', null, '포지션'))),
        React.createElement('tbody', null,
          items.map(e => React.createElement('tr', { key: e.id },
            React.createElement('td', { className: 'mono' }, window.fmt.dateTime(e.occurred_at)),
            React.createElement('td', null,
              React.createElement('span', { className: 'tev-row-marker' },
                React.createElement('span', { className: 'tev-dot tev-dot--' + e.meta.cat, style: { width: 8, height: 8 } }),
                React.createElement(U.Tag, { type: e.meta.tag, size: 'sm' }, e.meta.label))),
            React.createElement('td', null,
              e.stock
                ? React.createElement('a', { className: 'cds-link', onClick: () => onNav('tracked-stocks/' + e.stock.id) },
                    e.stock.stock_name, ' ', React.createElement('span', { className: 'mono text-helper' }, e.stock_code))
                : React.createElement('span', { className: 'mono' }, e.stock_code)),
            React.createElement('td', { className: 'price' }, e.quantity > 0 ? e.quantity : '—'),
            React.createElement('td', { className: 'price' }, window.fmt.krw(e.price)),
            React.createElement('td', { className: 'price' }, e.quantity > 0 ? window.fmt.krw(e.amount) : '—'),
            React.createElement('td', null,
              React.createElement('span', { className: 'tev-src tev-src--' + e.source.toLowerCase() },
                { AUTO: '자동', MANUAL: '수동', SYSTEM: '시스템' }[e.source])),
            React.createElement('td', { className: 'mono text-helper' }, e.pos ? e.pos.id : '—'))))))
  );
}

window.Pages = window.Pages || {};
window.Pages.TradeEvents = TradeEvents;

})();
