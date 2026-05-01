// SessionExtendButton -- header button that shows the access-token
// expiry countdown ("MM:SS") next to a "로그인 연장" label, and on click
// calls POST /api/v71/auth/refresh to mint a fresh access token (1-hour
// lifetime per current backend settings).
//
// Countdown source = JWT ``exp`` claim of the current access token
// (decoded client-side, signature not verified — strictly for display).
// This stays consistent with whatever lifetime the backend signs, so
// changing ``access_token_minutes`` in WebSettings is automatically
// reflected here.
//
// Color cues:
//   * normal (>5 min)         → muted text colour
//   * low (≤5 min, >0)        → warning yellow
//   * expired (≤0)            → error red, tooltip changes
//
// Visual feedback dot appears for ~2s after refresh success/failure
// (matches the prior design — green / red dot at the top-right).

import { useCallback, useEffect, useState } from 'react';

import { authApi } from '@/api/auth';
import { I } from '@/components/icons';
import { decodeJwtExp } from '@/lib/jwt';
import { tokenStore } from '@/lib/tokenStore';

type Feedback = 'idle' | 'success' | 'error';

const LOW_THRESHOLD_SEC = 300; // 5 min — switch label to warning colour

function formatRemaining(sec: number): string {
  if (sec <= 0) return '00:00';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function SessionExtendButton() {
  const [remaining, setRemaining] = useState<number | null>(null);
  const [extending, setExtending] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>('idle');

  // Tick every second + react to token-store changes (login / refresh).
  useEffect(() => {
    const update = () => {
      const exp = decodeJwtExp(tokenStore.getAccessToken());
      if (exp == null) {
        setRemaining(null);
        return;
      }
      const now = Math.floor(Date.now() / 1000);
      setRemaining(Math.max(0, exp - now));
    };
    update();
    const tickId = window.setInterval(update, 1000);
    const unsub = tokenStore.subscribe(update);
    return () => {
      window.clearInterval(tickId);
      unsub();
    };
  }, []);

  const extend = useCallback(async () => {
    if (extending) return;
    const refresh = tokenStore.getRefreshToken();
    if (!refresh) {
      setFeedback('error');
      window.setTimeout(() => setFeedback('idle'), 2000);
      return;
    }
    setExtending(true);
    setFeedback('idle');
    try {
      const res = await authApi.refresh(refresh);
      // PRD §3.5 sliding refresh: backend rotates BOTH tokens. Persist
      // both so the next /auth/refresh has the rotated refresh available
      // (otherwise we silently revert to the old refresh which is now
      // revoked → next 401 logs the user out).
      tokenStore.setTokens(res.access_token, res.refresh_token);
      setFeedback('success');
      window.setTimeout(() => setFeedback('idle'), 2000);
    } catch {
      setFeedback('error');
      window.setTimeout(() => setFeedback('idle'), 2000);
    } finally {
      setExtending(false);
    }
  }, [extending]);

  const expired = remaining != null && remaining <= 0;
  const warningLow =
    remaining != null && remaining > 0 && remaining < LOW_THRESHOLD_SEC;

  const countdownColor = expired
    ? 'var(--cds-support-error, #fa4d56)'
    : warningLow
      ? 'var(--cds-support-warning, #f1c21b)'
      : 'var(--cds-text-secondary, #c6c6c6)';

  const tooltip = (() => {
    if (feedback === 'success') return '세션 연장됨 (1시간)';
    if (feedback === 'error') return '세션 연장 실패 - 다시 로그인 필요';
    if (extending) return '세션 연장 중...';
    if (expired) return '세션 만료됨 - 클릭 시 재발급 시도';
    if (remaining != null) {
      return `남은 시간 ${formatRemaining(remaining)} - 클릭 시 1시간 연장`;
    }
    return '클릭 시 세션 1시간 연장';
  })();

  const dotColor =
    feedback === 'success'
      ? 'var(--cds-support-success, #42be65)'
      : feedback === 'error'
        ? 'var(--cds-support-error, #fa4d56)'
        : null;

  return (
    <button
      type="button"
      className="cds-header__action"
      onClick={extend}
      disabled={extending}
      title={tooltip}
      aria-label={tooltip}
    >
      <I.Renew className="cds-icon" size={16} />
      <span className="cds-header__action__label">로그인 연장</span>
      {remaining != null ? (
        <span
          className="cds-header__action__countdown"
          style={{ color: countdownColor }}
        >
          {formatRemaining(remaining)}
        </span>
      ) : null}
      {dotColor ? (
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 8,
            right: 4,
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: dotColor,
            boxShadow: '0 0 0 2px var(--cds-background, #161616)',
          }}
        />
      ) : null}
    </button>
  );
}
