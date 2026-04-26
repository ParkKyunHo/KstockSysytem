"""API 잔고 조회 테스트"""
import asyncio
from src.api.client import KiwoomAPIClient
from src.api.endpoints.account import AccountAPI


async def test():
    client = KiwoomAPIClient()
    await client.initialize()
    account = AccountAPI(client)

    print("=== KRX 조회 ===")
    try:
        result = await account.get_positions(exchange="KRX")
        print(f"positions count: {len(result.positions)}")
        for p in result.positions:
            print(f"  {p.stock_code} {p.stock_name} qty={p.quantity}")
    except Exception as e:
        print(f"KRX Error: {e}")

    print("\n=== NXT 조회 ===")
    try:
        result = await account.get_positions(exchange="NXT")
        print(f"positions count: {len(result.positions)}")
        for p in result.positions:
            print(f"  {p.stock_code} {p.stock_name} qty={p.quantity}")
    except Exception as e:
        print(f"NXT Error: {e}")

    print("\n=== 통합 조회 ===")
    try:
        result = await account.get_positions()
        print(f"positions count: {len(result.positions)}")
        for p in result.positions:
            print(f"  {p.stock_code} {p.stock_name} qty={p.quantity}")
    except Exception as e:
        print(f"통합 Error: {e}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(test())
