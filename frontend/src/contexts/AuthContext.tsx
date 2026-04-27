// AuthContext -- global authentication state + login/logout actions.
//
// Responsibilities:
//   * Listen on tokenStore for cross-tab login/logout.
//   * Expose ``user`` (the result of ``GET /users/me``).
//   * Provide ``login``, ``verifyTotp``, ``logout`` actions to pages.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { authApi, type CurrentUser, type LoginResult } from '@/api/auth';
import { apiGet, ApiClientError } from '@/lib/api';
import { tokenStore } from '@/lib/tokenStore';

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
}

interface AuthValue extends AuthState {
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<LoginResult>;
  verifyTotp: (sessionId: string, totpCode: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | undefined>(undefined);

async function fetchMe(): Promise<CurrentUser | null> {
  try {
    return await apiGet<CurrentUser>('/api/v71/users/me');
  } catch (err) {
    if (err instanceof ApiClientError && err.status === 401) {
      return null;
    }
    throw err;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    loading: true,
    error: null,
  });

  const reload = useCallback(async () => {
    if (!tokenStore.getAccessToken()) {
      setState({ user: null, loading: false, error: null });
      return;
    }
    try {
      const user = await fetchMe();
      setState({ user, loading: false, error: null });
    } catch (err) {
      setState({
        user: null,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load user',
      });
    }
  }, []);

  useEffect(() => {
    void reload();
    // Sync across tabs (manual updates won't fire 'storage', but cross-
    // tab logout will).
    const handler = (e: StorageEvent) => {
      if (e.key === 'v71.access_token') void reload();
    };
    window.addEventListener('storage', handler);
    return () => window.removeEventListener('storage', handler);
  }, [reload]);

  const login = useCallback(
    async (username: string, password: string): Promise<LoginResult> => {
      const result = await authApi.login(username, password);
      if (result.totp_required === false) {
        tokenStore.setTokens(result.access_token, result.refresh_token);
        await reload();
      }
      return result;
    },
    [reload],
  );

  const verifyTotp = useCallback(
    async (sessionId: string, totpCode: string): Promise<void> => {
      const tokens = await authApi.totpVerify(sessionId, totpCode);
      tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
      await reload();
    },
    [reload],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await authApi.logout();
    } catch {
      // even if the server rejects, clear locally.
    }
    tokenStore.clear();
    setState({ user: null, loading: false, error: null });
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      ...state,
      isAuthenticated: state.user != null,
      login,
      verifyTotp,
      logout,
      refreshUser: reload,
    }),
    [state, login, verifyTotp, logout, reload],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error('useAuth must be used within <AuthProvider>');
  }
  return ctx;
}
