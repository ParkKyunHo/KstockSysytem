"""
유니버스 선정 모듈

Ju-Do-Ju Sniper 전략의 매매 대상 종목(유니버스)을 선정합니다.

선정 기준:
- 거래대금 300억 이상 실시간 상위 종목
- 등락률 +3% ~ +25%
- 제외: 관리종목, ETF, ETN, SPAC, 1000원 미만
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Dict, List, Optional, Set, Tuple
import re

from src.api.endpoints.market import MarketAPI, RankingItem, StockInfo
from src.utils.logger import get_logger


@dataclass
class UniverseConfig:
    """유니버스 선정 설정"""
    # 거래대금 최소 기준 (억원)
    min_trading_value: int = 300

    # 등락률 범위 (%)
    min_change_rate: float = 3.0
    max_change_rate: float = 25.0

    # 최소 가격 (원)
    min_price: int = 1000

    # 최대 종목 수
    max_stocks: int = 30

    # 갱신 주기 (분)
    refresh_interval_minutes: int = 5


@dataclass
class UniverseStock:
    """유니버스 편입 종목"""
    stock_code: str
    stock_name: str
    current_price: int
    change_rate: float
    trading_value: int      # 거래대금 (억원)
    added_at: datetime = field(default_factory=datetime.now)

    def __hash__(self):
        return hash(self.stock_code)

    def __eq__(self, other):
        if isinstance(other, UniverseStock):
            return self.stock_code == other.stock_code
        return False


class StockFilter:
    """종목 필터"""

    # ETF/ETN 패턴 (종목명)
    ETF_PATTERNS = [
        r"^KODEX",
        r"^TIGER",
        r"^KBSTAR",
        r"^HANARO",
        r"^ARIRANG",
        r"^KOSEF",
        r"^SOL",
        r"^ACE",
        r"^RISE",
        r"^PLUS",
        r"ETF$",
        r"ETN$",
    ]

    # SPAC 패턴
    SPAC_PATTERNS = [
        r"스팩",
        r"SPAC",
        r"기업인수목적",
    ]

    # 제외 종목 (관리종목, 우선주 등)
    EXCLUDE_PATTERNS = [
        r"우$",           # 우선주
        r"우B$",          # 우선주 B
        r"우C$",          # 우선주 C
        r"\d우$",         # N우 형태 우선주
        r"리츠$",         # 리츠
    ]

    @classmethod
    def is_etf_etn(cls, stock_name: str) -> bool:
        """ETF/ETN 여부"""
        for pattern in cls.ETF_PATTERNS:
            if re.search(pattern, stock_name, re.IGNORECASE):
                return True
        return False

    @classmethod
    def is_spac(cls, stock_name: str) -> bool:
        """SPAC 여부"""
        for pattern in cls.SPAC_PATTERNS:
            if re.search(pattern, stock_name):
                return True
        return False

    @classmethod
    def is_excluded(cls, stock_name: str) -> bool:
        """제외 종목 여부"""
        for pattern in cls.EXCLUDE_PATTERNS:
            if re.search(pattern, stock_name):
                return True
        return False

    @classmethod
    def is_valid(cls, stock_name: str) -> bool:
        """유효한 종목인지 검사"""
        if cls.is_etf_etn(stock_name):
            return False
        if cls.is_spac(stock_name):
            return False
        if cls.is_excluded(stock_name):
            return False
        return True


class Universe:
    """
    유니버스 관리자

    거래대금 상위 종목을 주기적으로 갱신하고,
    필터 조건에 맞는 종목만 유니버스에 편입합니다.

    Usage:
        universe = Universe(market_api, config)
        await universe.refresh()
        stocks = universe.get_stocks()
    """

    def __init__(
        self,
        market_api: MarketAPI,
        config: Optional[UniverseConfig] = None,
    ):
        self._market_api = market_api
        self._config = config or UniverseConfig()
        self._logger = get_logger(__name__)

        # 현재 유니버스
        self._stocks: Dict[str, UniverseStock] = {}

        # 마지막 갱신 시간
        self._last_refresh: Optional[datetime] = None

        # 수동 제외 종목
        self._manual_exclusions: Set[str] = set()

        # 수동 추가 종목 (refresh 시에도 유지됨)
        self._manual_additions: Set[str] = set()

    @property
    def stock_codes(self) -> List[str]:
        """유니버스 종목 코드 목록"""
        return list(self._stocks.keys())

    @property
    def stocks(self) -> List[UniverseStock]:
        """유니버스 종목 목록"""
        return list(self._stocks.values())

    @property
    def count(self) -> int:
        """유니버스 종목 수"""
        return len(self._stocks)

    @property
    def manual_additions(self) -> Set[str]:
        """수동 추가 종목 코드 목록 (refresh 시에도 유지되는 종목)"""
        return self._manual_additions.copy()

    def is_in_universe(self, stock_code: str) -> bool:
        """종목이 유니버스에 있는지 확인"""
        return stock_code in self._stocks

    def is_manual_addition(self, stock_code: str) -> bool:
        """수동 추가 종목인지 확인"""
        return stock_code in self._manual_additions

    def get_stock(self, stock_code: str) -> Optional[UniverseStock]:
        """종목 정보 조회"""
        return self._stocks.get(stock_code)

    def add_stock(
        self,
        stock_code: str,
        stock_name: str,
        current_price: int = 0,
        change_rate: float = 0.0,
        trading_value: int = 0,
        metadata: Optional[dict] = None,
        manual: bool = False,
    ) -> UniverseStock:
        """
        개별 종목을 유니버스에 추가

        조건식 편입 등 외부 신호로 종목을 추가할 때 사용합니다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            current_price: 현재가 (옵션)
            change_rate: 등락률 (옵션)
            trading_value: 거래대금 (옵션)
            metadata: 추가 메타데이터 (옵션)
            manual: True면 refresh() 시에도 유지됨 (/add 명령용)

        Returns:
            추가된 UniverseStock 객체
        """
        if stock_code in self._stocks:
            # 이미 있어도 manual=True면 수동 추가 목록에 등록
            if manual:
                self._manual_additions.add(stock_code)
                self._logger.info(f"유니버스 수동 추가 등록 (기존 종목): {stock_code}")
            else:
                self._logger.debug(f"이미 유니버스에 존재: {stock_code}")
            return self._stocks[stock_code]

        stock = UniverseStock(
            stock_code=stock_code,
            stock_name=stock_name,
            current_price=current_price,
            change_rate=change_rate,
            trading_value=trading_value,
        )
        self._stocks[stock_code] = stock

        # 수동 추가 목록에 등록
        if manual:
            self._manual_additions.add(stock_code)

        self._logger.info(
            f"유니버스 {'수동 ' if manual else ''}추가: {stock_name}({stock_code})",
            metadata=metadata,
        )

        return stock

    def remove_stock(self, stock_code: str) -> bool:
        """
        개별 종목을 유니버스에서 제거

        Args:
            stock_code: 종목코드

        Returns:
            제거 성공 여부
        """
        # 수동 추가 목록에서도 제거 (다음 refresh 시 이탈 가능)
        self._manual_additions.discard(stock_code)

        if stock_code in self._stocks:
            stock = self._stocks.pop(stock_code)
            self._logger.info(f"유니버스에서 제거: {stock.stock_name}({stock_code})")
            return True
        return False

    def add_manual_exclusion(self, stock_code: str) -> None:
        """수동 제외 종목 추가"""
        self._manual_exclusions.add(stock_code)
        if stock_code in self._stocks:
            del self._stocks[stock_code]
            self._logger.info(f"유니버스에서 수동 제외: {stock_code}")

    def remove_manual_exclusion(self, stock_code: str) -> None:
        """수동 제외 해제"""
        self._manual_exclusions.discard(stock_code)

    async def refresh(self) -> Tuple[List[UniverseStock], Set[str]]:
        """
        유니버스 갱신

        거래대금 상위 종목을 조회하고, 필터 조건에 맞는 종목만
        유니버스에 편입합니다.

        Returns:
            (갱신된 유니버스 종목 목록, 이탈 종목 코드 집합)
        """
        self._logger.info("유니버스 갱신 시작")

        try:
            # 거래대금 상위 종목 조회
            ranking = await self._market_api.get_trading_volume_ranking(
                market="0",  # 전체 시장
                top_n=100,   # 상위 100개 조회
            )

            new_stocks: Dict[str, UniverseStock] = {}
            added_count = 0
            filtered_count = 0

            for item in ranking:
                # 최대 종목 수 체크
                if len(new_stocks) >= self._config.max_stocks:
                    break

                # 수동 제외 체크
                if item.stock_code in self._manual_exclusions:
                    filtered_count += 1
                    continue

                # 필터 조건 체크
                if not self._passes_filter(item):
                    filtered_count += 1
                    continue

                # 유니버스 편입
                stock = UniverseStock(
                    stock_code=item.stock_code,
                    stock_name=item.stock_name,
                    current_price=item.current_price,
                    change_rate=item.change_rate,
                    trading_value=item.trading_value // 100_000_000,  # 억원 단위
                )

                new_stocks[item.stock_code] = stock
                added_count += 1

            # 수동 추가 종목 병합 (refresh 시에도 유지)
            preserved_count = 0
            for manual_code in self._manual_additions:
                if manual_code not in new_stocks:
                    # 기존 정보가 있으면 유지
                    if manual_code in self._stocks:
                        new_stocks[manual_code] = self._stocks[manual_code]
                        preserved_count += 1
                        self._logger.debug(f"수동 추가 종목 유지: {manual_code}")

            if preserved_count > 0:
                self._logger.info(f"수동 추가 종목 {preserved_count}개 유지됨")

            # 기존 유니버스 대비 변경 로깅
            prev_codes = set(self._stocks.keys())
            new_codes = set(new_stocks.keys())

            added = new_codes - prev_codes
            # 수동 추가 종목은 이탈 목록에서 제외
            removed = prev_codes - new_codes - self._manual_additions

            if added:
                self._logger.info(f"유니버스 신규 편입: {len(added)}개 - {list(added)[:5]}...")
            if removed:
                self._logger.info(f"유니버스 이탈: {len(removed)}개 - {list(removed)[:5]}...")

            # 갱신
            self._stocks = new_stocks
            self._last_refresh = datetime.now()

            self._logger.info(
                f"유니버스 갱신 완료: {len(self._stocks)}개 종목 "
                f"(필터링: {filtered_count}개)"
            )

            return list(self._stocks.values()), removed

        except Exception as e:
            # PRD v2.0: 수동 종목 관리 모드에서는 API 실패 무시 (warning)
            self._logger.warning(f"유니버스 갱신 실패 (수동 모드에서는 무시): {e}")
            return list(self._stocks.values()), set()

    def _passes_filter(self, item: RankingItem) -> bool:
        """
        필터 조건 통과 여부

        Args:
            item: 랭킹 종목 정보

        Returns:
            필터 통과 여부
        """
        # 종목명 기반 필터 (ETF, SPAC 등)
        if not StockFilter.is_valid(item.stock_name):
            return False

        # 최소 가격
        if item.current_price < self._config.min_price:
            return False

        # 등락률 범위
        if not (self._config.min_change_rate <= item.change_rate <= self._config.max_change_rate):
            return False

        # 거래대금 (억원 단위로 변환하여 비교)
        trading_value_billion = item.trading_value / 100_000_000
        if trading_value_billion < self._config.min_trading_value:
            return False

        return True

    def needs_refresh(self) -> bool:
        """갱신 필요 여부"""
        if self._last_refresh is None:
            return True

        elapsed = (datetime.now() - self._last_refresh).total_seconds() / 60
        return elapsed >= self._config.refresh_interval_minutes

    def clear(self) -> None:
        """유니버스 초기화"""
        self._stocks.clear()
        self._manual_additions.clear()
        self._last_refresh = None

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (상태 저장용)"""
        return {
            "stocks": [
                {
                    "stock_code": s.stock_code,
                    "stock_name": s.stock_name,
                    "current_price": s.current_price,
                    "change_rate": s.change_rate,
                    "trading_value": s.trading_value,
                }
                for s in self._stocks.values()
            ],
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "manual_exclusions": list(self._manual_exclusions),
            "manual_additions": list(self._manual_additions),
        }

    def get_summary(self) -> str:
        """유니버스 요약 문자열"""
        if not self._stocks:
            return "유니버스: 비어있음"

        lines = [f"유니버스 ({len(self._stocks)}개)"]
        for i, stock in enumerate(sorted(
            self._stocks.values(),
            key=lambda x: x.trading_value,
            reverse=True,
        )[:10], 1):
            lines.append(
                f"  {i}. {stock.stock_name}({stock.stock_code}) "
                f"{stock.change_rate:+.1f}% 거래대금:{stock.trading_value}억"
            )

        if len(self._stocks) > 10:
            lines.append(f"  ... 외 {len(self._stocks) - 10}개")

        return "\n".join(lines)
