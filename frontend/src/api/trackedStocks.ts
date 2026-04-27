// tracked_stocks + stocks.search API client (09_API_SPEC §3).

import {
  apiDelete,
  apiGet,
  apiGetList,
  apiPatch,
  apiPost,
  type ApiListResponse,
} from '@/lib/api';

// ---------------------------------------------------------------------
// Shapes mirror src/web/v71/schemas/trading.py
// ---------------------------------------------------------------------

export type TrackedStatusLit =
  | 'TRACKING'
  | 'BOX_SET'
  | 'POSITION_OPEN'
  | 'POSITION_PARTIAL'
  | 'EXITED';
export type PathTypeLit = 'PATH_A' | 'PATH_B';
export type BoxStatusLit =
  | 'WAITING'
  | 'TRIGGERED'
  | 'INVALIDATED'
  | 'CANCELLED';
export type StrategyTypeLit = 'PULLBACK' | 'BREAKOUT';
export type PositionSourceLit = 'SYSTEM_A' | 'SYSTEM_B' | 'MANUAL';
export type PositionStatusLit = 'OPEN' | 'PARTIAL_CLOSED' | 'CLOSED';

export interface TrackedStockSummary {
  active_box_count: number;
  path_a_box_count: number;
  path_b_box_count: number;
  triggered_box_count: number;
  current_position_qty: number;
  current_position_avg_price: number | null;
  total_position_pct: number;
}

export interface TrackedStockOut {
  id: string;
  stock_code: string;
  stock_name: string;
  market: string | null;
  status: TrackedStatusLit;
  user_memo: string | null;
  source: string | null;
  vi_recovered_today: boolean;
  auto_exit_reason: string | null;
  created_at: string;
  last_status_changed_at: string;
  summary: TrackedStockSummary;
}

export interface TrackedStockBoxOut {
  id: string;
  path_type: PathTypeLit;
  box_tier: number;
  upper_price: number;
  lower_price: number;
  position_size_pct: number;
  stop_loss_pct: number;
  strategy_type: StrategyTypeLit;
  status: BoxStatusLit;
  created_at: string;
}

export interface TrackedStockPositionOut {
  id: string;
  source: PositionSourceLit;
  weighted_avg_price: number;
  total_quantity: number;
  status: PositionStatusLit;
}

export interface TrackedStockDetailOut extends TrackedStockOut {
  boxes: TrackedStockBoxOut[];
  positions: TrackedStockPositionOut[];
}

export interface TrackedStockCreate {
  stock_code: string;
  user_memo?: string | null;
  source?: string | null;
}

export interface TrackedStockPatch {
  user_memo?: string | null;
  source?: string | null;
}

export interface TrackedStockListParams {
  status?: TrackedStatusLit;
  stock_code?: string;
  q?: string;
  limit?: number;
  cursor?: string;
  sort?: '-created_at' | 'created_at';
}

export interface StockSearchItem {
  stock_code: string;
  stock_name: string;
  market: string | null;
  current_price: number | null;
  is_managed: boolean;
  is_warning: boolean;
}

// ---------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------

export const trackedStocksApi = {
  list(
    params: TrackedStockListParams = {},
  ): Promise<ApiListResponse<TrackedStockOut>> {
    return apiGetList<TrackedStockOut>('/api/v71/tracked_stocks', { params });
  },
  get(id: string): Promise<TrackedStockDetailOut> {
    return apiGet<TrackedStockDetailOut>(`/api/v71/tracked_stocks/${id}`);
  },
  create(body: TrackedStockCreate): Promise<TrackedStockOut> {
    return apiPost<TrackedStockOut, TrackedStockCreate>(
      '/api/v71/tracked_stocks',
      body,
    );
  },
  patch(id: string, body: TrackedStockPatch): Promise<TrackedStockOut> {
    return apiPatch<TrackedStockOut, TrackedStockPatch>(
      `/api/v71/tracked_stocks/${id}`,
      body,
    );
  },
  remove(id: string): Promise<void> {
    return apiDelete(`/api/v71/tracked_stocks/${id}`);
  },
};

export const stocksApi = {
  search(q: string): Promise<StockSearchItem[]> {
    return apiPost<StockSearchItem[], { q: string }>(
      '/api/v71/stocks/search',
      { q },
    );
  },
};
