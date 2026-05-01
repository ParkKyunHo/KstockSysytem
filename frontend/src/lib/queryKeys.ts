// Stable TanStack Query keys (avoids cache-key drift between hooks).

export const qk = {
  me: ['me'] as const,
  trackedStocks: (params?: object) =>
    ['tracked_stocks', params ?? null] as const,
  trackedStock: (id: string) => ['tracked_stock', id] as const,
  boxes: (params?: object) => ['boxes', params ?? null] as const,
  box: (id: string) => ['box', id] as const,
  positions: (params?: object) => ['positions', params ?? null] as const,
  position: (id: string) => ['position', id] as const,
  positionsSummary: ['positions', 'summary'] as const,
  tradeEvents: (params?: object) => ['trade_events', params ?? null] as const,
  tradeEventsToday: ['trade_events', 'today'] as const,
  notifications: (params?: object) =>
    ['notifications', params ?? null] as const,
  notificationsUnread: ['notifications', 'unread'] as const,
  reports: (params?: object) => ['reports', params ?? null] as const,
  report: (id: string) => ['report', id] as const,
  systemStatus: ['system', 'status'] as const,
  systemHealth: ['system', 'health'] as const,
  systemRestarts: (params?: object) =>
    ['system', 'restarts', params ?? null] as const,
  systemTask: (id: string) => ['system', 'tasks', id] as const,
  settings: ['settings'] as const,
  featureFlags: ['settings', 'feature_flags'] as const,
  stockSearch: (q: string) => ['stocks', 'search', q] as const,
};
