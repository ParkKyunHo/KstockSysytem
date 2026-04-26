"""
Phase 6: wave_harvest_exit.py 단위 테스트 (V7.0)

Wave Harvest 청산 시스템의 R-Multiple, ATR 배수, Trend Hold Filter를 검증합니다.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.wave_harvest_exit import (
    WaveHarvestExit,
    PositionExitState,
    FIXED_STOP_PERCENT,
    ATR_MULT_DEFAULT,
    ATR_MULT_WARNING,
    ATR_MULT_1R,
    ATR_MULT_2R,
    ATR_MULT_3R,
    ATR_MULT_5R,
)


def create_sample_ohlcv(n_bars: int = 60, base_price: float = 10000, trend: float = 0) -> pd.DataFrame:
    """
    테스트용 OHLCV 데이터 생성

    Args:
        n_bars: 봉 개수
        base_price: 기준 가격
        trend: 추세 (양수: 상승, 음수: 하락)

    Returns:
        OHLCV DataFrame
    """
    np.random.seed(42)

    prices = base_price + np.cumsum(np.random.randn(n_bars) * 50 + trend)
    prices = np.maximum(prices, base_price * 0.8)  # 최소값 보장

    data = []
    for i, close in enumerate(prices):
        open_price = close + np.random.uniform(-30, 30)
        high = max(open_price, close) + np.random.uniform(0, 50)
        low = min(open_price, close) - np.random.uniform(0, 50)
        volume = int(np.random.uniform(50000, 150000))

        data.append({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    return pd.DataFrame(data)


def create_uptrend_ohlcv(n_bars: int = 60, base_price: float = 10000) -> pd.DataFrame:
    """상승 추세 데이터 생성"""
    return create_sample_ohlcv(n_bars, base_price, trend=10)


def create_downtrend_ohlcv(n_bars: int = 60, base_price: float = 10000) -> pd.DataFrame:
    """하락 추세 데이터 생성"""
    return create_sample_ohlcv(n_bars, base_price, trend=-10)


class TestPositionExitState:
    """PositionExitState 테스트"""

    def test_state_creation(self):
        """상태 생성 테스트"""
        state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
        )

        assert state.stock_code == "005930"
        assert state.entry_price == 10000
        assert state.current_multiplier == ATR_MULT_DEFAULT
        assert state.initial_risk == 10000 * FIXED_STOP_PERCENT

    def test_fallback_stop(self):
        """Fallback 손절가 테스트"""
        state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
        )

        fallback = state.get_fallback_stop()
        expected = int(10000 * (1 - FIXED_STOP_PERCENT))  # 9600
        assert fallback == expected

    def test_initial_trailing_stop(self):
        """초기 트레일링 스탑 테스트"""
        state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
        )

        # 초기 trailing_stop은 fallback과 동일
        assert state.trailing_stop == state.get_fallback_stop()


class TestWaveHarvestExit:
    """WaveHarvestExit 기본 기능 테스트"""

    def test_create_state(self):
        """상태 생성 테스트"""
        exit_mgr = WaveHarvestExit()
        state = exit_mgr.create_state("005930", 10000)

        assert state.stock_code == "005930"
        assert state.entry_price == 10000

    def test_calculate_base_price(self):
        """고점 기준가 계산 테스트"""
        exit_mgr = WaveHarvestExit(base_price_period=20)
        df = create_sample_ohlcv(30)

        base_price = exit_mgr.calculate_base_price(df)

        # 최근 20봉 중 최고가와 동일해야 함
        expected = int(df['high'].rolling(20).max().iloc[-1])
        assert base_price == expected

    def test_calculate_atr(self):
        """ATR 계산 테스트"""
        exit_mgr = WaveHarvestExit(atr_period=10)
        df = create_sample_ohlcv(30)

        atr = exit_mgr.calculate_atr(df)

        assert atr > 0
        assert isinstance(atr, float)

    def test_calculate_trailing_stop(self):
        """트레일링 스탑 계산 테스트"""
        exit_mgr = WaveHarvestExit()

        base_price = 10000
        atr = 200
        multiplier = 6.0

        stop = exit_mgr.calculate_trailing_stop(base_price, atr, multiplier)

        # 10000 - 200 × 6 = 8800
        assert stop == 8800


class TestRMultiple:
    """R-Multiple 테스트"""

    def test_r_multiple_breakeven(self):
        """R=0 (손익분기) 테스트"""
        exit_mgr = WaveHarvestExit()

        R = exit_mgr.calculate_r_multiple(current_price=10000, entry_price=10000)
        assert R == 0.0

    def test_r_multiple_1r_profit(self):
        """R=1 (1R 수익) 테스트"""
        exit_mgr = WaveHarvestExit()

        # entry=10000, 4% = 400, so +400 = 1R
        R = exit_mgr.calculate_r_multiple(current_price=10400, entry_price=10000)
        assert R == 1.0

    def test_r_multiple_2r_profit(self):
        """R=2 (2R 수익) 테스트"""
        exit_mgr = WaveHarvestExit()

        R = exit_mgr.calculate_r_multiple(current_price=10800, entry_price=10000)
        assert R == 2.0

    def test_r_multiple_loss(self):
        """손실 시 R-Multiple 테스트"""
        exit_mgr = WaveHarvestExit()

        R = exit_mgr.calculate_r_multiple(current_price=9800, entry_price=10000)
        assert R == -0.5  # -200 / 400 = -0.5


class TestMultiplierReduction:
    """ATR 배수 단방향 축소 테스트"""

    def test_initial_multiplier(self):
        """초기 배수 테스트"""
        exit_mgr = WaveHarvestExit()

        mult = exit_mgr.get_multiplier(
            r_multiple=0,
            structure_warning=False,
            current_mult=ATR_MULT_DEFAULT
        )

        assert mult == ATR_MULT_DEFAULT

    def test_structure_warning_reduction(self):
        """구조 경고 시 배수 축소 테스트"""
        exit_mgr = WaveHarvestExit()

        mult = exit_mgr.get_multiplier(
            r_multiple=0,
            structure_warning=True,
            current_mult=ATR_MULT_DEFAULT
        )

        assert mult == ATR_MULT_WARNING  # 6.0 → 4.5

    def test_1r_reduction(self):
        """R>=1 배수 축소 테스트"""
        exit_mgr = WaveHarvestExit()

        mult = exit_mgr.get_multiplier(
            r_multiple=1.0,
            structure_warning=False,
            current_mult=ATR_MULT_DEFAULT
        )

        assert mult == ATR_MULT_1R  # 4.0

    def test_progressive_reduction(self):
        """점진적 배수 축소 테스트"""
        exit_mgr = WaveHarvestExit()

        # R=2 -> 3.5
        mult = exit_mgr.get_multiplier(r_multiple=2.0, structure_warning=False, current_mult=6.0)
        assert mult == ATR_MULT_2R

        # R=3 -> 2.5
        mult = exit_mgr.get_multiplier(r_multiple=3.0, structure_warning=False, current_mult=3.5)
        assert mult == ATR_MULT_3R

        # R=5+ -> 2.0
        mult = exit_mgr.get_multiplier(r_multiple=5.0, structure_warning=False, current_mult=2.5)
        assert mult == ATR_MULT_5R

    def test_no_multiplier_increase(self):
        """배수 재증가 불가 테스트"""
        exit_mgr = WaveHarvestExit()

        # 이미 3.5인데 R이 1로 떨어져도 4.0으로 증가하지 않음
        mult = exit_mgr.get_multiplier(
            r_multiple=1.0,  # 이론적으로는 4.0이어야 하지만
            structure_warning=False,
            current_mult=3.5  # 이미 3.5이면 유지 (최소값 적용)
        )

        # min(3.5, 4.0) = 3.5 유지
        assert mult == 3.5


class TestStopDirection:
    """스탑 상향 단방향 테스트"""

    def test_stop_increase(self):
        """스탑 상승 테스트"""
        exit_mgr = WaveHarvestExit()

        new_stop = exit_mgr.update_stop(new_stop=9800, prev_stop=9500)
        assert new_stop == 9800  # 상승 허용

    def test_stop_no_decrease(self):
        """스탑 하락 불가 테스트"""
        exit_mgr = WaveHarvestExit()

        new_stop = exit_mgr.update_stop(new_stop=9500, prev_stop=9800)
        assert new_stop == 9800  # 하락 불가, 이전 값 유지

    def test_stop_same_value(self):
        """동일 값 유지 테스트"""
        exit_mgr = WaveHarvestExit()

        new_stop = exit_mgr.update_stop(new_stop=9500, prev_stop=9500)
        assert new_stop == 9500


class TestTrendHoldFilter:
    """Trend Hold Filter 테스트"""

    def test_trend_hold_in_uptrend(self):
        """상승 추세 시 Trend Hold 테스트"""
        exit_mgr = WaveHarvestExit()
        df = create_uptrend_ohlcv(80)

        # 강한 상승 추세에서는 Trend Hold 가능
        trend_hold = exit_mgr.check_trend_hold(df)
        # 결과는 데이터에 따라 다를 수 있음 (True 또는 False)
        assert isinstance(trend_hold, bool)

    def test_trend_hold_insufficient_data(self):
        """데이터 부족 시 Trend Hold 테스트"""
        exit_mgr = WaveHarvestExit()
        df = create_sample_ohlcv(20)  # 짧은 데이터

        trend_hold = exit_mgr.check_trend_hold(df)
        assert trend_hold is False  # 데이터 부족 시 False


class TestExitConditions:
    """청산 조건 테스트"""

    def test_should_exit_below_stop(self):
        """스탑 이탈 청산 테스트"""
        exit_mgr = WaveHarvestExit()

        # Trend Hold 아닐 때 스탑 이탈 -> 청산
        should_exit = exit_mgr.should_exit(
            close=9500,
            trailing_stop=9600,
            trend_hold=False
        )
        assert should_exit is True

    def test_should_exit_above_stop(self):
        """스탑 위 유지 테스트"""
        exit_mgr = WaveHarvestExit()

        should_exit = exit_mgr.should_exit(
            close=9700,
            trailing_stop=9600,
            trend_hold=False
        )
        assert should_exit is False

    def test_should_exit_blocked_by_trend_hold(self):
        """Trend Hold 시 청산 차단 테스트"""
        exit_mgr = WaveHarvestExit()

        # 스탑 이탈이지만 Trend Hold 중이면 청산 안 함
        should_exit = exit_mgr.should_exit(
            close=9500,
            trailing_stop=9600,
            trend_hold=True  # Trend Hold 중
        )
        assert should_exit is False


class TestHardStop:
    """고정 손절 테스트"""

    def test_hard_stop_triggered(self):
        """고정 손절 발동 테스트"""
        exit_mgr = WaveHarvestExit()

        # 10000의 -4% = 9600 미만이면 손절
        should_stop = exit_mgr.check_hard_stop(
            current_price=9500,
            entry_price=10000
        )
        assert should_stop is True

    def test_hard_stop_not_triggered(self):
        """고정 손절 미발동 테스트"""
        exit_mgr = WaveHarvestExit()

        should_stop = exit_mgr.check_hard_stop(
            current_price=9700,
            entry_price=10000
        )
        assert should_stop is False


class TestMaxHoldingDays:
    """최대 보유일 테스트"""

    def test_within_holding_period(self):
        """보유 기간 내 테스트"""
        exit_mgr = WaveHarvestExit()

        entry_date = datetime.now() - timedelta(days=30)
        should_exit = exit_mgr.check_max_holding_days(entry_date, max_days=60)

        assert should_exit is False

    def test_exceeded_holding_period(self):
        """보유 기간 초과 테스트"""
        exit_mgr = WaveHarvestExit()

        entry_date = datetime.now() - timedelta(days=65)
        should_exit = exit_mgr.check_max_holding_days(entry_date, max_days=60)

        assert should_exit is True


class TestUpdateAndCheck:
    """통합 업데이트 및 청산 체크 테스트"""

    def test_update_and_check_no_exit(self):
        """청산 없는 업데이트 테스트"""
        exit_mgr = WaveHarvestExit()
        df = create_uptrend_ohlcv(60)
        state = exit_mgr.create_state("005930", 10000)

        should_exit, reason = exit_mgr.update_and_check(
            state, df, current_price=10500
        )

        assert should_exit is False
        assert reason == ""
        assert state.r_multiple > 0  # 수익 상태

    def test_update_and_check_fallback(self):
        """Fallback 손절 테스트"""
        exit_mgr = WaveHarvestExit()
        df = create_sample_ohlcv(60)
        state = exit_mgr.create_state("005930", 10000)

        # 큰 손실
        should_exit, reason = exit_mgr.update_and_check(
            state, df, current_price=9000
        )

        assert should_exit is True
        # ATR_TS_x.xx 또는 STOP/FALLBACK 형태의 reason
        assert "ATR_TS" in reason or "STOP" in reason or "FALLBACK" in reason

    def test_update_with_insufficient_data(self):
        """데이터 부족 시 테스트"""
        exit_mgr = WaveHarvestExit()
        df = create_sample_ohlcv(10)  # 데이터 부족
        state = exit_mgr.create_state("005930", 10000)

        # 손실이 아니면 유지
        should_exit, reason = exit_mgr.update_and_check(
            state, df, current_price=10500
        )

        assert should_exit is False

    def test_state_updates_correctly(self):
        """상태 업데이트 테스트"""
        exit_mgr = WaveHarvestExit()
        df = create_uptrend_ohlcv(60, base_price=10000)
        state = exit_mgr.create_state("005930", 10000)

        initial_ts = state.trailing_stop

        # 큰 수익 상태로 업데이트
        exit_mgr.update_and_check(state, df, current_price=12000)

        # 상태가 업데이트되었는지 확인
        assert state.r_multiple > 0
        assert state.highest_high > state.entry_price


class TestExitSummary:
    """청산 상태 요약 테스트"""

    def test_exit_summary(self):
        """상태 요약 테스트"""
        exit_mgr = WaveHarvestExit()
        state = PositionExitState(
            stock_code="005930",
            entry_price=10000,
            highest_high=10500,
            trailing_stop=9800,
            current_multiplier=4.0,
            r_multiple=1.5,
        )

        summary = exit_mgr.get_exit_summary(state, current_price=10600)

        assert summary["stock_code"] == "005930"
        assert summary["entry_price"] == 10000
        assert summary["current_price"] == 10600
        assert summary["profit_pct"] == 6.0  # (10600-10000)/10000 * 100
        assert summary["r_multiple"] == 1.5
        assert summary["atr_multiplier"] == 4.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
