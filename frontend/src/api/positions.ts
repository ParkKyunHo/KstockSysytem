// positions API client (09_API_SPEC §5).

import {
  apiGet,
  apiGetList,
  apiPost,
  type ApiListResponse,
} from '@/lib/api';
import type {
  PositionSourceLit,
  PositionStatusLit,
} from './trackedStocks';

export interface PositionOut {
  id: string;
  source: PositionSourceLit;
  stock_code: string;
  stock_name: string;
  tracked_stock_id: string | null;
  triggered_box_id: string | null;
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
  status: PositionStatusLit;

  // ★ PRD Patch #5 (V7.1.0d, 2026-04-27): live-price columns
  // WebSocket 0B (<1s) > kt00018 (5s) > ka10001 (재시작) 갱신
  current_price: number | null;
  current_price_at: string | null;
  pnl_amount: number | null;
  pnl_pct: number | null;

  closed_at: string | null;
  final_pnl: number | null;
  close_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface TradeEventInline {
  id: string;
  event_type: string;
  price: number | null;
  quantity: number | null;
  occurred_at: string;
}

export interface EffectiveStopOut {
  fixed_stop: number;
  ts_stop: number | null;
  effective: number;
  should_exit: boolean;
}

export interface PositionDetailOut extends PositionOut {
  events: TradeEventInline[];
  effective_stop: EffectiveStopOut;
}

export interface PositionSourceBreakdown {
  count: number;
  capital: number;
}

export interface PositionStockAtLimit {
  stock_code: string;
  actual_pct: number;
  limit_pct: number;
}

export interface PositionSummaryOut {
  total_positions: number;
  total_capital_invested: number;
  total_capital_pct: number;
  total_pnl_amount: number;
  total_pnl_pct: number;
  by_source: Record<PositionSourceLit, PositionSourceBreakdown>;
  by_status: Record<PositionStatusLit, number>;
  top_pnl: PositionOut[];
  bottom_pnl: PositionOut[];
  stocks_at_limit: PositionStockAtLimit[];
}

export interface ReconcileTaskOut {
  task_id: string;
  started_at: string;
  estimated_seconds: number;
}

export interface PositionListParams {
  source?: PositionSourceLit;
  status?: PositionStatusLit;
  stock_code?: string;
  limit?: number;
  cursor?: string;
  sort?: '-created_at' | 'created_at';
}

export const positionsApi = {
  list(
    params: PositionListParams = {},
  ): Promise<ApiListResponse<PositionOut>> {
    return apiGetList<PositionOut>('/api/v71/positions', { params });
  },
  get(id: string): Promise<PositionDetailOut> {
    return apiGet<PositionDetailOut>(`/api/v71/positions/${id}`);
  },
  summary(): Promise<PositionSummaryOut> {
    return apiGet<PositionSummaryOut>('/api/v71/positions/summary');
  },
  reconcile(): Promise<ReconcileTaskOut> {
    return apiPost<ReconcileTaskOut>('/api/v71/positions/reconcile');
  },
};
