"""
Phase 3 리팩토링: V7SignalCoordinator

V7 Purple-ReAbs 신호 탐지 루프를 담당합니다.
TradingEngine에서 분리되어 독립적으로 동작합니다.

책임:
- Dual-Pass 타이밍 관리 (Pre-Check, Confirm-Check)
- 신호 탐지 및 알림 전송
- 알림 큐 처리
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
import asyncio
import logging

from src.core.signal_detector_purple import (
    PurpleSignal,
    calculate_confidence,
    generate_signal_summary,
    format_condition_log,
)
from src.core.missed_signal_tracker import SignalAttempt


@dataclass
class V7Callbacks:
    """
    V7SignalCoordinator 콜백 인터페이스

    TradingEngine과의 의존성을 콜백으로 분리합니다.
    """
    # 캔들 데이터
    get_candles: Optional[Callable[[str, Any], Any]] = None
    is_candle_loaded: Optional[Callable[[str], bool]] = None
    promote_to_tier1: Optional[Callable[[str], Awaitable[bool]]] = None

    # SignalPool
    get_signal_pool: Optional[Callable[[], Any]] = None
    get_pool_stock: Optional[Callable[[str], Any]] = None
    get_all_pool_stocks: Optional[Callable[[], List[Any]]] = None
    get_recent_pool_stocks: Optional[Callable[[float], List[Any]]] = None

    # DualPass
    get_dual_pass: Optional[Callable[[], Any]] = None
    # Note: run_pre_check_single, run_confirm_check_single 제거됨
    # - DualPass 객체의 메서드를 직접 호출 (get_dual_pass()로 접근)
    get_candidates: Optional[Callable[[], Set[str]]] = None
    clear_candidates: Optional[Callable[[], None]] = None

    # Watermark
    is_market_open: Optional[Callable[[datetime], bool]] = None
    is_signal_time: Optional[Callable[[datetime], bool]] = None
    is_pre_check_time: Optional[Callable[[datetime, int], bool]] = None
    is_confirm_check_time: Optional[Callable[[datetime, int], bool]] = None
    get_current_bar_start: Optional[Callable[[], datetime]] = None

    # MissedSignalTracker
    log_missed_attempt: Optional[Callable[[SignalAttempt], None]] = None

    # NotificationQueue
    enqueue_notification: Optional[Callable[..., bool]] = None
    process_next_notification: Optional[Callable[[], Awaitable[Any]]] = None

    # 텔레그램
    send_telegram: Optional[Callable[[str], Awaitable]] = None

    # 엔진 상태
    is_engine_running: Optional[Callable[[], bool]] = None


class V7SignalCoordinator:
    """
    V7 Purple-ReAbs 신호 조율자

    Dual-Pass 타이밍 관리 및 신호 알림을 담당합니다.

    사용 예:
        coordinator = V7SignalCoordinator(logger=logger)
        callbacks = V7Callbacks(
            get_candles=candle_manager.get_candles,
            ...
        )
        await coordinator.start(callbacks)
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            logger: 로거 (None이면 기본 로거 사용)
        """
        self._logger = logger or logging.getLogger(__name__)

        # 동시성 제한 (API Rate Limit 보호)
        self._gather_semaphore = asyncio.Semaphore(20)

        # 통계
        self._stats = {
            "pre_checks": 0,
            "confirm_checks": 0,
            "signals_sent": 0,
            "same_bar_skipped": 0,
            "errors": 0,
        }

        # 태스크
        self._dual_pass_task: Optional[asyncio.Task] = None
        self._notification_task: Optional[asyncio.Task] = None
        self._running = False

    async def ensure_candle_loaded(
        self,
        stock_code: str,
        callbacks: V7Callbacks,
        timeout: float = 5.0,
    ) -> bool:
        """
        V7 SignalPool 종목의 캔들 로딩 보장

        Args:
            stock_code: 종목코드
            callbacks: 콜백 인터페이스
            timeout: 타임아웃 (초)

        Returns:
            True: 캔들 로딩 완료, False: 타임아웃 또는 실패
        """
        # 이미 로딩된 경우 즉시 반환
        if callbacks.is_candle_loaded and callbacks.is_candle_loaded(stock_code):
            return True

        try:
            if callbacks.promote_to_tier1:
                return await asyncio.wait_for(
                    callbacks.promote_to_tier1(stock_code),
                    timeout=timeout
                )
            return False
        except asyncio.TimeoutError:
            self._logger.warning(f"[V7] 캔들 로딩 타임아웃: {stock_code} ({timeout}초)")
            return False
        except Exception as e:
            self._logger.warning(f"[V7] 캔들 로딩 실패: {stock_code} - {e}")
            return False

    async def start(self, callbacks: V7Callbacks) -> None:
        """
        V7 신호 조율 시작

        Args:
            callbacks: 콜백 인터페이스
        """
        self._callbacks = callbacks  # [V7.1-Fix13] 이벤트 기반 ConfirmCheck용
        self._running = True

        # Dual-Pass 루프 시작
        self._dual_pass_task = asyncio.create_task(
            self._dual_pass_loop(callbacks)
        )

        # 알림 루프 시작
        self._notification_task = asyncio.create_task(
            self._notification_loop(callbacks)
        )

        self._logger.info("[V7SignalCoordinator] 시작됨")

    async def stop(self) -> None:
        """V7 신호 조율 중지"""
        self._running = False

        # 태스크 취소
        if self._dual_pass_task:
            self._dual_pass_task.cancel()
            try:
                await self._dual_pass_task
            except asyncio.CancelledError:
                pass

        if self._notification_task:
            self._notification_task.cancel()
            try:
                await self._notification_task
            except asyncio.CancelledError:
                pass

        self._logger.info("[V7SignalCoordinator] 중지됨")

    async def _dual_pass_loop(self, callbacks: V7Callbacks) -> None:
        """
        V7.0 Dual-Pass 타이밍 관리 루프

        3분봉 완성 시점에 맞춰 Pre-Check → Confirm-Check를 실행합니다.
        """
        self._logger.info("[V7.0] DualPass 루프 시작")

        # 디버깅: SignalPool 상태 출력
        if callbacks.get_signal_pool:
            pool = callbacks.get_signal_pool()
            if pool:
                self._logger.info(f"[V7.0] SignalPool 초기 크기: {pool.size()}개")

        while self._running:
            # 엔진 상태 확인
            if callbacks.is_engine_running and not callbacks.is_engine_running():
                await asyncio.sleep(10)
                continue

            try:
                now = datetime.now()

                # 장중인지 확인
                if callbacks.is_market_open and not callbacks.is_market_open(now):
                    await asyncio.sleep(10)
                    continue

                # 신호 탐지 시간인지 확인 (09:05 이후)
                if callbacks.is_signal_time and not callbacks.is_signal_time(now):
                    await asyncio.sleep(10)
                    continue

                # Pre-Check 구간인지 확인 (봉 완성 30초 전)
                if callbacks.is_pre_check_time and callbacks.is_pre_check_time(now, 30):
                    await self._run_pre_check(callbacks)

                # [V7.1-Fix13] Confirm-Check 구간 (봉 완성 직후 15초 이내, 5→15초 확대)
                elif callbacks.is_confirm_check_time and callbacks.is_confirm_check_time(now, 15):
                    await self._run_confirm_check(callbacks)

                # 다음 체크까지 대기 (5초)
                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"[V7 DualPass] 오류: {e}")
                self._stats["errors"] += 1
                await asyncio.sleep(10)

        self._logger.info("[V7 DualPass] 루프 종료")

    async def _run_pre_check(self, callbacks: V7Callbacks) -> None:
        """
        V7.0 Pre-Check 실행 (병렬화)

        SignalPool의 모든 종목에 대해 Pre-Check를 병렬 수행합니다.
        """
        if not callbacks.get_all_pool_stocks:
            return

        pool_stocks = callbacks.get_all_pool_stocks()
        pool_size = len(pool_stocks)

        if pool_size == 0:
            return

        self._logger.info(f"[V7.0] Pre-Check 시작 (SignalPool: {pool_size}개, 병렬)")
        self._stats["pre_checks"] += 1

        sem = self._gather_semaphore

        async def check_single(stock_info):
            """단일 종목 Pre-Check (병렬 실행용)"""
            async with sem:
                try:
                    # 캔들 데이터 가져오기
                    df = None
                    if callbacks.get_candles:
                        from src.core.candle_builder import Timeframe
                        df = callbacks.get_candles(stock_info.stock_code, Timeframe.M3)

                    if df is None or len(df) < 60:
                        return None

                    # Pre-Check 실행
                    dual_pass = callbacks.get_dual_pass() if callbacks.get_dual_pass else None
                    if not dual_pass:
                        return None

                    result = dual_pass.run_pre_check_single(
                        stock_info.stock_code,
                        stock_info.stock_name,
                        df
                    )

                    # 결과 반환
                    cond_short = ""
                    if result.conditions:
                        cond_short = "".join(
                            "O" if result.conditions.get(k, False) else "X"
                            for k in ["purple_ok", "trend", "zone", "reabs_start", "trigger"]
                        )

                    return (stock_info, result, cond_short)

                except Exception as e:
                    self._logger.warning(f"[V7 PreCheck] {stock_info.stock_code} 오류: {e}")
                    return None

        # 병렬 실행
        results = await asyncio.gather(
            *[check_single(s) for s in pool_stocks],
            return_exceptions=True
        )

        # 결과 집계
        candidates = []
        checked_count = 0
        sample_results = []

        for result in results:
            if result is None or isinstance(result, Exception):
                continue

            stock_info, check_result, cond_short = result
            checked_count += 1

            # 샘플 결과 수집 (처음 3개)
            if cond_short and len(sample_results) < 3:
                sample_results.append(f"{stock_info.stock_code}({cond_short})")

            if check_result.is_candidate:
                # PurpleOK 캐시: API 캔들 기반 판정을 ConfirmCheck에서 재사용
                if check_result.conditions and check_result.conditions.get("purple_ok"):
                    stock_info.purple_ok_cached = True
                    stock_info.purple_ok_cached_at = datetime.now()

                candidates.append(stock_info.stock_code)
                cond_log = ""
                if check_result.condition_values:
                    cond_log = f" | {format_condition_log(check_result.conditions, check_result.condition_values)}"
                self._logger.info(
                    f"[V7 PreCheck] 후보 등록: {stock_info.stock_name}({stock_info.stock_code}) "
                    f"조건 {check_result.conditions_met}/5 충족{cond_log}"
                )

        # Pre-Check 결과 요약 로깅
        if sample_results:
            self._logger.info(
                f"[V7 PreCheck] 검사 {checked_count}개, 후보 {len(candidates)}개 | "
                f"샘플(P/T/Z/R/Tr): {', '.join(sample_results)}"
            )

        if candidates:
            self._logger.info(
                f"[V7 PreCheck] 후보 {len(candidates)}개: "
                f"{', '.join(candidates[:5])}{'...' if len(candidates) > 5 else ''}"
            )

    async def _run_confirm_check(self, callbacks: V7Callbacks) -> None:
        """
        V7.0 Confirm-Check 실행 (병렬화)

        Pre-Check 후보들에 대해 최종 신호 확인을 병렬 수행합니다.
        """
        dual_pass = callbacks.get_dual_pass() if callbacks.get_dual_pass else None
        if not dual_pass:
            return

        # Pre-Check 후보 가져오기
        precheck_candidates = set(dual_pass.get_candidates())

        # Late-Arriving 종목 포함
        late_arriving_codes = set()
        if callbacks.get_recent_pool_stocks:
            late_stocks = callbacks.get_recent_pool_stocks(30.0)
            late_arriving_codes = {s.stock_code for s in late_stocks}

        # 통합 후보
        all_candidates = precheck_candidates | late_arriving_codes
        late_only_count = len(all_candidates) - len(precheck_candidates)

        if not all_candidates:
            return

        self._logger.info(
            f"[V7.0] Confirm-Check 시작 "
            f"(Pre-Check: {len(precheck_candidates)}개, Late: {late_only_count}개, 병렬)"
        )
        self._stats["confirm_checks"] += 1

        # 현재 봉 완성 시간
        bar_close_time = None
        if callbacks.get_current_bar_start:
            bar_close_time = callbacks.get_current_bar_start()
        now = datetime.now()

        signal_pool = callbacks.get_signal_pool() if callbacks.get_signal_pool else None

        sem = self._gather_semaphore

        async def check_single(stock_code: str):
            """단일 종목 Confirm-Check (병렬 실행용)"""
            async with sem:
                try:
                    stock_info = None
                    if callbacks.get_pool_stock:
                        stock_info = callbacks.get_pool_stock(stock_code)
                    if not stock_info:
                        return None

                    # 캔들 데이터 가져오기
                    df = None
                    if callbacks.get_candles:
                        from src.core.candle_builder import Timeframe
                        df = callbacks.get_candles(stock_code, Timeframe.M3)

                    if df is None or len(df) < 60:
                        return None

                    # 조건 체크 (1회만 수행)
                    detector = dual_pass.detector
                    conditions = detector._check_all_conditions(df)

                    # PurpleOK 캐시 적용: PreCheck에서 API 캔들 기반 통과했고 30분 이내면 캐시 사용
                    if not conditions.get("purple_ok") and stock_info.purple_ok_cached:
                        cache_age = (datetime.now() - stock_info.purple_ok_cached_at).total_seconds()
                        if cache_age < 1800:
                            conditions["purple_ok"] = True
                            self._logger.debug(
                                f"[V7 ConfirmCheck] {stock_code} purple_ok_cached 적용 "
                                f"(캐시 {cache_age:.0f}초 전)"
                            )

                    conditions_met = sum(conditions.values())

                    # 봉 단위 쿨다운 체크
                    is_same_bar = False
                    if bar_close_time:
                        is_same_bar = not stock_info.can_signal_new_bar(bar_close_time)

                    # Confirm-Check 실행 (쿨다운 아닐 때 + 5/5 충족 시만)
                    signal = None
                    if not is_same_bar and conditions_met == 5:
                        signal = dual_pass.run_confirm_check_single(
                            stock_code,
                            stock_info.stock_name,
                            df
                        )

                    # 신호 발생 시 metadata에서 재사용 (이중 계산 방지)
                    if signal:
                        meta = signal.metadata or {}
                        details = {k: v for k, v in meta.items() if k != "conditions"}
                        confidence = signal.confidence
                    else:
                        details = detector._get_signal_details(df)
                        confidence = calculate_confidence(details)

                    # 진단 로깅용 수치 (5/5 미달 시)
                    condition_values = {}
                    if conditions_met < 5:
                        condition_values = detector._get_condition_values(df)

                    return {
                        "stock_code": stock_code,
                        "stock_info": stock_info,
                        "signal": signal,
                        "is_same_bar": is_same_bar,
                        "conditions": conditions,
                        "conditions_met": conditions_met,
                        "confidence": confidence,
                        "details": details,
                        "condition_values": condition_values,
                    }

                except Exception as e:
                    self._logger.warning(f"[V7 ConfirmCheck] {stock_code} 오류: {e}")
                    return None

        # 병렬 실행
        results = await asyncio.gather(
            *[check_single(code) for code in all_candidates],
            return_exceptions=True
        )

        # 결과 처리 (순차)
        signals = []
        skipped_same_bar = 0

        for result in results:
            if result is None or isinstance(result, Exception):
                continue

            stock_code = result["stock_code"]
            stock_info = result["stock_info"]
            signal = result["signal"]
            is_same_bar = result["is_same_bar"]
            conditions = result["conditions"]
            conditions_met = result["conditions_met"]
            confidence = result["confidence"]
            details = result["details"]

            if is_same_bar:
                skipped_same_bar += 1
                self._stats["same_bar_skipped"] += 1
                self._logger.debug(
                    f"[V7 ConfirmCheck] {stock_code} 동일 봉 스킵 "
                    f"(last_bar: {stock_info.last_signal_bar})"
                )

                # 놓친 신호 추적 (5/5 충족했으나 same_bar로 스킵)
                if callbacks.log_missed_attempt and conditions_met == 5:
                    attempt = SignalAttempt(
                        stock_code=stock_code,
                        stock_name=stock_info.stock_name,
                        timestamp=now,
                        bar_close_time=bar_close_time,
                        conditions=conditions,
                        conditions_met=conditions_met,
                        confidence=confidence,
                        notified=False,
                        skip_reason="same_bar",
                        details=details,
                    )
                    callbacks.log_missed_attempt(attempt)
                continue

            # 신호 시도 추적
            if callbacks.log_missed_attempt:
                attempt = SignalAttempt(
                    stock_code=stock_code,
                    stock_name=stock_info.stock_name,
                    timestamp=now,
                    bar_close_time=bar_close_time,
                    conditions=conditions,
                    conditions_met=conditions_met,
                    confidence=confidence,
                    notified=signal is not None,
                    skip_reason=None if signal else "insufficient",
                    details=details,
                )
                callbacks.log_missed_attempt(attempt)

            # 미달 종목 조건 수치 로깅 (진단용)
            condition_values = result.get("condition_values", {})
            if not signal and conditions_met >= 3 and condition_values:
                cond_log = format_condition_log(conditions, condition_values)
                failed = [k for k, v in conditions.items() if not v]
                label = "NearMiss" if conditions_met >= 4 else "ConfirmCheck"
                self._logger.info(
                    f"[V7 {label}] {stock_info.stock_name}({stock_code}) "
                    f"{conditions_met}/5, 미달: {', '.join(failed)} | {cond_log}"
                )

            if signal:
                # C-007 FIX: 원자적 봉 단위 쿨다운 업데이트 (중복 방지)
                # update_signal_bar가 False 반환하면 이미 같은 봉에서 신호 발생
                if bar_close_time is None:
                    self._logger.warning(
                        f"[V7 ConfirmCheck] {stock_code} bar_close_time=None, 쿨다운 스킵"
                    )
                elif not stock_info.update_signal_bar(bar_close_time):
                    self._logger.debug(
                        f"[V7 ConfirmCheck] {stock_code} 중복 신호 차단 (atomic check)"
                    )
                    self._stats["same_bar_skipped"] += 1
                    continue

                signals.append(signal)
                self._stats["signals_sent"] += 1
                # 알림 전송
                await self._send_purple_signal(signal, callbacks)

        # 후보 목록 정리
        dual_pass.clear_candidates()

        if signals or skipped_same_bar:
            self._logger.info(
                f"[V7 ConfirmCheck] 신호 {len(signals)}개 발생, "
                f"동일봉 스킵 {skipped_same_bar}개"
            )

    async def _on_candle_complete_confirm(
        self, stock_code: str, candle, callbacks: V7Callbacks
    ) -> None:
        """
        [V7.1-Fix13] 봉 완성 이벤트 기반 ConfirmCheck (단일 종목)

        CandleBuilder에서 3m 봉이 완성되면 호출됨.
        벽시계 타이밍 대신 실제 봉 완성 시점에 조건 체크하여 레이스 컨디션 해결.
        """
        # 엔진/장 상태 확인
        if callbacks.is_engine_running and not callbacks.is_engine_running():
            return
        now = datetime.now()
        if callbacks.is_signal_time and not callbacks.is_signal_time(now):
            return

        # DualPass 가져오기
        dual_pass = callbacks.get_dual_pass() if callbacks.get_dual_pass else None
        if not dual_pass:
            return

        # PreCheck 후보 또는 최근 Pool 종목인지 확인
        candidates = set(dual_pass.get_candidates())
        late_codes = set()
        if callbacks.get_recent_pool_stocks:
            late_codes = {s.stock_code for s in callbacks.get_recent_pool_stocks(30.0)}

        if stock_code not in candidates and stock_code not in late_codes:
            return

        # SignalPool에서 종목 정보 가져오기
        stock_info = None
        if callbacks.get_pool_stock:
            stock_info = callbacks.get_pool_stock(stock_code)
        if not stock_info:
            return

        # 캔들 데이터 (방금 완성된 봉 포함)
        df = None
        if callbacks.get_candles:
            from src.core.candle_builder import Timeframe
            df = callbacks.get_candles(stock_code, Timeframe.M3)
        if df is None or len(df) < 60:
            return

        # 조건 체크
        detector = dual_pass.detector
        conditions = detector._check_all_conditions(df, stock_code)

        # PurpleOK 캐시 적용: PreCheck에서 API 캔들 기반 통과했고 30분 이내면 캐시 사용
        if not conditions.get("purple_ok") and stock_info.purple_ok_cached:
            cache_age = (datetime.now() - stock_info.purple_ok_cached_at).total_seconds()
            if cache_age < 1800:
                conditions["purple_ok"] = True
                self._logger.debug(
                    f"[V7 EventConfirm] {stock_code} purple_ok_cached 적용 "
                    f"(캐시 {cache_age:.0f}초 전)"
                )

        conditions_met = sum(conditions.values())

        # 봉 단위 쿨다운
        bar_close_time = candle.time  # 완성된 봉의 시작 시간
        is_same_bar = not stock_info.can_signal_new_bar(bar_close_time)

        if is_same_bar:
            return

        # 5/5 충족 시 신호 생성
        if conditions_met == 5:
            signal = dual_pass.run_confirm_check_single(
                stock_code, stock_info.stock_name, df
            )
            if signal and stock_info.update_signal_bar(bar_close_time):
                self._stats["signals_sent"] += 1
                await self._send_purple_signal(signal, callbacks)
                self._logger.info(
                    f"[V7 EventConfirm] 신호 발생! {stock_info.stock_name}({stock_code}) "
                    f"5/5 충족 (이벤트 기반)"
                )

        # NearMiss (4/5 충족)
        if conditions_met == 4:
            failed = [k for k, v in conditions.items() if not v]
            self._logger.info(
                f"[V7 EventNearMiss] {stock_info.stock_name}({stock_code}) "
                f"{conditions_met}/5 충족, 미달: {', '.join(failed)}"
            )

    async def _send_purple_signal(
        self,
        signal: PurpleSignal,
        callbacks: V7Callbacks,
    ) -> None:
        """
        V7.0 Purple 신호 알림 전송

        Args:
            signal: PurpleSignal 객체
            callbacks: 콜백 인터페이스
        """
        try:
            # 신호 이유 자동 요약 생성
            summary = generate_signal_summary(signal)

            # 알림 메시지 생성
            message = (
                f"[V7 PURPLE] {signal.stock_name}({signal.stock_code})\n"
                f"현재가: {signal.price:,}원\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{summary}"
            )

            # 알림 큐에 추가
            if callbacks.enqueue_notification:
                result = callbacks.enqueue_notification(
                    message=message,
                    stock_code=signal.stock_code,
                    stock_name=signal.stock_name,
                )
                if not result:
                    # M-003 FIX: Enqueue 실패 시 (쿨다운 등) direct send fallback
                    # 중요한 신호가 쿨다운으로 누락되지 않도록 함
                    self._logger.info(f"[V7] {signal.stock_code} Enqueue 실패 - direct send fallback")
                    if callbacks.send_telegram:
                        await callbacks.send_telegram(message)
            elif callbacks.send_telegram:
                # 큐가 없으면 직접 전송
                await callbacks.send_telegram(message)

        except Exception as e:
            self._logger.error(f"[V7] 알림 전송 실패: {e}")
            self._stats["errors"] += 1

    async def _notification_loop(self, callbacks: V7Callbacks) -> None:
        """
        V7.0 알림 큐 처리 루프

        큐에 쌓인 알림을 순차적으로 처리합니다.
        """
        self._logger.info("[V7 Notification] 루프 시작")
        loop_count = 0

        while self._running:
            # 엔진 상태 확인
            if callbacks.is_engine_running and not callbacks.is_engine_running():
                await asyncio.sleep(1)
                continue

            try:
                if callbacks.process_next_notification:
                    result = await callbacks.process_next_notification()
                    if result is not None:
                        # [V7.1-Fix3] DEBUG→INFO로 변경 (진단용)
                        self._logger.info(f"[V7 Notification] 처리 완료: {result}")

                await asyncio.sleep(1)

                # [V7.1-Fix3] 60초마다 루프 동작 확인 로그
                loop_count += 1
                if loop_count % 60 == 0:
                    self._logger.info(f"[V7 Notification] 루프 활성 (60초 경과)")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"[V7 Notification] 오류: {e}")
                self._stats["errors"] += 1
                await asyncio.sleep(5)

        self._logger.info("[V7 Notification] 루프 종료")

    def get_stats(self) -> Dict[str, int]:
        """통계 조회"""
        return self._stats.copy()

    def get_status(self) -> Dict[str, Any]:
        """상태 조회"""
        return {
            "running": self._running,
            "dual_pass_task_active": self._dual_pass_task is not None and not self._dual_pass_task.done(),
            "notification_task_active": self._notification_task is not None and not self._notification_task.done(),
            "stats": self._stats.copy(),
        }

    def __str__(self) -> str:
        return (
            f"V7SignalCoordinator(running={self._running}, "
            f"signals={self._stats['signals_sent']}, "
            f"errors={self._stats['errors']})"
        )
