// V7.1 WS POSITION_PRICE_UPDATE → priceStore subscription.
//
// Mounted ONCE inside AppShell (after useWsBootstrap), bridges the WS
// envelope to the Zustand store. Per-page hooks (usePriceByStock /
// usePnlByPosition) read the store with selective subscribe so only
// affected components re-render.
//
// Channel scope (architect Q2 PR1): currently subscribes to ``positions``
// channel only. Adds ``boxes`` (for BOX_ENTRY_PROXIMITY) in PR2.

import { useEffect } from 'react';

import { useWsChannels, useWsMessages } from '@/hooks/useWebSocket';
import { usePriceStore, type PriceUpdatePayload } from '@/stores/priceStore';
import type { WsEnvelope } from '@/lib/ws';

const POSITION_PRICE_UPDATE = 'POSITION_PRICE_UPDATE';
const POSITION_CLOSED = 'POSITION_CLOSED';

/**
 * Subscribe to ``positions`` channel and forward POSITION_PRICE_UPDATE
 * events to the price store. Mount once -- AppShell is the canonical
 * call site.
 */
export function usePriceTickSubscription(): void {
  // Subscribe channels for the lifetime of the AppShell.
  useWsChannels(['positions']);

  const applyPriceUpdate = usePriceStore((s) => s.applyPriceUpdate);
  const removePosition = usePriceStore((s) => s.removePosition);

  // useWsMessages takes a stable handler; useEffect captures the latest
  // store actions via closure but actions are stable in Zustand v5 so
  // the dependency array is intentionally empty after mount.
  useEffect(() => {
    // No-op: handler registration happens via useWsMessages below.
  }, []);

  useWsMessages((env: WsEnvelope) => {
    if (env.channel !== 'positions') return;
    if (env.type === POSITION_PRICE_UPDATE) {
      const data = env.data as Partial<PriceUpdatePayload> | undefined;
      if (
        data?.position_id == null ||
        data.stock_code == null ||
        data.current_price == null ||
        data.pnl_amount == null ||
        data.pnl_pct == null
      ) {
        return;
      }
      applyPriceUpdate({
        position_id: data.position_id,
        stock_code: data.stock_code,
        current_price: data.current_price,
        pnl_amount: data.pnl_amount,
        pnl_pct: data.pnl_pct,
        timestamp: data.timestamp,
      });
      return;
    }
    if (env.type === POSITION_CLOSED) {
      const data = env.data as { position_id?: string } | undefined;
      if (data?.position_id) {
        removePosition(data.position_id);
      }
    }
  });
}
