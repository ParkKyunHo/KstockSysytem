// SessionExpiryWatcher — headless component that watches the access
// token's ``exp`` claim and fires callbacks once the session crosses
// 5-minute and 0-second thresholds.
//
// Mounted by ``AppShell`` so the user sees a toast warning before the
// session auto-expires (PRD §3.5 + Phase 4 frontend UX requirement).
// Renders nothing — the AppShell consumes ``onWarn`` / ``onExpired``
// to trigger the global toast container.
//
// Reset semantics:
//   * When the access token rotates (e.g. user clicked the
//     SessionExtendButton, or the api.ts auto-refresh ran), the new
//     ``exp`` jumps back above the warn threshold and we reset the
//     "already warned" / "already expired" flags so the next cycle
//     can fire again.

import { useEffect, useRef } from 'react';

import { decodeJwtExp } from '@/lib/jwt';
import { tokenStore } from '@/lib/tokenStore';

interface SessionExpiryWatcherProps {
  /** seconds before exp at which to fire ``onWarn`` (default 300 = 5 min) */
  warnAtSeconds?: number;
  onWarn: () => void;
  onExpired: () => void;
}

export function SessionExpiryWatcher({
  warnAtSeconds = 300,
  onWarn,
  onExpired,
}: SessionExpiryWatcherProps) {
  // Use refs so the interval / subscribe callback always sees the
  // latest values without re-creating on every render.
  const warnedRef = useRef(false);
  const expiredRef = useRef(false);
  const onWarnRef = useRef(onWarn);
  const onExpiredRef = useRef(onExpired);

  // Keep latest callbacks without retriggering the effect.
  useEffect(() => {
    onWarnRef.current = onWarn;
    onExpiredRef.current = onExpired;
  }, [onWarn, onExpired]);

  useEffect(() => {
    const tick = () => {
      const exp = decodeJwtExp(tokenStore.getAccessToken());
      if (exp == null) {
        // No token (logged out). Reset state so the next login can
        // fire warnings again.
        warnedRef.current = false;
        expiredRef.current = false;
        return;
      }
      const now = Math.floor(Date.now() / 1000);
      const remaining = exp - now;

      // Token rotated → above the warn threshold again → reset flags.
      if (remaining > warnAtSeconds) {
        if (warnedRef.current || expiredRef.current) {
          warnedRef.current = false;
          expiredRef.current = false;
        }
        return;
      }

      if (remaining > 0 && !warnedRef.current) {
        warnedRef.current = true;
        try {
          onWarnRef.current();
        } catch {
          /* swallow callback errors so the watcher keeps running */
        }
      }
      if (remaining <= 0 && !expiredRef.current) {
        expiredRef.current = true;
        try {
          onExpiredRef.current();
        } catch {
          /* swallow */
        }
      }
    };

    // Tick once immediately + every 5s afterwards. 5s polling matches
    // backend's worst-case clock skew tolerance and is cheap.
    tick();
    const intervalId = window.setInterval(tick, 5000);
    const unsub = tokenStore.subscribe(tick);
    return () => {
      window.clearInterval(intervalId);
      unsub();
    };
  }, [warnAtSeconds]);

  return null;
}
