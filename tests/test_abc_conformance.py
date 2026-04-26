"""
ABC 적합화 테스트 (Phase 1)

기존 V6/V7 구현체가 BaseDetector, BaseExit, BaseSignal ABC를
올바르게 상속하는지 검증합니다.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.core.detectors.base_detector import BaseDetector, MultiConditionMixin, DualPassMixin
from src.core.exit.base_exit import BaseExit, ExitDecision, ExitReason, TrendHoldMixin
from src.core.signals.base_signal import BaseSignal, SignalType, StrategyType


# ===== Phase 1-A: PurpleSignalDetector → BaseDetector =====

class TestPurpleDetectorABC:
    """PurpleSignalDetector가 BaseDetector를 올바르게 상속하는지 검증"""

    def test_isinstance_base_detector(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()
        assert isinstance(detector, BaseDetector)

    def test_isinstance_multi_condition_mixin(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()
        assert isinstance(detector, MultiConditionMixin)

    def test_isinstance_dual_pass_mixin(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()
        assert isinstance(detector, DualPassMixin)

    def test_strategy_name(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()
        assert detector.strategy_name == "PURPLE_REABS"

    def test_min_candles_required(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()
        assert detector.min_candles_required == 60  # MIN_CANDLES_REQUIRED

    def test_detect_delegates_to_detect_signal(self):
        """detect()가 detect_signal()에 위임하는지 확인"""
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()

        # 데이터 부족 시 None 반환
        df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
        result = detector.detect(df, "005930", "삼성전자")
        assert result is None

    def test_is_ready(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()

        # 데이터 부족
        df_short = pd.DataFrame({"close": range(10)})
        assert detector.is_ready(df_short) is False

        # 충분한 데이터
        df_long = pd.DataFrame({"close": range(100)})
        assert detector.is_ready(df_long) is True

    def test_str_repr(self):
        from src.core.signal_detector_purple import PurpleSignalDetector
        detector = PurpleSignalDetector()
        assert "PURPLE_REABS" in str(detector)
        assert "PURPLE_REABS" in repr(detector)


# ===== Phase 1-B: SniperTrapDetector → BaseDetector =====

class TestSniperDetectorABC:
    """SniperTrapDetector가 BaseDetector를 올바르게 상속하는지 검증"""

    @pytest.fixture
    def detector(self):
        with patch('src.core.signal_detector.get_risk_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                signal_start_time="09:05",
                signal_end_time="15:20",
                early_signal_time="09:00",
                nxt_signal_enabled=False,
            )
            from src.core.signal_detector import SniperTrapDetector
            return SniperTrapDetector()

    def test_isinstance_base_detector(self, detector):
        assert isinstance(detector, BaseDetector)

    def test_isinstance_multi_condition_mixin(self, detector):
        assert isinstance(detector, MultiConditionMixin)

    def test_strategy_name(self, detector):
        assert detector.strategy_name == "SNIPER_TRAP"

    def test_min_candles_required(self, detector):
        assert detector.min_candles_required == 205  # EMA200 + 5

    def test_detect_delegates_to_check_signal(self, detector):
        """detect()가 check_signal()에 위임하는지 확인"""
        df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
        result = detector.detect(df, "005930", "삼성전자")
        assert result is None


# ===== Phase 1-C: WaveHarvestExit → BaseExit =====

class TestWaveHarvestExitABC:
    """WaveHarvestExit가 BaseExit를 올바르게 상속하는지 검증"""

    def test_isinstance_base_exit(self):
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()
        assert isinstance(exit_mgr, BaseExit)

    def test_isinstance_trend_hold_mixin(self):
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()
        assert isinstance(exit_mgr, TrendHoldMixin)

    def test_strategy_name(self):
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()
        assert exit_mgr.strategy_name == "WAVE_HARVEST"

    def test_check_exit_hard_stop(self):
        """check_exit()가 고정 손절을 최우선 확인하는지 검증"""
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()

        # -4% 이하일 때 hard stop 발동
        result = exit_mgr.check_exit(
            df=pd.DataFrame(),
            entry_price=10000,
            current_price=9500,  # -5%
        )
        assert result.should_exit is True
        assert result.reason == ExitReason.HARD_STOP

    def test_check_exit_hold(self):
        """check_exit()가 state 없이 hold 반환"""
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()

        result = exit_mgr.check_exit(
            df=pd.DataFrame(),
            entry_price=10000,
            current_price=10500,  # +5%
        )
        assert result.should_exit is False

    def test_update_trailing_stop_direction(self):
        """update_trailing_stop()이 상향 단방향을 보장하는지 검증"""
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()

        # 충분한 데이터 생성
        np.random.seed(42)
        n = 30
        df = pd.DataFrame({
            "open": np.random.uniform(9000, 11000, n),
            "high": np.random.uniform(10000, 12000, n),
            "low": np.random.uniform(8000, 10000, n),
            "close": np.random.uniform(9000, 11000, n),
            "volume": np.random.uniform(1000, 5000, n),
        })

        new_stop, new_mult = exit_mgr.update_trailing_stop(
            df=df,
            current_stop=9500,
            current_price=10500,
            entry_price=10000,
            current_multiplier=6.0,
        )

        # 스탑은 현재보다 낮아질 수 없음
        assert new_stop >= 9500
        # ATR 배수는 현재보다 높아질 수 없음
        assert new_mult <= 6.0

    def test_check_hard_stop_inherited(self):
        """BaseExit.check_hard_stop() 상속 동작 검증"""
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()

        # BaseExit.check_hard_stop(entry_price, current_price) 사용
        result = BaseExit.check_hard_stop(exit_mgr, 10000, 9500)  # -5%
        assert result is not None
        assert result.should_exit is True
        assert result.reason == ExitReason.HARD_STOP

    def test_enforce_stop_direction_inherited(self):
        """BaseExit.enforce_stop_direction() 상속 동작 검증"""
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()

        assert exit_mgr.enforce_stop_direction(9000, 9500) == 9500  # max
        assert exit_mgr.enforce_stop_direction(10000, 9500) == 10000

    def test_enforce_multiplier_direction_inherited(self):
        """BaseExit.enforce_multiplier_direction() 상속 동작 검증"""
        from src.core.wave_harvest_exit import WaveHarvestExit
        exit_mgr = WaveHarvestExit()

        assert exit_mgr.enforce_multiplier_direction(6.0, 4.5) == 4.5  # min
        assert exit_mgr.enforce_multiplier_direction(3.5, 4.5) == 3.5


# ===== Phase 1-E: PurpleSignal → BaseSignal =====

class TestPurpleSignalABC:
    """PurpleSignal이 BaseSignal을 올바르게 상속하는지 검증"""

    def test_isinstance_base_signal(self):
        from src.core.signal_detector_purple import PurpleSignal
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=50000,
            score=0.85,
            rise_ratio=0.05,
            convergence_ratio=0.04,
        )
        assert isinstance(signal, BaseSignal)

    def test_signal_type_auto_set(self):
        from src.core.signal_detector_purple import PurpleSignal
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=50000,
        )
        assert signal.signal_type == SignalType.BUY
        assert signal.strategy == StrategyType.PURPLE_REABS

    def test_get_strength(self):
        from src.core.signal_detector_purple import PurpleSignal
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=50000,
            confidence=0.75,
        )
        assert signal.get_strength() == 0.75

    def test_get_summary(self):
        from src.core.signal_detector_purple import PurpleSignal
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=50000,
            score=0.85,
            rise_ratio=0.05,
            convergence_ratio=0.04,
            metadata={"score": 0.85, "rise_pct": 5.0, "convergence_pct": 4.0},
        )
        summary = signal.get_summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_to_dict_compatibility(self):
        """기존 to_dict() 호환성 검증"""
        from src.core.signal_detector_purple import PurpleSignal
        signal = PurpleSignal(
            stock_code="005930",
            stock_name="삼성전자",
            price=50000,
            score=0.85,
            rise_ratio=0.05,
            convergence_ratio=0.04,
        )
        d = signal.to_dict()
        assert d["stock_code"] == "005930"
        assert d["price"] == 50000
        assert d["score"] == 0.85
        assert "rise_ratio" in d
        assert "convergence_ratio" in d


# ===== Phase 1-E: Signal → BaseSignal =====

class TestSignalABC:
    """Signal이 BaseSignal을 올바르게 상속하는지 검증"""

    @pytest.fixture
    def signal(self):
        with patch('src.core.signal_detector.get_risk_settings') as mock_settings:
            mock_settings.return_value = MagicMock(
                signal_start_time="09:05",
                signal_end_time="15:20",
                nxt_signal_enabled=False,
            )
            from src.core.signal_detector import Signal, SignalType, StrategyType
            from src.core.candle_builder import Timeframe
            return Signal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                strategy=StrategyType.SNIPER_TRAP,
                price=50000,
                timestamp=datetime.now(),
                timeframe=Timeframe.M3,
                reason="테스트 신호",
                strength=0.85,
            )

    def test_isinstance_base_signal(self, signal):
        assert isinstance(signal, BaseSignal)

    def test_get_strength(self, signal):
        assert signal.get_strength() == 0.85

    def test_get_summary(self, signal):
        assert signal.get_summary() == "테스트 신호"

    def test_to_dict_compatibility(self, signal):
        d = signal.to_dict()
        assert d["stock_code"] == "005930"
        assert d["price"] == 50000
        assert d["strategy"] == "SNIPER_TRAP"
        assert d["reason"] == "테스트 신호"
