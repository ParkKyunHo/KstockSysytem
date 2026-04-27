-- V7.1 migration 020 -- PRD Patch #5 (V7.1.0d, 2026-04-27):
-- Soft-delete support for ``daily_reports``. Reports are permanent records
-- (audit + retrospective); UI delete becomes ``is_hidden = TRUE``.
--
-- Spec source: docs/v71/03_DATA_MODEL.md §4.1 (daily_reports) +
--              docs/v71/09_API_SPEC.md §8.7-8.8 (DELETE soft / restore) +
--              docs/v71/13_APPENDIX.md §6.2.Z (한계 2 해결).
--
-- Migration strategy follows 03_DATA_MODEL.md §0.1 (NOT NULL 추가는 3단계):
--   1) Add column NULL-allowed
--   2) UPDATE existing rows to FALSE
--   3) Tighten to NOT NULL + DEFAULT
--
-- Migration Strategy Agent (06_AGENTS_SPEC.md §3) verified WARNING-PASS.

BEGIN;

-- Step 1: Add NULL-allowed columns.
ALTER TABLE daily_reports
    ADD COLUMN is_hidden BOOLEAN;

ALTER TABLE daily_reports
    ADD COLUMN hidden_at TIMESTAMPTZ;

ALTER TABLE daily_reports
    ADD COLUMN hidden_reason VARCHAR(50);

-- Step 2: Backfill all existing reports as visible.
UPDATE daily_reports
   SET is_hidden = FALSE
 WHERE is_hidden IS NULL;

-- Step 3: Lock is_hidden down (NOT NULL + DEFAULT).
ALTER TABLE daily_reports
    ALTER COLUMN is_hidden SET NOT NULL;

ALTER TABLE daily_reports
    ALTER COLUMN is_hidden SET DEFAULT FALSE;

-- Step 4: Partial index for fast "visible reports" queries.
CREATE INDEX idx_reports_visible
    ON daily_reports(created_at DESC)
 WHERE is_hidden = FALSE;

-- Step 5: Comments.
COMMENT ON COLUMN daily_reports.is_hidden IS
    'PRD Patch #5: 소프트 삭제 플래그. DELETE 호출 시 true로 설정 (영구 보존, 목록에서만 숨김)';
COMMENT ON COLUMN daily_reports.hidden_at IS
    'PRD Patch #5: 숨김 처리 시각';
COMMENT ON COLUMN daily_reports.hidden_reason IS
    'PRD Patch #5: 숨김 사유 (USER_REQUEST / DUPLICATE / OUTDATED 등)';

COMMIT;
