#!/usr/bin/env python3
"""Check database record counts"""
import os
import asyncio
os.chdir('/home/ubuntu/K_stock_trading/current')

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from src.database.connection import get_db_manager

async def check():
    db = get_db_manager()
    await db.initialize()
    async with db._session_factory() as session:
        # Count records
        print("=== DB Record Counts ===")
        for table in ["trades", "orders"]:
            r = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            print(f"{table}: {r.scalar()} rows")

        # Recent trades (if any)
        r = await session.execute(text("""
            SELECT id, stock_code, status, entry_source, created_at
            FROM trades
            ORDER BY created_at DESC
            LIMIT 5
        """))
        rows = r.fetchall()
        if rows:
            print("\n=== Recent Trades ===")
            for row in rows:
                print(f"  ID:{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]}")
        else:
            print("\n=== No trades in database ===")

    await db.close()

if __name__ == "__main__":
    asyncio.run(check())
