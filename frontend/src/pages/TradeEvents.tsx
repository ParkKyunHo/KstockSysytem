// V7.1 TradeEvents -- wired to /api/v71/trade_events (PRD §6.1).
// Vertical timeline + table view of executions and system events.

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type { PositionOut } from '@/api/positions';
import type { TrackedStockOut } from '@/api/trackedStocks';
import type { TradeEventOut } from '@/api/tradeEvents';
import { I, type IconComponent } from '@/components/icons';
import {
  Btn,
  Dropdown,
  Tag,
  type TagType,
  ToastContainer,
  useToasts,
} from '@/components/ui';
import {
  usePositions,
  useTrackedStocks,
  useTradeEvents,
} from '@/hooks/useApi';
import {
  formatDateTime,
  formatKrw,
  formatKrwSigned,
  formatTimeSeconds,
} from '@/lib/formatters';

// ---------------------------------------------------------------------
// Event taxonomy
// ---------------------------------------------------------------------

type Category = 'buy' | 'profit' | 'loss' | 'ts' | 'system';

interface EventMeta {
  cat: Category;
  label: string;
  icon: IconComponent;
  tag: TagType;
}

const EVENT_META: Record<string, EventMeta> = {
  BUY_EXECUTED: { cat: 'buy', label: '매수 체결', icon: I.ArrowDown, tag: 'blue' },
  PYRAMID_BUY: {
    cat: 'buy',
    label: '추가매수',
    icon: I.ArrowDown,
    tag: 'blue',
  },
  MANUAL_PYRAMID_BUY: {
    cat: 'buy',
    label: '수동 추가매수',
    icon: I.ArrowDown,
    tag: 'cyan',
  },
  PROFIT_TAKE_5: {
    cat: 'profit',
    label: '+5% 청산',
    icon: I.ArrowUp,
    tag: 'green',
  },
  PROFIT_TAKE_10: {
    cat: 'profit',
    label: '+10% 청산',
    icon: I.ArrowUp,
    tag: 'green',
  },
  MANUAL_SELL: {
    cat: 'profit',
    label: '수동 매도',
    icon: I.ArrowUp,
    tag: 'cyan',
  },
  TS_ACTIVATED: {
    cat: 'ts',
    label: '트레일링 활성',
    icon: I.Lock,
    tag: 'purple',
  },
  TS_EXIT: { cat: 'ts', label: 'TS 청산', icon: I.ArrowUp, tag: 'purple' },
  STOP_LOSS: { cat: 'loss', label: '손절', icon: I.ArrowUp, tag: 'red' },
  BUY_REJECTED: {
    cat: 'system',
    label: '매수 거부',
    icon: I.Close,
    tag: 'cool-gray',
  },
  POSITION_CLOSED: {
    cat: 'system',
    label: '포지션 종료',
    icon: I.View,
    tag: 'cool-gray',
  },
};

const CAT_LABEL: Record<Category, string> = {
  buy: '매수',
  profit: '수익실현',
  loss: '손절',
  ts: '트레일링',
  system: '시스템',
};
const CAT_ORDER: Category[] = ['buy', 'profit', 'ts', 'loss', 'system'];

type Source = 'AUTO' | 'MANUAL' | 'SYSTEM';

const sourceOf = (eventType: string): Source => {
  if (eventType.startsWith('MANUAL_')) return 'MANUAL';
  if (
    eventType === 'BUY_REJECTED' ||
    eventType === 'POSITION_CLOSED' ||
    eventType === 'TS_ACTIVATED'
  )
    return 'SYSTEM';
  return 'AUTO';
};

const SRC_LABEL: Record<Source, string> = {
  AUTO: '자동',
  MANUAL: '수동',
  SYSTEM: '시스템',
};

interface EnrichedEvent {
  raw: TradeEventOut;
  meta: EventMeta;
  pos?: PositionOut;
  stock?: TrackedStockOut;
  source: Source;
  amount: number;
  quantity: number;
  price: number;
}

const FALLBACK_META: EventMeta = {
  cat: 'system',
  label: 'EVENT',
  icon: I.View,
  tag: 'gray',
};

// ---------------------------------------------------------------------
// Day grouping
// ---------------------------------------------------------------------

interface DayGroup {
  key: string;
  date: Date;
  items: EnrichedEvent[];
}

function groupByDay(events: EnrichedEvent[]): DayGroup[] {
  const map = new Map<string, DayGroup>();
  events.forEach((e) => {
    const d = new Date(e.raw.occurred_at);
    const key = d.toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
    if (!map.has(key)) map.set(key, { key, date: d, items: [] });
    map.get(key)!.items.push(e);
  });
  return Array.from(map.values()).sort(
    (a, b) => b.date.getTime() - a.date.getTime(),
  );
}

function dayHeading(d: Date): string {
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  const isYday =
    d.toDateString() ===
    new Date(today.getTime() - 86_400_000).toDateString();
  const datePart = d.toLocaleDateString('ko-KR', {
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  });
  if (isToday) return `오늘 · ${datePart}`;
  if (isYday) return `어제 · ${datePart}`;
  return datePart;
}

// ---------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------

type View = 'timeline' | 'table';
type CatFilter = 'all' | Category;
type SourceFilter = 'all' | Source;
type RangeFilter = '24h' | '7d' | '30d' | 'all';

export function TradeEvents() {
  const navigate = useNavigate();
  const { toasts, addToast, closeToast } = useToasts();

  const [view, setView] = useState<View>('timeline');
  const [catFilter, setCatFilter] = useState<CatFilter>('all');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [stockFilter, setStockFilter] = useState<string>('all');
  const [range, setRange] = useState<RangeFilter>('7d');

  // Derive a server-side `from_date` from the current range filter so we
  // do not pull the entire history when only the last 24h is needed.
  const fromDate = useMemo(() => {
    if (range === 'all') return undefined;
    const horizons: Record<Exclude<RangeFilter, 'all'>, number> = {
      '24h': 86_400_000,
      '7d': 7 * 86_400_000,
      '30d': 30 * 86_400_000,
    };
    return new Date(Date.now() - horizons[range]).toISOString().slice(0, 10);
  }, [range]);

  const { data: list, isLoading } = useTradeEvents({
    limit: 500,
    from_date: fromDate,
  });
  const { data: positionList } = usePositions({ limit: 500 });
  const { data: trackedList } = useTrackedStocks({ limit: 500 });

  const positions = positionList?.data ?? [];
  const trackedStocks = trackedList?.data ?? [];
  const events = list?.data ?? [];

  const enriched: EnrichedEvent[] = useMemo(
    () =>
      events.map((e): EnrichedEvent => {
        const meta = EVENT_META[e.event_type] ?? FALLBACK_META;
        const pos = e.position_id
          ? positions.find((p) => p.id === e.position_id)
          : undefined;
        const stock = trackedStocks.find(
          (s) => s.stock_code === e.stock_code,
        );
        const quantity = e.quantity ?? 0;
        const price = e.price ?? 0;
        return {
          raw: e,
          meta,
          pos,
          stock,
          source: sourceOf(e.event_type),
          amount: quantity * price,
          quantity,
          price,
        };
      }),
    [events, positions, trackedStocks],
  );

  const filtered = useMemo(() => {
    return enriched
      .filter((e) => {
        if (catFilter !== 'all' && e.meta.cat !== catFilter) return false;
        if (sourceFilter !== 'all' && e.source !== sourceFilter) return false;
        if (stockFilter !== 'all' && e.raw.stock_code !== stockFilter)
          return false;
        return true;
      })
      .sort(
        (a, b) =>
          new Date(b.raw.occurred_at).getTime() -
          new Date(a.raw.occurred_at).getTime(),
      );
  }, [enriched, catFilter, sourceFilter, stockFilter]);

  const kpi = useMemo(() => {
    let buyVol = 0;
    let sellVol = 0;
    let realized = 0;
    filtered.forEach((e) => {
      if (e.meta.cat === 'buy') buyVol += e.amount;
      if (
        e.meta.cat === 'profit' ||
        e.meta.cat === 'ts' ||
        e.meta.cat === 'loss'
      )
        sellVol += e.amount;
      if (e.raw.pnl_amount != null) {
        realized += e.raw.pnl_amount;
      } else if (
        ['profit', 'ts', 'loss'].includes(e.meta.cat) &&
        e.pos &&
        e.quantity > 0
      ) {
        realized += (e.price - e.pos.weighted_avg_price) * e.quantity;
      }
    });
    return {
      total: filtered.length,
      buys: filtered.filter((e) => e.meta.cat === 'buy').length,
      sells: filtered.filter((e) =>
        ['profit', 'ts', 'loss'].includes(e.meta.cat),
      ).length,
      buyVol,
      sellVol,
      realized,
    };
  }, [filtered]);

  const stockOpts = useMemo(() => {
    const codes = Array.from(new Set(events.map((e) => e.stock_code)));
    return [
      { value: 'all', label: '종목: 전체' },
      ...codes.map((c) => {
        const s = trackedStocks.find((x) => x.stock_code === c);
        return { value: c, label: `${s ? s.stock_name : c} (${c})` };
      }),
    ];
  }, [events, trackedStocks]);

  const catCounts = useMemo(() => {
    const base: Record<CatFilter, number> = {
      all: enriched.length,
      buy: 0,
      profit: 0,
      loss: 0,
      ts: 0,
      system: 0,
    };
    CAT_ORDER.forEach((c) => {
      base[c] = enriched.filter((e) => e.meta.cat === c).length;
    });
    return base;
  }, [enriched]);

  const exportCsv = () => {
    addToast({
      kind: 'success',
      title: 'CSV 내보내기 완료',
      subtitle: `${filtered.length}건 다운로드`,
    });
  };

  const onStockNav = (stockId: string) => navigate(`/tracked-stocks/${stockId}`);

  return (
    <div>
      {/* Header */}
      <div className="page-hd">
        <div>
          <h1 className="page-hd__title">거래 이벤트</h1>
          <div className="page-hd__subtitle">
            전체 {enriched.length}건 · 표시 {filtered.length}건 · 자동{' '}
            {enriched.filter((e) => e.source === 'AUTO').length}건 / 수동{' '}
            {enriched.filter((e) => e.source === 'MANUAL').length}건
          </div>
        </div>
        <div className="page-hd__actions">
          <Btn
            kind="tertiary"
            size="sm"
            icon={I.Download}
            onClick={exportCsv}
          >
            CSV
          </Btn>
          <Btn
            kind="tertiary"
            size="sm"
            icon={I.Renew}
            onClick={() =>
              addToast({ kind: 'info', title: '이벤트 동기화' })
            }
          >
            동기화
          </Btn>
        </div>
      </div>

      {/* KPI strip */}
      <div className="tev-kpi">
        <KpiCell
          label="체결 이벤트"
          value={kpi.total}
          sub={`매수 ${kpi.buys} · 매도 ${kpi.sells}`}
        />
        <KpiCell
          label="매수 금액"
          value={formatKrw(kpi.buyVol)}
          sub="원"
          mono
          accent="blue"
        />
        <KpiCell
          label="매도 금액"
          value={formatKrw(kpi.sellVol)}
          sub="원"
          mono
          accent="green"
        />
        <KpiCell
          label="실현 손익(추정)"
          value={formatKrwSigned(kpi.realized)}
          sub="원"
          mono
          accent={kpi.realized >= 0 ? 'green' : 'red'}
        />
      </div>

      {/* Filter bar */}
      <div className="tev-filter">
        <div className="tev-chips">
          {(['all', ...CAT_ORDER] as CatFilter[]).map((c) => (
            <Chip
              key={c}
              active={catFilter === c}
              onClick={() => setCatFilter(c)}
              dotCat={c === 'all' ? null : c}
            >
              {c === 'all' ? '전체' : CAT_LABEL[c]}
              <span className="tev-chip__count">{catCounts[c] || 0}</span>
            </Chip>
          ))}
        </div>

        <div className="tev-filter__rhs">
          <div
            className="tev-segmented"
            role="tablist"
            aria-label="기간"
          >
            {(
              [
                ['24h', '24h'],
                ['7d', '7일'],
                ['30d', '30일'],
                ['all', '전체'],
              ] as Array<[RangeFilter, string]>
            ).map(([v, l]) => (
              <button
                key={v}
                type="button"
                className={`tev-seg${range === v ? ' is-active' : ''}`}
                onClick={() => setRange(v)}
              >
                {l}
              </button>
            ))}
          </div>
          <Dropdown<SourceFilter>
            value={sourceFilter}
            onChange={setSourceFilter}
            options={[
              { value: 'all', label: '소스: 전체' },
              { value: 'AUTO', label: '시스템 자동' },
              { value: 'MANUAL', label: '수동' },
              { value: 'SYSTEM', label: '내부 이벤트' },
            ]}
          />
          <Dropdown<string>
            value={stockFilter}
            onChange={setStockFilter}
            options={stockOpts}
          />
          <div className="tev-segmented">
            <button
              type="button"
              className={`tev-seg${view === 'timeline' ? ' is-active' : ''}`}
              onClick={() => setView('timeline')}
              aria-label="타임라인"
            >
              타임라인
            </button>
            <button
              type="button"
              className={`tev-seg${view === 'table' ? ' is-active' : ''}`}
              onClick={() => setView('table')}
              aria-label="테이블"
            >
              테이블
            </button>
          </div>
        </div>
      </div>

      {/* Body */}
      {isLoading ? (
        <div
          className="cds-tile"
          style={{ padding: 48, textAlign: 'center', marginTop: 16 }}
        >
          <p className="text-helper" style={{ margin: 0 }}>
            이벤트 불러오는 중…
          </p>
        </div>
      ) : filtered.length === 0 ? (
        <div
          className="cds-tile"
          style={{ padding: 48, textAlign: 'center', marginTop: 16 }}
        >
          <p className="text-helper" style={{ margin: 0 }}>
            조건에 해당하는 이벤트가 없습니다.
          </p>
        </div>
      ) : view === 'timeline' ? (
        <Timeline groups={groupByDay(filtered)} onNav={onStockNav} />
      ) : (
        <EventTable items={filtered} onNav={onStockNav} />
      )}

      <ToastContainer toasts={toasts} onClose={closeToast} />
    </div>
  );
}

// ---------------------------------------------------------------------
// KPI cell
// ---------------------------------------------------------------------

type KpiAccent = 'blue' | 'green' | 'red';

function KpiCell({
  label,
  value,
  sub,
  mono,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  mono?: boolean;
  accent?: KpiAccent;
}) {
  return (
    <div
      className={`tev-kpi__cell${accent ? ` tev-kpi__cell--${accent}` : ''}`}
    >
      <div className="tev-kpi__label">{label}</div>
      <div className={`tev-kpi__val${mono ? ' mono' : ''}`}>{value}</div>
      {sub ? <div className="tev-kpi__sub mono">{sub}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------
// Chip
// ---------------------------------------------------------------------

function Chip({
  active,
  onClick,
  dotCat,
  children,
}: {
  active: boolean;
  onClick: () => void;
  dotCat: Category | null;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`tev-chip${active ? ' is-active' : ''}`}
      onClick={onClick}
    >
      {dotCat ? <span className={`tev-dot tev-dot--${dotCat}`} /> : null}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------
// Timeline view
// ---------------------------------------------------------------------

function Timeline({
  groups,
  onNav,
}: {
  groups: DayGroup[];
  onNav: (stockId: string) => void;
}) {
  return (
    <div className="tev-timeline">
      {groups.map((g) => (
        <section key={g.key} className="tev-tl-day">
          <div className="tev-tl-day__hd">
            <span className="tev-tl-day__title">{dayHeading(g.date)}</span>
            <span className="tev-tl-day__count mono text-helper">
              {g.items.length}건
            </span>
          </div>
          <div className="tev-tl-list">
            {g.items.map((e) => (
              <TimelineRow key={e.raw.id} e={e} onNav={onNav} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function TimelineRow({
  e,
  onNav,
}: {
  e: EnrichedEvent;
  onNav: (stockId: string) => void;
}) {
  const Icon = e.meta.icon;
  const hasQty = e.quantity > 0;
  const stockName = e.stock ? e.stock.stock_name : e.raw.stock_code;
  const sourceLabel = SRC_LABEL[e.source];

  let zeroQtyNote: string | null = null;
  if (!hasQty) {
    if (e.raw.event_type === 'TS_ACTIVATED')
      zeroQtyNote = `기준가 ${formatKrw(e.price)}원 — 트레일링 스탑 추적 시작`;
    else if (e.raw.event_type === 'BUY_REJECTED')
      zeroQtyNote = `참조가 ${formatKrw(e.price)}원 — 갭업 차단 / 비중 초과`;
    else if (e.raw.event_type === 'POSITION_CLOSED')
      zeroQtyNote = `청산가 ${formatKrw(e.price)}원 — 전량 매도 완료`;
    else zeroQtyNote = `${formatKrw(e.price)}원`;
  }

  return (
    <article className="tev-tl-row">
      <div className="tev-tl-row__gutter">
        <time className="tev-tl-row__time mono">
          {formatTimeSeconds(e.raw.occurred_at)}
        </time>
        <span className="tev-tl-row__axis">
          <span className={`tev-tl-dot tev-dot--${e.meta.cat}`}>
            <Icon size={12} />
          </span>
        </span>
      </div>

      <div
        className="tev-tl-row__card"
        onClick={() => e.stock && onNav(e.stock.id)}
      >
        <header className="tev-tl-row__hd">
          <Tag type={e.meta.tag} size="sm">
            {e.meta.label}
          </Tag>
          <span className="tev-tl-row__stock">
            <strong>{stockName}</strong>
            <span className="mono text-helper">{e.raw.stock_code}</span>
          </span>
          <span
            className={`tev-tl-row__src tev-src--${e.source.toLowerCase()}`}
          >
            {sourceLabel}
          </span>
        </header>

        <div className="tev-tl-row__body">
          {hasQty ? (
            <>
              <span className="tev-tl-row__qty mono">{e.quantity}주</span>
              <span className="tev-tl-row__sep">×</span>
              <span className="tev-tl-row__price mono">
                {formatKrw(e.price)}원
              </span>
              <span className="tev-tl-row__sep">=</span>
              <span
                className={`tev-tl-row__amt mono${e.meta.cat === 'buy' ? '' : ' is-credit'}`}
              >
                {e.meta.cat === 'buy' ? '−' : '+'}
                {formatKrw(e.amount)}원
              </span>
            </>
          ) : (
            <span className="tev-tl-row__note text-helper">
              {zeroQtyNote}
            </span>
          )}
        </div>

        {e.pos ? (
          <footer className="tev-tl-row__ft text-helper">
            포지션 <span className="mono">{e.pos.id}</span> · 평단{' '}
            <span className="mono">
              {formatKrw(e.pos.weighted_avg_price)}원
            </span>{' '}
            · 보유 <span className="mono">{e.pos.total_quantity}주</span>
          </footer>
        ) : null}
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------
// Table view
// ---------------------------------------------------------------------

function EventTable({
  items,
  onNav,
}: {
  items: EnrichedEvent[];
  onNav: (stockId: string) => void;
}) {
  return (
    <div className="cds-data-table" style={{ marginTop: 16 }}>
      <div className="table-wrap">
        <table className="cds-table cds-table--compact">
          <thead>
            <tr>
              <th>시각</th>
              <th>이벤트</th>
              <th>종목</th>
              <th style={{ textAlign: 'right' }}>수량</th>
              <th style={{ textAlign: 'right' }}>가격</th>
              <th style={{ textAlign: 'right' }}>체결금액</th>
              <th>소스</th>
              <th>포지션</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.raw.id}>
                <td className="mono">{formatDateTime(e.raw.occurred_at)}</td>
                <td>
                  <span className="tev-row-marker">
                    <span
                      className={`tev-dot tev-dot--${e.meta.cat}`}
                      style={{ width: 8, height: 8 }}
                    />
                    <Tag type={e.meta.tag} size="sm">
                      {e.meta.label}
                    </Tag>
                  </span>
                </td>
                <td>
                  {e.stock ? (
                    <a
                      className="cds-link"
                      onClick={() => onNav(e.stock!.id)}
                    >
                      {e.stock.stock_name}{' '}
                      <span className="mono text-helper">
                        {e.raw.stock_code}
                      </span>
                    </a>
                  ) : (
                    <span className="mono">{e.raw.stock_code}</span>
                  )}
                </td>
                <td className="price">
                  {e.quantity > 0 ? e.quantity : '—'}
                </td>
                <td className="price">{formatKrw(e.price)}</td>
                <td className="price">
                  {e.quantity > 0 ? formatKrw(e.amount) : '—'}
                </td>
                <td>
                  <span
                    className={`tev-src tev-src--${e.source.toLowerCase()}`}
                  >
                    {SRC_LABEL[e.source]}
                  </span>
                </td>
                <td className="mono text-helper">
                  {e.pos ? e.pos.id : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
