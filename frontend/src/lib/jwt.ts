// JWT helpers — frontend reads ``exp`` claim for the session-expiry
// countdown. Signature is NOT verified here (the backend does that on
// every API call); we just need the unix seconds for display.

export function decodeJwtExp(token: string | null): number | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const payload = JSON.parse(atob(padded)) as { exp?: unknown };
    return typeof payload.exp === 'number' ? payload.exp : null;
  } catch {
    return null;
  }
}

export function remainingSeconds(token: string | null): number | null {
  const exp = decodeJwtExp(token);
  if (exp == null) return null;
  return Math.max(0, exp - Math.floor(Date.now() / 1000));
}
