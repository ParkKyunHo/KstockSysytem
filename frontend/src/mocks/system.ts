import type { SystemStatusData } from '@/types';
import { MOCK_NOW, isoMinusHour } from '@/lib/time';

export const mockSystemStatus: SystemStatusData = {
  status: 'RUNNING',
  uptime_seconds: 367920,
  websocket: {
    connected: true,
    last_disconnect_at: isoMinusHour(3),
    reconnect_count_today: 1,
  },
  kiwoom_api: {
    available: true,
    rate_limit_used_per_sec: 3,
    rate_limit_max: 5,
  },
  telegram_bot: {
    active: true,
    circuit_breaker_state: 'CLOSED',
  },
  database: {
    connected: true,
    latency_ms: 8,
  },
  feature_flags: {
    'v71.box_system': true,
    'v71.exit_v71': true,
    'v71.partial_close': true,
    'v71.ts_multiplier': false,
    'v71.report_v2': true,
  },
  market: {
    is_open: true,
    session: 'REGULAR',
    next_open_at: null,
    next_close_at: '2026-04-26T06:30:00Z',
  },
  current_time: MOCK_NOW.toISOString(),
};
