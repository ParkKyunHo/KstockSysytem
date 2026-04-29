// system API client (09_API_SPEC §9).

import {
  apiGet,
  apiGetList,
  apiPost,
  type ApiListResponse,
} from '@/lib/api';

export type SystemStatusLit = 'RUNNING' | 'SAFE_MODE' | 'RECOVERING';

export interface SystemStatusOut {
  status: SystemStatusLit;
  uptime_seconds: number;
  websocket: {
    connected: boolean;
    last_disconnect_at: string | null;
    reconnect_count_today: number;
  };
  kiwoom_api: {
    available: boolean;
    rate_limit_used_per_sec: number;
    rate_limit_max: number;
  };
  telegram_bot: {
    active: boolean;
    circuit_breaker_state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
  };
  database: {
    connected: boolean;
    latency_ms: number;
  };
  feature_flags: Record<string, boolean>;
  market: {
    is_open: boolean;
    session: 'PRE' | 'REGULAR' | 'POST' | null;
    next_open_at: string | null;
    next_close_at: string | null;
  };
  current_time: string;
  // 박스 wizard 비중 표시용 실제 키움 잔고 (kt00018 5분 TTL cache).
  // ``total_capital`` 이 ``null`` 이면 buy_executor 비활성 또는 키움
  // fetch 실패 -- frontend 는 fallback (1억) + "(추정)" 표시.
  account?: {
    total_capital: number | null;
  };
}

export interface SystemHealthOut {
  status: 'healthy' | 'degraded';
  checks: Record<string, 'ok' | 'fail'>;
  details?: Record<string, string>;
}

export interface SafeModeRequest {
  reason: string;
}

export interface SafeModeResponse {
  safe_mode: boolean;
  entered_at: string | null;
  resumed_at: string | null;
}

export interface SystemRestartOut {
  id: string;
  restart_at: string;
  recovery_completed_at: string | null;
  recovery_duration_seconds: number | null;
  reason: string | null;
  reason_detail: string | null;
  reconciliation_summary: Record<string, unknown> | null;
  cancelled_orders_count: number;
}

export interface AsyncTaskOut {
  task_id: string;
  type: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  progress: number;
  started_at: string | null;
  completed_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export const systemApi = {
  status(): Promise<SystemStatusOut> {
    return apiGet<SystemStatusOut>('/api/v71/system/status');
  },
  health(): Promise<SystemHealthOut> {
    return apiGet<SystemHealthOut>('/api/v71/system/health');
  },
  enterSafeMode(reason: string): Promise<SafeModeResponse> {
    return apiPost<SafeModeResponse, SafeModeRequest>(
      '/api/v71/system/safe_mode',
      { reason },
    );
  },
  resume(): Promise<SafeModeResponse> {
    return apiPost<SafeModeResponse>('/api/v71/system/resume');
  },
  restarts(
    params: { limit?: number; cursor?: string; from_date?: string } = {},
  ): Promise<ApiListResponse<SystemRestartOut>> {
    return apiGetList<SystemRestartOut>('/api/v71/system/restarts', { params });
  },
  task(id: string): Promise<AsyncTaskOut> {
    return apiGet<AsyncTaskOut>(`/api/v71/system/tasks/${id}`);
  },
};
