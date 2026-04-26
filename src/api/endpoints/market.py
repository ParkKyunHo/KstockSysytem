"""
시세 관련 API 엔드포인트

종목 정보, 호가, 현재가, 분봉 차트 조회를 제공합니다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.api.client import KiwoomAPIClient
from src.utils.logger import get_logger


def _safe_float(value, default: float = 0.0) -> float:
    """빈 문자열, None 등을 안전하게 float로 변환"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value, default: int = 0) -> int:
    """빈 문자열, None 등을 안전하게 int로 변환"""
    return int(_safe_float(value, float(default)))


@dataclass
class Quote:
    """호가 정보"""
    stock_code: str
    stock_name: str
    current_price: int
    change: int
    change_rate: float
    volume: int

    # 매수호가
    bid_price_1: int
    bid_qty_1: int
    bid_price_2: int
    bid_qty_2: int
    bid_price_3: int
    bid_qty_3: int

    # 매도호가
    ask_price_1: int
    ask_qty_1: int
    ask_price_2: int
    ask_qty_2: int
    ask_price_3: int
    ask_qty_3: int


@dataclass
class StockInfo:
    """종목 기본 정보"""
    stock_code: str
    stock_name: str
    current_price: int
    change: int
    change_rate: float
    volume: int
    market_cap: int
    high_price: int
    low_price: int
    open_price: int
    prev_close: int


@dataclass
class RankingItem:
    """거래대금 랭킹 종목"""
    rank: int
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    volume: int
    trading_value: int  # 거래대금 (원)


@dataclass
class MinuteCandle:
    """분봉 데이터"""
    timestamp: datetime
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int


@dataclass
class DailyCandle:
    """일봉 데이터"""
    date: datetime
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int
    trading_value: int = 0  # 거래대금 (원)
    change_rate: float = 0.0  # 등락률 (%) - trde_tern_rt


class MarketAPI:
    """
    시세 관련 API

    API ID:
    - ka10001: 주식기본정보요청
    - ka10004: 주식호가요청
    - ka10005: 주식일주월시분요청
    """

    def __init__(self, client: KiwoomAPIClient):
        self._client = client
        self._logger = get_logger(__name__)

    async def get_stock_info(self, stock_code: str) -> StockInfo:
        """
        종목 기본정보 조회 (ka10001)

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            StockInfo 객체
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        response = await self._client.post(
            url=KiwoomAPIClient.STOCK_INFO_URL,
            api_id="ka10001",
            body={"stk_cd": stock_code},
        )

        data = response.data
        return StockInfo(
            stock_code=stock_code,
            stock_name=data.get("stk_nm", ""),
            current_price=abs(_safe_int(data.get("cur_prc"))),  # 키움 API 음수 부호 제거
            change=_safe_int(data.get("prc_chng")),
            change_rate=_safe_float(data.get("prc_chng_rt")),
            volume=_safe_int(data.get("volume")),
            market_cap=_safe_int(data.get("mac")) * 100_000_000,  # 억원 → 원 (시가총액 필드: mac)
            high_price=_safe_int(data.get("high_prc")),
            low_price=_safe_int(data.get("low_prc")),
            open_price=_safe_int(data.get("open_prc")),
            prev_close=_safe_int(data.get("prev_cls_prc")),
        )

    async def get_quote(self, stock_code: str) -> Quote:
        """
        호가 조회 (ka10004)

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            Quote 객체
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        response = await self._client.post(
            url=KiwoomAPIClient.MARKET_URL,
            api_id="ka10004",
            body={"stk_cd": stock_code},
        )

        data = response.data
        return Quote(
            stock_code=stock_code,
            stock_name=data.get("stk_nm", ""),
            current_price=abs(_safe_int(data.get("cur_prc"))),  # 키움 API 음수 부호 제거
            change=_safe_int(data.get("prc_chng")),
            change_rate=_safe_float(data.get("prc_chng_rt")),
            volume=_safe_int(data.get("volume")),
            # 매수호가
            bid_price_1=_safe_int(data.get("bid_prc_1")),
            bid_qty_1=_safe_int(data.get("bid_qty_1")),
            bid_price_2=_safe_int(data.get("bid_prc_2")),
            bid_qty_2=_safe_int(data.get("bid_qty_2")),
            bid_price_3=_safe_int(data.get("bid_prc_3")),
            bid_qty_3=_safe_int(data.get("bid_qty_3")),
            # 매도호가
            ask_price_1=_safe_int(data.get("ask_prc_1")),
            ask_qty_1=_safe_int(data.get("ask_qty_1")),
            ask_price_2=_safe_int(data.get("ask_prc_2")),
            ask_qty_2=_safe_int(data.get("ask_qty_2")),
            ask_price_3=_safe_int(data.get("ask_prc_3")),
            ask_qty_3=_safe_int(data.get("ask_qty_3")),
        )

    async def get_current_price(self, stock_code: str) -> int:
        """
        현재가 조회

        Args:
            stock_code: 종목코드

        Returns:
            현재가
        """
        info = await self.get_stock_info(stock_code)
        return info.current_price

    async def get_stock_name(self, stock_code: str) -> str:
        """
        종목명 조회

        Args:
            stock_code: 종목코드

        Returns:
            종목명
        """
        info = await self.get_stock_info(stock_code)
        return info.stock_name

    async def get_trading_volume_ranking(
        self,
        market: str = "0",
        top_n: int = 50,
    ) -> list["RankingItem"]:
        """
        거래대금 상위 종목 조회 (ka10032)

        Args:
            market: 시장 구분 ("0": 전체, "1": 코스피, "2": 코스닥)
            top_n: 조회할 종목 수

        Returns:
            RankingItem 리스트
        """
        # ka10032: 거래대금상위요청 (URL: /api/dostk/rkinfo)
        response = await self._client.post(
            url="/api/dostk/rkinfo",
            api_id="ka10032",
            body={
                "stex_tp": "K",         # 거래소 구분 (K: KRX) - 필수 파라미터
                "mrkt_tp": market,      # 시장 구분
                "sort_tp": "0",         # 거래대금 기준
                "cnt": str(top_n),      # 조회 개수
                "mang_stk_incls": "0",  # 관리종목 포함 여부 (0: 제외, 1: 포함)
            },
        )

        items = []
        # ka10032 응답 키: trde_prica_upper (거래대금 상위)
        data_list = response.data.get("trde_prica_upper", response.data.get("list", []))
        for item in data_list:
            try:
                raw_code = item.get("stk_cd", "")
                stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
                rank_item = RankingItem(
                    rank=_safe_int(item.get("now_rank", item.get("rank"))),
                    stock_code=stock_code,
                    stock_name=item.get("stk_nm", ""),
                    current_price=abs(_safe_int(item.get("cur_prc"))),  # 키움 API 음수 부호 제거
                    change_rate=_safe_float(item.get("flu_rt", item.get("prc_chng_rt"))),
                    volume=_safe_int(item.get("now_trde_qty", item.get("volume"))),
                    trading_value=_safe_int(item.get("trde_prica", item.get("trd_amt"))) * 1_000_000,  # 백만원 단위 → 원
                )
                items.append(rank_item)
            except (ValueError, TypeError) as e:
                self._logger.warning(f"랭킹 데이터 파싱 오류: {e}")
                continue

        return items

    async def get_minute_chart(
        self,
        stock_code: str,
        timeframe: int = 1,
        count: int = 400,
        use_pagination: bool = True,
    ) -> List[MinuteCandle]:
        """
        분봉 차트 조회 (ka10080) - 연속조회 지원

        Args:
            stock_code: 종목코드 (6자리)
            timeframe: 분봉 타임프레임 (1, 3, 5, 10, 15, 30, 60)
            count: 조회할 봉 개수 (2~3일치: 3분봉 400개, 1분봉 600개)
            use_pagination: 연속조회 사용 여부 (True: 모든 데이터, False: 단일 요청)

        Returns:
            MinuteCandle 리스트 (과거 → 최신 순, 최신 count개)
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]
        CHART_URL = "/api/dostk/chart"

        body = {
            "stk_cd": stock_code,
            "tic_scope": str(timeframe),  # 틱범위 (1:1분, 3:3분, 5:5분 등)
            "upd_stkpc_tp": "0",  # 수정주가구분 (0: 미적용)
        }

        candles = []

        if use_pagination:
            # 연속조회로 모든 데이터 수집 (HTS 완벽 일치)
            all_responses = await self._client.paginate(
                url=CHART_URL,
                api_id="ka10080",
                body=body,
                max_pages=10,  # 최대 10페이지 (약 1000개, EMA200용 800개 커버)
            )
            for response_data in all_responses:
                candles.extend(self._parse_candle_data(response_data))
        else:
            # 단일 요청 (기존 방식)
            response = await self._client.post(
                url=CHART_URL,
                api_id="ka10080",
                body=body,
            )
            candles = self._parse_candle_data(response.data)

        # 과거 → 최신 순으로 정렬 (시간 오름차순)
        candles.sort(key=lambda c: c.timestamp)

        # count 개수만큼 최신 캔들만 반환
        if len(candles) > count:
            candles = candles[-count:]

        self._logger.info(
            f"[분봉 조회] {stock_code} {timeframe}분봉: {len(candles)}개 (pagination={use_pagination})"
        )

        return candles

    def _parse_candle_data(self, response_data: dict) -> List[MinuteCandle]:
        """
        API 응답에서 캔들 데이터 파싱

        Args:
            response_data: API 응답 데이터

        Returns:
            MinuteCandle 리스트
        """
        candles = []

        # 응답 구조: stk_min_pole_chart_qry 배열
        if isinstance(response_data, dict):
            # 키움 분봉 API 응답 키: stk_min_pole_chart_qry
            data_list = response_data.get("stk_min_pole_chart_qry", [])
            if not data_list:
                # 대체 키 시도
                data_list = response_data.get("output", response_data.get("list", []))
        else:
            data_list = response_data if isinstance(response_data, list) else []

        for item in data_list:
            try:
                # 시간 파싱 (cntr_tm: YYYYMMDDHHMMSS 형식)
                time_str = str(item.get("cntr_tm", item.get("stck_cntg_hour", item.get("time", ""))))

                # cntr_tm은 YYYYMMDDHHMMSS (14자리) 형식
                if len(time_str) >= 14:
                    dt = datetime.strptime(time_str[:14], "%Y%m%d%H%M%S")
                elif len(time_str) >= 6:
                    # HHMMSS 형식이면 오늘 날짜 사용
                    today = datetime.now().strftime("%Y%m%d")
                    dt = datetime.strptime(f"{today}{time_str[:6]}", "%Y%m%d%H%M%S")
                else:
                    continue

                # 가격 필드: +기호 제거 후 파싱 (빈 문자열 안전 처리)
                def parse_price(val):
                    if val is None or val == "":
                        return 0
                    if isinstance(val, str):
                        val = val.replace("+", "").replace("-", "")
                    return _safe_int(val)

                candle = MinuteCandle(
                    timestamp=dt,
                    open_price=parse_price(item.get("open_pric", item.get("stck_oprc", item.get("open")))),
                    high_price=parse_price(item.get("high_pric", item.get("stck_hgpr", item.get("high")))),
                    low_price=parse_price(item.get("low_pric", item.get("stck_lwpr", item.get("low")))),
                    close_price=parse_price(item.get("cur_prc", item.get("stck_prpr", item.get("close")))),
                    volume=_safe_int(item.get("trde_qty", item.get("cntg_vol", item.get("volume")))),
                )
                candles.append(candle)

            except (ValueError, TypeError) as e:
                self._logger.warning(f"분봉 데이터 파싱 오류: {e}, item={item}")
                continue

        return candles

    async def get_index_price(self, index_code: str = "101"):
        """
        주가지수 현재가 조회 (PRD v3.0)

        Args:
            index_code: 지수코드 (001: 코스피, 101: 코스닥)

        Returns:
            APIResponse with index data
        """
        # ka20001: 업종현재가요청 (URL: /api/dostk/sect)
        # 시장구분: "1"=코스피, "2"=코스닥
        market_type = "1" if index_code == "001" else "2"  # KOSDAQ 101 → "2"
        response = await self._client.post(
            url="/api/dostk/sect",
            api_id="ka20001",
            body={
                "mrkt_tp": market_type,     # 시장 구분 (필수)
                "bstp_cd": index_code,      # 업종코드
            },
        )
        return response

    async def get_daily_chart(
        self,
        stock_code: str,
        count: int = 20,
    ) -> List[DailyCandle]:
        """
        일봉 차트 조회 (ka10081)

        PRD v3.1: 20일 최고가 조회를 위해 사용

        Args:
            stock_code: 종목코드 (6자리)
            count: 조회할 봉 개수 (기본 20)

        Returns:
            DailyCandle 리스트 (과거 → 최신 순)
        """
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        if stock_code.startswith("A"):
            stock_code = stock_code[1:]

        # ka10081: 주식일봉차트조회요청
        DAILY_CHART_URL = "/api/dostk/chart"

        # base_dt: 기준일자 (필수 파라미터) - 오늘 날짜 사용
        base_dt = datetime.now().strftime("%Y%m%d")

        response = await self._client.post(
            url=DAILY_CHART_URL,
            api_id="ka10081",
            body={
                "stk_cd": stock_code,
                "base_dt": base_dt,  # 기준일자 (필수)
                "upd_stkpc_tp": "0",  # 수정주가구분 (0: 미적용)
            },
        )

        candles = []

        # 디버그: 응답 구조 확인 (info 레벨로 항상 출력)
        self._logger.info(
            f"[일봉 API 응답] {stock_code}: type={type(response.data).__name__}, "
            f"keys={list(response.data.keys()) if isinstance(response.data, dict) else 'N/A'}, "
            f"sample={str(response.data)[:300]}"
        )

        # 응답 구조: stk_dt_pole_chart_qry 배열
        if isinstance(response.data, dict):
            data_list = response.data.get("stk_dt_pole_chart_qry", [])
            if not data_list:
                # 대체 키 시도
                data_list = response.data.get("output", response.data.get("list", []))

            # 디버그: 파싱 결과
            if not data_list:
                self._logger.warning(
                    f"[일봉 API] {stock_code}: 응답 키 불일치 - keys={list(response.data.keys())}, "
                    f"sample={str(response.data)[:200]}"
                )
        else:
            data_list = response.data if isinstance(response.data, list) else []

        for item in data_list[:count]:  # count개만 가져오기
            try:
                # 날짜 파싱 (dt 또는 trde_dd: YYYYMMDD 형식)
                date_str = str(item.get("dt", item.get("trde_dd", item.get("stck_bsop_date", ""))))

                if len(date_str) >= 8:
                    dt = datetime.strptime(date_str[:8], "%Y%m%d")
                else:
                    continue

                # 가격 필드 파싱 (빈 문자열 안전 처리)
                def parse_price(val):
                    if val is None or val == "":
                        return 0
                    if isinstance(val, str):
                        val = val.replace("+", "").replace("-", "")
                    return _safe_int(val)

                # 가격 파싱 (등락률 계산 전에 필요)
                close_price = parse_price(item.get("cur_prc", item.get("stck_clpr")))

                # 등락률 직접 계산 - pred_pre(전일대비 변동액)와 cur_prc(현재가) 사용
                # trde_tern_rt는 신규 상장종목에서 공모가 대비 등락률이므로 신뢰 불가
                pred_pre_str = str(item.get("pred_pre", "0")).replace("+", "")
                try:
                    pred_pre = float(pred_pre_str) if pred_pre_str else 0.0
                except ValueError:
                    pred_pre = 0.0
                prev_close = close_price - pred_pre
                if prev_close > 0:
                    change_rate = (pred_pre / prev_close) * 100
                else:
                    change_rate = 0.0

                candle = DailyCandle(
                    date=dt,
                    open_price=parse_price(item.get("open_pric", item.get("stck_oprc"))),
                    high_price=parse_price(item.get("high_pric", item.get("stck_hgpr"))),
                    low_price=parse_price(item.get("low_pric", item.get("stck_lwpr"))),
                    close_price=close_price,  # 이미 위에서 파싱됨
                    volume=_safe_int(item.get("trde_qty", item.get("acml_vol"))),
                    # trde_prica: 거래대금 (백만원 단위) → 원 단위로 변환
                    trading_value=_safe_int(item.get("trde_prica", item.get("trde_amt", item.get("acml_tr_pbmn")))) * 1000000,
                    change_rate=change_rate,  # 등락률 (일봉 API trde_tern_rt)
                )
                candles.append(candle)

            except (ValueError, TypeError) as e:
                self._logger.warning(f"일봉 데이터 파싱 오류: {e}, item={item}")
                continue

        # 과거 → 최신 순으로 정렬
        candles.sort(key=lambda c: c.date)

        self._logger.info(
            f"[일봉 조회] {stock_code}: {len(candles)}개"
        )

        return candles
