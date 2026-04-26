import { formatKrwSigned, formatPct } from '@/lib/formatters';

interface PnLCellProps {
  /** Absolute KRW amount, signed. Null = no data dash. */
  amount: number | null | undefined;
  /** Percentage (e.g. 1.77 means +1.77%). Null = dash. */
  pct: number | null | undefined;
  /** Variant: stacked (default) shows amount + pct on two lines. */
  layout?: 'stacked' | 'inline';
}

/**
 * Korean-convention PnL cell.
 *
 * Positive (profit) → red (`pnl-profit`).
 * Negative (loss)   → blue (`pnl-loss`).
 * Zero / null       → text-secondary.
 *
 * Tabular numerals via `IBM Plex Mono`.
 */
export function PnLCell({ amount, pct, layout = 'stacked' }: PnLCellProps) {
  const klass =
    amount == null
      ? 'pnl-neutral'
      : amount > 0
        ? 'pnl-profit'
        : amount < 0
          ? 'pnl-loss'
          : 'pnl-neutral';

  if (layout === 'inline') {
    return (
      <span className={klass}>
        {formatPct(pct)} ({formatKrwSigned(amount)})
      </span>
    );
  }

  return (
    <div className={klass} style={{ lineHeight: 1.25 }}>
      <strong>{formatPct(pct)}</strong>
      <div
        className="cds--type-helper-text-01"
        style={{
          fontFamily: 'inherit',
          color: 'inherit',
          opacity: 0.85,
        }}
      >
        {formatKrwSigned(amount)}원
      </div>
    </div>
  );
}
