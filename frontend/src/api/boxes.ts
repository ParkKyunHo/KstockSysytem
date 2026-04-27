// boxes API client (09_API_SPEC §4).

import {
  apiClient,
  apiDelete,
  apiGet,
  apiGetList,
  apiPostRaw,
  type ApiListResponse,
} from '@/lib/api';
import type {
  BoxStatusLit,
  PathTypeLit,
  StrategyTypeLit,
} from './trackedStocks';

export interface BoxOut {
  id: string;
  tracked_stock_id: string;
  stock_code: string;
  stock_name: string;
  path_type: PathTypeLit;
  box_tier: number;
  upper_price: number;
  lower_price: number;
  position_size_pct: number;
  stop_loss_pct: number;
  strategy_type: StrategyTypeLit;
  status: BoxStatusLit;
  memo: string | null;
  created_at: string;
  modified_at: string;
  triggered_at?: string | null;
  invalidated_at?: string | null;
  invalidation_reason?: string | null;
  last_reminder_at?: string | null;
  entry_proximity_pct?: number | null;
}

export interface BoxCreate {
  tracked_stock_id: string;
  path_type: PathTypeLit;
  upper_price: number;
  lower_price: number;
  position_size_pct: number;
  stop_loss_pct?: number;
  strategy_type: StrategyTypeLit;
  memo?: string | null;
}

export interface BoxPatch {
  upper_price?: number;
  lower_price?: number;
  position_size_pct?: number;
  stop_loss_pct?: number;
  memo?: string | null;
}

export interface BoxListParams {
  tracked_stock_id?: string;
  path_type?: PathTypeLit;
  status?: BoxStatusLit;
  strategy_type?: StrategyTypeLit;
  limit?: number;
  cursor?: string;
  sort?: '-created_at' | 'created_at';
}

export interface BoxPatchResult {
  box: BoxOut;
  warnings: string[];
}

export const boxesApi = {
  list(params: BoxListParams = {}): Promise<ApiListResponse<BoxOut>> {
    return apiGetList<BoxOut>('/api/v71/boxes', { params });
  },
  get(id: string): Promise<BoxOut> {
    return apiGet<BoxOut>(`/api/v71/boxes/${id}`);
  },
  async create(body: BoxCreate): Promise<BoxOut> {
    const resp = await apiPostRaw<BoxOut, BoxCreate>('/api/v71/boxes', body);
    return resp.data.data;
  },
  async patch(id: string, body: BoxPatch): Promise<BoxPatchResult> {
    const resp = await apiClient.patch<{ data: BoxOut }>(
      `/api/v71/boxes/${id}`,
      body,
    );
    const headerVal = (resp.headers['x-warning'] ?? '') as string;
    const warnings = headerVal
      .split(',')
      .map((s: string) => s.trim())
      .filter(Boolean);
    return { box: resp.data.data, warnings };
  },
  remove(id: string): Promise<void> {
    return apiDelete(`/api/v71/boxes/${id}`);
  },
};
