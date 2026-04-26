(function(){
/* OrderDialog — manual buy / sell with safety checks */
const { useState, useMemo } = React;
const U = window.UI;
const I = window.Icons;

function OrderDialog({ open, onClose, mock, addToast, defaultStock, defaultSide, defaultPosition }) {
  const [side, setSide] = useState(defaultSide || 'BUY'); // BUY / SELL
  const [stockId, setStockId] = useState((defaultStock && defaultStock.id) || (defaultPosition && defaultPosition.tracked_stock_id) || mock.trackedStocks[0].id);
  const [orderType, setOrderType] = useState('LIMIT'); // LIMIT / MARKET
  const [quantity, setQuantity] = useState(1);
  const [price, setPrice] = useState(0);
  const [reason, setReason] = useState('');
  const [confirmStep, setConfirmStep] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const stock = mock.trackedStocks.find(s => s.id === stockId) || mock.trackedStocks[0];
  const position = side === 'SELL'
    ? (defaultPosition || mock.positions.find(p => p.tracked_stock_id === stock.id && p.status !== 'CLOSED'))
    : null;

  // initialize price from stock
  React.useEffect(() => { if (stock) setPrice(stock.current_price); }, [stock]);
  React.useEffect(() => {
    if (open) {
      setConfirmStep(false); setSubmitting(false);
      setSide(defaultSide || 'BUY');
      setStockId((defaultStock && defaultStock.id) || (defaultPosition && defaultPosition.tracked_stock_id) || mock.trackedStocks[0].id);
      setOrderType('LIMIT'); setQuantity(1); setReason('');
    }
  }, [open, defaultStock, defaultSide, defaultPosition]);

  const totalCapital = mock.settings.general.total_capital;
  const orderPrice = orderType === 'MARKET' ? stock.current_price : price;
  const totalAmount = orderPrice * quantity;
  const totalPct = (totalAmount / totalCapital) * 100;
  const fees = Math.round(totalAmount * 0.00015 + (side === 'SELL' ? totalAmount * 0.0023 : 0));

  // Validations
  const errors = [];
  if (!stockId) errors.push('종목을 선택하세요');
  if (quantity <= 0) errors.push('수량은 1주 이상');
  if (orderType === 'LIMIT' && price <= 0) errors.push('지정가는 0보다 커야 합니다');
  if (side === 'SELL' && position && quantity > position.total_quantity) errors.push('보유 수량(' + position.total_quantity + '주) 초과');
  if (side === 'BUY' && totalPct > 30) errors.push('단일 종목 30% 한도 초과 (' + totalPct.toFixed(1) + '%)');

  // Warnings (allow but caution)
  const warnings = [];
  if (orderType === 'LIMIT' && side === 'BUY' && price > stock.current_price * 1.03) warnings.push('지정가가 현재가 대비 +3% 초과 — 즉시 체결 가능성');
  if (orderType === 'LIMIT' && side === 'SELL' && price < stock.current_price * 0.97) warnings.push('지정가가 현재가 대비 -3% 초과 — 즉시 체결 가능성');
  if (orderType === 'MARKET') warnings.push('시장가 — 체결 가격이 현재가와 다를 수 있습니다');
  if (side === 'BUY' && totalPct > 15) warnings.push('단일 종목 비중 ' + totalPct.toFixed(1) + '% — 권장 한도 15% 초과');

  const valid = errors.length === 0;

  const submit = () => {
    setSubmitting(true);
    setTimeout(() => {
      addToast({
        kind: 'success',
        title: (side === 'BUY' ? '매수' : '매도') + ' 주문 접수',
        subtitle: stock.stock_name + ' · ' + quantity + '주 · ' + (orderType === 'MARKET' ? '시장가' : window.fmt.krw(price) + '원'),
        caption: 'order_id: ord-' + Math.random().toString(36).slice(2, 10),
      });
      setSubmitting(false);
      onClose();
    }, 800);
  };

  if (!open) return null;

  return React.createElement(U.Modal, {
    open: true, onClose, size: 'md',
    title: confirmStep ? '주문 확인' : '수동 주문',
    subtitle: confirmStep ? '아래 내용을 확인하고 전송하세요' : '신중하게 입력하세요 — 즉시 키움 API로 전송됩니다',
    danger: side === 'SELL',
    primary: confirmStep
      ? { label: submitting ? '전송 중...' : (side === 'BUY' ? '매수 주문 전송' : '매도 주문 전송'), onClick: submit }
      : { label: '주문 검토', onClick: () => setConfirmStep(true) },
    primaryDisabled: !valid || submitting,
    secondary: confirmStep
      ? { label: '돌아가기', onClick: () => setConfirmStep(false) }
      : { label: '취소', onClick: onClose },
  },
    confirmStep
      ? React.createElement(OrderConfirmView, { side, stock, quantity, orderType, orderPrice, totalAmount, totalPct, fees, reason, position })
      : React.createElement(OrderFormView, {
          side, setSide, mock, stock, stockId, setStockId,
          orderType, setOrderType, quantity, setQuantity, price, setPrice,
          reason, setReason, position, errors, warnings,
          totalAmount, totalPct, fees,
          fixedSide: !!defaultSide, fixedStock: !!defaultStock || !!defaultPosition,
        })
  );
}

function OrderFormView({ side, setSide, mock, stock, stockId, setStockId, orderType, setOrderType,
                       quantity, setQuantity, price, setPrice, reason, setReason, position,
                       errors, warnings, totalAmount, totalPct, fees, fixedSide, fixedStock }) {
  return React.createElement('div', { className: 'col gap-16' },

    // Side toggle
    !fixedSide && React.createElement('div', { className: 'order-side-toggle' },
      React.createElement('button', {
        type: 'button',
        className: 'is-buy' + (side === 'BUY' ? ' is-active' : ''),
        onClick: () => setSide('BUY')
      }, '매수'),
      React.createElement('button', {
        type: 'button',
        className: 'is-sell' + (side === 'SELL' ? ' is-active' : ''),
        onClick: () => setSide('SELL')
      }, '매도')),

    // Stock picker
    React.createElement(U.Field, { label: '종목' },
      fixedStock
        ? React.createElement('div', { className: 'cds-tile', style: { padding: 12, background: 'var(--cds-layer-02)' } },
            React.createElement('strong', null, stock.stock_name), ' ',
            React.createElement('span', { className: 'mono text-helper' }, stock.stock_code), ' · ',
            React.createElement('span', { className: 'mono' }, window.fmt.krw(stock.current_price), '원'))
        : React.createElement(U.Dropdown, { value: stockId, onChange: setStockId,
            options: mock.trackedStocks
              .filter(s => side === 'SELL' ? mock.positions.some(p => p.tracked_stock_id === s.id && p.status !== 'CLOSED') : true)
              .map(s => ({ value: s.id, label: s.stock_name + ' (' + s.stock_code + ') · ' + window.fmt.krw(s.current_price) + '원' })),
          })),

    // Position info if SELL
    side === 'SELL' && position && React.createElement('div', { className: 'cds-tile', style: { background: 'var(--cds-layer-02)', padding: 12 } },
      React.createElement('div', { className: 'grid-3' },
        React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '보유'), React.createElement('div', { className: 'mono' }, position.total_quantity, '주')),
        React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '평단가'), React.createElement('div', { className: 'mono' }, window.fmt.krw(position.weighted_avg_price), '원')),
        React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '평가손익'),
          React.createElement('div', { className: 'mono ' + (position.pnl_amount >= 0 ? 'pnl-profit' : 'pnl-loss') }, window.fmt.krwSigned(position.pnl_amount), '원')))),

    // Order type + qty + price
    React.createElement('div', { className: 'box-form-grid' },
      React.createElement(U.Field, { label: '주문 유형' },
        React.createElement(U.Dropdown, { value: orderType, onChange: setOrderType, options: [
          { value: 'LIMIT', label: '지정가' },
          { value: 'MARKET', label: '시장가' },
        ]})),
      React.createElement(U.Field, { label: '수량 (주)' },
        React.createElement(U.NumInput, { value: quantity, onChange: setQuantity, min: 1, step: 1 }))),

    orderType === 'LIMIT' && React.createElement(U.Field, {
      label: '지정가 (원)',
      helper: '현재가 ' + window.fmt.krw(stock.current_price) + '원 (' + (price > 0 ? (((price - stock.current_price) / stock.current_price) * 100).toFixed(2) : 0) + '%)',
    },
      React.createElement(U.NumInput, { value: price, onChange: setPrice, step: 100 })),

    // Quick qty buttons (for SELL)
    side === 'SELL' && position && React.createElement('div', { className: 'row-12' },
      [25, 50, 75, 100].map(p => React.createElement(U.Btn, {
        key: p, kind: 'tertiary', size: 'sm',
        onClick: () => setQuantity(Math.max(1, Math.floor(position.total_quantity * p / 100)))
      }, p + '%'))),

    // Summary
    React.createElement('div', { className: 'order-summary' },
      React.createElement('div', null, '주문 금액'),
      React.createElement('div', null, window.fmt.krw(totalAmount), '원'),
      React.createElement('div', null, '비중'),
      React.createElement('div', null, totalPct.toFixed(2), '%'),
      React.createElement('div', null, '예상 수수료/세금'),
      React.createElement('div', null, window.fmt.krw(fees), '원'),
      React.createElement('div', null, side === 'BUY' ? '총 매수가' : '실수령액'),
      React.createElement('div', { style: { fontWeight: 600 } }, window.fmt.krw(side === 'BUY' ? totalAmount + fees : totalAmount - fees), '원')),

    // Errors / warnings
    errors.length > 0 && React.createElement(U.InlineNotif, { kind: 'error', title: '주문 불가',
      subtitle: errors.join(' · ') }),
    errors.length === 0 && warnings.length > 0 && React.createElement(U.InlineNotif, { kind: 'warning', title: '주의',
      subtitle: warnings.join(' · '), lowContrast: true }),

    // Reason
    React.createElement(U.Field, { label: '사유 (선택, 추후 분석용)' },
      React.createElement(U.Textarea, { value: reason, onChange: setReason, rows: 2,
        placeholder: '예: 시장 급변동, 손절 지연 등' }))
  );
}

function OrderConfirmView({ side, stock, quantity, orderType, orderPrice, totalAmount, totalPct, fees, reason, position }) {
  return React.createElement('div', { className: 'col gap-16' },
    React.createElement(U.InlineNotif, { kind: side === 'BUY' ? 'info' : 'warning',
      title: '실거래 주문 — 키움 API로 전송됩니다',
      subtitle: '취소는 미체결 상태에서만 가능. 시장가는 즉시 체결.',
      lowContrast: true }),
    React.createElement('div', { className: 'cds-slist' },
      [
        ['종류', side === 'BUY' ? '매수' : '매도'],
        ['종목', stock.stock_name + ' (' + stock.stock_code + ')'],
        ['주문 유형', orderType === 'LIMIT' ? '지정가' : '시장가'],
        ['수량', quantity + '주'],
        ['가격', orderType === 'MARKET' ? '시장가 (현재 ' + window.fmt.krw(stock.current_price) + '원)' : window.fmt.krw(orderPrice) + '원'],
        ['주문 금액', window.fmt.krw(totalAmount) + '원'],
        ['비중', totalPct.toFixed(2) + '%'],
        ['수수료/세금', window.fmt.krw(fees) + '원'],
        side === 'SELL' && position ? ['청산 후 잔량', (position.total_quantity - quantity) + '주'] : null,
        reason ? ['사유', reason] : null,
      ].filter(Boolean).map(([k, v]) => React.createElement('div', { key: k, className: 'cds-slist__row' },
        React.createElement('div', { className: 'cds-slist__cell' }, k),
        React.createElement('div', { className: 'cds-slist__cell mono', style: { fontWeight: 600 } }, v)))));
}

window.UI = window.UI || {};
window.UI.OrderDialog = OrderDialog;

})();
