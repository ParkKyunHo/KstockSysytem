"""
매매 신호 탐지 모듈

SNIPER_TRAP 전략 신호를 탐지합니다 (3분봉 기반):
- TrendFilter: C > EMA200 AND EMA60 > EMA60(5)
- Zone: L <= EMA20 AND C >= EMA60
- Meaningful: CrossUp(C, EMA3) + 양봉 + 거래량 증가
- BodySize: (C-O)/O >= 0.3%

V6.2-Q: Ceiling Break 및 Floor Line 제거 (미사용)
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional, List
from enum import Enum
import pandas as pd

from src.core.indicator import Indicator
from src.core.candle_builder import Timeframe
from src.core.detectors.base_detector import BaseDetector, MultiConditionMixin
from src.core.signals.base_signal import BaseSignal, SignalType as BaseSignalType, StrategyType as BaseStrategyType
from src.utils.logger import get_logger, KST  # PRD v3.2.1: KST 타임존 명시
from src.utils.config import get_risk_settings


class SignalType(str, Enum):
    """신호 타입"""
    BUY = "BUY"
    SELL = "SELL"


class StrategyType(str, Enum):
    """전략 타입"""
    SNIPER_TRAP = "SNIPER_TRAP"      # 스나이퍼 (유일 전략)


@dataclass
class Signal(BaseSignal):
    """매매 신호 - BaseSignal ABC를 상속하여 전략 플러그인 아키텍처와 호환"""
    # BaseSignal 필드: stock_code, stock_name, signal_type, strategy, price, timestamp, metadata
    # 오버라이드: signal_type/strategy에 기본값 추가 → price에도 기본값 필요 (dataclass 규칙)
    signal_type: SignalType = SignalType.BUY  # 로컬 SignalType 사용 (기존 호환성)
    strategy: StrategyType = StrategyType.SNIPER_TRAP  # 로컬 StrategyType 사용 (기존 호환성)
    price: int = 0                   # dataclass 필드 순서 호환 (기본값 필수)
    timeframe: Timeframe = Timeframe.M3
    reason: str = ""                 # 신호 발생 이유
    strength: float = 1.0            # 신호 강도 (0~1)

    def get_strength(self) -> float:
        """BaseSignal ABC 구현: 신호 강도 반환"""
        return self.strength

    def get_summary(self) -> str:
        """BaseSignal ABC 구현: 신호 요약 문자열 반환"""
        return self.reason

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (기존 호환성 유지)"""
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "signal_type": self.signal_type.value,
            "strategy": self.strategy.value,
            "price": self.price,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe.value,
            "reason": self.reason,
            "strength": self.strength,
            "metadata": self.metadata,
        }



class SniperTrapDetector(BaseDetector, MultiConditionMixin):
    """
    지저깨(스나이퍼) 전략 탐지기 (3분봉) - Grand Trend V6.2-A

    BaseDetector ABC를 상속하여 전략 플러그인 아키텍처와 호환됩니다.

    진입 조건 (V6.2-A):
    0. TrendFilter: C > EMA200 AND EMA60 > EMA60(5) - 대세 상승 확인
    1. Zone: L <= M20 && C >= M60 - 헌팅존
    2. Meaningful: CrossUp(C, M3) && C > O && V >= V(1) - 의미있는 캔들
    3. BodySize: (C-O)/O*100 >= 0.3 - 캔들 몸통 0.3% 이상
    4. TimeFilter: 09:30 이후만 신호 탐색 (시간 조건)
    """

    # 설정: EMA 기간
    EMA_SHORT = 3               # 단기 이평 (M3)
    EMA_MID = 20                # 중기 이평 (M20)
    EMA_LONG = 60               # 장기 이평 (M60)
    EMA_TREND = 200             # V6.2-A: 대세 판단용 (EMA200)
    ANGLE_PERIOD = 5            # 추세 각도 비교 기간 (5봉 전)
    MIN_CANDLES = 205           # V6.2-A: EMA200 + 5봉 여유 (기존 65)
    MIN_BODY_SIZE = 0.3         # 최소 캔들 몸통 크기 (%)

    # 설정: 신호 강도 계산
    BASE_SIGNAL_STRENGTH = 0.7          # 기본 신호 강도
    BODY_SIZE_BONUS_THRESHOLD = 0.5     # 캔들 크기 보너스 기준 (%)
    BODY_SIZE_BONUS = 0.15              # 캔들 크기 보너스
    VOLUME_RATIO_THRESHOLD = 1.5        # 거래량 비율 보너스 기준 (배)
    VOLUME_BONUS = 0.15                 # 거래량 보너스

    def __init__(self):
        self._logger = get_logger(__name__)
        self._risk_settings = get_risk_settings()

        # V6.2-L: 시간 조건 파싱 (예: "09:20")
        signal_start_str = self._risk_settings.signal_start_time
        try:
            parts = signal_start_str.split(":")
            self._signal_start_time = time(int(parts[0]), int(parts[1]))
        except Exception:
            self._signal_start_time = time(9, 5)  # V7: 기본값 09:20→09:05

        # V6.2-D: 조기 신호 시간 파싱 (예: "09:00")
        early_signal_str = getattr(self._risk_settings, 'early_signal_time', '09:00')
        try:
            parts = early_signal_str.split(":")
            self._early_signal_time = time(int(parts[0]), int(parts[1]))
        except Exception:
            self._early_signal_time = time(9, 0)  # 기본값 09:00

        # V6.2-L: 신호 종료 시간 파싱 (예: "15:20")
        signal_end_str = getattr(self._risk_settings, 'signal_end_time', '15:20')
        try:
            parts = signal_end_str.split(":")
            self._signal_end_time = time(int(parts[0]), int(parts[1]))
        except Exception:
            self._signal_end_time = time(15, 20)  # 기본값 15:20

        # V6.2-L: NXT 애프터마켓 신호 활성화 여부
        self._nxt_signal_enabled = getattr(self._risk_settings, 'nxt_signal_enabled', False)

    # ===== BaseDetector ABC 구현 =====

    @property
    def strategy_name(self) -> str:
        return "SNIPER_TRAP"

    @property
    def min_candles_required(self) -> int:
        return self.MIN_CANDLES

    def detect(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        **kwargs
    ) -> Optional[Signal]:
        """BaseDetector ABC 구현: check_signal()에 위임"""
        return self.check_signal(df, stock_code, stock_name, **kwargs)

    def check_signal(
        self,
        candles: pd.DataFrame,
        stock_code: str,
        stock_name: str = "",
        override_time_filter: bool = False,
        current_time: Optional[time] = None,
    ) -> Optional[Signal]:
        """
        지저깨 신호 탐지 (Grand Trend V6.2-A, V6.2-D)

        수식 (V6.2-A):
        M3 = eavg(C, 3); M20 = eavg(C, 20); M60 = eavg(C, 60); M200 = eavg(C, 200);
        TrendFilter = C > M200 && M60 > M60(5);  // 대세 상승 확인
        Zone = L <= M20 && C >= M60;              // 헌팅존
        Meaningful = CrossUp(C, M3) && C > O && V >= V(1);
        BodySize = (C - O) / O * 100 >= 0.3;
        TimeFilter = CurrentTime >= 09:30;        // 시간 조건

        V6.2-D: 52주 고점 근접 종목은 09:00부터 신호 허용 (override_time_filter=True)

        TrendFilter && Zone && Meaningful && BodySize && TimeFilter

        Args:
            candles: 3분봉 OHLCV DataFrame
            stock_code: 종목 코드
            stock_name: 종목명
            override_time_filter: V6.2-D 52주 고점 근접 종목 조기 신호 허용
            current_time: V6.2-P 현재 시간 (캐싱용, None이면 자동 계산)

        Returns:
            Signal 또는 None
        """
        if len(candles) < self.MIN_CANDLES:
            return None

        # ============================================
        # V6.2-L 조건 0: 시간 필터 (NXT 확장)
        # - 정규장: 09:20~15:20 (V6.2-L: 09:30→09:20 단축)
        # - NXT 애프터마켓: 15:30~20:00 (NXT_SIGNAL_ENABLED=True 시)
        # - V6.2-D: 52주 고점 근접 종목은 09:00부터 허용
        # V6.2-P: current_time 파라미터로 중복 호출 방지
        # ============================================
        if current_time is None:
            current_time = datetime.now(KST).time()

        # 정규장 종료 시간 체크 (15:20)
        if current_time >= self._signal_end_time:
            # NXT 애프터마켓 (15:30~20:00) 신호 허용 여부
            if self._nxt_signal_enabled:
                nxt_after_start = time(15, 30)
                nxt_after_end = time(20, 0)
                if not (nxt_after_start <= current_time < nxt_after_end):
                    return None  # 15:20~15:30 NXT 중단 또는 20:00 이후
            else:
                return None  # NXT 신호 비활성화

        # 정규장 시작 시간 체크
        if override_time_filter:
            # V6.2-D: 조기 신호 허용 (09:00부터)
            if current_time < self._early_signal_time:
                return None
        else:
            # 일반 종목: 09:20 이후만 (V6.2-L)
            if current_time < self._signal_start_time:
                return None

        # ============================================
        # V6.2-P: EMA Fail-Fast 최적화
        # TrendFilter 탈락률 60-70% → EMA200/60 먼저 계산 후 조기 반환
        # ============================================

        # Step 1: DataFrame 복사 및 기본 검증
        df = candles.copy()

        # V6.2-P: len >= 6 체크 (5봉 전 EMA60 + 최신 봉 필요)
        # 이 조건이 만족되면 len > 1도 자동으로 충족되어 prev 접근 안전
        if len(df) < 6:
            return None

        # Step 2: TrendFilter용 EMA만 먼저 계산 (EMA200, EMA60)
        df["ema200"] = Indicator.ema(df["close"], self.EMA_TREND)
        df["ema60"] = Indicator.ema(df["close"], self.EMA_LONG)

        latest = df.iloc[-1]

        # NaN 체크 (TrendFilter용)
        if pd.isna(latest["ema200"]) or pd.isna(latest["ema60"]):
            return None

        # 5봉 전 ema60 값 확인 (Angle 조건용)
        ema60_5ago = df["ema60"].iloc[-6]  # 5봉 전
        if pd.isna(ema60_5ago):
            return None

        # ============================================
        # V6.2-A 조건 1: TrendFilter = C > EMA200 AND EMA60 > EMA60(5)
        # 대세 상승: EMA200 위 + 60선 우상향
        # V6.2-P: 조기 반환으로 EMA3/EMA20 계산 스킵
        # ============================================
        trend_filter = (
            latest["close"] > latest["ema200"] and
            latest["ema60"] > ema60_5ago
        )

        if not trend_filter:
            # V6.2-H: TrendFilter 미충족 디버그 로그
            self._logger.debug(
                f"[SNIPER_TRAP] {stock_code} TrendFilter 미충족: "
                f"C({int(latest['close']):,}) > EMA200({int(latest['ema200']):,})? {latest['close'] > latest['ema200']}, "
                f"EMA60상승? {latest['ema60'] > ema60_5ago}"
            )
            return None  # V6.2-P: EMA3/EMA20 계산 없이 조기 반환

        # Step 3: TrendFilter 통과 시에만 나머지 EMA 계산 (EMA3, EMA20)
        df["ema20"] = Indicator.ema(df["close"], self.EMA_MID)
        df["ema3"] = Indicator.ema(df["close"], self.EMA_SHORT)

        # latest 갱신 (EMA3, EMA20 포함)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # NaN 체크 (Zone/Meaningful용)
        if pd.isna(latest["ema3"]) or pd.isna(latest["ema20"]):
            return None

        # ============================================
        # V6.2-A 조건 2: Zone = L <= M20 && C >= M60
        # 헌팅존: 20선 아래로 내려갔다가 60선 위로 복귀
        # ============================================
        zone_ok = latest["low"] <= latest["ema20"] and latest["close"] >= latest["ema60"]

        # ============================================
        # V6.2-A 조건 3: Meaningful = CrossUp(C, M3) && C > O && V >= V(1)
        # 의미있는 캔들: 3선 상향돌파 + 양봉 + 거래량 증가
        # ============================================
        # V6.2-Q FIX: prev["ema3"] NaN 체크 (초기 캔들 부족 시 안전 처리)
        if pd.isna(prev["ema3"]) or pd.isna(latest["ema3"]):
            return None

        # CrossUp(C, M3): 이전봉 종가 < 이전봉 3선 AND 현재봉 종가 >= 현재봉 3선
        prev_below_m3 = prev["close"] < prev["ema3"]
        curr_above_m3 = latest["close"] >= latest["ema3"]
        crossup_m3 = prev_below_m3 and curr_above_m3

        # C > O: 양봉
        is_bullish = latest["close"] > latest["open"]

        # V >= V(1): 현재 거래량 >= 전봉 거래량
        volume_increase = latest["volume"] >= prev["volume"]

        meaningful = crossup_m3 and is_bullish and volume_increase

        # ============================================
        # V6.2-A 조건 4: BodySize = (C - O) / O * 100 >= 0.3
        # 캔들 몸통 크기 0.3% 이상
        # ============================================
        if latest["open"] == 0:
            return None
        body_size_pct = (latest["close"] - latest["open"]) / latest["open"] * 100
        body_size_ok = body_size_pct >= self.MIN_BODY_SIZE

        # ============================================
        # V6.2-A: 모든 조건 충족
        # TrendFilter(이미 체크) && Zone && Meaningful && BodySize
        # ============================================
        if zone_ok and meaningful and body_size_ok:
            # 신호 강도 계산 (상수 사용)
            strength = self.BASE_SIGNAL_STRENGTH
            if body_size_pct >= self.BODY_SIZE_BONUS_THRESHOLD:
                strength += self.BODY_SIZE_BONUS  # 캔들 크기 큰 경우
            if latest["volume"] >= prev["volume"] * self.VOLUME_RATIO_THRESHOLD:
                strength += self.VOLUME_BONUS  # 거래량 보너스
            strength = min(strength, 1.0)

            reason = (
                f"[V6.2-A] EMA200↑({int(latest['ema200']):,}), "
                f"헌팅존(L≤M20, C≥M60), "
                f"3선 상향돌파+양봉+거래량↑, "
                f"캔들크기 {body_size_pct:.2f}%"
            )

            signal = Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                signal_type=SignalType.BUY,
                strategy=StrategyType.SNIPER_TRAP,
                price=int(latest["close"]),
                timestamp=datetime.now(KST),  # PRD v3.2.1: KST 명시
                timeframe=Timeframe.M3,
                reason=reason,
                strength=strength,
                metadata={
                    "ema3": float(latest["ema3"]),
                    "ema20": float(latest["ema20"]),
                    "ema60": float(latest["ema60"]),
                    "ema200": float(latest["ema200"]),  # V6.2-A
                    "ema60_5ago": float(ema60_5ago),
                    "body_size_pct": body_size_pct,
                    "volume_ratio": latest["volume"] / prev["volume"] if prev["volume"] > 0 else 0,
                    "crossup_m3": crossup_m3,
                },
            )

            self._logger.info(
                f"지저깨 신호 발생",
                stock_code=stock_code,
                price=int(latest["close"]),
                reason=reason,
            )

            return signal

        # V6.2-H: Zone/Meaningful/BodySize 미충족 디버그 로그
        self._logger.debug(
            f"[SNIPER_TRAP] {stock_code} 조건 미충족: "
            f"Zone(L≤M20,C≥M60)={zone_ok}, "
            f"Meaningful(CrossUp+양봉+V↑)={meaningful}, "
            f"BodySize(≥0.3%)={body_size_ok} | "
            f"L={int(latest['low']):,} M20={int(latest['ema20']):,} "
            f"C={int(latest['close']):,} M60={int(latest['ema60']):,} "
            f"크기={body_size_pct:.2f}%"
        )
        return None


class SignalDetector:
    """
    통합 신호 탐지기 (V6.2-Q)

    SNIPER_TRAP 전략만 사용합니다.

    Usage:
        detector = SignalDetector()
        signals = detector.check_all_signals(candles_1m, candles_3m, stock_code)
    """

    def __init__(self):
        self._sniper_detector = SniperTrapDetector()
        self._logger = get_logger(__name__)

    def check_sniper_trap(
        self,
        candles_3m: pd.DataFrame,
        stock_code: str,
        stock_name: str = "",
        override_time_filter: bool = False,
        current_time: Optional[time] = None,
    ) -> Optional[Signal]:
        """
        스나이퍼 신호 탐지 (3분봉)

        Args:
            override_time_filter: V6.2-D 52주 고점 근접 종목 조기 신호 허용
            current_time: V6.2-P 현재 시간 (캐싱용, None이면 자동 계산)
        """
        return self._sniper_detector.check_signal(
            candles_3m, stock_code, stock_name, override_time_filter, current_time
        )

    def check_all_signals(
        self,
        candles_1m: Optional[pd.DataFrame],
        candles_3m: Optional[pd.DataFrame],
        stock_code: str,
        stock_name: str = "",
        override_time_filter: bool = False,
        current_time: Optional[time] = None,
    ) -> List[Signal]:
        """
        SNIPER_TRAP 신호를 탐지 (V6.2-Q)

        Args:
            candles_1m: 1분봉 OHLCV DataFrame (미사용, 호환성 유지)
            candles_3m: 3분봉 OHLCV DataFrame (SNIPER_TRAP용)
            stock_code: 종목 코드
            stock_name: 종목명
            override_time_filter: V6.2-D 52주 고점 근접 종목 조기 신호 허용
            current_time: V6.2-P 현재 시간 (캐싱용, None이면 자동 계산)

        Returns:
            발생한 Signal 목록
        """
        signals = []

        # SNIPER_TRAP (3분봉) - V6.2-Q: 유일한 전략
        if candles_3m is not None and len(candles_3m) >= SniperTrapDetector.MIN_CANDLES:
            sniper_signal = self.check_sniper_trap(
                candles_3m, stock_code, stock_name, override_time_filter, current_time
            )
            if sniper_signal:
                signals.append(sniper_signal)

        return signals

    def check_exit_signal(
        self,
        candles: pd.DataFrame,
        strategy: StrategyType,
        entry_price: int,
    ) -> Optional[Signal]:
        """
        청산 신호 탐지 (V6.2-Q: SNIPER_TRAP 전용)

        현재는 RiskManager에서 손절/익절을 관리하므로
        기술적 청산 신호만 탐지합니다.

        Args:
            candles: 봉 데이터
            strategy: 진입 전략
            entry_price: 진입 가격

        Returns:
            청산 Signal 또는 None
        """
        if len(candles) < 5:
            return None

        df = candles.copy()
        latest = df.iloc[-1]

        # SNIPER_TRAP: EMA 60 하향 돌파 시 청산 고려
        if strategy == StrategyType.SNIPER_TRAP:
            df["ema60"] = Indicator.ema(df["close"], 60)
            if latest["close"] < df["ema60"].iloc[-1]:
                return Signal(
                    stock_code="",
                    stock_name="",
                    signal_type=SignalType.SELL,
                    strategy=strategy,
                    price=int(latest["close"]),
                    timestamp=datetime.now(KST),
                    timeframe=Timeframe.M3,
                    reason="EMA60 하향 이탈",
                    strength=0.5,
                )

        return None
