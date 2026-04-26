(function(){
/* TrackedStocks list + detail */
const { useState, useMemo } = React;
const U = window.UI;
const I = window.Icons;

function TrackedStocksList({ onNav, mock, addToast, openNew }) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [pathFilter, setPathFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [showNew, setShowNew] = useState(!!openNew);
  const [confirmDel, setConfirmDel] = useState(null);
  const perPage = 10;

  const filtered = useMemo(() => mock.trackedStocks.filter(s => {
    if (search && !(s.stock_name.includes(search) || s.stock_code.includes(search))) return false;
    if (statusFilter !== 'all' && s.status !== statusFilter) return false;
    if (pathFilter !== 'all' && s.path_type !== pathFilter) return false;
    return true;
  }), [search, statusFilter, pathFilter, mock.trackedStocks]);

  const paged = filtered.slice((page-1)*perPage, page*perPage);

  return React.createElement('div', null,
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '추적 종목'),
        React.createElement('div', { className: 'page-hd__subtitle' }, `총 ${filtered.length}개 / 박스 대기 ${mock.boxes.filter(b=>b.status==='WAITING').length}`)),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'primary', size: 'sm', icon: I.Add, onClick: () => setShowNew(true) }, '새 종목 추적'))),

    // toolbar
    React.createElement('div', { className: 'cds-data-table' },
      React.createElement('div', { className: 'table-toolbar' },
        React.createElement(U.SearchBox, { value: search, onChange: setSearch, placeholder: '종목명 또는 코드 검색' }),
        React.createElement('div', { className: 'table-toolbar__tools' },
          React.createElement(U.Dropdown, { value: statusFilter, onChange: setStatusFilter, options: [
            { value: 'all', label: '상태: 전체' },
            { value: 'TRACKING', label: '추적 중' },
            { value: 'BOX_SET', label: '박스 설정' },
            { value: 'POSITION_OPEN', label: '포지션 보유' },
            { value: 'POSITION_PARTIAL', label: '부분 청산' },
            { value: 'EXITED', label: '종료' },
          ]}),
          React.createElement(U.Dropdown, { value: pathFilter, onChange: setPathFilter, options: [
            { value: 'all', label: '경로: 전체' },
            { value: 'PATH_A', label: 'PATH_A' },
            { value: 'PATH_B', label: 'PATH_B' },
          ]})
        )
      ),
      React.createElement('div', { className: 'table-wrap' },
        React.createElement('table', { className: 'cds-table' },
          React.createElement('thead', null, React.createElement('tr', null,
            React.createElement('th', null, '종목명'), React.createElement('th', null, '코드'), React.createElement('th', null, '경로'),
            React.createElement('th', null, '상태'), React.createElement('th', { style: { textAlign: 'right' } }, '박스'),
            React.createElement('th', { style: { textAlign: 'right' } }, '포지션'),
            React.createElement('th', { style: { textAlign: 'right' } }, '현재가'),
            React.createElement('th', null, '등록일'), React.createElement('th', null, ''))),
          React.createElement('tbody', null, paged.map(s =>
            React.createElement('tr', { key: s.id, style: { cursor: 'pointer' }, onClick: () => onNav(`tracked-stocks/${s.id}`) },
              React.createElement('td', null, React.createElement('strong', null, s.stock_name), s.user_memo && React.createElement('div', { className: 'text-helper', style: { marginTop: 2 } }, s.user_memo)),
              React.createElement('td', { className: 'mono' }, s.stock_code, ' ', React.createElement('span', { className: 'text-helper' }, s.market)),
              React.createElement('td', null, React.createElement(U.Tag, { type: s.path_type === 'PATH_A' ? 'blue' : 'purple', size: 'sm' }, s.path_type)),
              React.createElement('td', null, React.createElement(U.TrackedStatusTag, { status: s.status, sm: true })),
              React.createElement('td', { className: 'price' }, s.summary.active_box_count, ' / ', s.summary.triggered_box_count),
              React.createElement('td', { className: 'price' }, s.summary.current_position_qty || '-'),
              React.createElement('td', { className: 'price' }, window.fmt.krw(s.current_price)),
              React.createElement('td', { className: 'mono', style: { fontSize: 12 } }, window.fmt.relative(s.created_at)),
              React.createElement('td', { onClick: e => e.stopPropagation() },
                React.createElement(U.OverflowMenu, { items: [
                  { label: '박스 추가', onClick: () => onNav(`tracked-stocks/${s.id}?addbox=1`) },
                  { label: '메모 수정', onClick: () => addToast({ kind: 'info', title: '메모 수정 (스텁)' }) },
                  { label: '리포트 생성', onClick: () => { onNav('reports'); addToast({ kind: 'info', title: `${s.stock_name} 리포트 생성 시작` }); } },
                  { divider: true },
                  { label: '추적 종료', danger: true, onClick: () => setConfirmDel(s) },
                ]})
              )
            )))
        )),
      React.createElement(U.Pagination, { total: filtered.length, page, perPage, onPage: setPage })
    ),

    showNew && React.createElement(NewTrackedStockModal, { onClose: () => setShowNew(false), mock, onSubmit: (selected, memo, source) => {
      setShowNew(false);
      addToast({ kind: 'success', title: '종목 추적 시작', subtitle: `${selected.name} (${selected.code}) · 박스 설정으로 이동` });
      // PRD Patch #3: 종목 등록 후 박스 설정 마법사 자동 이동 (경로는 박스마다 선택)
      onNav(`boxes/new?stock_id=${selected.code}`);
    }}),
    confirmDel && React.createElement(U.Modal, {
      open: true, danger: true, onClose: () => setConfirmDel(null),
      title: `${confirmDel.stock_name} 추적 종료`, subtitle: '확인 필요',
      primary: { label: '추적 종료', onClick: () => { addToast({ kind: 'success', title: `${confirmDel.stock_name} 추적 종료됨` }); setConfirmDel(null); }},
      secondary: { label: '취소', onClick: () => setConfirmDel(null) },
    },
      React.createElement('p', null, `${confirmDel.stock_name} (${confirmDel.stock_code}) 추적을 종료할까요?`),
      React.createElement('ul', { style: { paddingLeft: 20, fontSize: 14 } },
        React.createElement('li', null, '활성 박스 ', confirmDel.summary.active_box_count, '개 모두 취소됩니다'),
        React.createElement('li', null, '시세 모니터링 중지'),
        React.createElement('li', null, '이 작업은 되돌릴 수 없습니다')))
  );
}

function NewTrackedStockModal({ onClose, mock, onSubmit }) {
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState(null);
  const [memo, setMemo] = useState('');
  const [source, setSource] = useState('HTS');
  const results = window.MOCK.stockSearch(q);
  return React.createElement(U.Modal, {
    open: true, onClose, title: '새 종목 추적', subtitle: '종목을 검색해 추적 시작 — 경로는 박스 설정에서 선택', size: 'md',
    primary: { label: '추적 시작', onClick: () => onSubmit(selected, memo, source) },
    secondary: { label: '취소', onClick: onClose },
    primaryDisabled: !selected,
  },
    React.createElement(U.SearchBox, { value: q, onChange: setQ, placeholder: '종목명 또는 코드' }),
    React.createElement('div', { className: 'cds-slist cds-slist--simple', style: { maxHeight: 200, overflowY: 'auto', marginTop: 12 } },
      results.map(r => React.createElement('div', { key: r.code, className: 'cds-slist__row' },
        React.createElement('div', { className: `cds-slist__cell${selected?.code === r.code ? ' is-selected' : ''}`, onClick: () => setSelected(r) },
          React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between' } },
            React.createElement('div', null,
              React.createElement('strong', null, r.name), ' ',
              React.createElement('span', { className: 'text-helper mono' }, r.code, ' · ', r.market)),
            React.createElement('span', { className: 'mono' }, window.fmt.krw(r.currentPrice), '원')))))),
    React.createElement(U.InlineNotif, {
      kind: 'info', lowContrast: true,
      title: '경로 선택은 박스 설정에서',
      subtitle: '종목 등록 후 박스 설정 마법사에서 PATH_A(단타) / PATH_B(중기)를 박스 단위로 지정합니다.',
      style: { marginTop: 12 }
    }),
    React.createElement('div', { style: { marginTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 } },
      React.createElement(U.Field, { label: '출처' },
        React.createElement(U.Dropdown, { value: source, onChange: setSource, options: [
          { value: 'HTS', label: 'HTS' }, { value: '뉴스', label: '뉴스' }, { value: '리포트', label: '리포트' }, { value: '직접 분석', label: '직접 분석' },
        ]})),
      React.createElement(U.Field, { label: '메모 (선택)' },
        React.createElement(U.Textarea, { value: memo, onChange: setMemo, rows: 2, placeholder: '예: 반도체 사이클 회복' })))
  );
}

function TrackedStockDetail({ id, onNav, mock, addToast }) {
  const stock = mock.trackedStocks.find(s => s.id === id);
  const [tab, setTab] = useState('boxes');
  const [editBox, setEditBox] = useState(null);
  const [delBox, setDelBox] = useState(null);
  const [orderDlg, setOrderDlg] = useState(null);
  if (!stock) return React.createElement('div', { className: 'cds-tile' }, '종목을 찾을 수 없습니다.');
  const boxes = mock.boxes.filter(b => b.tracked_stock_id === id);
  const positions = mock.positions.filter(p => p.tracked_stock_id === id);
  const events = mock.tradeEvents.filter(e => e.stock_code === stock.stock_code);
  const change = stock.summary.current_position_avg_price
    ? ((stock.current_price - stock.summary.current_position_avg_price) / stock.summary.current_position_avg_price) * 100
    : 0;

  return React.createElement('div', null,
    React.createElement('div', { className: 'breadcrumbs' },
      React.createElement('a', { onClick: () => onNav('tracked-stocks') }, '추적 종목'),
      React.createElement('span', { className: 'sep' }, '/'),
      React.createElement('span', null, stock.stock_name)),
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, stock.stock_name, ' ',
          React.createElement('span', { className: 'mono', style: { fontSize: 16, color: 'var(--cds-text-helper)' } }, stock.stock_code)),
        React.createElement('div', { className: 'page-hd__subtitle' },
          React.createElement(U.Tag, { type: stock.path_type === 'PATH_A' ? 'blue' : 'purple', size: 'sm' }, stock.path_type), ' ',
          React.createElement(U.TrackedStatusTag, { status: stock.status, sm: true }), ' ',
          stock.market, ' · 등록 ', window.fmt.relative(stock.created_at), ' · 출처 ', stock.source || '-')),
      React.createElement('div', { className: 'page-hd__actions' },
        React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', icon: I.Document, onClick: () => onNav('reports') }, '리포트 생성'),
        React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', onClick: () => setOrderDlg({ side: 'BUY' }) }, '수동 매수'),
        positions.length > 0 && React.createElement(U.Btn, { kind: 'tertiary', size: 'sm', onClick: () => setOrderDlg({ side: 'SELL', position: positions[0] }) }, '수동 매도'),
        React.createElement(U.Btn, { kind: 'primary', size: 'sm', icon: I.Add, onClick: () => onNav(`boxes/new?stock_id=${id}`) }, '박스 추가'))
    ),
    React.createElement('div', { className: 'cds-tile', style: { marginBottom: 24 } },
      React.createElement('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 32, alignItems: 'flex-end' } },
        React.createElement('div', null,
          React.createElement('div', { className: 'text-helper' }, '현재가'),
          React.createElement('div', { className: 'mono', style: { fontSize: 32, lineHeight: '40px' } }, window.fmt.krw(stock.current_price), '원')),
        positions.length > 0 && React.createElement('div', null,
          React.createElement('div', { className: 'text-helper' }, '평단가 대비'),
          React.createElement('div', { className: change >= 0 ? 'pnl-profit' : 'pnl-loss', style: { fontSize: 20, fontFamily: 'var(--font-mono)' } }, window.fmt.pct(change))),
        stock.user_memo && React.createElement('div', { style: { flex: 1, minWidth: 200 } },
          React.createElement('div', { className: 'text-helper' }, '메모'),
          React.createElement('div', null, stock.user_memo)))),

    React.createElement(U.Tabs, { value: tab, onChange: setTab, tabs: [
      { value: 'boxes', label: '박스', count: boxes.length },
      { value: 'positions', label: '포지션', count: positions.length },
      { value: 'events', label: '거래 이벤트', count: events.length },
    ]}),
    React.createElement('div', { style: { marginTop: 16 } },
      tab === 'boxes' && (boxes.length === 0
        ? React.createElement(EmptyTile, { msg: '아직 박스가 없습니다.', cta: '박스 추가', onCta: () => onNav(`boxes/new?stock_id=${id}`) })
        : React.createElement('div', { className: 'cds-data-table' }, React.createElement('table', { className: 'cds-table' },
          React.createElement('thead', null, React.createElement('tr', null,
            React.createElement('th', null, 'Tier'),
            React.createElement('th', { style: { textAlign: 'right' } }, '가격대'),
            React.createElement('th', { style: { textAlign: 'right' } }, '비중'),
            React.createElement('th', { style: { textAlign: 'right' } }, '손절'),
            React.createElement('th', null, '전략'),
            React.createElement('th', null, '상태'),
            React.createElement('th', { style: { textAlign: 'right' } }, '거리'),
            React.createElement('th', null, '메모'),
            React.createElement('th', null, ''))),
          React.createElement('tbody', null, boxes.map(b => {
            const editable = b.status === 'WAITING' || b.status === 'TRIGGERED_PENDING';
            return React.createElement('tr', { key: b.id },
              React.createElement('td', null, b.box_tier, '차'),
              React.createElement('td', { className: 'price' }, window.fmt.krw(b.lower_price), ' ~ ', window.fmt.krw(b.upper_price)),
              React.createElement('td', { className: 'price' }, b.position_size_pct, '%'),
              React.createElement('td', { className: 'price pnl-loss' }, b.stop_loss_pct, '%'),
              React.createElement('td', null, React.createElement(U.Tag, { type: 'cool-gray', size: 'sm' }, b.strategy_type)),
              React.createElement('td', null, React.createElement(U.BoxStatusTag, { status: b.status })),
              React.createElement('td', { className: 'price' }, b.entry_proximity_pct != null ? window.fmt.pct(b.entry_proximity_pct) : '-'),
              React.createElement('td', { className: 'text-helper' }, b.memo || '-'),
              React.createElement('td', null,
                React.createElement(U.OverflowMenu, { items: [
                  { label: '편집', onClick: () => setEditBox(b), disabled: !editable },
                  { label: '복제', onClick: () => addToast({ kind: 'info', title: '박스 복제 (스텁)', subtitle: `${b.box_tier}차 박스 → 새 박스 생성` }) },
                  { divider: true },
                  { label: editable ? '취소' : '비활성화', danger: true, onClick: () => setDelBox(b) },
                ]})));
          })))) ),

      tab === 'positions' && (positions.length === 0
        ? React.createElement(EmptyTile, { msg: '아직 포지션이 없습니다.' })
        : positions.map(p => React.createElement(U.ExpandableTile, { key: p.id, defaultOpen: true,
            head: React.createElement('div', { style: { display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 } },
              React.createElement('div', null,
                React.createElement('strong', null, p.stock_name), ' ',
                React.createElement(U.PositionSourceTag, { source: p.source }), ' ',
                React.createElement('span', { className: 'text-helper' }, p.total_quantity, '주 @ ', window.fmt.krw(p.weighted_avg_price))),
              React.createElement(U.PnLCell, { amount: p.pnl_amount, pct: p.pnl_pct, big: true }))
          },
            React.createElement('div', { className: 'grid-4' },
              React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '평단가'), React.createElement('div', { className: 'mono' }, window.fmt.krw(p.weighted_avg_price))),
              React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '손절선'), React.createElement('div', { className: 'mono pnl-loss' }, window.fmt.krw(p.fixed_stop_price))),
              React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '+5% 청산'), React.createElement('div', null, p.profit_5_executed ? '✓ 완료' : '대기')),
              React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '+10% 청산'), React.createElement('div', null, p.profit_10_executed ? '✓ 완료' : '대기'))
            )))),

      tab === 'events' && (events.length === 0
        ? React.createElement(EmptyTile, { msg: '거래 이벤트 없음' })
        : React.createElement('div', { className: 'cds-data-table' }, React.createElement('table', { className: 'cds-table cds-table--compact' },
          React.createElement('thead', null, React.createElement('tr', null,
            React.createElement('th', null, '시각'), React.createElement('th', null, '이벤트'),
            React.createElement('th', { style: { textAlign: 'right' } }, '수량'), React.createElement('th', { style: { textAlign: 'right' } }, '가격'))),
          React.createElement('tbody', null, events.map(e => React.createElement('tr', { key: e.id },
            React.createElement('td', { className: 'mono' }, window.fmt.dateTime(e.occurred_at)),
            React.createElement('td', null, e.event_type),
            React.createElement('td', { className: 'price' }, e.quantity),
            React.createElement('td', { className: 'price' }, window.fmt.krw(e.price))))))))
    ),
    editBox && React.createElement(BoxEditModal, { box: editBox, stock, mock, addToast,
      onClose: () => setEditBox(null) }),
    orderDlg && React.createElement(U.OrderDialog, {
      open: true, onClose: () => setOrderDlg(null), mock, addToast,
      defaultSide: orderDlg.side, defaultStock: stock, defaultPosition: orderDlg.position,
    }),
    delBox && React.createElement(U.Modal, {
      open: true, danger: true, onClose: () => setDelBox(null),
      title: delBox.status === 'WAITING' ? '박스 취소' : '박스 비활성화',
      subtitle: stock.stock_name + ' · ' + delBox.box_tier + '차 박스',
      primary: { label: delBox.status === 'WAITING' ? '취소' : '비활성화',
        onClick: () => { addToast({ kind: 'success', title: '박스 ' + (delBox.status === 'WAITING' ? '취소됨' : '비활성화됨') }); setDelBox(null); }},
      secondary: { label: '돌아가기', onClick: () => setDelBox(null) },
    },
      React.createElement('p', null, window.fmt.krw(delBox.lower_price), '~', window.fmt.krw(delBox.upper_price), '원 · ', delBox.position_size_pct, '% · ', delBox.strategy_type),
      React.createElement('p', { className: 'text-helper' }, '이 박스는 더 이상 진입 트리거를 발동하지 않습니다.'))
  );
}

function EmptyTile({ msg, cta, onCta }) {
  return React.createElement('div', { className: 'cds-tile', style: { padding: 32, textAlign: 'center' } },
    React.createElement('p', { className: 'text-helper' }, msg),
    cta && React.createElement(U.Btn, { kind: 'primary', size: 'sm', onClick: onCta }, cta));
}

// ===== Box Edit Modal =====
function BoxEditModal({ box, stock, mock, addToast, onClose }) {
  const [upper, setUpper] = useState(box.upper_price);
  const [lower, setLower] = useState(box.lower_price);
  const [strategy, setStrategy] = useState(box.strategy_type);
  const [sizePct, setSizePct] = useState(box.position_size_pct);
  const [stopLoss, setStopLoss] = useState(box.stop_loss_pct);
  const [memo, setMemo] = useState(box.memo || '');

  const totalCapital = mock.settings.general.total_capital;
  const investAmount = (totalCapital * sizePct) / 100;
  const estQty = upper > 0 ? Math.floor(investAmount / upper) : 0;
  const stopPrice = upper * (1 + stopLoss / 100);

  // sum of OTHER active boxes (excluding this one)
  const otherUsedPct = mock.boxes
    .filter(b => b.tracked_stock_id === stock.id && b.id !== box.id && b.status !== 'INVALIDATED' && b.status !== 'CANCELLED')
    .reduce((s, b) => s + b.position_size_pct, 0);
  const totalIfApplied = otherUsedPct + sizePct;
  const overLimit = totalIfApplied > 30;

  const dirty = upper !== box.upper_price || lower !== box.lower_price ||
    strategy !== box.strategy_type || sizePct !== box.position_size_pct ||
    stopLoss !== box.stop_loss_pct || memo !== (box.memo || '');

  const valid = upper > lower && lower > 0 && sizePct > 0 && sizePct <= 30 && !overLimit && stopLoss < 0 && stopLoss >= -10;

  return React.createElement(U.Modal, {
    open: true, onClose, size: 'lg',
    title: stock.stock_name + ' · ' + box.box_tier + '차 박스 편집',
    subtitle: '상태 ' + box.status + ' · 현재가 ' + window.fmt.krw(stock.current_price) + '원',
    primary: { label: '변경 저장', onClick: () => { addToast({ kind: 'success', title: '박스 변경 저장됨', subtitle: stock.stock_name + ' ' + box.box_tier + '차' }); onClose(); }},
    secondary: { label: '취소', onClick: onClose },
    primaryDisabled: !valid || !dirty,
  },
    React.createElement('div', { className: 'col gap-16' },
      React.createElement('div', { className: 'box-form-grid' },
        React.createElement(U.Field, { label: '상단 (원)' }, React.createElement(U.NumInput, { value: upper, onChange: setUpper, step: 100 })),
        React.createElement(U.Field, { label: '하단 (원)', error: lower >= upper ? '하단은 상단보다 낮아야 합니다' : null },
          React.createElement(U.NumInput, { value: lower, onChange: setLower, step: 100, invalid: lower >= upper }))),
      React.createElement(U.Field, { label: '진입 전략' },
        React.createElement('div', { className: 'box-form-row' },
          React.createElement('button', { type: 'button', className: 'radio-tile' + (strategy === 'PULLBACK' ? ' is-selected' : ''), onClick: () => setStrategy('PULLBACK') },
            React.createElement('h4', null, '눌림 (PULLBACK)'),
            React.createElement('p', { className: 'helper' }, '박스 내 양봉 형성 시 매수')),
          React.createElement('button', { type: 'button', className: 'radio-tile' + (strategy === 'BREAKOUT' ? ' is-selected' : ''), onClick: () => setStrategy('BREAKOUT') },
            React.createElement('h4', null, '돌파 (BREAKOUT)'),
            React.createElement('p', { className: 'helper' }, '박스 상단 돌파 매수')))),
      React.createElement('div', { className: 'box-form-grid' },
        React.createElement(U.Field, { label: '비중 (%)', helper: '기타 박스 ' + otherUsedPct + '% + 신규 = ' + totalIfApplied.toFixed(1) + '% / 30%' },
          React.createElement(U.NumInput, { value: sizePct, onChange: setSizePct, min: 0.1, max: 30, step: 0.5, invalid: overLimit })),
        React.createElement(U.Field, { label: '손절폭 (%)' },
          React.createElement(U.NumInput, { value: stopLoss, onChange: setStopLoss, min: -10, max: -1, step: 0.5 }))),
      overLimit && React.createElement(U.InlineNotif, { kind: 'error', title: '비중 한도 초과', subtitle: '누적 ' + totalIfApplied.toFixed(1) + '% > 30%' }),
      React.createElement('div', { className: 'cds-tile', style: { background: 'var(--cds-layer-02)', padding: 12 } },
        React.createElement('div', { className: 'grid-3' },
          React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '예상 투입'), React.createElement('div', { className: 'mono' }, window.fmt.krw(investAmount), '원')),
          React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '예상 수량'), React.createElement('div', { className: 'mono' }, '약 ', estQty, '주')),
          React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '손절선'), React.createElement('div', { className: 'mono pnl-loss' }, window.fmt.krw(stopPrice), '원')))),
      React.createElement(U.Field, { label: '메모' }, React.createElement(U.Textarea, { value: memo, onChange: setMemo, rows: 2 }))));
}

window.Pages = window.Pages || {};
window.Pages.TrackedStocksList = TrackedStocksList;
window.Pages.TrackedStockDetail = TrackedStockDetail;
window.Pages.NewTrackedStockModal = NewTrackedStockModal;

})();
