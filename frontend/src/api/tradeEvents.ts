// trade_events API client (09_API_SPEC §6).

import { apiGet, apiGetList, type ApiListResponse } from '@/lib/api';

export interface TradeEventOut {
  id: string;
  position_id: string | null;
  tracked_stock_id: string | null;
  box_id: string | null;
  stock_code: string;
  stock_name: string | null;
  event_type: string;
  price: number | null;
  quantity: number | null;
  order_id: string | null;
  client_order_id: string | null;
  attempt: number | null;
  pnl_amount: number | null;
  pnl_pct: number | null;
  avg_price_before: number | null;
  avg_price_after: number | null;
  payload: Record<string, unknown> | null;
  reason: string | null;
  error_message: string | null;
  occurred_at: string;
}

export interface TradeEventTodayBuy {
  stock_code: string;
  quantity: number | null;
  price: number | null;
  occurred_at: string;
}

export interface TradeEventTodaySell {
  stock_code: string;
  quantity: number | null;
  price: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  reason: string | null;
  occurred_at: string;
}

export interface TradeEventTodayOut {
  date: string;
  total_pnl: number;
  total_pnl_pct: number | null;
  buys: TradeEventTodayBuy[];
  sells: TradeEventTodaySell[];
  auto_exits: TradeEventTodaySell[];
  manual_trades: TradeEventTodaySell[];
}

export interface TradeEventListParams {
  position_id?: string;
  tracked_stock_id?: string;
  event_type?: string;
  stock_code?: string;
  from_date?: string;
  to_date?: string;
  limit?: number;
  cursor?: string;
}

export const tradeEventsApi = {
  list(
    params: TradeEventListParams = {},
  ): Promise<ApiListResponse<TradeEventOut>> {
    return apiGetList<TradeEventOut>('/api/v71/trade_events', { params });
  },
  today(): Promise<TradeEventTodayOut> {
    return apiGet<TradeEventTodayOut>('/api/v71/trade_events/today');
  },
};
