// V7.1 TanStack Query hooks across all domains.
//
// Each hook wraps a typed API call from ``src/api/*`` with stable query
// keys (``qk``) so cache invalidation can target precise scopes.

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
  type UseQueryOptions,
} from '@tanstack/react-query';

import { boxesApi, type BoxCreate, type BoxListParams, type BoxOut, type BoxPatch, type BoxPatchResult } from '@/api/boxes';
import {
  notificationsApi,
  type NotificationListParams,
  type NotificationOut,
  type NotificationTestRequest,
  type NotificationTestResponse,
  type NotificationUnreadOut,
} from '@/api/notifications';
import {
  positionsApi,
  type PositionDetailOut,
  type PositionListParams,
  type PositionOut,
  type PositionSummaryOut,
  type ReconcileTaskOut,
} from '@/api/positions';
import {
  reportsApi,
  type ReportListParams,
  type ReportOut,
  type ReportPatch,
  type ReportRequestBody,
  type ReportRequestResponse,
} from '@/api/reports';
import {
  settingsApi,
  type FeatureFlagsOut,
  type FeatureFlagsPatch,
  type UserSettingsOut,
  type UserSettingsPatch,
} from '@/api/settings';
import {
  systemApi,
  type AsyncTaskOut,
  type SafeModeResponse,
  type SystemHealthOut,
  type SystemRestartOut,
  type SystemStatusOut,
} from '@/api/system';
import {
  stocksApi,
  trackedStocksApi,
  type StockSearchItem,
  type TrackedStockCreate,
  type TrackedStockDetailOut,
  type TrackedStockListParams,
  type TrackedStockOut,
  type TrackedStockPatch,
} from '@/api/trackedStocks';
import {
  tradeEventsApi,
  type TradeEventListParams,
  type TradeEventOut,
  type TradeEventTodayOut,
} from '@/api/tradeEvents';
import type { ApiListResponse } from '@/lib/api';
import { qk } from '@/lib/queryKeys';

// ---------------------------------------------------------------------
// tracked_stocks
// ---------------------------------------------------------------------

export function useTrackedStocks(
  params: TrackedStockListParams = {},
  options?: Partial<UseQueryOptions<ApiListResponse<TrackedStockOut>>>,
) {
  return useQuery({
    queryKey: qk.trackedStocks(params),
    queryFn: () => trackedStocksApi.list(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useTrackedStock(
  id: string | null | undefined,
  options?: Partial<UseQueryOptions<TrackedStockDetailOut>>,
) {
  return useQuery({
    queryKey: qk.trackedStock(id ?? ''),
    queryFn: () => trackedStocksApi.get(id as string),
    enabled: !!id,
    ...options,
  });
}

export function useCreateTrackedStock(
  options?: UseMutationOptions<TrackedStockOut, unknown, TrackedStockCreate>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TrackedStockCreate) => trackedStocksApi.create(body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: ['tracked_stocks'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

export function usePatchTrackedStock(
  id: string,
  options?: UseMutationOptions<TrackedStockOut, unknown, TrackedStockPatch>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TrackedStockPatch) => trackedStocksApi.patch(id, body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: qk.trackedStock(id) });
      void qc.invalidateQueries({ queryKey: ['tracked_stocks'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

export function useDeleteTrackedStock(
  options?: UseMutationOptions<void, unknown, string>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => trackedStocksApi.remove(id),
    onSuccess: (...args) => {
      void qc.invalidateQueries({ queryKey: ['tracked_stocks'] });
      const deletedId = args[1] as string;
      void qc.invalidateQueries({ queryKey: qk.trackedStock(deletedId) });
      (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args);
    },
    ...options,
  });
}

export function useStockSearch(
  q: string,
  options?: Partial<UseQueryOptions<StockSearchItem[]>>,
) {
  return useQuery({
    queryKey: qk.stockSearch(q),
    queryFn: () => stocksApi.search(q),
    enabled: q.length > 0,
    staleTime: 60_000,
    ...options,
  });
}

// ---------------------------------------------------------------------
// boxes
// ---------------------------------------------------------------------

export function useBoxes(
  params: BoxListParams = {},
  options?: Partial<UseQueryOptions<ApiListResponse<BoxOut>>>,
) {
  return useQuery({
    queryKey: qk.boxes(params),
    queryFn: () => boxesApi.list(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useBox(
  id: string | null | undefined,
  options?: Partial<UseQueryOptions<BoxOut>>,
) {
  return useQuery({
    queryKey: qk.box(id ?? ''),
    queryFn: () => boxesApi.get(id as string),
    enabled: !!id,
    ...options,
  });
}

export function useCreateBox(
  options?: UseMutationOptions<BoxOut, unknown, BoxCreate>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BoxCreate) => boxesApi.create(body),
    onSuccess: (...args) => {
      void qc.invalidateQueries({ queryKey: ['boxes'] });
      const vars = args[1] as BoxCreate;
      void qc.invalidateQueries({
        queryKey: qk.trackedStock(vars.tracked_stock_id),
      });
      void qc.invalidateQueries({ queryKey: ['tracked_stocks'] });
      (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args);
    },
    ...options,
  });
}

export function usePatchBox(
  id: string,
  options?: UseMutationOptions<BoxPatchResult, unknown, BoxPatch>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BoxPatch) => boxesApi.patch(id, body),
    onSuccess: (...args) => {
      void qc.invalidateQueries({ queryKey: qk.box(id) });
      void qc.invalidateQueries({ queryKey: ['boxes'] });
      const data = args[0] as BoxPatchResult;
      void qc.invalidateQueries({
        queryKey: qk.trackedStock(data.box.tracked_stock_id),
      });
      (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args);
    },
    ...options,
  });
}

export function useDeleteBox(
  options?: UseMutationOptions<void, unknown, string>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => boxesApi.remove(id),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: ['boxes'] });
      void qc.invalidateQueries({ queryKey: ['tracked_stocks'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

// ---------------------------------------------------------------------
// positions
// ---------------------------------------------------------------------

export function usePositions(
  params: PositionListParams = {},
  options?: Partial<UseQueryOptions<ApiListResponse<PositionOut>>>,
) {
  return useQuery({
    queryKey: qk.positions(params),
    queryFn: () => positionsApi.list(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function usePosition(
  id: string | null | undefined,
  options?: Partial<UseQueryOptions<PositionDetailOut>>,
) {
  return useQuery({
    queryKey: qk.position(id ?? ''),
    queryFn: () => positionsApi.get(id as string),
    enabled: !!id,
    ...options,
  });
}

export function usePositionsSummary(
  options?: Partial<UseQueryOptions<PositionSummaryOut>>,
) {
  return useQuery({
    queryKey: qk.positionsSummary,
    queryFn: () => positionsApi.summary(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useReconcilePositions(
  options?: UseMutationOptions<ReconcileTaskOut, unknown, void>,
) {
  return useMutation({
    mutationFn: () => positionsApi.reconcile(),
    ...options,
  });
}

// ---------------------------------------------------------------------
// trade_events
// ---------------------------------------------------------------------

export function useTradeEvents(
  params: TradeEventListParams = {},
  options?: Partial<UseQueryOptions<ApiListResponse<TradeEventOut>>>,
) {
  return useQuery({
    queryKey: qk.tradeEvents(params),
    queryFn: () => tradeEventsApi.list(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useTradeEventsToday(
  options?: Partial<UseQueryOptions<TradeEventTodayOut>>,
) {
  return useQuery({
    queryKey: qk.tradeEventsToday,
    queryFn: () => tradeEventsApi.today(),
    refetchInterval: 60_000,
    ...options,
  });
}

// ---------------------------------------------------------------------
// notifications
// ---------------------------------------------------------------------

export function useNotifications(
  params: NotificationListParams = {},
  options?: Partial<UseQueryOptions<ApiListResponse<NotificationOut>>>,
) {
  return useQuery({
    queryKey: qk.notifications(params),
    queryFn: () => notificationsApi.list(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useUnreadNotifications(
  options?: Partial<UseQueryOptions<NotificationUnreadOut>>,
) {
  return useQuery({
    queryKey: qk.notificationsUnread,
    queryFn: () => notificationsApi.unread(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useMarkNotificationRead(
  options?: UseMutationOptions<void, unknown, string>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: ['notifications'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

export function useTestNotification(
  options?: UseMutationOptions<
    NotificationTestResponse,
    unknown,
    NotificationTestRequest
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NotificationTestRequest) => notificationsApi.test(body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: ['notifications'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

// ---------------------------------------------------------------------
// reports
// ---------------------------------------------------------------------

export function useReports(
  params: ReportListParams = {},
  options?: Partial<UseQueryOptions<ApiListResponse<ReportOut>>>,
) {
  return useQuery({
    queryKey: qk.reports(params),
    queryFn: () => reportsApi.list(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useReport(
  id: string | null | undefined,
  options?: Partial<UseQueryOptions<ReportOut>>,
) {
  return useQuery({
    queryKey: qk.report(id ?? ''),
    queryFn: () => reportsApi.get(id as string),
    enabled: !!id,
    ...options,
  });
}

export function useRequestReport(
  options?: UseMutationOptions<
    ReportRequestResponse,
    unknown,
    ReportRequestBody
  >,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportRequestBody) => reportsApi.request(body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: ['reports'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

export function usePatchReport(
  id: string,
  options?: UseMutationOptions<ReportOut, unknown, ReportPatch>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportPatch) => reportsApi.patch(id, body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: qk.report(id) });
      void qc.invalidateQueries({ queryKey: ['reports'] }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

// ★ PRD Patch #5: soft delete (is_hidden=true)
export function useDeleteReport(
  options?: UseMutationOptions<void, unknown, string>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => reportsApi.remove(id),
    onSuccess: (...args) => {
      void qc.invalidateQueries({ queryKey: ['reports'] });
      const id = args[1] as string;
      void qc.invalidateQueries({ queryKey: qk.report(id) });
      (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args);
    },
    ...options,
  });
}

// ★ PRD Patch #5: 숨긴 리포트 복구 (is_hidden=false)
export function useRestoreReport(
  options?: UseMutationOptions<ReportOut, unknown, string>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => reportsApi.restore(id),
    onSuccess: (...args) => {
      void qc.invalidateQueries({ queryKey: ['reports'] });
      const id = args[1] as string;
      void qc.invalidateQueries({ queryKey: qk.report(id) });
      (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args);
    },
    ...options,
  });
}

// ---------------------------------------------------------------------
// settings + feature flags
// ---------------------------------------------------------------------

export function useSettings(options?: Partial<UseQueryOptions<UserSettingsOut>>) {
  return useQuery({
    queryKey: qk.settings,
    queryFn: () => settingsApi.get(),
    ...options,
  });
}

export function usePatchSettings(
  options?: UseMutationOptions<UserSettingsOut, unknown, UserSettingsPatch>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: UserSettingsPatch) => settingsApi.patch(body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: qk.settings }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

export function useFeatureFlags(
  options?: Partial<UseQueryOptions<FeatureFlagsOut>>,
) {
  return useQuery({
    queryKey: qk.featureFlags,
    queryFn: () => settingsApi.getFeatureFlags(),
    ...options,
  });
}

export function usePatchFeatureFlags(
  options?: UseMutationOptions<FeatureFlagsOut, unknown, FeatureFlagsPatch>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: FeatureFlagsPatch) => settingsApi.patchFeatureFlags(body),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: qk.featureFlags });
      void qc.invalidateQueries({ queryKey: qk.systemStatus }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

// ---------------------------------------------------------------------
// system
// ---------------------------------------------------------------------

export function useSystemStatus(
  options?: Partial<UseQueryOptions<SystemStatusOut>>,
) {
  return useQuery({
    queryKey: qk.systemStatus,
    queryFn: () => systemApi.status(),
    refetchInterval: 15_000,
    ...options,
  });
}

export function useSystemHealth(
  options?: Partial<UseQueryOptions<SystemHealthOut>>,
) {
  return useQuery({
    queryKey: qk.systemHealth,
    queryFn: () => systemApi.health(),
    refetchInterval: 30_000,
    ...options,
  });
}

export function useSystemRestarts(
  params: { limit?: number; cursor?: string; from_date?: string } = {},
  options?: Partial<UseQueryOptions<ApiListResponse<SystemRestartOut>>>,
) {
  return useQuery({
    queryKey: qk.systemRestarts(params),
    queryFn: () => systemApi.restarts(params),
    placeholderData: keepPreviousData,
    ...options,
  });
}

export function useSystemTask(
  id: string | null | undefined,
  options?: Partial<UseQueryOptions<AsyncTaskOut>>,
) {
  return useQuery({
    queryKey: qk.systemTask(id ?? ''),
    queryFn: () => systemApi.task(id as string),
    enabled: !!id,
    refetchInterval: 2_000,
    ...options,
  });
}

export function useEnterSafeMode(
  options?: UseMutationOptions<SafeModeResponse, unknown, string>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) => systemApi.enterSafeMode(reason),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: qk.systemStatus }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}

export function useResumeFromSafeMode(
  options?: UseMutationOptions<SafeModeResponse, unknown, void>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => systemApi.resume(),
    onSuccess: (...args) => { void qc.invalidateQueries({ queryKey: qk.systemStatus }); (options?.onSuccess as ((...a: unknown[]) => void) | undefined)?.(...args); },
    ...options,
  });
}
