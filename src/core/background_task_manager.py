"""
백그라운드 태스크 관리 모듈

TradingEngine에서 추출된 비동기 루프 태스크 관리.
Phase 4-B: ~450줄 절감.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Callable, Awaitable, List, Dict, Any, Set
import logging

from src.core.realtime_data_manager import Tier


@dataclass
class BackgroundTaskCallbacks:
    """BackgroundTaskManager → TradingEngine 콜백"""

    get_engine_state: Callable[[], str]
    check_and_handle_market_open: Callable[[], Awaitable[None]]
    check_daily_reset: Callable[[], Awaitable[None]]
    sync_positions: Callable[[], Awaitable[None]]
    verify_tier1_consistency: Callable[[], Awaitable[int]]
    cancel_pending_orders_at_eod: Callable[[], Awaitable[None]]
    get_market_status: Callable[[], str]
    build_v7_callbacks: Callable[[], Any]
    collect_strategy_tasks: Callable[[Dict], List[asyncio.Task]]


class BackgroundTaskManager:
    """
    백그라운드 비동기 루프 태스크 관리.

    TradingEngine의 10개 루프 메서드와 lifecycle 관리를 캡슐화합니다.
    - 장 시작 스케줄러
    - EOD 알림 / 미체결 주문 정리
    - 시스템 상태 모니터링
    - 포지션 동기화
    - 거래대금 순위 갱신 / Watchlist 재검증
    - highest_price 주기적 저장
    """

    # 백그라운드 태스크 간격 상수
    STATUS_MONITOR_INTERVAL: int = 60
    HIGHEST_PRICE_PERSIST_INTERVAL: int = 30
    STATUS_REPORT_INTERVAL: int = 30

    def __init__(
        self,
        config,
        risk_settings,
        position_manager,
        risk_manager,
        trade_repo,
        data_manager,
        market_schedule,
        auto_screener,
        strategy_orchestrator,
        universe,
        market_api,
        candle_manager,
        telegram,
        logger: logging.Logger,
        callbacks: BackgroundTaskCallbacks,
    ):
        self._config = config
        self._risk_settings = risk_settings
        self._position_manager = position_manager
        self._risk_manager = risk_manager
        self._trade_repo = trade_repo
        self._data_manager = data_manager
        self._market_schedule = market_schedule
        self._auto_screener = auto_screener
        self._strategy_orchestrator = strategy_orchestrator
        self._universe = universe
        self._market_api = market_api
        self._candle_manager = candle_manager
        self._telegram = telegram
        self._logger = logger
        self._callbacks = callbacks

    # =========================================
    # 태스크 시작
    # =========================================

    def start_all(self, tasks: List[asyncio.Task]) -> None:
        """백그라운드 태스크 시작 - tasks 리스트에 추가"""
        # 장 종료 알림 태스크
        tasks.append(asyncio.create_task(self._eod_alert_loop()))

        # PRD v3.2.1: 장 종료 미체결 주문 정리 태스크
        tasks.append(asyncio.create_task(self._eod_pending_order_cleanup_loop()))

        # 시스템 상태 모니터링 태스크
        tasks.append(asyncio.create_task(self._status_monitor_loop()))

        # PRD v2.0: 포지션 동기화 루프 (1분마다 HTS 매매 감지)
        tasks.append(asyncio.create_task(self._position_sync_loop()))

        # PRD v3.1+: 거래대금 순위 갱신 루프 (Auto-Universe)
        if self._risk_settings.auto_universe_enabled:
            tasks.append(asyncio.create_task(self._ranking_update_loop()))

        # V6.2-B: Watchlist 재검증 루프 (30초마다)
        if self._risk_settings.auto_universe_enabled:
            tasks.append(asyncio.create_task(self._watchlist_revalidation_loop()))

        # PRD v3.0: highest_price 주기적 저장 (30초마다)
        tasks.append(asyncio.create_task(self._highest_price_persist_loop()))

        # PRD v3.0: 시장 감시 (KOSDAQ 급락 감지) - Phase 4-D: MarketMonitor
        # TODO: ka20001 API 파라미터 수정 후 재활성화
        # tasks.append(asyncio.create_task(self._market_monitor.market_watcher_loop()))
        self._logger.info("[MarketWatcher] 임시 비활성화 (API 파라미터 수정 필요)")

        # =========================================
        # V7.0 Purple-ReAbs 배경 태스크 (V7SignalCoordinator)
        # =========================================
        if self._strategy_orchestrator:
            # Phase 3-1: StrategyOrchestrator를 통한 백그라운드 태스크 수집
            v7_callbacks = self._callbacks.build_v7_callbacks()
            strategy_tasks = self._callbacks.collect_strategy_tasks({
                "v7_callbacks": v7_callbacks,
            })
            tasks.extend(strategy_tasks)
            if strategy_tasks:
                self._logger.info(
                    f"[Phase 3-1] 전략 백그라운드 태스크 {len(strategy_tasks)}개 시작"
                )

        # V6.2-K: 장 시작 스케줄러 (tick 의존성 없이 09:00:05 조건검색 재구독)
        tasks.append(asyncio.create_task(self._market_open_scheduler_loop()))
        self._logger.info("[V6.2-K] 장 시작 스케줄러 태스크 시작")

        # Note: _promotion_timeout_loop 제거됨 (조건식 비활성화)
        # Note: _position_check_loop 제거됨
        # 포지션 체크는 RealTimeDataManager의 on_market_data 콜백에서 처리

    # =========================================
    # 루프 메서드
    # =========================================

    async def _chunked_sleep(self, total_seconds: float, chunk: float = 3600) -> None:
        """긴 대기를 chunk 단위로 분할 (graceful shutdown 대응)"""
        remaining = total_seconds
        while remaining > 0:
            await asyncio.sleep(min(remaining, chunk))
            remaining -= chunk

    async def _market_open_scheduler_loop(self) -> None:
        """
        V6.2-K: 장 시작 시 조건검색 재구독 스케줄러 (tick 의존성 제거)

        tick이 없어도 09:00:05에 정확히 조건검색 재구독을 실행합니다.
        """
        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                now = datetime.now()

                # 오늘 09:00:05 계산
                target_time = datetime.combine(
                    now.date(),
                    time(hour=9, minute=0, second=5)
                )

                # 이미 지났으면 내일로
                if now >= target_time:
                    target_time = target_time + timedelta(days=1)

                # 대기 (최대 1시간씩, graceful shutdown 대응)
                wait_seconds = (target_time - now).total_seconds()
                if wait_seconds > 0:
                    self._logger.debug(
                        f"[V6.2-K] 다음 장 시작 체크까지 {wait_seconds:.0f}초 대기"
                    )
                    await asyncio.sleep(min(wait_seconds, 3600))
                    continue

                # 장 시작 처리 실행
                self._logger.info("[V6.2-K] 09:00:05 장 시작 처리 시작")
                await self._callbacks.check_and_handle_market_open()

                # 실행 후 1분 대기 (중복 실행 방지)
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                self._logger.info("[V6.2-K] 장 시작 스케줄러 종료")
                break
            except Exception as e:
                self._logger.error(f"[V6.2-K] 장 시작 스케줄러 에러: {e}")
                await asyncio.sleep(60)

    async def _eod_alert_loop(self) -> None:
        """장 종료 알림"""
        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                now = datetime.now()
                alert_time = datetime.combine(now.date(), self._config.eod_alert_time)

                if now < alert_time:
                    wait_seconds = (alert_time - now).total_seconds()
                    await self._chunked_sleep(wait_seconds)
                else:
                    # 다음 날 알림
                    tomorrow_alert = alert_time + timedelta(days=1)
                    wait_seconds = (tomorrow_alert - now).total_seconds()
                    await self._chunked_sleep(wait_seconds)
                    continue

                # 장 종료 알림 전송
                if self._position_manager.get_position_count() > 0:
                    await self._telegram.send_eod_choice()

            except asyncio.CancelledError:
                self._logger.info("[EOD Alert] 장 종료 알림 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[EOD Alert] 에러: {e}")
                await asyncio.sleep(60)

    async def _eod_pending_order_cleanup_loop(self) -> None:
        """
        PRD v3.2.1: 장 종료 미체결 주문 정리

        15:25에 미체결 매도 주문을 모두 취소하고 야간 자동 결제 위험을 방지합니다.
        취소 후 포지션이 남아있으면 텔레그램으로 경고합니다.
        """
        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                now = datetime.now()
                cleanup_time = datetime.combine(now.date(), self._config.eod_pending_cleanup_time)

                if now < cleanup_time:
                    wait_seconds = (cleanup_time - now).total_seconds()
                    await self._chunked_sleep(wait_seconds)
                else:
                    # 다음 날 정리 시간
                    tomorrow_cleanup = cleanup_time + timedelta(days=1)
                    wait_seconds = (tomorrow_cleanup - now).total_seconds()
                    await self._chunked_sleep(wait_seconds)
                    continue

                # 미체결 매도 주문 정리
                await self._callbacks.cancel_pending_orders_at_eod()

            except asyncio.CancelledError:
                self._logger.info("[EOD Cleanup] 미체결 주문 정리 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[EOD Cleanup] 에러: {e}")
                await asyncio.sleep(60)

    async def _status_monitor_loop(self) -> None:
        """
        시스템 상태 모니터링 루프

        - 모니터링 종목이 없을 때 5분마다 텔레그램 알림
        - 30분마다 정상 운영 상태 보고
        """
        from src.core.market_schedule import MarketState

        empty_alert_count = 0
        status_report_counter = 0

        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                await asyncio.sleep(self.STATUS_MONITOR_INTERVAL)  # 1분마다 체크
                status_report_counter += 1

                # V6.2-B: 24시간 운영 대응 - 일일 Pool 리셋 체크 (07:40~07:50)
                await self._callbacks.check_daily_reset()

                # 종목 수 확인
                total_stocks = self._data_manager.total_count
                tier1_count = self._data_manager.tier1_count
                tier2_count = self._data_manager.tier2_count

                if total_stocks == 0:
                    empty_alert_count += 1

                    # 장외 시간에는 경고 스킵 (WAIT_FOR_MARKET_OPEN=false로 장외 연결 시)
                    market_state = self._market_schedule.get_state()
                    if market_state != MarketState.OPEN:
                        continue  # 장외 시간에는 종목 없는게 정상

                    # 5분마다 텔레그램 경고 (5회 * 60초)
                    if empty_alert_count % 5 == 1:
                        await self._telegram.send_message(
                            f"[시스템 경고]\n"
                            f"모니터링 종목 없음 ({empty_alert_count}분 경과)\n\n"
                            f"조건검색에 편입된 종목이 없습니다.\n"
                            f"/status 로 상태 확인"
                        )
                        self._logger.warning(
                            f"[상태 모니터] 모니터링 종목 없음 ({empty_alert_count}분)"
                        )
                else:
                    # 종목이 있으면 카운터 리셋
                    if empty_alert_count > 0:
                        await self._telegram.send_message(
                            f"[복구 알림]\n"
                            f"모니터링 재개: Tier1={tier1_count}, Tier2={tier2_count}"
                        )
                        self._logger.info(
                            f"[상태 모니터] 모니터링 복구: T1={tier1_count}, T2={tier2_count}"
                        )
                    empty_alert_count = 0

                # 30분마다 정상 운영 보고
                if status_report_counter >= self.STATUS_REPORT_INTERVAL and total_stocks > 0:
                    status_report_counter = 0
                    stats = self._data_manager.get_stats()
                    positions = self._position_manager.get_position_count()

                    self._logger.info(
                        f"[정기 상태] Tier1={tier1_count}, Tier2={tier2_count}, "
                        f"포지션={positions}, 폴링={stats['tier1_polls']}회"
                    )

            except asyncio.CancelledError:
                self._logger.info("[상태 모니터] 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[상태 모니터] 에러: {e}")
                await asyncio.sleep(60)

    async def _position_sync_loop(self) -> None:
        """
        포지션 동기화 루프 (PRD v2.0)

        설정된 간격마다 API와 포지션을 동기화하여 HTS 직접 매매를 감지합니다.
        - HTS 매수 감지 → 포지션 등록 + 백업 손절 모니터링
        - HTS 매도 감지 → 포지션 청산
        - 수량 변동 감지 → 동기화
        """
        from src.utils.config import get_risk_settings

        sync_interval = get_risk_settings().position_sync_interval
        self._logger.info(f"[포지션 동기화] 루프 시작 ({sync_interval}초 간격)")

        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                await asyncio.sleep(sync_interval)

                if self._callbacks.get_engine_state() != "RUNNING":
                    continue

                await self._callbacks.sync_positions()
                # V6.2-J: 동기화 후 Tier 1 일관성 검증
                await self._callbacks.verify_tier1_consistency()

            except asyncio.CancelledError:
                self._logger.info("[포지션 동기화] 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[포지션 동기화] 에러: {e}")
                await asyncio.sleep(60)

    async def _ranking_update_loop(self) -> None:
        """
        거래대금 순위 갱신 루프 (PRD v3.1+)

        설정된 간격마다 AutoScreener의 거래대금 순위를 갱신합니다.
        - Candidate Pool 종목들의 최신 거래대금 조회
        - Active Pool 재정렬 (상위 5개 선정)
        """
        from src.utils.config import TradingMode

        update_interval = self._risk_settings.ranking_update_interval  # 60초
        self._logger.info(f"[AutoScreener] 순위 갱신 루프 시작 ({update_interval}초 간격)")

        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                await asyncio.sleep(update_interval)

                if self._callbacks.get_engine_state() != "RUNNING":
                    continue

                # V7 SIGNAL_ALERT 모드: 순위 갱신 불필요 (SignalPool 단일 구조)
                if self._strategy_orchestrator and self._strategy_orchestrator.get_base_strategy("V7_PURPLE_REABS"):
                    if self._risk_settings.trading_mode == TradingMode.SIGNAL_ALERT:
                        continue

                # Auto-Universe 비활성화 시 스킵
                if not self._risk_settings.auto_universe_enabled:
                    continue

                await self._auto_screener.update_rankings()

            except asyncio.CancelledError:
                self._logger.info("[AutoScreener] 순위 갱신 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[AutoScreener] 순위 갱신 에러: {e}")
                await asyncio.sleep(60)

    async def _watchlist_revalidation_loop(self) -> None:
        """
        V6.2-B: Watchlist 재검증 루프 (30초 간격)

        Watchlist에만 있고 Candidate Pool에 없는 종목들을 30초마다 재검증합니다.
        - 장초반 필터 미통과 → 시간이 지나 조건 충족 시 승격
        - 조건검색 이탈 후에도 재검증 기회 제공
        - 승격된 종목은 Universe에 등록 → 신호 탐지 대상
        """
        from src.utils.config import TradingMode

        revalidation_interval = getattr(
            self._risk_settings, 'watchlist_revalidation_interval', 30
        )  # 기본 30초
        self._logger.info(
            f"[V6.2-B] Watchlist 재검증 루프 시작 ({revalidation_interval}초 간격)"
        )

        # 장외 시간 스킵 카운터 (10분마다 상태 로그 출력용)
        skip_count = 0

        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                await asyncio.sleep(revalidation_interval)

                if self._callbacks.get_engine_state() != "RUNNING":
                    continue

                # V7 SIGNAL_ALERT 모드: Watchlist 재검증 불필요 (SignalPool 단일 구조)
                if self._strategy_orchestrator and self._strategy_orchestrator.get_base_strategy("V7_PURPLE_REABS"):
                    if self._risk_settings.trading_mode == TradingMode.SIGNAL_ALERT:
                        continue

                # Auto-Universe 비활성화 시 스킵
                if not self._risk_settings.auto_universe_enabled:
                    continue

                # 장중이 아니면 스킵 (10분마다 상태 로그 출력)
                if self._callbacks.get_market_status() != "REGULAR":
                    skip_count += 1
                    if skip_count % 20 == 0:  # 30초 × 20 = 10분마다
                        self._logger.info(
                            f"[V6.2-B] Watchlist 재검증 스킵: 장중 아님 "
                            f"(Watchlist {self._auto_screener.watchlist_count}개, "
                            f"Candidate {self._auto_screener.candidate_count}개, "
                            f"Active {self._auto_screener.active_count}개)"
                        )
                    continue

                # 장중 진입 시 스킵 카운터 리셋
                skip_count = 0

                # 재검증 대상 확인 (Watchlist O, Candidate X)
                watchlist_only = [
                    code for code in self._auto_screener.watchlist_stocks
                    if code not in self._auto_screener.candidate_stocks
                ]
                self._logger.info(
                    f"[V6.2-B] Watchlist 재검증 시작: {len(watchlist_only)}개 대상 "
                    f"(Watchlist {self._auto_screener.watchlist_count}개)"
                )

                # Watchlist 재검증 실행
                promoted = await self._auto_screener.revalidate_watchlist()

                # 승격된 종목이 있으면 Universe에 등록
                for stock_code in promoted:
                    await self._register_promoted_watchlist_stock(stock_code)

                # 항상 결과 로깅 (승격 여부와 관계없이)
                self._logger.info(
                    f"[V6.2-B] Watchlist 재검증 완료: {len(promoted)}개 승격 → "
                    f"Watchlist {self._auto_screener.watchlist_count}개, "
                    f"Candidate {self._auto_screener.candidate_count}개, "
                    f"Active {self._auto_screener.active_count}개"
                )

            except asyncio.CancelledError:
                self._logger.info("[V6.2-B] Watchlist 재검증 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[V6.2-B] Watchlist 재검증 에러: {e}")

    async def _register_promoted_watchlist_stock(self, stock_code: str) -> None:
        """
        V6.2-B: Watchlist에서 승격된 종목을 Universe에 등록

        재검증으로 Candidate Pool에 승격된 종목을 Universe에 등록하여
        신호 탐지 대상에 포함시킵니다.

        Args:
            stock_code: 승격된 종목코드
        """
        # 이미 Universe에 있으면 스킵
        if self._universe.is_in_universe(stock_code):
            self._logger.debug(f"[V6.2-B] 이미 Universe에 있음: {stock_code}")
            return

        # 종목명 조회
        stock_name = ""
        if self._auto_screener.is_in_watchlist(stock_code):
            watchlist_entry = self._auto_screener._watchlist.get(stock_code)
            if watchlist_entry:
                stock_name = watchlist_entry.stock_name

        if not stock_name:
            try:
                stock_name = await self._market_api.get_stock_name(stock_code)
            except Exception:
                stock_name = stock_code

        self._logger.info(f"[V6.2-B] Watchlist 승격 → Universe 등록: {stock_name}({stock_code})")

        # Universe에 추가
        self._universe.add_stock(
            stock_code=stock_code,
            stock_name=stock_name,
            metadata={
                "source": "watchlist_revalidation",
                "condition_seq": self._risk_settings.auto_universe_condition_seq,
            },
        )

        # V6.2-R: 캔들 빌더 추가 + Tier 1 승격 (Active Pool 종목만)
        try:
            # CandleBuilder 생성
            if self._candle_manager.get_builder(stock_code) is None:
                self._candle_manager.add_stock(stock_code)
                self._logger.debug(f"[V6.2-B] CandleBuilder 생성: {stock_code}")

            # Active Pool 여부 확인 → Active면 Tier 1, 아니면 Tier 2
            is_active = self._auto_screener.is_active(stock_code)

            if is_active:
                # Tier 1 등록 + 과거 캔들 로드
                self._data_manager.register_stock(stock_code, Tier.TIER_1, stock_name)
                await self._data_manager.promote_to_tier1(stock_code)
                self._logger.info(f"[V6.2-R] Active Pool → Tier 1 승격: {stock_name}({stock_code})")
            else:
                # Tier 2 등록 (3분봉만 로드)
                self._data_manager.register_stock(stock_code, Tier.TIER_2, stock_name)
                await self._data_manager.load_historical_candles_for_watchlist(stock_code)
                self._logger.info(f"[V6.2-B] Candidate → Tier 2 등록: {stock_name}({stock_code})")

        except Exception as e:
            self._logger.warning(f"[V6.2-B] {stock_code} 데이터 설정 실패: {e}")

    async def _highest_price_persist_loop(self) -> None:
        """
        highest_price 주기적 저장 루프 (PRD v3.0)

        30초마다 분할 익절 후 포지션의 highest_price를 DB에 저장합니다.
        시스템 크래시 후 재시작 시 트레일링 스탑 기준가를 복원하기 위함입니다.
        """
        self._logger.info("[Persistence] highest_price 저장 루프 시작 (30초 간격)")

        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            try:
                await asyncio.sleep(self.HIGHEST_PRICE_PERSIST_INTERVAL)  # 30초 간격

                if self._callbacks.get_engine_state() != "RUNNING":
                    continue

                if not self._trade_repo:
                    continue

                # 분할 익절 완료된 포지션만 처리 (스냅샷으로 안전한 반복)
                for stock_code, position_risk in self._risk_manager.get_all_position_risks().items():
                    if not position_risk.is_partial_exit:
                        continue

                    # 포지션에서 trade_id 가져오기
                    position = self._position_manager.get_position(stock_code)
                    if not position or not position.signal_metadata:
                        continue

                    trade_id = position.signal_metadata.get("trade_id")
                    if not trade_id:
                        continue

                    # DB에 최고가 저장
                    await self._trade_repo.update_highest_price(
                        trade_id=trade_id,
                        highest_price=position_risk.highest_price,
                    )

            except asyncio.CancelledError:
                self._logger.info("[Persistence] highest_price 저장 루프 종료")
                break
            except Exception as e:
                self._logger.error(f"[Persistence] highest_price 저장 에러: {e}")
