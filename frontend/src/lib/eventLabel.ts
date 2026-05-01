// 거래 이벤트 type → 한국어 라벨.
// Mirrors `frontend-prototype/src/pages/dashboard.js eventLabel`.

const LABELS: Record<string, string> = {
  BUY_EXECUTED: '매수',
  PYRAMID_BUY: '추가매수',
  MANUAL_PYRAMID_BUY: '수동매수',
  PROFIT_TAKE_5: '+5% 청산',
  PROFIT_TAKE_10: '+10% 청산',
  STOP_LOSS: '손절',
  TS_EXIT: 'TS 청산',
  MANUAL_SELL: '수동매도',
};

export function eventLabel(eventType: string): string {
  return LABELS[eventType] ?? eventType;
}
