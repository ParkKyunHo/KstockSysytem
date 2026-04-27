// Mock stock search helper -- mirrors window.MOCK.stockSearch from the prototype.
// Used by the "새 종목 추적" modal in TrackedStocks.

import { mockTrackedStocks } from './trackedStocks';

export interface StockSearchResult {
  code: string;
  name: string;
  market: 'KOSPI' | 'KOSDAQ';
  currentPrice: number;
}

const EXTRA_STOCKS: StockSearchResult[] = [
  { code: '005380', name: '현대차', market: 'KOSPI', currentPrice: 248500 },
  { code: '051910', name: 'LG화학', market: 'KOSPI', currentPrice: 412500 },
  { code: '068270', name: '셀트리온', market: 'KOSPI', currentPrice: 198200 },
  { code: '207940', name: '삼성바이오로직스', market: 'KOSPI', currentPrice: 952000 },
  { code: '373220', name: 'LG에너지솔루션', market: 'KOSPI', currentPrice: 412000 },
];

export function searchStocks(q: string): StockSearchResult[] {
  const all: StockSearchResult[] = [
    ...mockTrackedStocks.map((s) => ({
      code: s.stock_code,
      name: s.stock_name,
      market: s.market,
      currentPrice: s.current_price,
    })),
    ...EXTRA_STOCKS,
  ];
  if (!q) return all.slice(0, 8);
  const ql = q.toLowerCase();
  return all
    .filter((s) => s.code.includes(q) || s.name.toLowerCase().includes(ql))
    .slice(0, 8);
}
