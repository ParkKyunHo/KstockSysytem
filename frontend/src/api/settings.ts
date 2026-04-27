// settings API client (09_API_SPEC §10).

import { apiGet, apiPatch } from '@/lib/api';

export interface UserSettingsOut {
  total_capital: number | null;
  notify_critical: boolean;
  notify_high: boolean;
  notify_medium: boolean;
  notify_low: boolean;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  theme: string;
  language: string;
  preferences: Record<string, unknown> | null;
  telegram_chat_id: string | null;
  totp_enabled: boolean;
  updated_at: string;
}

export interface UserSettingsPatch {
  total_capital?: number;
  notify_critical?: boolean;
  notify_high?: boolean;
  notify_medium?: boolean;
  notify_low?: boolean;
  quiet_hours_enabled?: boolean;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  theme?: string;
  language?: string;
  preferences?: Record<string, unknown>;
}

export interface FeatureFlagsOut {
  v71: Record<string, boolean>;
}

export interface FeatureFlagsPatch {
  flags: Record<string, boolean>;
}

export const settingsApi = {
  get(): Promise<UserSettingsOut> {
    return apiGet<UserSettingsOut>('/api/v71/settings');
  },
  patch(body: UserSettingsPatch): Promise<UserSettingsOut> {
    return apiPatch<UserSettingsOut, UserSettingsPatch>(
      '/api/v71/settings',
      body,
    );
  },
  getFeatureFlags(): Promise<FeatureFlagsOut> {
    return apiGet<FeatureFlagsOut>('/api/v71/settings/feature_flags');
  },
  patchFeatureFlags(body: FeatureFlagsPatch): Promise<FeatureFlagsOut> {
    return apiPatch<FeatureFlagsOut, FeatureFlagsPatch>(
      '/api/v71/settings/feature_flags',
      body,
    );
  },
};
