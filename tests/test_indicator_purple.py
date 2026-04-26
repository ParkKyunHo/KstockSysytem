"""
Phase 1: indicator_purple.py 단위 테스트 (V7.0)

Purple-ReAbs 지표 계산 모듈의 정확성을 검증합니다.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.indicator_purple import (
    PurpleIndicator,
    calculate_purple_indicators,
    MIN_RISE_PCT,
    MAX_CONVERGENCE_PCT,
    MIN_BAR_VALUE,
)


def create_sample_ohlcv(n_bars: int = 60, seed: int = 42) -> pd.DataFrame:
    """
    테스트용 샘플 OHLCV 데이터 생성

    Args:
        n_bars: 생성할 봉 개수
        seed: 랜덤 시드

    Returns:
        OHLCV DataFrame
    """
    np.random.seed(seed)

    # 기준 가격 (추세 + 노이즈)
    base_price = 10000
    trend = np.linspace(0, 500, n_bars)  # 상승 추세
    noise = np.random.normal(0, 100, n_bars)
    close_prices = base_price + trend + noise

    # OHLCV 생성
    data = []
    for i, close in enumerate(close_prices):
        open_price = close + np.random.uniform(-50, 50)
        high = max(open_price, close) + np.random.uniform(0, 100)
        low = min(open_price, close) - np.random.uniform(0, 100)
        volume = int(np.random.uniform(50000, 200000))

        data.append({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    return pd.DataFrame(data)


def create_purple_ok_data() -> pd.DataFrame:
    """
    PurpleOK 조건을 충족하는 테스트 데이터 생성

    - 상승률 >= 4%: H1/L1 - 1 >= 0.04
    - 수렴률 <= 7%: H2/L2 - 1 <= 0.07
    - 거래대금 >= 5억
    """
    n_bars = 60

    # 기본 가격 (10000원 기준)
    base_price = 10000

    # 초반 20봉: 저점 형성 (9500원대)
    # 중반 20봉: 상승 (9800 → 10200)
    # 후반 20봉: 수렴 (10100~10300, 변동폭 2%)

    prices = []
    # 초반: 저점 9500
    for i in range(20):
        prices.append(9500 + i * 10)  # 9500 → 9690
    # 중반: 상승
    for i in range(20):
        prices.append(9700 + i * 25)  # 9700 → 10175
    # 후반: 수렴 (10100 ~ 10300)
    for i in range(20):
        prices.append(10100 + (i % 5) * 40)  # 10100 ~ 10260 반복

    data = []
    for i, close in enumerate(prices):
        open_price = close - 20
        high = close + 50
        low = close - 30

        # 거래대금 5억 이상 되도록 volume 설정
        # money = close * volume >= 5억
        # volume >= 5억 / close ≈ 50000 (close ≈ 10000일 때)
        volume = int(600_000_000 / close)  # 거래대금 약 6억

        data.append({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    return pd.DataFrame(data)


class TestPurpleIndicatorBasics:
    """기본 지표 계산 테스트"""

    def test_ema_calculation(self):
        """EMA 계산 테스트"""
        df = create_sample_ohlcv(30)
        ema3 = PurpleIndicator.ema(df['close'], span=3)

        assert len(ema3) == len(df)
        assert not ema3.isna().all()
        # EMA는 adjust=False이므로 첫 값부터 계산됨
        assert not pd.isna(ema3.iloc[0])

    def test_money_calculation(self):
        """거래대금 계산 테스트"""
        df = create_sample_ohlcv(10)
        M = PurpleIndicator.money(df)

        # M = close × volume
        expected = df['close'] * df['volume']
        pd.testing.assert_series_equal(M, expected)

    def test_weighted_price_calculation(self):
        """가중평균가격 계산 테스트"""
        df = create_sample_ohlcv(50)
        W = PurpleIndicator.weighted_price(df, period=40)

        # NaN 체크 (첫 39봉은 NaN)
        assert W.iloc[:39].isna().all()
        assert not W.iloc[39:].isna().any()

        # W는 종가 범위 내에 있어야 함
        valid_W = W.dropna()
        assert (valid_W >= df['close'].min() * 0.9).all()
        assert (valid_W <= df['close'].max() * 1.1).all()


class TestPurpleIndicatorAdvanced:
    """고급 지표 계산 테스트"""

    def test_log_normalized(self):
        """로그 정규화 테스트"""
        df = create_sample_ohlcv(30)
        LG = PurpleIndicator.log_normalized(df)

        assert len(LG) == len(df)
        assert not LG.isna().any()
        # LG는 log(M / range)이므로 큰 양수 또는 음수 가능
        assert LG.dtype == np.float64

    def test_fund_zscore(self):
        """자금 Z-Score 테스트"""
        df = create_sample_ohlcv(50)
        LZ = PurpleIndicator.fund_zscore(df, period=20)

        # Z-Score는 대략 -3 ~ +3 범위 (이상치 제외)
        # 단, 금융 데이터는 더 넓을 수 있음
        valid_LZ = LZ.dropna()
        assert len(valid_LZ) > 0

    def test_h1l1_h2l2_calculation(self):
        """H1L1/H2L2 계산 테스트"""
        df = create_sample_ohlcv(50)

        H1, L1 = PurpleIndicator.h1l1(df, period=40)
        H2, L2 = PurpleIndicator.h2l2(df, period=20)

        # H1 >= L1, H2 >= L2
        valid_idx = ~(H1.isna() | L1.isna())
        assert (H1[valid_idx] >= L1[valid_idx]).all()

        valid_idx2 = ~(H2.isna() | L2.isna())
        assert (H2[valid_idx2] >= L2[valid_idx2]).all()

    def test_score_calculation(self):
        """Score 계산 테스트"""
        df = create_sample_ohlcv(60)
        S = PurpleIndicator.score(df, smooth_period=10)

        assert len(S) == len(df)
        # Score 유효성 (NaN 아닌 값 존재)
        valid_S = S.dropna()
        assert len(valid_S) > 0


class TestPurpleOK:
    """PurpleOK 필터 테스트"""

    def test_purple_ok_conditions(self):
        """PurpleOK 조건 테스트"""
        df = create_purple_ok_data()

        # 개별 조건 확인
        rise = PurpleIndicator.rise_ratio(df)
        convergence = PurpleIndicator.convergence_ratio(df)
        M = PurpleIndicator.money(df)

        # 마지막 봉 기준 검증
        last_rise = rise.iloc[-1]
        last_convergence = convergence.iloc[-1]
        last_money = M.iloc[-1]

        print(f"Rise ratio: {last_rise:.4f} (min: {MIN_RISE_PCT})")
        print(f"Convergence ratio: {last_convergence:.4f} (max: {MAX_CONVERGENCE_PCT})")
        print(f"Money: {last_money:,.0f} (min: {MIN_BAR_VALUE:,.0f})")

        # 거래대금 확인
        assert last_money >= MIN_BAR_VALUE, f"Money {last_money} < {MIN_BAR_VALUE}"

    def test_purple_ok_combined(self):
        """PurpleOK 통합 필터 테스트"""
        df = create_sample_ohlcv(60)
        purple_ok = PurpleIndicator.purple_ok(df)

        assert len(purple_ok) == len(df)
        # bool 시리즈 확인
        assert purple_ok.dtype == bool


class TestReAbsorption:
    """Re-Absorption 테스트"""

    def test_reabs_start(self):
        """Re-Absorption 시작 감지 테스트"""
        # 상승하는 Score 시리즈
        scores = pd.Series([0.1, 0.2, 0.15, 0.3, 0.4, 0.35, 0.5])
        reabs = PurpleIndicator.reabs_start(scores)

        # Score 상승한 봉: idx 1, 3, 4, 6
        expected = pd.Series([False, True, False, True, True, False, True])

        # 첫 번째 값은 이전 값이 없으므로 False (NaN 비교)
        assert reabs.iloc[1] == True   # 0.1 → 0.2 상승
        assert reabs.iloc[2] == False  # 0.2 → 0.15 하락
        assert reabs.iloc[3] == True   # 0.15 → 0.3 상승

    def test_landing_zone(self):
        """Landing Zone 판단 테스트"""
        close = pd.Series([10000, 9960, 9940, 10050, 9990])
        ema60 = pd.Series([10000, 10000, 10000, 10000, 10000])

        zone = PurpleIndicator.is_landing_zone(close, ema60, tolerance=0.005)

        # C >= EMA60 × 0.995 (= 9950)
        # 10000 >= 9950: True
        # 9960 >= 9950: True
        # 9940 >= 9950: False
        # 10050 >= 9950: True
        # 9990 >= 9950: True
        expected = pd.Series([True, True, False, True, True])
        pd.testing.assert_series_equal(zone, expected)

    def test_crossup(self):
        """CrossUp 테스트"""
        close = pd.Series([100, 95, 98, 102, 101])
        ema3 = pd.Series([99, 97, 99, 100, 101])

        crossup = PurpleIndicator.crossup(close, ema3)

        # idx 0: 이전 없음 → False
        # idx 1: 100>99 → 95<97 → 하향 돌파 아님, 상향 돌파 아님 → False
        # idx 2: 95<97 → 98<99 → 아직 아래 → False
        # idx 3: 98<99 → 102>=100 → 상향 돌파 → True
        # idx 4: 102>=100 → 101>=101 → 이미 위 → False
        assert crossup.iloc[3] == True
        assert crossup.iloc[4] == False


class TestCalculateAllIndicators:
    """calculate_purple_indicators 통합 테스트"""

    def test_all_columns_created(self):
        """모든 지표 컬럼이 생성되는지 테스트"""
        df = create_sample_ohlcv(60)
        result = calculate_purple_indicators(df)

        expected_columns = [
            'ema3', 'ema20', 'ema60',
            'weighted_price', 'log_normalized', 'fund_zscore', 'score',
            'h1', 'l1', 'rise_ratio',
            'h2', 'l2', 'convergence_ratio',
            'money', 'purple_ok', 'reabs_start', 'landing_zone',
            'crossup_ema3', 'is_bullish',
        ]

        for col in expected_columns:
            assert col in result.columns, f"Missing column: {col}"

    def test_original_columns_preserved(self):
        """원본 OHLCV 컬럼이 보존되는지 테스트"""
        df = create_sample_ohlcv(30)
        result = calculate_purple_indicators(df)

        for col in ['open', 'high', 'low', 'close', 'volume']:
            assert col in result.columns
            pd.testing.assert_series_equal(result[col], df[col])

    def test_no_inplace_modification(self):
        """원본 DataFrame이 수정되지 않는지 테스트"""
        df = create_sample_ohlcv(30)
        original_columns = list(df.columns)

        _ = calculate_purple_indicators(df)

        assert list(df.columns) == original_columns


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_minimum_data(self):
        """최소 데이터로 테스트 (40봉 - H1L1 기간)"""
        df = create_sample_ohlcv(40)
        result = calculate_purple_indicators(df)

        # 마지막 봉에서 유효한 값이 있어야 함
        assert not pd.isna(result['weighted_price'].iloc[-1])
        assert not pd.isna(result['score'].iloc[-1])

    def test_zero_volume(self):
        """거래량 0인 경우 처리"""
        df = create_sample_ohlcv(30)
        df.loc[10, 'volume'] = 0

        # 에러 없이 처리되어야 함
        result = calculate_purple_indicators(df)
        assert len(result) == len(df)

    def test_flat_price(self):
        """횡보장 (가격 변동 없음) 처리"""
        n_bars = 50
        df = pd.DataFrame({
            'open': [10000] * n_bars,
            'high': [10010] * n_bars,
            'low': [9990] * n_bars,
            'close': [10000] * n_bars,
            'volume': [100000] * n_bars,
        })

        result = calculate_purple_indicators(df)
        assert len(result) == n_bars

        # 수렴률은 매우 낮아야 함
        convergence = result['convergence_ratio'].iloc[-1]
        assert convergence < 0.01  # 1% 미만


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
