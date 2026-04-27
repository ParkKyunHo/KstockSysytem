// Mock data aggregator. The shape is the snapshot consumed by the
// dashboard; mutated in-place by useLiveMock to simulate WebSocket
// price updates.

import { mockBoxes } from './boxes';
import { mockNotifications } from './notifications';
import { mockPositions } from './positions';
import { mockReports } from './reports';
import { mockSystemStatus } from './system';
import { mockTradeEvents } from './tradeEvents';
import { mockTrackedStocks, type TrackedStockWithPrice } from './trackedStocks';

import type {
  Box,
  NotificationRecord,
  Position,
  Report,
  SystemStatusData,
  TradeEvent,
} from '@/types';

export interface MockState {
  trackedStocks: TrackedStockWithPrice[];
  boxes: Box[];
  positions: Position[];
  tradeEvents: TradeEvent[];
  notifications: NotificationRecord[];
  reports: Report[];
  systemStatus: SystemStatusData;
}

export const initialMock: MockState = {
  trackedStocks: mockTrackedStocks,
  boxes: mockBoxes,
  positions: mockPositions,
  tradeEvents: mockTradeEvents,
  notifications: mockNotifications,
  reports: mockReports,
  systemStatus: mockSystemStatus,
};

export type { TrackedStockWithPrice };
