"""
Phase 3 리팩토링: PositionSyncManager

HTS 매수/매도 감지 및 포지션 동기화를 담당합니다.
TradingEngine에서 분리되어 독립적으로 동작합니다.

책임:
- API 잔고와 로컬 포지션 비교
- HTS 매수 감지 → 포지션 등록
- HTS 매도 감지 → 포지션 청산
- 수량 변동 감지 → 동기화
- Tier 1 일관성 검증
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
import asyncio
import logging

from src.core.exit_manager import ExitReason
from src.core.position_manager import Position
from src.core.realtime_data_manager import Tier
from src.core.signal_detector import StrategyType


@dataclass
class PositionInfo:
    """API 포지션 정보"""
    stock_code: str
    stock_name: str
    quantity: int
    average_price: int


@dataclass
class SyncCallbacks:
    """
    PositionSyncManager 콜백 인터페이스

    TradingEngine과의 의존성을 콜백으로 분리합니다.
    """
    # 포지션 관리
    open_position: Optional[Callable[..., Awaitable]] = None
    close_position: Optional[Callable[..., Awaitable]] = None
    get_position: Optional[Callable[[str], Optional[Position]]] = None
    get_all_positions: Optional[Callable[[], List[Position]]] = None
    get_position_codes: Optional[Callable[[], List[str]]] = None
    update_quantity: Optional[Callable[[str, int], None]] = None
    update_entry_price: Optional[Callable[[str, int, str], None]] = None

    # Risk 관리
    on_risk_entry: Optional[Callable[..., None]] = None
    on_risk_exit: Optional[Callable[..., None]] = None
    sync_quantity: Optional[Callable[[str, int], None]] = None
    sync_entry_price: Optional[Callable[[str, int, bool], bool]] = None
    is_partial_exited: Optional[Callable[[str], bool]] = None
    get_position_risk: Optional[Callable[[str], Any]] = None

    # 인프라
    add_candle_stock: Optional[Callable[[str], None]] = None
    add_universe_stock: Optional[Callable[[str, str, dict], None]] = None
    is_in_universe: Optional[Callable[[str], bool]] = None
    register_tier1: Optional[Callable[[str, str], None]] = None
    is_tier1: Optional[Callable[[str], bool]] = None

    # 주문 상태
    is_ordering_stock: Optional[Callable[[str], bool]] = None

    # V7 Exit State
    initialize_v7_state: Optional[Callable[..., Any]] = None
    register_position_strategy: Optional[Callable[[str, str], None]] = None

    # 트레일링 스탑
    init_ts_fallback: Optional[Callable[..., Awaitable]] = None
    init_trailing_stop_partial: Optional[Callable[..., Awaitable]] = None

    # DB
    close_trade: Optional[Callable[..., Awaitable]] = None
    update_partial_exit: Optional[Callable[..., Awaitable]] = None

    # 알림
    send_telegram: Optional[Callable[[str], Awaitable]] = None


@dataclass
class SyncResult:
    """동기화 결과"""
    new_positions: int = 0  # HTS 매수 감지
    closed_positions: int = 0  # HTS 매도 감지
    quantity_changes: int = 0  # 수량 변동
    tier1_recovered: int = 0  # Tier 1 복구
    errors: List[str] = field(default_factory=list)


class PositionSyncManager:
    """
    포지션 동기화 관리자

    API 잔고와 로컬 포지션을 비교하여 HTS 매매를 감지하고
    포지션을 동기화합니다.

    사용 예:
        sync_manager = PositionSyncManager()
        callbacks = SyncCallbacks(
            open_position=engine._position_manager.open_position,
            ...
        )
        await sync_manager.sync_positions(callbacks)
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        sync_interval: int = 60,
    ):
        """
        Args:
            logger: 로거 (None이면 기본 로거 사용)
            sync_interval: 동기화 간격 (초)
        """
        self._logger = logger or logging.getLogger(__name__)
        self._sync_interval = sync_interval

        # 통계
        self._stats = {
            "total_syncs": 0,
            "hts_buys_detected": 0,
            "hts_sells_detected": 0,
            "quantity_changes": 0,
            "tier1_recovered": 0,
            "errors": 0,
        }

        # 동기화 루프 상태
        self._running = False
        self._sync_task: Optional[asyncio.Task] = None

    async def reconcile_with_api_balance(
        self,
        api_positions: List[PositionInfo],
        callbacks: SyncCallbacks,
    ) -> SyncResult:
        """
        API 잔고와 포지션 대조 (PRD v3.0)

        DB 복구 후 API 실제 잔고와 비교하여:
        - DB에 없는 HTS 매수 → 알림 (실제 처리는 sync_positions에서)
        - API에 없는 DB 포지션 → 경고 알림
        - 수량 불일치 → 동기화

        Args:
            api_positions: API에서 조회한 포지션 목록
            callbacks: 콜백 인터페이스

        Returns:
            SyncResult: 동기화 결과
        """
        result = SyncResult()

        try:
            # API 포지션 맵 생성
            api_holdings = {
                p.stock_code: p for p in api_positions if p.quantity > 0
            }

            # 현재 로컬 포지션 코드
            current_positions = set()
            if callbacks.get_all_positions:
                current_positions = {
                    p.stock_code for p in callbacks.get_all_positions()
                }

            # 1. API에 있지만 포지션에 없는 종목 (HTS 매수) - 알림만
            for code, info in api_holdings.items():
                if code not in current_positions:
                    self._logger.warning(
                        f"[API 불일치] HTS 매수 감지: {info.stock_name}({code}) "
                        f"수량={info.quantity}, 평균가={info.average_price:,}원"
                    )
                    if callbacks.send_telegram:
                        await callbacks.send_telegram(
                            f"⚠️ 시스템 재시작 시 HTS 보유 감지\n\n"
                            f"📌 {info.stock_name}({code})\n"
                            f"📊 수량: {info.quantity}주\n"
                            f"💰 평균가: {info.average_price:,}원\n\n"
                            f"1분 내 자동 동기화 예정"
                        )
                    result.new_positions += 1

            # 2. 포지션에 있지만 API에 없는 종목 (HTS 매도됨) - 알림만
            for code in current_positions:
                if code not in api_holdings:
                    position = None
                    if callbacks.get_position:
                        position = callbacks.get_position(code)
                    if position:
                        self._logger.warning(
                            f"[API 불일치] HTS 매도 감지: {position.stock_name}({code})"
                        )
                        if callbacks.send_telegram:
                            await callbacks.send_telegram(
                                f"⚠️ 시스템 재시작 시 HTS 매도 감지\n\n"
                                f"📌 {position.stock_name}({code})\n"
                                f"⚠️ DB에는 보유 중이나 API 잔고 없음\n\n"
                                f"1분 내 자동 동기화 예정"
                            )
                        result.closed_positions += 1

            # 3. 양쪽에 있지만 수량 불일치 (부분 체결/HTS 매도)
            needs_trailing_stop_init = []

            for code in current_positions & set(api_holdings.keys()):
                position = None
                if callbacks.get_position:
                    position = callbacks.get_position(code)
                if position:
                    api_info = api_holdings[code]
                    api_qty = api_info.quantity
                    db_qty = position.quantity

                    if api_qty != db_qty:
                        self._logger.warning(
                            f"[API 불일치] 수량 불일치: {position.stock_name}({code}) "
                            f"DB={db_qty}주, API={api_qty}주"
                        )

                        if api_qty > 0:
                            # 분할 익절 상태 변화 추적
                            was_partial_before = False
                            if callbacks.is_partial_exited:
                                was_partial_before = callbacks.is_partial_exited(code)

                            # 수량 업데이트
                            position.quantity = api_qty
                            if callbacks.sync_quantity:
                                callbacks.sync_quantity(code, api_qty)

                            # 분할 익절 상태 전환 확인
                            is_partial_now = False
                            if callbacks.is_partial_exited:
                                is_partial_now = callbacks.is_partial_exited(code)
                            if not was_partial_before and is_partial_now:
                                needs_trailing_stop_init.append(code)

                            if callbacks.send_telegram:
                                await callbacks.send_telegram(
                                    f"⚠️ 포지션 수량 불일치 감지\n\n"
                                    f"📌 {position.stock_name}({code})\n"
                                    f"📊 DB 수량: {db_qty}주\n"
                                    f"📊 API 수량: {api_qty}주\n\n"
                                    f"✅ API 수량으로 동기화됨"
                                )
                            result.quantity_changes += 1

            # 분할 익절 상태로 전환된 종목들의 트레일링 스탑 초기화
            for code in needs_trailing_stop_init:
                if callbacks.init_trailing_stop_partial:
                    await callbacks.init_trailing_stop_partial(code)

        except Exception as e:
            self._logger.error(f"API 잔고 대조 실패: {e}")
            result.errors.append(str(e))
            self._stats["errors"] += 1

        return result

    async def sync_positions(
        self,
        api_positions: List[PositionInfo],
        callbacks: SyncCallbacks,
    ) -> SyncResult:
        """
        API와 포지션 동기화 (PRD v2.0: HTS 매매 감지)

        - HTS 매수 감지: 로컬에 없지만 API에 있음 → 포지션 등록 + 알림
        - HTS 매도 감지: 로컬에 있지만 API에 없음 → 포지션 청산 + 알림
        - 수량 변동 감지: 수량이 다르면 동기화

        Args:
            api_positions: API에서 조회한 포지션 목록
            callbacks: 콜백 인터페이스

        Returns:
            SyncResult: 동기화 결과
        """
        result = SyncResult()
        self._stats["total_syncs"] += 1

        try:
            # API 포지션 맵 생성
            api_codes = {p.stock_code for p in api_positions}
            api_positions_map = {p.stock_code: p for p in api_positions}

            # 로컬 포지션 코드
            local_codes = set()
            if callbacks.get_position_codes:
                local_codes = set(callbacks.get_position_codes())

            # 주문 진행 중인 종목 제외 (C-06: 주문/동기화 Lock 충돌 방지)
            ordering_codes = set()
            if callbacks.is_ordering_stock:
                ordering_codes = {c for c in (api_codes | local_codes) if callbacks.is_ordering_stock(c)}
                if ordering_codes:
                    self._logger.debug(f"주문 진행 중 동기화 스킵: {ordering_codes}")

            # ============================================
            # 1. HTS 매수 감지 (API에 있지만 로컬에 없음)
            # ============================================
            new_codes = api_codes - local_codes - ordering_codes
            for code in new_codes:
                pos = api_positions_map[code]
                self._logger.info(
                    f"HTS 매수 감지: {pos.stock_name}({code}) {pos.quantity}주"
                )

                try:
                    await self._handle_hts_buy(code, pos, callbacks)
                    result.new_positions += 1
                    self._stats["hts_buys_detected"] += 1

                except ValueError as e:
                    # 이미 포지션 존재 시 Tier 1 등록만
                    self._logger.warning(
                        f"HTS 포지션 등록 스킵 (이미 존재): {code} - {e}"
                    )
                    if callbacks.register_tier1:
                        callbacks.register_tier1(code, pos.stock_name)

                except Exception as e:
                    self._logger.error(f"HTS 포지션 등록 실패: {code} - {e}")
                    result.errors.append(f"{code}: {e}")
                    # 실패해도 Tier 1 등록 시도
                    try:
                        if callbacks.register_tier1:
                            callbacks.register_tier1(code, pos.stock_name)
                    except Exception:
                        pass

            # ============================================
            # 2. HTS 매도 감지 (로컬에 있지만 API에 없음)
            # ============================================
            sold_codes = local_codes - api_codes - ordering_codes
            for code in sold_codes:
                position = None
                if callbacks.get_position:
                    position = callbacks.get_position(code)
                if position is None:
                    continue

                self._logger.info(
                    f"HTS 매도 감지: {position.stock_name}({code})"
                )

                await self._handle_hts_sell(code, position, callbacks)
                result.closed_positions += 1
                self._stats["hts_sells_detected"] += 1

            # ============================================
            # 3. 수량 변동 감지
            # ============================================
            common_codes = api_codes & local_codes
            needs_trailing_stop_init = []

            for code in common_codes:
                pos = api_positions_map[code]
                local_pos = None
                if callbacks.get_position:
                    local_pos = callbacks.get_position(code)

                if local_pos and local_pos.quantity != pos.quantity:
                    old_qty = local_pos.quantity
                    new_qty = pos.quantity

                    if new_qty > old_qty:
                        # 수량 증가 = 추가 매수
                        await self._handle_quantity_increase(
                            code, pos, local_pos, old_qty, new_qty, callbacks
                        )
                    else:
                        # 수량 감소 = 부분 매도
                        needs_ts_init = await self._handle_quantity_decrease(
                            code, pos, local_pos, old_qty, new_qty, callbacks
                        )
                        if needs_ts_init:
                            needs_trailing_stop_init.append(code)

                    # 수량 동기화
                    if callbacks.update_quantity:
                        callbacks.update_quantity(code, pos.quantity)

                    result.quantity_changes += 1
                    self._stats["quantity_changes"] += 1

            # 분할 익절 상태로 전환된 종목들의 트레일링 스탑 초기화
            for code in needs_trailing_stop_init:
                if callbacks.init_trailing_stop_partial:
                    await callbacks.init_trailing_stop_partial(code)

            self._logger.debug(
                f"포지션 동기화 완료: API={len(api_codes)}, "
                f"신규={len(new_codes)}, 청산={len(sold_codes)}"
            )

        except Exception as e:
            self._logger.error(f"포지션 동기화 실패: {e}")
            result.errors.append(str(e))
            self._stats["errors"] += 1

        return result

    async def _handle_hts_buy(
        self,
        code: str,
        pos: PositionInfo,
        callbacks: SyncCallbacks,
    ) -> None:
        """HTS 매수 처리"""
        from src.core.position_manager import EntrySource

        # 1. 포지션 등록
        if callbacks.open_position:
            await callbacks.open_position(
                stock_code=code,
                stock_name=pos.stock_name,
                strategy=StrategyType.SNIPER_TRAP,  # HTS 매수
                entry_price=pos.average_price,
                quantity=pos.quantity,
                entry_source=EntrySource.HTS,
            )

        # 2. RiskManager 진입 처리
        if callbacks.on_risk_entry:
            from src.core.position_manager import EntrySource
            callbacks.on_risk_entry(
                code, pos.average_price, pos.quantity,
                entry_source=EntrySource.HTS,
            )

        # 3. 인프라 등록
        if callbacks.add_candle_stock:
            callbacks.add_candle_stock(code)

        if callbacks.is_in_universe and not callbacks.is_in_universe(code):
            if callbacks.add_universe_stock:
                callbacks.add_universe_stock(code, pos.stock_name, {"source": "hts"})

        if callbacks.register_tier1:
            callbacks.register_tier1(code, pos.stock_name)

        # 4. ATR 트레일링 스탑 초기화 시도
        trailing_stop_price = None
        try:
            if callbacks.get_position:
                position = callbacks.get_position(code)
                if position and callbacks.init_ts_fallback:
                    await callbacks.init_ts_fallback(code, position)
                    if callbacks.get_position_risk:
                        position_risk = callbacks.get_position_risk(code)
                        if position_risk and hasattr(position_risk, 'trailing_stop_price'):
                            trailing_stop_price = position_risk.trailing_stop_price
        except Exception as ts_err:
            self._logger.warning(
                f"HTS ATR TS 초기화 실패 (fallback -4% 사용): {code} - {ts_err}"
            )

        # 5.0 포지션-전략 매핑 등록 (V7 Exit 라우팅용 - Exit State 생성 전 필요)
        if callbacks.register_position_strategy:
            callbacks.register_position_strategy(code, "V7_PURPLE_REABS")
            self._logger.info(f"[V7.0] HTS 매수 전략 매핑: {code} -> V7_PURPLE_REABS")

        # 5. V7 Exit State 생성
        if callbacks.initialize_v7_state:
            exit_state = callbacks.initialize_v7_state(
                stock_code=code,
                entry_price=pos.average_price,
                entry_date=datetime.now(),
            )
            if exit_state:
                self._logger.info(
                    f"[V7.0] HTS 매수 Exit State 생성: {code} | "
                    f"entry={pos.average_price:,} | "
                    f"fallback_stop={exit_state.get_fallback_stop():,} (-4%)"
                )

        # 6. 텔레그램 알림
        if callbacks.send_telegram:
            safety_net_price = int(pos.average_price * 0.96)  # -4%
            if trailing_stop_price and trailing_stop_price > safety_net_price:
                ts_display = f"🛡️ ATR 손절가: {trailing_stop_price:,}원"
            else:
                ts_display = f"🛡️ 손절가: {safety_net_price:,}원 (-4%)"

            await callbacks.send_telegram(
                f"🔔 HTS 매수 감지\n\n"
                f"📌 {pos.stock_name}({code})\n"
                f"💰 {pos.quantity:,}주 × {pos.average_price:,}원\n"
                f"{ts_display}\n"
                f"📊 시스템 모니터링 시작"
            )

    async def _handle_hts_sell(
        self,
        code: str,
        position: Position,
        callbacks: SyncCallbacks,
    ) -> None:
        """HTS 매도 처리"""
        # 청산 가격 (현재가 또는 진입가)
        exit_price = position.current_price or position.entry_price

        # 1. 포지션 청산
        if callbacks.close_position:
            await callbacks.close_position(code, exit_price, "HTS 직접 매도")

        # 2. RiskManager 청산 처리
        if callbacks.on_risk_exit:
            callbacks.on_risk_exit(code, exit_price, ExitReason.MANUAL)

        # 3. DB 동기화
        trade_id = position.signal_metadata.get("trade_id") if position.signal_metadata else None
        if trade_id and callbacks.close_trade:
            try:
                await callbacks.close_trade(
                    trade_id=trade_id,
                    exit_price=exit_price,
                    exit_order_no="HTS",
                    exit_reason=ExitReason.MANUAL.value,
                )
                self._logger.info(f"HTS 매도 DB 업데이트: {code}, trade_id={trade_id}")
            except Exception as e:
                self._logger.warning(f"HTS 매도 DB 업데이트 실패: {code}, {e}")

        # 4. 텔레그램 알림
        if callbacks.send_telegram:
            pnl = (exit_price - position.entry_price) * position.quantity
            pnl_rate = (
                ((exit_price - position.entry_price) / position.entry_price) * 100
                if position.entry_price else 0
            )
            pnl_emoji = "📈" if pnl >= 0 else "📉"

            await callbacks.send_telegram(
                f"🔔 HTS 매도 감지\n\n"
                f"📌 {position.stock_name}({code})\n"
                f"💰 {position.quantity:,}주\n"
                f"{pnl_emoji} 추정 손익: {pnl:+,}원 ({pnl_rate:+.2f}%)\n"
                f"📊 시스템 모니터링 종료"
            )

    async def _handle_quantity_increase(
        self,
        code: str,
        pos: PositionInfo,
        local_pos: Position,
        old_qty: int,
        new_qty: int,
        callbacks: SyncCallbacks,
    ) -> None:
        """수량 증가 (추가 매수) 처리"""
        api_avg_price = pos.average_price
        local_entry_price = local_pos.entry_price

        if api_avg_price > 0 and api_avg_price != local_entry_price:
            # 1. 평균단가 갱신
            if callbacks.update_entry_price:
                callbacks.update_entry_price(code, api_avg_price, "HTS 추가 매수")

            # 2. RiskManager 동기화 + TS 리셋
            trailing_stop_after_reinit = None
            if callbacks.sync_entry_price:
                needs_ts_reinit = callbacks.sync_entry_price(
                    code, api_avg_price, True  # reset_trailing_stop=True
                )

                if needs_ts_reinit and callbacks.init_trailing_stop_partial:
                    try:
                        await callbacks.init_trailing_stop_partial(code)
                        if callbacks.get_position_risk:
                            position_risk = callbacks.get_position_risk(code)
                            if position_risk:
                                trailing_stop_after_reinit = position_risk.trailing_stop_price
                        self._logger.info(
                            f"[추가 매수] 트레일링 스탑 즉시 재초기화 완료: {code}"
                        )
                    except Exception as e:
                        self._logger.warning(
                            f"[추가 매수] 트레일링 스탑 재초기화 실패: {code} - {e}"
                        )

            # 3. 텔레그램 알림
            if callbacks.send_telegram:
                new_safety_net = int(api_avg_price * 0.96)
                if trailing_stop_after_reinit and trailing_stop_after_reinit < new_safety_net:
                    ts_display = f"🛡️ ATR 손절가: {trailing_stop_after_reinit:,}원"
                else:
                    ts_display = f"🛡️ 손절가: {new_safety_net:,}원 (-4%)"

                await callbacks.send_telegram(
                    f"📊 추가 매수 감지\n\n"
                    f"📌 {pos.stock_name}({code})\n"
                    f"📈 수량: {old_qty}주 → {new_qty}주\n"
                    f"💰 평균단가: {local_entry_price:,}원 → {api_avg_price:,}원\n"
                    f"{ts_display}"
                )

            self._logger.info(
                f"추가 매수 동기화: {pos.stock_name}({code}) "
                f"{old_qty}주 → {new_qty}주, "
                f"평균단가 {local_entry_price:,}원 → {api_avg_price:,}원"
            )
        else:
            # 평균단가 동일 시 수량만 알림
            if callbacks.send_telegram:
                await callbacks.send_telegram(
                    f"🔄 추가 매수 감지\n\n"
                    f"📌 {pos.stock_name}({code})\n"
                    f"📈 수량: {old_qty}주 → {new_qty}주"
                )
            self._logger.info(
                f"추가 매수 (평균단가 동일): {pos.stock_name}({code}) "
                f"{old_qty}주 → {new_qty}주"
            )

    async def _handle_quantity_decrease(
        self,
        code: str,
        pos: PositionInfo,
        local_pos: Position,
        old_qty: int,
        new_qty: int,
        callbacks: SyncCallbacks,
    ) -> bool:
        """
        수량 감소 (부분 매도) 처리

        Returns:
            트레일링 스탑 초기화 필요 여부
        """
        needs_ts_init = False

        if callbacks.sync_quantity:
            # 분할 익절 상태 추적
            was_partial_before = False
            if callbacks.is_partial_exited:
                was_partial_before = callbacks.is_partial_exited(code)

            callbacks.sync_quantity(code, pos.quantity)

            is_partial_now = False
            if callbacks.is_partial_exited:
                is_partial_now = callbacks.is_partial_exited(code)

            # 분할 익절 상태 전환 시 트레일링 스탑 초기화 필요
            if not was_partial_before and is_partial_now:
                needs_ts_init = True
                self._logger.info(f"[수량 기반 복구] 트레일링 스탑 초기화 예약: {code}")

                # DB 동기화
                trade_id = local_pos.signal_metadata.get("trade_id") if local_pos.signal_metadata else None
                if trade_id and callbacks.update_partial_exit:
                    try:
                        highest = local_pos.current_price
                        if callbacks.get_position_risk:
                            position_risk = callbacks.get_position_risk(code)
                            if position_risk:
                                highest = position_risk.highest_price

                        await callbacks.update_partial_exit(
                            trade_id=trade_id,
                            new_stop_loss_price=local_pos.entry_price,
                            highest_price=highest,
                        )
                        self._logger.info(f"분할 익절 DB 동기화: {code}, trade_id={trade_id}")
                    except Exception as e:
                        self._logger.warning(f"분할 익절 DB 동기화 실패: {code}, {e}")

        self._logger.info(
            f"수량 감소 동기화: {pos.stock_name}({code}) "
            f"{old_qty}주 → {new_qty}주"
        )

        if callbacks.send_telegram:
            await callbacks.send_telegram(
                f"🔄 수량 감소 감지\n\n"
                f"📌 {pos.stock_name}({code})\n"
                f"📉 수량: {old_qty}주 → {new_qty}주"
            )

        return needs_ts_init

    async def verify_tier1_consistency(
        self,
        callbacks: SyncCallbacks,
    ) -> int:
        """
        V6.2-J: 포지션과 Tier 1 등록 일관성 검증

        PositionManager에 있는 모든 포지션이 Tier 1에 등록되어 있는지 확인하고,
        미등록된 포지션은 즉시 Tier 1에 등록합니다.

        Returns:
            복구된 종목 수
        """
        recovered_count = 0

        if not callbacks.get_all_positions or not callbacks.is_tier1:
            return recovered_count

        for position in callbacks.get_all_positions():
            if not callbacks.is_tier1(position.stock_code):
                self._logger.error(
                    f"[CRITICAL] Tier 1 미등록 포지션 발견: "
                    f"{position.stock_name}({position.stock_code})"
                )

                # 즉시 Tier 1 등록
                if callbacks.register_tier1:
                    callbacks.register_tier1(position.stock_code, position.stock_name)
                recovered_count += 1
                self._stats["tier1_recovered"] += 1

                # 텔레그램 알림
                if callbacks.send_telegram:
                    try:
                        await callbacks.send_telegram(
                            f"⚠️ Tier 1 미등록 포지션 자동 복구\n\n"
                            f"📌 {position.stock_name}({position.stock_code})\n"
                            f"💰 보유: {position.quantity:,}주\n"
                            f"📊 가격 모니터링 재개됨"
                        )
                    except Exception:
                        pass

        if recovered_count > 0:
            self._logger.warning(
                f"[V6.2-J] Tier 1 일관성 검증: {recovered_count}개 포지션 복구됨"
            )

        return recovered_count

    # =========================================
    # 상태 조회
    # =========================================

    def get_stats(self) -> Dict[str, int]:
        """통계 반환"""
        return dict(self._stats)

    def get_status(self) -> Dict[str, Any]:
        """상태 반환"""
        return {
            "running": self._running,
            "sync_interval": self._sync_interval,
            "stats": self.get_stats(),
        }

    def __str__(self) -> str:
        return (
            f"PositionSyncManager("
            f"syncs={self._stats['total_syncs']}, "
            f"hts_buys={self._stats['hts_buys_detected']}, "
            f"hts_sells={self._stats['hts_sells_detected']}"
            f")"
        )
