// Korean locale + tabular-num formatters.
//
// Mirrors `frontend-prototype/src/mocks/index.js` `window.fmt.*` 1:1.

const krwFormatter = new Intl.NumberFormat('ko-KR');

export function formatKrw(n: number | null | undefined): string {
  if (n == null) return '-';
  return krwFormatter.format(Math.round(n));
}

export function formatKrwSigned(n: number | null | undefined): string {
  if (n == null) return '-';
  const sign = n >= 0 ? '+' : '';
  return sign + krwFormatter.format(Math.round(n));
}

export function formatPct(
  n: number | null | undefined,
  digits = 2,
): string {
  if (n == null) return '-';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}%`;
}

export function formatPctRaw(
  n: number | null | undefined,
  digits = 2,
): string {
  if (n == null) return '-';
  return `${n.toFixed(digits)}%`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function formatTimeSeconds(iso: string | null | undefined): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('ko-KR', {
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** "1h 7m" -- time remaining until ISO timestamp. */
export function formatUntil(iso: string | null | undefined): string {
  if (!iso) return '-';
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return '0m';
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return (h ? `${h}h ` : '') + `${m}m`;
}

/** "12d 4h" -- uptime from seconds. */
export function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86_400);
  const h = Math.floor((seconds % 86_400) / 3_600);
  return `${d}d ${h}h`;
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '-';
  const diffSec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffSec < 60) return `${diffSec}초 전`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}시간 전`;
  return `${Math.floor(diffSec / 86400)}일 전`;
}
