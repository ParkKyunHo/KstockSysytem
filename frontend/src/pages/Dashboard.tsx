import {
  Button,
  DataTable,
  OverflowMenu,
  OverflowMenuItem,
  StructuredListBody,
  StructuredListCell,
  StructuredListRow,
  StructuredListWrapper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
} from '@carbon/react';
import { Add, Renew } from '@carbon/icons-react';
import { useNavigate } from 'react-router-dom';

import { KPITile } from '@/components/kpi/KPITile';
import { PnLCell } from '@/components/pnl/PnLCell';
import {
  PositionSourceTag,
  SeverityTag,
} from '@/components/tags/StatusTag';
import { useAppShellContext } from '@/hooks/useAppShell';
import { eventLabel } from '@/lib/eventLabel';
import {
  formatKrw,
  formatKrwSigned,
  formatPct,
  formatTime,
  formatUntil,
  formatUptime,
} from '@/lib/formatters';

const TOTAL_CAPITAL = 100_000_000;

export function Dashboard() {
  const { mock } = useAppShellContext();
  const navigate = useNavigate();
  const sys = mock.systemStatus;

  // -------- KPI computations --------
  const trackedCount = mock.trackedStocks.filter(
    (t) => t.status !== 'EXITED',
  ).length;
  const boxWaiting = mock.boxes.filter((b) => b.status === 'WAITING').length;
  const boxTriggered = mock.boxes.filter(
    (b) => b.status === 'TRIGGERED',
  ).length;
  const positions = mock.positions.filter((p) => p.status !== 'CLOSED');
  const partial = positions.filter((p) => p.status === 'PARTIAL_CLOSED').length;
  const used = positions.reduce((s, p) => s + p.actual_capital_invested, 0);
  const usedPct = (used / TOTAL_CAPITAL) * 100;
  const todayPnl = positions.reduce((s, p) => s + p.pnl_amount, 0);
  const todayPnlPct = (todayPnl / TOTAL_CAPITAL) * 100;

  // -------- imminent boxes (proximity within ±2%) --------
  const upcoming = mock.boxes
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

  // -------- today's trades --------
  const dayMs = 86_400_000;
  const todaysTrades = mock.tradeEvents.filter(
    (e) => Date.now() - new Date(e.occurred_at).getTime() < dayMs,
  );

  // -------- recent notifications --------
  const recentNotifs = [...mock.notifications]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
    .slice(0, 5);

  return (
    <div>
      {/* Page header */}
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
          <Button
            kind="tertiary"
            size="sm"
            renderIcon={Renew}
            onClick={() => {
              /* P5.4: TanStack Query refetch */
            }}
          >
            새로고침
          </Button>
          <Button
            kind="primary"
            size="sm"
            renderIcon={Add}
            onClick={() => navigate('/tracked-stocks?new=1')}
          >
            새 종목 추적
          </Button>
        </div>
      </div>

      {/* KPI grid */}
      <div className="kpi-grid">
        <KPITile
          label="추적 종목"
          value={String(trackedCount)}
          subtitle={`박스 대기 ${boxWaiting} / 진입 완료 ${boxTriggered}`}
        />
        <KPITile
          label="활성 포지션"
          value={String(positions.length)}
          subtitle={`부분청산 ${partial} / 전체 보유 ${
            positions.length - partial
          }`}
        />
        <KPITile
          label="자본 사용"
          value={`${usedPct.toFixed(1)}%`}
          subtitle={`가용 ${(100 - usedPct).toFixed(1)}% · ${formatKrw(
            TOTAL_CAPITAL - used,
          )}원`}
          progress={usedPct}
        />
        <KPITile
          label="오늘 손익"
          value={`${formatKrwSigned(todayPnl)}원`}
          subtitle={formatPct(todayPnlPct)}
          tone={todayPnl >= 0 ? 'profit' : 'loss'}
          compact
        />
      </div>

      {/* System status row */}
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
        <span className="tile-row__separator" />
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
        <span className="tile-row__spacer" />
        <span className="text-helper numeric">
          Uptime {formatUptime(sys.uptime_seconds)}
        </span>
      </div>

      {/* Imminent boxes */}
      <div className="section-hd">
        <h2>진입 임박 박스</h2>
        <Button
          kind="ghost"
          size="sm"
          onClick={() => navigate('/tracked-stocks')}
        >
          전체 보기
        </Button>
      </div>
      {upcoming.length === 0 ? (
        <div
          style={{
            background: 'var(--cds-layer)',
            padding: '1rem',
          }}
        >
          <p className="text-helper" style={{ margin: 0 }}>
            현재 진입 임박 박스 없음
          </p>
        </div>
      ) : (
        <DataTable
          rows={upcoming.map((b) => {
            const ts = mock.trackedStocks.find(
              (t) => t.id === b.tracked_stock_id,
            );
            const proximity = b.entry_proximity_pct ?? 0;
            return {
              id: b.id,
              stock: (
                <span>
                  <strong>{b.stock_name}</strong>{' '}
                  <span className="text-helper numeric">{b.stock_code}</span>
                </span>
              ),
              currentPrice: ts ? `${formatKrw(ts.current_price)}원` : '-',
              box: `${formatKrw(b.lower_price)}~${formatKrw(b.upper_price)}`,
              distance: (
                <span className={proximity >= 0 ? 'pnl-profit' : 'pnl-loss'}>
                  {formatPct(proximity)}
                </span>
              ),
              size: `${b.position_size_pct}%`,
              strategy: <Tag type="cool-gray">{b.strategy_type}</Tag>,
              actions: (
                <OverflowMenu
                  flipped
                  aria-label={`${b.stock_name} ${b.box_tier}차 박스 메뉴`}
                >
                  <OverflowMenuItem
                    itemText="박스 수정"
                    onClick={() =>
                      navigate(`/tracked-stocks/${b.tracked_stock_id}`)
                    }
                  />
                  <OverflowMenuItem
                    itemText="종목 상세"
                    onClick={() =>
                      navigate(`/tracked-stocks/${b.tracked_stock_id}`)
                    }
                  />
                  <OverflowMenuItem
                    itemText="박스 취소"
                    isDelete
                    hasDivider
                    onClick={() => {
                      /* P5.4 mutation */
                    }}
                  />
                </OverflowMenu>
              ),
            };
          })}
          headers={[
            { key: 'stock', header: '종목명' },
            { key: 'currentPrice', header: '현재가' },
            { key: 'box', header: '박스' },
            { key: 'distance', header: '거리' },
            { key: 'size', header: '비중' },
            { key: 'strategy', header: '전략' },
            { key: 'actions', header: '' },
          ]}
        >
          {({ rows, headers, getHeaderProps, getRowProps, getTableProps }) => (
            <TableContainer>
              <Table {...getTableProps()}>
                <TableHead>
                  <TableRow>
                    {headers.map((h) => (
                      <TableHeader {...getHeaderProps({ header: h })}>
                        {h.header}
                      </TableHeader>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow {...getRowProps({ row })}>
                      {row.cells.map((cell) => (
                        <TableCell key={cell.id}>{cell.value}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DataTable>
      )}

      {/* Active positions */}
      <div className="section-hd">
        <h2>활성 포지션</h2>
        <Button kind="ghost" size="sm" onClick={() => navigate('/positions')}>
          전체 보기
        </Button>
      </div>
      {positions.length === 0 ? (
        <div style={{ background: 'var(--cds-layer)', padding: '1rem' }}>
          <p className="text-helper" style={{ margin: 0 }}>
            활성 포지션 없음
          </p>
        </div>
      ) : (
        <DataTable
          rows={positions.map((p) => ({
            id: p.id,
            stock: (
              <span>
                <strong>{p.stock_name}</strong>{' '}
                <span className="text-helper numeric">{p.stock_code}</span>
              </span>
            ),
            source: <PositionSourceTag source={p.source} />,
            qty: String(p.total_quantity),
            avg: formatKrw(p.weighted_avg_price),
            price: formatKrw(p.current_price),
            pnl: (
              <div style={{ textAlign: 'right' }}>
                <PnLCell amount={p.pnl_amount} pct={p.pnl_pct} />
              </div>
            ),
            stop: formatKrw(p.fixed_stop_price),
            ts: p.ts_activated ? (
              <Tag type="green" size="sm">
                TS 활성
              </Tag>
            ) : (
              <span className="text-helper">-</span>
            ),
          }))}
          headers={[
            { key: 'stock', header: '종목' },
            { key: 'source', header: '출처' },
            { key: 'qty', header: '수량' },
            { key: 'avg', header: '평단' },
            { key: 'price', header: '현재가' },
            { key: 'pnl', header: '손익' },
            { key: 'stop', header: '손절선' },
            { key: 'ts', header: 'TS' },
          ]}
        >
          {({ rows, headers, getHeaderProps, getRowProps, getTableProps }) => (
            <TableContainer>
              <Table {...getTableProps()}>
                <TableHead>
                  <TableRow>
                    {headers.map((h) => (
                      <TableHeader {...getHeaderProps({ header: h })}>
                        {h.header}
                      </TableHeader>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow
                      {...getRowProps({ row })}
                      onClick={() => navigate('/positions')}
                      style={{ cursor: 'pointer' }}
                    >
                      {row.cells.map((cell) => (
                        <TableCell key={cell.id}>{cell.value}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DataTable>
      )}

      {/* Today's trades + recent notifications (2-up) */}
      <div className="grid-2" style={{ marginTop: '1.5rem' }}>
        {/* Today's trades */}
        <div>
          <div className="section-hd">
            <h2>오늘 거래</h2>
            <span className="text-helper">{todaysTrades.length}건</span>
          </div>
          <DataTable
            rows={
              todaysTrades.length === 0
                ? [
                    {
                      id: 'empty',
                      time: '',
                      stock: '오늘 거래 없음',
                      kind: '',
                      qty: '',
                      price: '',
                    },
                  ]
                : todaysTrades.slice(0, 6).map((e) => {
                    const pos = mock.positions.find(
                      (p) => p.id === e.position_id,
                    );
                    return {
                      id: e.id,
                      time: formatTime(e.occurred_at),
                      stock: pos?.stock_name ?? e.stock_code,
                      kind: eventLabel(e.event_type),
                      qty: String(e.quantity),
                      price: formatKrw(e.price),
                    };
                  })
            }
            headers={[
              { key: 'time', header: '시간' },
              { key: 'stock', header: '종목' },
              { key: 'kind', header: '이벤트' },
              { key: 'qty', header: '수량' },
              { key: 'price', header: '가격' },
            ]}
            size="sm"
          >
            {({
              rows,
              headers,
              getHeaderProps,
              getRowProps,
              getTableProps,
            }) => (
              <TableContainer>
                <Table {...getTableProps()}>
                  <TableHead>
                    <TableRow>
                      {headers.map((h) => (
                        <TableHeader {...getHeaderProps({ header: h })}>
                          {h.header}
                        </TableHeader>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow {...getRowProps({ row })}>
                        {row.cells.map((cell) => (
                          <TableCell key={cell.id}>{cell.value}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </DataTable>
        </div>

        {/* Recent notifications */}
        <div>
          <div className="section-hd">
            <h2>최근 알림</h2>
            <Button
              kind="ghost"
              size="sm"
              onClick={() => navigate('/notifications')}
            >
              전체
            </Button>
          </div>
          <StructuredListWrapper isCondensed>
            <StructuredListBody>
              {recentNotifs.map((n) => (
                <StructuredListRow key={n.id}>
                  <StructuredListCell style={{ width: '5.5rem' }}>
                    <SeverityTag severity={n.severity} />
                  </StructuredListCell>
                  <StructuredListCell>
                    <div style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
                      {n.title}
                    </div>
                    <div className="text-helper" style={{ marginTop: '0.125rem' }}>
                      {n.message}
                    </div>
                  </StructuredListCell>
                  <StructuredListCell
                    style={{
                      width: '4rem',
                      textAlign: 'right',
                      fontFamily: 'IBM Plex Mono, monospace',
                      fontSize: '0.75rem',
                    }}
                  >
                    {formatTime(n.created_at)}
                  </StructuredListCell>
                </StructuredListRow>
              ))}
            </StructuredListBody>
          </StructuredListWrapper>
        </div>
      </div>
    </div>
  );
}
