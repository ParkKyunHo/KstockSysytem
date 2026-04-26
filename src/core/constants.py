"""
트레이딩 시스템 상수 정의 (Phase 1 리팩토링)

모든 전략(V6 SNIPER_TRAP, V7 Purple-ReAbs)에서 사용하는 상수를 중앙 관리합니다.

CLAUDE.md 불변 조건:
- EMA adjust=False
- V7 Score 가중치: PRICE_VWAP_MULT=2.0, FUND_LZ_MULT=0.8, RECOVERY_MULT=1.2
- V7 PurpleOK 임계값: MIN_RISE_PCT=0.04, MAX_CONVERGENCE_PCT=0.07, MIN_BAR_VALUE=5억
- V7 ATR 배수 단계: 6.0 → 4.5 → 4.0 → 3.5 → 2.5 → 2.0 (복원 불가)
"""


class EMAConstants:
    """EMA 기간 상수"""
    SHORT = 3       # 단기 EMA (빠른 반응)
    MID = 20        # 중기 EMA (기준선)
    LONG = 60       # 장기 EMA (추세선)
    TREND = 200     # 대추세 EMA


class ATRConstants:
    """ATR 관련 상수"""
    DEFAULT_PERIOD = 10        # 기본 ATR 기간
    TRADINGVIEW_PERIOD = 14    # TradingView 기본 기간

    # Wave Harvest ATR 배수 (CLAUDE.md 불변 - 복원 불가)
    MULT_INITIAL = 6.0         # 초기 진입
    MULT_STRUCTURE_WARNING = 4.5  # 구조 경고
    MULT_R1 = 4.0              # R >= 1
    MULT_R2 = 3.5              # R >= 2
    MULT_R3 = 2.5              # R >= 3
    MULT_R5 = 2.0              # R >= 5


class VolumeConstants:
    """거래량 관련 상수"""
    AVG_PERIOD = 20            # 거래량 평균 기간


class TradingTimeConstants:
    """매매 시간 상수"""
    # 정규장
    MARKET_OPEN = "09:00"
    MARKET_CLOSE = "15:20"

    # 단일가
    SINGLE_PRICE_START = "15:20"
    SINGLE_PRICE_END = "15:30"

    # NXT 시장
    NXT_OPEN = "08:00"
    NXT_CLOSE = "20:00"

    # 신호 탐지
    SIGNAL_START = "09:05"
    SIGNAL_END = "15:20"


# ===========================================
# V7 Purple-ReAbs 상수 (CLAUDE.md 불변)
# ===========================================

class PurpleConstants:
    """V7 Purple-ReAbs 전략 상수"""

    # 지표 기간
    WEIGHTED_PRICE_PERIOD = 40   # W = sum(C*M, 40) / sum(M, 40)
    FUND_ZSCORE_PERIOD = 20      # LZ Z-Score 기간
    SCORE_SMOOTH_PERIOD = 10     # S = EMA(..., 10)
    H1L1_PERIOD = 40             # 상승률 계산 기간
    H2L2_PERIOD = 20             # 수렴률 계산 기간
    RECOVERY_LOOKBACK = 20       # 회복률 기간

    # Score 가중치 (CLAUDE.md 불변)
    PRICE_VWAP_MULT = 2.0        # (C/W - 1) × 2
    FUND_LZ_MULT = 0.8           # LZ × 0.8
    RECOVERY_MULT = 1.2          # recovery × 1.2

    # PurpleOK 임계값 (CLAUDE.md 불변)
    MIN_RISE_PCT = 0.04          # H1/L1 - 1 >= 4%
    MAX_CONVERGENCE_PCT = 0.07   # H2/L2 - 1 <= 7%
    MIN_BAR_VALUE = 500_000_000  # M >= 5억

    # Zone 허용 범위 (CLAUDE.md 불변)
    ZONE_EMA60_TOLERANCE = 0.005  # C >= EMA60 × 0.995 (0.5% 하회 허용)


class WaveHarvestConstants:
    """V7 Wave Harvest 청산 상수"""

    # R-Multiple 기준
    R_THRESHOLD_1 = 1.0   # ATR 4.0 적용
    R_THRESHOLD_2 = 2.0   # ATR 3.5 적용
    R_THRESHOLD_3 = 3.0   # ATR 2.5 적용
    R_THRESHOLD_5 = 5.0   # ATR 2.0 적용

    # 고정 손절 (CLAUDE.md 불변)
    SAFETY_STOP_RATE = -0.04  # -4% 고정 손절

    # 트레일링 스탑 기준
    TRAILING_BASE_PERIOD = 20  # Highest(High, 20)

    # Trend Hold Filter
    TREND_HOLD_EMA_SHORT = 20
    TREND_HOLD_EMA_LONG = 60


# ===========================================
# V6 SNIPER_TRAP 상수
# ===========================================

class SniperTrapConstants:
    """V6 SNIPER_TRAP 전략 상수"""

    # 지표 기간
    EMA_SHORT = 3
    EMA_MID = 20
    EMA_LONG = 60

    # Ceiling/Floor 기간
    CEILING_PERIOD = 20
    FLOOR_PERIOD = 20

    # 거래량 기준
    VOLUME_RATIO_THRESHOLD = 1.5  # 평균 대비 150%


# ===========================================
# 리스크 관리 상수
# ===========================================

class RiskConstants:
    """리스크 관리 상수"""

    # 포지션 크기
    DEFAULT_BUY_RATIO = 0.10     # 기본 매수 비율 10%
    MAX_POSITION_RATIO = 0.20    # 최대 포지션 비율 20%

    # 보유 기간
    MAX_HOLDING_DAYS = 60        # 최대 보유일

    # 슬리피지
    SLIPPAGE_RATE = 0.001        # 0.1% 슬리피지


# ===========================================
# API 상수
# ===========================================

class APIConstants:
    """API 관련 상수"""

    # 호출 속도 제한
    REAL_RATE_LIMIT = 4.5        # 실전: 초당 4.5회
    MOCK_RATE_LIMIT = 0.33       # 모의: 초당 0.33회

    # 병렬 처리
    DEFAULT_CONCURRENCY = 3      # 기본 동시 요청 수
    MAX_CONCURRENCY = 15         # 최대 동시 요청 수

    # 재시도
    MAX_RETRIES = 3
    RETRY_DELAY_SEC = 1.0
