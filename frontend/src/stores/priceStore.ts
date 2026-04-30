// V7.1 Zustand price store -- WS POSITION_PRICE_UPDATE → state.
//
// Backend V71PricePublisher (P-Wire-Price-Tick) publishes:
//   { type: "POSITION_PRICE_UPDATE", channel: "positions",
//     data: { position_id, stock_code, current_price, pnl_amount,
//             pnl_pct, timestamp } }
//
// Architect Q5 + Q6 (architect verification, 2026-04-30):
//   - Zustand selective subscribe → re-render isolation
//   - Dual key: stock_code (for Dashboard's "진입 임박 박스" + price-only
//     consumers) + position_id (sibling positions on the same stock get
//     distinct pnl_amount/pnl_pct)
//
// Q7 fallback strategy:
//   - WS push 우선: store value (가장 신선)
//   - WS 끊김: store 마지막 값 + useStaleStatus() 표시
//   - 페이지 새로고침: PositionOut.current_price (DB Patch #5)로 hydrate
//   - dev: VITE_USE_LIVE_MOCK=true 시 useLiveMock 활성 (priceStore도 동작
//     하나, mock vs real 충돌은 useLiveMock 호출 측에서 가드)

import { create } from 'zustand';

export interface StockPriceData {
  /** 현재가 (KRW). null = 아직 받지 못함. */
  price: number | null;
  /** 마지막 갱신 시각 (ISO 8601, KST aware). */
  lastUpdatedAt: string | null;
}

export interface PositionPnlData {
  stock_code: string;
  /** 손익 금액 (KRW). null = 아직 계산 전. */
  pnlAmount: number | null;
  /** 손익률 (배수, 예: 0.05 = +5%). null = 아직 계산 전. */
  pnlPct: number | null;
  lastUpdatedAt: string | null;
}

interface PriceStoreState {
  byStockCode: Map<string, StockPriceData>;
  byPositionId: Map<string, PositionPnlData>;

  /** WS POSITION_PRICE_UPDATE 메시지로 갱신. */
  applyPriceUpdate: (update: PriceUpdatePayload) => void;

  /** REST GET /positions 결과로 hydrate (페이지 새로고침 fallback). */
  hydrateFromPositions: (positions: HydrateInput[]) => void;

  /** 포지션 close / 로그아웃 시 정리. */
  removePosition: (positionId: string) => void;

  /** 모든 상태 리셋 (로그아웃). */
  clear: () => void;
}

export interface PriceUpdatePayload {
  position_id: string;
  stock_code: string;
  current_price: number;
  pnl_amount: number;
  pnl_pct: number;
  /** Backend가 V71Position.current_price_at 으로 채움. */
  timestamp?: string;
}

export interface HydrateInput {
  id: string;
  stock_code: string;
  current_price: number | null;
  current_price_at: string | null;
  pnl_amount: number | null;
  pnl_pct: number | null;
}

export const usePriceStore = create<PriceStoreState>((set) => ({
  byStockCode: new Map(),
  byPositionId: new Map(),

  applyPriceUpdate: (update) =>
    set((state) => {
      // Map은 React state로 직접 mutate 불가 — 새 Map 만들어 교체.
      const nextStock = new Map(state.byStockCode);
      const nextPos = new Map(state.byPositionId);
      const ts = update.timestamp ?? new Date().toISOString();
      // Timestamp idempotency: stale push가 fresh state를 덮지 않도록
      // (backend test-strategy 회귀 #5 mirror — backend WHERE
      // current_price_at < :new_at 가드와 짝).
      const existing = nextStock.get(update.stock_code);
      if (existing?.lastUpdatedAt && existing.lastUpdatedAt > ts) {
        return state;
      }
      nextStock.set(update.stock_code, {
        price: update.current_price,
        lastUpdatedAt: ts,
      });
      nextPos.set(update.position_id, {
        stock_code: update.stock_code,
        pnlAmount: update.pnl_amount,
        pnlPct: update.pnl_pct,
        lastUpdatedAt: ts,
      });
      return { byStockCode: nextStock, byPositionId: nextPos };
    }),

  hydrateFromPositions: (positions) =>
    set((state) => {
      const nextStock = new Map(state.byStockCode);
      const nextPos = new Map(state.byPositionId);
      for (const p of positions) {
        if (p.current_price == null) continue;
        const existing = nextStock.get(p.stock_code);
        // Hydrate는 REST 응답이라 WS 보다 보수적 — store에 더 신선한
        // 값이 이미 있으면 덮지 않음.
        if (
          existing?.lastUpdatedAt &&
          p.current_price_at &&
          existing.lastUpdatedAt >= p.current_price_at
        ) {
          continue;
        }
        nextStock.set(p.stock_code, {
          price: p.current_price,
          lastUpdatedAt: p.current_price_at,
        });
        if (p.pnl_amount != null && p.pnl_pct != null) {
          nextPos.set(p.id, {
            stock_code: p.stock_code,
            pnlAmount: p.pnl_amount,
            pnlPct: p.pnl_pct,
            lastUpdatedAt: p.current_price_at,
          });
        }
      }
      return { byStockCode: nextStock, byPositionId: nextPos };
    }),

  removePosition: (positionId) =>
    set((state) => {
      if (!state.byPositionId.has(positionId)) return state;
      const next = new Map(state.byPositionId);
      next.delete(positionId);
      return { byPositionId: next };
    }),

  clear: () =>
    set({
      byStockCode: new Map(),
      byPositionId: new Map(),
    }),
}));

// ---------------------------------------------------------------------
// Selectors (React hooks)
// ---------------------------------------------------------------------

/** 종목 현재가 lookup. byStockCode 변경 시에만 re-render. */
export function usePriceByStock(stockCode: string): StockPriceData {
  return (
    usePriceStore((s) => s.byStockCode.get(stockCode)) ?? {
      price: null,
      lastUpdatedAt: null,
    }
  );
}

/** 포지션별 PnL lookup. sibling position 분리. */
export function usePnlByPosition(positionId: string): PositionPnlData {
  return (
    usePriceStore((s) => s.byPositionId.get(positionId)) ?? {
      stock_code: '',
      pnlAmount: null,
      pnlPct: null,
      lastUpdatedAt: null,
    }
  );
}

/** Stale 판정 (마지막 갱신 시각으로부터 N초 이상 경과). */
export type StaleStatus = 'fresh' | 'stale' | 'unknown';

export function staleStatusFromTimestamp(
  lastUpdatedAt: string | null,
  now: number = Date.now(),
  thresholdMs = 5_000,
): StaleStatus {
  if (lastUpdatedAt == null) return 'unknown';
  const ts = Date.parse(lastUpdatedAt);
  if (Number.isNaN(ts)) return 'unknown';
  return now - ts >= thresholdMs ? 'stale' : 'fresh';
}
