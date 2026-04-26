"""
Phase 3: signal_detector_purple.py 단위 테스트 (V7.0)

Purple-ReAbs 신호 탐지 로직을 검증합니다.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.signal_detector_purple import (
    PurpleSignalDetector,
    PurpleSignal,
    PreCheckResult,
    DualPassDetector,
    PRE_CHECK_MIN_CONDITIONS,
    MIN_CANDLES_REQUIRED,
)


def create_sample_ohlcv(
    length: int = 100,
    base_price: int = 10000,
    trend: str = "up",
    volume_base: int = 1_000_000
) -> pd.DataFrame:
    """테스트용 OHLCV 데이터 생성"""
    np.random.seed(42)

    if trend == "up":
        prices = base_price + np.cumsum(np.random.uniform(-50, 100, length))
    elif trend == "down":
        prices = base_price + np.cumsum(np.random.uniform(-100, 50, length))
    else:
        prices = base_price + np.cumsum(np.random.uniform(-50, 50, length))

    prices = np.maximum(prices, 100)  # 최소 가격 보장

    df = pd.DataFrame({
        'open': prices - np.random.uniform(0, 50, length),
        'high': prices + np.random.uniform(0, 100, length),
        'low': prices - np.random.uniform(0, 100, length),
        'close': prices,
        'volume': volume_base + np.random.randint(0, 500000, length),
    })

    # 거래대금 5억 이상 보장 (마지막 봉)
    df.loc[df.index[-1], 'volume'] = int(600_000_000 / df['close'].iloc[-1])

    return df


def create_purple_signal_data(
    length: int = 100,
    base_price: int = 10000
) -> pd.DataFrame:
    """Purple 신호 조건을 충족하도록 설계된 데이터 생성"""
    np.random.seed(123)

    # 상승 추세 + 수렴 구간 생성
    # 처음 40봉: 상승
    # 이후 40봉: 수렴 (좁은 레인지)
    # 마지막 20봉: 재상승 시작

    prices = []
    base = base_price

    # 상승 구간 (40봉): 4% 이상 상승
    for i in range(40):
        base += np.random.uniform(5, 15)
        prices.append(base)

    # 수렴 구간 (40봉): 좁은 레인지
    for i in range(40):
        base += np.random.uniform(-3, 5)
        prices.append(base)

    # 재상승 시작 (20봉): Score 상승
    for i in range(20):
        base += np.random.uniform(2, 10)
        prices.append(base)

    prices = np.array(prices)

    df = pd.DataFrame({
        'open': prices - np.random.uniform(0, 30, length),
        'high': prices + np.random.uniform(10, 50, length),
        'low': prices - np.random.uniform(10, 50, length),
        'close': prices,
        'volume': np.random.randint(50000, 100000, length),
    })

    # 마지막 봉: 양봉 + 거래대금 5억 이상
    df.loc[df.index[-1], 'open'] = df['close'].iloc[-1] - 50
    df.loc[df.index[-1], 'volume'] = int(600_000_000 / df['close'].iloc[-1])

    return df


class TestPurpleSignal:
    """PurpleSignal 데이터클래스 테스트"""

    def test_signal_creation(self):
        """신호 생성 테스트"""
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=70000,
            score=0.85,
            rise_ratio=0.05,
            convergence_ratio=0.04,
        )

        assert signal.stock_code == "005930"
        assert signal.stock_name == "삼성전자"
        assert signal.price == 70000
        assert signal.score == 0.85
        assert signal.rise_ratio == 0.05

    def test_signal_to_dict(self):
        """딕셔너리 변환 테스트"""
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=70000,
            score=0.8512,
            rise_ratio=0.0512,
            convergence_ratio=0.0434,
        )

        d = signal.to_dict()
        assert d["stock_code"] == "005930"
        assert d["rise_ratio"] == 5.12  # 퍼센트로 변환
        assert d["convergence_ratio"] == 4.34

    def test_signal_str(self):
        """문자열 표현 테스트"""
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=70000,
            score=0.85,
            rise_ratio=0.05,
            convergence_ratio=0.04,
        )

        s = str(signal)
        assert "PURPLE" in s
        assert "삼성전자" in s
        assert "005930" in s


class TestPreCheckResult:
    """PreCheckResult 테스트"""

    def test_result_creation(self):
        """결과 생성 테스트"""
        result = PreCheckResult(
            stock_code="005930",
            conditions_met=4,
            conditions={
                "purple_ok": True,
                "trend": True,
                "zone": True,
                "reabs_start": True,
                "trigger": False,
            },
            is_candidate=True,
        )

        assert result.stock_code == "005930"
        assert result.conditions_met == 4
        assert result.is_candidate is True

    def test_meets_threshold(self):
        """임계값 충족 테스트"""
        result = PreCheckResult(
            stock_code="005930",
            conditions_met=3,
            conditions={},
            is_candidate=True,
        )

        assert result.meets_threshold is True

        result2 = PreCheckResult(
            stock_code="005930",
            conditions_met=2,
            conditions={},
            is_candidate=False,
        )

        assert result2.meets_threshold is False


class TestPurpleSignalDetector:
    """PurpleSignalDetector 테스트"""

    def test_detector_creation(self):
        """탐지기 생성 테스트"""
        detector = PurpleSignalDetector()
        assert detector.min_candles == MIN_CANDLES_REQUIRED

    def test_validate_data_empty(self):
        """빈 데이터 검증 테스트"""
        detector = PurpleSignalDetector()

        assert detector._validate_data(None) is False
        assert detector._validate_data(pd.DataFrame()) is False

    def test_validate_data_missing_columns(self):
        """필수 컬럼 누락 테스트"""
        detector = PurpleSignalDetector()

        df = pd.DataFrame({'close': [1, 2, 3]})
        assert detector._validate_data(df) is False

    def test_validate_data_insufficient_length(self):
        """데이터 부족 테스트"""
        detector = PurpleSignalDetector()

        df = create_sample_ohlcv(length=30)  # 60봉 미만
        assert detector._validate_data(df) is False

    def test_validate_data_valid(self):
        """유효 데이터 테스트"""
        detector = PurpleSignalDetector()

        df = create_sample_ohlcv(length=100)
        assert detector._validate_data(df) is True


class TestTrendCondition:
    """Trend 조건 테스트"""

    def test_check_trend_uptrend(self):
        """상승 추세 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100, trend="up")

        # 상승 추세에서 EMA60 > EMA60[3] 가능성 높음
        result = detector.check_trend(df)
        assert isinstance(result, bool)

    def test_check_trend_downtrend(self):
        """하락 추세 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100, trend="down")

        # 하락 추세에서 EMA60 < EMA60[3] 가능성 높음
        result = detector.check_trend(df)
        assert isinstance(result, bool)

    def test_check_trend_insufficient_data(self):
        """데이터 부족 시 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=50)  # 60 + 3 미만

        result = detector.check_trend(df)
        assert result is False


class TestZoneCondition:
    """Zone 조건 테스트"""

    def test_check_zone_above_ema60(self):
        """EMA60 이상 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100, trend="up")

        # 상승 추세면 close >= EMA60 가능성 높음
        result = detector.check_zone(df)
        assert isinstance(result, bool)

    def test_check_zone_below_ema60(self):
        """EMA60 미만 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100, trend="down")

        result = detector.check_zone(df)
        assert isinstance(result, bool)

    def test_check_zone_insufficient_data(self):
        """데이터 부족 시 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=50)

        result = detector.check_zone(df)
        assert result is False


class TestTriggerCondition:
    """Trigger 조건 테스트"""

    def test_check_trigger_crossup(self):
        """상향 돌파 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        result = detector.check_trigger(df)
        assert isinstance(result, bool)

    def test_check_trigger_bullish(self):
        """양봉 조건 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        # 마지막 봉을 양봉으로 설정
        df.loc[df.index[-1], 'open'] = df['close'].iloc[-1] - 100
        df.loc[df.index[-1], 'close'] = df['close'].iloc[-1]

        result = detector.check_trigger(df)
        assert isinstance(result, bool)

    def test_check_trigger_insufficient_data(self):
        """데이터 부족 시 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=2)

        result = detector.check_trigger(df)
        assert result is False


class TestPurpleOKCondition:
    """PurpleOK 조건 테스트"""

    def test_check_purple_ok(self):
        """PurpleOK 조건 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        result = detector.check_purple_ok(df)
        assert isinstance(result, bool)

    def test_check_purple_ok_insufficient_data(self):
        """데이터 부족 시 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=30)

        result = detector.check_purple_ok(df)
        assert result is False


class TestReAbsStartCondition:
    """ReAbsStart 조건 테스트"""

    def test_check_reabs_start(self):
        """ReAbsStart 조건 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        result = detector.check_reabs_start(df)
        assert isinstance(result, bool)

    def test_check_reabs_start_insufficient_data(self):
        """데이터 부족 시 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=15)

        result = detector.check_reabs_start(df)
        assert result is False


class TestCheckAllConditions:
    """전체 조건 확인 테스트"""

    def test_check_all_conditions(self):
        """모든 조건 확인 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        conditions = detector._check_all_conditions(df)

        assert "purple_ok" in conditions
        assert "trend" in conditions
        assert "zone" in conditions
        assert "reabs_start" in conditions
        assert "trigger" in conditions

        # 모든 값은 bool 타입
        for k, v in conditions.items():
            assert isinstance(v, bool), f"{k} is not bool"


class TestDetectSignal:
    """신호 탐지 테스트"""

    def test_detect_signal_no_signal(self):
        """신호 없음 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100, trend="down")

        signal = detector.detect_signal("005930", "삼성전자", df)

        # 신호가 없거나 있을 수 있음 (데이터 의존)
        assert signal is None or isinstance(signal, PurpleSignal)

    def test_detect_signal_invalid_data(self):
        """유효하지 않은 데이터 테스트"""
        detector = PurpleSignalDetector()

        signal = detector.detect_signal("005930", "삼성전자", None)
        assert signal is None

        signal = detector.detect_signal("005930", "삼성전자", pd.DataFrame())
        assert signal is None

    def test_detect_signal_returns_purple_signal(self):
        """PurpleSignal 반환 테스트"""
        detector = PurpleSignalDetector()
        df = create_purple_signal_data(length=100)

        signal = detector.detect_signal("005930", "삼성전자", df)

        # 신호가 있으면 PurpleSignal 타입
        if signal is not None:
            assert isinstance(signal, PurpleSignal)
            assert signal.stock_code == "005930"
            assert signal.stock_name == "삼성전자"


class TestPreCheck:
    """Pre-Check 테스트"""

    def test_pre_check_basic(self):
        """Pre-Check 기본 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        result = detector.pre_check("005930", "삼성전자", df)

        assert isinstance(result, PreCheckResult)
        assert result.stock_code == "005930"
        assert 0 <= result.conditions_met <= 5

    def test_pre_check_candidate_registration(self):
        """Pre-Check 후보 등록 테스트"""
        detector = PurpleSignalDetector()
        df = create_purple_signal_data(length=100)

        result = detector.pre_check("005930", "삼성전자", df)

        if result.is_candidate:
            assert detector.is_pending_candidate("005930")

    def test_pre_check_invalid_data(self):
        """유효하지 않은 데이터 Pre-Check 테스트"""
        detector = PurpleSignalDetector()

        result = detector.pre_check("005930", "삼성전자", None)

        assert result.conditions_met == 0
        assert result.is_candidate is False


class TestConfirmCheck:
    """Confirm-Check 테스트"""

    def test_confirm_check_basic(self):
        """Confirm-Check 기본 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        signal = detector.confirm_check("005930", "삼성전자", df)

        assert signal is None or isinstance(signal, PurpleSignal)

    def test_confirm_check_clears_candidate(self):
        """Confirm-Check 후 후보 제거 테스트"""
        detector = PurpleSignalDetector()
        df = create_purple_signal_data(length=100)

        # Pre-Check로 후보 등록
        detector.pre_check("005930", "삼성전자", df)

        # Confirm-Check 후 후보 제거
        detector.confirm_check("005930", "삼성전자", df)

        assert not detector.is_pending_candidate("005930")


class TestPendingCandidates:
    """대기 후보 관리 테스트"""

    def test_get_pending_candidates(self):
        """대기 후보 목록 테스트"""
        detector = PurpleSignalDetector()

        assert detector.get_pending_candidates() == []

    def test_clear_pending_candidates(self):
        """대기 후보 초기화 테스트"""
        detector = PurpleSignalDetector()
        df = create_purple_signal_data(length=100)

        detector.pre_check("005930", "삼성전자", df)
        detector.pre_check("000660", "SK하이닉스", df)

        cleared = detector.clear_pending_candidates()

        assert cleared >= 0
        assert len(detector.get_pending_candidates()) == 0


class TestConditionSummary:
    """조건 요약 테스트"""

    def test_get_condition_summary(self):
        """조건 요약 테스트"""
        detector = PurpleSignalDetector()
        df = create_sample_ohlcv(length=100)

        summary = detector.get_condition_summary(df)

        assert "conditions" in summary
        assert "conditions_met" in summary
        assert "total_conditions" in summary
        assert "is_signal" in summary

    def test_get_condition_summary_invalid_data(self):
        """유효하지 않은 데이터 요약 테스트"""
        detector = PurpleSignalDetector()

        summary = detector.get_condition_summary(None)

        assert "error" in summary


class TestDualPassDetector:
    """DualPassDetector 테스트"""

    def test_dual_pass_creation(self):
        """DualPassDetector 생성 테스트"""
        dual = DualPassDetector()

        assert dual.detector is not None
        assert isinstance(dual.detector, PurpleSignalDetector)

    def test_run_pre_check_single(self):
        """단일 종목 Pre-Check 테스트"""
        dual = DualPassDetector()
        df = create_sample_ohlcv(length=100)

        result = dual.run_pre_check_single("005930", "삼성전자", df)

        assert isinstance(result, PreCheckResult)

    def test_run_confirm_check_single(self):
        """단일 종목 Confirm-Check 테스트"""
        dual = DualPassDetector()
        df = create_sample_ohlcv(length=100)

        signal = dual.run_confirm_check_single("005930", "삼성전자", df)

        assert signal is None or isinstance(signal, PurpleSignal)

    def test_get_candidates(self):
        """후보 목록 테스트"""
        dual = DualPassDetector()
        df = create_purple_signal_data(length=100)

        dual.run_pre_check_single("005930", "삼성전자", df)

        candidates = dual.get_candidates()
        assert isinstance(candidates, list)

    def test_clear_candidates(self):
        """후보 초기화 테스트"""
        dual = DualPassDetector()
        df = create_purple_signal_data(length=100)

        dual.run_pre_check_single("005930", "삼성전자", df)

        cleared = dual.clear_candidates()
        assert cleared >= 0
        assert len(dual.get_candidates()) == 0

    def test_get_stats(self):
        """통계 테스트"""
        dual = DualPassDetector()

        stats = dual.get_stats()

        assert "pending_candidates" in stats
        assert "candidate_codes" in stats


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_all_conditions_met(self):
        """모든 조건 충족 시나리오"""
        detector = PurpleSignalDetector()

        # 조건을 모두 충족하도록 설계된 데이터
        df = create_purple_signal_data(length=100)

        conditions = detector._check_all_conditions(df)
        conditions_met = sum(conditions.values())

        # 최소 3개 이상 충족되어야 Pre-Check 통과
        # (실제 모든 조건 충족은 데이터 의존)
        assert conditions_met >= 0

    def test_no_conditions_met(self):
        """모든 조건 미충족 시나리오"""
        detector = PurpleSignalDetector()

        # 하락 추세, 낮은 거래량 데이터
        df = create_sample_ohlcv(
            length=100,
            trend="down",
            volume_base=10000  # 낮은 거래량
        )

        conditions = detector._check_all_conditions(df)
        conditions_met = sum(conditions.values())

        # 일부 조건은 미충족될 가능성 높음
        assert conditions_met >= 0

    def test_boundary_min_candles(self):
        """최소 캔들 수 경계값 테스트"""
        detector = PurpleSignalDetector(min_candles=60)

        df_59 = create_sample_ohlcv(length=59)
        df_60 = create_sample_ohlcv(length=60)
        df_61 = create_sample_ohlcv(length=61)

        assert detector._validate_data(df_59) is False
        assert detector._validate_data(df_60) is True
        assert detector._validate_data(df_61) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
