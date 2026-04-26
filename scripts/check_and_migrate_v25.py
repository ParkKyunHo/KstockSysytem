"""
PRD v2.5 마이그레이션 스크립트
- DB 스키마 체크
- 신규 컬럼 추가
"""

import asyncio
import sys
sys.path.insert(0, "C:/K_stock_trading")

from sqlalchemy import text
from src.database.connection import get_db_manager


async def check_schema():
    """현재 trades 테이블 스키마 확인"""
    db = get_db_manager()

    print("=" * 60)
    print("현재 trades 테이블 스키마 확인")
    print("=" * 60)

    async with db.session() as session:
        # PostgreSQL: 컬럼 정보 조회
        result = await session.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'trades'
            ORDER BY ordinal_position
        """))

        columns = result.fetchall()

        print(f"\n{'컬럼명':<25} {'타입':<20} {'Nullable':<10} {'기본값'}")
        print("-" * 80)

        existing_columns = set()
        for col in columns:
            col_name, data_type, nullable, default = col
            existing_columns.add(col_name)
            print(f"{col_name:<25} {data_type:<20} {nullable:<10} {default or ''}")

        # PRD v2.5 컬럼 존재 여부 체크
        print("\n" + "=" * 60)
        print("PRD v2.5 컬럼 존재 여부")
        print("=" * 60)

        v25_columns = ['stop_loss_price', 'is_partial_exit', 'entry_floor_line']
        missing = []

        for col in v25_columns:
            status = "✅ 존재" if col in existing_columns else "❌ 없음"
            print(f"  {col}: {status}")
            if col not in existing_columns:
                missing.append(col)

        return missing


async def run_migration():
    """PRD v2.5 마이그레이션 실행"""
    db = get_db_manager()

    print("\n" + "=" * 60)
    print("PRD v2.5 마이그레이션 실행")
    print("=" * 60)

    migration_sql = """
    -- PRD v2.5: 기술적 손절 및 분할 매도 컬럼 추가
    ALTER TABLE trades
    ADD COLUMN IF NOT EXISTS stop_loss_price INTEGER,
    ADD COLUMN IF NOT EXISTS is_partial_exit BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS entry_floor_line INTEGER;

    -- 컬럼 설명 추가
    COMMENT ON COLUMN trades.stop_loss_price IS '기술적 손절 가격 - Floor Line (Lowest 20) 기반';
    COMMENT ON COLUMN trades.is_partial_exit IS '분할 매도 실행 여부 - +2.5% 도달 시 50% 매도 후 True';
    COMMENT ON COLUMN trades.entry_floor_line IS '진입 시점의 바닥 라인 (Floor Line) 기록용';

    -- 인덱스 추가
    CREATE INDEX IF NOT EXISTS ix_trades_stop_loss_price ON trades(stop_loss_price);
    CREATE INDEX IF NOT EXISTS ix_trades_is_partial_exit ON trades(is_partial_exit);
    """

    async with db.session() as session:
        try:
            await session.execute(text(migration_sql))
            await session.commit()
            print("\n✅ 마이그레이션 완료!")
        except Exception as e:
            print(f"\n❌ 마이그레이션 실패: {e}")
            raise


async def main():
    print("\n🔍 Supabase DB 스키마 체크 시작...\n")

    try:
        missing_columns = await check_schema()

        if missing_columns:
            print(f"\n⚠️  누락된 컬럼: {missing_columns}")
            print("\n마이그레이션을 진행합니다...")
            await run_migration()

            # 재확인
            print("\n🔍 마이그레이션 후 재확인...")
            await check_schema()
        else:
            print("\n✅ 모든 PRD v2.5 컬럼이 이미 존재합니다. 마이그레이션 불필요.")

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
