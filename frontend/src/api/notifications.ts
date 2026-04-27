// notifications API client (09_API_SPEC §7).

import {
  apiGet,
  apiGetList,
  apiPost,
  type ApiListResponse,
} from '@/lib/api';

export type NotificationSeverityLit = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export type NotificationChannelLit = 'TELEGRAM' | 'WEB' | 'BOTH';
export type NotificationStatusLit =
  | 'PENDING'
  | 'SENT'
  | 'FAILED'
  | 'SUPPRESSED'
  | 'EXPIRED';

export interface NotificationOut {
  id: string;
  severity: NotificationSeverityLit;
  channel: NotificationChannelLit;
  event_type: string;
  stock_code: string | null;
  title: string | null;
  message: string;
  payload: Record<string, unknown> | null;
  status: NotificationStatusLit;
  sent_at: string | null;
  created_at: string;
}

export interface NotificationUnreadOut {
  unread_count: number;
  items: NotificationOut[];
}

export interface NotificationListParams {
  severity?: NotificationSeverityLit;
  status?: NotificationStatusLit;
  event_type?: string;
  stock_code?: string;
  from_date?: string;
  to_date?: string;
  limit?: number;
  cursor?: string;
}

export interface NotificationTestRequest {
  severity?: NotificationSeverityLit;
  channel?: NotificationChannelLit;
}

export interface NotificationTestResponse {
  notification_id: string;
  status: NotificationStatusLit;
  sent_at: string | null;
}

export const notificationsApi = {
  list(
    params: NotificationListParams = {},
  ): Promise<ApiListResponse<NotificationOut>> {
    return apiGetList<NotificationOut>('/api/v71/notifications', { params });
  },
  unread(): Promise<NotificationUnreadOut> {
    return apiGet<NotificationUnreadOut>('/api/v71/notifications/unread');
  },
  markRead(id: string): Promise<void> {
    return apiPost<void>(`/api/v71/notifications/${id}/mark_read`);
  },
  test(body: NotificationTestRequest = {}): Promise<NotificationTestResponse> {
    return apiPost<NotificationTestResponse, NotificationTestRequest>(
      '/api/v71/notifications/test',
      body,
    );
  },
};
