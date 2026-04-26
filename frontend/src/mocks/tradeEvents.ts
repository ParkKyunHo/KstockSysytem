import type { TradeEvent } from '@/types';
import { isoMinusDay, isoMinusHour, isoMinusMin } from '@/lib/time';

export const mockTradeEvents: TradeEvent[] = [
  { id: 'tev-001', event_type: 'BUY_EXECUTED', position_id: 'pos-001', stock_code: '036040', quantity: 100, price: 18100, occurred_at: isoMinusHour(5) },
  { id: 'tev-002', event_type: 'BUY_EXECUTED', position_id: 'pos-002', stock_code: '000660', quantity: 30, price: 218500, occurred_at: isoMinusDay(2) },
  { id: 'tev-003', event_type: 'PROFIT_TAKE_5', position_id: 'pos-002', stock_code: '000660', quantity: 10, price: 229425, occurred_at: isoMinusHour(8) },
  { id: 'tev-004', event_type: 'BUY_EXECUTED', position_id: 'pos-003', stock_code: '035420', quantity: 50, price: 195500, occurred_at: isoMinusHour(20) },
  { id: 'tev-005', event_type: 'MANUAL_PYRAMID_BUY', position_id: 'pos-004', stock_code: '009540', quantity: 20, price: 218000, occurred_at: isoMinusHour(2) },
  { id: 'tev-006', event_type: 'BUY_EXECUTED', position_id: 'pos-005', stock_code: '247540', quantity: 25, price: 122000, occurred_at: isoMinusDay(3) },
  { id: 'tev-007', event_type: 'PROFIT_TAKE_5', position_id: 'pos-005', stock_code: '247540', quantity: 6, price: 128100, occurred_at: isoMinusDay(2) },
  { id: 'tev-008', event_type: 'PROFIT_TAKE_10', position_id: 'pos-005', stock_code: '247540', quantity: 6, price: 134200, occurred_at: isoMinusDay(1) },
  { id: 'tev-009', event_type: 'PYRAMID_BUY', position_id: 'pos-002', stock_code: '000660', quantity: 15, price: 224800, occurred_at: isoMinusDay(1) },
  { id: 'tev-010', event_type: 'TS_EXIT', position_id: 'pos-005', stock_code: '247540', quantity: 13, price: 131500, occurred_at: isoMinusHour(14) },
  { id: 'tev-011', event_type: 'STOP_LOSS', position_id: 'pos-004', stock_code: '009540', quantity: 20, price: 207100, occurred_at: isoMinusHour(11) },
  { id: 'tev-012', event_type: 'MANUAL_SELL', position_id: 'pos-002', stock_code: '000660', quantity: 5, price: 226400, occurred_at: isoMinusHour(7) },
  { id: 'tev-013', event_type: 'PROFIT_TAKE_5', position_id: 'pos-003', stock_code: '035420', quantity: 12, price: 205275, occurred_at: isoMinusHour(4) },
  { id: 'tev-014', event_type: 'PYRAMID_BUY', position_id: 'pos-001', stock_code: '036040', quantity: 30, price: 18380, occurred_at: isoMinusHour(3) },
  { id: 'tev-015', event_type: 'MANUAL_PYRAMID_BUY', position_id: 'pos-004', stock_code: '009540', quantity: 20, price: 218000, occurred_at: isoMinusHour(2) },
  { id: 'tev-016', event_type: 'BUY_EXECUTED', position_id: 'pos-001', stock_code: '036040', quantity: 100, price: 18100, occurred_at: isoMinusMin(45) },
];
