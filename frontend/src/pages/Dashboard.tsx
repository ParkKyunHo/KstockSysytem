// V7.1 Dashboard -- wired to real REST APIs (PRD §0~§9).
//
// Data sources:
//   - useSystemStatus() / useUnreadNotifications()    (PRD §9, §7)
//   - useTrackedStocks() / useBoxes()                 (PRD §3, §4)
//   - usePositions() / usePositionsSummary()          (PRD §5)
//   - useTradeEventsToday()                           (PRD §6.2)
//   - useNotifications({ limit: 100 })                (PRD §7.1)
//
// P-Wire-Price-Tick (2026-04-30) — live price source 우선순위:
//   1. priceStore (WS POSITION_PRICE_UPDATE, 1Hz throttled by backend)
//   2. PositionOut.current_price (PRD Patch #5 DB column)
//   3. mock.trackedStocks (dev fallback only — useLiveMock setInterval)
//   4. null → "—" UI

import { useNavigate } from 'react-router-dom';

import type { BoxOut } from '@/api/boxes';
import type { PositionOut } from '@/api/positions';
import { I } from '@/components/icons';
import {
  Btn,
  KPITile,
  OverflowMenu,
  PnLCell,
  PositionSourceTag,
  SeverityTag,
  Tag,
} from '@/components/ui';
import { useAppShellContext } from '@/hooks/useAppShell';
import {
  useBoxes,
  useNotifications,
  usePositions,
  usePositionsSummary,
  useSystemStatus,
  useTrackedStocks,
  useTradeEventsToday,
} from '@/hooks/useApi';
import { eventLabel } from '@/lib/eventLabel';
import {
  formatKrw,
  formatKrwSigned,
  formatPct,
  formatTime,
  formatUntil,
  formatUptime,
} from '@/lib/formatters';
import { usePriceStore } from '@/stores/priceStore';

interface PnlComputed {
  current_price: number | null;
  pnl_amount: number | null;
  pnl_pct: number | null;
}

function computePnl(
  p: PositionOut,
  wsPrice: number | null,
  wsPnlAmount: number | null,
  wsPnlPct: number | null,
  fallbackPriceByCode: Map<string, number>,
): PnlComputed {
  // 1. WS push (live, 1Hz)
  if (wsPrice != null && wsPnlAmount != null && wsPnlPct != null) {
    return {
      current_price: wsPrice,
      pnl_amount: wsPnlAmount,
      pnl_pct: Number((wsPnlPct * 100).toFixed(2)),
    };
  }
  // 2. DB column (PRD Patch #5)
  if (p.current_price != null) {
    return {
      current_price: p.current_price,
      pnl_amount: p.pnl_amount ?? 0,
      pnl_pct: p.pnl_pct != null ? Number((p.pnl_pct * 100).toFixed(2)) : 0,
    };
  }
  // 3. mock fallback (dev only)
  const fallback = fallbackPriceByCode.get(p.stock_code);
  if (fallback == null) {
    return { current_price: null, pnl_amount: null, pnl_pct: null };
  }
  const amount = (fallback - p.weighted_avg_price) * p.total_quantity;
  const pct =
    p.weighted_avg_price > 0
      ? ((fallback - p.weighted_avg_price) / p.weighted_avg_price) * 100
      : 0;
  return {
    current_price: fallback,
    pnl_amount: Math.round(amount),
    pnl_pct: Number(pct.toFixed(2)),
  };
}

export function Dashboard() {
  const navigate = useNavigate();
  const { mock } = useAppShellContext();

  // Real API.
  const { data: systemStatus } = useSystemStatus();
  const { data: trackedList } = useTrackedStocks({ limit: 200 });
  const { data: boxList } = useBoxes({ limit: 200 });
  const { data: positionList } = usePositions({ limit: 200 });
  const { data: summary } = usePositionsSummary();
  const { data: today } = useTradeEventsToday();
  const { data: notifList } = useNotifications({ limit: 5 });

  const sys = systemStatus ?? mock.systemStatus;
  const trackedStocks = trackedList?.data ?? [];
  const boxes = boxList?.data ?? [];
  const positions = (positionList?.data ?? []).filter(
    (p) => p.status !== 'CLOSED',
  );

  const trackedCount = trackedStocks.filter(
    (t) => t.status !== 'EXITED',
  ).length;
  const boxWaiting = boxes.filter((b) => b.status === 'WAITING').length;
  const boxTriggered = boxes.filter((b) => b.status === 'TRIGGERED').length;
  const partial = positions.filter((p) => p.status === 'PARTIAL_CLOSED').length;

  const totalCapitalPct = summary?.total_capital_pct ?? 0;
  const totalCapitalInvested = summary?.total_capital_invested ?? 0;
  const totalPnl = today?.total_pnl ?? summary?.total_pnl_amount ?? 0;
  const totalPnlPct = today?.total_pnl_pct ?? summary?.total_pnl_pct ?? null;

  // P-Wire-Price-Tick (2026-04-30): WS push priority. Mock kept as
  // fallback (dev) and as initial render before first tick lands.
  const wsByStockCode = usePriceStore((s) => s.byStockCode);
  const wsByPositionId = usePriceStore((s) => s.byPositionId);

  const priceByCode = new Map<string, number>();
  for (const m of mock.trackedStocks) {
    priceByCode.set(m.stock_code, m.current_price);
  }

  const upcoming: BoxOut[] = boxes
    .filter(
      (b) =>
        b.status === 'WAITING' &&
        b.entry_proximity_pct != null &&
        Math.abs(b.entry_proximity_pct) < 2,
    )
    .sort(
      (a, b) =>
        Math.abs(a.entry_proximity_pct ?? 99) -
        Math.abs(b.entry_proximity_pct ?? 99),
    )
    .slice(0, 5);

  const todaysBuys = today?.buys ?? [];
  const todaysSells = [
    ...(today?.sells ?? []),
    ...(today?.auto_exits ?? []),
    ...(today?.manual_trades ?? []),
  ];
  const todaysCount = todaysBuys.length + todaysSells.length;

  const recentNotifs = (notifList?.data ?? []).slice(0, 5);

  return (
    <div>
      {/* page-hd */}
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">대시보드</h1>
          <div className="page-hd__subtitle">
            {sys.market.is_open
              ? `장 진행중 · 마감까지 ${formatUntil(sys.market.next_close_at)}`
              : '장 마감'}
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn kind="tertiary" size="sm" icon={I.Renew}>
            새로고침
          </Btn>
          <Btn
            kind="primary"
            size="sm"
            icon={I.Add}
            onClick={() => navigate('/tracked-stocks?new=1')}
          >
            새 종목 추적
          </Btn>
        </div>
      </div>

      {/* KPI grid */}
      <div className="kpi-grid">
        <KPITile
          label="추적 종목"
          value={trackedCount}
          sub={`박스 대기 ${boxWaiting} / 진입 완료 ${boxTriggered}`}
        />
        <KPITile
          label="활성 포지션"
          value={positions.length}
          sub={`부분청산 ${partial} / 전체 보유 ${
            positions.length - partial
          }`}
        />
        <KPITile
          label="자본 사용"
          value={`${totalCapitalPct.toFixed(1)}%`}
          sub={`투입 ${formatKrw(totalCapitalInvested)}원`}
          progress={totalCapitalPct}
        />
        <KPITile
          label="오늘 손익"
          value={`${formatKrwSigned(totalPnl)}원`}
          sub={formatPct(totalPnlPct)}
          color={totalPnl >= 0 ? 'profit' : 'loss'}
        />
      </div>

      {/* tile-row 시스템 상태 */}
      <div className="tile-row">
        <Tag type={sys.status === 'RUNNING' ? 'green' : 'red'}>
          {sys.status === 'RUNNING' ? '시스템 정상' : '안전 모드'}
        </Tag>
        <Tag type={sys.websocket.connected ? 'green' : 'red'}>WebSocket</Tag>
        <Tag type={sys.kiwoom_api.available ? 'green' : 'red'}>
          키움 API {sys.kiwoom_api.rate_limit_used_per_sec}/
          {sys.kiwoom_api.rate_limit_max}
        </Tag>
        <Tag type={sys.telegram_bot.active ? 'green' : 'red'}>Telegram</Tag>
        <div
          style={{
            width: 1,
            height: 16,
            background: 'var(--cds-border-subtle-00)',
            margin: '0 4px',
          }}
        />
        <Tag type="blue">
          {sys.market.is_open
            ? `장 진행중 ${formatTime(sys.current_time)}`
            : '장 마감'}
        </Tag>
        {sys.market.is_open ? (
          <span className="text-helper">
            마감까지 {formatUntil(sys.market.next_close_at)}
          </span>
        ) : null}
        <span className="spacer" />
        <span className="text-helper tnum">
          Uptime {formatUptime(sys.uptime_seconds)}
        </span>
      </div>

      {/* 진입 임박 박스 */}
      <div className="section-hd">
        <h2>진입 임박 박스</h2>
        <Btn
          kind="ghost"
          size="sm"
          onClick={() => navigate('/tracked-stocks')}
        >
          전체 보기
        </Btn>
      </div>
      {upcoming.length === 0 ? (
        <div className="cds-tile">
          <p className="text-helper" style={{ margin: 0 }}>
            현재 진입 임박 박스 없음
          </p>
        </div>
      ) : (
        <div className="cds-data-table">
          <div className="table-wrap">
            <table className="cds-table">
              <thead>
                <tr>
                  <th>종목명</th>
                  <th style={{ textAlign: 'right' }}>현재가</th>
                  <th>박스</th>
                  <th style={{ textAlign: 'right' }}>거리</th>
                  <th style={{ textAlign: 'right' }}>비중</th>
                  <th>전략</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {upcoming.map((b) => {
                  const proximity = b.entry_proximity_pct ?? 0;
                  const livePrice =
                    wsByStockCode.get(b.stock_code)?.price ??
                    priceByCode.get(b.stock_code);
                  return (
                    <tr key={b.id}>
                      <td>
                        <strong>{b.stock_name}</strong>{' '}
                        <span className="text-helper mono">{b.stock_code}</span>
                      </td>
                      <td className="price">
                        {livePrice != null ? `${formatKrw(livePrice)}원` : '-'}
                      </td>
                      <td className="mono">
                        {formatKrw(b.lower_price)}~{formatKrw(b.upper_price)}
                      </td>
                      <td
                        className={`price ${
                          proximity >= 0 ? 'pnl-profit' : 'pnl-loss'
                        }`}
                      >
                        {formatPct(proximity)}
                      </td>
                      <td className="price">{b.position_size_pct}%</td>
                      <td>
                        <Tag type="cool-gray">{b.strategy_type}</Tag>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <OverflowMenu
                          items={[
                            {
                              label: '박스 수정',
                              onClick: () =>
                                navigate(
                                  `/tracked-stocks/${b.tracked_stock_id}`,
                                ),
                            },
                            {
                              label: '종목 상세',
                              onClick: () =>
                                navigate(
                                  `/tracked-stocks/${b.tracked_stock_id}`,
                                ),
                            },
                            { divider: true },
                            { label: '박스 취소', danger: true },
                          ]}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 활성 포지션 */}
      <div className="section-hd">
        <h2>활성 포지션</h2>
        <Btn kind="ghost" size="sm" onClick={() => navigate('/positions')}>
          전체 보기
        </Btn>
      </div>
      {positions.length === 0 ? (
        <div className="cds-tile">
          <p className="text-helper" style={{ margin: 0 }}>
            활성 포지션 없음
          </p>
        </div>
      ) : (
        <div className="cds-data-table">
          <div className="table-wrap">
            <table className="cds-table">
              <thead>
                <tr>
                  <th>종목</th>
                  <th>출처</th>
                  <th style={{ textAlign: 'right' }}>수량</th>
                  <th style={{ textAlign: 'right' }}>평단</th>
                  <th style={{ textAlign: 'right' }}>현재가</th>
                  <th style={{ textAlign: 'right' }}>손익</th>
                  <th style={{ textAlign: 'right' }}>손절선</th>
                  <th>TS</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const wsStock = wsByStockCode.get(p.stock_code);
                  const wsPos = wsByPositionId.get(p.id);
                  const computed = computePnl(
                    p,
                    wsStock?.price ?? null,
                    wsPos?.pnlAmount ?? null,
                    wsPos?.pnlPct ?? null,
                    priceByCode,
                  );
                  return (
                    <tr
                      key={p.id}
                      style={{ cursor: 'pointer' }}
                      onClick={() => navigate('/positions')}
                    >
                      <td>
                        <strong>{p.stock_name}</strong>{' '}
                        <span className="text-helper mono">{p.stock_code}</span>
                      </td>
                      <td>
                        <PositionSourceTag source={p.source} />
                      </td>
                      <td className="price">{p.total_quantity}</td>
                      <td className="price">
                        {formatKrw(p.weighted_avg_price)}
                      </td>
                      <td className="price">{formatKrw(computed.current_price)}</td>
                      <td>
                        <div style={{ textAlign: 'right' }}>
                          <PnLCell
                            amount={computed.pnl_amount ?? 0}
                            pct={computed.pnl_pct ?? 0}
                          />
                        </div>
                      </td>
                      <td className="price">{formatKrw(p.fixed_stop_price)}</td>
                      <td>
                        {p.ts_activated ? (
                          <Tag type="green" size="sm">
                            TS 활성
                          </Tag>
                        ) : (
                          <span className="text-helper">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 오늘 거래 + 최근 알림 */}
      <div className="grid-2" style={{ marginTop: 24 }}>
        <div>
          <div className="section-hd">
            <h2>오늘 거래</h2>
            <span className="text-helper">{todaysCount}건</span>
          </div>
          <div className="cds-data-table">
            <table className="cds-table cds-table--compact">
              <thead>
                <tr>
                  <th>시간</th>
                  <th>종목</th>
                  <th>이벤트</th>
                  <th style={{ textAlign: 'right' }}>수량</th>
                  <th style={{ textAlign: 'right' }}>가격</th>
                </tr>
              </thead>
              <tbody>
                {todaysCount === 0 ? (
                  <tr>
                    <td
                      colSpan={5}
                      style={{ color: 'var(--cds-text-helper)' }}
                    >
                      오늘 거래 없음
                    </td>
                  </tr>
                ) : (
                  <>
                    {todaysBuys.slice(0, 6).map((e) => (
                      <tr key={`buy-${e.stock_code}-${e.occurred_at}`}>
                        <td className="mono">{formatTime(e.occurred_at)}</td>
                        <td>{e.stock_code}</td>
                        <td>{eventLabel('BUY_EXECUTED')}</td>
                        <td className="price">{e.quantity}</td>
                        <td className="price">{formatKrw(e.price)}</td>
                      </tr>
                    ))}
                    {todaysSells.slice(0, 6 - todaysBuys.length).map((e) => (
                      <tr key={`sell-${e.stock_code}-${e.occurred_at}`}>
                        <td className="mono">{formatTime(e.occurred_at)}</td>
                        <td>{e.stock_code}</td>
                        <td>{e.reason ?? '청산'}</td>
                        <td className="price">{e.quantity}</td>
                        <td className="price">{formatKrw(e.price)}</td>
                      </tr>
                    ))}
                  </>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div>
          <div className="section-hd">
            <h2>최근 알림</h2>
            <Btn
              kind="ghost"
              size="sm"
              onClick={() => navigate('/notifications')}
            >
              전체
            </Btn>
          </div>
          <div className="cds-slist">
            {recentNotifs.map((n) => (
              <div
                key={n.id}
                className="cds-slist__row"
                style={{ gridTemplateColumns: '88px 1fr 64px' }}
              >
                <div className="cds-slist__cell">
                  <SeverityTag severity={n.severity} sm />
                </div>
                <div
                  className="cds-slist__cell"
                  style={{ background: 'transparent' }}
                >
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    {n.title}
                  </div>
                  <div className="text-helper" style={{ marginTop: 2 }}>
                    {n.message}
                  </div>
                </div>
                <div
                  className="cds-slist__cell mono"
                  style={{
                    background: 'transparent',
                    textAlign: 'right',
                    fontSize: 12,
                  }}
                >
                  {formatTime(n.created_at)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
