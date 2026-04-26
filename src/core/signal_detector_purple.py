"""
Purple-ReAbs 신호 탐지 모듈 (V7.0)

돌파 이후 에너지가 소진되지 않고 다시 응축되는 구간(Re-Absorption)을 탐지합니다.

주요 기능:
- 5가지 신호 조건 검증 (PurpleOK, Trend, Zone, ReAbsStart, Trigger)
- Dual-Pass 신호 탐지 (Pre-Check → Confirm-Check)
- Zero Signal Miss 원칙: False Positive 허용, False Negative(신호 누락) 절대 불허

신호 조건:
- PurpleOK: (H1/L1-1) >= 4% AND (H2/L2-1) <= 7% AND M >= 5억
- Trend: EMA60 > EMA60[3] (EMA60 상승 추세)
- Zone: C >= EMA60 × 0.995 (Landing Zone 진입)
- ReAbsStart: S > S[1] (Score 재상승)
- Trigger: CrossUp(C, EMA3) AND 양봉 (EMA3 돌파 + 양봉)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
import logging
import threading
import pandas as pd
import numpy as np

from src.core.indicator_purple import (
    PurpleIndicator,
    calculate_purple_indicators,
    ZONE_EMA60_TOLERANCE,
)
from src.core.detectors.base_detector import BaseDetector, MultiConditionMixin, DualPassMixin
from src.core.signals.base_signal import BaseSignal, SignalType as BaseSignalType, StrategyType as BaseStrategyType


# ===== 신호 조건 설정 =====
TREND_LOOKBACK = 3            # M60 > M60[3] - EMA60 비교 봉 수
PRE_CHECK_MIN_CONDITIONS = 3  # Pre-Check 최소 조건 충족 수 (5개 중 3개)
MIN_CANDLES_REQUIRED = 60     # 신호 탐지 최소 필요 캔들 수
# C-002: Score 계산에 필요한 최소 캔들 수 (LZ_lookback=40 + rolling 30 = 70)
MIN_CANDLES_FOR_SCORE = 70


@dataclass
class PurpleSignal(BaseSignal):
    """
    Purple-ReAbs 신호 데이터

    BaseSignal ABC를 상속하여 전략 플러그인 아키텍처와 호환됩니다.

    Attributes:
        stock_code: 종목 코드
        stock_name: 종목명
        price: 현재가
        score: Purple Score (S)
        rise_ratio: 상승률 (H1/L1 - 1)
        convergence_ratio: 수렴률 (H2/L2 - 1)
        timestamp: 신호 발생 시간
        metadata: 추가 정보 (조건별 세부 값)
        confidence: 신호 강도 (0~1, 신호 결정용 아님, 우선순위/분석용)
    """
    # BaseSignal 필드: stock_code, stock_name, signal_type, strategy, price, timestamp, metadata
    # PurpleSignal 추가 필드:
    score: float = 0.0
    rise_ratio: float = 0.0
    convergence_ratio: float = 0.0
    confidence: float = 0.0

    def __init__(
        self,
        stock_code: str,
        stock_name: str,
        price: int,
        score: float = 0.0,
        rise_ratio: float = 0.0,
        convergence_ratio: float = 0.0,
        timestamp: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
        **kwargs,
    ):
        """기존 생성자 시그니처 유지 + BaseSignal 필드 초기화"""
        # BaseSignal 필수 필드 초기화
        object.__setattr__(self, 'stock_code', stock_code)
        object.__setattr__(self, 'stock_name', stock_name)
        object.__setattr__(self, 'signal_type', BaseSignalType.BUY)
        object.__setattr__(self, 'strategy', BaseStrategyType.PURPLE_REABS)
        object.__setattr__(self, 'price', price)
        object.__setattr__(self, 'timestamp', timestamp or datetime.now())
        object.__setattr__(self, 'metadata', metadata or {})
        # PurpleSignal 고유 필드
        object.__setattr__(self, 'score', score)
        object.__setattr__(self, 'rise_ratio', rise_ratio)
        object.__setattr__(self, 'convergence_ratio', convergence_ratio)
        object.__setattr__(self, 'confidence', confidence)

    def get_strength(self) -> float:
        """BaseSignal ABC 구현: 신호 강도 반환"""
        return self.confidence

    def get_summary(self) -> str:
        """BaseSignal ABC 구현: 신호 요약 문자열 반환"""
        return generate_signal_summary(self)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환 (기존 호환성 유지)"""
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "price": self.price,
            "score": round(self.score, 4),
            "rise_ratio": round(self.rise_ratio * 100, 2),  # 퍼센트
            "convergence_ratio": round(self.convergence_ratio * 100, 2),
            "confidence": round(self.confidence, 2),
            "timestamp": self.timestamp.isoformat(),
            **self.metadata,
        }

    def __str__(self) -> str:
        return (
            f"[PURPLE] {self.stock_name}({self.stock_code}) "
            f"@{self.price:,}원 "
            f"Score={self.score:.2f} "
            f"Rise={self.rise_ratio*100:.1f}% "
            f"Conv={self.convergence_ratio*100:.1f}%"
        )


def generate_signal_summary(signal: PurpleSignal) -> str:
    """
    신호 발생 이유 자연어 요약

    트레이더가 빠르게 신호 품질을 판단할 수 있도록
    핵심 지표를 한 줄로 요약합니다.

    Args:
        signal: PurpleSignal 객체

    Returns:
        요약 문자열 (예: "상승 5.2% / 수렴 3.1% | Score 0.82→0.91(+0.09) | 거래대금 8.2억 | EMA60+0.3%")
    """
    m = signal.metadata
    parts = []

    # 1. 구조 (Rise/Convergence)
    rise_pct = m.get('rise_pct', signal.rise_ratio * 100)
    conv_pct = m.get('convergence_pct', signal.convergence_ratio * 100)
    parts.append(f"상승 {rise_pct:.1f}% / 수렴 {conv_pct:.1f}%")

    # 2. Score 변화
    score = m.get('score', signal.score)
    score_prev = m.get('score_prev')
    if score_prev is not None:
        score_delta = score - score_prev
        direction = "+" if score_delta > 0 else ""
        parts.append(f"Score {score_prev:.2f}→{score:.2f}({direction}{score_delta:.2f})")
    else:
        parts.append(f"Score {score:.2f}")

    # 3. 거래대금
    money_billion = m.get('money_billion')
    if money_billion is not None:
        parts.append(f"거래대금 {money_billion:.1f}억")

    # 4. Zone 위치 (EMA60 대비)
    ema60 = m.get('ema60')
    if ema60 and ema60 > 0:
        zone_pct = (signal.price / ema60 - 1) * 100
        if zone_pct >= 0:
            parts.append(f"EMA60+{zone_pct:.1f}%")
        else:
            parts.append(f"EMA60{zone_pct:.1f}%")

    return " | ".join(parts)


def calculate_confidence(details: dict) -> float:
    """
    5/5 충족 신호의 "강도" 계산 (0~1)

    신호 결정에 사용하지 않고, 다중 신호 시 우선순위 결정 및
    분석/리포트 목적으로 사용합니다.

    Args:
        details: 신호 세부 정보 딕셔너리
            - rise_pct: 상승률 (%)
            - convergence_pct: 수렴률 (%)
            - money_billion: 거래대금 (억원)
            - score: 현재 Score
            - score_prev: 이전 Score
            - zone_pct: Zone 위치 (EMA60 대비 %)

    Returns:
        신호 강도 (0~1)
    """
    # 1. PurpleOK 여유도 (임계값 대비 얼마나 여유 있는가)
    # 상승률: 4% 이상 필요, 4~10% 범위에서 0~1
    rise_pct = details.get('rise_pct', 4.0)
    rise_margin = min((rise_pct - 4.0) / 6.0, 1.0)
    rise_margin = max(rise_margin, 0.0)

    # 수렴률: 7% 이하 필요, 2~7% 범위에서 1~0
    conv_pct = details.get('convergence_pct', 7.0)
    conv_margin = min((7.0 - conv_pct) / 5.0, 1.0)
    conv_margin = max(conv_margin, 0.0)

    # 거래대금: 5억 이상 필요, 5~10억 범위에서 0~1
    money_billion = details.get('money_billion', 0.5)
    money_margin = min((money_billion - 0.5) / 1.5, 1.0)  # 0.5~2억 -> 0~1
    money_margin = max(money_margin, 0.0)

    # 2. Score 상승폭
    score = details.get('score', 0)
    score_prev = details.get('score_prev', score)
    score_delta = score - score_prev if score_prev is not None else 0
    score_margin = min(max(score_delta / 0.3, 0), 1.0)  # 0~0.3 -> 0~1

    # 3. Zone 위치 (EMA60 위일수록 좋음)
    zone_pct = details.get('zone_pct', 0)
    if zone_pct is None:
        zone_pct = 0
    zone_margin = min(max((zone_pct + 0.5) / 2.0, 0), 1.0)  # -0.5~1.5% -> 0~1

    # 가중 평균
    confidence = (
        rise_margin * 0.20 +
        conv_margin * 0.20 +
        money_margin * 0.20 +
        score_margin * 0.25 +
        zone_margin * 0.15
    )

    return round(confidence, 2)


def format_condition_log(conditions: Dict[str, bool], values: Dict[str, Any]) -> str:
    """조건 상태와 수치를 한 줄 요약으로 포맷 (진단 로깅용)"""
    def v(key, default='?'):
        val = values.get(key, default)
        return default if val is None else val

    parts = []

    p = "O" if conditions.get("purple_ok") else "X"
    parts.append(f"P:{p}(↑{v('rise_pct')}%/↔{v('conv_pct')}%/{v('money_억')}억)")

    t = "O" if conditions.get("trend") else "X"
    parts.append(f"T:{t}({v('ema60')}/{v('ema60_3ago')})")

    z = "O" if conditions.get("zone") else "X"
    parts.append(f"Z:{z}(C:{v('close')}/Th:{v('zone_threshold')})")

    r = "O" if conditions.get("reabs_start") else "X"
    parts.append(f"R:{r}({v('score_prev')}→{v('score')})")

    tr = "O" if conditions.get("trigger") else "X"
    b = "양" if values.get('is_bullish') else "음"
    parts.append(f"Tr:{tr}({b},{v('prev_close')}/{v('prev_ema3')})")

    return " ".join(parts)


@dataclass
class PreCheckResult:
    """
    Pre-Check 결과

    봉 완성 30초 전 조기 탐지 결과.

    Attributes:
        stock_code: 종목 코드
        conditions_met: 충족된 조건 수
        conditions: 개별 조건 충족 여부
        is_candidate: 신호 후보 여부 (3개 이상 충족)
        timestamp: 체크 시간
    """
    stock_code: str
    conditions_met: int
    conditions: Dict[str, bool]
    is_candidate: bool
    condition_values: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def meets_threshold(self) -> bool:
        """Pre-Check 임계값 충족 여부"""
        return self.conditions_met >= PRE_CHECK_MIN_CONDITIONS


class PurpleSignalDetector(BaseDetector, MultiConditionMixin, DualPassMixin):
    """
    Purple-ReAbs 신호 탐지기

    BaseDetector ABC를 상속하여 전략 플러그인 아키텍처와 호환됩니다.
    MultiConditionMixin: 다중 조건 검증 헬퍼
    DualPassMixin: Pre-Check / Confirm-Check 2단계 탐지

    5가지 조건을 확인하여 신호를 탐지합니다.

    Dual-Pass 탐지:
    1. Pre-Check (봉 완성 30초 전): 5개 중 3개 이상 충족 시 후보 등록
    2. Confirm-Check (봉 완성 시점): 5개 조건 모두 확인

    Usage:
        detector = PurpleSignalDetector()

        # Pre-Check
        pre_result = detector.pre_check("005930", "삼성전자", df)
        if pre_result.is_candidate:
            # 후보 등록

        # Confirm-Check
        signal = detector.confirm_check("005930", "삼성전자", df)
        if signal:
            # 신호 발생 처리
    """

    def __init__(
        self,
        min_candles: int = MIN_CANDLES_REQUIRED,
        logger: Optional[logging.Logger] = None,
    ):
        """
        PurpleSignalDetector 초기화

        Args:
            min_candles: 신호 탐지 최소 필요 캔들 수
            logger: 로거 (None이면 기본 로거 사용)
        """
        self.min_candles = min_candles
        self._logger = logger or logging.getLogger(__name__)
        self._pending_candidates: Dict[str, PreCheckResult] = {}
        self._candidates_lock = threading.RLock()  # P0: 동시 접근 보호

    # ===== BaseDetector ABC 구현 =====

    @property
    def strategy_name(self) -> str:
        return "PURPLE_REABS"

    @property
    def min_candles_required(self) -> int:
        return self.min_candles

    def detect(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str,
        **kwargs
    ) -> Optional[PurpleSignal]:
        """BaseDetector ABC 구현: detect_signal()에 위임"""
        return self.detect_signal(stock_code, stock_name, df)

    def _validate_data(self, df: pd.DataFrame) -> bool:
        """
        데이터 유효성 검증

        Args:
            df: OHLCV DataFrame

        Returns:
            True: 유효, False: 무효
        """
        if df is None or df.empty:
            return False

        required_cols = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_cols):
            return False

        if len(df) < self.min_candles:
            return False

        return True

    def check_trend(self, df: pd.DataFrame, stock_code: str = "") -> bool:
        """
        Trend 조건 확인

        Trend = EMA60 > EMA60[3] (EMA60 상승 추세)

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드 (로깅용)

        Returns:
            True: Trend 조건 충족
        """
        if len(df) < 60 + TREND_LOOKBACK:
            return False

        ema60 = PurpleIndicator.ema(df['close'], span=60)
        current_ema60 = ema60.iloc[-1]
        prev_ema60 = ema60.iloc[-1 - TREND_LOOKBACK]

        result = bool(current_ema60 > prev_ema60)

        if stock_code and not result:
            self._logger.debug(
                f"[Signal] {stock_code} Trend 미달: "
                f"EMA60 {current_ema60:.0f} <= {prev_ema60:.0f} (3봉전)"
            )

        return result

    def check_zone(
        self,
        df: pd.DataFrame,
        tolerance: float = ZONE_EMA60_TOLERANCE,
        stock_code: str = "",
    ) -> bool:
        """
        Zone 조건 확인

        Zone = C >= EMA60 × (1 - tolerance)

        Landing Zone: EMA60 근처 (0.5% 하회까지 허용)

        Args:
            df: OHLCV DataFrame
            tolerance: EMA60 대비 허용 범위 (기본 0.5%)
            stock_code: 종목 코드 (로깅용)

        Returns:
            True: Zone 조건 충족
        """
        if len(df) < 60:
            return False

        close = df['close'].iloc[-1]
        ema60 = PurpleIndicator.ema(df['close'], span=60).iloc[-1]
        threshold = ema60 * (1 - tolerance)

        result = bool(close >= threshold)

        if stock_code and not result:
            zone_pct = (close / ema60 - 1) * 100 if ema60 > 0 else 0
            self._logger.debug(
                f"[Signal] {stock_code} Zone 미달: "
                f"Close {close:.0f} < EMA60x0.995 ({threshold:.0f}), "
                f"EMA60 대비 {zone_pct:.2f}%"
            )

        return result

    def check_trigger(self, df: pd.DataFrame, stock_code: str = "") -> bool:
        """
        Trigger 조건 확인

        Trigger = CrossUp(C, EMA3) AND 양봉

        EMA3 상향 돌파 + 양봉 조건

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드 (로깅용)

        Returns:
            True: Trigger 조건 충족
        """
        if len(df) < 3:
            return False

        close = df['close']
        ema3 = PurpleIndicator.ema(close, span=3)

        # CrossUp: 이전 봉 close < EMA3, 현재 봉 close >= EMA3
        prev_close = close.iloc[-2]
        prev_ema3 = ema3.iloc[-2]
        curr_close = close.iloc[-1]
        curr_ema3 = ema3.iloc[-1]

        crossup = bool(prev_close < prev_ema3) and bool(curr_close >= curr_ema3)

        # 양봉: close > open
        is_bullish = bool(df['close'].iloc[-1] > df['open'].iloc[-1])

        result = crossup and is_bullish

        if stock_code and not result:
            reasons = []
            if not crossup:
                reasons.append(f"EMA3 미돌파(prev:{prev_close:.0f}<{prev_ema3:.0f}, curr:{curr_close:.0f}>={curr_ema3:.0f})")
            if not is_bullish:
                reasons.append("음봉")
            self._logger.debug(
                f"[Signal] {stock_code} Trigger 미달: {', '.join(reasons)}"
            )

        return result

    def check_purple_ok(self, df: pd.DataFrame, stock_code: str = "") -> bool:
        """
        PurpleOK 필터 확인

        PurpleOK = (H1/L1-1) >= 4% AND (H2/L2-1) <= 7% AND M >= 5억

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드 (로깅용)

        Returns:
            True: PurpleOK 조건 충족
        """
        if len(df) < 40:
            return False

        # 개별 값 계산
        rise = PurpleIndicator.rise_ratio(df).iloc[-1]
        conv = PurpleIndicator.convergence_ratio(df).iloc[-1]
        money = PurpleIndicator.money(df).iloc[-1]

        # [V7.1-Fix13] NaN 검증 (check_reabs_start 패턴과 동일)
        if pd.isna(rise) or pd.isna(conv) or pd.isna(money):
            if stock_code:
                self._logger.debug(
                    f"[Signal] {stock_code} PurpleOK 미달: "
                    f"NaN 값 (rise={rise}, conv={conv}, money={money})"
                )
            return False

        rise_ok = bool(rise >= 0.04)
        conv_ok = bool(conv <= 0.07)
        money_ok = bool(money >= 500_000_000)

        result = rise_ok and conv_ok and money_ok

        if stock_code and not result:
            self._logger.debug(
                f"[Signal] {stock_code} PurpleOK 미달: "
                f"상승률 {rise*100:.1f}%({'O' if rise_ok else 'X'}>=4%) "
                f"수렴률 {conv*100:.1f}%({'O' if conv_ok else 'X'}<=7%) "
                f"거래대금 {money/1e8:.1f}억({'O' if money_ok else 'X'}>=5억)"
            )

        return result

    def check_reabs_start(self, df: pd.DataFrame, stock_code: str = "") -> bool:
        """
        ReAbsStart 조건 확인

        ReAbsStart = S > S[1] (Score 재상승)

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드 (로깅용)

        Returns:
            True: ReAbsStart 조건 충족
        """
        # C-002 FIX: Score 계산에 필요한 최소 캔들 수 (70봉)
        # 기존: 20봉만 체크 → NaN 발생 시 False Negative
        # 수정: MIN_CANDLES_FOR_SCORE(70봉) 체크 + NaN 검증
        if len(df) < MIN_CANDLES_FOR_SCORE:
            if stock_code:
                self._logger.debug(
                    f"[Signal] {stock_code} ReAbsStart 미달: "
                    f"캔들 수 부족 ({len(df)}/{MIN_CANDLES_FOR_SCORE})"
                )
            return False

        score = PurpleIndicator.score(df)
        if len(score) < 2:
            return False

        curr_score = score.iloc[-1]
        prev_score = score.iloc[-2]

        # C-002 FIX: NaN 검증 추가 (NaN > NaN = False로 인한 False Negative 방지)
        if pd.isna(curr_score) or pd.isna(prev_score):
            if stock_code:
                self._logger.debug(
                    f"[Signal] {stock_code} ReAbsStart 미달: "
                    f"Score NaN (curr={curr_score}, prev={prev_score})"
                )
            return False

        result = bool(curr_score > prev_score)

        if stock_code and not result:
            delta = curr_score - prev_score
            self._logger.debug(
                f"[Signal] {stock_code} ReAbsStart 미달: "
                f"Score {prev_score:.3f}->{curr_score:.3f} ({delta:+.3f})"
            )

        return result

    def _check_all_conditions(
        self,
        df: pd.DataFrame,
        stock_code: str = "",
    ) -> Dict[str, bool]:
        """
        모든 조건 확인

        Args:
            df: OHLCV DataFrame
            stock_code: 종목 코드 (로깅용, 미달 시 DEBUG 로그 출력)

        Returns:
            조건별 충족 여부 딕셔너리
        """
        return {
            "purple_ok": self.check_purple_ok(df, stock_code),
            "trend": self.check_trend(df, stock_code),
            "zone": self.check_zone(df, stock_code=stock_code),
            "reabs_start": self.check_reabs_start(df, stock_code),
            "trigger": self.check_trigger(df, stock_code),
        }

    def _get_condition_values(self, df: pd.DataFrame) -> Dict[str, Any]:
        """조건별 실제 수치 추출 (진단 로깅용)"""
        values = {}
        try:
            close = df['close'].iloc[-1]
            open_price = df['open'].iloc[-1]

            # PurpleOK 구성요소
            rise = PurpleIndicator.rise_ratio(df).iloc[-1]
            conv = PurpleIndicator.convergence_ratio(df).iloc[-1]
            money = PurpleIndicator.money(df).iloc[-1]
            values['rise_pct'] = round(rise * 100, 2) if not pd.isna(rise) else None
            values['conv_pct'] = round(conv * 100, 2) if not pd.isna(conv) else None
            values['money_억'] = round(money / 1e8, 1) if not pd.isna(money) else None

            # Trend
            ema60 = PurpleIndicator.ema(df['close'], span=60)
            ema60_curr = ema60.iloc[-1]
            ema60_3ago = ema60.iloc[-1 - TREND_LOOKBACK] if len(ema60) > TREND_LOOKBACK else None
            values['ema60'] = round(ema60_curr, 0)
            values['ema60_3ago'] = round(ema60_3ago, 0) if ema60_3ago is not None else None

            # Zone
            threshold = ema60_curr * (1 - ZONE_EMA60_TOLERANCE)
            values['close'] = round(close, 0)
            values['zone_threshold'] = round(threshold, 0)

            # ReAbsStart
            score = PurpleIndicator.score(df)
            curr_score = score.iloc[-1]
            prev_score = score.iloc[-2] if len(score) > 1 else None
            values['score'] = round(curr_score, 4) if not pd.isna(curr_score) else None
            values['score_prev'] = round(prev_score, 4) if prev_score is not None and not pd.isna(prev_score) else None

            # Trigger
            ema3 = PurpleIndicator.ema(df['close'], span=3)
            values['prev_close'] = round(df['close'].iloc[-2], 0) if len(df) > 1 else None
            values['prev_ema3'] = round(ema3.iloc[-2], 0) if len(ema3) > 1 else None
            values['curr_ema3'] = round(ema3.iloc[-1], 0)
            values['is_bullish'] = bool(close > open_price)
        except Exception:
            pass

        return values

    def _get_signal_details(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        신호 세부 정보 추출

        Args:
            df: OHLCV DataFrame

        Returns:
            세부 정보 딕셔너리
        """
        details = {}

        # EMA values
        ema3 = PurpleIndicator.ema(df['close'], span=3).iloc[-1]
        ema60 = PurpleIndicator.ema(df['close'], span=60).iloc[-1]
        details['ema3'] = round(ema3, 2)
        details['ema60'] = round(ema60, 2)

        # Rise/Convergence
        rise_ratio = PurpleIndicator.rise_ratio(df).iloc[-1]
        conv_ratio = PurpleIndicator.convergence_ratio(df).iloc[-1]
        details['rise_pct'] = round(rise_ratio * 100, 2)
        details['convergence_pct'] = round(conv_ratio * 100, 2)

        # Money
        money = PurpleIndicator.money(df).iloc[-1]
        details['money'] = int(money)
        details['money_billion'] = round(money / 1_000_000_000, 2)

        # Score
        score = PurpleIndicator.score(df)
        details['score'] = round(score.iloc[-1], 4)
        details['score_prev'] = round(score.iloc[-2], 4) if len(score) > 1 else None

        # Zone 위치 (EMA60 대비 %)
        close = df['close'].iloc[-1]
        if ema60 > 0:
            details['zone_pct'] = round((close / ema60 - 1) * 100, 2)
        else:
            details['zone_pct'] = 0.0

        return details

    def detect_signal(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> Optional[PurpleSignal]:
        """
        신호 탐지 (5개 조건 모두 확인)

        Signal = PurpleOK AND Trend AND Zone AND ReAbsStart AND Trigger

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame

        Returns:
            PurpleSignal: 신호 발생 시, None: 신호 없음
        """
        if not self._validate_data(df):
            return None

        conditions = self._check_all_conditions(df)

        # 모든 조건 충족 확인
        all_met = all(conditions.values())

        if not all_met:
            return None

        # 신호 세부 정보 추출
        details = self._get_signal_details(df)

        # Confidence 계산 (신호 결정용 아님, 우선순위/분석용)
        confidence = calculate_confidence(details)

        return PurpleSignal(
            stock_code=stock_code,
            stock_name=stock_name,
            price=int(df['close'].iloc[-1]),
            score=details['score'],
            rise_ratio=details['rise_pct'] / 100,
            convergence_ratio=details['convergence_pct'] / 100,
            timestamp=datetime.now(),
            metadata={
                "conditions": conditions,
                **details,
            },
            confidence=confidence,
        )

    def pre_check(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> PreCheckResult:
        """
        Pre-Check (봉 완성 30초 전 조기 탐지)

        5개 중 3개 이상 충족 시 후보로 등록.
        Zero Signal Miss 원칙: 조건 근접 시 반드시 후보로 등록.

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame

        Returns:
            PreCheckResult: 조기 탐지 결과
        """
        if not self._validate_data(df):
            return PreCheckResult(
                stock_code=stock_code,
                conditions_met=0,
                conditions={},
                is_candidate=False,
            )

        conditions = self._check_all_conditions(df)
        conditions_met = sum(conditions.values())

        result = PreCheckResult(
            stock_code=stock_code,
            conditions_met=conditions_met,
            conditions=conditions,
            is_candidate=conditions_met >= PRE_CHECK_MIN_CONDITIONS,
        )

        # P0: Lock으로 후보 등록 보호
        if result.is_candidate:
            result.condition_values = self._get_condition_values(df)
            with self._candidates_lock:
                self._pending_candidates[stock_code] = result

        return result

    def confirm_check(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> Optional[PurpleSignal]:
        """
        Confirm-Check (봉 완성 시점 최종 확인)

        5개 조건 모두 확인하여 신호 확정.

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame

        Returns:
            PurpleSignal: 신호 확정 시, None: 신호 없음
        """
        # detect_signal과 동일한 로직
        signal = self.detect_signal(stock_code, stock_name, df)

        # P0: Lock으로 대기 후보 제거 보호
        with self._candidates_lock:
            if stock_code in self._pending_candidates:
                del self._pending_candidates[stock_code]

        return signal

    def is_pending_candidate(self, stock_code: str) -> bool:
        """
        대기 중인 후보인지 확인

        Args:
            stock_code: 종목 코드

        Returns:
            True: 대기 중인 후보
        """
        with self._candidates_lock:
            return stock_code in self._pending_candidates

    def get_pending_candidates(self) -> List[str]:
        """
        대기 중인 후보 목록 반환

        Returns:
            종목 코드 리스트
        """
        with self._candidates_lock:
            return list(self._pending_candidates.keys())

    def clear_pending_candidates(self) -> int:
        """
        대기 중인 후보 초기화

        Returns:
            제거된 후보 수
        """
        with self._candidates_lock:
            count = len(self._pending_candidates)
            self._pending_candidates.clear()
            return count

    def get_condition_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        조건 요약 정보 반환 (디버깅/분석용)

        Args:
            df: OHLCV DataFrame

        Returns:
            조건별 상세 정보 딕셔너리
        """
        if not self._validate_data(df):
            return {"error": "Invalid data"}

        conditions = self._check_all_conditions(df)
        details = self._get_signal_details(df)

        return {
            "conditions": conditions,
            "conditions_met": sum(conditions.values()),
            "total_conditions": len(conditions),
            "is_signal": all(conditions.values()),
            **details,
        }


class DualPassDetector:
    """
    Dual-Pass 신호 탐지 매니저

    Pre-Check와 Confirm-Check를 관리하는 상위 클래스.

    Usage:
        detector = DualPassDetector()

        # 봉 완성 30초 전
        candidates = await detector.run_pre_check(pool, candle_fetcher)

        # 봉 완성 시점
        signals = await detector.run_confirm_check(candidates, candle_fetcher)
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger(__name__)
        self.detector = PurpleSignalDetector(logger=self._logger)
        self._pre_check_results: Dict[str, PreCheckResult] = {}
        self._results_lock = threading.RLock()  # P0: 동시 접근 보호

    def run_pre_check_single(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> PreCheckResult:
        """
        단일 종목 Pre-Check 실행

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame

        Returns:
            PreCheckResult
        """
        result = self.detector.pre_check(stock_code, stock_name, df)
        if result.is_candidate:
            with self._results_lock:
                self._pre_check_results[stock_code] = result
        return result

    def run_confirm_check_single(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> Optional[PurpleSignal]:
        """
        단일 종목 Confirm-Check 실행

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            df: OHLCV DataFrame

        Returns:
            PurpleSignal: 신호 발생 시
        """
        signal = self.detector.confirm_check(stock_code, stock_name, df)

        # P0: Lock으로 Pre-Check 결과 정리 보호
        with self._results_lock:
            if stock_code in self._pre_check_results:
                del self._pre_check_results[stock_code]

        return signal

    def get_candidates(self) -> List[str]:
        """
        Pre-Check 후보 목록 반환

        Returns:
            종목 코드 리스트
        """
        with self._results_lock:
            return list(self._pre_check_results.keys())

    def clear_candidates(self) -> int:
        """
        후보 목록 초기화

        Returns:
            제거된 후보 수
        """
        with self._results_lock:
            count = len(self._pre_check_results)
            self._pre_check_results.clear()
        self.detector.clear_pending_candidates()
        return count

    def get_stats(self) -> Dict[str, Any]:
        """
        탐지 통계 반환

        Returns:
            통계 딕셔너리
        """
        with self._results_lock:
            return {
                "pending_candidates": len(self._pre_check_results),
                "candidate_codes": list(self._pre_check_results.keys()),
            }
