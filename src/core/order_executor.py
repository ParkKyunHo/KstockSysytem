"""
OrderExecutor - 주문 실행 전문 모듈

PRD v3.2.1 Phase 2: TradingEngine에서 분리

책임:
- 매수 주문 실행 및 체결 대기
- 종목별 Lock 관리
- 시스템 매수 쿨다운 관리
"""

import asyncio
from datetime import datetime
from typing import Awaitable, Callable, Dict, Optional

import structlog

from src.api.endpoints.account import AccountAPI
from src.api.endpoints.order import OrderAPI, OrderType
from src.core.signal_detector import Signal
from src.core.position_manager import PositionManager, EntrySource
from src.database.models import OrderSide, OrderStatus, TradeStatus
from src.core.risk_manager import RiskManager
from src.utils.config import RiskSettings
from src.utils.logger import generate_correlation_id, bind_context, unbind_context
from src.database.repository import OrderRepository, TradeRepository, atomic_session
from src.notification.telegram import TelegramBot

# V6.2-A: 진입 후 TS 초기화 콜백 타입
OnBuyFilledCallback = Callable[[str, int], Awaitable[int]]  # (stock_code, entry_price) -> trailing_stop


class TradingConstants:
    """거래 관련 상수"""

    # V6.2-A Phase 4: 체결 대기 타임아웃 5초→10초 (호가 급변 대응)
    EXECUTION_WAIT_SECONDS = 10
    EXECUTION_POLL_INTERVAL = 0.5

    # V6.2-A: 부분 체결 재시도 설정
    PARTIAL_FILL_MAX_RETRIES = 2      # 미체결 수량 재시도 횟수
    PARTIAL_FILL_RETRY_DELAY = 0.5    # 재시도 간 대기 (초)


class OrderExecutor:
    """
    주문 실행 전문 모듈

    TradingEngine에서 매수 관련 로직 분리:
    - _execute_buy_order
    - _get_order_lock
    - 시스템 매수 쿨다운 관리
    """

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        order_api: OrderAPI,
        account_api: AccountAPI,
        trade_repo: Optional[TradeRepository],
        order_repo: Optional[OrderRepository],
        telegram: Optional[TelegramBot],
        risk_settings: RiskSettings,
        logger,
        is_regular_trading_hours_fn: Callable[[], bool],
        is_market_open_fn: Callable[[], bool],
        # P0: 공유 Lock (Race Condition 방지)
        order_locks: Optional[Dict[str, asyncio.Lock]] = None,
        # V6.2-A: 진입 후 TS 초기화 콜백
        on_buy_filled_callback: Optional[OnBuyFilledCallback] = None,
        # V6.2-A: 신호 큐 처리 콜백 (쿨다운 해제 후 호출)
        on_cooldown_expired_callback: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        """
        Args:
            position_manager: 포지션 관리자
            risk_manager: 리스크 관리자
            order_api: 주문 API
            account_api: 계좌 API
            trade_repo: 거래 기록 저장소 (Optional)
            order_repo: 주문 기록 저장소 (Optional)
            telegram: 텔레그램 봇 (Optional)
            risk_settings: 리스크 설정
            logger: 로거
            is_regular_trading_hours_fn: 장중 여부 확인 콜백
            is_market_open_fn: 장 운영 여부 확인 콜백
            order_locks: 공유 Lock 딕셔너리 (Race Condition 방지)
            on_buy_filled_callback: V6.2-A 진입 후 TS 초기화 콜백
            on_cooldown_expired_callback: V6.2-A 신호 큐 처리 콜백 (쿨다운 해제 후)
        """
        self._position_manager = position_manager
        self._risk_manager = risk_manager
        self._order_api = order_api
        self._account_api = account_api
        self._trade_repo = trade_repo
        self._order_repo = order_repo
        self._telegram = telegram
        self._settings = risk_settings
        self._logger = logger.bind(component="OrderExecutor") if hasattr(logger, "bind") else logger

        # 콜백 함수
        self._is_regular_trading_hours = is_regular_trading_hours_fn
        self._is_market_open = is_market_open_fn
        self._on_buy_filled_callback = on_buy_filled_callback  # V6.2-A
        self._on_cooldown_expired_callback = on_cooldown_expired_callback  # V6.2-A 신호 큐

        # 상태
        # P0: 공유 Lock 사용 (Race Condition 방지)
        self._order_locks = order_locks if order_locks is not None else {}
        self._last_system_buy_time: Optional[datetime] = None
        # V6.2-A: 신호 큐 처리 Task 참조 (종료 시 취소용)
        self._queue_processing_task: Optional[asyncio.Task] = None

        # 통계
        self.stats = {
            "orders_placed": 0,
            "orders_filled": 0,
            "orders_cancelled": 0,
            "orders_failed": 0,
        }

        self._logger.info("OrderExecutor 초기화 완료")

    def _get_order_lock(self, stock_code: str) -> asyncio.Lock:
        """종목별 주문 Lock 반환"""
        if stock_code not in self._order_locks:
            self._order_locks[stock_code] = asyncio.Lock()
        return self._order_locks[stock_code]

    def set_system_buy_cooldown(self) -> None:
        """시스템 매수 쿨다운 시작"""
        self._last_system_buy_time = datetime.now()
        self._logger.info(
            f"[PRD v3.2] 시스템 매수 쿨다운 시작: {self._settings.buy_cooldown_seconds}초"
        )

    def is_in_cooldown(self) -> bool:
        """시스템 매수 쿨다운 중인지 확인"""
        if self._last_system_buy_time is None:
            return False

        elapsed = (datetime.now() - self._last_system_buy_time).total_seconds()
        return elapsed < self._settings.buy_cooldown_seconds

    def is_in_system_buy_cooldown(self) -> bool:
        """
        시스템 매수 쿨다운 중인지 확인 (alias)

        V6.2-A: TradingEngine에서 호출하는 메서드명과 일치시키기 위한 alias
        """
        return self.is_in_cooldown()

    def get_cooldown_remaining(self) -> float:
        """쿨다운 남은 시간(초) 반환"""
        if self._last_system_buy_time is None:
            return 0.0

        elapsed = (datetime.now() - self._last_system_buy_time).total_seconds()
        remaining = self._settings.buy_cooldown_seconds - elapsed
        return max(0.0, remaining)

    def cancel_pending_tasks(self) -> None:
        """V6.2-A: 대기 중인 Task 취소 (종료 시 호출)"""
        if self._queue_processing_task and not self._queue_processing_task.done():
            self._queue_processing_task.cancel()
            self._logger.info("[신호 큐] 대기 중인 Task 취소됨")

    async def _schedule_signal_queue_processing(self) -> None:
        """
        V6.2-A: 쿨다운 해제 후 신호 큐 처리 스케줄링

        쿨다운 시간만큼 대기 후 콜백을 호출합니다.
        매수 성공 후 호출되어, 쿨다운 해제 시점에 대기 중인 신호를 처리합니다.
        """
        if not self._on_cooldown_expired_callback:
            return

        try:
            # 쿨다운 시간만큼 대기 (+0.5초 여유)
            wait_seconds = self._settings.buy_cooldown_seconds + 0.5
            self._logger.debug(
                f"[신호 큐] 스케줄링: {wait_seconds:.1f}초 후 큐 처리 예정"
            )
            await asyncio.sleep(wait_seconds)

            # 콜백 호출 (TradingEngine._process_signal_queue)
            # 실패 시 1회 재시도
            self._logger.info("[신호 큐] 쿨다운 해제 - 큐 처리 시작")
            try:
                await self._on_cooldown_expired_callback()
            except Exception as callback_error:
                self._logger.warning(f"[신호 큐] 콜백 실패, 2초 후 재시도: {callback_error}")
                await asyncio.sleep(2.0)
                await self._on_cooldown_expired_callback()

        except asyncio.CancelledError:
            self._logger.debug("[신호 큐] 스케줄링 취소됨")
        except Exception as e:
            self._logger.error(f"[신호 큐] 스케줄링 에러: {e}")
        finally:
            self._queue_processing_task = None

    async def execute_buy_order(self, signal: Signal) -> bool:
        """
        매수 주문 실행

        P0 이슈 수정:
        1. 종목별 Lock으로 동시 주문 방지
        2. 체결 확인 후 포지션 등록
        3. 체결가 기반 포지션 등록
        4. 미체결 시 주문 취소

        Args:
            signal: 매수 신호

        Returns:
            bool: 성공 여부
        """
        stock_code = signal.stock_code
        lock = self._get_order_lock(stock_code)

        try:
            await asyncio.wait_for(lock.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            self._logger.error(
                f"[OrderExecutor] Lock 획득 타임아웃 (30초): {stock_code}"
            )
            return False

        try:
            # V6.2-A D1: correlation_id 생성 및 바인딩 (거래 추적용)
            correlation_id = generate_correlation_id(stock_code)
            bind_context(correlation_id=correlation_id)

            try:
                # 1. Lock 획득 후 상태 재확인
                if self._position_manager.has_position(stock_code):
                    self._logger.debug(f"Lock 획득 후 이미 보유 중: {stock_code}")
                    return False

                # 2. 주문 가능 금액 조회
                balance = await self._account_api.get_balance()
                available = balance.available_amount

                # 3. PRD v3.1: 매수 금액/수량 계산 (총 평가금액의 5%)
                # 총 평가금액 = 예수금 + 보유종목 평가금액
                positions_data = await self._account_api.get_positions()
                total_eval = positions_data.deposit + positions_data.total_eval_amount

                # 매수 금액 = 총 평가금액 * buy_amount_ratio (기본 5%)
                buy_amount_ratio = self._settings.buy_amount_ratio
                buy_amount = int(total_eval * buy_amount_ratio)

                # 미수 방지: 가용 금액을 초과하지 않도록 제한
                if buy_amount > available:
                    self._logger.info(
                        f"[V7.0] 매수금액 조정: {buy_amount:,} → {available:,} (미수 방지)"
                    )
                    buy_amount = available

                # 매수 수량 계산
                quantity = buy_amount // signal.price
                if quantity < 1:
                    msg = f"매수 금액 부족: {stock_code} (1주 가격 {signal.price:,}원 > 매수금액 {buy_amount:,}원)"
                    self._logger.warning(msg)
                    # V6.2-A: 매수 실패 알림
                    if self._telegram:
                        await self._telegram.send_message(
                            f"⚠️ 매수 실패\n\n"
                            f"📌 {signal.stock_name} ({stock_code})\n"
                            f"💰 가용금액 부족\n"
                            f"   필요: {signal.price:,}원/주\n"
                            f"   가용: {buy_amount:,}원"
                        )
                    return False

                if signal.price > available:
                    msg = f"매수 금액 부족: {stock_code} (1주 가격 {signal.price:,}원 > 가용 {available:,}원)"
                    self._logger.warning(msg)
                    # V6.2-A: 매수 실패 알림
                    if self._telegram:
                        await self._telegram.send_message(
                            f"⚠️ 매수 실패\n\n"
                            f"📌 {signal.stock_name} ({stock_code})\n"
                            f"💰 가용금액 부족\n"
                            f"   필요: {signal.price:,}원/주\n"
                            f"   가용: {available:,}원"
                        )
                    return False

                self._logger.info(
                    f"[V7.0] 자금관리: 총평가 {total_eval:,}원 × {buy_amount_ratio*100:.1f}% "
                    f"= {buy_amount:,}원 → {quantity}주"
                )

                # 4. 시장가 매수 주문 제출
                self._logger.info(
                    f"매수 주문 제출: {signal.stock_name}({stock_code})",
                    quantity=quantity,
                    estimated_price=signal.price,
                )

                result = await self._order_api.buy(
                    stock_code=stock_code,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                )

                self.stats["orders_placed"] += 1

                if not result.success:
                    self._logger.error(f"매수 주문 실패: {result.message}")
                    self.stats["orders_failed"] += 1
                    return False

                # 5. 체결 확인 (최대 5초 대기) + V6.2-A 부분체결 재시도
                self._logger.info(f"체결 대기 중: 주문번호={result.order_no}")

                # V6.2-A: 부분 체결 재시도를 위한 누적 변수
                # V6.2-A 코드리뷰 B2: 주문번호 추적 개선
                original_order_no = result.order_no  # 원본 주문번호 보존
                all_order_nos = [result.order_no]    # 모든 관련 주문번호 추적
                total_filled_qty = 0
                total_filled_value = 0  # 가중평균가 계산용
                remaining_qty = quantity
                retry_count = 0

                while remaining_qty > 0 and retry_count <= TradingConstants.PARTIAL_FILL_MAX_RETRIES:
                    execution = await self._account_api.wait_for_execution(
                        order_no=result.order_no,
                        stock_code=stock_code,
                        max_wait_seconds=TradingConstants.EXECUTION_WAIT_SECONDS,
                        poll_interval=TradingConstants.EXECUTION_POLL_INTERVAL,
                    )

                    # 6. 타임아웃 처리
                    if execution is None:
                        if retry_count == 0:
                            # 첫 시도에서 타임아웃 - 취소
                            self._logger.warning(f"체결 타임아웃, 주문 취소 시도: {result.order_no}")
                            try:
                                await self._order_api.cancel(
                                    original_order_no=result.order_no,
                                    stock_code=stock_code,
                                    quantity=remaining_qty,
                                )
                                self.stats["orders_cancelled"] += 1

                                # V6.2-A 코드리뷰 B5: 취소 후 최종 체결 확인
                                # - Ghost Order 방지: 취소 전 체결됐을 수 있음
                                await asyncio.sleep(1.0)
                                final_exec = await self._account_api.get_execution_info(
                                    order_no=result.order_no,
                                    stock_code=stock_code,
                                )
                                if final_exec and final_exec.filled_qty > 0:
                                    # 취소 전 체결됨 → 포지션 등록 진행
                                    self._logger.warning(
                                        f"[B5] 취소 전 체결 감지: {final_exec.filled_qty}주 @ {final_exec.filled_price:,}원"
                                    )
                                    total_filled_qty = final_exec.filled_qty
                                    total_filled_value = final_exec.filled_price * final_exec.filled_qty
                                    remaining_qty = 0  # while 루프 종료
                                    continue  # 정상 처리로 진행
                            except Exception as e:
                                # [P0-2] 주문 취소 실패 시 텔레그램 알림 필수
                                # Ghost Order 발생 가능성 - 운영자가 즉시 확인해야 함
                                self._logger.error(f"주문 취소 실패 (Ghost Order 위험): {e}")
                                if self._telegram:
                                    try:
                                        await self._telegram.send_message(
                                            f"⚠️ [CRITICAL] 주문 취소 실패\n"
                                            f"종목: {stock_code}\n"
                                            f"주문번호: {result.order_no}\n"
                                            f"수량: {remaining_qty}주\n"
                                            f"오류: {e}\n"
                                            f"→ HTS에서 미체결 주문 확인 필요"
                                        )
                                    except Exception:
                                        pass  # 텔레그램 전송 실패는 무시
                            return False
                        else:
                            # 재시도 중 타임아웃 - 현재까지 체결된 수량으로 진행
                            self._logger.warning(
                                f"부분체결 재시도 타임아웃, 체결된 수량으로 진행: "
                                f"{total_filled_qty}/{quantity}주"
                            )
                            break

                    if execution.filled_qty == 0:
                        if total_filled_qty == 0:
                            self._logger.warning(f"체결 수량 0: {result.order_no}")
                            return False
                        break

                    # 체결 수량 누적
                    total_filled_qty += execution.filled_qty
                    total_filled_value += execution.filled_price * execution.filled_qty
                    remaining_qty = quantity - total_filled_qty

                    if remaining_qty > 0:
                        # 부분 체결 - 재시도
                        retry_count += 1
                        self._logger.info(
                            f"부분체결 감지: {execution.filled_qty}/{quantity}주, "
                            f"미체결 {remaining_qty}주, 재시도 {retry_count}/{TradingConstants.PARTIAL_FILL_MAX_RETRIES}"
                        )

                        if retry_count <= TradingConstants.PARTIAL_FILL_MAX_RETRIES:
                            # 미체결 수량 재주문
                            await asyncio.sleep(TradingConstants.PARTIAL_FILL_RETRY_DELAY)
                            result = await self._order_api.buy(
                                stock_code=stock_code,
                                quantity=remaining_qty,
                                order_type=OrderType.MARKET,
                            )
                            if not result.success:
                                self._logger.warning(f"미체결 재주문 실패, 현재 체결량으로 진행: {total_filled_qty}주")
                                break
                            # V6.2-A 코드리뷰 B2: 재주문 번호 추적
                            all_order_nos.append(result.order_no)
                            self._logger.info(
                                f"재주문 생성: {result.order_no} (원본: {original_order_no}, "
                                f"총 {len(all_order_nos)}건)"
                            )

                if total_filled_qty == 0:
                    self._logger.warning(f"최종 체결 수량 0: {stock_code}")
                    return False

                # 7. 체결 정보로 포지션 등록 (가중평균가 사용)
                # V6.2-A: 부분체결 누적 기준
                actual_quantity = total_filled_qty
                actual_price = int(total_filled_value / total_filled_qty) if total_filled_qty > 0 else execution.filled_price
                slippage = actual_price - signal.price
                slippage_rate = (slippage / signal.price) * 100 if signal.price > 0 else 0

                self._logger.info(
                    f"매수 체결 완료: {signal.stock_name}({stock_code})",
                    order_no=result.order_no,
                    filled_qty=actual_quantity,
                    filled_price=actual_price,
                    estimated_price=signal.price,
                    slippage=f"{slippage_rate:+.2f}%",
                )

                # V6.2-A D2: 진입 시점 핵심 지표 로깅
                if signal.metadata:
                    self._logger.info(
                        f"[D2] 진입 지표: {stock_code}",
                        ema3=signal.metadata.get("ema3"),
                        ema20=signal.metadata.get("ema20"),
                        ema60=signal.metadata.get("ema60"),
                        ema200=signal.metadata.get("ema200"),
                        body_size_pct=signal.metadata.get("body_size_pct"),
                        volume_ratio=signal.metadata.get("volume_ratio"),
                    )

                self.stats["orders_filled"] += 1

                # 8. 리스크 매니저에 진입 등록 (체결가 기반)
                self._risk_manager.on_entry(
                    stock_code,
                    actual_price,      # 체결가 사용
                    actual_quantity,   # 체결 수량 사용
                    entry_source=EntrySource.SYSTEM,   # V6.2-Q: 시스템 자동 매수
                )

                # 9. 데이터베이스 기록 (Trade, Order 생성)
                # V6.2-Q FIX: atomic_session으로 진정한 원자성 보장
                trade_id = None
                if self._trade_repo and self._order_repo:
                    try:
                        async with atomic_session() as session:
                            # Trade와 Order를 동일 트랜잭션에서 생성
                            trade = await self._trade_repo.create(
                                stock_code=stock_code,
                                stock_name=signal.stock_name,
                                strategy=signal.strategy.value,
                                entry_price=actual_price,
                                entry_quantity=actual_quantity,
                                entry_order_no=result.order_no,
                                entry_reason=signal.reason,
                                signal_strength=signal.metadata.get("strength") if signal.metadata else None,
                                session=session,  # V6.2-Q FIX: 세션 전달
                            )
                            trade_id = trade.id
                            # V6.2-A D1: trade_id로 correlation_id 업데이트
                            correlation_id = generate_correlation_id(stock_code, trade_id)
                            bind_context(correlation_id=correlation_id)
                            self._logger.info(f"거래 기록 생성: trade_id={trade_id}")

                            # Order 생성 (동일 트랜잭션 - 실패 시 자동 롤백)
                            order = await self._order_repo.create(
                                stock_code=stock_code,
                                side=OrderSide.BUY,
                                order_type="MARKET",
                                quantity=actual_quantity,
                                trade_id=trade_id,
                                session=session,  # V6.2-Q FIX: 세션 전달
                            )
                            await self._order_repo.update_status(
                                order_id=order.id,
                                status=OrderStatus.FILLED,
                                order_no=result.order_no,
                                filled_quantity=actual_quantity,
                                filled_price=actual_price,
                                session=session,  # V6.2-Q FIX: 세션 전달
                            )
                        # atomic_session 블록 종료 시 자동 commit

                    except Exception as db_err:
                        self._logger.error(f"거래 기록 저장 실패: {db_err}")
                        # V6.2-A 코드리뷰 A5: DB 저장 실패 시 텔레그램 알림
                        if self._telegram:
                            await self._telegram.send_message(
                                f"⚠️ [CRITICAL] DB 저장 실패\n\n"
                                f"📌 종목: {signal.stock_name} ({stock_code})\n"
                                f"💰 체결가: {actual_price:,}원\n"
                                f"📊 수량: {actual_quantity}주\n"
                                f"❌ 오류: {str(db_err)[:100]}\n\n"
                                f"⚠️ 수동 확인 필요!"
                            )

                # 10. 포지션 매니저에 등록 (체결가 기반)
                # V6.2-A 코드리뷰 B1: 실패 시 RiskManager/Trade 롤백
                metadata = signal.metadata.copy() if signal.metadata else {}
                metadata["reason"] = signal.reason
                metadata["order_no"] = result.order_no
                metadata["estimated_price"] = signal.price
                metadata["slippage"] = slippage
                metadata["slippage_rate"] = slippage_rate
                metadata["trade_id"] = trade_id  # DB Trade ID 저장

                try:
                    await self._position_manager.open_position(
                        stock_code=stock_code,
                        stock_name=signal.stock_name,
                        strategy=signal.strategy,
                        entry_price=actual_price,      # 체결가 사용
                        quantity=actual_quantity,      # 체결 수량 사용
                        order_no=result.order_no,
                        signal_metadata=metadata,
                        entry_source=EntrySource.SYSTEM,  # 시스템 자동 매수
                    )
                except Exception as pos_err:
                    # V6.2-A 코드리뷰 B1: 포지션 등록 실패 시 롤백
                    self._logger.error(f"포지션 등록 실패, 롤백 진행: {pos_err}")

                    # 1. RiskManager에서 제거
                    self._risk_manager.remove_position_risk(stock_code)

                    # 2. Trade를 CANCELLED로 롤백
                    if trade_id and self._trade_repo:
                        await self._trade_repo.update_status(trade_id, TradeStatus.CANCELLED)

                    # 3. 텔레그램 알림
                    if self._telegram:
                        await self._telegram.send_message(
                            f"⚠️ [CRITICAL] 포지션 등록 실패\n\n"
                            f"📌 종목: {signal.stock_name} ({stock_code})\n"
                            f"💰 체결가: {actual_price:,}원\n"
                            f"📊 수량: {actual_quantity}주\n"
                            f"❌ 오류: {str(pos_err)[:100]}\n\n"
                            f"⚠️ 실제 체결은 되었으나 시스템 미등록!\n"
                            f"수동 확인 필요!"
                        )
                    raise  # 상위로 예외 전파

                # 11. V6.2-A: 진입 즉시 트레일링 스탑 초기화
                if self._on_buy_filled_callback:
                    try:
                        initial_ts = await self._on_buy_filled_callback(stock_code, actual_price)
                        if initial_ts > 0:
                            self._logger.info(
                                f"[V6.2-A] 진입 시 TS 초기화 완료: {stock_code}",
                                entry_price=actual_price,
                                trailing_stop=initial_ts,
                            )
                        else:
                            # V6.2-A Phase 4: TS 0 또는 음수 - fallback 적용
                            fallback_ts = int(actual_price * 0.96)  # -4% 고정손절 수준
                            self._logger.warning(
                                f"[V6.2-A] TS 초기화 실패 (값={initial_ts}), fallback 적용: {stock_code}",
                                entry_price=actual_price,
                                fallback_ts=fallback_ts,
                            )
                            # RiskManager에 fallback TS 설정
                            self._risk_manager.set_trailing_stop_price(stock_code, fallback_ts)
                            # V6.2-A 코드리뷰 C2: fallback 상태 플래그 설정
                            self._risk_manager.set_ts_fallback(stock_code, True)
                    except Exception as ts_err:
                        # V6.2-A Phase 4: 예외 시 fallback + 알림
                        fallback_ts = int(actual_price * 0.96)
                        self._logger.error(
                            f"[V6.2-A] TS 초기화 예외, fallback 적용: {stock_code}",
                            error=str(ts_err),
                            entry_price=actual_price,
                            fallback_ts=fallback_ts,
                        )
                        self._risk_manager.set_trailing_stop_price(stock_code, fallback_ts)
                        # V6.2-A 코드리뷰 C2: fallback 상태 플래그 설정
                        self._risk_manager.set_ts_fallback(stock_code, True)
                        if self._telegram:
                            await self._telegram.send_message(
                                f"⚠️ TS 초기화 실패\n\n"
                                f"📌 {signal.stock_name} ({stock_code})\n"
                                f"💰 진입가: {actual_price:,}원\n"
                                f"🛡️ Fallback TS: {fallback_ts:,}원 (-4%)\n"
                                f"❌ 오류: {str(ts_err)[:50]}"
                            )

                # PRD v3.2: 시스템 매수 쿨다운 기록 (모든 종목 신규 매수 금지)
                self.set_system_buy_cooldown()

                # V6.2-A: 쿨다운 해제 후 신호 큐 처리 스케줄링
                # - 대기 중인 신호가 있으면 쿨다운 해제 시점에 처리
                if self._on_cooldown_expired_callback:
                    # Task 참조 저장 (종료 시 취소용)
                    self._queue_processing_task = asyncio.create_task(
                        self._schedule_signal_queue_processing()
                    )

                return True

            except Exception as e:
                self._logger.error(f"매수 주문 에러: {e}")
                self.stats["orders_failed"] += 1
                return False

            finally:
                # V6.2-A D1: correlation_id 컨텍스트 해제
                unbind_context("correlation_id")

        finally:
            lock.release()
