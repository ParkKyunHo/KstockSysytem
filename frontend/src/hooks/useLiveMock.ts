import { useEffect, useState } from 'react';
import type { MockState } from '@/mocks';

const TICK_MS = 2000;
const DRIFT_RANGE = 0.006; // ±0.3%

/**
 * Mock WebSocket simulator.
 *
 * Mirrors `frontend-prototype/V7.1 Dashboard.html` `useLiveMock`:
 *   - Every 2 seconds, every tracked stock's price drifts by
 *     a uniform random within ±0.3%.
 *   - Open positions recompute pnl_amount + pnl_pct against the
 *     refreshed price (using their own tracked_stock_id link).
 *   - systemStatus.current_time advances to the wall-clock now.
 *
 * Replace with the real WebSocket client (P5.4) by swapping this
 * hook's body with a `useWebSocket(`/ws/positions`)` adapter.
 */
export function useLiveMock(initial: MockState): MockState {
  const [state, setState] = useState<MockState>(initial);

  useEffect(() => {
    const id = window.setInterval(() => {
      setState((prev) => {
        const trackedStocks = prev.trackedStocks.map((stock) => {
          const drift = (Math.random() - 0.5) * DRIFT_RANGE;
          const nextPrice = Math.max(
            100,
            Math.round(stock.current_price * (1 + drift)),
          );
          return { ...stock, current_price: nextPrice };
        });

        const priceByTrackedId = new Map<string, number>();
        for (const s of trackedStocks) {
          priceByTrackedId.set(s.id, s.current_price);
        }

        const positions = prev.positions.map((p) => {
          if (p.status === 'CLOSED') return p;
          const live =
            p.tracked_stock_id != null
              ? priceByTrackedId.get(p.tracked_stock_id)
              : undefined;
          if (live == null) return p;
          const pnlAmount = (live - p.weighted_avg_price) * p.total_quantity;
          const pnlPct =
            ((live - p.weighted_avg_price) / p.weighted_avg_price) * 100;
          return {
            ...p,
            current_price: live,
            pnl_amount: Math.round(pnlAmount),
            pnl_pct: Number(pnlPct.toFixed(2)),
          };
        });

        return {
          ...prev,
          trackedStocks,
          positions,
          systemStatus: {
            ...prev.systemStatus,
            current_time: new Date().toISOString(),
          },
        };
      });
    }, TICK_MS);

    return () => window.clearInterval(id);
  }, []);

  return state;
}
