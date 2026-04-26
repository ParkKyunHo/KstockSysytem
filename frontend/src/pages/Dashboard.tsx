import {
  Column,
  DataTable,
  Grid,
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
  Tile,
} from '@carbon/react';
import { useNavigate } from 'react-router-dom';

import { KPITile } from '@/components/kpi/KPITile';
import { PnLCell } from '@/components/pnl/PnLCell';
import {
  BoxStatusTag,
  PositionSourceTag,
  PositionStatusTag,
  SeverityTag,
  TrackedStatusTag,
} from '@/components/tags/StatusTag';
import { useLiveMock } from '@/hooks/useLiveMock';
import {
  formatKrw,
  formatKrwSigned,
  formatPct,
  formatPctRaw,
  formatTime,
} from '@/lib/formatters';
import { initialMock, type TrackedStockWithPrice } from '@/mocks';
import type { Box, NotificationRecord, Position, TradeEvent } from '@/types';

const TOTAL_CAPITAL = 100_000_000;

export function Dashboard() {
  const mock = useLiveMock(initialMock);
  const navigate = useNavigate();

  // ---------- KPI computations ----------
  const trackingCount = mock.trackedStocks.filter(
    (s) => s.status !== 'EXITED',
  ).length;
  const waitingBoxCount = mock.boxes.filter((b) => b.status === 'WAITING').length;
  const activePositions = mock.positions.filter((p) => p.status !== 'CLOSED');
  const partialPositionCount = activePositions.filter(
    (p) => p.status === 'PARTIAL_CLOSED',
  ).length;
  const capitalUsed = activePositions.reduce(
    (acc, p) => acc + p.actual_capital_invested,
    0,
  );
  const capitalUsedPct = (capitalUsed / TOTAL_CAPITAL) * 100;
  const todayPnl = activePositions.reduce((acc, p) => acc + p.pnl_amount, 0);
  const todayPnlPct = (todayPnl / TOTAL_CAPITAL) * 100;

  // ---------- imminent boxes (entry_proximity_pct within ±2%) ----------
  const imminentBoxes = mock.boxes
    .filter(
      (b) =>
        b.status === 'WAITING' &&
        b.entry_proximity_pct != null &&
        Math.abs(b.entry_proximity_pct) <= 2,
    )
    .sort(
      (a, b) =>
        Math.abs(a.entry_proximity_pct ?? 99) -
        Math.abs(b.entry_proximity_pct ?? 99),
    );

  // ---------- today's trade events ----------
  const todayStartIso = new Date(
    new Date(mock.systemStatus.current_time).setHours(0, 0, 0, 0),
  ).toISOString();
  const todayEvents = mock.tradeEvents
    .filter((e) => e.occurred_at >= todayStartIso)
    .sort((a, b) => (b.occurred_at < a.occurred_at ? -1 : 1));

  // ---------- recent notifications ----------
  const recentNotifications = [...mock.notifications]
    .sort((a, b) => (b.created_at < a.created_at ? -1 : 1))
    .slice(0, 5);

  return (
    <>
      <header className="page-header">
        <h1 className="page-header__title">대시보드</h1>
      </header>

      {/* KPI 4 */}
      <Grid narrow style={{ marginBottom: '1.5rem' }}>
        <Column sm={4} md={4} lg={4}>
          <KPITile
            title="추적 종목"
            value={String(trackingCount)}
            subtitle={`박스 대기 ${waitingBoxCount}`}
          />
        </Column>
        <Column sm={4} md={4} lg={4}>
          <KPITile
            title="활성 포지션"
            value={String(activePositions.length)}
            subtitle={`부분청산 ${partialPositionCount}`}
          />
        </Column>
        <Column sm={4} md={4} lg={4}>
          <KPITile
            title="자본 사용"
            value={`${capitalUsedPct.toFixed(1)}%`}
            subtitle={`가용 ${(100 - capitalUsedPct).toFixed(1)}%`}
            progress={capitalUsedPct}
          />
        </Column>
        <Column sm={4} md={4} lg={4}>
          <KPITile
            title="오늘 손익"
            value={`${formatKrwSigned(todayPnl)}원`}
            subtitle={formatPct(todayPnlPct)}
            tone={todayPnl > 0 ? 'profit' : todayPnl < 0 ? 'loss' : 'neutral'}
          />
        </Column>
      </Grid>

      {/* System status */}
      <SystemStatusRow mock={mock} />

      {/* Imminent boxes */}
      <ImminentBoxesTable
        boxes={imminentBoxes}
        trackedStocks={mock.trackedStocks}
        onSelect={(box) => navigate(`/tracked-stocks/${box.tracked_stock_id}`)}
      />

      {/* Active positions */}
      <PositionsTable positions={activePositions} />

      {/* Today's trades */}
      <TodayTradesTable events={todayEvents} />

      {/* Recent notifications */}
      <RecentNotificationsList
        notifications={recentNotifications}
        onSelect={() => navigate('/notifications')}
      />
    </>
  );
}

// ---------------------------------------------------------------------
// Sub-sections
// ---------------------------------------------------------------------

function SystemStatusRow({ mock }: { mock: ReturnType<typeof useLiveMock> }) {
  const ws = mock.systemStatus.websocket.connected;
  const kiwoom = mock.systemStatus.kiwoom_api.available;
  const session = mock.systemStatus.market.is_open ? '장 진행중' : '장 외';
  const now = new Date(mock.systemStatus.current_time);
  const closeIso = mock.systemStatus.market.next_close_at;
  const closeMin = closeIso
    ? Math.max(
        0,
        Math.round((new Date(closeIso).getTime() - now.getTime()) / 60_000),
      )
    : null;
  const closeLabel =
    closeMin != null
      ? `마감까지 ${Math.floor(closeMin / 60)}h ${closeMin % 60}m`
      : '';

  return (
    <Tile
      style={{
        marginBottom: '1.5rem',
        display: 'flex',
        flexWrap: 'wrap',
        gap: '0.75rem',
        alignItems: 'center',
      }}
    >
      <Tag type={mock.systemStatus.status === 'RUNNING' ? 'green' : 'red'}>
        시스템 {mock.systemStatus.status === 'RUNNING' ? '정상' : '안전 모드'}
      </Tag>
      <Tag type={ws ? 'green' : 'red'}>WebSocket {ws ? 'OK' : '끊김'}</Tag>
      <Tag type={kiwoom ? 'green' : 'red'}>키움 API {kiwoom ? 'OK' : '오류'}</Tag>
      <span style={{ flex: 1 }} />
      <Tag type="blue">
        {session} {formatTime(mock.systemStatus.current_time)}
      </Tag>
      {closeLabel ? (
        <span className="cds--type-helper-text-01">{closeLabel}</span>
      ) : null}
    </Tile>
  );
}

function ImminentBoxesTable({
  boxes,
  trackedStocks,
  onSelect,
}: {
  boxes: Box[];
  trackedStocks: TrackedStockWithPrice[];
  onSelect: (box: Box) => void;
}) {
  if (boxes.length === 0) {
    return (
      <Tile
        style={{ marginBottom: '1.5rem', padding: '1.5rem', textAlign: 'center' }}
      >
        <p className="cds--type-helper-text-01">진입 임박 박스가 없습니다.</p>
      </Tile>
    );
  }

  const headers = [
    { key: 'stock', header: '종목' },
    { key: 'currentPrice', header: '현재가' },
    { key: 'box', header: '박스' },
    { key: 'distance', header: '거리' },
    { key: 'size', header: '비중' },
  ];

  const rows = boxes.map((box) => {
    const stock = trackedStocks.find((s) => s.id === box.tracked_stock_id);
    const proximity = box.entry_proximity_pct ?? 0;
    return {
      id: box.id,
      _box: box,
      stock: `${box.stock_name} (${box.stock_code})`,
      currentPrice: stock ? formatKrw(stock.current_price) + '원' : '-',
      box: `${formatKrw(box.lower_price)} ~ ${formatKrw(box.upper_price)}`,
      distance: (
        <span className={proximity >= 0 ? 'pnl-profit' : 'pnl-loss'}>
          {formatPct(proximity)}
        </span>
      ),
      size: formatPctRaw(box.position_size_pct),
    };
  });

  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <DataTable rows={rows} headers={headers}>
        {({ rows: r, headers: h, getHeaderProps, getRowProps, getTableProps }) => (
          <TableContainer
            title="진입 임박 박스"
            description={`${boxes.length}개 -- 클릭 시 종목 상세`}
          >
            <Table {...getTableProps()}>
              <TableHead>
                <TableRow>
                  {h.map((header) => (
                    // eslint-disable-next-line react/jsx-key -- key is on getHeaderProps
                    <TableHeader {...getHeaderProps({ header })}>
                      {header.header}
                    </TableHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {r.map((row) => {
                  const original = rows.find((rw) => rw.id === row.id);
                  return (
                    <TableRow
                      {...getRowProps({ row })}
                      onClick={() => original && onSelect(original._box)}
                      style={{ cursor: 'pointer' }}
                    >
                      {row.cells.map((cell) => (
                        <TableCell key={cell.id}>{cell.value}</TableCell>
                      ))}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DataTable>
    </div>
  );
}

function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <Tile
        style={{ marginBottom: '1.5rem', padding: '1.5rem', textAlign: 'center' }}
      >
        <p className="cds--type-helper-text-01">활성 포지션이 없습니다.</p>
      </Tile>
    );
  }

  const headers = [
    { key: 'stock', header: '종목' },
    { key: 'source', header: '경로' },
    { key: 'qty', header: '수량' },
    { key: 'avg', header: '평단가' },
    { key: 'price', header: '현재가' },
    { key: 'pnl', header: '손익' },
    { key: 'stop', header: '손절선' },
    { key: 'status', header: '상태' },
  ];

  const rows = positions.map((p) => ({
    id: p.id,
    stock: `${p.stock_name} (${p.stock_code})`,
    source: <PositionSourceTag source={p.source} />,
    qty: `${p.total_quantity.toLocaleString('ko-KR')}주`,
    avg: formatKrw(p.weighted_avg_price) + '원',
    price: formatKrw(p.current_price) + '원',
    pnl: <PnLCell amount={p.pnl_amount} pct={p.pnl_pct} layout="stacked" />,
    stop: formatKrw(p.fixed_stop_price) + '원',
    status: <PositionStatusTag status={p.status} />,
  }));

  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <DataTable rows={rows} headers={headers}>
        {({ rows: r, headers: h, getHeaderProps, getRowProps, getTableProps }) => (
          <TableContainer
            title="활성 포지션"
            description={`${positions.length}건 -- 실시간 가격 (2초 간격)`}
          >
            <Table {...getTableProps()}>
              <TableHead>
                <TableRow>
                  {h.map((header) => (
                    <TableHeader {...getHeaderProps({ header })}>
                      {header.header}
                    </TableHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {r.map((row) => (
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
  );
}

function TodayTradesTable({ events }: { events: TradeEvent[] }) {
  if (events.length === 0) {
    return (
      <Tile
        style={{ marginBottom: '1.5rem', padding: '1.5rem', textAlign: 'center' }}
      >
        <p className="cds--type-helper-text-01">오늘 거래 내역이 없습니다.</p>
      </Tile>
    );
  }

  const headers = [
    { key: 'time', header: '시간' },
    { key: 'kind', header: '구분' },
    { key: 'stock', header: '종목' },
    { key: 'qty', header: '수량' },
    { key: 'price', header: '가격' },
  ];

  const rows = events.slice(0, 10).map((e) => ({
    id: e.id,
    time: formatTime(e.occurred_at),
    kind: e.event_type,
    stock: e.stock_code,
    qty: `${e.quantity}주`,
    price: formatKrw(e.price) + '원',
  }));

  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <DataTable rows={rows} headers={headers}>
        {({ rows: r, headers: h, getHeaderProps, getRowProps, getTableProps }) => (
          <TableContainer title="오늘 거래" description={`${events.length}건`}>
            <Table {...getTableProps()}>
              <TableHead>
                <TableRow>
                  {h.map((header) => (
                    <TableHeader {...getHeaderProps({ header })}>
                      {header.header}
                    </TableHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {r.map((row) => (
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
  );
}

function RecentNotificationsList({
  notifications,
  onSelect,
}: {
  notifications: NotificationRecord[];
  onSelect: () => void;
}) {
  return (
    <Tile style={{ padding: '1rem' }}>
      <h3
        style={{
          fontSize: '1.125rem',
          fontWeight: 400,
          marginTop: 0,
          marginBottom: '0.75rem',
        }}
      >
        최근 알림
      </h3>
      <StructuredListWrapper isCondensed>
        <StructuredListBody>
          {notifications.map((n) => (
            <StructuredListRow
              key={n.id}
              onClick={onSelect}
              style={{ cursor: 'pointer' }}
            >
              <StructuredListCell style={{ width: '8rem' }}>
                <SeverityTag severity={n.severity} />
              </StructuredListCell>
              <StructuredListCell>
                <strong>{n.title}</strong>
                <div className="cds--type-helper-text-01">{n.message}</div>
              </StructuredListCell>
              <StructuredListCell style={{ width: '6rem', textAlign: 'right' }}>
                {formatTime(n.created_at)}
              </StructuredListCell>
            </StructuredListRow>
          ))}
        </StructuredListBody>
      </StructuredListWrapper>
    </Tile>
  );
}

// Suppress lint for unused TrackedStatusTag (used by other pages later).
void TrackedStatusTag;
void BoxStatusTag;
