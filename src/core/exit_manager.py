"""
청산 매니저 모듈 (ExitManager)

Grand Trend V6.2-A 청산 로직 전문 모듈
- 3단계 청산 우선순위 통합 관리
- TradingEngine에서 분리하여 단일 책임 원칙 준수

청산 우선순위 (Grand Trend V6.2-A):
1. 고정 손절 (-4%): bar_low <= entry × 0.96
2. TS 이탈: current_price <= trailing_stop_price
   - 기본 ATR 배수: 6.0
   - 구조 경고 시: 4.5 (Tight Policy)
3. 최대 보유일: 60일 초과

분할 익절 비활성화 (USE_PARTIAL_EXIT=false):
- 진입 즉시 트레일링 스탑 활성화
- 구조 경고(EMA9/VWAP 2봉 연속 하회) 시 TS 타이트닝
"""

from dataclasses import dataclass
from datetime import datetime, time, date
from typing import Dict, Optional, Callable, Tuple, Awaitable
import asyncio

from src.core.candle_builder import CandleManager, Candle, Timeframe
from src.core.indicator import Indicator
from src.core.risk_manager import RiskManager, ExitReason, PROFIT_RATE_EPSILON
from src.core.position_manager import PositionManager, Position
from src.api.endpoints.order import OrderAPI, OrderType, Exchange
from src.api.endpoints.account import AccountAPI
from src.api.endpoints.market import MarketAPI
from src.notification.telegram import TelegramBot
from src.database.repository import TradeRepository, OrderRepository
from src.database.models import OrderSide, OrderStatus
from src.core.exit.base_exit import BaseExit, ExitDecision as BaseExitDecision, ExitReason as BaseExitReason
from src.utils.config import get_risk_settings
from src.utils.logger import generate_correlation_id, bind_context, unbind_context


# 트레이딩 상수
class ExitConstants:
    """청산 관련 상수"""
    EXECUTION_WAIT_SECONDS: float = 5.0      # 체결 대기 최대 시간 (초)
    EXECUTION_POLL_INTERVAL: float = 0.5     # 체결 확인 폴링 간격 (초)


class ExitManager(BaseExit):
    """
    청산 로직 전문 모듈 (Grand Trend V6.2-A)

    BaseExit ABC를 상속하여 전략 플러그인 아키텍처와 호환됩니다.

    3단계 청산 우선순위를 통합 관리하며,
    TradingEngine의 책임을 분산하여 유지보수성을 향상시킵니다.

    V6.2-A 변경사항:
    - 분할 익절 제거 (USE_PARTIAL_EXIT=false)
    - 진입 즉시 TS 활성화
    - 구조 경고 기반 TS 타이트닝 (6.0 → 4.5)
    - 최대 보유일 60일
    """

    def __init__(
        self,
        risk_manager: RiskManager,
        position_manager: PositionManager,
        candle_manager: CandleManager,
        order_api: OrderAPI,
        account_api: AccountAPI,
        market_api: MarketAPI,
        trade_repo: Optional[TradeRepository],
        order_repo: Optional[OrderRepository],
        telegram: Optional[TelegramBot],
        logger,
        # 콜백 함수들 (TradingEngine에서 주입)
        # C-009 FIX: async 콜백으로 변경 (VI Lock이 asyncio.Lock으로 변경됨)
        is_vi_active_fn: Callable[[str], Awaitable[bool]],
        is_regular_trading_hours_fn: Callable[[], bool],
        is_market_open_fn: Callable[[], bool],
        # P0: 공유 Lock (Race Condition 방지)
        order_locks: Optional[Dict[str, asyncio.Lock]] = None,
        # P0: 공유 pending_sell_orders (중복 주문 방지)
        pending_sell_orders: Optional[Dict[str, str]] = None,
        # P0: 공유 pending_sell_lock (동시 접근 보호)
        pending_sell_lock: Optional[asyncio.Lock] = None,
    ):
        """
        ExitManager 초기화

        Args:
            risk_manager: 리스크 관리자
            position_manager: 포지션 관리자
            candle_manager: 캔들 관리자
            order_api: 주문 API
            account_api: 계좌 API
            market_api: 시세 API
            trade_repo: 거래 저장소
            order_repo: 주문 저장소
            telegram: 텔레그램 봇
            logger: 로거
            is_vi_active_fn: VI 활성 여부 콜백 (C-009: async)
            is_regular_trading_hours_fn: 장중 시간 여부 콜백
            is_market_open_fn: 장 운영 여부 콜백
            order_locks: 공유 Lock 딕셔너리 (Race Condition 방지)
            pending_sell_orders: 공유 미체결 매도 주문 딕셔너리 (중복 주문 방지)
            pending_sell_lock: 공유 pending_sell_orders Lock (동시 접근 보호)
        """
        self._risk_manager = risk_manager
        self._position_manager = position_manager
        self._candle_manager = candle_manager
        self._order_api = order_api
        self._account_api = account_api
        self._market_api = market_api
        self._trade_repo = trade_repo
        self._order_repo = order_repo
        self._telegram = telegram
        self._logger = logger

        # 콜백 함수
        self._is_vi_active = is_vi_active_fn
        self._is_regular_trading_hours = is_regular_trading_hours_fn
        self._is_market_open = is_market_open_fn

        # 설정
        self._risk_settings = get_risk_settings()

        # 상태 (P0: 공유 자원 사용 - Race Condition/중복 주문 방지)
        self._pending_sell_orders = pending_sell_orders if pending_sell_orders is not None else {}
        self._order_locks = order_locks if order_locks is not None else {}
        self._pending_sell_lock = pending_sell_lock if pending_sell_lock is not None else asyncio.Lock()

        # 통계 (외부에서 참조 가능)
        self.stats = {
            "trades_completed": 0,
        }

    # ===== BaseExit ABC 구현 =====

    @property
    def strategy_name(self) -> str:
        return "GRAND_TREND_V6"

    def check_exit(
        self,
        df,
        entry_price: int,
        current_price: int,
        **kwargs
    ) -> BaseExitDecision:
        """
        BaseExit ABC 구현: V6 Grand Trend 청산 결정

        실제 V6 청산은 check_position_exit() (async)에서 수행되므로,
        이 메서드는 순수 결정 로직만 제공합니다.
        """
        # 고정 손절 최우선 (BaseExit 헬퍼)
        hard_stop = self.check_hard_stop(entry_price, current_price)
        if hard_stop and hard_stop.should_exit:
            return hard_stop

        # 트레일링 스탑 확인
        trailing_stop = kwargs.get('trailing_stop', 0)
        if trailing_stop > 0 and current_price <= trailing_stop:
            profit_rate = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
            return BaseExitDecision(
                should_exit=True,
                reason=BaseExitReason.TRAILING_STOP,
                exit_price=current_price,
                stop_price=trailing_stop,
                profit_rate=profit_rate,
            )

        # 최대 보유일 확인
        entry_date = kwargs.get('entry_date')
        max_holding_days = kwargs.get('max_holding_days', 60)
        if entry_date:
            from datetime import datetime
            holding_days = (datetime.now() - entry_date).days
            if holding_days > max_holding_days:
                profit_rate = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
                return BaseExitDecision(
                    should_exit=True,
                    reason=BaseExitReason.MAX_HOLDING_DAYS,
                    exit_price=current_price,
                    profit_rate=profit_rate,
                    metadata={"holding_days": holding_days},
                )

        return BaseExitDecision(should_exit=False)

    def update_trailing_stop(
        self,
        df,
        current_stop: int,
        current_price: int,
        **kwargs
    ) -> tuple:
        """
        BaseExit ABC 구현: V6 트레일링 스탑 업데이트

        V6에서는 RiskManager가 TS를 관리하므로 기본 상향 강제만 적용합니다.
        """
        current_multiplier = kwargs.get('current_multiplier', 6.0)
        # 스탑 상향 단방향 강제 (BaseExit 헬퍼)
        new_stop = self.enforce_stop_direction(current_stop, current_stop)
        return new_stop, current_multiplier

    def _get_order_lock(self, stock_code: str) -> asyncio.Lock:
        """종목별 주문 Lock 획득"""
        if stock_code not in self._order_locks:
            self._order_locks[stock_code] = asyncio.Lock()
        return self._order_locks[stock_code]

    def _is_opening_protection_period(self) -> bool:
        """
        V6.2-L: 장 초반 보호 기간 여부 (bar_low 손절 비활성화)

        NXT 시장조작 방어: 동시호가/시가결정 가격이 bar_low에 포함되는 것을 방지.

        보호 구간:
        - 08:00~08:01: NXT 프리마켓 시작 (전일 KRX 종가로 시가 결정)
        - 09:00~09:01: KRX/NXT 정규장 시작
        - 15:30~15:31: NXT 애프터마켓 시작 (호가접수 → 체결 전환)

        이 기간 동안 bar_low 기반 손절 비활성화, current_price 기반 손절만 적용.
        """
        from datetime import datetime, time

        now = datetime.now().time()
        protection_minutes = self._risk_settings.exit_protection_minutes

        # V6.2-L: 보호 구간 정의
        protection_periods = [
            (time(8, 0, 0), time(8, protection_minutes, 0)),   # NXT 프리마켓 시작
            (time(9, 0, 0), time(9, protection_minutes, 0)),   # 정규장 시작
            (time(15, 30, 0), time(15, 30 + protection_minutes, 0)),  # NXT 애프터마켓 시작
        ]

        return any(start <= now < end for start, end in protection_periods)

    # =========================================
    # Grand Trend V6.2-A: 3단계 청산 로직
    # =========================================

    async def check_position_exit(
        self,
        stock_code: str,
        current_price: int,
        bar_low: Optional[int] = None,
    ) -> None:
        """
        Grand Trend V6.2-A: 포지션 청산 조건 체크

        ========== 청산 우선순위 (V6.2-A) ==========

        1. 고정 손절 (HARD_STOP)
           조건: bar_low <= entry_price × 0.96 (or current_price <= entry × 0.96)
           동작: 전량 청산

        2. TS 이탈 (TRAILING_STOP / TRAILING_STOP_TIGHT)
           조건: current_price <= trailing_stop_price
           배수: 기본 6.0, 구조 경고 시 4.5

        3. 최대 보유일 (MAX_HOLDING)
           조건: holding_days > 60

        ========== 분할 익절 (USE_PARTIAL_EXIT=true 시 작동) ==========
        - USE_PARTIAL_EXIT=false 기본값: 분할 익절 비활성화, 진입 즉시 TS 활성화
        - USE_PARTIAL_EXIT=true: 기존 V6 로직 (+10% → 50% 매도 후 TS 활성화)
        """
        # V7.0-Fix: NXT 시간대 + 가격 괴리 검증
        from src.core.market_schedule import get_market_schedule, MarketState

        schedule = get_market_schedule()
        market_state = schedule.get_state()

        # V7.0-Fix: NXT 중단 구간(15:20~15:30) 스킵
        if market_state == MarketState.KRX_CLOSING:
            return

        # V7.0-Fix: NXT 시간대 가격 괴리 검증
        is_nxt_time = market_state in (MarketState.NXT_PRE_MARKET, MarketState.NXT_AFTER)

        # V7.0-C1 FIX: 가격 괴리가 있어도 Hard Stop(-4%)은 항상 체크
        # 괴리 플래그만 설정하고, 아래에서 Safety Net 손절은 항상 체크
        skip_ts_exit = False
        if is_nxt_time:
            position = self._position_manager.get_position(stock_code)
            if position:
                price_gap_pct = abs(current_price - position.entry_price) / position.entry_price * 100
                if price_gap_pct > 5.0:
                    self._logger.warning(
                        f"[NXT] 가격 괴리 감지 - TS Exit 보류 (Hard Stop은 체크): {stock_code} | "
                        f"entry={position.entry_price:,} | current={current_price:,} | "
                        f"gap={price_gap_pct:.1f}%"
                    )
                    skip_ts_exit = True  # TS Exit만 보류, Hard Stop은 아래에서 체크

        # 장전 데이터(08:30~09:00)는 예상 체결가이므로 무시 (정규장 체크)
        # V7.0-Fix: NXT 시간대에서는 위에서 이미 검증됨
        if not is_nxt_time and not self._is_regular_trading_hours():
            return

        # V6.2-E: 장 초반 보호 기간 체크 (09:00~09:01)
        is_opening_protection = self._is_opening_protection_period()

        # 가격 업데이트
        self._position_manager.update_price(stock_code, current_price)

        # VI 활성 상태 로깅
        # C-009 FIX: await 추가 (is_vi_active가 async로 변경됨)
        vi_active = await self._is_vi_active(stock_code)
        if vi_active:
            self._logger.debug(f"VI 활성 중 - Grand Trend V6.2-A: 모든 청산 작동: {stock_code}")

        # ========== V6.2-A: USE_PARTIAL_EXIT=false 시 새 로직 ==========
        if not self._risk_settings.use_partial_exit:
            # V7.0-C1 FIX: 가격 괴리 시에도 Hard Stop은 체크 (check_exit_v62a 내부에서 처리)
            # V6.2-A 청산 로직 사용 (V6.2-E 파라미터 추가)
            should_exit, exit_reason, message = self._risk_manager.check_exit_v62a(
                stock_code=stock_code,
                current_price=current_price,
                bar_low=bar_low,
                max_holding_days=self._risk_settings.max_holding_days,
                is_opening_protection=is_opening_protection,
            )
            # V7.0-C1 FIX: skip_ts_exit 시 Hard Stop/Max Holding만 처리, TS Exit은 스킵
            if should_exit and exit_reason:
                if skip_ts_exit and exit_reason in (ExitReason.TRAILING_STOP, ExitReason.TRAILING_STOP_TIGHT):
                    self._logger.info(f"[NXT] 가격 괴리로 TS Exit 스킵: {stock_code}")
                else:
                    await self.execute_full_sell(stock_code, exit_reason, message)
            return

        # ========== 기존 V6 로직 (USE_PARTIAL_EXIT=true) ==========
        # V7.0-C3 FIX: 청산 우선순위 수정 (고정 손절 > ATR TS > 분할 익절)

        # ===== 1. 고정 손절: -4% (최우선) =====
        should_exit, exit_reason, message = self._risk_manager.check_exit(
            stock_code, current_price
        )
        if should_exit and exit_reason == ExitReason.HARD_STOP:
            await self.execute_full_sell(stock_code, exit_reason, message)
            return

        # ===== 2. ATR 트레일링 스탑 =====
        if not skip_ts_exit:  # V7.0-C1 FIX: 가격 괴리 시 TS Exit 스킵
            should_trailing, trailing_reason, trailing_msg = self._risk_manager.check_atr_trailing_exit(
                stock_code, current_price
            )
            if should_trailing and trailing_reason:
                await self.execute_full_sell(stock_code, trailing_reason, trailing_msg)
                return

        # ===== 3. 분할 익절: +10% → 50% 매도 =====
        partial_result = self._risk_manager.check_partial_exit(stock_code, current_price)
        if partial_result and partial_result.get("trigger"):
            partial_qty = partial_result.get("quantity", 0)
            profit_rate = partial_result.get("profit_rate", 0)
            partial_msg = f"분할 익절 (+{profit_rate:.1f}% → 50% 매도)"
            if partial_qty > 0:
                await self.execute_partial_sell(stock_code, current_price, partial_qty, partial_msg)

    # =========================================
    # 청산 실행
    # =========================================

    async def execute_partial_sell(
        self,
        stock_code: str,
        current_price: int,
        sell_quantity: int,
        message: str,
    ) -> None:
        """
        Grand Trend V6: 분할 매도 주문 실행

        +10% 도달 시 50% 물량 매도 후:
        1. 리스크 매니저 on_partial_exit() 호출 → ATR 트레일링 스탑 활성화
        2. 초기 trailing_stop_price = close - ATR(10) × 6.0 설정
        3. DB Trade 업데이트 (is_partial_exit=True)
        4. 포지션 수량 업데이트
        """
        lock = self._get_order_lock(stock_code)

        async with lock:
            position = self._position_manager.get_position(stock_code)
            if position is None:
                self._logger.debug(f"Lock 획득 후 포지션 없음 (분할 매도): {stock_code}")
                return

            try:
                self._logger.info(
                    f"분할 매도 주문 제출: {position.stock_name}({stock_code})",
                    message=message,
                    sell_quantity=sell_quantity,
                    remaining_quantity=position.quantity - sell_quantity,
                )

                # 1. 시장가 매도 주문 제출
                result = await self._order_api.sell(
                    stock_code=stock_code,
                    quantity=sell_quantity,
                    order_type=OrderType.MARKET,
                )

                if not result.success:
                    self._logger.error(f"분할 매도 주문 실패: {result.message}")
                    return

                # 2. 체결 확인
                execution = await self._account_api.wait_for_execution(
                    order_no=result.order_no,
                    stock_code=stock_code,
                    max_wait_seconds=ExitConstants.EXECUTION_WAIT_SECONDS,
                    poll_interval=ExitConstants.EXECUTION_POLL_INTERVAL,
                )

                if execution is None or execution.filled_qty == 0:
                    self._logger.warning(f"분할 매도 체결 실패/타임아웃: {result.order_no}")
                    return

                actual_exit_price = execution.filled_price
                filled_qty = execution.filled_qty

                self._logger.info(
                    f"분할 매도 체결 완료: {position.stock_name}({stock_code})",
                    order_no=result.order_no,
                    filled_price=actual_exit_price,
                    filled_qty=filled_qty,
                )

                # 3. 리스크 매니저 on_partial_exit() 호출
                entry_price = position.entry_price
                position_risk = self._risk_manager.get_position_risk(stock_code)
                original_quantity = position_risk.quantity if position_risk else position.quantity
                original_highest = position_risk.highest_price if position_risk else 0

                pnl = self._risk_manager.on_partial_exit(
                    stock_code,
                    filled_qty,
                    actual_exit_price,
                    entry_price  # 고정 손절 기준 (폴백)
                )

                # Grand Trend V6: ATR 트레일링 스탑 초기화
                initial_trailing_stop = await self._calculate_initial_trailing_stop(
                    stock_code, actual_exit_price
                )
                if initial_trailing_stop > 0:
                    self._risk_manager.set_trailing_stop_price(stock_code, initial_trailing_stop)
                    self._logger.info(
                        f"ATR 트레일링 스탑 활성화: {stock_code}",
                        trailing_stop=initial_trailing_stop,
                        current_price=actual_exit_price,
                    )

                # 4. DB 업데이트
                trade_id = position.signal_metadata.get("trade_id") if position.signal_metadata else None
                if self._trade_repo and trade_id:
                    try:
                        await self._trade_repo.update_partial_exit(
                            trade_id=trade_id,
                            highest_price=actual_exit_price,
                        )

                        if self._order_repo:
                            order = await self._order_repo.create(
                                stock_code=stock_code,
                                side=OrderSide.SELL,
                                order_type="MARKET",
                                quantity=filled_qty,
                                trade_id=trade_id,
                            )
                            await self._order_repo.update_status(
                                order_id=order.id,
                                status=OrderStatus.FILLED,
                                order_no=result.order_no,
                                filled_quantity=filled_qty,
                                filled_price=actual_exit_price,
                            )

                    except Exception as db_err:
                        self._logger.error(f"분할 매도 DB 기록 실패, 롤백 수행: {db_err}")
                        self._risk_manager.rollback_partial_exit(
                            stock_code,
                            original_quantity,
                            original_highest,
                            pnl,
                        )
                        return

                # 5. 포지션 수량 업데이트
                self._position_manager.update_quantity(
                    stock_code,
                    position.quantity - filled_qty,
                )

                self._position_manager.set_partial_exit_status(
                    stock_code,
                    is_partial_exit=True,
                    highest_price=actual_exit_price,
                )

                # 6. 텔레그램 알림 (Grand Trend V6: ATR 트레일링 스탑 정보 포함)
                if self._telegram:
                    profit_rate = ((actual_exit_price - position.entry_price) / position.entry_price) * 100
                    trailing_info = f"ATR 트레일링 스탑: {initial_trailing_stop:,}원" if initial_trailing_stop > 0 else "ATR 계산 실패"
                    await self._telegram.send_message(
                        f"[분할 익절 +10%]\n"
                        f"종목: {position.stock_name} ({stock_code})\n"
                        f"매도가: {actual_exit_price:,}원\n"
                        f"수량: {filled_qty}주 (잔량 {position.quantity - filled_qty}주)\n"
                        f"수익률: {profit_rate:+.2f}%\n"
                        f"{trailing_info}"
                    )

            except Exception as e:
                self._logger.error(f"분할 매도 주문 에러: {e}")

    async def execute_full_sell(
        self,
        stock_code: str,
        exit_reason: ExitReason,
        message: str,
    ) -> bool:
        """
        전량 매도 주문 실행

        1. 종목별 Lock으로 동시 매도 방지
        2. 체결 확인 후 포지션 청산
        3. 체결가 기반 손익 계산

        Returns:
            bool: 매도 성공 여부 (V7.1 Circuit Breaker 연동용)
        """
        lock = self._get_order_lock(stock_code)

        async with lock:
            position = self._position_manager.get_position(stock_code)
            if position is None:
                self._logger.debug(f"Lock 획득 후 포지션 없음: {stock_code}")
                return True  # 포지션 없음 = 성공으로 간주

            # V6.2-A D1: correlation_id 바인딩 (거래 추적용)
            trade_id = position.signal_metadata.get("trade_id") if position.signal_metadata else None
            correlation_id = generate_correlation_id(stock_code, trade_id)
            bind_context(correlation_id=correlation_id)

            try:
                # 미체결 매도 주문 확인
                pending_result = await self._check_pending_sell_order(stock_code, position)
                if pending_result is True:
                    return True  # 이미 체결됨 = 성공
                elif pending_result is False:
                    self._logger.info(f"미체결 주문 대기 중, 새 주문 스킵: {stock_code}")
                    return True  # 진행 중 = 재시도 불필요
                # V6.2-P: 거래소 자동 탐지 (NXT 프리마켓 매수 종목 대응)
                target_exchange = Exchange.KRX  # 기본값
                sell_quantity = position.quantity

                try:
                    # KRX와 NXT 각각 조회하여 종목이 어느 거래소에 있는지 확인
                    for ex in ["KRX", "NXT"]:
                        ex_positions = await self._account_api.get_positions(exchange=ex)
                        api_pos = next(
                            (p for p in ex_positions.positions if p.stock_code == stock_code),
                            None
                        )
                        if api_pos and api_pos.quantity > 0:
                            target_exchange = Exchange(ex)
                            sell_quantity = min(position.quantity, api_pos.quantity)
                            self._logger.info(
                                f"[V6.2-P] 거래소 탐지: {stock_code} → {ex} ({api_pos.quantity}주)"
                            )
                            break
                    else:
                        # 어느 거래소에서도 찾지 못함
                        self._logger.warning(
                            f"[V6.2-P] 거래소에서 종목 미발견: {stock_code}, 기본값 KRX로 시도"
                        )
                except Exception as e:
                    self._logger.warning(f"[V6.2-P] 거래소 탐지 실패: {e}, 기본값 KRX로 시도")

                self._logger.info(
                    f"매도 주문 제출: {position.stock_name}({stock_code})",
                    reason=exit_reason.value,
                    message=message,
                    quantity=sell_quantity,
                    exchange=target_exchange.value,
                )

                # C5 Fix: 매도 주문 재시도 로직 (지수 백오프)
                max_retries = 3
                result = None
                last_error = None

                for attempt in range(max_retries):
                    result = await self._order_api.sell(
                        stock_code=stock_code,
                        quantity=sell_quantity,
                        order_type=OrderType.MARKET,
                        exchange=target_exchange,
                    )

                    if result.success:
                        break

                    last_error = result.message
                    self._logger.warning(
                        f"매도 주문 실패 (시도 {attempt + 1}/{max_retries}): {result.message}",
                        stock_code=stock_code,
                    )

                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # 1초, 2초, 4초
                        await asyncio.sleep(wait_time)

                if not result or not result.success:
                    self._logger.error(
                        f"매도 주문 최종 실패 ({max_retries}회 시도): {last_error}",
                        stock_code=stock_code,
                    )
                    # CRITICAL 알림 전송
                    if self._telegram:
                        await self._telegram.send_message(
                            f"🚨 CRITICAL: 매도 주문 실패\n\n"
                            f"📌 {position.stock_name} ({stock_code})\n"
                            f"📊 수량: {position.quantity}주\n"
                            f"❌ 사유: {exit_reason.value}\n"
                            f"⚠️ 오류: {last_error}\n\n"
                            f"수동 매도 필요! (10분간 재시도 중단)"
                        )
                    return False  # V7.1: 매도 실패 → Circuit Breaker 활성화

                execution = await self._account_api.wait_for_execution(
                    order_no=result.order_no,
                    stock_code=stock_code,
                    max_wait_seconds=ExitConstants.EXECUTION_WAIT_SECONDS,
                    poll_interval=ExitConstants.EXECUTION_POLL_INTERVAL,
                )

                if execution is None:
                    self._logger.warning(f"매도 체결 타임아웃: {result.order_no}")
                    async with self._pending_sell_lock:
                        self._pending_sell_orders[stock_code] = result.order_no
                    return True  # pending 처리 중 = 재시도 불필요

                if execution.filled_qty == 0:
                    self._logger.warning(f"매도 체결 수량 0: {result.order_no}")
                    async with self._pending_sell_lock:
                        self._pending_sell_orders[stock_code] = result.order_no
                    return True  # pending 처리 중 = 재시도 불필요

                actual_exit_price = execution.filled_price

                self._logger.info(
                    f"매도 체결 완료: {position.stock_name}({stock_code})",
                    order_no=result.order_no,
                    filled_price=actual_exit_price,
                    filled_qty=execution.filled_qty,
                )

                async with self._pending_sell_lock:
                    if stock_code in self._pending_sell_orders:
                        del self._pending_sell_orders[stock_code]

                # V6.2-A D2: 청산 시점 핵심 지표 로깅
                position_risk = self._risk_manager.get_position_risk(stock_code)
                if position_risk:
                    sw = position_risk.structure_warning
                    self._logger.info(
                        f"[D2] 청산 지표: {stock_code}",
                        exit_reason=exit_reason.value,
                        entry_price=position_risk.entry_price,
                        trailing_stop=position_risk.trailing_stop_price,
                        highest_price=position_risk.highest_price,
                        is_ts_fallback=position_risk.is_ts_fallback,
                        ema9_below_count=sw.ema9_below_count if sw else 0,
                        vwap_below_count=sw.vwap_below_count if sw else 0,
                        is_warning=sw.is_warning if sw else False,
                        warning_type=sw.warning_type if sw else "",
                    )

                # 리스크 매니저 청산 처리
                pnl = self._risk_manager.on_exit(
                    stock_code,
                    actual_exit_price,
                    exit_reason,
                )

                # DB 기록
                trade_id = position.signal_metadata.get("trade_id") if position.signal_metadata else None
                if self._trade_repo and self._order_repo and trade_id:
                    try:
                        max_profit_rate = position.max_profit_rate if hasattr(position, "max_profit_rate") else None
                        max_loss_rate = position.max_loss_rate if hasattr(position, "max_loss_rate") else None

                        await self._trade_repo.close(
                            trade_id=trade_id,
                            exit_price=actual_exit_price,
                            exit_order_no=result.order_no,
                            exit_reason=exit_reason.value,
                            max_profit_rate=max_profit_rate,
                            max_loss_rate=max_loss_rate,
                        )

                        order = await self._order_repo.create(
                            stock_code=stock_code,
                            side=OrderSide.SELL,
                            order_type="MARKET",
                            quantity=execution.filled_qty,
                            trade_id=trade_id,
                        )
                        await self._order_repo.update_status(
                            order_id=order.id,
                            status=OrderStatus.FILLED,
                            order_no=result.order_no,
                            filled_quantity=execution.filled_qty,
                            filled_price=actual_exit_price,
                        )

                    except Exception as db_err:
                        self._logger.error(f"거래 청산 기록 실패: {db_err}")
                        # V6.2-A 코드리뷰 A5: DB 저장 실패 시 텔레그램 알림
                        if self._telegram:
                            await self._telegram.send_message(
                                f"⚠️ [CRITICAL] 청산 DB 저장 실패\n\n"
                                f"📌 종목: {stock_code}\n"
                                f"💰 청산가: {actual_exit_price:,}원\n"
                                f"📊 수량: {execution.filled_qty}주\n"
                                f"📝 사유: {exit_reason.value}\n"
                                f"❌ 오류: {str(db_err)[:100]}\n\n"
                                f"⚠️ 수동 확인 필요!"
                            )

                # 포지션 매니저 청산 처리
                await self._position_manager.close_position(
                    stock_code=stock_code,
                    exit_price=actual_exit_price,
                    reason=exit_reason.value,
                    order_no=result.order_no,
                )

                self.stats["trades_completed"] += 1
                return True  # V7.1: 매도 성공

            except Exception as e:
                self._logger.error(f"매도 주문 에러: {e}")
                return False  # V7.1: 예외 발생 시 실패로 처리

            finally:
                # V6.2-A D1: correlation_id 컨텍스트 해제
                unbind_context("correlation_id")

        return True  # Lock 외부 - 정상 완료

    async def execute_manual_sell(
        self,
        stock_code: str,
        quantity: int,
    ) -> Tuple[bool, str]:
        """
        수동 매도 실행 (PRD REQ-007)

        Args:
            stock_code: 종목코드
            quantity: 매도 수량 (주)

        Returns:
            (성공여부, 메시지)
        """
        # V6.2-Q FIX: Lock 추가 - 동시 매도 요청 방지
        lock = self._get_order_lock(stock_code)
        async with lock:
            return await self._execute_manual_sell_impl(stock_code, quantity)

    async def _execute_manual_sell_impl(
        self,
        stock_code: str,
        quantity: int,
    ) -> Tuple[bool, str]:
        """수동 매도 실행 구현 (Lock 내부에서 호출)"""
        try:
            if not self._is_market_open():
                return False, "장 운영 시간이 아닙니다"

            position = self._position_manager.get_position(stock_code)
            if not position:
                return False, f"{stock_code} 보유 포지션이 없습니다"

            if quantity > position.quantity:
                return False, (
                    f"매도 수량 초과\n"
                    f"보유: {position.quantity}주\n"
                    f"요청: {quantity}주"
                )

            stock_name = position.stock_name

            self._logger.info(
                f"수동 매도 주문: {stock_name}({stock_code})",
                quantity=quantity,
            )

            result = await self._order_api.sell(
                stock_code=stock_code,
                quantity=quantity,
                order_type=OrderType.MARKET,
            )

            if not result.success:
                return False, f"매도 주문 실패: {result.message}"

            execution = await self._account_api.wait_for_execution(
                order_no=result.order_no,
                stock_code=stock_code,
                max_wait_seconds=ExitConstants.EXECUTION_WAIT_SECONDS,
            )

            if execution is None or execution.filled_qty == 0:
                return False, f"체결 타임아웃 (주문번호: {result.order_no})"

            actual_price = execution.filled_price
            actual_qty = execution.filled_qty

            entry_price = position.entry_price
            pnl = (actual_price - entry_price) * actual_qty
            pnl_rate = ((actual_price / entry_price) - 1) * 100

            if actual_qty >= position.quantity:
                self._risk_manager.on_exit(stock_code, actual_price, ExitReason.MANUAL)
                await self._position_manager.close_position(
                    stock_code=stock_code,
                    exit_price=actual_price,
                    reason="수동 매도",
                    order_no=result.order_no,
                )
            else:
                self._position_manager.update_quantity(stock_code, position.quantity - actual_qty)

            pnl_sign = "+" if pnl >= 0 else ""
            return True, (
                f"매도 체결\n"
                f"종목: {stock_name}({stock_code})\n"
                f"수량: {actual_qty}주\n"
                f"단가: {actual_price:,}원\n"
                f"손익: {pnl_sign}{pnl:,.0f}원 ({pnl_sign}{pnl_rate:.2f}%)"
            )

        except Exception as e:
            self._logger.error(f"수동 매도 실패: {stock_code} - {e}")
            return False, f"매도 실패: {e}"

    # =========================================
    # 헬퍼 메서드
    # =========================================

    async def _check_pending_sell_order(
        self,
        stock_code: str,
        position: Position,
    ) -> Optional[bool]:
        """
        미체결 매도 주문 확인 및 처리

        Returns:
            None: 미체결 주문 없음 → 새 주문 진행
            True: 체결 완료 → 청산 처리됨
            False: 미체결/부분체결 → 대기 필요
        """
        # P0: Lock으로 pending_sell_orders 접근 보호
        async with self._pending_sell_lock:
            if stock_code not in self._pending_sell_orders:
                return None
            pending_order_no = self._pending_sell_orders[stock_code]

        self._logger.info(f"미체결 매도 주문 확인: {stock_code}, 주문번호={pending_order_no}")

        try:
            execution = await self._account_api.get_execution_info(
                order_no=pending_order_no,
                stock_code=stock_code,
            )

            if execution is None:
                self._logger.warning(f"미체결 주문 정보 없음, 추적 제거: {pending_order_no}")
                async with self._pending_sell_lock:
                    del self._pending_sell_orders[stock_code]
                return None

            if execution.filled_qty > 0 and execution.unfilled_qty == 0:
                # 전량 체결됨
                self._logger.info(
                    f"미체결 주문 전량 체결 확인: {pending_order_no}",
                    filled_qty=execution.filled_qty,
                    filled_price=execution.filled_price,
                )

                actual_exit_price = execution.filled_price

                pnl = self._risk_manager.on_exit(
                    stock_code,
                    actual_exit_price,
                    ExitReason.MANUAL,
                )

                trade_id = position.signal_metadata.get("trade_id") if position.signal_metadata else None
                if self._trade_repo and trade_id:
                    try:
                        await self._trade_repo.close(
                            trade_id=trade_id,
                            exit_price=actual_exit_price,
                            exit_order_no=pending_order_no,
                            exit_reason="DELAYED_FILL",
                        )
                    except Exception as db_err:
                        self._logger.error(f"지연 체결 DB 기록 실패: {db_err}")

                await self._position_manager.close_position(
                    stock_code=stock_code,
                    exit_price=actual_exit_price,
                    reason="DELAYED_FILL",
                    order_no=pending_order_no,
                )

                async with self._pending_sell_lock:
                    del self._pending_sell_orders[stock_code]
                self.stats["trades_completed"] += 1

                if self._telegram:
                    profit_rate = ((actual_exit_price - position.entry_price) / position.entry_price) * 100
                    await self._telegram.send_message(
                        f"[지연 체결 확인]\n"
                        f"종목: {position.stock_name} ({stock_code})\n"
                        f"체결가: {actual_exit_price:,}원\n"
                        f"수익률: {profit_rate:+.2f}%\n"
                        f"주문번호: {pending_order_no}"
                    )

                return True

            elif execution.unfilled_qty > 0:
                # V6.2-A: 부분 체결 시 포지션 수량 동기화
                if execution.filled_qty > 0:
                    # 부분 체결됨 - 포지션 수량 업데이트
                    new_qty = position.quantity - execution.filled_qty
                    if new_qty > 0:
                        self._position_manager.update_quantity(stock_code, new_qty)
                        self._logger.info(
                            f"부분 체결 수량 동기화: {stock_code}",
                            original_qty=position.quantity,
                            filled_qty=execution.filled_qty,
                            remaining_qty=new_qty,
                        )
                        # RiskManager에도 수량 동기화
                        if self._risk_manager:
                            self._risk_manager.sync_quantity(stock_code, new_qty)
                    else:
                        # 모든 수량이 체결됨 (unfilled_qty가 원 주문의 잔량일 수 있음)
                        self._logger.warning(
                            f"부분 체결로 잔량 0: {stock_code}, 포지션 종료 처리 필요"
                        )
                else:
                    self._logger.info(
                        f"미체결 주문 대기 중: {pending_order_no}",
                        filled_qty=execution.filled_qty,
                        unfilled_qty=execution.unfilled_qty,
                    )
                return False

        except Exception as e:
            self._logger.error(f"미체결 주문 확인 에러: {e}")

        return False

    async def handle_condition_exit_signal(
        self,
        stock_code: str,
        stock_name: str,
        condition_seq: int,
    ) -> None:
        """
        조건식 이탈 신호 처리

        보유 중인 종목: 자동 청산
        """
        if not self._position_manager.has_position(stock_code):
            self._logger.info(
                f"조건식 이탈 (미보유): {stock_name}({stock_code}) - 계속 모니터링"
            )
            return

        position = self._position_manager.get_position(stock_code)
        if position is None:
            return

        self._logger.info(
            f"조건식 이탈 청산: {stock_name}({stock_code})",
            condition_seq=condition_seq,
            profit_loss_rate=f"{position.profit_loss_rate:.2f}%",
        )

        if self._telegram:
            await self._telegram.send_message(
                f"[조건식 이탈]\n"
                f"종목: {stock_name}({stock_code})\n"
                f"조건식: {condition_seq}번\n"
                f"수익률: {position.profit_loss_rate:+.2f}%\n"
                f"-> 자동 청산 진행"
            )

        await self.execute_full_sell(
            stock_code=stock_code,
            exit_reason=ExitReason.TECHNICAL_EXIT,
            message=f"조건식 {condition_seq}번 이탈",
        )

    # =========================================
    # Grand Trend V6: ATR 트레일링 스탑
    # =========================================

    async def _calculate_initial_trailing_stop(
        self,
        stock_code: str,
        current_price: int,
        multiplier: Optional[float] = None,
    ) -> int:
        """
        Grand Trend V6.2-A: ATR 트레일링 스탑 계산

        수식: trailing_stop = close - ATR(10) × multiplier

        Args:
            stock_code: 종목코드
            current_price: 현재가
            multiplier: ATR 배수 (None이면 기본값 사용)
                - 기본값: ts_atr_mult_base (6.0)
                - 구조 경고 시: ts_atr_mult_tight (4.5)

        Returns:
            트레일링 스탑 가격 (원), 실패 시 0
        """
        try:
            builder = self._candle_manager.get_builder(stock_code)
            if builder is None:
                self._logger.warning(f"ATR 트레일링 스탑 계산 실패 - 캔들 빌더 없음: {stock_code}")
                return 0

            # 3분봉 기준 ATR 계산
            candles = builder.get_candles(Timeframe.M3)
            if candles is None or len(candles) < self._risk_settings.atr_trailing_period:
                # V6.2-A: 캔들 부족 시 고정손절 수준으로 fallback TS 설정
                # V6.2-C Fix: entry_price 기준으로 fallback TS 계산 (current_price 대신)
                position_risk = self._risk_manager.get_position_risk(stock_code)
                if position_risk and position_risk.entry_price > 0:
                    fallback_ts = int(position_risk.entry_price * 0.96)  # 진입가 기준 -4%
                    price_basis = f"entry_price={position_risk.entry_price:,}원"
                else:
                    fallback_ts = int(current_price * 0.96)  # 폴백: 현재가 기준
                    price_basis = f"current_price={current_price:,}원 (폴백)"

                self._logger.warning(
                    f"ATR 트레일링 스탑 계산 실패 - 캔들 부족: {stock_code} "
                    f"(현재 {len(candles) if candles is not None else 0}개, 필요 {self._risk_settings.atr_trailing_period}개) "
                    f"→ Fallback TS 적용: {fallback_ts:,}원 ({price_basis})"
                )
                # RiskManager에 fallback TS 설정
                self._risk_manager.set_trailing_stop_price(stock_code, fallback_ts)
                return fallback_ts

            # ATR(10) 계산
            atr = Indicator.atr(
                candles['high'],
                candles['low'],
                candles['close'],
                period=self._risk_settings.atr_trailing_period
            )

            if atr is None or len(atr) == 0:
                self._logger.warning(f"ATR 계산 결과 없음: {stock_code}")
                return 0

            current_atr = atr.iloc[-1]
            if current_atr <= 0:
                self._logger.warning(f"ATR 값 비정상: {stock_code}, ATR={current_atr}")
                return 0

            # V6.2-I: effective_atr 계산 (매수 시점 ATR 이상 유지)
            position_risk = self._risk_manager.get_position_risk(stock_code)
            effective_atr = current_atr

            if position_risk:
                # V6.2-I: 최초 호출 시 entry_atr 저장
                if position_risk.entry_atr == 0 or position_risk.entry_atr < 0.01:
                    position_risk.entry_atr = current_atr
                    self._logger.info(
                        f"[V6.2-I] entry_atr 저장: {stock_code} ATR={current_atr:.0f}"
                    )

                # 1. 매수 시점 ATR과 비교 (더 큰 값 사용)
                if position_risk.entry_atr > 0:
                    effective_atr = max(current_atr, position_risk.entry_atr)

                # 2. 최소 ATR 보장 (매수가의 0.5%)
                if position_risk.entry_price > 0:
                    min_atr = position_risk.entry_price * 0.005
                    effective_atr = max(effective_atr, min_atr)

                # 로그 (current_atr과 다른 경우만)
                if effective_atr != current_atr:
                    self._logger.info(
                        f"[V6.2-I] effective_atr 적용: {stock_code} "
                        f"(current={current_atr:.0f}, entry={position_risk.entry_atr:.0f}, "
                        f"min={position_risk.entry_price * 0.005:.0f}) → {effective_atr:.0f}"
                    )

            # V6.2-A: multiplier 선택 (구조 경고 상태 기반)
            if multiplier is None:
                # 기본값: ts_atr_mult_base (6.0)
                multiplier = self._risk_settings.ts_atr_mult_base

            # trailing_stop = close - effective_atr × multiplier (V6.2-I)
            trailing_stop = int(current_price - effective_atr * multiplier)

            self._logger.debug(
                f"ATR 트레일링 스탑 계산: {stock_code}",
                current_price=current_price,
                atr=int(current_atr),
                multiplier=multiplier,
                trailing_stop=trailing_stop,
            )

            return max(trailing_stop, 0)

        except Exception as e:
            self._logger.error(f"ATR 트레일링 스탑 계산 에러: {stock_code} - {e}")
            return 0

    async def update_trailing_stop_on_candle_complete(
        self,
        stock_code: str,
        candle: Candle,
    ) -> None:
        """
        Grand Trend V6.2-A: 3분봉 완성 시 ATR 트레일링 스탑 업데이트

        V6.2-A 변경:
        - USE_PARTIAL_EXIT=false: 진입 즉시 TS 활성화 (분할익절 대기 없음)
        - 구조 경고 업데이트: EMA9/VWAP 2봉 연속 하회 시 TS 타이트닝

        (Pine Script: trailing_stop = max(close - ATR × mult, trailing_stop_prev))
        """
        # 3분봉만 처리
        if candle.timeframe != Timeframe.M3:
            return

        # 포지션 확인
        position_risk = self._risk_manager.get_position_risk(stock_code)
        if position_risk is None:
            return

        try:
            # ========== V6.2-A: 분할 익절 비활성화 시 로직 ==========
            if not self._risk_settings.use_partial_exit:
                # 1. 구조 경고 업데이트 (EMA9, VWAP)
                builder = self._candle_manager.get_builder(stock_code)
                if builder is not None:
                    candles = builder.get_candles(Timeframe.M3)
                    if candles is not None and len(candles) >= self._risk_settings.ema_struct_len:
                        # EMA9 계산
                        ema9 = Indicator.ema(candles['close'], span=self._risk_settings.ema_struct_len)
                        current_ema9 = ema9.iloc[-1] if len(ema9) > 0 else 0

                        # HLC3 (VWAP 근사)
                        hlc3 = Indicator.hlc3(candles['high'], candles['low'], candles['close'])
                        current_hlc3 = hlc3.iloc[-1] if len(hlc3) > 0 else 0

                        # 구조 경고 상태 업데이트
                        is_warning = self._risk_manager.update_structure_warning(
                            stock_code=stock_code,
                            close=candle.close,
                            ema9=current_ema9,
                            hlc3=current_hlc3,
                            confirm_bars=self._risk_settings.confirm_bars,
                            use_vwap_warn=self._risk_settings.use_vwap_warn,
                            use_hl_break=self._risk_settings.use_hl_break,
                        )

                        if is_warning:
                            self._logger.info(
                                f"[StructureWarning] {stock_code}: TS 타이트닝 적용 (4.5배수)"
                            )

                # 2. ATR 배수 선택 (구조 경고 상태 기반)
                ts_multiplier = position_risk.get_ts_multiplier(
                    base=self._risk_settings.ts_atr_mult_base,
                    tight=self._risk_settings.ts_atr_mult_tight,
                )

                # 3. 새로운 트레일링 스탑 계산
                new_trailing_stop = await self._calculate_initial_trailing_stop(
                    stock_code, candle.close, multiplier=ts_multiplier
                )

                if new_trailing_stop <= 0:
                    return

                # 4. 상승만 가능 (절대 하락 안 함)
                updated = self._risk_manager.set_trailing_stop_price(stock_code, new_trailing_stop)

                if updated:
                    current_trailing = position_risk.trailing_stop_price
                    warning_status = "(Tight)" if position_risk.structure_warning and position_risk.structure_warning.is_warning else ""

                    self._logger.info(
                        f"ATR 트레일링 스탑 상향 조정{warning_status}: {stock_code}",
                        new_trailing_stop=current_trailing,
                        candle_close=candle.close,
                        multiplier=ts_multiplier,
                    )

                return

            # ========== 기존 V6 로직 (USE_PARTIAL_EXIT=true) ==========

            # 분할 익절 후에만 트레일링 스탑 업데이트
            if not self._risk_manager.is_partial_exited(stock_code):
                return

            # 새로운 트레일링 스탑 계산
            new_trailing_stop = await self._calculate_initial_trailing_stop(
                stock_code, candle.close
            )

            if new_trailing_stop <= 0:
                return

            # 상승만 가능 (절대 하락 안 함)
            updated = self._risk_manager.set_trailing_stop_price(stock_code, new_trailing_stop)

            if updated:
                current_trailing = position_risk.trailing_stop_price if position_risk else 0

                self._logger.info(
                    f"ATR 트레일링 스탑 상향 조정: {stock_code}",
                    new_trailing_stop=current_trailing,
                    candle_close=candle.close,
                )

        except Exception as e:
            self._logger.error(f"트레일링 스탑 업데이트 에러: {stock_code} - {e}")

    # =========================================
    # Grand Trend V6.2-A: 진입 시 TS 즉시 초기화
    # =========================================

    async def initialize_trailing_stop_on_entry_v62a(
        self,
        stock_code: str,
        entry_price: int,
    ) -> int:
        """
        Grand Trend V6.2-A: 진입 시 트레일링 스탑 즉시 초기화

        V6.2-A에서는 분할 익절을 대기하지 않고 진입 즉시 TS를 활성화합니다.
        - 초기 배수: ts_atr_mult_base (6.0)
        - 수식: TS = entry_price - ATR(10) × 6.0

        Args:
            stock_code: 종목코드
            entry_price: 진입가

        Returns:
            초기 트레일링 스탑 가격 (원), 실패 시 0
        """
        if self._risk_settings.use_partial_exit:
            # 기존 V6 로직: 분할 익절 후 TS 활성화 (여기서는 아무것도 안 함)
            return 0

        try:
            # 구조 경고 초기화
            self._risk_manager.init_structure_warning(stock_code)

            # 진입 날짜 설정 (보유일 계산용)
            self._risk_manager.set_entry_date(stock_code, date.today())

            # 초기 TS 계산 (기본 배수 6.0 사용)
            initial_ts = await self._calculate_initial_trailing_stop(
                stock_code,
                entry_price,
                multiplier=self._risk_settings.ts_atr_mult_base,
            )

            if initial_ts > 0:
                self._risk_manager.set_trailing_stop_price(stock_code, initial_ts)
                self._logger.info(
                    f"[V6.2-A] 진입 시 TS 활성화: {stock_code}",
                    entry_price=entry_price,
                    trailing_stop=initial_ts,
                    multiplier=self._risk_settings.ts_atr_mult_base,
                )

            return initial_ts

        except Exception as e:
            self._logger.error(f"진입 시 TS 초기화 에러: {stock_code} - {e}")
            return 0
