"""
일일 리포트 테스트
"""

import asyncio
import sys
import io
from pathlib import Path
from datetime import date

# Windows 콘솔 인코딩 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def test_daily_report():
    """일일 리포트 테스트"""
    print("\n" + "=" * 50)
    print("일일 리포트 테스트")
    print("=" * 50)

    from src.database import init_database, close_database, get_trade_repository
    from src.notification.reporter import (
        DailyReporter,
        format_daily_report_detailed,
        format_weekly_summary,
    )

    await init_database()

    # 테스트 데이터 생성
    trade_repo = get_trade_repository()

    # 수익 거래 생성
    trade1 = await trade_repo.create(
        stock_code="005930",
        stock_name="삼성전자",
        strategy="CEILING_BREAK",
        entry_price=72000,
        entry_quantity=10,
        signal_strength=0.85,
    )
    await trade_repo.close(
        trade_id=trade1.id,
        exit_price=75000,
        exit_reason="TRAILING_STOP",
        max_profit_rate=5.5,
    )

    # 손실 거래 생성
    trade2 = await trade_repo.create(
        stock_code="000660",
        stock_name="SK하이닉스",
        strategy="SNIPER_TRAP",
        entry_price=120000,
        entry_quantity=5,
        signal_strength=0.7,
    )
    await trade_repo.close(
        trade_id=trade2.id,
        exit_price=116400,  # -3%
        exit_reason="HARD_STOP",
        max_loss_rate=-3.0,
    )

    # 리포터 생성
    reporter = DailyReporter()

    print("\n1. 일일 리포트 생성")
    print("-" * 40)

    report = await reporter.generate_report(date.today())

    print(f"  날짜: {report.date}")
    print(f"  총 거래: {report.total_trades}")
    print(f"  수익: {report.win_trades} / 손실: {report.loss_trades}")
    print(f"  승률: {report.win_rate:.1f}%")
    print(f"  순손익: {report.net_pnl:+,}원")
    print(f"  평균 보유: {report.avg_holding_minutes:.1f}분")

    print("\n2. 상세 리포트 출력")
    print("-" * 40)

    detailed = format_daily_report_detailed(report)
    print(detailed)

    print("\n3. 일일 통계 저장")
    print("-" * 40)

    await reporter.save_daily_stats(date.today())
    print("  저장 완료")

    print("\n4. 주간 요약")
    print("-" * 40)

    weekly = await reporter.generate_weekly_summary()
    weekly_text = format_weekly_summary(weekly)
    print(weekly_text)

    await close_database()
    print("\n[OK] 일일 리포트 테스트 성공")
    return True


async def main():
    """메인 테스트 함수"""
    print("\n" + "=" * 50)
    print("리포트 모듈 테스트")
    print("=" * 50)

    try:
        result = await test_daily_report()
        print(f"\n전체 결과: {'[OK] 성공' if result else '[FAIL] 실패'}")
        return result
    except Exception as e:
        print(f"[ERROR] 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
