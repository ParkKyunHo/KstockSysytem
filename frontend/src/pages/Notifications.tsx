// V7.1 Notifications -- wired to /api/v71/notifications (PRD §7).
// Read state is server-driven: ``status == 'SENT'`` means delivered/read
// for the WEB channel (PRD §7.3 mark_read flips the status to SENT).

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type {
  NotificationOut,
  NotificationSeverityLit,
} from '@/api/notifications';
import {
  Btn,
  Dropdown,
  SeverityTag,
  Tabs,
  ToastContainer,
  useToasts,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  useMarkNotificationRead,
  useNotifications,
} from '@/hooks/useApi';
import { formatDateTime } from '@/lib/formatters';

type NotifTab = 'all' | 'unread' | 'critical';
type TypeFilter = 'all' | string;

interface ActionSpec {
  label: string;
  go: () => void;
}

const isUnread = (n: NotificationOut): boolean => n.status !== 'SENT';

export function Notifications() {
  const navigate = useNavigate();
  const { toasts, addToast, closeToast } = useToasts();
  const { mock } = useAppShellContext(); // for tracked-stocks name lookup

  const [tab, setTab] = useState<NotifTab>('all');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');

  const { data: list, isLoading } = useNotifications({ limit: 100 });
  const markRead = useMarkNotificationRead({
    onSuccess: () =>
      addToast({ kind: 'success', title: '읽음 처리됨' }),
  });

  const items = list?.data ?? [];

  const filtered = items.filter((n) => {
    if (tab === 'unread' && !isUnread(n)) return false;
    if (tab === 'critical' && n.severity !== 'CRITICAL') return false;
    if (typeFilter !== 'all' && n.event_type !== typeFilter) return false;
    return true;
  });

  const unreadCount = items.filter(isUnread).length;
  const criticalCount = items.filter(
    (n) => n.severity === 'CRITICAL',
  ).length;

  const markOne = (id: string) => {
    markRead.mutate(id);
  };

  const markAll = () => {
    items.filter(isUnread).forEach((n) => markRead.mutate(n.id));
  };

  const actionFor = (n: NotificationOut): ActionSpec => {
    const map: Record<string, ActionSpec> = {
      STOP_LOSS: {
        label: '포지션 보기',
        go: () => {
          navigate('/positions');
          markOne(n.id);
        },
      },
      BOX_PROXIMITY: {
        label: '종목 보기',
        go: () => {
          navigate('/tracked-stocks');
          markOne(n.id);
        },
      },
      BOX_TRIGGERED: {
        label: '포지션 보기',
        go: () => {
          navigate('/positions');
          markOne(n.id);
        },
      },
      PROFIT_TAKE: {
        label: '포지션 보기',
        go: () => {
          navigate('/positions');
          markOne(n.id);
        },
      },
      PYRAMID: {
        label: '포지션 보기',
        go: () => {
          navigate('/positions');
          markOne(n.id);
        },
      },
      REPORT_COMPLETED: {
        label: '리포트 열기',
        go: () => {
          navigate('/reports');
          markOne(n.id);
        },
      },
      BOX_INVALIDATED: {
        label: '종목 보기',
        go: () => {
          navigate('/tracked-stocks');
          markOne(n.id);
        },
      },
      VI_TRIGGERED: { label: '확인', go: () => markOne(n.id) },
      TRACKING_AUTO_EXIT: { label: '확인', go: () => markOne(n.id) },
      WS_DISCONNECT: { label: '시스템 상태', go: () => markOne(n.id) },
    };
    return map[n.event_type] ?? { label: '읽음', go: () => markOne(n.id) };
  };

  const types = useMemo(
    () => Array.from(new Set(items.map((n) => n.event_type))),
    [items],
  );

  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">알림</h1>
          <div className="page-hd__subtitle">
            미확인 {unreadCount}건 · 전체 {items.length}건 · CRITICAL{' '}
            {criticalCount}건
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="tertiary"
            size="sm"
            onClick={markAll}
            disabled={unreadCount === 0 || markRead.isPending}
          >
            모두 읽음
          </Btn>
        </div>
      </div>

      <Tabs<NotifTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'all', label: '전체', count: items.length },
          { value: 'unread', label: '미확인', count: unreadCount },
          { value: 'critical', label: '긴급', count: criticalCount },
        ]}
      />

      <div className="cds-data-table" style={{ marginTop: 16 }}>
        <div className="table-toolbar">
          <div
            className="table-toolbar__tools"
            style={{ marginLeft: 'auto' }}
          >
            <Dropdown<TypeFilter>
              value={typeFilter}
              onChange={setTypeFilter}
              options={[
                { value: 'all', label: '유형: 전체' },
                ...types.map((t) => ({ value: t, label: t })),
              ]}
            />
          </div>
        </div>

        {isLoading ? (
          <div
            className="cds-tile"
            style={{ padding: 32, textAlign: 'center' }}
          >
            <p className="text-helper">알림 불러오는 중…</p>
          </div>
        ) : filtered.length === 0 ? (
          <div
            className="cds-tile"
            style={{ padding: 32, textAlign: 'center' }}
          >
            <p className="text-helper">알림이 없습니다.</p>
          </div>
        ) : (
          <div className="notif-list">
            {filtered.map((n) => {
              const unread = isUnread(n);
              const action = actionFor(n);
              const stock = n.stock_code
                ? mock.trackedStocks.find(
                    (s) => s.stock_code === n.stock_code,
                  )
                : null;
              return (
                <div
                  key={n.id}
                  className={`notif-row${unread ? ' is-unread' : ''}`}
                >
                  <div className="notif-row__sev">
                    <SeverityTag
                      severity={n.severity as NotificationSeverityLit}
                      sm
                    />
                  </div>
                  <div className="notif-row__body">
                    <div className="notif-row__title">
                      {unread ? <span className="unread-dot" /> : null}
                      <strong>{n.title}</strong>
                      <span className="notif-row__type mono">
                        {n.event_type}
                      </span>
                    </div>
                    <div className="notif-row__msg">{n.message}</div>
                    <div className="notif-row__meta mono text-helper">
                      {formatDateTime(n.sent_at ?? n.created_at)} · 채널{' '}
                      {n.channel || 'WEB'}
                      {stock
                        ? ` · ${stock.stock_name} (${n.stock_code})`
                        : n.stock_code
                          ? ` · ${n.stock_code}`
                          : ''}
                    </div>
                  </div>
                  <div className="notif-row__actions">
                    <Btn
                      kind="ghost"
                      size="sm"
                      onClick={action.go}
                      disabled={markRead.isPending}
                    >
                      {action.label}
                    </Btn>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}
