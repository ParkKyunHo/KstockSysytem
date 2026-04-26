"""
포지션 관리 모듈

보유 종목(포지션)의 실시간 추적 및 관리를 담당합니다.

기능:
- 포지션 상태 추적 (수익률, 최고가 등)
- 실시간 가격 업데이트
- 포지션 수량/가격 동기화 (API 조회)
- 포지션 이력 관리
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable, Awaitable, TYPE_CHECKING
from enum import Enum

from src.core.signal_detector import StrategyType
from src.database.models import EntrySource  # 중복 제거: models.py에서 import
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.core.risk_manager import RiskManager


class PositionStatus(str, Enum):
    """포지션 상태"""
    PENDING = "PENDING"         # 주문 대기
    OPEN = "OPEN"               # 보유 중
    CLOSING = "CLOSING"         # 청산 중
    CLOSED = "CLOSED"           # 청산 완료


# EntrySource는 src.database.models에서 import (Single Source of Truth)
# 기존 코드 호환성을 위해 re-export
__all__ = ["PositionStatus", "EntrySource", "Position", "PositionManager"]


@dataclass
class Position:
    """포지션 정보"""
    stock_code: str
    stock_name: str
    strategy: StrategyType          # 진입 전략
    status: PositionStatus
    entry_source: EntrySource       # 진입 출처 (MANUAL, SYSTEM, HTS, RESTORED)

    # 진입 정보
    entry_price: int                # 평균 매수가
    quantity: int                   # 보유 수량
    entry_time: datetime            # 진입 시간
    entry_order_no: str = ""        # 매수 주문번호

    # 실시간 정보
    current_price: int = 0          # 현재가
    highest_price: int = 0          # 보유 중 최고가
    lowest_price: int = 0           # 보유 중 최저가

    # 청산 정보
    exit_price: int = 0             # 청산가
    exit_time: Optional[datetime] = None
    exit_order_no: str = ""         # 매도 주문번호
    exit_reason: str = ""           # 청산 사유

    # 메타데이터
    signal_metadata: dict = field(default_factory=dict)

    # PRD v3.3: 분할 익절 상태 (RiskManager와 동기화)
    is_partial_exit: bool = False           # 분할 익절 완료 여부
    highest_price_after_partial: int = 0    # 분할 익절 후 최고가

    def __post_init__(self):
        if self.current_price == 0:
            self.current_price = self.entry_price
        if self.highest_price == 0:
            self.highest_price = self.entry_price
        if self.lowest_price == 0:
            self.lowest_price = self.entry_price

    @property
    def profit_loss(self) -> int:
        """평가 손익 (원)"""
        if self.status == PositionStatus.CLOSED:
            return (self.exit_price - self.entry_price) * self.quantity
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def profit_loss_rate(self) -> float:
        """수익률 (%)"""
        if self.entry_price == 0:
            return 0.0
        if self.status == PositionStatus.CLOSED:
            return ((self.exit_price - self.entry_price) / self.entry_price) * 100
        return ((self.current_price - self.entry_price) / self.entry_price) * 100

    @property
    def from_highest_rate(self) -> float:
        """고점 대비 하락률 (%)"""
        if self.highest_price == 0:
            return 0.0
        return ((self.current_price - self.highest_price) / self.highest_price) * 100

    @property
    def eval_amount(self) -> int:
        """평가 금액 (원)"""
        return self.current_price * self.quantity

    @property
    def invested_amount(self) -> int:
        """투자 금액 (원)"""
        return self.entry_price * self.quantity

    @property
    def holding_time(self) -> int:
        """보유 시간 (초)"""
        end_time = self.exit_time if self.exit_time else datetime.now()
        return int((end_time - self.entry_time).total_seconds())

    def update_price(self, price: int) -> None:
        """현재가 업데이트"""
        self.current_price = price
        if price > self.highest_price:
            self.highest_price = price
        if price < self.lowest_price:
            self.lowest_price = price

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "entry_source": self.entry_source.value,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "entry_time": self.entry_time.isoformat(),
            "current_price": self.current_price,
            "highest_price": self.highest_price,
            "profit_loss": self.profit_loss,
            "profit_loss_rate": self.profit_loss_rate,
            "holding_time": self.holding_time,
        }


# 콜백 타입
PositionUpdateCallback = Callable[[Position], Awaitable[None]]


class PositionManager:
    """
    포지션 관리자

    모든 보유 포지션의 상태를 추적하고 관리합니다.

    Usage:
        pm = PositionManager()
        pm.open_position(stock_code, stock_name, strategy, entry_price, quantity)
        pm.update_price(stock_code, current_price)
        pm.close_position(stock_code, exit_price, reason)
    """

    def __init__(self):
        self._logger = get_logger(__name__)

        # 활성 포지션
        self._positions: Dict[str, Position] = {}

        # 청산 이력 (당일)
        self._closed_positions: List[Position] = []

        # 콜백
        self.on_position_opened: Optional[PositionUpdateCallback] = None
        self.on_position_closed: Optional[PositionUpdateCallback] = None
        self.on_price_updated: Optional[PositionUpdateCallback] = None

        # RiskManager 참조 (수량 동기화용)
        self._risk_manager: Optional["RiskManager"] = None

    def set_risk_manager(self, risk_manager: "RiskManager") -> None:
        """
        RiskManager 참조 설정 (수량 동기화용)

        PositionManager와 RiskManager 간 수량 동기화를 위해 호출합니다.
        TradingEngine 초기화 시 설정해야 합니다.
        """
        self._risk_manager = risk_manager
        self._logger.debug("RiskManager 참조 설정 완료")

    # =========================================
    # 포지션 생성/수정/청산
    # =========================================

    async def open_position(
        self,
        stock_code: str,
        stock_name: str,
        strategy: StrategyType,
        entry_price: int,
        quantity: int,
        order_no: str = "",
        signal_metadata: Optional[dict] = None,
        entry_source: EntrySource = EntrySource.SYSTEM,
        is_partial_exit: bool = False,  # PRD v3.3: 분할 익절 상태 (DB 복구 시)
        highest_price_after_partial: int = 0,  # PRD v3.3: 분할 익절 후 최고가
    ) -> Position:
        """
        포지션 생성

        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            strategy: 진입 전략
            entry_price: 매수가
            quantity: 수량
            order_no: 주문번호
            signal_metadata: 신호 메타데이터
            entry_source: 진입 출처 (MANUAL, SYSTEM, HTS, RESTORED)
            is_partial_exit: 분할 익절 완료 여부 (DB 복구 시)
            highest_price_after_partial: 분할 익절 후 최고가 (DB 복구 시)

        Returns:
            생성된 Position

        Raises:
            ValueError: 이미 동일 종목 포지션이 존재하는 경우
        """
        # V6.2-A 안정성: 중복 포지션 덮어쓰기 방지
        if stock_code in self._positions:
            existing = self._positions[stock_code]
            self._logger.error(
                f"중복 포지션 방지: {stock_name}({stock_code}) 이미 존재",
                existing_qty=existing.quantity,
                existing_price=existing.entry_price,
                new_qty=quantity,
                new_price=entry_price,
            )
            raise ValueError(f"이미 포지션이 존재합니다: {stock_code}")

        position = Position(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy=strategy,
            status=PositionStatus.OPEN,
            entry_source=entry_source,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now(),
            entry_order_no=order_no,
            signal_metadata=signal_metadata or {},
            is_partial_exit=is_partial_exit,  # PRD v3.3
            highest_price_after_partial=highest_price_after_partial,  # PRD v3.3
        )

        self._positions[stock_code] = position

        self._logger.info(
            f"포지션 오픈: {stock_name}({stock_code})",
            strategy=strategy.value,
            entry_source=entry_source.value,
            entry_price=entry_price,
            quantity=quantity,
        )

        if self.on_position_opened:
            await self.on_position_opened(position)

        return position

    async def close_position(
        self,
        stock_code: str,
        exit_price: int,
        reason: str,
        order_no: str = "",
    ) -> Optional[Position]:
        """
        포지션 청산

        Args:
            stock_code: 종목 코드
            exit_price: 청산가
            reason: 청산 사유
            order_no: 주문번호

        Returns:
            청산된 Position
        """
        position = self._positions.get(stock_code)
        if position is None:
            self._logger.warning(f"청산할 포지션 없음: {stock_code}")
            return None

        # 상태 업데이트
        position.status = PositionStatus.CLOSED
        position.exit_price = exit_price
        position.exit_time = datetime.now()
        position.exit_order_no = order_no
        position.exit_reason = reason

        # 활성 포지션에서 제거
        del self._positions[stock_code]

        # 이력에 추가
        self._closed_positions.append(position)

        self._logger.info(
            f"포지션 청산: {position.stock_name}({stock_code})",
            reason=reason,
            exit_price=exit_price,
            pnl=position.profit_loss,
            pnl_rate=f"{position.profit_loss_rate:.2f}%",
            holding_time=f"{position.holding_time}초",
        )

        if self.on_position_closed:
            await self.on_position_closed(position)

        return position

    def update_price(self, stock_code: str, current_price: int) -> Optional[Position]:
        """
        현재가 업데이트

        Args:
            stock_code: 종목 코드
            current_price: 현재가

        Returns:
            업데이트된 Position
        """
        position = self._positions.get(stock_code)
        if position is None:
            return None

        position.update_price(current_price)
        return position

    async def update_price_async(
        self,
        stock_code: str,
        current_price: int,
    ) -> Optional[Position]:
        """비동기 현재가 업데이트 (콜백 포함)"""
        position = self.update_price(stock_code, current_price)

        if position and self.on_price_updated:
            await self.on_price_updated(position)

        return position

    def update_quantity(self, stock_code: str, quantity: int) -> None:
        """
        수량 업데이트 (부분 체결 등)

        V6.2-A 코드리뷰 B4: RiskManager 자동 동기화
        """
        position = self._positions.get(stock_code)
        if position:
            old_quantity = position.quantity
            position.quantity = quantity

            # V6.2-A 코드리뷰 B4: RiskManager 동기화
            if self._risk_manager and old_quantity != quantity:
                self._risk_manager.sync_quantity(stock_code, quantity)
                self._logger.debug(
                    f"수량 동기화: {stock_code} {old_quantity} -> {quantity}"
                )

    def update_entry_price(
        self,
        stock_code: str,
        new_entry_price: int,
        reason: str = "추가 매수",
    ) -> bool:
        """
        평균단가 업데이트 (HTS 추가 매수 대응)

        V6.3: 기존 entry_price를 새 average_price로 갱신합니다.
        RiskManager 동기화는 별도 호출 필요.

        Args:
            stock_code: 종목 코드
            new_entry_price: 새 평균단가 (API average_price)
            reason: 변경 사유

        Returns:
            갱신 성공 여부
        """
        position = self._positions.get(stock_code)
        if position is None:
            return False

        old_entry_price = position.entry_price
        if old_entry_price == new_entry_price:
            return False  # 변경 없음

        position.entry_price = new_entry_price

        self._logger.info(
            f"평균단가 업데이트: {stock_code}",
            old_entry_price=old_entry_price,
            new_entry_price=new_entry_price,
            reason=reason,
        )

        return True

    # =========================================
    # 조회
    # =========================================

    def get_position(self, stock_code: str) -> Optional[Position]:
        """포지션 조회"""
        return self._positions.get(stock_code)

    def has_position(self, stock_code: str) -> bool:
        """포지션 보유 여부"""
        return stock_code in self._positions

    def get_all_positions(self) -> List[Position]:
        """모든 활성 포지션"""
        return list(self._positions.values())

    def get_position_codes(self) -> List[str]:
        """보유 종목 코드 목록"""
        return list(self._positions.keys())

    def get_position_count(self) -> int:
        """보유 포지션 수"""
        return len(self._positions)

    def get_closed_positions(self) -> List[Position]:
        """청산된 포지션 (당일)"""
        return self._closed_positions.copy()

    # =========================================
    # 통계/요약
    # =========================================

    def get_total_pnl(self) -> int:
        """총 평가 손익 (원)"""
        return sum(p.profit_loss for p in self._positions.values())

    def get_total_eval_amount(self) -> int:
        """총 평가 금액 (원)"""
        return sum(p.eval_amount for p in self._positions.values())

    def get_total_invested(self) -> int:
        """총 투자 금액 (원)"""
        return sum(p.invested_amount for p in self._positions.values())

    def get_realized_pnl(self) -> int:
        """실현 손익 (당일, 원)"""
        return sum(p.profit_loss for p in self._closed_positions)

    def get_summary(self) -> dict:
        """포지션 요약"""
        return {
            "position_count": len(self._positions),
            "total_invested": self.get_total_invested(),
            "total_eval": self.get_total_eval_amount(),
            "total_pnl": self.get_total_pnl(),
            "realized_pnl": self.get_realized_pnl(),
            "closed_count": len(self._closed_positions),
        }

    def get_positions_text(self) -> str:
        """포지션 목록 텍스트"""
        if not self._positions:
            return "보유 종목 없음"

        lines = []
        for pos in self._positions.values():
            emoji = "+" if pos.profit_loss >= 0 else "-"
            lines.append(
                f"{emoji} {pos.stock_name}({pos.stock_code}): "
                f"{pos.quantity}주 {pos.profit_loss_rate:+.2f}% "
                f"({pos.profit_loss:+,}원)"
            )

        return "\n".join(lines)

    # =========================================
    # 유틸리티
    # =========================================

    def clear(self) -> None:
        """모든 포지션 초기화"""
        self._positions.clear()
        self._closed_positions.clear()

    def reset_daily(self) -> None:
        """당일 이력 초기화 (새 거래일)"""
        self._closed_positions.clear()

    async def sync_with_api(
        self,
        api_positions: List[dict],
    ) -> None:
        """
        API 조회 결과와 동기화

        Args:
            api_positions: API에서 조회한 보유종목 목록
                [{"stock_code": "005930", "quantity": 10, "avg_price": 70000}, ...]

        Note:
            수량 변경 시 RiskManager에도 동기화하여 불일치를 방지합니다.
        """
        api_codes = {p["stock_code"] for p in api_positions}
        local_codes = set(self._positions.keys())

        # 로컬에만 있는 포지션 (API에서 이미 청산됨)
        for code in local_codes - api_codes:
            position = self._positions[code]
            self._logger.warning(
                f"포지션 불일치 (API에 없음): {code} - 청산 처리"
            )
            # RiskManager 포지션 리스크 정보 제거
            if self._risk_manager:
                self._risk_manager.remove_position_risk(code)
            await self.close_position(code, position.current_price, "API 동기화 - 청산됨")

        # API와 수량/가격 동기화
        for api_pos in api_positions:
            code = api_pos["stock_code"]
            if code in self._positions:
                position = self._positions[code]
                new_quantity = api_pos.get("quantity", position.quantity)

                # 수량 동기화
                if position.quantity != new_quantity:
                    old_qty = position.quantity
                    position.quantity = new_quantity
                    self._logger.info(
                        f"수량 동기화: {code} {old_qty} -> {position.quantity}"
                    )

                    # RiskManager에도 수량 동기화
                    if self._risk_manager:
                        self._risk_manager.sync_quantity(code, new_quantity)

    # =========================================
    # PRD v3.3: 분할 익절 상태 동기화
    # =========================================

    def set_partial_exit_status(
        self,
        stock_code: str,
        is_partial_exit: bool,
        highest_price: int = 0,
    ) -> bool:
        """
        분할 익절 상태 설정 (PRD v3.3: 상태 일관성 보장)

        RiskManager에서 분할 익절 완료 시 Position에도 동기화합니다.
        이를 통해 두 객체 간 상태 불일치를 방지합니다.

        Args:
            stock_code: 종목 코드
            is_partial_exit: 분할 익절 완료 여부
            highest_price: 분할 익절 시점 최고가 (트레일링 스탑용)

        Returns:
            성공 여부
        """
        position = self._positions.get(stock_code)
        if position is None:
            self._logger.warning(f"분할 익절 상태 설정 실패 (포지션 없음): {stock_code}")
            return False

        position.is_partial_exit = is_partial_exit
        if highest_price > 0:
            position.highest_price_after_partial = highest_price

        self._logger.debug(
            f"분할 익절 상태 설정: {stock_code}",
            is_partial_exit=is_partial_exit,
            highest_price=highest_price,
        )
        return True

    def is_partial_exited(self, stock_code: str) -> bool:
        """
        분할 익절 완료 여부 조회

        Args:
            stock_code: 종목 코드

        Returns:
            분할 익절 완료 여부 (포지션 없으면 False)
        """
        position = self._positions.get(stock_code)
        return position.is_partial_exit if position else False
