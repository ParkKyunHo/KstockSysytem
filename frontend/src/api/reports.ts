// reports API client (09_API_SPEC §8). PRD Patch #5: soft delete + restore.

import {
  apiDelete,
  apiGet,
  apiGetList,
  apiPatch,
  apiPost,
  type ApiListResponse,
} from '@/lib/api';

export type ReportStatusLit =
  | 'PENDING'
  | 'GENERATING'
  | 'COMPLETED'
  | 'FAILED';

export interface ReportOut {
  id: string;
  stock_code: string;
  stock_name: string;
  status: ReportStatusLit;
  model_version: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  narrative_part: string | null;
  facts_part: string | null;
  data_sources: Record<string, unknown> | null;
  pdf_path: string | null;
  excel_path: string | null;
  user_notes: string | null;
  error_message: string | null;
  progress: number | null;
  elapsed_seconds: number | null;
  generation_started_at: string | null;
  generation_completed_at: string | null;
  generation_duration_seconds: number | null;
  requested_at: string;
  created_at: string;

  // ★ PRD Patch #5: soft-delete
  is_hidden: boolean;
  hidden_at: string | null;
  hidden_reason: string | null;
}

export interface ReportRequestBody {
  stock_code: string;
  tracked_stock_id?: string | null;
}

export interface ReportRequestResponse {
  report_id: string;
  status: ReportStatusLit;
  estimated_seconds: number;
  stock_code: string;
  stock_name: string;
  requested_at: string;
}

export interface ReportPatch {
  user_notes?: string | null;
}

export interface ReportListParams {
  stock_code?: string;
  status?: ReportStatusLit;
  from_date?: string;
  to_date?: string;
  include_hidden?: boolean;  // ★ PRD Patch #5
  limit?: number;
  cursor?: string;
}

export const reportsApi = {
  list(params: ReportListParams = {}): Promise<ApiListResponse<ReportOut>> {
    return apiGetList<ReportOut>('/api/v71/reports', { params });
  },
  get(id: string): Promise<ReportOut> {
    return apiGet<ReportOut>(`/api/v71/reports/${id}`);
  },
  request(body: ReportRequestBody): Promise<ReportRequestResponse> {
    return apiPost<ReportRequestResponse, ReportRequestBody>(
      '/api/v71/reports/request',
      body,
    );
  },
  patch(id: string, body: ReportPatch): Promise<ReportOut> {
    return apiPatch<ReportOut, ReportPatch>(`/api/v71/reports/${id}`, body);
  },
  // ★ PRD Patch #5: soft delete (영구 보존, 목록에서만 숨김)
  remove(id: string): Promise<void> {
    return apiDelete(`/api/v71/reports/${id}`);
  },
  // ★ PRD Patch #5: 숨긴 리포트 복구
  restore(id: string): Promise<ReportOut> {
    return apiPost<ReportOut>(`/api/v71/reports/${id}/restore`);
  },
};
