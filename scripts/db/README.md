# V7.1 DB Migration Bundle

> 새 Supabase 프로젝트에 V7.1 스키마 + PRD Patch #5 (V7.1.0d) 일괄 적용 가이드

## 파일

- `v71_full_schema_2026-04-27.sql` — 마이그레이션 000~020 통합 (991 라인)
  - 000~017: V7.1 기본 스키마 (사용자 / 추적 / 박스 / 포지션 / 거래 이벤트 / 알림 / 리포트 / 시스템 / Patch #3)
  - 018~020: ★ PRD Patch #5 (v71_orders 신규 + positions.current_price + daily_reports.is_hidden)

## 적용 방법 (3가지 옵션)

### 옵션 A: Supabase Dashboard SQL Editor (권장 — 가장 안전)

1. Supabase Dashboard 로그인 (https://supabase.com/dashboard)
2. 프로젝트 선택: `wlkcuqfflmdshpzbfndz` (.env의 SUPABASE_URL)
3. 좌측 메뉴 → **SQL Editor**
4. **New Query** → `v71_full_schema_2026-04-27.sql` 내용 붙여넣기
5. **Run** 실행
6. 검증 (실행 후 같은 Editor에서):
   ```sql
   SELECT table_name FROM information_schema.tables
   WHERE table_schema='public' ORDER BY table_name;
   ```
   기대 결과 (17개 테이블):
   ```
   audit_logs / daily_reports / market_calendar / monthly_reviews / notifications /
   positions / stocks / support_boxes / system_events / system_restarts /
   tracked_stocks / trade_events / user_sessions / user_settings / users /
   v71_orders / vi_events
   ```

### 옵션 B: Claude Code 재시작 + MCP OAuth (Claude가 직접 적용)

1. **Claude Code 종료 + 재시작** (`.mcp.json` 새 project_ref 적용을 위해 필수)
2. 새 세션에서 사용자가 다음 메시지로 작업 재개:
   > "Supabase MCP 인증해줘. 그 다음 scripts/db/v71_full_schema_2026-04-27.sql 적용"
3. Claude가 `mcp__supabase__authenticate` 호출 → 사용자가 브라우저 OAuth 완료
4. Claude가 MCP 도구로 SQL 실행

### 옵션 C: psql CLI (개발자 권장 — 로그 확인 가능)

```bash
# .env에서 DATABASE_URL 추출 (PowerShell)
$env:DB_URL = (Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''

# 적용
psql $env:DB_URL -f scripts/db/v71_full_schema_2026-04-27.sql

# 검증
psql $env:DB_URL -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
```

## Patch #5 신규 테이블/컬럼 (적용 후 확인)

| 항목 | 검증 SQL |
|------|----------|
| v71_orders 테이블 | `SELECT count(*) FROM information_schema.tables WHERE table_name='v71_orders';` → 1 |
| order_state ENUM | `SELECT enumlabel FROM pg_enum WHERE enumtypid='order_state'::regtype;` → 5 values |
| positions.current_price | `SELECT column_name FROM information_schema.columns WHERE table_name='positions' AND column_name='current_price';` → 1 row |
| daily_reports.is_hidden | `SELECT column_name FROM information_schema.columns WHERE table_name='daily_reports' AND column_name='is_hidden';` → 1 row |
| idx_reports_visible | `SELECT indexname FROM pg_indexes WHERE indexname='idx_reports_visible';` → 1 row |
| idx_v71_orders_state_pending | `SELECT indexname FROM pg_indexes WHERE indexname='idx_v71_orders_state_pending';` → 1 row |

## 롤백

마이그레이션을 되돌리려면 down SQL 역순 실행:

```bash
# 020 → 019 → 018 → 017 → ... → 000 순서
for f in $(ls -r src/database/migrations/v71/*.down.sql); do
  psql $DB_URL -f "$f"
done
```

또는 빈 프로젝트로 돌아가려면 Supabase Dashboard에서 새 프로젝트 재생성.

## 관련 PRD

- [03_DATA_MODEL.md](../../docs/v71/03_DATA_MODEL.md) — 모든 테이블 정의
- [13_APPENDIX.md §6.2.Z](../../docs/v71/13_APPENDIX.md) — PRD Patch #5 결정 이력
- [KIWOOM_API_ANALYSIS.md](../../docs/v71/KIWOOM_API_ANALYSIS.md) — 키움 18개 API 매핑

---

*최종 업데이트: 2026-04-27 (V7.1.0d, PRD Patch #5 적용)*
