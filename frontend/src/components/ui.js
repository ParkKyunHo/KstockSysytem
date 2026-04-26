(function(){
/* V7.1 Common UI components — Carbon-style */
/* Globals: window.UI = { Tag, Btn, Modal, Toast, Tile, KPITile, Pagination, ... } */
const { useState, useEffect, useRef, useCallback } = React;
const I = window.Icons;

// ===== Tag =====
function Tag({ type='gray', size, children }) {
  return React.createElement('span', { className: `cds-tag cds-tag--${type}${size==='sm'?' cds-tag--sm':''}` }, children);
}

// ===== Button =====
function Btn({ kind='primary', size, icon: Icon, full, onClick, disabled, children, type='button', title }) {
  const cls = ['cds-btn'];
  if (kind !== 'primary') cls.push(`cds-btn--${kind}`);
  if (size) cls.push(`cds-btn--${size}`);
  if (full) cls.push('cds-btn--full');
  if (Icon) cls.push('cds-btn--has-icon');
  return React.createElement('button', { type, className: cls.join(' '), onClick, disabled, title },
    children,
    Icon && React.createElement(Icon, { className: 'cds-btn-icon' })
  );
}

// ===== Field / Input =====
function Field({ label, helper, error, children }) {
  return React.createElement('div', { className: 'cds-field' },
    label && React.createElement('label', { className: 'cds-field__label' }, label),
    children,
    error ? React.createElement('span', { className: 'cds-field__error' }, error)
      : helper ? React.createElement('span', { className: 'cds-field__helper' }, helper) : null
  );
}
function Input({ value, onChange, placeholder, type='text', invalid, lg, mono, maxLength, autoFocus, disabled }) {
  return React.createElement('input', {
    type, value: value ?? '', onChange: e => onChange && onChange(e.target.value),
    placeholder, maxLength, autoFocus, disabled,
    className: `cds-input${invalid?' cds-input--invalid':''}${lg?' cds-input--lg':''}${mono?' mono':''}`,
  });
}
function NumInput({ value, onChange, step=1, min, max, invalid }) {
  return React.createElement('input', {
    type: 'number', value: value ?? '', step, min, max,
    onChange: e => onChange && onChange(e.target.value === '' ? null : Number(e.target.value)),
    className: `cds-input mono${invalid?' cds-input--invalid':''}`,
  });
}
function Textarea({ value, onChange, placeholder, rows=3 }) {
  return React.createElement('textarea', {
    value: value ?? '', onChange: e => onChange && onChange(e.target.value),
    placeholder, rows, className: 'cds-input',
  });
}

// ===== Search =====
function SearchBox({ value, onChange, placeholder='검색', lg }) {
  return React.createElement('div', { className: `cds-search${lg?' cds-search--lg':''}` },
    React.createElement(I.Search, { className: 'cds-search__icon' }),
    React.createElement('input', { value, onChange: e => onChange(e.target.value), placeholder })
  );
}

// ===== Toggle =====
function Toggle({ on, checked, onChange, disabled, label, helper, sub }) {
  const value = on != null ? on : !!checked;
  helper = helper || sub;
  on = value;
  return React.createElement('div', { className: 'col gap-8' },
    React.createElement('button', {
      className: `toggle${on?' is-on':''}`, onClick: () => !disabled && onChange(!on), disabled, type: 'button'
    },
      React.createElement('span', { className: 'toggle__track' }, React.createElement('span', { className: 'toggle__thumb' })),
      React.createElement('span', null, label)
    ),
    helper && React.createElement('span', { className: 'cds-field__helper' }, helper)
  );
}

// ===== Checkbox =====
function Checkbox({ checked, onChange, label }) {
  return React.createElement('label', { className: 'cds-checkbox' },
    React.createElement('input', { type: 'checkbox', checked: !!checked, onChange: e => onChange && onChange(e.target.checked) }),
    React.createElement('span', { className: 'cds-checkbox__box' }),
    React.createElement('span', null, label)
  );
}

// ===== Radio Tile Group =====
function RadioTileGroup({ value, onChange, options }) {
  return React.createElement('div', { className: 'radio-tile-group' },
    options.map(opt => React.createElement('button', {
      key: opt.value, type: 'button',
      className: `radio-tile${value === opt.value ? ' is-selected' : ''}`,
      onClick: () => onChange(opt.value)
    },
      React.createElement('h4', null, opt.title),
      opt.desc && React.createElement('p', null, opt.desc),
      opt.helper && React.createElement('p', { className: 'helper' }, opt.helper)
    ))
  );
}

// ===== Slider =====
function SliderInput({ value, onChange, min=0, max=100, step=1, fmt }) {
  return React.createElement('div', { className: 'slider' },
    React.createElement('input', { type: 'range', min, max, step, value, onChange: e => onChange(Number(e.target.value)) }),
    React.createElement('span', { className: 'slider__value' }, fmt ? fmt(value) : value)
  );
}

// ===== Dropdown =====
function Dropdown({ value, onChange, options, placeholder='선택' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const sel = options.find(o => o.value === value);
  return React.createElement('div', { className: 'cds-dropdown', ref },
    React.createElement('button', { className: 'cds-dropdown__trigger', onClick: () => setOpen(!open), type: 'button' },
      React.createElement('span', null, sel ? sel.label : placeholder),
      React.createElement(I.CaretDown, { className: 'cds-icon' })
    ),
    open && React.createElement('div', { className: 'cds-dropdown__menu' },
      options.map(o => React.createElement('button', {
        key: o.value, className: 'cds-dropdown__item', type: 'button',
        onClick: () => { onChange(o.value); setOpen(false); }
      }, o.label))
    )
  );
}

// ===== OverflowMenu =====
function OverflowMenu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const h = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  return React.createElement('div', { className: 'overflow-menu', ref },
    React.createElement('button', { className: 'overflow-menu__trigger', onClick: () => setOpen(!open), type: 'button' },
      React.createElement(I.More, { className: 'cds-icon' })
    ),
    open && React.createElement('div', { className: 'overflow-menu__menu' },
      items.map((it, i) => it.divider
        ? React.createElement('div', { key: i, className: 'overflow-menu__divider' })
        : React.createElement('button', {
            key: i, className: `overflow-menu__item${it.danger?' overflow-menu__item--danger':''}`, type: 'button',
            onClick: () => { setOpen(false); it.onClick && it.onClick(); }
          }, it.label)
      )
    )
  );
}

// ===== Modal =====
function Modal({ open, onClose, title, subtitle, danger, children, primary, secondary, size, primaryDisabled, primaryLoading, footer }) {
  if (!open) return null;
  return React.createElement('div', { className: 'cds-modal-overlay', onClick: e => e.target === e.currentTarget && onClose && onClose() },
    React.createElement('div', { className: `cds-modal${size==='xl'?' cds-modal--xl':size==='lg'?' cds-modal--lg':size==='md'?' cds-modal--md':size==='sm'?' cds-modal--sm':''}` },
      React.createElement('div', { className: 'cds-modal__hd' },
        subtitle && React.createElement('div', { className: 'cds-modal__subtitle' }, subtitle),
        React.createElement('div', { className: `cds-modal__title${danger?' cds-modal__title--danger':''}` }, title),
        onClose && React.createElement('button', { className: 'cds-modal__close', onClick: onClose, type: 'button' },
          React.createElement(I.Close, { className: 'cds-icon' }))
      ),
      React.createElement('div', { className: 'cds-modal__body' }, children),
      footer || (primary || secondary) && React.createElement('div', { className: 'cds-modal__ft' },
        secondary && React.createElement(Btn, { kind: 'secondary', onClick: secondary.onClick }, secondary.label),
        primary && React.createElement(Btn, { kind: danger ? 'danger' : 'primary', onClick: primary.onClick, disabled: primaryDisabled || primaryLoading },
          primaryLoading ? '처리 중...' : primary.label)
      )
    )
  );
}

// ===== Inline Notification =====
function InlineNotif({ kind='info', title, subtitle, caption, lowContrast, action, onClose }) {
  const Icon = { info: I.Info, success: I.Success, warning: I.Warning, error: I.Error }[kind];
  return React.createElement('div', { className: `cds-inline-notif cds-inline-notif--${kind}${lowContrast?' cds-inline-notif--low':''}` },
    Icon && React.createElement(Icon, { className: `cds-inline-notif__icon cds-inline-notif__icon--${kind}` }),
    React.createElement('div', { className: 'cds-inline-notif__body' },
      title && React.createElement('div', { className: 'cds-inline-notif__title' }, title),
      subtitle && React.createElement('div', { className: 'cds-inline-notif__subtitle' }, subtitle),
      caption && React.createElement('div', { className: 'cds-inline-notif__caption' }, caption)
    ),
    action && React.createElement(Btn, { kind: 'ghost', size: 'sm', onClick: action.onClick }, action.label),
    onClose && React.createElement('button', { className: 'cds-modal__close', style: { position: 'static', marginLeft: 8 }, onClick: onClose, type: 'button' },
      React.createElement(I.Close, { className: 'cds-icon' }))
  );
}

// ===== Toast Container =====
function ToastContainer({ toasts, onClose }) {
  return React.createElement('div', { className: 'toast-container' },
    toasts.map(t => React.createElement('div', { key: t.id, className: `cds-toast cds-toast--${t.kind || 'info'}` },
      React.createElement('div', { style: { fontWeight: 600, fontSize: 14, marginBottom: 2 } }, t.title),
      t.subtitle && React.createElement('div', { style: { fontSize: 13, color: 'var(--cds-text-secondary)' } }, t.subtitle),
      t.caption && React.createElement('div', { style: { fontSize: 12, color: 'var(--cds-text-helper)', marginTop: 4, fontFamily: 'var(--font-mono)' } }, t.caption),
      React.createElement('button', { className: 'cds-toast__close', onClick: () => onClose(t.id), type: 'button' },
        React.createElement(I.Close, { className: 'cds-icon' }))
    ))
  );
}

// ===== Tabs =====
function Tabs({ value, onChange, tabs }) {
  return React.createElement('div', { className: 'cds-tabs' },
    tabs.map(t => React.createElement('button', {
      key: t.value, className: `cds-tabs__tab${value===t.value?' is-active':''}`, type: 'button',
      onClick: () => onChange(t.value)
    }, t.label, t.count != null && ` (${t.count})`))
  );
}

// ===== ProgressIndicator =====
function ProgressIndicator({ steps, current }) {
  return React.createElement('ol', { className: 'cds-prog' },
    steps.map((s, i) => React.createElement('li', {
      key: i,
      className: `cds-prog__step${i<current?' is-complete':i===current?' is-current':''}`
    },
      React.createElement('span', { className: 'cds-prog__circle' }, i<current ? React.createElement(I.Check, { className: 'cds-icon' }) : (i+1)),
      React.createElement('span', { className: 'cds-prog__label' }, s)
    ))
  );
}

// ===== ProgressBar =====
function ProgressBar({ value, max=100, kind, label, helper, sm }) {
  const cls = ['progress-bar'];
  if (kind) cls.push(`progress-bar--${kind}`);
  return React.createElement('div', { className: 'col gap-8' },
    label && React.createElement('div', { style: { fontSize: 12, color: 'var(--cds-text-secondary)' } }, label),
    React.createElement('div', { className: cls.join(' '), style: { height: sm ? 2 : 4 } },
      React.createElement('div', { className: 'progress-bar__fill', style: { width: `${Math.min(100, (value/max)*100)}%` } })),
    helper && React.createElement('div', { className: 'cds-field__helper' }, helper)
  );
}

// ===== Pagination =====
function Pagination({ total, page, perPage, onPage }) {
  const last = Math.max(1, Math.ceil(total / perPage));
  const start = (page-1)*perPage + 1;
  const end = Math.min(total, page*perPage);
  return React.createElement('div', { className: 'pagination' },
    React.createElement('span', null, `${start}–${end} / 총 ${total}`),
    React.createElement('div', { className: 'pagination__btns' },
      React.createElement('button', { className: 'pagination__btn', disabled: page<=1, onClick: () => onPage(page-1), type: 'button' },
        React.createElement(I.ChevronLeft, { className: 'cds-icon' })),
      React.createElement('span', { style: { padding: '0 8px', alignSelf: 'center' } }, `${page} / ${last}`),
      React.createElement('button', { className: 'pagination__btn', disabled: page>=last, onClick: () => onPage(page+1), type: 'button' },
        React.createElement(I.ChevronRight, { className: 'cds-icon' }))
    )
  );
}

// ===== Tile / KPI =====
function KPITile({ label, value, sub, color, progress }) {
  return React.createElement('div', { className: 'kpi-tile' },
    React.createElement('div', { className: 'kpi-tile__label' }, label),
    React.createElement('div', {
      className: `kpi-tile__value${color==='profit'?' pnl-profit':color==='loss'?' pnl-loss':''}`,
    }, value),
    sub && React.createElement('div', { className: 'kpi-tile__sub' }, sub),
    progress != null && React.createElement(ProgressBar, { value: progress })
  );
}

// ===== PnL Cell =====
function PnLCell({ amount, pct, big }) {
  const isProfit = amount >= 0;
  return React.createElement('div', { className: `pnl-row ${isProfit ? 'pnl-profit' : 'pnl-loss'}` },
    React.createElement('strong', { style: big ? { fontSize: 24 } : null }, window.fmt.pct(pct)),
    React.createElement('small', { className: isProfit ? 'pnl-profit' : 'pnl-loss', style: { fontFamily: 'var(--font-mono)' } },
      window.fmt.krwSigned(amount), '원')
  );
}

// ===== Severity → Tag =====
function SeverityTag({ severity, sm }) {
  const map = { CRITICAL: { type: 'red', label: 'CRITICAL' }, HIGH: { type: 'magenta', label: 'HIGH' }, MEDIUM: { type: 'blue', label: 'MEDIUM' }, LOW: { type: 'cool-gray', label: 'LOW' } };
  const m = map[severity] || map.LOW;
  return React.createElement(Tag, { type: m.type, size: sm ? 'sm' : null }, m.label);
}

// ===== Status Tag (tracked stock) =====
function TrackedStatusTag({ status, sm }) {
  const map = {
    TRACKING: { type: 'cool-gray', label: '추적 중' },
    BOX_SET: { type: 'blue', label: '박스 설정' },
    POSITION_OPEN: { type: 'green', label: '포지션 보유' },
    POSITION_PARTIAL: { type: 'cyan', label: '부분 청산' },
    EXITED: { type: 'cool-gray', label: '종료' },
  };
  const m = map[status] || map.TRACKING;
  return React.createElement(Tag, { type: m.type, size: sm ? 'sm' : null }, m.label);
}

function PositionSourceTag({ source }) {
  const map = { SYSTEM_A: { type: 'blue', label: 'SYSTEM_A' }, SYSTEM_B: { type: 'purple', label: 'SYSTEM_B' }, MANUAL: { type: 'warning', label: 'MANUAL' } };
  const m = map[source] || map.MANUAL;
  return React.createElement(Tag, { type: m.type }, m.label);
}

function BoxStatusTag({ status }) {
  const map = { WAITING: { type: 'cool-gray', label: '대기' }, TRIGGERED: { type: 'green', label: '진입 완료' }, INVALIDATED: { type: 'red', label: '무효화' }, CANCELLED: { type: 'cool-gray', label: '취소' } };
  const m = map[status] || map.WAITING;
  return React.createElement(Tag, { type: m.type }, m.label);
}

// ===== Skeleton =====
function Skeleton({ height = 20, width = '100%' }) {
  return React.createElement('div', { style: { height, width, background: 'var(--cds-skeleton-background)', animation: 'pulse 1.5s ease-in-out infinite' } });
}

// ===== Tile =====
function Tile({ children, padding=16, ...rest }) {
  return React.createElement('div', { className: 'cds-tile', style: { padding }, ...rest }, children);
}

// ===== Expandable Tile =====
function ExpandableTile({ head, children, defaultOpen=false }) {
  const [open, setOpen] = useState(defaultOpen);
  return React.createElement('div', { className: `expand-tile${open?' is-expanded':''}` },
    React.createElement('button', { className: 'expand-tile__head', onClick: () => setOpen(!open), type: 'button' },
      React.createElement(I.ChevronRight, { className: 'expand-tile__chevron' }),
      React.createElement('div', { style: { flex: 1 } }, head)
    ),
    open && React.createElement('div', { className: 'expand-tile__body' }, children)
  );
}

window.UI = {
  Tag, Btn, Field, Input, TextInput: Input, NumInput, Textarea, SearchBox, Toggle, Checkbox,
  RadioTileGroup, SliderInput, Dropdown, OverflowMenu, Modal, InlineNotif, ToastContainer,
  Tabs, ProgressIndicator, ProgressBar, Pagination, KPITile, MetricTile: KPITile, PnLCell,
  SeverityTag, TrackedStatusTag, PositionSourceTag, BoxStatusTag, Tile, ExpandableTile, Skeleton,
};

})();
