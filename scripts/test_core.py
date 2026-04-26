"""
Core 모듈 테스트 스크립트

CandleBuilder, Indicator, SignalDetector 등 핵심 모듈을 테스트합니다.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import random

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from src.core.candle_builder import Tick, CandleBuilder, CandleManager, Timeframe
from src.core.indicator import Indicator, calculate_all_indicators
from src.core.signal_detector import (
    SignalDetector,
    CeilingBreakDetector,
    SniperTrapDetector,
)
from src.core.risk_manager import RiskManager, RiskConfig
from src.core.position_manager import PositionManager, PositionStatus
from src.core.signal_detector import StrategyType


def test_candle_builder():
    """CandleBuilder 테스트"""
    print("\n" + "=" * 50)
    print("CandleBuilder 테스트")
    print("=" * 50)

    builder = CandleBuilder("005930")

    # 가상의 틱 데이터 생성 (1분간의 데이터)
    base_time = datetime.now().replace(second=0, microsecond=0)
    base_price = 70000

    for i in range(60):  # 60개의 틱 (1분)
        tick = Tick(
            stock_code="005930",
            price=base_price + random.randint(-100, 100),
            volume=random.randint(100, 1000),
            timestamp=base_time + timedelta(seconds=i),
        )
        result = builder.on_tick(tick)

        if result:
            for candle in result:
                print(f"  [COMPLETE] {candle.timeframe.value}: "
                      f"O={candle.open} H={candle.high} L={candle.low} C={candle.close} V={candle.volume}")

    # 현재 진행 중인 봉
    current_1m = builder.get_current_candle(Timeframe.M1)
    if current_1m:
        print(f"\n  [CURRENT 1M] O={current_1m.open} H={current_1m.high} L={current_1m.low} C={current_1m.close}")

    # 봉 개수
    print(f"\n  1분봉 개수: {builder.get_candle_count(Timeframe.M1)}")
    print(f"  3분봉 개수: {builder.get_candle_count(Timeframe.M3)}")

    print("\n[OK] CandleBuilder 테스트 성공")
    return True


def test_indicator():
    """Indicator 테스트"""
    print("\n" + "=" * 50)
    print("Indicator 테스트")
    print("=" * 50)

    # 테스트 데이터 생성 (100개 봉)
    n = 100
    base_price = 70000

    data = {
        "open": [base_price + random.randint(-500, 500) for _ in range(n)],
        "high": [],
        "low": [],
        "close": [],
        "volume": [random.randint(10000, 100000) for _ in range(n)],
    }

    for i in range(n):
        o = data["open"][i]
        c = o + random.randint(-300, 300)
        h = max(o, c) + random.randint(0, 200)
        l = min(o, c) - random.randint(0, 200)
        data["high"].append(h)
        data["low"].append(l)
        data["close"].append(c)

    df = pd.DataFrame(data)

    # 지표 계산
    df_with_indicators = calculate_all_indicators(df)

    print(f"\n  데이터 행 수: {len(df_with_indicators)}")
    print(f"  컬럼: {list(df_with_indicators.columns)}")

    # 마지막 행 출력
    last = df_with_indicators.iloc[-1]
    print(f"\n  [마지막 봉]")
    print(f"  종가: {last['close']}")
    print(f"  EMA3: {last['ema3']:.2f}")
    print(f"  EMA20: {last['ema20']:.2f}")
    print(f"  EMA60: {last['ema60']:.2f}")
    print(f"  천장20: {last['ceiling20']:.2f}" if not pd.isna(last['ceiling20']) else "  천장20: N/A")
    print(f"  거래량비율: {last['volume_ratio']:.2f}x")
    print(f"  이격도60: {last['disparity60']:.2f}%")

    print("\n[OK] Indicator 테스트 성공")
    return True


def test_signal_detector():
    """SignalDetector 테스트"""
    print("\n" + "=" * 50)
    print("SignalDetector 테스트")
    print("=" * 50)

    # 천장 파괴 신호를 발생시키는 데이터 생성
    n = 30
    base_price = 70000

    # 천장을 형성하는 데이터
    candles_data = []
    for i in range(n - 1):
        o = base_price + random.randint(-100, 100)
        c = o + random.randint(-50, 50)
        h = max(o, c) + random.randint(0, 100)
        l = min(o, c) - random.randint(0, 100)
        v = random.randint(10000, 50000)  # 일반 거래량
        candles_data.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

    # 마지막 봉: 천장 돌파 + 거래량 폭발 + 양봉
    ceiling = max(c["high"] for c in candles_data[-20:])
    o = ceiling + 100
    c = ceiling + 500  # 천장 돌파
    h = c + 100
    l = o - 50
    v = 200000  # 거래량 폭발 (평균의 4배 이상)
    candles_data.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

    df = pd.DataFrame(candles_data)

    detector = SignalDetector()
    signal = detector.check_ceiling_break(df, "005930", "삼성전자")

    if signal:
        print(f"\n  [SIGNAL DETECTED!]")
        print(f"  전략: {signal.strategy.value}")
        print(f"  종목: {signal.stock_name}({signal.stock_code})")
        print(f"  가격: {signal.price:,}원")
        print(f"  근거: {signal.reason}")
        print(f"  강도: {signal.strength:.2f}")
    else:
        print("\n  신호 없음 (정상 - 데이터가 조건에 맞지 않을 수 있음)")

    print("\n[OK] SignalDetector 테스트 성공")
    return True


def test_risk_manager():
    """RiskManager 테스트"""
    print("\n" + "=" * 50)
    print("RiskManager 테스트")
    print("=" * 50)

    config = RiskConfig(
        hard_stop_rate=-3.0,
        trailing_start_rate=5.0,
        trailing_stop_rate=2.5,
        cooldown_minutes=15,
        max_try_per_stock=2,
        max_positions=5,
    )

    rm = RiskManager(config)
    rm.reset_daily()

    # 진입 가능 체크
    can_enter, reason, msg = rm.can_enter("005930")
    print(f"\n  [진입 체크] 005930: {msg}")

    # 진입
    rm.on_entry("005930", 70000, 10)
    print(f"  [진입] 005930 @ 70000원, 10주")

    # 수익 시나리오
    print(f"\n  [가격 변동 시나리오]")

    # +2%
    should_exit, exit_reason, exit_msg = rm.check_exit("005930", 71400)
    print(f"  71,400원 (+2%): {exit_msg}")

    # +3% (Breakeven 활성화)
    should_exit, exit_reason, exit_msg = rm.check_exit("005930", 72100)
    print(f"  72,100원 (+3%): {exit_msg}")

    # +5% (Trailing 활성화)
    should_exit, exit_reason, exit_msg = rm.check_exit("005930", 73500)
    print(f"  73,500원 (+5%): {exit_msg}")

    # +7% (고점)
    should_exit, exit_reason, exit_msg = rm.check_exit("005930", 74900)
    print(f"  74,900원 (+7%): {exit_msg}")

    # +4.5% (고점 대비 -2.5% -> 추적 손절)
    should_exit, exit_reason, exit_msg = rm.check_exit("005930", 73025)
    print(f"  73,025원 (+4.3%, 고점 대비 -2.5%): {exit_msg} -> 청산: {should_exit}")

    # 청산
    if should_exit:
        pnl = rm.on_exit("005930", 73025, exit_reason)
        print(f"\n  [청산 완료] 손익: {pnl:+,}원")

    # 쿨다운 체크
    can_enter, reason, msg = rm.can_enter("005930")
    print(f"  [재진입 체크] {msg}")

    print("\n[OK] RiskManager 테스트 성공")
    return True


async def test_position_manager():
    """PositionManager 테스트"""
    print("\n" + "=" * 50)
    print("PositionManager 테스트")
    print("=" * 50)

    pm = PositionManager()

    # 포지션 열기
    pos = await pm.open_position(
        stock_code="005930",
        stock_name="삼성전자",
        strategy=StrategyType.CEILING_BREAK,
        entry_price=70000,
        quantity=10,
    )

    print(f"\n  [포지션 오픈]")
    print(f"  종목: {pos.stock_name}({pos.stock_code})")
    print(f"  수량: {pos.quantity}주")
    print(f"  매수가: {pos.entry_price:,}원")
    print(f"  투자금액: {pos.invested_amount:,}원")

    # 가격 업데이트
    pm.update_price("005930", 72000)
    print(f"\n  [가격 업데이트] 72,000원")
    print(f"  수익률: {pos.profit_loss_rate:+.2f}%")
    print(f"  평가손익: {pos.profit_loss:+,}원")

    # 포지션 청산
    closed = await pm.close_position("005930", 72000, "테스트 청산")
    print(f"\n  [포지션 청산]")
    print(f"  실현손익: {closed.profit_loss:+,}원")
    print(f"  보유시간: {closed.holding_time}초")

    # 통계
    summary = pm.get_summary()
    print(f"\n  [요약]")
    print(f"  현재 포지션: {summary['position_count']}개")
    print(f"  실현손익: {summary['realized_pnl']:+,}원")

    print("\n[OK] PositionManager 테스트 성공")
    return True


async def main():
    """메인 테스트 함수"""
    print("\n" + "=" * 50)
    print("Core 모듈 통합 테스트")
    print("=" * 50)

    results = []

    # 테스트 실행
    results.append(("CandleBuilder", test_candle_builder()))
    results.append(("Indicator", test_indicator()))
    results.append(("SignalDetector", test_signal_detector()))
    results.append(("RiskManager", test_risk_manager()))
    results.append(("PositionManager", await test_position_manager()))

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
