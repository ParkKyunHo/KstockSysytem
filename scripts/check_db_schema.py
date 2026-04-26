#!/usr/bin/env python3
"""Add missing columns to trades table"""
import os
import asyncio
os.chdir('/home/ubuntu/K_stock_trading/current')

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from src.database.connection import get_db_manager

async def add_columns():
    db = get_db_manager()
    await db.initialize()
    async with db._session_factory() as session:
        # Add missing columns
        alter_statements = [
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_source VARCHAR(20) NOT NULL DEFAULT 'SYSTEM'",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS stop_loss_price INTEGER",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS is_partial_exit BOOLEAN DEFAULT FALSE",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_floor_line INTEGER",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS highest_price_after_partial INTEGER",
        ]

        for stmt in alter_statements:
            try:
                await session.execute(text(stmt))
                print(f"SUCCESS: {stmt[:50]}...")
            except Exception as e:
                print(f"ERROR: {stmt[:50]}... - {e}")

        await session.commit()

        # Verify
        result = await session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'trades' ORDER BY ordinal_position"))
        columns = result.fetchall()
        print('\nColumns in trades table after migration:')
        for col in columns:
            print(f'  - {col[0]}')
    await db.close()

if __name__ == "__main__":
    asyncio.run(add_columns())
