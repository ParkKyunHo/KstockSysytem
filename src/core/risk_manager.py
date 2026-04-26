"""
리스크 관리 모듈

리스크 관리를 담당합니다:

진입 제한:
- Cooldown: 매도 후 15분 재진입 금지
- Max Try: 종목당 당일 최대 2회 진입
- Blacklist: 손절 종목 당일 영구 차단
- Daily Max Loss: 일일 최대 손실 한도
- Max Positions: 최대 동시 포지션 수

청산 로직 (V6.2-Q):
- Safety Net: bar_low <= entry_price × 0.96 (-4% 고정 손절)
- ATR Trailing Stop: close <= trailing_stop_price (ATR × 6.0 기반)
- Max Holding: 60일 초과 시 청산
- 수동 청산: 텔레그램 명령어

Note: Breakeven Stop, Floor Line은 V6.2-Q에서 제거됨
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from enum import Enum
import math
import threading  # V6.2-Q FIX: 동시성 Lock

from src.utils.logger import get_logger
from src.utils.config import get_risk_settings
from src.database.models import EntrySource, TradeStatus

# 부동소수점 비교용 허용 오차 (0.01% = 0.0001)
PROFIT_RATE_EPSILON = 0.01

if TYPE_CHECKING:
    from src.utils.config import RiskSettings


class ExitReason(str, Enum):
    """청산 사유"""
    # V6.2-Q 현재 사용
    HARD_STOP = "HARD_STOP"           # Safety Net (-4% 고정 손절)
    TRAILING_STOP = "TRAILING_STOP"   # ATR 트레일링 스탑
    TRAILING_STOP_TIGHT = "TRAILING_STOP_TIGHT"  # 구조 경고 시 타이트 TS (ATR × 4.5)
    MAX_HOLDING = "MAX_HOLDING"       # 최대 보유일 초과 (60일)
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"  # 분할 익절
    EOD_LIQUIDATE = "EOD_LIQUIDATE"   # 장 종료 청산
    MANUAL = "MANUAL"                 # 수동 청산

    # 레거시 (DB 호환성 유지, 신규 사용 금지)
    BREAKEVEN_STOP = "BREAKEVEN_STOP" # [레거시] 본전 손절 - V6.2-Q 삭제
    TECHNICAL_STOP = "TECHNICAL_STOP" # [레거시] Floor Line 이탈 - V6.2-Q 삭제
    TECHNICAL_EXIT = "TECHNICAL_EXIT" # [레거시] EMA 이탈
    TREND_BREAK = "TREND_BREAK"       # [레거시] M20 이탈
    TAKE_PROFIT = "TAKE_PROFIT"       # [레거시] 익절


class EntryBlockReason(str, Enum):
    """진입 차단 사유"""
    COOLDOWN = "COOLDOWN"             # 쿨다운 중
    MAX_TRY = "MAX_TRY"               # 최대 진입 횟수 초과
    BLACKLIST = "BLACKLIST"           # 블랙리스트
    MAX_POSITIONS = "MAX_POSITIONS"   # 최대 포지션 수 초과
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"  # 일일 손실 한도
    DUPLICATE_POSITION = "DUPLICATE_POSITION"  # V6.2-A: 이미 동일 종목 포지션 보유


@dataclass
class RiskConfig:
    """
    리스크 관리 설정

    환경 변수에서 기본값을 로드하며, 인스턴스 생성 시 오버라이드 가능.
    환경 변수 설정은 src.utils.config.RiskSettings 참조.
    """

    # Grand Trend V6: 청산 설정
    safety_stop_rate: float = field(default=-4.0)         # 고정 손절 -4%
    partial_take_profit_rate: float = field(default=10.0) # 분할 익절 트리거 +10%
    partial_exit_ratio: float = field(default=0.5)        # 분할 익절 비율 (50%)

    # PRD v2.5 보완: 트레일링 스탑 (분할 익절 후 적용)
    trailing_stop_rate: float = field(default=-2.5)       # 최고점 대비 하락률 (-2.5%)

    # 쿨다운 (분)
    cooldown_minutes: int = field(default=15)

    # 종목당 최대 진입 횟수
    max_try_per_stock: int = field(default=2)

    # PRD v3.2: 최대 동시 포지션 수 (5→3)
    max_positions: int = field(default=3)

    # 일일 최대 손실액 (원)
    daily_max_loss: int = field(default=500_000)

    # 상한가 비율 (%)
    limit_up_rate: float = field(default=30.0)

    # V6.2-E: NXT 시장조작 방어
    extreme_drop_threshold: float = field(default=-0.15)  # 극단값 임계치 (-15%)

    @classmethod
    def from_settings(cls) -> "RiskConfig":
        """환경 변수에서 설정을 로드하여 RiskConfig 생성"""
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
        settings = get_risk_settings()
        logger.info(
            f"[RiskConfig] 환경변수 로드: "
            f"PARTIAL={settings.partial_take_profit_rate}%, "
            f"SAFETY={settings.safety_stop_rate}%"
        )
        return cls(
            safety_stop_rate=settings.safety_stop_rate,
            partial_take_profit_rate=settings.partial_take_profit_rate,
            partial_exit_ratio=settings.partial_exit_ratio,
            cooldown_minutes=15,  # 청산 후 재진입 금지 15분 (고정값)
            max_try_per_stock=settings.max_try_per_stock,
            max_positions=settings.max_positions,
            daily_max_loss=settings.daily_max_loss,
            # V6.2-E: NXT 시장조작 방어
            extreme_drop_threshold=settings.extreme_drop_threshold,
        )


# ========================================
# Grand Trend V6.2-A: 구조 경고 (Structure Warning)
# ========================================

@dataclass
class StructureWarning:
    """
    구조 경고 상태 추적 (V6.2-A)

    EMA9/VWAP 하회 연속 봉 수를 추적하여 TS 타이트닝 여부를 결정합니다.
    warnNow = emaWarn OR (useVWAPWarn AND vwapWarn) OR hlBreak

    핵심: warnNow는 '즉시 청산'이 아니라 TS 정책 전환 신호
    - 기본 ATR 배수: 6.0
    - 경고 시 ATR 배수: 4.5 (타이트닝)
    """
    stock_code: str
    ema9_below_count: int = 0           # EMA9 하회 연속 봉 수
    vwap_below_count: int = 0           # VWAP(hlc3) 하회 연속 봉 수
    last_pivot_low: float = 0           # 마지막 피봇 로우 (옵션, USE_HL_BREAK)
    is_warning: bool = False            # 현재 경고 상태
    warning_type: str = ""              # 경고 유형 ("ema9", "vwap", "hl_break")

    def update(
        self,
        close: float,
        ema9: float,
        hlc3: float,
        confirm_bars: int = 2,
        use_vwap_warn: bool = True,
        use_hl_break: bool = False
    ) -> bool:
        """
        3분봉 완성 시 경고 상태 업데이트

        Args:
            close: 현재 종가
            ema9: EMA(9) 값
            hlc3: (High + Low + Close) / 3 - VWAP 근사값
            confirm_bars: 연속 확인 봉 수 (기본 2)
            use_vwap_warn: VWAP 경고 사용 여부
            use_hl_break: 피봇 로우 이탈 사용 여부 (옵션)

        Returns:
            경고 상태 (True: 경고 발생)
        """
        # EMA9 경고: close < EMA9가 confirmBars 연속 발생
        if close < ema9:
            self.ema9_below_count += 1
        else:
            self.ema9_below_count = 0

        # VWAP 경고: close < hlc3가 confirmBars 연속 발생
        if close < hlc3:
            self.vwap_below_count += 1
        else:
            self.vwap_below_count = 0

        # 경고 판정
        ema_warn = self.ema9_below_count >= confirm_bars
        vwap_warn = self.vwap_below_count >= confirm_bars if use_vwap_warn else False
        hl_break = use_hl_break and self.last_pivot_low > 0 and close < self.last_pivot_low

        # 종합 경고
        self.is_warning = ema_warn or vwap_warn or hl_break

        # 경고 유형 기록
        if ema_warn:
            self.warning_type = "ema9"
        elif vwap_warn:
            self.warning_type = "vwap"
        elif hl_break:
            self.warning_type = "hl_break"
        else:
            self.warning_type = ""

        return self.is_warning

    def reset(self) -> None:
        """경고 상태 초기화"""
        self.ema9_below_count = 0
        self.vwap_below_count = 0
        self.is_warning = False
        self.warning_type = ""


@dataclass
class PositionRisk:
    """포지션별 리스크 정보"""
    stock_code: str
    entry_price: int                    # 진입 가격
    quantity: int                       # 현재 수량 (분할 매도 후 감소)
    entry_time: datetime                # 진입 시간
    highest_price: int                  # 보유 중 최고가

    # Grand Trend V6.2-A: ATR 트레일링 스탑 (진입 즉시 활성화)
    trailing_stop_price: int = 0        # ATR 기반 트레일링 스탑 가격 (상승만)

    # V6.2-I: 매수 시점 ATR 값 저장 (TS 계산 시 최소값 보장용)
    entry_atr: float = 0.0

    # Grand Trend V6.2-A: 보유일 관리
    entry_date: Optional[date] = None   # 진입 날짜 (최대 보유일 계산용)

    # Grand Trend V6.2-A: 구조 경고 상태
    structure_warning: Optional[StructureWarning] = None

    # [레거시] 분할 익절 관련 (V6.2-A에서는 비활성화)
    is_partial_exit: bool = False       # 분할 매도 완료 여부 (USE_PARTIAL_EXIT=false 시 무시)

    # PRD v3.2.5: 원래 매수 수량 (수량 기반 분할익절 검증용)
    entry_quantity: int = 0             # 최초 매수 수량 (변하지 않음)

    # 진입 출처 (HTS 분할익절 제외용)
    entry_source: EntrySource = EntrySource.SYSTEM

    # V6.2-A 코드리뷰 C2: TS 초기화 실패 복구 플래그
    # - fallback TS(-4%) 사용 중인지 표시
    # - 이후 정상 TS 업데이트 성공 시 자동 해제
    is_ts_fallback: bool = False

    def update_highest(self, price: int) -> None:
        """최고가 갱신"""
        if price > self.highest_price:
            self.highest_price = price

    def get_profit_rate(self, current_price: int) -> float:
        """현재 수익률 (%)"""
        if self.entry_price == 0:
            return 0.0
        return ((current_price - self.entry_price) / self.entry_price) * 100

    def get_from_highest_rate(self, current_price: int) -> float:
        """고점 대비 하락률 (%)"""
        if self.highest_price == 0:
            return 0.0
        return ((current_price - self.highest_price) / self.highest_price) * 100

    def update_trailing_stop(self, new_stop: int) -> bool:
        """
        Grand Trend V6.2-A: ATR 트레일링 스탑 갱신 (상승만)

        Pine Script 로직: trailStop := max(ts_line, trailStop[1])
        - 새 스탑이 기존보다 높으면 갱신
        - 낮으면 무시 (절대 하락 안 함)

        Args:
            new_stop: 새 트레일링 스탑 가격 (close - ATR*mult)

        Returns:
            갱신 여부
        """
        if new_stop > self.trailing_stop_price:
            self.trailing_stop_price = new_stop

            # V6.2-A 코드리뷰 C2: fallback 상태 해제
            # - 정상적인 ATR 기반 TS 업데이트 성공 시 fallback 해제
            if self.is_ts_fallback:
                self.is_ts_fallback = False

            return True
        return False

    def get_holding_days(self) -> int:
        """
        V6.2-A Phase 4: 보유일 계산 (거래일 기준)

        주말을 제외한 영업일 기준으로 계산합니다.
        공휴일은 포함되나, 실전에서 무시 가능한 수준입니다.

        Returns:
            보유일 수 (entry_date가 없으면 0)
        """
        if self.entry_date is None:
            return 0

        # V6.2-A Phase 4: 거래일 기준 (주말 제외)
        count = 0
        current = self.entry_date
        today = date.today()
        while current < today:
            if current.weekday() < 5:  # 월(0)~금(4)
                count += 1
            current += timedelta(days=1)
        return count

    def init_structure_warning(self) -> None:
        """V6.2-A: 구조 경고 상태 초기화"""
        if self.structure_warning is None:
            self.structure_warning = StructureWarning(stock_code=self.stock_code)
        else:
            self.structure_warning.reset()

    def get_ts_multiplier(self, base: float = 6.0, tight: float = 4.5) -> float:
        """
        V6.2-A: 현재 상태에 따른 ATR 배수 반환

        Args:
            base: 기본 ATR 배수 (기본 6.0)
            tight: 경고 시 ATR 배수 (기본 4.5)

        Returns:
            ATR 배수 (경고 시 tight, 아니면 base)
        """
        if self.structure_warning and self.structure_warning.is_warning:
            return tight
        return base


class RiskManager:
    """
    리스크 관리자

    진입 전 검증, 청산 조건 체크, 쿨다운/블랙리스트 관리를 담당합니다.

    Note: PositionManager가 포지션 데이터의 Single Source of Truth입니다.
    RiskManager는 리스크 관련 추적(쿨다운, 블랙리스트, 일일손익 등)만 담당합니다.

    Usage:
        risk_manager = RiskManager()
        risk_manager.set_position_manager(position_manager)  # 필수!
        can_enter, reason = risk_manager.can_enter(stock_code)
        exit_reason = risk_manager.check_exit(position_risk, current_price)
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self._config = config or RiskConfig()
        self._logger = get_logger(__name__)

        # PositionManager 참조 (Single Source of Truth)
        self._position_manager: Optional["PositionManager"] = None

        # 쿨다운 (종목코드 -> 쿨다운 종료 시간)
        self._cooldowns: Dict[str, datetime] = {}

        # 진입 횟수 (종목코드 -> 당일 진입 횟수)
        self._try_counts: Dict[str, int] = {}

        # 블랙리스트 (당일 손절 종목)
        self._blacklist: Set[str] = set()

        # 포지션별 리스크 추적 정보 (최고가, breakeven 등 - PositionManager와 별도)
        self._position_risks: Dict[str, PositionRisk] = {}

        # 일일 손익
        self._daily_pnl: int = 0
        self._pnl_lock = threading.Lock()  # V6.2-Q FIX: daily_pnl 동시성 보호

        # 당일 시작 시간 (리셋용)
        self._trading_date: Optional[datetime] = None

    def set_position_manager(self, position_manager: "PositionManager") -> None:
        """
        PositionManager 참조 설정

        RiskManager는 PositionManager를 통해 포지션 수를 확인합니다.
        """
        self._position_manager = position_manager
        self._logger.debug("PositionManager 참조 설정 완료")

    def reset_daily(self) -> None:
        """당일 데이터 리셋 (새 거래일 시작)"""
        today = datetime.now().date()
        if self._trading_date is None or self._trading_date.date() != today:
            self._cooldowns.clear()
            self._try_counts.clear()
            self._blacklist.clear()
            with self._pnl_lock:  # V6.2-Q FIX: Lock으로 보호
                self._daily_pnl = 0
            self._trading_date = datetime.now()
            self._logger.info("리스크 매니저 일일 리셋 완료")

    async def restore_from_db(self, trade_repo) -> None:
        """
        V6.2-A 코드리뷰 A4: 재시작 시 쿨다운/블랙리스트 복구

        당일 거래 기록에서 쿨다운, 블랙리스트, 진입 시도 횟수를 복구합니다.
        시스템 재시작 시 손절 종목 재진입 방지를 위해 필수입니다.

        Args:
            trade_repo: TradeRepository 인스턴스
        """
        from datetime import date as date_type

        today = date_type.today()
        today_trades = await trade_repo.get_trades_by_date(today)

        if not today_trades:
            self._logger.info("[복구] 당일 거래 기록 없음")
            return

        restored_blacklist = 0
        restored_cooldowns = 0

        for trade in today_trades:
            stock_code = trade.stock_code

            # 진입 시도 횟수 복구 (모든 거래 카운트)
            self._try_counts[stock_code] = self._try_counts.get(stock_code, 0) + 1

            # 청산된 거래만 처리
            if trade.status != TradeStatus.CLOSED:
                continue

            # 블랙리스트: 손절 종목 (HARD_STOP, TRAILING_STOP, TRAILING_STOP_TIGHT 등)
            if trade.exit_reason in [
                ExitReason.HARD_STOP.value,
                ExitReason.TRAILING_STOP.value,
                ExitReason.TRAILING_STOP_TIGHT.value,
                ExitReason.BREAKEVEN_STOP.value,
                ExitReason.TECHNICAL_STOP.value,
            ]:
                self._blacklist.add(stock_code)
                restored_blacklist += 1

            # 쿨다운: 최근 청산 종목 (cooldown_minutes 이내)
            if trade.exit_time:
                cooldown_end = trade.exit_time + timedelta(minutes=self._config.cooldown_minutes)
                if datetime.now() < cooldown_end:
                    # 기존 쿨다운이 없거나, 더 긴 쿨다운으로 업데이트
                    if stock_code not in self._cooldowns or self._cooldowns[stock_code] < cooldown_end:
                        self._cooldowns[stock_code] = cooldown_end
                        restored_cooldowns += 1

        self._logger.info(
            f"[V6.2-A 복구] 블랙리스트: {restored_blacklist}개, "
            f"쿨다운: {restored_cooldowns}개, "
            f"진입시도: {len(self._try_counts)}종목"
        )

    # =========================================
    # 진입 검증
    # =========================================

    def can_enter(self, stock_code: str) -> Tuple[bool, Optional[EntryBlockReason], str]:
        """
        진입 가능 여부 검증

        Args:
            stock_code: 종목 코드

        Returns:
            (가능 여부, 차단 사유, 상세 메시지)
        """
        self.reset_daily()

        # 0. V6.2-A 안정성: 중복 포지션 체크 (최우선)
        if self._position_manager and self._position_manager.has_position(stock_code):
            return (
                False,
                EntryBlockReason.DUPLICATE_POSITION,
                f"이미 포지션 보유 중: {stock_code}",
            )

        # 1. 일일 손실 한도 체크 (V7.0-C1 FIX: Lock으로 보호)
        with self._pnl_lock:
            current_pnl = self._daily_pnl
        if current_pnl <= -self._config.daily_max_loss:
            return (
                False,
                EntryBlockReason.DAILY_LOSS_LIMIT,
                f"일일 손실 한도 초과 ({current_pnl:,}원)",
            )

        # 2. 최대 포지션 수 체크 (PositionManager 참조)
        position_count = (
            self._position_manager.get_position_count()
            if self._position_manager
            else len(self._position_risks)
        )
        if position_count >= self._config.max_positions:
            return (
                False,
                EntryBlockReason.MAX_POSITIONS,
                f"최대 포지션 수 초과 ({position_count}/{self._config.max_positions})",
            )

        # 3. 블랙리스트 체크
        if stock_code in self._blacklist:
            return (
                False,
                EntryBlockReason.BLACKLIST,
                f"블랙리스트 종목 (손절 이력)",
            )

        # 4. 쿨다운 체크
        if stock_code in self._cooldowns:
            cooldown_end = self._cooldowns[stock_code]
            if datetime.now() < cooldown_end:
                remaining = (cooldown_end - datetime.now()).seconds // 60
                return (
                    False,
                    EntryBlockReason.COOLDOWN,
                    f"쿨다운 중 ({remaining}분 남음)",
                )
            else:
                # 쿨다운 만료 - 삭제
                del self._cooldowns[stock_code]

        # 5. 최대 진입 횟수 체크
        try_count = self._try_counts.get(stock_code, 0)
        if try_count >= self._config.max_try_per_stock:
            return (
                False,
                EntryBlockReason.MAX_TRY,
                f"최대 진입 횟수 초과 ({try_count}/{self._config.max_try_per_stock}회)",
            )

        return (True, None, "진입 가능")

    def on_entry(
        self,
        stock_code: str,
        entry_price: int,
        quantity: int,
        # PRD v3.0: 포지션 복구용 파라미터
        is_partial_exit: bool = False,
        highest_price: int = 0,
        # PRD v3.2.2: 진입 출처 (HTS 분할익절 제외용)
        entry_source: EntrySource = EntrySource.SYSTEM,
    ) -> None:
        """
        진입 시 호출 (V6.2-Q: Floor Line 제거)

        PRD v3.0: 포지션 복구 시 is_partial_exit, highest_price 전달
        PRD v3.2.2: entry_source로 HTS 매수 식별

        Args:
            stock_code: 종목 코드
            entry_price: 진입 가격
            quantity: 수량
            is_partial_exit: 분할 매도 완료 여부 (복구용)
            highest_price: 분할 익절 후 최고가 (복구용)
            entry_source: 진입 출처 (MANUAL, SYSTEM, HTS, RESTORED)
        """
        # 진입 횟수 증가
        self._try_counts[stock_code] = self._try_counts.get(stock_code, 0) + 1

        # PRD v3.0: 복구 시 highest_price가 없으면 entry_price 사용
        if highest_price == 0:
            highest_price = entry_price

        # 포지션 리스크 추적 정보 등록
        self._position_risks[stock_code] = PositionRisk(
            stock_code=stock_code,
            entry_price=entry_price,
            quantity=quantity,
            entry_quantity=quantity,  # PRD v3.2.5: 원래 매수 수량 저장
            entry_time=datetime.now(),
            entry_date=date.today(),  # V6.2-Q FIX: MAX_HOLDING 60일 청산을 위해 필수
            highest_price=highest_price,
            is_partial_exit=is_partial_exit,
            entry_source=entry_source,  # PRD v3.2.2
        )

        self._logger.info(
            f"포지션 리스크 등록: {stock_code}",
            entry_price=entry_price,
            quantity=quantity,
            try_count=self._try_counts[stock_code],
        )

    # =========================================
    # 청산 조건 체크
    # =========================================

    def check_exit(
        self,
        stock_code: str,
        current_price: int,
    ) -> Tuple[bool, Optional[ExitReason], str]:
        """
        청산 조건 체크 (V6.2-Q: Floor Line 제거, Safety Net만 사용)

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            (청산 필요 여부, 청산 사유, 상세 메시지)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return (False, None, "포지션 없음")

        # 최고가 갱신 (기록용)
        position_risk.update_highest(current_price)

        # 수익률 계산
        profit_rate = position_risk.get_profit_rate(current_price)

        # 상한가 체크 (매도 불가 - 정보 제공용)
        if self._is_limit_up(position_risk.entry_price, current_price):
            return (False, None, f"상한가 도달 - Hold (수익률: {profit_rate:.1f}%)")

        # Safety Net (-4% 하드 손절)
        # 진입가 대비 -4% 도달 시 청산
        if profit_rate <= self._config.safety_stop_rate + PROFIT_RATE_EPSILON:
            return (
                True,
                ExitReason.HARD_STOP,
                f"Safety Stop ({profit_rate:.1f}% ≤ {self._config.safety_stop_rate}%)"
            )

        # 손절 조건에 해당하지 않으면 보유 유지
        return (False, None, f"보유 중 (수익률: {profit_rate:.1f}%)")

    def _is_limit_up(self, entry_price: int, current_price: int) -> bool:
        """상한가 여부 (가격 제한폭 기준)"""
        # 가격대별 상한가 계산 (실제로는 전일 종가 기준이지만, 간단히 처리)
        limit_up_price = int(entry_price * (1 + self._config.limit_up_rate / 100))
        return current_price >= limit_up_price

    # =========================================
    # PRD v2.5: 분할 매도 체크
    # =========================================

    def check_partial_exit(
        self,
        stock_code: str,
        current_price: int,
    ) -> Optional[dict]:
        """
        분할 매도 조건 체크

        PRD v2.5: +3% 도달 시 50% 분할 매도
        - 수익률 >= partial_take_profit_rate(3%)
        - is_partial_exit == False (아직 분할 매도 안함)

        PRD v3.2.5: 수량 기반 검증 추가
        - DB 오류/크래시 후 복구 시 수량으로 분할 익절 여부 재검증
        - 현재 수량 < 원래 수량 × 90% → 이미 분할 익절 완료로 간주

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            분할 매도 정보 딕셔너리 또는 None
            {
                "trigger": True,
                "quantity": 매도 수량 (50%, 올림),
                "new_stop_loss": 새 손절가 (평단가 = 본전컷),
                "profit_rate": 현재 수익률,
            }
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return None

        # 이미 분할 매도 완료
        if position_risk.is_partial_exit:
            return None

        # PRD v3.2.5: 수량 기반 분할 익절 검증 (DB 오류/크래시 복구용)
        # 현재 수량이 원래 수량의 90% 미만이면 이미 분할 익절 완료로 간주
        if position_risk.entry_quantity > 0:
            quantity_ratio = position_risk.quantity / position_risk.entry_quantity
            if quantity_ratio < 0.9:
                # 이미 10% 이상 매도됨 → 분할 익절 완료로 상태 복구
                position_risk.is_partial_exit = True
                self._logger.warning(
                    f"[수량 기반 복구] 분할 익절 상태로 전환: {stock_code} "
                    f"(현재 {position_risk.quantity}주 / 원래 {position_risk.entry_quantity}주 = {quantity_ratio:.1%})"
                )
                return None

        # Grand Trend V6: HTS 매수 종목도 분할익절 적용 (기존 제외 조건 삭제)

        # 수익률 계산
        profit_rate = position_risk.get_profit_rate(current_price)

        # +3% 이상이면 분할 매도 트리거
        # EPSILON 적용: 부동소수점 비교 오차 방지
        if profit_rate >= self._config.partial_take_profit_rate - PROFIT_RATE_EPSILON:
            # 50% 수량 (올림 처리)
            partial_quantity = math.ceil(position_risk.quantity * self._config.partial_exit_ratio)

            # 남은 수량 확인 (최소 1주 남겨야 함)
            remaining = position_risk.quantity - partial_quantity
            if remaining < 1:
                partial_quantity = position_risk.quantity - 1
                if partial_quantity < 1:
                    return None  # 수량이 너무 적어 분할 매도 불가

            return {
                "trigger": True,
                "quantity": partial_quantity,
                "new_stop_loss": position_risk.entry_price,  # 본전컷
                "profit_rate": profit_rate,
            }

        return None

    def on_partial_exit(
        self,
        stock_code: str,
        exit_quantity: int,
        exit_price: int,
        new_stop_loss: int,
    ) -> int:
        """
        분할 매도 완료 시 호출

        PRD v2.5 보완: 분할 익절 후 트레일링 스탑 활성화
        - highest_price를 현재가로 초기화 (추세 추종 시작점)

        Args:
            stock_code: 종목 코드
            exit_quantity: 매도 수량
            exit_price: 매도 가격
            new_stop_loss: 새 손절가 (평단가)

        Returns:
            실현 손익 (원)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return 0

        # 실현 손익 계산 (분할 매도분)
        pnl = (exit_price - position_risk.entry_price) * exit_quantity
        with self._pnl_lock:  # V6.2-Q FIX: Lock으로 보호
            self._daily_pnl += pnl

        # 상태 업데이트
        position_risk.is_partial_exit = True
        position_risk.quantity -= exit_quantity
        position_risk.highest_price = exit_price  # PRD v2.5 보완: 트레일링 스탑 시작점

        self._logger.info(
            f"분할 매도 완료: {stock_code}",
            exit_quantity=exit_quantity,
            exit_price=exit_price,
            remaining_quantity=position_risk.quantity,
            new_stop_loss=new_stop_loss,
            highest_price=exit_price,
            pnl=pnl,
        )

        return pnl

    def rollback_partial_exit(
        self,
        stock_code: str,
        original_quantity: int,
        original_highest_price: int,
        pnl_to_revert: int,
    ) -> None:
        """
        분할 매도 롤백 (DB 업데이트 실패 시)

        Args:
            stock_code: 종목 코드
            original_quantity: 원래 수량
            original_highest_price: 원래 최고가
            pnl_to_revert: 되돌릴 손익
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return

        position_risk.is_partial_exit = False
        position_risk.quantity = original_quantity
        position_risk.highest_price = original_highest_price
        with self._pnl_lock:  # V6.2-Q FIX: Lock으로 보호
            self._daily_pnl -= pnl_to_revert

        self._logger.warning(
            f"분할 매도 롤백: {stock_code}",
            quantity=original_quantity,
        )

    # =========================================
    # 청산 후 처리
    # =========================================

    def on_exit(
        self,
        stock_code: str,
        exit_price: int,
        reason: ExitReason,
    ) -> int:
        """
        청산 시 호출

        Args:
            stock_code: 종목 코드
            exit_price: 청산 가격
            reason: 청산 사유

        Returns:
            손익 금액 (원)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return 0

        # 손익 계산
        pnl = (exit_price - position_risk.entry_price) * position_risk.quantity
        with self._pnl_lock:  # V6.2-Q FIX: Lock으로 보호
            self._daily_pnl += pnl

        # 쿨다운 설정
        cooldown_end = datetime.now() + timedelta(minutes=self._config.cooldown_minutes)
        self._cooldowns[stock_code] = cooldown_end

        # 손절 시 블랙리스트 추가 (V7.0-C3 FIX: TRAILING_STOP_TIGHT 추가)
        if reason in [
            ExitReason.HARD_STOP,
            ExitReason.BREAKEVEN_STOP,
            ExitReason.TECHNICAL_STOP,
            ExitReason.TRAILING_STOP,
            ExitReason.TRAILING_STOP_TIGHT,  # V7.0-C3: 구조 경고 손절도 블랙리스트
        ]:
            self._blacklist.add(stock_code)
            self._logger.warning(f"블랙리스트 추가: {stock_code} ({reason.value})")

        # 포지션 리스크 정보 제거
        del self._position_risks[stock_code]

        self._logger.info(
            f"포지션 리스크 청산: {stock_code}",
            reason=reason.value,
            pnl=pnl,
            daily_pnl=self._daily_pnl,
        )

        return pnl

    # =========================================
    # 조회
    # =========================================

    def get_position_risk(self, stock_code: str) -> Optional[PositionRisk]:
        """포지션 리스크 정보 조회"""
        return self._position_risks.get(stock_code)

    def get_all_position_risks(self) -> Dict[str, PositionRisk]:
        """모든 포지션 리스크 정보 조회"""
        return self._position_risks.copy()

    def get_daily_pnl(self) -> int:
        """일일 손익 (V7.0-C2 FIX: Lock으로 보호)"""
        with self._pnl_lock:
            return self._daily_pnl

    def get_position_count(self) -> int:
        """
        현재 포지션 수

        PositionManager가 설정되어 있으면 PositionManager에서 조회,
        그렇지 않으면 내부 리스크 정보에서 조회
        """
        if self._position_manager:
            return self._position_manager.get_position_count()
        return len(self._position_risks)

    def is_blacklisted(self, stock_code: str) -> bool:
        """블랙리스트 여부"""
        return stock_code in self._blacklist

    def is_in_cooldown(self, stock_code: str) -> bool:
        """쿨다운 중 여부"""
        if stock_code not in self._cooldowns:
            return False
        return datetime.now() < self._cooldowns[stock_code]

    def get_try_count(self, stock_code: str) -> int:
        """진입 횟수 조회"""
        return self._try_counts.get(stock_code, 0)

    def get_status_summary(self) -> str:
        """리스크 상태 요약"""
        position_count = self.get_position_count()
        lines = [
            f"일일 손익: {self._daily_pnl:+,}원",
            f"포지션 수: {position_count}/{self._config.max_positions}",
            f"블랙리스트: {len(self._blacklist)}종목",
            f"쿨다운 중: {sum(1 for c in self._cooldowns.values() if datetime.now() < c)}종목",
        ]
        return "\n".join(lines)

    # =========================================
    # 외부 수량 동기화 (HTS 매매 대응)
    # =========================================

    def sync_quantity(self, stock_code: str, new_quantity: int) -> bool:
        """
        외부 매매(HTS)로 인한 수량 동기화

        PositionManager.sync_with_api()에서 API 잔고와 동기화 후 호출됩니다.
        RiskManager의 position_risk.quantity를 업데이트하여 불일치를 방지합니다.

        PRD v3.2.5: 수량 감소 시 분할 익절 상태 자동 전환
        - 원래 수량의 90% 미만으로 감소 시 is_partial_exit=True로 설정
        - DB 오류/크래시 후에도 중복 분할 매도 방지

        Args:
            stock_code: 종목 코드
            new_quantity: 새 수량 (API 조회 결과)

        Returns:
            동기화 성공 여부 (True: 분할 익절 상태 전환 필요)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False

        old_qty = position_risk.quantity
        if old_qty != new_quantity:
            position_risk.quantity = new_quantity
            self._logger.info(
                f"RiskManager 수량 동기화: {stock_code}",
                old_quantity=old_qty,
                new_quantity=new_quantity,
            )

            # PRD v3.2.5: 수량 감소 감지 시 분할 익절 상태 전환
            # 원래 수량의 90% 미만이면 이미 분할 익절 완료로 간주
            if (
                not position_risk.is_partial_exit
                and position_risk.entry_quantity > 0
                and new_quantity < position_risk.entry_quantity * 0.9
            ):
                position_risk.is_partial_exit = True
                self._logger.warning(
                    f"[수량 기반 복구] 분할 익절 상태로 전환: {stock_code} "
                    f"(수량 {old_qty}→{new_quantity}주, "
                    f"원래 {position_risk.entry_quantity}주)"
                )
                # True 리턴 → 호출자(TradingEngine)에서 트레일링 스탑 초기화 필요
                return True

            return True

        return False

    def sync_entry_price(
        self,
        stock_code: str,
        new_entry_price: int,
        reset_trailing_stop: bool = True,
    ) -> bool:
        """
        평균단가 동기화 (HTS 추가 매수 대응)

        V6.3: entry_price 변경에 따른 리스크 관리 재설정.
        - entry_price 갱신
        - 트레일링 스탑 초기화 (reset_trailing_stop=True 시)
        - 분할 익절 상태는 유지

        Args:
            stock_code: 종목 코드
            new_entry_price: 새 평균단가
            reset_trailing_stop: TS 재초기화 여부 (기본 True)

        Returns:
            동기화 성공 여부 (True 시 TS 재초기화 필요)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False

        old_entry_price = position_risk.entry_price
        if old_entry_price == new_entry_price:
            return False

        # 1. entry_price 갱신
        position_risk.entry_price = new_entry_price

        # 2. entry_quantity는 유지 (최초 진입 기준 - 분할 익절 판정에 사용)

        # 3. 트레일링 스탑 리셋
        if reset_trailing_stop:
            # Safety Net 수준으로 리셋 (TradingEngine에서 ATR 재계산)
            safety_net = int(new_entry_price * (1 + self._config.safety_stop_rate / 100))
            position_risk.trailing_stop_price = safety_net
            position_risk.is_ts_fallback = True  # 재초기화 필요 플래그

        # 4. highest_price는 유지 (이미 달성한 고점 기록)

        # 5. 분할 익절 후 추가 매수: 본전컷 기준 갱신
        if position_risk.is_partial_exit:
            # 새 평균단가가 본전컷 기준이 됨
            if position_risk.trailing_stop_price < new_entry_price:
                position_risk.trailing_stop_price = new_entry_price
                self._logger.info(
                    f"[분할 익절 중 추가 매수] 본전컷 갱신: {stock_code} → {new_entry_price:,}원"
                )

        self._logger.info(
            f"RiskManager entry_price 동기화: {stock_code}",
            old_entry_price=old_entry_price,
            new_entry_price=new_entry_price,
            new_safety_net=int(new_entry_price * (1 + self._config.safety_stop_rate / 100)),
        )

        return reset_trailing_stop  # TS 재초기화 필요 여부 리턴

    def remove_position_risk(self, stock_code: str) -> bool:
        """
        포지션 리스크 정보 제거 (HTS 청산 대응)

        PositionManager.sync_with_api()에서 HTS 청산 감지 시 호출됩니다.

        Args:
            stock_code: 종목 코드

        Returns:
            제거 성공 여부
        """
        if stock_code in self._position_risks:
            del self._position_risks[stock_code]
            self._logger.info(f"RiskManager 포지션 리스크 제거 (외부 청산): {stock_code}")
            return True
        return False

    # =========================================
    # Grand Trend V6: ATR 트레일링 스탑
    # =========================================

    def check_atr_trailing_exit(
        self,
        stock_code: str,
        current_price: int,
    ) -> Tuple[bool, Optional[ExitReason], str]:
        """
        Grand Trend V6: ATR 트레일링 스탑 체크

        분할 익절 후 trailing_stop_price 하향 돌파 시 전량 청산
        조건: is_partial_exit=True 상태에서만 동작

        Pine Script 로직:
        - trailStop := max(ts_line, trailStop[1])
        - if crossunder(close, trailStop) → 전량 청산

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            (청산 필요 여부, 청산 사유, 상세 메시지)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return (False, None, "")

        # 분할 익절 전에는 트레일링 스탑 비활성
        if not position_risk.is_partial_exit:
            return (False, None, "")

        # 트레일링 스탑 미설정 (초기화 안됨)
        if position_risk.trailing_stop_price <= 0:
            return (False, None, "")

        # 트레일링 스탑 하향 돌파 시 청산
        if current_price < position_risk.trailing_stop_price:
            profit_rate = position_risk.get_profit_rate(current_price)
            return (
                True,
                ExitReason.TRAILING_STOP,
                f"ATR 트레일링 스탑 (현재가 {current_price:,} < 스탑 {position_risk.trailing_stop_price:,}, 수익률 {profit_rate:+.1f}%)"
            )

        return (False, None, "")

    def get_trailing_stop_price(self, stock_code: str) -> int:
        """트레일링 스탑 가격 조회"""
        position_risk = self._position_risks.get(stock_code)
        return position_risk.trailing_stop_price if position_risk else 0

    def set_trailing_stop_price(self, stock_code: str, stop_price: int) -> bool:
        """
        트레일링 스탑 가격 설정 (상승만)

        Args:
            stock_code: 종목 코드
            stop_price: 새 트레일링 스탑 가격

        Returns:
            갱신 여부
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False
        return position_risk.update_trailing_stop(stop_price)

    def set_ts_fallback(self, stock_code: str, is_fallback: bool = True) -> None:
        """
        V6.2-A 코드리뷰 C2: TS fallback 상태 설정

        TS 초기화 실패 시 fallback(-4%) 사용 중임을 표시합니다.
        이후 정상적인 TS 업데이트 성공 시 자동으로 해제됩니다.

        Args:
            stock_code: 종목 코드
            is_fallback: fallback 상태 (True: 사용 중, False: 해제)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk:
            position_risk.is_ts_fallback = is_fallback
            self._logger.debug(
                f"[C2] TS fallback 상태: {stock_code} = {is_fallback}"
            )

    def is_partial_exited(self, stock_code: str) -> bool:
        """분할 익절 완료 여부 조회"""
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False
        return position_risk.is_partial_exit

    def update_highest_price(self, stock_code: str, current_price: int) -> bool:
        """
        분할 익절 후 최고가 갱신

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            갱신 여부
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk and position_risk.is_partial_exit:
            if current_price > position_risk.highest_price:
                position_risk.highest_price = current_price
                return True
        return False

    def get_highest_price(self, stock_code: str) -> int:
        """최고가 조회"""
        position_risk = self._position_risks.get(stock_code)
        if position_risk:
            return position_risk.highest_price
        return 0

    # =========================================
    # Grand Trend V6.2-A: 통합 청산 로직
    # =========================================

    def check_exit_v62a(
        self,
        stock_code: str,
        current_price: int,
        bar_low: Optional[int] = None,
        max_holding_days: int = 60,
        is_opening_protection: bool = False,
    ) -> Tuple[bool, Optional[ExitReason], str]:
        """
        V6.2-A 청산 조건 체크 (우선순위 순서)

        Pine Script 로직 준수:
        1. 고정 손절: bar_low <= entry_price × 0.96 (-4%)
        2. TS 이탈: current_price <= trailing_stop_price
           - 경고 시: ExitReason.TRAILING_STOP_TIGHT
           - 정상 시: ExitReason.TRAILING_STOP
        3. 최대 보유일: holding_days > max_holding_days (60일)

        V6.2-E 추가: NXT 시장조작 방어
        - is_opening_protection=True: bar_low 기반 손절 비활성화, current_price 기반만 적용
        - 극단값 필터: 진입가 대비 -15% 이상 급락한 bar_low 무시

        Args:
            stock_code: 종목 코드
            current_price: 현재 종가
            bar_low: 현재 봉 저가 (고정 손절 체크용, 없으면 current_price 사용)
            max_holding_days: 최대 보유일 (기본 60일)
            is_opening_protection: V6.2-E 장 초반 보호 기간 여부

        Returns:
            (청산 필요 여부, 청산 사유, 상세 메시지)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return (False, None, "포지션 없음")

        # bar_low가 없으면 current_price 사용
        if bar_low is None:
            bar_low = current_price

        # 최고가 갱신 (기록용)
        position_risk.update_highest(current_price)

        # 수익률 계산
        profit_rate = position_risk.get_profit_rate(current_price)

        # ----------------------------------------
        # V6.2-E: 극단값 필터 (bar_low 신뢰도 검증)
        # ----------------------------------------
        extreme_threshold = self._config.extreme_drop_threshold  # -0.15
        bar_low_drop_rate = (bar_low - position_risk.entry_price) / position_risk.entry_price
        is_extreme_bar_low = bar_low_drop_rate < extreme_threshold

        if is_extreme_bar_low:
            self._logger.warning(
                f"[극단값 필터] {stock_code}: bar_low {bar_low:,}원 의심 "
                f"(진입가 {position_risk.entry_price:,}원 대비 {bar_low_drop_rate*100:.1f}%)"
            )

        # ----------------------------------------
        # 1. 고정 손절 (-4%): bar_low <= entry × 0.96
        #    V6.2-E: 장 초반 보호 또는 극단값이면 bar_low 손절 스킵
        # ----------------------------------------
        sl_price = int(position_risk.entry_price * (1 + self._config.safety_stop_rate / 100))

        # Case A: 정상 상태 - bar_low 기반 손절 적용
        if not is_opening_protection and not is_extreme_bar_low:
            if bar_low <= sl_price:
                return (
                    True,
                    ExitReason.HARD_STOP,
                    f"고정손절({self._config.safety_stop_rate}%): 저가 {bar_low:,} ≤ 손절가 {sl_price:,}"
                )
        # Case B: 보호 상태 - current_price 기반 손절만 적용 (Safety Net)
        else:
            if current_price <= sl_price:
                reason_detail = "장초반보호" if is_opening_protection else "극단값필터"
                return (
                    True,
                    ExitReason.HARD_STOP,
                    f"고정손절({self._config.safety_stop_rate}%, {reason_detail}): 현재가 {current_price:,} ≤ 손절가 {sl_price:,}"
                )

        # ----------------------------------------
        # 2. TS 이탈: current_price <= trailing_stop
        # ----------------------------------------
        if position_risk.trailing_stop_price > 0:
            if current_price <= position_risk.trailing_stop_price:
                # 구조 경고 상태에 따라 청산 사유 분기
                if position_risk.structure_warning and position_risk.structure_warning.is_warning:
                    warning_type = position_risk.structure_warning.warning_type
                    return (
                        True,
                        ExitReason.TRAILING_STOP_TIGHT,
                        f"TS Exit (Tight Policy - {warning_type}): 현재가 {current_price:,} ≤ TS {position_risk.trailing_stop_price:,}, 수익률 {profit_rate:+.1f}%"
                    )
                else:
                    return (
                        True,
                        ExitReason.TRAILING_STOP,
                        f"TS Exit: 현재가 {current_price:,} ≤ TS {position_risk.trailing_stop_price:,}, 수익률 {profit_rate:+.1f}%"
                    )

        # ----------------------------------------
        # 3. 최대 보유일 초과: holding_days > 60
        # ----------------------------------------
        holding_days = position_risk.get_holding_days()
        if holding_days > max_holding_days:
            return (
                True,
                ExitReason.MAX_HOLDING,
                f"최대보유일 초과: {holding_days}일 > {max_holding_days}일, 수익률 {profit_rate:+.1f}%"
            )

        # 청산 조건 없음 - 보유 유지
        ts_info = f", TS={position_risk.trailing_stop_price:,}" if position_risk.trailing_stop_price > 0 else ""
        return (False, None, f"보유 중 (수익률: {profit_rate:+.1f}%{ts_info})")

    def init_structure_warning(self, stock_code: str) -> bool:
        """
        V6.2-A: 구조 경고 상태 초기화

        Args:
            stock_code: 종목 코드

        Returns:
            초기화 성공 여부
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False
        position_risk.init_structure_warning()
        return True

    def update_structure_warning(
        self,
        stock_code: str,
        close: float,
        ema9: float,
        hlc3: float,
        confirm_bars: int = 2,
        use_vwap_warn: bool = True,
        use_hl_break: bool = False,
    ) -> bool:
        """
        V6.2-A: 구조 경고 상태 업데이트 (3분봉 완성 시 호출)

        Args:
            stock_code: 종목 코드
            close: 현재 종가
            ema9: EMA(9) 값
            hlc3: (High + Low + Close) / 3 - VWAP 근사값
            confirm_bars: 연속 확인 봉 수 (기본 2)
            use_vwap_warn: VWAP 경고 사용 여부
            use_hl_break: 피봇 로우 이탈 사용 여부

        Returns:
            경고 상태 (True: 경고 발생)
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False

        # 구조 경고 객체가 없으면 초기화
        if position_risk.structure_warning is None:
            position_risk.init_structure_warning()

        # 경고 상태 업데이트
        is_warning = position_risk.structure_warning.update(
            close=close,
            ema9=ema9,
            hlc3=hlc3,
            confirm_bars=confirm_bars,
            use_vwap_warn=use_vwap_warn,
            use_hl_break=use_hl_break,
        )

        if is_warning:
            self._logger.info(
                f"[StructureWarning] {stock_code}: {position_risk.structure_warning.warning_type} 경고 발생 "
                f"(EMA9 {position_risk.structure_warning.ema9_below_count}봉, "
                f"VWAP {position_risk.structure_warning.vwap_below_count}봉)"
            )

        return is_warning

    def get_structure_warning(self, stock_code: str) -> Optional[StructureWarning]:
        """V6.2-A: 구조 경고 상태 조회"""
        position_risk = self._position_risks.get(stock_code)
        if position_risk:
            return position_risk.structure_warning
        return None

    def set_entry_date(self, stock_code: str, entry_date: date) -> bool:
        """
        V6.2-A: 진입 날짜 설정

        Args:
            stock_code: 종목 코드
            entry_date: 진입 날짜

        Returns:
            설정 성공 여부
        """
        position_risk = self._position_risks.get(stock_code)
        if position_risk is None:
            return False
        position_risk.entry_date = entry_date
        return True

    def get_holding_days(self, stock_code: str) -> int:
        """V6.2-A: 보유일 조회"""
        position_risk = self._position_risks.get(stock_code)
        if position_risk:
            return position_risk.get_holding_days()
        return 0
