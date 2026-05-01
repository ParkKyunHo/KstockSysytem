// Auth API client (09_API_SPEC §1).

import { apiGet, apiPost } from '@/lib/api';

export interface LoginPendingTotp {
  totp_required: true;
  session_id: string;
  message: string;
}

export interface TokenPair {
  totp_required: false;
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export type LoginResult = LoginPendingTotp | TokenPair;

export interface TotpVerifyResult {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface RefreshResult {
  // PRD §3.5 sliding refresh: backend now returns BOTH new access AND
  // new refresh on every /auth/refresh call. Old shape kept as optional
  // for backwards compat with cached responses.
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface CurrentUser {
  id: string;
  username: string;
  role: string;
  totp_enabled: boolean;
  telegram_chat_id?: string | null;
}

export interface TotpSetupResult {
  totp_secret: string;
  qr_code_url: string;
  backup_codes: string[];
}

export const authApi = {
  login(username: string, password: string): Promise<LoginResult> {
    return apiPost<LoginResult, { username: string; password: string }>(
      '/api/v71/auth/login',
      { username, password },
    );
  },
  totpVerify(session_id: string, totp_code: string): Promise<TotpVerifyResult> {
    return apiPost<
      TotpVerifyResult,
      { session_id: string; totp_code: string }
    >('/api/v71/auth/totp/verify', { session_id, totp_code });
  },
  refresh(refresh_token: string): Promise<RefreshResult> {
    return apiPost<RefreshResult, { refresh_token: string }>(
      '/api/v71/auth/refresh',
      { refresh_token },
    );
  },
  logout(): Promise<void> {
    return apiPost<void>('/api/v71/auth/logout');
  },
  me(): Promise<CurrentUser> {
    return apiGet<CurrentUser>('/api/v71/users/me');
  },
  totpSetup(): Promise<TotpSetupResult> {
    return apiPost<TotpSetupResult>('/api/v71/auth/totp/setup');
  },
  totpConfirm(totp_code: string): Promise<{ totp_enabled: boolean }> {
    return apiPost<{ totp_enabled: boolean }, { totp_code: string }>(
      '/api/v71/auth/totp/confirm',
      { totp_code },
    );
  },
};
