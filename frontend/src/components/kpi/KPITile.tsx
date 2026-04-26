import { ProgressBar, Tile } from '@carbon/react';

interface KPITileProps {
  title: string;
  value: string;
  subtitle?: string;
  /**
   * 'profit' or 'loss' applies the Korean PnL color to the big value.
   */
  tone?: 'profit' | 'loss' | 'neutral';
  /**
   * Optional 0-100 progress under the value (e.g. capital usage).
   */
  progress?: number;
}

export function KPITile({
  title,
  value,
  subtitle,
  tone = 'neutral',
  progress,
}: KPITileProps) {
  const valueClass =
    tone === 'profit'
      ? 'pnl-profit kpi-value'
      : tone === 'loss'
        ? 'pnl-loss kpi-value'
        : 'kpi-value';

  return (
    <Tile style={{ minHeight: '8rem' }}>
      <p
        className="cds--type-helper-text-01"
        style={{ marginBottom: '0.5rem' }}
      >
        {title}
      </p>
      <div className={valueClass}>{value}</div>
      {subtitle ? (
        <p
          className="cds--type-helper-text-01"
          style={{ marginTop: '0.25rem' }}
        >
          {subtitle}
        </p>
      ) : null}
      {progress !== undefined ? (
        <div style={{ marginTop: '0.75rem' }}>
          <ProgressBar
            label={title}
            hideLabel
            value={progress}
            max={100}
          />
        </div>
      ) : null}
    </Tile>
  );
}
