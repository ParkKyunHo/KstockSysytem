"""
조건검색 신호 핸들러 (Phase 6E)

TradingEngine에서 조건검색 관련 로직을 분리합니다.

주요 기능:
- 조건검색 실시간 신호 처리 (_on_condition_signal_v31)
- 폴링 Fallback 신호 처리 (_on_polling_signal)
- 필터링 및 유니버스 등록 (_process_condition_signal_core)
- Auto-Universe 종목 등록 (_register_auto_universe_stock)
- V7 캔들 로딩 보장 (_ensure_candle_loaded_v7)
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Awaitable, Any, TYPE_CHECKING

from src.core.manual_command_handler import StockMode, ManualStockConfig
from src.core.realtime_data_manager import Tier
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.core.trading_engine import TradingEngine


@dataclass
class ConditionSearchCallbacks:
    """ConditionSearchHandler가 필요로 하는 외부 의존성 콜백"""
    # 상태
    is_startup_complete: Callable[[], bool]
    get_engine_state: Callable[[], str]
    get_market_status: Callable[[], str]
    # 구독 관리
    on_signal_received: Callable[[str], None]
    # 시장 API
    get_stock_name: Callable[[str], Awaitable[Optional[str]]]
    # ATR 알림
    register_atr_stock: Callable[[str, str], Awaitable[None]]
    get_atr_state: Callable[[str], Any]
    # 리스크 설정
    get_risk_settings: Callable[[], Any]
    # 유니버스/데이터
    is_in_universe: Callable[[str], bool]
    add_to_universe: Callable[..., None]
    get_candle_builder: Callable[[str], Any]
    add_candle_stock: Callable[[str], Any]
    register_stock: Callable[..., None]
    is_candle_loaded: Callable[[str], bool]
    load_historical_candles: Callable[[str], Awaitable[None]]
    promote_to_tier1: Callable[[str], Awaitable[Any]]
    # 포지션
    has_position: Callable[[str], bool]
    # 전략
    dispatch_condition_signal: Callable[[str, str, dict], Optional[str]]
    # 필터링
    on_condition_signal_filter: Callable[[str, str], Awaitable[Any]]
    # 텔레그램
    send_telegram: Callable[[str], Awaitable[None]]
    # 수동 종목
    get_manual_stocks: Callable[[], dict]


class ConditionSearchHandler:
    """조건검색 신호 핸들러"""

    def __init__(self, callbacks: ConditionSearchCallbacks):
        self._cb = callbacks
        self._logger = get_logger(__name__)

    async def on_condition_signal_v31(self, signal) -> None:
        """PRD v3.1: Auto-Universe 조건검색 신호 처리"""
        if not self._cb.is_startup_complete():
            self._logger.debug(f"[조건검색] Startup 미완료 - 신호 무시: {signal.stock_code}")
            return

        self._cb.on_signal_received(signal.condition_seq)

        risk_settings = self._cb.get_risk_settings()
        atr_alert_enabled = getattr(risk_settings, 'atr_alert_enabled', True)
        atr_alert_seq = int(risk_settings.atr_alert_condition_seq) if hasattr(risk_settings, 'atr_alert_condition_seq') else 0

        if int(signal.condition_seq) == atr_alert_seq:
            if signal.is_buy_signal:
                if self._cb.get_market_status() == "REGULAR":
                    stock_name = signal.stock_name
                    if not stock_name or stock_name == signal.stock_code:
                        try:
                            stock_name = await self._cb.get_stock_name(signal.stock_code)
                        except Exception:
                            stock_name = signal.stock_code

                    if atr_alert_enabled:
                        await self._cb.register_atr_stock(signal.stock_code, stock_name)
            else:
                state = self._cb.get_atr_state(signal.stock_code)
                if state:
                    self._logger.info(
                        f"[ATR Alert] 조건검색 편출 - 감시 유지: {state.stock_name}({signal.stock_code})"
                    )

            expected_seq = risk_settings.auto_universe_condition_seq
            if str(atr_alert_seq) != str(expected_seq):
                return

        await self.process_condition_signal_core(signal)

    async def on_polling_signal(self, stock_code: str) -> None:
        """폴링 Fallback에서 감지된 종목 처리"""
        self._logger.info(f"[Polling Fallback] 신규 종목 신호: {stock_code}")

        from src.api.websocket import SignalEvent
        risk_settings = self._cb.get_risk_settings()
        expected_seq = risk_settings.auto_universe_condition_seq
        signal = SignalEvent(
            stock_code=stock_code,
            stock_name="",
            signal_type="I",
            condition_seq=expected_seq,
            timestamp="",
        )

        await self.on_condition_signal_v31(signal)

    async def process_condition_signal_core(self, signal) -> None:
        """조건검색 신호 실제 처리 (core 로직)"""
        stock_code = signal.stock_code
        risk_settings = self._cb.get_risk_settings()

        from src.utils.config import TradingMode
        if risk_settings.trading_mode == TradingMode.MANUAL_ONLY:
            self._logger.debug(f"[MANUAL_ONLY] 조건검색 신호 무시: {stock_code}")
            return

        expected_seq = risk_settings.auto_universe_condition_seq
        if signal.condition_seq != expected_seq:
            self._logger.debug(
                f"[V7.0] 다른 조건검색식 신호 무시: seq={signal.condition_seq} "
                f"(설정: {expected_seq})"
            )
            return

        if not signal.is_buy_signal:
            self._logger.debug(f"[V7.0] 이탈 신호 무시: {stock_code}")
            return

        if self._cb.get_market_status() != "REGULAR":
            self._logger.debug(f"[V7.0] 장중 아님 - 신호 무시: {stock_code}")
            return

        if self._cb.get_engine_state() != "RUNNING":
            self._logger.debug(f"[V7.0] 엔진 미실행 - 신호 무시: {stock_code}")
            return

        stock_name = signal.stock_name
        if not stock_name or stock_name == stock_code:
            try:
                stock_name = await self._cb.get_stock_name(stock_code)
            except Exception as e:
                self._logger.warning(f"[V7.0] 종목명 조회 실패: {stock_code} - {e}")
                stock_name = stock_code

        self._logger.info(
            f"[V7.0] 조건검색 신호: {stock_name}({stock_code}) - 필터링 시작"
        )

        # Universe/CandleBuilder 등록 (전략 무관 인프라)
        if not self._cb.is_in_universe(stock_code):
            self._cb.add_to_universe(
                stock_code=stock_code,
                stock_name=stock_name,
                metadata={"source": "condition_search", "tier": "TIER_2"},
            )
            if self._cb.get_candle_builder(stock_code) is None:
                self._cb.add_candle_stock(stock_code)
            self._cb.register_stock(stock_code, Tier.TIER_2, stock_name)

        # 전략 디스패치 (V7 → SignalPool, V6 → Watchlist)
        handled_by = self._cb.dispatch_condition_signal(
            stock_code, stock_name, {"source": "condition_search"}
        )

        # 캔들 로딩 (V7 Pre-Check/Confirm-Check 대비)
        if handled_by:
            candle_loaded = await self.ensure_candle_loaded_v7(stock_code)
            self._logger.info(
                f"[Phase 3-1] 조건검색 신호 처리: {stock_name}({stock_code}) "
                f"→ {handled_by} (캔들: {'OK' if candle_loaded else 'PENDING'})"
            )

            from src.utils.config import TradingMode
            if risk_settings.trading_mode == TradingMode.SIGNAL_ALERT:
                return

        if not self._cb.is_candle_loaded(stock_code):
            await self._cb.load_historical_candles(stock_code)

        if self._cb.has_position(stock_code):
            self._logger.debug(f"[V7.0] 이미 보유 중: {stock_code}")
            return

        # 3단계 필터링 실행 (AutoScreener)
        try:
            result = await self._cb.on_condition_signal_filter(stock_code, stock_name)
        except Exception as e:
            self._logger.error(f"[V7.0] 필터링 에러: {e}")
            return

        passed_reasons = ("active", "candidate_registered", "updated", "added", "replaced")

        if result.reason not in passed_reasons:
            detail_msg = result.details.get('message', '') if result.details else ''
            self._logger.info(
                f"[V7.0] 필터링 탈락: {stock_name}({stock_code}) - {result.reason} | {detail_msg}"
            )
            if result.reason == "daily_limit":
                await self._cb.send_telegram(
                    f"[Auto-Universe] 당일 최대 종목 수 도달\n"
                    f"종목: {stock_name}({stock_code})\n"
                    f"사유: {result.details.get('message', '')}"
                )
            return

        # 6필터 통과 - 유니버스 등록
        await self.register_auto_universe_stock(
            stock_code=stock_code,
            stock_name=stock_name,
            filter_details=result.details,
        )

    async def register_auto_universe_stock(
        self,
        stock_code: str,
        stock_name: str,
        filter_details: dict,
    ) -> None:
        """PRD v3.1: Auto-Universe 필터링 통과 종목 등록"""
        if self._cb.is_in_universe(stock_code):
            self._logger.debug(f"[V7.0] 이미 모니터링 중: {stock_code}")
            return

        self._logger.info(f"[V7.0] Auto-Universe 등록: {stock_code} {stock_name}")

        risk_settings = self._cb.get_risk_settings()

        # 1. 유니버스에 추가
        self._cb.add_to_universe(
            stock_code=stock_code,
            stock_name=stock_name,
            metadata={
                "source": "auto_universe",
                "condition_seq": risk_settings.auto_universe_condition_seq,
                **filter_details,
            },
        )
        self._logger.info(f"[Auto-Universe] Step 1/5: 유니버스 추가 완료 - {stock_code}")

        # 2. CandleBuilder 추가
        if self._cb.get_candle_builder(stock_code) is None:
            builder = self._cb.add_candle_stock(stock_code)
            self._logger.info(
                f"[Auto-Universe] Step 2/5: CandleBuilder 생성 - {stock_code}, "
                f"콜백설정={builder.on_candle_complete is not None}"
            )
        else:
            self._logger.info(f"[Auto-Universe] Step 2/5: CandleBuilder 이미 존재 - {stock_code}")

        # 3. 수동 종목 설정에 AUTO 모드로 등록
        manual_stocks = self._cb.get_manual_stocks()
        manual_stocks[stock_code] = ManualStockConfig(
            stock_code=stock_code,
            stock_name=stock_name,
            mode=StockMode.AUTO,
            added_at=datetime.now(),
        )
        self._logger.info(f"[Auto-Universe] Step 3/5: AUTO 모드 설정 - {stock_code}")

        # 4. RealTimeDataManager에 Tier 1로 등록 (고속 폴링)
        self._cb.register_stock(stock_code, Tier.TIER_1, stock_name)
        self._logger.info(f"[Auto-Universe] Step 4/5: Tier 1 폴링 등록 - {stock_code}")

        # 5. 과거 캔들 로드
        await self._cb.promote_to_tier1(stock_code)
        self._logger.info(f"[Auto-Universe] Step 5/5: 과거 캔들 로드 완료 - {stock_code}")

        # 6. 텔레그램 알림
        trading_value = filter_details.get("trading_value", 0)
        high20_ratio = filter_details.get("high_20d_ratio", 0)
        registered_count = filter_details.get("registered_count", 0)

        await self._cb.send_telegram(
            f"✅ [Auto-Universe] 종목 자동 등록\n"
            f"종목: {stock_name}({stock_code})\n"
            f"거래대금: {trading_value / 100_000_000:.0f}억원\n"
            f"20일고점비: {high20_ratio * 100:.1f}%\n"
            f"등록 현황: {registered_count}/{risk_settings.auto_universe_max_stocks}\n\n"
            f"⏳ SNIPER_TRAP 신호 대기 중..."
        )

        self._logger.info(
            f"[V7.0] Auto-Universe 등록 완료: {stock_name}({stock_code}) "
            f"(Tier 1 고속 폴링 시작)"
        )

    async def ensure_candle_loaded_v7(self, stock_code: str, timeout: float = 5.0) -> bool:
        """V7 SignalPool 종목의 캔들 로딩 보장"""
        if self._cb.is_candle_loaded(stock_code):
            return True

        try:
            return await asyncio.wait_for(
                self._cb.promote_to_tier1(stock_code),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            self._logger.warning(f"[V7] 캔들 로딩 타임아웃: {stock_code} ({timeout}초)")
            return False
        except Exception as e:
            self._logger.warning(f"[V7] 캔들 로딩 실패: {stock_code} - {e}")
            return False
