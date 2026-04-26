"""
수동 매매 명령어 핸들러 (Phase 6D)

TradingEngine에서 수동 종목 관리/매매 로직을 분리합니다.

주요 기능:
- 수동 종목 추가/제거 (PRD REQ-003~005)
- 수동 매수/매도 (PRD REQ-006~007)
- 손절/익절/모드 설정 (PRD REQ-008~009)
- ignore 목록 관리 (V6.2-A C3)
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Set, Callable, Awaitable, Any

from src.utils.logger import get_logger


class StockMode(str, Enum):
    """종목 감시 모드 (PRD REQ-009)"""
    AUTO = "auto"
    WATCH = "watch"


@dataclass
class ManualStockConfig:
    """수동 추가 종목 설정"""
    stock_code: str
    stock_name: str
    mode: StockMode
    added_at: datetime
    custom_stop_loss: Optional[float] = None
    custom_take_profit: Optional[float] = None


@dataclass
class ManualCommandCallbacks:
    """ManualCommandHandler가 필요로 하는 외부 의존성 콜백"""
    # 시장 API
    get_stock_name: Callable[[str], Awaitable[Optional[str]]]
    get_current_price: Callable[[str], Awaitable[Optional[int]]]
    # 유니버스
    is_in_universe: Callable[[str], bool]
    add_to_universe: Callable[..., None]
    remove_from_universe: Callable[[str], None]
    get_universe_stock: Callable[[str], Any]
    get_universe_stocks: Callable[[], list]
    # 캔들
    add_candle_stock: Callable[[str], None]
    get_candle_builder: Callable[[str], Any]
    remove_candle_stock: Callable[[str], None]
    # 데이터 매니저
    register_stock: Callable[..., None]
    unregister_stock: Callable[[str], None]
    promote_to_tier1: Callable[[str], Awaitable[Any]]
    is_tier1: Callable[[str], bool]
    get_price_data: Callable[[str], Any]
    # 포지션
    has_position: Callable[[str], bool]
    get_position: Callable[[str], Any]
    get_all_positions: Callable[[], list]
    # 매수 실행
    get_balance: Callable[[], Awaitable[Any]]
    buy_order: Callable[..., Awaitable[Any]]
    wait_for_execution: Callable[..., Awaitable[Any]]
    # 리스크/포지션 등록
    on_entry: Callable[..., None]
    open_position: Callable[..., Awaitable[None]]
    set_trailing_stop_price: Callable[[str, int], None]
    set_ts_fallback: Callable[[str, bool], None]
    # 매도
    execute_manual_sell: Optional[Callable[..., Awaitable[tuple]]]
    # ATR
    initialize_trailing_stop: Optional[Callable[..., Awaitable[int]]]
    unregister_atr_alert: Callable[[str], None]
    # 상태
    is_regular_trading_hours: Callable[[], bool]
    get_engine_state: Callable[[], str]


class ManualCommandHandler:
    """수동 매매 명령어 핸들러"""

    def __init__(
        self,
        callbacks: ManualCommandCallbacks,
        ignore_file_path: str = "data/ignore_stocks.json",
    ):
        self._cb = callbacks
        self._logger = get_logger(__name__)
        self._manual_stocks: Dict[str, ManualStockConfig] = {}
        self._ignore_stocks: Set[str] = set()
        self._ignore_file_path = ignore_file_path
        self._load_ignore_stocks()

    @property
    def manual_stocks(self) -> Dict[str, ManualStockConfig]:
        return self._manual_stocks

    @property
    def ignore_stocks(self) -> Set[str]:
        return self._ignore_stocks

    # =========================================
    # 수동 종목 관리 (PRD REQ-003~005)
    # =========================================

    async def add_manual_stock(
        self,
        stock_code: str,
        mode: str = "auto",
    ) -> tuple:
        """수동 종목 추가 (PRD REQ-003)"""
        try:
            stock_name = await self._cb.get_stock_name(stock_code)
            if not stock_name or stock_name == stock_code:
                current_price = await self._cb.get_current_price(stock_code)
                if current_price is None or current_price <= 0:
                    return False, f"종목코드 {stock_code}를 찾을 수 없습니다"
                stock_name = stock_code

            if self._cb.is_in_universe(stock_code):
                return False, f"{stock_name}({stock_code})는 이미 감시 중입니다"

            stock_mode = StockMode.AUTO if mode.lower() == "auto" else StockMode.WATCH

            self._cb.add_to_universe(
                stock_code=stock_code,
                stock_name=stock_name,
                metadata={"source": "manual", "mode": stock_mode.value},
                manual=True,
            )

            if self._cb.get_candle_builder(stock_code) is None:
                self._cb.add_candle_stock(stock_code)

            from src.core.realtime_data_manager import Tier
            self._cb.register_stock(stock_code, Tier.TIER_1, stock_name)
            await self._cb.promote_to_tier1(stock_code)

            self._manual_stocks[stock_code] = ManualStockConfig(
                stock_code=stock_code,
                stock_name=stock_name,
                mode=stock_mode,
                added_at=datetime.now(),
            )

            mode_text = "자동매수" if stock_mode == StockMode.AUTO else "감시만"
            self._logger.info(f"수동 종목 추가: {stock_name}({stock_code}), 모드={mode_text}")

            return True, f"✅ {stock_name}({stock_code}) 감시 시작\n모드: {mode_text}"

        except Exception as e:
            self._logger.error(f"수동 종목 추가 실패: {stock_code} - {e}")
            return False, f"종목 추가 실패: {e}"

    async def remove_manual_stock(
        self,
        stock_code: str,
        force: bool = False,
    ) -> tuple:
        """종목 제거 (PRD REQ-004)"""
        if not self._cb.is_in_universe(stock_code):
            return False, f"종목코드 {stock_code}는 감시 중이 아닙니다"

        stock_name = self._cb.get_universe_stock(stock_code).stock_name

        position = self._cb.get_position(stock_code)
        if position and not force:
            return False, (
                f"⚠️ {stock_name}({stock_code})를 {position.quantity}주 보유 중입니다.\n"
                f"청산 후 제거하려면 /sell {stock_code} 전량 명령을 먼저 실행하세요."
            )

        self._cb.remove_from_universe(stock_code)
        self._cb.remove_candle_stock(stock_code)
        self._cb.unregister_stock(stock_code)
        self._manual_stocks.pop(stock_code, None)
        self._cb.unregister_atr_alert(stock_code)

        self._logger.info(f"종목 제거: {stock_name}({stock_code})")
        return True, f"✅ {stock_name}({stock_code}) 감시 종료"

    def get_watched_stocks_text(self, filter_type: str = "all") -> str:
        """감시 종목 목록 텍스트 (PRD REQ-005)"""
        stocks = []

        for stock in self._cb.get_universe_stocks():
            code = stock.stock_code
            name = stock.stock_name
            position = self._cb.get_position(code)
            price_data = self._cb.get_price_data(code)
            manual_config = self._manual_stocks.get(code)

            if filter_type == "holding" and not position:
                continue
            if filter_type == "active" and not self._cb.is_tier1(code):
                continue

            if position:
                status_emoji = "🟡"
                status_text = "보유중"
            elif self._cb.is_tier1(code):
                status_emoji = "🟢"
                status_text = "감시중"
            else:
                status_emoji = "🔵"
                status_text = "대기"

            if manual_config:
                mode_text = "자동매수" if manual_config.mode == StockMode.AUTO else "감시만"
            else:
                mode_text = "조건식"

            if price_data:
                price_text = f"{price_data.current_price:,}원"
                if price_data.change_rate:
                    sign = "+" if price_data.change_rate >= 0 else ""
                    price_text += f" ({sign}{price_data.change_rate:.1f}%)"
            else:
                price_text = "가격 미확인"

            stock_info = {
                "code": code,
                "name": name,
                "status_emoji": status_emoji,
                "status_text": status_text,
                "mode": mode_text,
                "price": price_text,
                "position": position,
            }
            stocks.append(stock_info)

        if not stocks:
            return "📋 감시 중인 종목이 없습니다."

        lines = [f"📋 감시 종목 ({len(stocks)}개)\n"]

        for i, s in enumerate(stocks, 1):
            lines.append(f"{i}. {s['name']} ({s['code']})")
            lines.append(f"   상태: {s['status_emoji']} {s['status_text']} | 모드: {s['mode']}")
            lines.append(f"   현재가: {s['price']}")

            if s['position']:
                pos = s['position']
                pnl_sign = "+" if pos.profit_loss_rate >= 0 else ""
                lines.append(
                    f"   보유: {pos.quantity}주 ({pos.invested_amount:,}원) "
                    f"[{pnl_sign}{pos.profit_loss_rate:.1f}%]"
                )
            lines.append("")

        return "\n".join(lines)

    # =========================================
    # 수동 매매 (PRD REQ-006~007)
    # =========================================

    async def execute_manual_buy(
        self,
        stock_code: str,
        amount: int,
    ) -> tuple:
        """수동 매수 실행 (PRD REQ-006)"""
        try:
            if not self._cb.is_regular_trading_hours():
                return False, "❌ 정규장(09:00~15:20) 시간이 아닙니다. NXT 애프터마켓에서는 청산만 가능합니다."

            engine_state = self._cb.get_engine_state()
            if engine_state not in ("RUNNING", "PAUSED"):
                return False, f"❌ 엔진이 실행 중이 아닙니다 (상태: {engine_state})"

            stock_name = await self._cb.get_stock_name(stock_code)
            if not stock_name:
                stock_name = stock_code

            balance = await self._cb.get_balance()
            available = balance.available_amount

            if available < amount:
                return False, (
                    f"❌ 잔고 부족\n"
                    f"가용: {available:,}원\n"
                    f"필요: {amount:,}원"
                )

            current_price = await self._cb.get_current_price(stock_code)
            if not current_price or current_price <= 0:
                return False, f"❌ 현재가 조회 실패: {stock_code}"

            quantity = amount // current_price
            if quantity < 1:
                return False, f"❌ 매수 금액이 1주 가격보다 적습니다 (현재가: {current_price:,}원)"

            self._logger.info(
                f"수동 매수 주문: {stock_name}({stock_code})",
                quantity=quantity,
                price=current_price,
            )

            from src.api.endpoints.order import OrderType
            result = await self._cb.buy_order(
                stock_code=stock_code,
                quantity=quantity,
                order_type=OrderType.MARKET,
            )

            if not result.success:
                return False, f"❌ 매수 주문 실패: {result.message}"

            from src.core.trading_engine import TradingConstants
            execution = await self._cb.wait_for_execution(
                order_no=result.order_no,
                stock_code=stock_code,
                max_wait_seconds=TradingConstants.EXECUTION_WAIT_SECONDS,
            )

            if execution is None or execution.filled_qty == 0:
                return False, f"❌ 체결 타임아웃 (주문번호: {result.order_no})"

            actual_price = execution.filled_price
            actual_qty = execution.filled_qty

            from src.core.position_manager import EntrySource
            from src.core.signal_detector import StrategyType
            self._cb.on_entry(
                stock_code, actual_price, actual_qty,
                entry_source=EntrySource.MANUAL,
            )

            await self._cb.open_position(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy=StrategyType.SNIPER_TRAP,
                entry_price=actual_price,
                quantity=actual_qty,
                order_no=result.order_no,
                signal_metadata={"source": "manual_buy"},
                entry_source=EntrySource.MANUAL,
            )

            if not self._cb.is_in_universe(stock_code):
                self._cb.add_to_universe(stock_code, stock_name, {"source": "manual"})
                self._cb.add_candle_stock(stock_code)
                from src.core.realtime_data_manager import Tier
                self._cb.register_stock(stock_code, Tier.TIER_1, stock_name)

            initial_ts = 0
            if self._cb.initialize_trailing_stop:
                try:
                    initial_ts = await self._cb.initialize_trailing_stop(
                        stock_code, actual_price
                    )
                    self._logger.info(
                        f"[수동매수] ATR TS 초기화: {stock_code}, "
                        f"진입가={actual_price:,}, TS={initial_ts:,}"
                    )
                except Exception as ts_err:
                    fallback_ts = int(actual_price * 0.96)
                    self._cb.set_trailing_stop_price(stock_code, fallback_ts)
                    self._cb.set_ts_fallback(stock_code, True)
                    self._logger.warning(
                        f"[수동매수] ATR TS 초기화 실패, fallback 적용: {stock_code}, "
                        f"TS={fallback_ts:,}, 에러={ts_err}"
                    )

            actual_amount = actual_price * actual_qty
            safety_net_price = int(actual_price * 0.96)
            return True, (
                f"✅ 매수 체결\n"
                f"종목: {stock_name}({stock_code})\n"
                f"수량: {actual_qty}주\n"
                f"단가: {actual_price:,}원\n"
                f"금액: {actual_amount:,}원\n"
                f"🛡️ 손절가: {safety_net_price:,}원 (-4%)"
            )

        except Exception as e:
            self._logger.error(f"수동 매수 실패: {stock_code} - {e}")
            return False, f"❌ 매수 실패: {e}"

    async def execute_manual_sell(
        self,
        stock_code: str,
        quantity: int,
    ) -> tuple:
        """수동 매도 실행 (PRD REQ-007)"""
        if self._cb.execute_manual_sell:
            return await self._cb.execute_manual_sell(stock_code, quantity)
        else:
            self._logger.warning(f"ExitManager 미초기화 - 수동 매도 스킵: {stock_code}")
            return False, "ExitManager 미초기화"

    # =========================================
    # 손절/익절/모드 설정 (PRD REQ-008~009)
    # =========================================

    async def update_stop_loss(
        self,
        stock_code: str,
        rate: float,
    ) -> tuple:
        """손절가 변경 (PRD REQ-008)"""
        position = self._cb.get_position(stock_code)
        if not position:
            return False, f"❌ {stock_code} 보유 포지션이 없습니다"

        if stock_code in self._manual_stocks:
            self._manual_stocks[stock_code].custom_stop_loss = rate
        else:
            self._manual_stocks[stock_code] = ManualStockConfig(
                stock_code=stock_code,
                stock_name=position.stock_name,
                mode=StockMode.AUTO,
                added_at=datetime.now(),
                custom_stop_loss=rate,
            )

        stop_price = int(position.entry_price * (1 + rate))
        rate_pct = rate * 100

        self._logger.info(f"손절가 변경: {stock_code} -> {rate_pct:.1f}% ({stop_price:,}원)")

        return True, (
            f"✅ 손절가 변경\n"
            f"종목: {position.stock_name}({stock_code})\n"
            f"평균가: {position.entry_price:,}원\n"
            f"손절: {rate_pct:.1f}% ({stop_price:,}원)"
        )

    async def update_take_profit(
        self,
        stock_code: str,
        rate: float,
    ) -> tuple:
        """익절가 변경 (PRD REQ-008)"""
        position = self._cb.get_position(stock_code)
        if not position:
            return False, f"❌ {stock_code} 보유 포지션이 없습니다"

        if stock_code in self._manual_stocks:
            self._manual_stocks[stock_code].custom_take_profit = rate
        else:
            self._manual_stocks[stock_code] = ManualStockConfig(
                stock_code=stock_code,
                stock_name=position.stock_name,
                mode=StockMode.AUTO,
                added_at=datetime.now(),
                custom_take_profit=rate,
            )

        target_price = int(position.entry_price * (1 + rate))
        rate_pct = rate * 100

        self._logger.info(f"익절가 변경: {stock_code} -> +{rate_pct:.1f}% ({target_price:,}원)")

        return True, (
            f"✅ 익절가 변경\n"
            f"종목: {position.stock_name}({stock_code})\n"
            f"평균가: {position.entry_price:,}원\n"
            f"익절: +{rate_pct:.1f}% ({target_price:,}원)"
        )

    async def update_stock_mode(
        self,
        stock_code: str,
        mode: str,
    ) -> tuple:
        """종목 모드 변경 (PRD REQ-009)"""
        if not self._cb.is_in_universe(stock_code):
            return False, f"❌ {stock_code}는 감시 중이 아닙니다"

        stock = self._cb.get_universe_stock(stock_code)
        stock_name = stock.stock_name

        new_mode = StockMode.AUTO if mode.lower() == "auto" else StockMode.WATCH

        if stock_code in self._manual_stocks:
            self._manual_stocks[stock_code].mode = new_mode
        else:
            self._manual_stocks[stock_code] = ManualStockConfig(
                stock_code=stock_code,
                stock_name=stock_name,
                mode=new_mode,
                added_at=datetime.now(),
            )

        mode_text = "자동매수" if new_mode == StockMode.AUTO else "감시만"
        self._logger.info(f"종목 모드 변경: {stock_name}({stock_code}) -> {mode_text}")

        return True, f"✅ {stock_name}({stock_code}): {mode_text} 모드"

    def get_stock_mode(self, stock_code: str) -> StockMode:
        """종목의 현재 모드 반환"""
        if stock_code in self._manual_stocks:
            return self._manual_stocks[stock_code].mode
        return StockMode.AUTO

    # =========================================
    # V6.2-A 코드리뷰 C3: /ignore 영속성
    # =========================================

    def _load_ignore_stocks(self) -> None:
        """ignore 목록 로드"""
        try:
            if os.path.exists(self._ignore_file_path):
                with open(self._ignore_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._ignore_stocks = set(data.get("stocks", []))
                    self._logger.info(
                        f"[C3] ignore 목록 로드: {len(self._ignore_stocks)}개 종목"
                    )
        except Exception as e:
            self._logger.warning(f"[C3] ignore 목록 로드 실패: {e}")
            self._ignore_stocks = set()

    def _save_ignore_stocks(self) -> None:
        """ignore 목록 저장"""
        try:
            os.makedirs(os.path.dirname(self._ignore_file_path), exist_ok=True)

            with open(self._ignore_file_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "stocks": list(self._ignore_stocks),
                    "updated_at": datetime.now().isoformat(),
                }, f, indent=2, ensure_ascii=False)

            self._logger.debug(
                f"[C3] ignore 목록 저장: {len(self._ignore_stocks)}개 종목"
            )
        except Exception as e:
            self._logger.error(f"[C3] ignore 목록 저장 실패: {e}")

    def add_ignore_stock(self, stock_code: str) -> bool:
        """ignore 목록에 종목 추가"""
        if stock_code in self._ignore_stocks:
            return False
        self._ignore_stocks.add(stock_code)
        self._save_ignore_stocks()
        return True

    def remove_ignore_stock(self, stock_code: str) -> bool:
        """ignore 목록에서 종목 제거"""
        if stock_code not in self._ignore_stocks:
            return False
        self._ignore_stocks.discard(stock_code)
        self._save_ignore_stocks()
        return True
