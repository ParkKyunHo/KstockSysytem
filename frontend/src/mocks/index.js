/* V7.1 Mock Data — matches CLAUDE_DESIGN_PROMPT.md §6.2 types */
/* Globals: window.MOCK */

(function() {
  'use strict';

  const now = new Date('2026-04-26T05:23:00Z');
  const isoMinusMin = (m) => new Date(now.getTime() - m * 60_000).toISOString();
  const isoMinusHour = (h) => new Date(now.getTime() - h * 3_600_000).toISOString();
  const isoMinusDay = (d) => new Date(now.getTime() - d * 86_400_000).toISOString();

  // ----- Tracked Stocks (12) -----
  const trackedStocks = [
    { id: 'ts-001', stock_code: '005930', stock_name: '삼성전자', market: 'KOSPI', path_type: 'PATH_A', status: 'BOX_SET', user_memo: '반도체 사이클 회복 기대', source: 'HTS', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(1), last_status_changed_at: isoMinusHour(2), summary: { active_box_count: 3, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 73500 },
    { id: 'ts-002', stock_code: '036040', stock_name: '에프알텍',  market: 'KOSDAQ', path_type: 'PATH_A', status: 'POSITION_OPEN',    user_memo: null, source: '뉴스', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(4), last_status_changed_at: isoMinusHour(5), summary: { active_box_count: 1, triggered_box_count: 1, current_position_qty: 100, current_position_avg_price: 18100 }, current_price: 18420 },
    { id: 'ts-003', stock_code: '000660', stock_name: 'SK하이닉스', market: 'KOSPI', path_type: 'PATH_B', status: 'POSITION_PARTIAL', user_memo: 'HBM 공급 수혜', source: '리포트', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(8), last_status_changed_at: isoMinusHour(1), summary: { active_box_count: 2, triggered_box_count: 1, current_position_qty: 30, current_position_avg_price: 218500 }, current_price: 226000 },
    { id: 'ts-004', stock_code: '267260', stock_name: 'HD현대일렉트릭', market: 'KOSPI', path_type: 'PATH_A', status: 'TRACKING', user_memo: null, source: '직접 분석', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(2), last_status_changed_at: isoMinusDay(2), summary: { active_box_count: 0, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 412000 },
    { id: 'ts-005', stock_code: '042660', stock_name: '한화오션',   market: 'KOSPI', path_type: 'PATH_A', status: 'BOX_SET', user_memo: '조선 슈퍼사이클', source: 'HTS', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(3), last_status_changed_at: isoMinusHour(8), summary: { active_box_count: 2, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 76800 },
    { id: 'ts-006', stock_code: '035420', stock_name: 'NAVER',      market: 'KOSPI', path_type: 'PATH_B', status: 'POSITION_OPEN', user_memo: null, source: '뉴스', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(11), last_status_changed_at: isoMinusHour(20), summary: { active_box_count: 1, triggered_box_count: 1, current_position_qty: 50, current_position_avg_price: 195500 }, current_price: 198200 },
    { id: 'ts-007', stock_code: '247540', stock_name: '에코프로비엠', market: 'KOSDAQ', path_type: 'PATH_A', status: 'BOX_SET', user_memo: null, source: 'HTS', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(5), last_status_changed_at: isoMinusHour(15), summary: { active_box_count: 1, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 124500 },
    { id: 'ts-008', stock_code: '012450', stock_name: '한화에어로스페이스', market: 'KOSPI', path_type: 'PATH_B', status: 'TRACKING', user_memo: 'K2 수출 확정', source: '리포트', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(1), last_status_changed_at: isoMinusDay(1), summary: { active_box_count: 0, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 358000 },
    { id: 'ts-009', stock_code: '009540', stock_name: 'HD한국조선해양', market: 'KOSPI', path_type: 'PATH_A', status: 'POSITION_OPEN',  user_memo: null, source: 'HTS', vi_recovered_today: true, auto_exit_reason: null, created_at: isoMinusDay(6), last_status_changed_at: isoMinusMin(35), summary: { active_box_count: 0, triggered_box_count: 1, current_position_qty: 20, current_position_avg_price: 218000 }, current_price: 215500 },
    { id: 'ts-010', stock_code: '326030', stock_name: 'SK바이오팜',  market: 'KOSPI', path_type: 'PATH_A', status: 'EXITED', user_memo: null, source: '뉴스', vi_recovered_today: false, auto_exit_reason: '거래량 급감 (5일 연속)', created_at: isoMinusDay(20), last_status_changed_at: isoMinusDay(2), summary: { active_box_count: 0, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 92800 },
    { id: 'ts-011', stock_code: '293490', stock_name: '카카오게임즈', market: 'KOSDAQ', path_type: 'PATH_B', status: 'BOX_SET', user_memo: null, source: '직접 분석', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(7), last_status_changed_at: isoMinusHour(12), summary: { active_box_count: 1, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 18900 },
    { id: 'ts-012', stock_code: '034020', stock_name: '두산에너빌리티', market: 'KOSPI', path_type: 'PATH_A', status: 'TRACKING', user_memo: 'SMR 모멘텀', source: 'HTS', vi_recovered_today: false, auto_exit_reason: null, created_at: isoMinusDay(0.5), last_status_changed_at: isoMinusMin(45), summary: { active_box_count: 0, triggered_box_count: 0, current_position_qty: 0, current_position_avg_price: null }, current_price: 24850 },
  ];

  // ----- Boxes (~20) -----
  const boxes = [
    { id: 'b-001', tracked_stock_id: 'ts-001', stock_code: '005930', stock_name: '삼성전자', path_type: 'PATH_A', box_tier: 1, upper_price: 74000, lower_price: 73000, position_size_pct: 10, stop_loss_pct: -5, strategy_type: 'PULLBACK', status: 'WAITING', memo: '1차 진입', created_at: isoMinusHour(20), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: isoMinusMin(-30), entry_proximity_pct: 0.27 },
    { id: 'b-002', tracked_stock_id: 'ts-001', stock_code: '005930', stock_name: '삼성전자', path_type: 'PATH_A', box_tier: 2, upper_price: 72500, lower_price: 71500, position_size_pct: 8,  stop_loss_pct: -5, strategy_type: 'PULLBACK', status: 'WAITING', memo: null, created_at: isoMinusHour(20), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: -1.36 },
    { id: 'b-003', tracked_stock_id: 'ts-001', stock_code: '005930', stock_name: '삼성전자', path_type: 'PATH_A', box_tier: 3, upper_price: 71000, lower_price: 70000, position_size_pct: 6,  stop_loss_pct: -5, strategy_type: 'BREAKOUT', status: 'WAITING', memo: null, created_at: isoMinusHour(20), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: -3.40 },
    { id: 'b-004', tracked_stock_id: 'ts-002', stock_code: '036040', stock_name: '에프알텍', path_type: 'PATH_A', box_tier: 1, upper_price: 18200, lower_price: 17800, position_size_pct: 5, stop_loss_pct: -4, strategy_type: 'PULLBACK', status: 'TRIGGERED', memo: null, created_at: isoMinusDay(2), triggered_at: isoMinusHour(5), invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: null },
    { id: 'b-005', tracked_stock_id: 'ts-002', stock_code: '036040', stock_name: '에프알텍', path_type: 'PATH_A', box_tier: 2, upper_price: 17000, lower_price: 16500, position_size_pct: 3, stop_loss_pct: -4, strategy_type: 'PULLBACK', status: 'WAITING', memo: null, created_at: isoMinusDay(2), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: -7.71 },
    { id: 'b-006', tracked_stock_id: 'ts-003', stock_code: '000660', stock_name: 'SK하이닉스', path_type: 'PATH_B', box_tier: 1, upper_price: 220000, lower_price: 215000, position_size_pct: 8, stop_loss_pct: -7, strategy_type: 'PULLBACK', status: 'TRIGGERED', memo: null, created_at: isoMinusDay(7), triggered_at: isoMinusDay(2), invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: null },
    { id: 'b-007', tracked_stock_id: 'ts-003', stock_code: '000660', stock_name: 'SK하이닉스', path_type: 'PATH_B', box_tier: 2, upper_price: 232000, lower_price: 228000, position_size_pct: 6, stop_loss_pct: -7, strategy_type: 'BREAKOUT', status: 'WAITING', memo: null, created_at: isoMinusDay(7), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: 0.88 },
    { id: 'b-008', tracked_stock_id: 'ts-005', stock_code: '042660', stock_name: '한화오션', path_type: 'PATH_A', box_tier: 1, upper_price: 77500, lower_price: 76500, position_size_pct: 8, stop_loss_pct: -5, strategy_type: 'PULLBACK', status: 'WAITING', memo: null, created_at: isoMinusDay(3), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: 0.91 },
    { id: 'b-009', tracked_stock_id: 'ts-005', stock_code: '042660', stock_name: '한화오션', path_type: 'PATH_A', box_tier: 2, upper_price: 75000, lower_price: 74000, position_size_pct: 6, stop_loss_pct: -5, strategy_type: 'PULLBACK', status: 'WAITING', memo: null, created_at: isoMinusDay(3), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: -2.34 },
    { id: 'b-010', tracked_stock_id: 'ts-007', stock_code: '247540', stock_name: '에코프로비엠', path_type: 'PATH_A', box_tier: 1, upper_price: 126000, lower_price: 124000, position_size_pct: 5, stop_loss_pct: -6, strategy_type: 'PULLBACK', status: 'WAITING', memo: '낙폭 회복 신호 대기', created_at: isoMinusDay(5), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: 1.20 },
    { id: 'b-011', tracked_stock_id: 'ts-006', stock_code: '035420', stock_name: 'NAVER', path_type: 'PATH_B', box_tier: 1, upper_price: 196000, lower_price: 194000, position_size_pct: 6, stop_loss_pct: -6, strategy_type: 'PULLBACK', status: 'TRIGGERED', memo: null, created_at: isoMinusDay(11), triggered_at: isoMinusHour(20), invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: null },
    { id: 'b-012', tracked_stock_id: 'ts-009', stock_code: '009540', stock_name: 'HD한국조선해양', path_type: 'PATH_A', box_tier: 1, upper_price: 219000, lower_price: 217000, position_size_pct: 7, stop_loss_pct: -5, strategy_type: 'PULLBACK', status: 'TRIGGERED', memo: null, created_at: isoMinusDay(6), triggered_at: isoMinusHour(2), invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: null },
    { id: 'b-013', tracked_stock_id: 'ts-011', stock_code: '293490', stock_name: '카카오게임즈', path_type: 'PATH_B', box_tier: 1, upper_price: 19200, lower_price: 18800, position_size_pct: 4, stop_loss_pct: -7, strategy_type: 'BREAKOUT', status: 'WAITING', memo: null, created_at: isoMinusDay(7), triggered_at: null, invalidated_at: null, invalidation_reason: null, next_reminder_at: null, entry_proximity_pct: 1.59 },
    { id: 'b-014', tracked_stock_id: 'ts-002', stock_code: '036040', stock_name: '에프알텍', path_type: 'PATH_A', box_tier: 3, upper_price: 15500, lower_price: 15000, position_size_pct: 2, stop_loss_pct: -4, strategy_type: 'PULLBACK', status: 'INVALIDATED', memo: null, created_at: isoMinusDay(4), triggered_at: null, invalidated_at: isoMinusDay(1), invalidation_reason: '14일 미진입', next_reminder_at: null, entry_proximity_pct: null },
  ];

  // ----- Positions (5) -----
  const positions = [
    { id: 'pos-001', source: 'SYSTEM_A', stock_code: '036040', stock_name: '에프알텍', tracked_stock_id: 'ts-002', triggered_box_id: 'b-004', initial_avg_price: 18100, weighted_avg_price: 18100, total_quantity: 100, fixed_stop_price: 17376, profit_5_executed: false, profit_10_executed: false, ts_activated: false, ts_base_price: null, ts_stop_price: null, ts_active_multiplier: null, actual_capital_invested: 1810000, status: 'OPEN', current_price: 18420, pnl_amount: 32000, pnl_pct: 1.77, closed_at: null, final_pnl: null, close_reason: null, created_at: isoMinusHour(5), updated_at: isoMinusMin(2) },
    { id: 'pos-002', source: 'SYSTEM_B', stock_code: '000660', stock_name: 'SK하이닉스', tracked_stock_id: 'ts-003', triggered_box_id: 'b-006', initial_avg_price: 218500, weighted_avg_price: 218500, total_quantity: 30, fixed_stop_price: 203205, profit_5_executed: true, profit_10_executed: false, ts_activated: false, ts_base_price: null, ts_stop_price: null, ts_active_multiplier: null, actual_capital_invested: 6555000, status: 'PARTIAL_CLOSED', current_price: 226000, pnl_amount: 225000, pnl_pct: 3.43, closed_at: null, final_pnl: null, close_reason: null, created_at: isoMinusDay(2), updated_at: isoMinusMin(3) },
    { id: 'pos-003', source: 'SYSTEM_A', stock_code: '035420', stock_name: 'NAVER', tracked_stock_id: 'ts-006', triggered_box_id: 'b-011', initial_avg_price: 195500, weighted_avg_price: 195500, total_quantity: 50, fixed_stop_price: 183770, profit_5_executed: false, profit_10_executed: false, ts_activated: false, ts_base_price: null, ts_stop_price: null, ts_active_multiplier: null, actual_capital_invested: 9775000, status: 'OPEN', current_price: 198200, pnl_amount: 135000, pnl_pct: 1.38, closed_at: null, final_pnl: null, close_reason: null, created_at: isoMinusHour(20), updated_at: isoMinusMin(1) },
    { id: 'pos-004', source: 'MANUAL', stock_code: '009540', stock_name: 'HD한국조선해양', tracked_stock_id: 'ts-009', triggered_box_id: null, initial_avg_price: 218000, weighted_avg_price: 218000, total_quantity: 20, fixed_stop_price: 207100, profit_5_executed: false, profit_10_executed: false, ts_activated: false, ts_base_price: null, ts_stop_price: null, ts_active_multiplier: null, actual_capital_invested: 4360000, status: 'OPEN', current_price: 215500, pnl_amount: -50000, pnl_pct: -1.15, closed_at: null, final_pnl: null, close_reason: null, created_at: isoMinusHour(2), updated_at: isoMinusMin(2) },
    { id: 'pos-005', source: 'SYSTEM_A', stock_code: '247540', stock_name: '에코프로비엠', tracked_stock_id: 'ts-007', triggered_box_id: null, initial_avg_price: 122000, weighted_avg_price: 122000, total_quantity: 25, fixed_stop_price: 114680, profit_5_executed: true, profit_10_executed: true, ts_activated: true, ts_base_price: 134200, ts_stop_price: 130274, ts_active_multiplier: 0.97, actual_capital_invested: 3050000, status: 'OPEN', current_price: 132500, pnl_amount: 262500, pnl_pct: 8.61, closed_at: null, final_pnl: null, close_reason: null, created_at: isoMinusDay(3), updated_at: isoMinusMin(1) },
  ];

  // ----- Trade Events (~20) -----
  const tradeEvents = [
    { id: 'tev-001', event_type: 'BUY_EXECUTED', position_id: 'pos-001', stock_code: '036040', quantity: 100, price: 18100, occurred_at: isoMinusHour(5) },
    { id: 'tev-002', event_type: 'BUY_EXECUTED', position_id: 'pos-002', stock_code: '000660', quantity: 30, price: 218500, occurred_at: isoMinusDay(2) },
    { id: 'tev-003', event_type: 'PROFIT_TAKE_5', position_id: 'pos-002', stock_code: '000660', quantity: 10, price: 229425, occurred_at: isoMinusHour(8) },
    { id: 'tev-004', event_type: 'BUY_EXECUTED', position_id: 'pos-003', stock_code: '035420', quantity: 50, price: 195500, occurred_at: isoMinusHour(20) },
    { id: 'tev-005', event_type: 'MANUAL_PYRAMID_BUY', position_id: 'pos-004', stock_code: '009540', quantity: 20, price: 218000, occurred_at: isoMinusHour(2) },
    { id: 'tev-006', event_type: 'BUY_EXECUTED', position_id: 'pos-005', stock_code: '247540', quantity: 25, price: 122000, occurred_at: isoMinusDay(3) },
    { id: 'tev-007', event_type: 'PROFIT_TAKE_5', position_id: 'pos-005', stock_code: '247540', quantity: 6, price: 128100, occurred_at: isoMinusDay(2) },
    { id: 'tev-008', event_type: 'PROFIT_TAKE_10', position_id: 'pos-005', stock_code: '247540', quantity: 6, price: 134200, occurred_at: isoMinusDay(1) },
    { id: 'tev-009', event_type: 'PYRAMID_BUY',       position_id: 'pos-002', stock_code: '000660', quantity: 15, price: 224800, occurred_at: isoMinusDay(1) },
    { id: 'tev-010', event_type: 'TS_ACTIVATED',      position_id: 'pos-005', stock_code: '247540', quantity: 0,  price: 134200, occurred_at: isoMinusDay(1) },
    { id: 'tev-011', event_type: 'TS_EXIT',           position_id: 'pos-005', stock_code: '247540', quantity: 13, price: 131500, occurred_at: isoMinusHour(14) },
    { id: 'tev-012', event_type: 'STOP_LOSS',         position_id: 'pos-004', stock_code: '009540', quantity: 20, price: 207100, occurred_at: isoMinusHour(11) },
    { id: 'tev-013', event_type: 'BUY_REJECTED',      position_id: null,      stock_code: '293490', quantity: 0,  price: 19250,  occurred_at: isoMinusHour(9) },
    { id: 'tev-014', event_type: 'MANUAL_SELL',       position_id: 'pos-002', stock_code: '000660', quantity: 5,  price: 226400, occurred_at: isoMinusHour(7) },
    { id: 'tev-015', event_type: 'BUY_EXECUTED',      position_id: 'pos-001', stock_code: '036040', quantity: 100, price: 18100, occurred_at: isoMinusHour(5) },
    { id: 'tev-016', event_type: 'PROFIT_TAKE_5',     position_id: 'pos-003', stock_code: '035420', quantity: 12, price: 205275, occurred_at: isoMinusHour(4) },
    { id: 'tev-017', event_type: 'PYRAMID_BUY',       position_id: 'pos-001', stock_code: '036040', quantity: 30, price: 18380,  occurred_at: isoMinusHour(3) },
    { id: 'tev-018', event_type: 'MANUAL_PYRAMID_BUY',position_id: 'pos-004', stock_code: '009540', quantity: 20, price: 218000, occurred_at: isoMinusHour(2) },
    { id: 'tev-019', event_type: 'BUY_REJECTED',      position_id: null,      stock_code: '042660', quantity: 0,  price: 77900,  occurred_at: isoMinusHour(1) },
    { id: 'tev-020', event_type: 'POSITION_CLOSED',   position_id: 'pos-005', stock_code: '247540', quantity: 0,  price: 131500, occurred_at: isoMinusMin(45) },
  ];

  // ----- Notifications (12 displayed) -----
  const notifications = [
    { id: 'n-001', severity: 'CRITICAL', channel: 'BOTH', event_type: 'STOP_LOSS', stock_code: '009540', title: '[CRITICAL] 손절 임박', message: 'HD한국조선해양 현재가 215,500원, 손절선 207,100원까지 -3.9%', payload: null, status: 'SENT', priority: 1, rate_limit_key: null, retry_count: 0, sent_at: isoMinusMin(2), failed_at: null, failure_reason: null, created_at: isoMinusMin(2), expires_at: null },
    { id: 'n-002', severity: 'HIGH', channel: 'BOTH', event_type: 'BOX_PROXIMITY', stock_code: '005930', title: '박스 진입 임박', message: '삼성전자 73,500원, 1차 박스 (73,000~74,000) 안 진입 중', payload: null, status: 'SENT', priority: 2, rate_limit_key: null, retry_count: 0, sent_at: isoMinusMin(8), failed_at: null, failure_reason: null, created_at: isoMinusMin(8), expires_at: null },
    { id: 'n-003', severity: 'HIGH', channel: 'BOTH', event_type: 'BOX_PROXIMITY', stock_code: '042660', title: '박스 진입 임박', message: '한화오션 76,800원, 1차 박스 (76,500~77,500) 진입', payload: null, status: 'SENT', priority: 2, rate_limit_key: null, retry_count: 0, sent_at: isoMinusMin(15), failed_at: null, failure_reason: null, created_at: isoMinusMin(15), expires_at: null },
    { id: 'n-004', severity: 'MEDIUM', channel: 'WEB', event_type: 'PROFIT_TAKE', stock_code: '247540', title: '+10% 수익 실현', message: '에코프로비엠 134,200원에 6주 매도 (TS 활성화)', payload: null, status: 'SENT', priority: 3, rate_limit_key: null, retry_count: 0, sent_at: isoMinusHour(24), failed_at: null, failure_reason: null, created_at: isoMinusHour(24), expires_at: null },
    { id: 'n-005', severity: 'MEDIUM', channel: 'BOTH', event_type: 'BOX_TRIGGERED', stock_code: '036040', title: '박스 진입', message: '에프알텍 18,100원 매수 체결 (1차 박스)', payload: null, status: 'SENT', priority: 3, rate_limit_key: null, retry_count: 0, sent_at: isoMinusHour(5), failed_at: null, failure_reason: null, created_at: isoMinusHour(5), expires_at: null },
    { id: 'n-006', severity: 'LOW', channel: 'WEB', event_type: 'REPORT_COMPLETED', stock_code: '000660', title: '리포트 생성 완료', message: 'SK하이닉스 리포트가 준비되었습니다.', payload: null, status: 'SENT', priority: 4, rate_limit_key: null, retry_count: 0, sent_at: isoMinusHour(6), failed_at: null, failure_reason: null, created_at: isoMinusHour(6), expires_at: null },
    { id: 'n-007', severity: 'LOW', channel: 'WEB', event_type: 'BOX_INVALIDATED', stock_code: '036040', title: '박스 무효화', message: '에프알텍 3차 박스 14일 미진입으로 자동 무효화', payload: null, status: 'SENT', priority: 4, rate_limit_key: null, retry_count: 0, sent_at: isoMinusDay(1), failed_at: null, failure_reason: null, created_at: isoMinusDay(1), expires_at: null },
    { id: 'n-008', severity: 'HIGH', channel: 'BOTH', event_type: 'VI_TRIGGERED', stock_code: '009540', title: 'VI 발동 후 회복', message: 'HD한국조선해양 VI 발동 → 정상 거래 회복', payload: null, status: 'SENT', priority: 2, rate_limit_key: null, retry_count: 0, sent_at: isoMinusMin(35), failed_at: null, failure_reason: null, created_at: isoMinusMin(35), expires_at: null },
    { id: 'n-009', severity: 'MEDIUM', channel: 'WEB', event_type: 'BOX_PROXIMITY', stock_code: '293490', title: '박스 진입 임박', message: '카카오게임즈 18,900원, 1차 박스 (18,800~19,200) 진입', payload: null, status: 'SENT', priority: 3, rate_limit_key: null, retry_count: 0, sent_at: isoMinusMin(45), failed_at: null, failure_reason: null, created_at: isoMinusMin(45), expires_at: null },
    { id: 'n-010', severity: 'LOW', channel: 'WEB', event_type: 'TRACKING_AUTO_EXIT', stock_code: '326030', title: '자동 추적 종료', message: 'SK바이오팜 거래량 급감(5일 연속)으로 추적 종료', payload: null, status: 'SENT', priority: 4, rate_limit_key: null, retry_count: 0, sent_at: isoMinusDay(2), failed_at: null, failure_reason: null, created_at: isoMinusDay(2), expires_at: null },
    { id: 'n-011', severity: 'CRITICAL', channel: 'BOTH', event_type: 'WS_DISCONNECT', stock_code: null, title: '[CRITICAL] WebSocket 끊김', message: '키움 WebSocket 연결 일시 중단 (45초 후 자동 복구)', payload: null, status: 'SENT', priority: 1, rate_limit_key: null, retry_count: 0, sent_at: isoMinusHour(3), failed_at: null, failure_reason: null, created_at: isoMinusHour(3), expires_at: null },
    { id: 'n-012', severity: 'MEDIUM', channel: 'BOTH', event_type: 'PYRAMID', stock_code: '000660', title: '+5% 수익 실현', message: 'SK하이닉스 229,425원에 10주 매도', payload: null, status: 'SENT', priority: 3, rate_limit_key: null, retry_count: 0, sent_at: isoMinusHour(8), failed_at: null, failure_reason: null, created_at: isoMinusHour(8), expires_at: null },
  ];

  // ----- Reports (8) -----
  const reports = [
    { id: 'r-001', stock_code: '005930', stock_name: '삼성전자', status: 'COMPLETED', model_version: 'claude-opus-4.5', prompt_tokens: 12450, completion_tokens: 8230, narrative_part: '## 삼성전자의 이야기\n\n**메모리 반도체의 대장.** 2025년 한 해 HBM3E 양산 캐파를 두 배로 늘리며 SK하이닉스에 빼앗겼던 AI 메모리 시장 점유율을 빠르게 되찾았다.\n\n### 사업 구조\n\n- **DS 부문 (반도체)**: 매출의 60% 이상\n- **DX 부문 (스마트폰/가전)**: 30%\n- **하만 (전장)**: 10%\n\n### 최근 분기 핵심 변화\n\n2026 1Q 영업이익 7.1조 원 — 컨센서스 6.4조 원 상회. 메모리 가격 상승 + HBM 비중 확대가 견인했다.\n\n### 전략 의미\n\nPATH_A 단타로 박스 잡기에 적합한 종목. 거래대금 3조 원대로 유동성 충분.', facts_part: '## 객관 팩트\n\n| 항목 | 값 |\n|------|-----|\n| 시가총액 | 432조 원 |\n| 1년 최고 / 최저 | 78,500 / 65,200원 |\n| PER (TTM) | 14.2 |\n| PBR | 1.4 |\n| 배당수익률 | 1.9% |\n\n### 최근 공시 (60일)\n- 2026-04-12: 자사주 매입 1조 원 결의\n- 2026-03-28: 1Q 잠정실적 발표\n- 2026-03-15: HBM4 첫 샘플 출하\n\n### 외인/기관 수급 (5일)\n- 외인: +2,850억 원\n- 기관: +1,420억 원', pdf_path: '/reports/r-001.pdf', excel_path: '/reports/r-001.xlsx', user_notes: 'HBM 수혜 지속 — 1차 박스 진입 시 비중 10%로 포지션 시작', generation_started_at: isoMinusDay(1), generation_completed_at: isoMinusDay(0.96), generation_duration_seconds: 312, created_at: isoMinusDay(1) },
    { id: 'r-002', stock_code: '000660', stock_name: 'SK하이닉스', status: 'COMPLETED', model_version: 'claude-opus-4.5', prompt_tokens: 11200, completion_tokens: 7950, narrative_part: '## SK하이닉스 이야기\n\nHBM 시장의 압도적 1등.', facts_part: '## 객관 팩트\n시가총액 162조 원.', pdf_path: '/reports/r-002.pdf', excel_path: '/reports/r-002.xlsx', user_notes: null, generation_started_at: isoMinusDay(2), generation_completed_at: isoMinusDay(1.97), generation_duration_seconds: 285, created_at: isoMinusDay(2) },
    { id: 'r-003', stock_code: '247540', stock_name: '에코프로비엠', status: 'GENERATING', model_version: 'claude-opus-4.5', prompt_tokens: null, completion_tokens: null, narrative_part: null, facts_part: null, pdf_path: null, excel_path: null, user_notes: null, progress: 64, generation_started_at: isoMinusMin(3), generation_completed_at: null, generation_duration_seconds: null, created_at: isoMinusMin(3) },
    { id: 'r-004', stock_code: '042660', stock_name: '한화오션', status: 'COMPLETED', model_version: 'claude-sonnet-4.5', prompt_tokens: 8800, completion_tokens: 5600, narrative_part: '## 한화오션', facts_part: '## 팩트', pdf_path: '/reports/r-004.pdf', excel_path: '/reports/r-004.xlsx', user_notes: null, generation_started_at: isoMinusDay(3), generation_completed_at: isoMinusDay(2.98), generation_duration_seconds: 198, created_at: isoMinusDay(3) },
    { id: 'r-005', stock_code: '267260', stock_name: 'HD현대일렉트릭', status: 'PENDING', model_version: 'claude-opus-4.5', prompt_tokens: null, completion_tokens: null, narrative_part: null, facts_part: null, pdf_path: null, excel_path: null, user_notes: null, generation_started_at: null, generation_completed_at: null, generation_duration_seconds: null, created_at: isoMinusMin(8) },
    { id: 'r-006', stock_code: '293490', stock_name: '카카오게임즈', status: 'FAILED', model_version: 'claude-opus-4.5', prompt_tokens: 4200, completion_tokens: null, narrative_part: null, facts_part: null, pdf_path: null, excel_path: null, user_notes: null, error_message: 'Anthropic API 일시적 503', generation_started_at: isoMinusHour(4), generation_completed_at: null, generation_duration_seconds: null, created_at: isoMinusHour(4) },
    { id: 'r-007', stock_code: '012450', stock_name: '한화에어로스페이스', status: 'COMPLETED', model_version: 'claude-opus-4.5', prompt_tokens: 13500, completion_tokens: 9100, narrative_part: '## 한화에어로스페이스', facts_part: '## 팩트', pdf_path: '/reports/r-007.pdf', excel_path: '/reports/r-007.xlsx', user_notes: null, generation_started_at: isoMinusDay(4), generation_completed_at: isoMinusDay(3.97), generation_duration_seconds: 340, created_at: isoMinusDay(4) },
    { id: 'r-008', stock_code: '034020', stock_name: '두산에너빌리티', status: 'COMPLETED', model_version: 'claude-sonnet-4.5', prompt_tokens: 7800, completion_tokens: 5200, narrative_part: '## 두산에너빌리티', facts_part: '## 팩트', pdf_path: '/reports/r-008.pdf', excel_path: '/reports/r-008.xlsx', user_notes: null, generation_started_at: isoMinusDay(5), generation_completed_at: isoMinusDay(4.99), generation_duration_seconds: 167, created_at: isoMinusDay(5) },
  ];

  // ----- System status -----
  const systemStatus = {
    status: 'RUNNING',
    uptime_seconds: 367920,
    websocket: { connected: true, last_disconnect_at: isoMinusHour(3), reconnect_count_today: 1 },
    kiwoom_api: { available: true, rate_limit_used_per_sec: 3, rate_limit_max: 5 },
    telegram_bot: { active: true, circuit_breaker_state: 'CLOSED' },
    database: { connected: true, latency_ms: 8 },
    feature_flags: { 'v71.box_system': true, 'v71.exit_v71': true, 'v71.partial_close': true, 'v71.ts_multiplier': false, 'v71.report_v2': true },
    market: { is_open: true, session: 'REGULAR', next_open_at: null, next_close_at: '2026-04-26T06:30:00Z' },
    current_time: now.toISOString(),
  };

  // ----- Settings -----
  const settings = {
    general: { total_capital: 100_000_000, language: 'ko', theme: 'g100' },
    notifications: { critical: true, high: true, medium: true, low: false, quiet_hours: false, quiet_start: '22:00', quiet_end: '08:00' },
    sessions: [
      { id: 's-1', ip: '203.0.113.42', user_agent: 'Chrome 134 / macOS', last_active_at: isoMinusMin(1), is_current: true },
      { id: 's-2', ip: '203.0.113.42', user_agent: 'iOS Safari 17 / iPhone 15 Pro', last_active_at: isoMinusHour(8), is_current: false },
    ],
    restart_history: [
      { id: 'rh-1', occurred_at: isoMinusDay(2), reason: 'Manual safe-mode entry', duration_s: 45, status: 'OK' },
      { id: 'rh-2', occurred_at: isoMinusDay(7), reason: 'Deploy v7.0.4', duration_s: 22, status: 'OK' },
    ],
    telegram: { connected: true, bot_name: '@kstock_v71_bot', authorized_chats: [
      { id: 'c-1', chat_id: '524873611', registered_at: isoMinusDay(45) },
      { id: 'c-2', chat_id: '102938475', registered_at: isoMinusDay(20) },
    ]},
  };

  window.MOCK = { trackedStocks, boxes, positions, tradeEvents, notifications, reports, systemStatus, settings };

  // ----- formatters -----
  window.fmt = {
    krw: (n) => (n == null ? '-' : new Intl.NumberFormat('ko-KR').format(Math.round(n))),
    krwSigned: (n) => (n == null ? '-' : (n >= 0 ? '+' : '') + new Intl.NumberFormat('ko-KR').format(Math.round(n))),
    pct: (n, d=2) => (n == null ? '-' : (n >= 0 ? '+' : '') + n.toFixed(d) + '%'),
    pctRaw: (n, d=2) => (n == null ? '-' : n.toFixed(d) + '%'),
    time: (iso) => { if(!iso) return '-'; const d = new Date(iso); return d.toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',hour12:false}); },
    timeS: (iso) => { if(!iso) return '-'; const d = new Date(iso); return d.toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}); },
    dateTime: (iso) => { if(!iso) return '-'; const d = new Date(iso); return d.toLocaleString('ko-KR',{year:'2-digit',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}); },
    relative: (iso) => {
      if (!iso) return '-';
      const ms = new Date(iso).getTime();
      const diffSec = Math.floor((Date.now() - ms) / 1000);
      if (diffSec < 60) return diffSec + '초 전';
      if (diffSec < 3600) return Math.floor(diffSec / 60) + '분 전';
      if (diffSec < 86400) return Math.floor(diffSec / 3600) + '시간 전';
      return Math.floor(diffSec / 86400) + '일 전';
    },
  };

  // ----- search results (mock) -----
  window.MOCK.stockSearch = (q) => {
    const all = [
      ...trackedStocks.map(s => ({ code: s.stock_code, name: s.stock_name, market: s.market, currentPrice: s.current_price })),
      { code: '005380', name: '현대차', market: 'KOSPI', currentPrice: 248500 },
      { code: '051910', name: 'LG화학', market: 'KOSPI', currentPrice: 412500 },
      { code: '068270', name: '셀트리온', market: 'KOSPI', currentPrice: 198200 },
      { code: '207940', name: '삼성바이오로직스', market: 'KOSPI', currentPrice: 952000 },
      { code: '373220', name: 'LG에너지솔루션', market: 'KOSPI', currentPrice: 412000 },
    ];
    if (!q) return all.slice(0, 8);
    const ql = q.toLowerCase();
    return all.filter(s => s.code.includes(q) || s.name.toLowerCase().includes(ql)).slice(0, 8);
  };
})();
