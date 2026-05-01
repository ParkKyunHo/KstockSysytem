// Token persistence -- backed by localStorage. PRD §1.1 leaves the
// storage location to the client; localStorage matches the existing
// frontend conventions and survives page reloads.

const ACCESS_KEY = 'v71.access_token';
const REFRESH_KEY = 'v71.refresh_token';

export interface TokenSnapshot {
  access: string | null;
  refresh: string | null;
}

class TokenStore {
  private listeners = new Set<(snapshot: TokenSnapshot) => void>();

  getAccessToken(): string | null {
    try {
      return window.localStorage.getItem(ACCESS_KEY);
    } catch {
      return null;
    }
  }

  getRefreshToken(): string | null {
    try {
      return window.localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  }

  setAccessToken(token: string): void {
    try {
      window.localStorage.setItem(ACCESS_KEY, token);
    } catch {
      // ignore storage failures -- session degraded but operational
    }
    this.emit();
  }

  setTokens(access: string, refresh: string): void {
    try {
      window.localStorage.setItem(ACCESS_KEY, access);
      window.localStorage.setItem(REFRESH_KEY, refresh);
    } catch {
      // ignore
    }
    this.emit();
  }

  clear(): void {
    try {
      window.localStorage.removeItem(ACCESS_KEY);
      window.localStorage.removeItem(REFRESH_KEY);
    } catch {
      // ignore
    }
    this.emit();
  }

  snapshot(): TokenSnapshot {
    return {
      access: this.getAccessToken(),
      refresh: this.getRefreshToken(),
    };
  }

  subscribe(listener: (snapshot: TokenSnapshot) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private emit(): void {
    const snap = this.snapshot();
    this.listeners.forEach((l) => l(snap));
  }
}

export const tokenStore = new TokenStore();
