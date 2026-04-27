// V7.1 Settings -- wired to /api/v71/settings (PRD §10.1, §10.2) and
// /api/v71/settings/feature_flags (PRD §10.4).
//
// PRD coverage:
//   - 일반:    total_capital + theme + language + preferences.reserve_pct
//   - 알림:    notify_critical/high/medium/low + quiet_hours_*
//   - 보안:    totp_enabled (read-only here -- use dedicated /security/totp/*),
//             preferences.session_minutes
//
// 증권사 / 매매 탭은 PRD §10에 정의되지 않은 mock UI -- "PRD 미정의" 표시.

import { useEffect, useMemo, useState } from 'react';

import type { UserSettingsOut } from '@/api/settings';
import { I } from '@/components/icons';
import {
  Btn,
  Dropdown,
  Field,
  InlineNotif,
  Input,
  NumInput,
  SliderInput,
  Tabs,
  ToastContainer,
  Toggle,
  useToasts,
} from '@/components/ui';
import {
  useFeatureFlags,
  usePatchFeatureFlags,
  usePatchSettings,
  useSettings,
} from '@/hooks/useApi';
import { ApiClientError } from '@/lib/api';

type SettingsTab =
  | 'general'
  | 'broker'
  | 'trading'
  | 'notifications'
  | 'security';

interface GeneralDraft {
  total_capital: number;
  reserve_pct: number;
  theme: string;
  language: string;
}

interface NotifDraft {
  notify_critical: boolean;
  notify_high: boolean;
  notify_medium: boolean;
  notify_low: boolean;
  quiet_hours_enabled: boolean;
  quiet_hours_start: string;
  quiet_hours_end: string;
}

interface SecurityDraft {
  totp_enabled: boolean;
  session_minutes: number;
}

interface SettingsDraft {
  general: GeneralDraft;
  notifications: NotifDraft;
  security: SecurityDraft;
  flags: Record<string, boolean>;
}

const SEVERITY_LABEL: Record<keyof Pick<NotifDraft,
  'notify_critical' | 'notify_high' | 'notify_medium' | 'notify_low'
>, string> = {
  notify_critical: 'CRITICAL — 긴급 (즉시 텔레그램)',
  notify_high: 'HIGH — 높음 (텔레그램+웹)',
  notify_medium: 'MEDIUM — 보통 (웹)',
  notify_low: 'LOW — 낮음 (웹)',
};

function toDraft(
  settings: UserSettingsOut | undefined,
  flags: Record<string, boolean>,
): SettingsDraft {
  const prefs = (settings?.preferences ?? {}) as Record<string, unknown>;
  return {
    general: {
      total_capital: settings?.total_capital ?? 100_000_000,
      reserve_pct: typeof prefs.reserve_pct === 'number' ? prefs.reserve_pct : 30,
      theme: settings?.theme ?? 'g100',
      language: settings?.language ?? 'ko',
    },
    notifications: {
      notify_critical: settings?.notify_critical ?? true,
      notify_high: settings?.notify_high ?? true,
      notify_medium: settings?.notify_medium ?? true,
      notify_low: settings?.notify_low ?? false,
      quiet_hours_enabled: settings?.quiet_hours_enabled ?? false,
      quiet_hours_start: settings?.quiet_hours_start ?? '22:00',
      quiet_hours_end: settings?.quiet_hours_end ?? '07:00',
    },
    security: {
      totp_enabled: settings?.totp_enabled ?? false,
      session_minutes:
        typeof prefs.session_minutes === 'number' ? prefs.session_minutes : 60,
    },
    flags: { ...flags },
  };
}

export function Settings() {
  const { toasts, addToast, closeToast } = useToasts();

  const [tab, setTab] = useState<SettingsTab>('general');
  const { data: settings } = useSettings();
  const { data: flagsResp } = useFeatureFlags();

  const baseline = useMemo(
    () => toDraft(settings, flagsResp?.v71 ?? {}),
    [settings, flagsResp],
  );

  const [draft, setDraft] = useState<SettingsDraft>(baseline);

  // Sync the draft when the API resolves.
  useEffect(() => {
    setDraft(baseline);
  }, [baseline]);

  const patchSettings = usePatchSettings({
    onError: (err) =>
      addToast({
        kind: 'error',
        title: '설정 저장 실패',
        subtitle: err instanceof ApiClientError ? err.message : undefined,
      }),
  });
  const patchFlags = usePatchFeatureFlags({
    onError: (err) =>
      addToast({
        kind: 'error',
        title: '플래그 저장 실패',
        subtitle: err instanceof ApiClientError ? err.message : undefined,
      }),
  });

  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);
  const saving = patchSettings.isPending || patchFlags.isPending;

  const reset = () => setDraft(baseline);

  const save = async () => {
    const tasks: Array<Promise<unknown>> = [];

    // user_settings PATCH (only if anything changed there).
    const settingsChanged =
      JSON.stringify(draft.general) !== JSON.stringify(baseline.general) ||
      JSON.stringify(draft.notifications) !==
        JSON.stringify(baseline.notifications) ||
      draft.security.session_minutes !== baseline.security.session_minutes;

    if (settingsChanged) {
      tasks.push(
        patchSettings.mutateAsync({
          total_capital: draft.general.total_capital,
          theme: draft.general.theme,
          language: draft.general.language,
          notify_critical: draft.notifications.notify_critical,
          notify_high: draft.notifications.notify_high,
          notify_medium: draft.notifications.notify_medium,
          notify_low: draft.notifications.notify_low,
          quiet_hours_enabled: draft.notifications.quiet_hours_enabled,
          quiet_hours_start: draft.notifications.quiet_hours_start,
          quiet_hours_end: draft.notifications.quiet_hours_end,
          preferences: {
            ...((settings?.preferences as Record<string, unknown>) ?? {}),
            reserve_pct: draft.general.reserve_pct,
            session_minutes: draft.security.session_minutes,
          },
        }),
      );
    }

    // feature_flags PATCH (server merges).
    const flagsChanged =
      JSON.stringify(draft.flags) !== JSON.stringify(baseline.flags);
    if (flagsChanged) {
      tasks.push(patchFlags.mutateAsync({ flags: draft.flags }));
    }

    if (tasks.length === 0) return;

    try {
      await Promise.all(tasks);
      addToast({ kind: 'success', title: '설정 저장됨' });
    } catch {
      // individual onError handlers above will surface the failure.
    }
  };

  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">설정</h1>
          <div className="page-hd__subtitle">
            시스템 전반 설정. 변경 시 저장 버튼 활성화.
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="secondary"
            size="sm"
            onClick={reset}
            disabled={!dirty || saving}
          >
            되돌리기
          </Btn>
          <Btn
            kind="primary"
            size="sm"
            icon={I.Save}
            onClick={save}
            disabled={!dirty || saving}
          >
            {saving ? '저장 중…' : '저장'}
          </Btn>
        </div>
      </div>

      <Tabs<SettingsTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'general', label: '일반' },
          { value: 'broker', label: '증권사' },
          { value: 'trading', label: '매매' },
          { value: 'notifications', label: '알림' },
          { value: 'security', label: '보안' },
        ]}
      />

      <div
        className="cds-tile"
        style={{ marginTop: 16, padding: 24 }}
      >
        {tab === 'general' ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>계좌 / 자본</h3>
            <Field label="총 운용 자본 (원)">
              <NumInput
                value={draft.general.total_capital}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    general: { ...draft.general, total_capital: v ?? 0 },
                  })
                }
                step={1_000_000}
              />
            </Field>
            <Field label="예약 비중 (%) — 추가 진입 여력 (preferences)">
              <SliderInput
                value={draft.general.reserve_pct}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    general: { ...draft.general, reserve_pct: v },
                  })
                }
                min={0}
                max={50}
                step={1}
                fmt={(v) => `${v}%`}
              />
            </Field>
            <Field label="언어">
              <Dropdown<string>
                value={draft.general.language}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    general: { ...draft.general, language: v },
                  })
                }
                options={[
                  { value: 'ko', label: '한국어' },
                  { value: 'en', label: 'English' },
                ]}
              />
            </Field>
            <Field label="테마">
              <Dropdown<string>
                value={draft.general.theme}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    general: { ...draft.general, theme: v },
                  })
                }
                options={[
                  { value: 'g100', label: 'g100 (다크)' },
                  { value: 'g90', label: 'g90 (딥다크)' },
                  { value: 'g10', label: 'g10 (라이트)' },
                  { value: 'white', label: 'white (라이트)' },
                ]}
              />
            </Field>
          </div>
        ) : null}

        {tab === 'broker' ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>증권사 연동 (read-only)</h3>
            <InlineNotif
              kind="info"
              lowContrast
              title="이 설정은 .env 파일에서 관리됩니다"
              subtitle="PRD Patch #5: 키움 API 키 (KIWOOM_APP_KEY/SECRET), 계좌번호, 환경(REAL/MOCK)은 환경 변수로만 관리. UI는 read-only 상태 표시만 (백엔드 GET /settings/broker 연결 후 활성)."
            />
            {/* TODO: Phase D — useQuery(`settingsApi.broker()`)로 read-only 정보 표시
                응답 필드 (PRD Patch #5):
                  - kiwoom_account_no_masked (예: 1234-56**-**)
                  - kiwoom_account_type (REAL | MOCK)
                  - app_key_configured: bool, app_secret_configured: bool
                  - token_expires_at: ISO 8601 */}
            <p className="text-helper">
              백엔드 endpoint 미구현 — Phase D에서 GET /api/v71/settings/broker 호출로 채움.
            </p>
          </div>
        ) : null}

        {tab === 'trading' ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>매매 설정 (read-only)</h3>
            <InlineNotif
              kind="info"
              lowContrast
              title="이 설정은 .env 파일에서 관리됩니다"
              subtitle="PRD Patch #5: auto_trading_enabled, safe_mode, 거래 룰 상수 (max_position_pct 등)는 환경 변수 또는 02_TRADING_RULES.md 상수로 잠금. UI는 read-only 상태 표시만 (안전 모드 진입은 POST /system/safe_mode 사용)."
            />
            <h4 style={{ margin: '8px 0 0' }}>Feature Flags (런타임 토글)</h4>
            <p className="text-helper" style={{ margin: 0 }}>
              feature_flags는 PRD §10.4에 따라 OWNER/ADMIN만 변경 가능. 거래 룰 상수와는 별도.
            </p>
            {Object.keys(draft.flags).length === 0 ? (
              <p className="text-helper">활성 플래그가 없습니다.</p>
            ) : (
              Object.entries(draft.flags).map(([key, val]) => (
                <Toggle
                  key={key}
                  label={key}
                  checked={val}
                  onChange={(v) =>
                    setDraft({
                      ...draft,
                      flags: { ...draft.flags, [key]: v },
                    })
                  }
                />
              ))
            )}
          </div>
        ) : null}

        {tab === 'notifications' ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>심각도별 알림 채널</h3>
            {/* PRD §11.3: notify_critical은 disabled (강제 ON, 안전장치) */}
            <Toggle
              label={SEVERITY_LABEL.notify_critical}
              checked={true}
              disabled
              helper="강제 활성 (안전장치) -- 비활성화 시 백엔드 422 거부"
              onChange={() => {}}
            />
            {(['notify_high', 'notify_medium', 'notify_low'] as const).map(
              (k) => (
                <Toggle
                  key={k}
                  label={SEVERITY_LABEL[k]}
                  checked={draft.notifications[k]}
                  onChange={(v) =>
                    setDraft({
                      ...draft,
                      notifications: { ...draft.notifications, [k]: v },
                    })
                  }
                />
              ),
            )}
            <h3 style={{ margin: '8px 0 0' }}>방해 금지 시간</h3>
            <Toggle
              label="방해 금지 시간 활성"
              checked={draft.notifications.quiet_hours_enabled}
              onChange={(v) =>
                setDraft({
                  ...draft,
                  notifications: {
                    ...draft.notifications,
                    quiet_hours_enabled: v,
                  },
                })
              }
            />
            <Field label="시작 (HH:MM)">
              <Input
                value={draft.notifications.quiet_hours_start}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    notifications: {
                      ...draft.notifications,
                      quiet_hours_start: v,
                    },
                  })
                }
                placeholder="22:00"
              />
            </Field>
            <Field label="종료 (HH:MM)">
              <Input
                value={draft.notifications.quiet_hours_end}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    notifications: {
                      ...draft.notifications,
                      quiet_hours_end: v,
                    },
                  })
                }
                placeholder="07:00"
              />
            </Field>
          </div>
        ) : null}

        {tab === 'security' ? (
          <div className="col gap-16">
            <h3 style={{ margin: 0 }}>보안</h3>
            <InlineNotif
              kind={draft.security.totp_enabled ? 'success' : 'warning'}
              title={
                draft.security.totp_enabled
                  ? '2단계 인증 활성'
                  : '2단계 인증 비활성'
              }
              subtitle="TOTP 등록/해제는 별도 흐름(/security/totp/setup, /security/totp/disable)을 통해 진행합니다."
              lowContrast
            />
            <Field label="세션 만료 (분, preferences)">
              <NumInput
                value={draft.security.session_minutes}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    security: {
                      ...draft.security,
                      session_minutes: v ?? 0,
                    },
                  })
                }
                step={5}
              />
            </Field>
            <div style={{ paddingTop: 8 }}>
              <Btn
                kind="danger-tertiary"
                size="sm"
                onClick={() =>
                  addToast({
                    kind: 'info',
                    title: '활성 세션 종료는 /auth/logout 흐름을 사용하세요',
                  })
                }
              >
                모든 세션 로그아웃
              </Btn>
            </div>
          </div>
        ) : null}
      </div>

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}
