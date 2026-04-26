import type { TrackedStock, TrackedStockSummary } from '@/types';
import { isoMinusDay, isoMinusHour, isoMinusMin } from '@/lib/time';
import { mockBoxes } from './boxes';

// Live current price (mutated by useLiveMock).
export interface TrackedStockWithPrice extends TrackedStock {
  current_price: number;
}

const trackedStockSeeds: Array<
  Omit<TrackedStock, 'summary'> & { current_price: number }
> = [
  {
    id: 'ts-001',
    stock_code: '005930',
    stock_name: '삼성전자',
    market: 'KOSPI',
    status: 'BOX_SET',
    user_memo: '반도체 사이클 회복 기대',
    source: 'HTS',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(1),
    last_status_changed_at: isoMinusHour(2),
    current_price: 73500,
  },
  {
    id: 'ts-002',
    stock_code: '036040',
    stock_name: '에프알텍',
    market: 'KOSDAQ',
    status: 'POSITION_OPEN',
    user_memo: null,
    source: '뉴스',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(4),
    last_status_changed_at: isoMinusHour(5),
    current_price: 18420,
  },
  {
    id: 'ts-003',
    stock_code: '000660',
    stock_name: 'SK하이닉스',
    market: 'KOSPI',
    status: 'POSITION_PARTIAL',
    user_memo: 'HBM 공급 수혜',
    source: '리포트',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(8),
    last_status_changed_at: isoMinusHour(1),
    current_price: 226000,
  },
  {
    id: 'ts-004',
    stock_code: '267260',
    stock_name: 'HD현대일렉트릭',
    market: 'KOSPI',
    status: 'TRACKING',
    user_memo: null,
    source: '직접 분석',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(2),
    last_status_changed_at: isoMinusDay(2),
    current_price: 412000,
  },
  {
    id: 'ts-005',
    stock_code: '042660',
    stock_name: '한화오션',
    market: 'KOSPI',
    status: 'BOX_SET',
    user_memo: '조선 슈퍼사이클',
    source: 'HTS',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(3),
    last_status_changed_at: isoMinusHour(8),
    current_price: 76800,
  },
  {
    id: 'ts-006',
    stock_code: '035420',
    stock_name: 'NAVER',
    market: 'KOSPI',
    status: 'POSITION_OPEN',
    user_memo: null,
    source: '뉴스',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(11),
    last_status_changed_at: isoMinusHour(20),
    current_price: 198200,
  },
  {
    id: 'ts-007',
    stock_code: '247540',
    stock_name: '에코프로비엠',
    market: 'KOSDAQ',
    status: 'BOX_SET',
    user_memo: null,
    source: 'HTS',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(5),
    last_status_changed_at: isoMinusHour(15),
    current_price: 124500,
  },
  {
    id: 'ts-008',
    stock_code: '012450',
    stock_name: '한화에어로스페이스',
    market: 'KOSPI',
    status: 'TRACKING',
    user_memo: 'K2 수출 확정',
    source: '리포트',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(1),
    last_status_changed_at: isoMinusDay(1),
    current_price: 358000,
  },
  {
    id: 'ts-009',
    stock_code: '009540',
    stock_name: 'HD한국조선해양',
    market: 'KOSPI',
    status: 'POSITION_OPEN',
    user_memo: null,
    source: 'HTS',
    vi_recovered_today: true,
    auto_exit_reason: null,
    created_at: isoMinusDay(6),
    last_status_changed_at: isoMinusMin(35),
    current_price: 215500,
  },
  {
    id: 'ts-010',
    stock_code: '326030',
    stock_name: 'SK바이오팜',
    market: 'KOSPI',
    status: 'EXITED',
    user_memo: null,
    source: '뉴스',
    vi_recovered_today: false,
    auto_exit_reason: '거래량 급감 (5일 연속)',
    created_at: isoMinusDay(20),
    last_status_changed_at: isoMinusDay(2),
    current_price: 92800,
  },
  {
    id: 'ts-011',
    stock_code: '293490',
    stock_name: '카카오게임즈',
    market: 'KOSDAQ',
    status: 'BOX_SET',
    user_memo: null,
    source: '직접 분석',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusDay(7),
    last_status_changed_at: isoMinusHour(12),
    current_price: 18900,
  },
  {
    id: 'ts-012',
    stock_code: '034020',
    stock_name: '두산에너빌리티',
    market: 'KOSPI',
    status: 'TRACKING',
    user_memo: 'SMR 모멘텀',
    source: 'HTS',
    vi_recovered_today: false,
    auto_exit_reason: null,
    created_at: isoMinusHour(12),
    last_status_changed_at: isoMinusMin(45),
    current_price: 24850,
  },
];

// Build per-stock summary using boxes (PRD Patch #3 -- path counts).
function buildSummary(
  trackedStockId: string,
  positionQty: number,
  positionAvg: number | null,
): TrackedStockSummary {
  const stockBoxes = mockBoxes.filter(
    (b) => b.tracked_stock_id === trackedStockId,
  );
  const active = stockBoxes.filter((b) => b.status === 'WAITING');
  const triggered = stockBoxes.filter((b) => b.status === 'TRIGGERED');
  const pathACount = active.filter((b) => b.path_type === 'PATH_A').length;
  const pathBCount = active.filter((b) => b.path_type === 'PATH_B').length;

  return {
    active_box_count: active.length,
    triggered_box_count: triggered.length,
    path_a_box_count: pathACount,
    path_b_box_count: pathBCount,
    current_position_qty: positionQty,
    current_position_avg_price: positionAvg,
  };
}

// Position quantities are mirrored from positions.ts to keep the
// summary self-consistent; in production a single API populates both.
const positionInfoById: Record<string, { qty: number; avg: number }> = {
  'ts-002': { qty: 100, avg: 18100 },
  'ts-003': { qty: 30, avg: 218500 },
  'ts-006': { qty: 50, avg: 195500 },
  'ts-007': { qty: 25, avg: 122000 },
  'ts-009': { qty: 20, avg: 218000 },
};

export const mockTrackedStocks: TrackedStockWithPrice[] = trackedStockSeeds.map(
  (seed) => {
    const pos = positionInfoById[seed.id];
    return {
      ...seed,
      summary: buildSummary(seed.id, pos?.qty ?? 0, pos?.avg ?? null),
    };
  },
);
