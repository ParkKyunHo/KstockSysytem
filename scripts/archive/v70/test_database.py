"""
데이터베이스 모듈 테스트

SQLite 폴백을 사용하여 테스트합니다.
"""

import asyncio
import sys
from pathlib import Path
from datetime import date, datetime

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def test_database_connection():
    """데이터베이스 연결 테스트"""
    print("\n" + "=" * 50)
    print("데이터베이스 연결 테스트")
    print("=" * 50)

    from src.database import init_database, close_database, get_db_manager

    # 초기화
    success = await init_database()
    assert success, "데이터베이스 초기화 실패"

    db = get_db_manager()
    print(f"  PostgreSQL: {db.is_postgres}")
    print(f"  초기화 완료: {db.is_initialized}")

    # 종료
    await close_database()
    print("\n[OK] 데이터베이스 연결 테스트 성공")
    return True


async def test_trade_repository():
    """TradeRepository 테스트"""
    print("\n" + "=" * 50)
    print("TradeRepository 테스트")
    print("=" * 50)

    from src.database import (
        init_database,
        close_database,
        get_trade_repository,
        TradeStatus,
    )

    await init_database()
    repo = get_trade_repository()

    # 1. 거래 생성
    print("\n1. 거래 생성")
    print("-" * 40)

    trade = await repo.create(
        stock_code="005930",
        stock_name="삼성전자",
        strategy="CEILING_BREAK",
        entry_price=72000,
        entry_quantity=10,
        entry_order_no="ORD001",
        entry_reason="천장 파괴 + 거래량 폭발",
        signal_strength=0.85,
    )

    print(f"  생성된 거래: {trade}")
    print(f"  ID: {trade.id}")
    print(f"  종목: {trade.stock_name}({trade.stock_code})")
    print(f"  매수가: {trade.entry_price:,}원")
    print(f"  수량: {trade.entry_quantity}주")
    print(f"  투자금액: {trade.entry_amount:,}원")
    print(f"  상태: {trade.status}")

    assert trade.id is not None
    assert trade.status == TradeStatus.OPEN

    # 2. 조회
    print("\n2. 거래 조회")
    print("-" * 40)

    fetched = await repo.get_by_id(trade.id)
    assert fetched is not None
    print(f"  조회 성공: {fetched.stock_code}")

    open_trades = await repo.get_open_trades()
    print(f"  열린 거래 수: {len(open_trades)}")

    # 3. 청산
    print("\n3. 거래 청산")
    print("-" * 40)

    closed = await repo.close(
        trade_id=trade.id,
        exit_price=75000,
        exit_order_no="ORD002",
        exit_reason="TRAILING_STOP",
        max_profit_rate=5.5,
        max_loss_rate=-0.5,
    )

    assert closed is not None
    print(f"  청산 완료: {closed.stock_code}")
    print(f"  매도가: {closed.exit_price:,}원")
    print(f"  실현손익: {closed.profit_loss:+,}원")
    print(f"  수익률: {closed.profit_loss_rate:+.2f}%")
    print(f"  보유시간: {closed.holding_seconds}초")
    print(f"  상태: {closed.status}")

    assert closed.status == TradeStatus.CLOSED
    assert closed.profit_loss == (75000 - 72000) * 10  # 30,000원

    # 4. 일일 요약
    print("\n4. 일일 요약")
    print("-" * 40)

    summary = await repo.get_daily_summary(date.today())
    print(f"  날짜: {summary['date']}")
    print(f"  거래 수: {summary['trade_count']}")
    print(f"  승리: {summary['win_count']}")
    print(f"  패배: {summary['loss_count']}")
    print(f"  총 손익: {summary['total_pnl']:+,}원")

    await close_database()
    print("\n[OK] TradeRepository 테스트 성공")
    return True


async def test_daily_stats_repository():
    """DailyStatsRepository 테스트"""
    print("\n" + "=" * 50)
    print("DailyStatsRepository 테스트")
    print("=" * 50)

    from src.database import (
        init_database,
        close_database,
        get_daily_stats_repository,
    )

    await init_database()
    repo = get_daily_stats_repository()

    # 오늘 통계 생성/업데이트
    stats = await repo.upsert(
        target_date=date.today(),
        stats={
            "trade_count": 5,
            "win_count": 3,
            "loss_count": 2,
            "total_profit": 150000,
            "total_loss": -50000,
            "net_pnl": 100000,
            "win_rate": 60.0,
            "signals_detected": 10,
            "signals_executed": 5,
            "signals_blocked": 3,
        }
    )

    print(f"  날짜: {stats.date}")
    print(f"  거래 수: {stats.trade_count}")
    print(f"  승률: {stats.win_rate}%")
    print(f"  순손익: {stats.net_pnl:+,}원")

    # 조회
    fetched = await repo.get_by_date(date.today())
    assert fetched is not None
    print(f"  조회 성공: {fetched.date}")

    await close_database()
    print("\n[OK] DailyStatsRepository 테스트 성공")
    return True


async def test_signal_repository():
    """SignalRepository 테스트"""
    print("\n" + "=" * 50)
    print("SignalRepository 테스트")
    print("=" * 50)

    from src.database import (
        init_database,
        close_database,
        get_signal_repository,
    )

    await init_database()
    repo = get_signal_repository()

    # 신호 기록
    signal1 = await repo.create(
        stock_code="005930",
        stock_name="삼성전자",
        strategy="CEILING_BREAK",
        signal_type="BUY",
        price=72000,
        strength=0.85,
        reason="20일 천장 돌파 + 거래량 4배",
        executed=True,
    )

    signal2 = await repo.create(
        stock_code="000660",
        stock_name="SK하이닉스",
        strategy="SNIPER_TRAP",
        signal_type="BUY",
        price=120000,
        strength=0.75,
        reason="저점 갱신 후 반등",
        executed=False,
        blocked_reason="쿨다운 중",
    )

    print(f"  신호1: {signal1.stock_name} - 실행됨")
    print(f"  신호2: {signal2.stock_name} - 차단됨 ({signal2.blocked_reason})")

    # 최근 신호 조회
    recent = await repo.get_recent(limit=10)
    print(f"  최근 신호 수: {len(recent)}")

    await close_database()
    print("\n[OK] SignalRepository 테스트 성공")
    return True


async def main():
    """메인 테스트 함수"""
    print("\n" + "=" * 50)
    print("데이터베이스 모듈 통합 테스트")
    print("=" * 50)

    results = []

    try:
        results.append(("연결", await test_database_connection()))
    except Exception as e:
        print(f"[ERROR] 연결 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        results.append(("연결", False))

    try:
        results.append(("TradeRepository", await test_trade_repository()))
    except Exception as e:
        print(f"[ERROR] TradeRepository 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        results.append(("TradeRepository", False))

    try:
        results.append(("DailyStatsRepository", await test_daily_stats_repository()))
    except Exception as e:
        print(f"[ERROR] DailyStatsRepository 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        results.append(("DailyStatsRepository", False))

    try:
        results.append(("SignalRepository", await test_signal_repository()))
    except Exception as e:
        print(f"[ERROR] SignalRepository 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        results.append(("SignalRepository", False))

    # 결과 요약
    print("\n" + "=" * 50)
    print("테스트 결과")
    print("=" * 50)

    for name, success in results:
        status = "[OK]" if success else "[FAIL]"
        print(f"  {name}: {status}")

    all_passed = all(r[1] for r in results)
    print(f"\n전체 결과: {'[OK] 모두 통과' if all_passed else '[FAIL] 일부 실패'}")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
