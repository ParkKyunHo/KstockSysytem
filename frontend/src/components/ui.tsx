// V7.1 UI primitives -- direct port of frontend-prototype/src/components/ui.js.
// Uses the BEM classes defined in src/styles/legacy/{carbon-components,app}.css.

import {
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';

import { I, type IconComponent } from './icons';
import { formatKrwSigned, formatPct } from '@/lib/formatters';
import type { BoxStatus, PositionSource, Severity, TrackedStatus } from '@/types';

// ===== Tag =====================================================

export type TagType =
  | 'gray'
  | 'cool-gray'
  | 'warm-gray'
  | 'red'
  | 'magenta'
  | 'purple'
  | 'blue'
  | 'cyan'
  | 'teal'
  | 'green'
  | 'warning';

export function Tag({
  type = 'gray',
  size,
  children,
}: {
  type?: TagType;
  size?: 'sm';
  children: ReactNode;
}) {
  return (
    <span
      className={`cds-tag cds-tag--${type}${size === 'sm' ? ' cds-tag--sm' : ''}`}
    >
      {children}
    </span>
  );
}

// ===== Button ==================================================

export type BtnKind =
  | 'primary'
  | 'secondary'
  | 'tertiary'
  | 'ghost'
  | 'danger'
  | 'danger-tertiary';
export type BtnSize = 'sm' | 'md' | 'lg';

export function Btn({
  kind = 'primary',
  size,
  icon: Icon,
  full,
  onClick,
  disabled,
  children,
  type = 'button',
  title,
}: {
  kind?: BtnKind;
  size?: BtnSize;
  icon?: IconComponent;
  full?: boolean;
  onClick?: () => void;
  disabled?: boolean;
  children?: ReactNode;
  type?: 'button' | 'submit';
  title?: string;
}) {
  const cls = ['cds-btn'];
  if (kind !== 'primary') cls.push(`cds-btn--${kind}`);
  if (size) cls.push(`cds-btn--${size}`);
  if (full) cls.push('cds-btn--full');
  if (Icon) cls.push('cds-btn--has-icon');
  return (
    <button
      type={type}
      className={cls.join(' ')}
      onClick={onClick}
      disabled={disabled}
      title={title}
    >
      {children}
      {Icon ? <Icon className="cds-btn-icon" /> : null}
    </button>
  );
}

// ===== Field / Input ==========================================

export function Field({
  label,
  helper,
  error,
  children,
}: {
  label?: string;
  helper?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="cds-field">
      {label ? <label className="cds-field__label">{label}</label> : null}
      {children}
      {error ? (
        <span className="cds-field__error">{error}</span>
      ) : helper ? (
        <span className="cds-field__helper">{helper}</span>
      ) : null}
    </div>
  );
}

export function Input({
  value,
  onChange,
  placeholder,
  type = 'text',
  invalid,
  lg,
  mono,
  maxLength,
  autoFocus,
  disabled,
  onKeyDown,
}: {
  value?: string;
  onChange?: (v: string) => void;
  placeholder?: string;
  type?: string;
  invalid?: boolean;
  lg?: boolean;
  mono?: boolean;
  maxLength?: number;
  autoFocus?: boolean;
  disabled?: boolean;
  onKeyDown?: (e: KeyboardEvent<HTMLInputElement>) => void;
}) {
  return (
    <input
      type={type}
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
      placeholder={placeholder}
      maxLength={maxLength}
      autoFocus={autoFocus}
      disabled={disabled}
      onKeyDown={onKeyDown}
      className={`cds-input${invalid ? ' cds-input--invalid' : ''}${lg ? ' cds-input--lg' : ''}${mono ? ' mono' : ''}`}
    />
  );
}

export function NumInput({
  value,
  onChange,
  step = 1,
  min,
  max,
  invalid,
}: {
  value: number | null;
  onChange?: (v: number | null) => void;
  step?: number;
  min?: number;
  max?: number;
  invalid?: boolean;
}) {
  return (
    <input
      type="number"
      value={value ?? ''}
      step={step}
      min={min}
      max={max}
      onChange={(e: ChangeEvent<HTMLInputElement>) =>
        onChange?.(e.target.value === '' ? null : Number(e.target.value))
      }
      className={`cds-input mono${invalid ? ' cds-input--invalid' : ''}`}
    />
  );
}

export function Textarea({
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  value?: string;
  onChange?: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className="cds-input"
    />
  );
}

// ===== Search ==================================================

export function SearchBox({
  value,
  onChange,
  placeholder = '검색',
  lg,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  lg?: boolean;
}) {
  return (
    <div className={`cds-search${lg ? ' cds-search--lg' : ''}`}>
      <I.Search className="cds-search__icon" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

// ===== Toggle ==================================================

export function Toggle({
  on,
  checked,
  onChange,
  disabled,
  label,
  helper,
  sub,
}: {
  on?: boolean;
  checked?: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label: ReactNode;
  helper?: string;
  sub?: string;
}) {
  const value = on != null ? on : !!checked;
  const help = helper || sub;
  return (
    <div className="col gap-8">
      <button
        type="button"
        className={`toggle${value ? ' is-on' : ''}`}
        onClick={() => !disabled && onChange(!value)}
        disabled={disabled}
      >
        <span className="toggle__track">
          <span className="toggle__thumb" />
        </span>
        <span>{label}</span>
      </button>
      {help ? <span className="cds-field__helper">{help}</span> : null}
    </div>
  );
}

// ===== Checkbox ================================================

export function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked?: boolean;
  onChange?: (v: boolean) => void;
  label: ReactNode;
}) {
  return (
    <label className="cds-checkbox">
      <input
        type="checkbox"
        checked={!!checked}
        onChange={(e) => onChange?.(e.target.checked)}
      />
      <span className="cds-checkbox__box" />
      <span>{label}</span>
    </label>
  );
}

// ===== RadioTileGroup =========================================

export function RadioTileGroup<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{
    value: T;
    title: ReactNode;
    desc?: ReactNode;
    helper?: ReactNode;
  }>;
}) {
  return (
    <div className="radio-tile-group">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`radio-tile${value === opt.value ? ' is-selected' : ''}`}
          onClick={() => onChange(opt.value)}
        >
          <h4>{opt.title}</h4>
          {opt.desc ? <p>{opt.desc}</p> : null}
          {opt.helper ? <p className="helper">{opt.helper}</p> : null}
        </button>
      ))}
    </div>
  );
}

// ===== Slider ==================================================

export function SliderInput({
  value,
  onChange,
  min = 0,
  max = 100,
  step = 1,
  fmt,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  fmt?: (v: number) => string;
}) {
  return (
    <div className="slider">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="slider__value">{fmt ? fmt(value) : value}</span>
    </div>
  );
}

// ===== Dropdown ================================================

export function Dropdown<T extends string>({
  value,
  onChange,
  options,
  placeholder = '선택',
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string }>;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  const sel = options.find((o) => o.value === value);
  return (
    <div className="cds-dropdown" ref={ref}>
      <button
        type="button"
        className="cds-dropdown__trigger"
        onClick={() => setOpen(!open)}
      >
        <span>{sel ? sel.label : placeholder}</span>
        <I.CaretDown className="cds-icon" />
      </button>
      {open ? (
        <div className="cds-dropdown__menu">
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              className="cds-dropdown__item"
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ===== OverflowMenu ===========================================

export interface OverflowItem {
  label?: string;
  divider?: boolean;
  danger?: boolean;
  onClick?: () => void;
}

export function OverflowMenu({ items }: { items: OverflowItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);
  return (
    <div className="overflow-menu" ref={ref}>
      <button
        type="button"
        className="overflow-menu__trigger"
        onClick={() => setOpen(!open)}
      >
        <I.More className="cds-icon" />
      </button>
      {open ? (
        <div className="overflow-menu__menu">
          {items.map((it, i) =>
            it.divider ? (
              <div key={i} className="overflow-menu__divider" />
            ) : (
              <button
                key={i}
                type="button"
                className={`overflow-menu__item${it.danger ? ' overflow-menu__item--danger' : ''}`}
                onClick={() => {
                  setOpen(false);
                  it.onClick?.();
                }}
              >
                {it.label}
              </button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}

// ===== Modal ===================================================

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl';

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  danger,
  children,
  primary,
  secondary,
  size,
  primaryDisabled,
  primaryLoading,
  footer,
}: {
  open: boolean;
  onClose?: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  danger?: boolean;
  children?: ReactNode;
  primary?: { label: string; onClick: () => void };
  secondary?: { label: string; onClick: () => void };
  size?: ModalSize;
  primaryDisabled?: boolean;
  primaryLoading?: boolean;
  footer?: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="cds-modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose?.()}
    >
      <div
        className={`cds-modal${size ? ` cds-modal--${size}` : ''}`}
      >
        <div className="cds-modal__hd">
          {subtitle ? <div className="cds-modal__subtitle">{subtitle}</div> : null}
          <div
            className={`cds-modal__title${danger ? ' cds-modal__title--danger' : ''}`}
          >
            {title}
          </div>
          {onClose ? (
            <button
              type="button"
              className="cds-modal__close"
              onClick={onClose}
            >
              <I.Close className="cds-icon" />
            </button>
          ) : null}
        </div>
        <div className="cds-modal__body">{children}</div>
        {footer
          ? footer
          : primary || secondary
            ? (
              <div className="cds-modal__ft">
                {secondary ? (
                  <Btn kind="secondary" onClick={secondary.onClick}>
                    {secondary.label}
                  </Btn>
                ) : null}
                {primary ? (
                  <Btn
                    kind={danger ? 'danger' : 'primary'}
                    onClick={primary.onClick}
                    disabled={primaryDisabled || primaryLoading}
                  >
                    {primaryLoading ? '처리 중...' : primary.label}
                  </Btn>
                ) : null}
              </div>
            )
            : null}
      </div>
    </div>
  );
}

// ===== InlineNotif ============================================

export type NotifKind = 'info' | 'success' | 'warning' | 'error';

export function InlineNotif({
  kind = 'info',
  title,
  subtitle,
  caption,
  lowContrast,
  action,
  onClose,
}: {
  kind?: NotifKind;
  title?: ReactNode;
  subtitle?: ReactNode;
  caption?: ReactNode;
  lowContrast?: boolean;
  action?: { label: string; onClick: () => void };
  onClose?: () => void;
}) {
  const Icon =
    kind === 'success'
      ? I.Success
      : kind === 'warning'
        ? I.Warning
        : kind === 'error'
          ? I.Error
          : I.Info;
  return (
    <div
      className={`cds-inline-notif cds-inline-notif--${kind}${lowContrast ? ' cds-inline-notif--low' : ''}`}
    >
      <Icon
        className={`cds-inline-notif__icon cds-inline-notif__icon--${kind}`}
      />
      <div className="cds-inline-notif__body">
        {title ? <div className="cds-inline-notif__title">{title}</div> : null}
        {subtitle ? (
          <div className="cds-inline-notif__subtitle">{subtitle}</div>
        ) : null}
        {caption ? (
          <div className="cds-inline-notif__caption">{caption}</div>
        ) : null}
      </div>
      {action ? (
        <Btn kind="ghost" size="sm" onClick={action.onClick}>
          {action.label}
        </Btn>
      ) : null}
      {onClose ? (
        <button
          type="button"
          className="cds-modal__close"
          style={{ position: 'static', marginLeft: 8 }}
          onClick={onClose}
        >
          <I.Close className="cds-icon" />
        </button>
      ) : null}
    </div>
  );
}

// ===== Toast ===================================================

export interface Toast {
  id: string;
  kind?: NotifKind;
  title: string;
  subtitle?: string;
  caption?: string;
  ttl?: number;
}

export function ToastContainer({
  toasts,
  onClose,
}: {
  toasts: Toast[];
  onClose: (id: string) => void;
}) {
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`cds-toast cds-toast--${t.kind || 'info'}`}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>
            {t.title}
          </div>
          {t.subtitle ? (
            <div style={{ fontSize: 13, color: 'var(--cds-text-secondary)' }}>
              {t.subtitle}
            </div>
          ) : null}
          {t.caption ? (
            <div
              style={{
                fontSize: 12,
                color: 'var(--cds-text-helper)',
                marginTop: 4,
                fontFamily: 'var(--font-mono)',
              }}
            >
              {t.caption}
            </div>
          ) : null}
          <button
            type="button"
            className="cds-toast__close"
            onClick={() => onClose(t.id)}
          >
            <I.Close className="cds-icon" />
          </button>
        </div>
      ))}
    </div>
  );
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const addToast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).slice(2);
    const ttl = t.ttl ?? 4500;
    setToasts((prev) => [...prev, { id, ...t }]);
    if (ttl > 0) {
      window.setTimeout(
        () => setToasts((prev) => prev.filter((x) => x.id !== id)),
        ttl,
      );
    }
  }, []);
  const closeToast = useCallback(
    (id: string) => setToasts((prev) => prev.filter((x) => x.id !== id)),
    [],
  );
  return { toasts, addToast, closeToast };
}

// ===== Tabs ====================================================

export interface TabSpec<T extends string> {
  value: T;
  label: ReactNode;
  count?: number;
}

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
}: {
  value: T;
  onChange: (v: T) => void;
  tabs: TabSpec<T>[];
}) {
  return (
    <div className="cds-tabs">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          className={`cds-tabs__tab${value === t.value ? ' is-active' : ''}`}
          onClick={() => onChange(t.value)}
        >
          {t.label}
          {t.count != null ? ` (${t.count})` : null}
        </button>
      ))}
    </div>
  );
}

// ===== ProgressIndicator ======================================

export function ProgressIndicator({
  steps,
  current,
}: {
  steps: string[];
  current: number;
}) {
  return (
    <ol className="cds-prog">
      {steps.map((s, i) => (
        <li
          key={i}
          className={`cds-prog__step${i < current ? ' is-complete' : i === current ? ' is-current' : ''}`}
        >
          <span className="cds-prog__circle">
            {i < current ? <I.Check className="cds-icon" /> : i + 1}
          </span>
          <span className="cds-prog__label">{s}</span>
        </li>
      ))}
    </ol>
  );
}

// ===== ProgressBar =============================================

export function ProgressBar({
  value,
  max = 100,
  kind,
  label,
  helper,
  sm,
}: {
  value: number;
  max?: number;
  kind?: string;
  label?: ReactNode;
  helper?: ReactNode;
  sm?: boolean;
}) {
  const cls = ['progress-bar'];
  if (kind) cls.push(`progress-bar--${kind}`);
  return (
    <div className="col gap-8">
      {label ? (
        <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>
          {label}
        </div>
      ) : null}
      <div className={cls.join(' ')} style={{ height: sm ? 2 : 4 }}>
        <div
          className="progress-bar__fill"
          style={{ width: `${Math.min(100, (value / max) * 100)}%` }}
        />
      </div>
      {helper ? <div className="cds-field__helper">{helper}</div> : null}
    </div>
  );
}

// ===== Pagination ==============================================

export function Pagination({
  total,
  page,
  perPage,
  onPage,
}: {
  total: number;
  page: number;
  perPage: number;
  onPage: (p: number) => void;
}) {
  const last = Math.max(1, Math.ceil(total / perPage));
  const start = total === 0 ? 0 : (page - 1) * perPage + 1;
  const end = Math.min(total, page * perPage);
  return (
    <div className="pagination">
      <span>
        {total === 0
          ? '전체 0건'
          : start === 1 && end === total
            ? `전체 ${total}건`
            : `전체 ${total}건 중 ${start}-${end}번째 표시`}
      </span>
      <div className="pagination__btns">
        <button
          type="button"
          className="pagination__btn"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <I.ChevronLeft className="cds-icon" />
        </button>
        <span style={{ padding: '0 8px', alignSelf: 'center' }}>
          {page} / {last}
        </span>
        <button
          type="button"
          className="pagination__btn"
          disabled={page >= last}
          onClick={() => onPage(page + 1)}
        >
          <I.ChevronRight className="cds-icon" />
        </button>
      </div>
    </div>
  );
}

// ===== KPITile / MetricTile ===================================

export function KPITile({
  label,
  value,
  sub,
  color,
  progress,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  color?: 'profit' | 'loss';
  progress?: number;
}) {
  return (
    <div className="kpi-tile">
      <div className="kpi-tile__label">{label}</div>
      <div
        className={`kpi-tile__value${color === 'profit' ? ' pnl-profit' : color === 'loss' ? ' pnl-loss' : ''}`}
      >
        {value}
      </div>
      {sub ? <div className="kpi-tile__sub">{sub}</div> : null}
      {progress != null ? <ProgressBar value={progress} /> : null}
    </div>
  );
}

export const MetricTile = KPITile;

// ===== PnLCell =================================================

export function PnLCell({
  amount,
  pct,
  big,
}: {
  amount: number;
  pct: number;
  big?: boolean;
}) {
  const isProfit = amount >= 0;
  return (
    <div className={`pnl-row ${isProfit ? 'pnl-profit' : 'pnl-loss'}`}>
      <strong style={big ? { fontSize: 24 } : undefined}>
        {formatPct(pct)}
      </strong>
      <small
        className={isProfit ? 'pnl-profit' : 'pnl-loss'}
        style={{ fontFamily: 'var(--font-mono)' }}
      >
        {formatKrwSigned(amount)}원
      </small>
    </div>
  );
}

// ===== Status tags =============================================

export function SeverityTag({
  severity,
  sm,
}: {
  severity: Severity;
  sm?: boolean;
}) {
  const map: Record<Severity, { type: TagType; label: string }> = {
    CRITICAL: { type: 'red', label: 'CRITICAL' },
    HIGH: { type: 'magenta', label: 'HIGH' },
    MEDIUM: { type: 'blue', label: 'MEDIUM' },
    LOW: { type: 'cool-gray', label: 'LOW' },
  };
  const m = map[severity];
  return (
    <Tag type={m.type} size={sm ? 'sm' : undefined}>
      {m.label}
    </Tag>
  );
}

export function TrackedStatusTag({
  status,
  sm,
}: {
  status: TrackedStatus;
  sm?: boolean;
}) {
  const map: Record<TrackedStatus, { type: TagType; label: string }> = {
    TRACKING: { type: 'cool-gray', label: '추적 중' },
    BOX_SET: { type: 'blue', label: '박스 설정' },
    POSITION_OPEN: { type: 'green', label: '포지션 보유' },
    POSITION_PARTIAL: { type: 'cyan', label: '부분 청산' },
    EXITED: { type: 'cool-gray', label: '종료' },
  };
  const m = map[status];
  return (
    <Tag type={m.type} size={sm ? 'sm' : undefined}>
      {m.label}
    </Tag>
  );
}

export function PositionSourceTag({ source }: { source: PositionSource }) {
  const map: Record<PositionSource, { type: TagType; label: string }> = {
    SYSTEM_A: { type: 'blue', label: 'SYSTEM_A' },
    SYSTEM_B: { type: 'purple', label: 'SYSTEM_B' },
    MANUAL: { type: 'warning', label: 'MANUAL' },
  };
  const m = map[source];
  return <Tag type={m.type}>{m.label}</Tag>;
}

export function BoxStatusTag({ status }: { status: BoxStatus }) {
  const map: Record<BoxStatus, { type: TagType; label: string }> = {
    WAITING: { type: 'cool-gray', label: '대기' },
    TRIGGERED: { type: 'green', label: '진입 완료' },
    INVALIDATED: { type: 'red', label: '무효화' },
    CANCELLED: { type: 'cool-gray', label: '취소' },
  };
  const m = map[status];
  return <Tag type={m.type}>{m.label}</Tag>;
}

// ===== Skeleton / Tile / ExpandableTile =======================

export function Skeleton({
  height = 20,
  width = '100%',
}: {
  height?: number | string;
  width?: number | string;
}) {
  return (
    <div
      style={{
        height,
        width,
        background: 'var(--cds-skeleton-background, #393939)',
        animation: 'pulse 1.5s ease-in-out infinite',
      }}
    />
  );
}

export function Tile({
  children,
  padding = 16,
  ...rest
}: {
  children: ReactNode;
  padding?: number;
  [key: string]: unknown;
}) {
  return (
    <div className="cds-tile" style={{ padding }} {...rest}>
      {children}
    </div>
  );
}

export function ExpandableTile({
  head,
  children,
  defaultOpen = false,
}: {
  head: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`expand-tile${open ? ' is-expanded' : ''}`}>
      <button
        type="button"
        className="expand-tile__head"
        onClick={() => setOpen(!open)}
      >
        <I.ChevronRight className="expand-tile__chevron" />
        <div style={{ flex: 1 }}>{head}</div>
      </button>
      {open ? <div className="expand-tile__body">{children}</div> : null}
    </div>
  );
}
