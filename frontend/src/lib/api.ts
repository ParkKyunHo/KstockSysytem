// V7.1 API client (09_API_SPEC §1, §2).
//
// * Bearer JWT Authorization header.
// * Single-flight refresh on 401 (PRD §1.1: Refresh 24h).
// * Response envelope is unwrapped to ``T`` (callers receive ``data``,
//   not the full envelope).
// * Errors are rethrown as ``ApiClientError`` carrying the PRD-shaped
//   ``error_code`` / ``message`` / ``details``.

import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios';

import { tokenStore } from './tokenStore';

// ---------------------------------------------------------------------
// Envelopes (mirror src/web/v71/schemas/common.py)
// ---------------------------------------------------------------------

export interface ApiMeta {
  request_id: string;
  timestamp: string;
}

export interface ApiListMeta extends ApiMeta {
  total?: number;
  limit: number;
  next_cursor: string | null;
  prev_cursor?: string | null;
}

export interface ApiResponse<T> {
  data: T;
  meta: ApiMeta;
}

export interface ApiListResponse<T> {
  data: T[];
  meta: ApiListMeta;
}

export interface ApiErrorEnvelope {
  error_code: string;
  message: string;
  details?: Record<string, unknown> | null;
  meta?: ApiMeta;
}

export class ApiClientError extends Error {
  status: number;
  errorCode: string;
  details?: Record<string, unknown> | null;

  constructor(
    status: number,
    errorCode: string,
    message: string,
    details?: Record<string, unknown> | null,
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.errorCode = errorCode;
    this.details = details;
  }
}

// ---------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------

const baseURL = import.meta.env.VITE_API_BASE_URL ?? '';

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// Attach the access token before every request.
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const access = tokenStore.getAccessToken();
  if (access) {
    config.headers.set('Authorization', `Bearer ${access}`);
  }
  return config;
});

// ---------------------------------------------------------------------
// Refresh-on-401 (single flight)
// ---------------------------------------------------------------------

let refreshPromise: Promise<string | null> | null = null;

// PRD §3.5 sliding refresh: backend rotates BOTH access + refresh on
// every /auth/refresh call. We must persist the rotated refresh too,
// otherwise the next 401 will use the now-revoked old refresh and
// silently log the user out.
async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokenStore.getRefreshToken();
  if (!refresh) return null;
  try {
    const resp = await axios.post<
      ApiResponse<{
        access_token: string;
        refresh_token: string;
        expires_in: number;
      }>
    >(
      `${baseURL}/api/v71/auth/refresh`,
      { refresh_token: refresh },
      { headers: { 'Content-Type': 'application/json' } },
    );
    const { access_token, refresh_token } = resp.data.data;
    tokenStore.setTokens(access_token, refresh_token);
    return access_token;
  } catch (_err) {
    tokenStore.clear();
    return null;
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorEnvelope>) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retried?: boolean;
    };
    if (
      error.response?.status === 401 &&
      original &&
      !original._retried &&
      !original.url?.includes('/auth/login') &&
      !original.url?.includes('/auth/totp/verify') &&
      !original.url?.includes('/auth/refresh')
    ) {
      original._retried = true;
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }
      const next = await refreshPromise;
      if (next) {
        original.headers?.set('Authorization', `Bearer ${next}`);
        return apiClient(original);
      }
    }
    return Promise.reject(toApiError(error));
  },
);

function toApiError(error: AxiosError<ApiErrorEnvelope>): ApiClientError {
  const status = error.response?.status ?? 0;
  const env = error.response?.data;
  if (env && typeof env.error_code === 'string') {
    return new ApiClientError(status, env.error_code, env.message, env.details);
  }
  return new ApiClientError(
    status,
    'NETWORK_ERROR',
    error.message || 'Network error',
  );
}

// ---------------------------------------------------------------------
// Typed helpers (unwrap ``data``)
// ---------------------------------------------------------------------

export async function apiGet<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<T> {
  const resp = await apiClient.get<ApiResponse<T>>(url, config);
  return resp.data.data;
}

export async function apiGetList<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<ApiListResponse<T>> {
  const resp: AxiosResponse<ApiListResponse<T>> = await apiClient.get(url, config);
  return resp.data;
}

export async function apiPost<T, B = unknown>(
  url: string,
  body?: B,
  config?: AxiosRequestConfig,
): Promise<T> {
  const resp = await apiClient.post<ApiResponse<T>>(url, body, config);
  return resp.data.data;
}

export async function apiPostRaw<T, B = unknown>(
  url: string,
  body?: B,
  config?: AxiosRequestConfig,
): Promise<AxiosResponse<ApiResponse<T>>> {
  return apiClient.post<ApiResponse<T>>(url, body, config);
}

export async function apiPatch<T, B = unknown>(
  url: string,
  body?: B,
  config?: AxiosRequestConfig,
): Promise<T> {
  const resp = await apiClient.patch<ApiResponse<T>>(url, body, config);
  return resp.data.data;
}

export async function apiDelete(
  url: string,
  config?: AxiosRequestConfig,
): Promise<void> {
  await apiClient.delete(url, config);
}
