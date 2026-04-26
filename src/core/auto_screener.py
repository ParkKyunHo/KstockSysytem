"""
V6.2-H: 주도주 자동 선별 (Auto-Universe Screener)

3단계 Pool 구조:
1. Watchlist Pool: 조건검색 포착 종목 (AUTO: 50개 / SIGNAL_ALERT: 무제한)
2. Candidate Pool: 5필터 통과 종목 (AUTO: 20개 / SIGNAL_ALERT: 무제한)
3. Active Pool: 거래대금 상위 종목 (AUTO: 10개 / SIGNAL_ALERT: 무제한)

조건검색 신호를 필터링하여 Pool에 등록하고,
거래대금 순위로 Active Pool을 관리합니다.

V6.2-H 변경:
- SIGNAL_ALERT 모드: 필터 실패 후 재시도 허용
  - already_processed 체크를 Active Pool 등록 여부로 변경
  - 필터 성공 시에만 processed_today 등록
- SNIPER_TRAP 조건 미충족 시 디버그 로그 추가 (signal_detector.py)

V6.2-G 변경:
- Universe.refresh() 레거시 제거 (거래대금 상위 100 조회 → 조건검색 기반)
- 보유 포지션은 시작 시 자동 Universe 등록
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, date, timezone, timedelta
from typing import Dict, Set, Optional, List, TYPE_CHECKING, Callable, Awaitable

from src.utils.config import RiskSettings
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.api.endpoints.market import MarketAPI
    from src.core.position_manager import PositionManager


@dataclass
class FilterResult:
    """필터링 결과"""
    passed: bool
    reason: str = ""
    details: Dict = field(default_factory=dict)


@dataclass
class StockScreenData:
    """스크리닝에 필요한 종목 데이터"""
    stock_code: str
    stock_name: str
    current_price: int
    open_price: int
    prev_close: int
    trading_value: int  # 누적 거래대금 (원)
    high_20d: int  # 20일 최고가

    # V6.2-A 스크리닝 필드
    market_cap: int = 0           # 시가총액 (원)
    prev_volume: int = 0          # 전일 거래량
    today_volume: int = 0         # 금일 누적 거래량
    change_rate: float = 0.0      # 등락률 (%)
    high_52w: int = 0             # 52주 최고가


@dataclass
class CandidateStock:
    """Candidate Pool 종목 데이터"""
    stock_code: str
    stock_name: str
    added_time: datetime
    trading_value: int = 0  # 누적 거래대금 (원)
    current_price: int = 0
    is_active: bool = False  # Active Pool 여부

    def __hash__(self):
        return hash(self.stock_code)


@dataclass
class WatchlistEntry:
    """V6.2-B: Watchlist (당일 주도주 후보) 항목"""
    stock_code: str
    stock_name: str
    first_seen: datetime      # 최초 조건검색 편입 시각
    last_checked: datetime    # 마지막 5필터 체크 시각
    check_count: int = 0      # 필터 체크 횟수
    last_passed: bool = False # 마지막 필터 통과 여부

    # V6.2-D: 52주 고점 대비 비율 (조기 신호 허용 판별용)
    high_52w_ratio: float = 0.0


class AutoScreener:
    """
    V6.2-G: 주도주 자동 선별 (3단계 Pool 구조)

    - Watchlist Pool: 조건검색 포착 종목 (AUTO: 50개 / SIGNAL_ALERT: 무제한)
    - Candidate Pool: 5필터 통과 종목 (AUTO: 20개 / SIGNAL_ALERT: 무제한)
    - Active Pool: 거래대금 상위 종목 (AUTO: 10개 / SIGNAL_ALERT: 무제한)
    """

    def __init__(
        self,
        market_api: "MarketAPI",
        settings: Optional[RiskSettings] = None,
        position_manager: Optional["PositionManager"] = None,
    ):
        """
        Args:
            market_api: 시세 API 클라이언트
            settings: 리스크 설정 (기본값 사용 시 None)
            position_manager: 포지션 매니저 (강등 예외 처리용)
        """
        self._market_api = market_api
        self._settings = settings or RiskSettings()
        self._position_manager = position_manager
        self._logger = get_logger(__name__)

        # Candidate Pool (포착된 종목)
        self._candidate_pool: Dict[str, CandidateStock] = {}

        # Active Pool (거래대금 상위 종목)
        self._active_pool: Set[str] = set()

        # V6.2-B: Watchlist (당일 주도주 후보 - 조건검색 포착 이력)
        self._watchlist: Dict[str, WatchlistEntry] = {}
        self._watchlist_max_size: int = getattr(
            self._settings, 'watchlist_max_size', 50
        )  # 기본 50개

        # Pool 제한 기본값
        self._candidate_max_size: int = self._settings.candidate_pool_max_stocks  # 기본 20개
        self._active_max_size: int = self._settings.auto_universe_max_stocks  # 기본 10개

        # V6.2-C: SIGNAL_ALERT 모드 Pool 무제한 설정
        from src.utils.config import TradingMode
        if self._settings.trading_mode == TradingMode.SIGNAL_ALERT:
            self._watchlist_max_size = 9999
            self._candidate_max_size = 9999
            self._active_max_size = 9999
            self._logger.info(
                f"[SIGNAL_ALERT] Pool 무제한 모드: Watchlist={self._watchlist_max_size}, "
                f"Candidate={self._candidate_max_size}, Active={self._active_max_size}"
            )

        # C6 Fix: Watchlist Race Condition 방지 Lock
        self._watchlist_lock = asyncio.Lock()

        # 일일 리셋 추적
        self._last_reset_date: Optional[date] = None

        # 이미 처리한 종목 (중복 처리 방지)
        self._processed_today: Set[str] = set()

        # 마지막 순위 갱신 시간
        self._last_ranking_update: Optional[datetime] = None

        # V6.2-R: Active Pool 변경 콜백 (Tier 승격/강등용)
        # callback(promoted: Set[str], demoted: Set[str]) -> Awaitable[None]
        self._on_active_pool_changed: Optional[Callable[[Set[str], Set[str]], Awaitable[None]]] = None

    def set_active_pool_callback(
        self,
        callback: Callable[[Set[str], Set[str]], Awaitable[None]]
    ) -> None:
        """
        V6.2-R: Active Pool 변경 콜백 설정

        Args:
            callback: (promoted_codes, demoted_codes) → Awaitable[None]
        """
        self._on_active_pool_changed = callback
        self._logger.info("[V6.2-R] Active Pool 변경 콜백 등록")

    def set_position_manager(self, position_manager: "PositionManager") -> None:
        """포지션 매니저 설정 (지연 주입)"""
        self._position_manager = position_manager

    def reset_daily(self) -> None:
        """일일 리셋 (장 시작 전 호출)"""
        today = date.today()
        if self._last_reset_date != today:
            self._candidate_pool.clear()
            self._active_pool.clear()
            self._watchlist.clear()  # V6.2-B: Watchlist도 리셋
            self._processed_today.clear()
            self._last_reset_date = today
            self._last_ranking_update = None
            self._logger.info("[AutoScreener] 일일 리셋 완료 (Watchlist 포함)")

    async def on_condition_signal(
        self,
        stock_code: str,
        stock_name: str,
    ) -> FilterResult:
        """
        조건검색 편입 신호 처리

        1. 기본 필터링 (갭, 20일 고점)
        2. Candidate Pool 등록 (최대 20개)
        3. Active Pool 갱신

        Args:
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            FilterResult: 필터링 결과
        """
        # 일일 리셋 체크
        self.reset_daily()

        # V6.2-H: 중복 처리 방지 (모드별 분기)
        from src.utils.config import TradingMode
        is_signal_alert_mode = self._settings.trading_mode == TradingMode.SIGNAL_ALERT

        if is_signal_alert_mode:
            # SIGNAL_ALERT 모드: 이미 Active Pool에 있으면 중복 처리 방지
            # 필터 실패 후 재시도 허용 (processed_today는 성공 시에만 등록)
            if stock_code in self._active_pool:
                return FilterResult(
                    passed=False,
                    reason="already_in_active_pool",
                    details={"message": "이미 Active Pool에 등록된 종목"}
                )
        else:
            # AUTO_UNIVERSE 모드: 기존 로직 유지 (한번 처리하면 재처리 방지)
            if stock_code in self._processed_today:
                return FilterResult(
                    passed=False,
                    reason="already_processed",
                    details={"message": "이미 오늘 처리된 종목"}
                )
            self._processed_today.add(stock_code)

        self._logger.info(
            f"[AutoScreener] 신호 수신: {stock_name}({stock_code}) - 필터링 시작"
        )

        # ========== 종목 데이터 조회 ==========
        try:
            screen_data = await self._fetch_screen_data(stock_code, stock_name)
        except Exception as e:
            self._logger.error(f"[AutoScreener] 데이터 조회 실패: {e}")
            return FilterResult(
                passed=False,
                reason="data_fetch_error",
                details={"error": str(e)}
            )

        # ========== V6.2-D: Watchlist 엔트리에 52주 고점 비율 저장 ==========
        if stock_code in self._watchlist and screen_data.high_52w > 0:
            high_52w_ratio = screen_data.current_price / screen_data.high_52w
            self._watchlist[stock_code].high_52w_ratio = high_52w_ratio
            # 로깅 (조기 신호 대상인 경우만)
            if high_52w_ratio >= self._settings.near_52w_high_ratio:
                self._logger.info(
                    f"[V6.2-D] 52주 고점 근접: {stock_name}({stock_code}) "
                    f"{high_52w_ratio*100:.1f}% (조기 신호 허용)"
                )

        # ========== V6.2-A 스크리닝 필터 ==========
        v62a_result = self._check_v62a_filters(screen_data)
        if not v62a_result.passed:
            self._logger.info(
                f"[AutoScreener] {stock_name} V6.2-A 탈락: {v62a_result.reason}"
            )
            return v62a_result

        # ========== 기본 필터링 (갭 + 20일 고점) ==========
        chart_result = self._check_chart_position_filter(screen_data)
        if not chart_result.passed:
            self._logger.info(
                f"[AutoScreener] {stock_name} 탈락: {chart_result.reason}"
            )
            return chart_result

        # ========== Candidate Pool 등록 ==========
        candidate_result = self._add_to_candidate_pool(screen_data)
        if not candidate_result.passed:
            self._logger.info(
                f"[AutoScreener] {stock_name} Candidate Pool 등록 실패: {candidate_result.reason}"
            )
            return candidate_result

        # ========== Active Pool 갱신 ==========
        self._update_active_pool()

        # Active Pool 여부 확인
        is_active = stock_code in self._active_pool

        # V6.2-H: SIGNAL_ALERT 모드에서 성공 시 processed_today 등록
        if is_signal_alert_mode:
            self._processed_today.add(stock_code)

        self._logger.info(
            f"[AutoScreener] {stock_name}({stock_code}) Candidate Pool 등록 완료 "
            f"(Candidate: {len(self._candidate_pool)}/{self._candidate_max_size}, "
            f"Active: {len(self._active_pool)}/{self._active_max_size}, "
            f"거래대금: {screen_data.trading_value:,}원, "
            f"Active여부: {is_active})"
        )

        return FilterResult(
            passed=is_active,  # Active Pool에 들어가야 실제 매매 가능
            reason="candidate_registered" if not is_active else "active",
            details={
                "trading_value": screen_data.trading_value,
                "is_active": is_active,
                "candidate_count": len(self._candidate_pool),
                "active_count": len(self._active_pool),
            }
        )

    def _add_to_candidate_pool(self, data: StockScreenData) -> FilterResult:
        """
        Candidate Pool에 종목 추가

        최대 20개 제한, 초과 시 거래대금 낮은 종목 제거
        """
        max_candidates = self._candidate_max_size

        # 새 후보 생성
        new_candidate = CandidateStock(
            stock_code=data.stock_code,
            stock_name=data.stock_name,
            added_time=datetime.now(),
            trading_value=data.trading_value,
            current_price=data.current_price,
        )

        # 이미 있으면 업데이트
        if data.stock_code in self._candidate_pool:
            self._candidate_pool[data.stock_code].trading_value = data.trading_value
            self._candidate_pool[data.stock_code].current_price = data.current_price
            return FilterResult(passed=True, reason="updated")

        # Pool 여유 있으면 바로 추가
        if len(self._candidate_pool) < max_candidates:
            self._candidate_pool[data.stock_code] = new_candidate
            return FilterResult(passed=True, reason="added")

        # Pool 꽉 찼으면 거래대금 가장 낮은 종목과 비교
        min_trading_value_code = min(
            self._candidate_pool.keys(),
            key=lambda k: self._candidate_pool[k].trading_value
        )
        min_trading_value = self._candidate_pool[min_trading_value_code].trading_value

        if data.trading_value > min_trading_value:
            # 기존 최저 거래대금 종목 제거 (Active Pool이 아닌 경우만)
            if min_trading_value_code not in self._active_pool:
                removed = self._candidate_pool.pop(min_trading_value_code)
                self._candidate_pool[data.stock_code] = new_candidate
                self._logger.info(
                    f"[AutoScreener] Candidate 교체: {removed.stock_name} 제거 → {data.stock_name} 추가"
                )
                return FilterResult(passed=True, reason="replaced")

        return FilterResult(
            passed=False,
            reason="candidate_pool_full",
            details={
                "current_count": len(self._candidate_pool),
                "max_stocks": max_candidates,
                "min_trading_value": min_trading_value,
                "new_trading_value": data.trading_value,
            }
        )

    def _update_active_pool(self) -> None:
        """
        Active Pool 갱신 (거래대금 상위 N개)

        포지션 보유 중인 종목은 강등하지 않음
        """
        max_active = self._active_max_size

        # 포지션 보유 중인 종목 코드
        position_codes: Set[str] = set()
        if self._position_manager:
            position_codes = set(self._position_manager.get_position_codes())

        # 거래대금 순으로 정렬
        sorted_candidates = sorted(
            self._candidate_pool.values(),
            key=lambda c: c.trading_value,
            reverse=True
        )

        # 새 Active Pool 구성
        new_active: Set[str] = set()

        # 1. 포지션 보유 종목은 무조건 유지
        for code in position_codes:
            if code in self._candidate_pool:
                new_active.add(code)

        # 2. 나머지는 거래대금 순으로 채움
        for candidate in sorted_candidates:
            if len(new_active) >= max_active:
                break
            if candidate.stock_code not in new_active:
                new_active.add(candidate.stock_code)

        # Active 상태 업데이트
        for code, candidate in self._candidate_pool.items():
            candidate.is_active = code in new_active

        # 변경 로깅
        demoted = self._active_pool - new_active
        promoted = new_active - self._active_pool

        if promoted:
            self._logger.info(f"[AutoScreener] Active 승격: {promoted}")
        if demoted:
            self._logger.info(f"[AutoScreener] Active 강등: {demoted}")

        self._active_pool = new_active

        # V6.2-R: Active Pool 변경 시 콜백 호출 (Tier 승격/강등)
        if (promoted or demoted) and self._on_active_pool_changed:
            asyncio.create_task(
                self._on_active_pool_changed(promoted, demoted)
            )

    async def update_rankings(self) -> None:
        """
        거래대금 순위 갱신 (주기적 호출)

        Candidate Pool 종목들의 최신 거래대금을 조회하고 Active Pool 재정렬
        """
        if not self._candidate_pool:
            return

        self._logger.info(
            f"[AutoScreener] 거래대금 순위 갱신 시작 (Candidate: {len(self._candidate_pool)}개)"
        )

        # 각 종목의 최신 거래대금 조회
        for stock_code in list(self._candidate_pool.keys()):
            try:
                _, trading_value = await self._get_daily_data(stock_code)
                if stock_code in self._candidate_pool:
                    self._candidate_pool[stock_code].trading_value = trading_value
            except Exception as e:
                self._logger.warning(
                    f"[AutoScreener] {stock_code} 거래대금 조회 실패: {e}"
                )

        # Active Pool 재정렬
        old_active = self._active_pool.copy()
        self._update_active_pool()

        # 변경 있으면 로깅
        if old_active != self._active_pool:
            self._logger.info(
                f"[AutoScreener] Active Pool 변경: {self._get_active_pool_summary()}"
            )

        self._last_ranking_update = datetime.now()

    def _get_active_pool_summary(self) -> str:
        """Active Pool 요약 문자열"""
        items = []
        for code in self._active_pool:
            if code in self._candidate_pool:
                c = self._candidate_pool[code]
                items.append(f"{c.stock_name}({c.trading_value // 100_000_000}억)")
        return ", ".join(items) if items else "없음"

    def _check_v62a_filters(self, data: StockScreenData) -> FilterResult:
        """
        V6.2-B 스크리닝 필터 (5필터)

        기본 필터:
        1. 시가총액: 1,000억 ~ 20조
        2. 등락률: +2% ~ +29.9%
        3. 장초반 거래대금: >= 200억

        Returns:
            FilterResult
        """
        # 1. 시가총액 필터 (1,000억 ~ 20조) - 항상 적용
        min_cap = self._settings.min_market_cap
        max_cap = self._settings.max_market_cap

        if data.market_cap > 0:
            if data.market_cap < min_cap:
                return FilterResult(
                    passed=False,
                    reason="market_cap_too_low",
                    details={
                        "market_cap": data.market_cap,
                        "min_market_cap": min_cap,
                        "message": f"시가총액 {data.market_cap // 100_000_000}억 < 최소 {min_cap // 100_000_000}억"
                    }
                )
            if data.market_cap > max_cap:
                return FilterResult(
                    passed=False,
                    reason="market_cap_too_high",
                    details={
                        "market_cap": data.market_cap,
                        "max_market_cap": max_cap,
                        "message": f"시가총액 {data.market_cap // 100_000_000}억 > 최대 {max_cap // 100_000_000}억"
                    }
                )

        # 2. 등락률 필터 (+2% ~ +29.9%) - 항상 적용
        min_change = self._settings.min_change_rate
        max_change = self._settings.max_change_rate

        if data.change_rate < min_change:
            return FilterResult(
                passed=False,
                reason="change_rate_too_low",
                details={
                    "change_rate": data.change_rate,
                    "min_change_rate": min_change,
                    "message": f"등락률 {data.change_rate:.1f}% < 최소 {min_change}%"
                }
            )
        if data.change_rate > max_change:
            return FilterResult(
                passed=False,
                reason="change_rate_too_high",
                details={
                    "change_rate": data.change_rate,
                    "max_change_rate": max_change,
                    "message": f"등락률 {data.change_rate:.1f}% > 최대 {max_change}% (상한가 근접)"
                }
            )

        # 3. 장초반 거래대금 필터 (>= 200억)
        min_morning_value = self._settings.min_morning_value

        if data.trading_value < min_morning_value:
            return FilterResult(
                passed=False,
                reason="trading_value_too_low",
                details={
                    "trading_value": data.trading_value,
                    "min_morning_value": min_morning_value,
                    "message": f"거래대금 {data.trading_value // 100_000_000}억 < 최소 {min_morning_value // 100_000_000}억"
                }
            )

        # 모든 필터 통과
        return FilterResult(passed=True)

    def _check_chart_position_filter(self, data: StockScreenData) -> FilterResult:
        """
        기본 필터링: Chart Position Filter

        조건:
        1. 현재가 >= 20일 최고가 * 0.90 (고점권 근처)
        2. 시가 갭 < 15% (과도한 갭업 제외)

        Returns:
            FilterResult
        """
        # 1. 20일 고점 대비 위치 체크
        if data.high_20d > 0:
            high20_ratio = data.current_price / data.high_20d
            min_ratio = self._settings.high20_ratio_min  # 0.90

            if high20_ratio < min_ratio:
                return FilterResult(
                    passed=False,
                    reason="chart_position_low",
                    details={
                        "current_price": data.current_price,
                        "high_20d": data.high_20d,
                        "ratio": high20_ratio,
                        "min_ratio": min_ratio,
                        "message": f"20일 고점 대비 {high20_ratio*100:.1f}% 위치 (최소 {min_ratio*100:.0f}%)"
                    }
                )

        # 2. 시가 갭 체크
        if data.prev_close > 0:
            gap_rate = (data.open_price - data.prev_close) / data.prev_close
            max_gap = self._settings.gap_limit_max  # 0.15 (15%)

            if gap_rate >= max_gap:
                return FilterResult(
                    passed=False,
                    reason="gap_too_large",
                    details={
                        "open_price": data.open_price,
                        "prev_close": data.prev_close,
                        "gap_rate": gap_rate,
                        "max_gap": max_gap,
                        "message": f"시가 갭 {gap_rate*100:.1f}% (최대 {max_gap*100:.0f}%)"
                    }
                )

        return FilterResult(passed=True)

    async def _fetch_screen_data(
        self,
        stock_code: str,
        stock_name: str,
    ) -> StockScreenData:
        """
        스크리닝에 필요한 데이터 조회

        Args:
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            StockScreenData
        """
        # 기본 정보 조회
        stock_info = await self._market_api.get_stock_info(stock_code)

        # 20일 최고가, 거래대금, 전일 거래량, 52주 최고가, 오늘 거래량, 등락률 조회 (일봉 API 사용)
        # V6.2-B 버그픽스: today_volume, change_rate도 일봉 API에서 가져옴 (ka10001 신뢰성 문제)
        high_20d, trading_value, prev_volume, high_52w, today_volume, change_rate = await self._get_daily_data_v62a(stock_code)

        # 시가총액 조회 (stock_info에서)
        market_cap = getattr(stock_info, 'market_cap', 0) or 0

        return StockScreenData(
            stock_code=stock_code,
            stock_name=stock_name,
            current_price=stock_info.current_price,
            open_price=stock_info.open_price,
            prev_close=stock_info.prev_close,
            trading_value=trading_value,
            high_20d=high_20d,
            # V6.2-A 필드
            market_cap=market_cap,
            prev_volume=prev_volume,
            today_volume=today_volume,
            change_rate=change_rate,
            high_52w=high_52w,
        )

    async def _get_daily_data(self, stock_code: str) -> tuple[int, int]:
        """
        20일 최고가 및 오늘 거래대금 조회 (일봉 API 사용)

        Args:
            stock_code: 종목코드

        Returns:
            (20일 최고가, 오늘 거래대금) 튜플 (원)
        """
        try:
            # 일봉 차트 조회 (ka10081)
            daily_candles = await self._market_api.get_daily_chart(
                stock_code, count=20
            )

            if daily_candles:
                high_20d = max(c.high_price for c in daily_candles)
                # 가장 최근 일봉 = 오늘 데이터 (trading_value 포함)
                today_trading_value = daily_candles[-1].trading_value
                return high_20d, today_trading_value

            # 일봉 데이터가 없으면 현재가 사용 (신규 상장 등)
            self._logger.warning(
                f"[AutoScreener] 일봉 데이터 없음, 현재가 사용: {stock_code}"
            )
            stock_info = await self._market_api.get_stock_info(stock_code)
            return stock_info.current_price, 0

        except Exception as e:
            self._logger.error(f"[AutoScreener] 일봉 데이터 조회 실패: {e}")
            # Fallback: 현재가 조회
            try:
                stock_info = await self._market_api.get_stock_info(stock_code)
                return stock_info.current_price, 0
            except Exception:
                return 0, 0

    async def _get_daily_data_v62a(self, stock_code: str) -> tuple[int, int, int, int, int, float]:
        """
        V6.2-A: 20일 최고가, 오늘 거래대금, 전일 거래량, 52주 최고가, 오늘 거래량, 등락률 조회

        Args:
            stock_code: 종목코드

        Returns:
            (20일 최고가, 오늘 거래대금, 전일 거래량, 52주 최고가, 오늘 거래량, 등락률) 튜플
        """
        try:
            # 일봉 차트 조회 (52주 = 약 260 거래일, 여유분 포함 270일)
            daily_candles = await self._market_api.get_daily_chart(
                stock_code, count=270
            )

            if daily_candles and len(daily_candles) >= 2:
                # 20일 최고가
                high_20d = max(c.high_price for c in daily_candles[-20:]) if len(daily_candles) >= 20 else max(c.high_price for c in daily_candles)

                # 52주 (260일) 최고가
                high_52w = max(c.high_price for c in daily_candles)

                # 가장 최근 일봉 = 오늘 데이터
                today_data = daily_candles[-1]
                today_trading_value = getattr(today_data, 'trading_value', 0) or 0

                # 전일 일봉 = 두 번째 최근 데이터
                prev_data = daily_candles[-2]
                prev_volume = getattr(prev_data, 'volume', 0) or 0

                # 오늘 거래량 (일봉 API에서 가져옴 - ka10001 volume 필드 미존재 버그 수정)
                today_volume = getattr(today_data, 'volume', 0) or 0

                # 오늘 등락률 (일봉 API의 trde_tern_rt - ka10001 prc_chng_rt보다 정확)
                change_rate = getattr(today_data, 'change_rate', 0.0) or 0.0

                return high_20d, today_trading_value, prev_volume, high_52w, today_volume, change_rate

            # 일봉 데이터가 없거나 부족하면 기본값 사용
            self._logger.warning(
                f"[AutoScreener] V6.2-A 일봉 데이터 부족: {stock_code}"
            )
            stock_info = await self._market_api.get_stock_info(stock_code)
            return stock_info.current_price, 0, 0, 0, 0, stock_info.change_rate

        except Exception as e:
            self._logger.error(f"[AutoScreener] V6.2-A 일봉 데이터 조회 실패: {e}")
            try:
                stock_info = await self._market_api.get_stock_info(stock_code)
                return stock_info.current_price, 0, 0, 0, 0, stock_info.change_rate
            except Exception:
                return 0, 0, 0, 0, 0, 0.0

    # ========== 공개 API ==========

    def is_active(self, stock_code: str) -> bool:
        """종목이 Active Pool에 있는지 확인 (매매 가능 여부)"""
        return stock_code in self._active_pool

    def is_candidate(self, stock_code: str) -> bool:
        """종목이 Candidate Pool에 있는지 확인"""
        return stock_code in self._candidate_pool

    @property
    def active_count(self) -> int:
        """Active Pool 종목 수"""
        return len(self._active_pool)

    @property
    def candidate_count(self) -> int:
        """Candidate Pool 종목 수"""
        return len(self._candidate_pool)

    @property
    def active_stocks(self) -> Set[str]:
        """Active Pool 종목 코드 세트"""
        return self._active_pool.copy()

    @property
    def candidate_stocks(self) -> Set[str]:
        """Candidate Pool 종목 코드 세트"""
        return set(self._candidate_pool.keys())

    def get_candidate_list(self) -> List[CandidateStock]:
        """Candidate Pool 종목 리스트 (거래대금 순)"""
        return sorted(
            self._candidate_pool.values(),
            key=lambda c: c.trading_value,
            reverse=True
        )

    def get_status(self) -> Dict:
        """현재 상태 반환"""
        return {
            "enabled": self._settings.auto_universe_enabled,
            "condition_seq": self._settings.auto_universe_condition_seq,
            "candidate_max": self._candidate_max_size,
            "active_max": self._active_max_size,
            "candidate_count": len(self._candidate_pool),
            "active_count": len(self._active_pool),
            "candidate_stocks": [
                {
                    "code": c.stock_code,
                    "name": c.stock_name,
                    "trading_value": c.trading_value,
                    "is_active": c.is_active,
                }
                for c in self.get_candidate_list()
            ],
            "active_stocks": list(self._active_pool),
            "last_ranking_update": self._last_ranking_update.isoformat() if self._last_ranking_update else None,
        }

    # ========== 하위 호환성 ==========

    @property
    def registered_count(self) -> int:
        """하위 호환: Active Pool 종목 수"""
        return self.active_count

    @property
    def registered_stocks(self) -> Set[str]:
        """하위 호환: Active Pool 종목 세트"""
        return self.active_stocks

    def is_registered(self, stock_code: str) -> bool:
        """하위 호환: Active Pool 여부"""
        return self.is_active(stock_code)

    # ========== V6.2-B: Watchlist (당일 주도주 후보) ==========

    def add_to_watchlist(
        self,
        stock_code: str,
        stock_name: str,
        high_52w_ratio: float = 0.0,
    ) -> bool:
        """
        V6.2-B: Watchlist에 종목 추가 (조건검색 편입 시 호출)

        - 중복 등록 무시
        - 최대 50개 제한 (초과 시 가장 오래된 항목 제거)

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            high_52w_ratio: V6.2-D 52주 고점 대비 현재가 비율

        Returns:
            새로 등록되었으면 True, 이미 있으면 False
        """
        # 이미 등록되어 있으면 무시
        if stock_code in self._watchlist:
            return False

        # 최대 개수 초과 시 가장 오래된 항목 제거 (FIFO)
        if len(self._watchlist) >= self._watchlist_max_size:
            oldest_code = min(
                self._watchlist.keys(),
                key=lambda k: self._watchlist[k].first_seen
            )
            removed = self._watchlist.pop(oldest_code)
            self._logger.info(
                f"[Watchlist] 최대 개수 초과 - 제거: {removed.stock_name}({oldest_code})"
            )

        # Watchlist에 추가
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)

        self._watchlist[stock_code] = WatchlistEntry(
            stock_code=stock_code,
            stock_name=stock_name,
            first_seen=now,
            last_checked=now,
            check_count=0,
            last_passed=False,
            high_52w_ratio=high_52w_ratio,  # V6.2-D
        )

        # V6.2-D: 52주 고점 근접 여부 로깅
        near_high_note = ""
        if high_52w_ratio >= self._settings.near_52w_high_ratio:
            near_high_note = f" [52주고점 {high_52w_ratio*100:.1f}%]"

        self._logger.info(
            f"[Watchlist] 등록: {stock_name}({stock_code}){near_high_note}, "
            f"현재 {len(self._watchlist)}개"
        )
        return True

    def is_in_watchlist(self, stock_code: str) -> bool:
        """V6.2-B: Watchlist 포함 여부 확인"""
        return stock_code in self._watchlist

    @property
    def watchlist_count(self) -> int:
        """Watchlist 종목 수"""
        return len(self._watchlist)

    @property
    def watchlist_stocks(self) -> Set[str]:
        """Watchlist 종목 코드 세트"""
        return set(self._watchlist.keys())

    async def revalidate_watchlist(self) -> List[str]:
        """
        V6.2-B: Watchlist 전체 재검증 (30초마다 호출)

        Candidate Pool에 없는 Watchlist 종목들을 5필터 재체크하여
        통과 시 Candidate Pool로 승격합니다.

        Returns:
            승격된 종목코드 리스트
        """
        promoted = []

        # C6 Fix: Lock 획득 후 Watchlist 접근
        async with self._watchlist_lock:
            for stock_code, entry in list(self._watchlist.items()):
                # 이미 Candidate Pool에 있으면 스킵
                if stock_code in self._candidate_pool:
                    continue

                try:
                    # 5필터 재체크
                    screen_data = await self._fetch_screen_data(stock_code, entry.stock_name)

                    # V6.2-A 스크리닝 필터
                    v62a_result = self._check_v62a_filters(screen_data)

                    # Chart Position 필터
                    chart_result = self._check_chart_position_filter(screen_data)

                    # 체크 기록 업데이트
                    entry.last_checked = datetime.now()
                    entry.check_count += 1
                    entry.last_passed = v62a_result.passed and chart_result.passed

                    if entry.last_passed:
                        # Candidate Pool로 승격
                        candidate_result = self._add_to_candidate_pool(screen_data)
                        if candidate_result.passed:
                            promoted.append(stock_code)
                            self._logger.info(
                                f"[Watchlist 승격] {entry.stock_name}({stock_code}) → Candidate Pool "
                                f"(재검증 {entry.check_count}회차)"
                            )

                except Exception as e:
                    self._logger.warning(
                        f"[Watchlist] 재검증 실패: {stock_code} - {e}"
                    )

        # 승격된 종목이 있으면 Active Pool도 갱신
        if promoted:
            self._update_active_pool()

        return promoted

    async def check_and_promote(self, stock_code: str) -> FilterResult:
        """
        V6.2-B: SNIPER_TRAP 신호 발생 시 즉시 필터 체크 + 승격

        Watchlist에 있는 종목에서 신호 발생 시 즉시 5필터를 체크하고,
        통과하면 Candidate + Active Pool로 승격 후 매수를 진행합니다.

        Args:
            stock_code: 종목코드

        Returns:
            FilterResult (passed=True이면 매수 진행 가능)
        """
        # C6 Fix: Lock 획득 후 Watchlist 접근
        async with self._watchlist_lock:
            # Watchlist에 없으면 실패
            if stock_code not in self._watchlist:
                return FilterResult(
                    passed=False,
                    reason="not_in_watchlist",
                    details={"message": "Watchlist에 없는 종목"}
                )

            entry = self._watchlist[stock_code]

            try:
                # 5필터 체크
                screen_data = await self._fetch_screen_data(stock_code, entry.stock_name)

                # V6.2-A 스크리닝 필터
                v62a_result = self._check_v62a_filters(screen_data)
                if not v62a_result.passed:
                    entry.last_checked = datetime.now()
                    entry.check_count += 1
                    entry.last_passed = False
                    return FilterResult(
                        passed=False,
                        reason=f"v62a_filter_failed: {v62a_result.reason}",
                        details=v62a_result.details
                    )

                # Chart Position 필터
                chart_result = self._check_chart_position_filter(screen_data)
                if not chart_result.passed:
                    entry.last_checked = datetime.now()
                    entry.check_count += 1
                    entry.last_passed = False
                    return FilterResult(
                        passed=False,
                        reason=f"chart_filter_failed: {chart_result.reason}",
                        details=chart_result.details
                    )

                # 필터 통과! Candidate + Active Pool로 즉시 승격
                entry.last_checked = datetime.now()
                entry.check_count += 1
                entry.last_passed = True

                # Candidate Pool 등록
                candidate_result = self._add_to_candidate_pool(screen_data)

                # V6.2-B 버그 수정: Active Pool 직접 수정 대신 _update_active_pool() 호출
                # - max_active 제한 준수
                # - 거래대금 순위 기반 선정
                self._update_active_pool()

                # Active Pool 진입 여부 확인
                is_now_active = stock_code in self._active_pool

                self._logger.info(
                    f"[Watchlist 즉시 승격] {entry.stock_name}({stock_code}) → "
                    f"{'Active Pool' if is_now_active else 'Candidate Pool'} "
                    f"(신호 발생 시 필터 통과)"
                )

                return FilterResult(
                    passed=True,
                    reason="watchlist_promoted",
                    details={
                        "stock_name": entry.stock_name,
                        "trading_value": screen_data.trading_value,
                        "check_count": entry.check_count,
                    }
                )

            except Exception as e:
                self._logger.error(
                    f"[Watchlist] 즉시 필터 체크 실패: {stock_code} - {e}"
                )
                return FilterResult(
                    passed=False,
                    reason="check_error",
                    details={"error": str(e)}
                )

    def get_watchlist_entry(self, stock_code: str) -> Optional[WatchlistEntry]:
        """
        V6.2-D: Watchlist 항목 조회

        Args:
            stock_code: 종목코드

        Returns:
            WatchlistEntry 또는 None (없는 경우)
        """
        return self._watchlist.get(stock_code)

    def get_watchlist_status(self) -> Dict:
        """Watchlist 상태 반환"""
        return {
            "count": len(self._watchlist),
            "max_size": self._watchlist_max_size,
            "stocks": [
                {
                    "code": e.stock_code,
                    "name": e.stock_name,
                    "first_seen": e.first_seen.strftime("%H:%M:%S"),
                    "check_count": e.check_count,
                    "last_passed": e.last_passed,
                    "in_candidate": e.stock_code in self._candidate_pool,
                    "high_52w_ratio": e.high_52w_ratio,  # V6.2-D
                }
                for e in sorted(
                    self._watchlist.values(),
                    key=lambda x: x.first_seen,
                    reverse=True
                )
            ],
        }
