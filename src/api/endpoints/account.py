"""
계좌 관련 API 엔드포인트

예수금, 보유종목, 미체결 조회, 체결 확인 등을 제공합니다.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.api.client import KiwoomAPIClient
from src.utils.logger import get_logger


@dataclass
class Balance:
    """계좌 잔고 정보"""
    deposit: int                    # 예수금
    available_amount: int           # 주문가능금액
    d2_estimated_deposit: int       # D+2 추정예수금
    withdrawal_amount: int          # 출금가능금액


@dataclass
class Position:
    """보유 종목 정보"""
    stock_code: str                 # 종목코드
    stock_name: str                 # 종목명
    quantity: int                   # 보유수량
    average_price: int              # 평균단가
    current_price: int              # 현재가
    eval_amount: int                # 평가금액
    profit_loss: int                # 손익금액
    profit_loss_rate: float         # 손익율 (%)
    purchase_amount: int            # 매입금액


@dataclass
class AccountSummary:
    """계좌 평가 요약"""
    account_name: str               # 계좌명
    deposit: int                    # 예수금
    total_eval_amount: int          # 유가잔고평가액
    total_purchase_amount: int      # 총매입금액
    total_profit_loss: int          # 총 손익
    profit_loss_rate: float         # 총 손익율
    positions: List[Position]       # 보유종목 목록


@dataclass
class ExecutionInfo:
    """체결 정보 (ka10076 응답)"""
    order_no: str                   # 주문번호
    stock_code: str                 # 종목코드
    stock_name: str                 # 종목명
    side: str                       # 매수/매도 구분
    order_qty: int                  # 주문수량
    filled_qty: int                 # 체결수량
    unfilled_qty: int               # 미체결수량
    filled_price: int               # 체결가 (평균)
    order_status: str               # 주문상태

    @property
    def is_fully_filled(self) -> bool:
        """전량 체결 여부"""
        return self.unfilled_qty == 0 and self.filled_qty > 0

    @property
    def is_partially_filled(self) -> bool:
        """부분 체결 여부"""
        return self.filled_qty > 0 and self.unfilled_qty > 0


class AccountAPI:
    """
    계좌 관련 API

    API ID:
    - kt00001: 예수금상세현황요청
    - kt00004: 계좌평가현황요청
    - kt00005: 체결잔고요청
    - ka10075: 미체결요청
    - ka10076: 체결요청 (체결 확인용)
    """

    def __init__(self, client: KiwoomAPIClient):
        self._client = client
        self._logger = get_logger(__name__)

    async def get_balance(self, query_type: str = "3") -> Balance:
        """
        예수금 조회 (kt00001)

        Args:
            query_type: "3" 추정, "2" 실제

        Returns:
            Balance 객체
        """
        response = await self._client.post(
            url=KiwoomAPIClient.ACCOUNT_URL,
            api_id="kt00001",
            body={"qry_tp": query_type},
        )

        data = response.data
        return Balance(
            deposit=int(data.get("entr", 0)),
            available_amount=int(data.get("ord_alow_amt", 0)),
            d2_estimated_deposit=int(data.get("d2_entra", 0)),
            withdrawal_amount=int(data.get("pymn_alow_amt", 0)),
        )

    async def get_positions(
        self,
        exclude_delisted: bool = True,
        exchange: str = "",  # "": 통합 조회 (KRX + NXT), "KRX" 또는 "NXT": 단일 조회
    ) -> AccountSummary:
        """
        계좌 평가 및 보유종목 조회 (kt00004)

        Args:
            exclude_delisted: 상장폐지 종목 제외
            exchange: "" = 통합 조회 (KRX + NXT), "KRX" 또는 "NXT" = 단일 조회

        Returns:
            AccountSummary 객체
        """
        # kt00004 API는 통합 조회 옵션이 없음 (KRX/NXT만 유효)
        # 빈 문자열이면 KRX + NXT 둘 다 조회하여 합침
        if not exchange:
            exchanges_to_query = ["KRX", "NXT"]
        else:
            exchanges_to_query = [exchange]

        all_positions = []
        account_name = ""
        deposit = 0
        total_eval_amount = 0
        total_purchase_amount = 0
        total_profit_loss = 0
        profit_loss_rate = 0.0

        for ex in exchanges_to_query:
            try:
                response = await self._client.post(
                    url=KiwoomAPIClient.ACCOUNT_URL,
                    api_id="kt00004",
                    body={
                        "qry_tp": "1" if exclude_delisted else "0",
                        "dmst_stex_tp": ex,
                    },
                )
                data = response.data

                # 첫 번째 응답에서 계좌 정보 저장
                if not account_name:
                    account_name = data.get("acnt_nm", "")
                    deposit = int(float(data.get("entr", 0)))

                # 평가금액 합산 (KRX + NXT)
                total_eval_amount += int(float(data.get("tot_est_amt", 0)))
                total_purchase_amount += int(float(data.get("tot_pur_amt", 0)))
                total_profit_loss += int(float(data.get("lspft", 0)))

                # 보유종목 파싱
                for item in data.get("stk_acnt_evlt_prst", []):
                    # 종목코드 파싱: API는 "A0001A0" 형태로 반환 (앞의 A만 제거)
                    raw_code = item.get("stk_cd", "")
                    stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
                    all_positions.append(Position(
                        stock_code=stock_code,
                        stock_name=item.get("stk_nm", ""),
                        quantity=int(item.get("rmnd_qty", 0)),
                        average_price=int(float(item.get("avg_prc", 0))),
                        current_price=int(float(item.get("cur_prc", 0))),
                        eval_amount=int(float(item.get("evlt_amt", 0))),
                        profit_loss=int(float(item.get("pl_amt", 0))),
                        profit_loss_rate=float(item.get("pl_rt", 0)),
                        purchase_amount=int(float(item.get("pur_amt", 0))),
                    ))

            except Exception as e:
                self._logger.warning(f"[get_positions] {ex} 조회 실패: {e}")
                continue

        # 수익률 재계산 (합산된 금액 기준)
        if total_purchase_amount > 0:
            profit_loss_rate = (total_profit_loss / total_purchase_amount) * 100

        return AccountSummary(
            account_name=account_name,
            deposit=deposit,
            total_eval_amount=total_eval_amount,
            total_purchase_amount=total_purchase_amount,
            total_profit_loss=total_profit_loss,
            profit_loss_rate=profit_loss_rate,
            positions=all_positions,
        )

    async def get_unfilled_orders(
        self,
        stock_code: str = "",
        trade_type: str = "0",
        exchange_type: str = "0",
    ) -> List[dict]:
        """
        미체결 주문 조회 (ka10075)

        Args:
            stock_code: 종목코드 (빈값이면 전체 조회)
            trade_type: "0"=전체, "1"=매도, "2"=매수
            exchange_type: "0"=통합, "1"=KRX, "2"=NXT

        Returns:
            미체결 주문 리스트 (oso 배열)
        """
        body = {
            "all_stk_tp": "0" if not stock_code else "1",  # 0=전체, 1=종목
            "trde_tp": trade_type,
            "stk_cd": stock_code,
            "stex_tp": exchange_type,
        }

        response = await self._client.post(
            url=KiwoomAPIClient.ACCOUNT_URL,
            api_id="ka10075",
            body=body,
        )

        return response.data.get("oso", [])

    async def has_position(self, stock_code: str) -> bool:
        """
        특정 종목 보유 여부 확인

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            보유 여부
        """
        summary = await self.get_positions()
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        stock_code_clean = stock_code[1:] if stock_code.startswith("A") else stock_code

        for pos in summary.positions:
            if pos.stock_code == stock_code_clean:
                return True
        return False

    async def get_position(self, stock_code: str) -> Optional[Position]:
        """
        특정 종목 보유 정보 조회

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            Position 객체 또는 None
        """
        summary = await self.get_positions()
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        stock_code_clean = stock_code[1:] if stock_code.startswith("A") else stock_code

        for pos in summary.positions:
            if pos.stock_code == stock_code_clean:
                return pos
        return None

    async def get_execution_info(
        self,
        order_no: str,
        stock_code: str = "",
        exchange: str = "1",
    ) -> Optional[ExecutionInfo]:
        """
        체결 정보 조회 (ka10076)

        Args:
            order_no: 주문번호
            stock_code: 종목코드 (선택, 빈값이면 전체)
            exchange: 거래소구분 (1:KRX, 2:NXT, 0:통합)

        Returns:
            ExecutionInfo 또는 None (주문 미발견 시)
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        stock_code_clean = ""
        if stock_code:
            stock_code_clean = stock_code[1:] if stock_code.startswith("A") else stock_code

        response = await self._client.post(
            url=KiwoomAPIClient.ACCOUNT_URL,
            api_id="ka10076",
            body={
                "stk_cd": stock_code_clean,
                "qry_tp": "1" if stock_code_clean else "0",  # 0:전체, 1:종목
                "sell_tp": "0",  # 0:전체
                "ord_no": "",    # 빈값 = 최신부터
                "stex_tp": exchange,
            },
        )

        # cntr 리스트에서 해당 주문번호 찾기
        for item in response.data.get("cntr", []):
            if item.get("ord_no") == order_no:
                raw_code = item.get("stk_cd", "")
                exec_stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
                return ExecutionInfo(
                    order_no=order_no,
                    stock_code=exec_stock_code,
                    stock_name=item.get("stk_nm", ""),
                    side=item.get("io_tp_nm", ""),
                    order_qty=int(item.get("ord_qty", 0) or 0),
                    filled_qty=int(item.get("cntr_qty", 0) or 0),
                    unfilled_qty=int(item.get("oso_qty", 0) or 0),
                    filled_price=int(item.get("cntr_pric", 0) or 0),
                    order_status=item.get("ord_stt", ""),
                )

        return None

    async def wait_for_execution(
        self,
        order_no: str,
        stock_code: str = "",
        max_wait_seconds: float = 5.0,
        poll_interval: float = 0.5,
    ) -> Optional[ExecutionInfo]:
        """
        체결 대기 (폴링)

        시장가 주문은 보통 0.5-2초 내 체결됨.
        최대 대기 시간 후에도 미체결이면 None 반환.

        Args:
            order_no: 주문번호
            stock_code: 종목코드 (선택)
            max_wait_seconds: 최대 대기 시간 (초)
            poll_interval: 폴링 간격 (초)

        Returns:
            ExecutionInfo (체결 완료 시) 또는 None (타임아웃)
        """
        start_time = datetime.now()

        while True:
            elapsed = (datetime.now() - start_time).total_seconds()

            if elapsed > max_wait_seconds:
                self._logger.warning(
                    f"체결 대기 타임아웃: {order_no} ({elapsed:.1f}초)"
                )
                return None

            info = await self.get_execution_info(order_no, stock_code)

            if info and info.is_fully_filled:
                self._logger.info(
                    f"체결 확인 완료",
                    order_no=order_no,
                    filled_qty=info.filled_qty,
                    filled_price=info.filled_price,
                    elapsed=f"{elapsed:.1f}초",
                )
                return info

            # 부분 체결인 경우 로깅
            if info and info.is_partially_filled:
                self._logger.info(
                    f"부분 체결 중",
                    order_no=order_no,
                    filled_qty=info.filled_qty,
                    unfilled_qty=info.unfilled_qty,
                )

            await asyncio.sleep(poll_interval)
