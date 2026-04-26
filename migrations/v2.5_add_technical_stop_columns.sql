-- PRD v2.5 마이그레이션: 기술적 손절 및 분할 매도 컬럼 추가
-- 실행일: 2025-12-07
-- 대상 DB: Supabase (PostgreSQL)

-- 1. trades 테이블에 새 컬럼 추가
ALTER TABLE trades
ADD COLUMN IF NOT EXISTS stop_loss_price INTEGER,           -- 기술적 손절 가격 (Floor Line = Lowest 20)
ADD COLUMN IF NOT EXISTS is_partial_exit BOOLEAN DEFAULT FALSE,  -- 분할 매도 실행 여부
ADD COLUMN IF NOT EXISTS entry_floor_line INTEGER;          -- 진입 시점 바닥 라인 기록용

-- 2. 컬럼 설명 추가 (Supabase/PostgreSQL)
COMMENT ON COLUMN trades.stop_loss_price IS '기술적 손절 가격 - Floor Line (Lowest 20) 기반';
COMMENT ON COLUMN trades.is_partial_exit IS '분할 매도 실행 여부 - +2.5% 도달 시 50% 매도 후 True';
COMMENT ON COLUMN trades.entry_floor_line IS '진입 시점의 바닥 라인 (Floor Line) 기록용';

-- 3. 기존 데이터 마이그레이션 (선택사항)
-- 기존 열린 포지션이 있다면, entry_price 기준으로 임시 손절가 설정
-- UPDATE trades
-- SET stop_loss_price = ROUND(entry_price * 0.965)  -- -3.5% Safety Stop
-- WHERE status = 'OPEN' AND stop_loss_price IS NULL;

-- 4. 인덱스 추가 (성능 최적화)
CREATE INDEX IF NOT EXISTS ix_trades_stop_loss_price ON trades(stop_loss_price);
CREATE INDEX IF NOT EXISTS ix_trades_is_partial_exit ON trades(is_partial_exit);
