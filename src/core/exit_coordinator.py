"""
청산 조율기 (Phase 3 리팩토링)

TradingEngine의 청산 조율 로직을 분리하여 단일 책임 원칙을 준수합니다.

주요 기능:
- V6/V7 청산 전략 라우팅
- V7 Exit State 관리
- 청산 조건 조율
- 청산 결과 집계

CLAUDE.md 불변 조건:
- 고정 손절 -4% 최우선 (Risk-First)
- 트레일링 스탑 상향 단방향
- ATR 배수 단방향 축소

Usage:
    from src.core.exit_coordinator import ExitCoordinator

    coordinator = ExitCoordinator(
        exit_manager=exit_manager,
        v7_exit_manager=wave_harvest_exit,
    )

    # 청산 체크
    await coordinator.check_exit(stock_code, current_price, bar_low)

    # V7 State 관리
    coordinator.initialize_v7_state(stock_code, entry_price, entry_date)
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, Callable, Awaitable, List
from enum import Enum
import asyncio

from src.core.risk_manager import ExitReason
from src.core.wave_harvest_exit import PositionExitState
from src.utils.logger import get_logger


class ExitSource(str, Enum):
    """청산 소스"""
    V6_EXIT_MANAGER = "V6_EXIT_MANAGER"
    V7_WAVE_HARVEST = "V7_WAVE_HARVEST"
    SAFETY_NET = "SAFETY_NET"
    MANUAL = "MANUAL"


@dataclass
class ExitCheckResult:
    """청산 체크 결과"""
    should_exit: bool = False
    reason: Optional[ExitReason] = None
    source: Optional[ExitSource] = None
    message: str = ""
    profit_rate: float = 0.0
    r_multiple: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.should_exit:
            return (
                f"EXIT: {self.reason.value if self.reason else 'UNKNOWN'} "
                f"({self.source.value if self.source else 'UNKNOWN'}) "
                f"profit={self.profit_rate:+.2f}%"
            )
        return "HOLD"


@dataclass
class ExitCoordinatorCallbacks:
    """
    청산 조율기 콜백 인터페이스

    ExitCoordinator가 TradingEngine에 의존하지 않도록
    필요한 기능을 콜백으로 전달받습니다.
    """
    has_position: Optional[Callable[[str], bool]] = None
    get_position_risk: Optional[Callable[[str], Any]] = None
    get_candle_data: Optional[Callable[[str], Any]] = None
    execute_sell: Optional[Callable[[str, ExitReason, str], Awaitable[None]]] = None
    get_market_state: Optional[Callable[[], Any]] = None
    is_ignore_stock: Optional[Callable[[str], bool]] = None


class ExitCoordinator:
    """
    청산 조율기

    V6/V7 청산 전략을 통합 조율하고 청산 결정을 관리합니다.
    TradingEngine에서 청산 관련 로직을 분리합니다.

    Features:
    - V6/V7 청산 전략 자동 라우팅
    - V7 Exit State 생명주기 관리
    - /ignore 종목 Safety Net 처리
    - 청산 통계 집계

    CLAUDE.md 불변 조건:
    - 고정 손절 -4%는 항상 최우선
    - 트레일링 스탑은 상향만 허용
    - ATR 배수는 축소만 허용

    Example:
        coordinator = ExitCoordinator(
            exit_manager=exit_mgr,
            v7_exit_manager=wave_harvest,
        )

        result = await coordinator.check_exit("005930", 50000, 49800, callbacks)
        if result.should_exit:
            await callbacks.execute_sell(stock_code, result.reason, result.message)
    """

    def __init__(
        self,
        exit_manager=None,
        v7_exit_manager=None,
        risk_settings=None,
        position_strategies: Optional[Dict[str, str]] = None,
    ):
        """
        Args:
            exit_manager: V6 ExitManager 인스턴스
            v7_exit_manager: V7 WaveHarvestExit 인스턴스
            risk_settings: RiskSettings 인스턴스
            position_strategies: 공유 포지션-전략 매핑 (M-09: 단일 소스)
        """
        self._logger = get_logger(__name__)
        self._exit_manager = exit_manager
        self._v7_exit_manager = v7_exit_manager
        self._risk_settings = risk_settings

        # V7 Exit States
        self._v7_exit_states: Dict[str, PositionExitState] = {}

        # Phase 3-3: 포지션-전략 매핑 (전략 무관 라우팅)
        # M-09: 외부에서 공유 dict 주입 가능 (StrategyOrchestrator와 동일 객체)
        self._position_strategies: Dict[str, str] = position_strategies if position_strategies is not None else {}

        # [V7.1] 청산 실패 Circuit Breaker
        # 매도 실패한 종목은 일정 시간 동안 청산 시도 중단
        self._blocked_exits: Dict[str, datetime] = {}
        self._block_duration_minutes: int = 5  # 5분간 재시도 방지 (10분→5분 단축)

        # 통계
        self._stats = {
            "total_exits": 0,
            "hard_stop_exits": 0,
            "trailing_stop_exits": 0,
            "max_holding_exits": 0,
            "safety_net_exits": 0,
            "v6_exits": 0,
            "v7_exits": 0,
        }

    # =========================================
    # 청산 체크
    # =========================================

    async def check_exit(
        self,
        stock_code: str,
        current_price: int,
        callbacks: ExitCoordinatorCallbacks,
        bar_low: Optional[int] = None,
    ) -> ExitCheckResult:
        """
        청산 조건 체크

        V6/V7 전략을 자동으로 라우팅하고 청산 조건을 검사합니다.
        /ignore 종목은 Safety Net만 작동합니다.

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            callbacks: 콜백 인터페이스
            bar_low: 3분봉 저가 (손절 체크용)

        Returns:
            청산 체크 결과
        """
        # [Risk-First] Hard Stop (-4%)은 CB 상태와 무관하게 항상 최우선 확인
        check_price = bar_low if bar_low is not None else current_price
        hard_stop_entry_price = None

        # V7 포지션에서 진입가 조회
        v7_state = self._v7_exit_states.get(stock_code)
        if v7_state:
            hard_stop_entry_price = v7_state.entry_price
        elif callbacks.get_position_risk:
            # V6 또는 기타 전략
            _pr = callbacks.get_position_risk(stock_code)
            if _pr:
                hard_stop_entry_price = _pr.entry_price

        if hard_stop_entry_price and hard_stop_entry_price > 0:
            sl_price = int(hard_stop_entry_price * 0.96)  # -4%
            if check_price <= sl_price:
                is_cb_blocked = stock_code in self._blocked_exits
                profit_rate = ((check_price - hard_stop_entry_price) / hard_stop_entry_price) * 100
                source = ExitSource.V7_WAVE_HARVEST if v7_state else ExitSource.V6_EXIT_MANAGER
                self._logger.warning(
                    f"[ExitCoordinator] Hard Stop (-4%) 발동{' (CB 우회)' if is_cb_blocked else ''}: "
                    f"{stock_code} | entry={hard_stop_entry_price:,} | "
                    f"check_price={check_price:,} <= sl={sl_price:,}"
                )
                self._stats["hard_stop_exits"] += 1
                if v7_state:
                    self._stats["v7_exits"] += 1
                self._stats["total_exits"] += 1

                return ExitCheckResult(
                    should_exit=True,
                    reason=ExitReason.HARD_STOP,
                    source=source,
                    message=f"Hard Stop (-4%): {check_price:,} <= {sl_price:,}",
                    profit_rate=profit_rate,
                    r_multiple=-1.0,
                    metadata={"entry_price": hard_stop_entry_price, "cb_bypass": is_cb_blocked},
                )

        # [V7.1] Circuit Breaker: 블록된 종목은 청산 체크 스킵 (Hard Stop 제외)
        if stock_code in self._blocked_exits:
            blocked_at = self._blocked_exits[stock_code]
            elapsed = (datetime.now() - blocked_at).total_seconds() / 60
            if elapsed < self._block_duration_minutes:
                # 블록 기간 내 - 청산 체크 스킵 (Hard Stop은 위에서 이미 확인됨)
                return ExitCheckResult()
            else:
                # 블록 기간 만료 - 자동 해제
                self._unblock_exit(stock_code)
                self._logger.info(
                    f"[ExitCoordinator] 청산 블록 자동 해제 (5분 경과): {stock_code}"
                )

        # /ignore 종목 처리 - Safety Net만 작동
        if callbacks.is_ignore_stock and callbacks.is_ignore_stock(stock_code):
            return await self._check_safety_net(
                stock_code, current_price, callbacks, bar_low
            )

        # 포지션-전략 매핑 기반 라우팅
        strategy_name = self._position_strategies.get(stock_code)
        if strategy_name:
            if strategy_name == "V7_PURPLE_REABS" and stock_code in self._v7_exit_states:
                return await self._check_exit_v7(
                    stock_code, current_price, callbacks, bar_low
                )
            else:
                # V6 또는 기타 전략
                return await self._check_exit_v6(
                    stock_code, current_price, callbacks, bar_low
                )

        # V6 청산 로직 (매핑 없는 포지션의 기본 경로)
        return await self._check_exit_v6(
            stock_code, current_price, callbacks, bar_low
        )

    async def _check_safety_net(
        self,
        stock_code: str,
        current_price: int,
        callbacks: ExitCoordinatorCallbacks,
        bar_low: Optional[int] = None,
    ) -> ExitCheckResult:
        """
        Safety Net 체크 (/ignore 종목용)

        /ignore 종목은 ATR TS, 최대 보유일을 무시하고
        고정 손절(-4%)만 작동합니다.

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            callbacks: 콜백 인터페이스
            bar_low: 3분봉 저가

        Returns:
            청산 체크 결과
        """
        if not callbacks.get_position_risk:
            return ExitCheckResult()

        position_risk = callbacks.get_position_risk(stock_code)
        if not position_risk:
            return ExitCheckResult()

        # -4% 고정 손절 체크
        check_price = bar_low if bar_low is not None else current_price
        sl_price = int(position_risk.entry_price * 0.96)  # -4%

        if check_price <= sl_price:
            self._logger.warning(
                f"[ExitCoordinator] Safety Net 손절: {stock_code} - "
                f"/ignore 중이지만 -4% 발동 | "
                f"entry={position_risk.entry_price:,} | "
                f"check_price={check_price:,} | "
                f"sl_price={sl_price:,}"
            )
            self._stats["safety_net_exits"] += 1
            self._stats["hard_stop_exits"] += 1
            self._stats["total_exits"] += 1

            return ExitCheckResult(
                should_exit=True,
                reason=ExitReason.HARD_STOP,
                source=ExitSource.SAFETY_NET,
                message=f"Safety Net 손절 (/ignore 중) - check_price={check_price:,} < sl={sl_price:,}",
                profit_rate=-4.0,
                metadata={"entry_price": position_risk.entry_price, "sl_price": sl_price},
            )

        return ExitCheckResult()

    async def _check_exit_v6(
        self,
        stock_code: str,
        current_price: int,
        callbacks: ExitCoordinatorCallbacks,
        bar_low: Optional[int] = None,
    ) -> ExitCheckResult:
        """
        V6 청산 체크

        ExitManager로 위임합니다.

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            callbacks: 콜백 인터페이스
            bar_low: 3분봉 저가

        Returns:
            청산 체크 결과
        """
        if not self._exit_manager:
            self._logger.warning(
                f"[ExitCoordinator] ExitManager 미초기화 - 청산 체크 스킵: {stock_code}"
            )
            return ExitCheckResult()

        # ExitManager로 위임 (기존 로직 유지)
        await self._exit_manager.check_position_exit(stock_code, current_price, bar_low)

        # ExitManager는 직접 청산 실행하므로 결과 반환 없음
        return ExitCheckResult()

    async def _check_exit_v7(
        self,
        stock_code: str,
        current_price: int,
        callbacks: ExitCoordinatorCallbacks,
        bar_low: Optional[int] = None,
    ) -> ExitCheckResult:
        """
        V7 Wave Harvest 청산 체크

        청산 우선순위:
        1. Hard Stop (-4%): bar_low 또는 current_price
        2. Max Holding (60일)
        3. ATR TS 이탈 + Trend Hold Filter

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            callbacks: 콜백 인터페이스
            bar_low: 3분봉 저가

        Returns:
            청산 체크 결과
        """
        # 1. V7 State 확인
        state = self._v7_exit_states.get(stock_code)
        if not state:
            self._logger.warning(f"[ExitCoordinator] V7 Exit State 없음: {stock_code}")
            return ExitCheckResult()

        # 2. 포지션 확인
        if callbacks.has_position and not callbacks.has_position(stock_code):
            self._logger.debug(
                f"[ExitCoordinator] 포지션 없음, 청산 체크 스킵: {stock_code}"
            )
            return ExitCheckResult()

        # 3. Hard Stop (-4%) 확인 - 최우선 (Risk-First)
        # [C-001] NXT/KRX_CLOSING 시간대와 관계없이 항상 먼저 체크
        check_price = bar_low if bar_low is not None else current_price
        if self._v7_exit_manager and self._v7_exit_manager.check_hard_stop(
            state.entry_price, check_price
        ):
            profit_rate = ((check_price - state.entry_price) / state.entry_price) * 100
            self._logger.warning(
                f"[ExitCoordinator] V7 Hard Stop 청산: {stock_code} | "
                f"entry={state.entry_price:,} | check_price={check_price:,} | "
                f"stop={state.get_fallback_stop():,}"
            )
            self._stats["hard_stop_exits"] += 1
            self._stats["v7_exits"] += 1
            self._stats["total_exits"] += 1

            return ExitCheckResult(
                should_exit=True,
                reason=ExitReason.HARD_STOP,
                source=ExitSource.V7_WAVE_HARVEST,
                message=f"[V7] Hard Stop (-4%): {check_price:,} < {state.get_fallback_stop():,}",
                profit_rate=profit_rate,
                r_multiple=-1.0,
                metadata={"entry_price": state.entry_price},
            )

        # 4. NXT 시간대 가격 괴리 검증 (ATR TS에만 적용, Hard Stop은 이미 체크됨)
        # [C-001, C-005] Hard Stop은 시간대와 관계없이 먼저 체크 완료
        if callbacks.get_market_state:
            market_state = callbacks.get_market_state()
            # MarketState enum 비교
            if hasattr(market_state, 'value'):
                state_value = market_state.value
            else:
                state_value = str(market_state)

            is_nxt_time = state_value in ("NXT_PRE_MARKET", "NXT_AFTER")

            if is_nxt_time:
                price_gap_pct = abs(current_price - state.entry_price) / state.entry_price * 100
                if price_gap_pct > 5.0:
                    self._logger.warning(
                        f"[ExitCoordinator] NXT 가격 괴리 감지 - ATR TS 보류: {stock_code} | "
                        f"entry={state.entry_price:,} | current={current_price:,} | "
                        f"gap={price_gap_pct:.1f}% (Hard Stop은 정상 체크됨)"
                    )
                    return ExitCheckResult()

            # KRX 단일가 구간 ATR TS 보류 (Hard Stop은 정상 작동)
            if state_value == "KRX_CLOSING":
                self._logger.debug(
                    f"[ExitCoordinator] KRX 단일가 시간 - ATR TS 보류: {stock_code} (Hard Stop은 정상 체크됨)"
                )
                return ExitCheckResult()

        # 5. Max Holding (60일) 확인
        max_holding_days = 60
        if self._risk_settings and hasattr(self._risk_settings, 'max_holding_days'):
            max_holding_days = self._risk_settings.max_holding_days

        if self._v7_exit_manager and self._v7_exit_manager.check_max_holding_days(
            state.entry_date, max_holding_days
        ):
            holding_days = (datetime.now() - state.entry_date).days
            profit_rate = ((current_price - state.entry_price) / state.entry_price) * 100
            self._logger.warning(
                f"[ExitCoordinator] V7 Max Holding 청산: {stock_code} | "
                f"holding_days={holding_days} > {max_holding_days}"
            )
            self._stats["max_holding_exits"] += 1
            self._stats["v7_exits"] += 1
            self._stats["total_exits"] += 1

            return ExitCheckResult(
                should_exit=True,
                reason=ExitReason.MAX_HOLDING,
                source=ExitSource.V7_WAVE_HARVEST,
                message=f"[V7] Max Holding ({holding_days}일 > {max_holding_days}일)",
                profit_rate=profit_rate,
                metadata={"holding_days": holding_days},
            )

        # 7. 캔들 데이터 가져오기 (ATR TS 계산용)
        if not callbacks.get_candle_data:
            self._logger.debug(
                f"[ExitCoordinator] get_candle_data 콜백 없음, ATR TS 스킵: {stock_code}"
            )
            return ExitCheckResult()

        candles = callbacks.get_candle_data(stock_code)
        if candles is None or len(candles) < 20:
            candle_count = len(candles) if candles is not None else 0
            self._logger.info(
                f"[ExitCoordinator] 신규 상장 모드: {stock_code} | "
                f"캔들 {candle_count}개 | ATR TS 비활성화, Hard Stop (-4%) 보호 중"
            )
            return ExitCheckResult()

        # 8. Wave Harvest Exit 업데이트 및 청산 체크
        if not self._v7_exit_manager:
            return ExitCheckResult()

        should_exit, reason = self._v7_exit_manager.update_and_check(
            state=state,
            df=candles,
            current_price=current_price,
            bar_low=bar_low
        )

        # F-7: WaveHarvest 예외 감지 알림
        if reason and "EXCEPTION_" in reason:
            self._logger.critical(
                f"[ExitCoordinator] WaveHarvest 예외 감지: {stock_code} | "
                f"reason={reason} | should_exit={should_exit}"
            )

        # 9. 청산 조건 충족 시 결과 반환
        if should_exit:
            profit_rate = ((current_price - state.entry_price) / state.entry_price) * 100
            self._logger.info(
                f"[ExitCoordinator] V7 ATR TS 청산: {stock_code} | "
                f"reason={reason} | "
                f"R={state.r_multiple:.2f} | "
                f"profit={profit_rate:.2f}% | "
                f"mult={state.current_multiplier}x | "
                f"ts={state.trailing_stop:,}"
            )
            self._stats["trailing_stop_exits"] += 1
            self._stats["v7_exits"] += 1
            self._stats["total_exits"] += 1

            return ExitCheckResult(
                should_exit=True,
                reason=ExitReason.TRAILING_STOP,
                source=ExitSource.V7_WAVE_HARVEST,
                message=f"[V7] {reason} | R={state.r_multiple:.2f} | {profit_rate:.2f}%",
                profit_rate=profit_rate,
                r_multiple=state.r_multiple,
                metadata={
                    "entry_price": state.entry_price,
                    "trailing_stop": state.trailing_stop,
                    "current_multiplier": state.current_multiplier,
                    "exception_fallback": "EXCEPTION_FALLBACK" in reason,
                },
            )

        # 보유 유지
        self._logger.debug(
            f"[ExitCoordinator] V7 보유 유지: {stock_code} | "
            f"R={state.r_multiple:.2f} | "
            f"mult={state.current_multiplier}x | "
            f"ts={state.trailing_stop:,} | "
            f"price={current_price:,}"
        )
        return ExitCheckResult()

    # =========================================
    # V7 Exit State 관리
    # =========================================

    def initialize_v7_state(
        self,
        stock_code: str,
        entry_price: int,
        entry_date: Optional[datetime] = None,
    ) -> Optional[PositionExitState]:
        """
        V7 Exit State 초기화

        Args:
            stock_code: 종목 코드
            entry_price: 진입가
            entry_date: 진입일 (기본: 현재)

        Returns:
            생성된 Exit State 또는 None
        """
        # position_strategies에 V7으로 등록되어 있어야 초기화 허용
        strategy_for_stock = self._position_strategies.get(stock_code)
        if strategy_for_stock != "V7_PURPLE_REABS" or not self._v7_exit_manager:
            return None

        if stock_code in self._v7_exit_states:
            self._logger.debug(f"[ExitCoordinator] V7 Exit State 이미 존재: {stock_code}")
            return self._v7_exit_states[stock_code]

        exit_state = self._v7_exit_manager.create_state(
            stock_code=stock_code,
            entry_price=entry_price,
            entry_date=entry_date or datetime.now(),
        )
        self._v7_exit_states[stock_code] = exit_state

        self._logger.info(
            f"[ExitCoordinator] V7 Exit State 생성: {stock_code} | "
            f"entry={entry_price:,} | "
            f"fallback_stop={exit_state.get_fallback_stop():,} (-4%)"
        )
        return exit_state

    def get_v7_state(self, stock_code: str) -> Optional[PositionExitState]:
        """V7 Exit State 조회"""
        return self._v7_exit_states.get(stock_code)

    def has_v7_state(self, stock_code: str) -> bool:
        """V7 Exit State 존재 여부"""
        return stock_code in self._v7_exit_states

    def check_emergency_hard_stop(self, stock_code: str, current_price: int) -> bool:
        """
        [Critical] V7 State 기반 긴급 손절 체크 (PositionManager 독립)

        PositionManager에 포지션이 없더라도 V7 Exit State가 존재하면
        -4% 손절 조건을 체크합니다. HTS 매수 후 API 동기화 지연 시 발생하는
        청산 누락 문제를 방지합니다.

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            True if -4% 이하로 손절 조건 충족
        """
        state = self._v7_exit_states.get(stock_code)
        if not state:
            return False

        stop_price = state.get_fallback_stop()  # -4%
        if current_price <= stop_price:
            self._logger.warning(
                f"[ExitCoordinator] 긴급 Hard Stop 발동: {stock_code} | "
                f"entry={state.entry_price:,} | current={current_price:,} | "
                f"stop={stop_price:,} (-4%)"
            )
            return True

        return False

    def cleanup_v7_state(self, stock_code: str) -> None:
        """
        V7 Exit State 정리

        포지션 청산 완료 후 호출합니다.

        Args:
            stock_code: 종목 코드
        """
        # position_strategies 매핑 해제
        self._position_strategies.pop(stock_code, None)

        if stock_code in self._v7_exit_states:
            state = self._v7_exit_states.pop(stock_code)
            self._logger.info(
                f"[ExitCoordinator] V7 Exit State 정리: {stock_code} | "
                f"final_R={state.r_multiple:.2f} | "
                f"final_mult={state.current_multiplier}x"
            )

    def get_all_v7_states(self) -> Dict[str, PositionExitState]:
        """모든 V7 Exit State 조회"""
        return self._v7_exit_states.copy()

    def clear_all_v7_states(self) -> int:
        """모든 V7 Exit State 정리 (엔진 종료 시)"""
        count = len(self._v7_exit_states)
        self._v7_exit_states.clear()
        self._position_strategies.clear()
        return count

    # =========================================
    # Phase 3-3: 포지션-전략 매핑
    # =========================================

    def register_position_strategy(self, stock_code: str, strategy_name: str) -> None:
        """
        포지션-전략 매핑 등록

        포지션 진입 시 호출하여 청산 라우팅에 사용합니다.

        Args:
            stock_code: 종목 코드
            strategy_name: 전략 이름 (예: "V7_PURPLE_REABS", "V6_SNIPER_TRAP")
        """
        self._position_strategies[stock_code] = strategy_name
        self._logger.debug(
            f"[ExitCoordinator] 포지션-전략 매핑: {stock_code} → {strategy_name}"
        )

    def unregister_position_strategy(self, stock_code: str) -> None:
        """포지션-전략 매핑 해제"""
        self._position_strategies.pop(stock_code, None)

    def get_position_strategy(self, stock_code: str) -> Optional[str]:
        """포지션의 전략 이름 조회"""
        return self._position_strategies.get(stock_code)

    def get_all_position_strategies(self) -> Dict[str, str]:
        """모든 포지션-전략 매핑 조회"""
        return self._position_strategies.copy()

    # =========================================
    # 유틸리티
    # =========================================

    def get_stats(self) -> Dict[str, int]:
        """통계 반환"""
        return self._stats.copy()

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        return {
            "v7_states_count": len(self._v7_exit_states),
            "v7_states": list(self._v7_exit_states.keys()),
            "position_strategies": dict(self._position_strategies),
            "stats": self._stats.copy(),
            "has_exit_manager": self._exit_manager is not None,
            "has_v7_exit_manager": self._v7_exit_manager is not None,
            "blocked_exits": list(self._blocked_exits.keys()),
        }

    # =========================================
    # [V7.1] Circuit Breaker - 청산 실패 방지
    # =========================================

    def block_exit(self, stock_code: str) -> None:
        """
        청산 실패 시 해당 종목의 청산 시도를 일시 중단

        Args:
            stock_code: 종목 코드
        """
        self._blocked_exits[stock_code] = datetime.now()
        self._logger.warning(
            f"[ExitCoordinator] 청산 블록 설정: {stock_code} | "
            f"재시도까지 {self._block_duration_minutes}분 대기"
        )

    def _unblock_exit(self, stock_code: str) -> None:
        """내부 블록 해제"""
        self._blocked_exits.pop(stock_code, None)

    def unblock_exit(self, stock_code: str) -> None:
        """
        청산 블록 수동 해제

        Args:
            stock_code: 종목 코드
        """
        if stock_code in self._blocked_exits:
            self._blocked_exits.pop(stock_code)
            self._logger.info(f"[ExitCoordinator] 청산 블록 수동 해제: {stock_code}")

    def unblock_all_exits(self) -> None:
        """모든 청산 블록 해제"""
        count = len(self._blocked_exits)
        self._blocked_exits.clear()
        self._logger.info(f"[ExitCoordinator] 모든 청산 블록 해제: {count}개")

    def is_exit_blocked(self, stock_code: str) -> bool:
        """청산 블록 여부 확인"""
        return stock_code in self._blocked_exits

    def __str__(self) -> str:
        return (
            f"ExitCoordinator("
            f"states={len(self._v7_exit_states)}, "
            f"exits={self._stats['total_exits']})"
        )
