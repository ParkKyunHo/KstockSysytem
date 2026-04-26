(function(){
/* BoxWizard — 7 step (PRD Patch #3: Step 1 경로 선택 추가) */
const { useState } = React;
const U = window.UI;
const I = window.Icons;

function BoxWizard({ stockId, onDone, onCancel, onNav, mock, addToast }) {
  if (typeof onNav !== 'function') onNav = () => {};
  const stock = mock.trackedStocks.find(s => s.id === stockId) || mock.trackedStocks[0];
  const existingBoxes = mock.boxes.filter(b => b.tracked_stock_id === stock.id && b.status !== 'INVALIDATED' && b.status !== 'CANCELLED');
  const usedPct = existingBoxes.reduce((s, b) => s + b.position_size_pct, 0);

  const [step, setStep] = useState(0);
  // PRD Patch #3: 경로는 박스 단위 속성. 종목의 path_type을 기본값으로 (없으면 PATH_A).
  const [path, setPath] = useState(stock.path_type || 'PATH_A');
  const [upper, setUpper] = useState(Math.round(stock.current_price * 1.01));
  const [lower, setLower] = useState(Math.round(stock.current_price * 0.99));
  const [strategy, setStrategy] = useState('PULLBACK');
  const [sizePct, setSizePct] = useState(10);
  const [stopLoss, setStopLoss] = useState(-5);
  const [memo, setMemo] = useState('');

  const totalCapital = mock.settings.general.total_capital;
  const investAmount = (totalCapital * sizePct) / 100;
  const estQty = upper > 0 ? Math.floor(investAmount / upper) : 0;
  const stopPrice = upper * (1 + stopLoss / 100);
  const boxWidth = upper - lower;
  const boxWidthPct = lower > 0 ? (boxWidth / lower) * 100 : 0;

  const totalPctIfAdded = usedPct + sizePct;
  const overLimit = totalPctIfAdded > 30;

  // 7단계: 0 경로, 1 전략, 2 가격, 3 비중, 4 손절, 5 확인, 6 저장
  const valid = (() => {
    if (step === 0) return path === 'PATH_A' || path === 'PATH_B';
    if (step === 1) return !!strategy;
    if (step === 2) return upper > 0 && lower > 0 && upper > lower;
    if (step === 3) return sizePct > 0 && sizePct <= 30 && !overLimit;
    if (step === 4) return stopLoss < 0 && stopLoss >= -10;
    return true;
  })();

  const next = () => {
    if (step < 5) setStep(step + 1);
    else if (step === 5) {
      setStep(6);
      setTimeout(() => { addToast({ kind: 'success', title: '박스 저장 완료', subtitle: `${stock.stock_name} ${existingBoxes.length + 1}차 박스 · ${path}` }); onDone(); }, 1200);
    }
  };
  const prev = () => step > 0 && setStep(step - 1);

  return React.createElement('div', null,
    React.createElement('div', { className: 'breadcrumbs' },
      React.createElement('a', { onClick: () => onNav('tracked-stocks') }, '추적 종목'),
      React.createElement('span', { className: 'sep' }, '/'),
      React.createElement('a', { onClick: () => onNav(`tracked-stocks/${stock.id}`) }, stock.stock_name),
      React.createElement('span', { className: 'sep' }, '/'),
      React.createElement('span', null, '박스 추가')),
    React.createElement('div', { className: 'page-hd' },
      React.createElement('div', null,
        React.createElement('h1', { className: 'page-hd__title' }, '박스 설정 — ', stock.stock_name),
        React.createElement('div', { className: 'page-hd__subtitle' }, `현재가 ${window.fmt.krw(stock.current_price)}원 · 기존 박스 ${existingBoxes.length}개 (사용 비중 ${usedPct}%)`))),

    React.createElement(U.ProgressIndicator, { current: step, steps: ['경로', '전략', '가격', '비중', '손절', '확인', '저장'] }),

    React.createElement('div', { className: 'cds-tile', style: { padding: 24 } },

      // Step 0 — 경로 (PRD Patch #3 신규)
      step === 0 && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '박스 진입 경로 선택'),
        React.createElement('p', { className: 'text-helper', style: { margin: 0 } },
          '같은 종목 안에서도 박스마다 다른 경로를 지정할 수 있습니다.'),
        React.createElement('div', { className: 'radio-tile-group' },
          React.createElement('button', { type: 'button', className: `radio-tile${path === 'PATH_A' ? ' is-selected' : ''}`, onClick: () => setPath('PATH_A') },
            React.createElement('h4', null, 'PATH_A — 단타 (3분봉)'),
            React.createElement('p', null, '며칠~몇 주 단위 매매. 박스 진입 → 빠른 청산.'),
            React.createElement('p', { className: 'helper' }, '진입: 3분봉 완성 즉시 매수'),
            React.createElement('p', { className: 'helper' }, '이용: 주도주, 테마주, 단기 모멘텀')),
          React.createElement('button', { type: 'button', className: `radio-tile${path === 'PATH_B' ? ' is-selected' : ''}`, onClick: () => setPath('PATH_B') },
            React.createElement('h4', null, 'PATH_B — 중기 (일봉)'),
            React.createElement('p', null, '월 단위 추세 추종. 분할 매수 + 트레일링 스탑.'),
            React.createElement('p', { className: 'helper' }, '진입: 일봉 완성 후 익일 09:01 매수'),
            React.createElement('p', { className: 'helper' }, '이용: 가치주, 증권주, 장기 테마'))),
        path === 'PATH_B' && React.createElement(U.InlineNotif, {
          kind: 'warning', lowContrast: true,
          title: '갭업 5% 이상 시 매수 포기',
          subtitle: 'PATH_B는 일봉 완성 후 익일 09:01 매수. 시초가 갭업이 5% 이상이면 진입을 포기합니다.'
        })
      ),

      // Step 1 — 전략 (기존 step 1)
      step === 1 && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '진입 전략 선택'),
        React.createElement('div', { className: 'radio-tile-group' },
          React.createElement('button', { type: 'button', className: `radio-tile${strategy === 'PULLBACK' ? ' is-selected' : ''}`, onClick: () => setStrategy('PULLBACK') },
            React.createElement('h4', null, '눌림 (PULLBACK)'),
            React.createElement('p', null, '박스 안에서 양봉 형성 시 매수'),
            React.createElement('p', { className: 'helper' }, '직전봉 + 현재봉 모두 양봉 + 박스 내 종가 · 봉 완성 직후 즉시 매수')),
          React.createElement('button', { type: 'button', className: `radio-tile${strategy === 'BREAKOUT' ? ' is-selected' : ''}`, onClick: () => setStrategy('BREAKOUT') },
            React.createElement('h4', null, '돌파 (BREAKOUT)'),
            React.createElement('p', null, '박스 상단 돌파 시 매수'),
            React.createElement('p', { className: 'helper' }, '종가 > 박스 상단 + 양봉 + 정상 시가 (갭업 제외)')))),

      // Step 2 — 가격 (기존 step 0)
      step === 2 && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '가격 범위 설정'),
        React.createElement('div', { className: 'tile-row', style: { background: 'var(--cds-layer-02)' } },
          React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '현재가'), React.createElement('div', { className: 'mono' }, window.fmt.krw(stock.current_price), '원')),
          React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '52주 최고'), React.createElement('div', { className: 'mono' }, window.fmt.krw(Math.round(stock.current_price * 1.15)), '원')),
          React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '52주 최저'), React.createElement('div', { className: 'mono' }, window.fmt.krw(Math.round(stock.current_price * 0.72)), '원'))),
        existingBoxes.length > 0 && React.createElement(U.InlineNotif, { kind: 'warning', title: '기존 박스 존재', subtitle: `이 종목에 ${existingBoxes.length}개의 활성 박스가 있습니다. 가격대 겹침 주의.`, lowContrast: true }),
        React.createElement(U.Field, { label: '박스 상단 (원)' }, React.createElement(U.NumInput, { value: upper, onChange: setUpper, step: 100 })),
        React.createElement(U.Field, { label: '박스 하단 (원)', error: lower >= upper ? '하단은 상단보다 낮아야 합니다' : null },
          React.createElement(U.NumInput, { value: lower, onChange: setLower, step: 100, invalid: lower >= upper })),
        React.createElement('div', { className: 'cds-tile', style: { background: 'var(--cds-layer-02)' } },
          React.createElement('div', { className: 'text-helper' }, '박스 폭'),
          React.createElement('div', { className: 'mono', style: { fontSize: 18 } },
            window.fmt.krw(boxWidth), '원 (', boxWidthPct.toFixed(2), '%)'))
      ),

      // Step 3 — 비중 (기존 step 2)
      step === 3 && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '비중 설정'),
        React.createElement(U.Field, { label: `비중 (%) — 단계별 한도 30%, 현재 사용 ${usedPct}%` },
          React.createElement('div', { className: 'row-12', style: { alignItems: 'center' } },
            React.createElement(U.NumInput, { value: sizePct, onChange: setSizePct, min: 0.1, max: 30, step: 0.5 }),
            React.createElement(U.SliderInput, { value: sizePct, onChange: setSizePct, min: 0.1, max: 30, step: 0.5, fmt: v => v + '%' }))),
        React.createElement('div', { className: 'cds-tile', style: { background: 'var(--cds-layer-02)' } },
          React.createElement('div', { className: 'grid-3' },
            React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '예상 투입'), React.createElement('div', { className: 'mono' }, window.fmt.krw(investAmount), '원')),
            React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '예상 수량'), React.createElement('div', { className: 'mono' }, '약 ', estQty, '주')),
            React.createElement('div', null, React.createElement('div', { className: 'text-helper' }, '추가 후 누적'), React.createElement('div', { className: 'mono' }, totalPctIfAdded.toFixed(1), '% / 30%')))),
        overLimit
          ? React.createElement(U.InlineNotif, { kind: 'error', title: '한도 초과', subtitle: `현재 ${usedPct}% + 신규 ${sizePct}% = ${totalPctIfAdded.toFixed(1)}%. 30% 한도를 초과합니다.` })
          : React.createElement(U.InlineNotif, { kind: 'success', title: '한도 내', subtitle: `누적 ${totalPctIfAdded.toFixed(1)}% / 30%`, lowContrast: true })),

      // Step 4 — 손절 (기존 step 3)
      step === 4 && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '손절폭 설정'),
        React.createElement(U.Field, { label: '손절폭 (%) — 매수 후 ~ +5% 미만 구간에 적용' },
          React.createElement('div', { className: 'row-12', style: { alignItems: 'center' } },
            React.createElement(U.NumInput, { value: -stopLoss, onChange: v => setStopLoss(-Math.abs(v)), min: 1, max: 10, step: 0.5 }),
            React.createElement(U.SliderInput, { value: -stopLoss, onChange: v => setStopLoss(-Math.abs(v)), min: 1, max: 10, step: 0.5, fmt: v => '-' + v + '%' }))),
        React.createElement('div', { className: 'cds-tile', style: { background: 'var(--cds-layer-02)' } },
          React.createElement('div', { className: 'text-helper' }, '예상 손절선 (박스 상단 ', window.fmt.krw(upper), '원 기준)'),
          React.createElement('div', { className: 'mono pnl-loss', style: { fontSize: 20 } }, window.fmt.krw(stopPrice), '원')),
        React.createElement(U.InlineNotif, { kind: 'info', lowContrast: true, title: '단계별 손절 자동 전환',
          subtitle: '매수 ~ +5% 미만: 사용자 설정 / +5% 청산 후: -2% / +10% 청산 후: +4% (본전)' })),

      // Step 5 — 확인 (기존 step 4) · 경로 항목 추가
      step === 5 && React.createElement('div', { className: 'col gap-16' },
        React.createElement('h3', { style: { margin: 0 } }, '저장 전 확인'),
        React.createElement('div', { className: 'cds-slist' },
          [
            ['종목', `${stock.stock_name} (${stock.stock_code})`],
            ['경로', path === 'PATH_A' ? 'PATH_A — 단타 (3분봉)' : 'PATH_B — 중기 (일봉)'],
            ['Tier', `${existingBoxes.length + 1}차 박스`],
            ['가격', `${window.fmt.krw(lower)} ~ ${window.fmt.krw(upper)}원 (폭 ${boxWidthPct.toFixed(2)}%)`],
            ['전략', strategy],
            ['비중', `${sizePct}% (예상 ${window.fmt.krw(investAmount)}원, 약 ${estQty}주)`],
            ['손절폭', `${stopLoss}% → ${window.fmt.krw(stopPrice)}원`],
          ].map(([k, v]) => React.createElement('div', { key: k, className: 'cds-slist__row' },
            React.createElement('div', { className: 'cds-slist__cell' }, k),
            React.createElement('div', { className: 'cds-slist__cell mono' }, v)))),
        React.createElement(U.Field, { label: '메모 (선택)' }, React.createElement(U.Textarea, { value: memo, onChange: setMemo, rows: 2 }))),

      // Step 6 — 저장 (기존 step 5)
      step === 6 && React.createElement('div', { className: 'col gap-16', style: { alignItems: 'center', textAlign: 'center', padding: 32 } },
        React.createElement(I.Success, { size: 48, style: { fill: 'var(--cds-support-success)' } }),
        React.createElement('h3', null, '박스 저장 중...'),
        React.createElement(U.ProgressBar, { value: 60, helper: '서버에 저장하는 중' }))
    ),

    step < 6 && React.createElement('div', { style: { display: 'flex', gap: 12, marginTop: 16, justifyContent: 'flex-end' } },
      React.createElement(U.Btn, { kind: 'secondary', onClick: step === 0 ? onCancel : prev }, step === 0 ? '취소' : '이전'),
      React.createElement(U.Btn, { kind: 'primary', onClick: next, disabled: !valid }, step === 5 ? '저장' : '다음'))
  );
}

window.Pages = window.Pages || {};
window.Pages.BoxWizard = BoxWizard;

})();
