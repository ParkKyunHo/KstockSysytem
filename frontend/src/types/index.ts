// V7.1 shared TypeScript types.
//
// Mirrors `docs/v71/03_DATA_MODEL.md` and `docs/v71/09_API_SPEC.md`
// with PRD Patch #3 applied:
//   - tracked_stocks.path_type REMOVED (path is a box attribute now).
//   - support_boxes.path_type required (NOT NULL).
//   - tracked_stocks.summary gains path_a_box_count / path_b_box_count.

// ---------------------------------------------------------------------
// Enums (canonical values mirror server ENUMs)
// ---------------------------------------------------------------------

export type PathType = 'PATH_A' | 'PATH_B';
export type StrategyType = 'PULLBACK' | 'BREAKOUT';

export type TrackedStatus =
  | 'TRACKING'
  | 'BOX_SET'
  | 'POSITION_OPEN'
  | 'POSITION_PARTIAL'
  | 'EXITED';

export type BoxStatus =
  | 'WAITING'
  | 'TRIGGERED'
  | 'INVALIDATED'
  | 'CANCELLED';

export type PositionSource = 'SYSTEM_A' | 'SYSTEM_B' | 'MANUAL';
export type PositionStatus = 'OPEN' | 'PARTIAL_CLOSED' | 'CLOSED';

export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type NotificationStatus =
  | 'PENDING'
  | 'SENT'
  | 'FAILED'
  | 'SUPPRESSED'
  | 'EXPIRED';
export type NotificationChannel = 'TELEGRAM' | 'WEB' | 'BOTH';

export type ReportStatus = 'PENDING' | 'GENERATING' | 'COMPLETED' | 'FAILED';
export type SystemStatus = 'RUNNING' | 'SAFE_MODE' | 'RECOVERING';

export type ThemeName = 'g100' | 'g90' | 'white' | 'g10';

// ---------------------------------------------------------------------
// Resources
// ---------------------------------------------------------------------

export interface TrackedStockSummary {
  active_box_count: number;
  triggered_box_count: number;
  // ★ PRD Patch #3: per-path counts.
  path_a_box_count: number;
  path_b_box_count: number;
  current_position_qty: number;
  current_position_avg_price: number | null;
}

export interface TrackedStock {
  id: string;
  stock_code: string;
  stock_name: string;
  market: 'KOSPI' | 'KOSDAQ';
  // ⚠️ PRD Patch #3: path_type is NOT here -- it lives on Box.
  status: TrackedStatus;
  user_memo: string | null;
  source: string | null;
  vi_recovered_today: boolean;
  auto_exit_reason: string | null;
  created_at: string;
  last_status_changed_at: string;
  summary: TrackedStockSummary;
}

export interface Box {
  id: string;
  tracked_stock_id: string;
  stock_code: string;
  stock_name: string;
  // ★ PRD Patch #3: required -- declared at box-creation time.
  path_type: PathType;
  box_tier: number;
  upper_price: number;
  lower_price: number;
  position_size_pct: number;
  stop_loss_pct: number;
  strategy_type: StrategyType;
  status: BoxStatus;
  memo: string | null;
  created_at: string;
  triggered_at: string | null;
  invalidated_at: string | null;
  invalidation_reason: string | null;
  next_reminder_at: string | null;
  entry_proximity_pct: number | null;
}

export interface Position {
  id: string;
  source: PositionSource;
  stock_code: string;
  stock_name: string;
  tracked_stock_id: string | null;
  triggered_box_id: string | null;
  // path_type is inherited from the triggered box.
  path_type: PathType | 'MANUAL';
  initial_avg_price: number;
  weighted_avg_price: number;
  total_quantity: number;
  fixed_stop_price: number;
  profit_5_executed: boolean;
  profit_10_executed: boolean;
  ts_activated: boolean;
  ts_base_price: number | null;
  ts_stop_price: number | null;
  ts_active_multiplier: number | null;
  actual_capital_invested: number;
  status: PositionStatus;
  current_price: number;
  pnl_amount: number;
  pnl_pct: number;
  closed_at: string | null;
  final_pnl: number | null;
  close_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface TradeEvent {
  id: string;
  event_type:
    | 'BUY_EXECUTED'
    | 'PYRAMID_BUY'
    | 'MANUAL_PYRAMID_BUY'
    | 'PROFIT_TAKE_5'
    | 'PROFIT_TAKE_10'
    | 'STOP_LOSS'
    | 'TS_EXIT'
    | 'TS_ACTIVATED'
    | 'BUY_REJECTED'
    | 'POSITION_CLOSED'
    | 'MANUAL_SELL';
  position_id: string;
  stock_code: string;
  quantity: number;
  price: number;
  occurred_at: string;
  events_reset?: boolean;
}

export interface NotificationRecord {
  id: string;
  severity: Severity;
  channel: NotificationChannel;
  event_type: string;
  stock_code: string | null;
  title: string;
  message: string;
  payload: Record<string, unknown> | null;
  status: NotificationStatus;
  priority: 1 | 2 | 3 | 4;
  rate_limit_key: string | null;
  retry_count: number;
  sent_at: string | null;
  failed_at: string | null;
  failure_reason: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface Report {
  id: string;
  stock_code: string;
  stock_name: string;
  status: ReportStatus;
  model_version: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  narrative_part: string | null;
  facts_part: string | null;
  pdf_path: string | null;
  excel_path: string | null;
  user_notes: string | null;
  progress?: number;
  generation_started_at: string | null;
  generation_completed_at: string | null;
  generation_duration_seconds: number | null;
  error_message?: string;
  created_at: string;
}

export interface SystemStatusData {
  status: SystemStatus;
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
  account?: {
    total_capital: number | null;
  };
}

// ---------------------------------------------------------------------
// API response wrappers (09_API_SPEC §2)
// ---------------------------------------------------------------------

export interface ApiMeta {
  request_id: string;
  timestamp: string;
}

export interface ApiResponse<T> {
  data: T;
  meta: ApiMeta;
}

export interface ApiListMeta extends ApiMeta {
  total?: number;
  limit: number;
  next_cursor: string | null;
  prev_cursor?: string | null;
}

export interface ApiListResponse<T> {
  data: T[];
  meta: ApiListMeta;
}

export interface ApiError {
  error_code: string;
  message: string;
  details?: Record<string, unknown>;
  meta: ApiMeta;
}
