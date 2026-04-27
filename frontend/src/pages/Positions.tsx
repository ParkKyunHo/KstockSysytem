// V7.1 Positions monitor -- wired to /api/v71/positions (PRD §5).
//
// Position pnl is recomputed on the client from PositionOut.weighted_avg_price
// against the cached mock price (until the price WebSocket is wired). The
// server-authoritative summary is also fetched for the KPI tiles.

import { useMemo, useState } from 'react';

import type { PositionOut } from '@/api/positions';
import type { PositionSourceLit } from '@/api/trackedStocks';
import { OrderDialog, type OrderSide } from '@/components/OrderDialog';
import {
  Btn,
  Dropdown,
  KPITile,
  OverflowMenu,
  PositionSourceTag,
  SearchBox,
  Tabs,
  ToastContainer,
  useToasts,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  usePositions,
  usePositionsSummary,
  useReconcilePositions,
} from '@/hooks/useApi';
import { ApiClientError } from '@/lib/api';
import {
  formatKrw,
  formatKrwSigned,
  formatPct,
} from '@/lib/formatters';

type PosTab = 'open' | 'closed';
type SourceFilter = 'all' | PositionSourceLit;

interface OrderDialogState {
  side: OrderSide;
  position?: PositionOut;
}

interface ComputedPnl {
  current: number | null;
  pnlAmount: number;
  pnlPct: number;
}

// ★ PRD Patch #5 (V7.1.0d, 2026-04-27):
// PositionOut.current_price/pnl_amount/pnl_pct를 직접 사용. 백엔드는
// WebSocket 0B (<1s) > kt00018 (5s) > ka10001 (재시작) 우선순위로 갱신.
// fallback으로 mock 가격 lookup도 유지 (백엔드 미갱신 row 대비).
function computePnl(p: PositionOut, fallbackPrice: number | null): ComputedPnl {
  if (p.current_price != null) {
    return {
      current: p.current_price,
      pnlAmount: p.pnl_amount ?? 0,
      pnlPct: p.pnl_pct != null ? Number((p.pnl_pct * 100).toFixed(2)) : 0,
    };
  }
  // Fallback: 백엔드가 아직 가격 갱신 전인 row (재시작 직후 등)
  if (fallbackPrice == null) {
    return { current: null, pnlAmount: 0, pnlPct: 0 };
  }
  const amount = (fallbackPrice - p.weighted_avg_price) * p.total_quantity;
  const pct =
    p.weighted_avg_price > 0
      ? ((fallbackPrice - p.weighted_avg_price) / p.weighted_avg_price) * 100
      : 0;
  return {
    current: fallbackPrice,
    pnlAmount: Math.round(amount),
    pnlPct: Number(pct.toFixed(2)),
  };
}

export function Positions() {
  const { mock } = useAppShellContext();
  const { toasts, addToast, closeToast } = useToasts();

  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [tab, setTab] = useState<PosTab>('open');
  const [orderDlg, setOrderDlg] = useState<OrderDialogState | null>(null);

  const { data: positionList } = usePositions({ limit: 200 });
  const { data: summary } = usePositionsSummary();

  const reconcile = useReconcilePositions({
    onSuccess: (task) =>
      addToast({
        kind: 'info',
        title: '동기화 시작',
        subtitle: `예상 ${task.estimated_seconds}초 (task ${task.task_id})`,
      }),
    onError: (err) =>
      addToast({
        kind: 'error',
        title: '동기화 실패',
        subtitle: err instanceof ApiClientError ? err.message : undefined,
      }),
  });

  const priceByCode = useMemo(() => {
    const m = new Map<string, number>();
    for (const ms of mock.trackedStocks) m.set(ms.stock_code, ms.current_price);
    return m;
  }, [mock.trackedStocks]);

  const positions = positionList?.data ?? [];
  const open = positions.filter(
    (p) => p.status === 'OPEN' || p.status === 'PARTIAL_CLOSED',
  );
  const closed = positions.filter((p) => p.status === 'CLOSED');
  const list = tab === 'open' ? open : closed;

  const filtered = useMemo(
    () =>
      list.filter((p) => {
        if (
          search &&
          !(p.stock_name.includes(search) || p.stock_code.includes(search))
        )
          return false;
        if (sourceFilter !== 'all' && p.source !== sourceFilter) return false;
        return true;
      }),
    [list, search, sourceFilter],
  );

  const totalPnL = summary?.total_pnl_amount ?? 0;
  const totalPnLPct = summary?.total_pnl_pct ?? 0;

  return (
    <div>
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">포지션</h1>
          <div className="page-hd__subtitle">
            보유 {open.length}개 · 종료 {closed.length}개
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="tertiary"
            size="sm"
            onClick={() => reconcile.mutate()}
            disabled={reconcile.isPending}
          >
            {reconcile.isPending ? '동기화 중…' : '키움 동기화'}
          </Btn>
          <Btn
            kind="primary"
            size="sm"
            onClick={() => setOrderDlg({ side: 'BUY' })}
          >
            수동 주문
          </Btn>
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: 24 }}>
        <KPITile label="보유 종목" value={open.length} sub="개" />
        <KPITile
          label="평가 손익"
          value={`${formatKrwSigned(totalPnL)}원`}
          color={totalPnL >= 0 ? 'profit' : 'loss'}
        />
        <KPITile
          label="수익률"
          value={formatPct(totalPnLPct)}
          color={totalPnL >= 0 ? 'profit' : 'loss'}
        />
      </div>

      <Tabs<PosTab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'open', label: '보유 중', count: open.length },
          { value: 'closed', label: '종료', count: closed.length },
        ]}
      />

      <div className="cds-data-table" style={{ marginTop: 16 }}>
        <div className="table-toolbar">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="종목명·코드"
          />
          <Dropdown<SourceFilter>
            value={sourceFilter}
            onChange={setSourceFilter}
            options={[
              { value: 'all', label: '출처: 전체' },
              { value: 'SYSTEM_A', label: 'SYSTEM_A' },
              { value: 'SYSTEM_B', label: 'SYSTEM_B' },
              { value: 'MANUAL', label: 'HTS 수동' },
            ]}
          />
        </div>
        <div className="table-wrap">
          <table className="cds-table">
            <thead>
              <tr>
                <th>종목</th>
                <th>출처</th>
                <th style={{ textAlign: 'right' }}>수량</th>
                <th style={{ textAlign: 'right' }}>평단가</th>
                <th style={{ textAlign: 'right' }}>현재가</th>
                <th style={{ textAlign: 'right' }}>평가손익</th>
                <th style={{ textAlign: 'right' }}>수익률</th>
                <th>단계</th>
                <th style={{ textAlign: 'right' }}>손절선</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => {
                const livePrice = priceByCode.get(p.stock_code) ?? null;
                const computed = computePnl(p, livePrice);
                return (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.stock_name}</strong>{' '}
                      <span className="mono text-helper">{p.stock_code}</span>
                    </td>
                    <td>
                      <PositionSourceTag source={p.source} />
                    </td>
                    <td className="price">{p.total_quantity}</td>
                    <td className="price">
                      {formatKrw(p.weighted_avg_price)}
                    </td>
                    <td className="price">{formatKrw(computed.current)}</td>
                    <td
                      className={`price ${computed.pnlAmount >= 0 ? 'pnl-profit' : 'pnl-loss'}`}
                    >
                      {formatKrwSigned(computed.pnlAmount)}
                    </td>
                    <td
                      className={`price ${computed.pnlAmount >= 0 ? 'pnl-profit' : 'pnl-loss'}`}
                    >
                      {formatPct(computed.pnlPct)}
                    </td>
                    <td>
                      {p.profit_10_executed
                        ? '+10% 후'
                        : p.profit_5_executed
                          ? '+5% 후'
                          : '초기'}
                    </td>
                    <td className="price pnl-loss">
                      {formatKrw(p.fixed_stop_price)}
                    </td>
                    <td>
                      {p.status !== 'CLOSED' ? (
                        <OverflowMenu
                          items={[
                            {
                              label: '추가 매수',
                              onClick: () =>
                                setOrderDlg({ side: 'BUY', position: p }),
                            },
                            {
                              label: '매도',
                              onClick: () =>
                                setOrderDlg({ side: 'SELL', position: p }),
                            },
                          ]}
                        />
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {orderDlg ? (
        <OrderDialog
          open
          onClose={() => setOrderDlg(null)}
          mock={mock}
          addToast={addToast}
          defaultSide={orderDlg.side}
          defaultPosition={
            orderDlg.position
              ? mock.positions.find((p) => p.id === orderDlg.position?.id) ??
                undefined
              : undefined
          }
        />
      ) : null}

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}
