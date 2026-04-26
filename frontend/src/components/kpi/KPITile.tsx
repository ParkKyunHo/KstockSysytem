import { ProgressBar } from '@carbon/react';

interface KPITileProps {
  label: string;
  value: string;
  subtitle?: string;
  /**
   * 'profit' or 'loss' applies the Korean PnL color to the big value.
   */
  tone?: 'profit' | 'loss' | 'neutral';
  /**
   * Optional 0-100 progress bar under the value (e.g. 자본 사용 %).
   */
  progress?: number;
  /**
   * Smaller value font (used when value text is long, e.g. KRW amount).
   */
  compact?: boolean;
}

/**
 * KPI tile -- mirrors the prototype's `.kpi-tile` BEM block.
 *
 * Uses a plain div with grid-cell styling so 4 tiles share a 1px
 * subtle divider via the parent `.kpi-grid` background trick.
 */
export function KPITile({
  label,
  value,
  subtitle,
  tone = 'neutral',
  progress,
  compact = false,
}: KPITileProps) {
  const valueClass = [
    'kpi-tile__value',
    compact ? 'kpi-tile__value-sm' : '',
    tone === 'profit' ? 'pnl-profit' : tone === 'loss' ? 'pnl-loss' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className="kpi-tile">
      <p className="kpi-tile__label">{label}</p>
      <div className={valueClass}>{value}</div>
      {subtitle ? <p className="kpi-tile__sub">{subtitle}</p> : null}
      {progress !== undefined ? (
        <div className="kpi-tile__progress">
          <ProgressBar
            label={label}
            hideLabel
            value={progress}
            max={100}
          />
        </div>
      ) : null}
    </div>
  );
}
