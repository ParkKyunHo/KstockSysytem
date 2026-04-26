"""
주문 관련 API 엔드포인트

매수, 매도, 정정, 취소 주문을 제공합니다.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.api.client import KiwoomAPIClient
from src.utils.logger import get_logger
from src.utils.exceptions import OrderSubmitError, OrderCancelError


class OrderType(str, Enum):
    """주문 유형 코드"""
    LIMIT = "0"           # 지정가
    MARKET = "3"          # 시장가
    CONDITIONAL = "5"     # 조건부지정가
    BEST_LIMIT = "6"      # 최유리지정가
    FIRST_LIMIT = "7"     # 최우선지정가
    LIMIT_IOC = "10"      # 지정가 IOC
    MARKET_IOC = "13"     # 시장가 IOC
    LIMIT_FOK = "20"      # 지정가 FOK
    MARKET_FOK = "23"     # 시장가 FOK
    PRE_MARKET = "61"     # 장시작전시간외
    AFTER_HOURS = "62"    # 시간외단일가
    POST_MARKET = "81"    # 장마감후시간외


class Exchange(str, Enum):
    """거래소 코드"""
    KRX = "KRX"           # 한국거래소
    NXT = "NXT"           # 넥스트트레이드
    SOR = "SOR"           # Smart Order Routing


@dataclass
class OrderResult:
    """주문 결과"""
    success: bool
    order_no: Optional[str] = None
    exchange: Optional[str] = None
    message: str = ""


class OrderAPI:
    """
    주문 관련 API

    API ID:
    - kt10000: 주식 매수주문
    - kt10001: 주식 매도주문
    - kt10002: 주식 정정주문
    - kt10003: 주식 취소주문
    """

    def __init__(self, client: KiwoomAPIClient):
        self._client = client
        self._logger = get_logger(__name__)

    async def buy(
        self,
        stock_code: str,
        quantity: int,
        price: Optional[int] = None,
        order_type: OrderType = OrderType.MARKET,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResult:
        """
        매수 주문 (kt10000)

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문 수량
            price: 주문 가격 (지정가 필수)
            order_type: 주문 유형
            exchange: 거래소

        Returns:
            OrderResult 객체
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        body = {
            "dmst_stex_tp": exchange.value,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price) if price else "",
            "trde_tp": order_type.value,
            "cond_uv": "",
            "crd_tp": "00",  # PRD v3.1: 현금 매수 강제 (미수 방지)
        }

        self._logger.info(
            "매수 주문",
            stock_code=stock_code,
            quantity=quantity,
            price=price,
            order_type=order_type.value,
        )

        try:
            response = await self._client.post(
                url=KiwoomAPIClient.ORDER_URL,
                api_id="kt10000",
                body=body,
            )

            return OrderResult(
                success=True,
                order_no=response.data.get("ord_no"),
                exchange=response.data.get("dmst_stex_tp"),
                message=response.return_msg,
            )

        except Exception as e:
            self._logger.error("매수 주문 실패", error=str(e))
            raise OrderSubmitError(f"매수 주문 실패: {e}")

    async def sell(
        self,
        stock_code: str,
        quantity: int,
        price: Optional[int] = None,
        order_type: OrderType = OrderType.MARKET,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResult:
        """
        매도 주문 (kt10001)

        Args:
            stock_code: 종목코드 (6자리)
            quantity: 주문 수량
            price: 주문 가격 (지정가 필수)
            order_type: 주문 유형
            exchange: 거래소

        Returns:
            OrderResult 객체
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        body = {
            "dmst_stex_tp": exchange.value,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price) if price else "",
            "trde_tp": order_type.value,
            "cond_uv": "",
        }

        self._logger.info(
            "매도 주문",
            stock_code=stock_code,
            quantity=quantity,
            price=price,
            order_type=order_type.value,
        )

        try:
            response = await self._client.post(
                url=KiwoomAPIClient.ORDER_URL,
                api_id="kt10001",
                body=body,
            )

            return OrderResult(
                success=True,
                order_no=response.data.get("ord_no"),
                exchange=response.data.get("dmst_stex_tp"),
                message=response.return_msg,
            )

        except Exception as e:
            self._logger.error("매도 주문 실패", error=str(e))
            raise OrderSubmitError(f"매도 주문 실패: {e}")

    async def modify(
        self,
        original_order_no: str,
        stock_code: str,
        quantity: int,
        price: Optional[int] = None,
        order_type: OrderType = OrderType.LIMIT,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResult:
        """
        정정 주문 (kt10002)

        Args:
            original_order_no: 원주문번호
            stock_code: 종목코드
            quantity: 정정 수량
            price: 정정 가격
            order_type: 주문 유형
            exchange: 거래소

        Returns:
            OrderResult 객체
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        body = {
            "dmst_stex_tp": exchange.value,
            "org_ord_no": original_order_no,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "ord_uv": str(price) if price else "",
            "trde_tp": order_type.value,
        }

        self._logger.info(
            "정정 주문",
            original_order_no=original_order_no,
            stock_code=stock_code,
            quantity=quantity,
            price=price,
        )

        try:
            response = await self._client.post(
                url=KiwoomAPIClient.ORDER_URL,
                api_id="kt10002",
                body=body,
            )

            return OrderResult(
                success=True,
                order_no=response.data.get("ord_no"),
                message=response.return_msg,
            )

        except Exception as e:
            self._logger.error("정정 주문 실패", error=str(e))
            raise OrderSubmitError(f"정정 주문 실패: {e}")

    async def cancel(
        self,
        original_order_no: str,
        stock_code: str,
        quantity: int,
        exchange: Exchange = Exchange.KRX,
    ) -> OrderResult:
        """
        취소 주문 (kt10003)

        Args:
            original_order_no: 원주문번호
            stock_code: 종목코드
            quantity: 취소 수량
            exchange: 거래소

        Returns:
            OrderResult 객체
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        body = {
            "dmst_stex_tp": exchange.value,
            "org_ord_no": original_order_no,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
        }

        self._logger.info(
            "취소 주문",
            original_order_no=original_order_no,
            stock_code=stock_code,
            quantity=quantity,
        )

        try:
            response = await self._client.post(
                url=KiwoomAPIClient.ORDER_URL,
                api_id="kt10003",
                body=body,
            )

            return OrderResult(
                success=True,
                order_no=response.data.get("ord_no"),
                message=response.return_msg,
            )

        except Exception as e:
            self._logger.error("취소 주문 실패", error=str(e))
            raise OrderCancelError(f"취소 주문 실패: {e}")
