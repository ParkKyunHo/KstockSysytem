"""
포지션 복구 관리 모듈

TradingEngine에서 추출된 DB 복구, API 잔고 대조, 트레일링 스탑 초기화.
Phase 4-C: ~340줄 절감.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Callable, Awaitable, List
import logging

import pandas as pd

from src.core.indicator import Indicator
from src.core.position_manager import PositionManager, EntrySource
from src.core.position_sync_manager import PositionSyncManager, PositionInfo
from src.core.signal_detector import StrategyType


@dataclass
class RecoveryCallbacks:
    """PositionRecoveryManager → TradingEngine 콜백"""

    build_sync_callbacks: Callable


class PositionRecoveryManager:
    """
    시스템 재시작 시 포지션 복구를 담당.

    - DB에서 열린 거래 로드 → PositionManager/RiskManager 복원
    - API 잔고와 대조하여 불일치 탐지
    - 트레일링 스탑 초기화
    """

    def __init__(
        self,
        trade_repo,
        position_manager: PositionManager,
        risk_manager,
        candle_manager,
        account_api,
        position_sync_manager: PositionSyncManager,
        exit_manager,
        market_api,
        risk_settings,
        telegram,
        logger: logging.Logger,
        callbacks: RecoveryCallbacks,
    ):
        self._trade_repo = trade_repo
        self._position_manager = position_manager
        self._risk_manager = risk_manager
        self._candle_manager = candle_manager
        self._account_api = account_api
        self._position_sync_manager = position_sync_manager
        self._exit_manager = exit_manager
        self._market_api = market_api
        self._risk_settings = risk_settings
        self._telegram = telegram
        self._logger = logger
        self._callbacks = callbacks

    # =========================================
    # DB 복구
    # =========================================

    async def restore_positions_from_db(self) -> None:
        """
        데이터베이스에서 열린 거래 복구 (V6.2-Q)

        시스템 재시작 시 OPEN 상태의 거래를 DB에서 로드하여
        PositionManager와 RiskManager에 복원합니다.
        """
        if not self._trade_repo:
            self._logger.debug("DB 리포지토리 미초기화 - 포지션 복구 건너뜀")
            return

        try:
            open_trades = await self._trade_repo.get_open_trades()

            if not open_trades:
                self._logger.info("DB에서 복구할 열린 거래 없음")
                await self.reconcile_with_api_balance()
                return

            self._logger.info(f"DB에서 {len(open_trades)}개 열린 거래 복구 중...")

            for trade in open_trades:
                stock_code = trade.stock_code

                if self._position_manager.has_position(stock_code):
                    self._logger.debug(f"이미 포지션 있음, 건너뜀: {stock_code}")
                    continue

                try:
                    strategy = StrategyType(trade.strategy)
                except ValueError:
                    strategy = StrategyType.SNIPER_TRAP

                is_partial = trade.is_partial_exit or False
                highest_price = trade.highest_price_after_partial or 0

                metadata = {
                    "trade_id": trade.id,
                    "reason": trade.entry_reason or "",
                    "order_no": trade.entry_order_no,
                    "restored_from_db": True,
                }

                await self._position_manager.open_position(
                    stock_code=stock_code,
                    stock_name=trade.stock_name,
                    strategy=strategy,
                    entry_price=trade.entry_price,
                    quantity=trade.entry_quantity,
                    order_no=trade.entry_order_no,
                    signal_metadata=metadata,
                    entry_source=EntrySource.RESTORED,
                    is_partial_exit=is_partial,
                    highest_price_after_partial=highest_price,
                )

                self._risk_manager.on_entry(
                    stock_code,
                    trade.entry_price,
                    trade.entry_quantity,
                    is_partial_exit=is_partial,
                    highest_price=highest_price,
                    entry_source=trade.entry_source,
                )

                if trade.entry_time:
                    self._risk_manager.set_entry_date(
                        stock_code, trade.entry_time.date()
                    )
                else:
                    self._risk_manager.set_entry_date(stock_code, date.today())
                    self._logger.warning(
                        f"entry_time이 None - 오늘 날짜로 fallback: {stock_code}"
                    )

                position_risk = self._risk_manager.get_position_risk(stock_code)
                if position_risk and position_risk.entry_atr == 0:
                    fallback_atr = trade.entry_price * 0.005
                    position_risk.entry_atr = fallback_atr
                    self._logger.info(
                        f"[V6.2-I] 기존 포지션 entry_atr fallback: {stock_code} "
                        f"ATR={fallback_atr:.0f} (매수가 {trade.entry_price:,}원 × 0.5%)"
                    )

                self._candle_manager.add_stock(stock_code)

                self._logger.info(
                    f"포지션 복구: {trade.stock_name}({stock_code})",
                    entry_price=trade.entry_price,
                    quantity=trade.entry_quantity,
                    trade_id=trade.id,
                    is_partial_exit=is_partial,
                    highest_price=highest_price,
                )

            self._logger.info(f"포지션 복구 완료: {len(open_trades)}개")

            await self.initialize_trailing_stops_after_recovery()
            await self.reconcile_with_api_balance()

        except Exception as e:
            self._logger.error(f"포지션 복구 실패: {e}")

    # =========================================
    # API 잔고 대조
    # =========================================

    async def reconcile_with_api_balance(self) -> None:
        """
        API 잔고와 포지션 대조 (PRD v3.0)

        DB 복구 후 API 실제 잔고와 비교하여:
        - DB에 없는 HTS 매수 → 포지션 등록 + 알림
        - API에 없는 DB 포지션 → 경고 알림
        """
        try:
            account_summary = await self._account_api.get_positions()

            api_positions = [
                PositionInfo(
                    stock_code=pos.stock_code,
                    stock_name=pos.stock_name,
                    quantity=pos.quantity,
                    average_price=pos.average_price,
                )
                for pos in account_summary.positions
                if pos.stock_code and pos.quantity > 0
            ]

            callbacks = self._callbacks.build_sync_callbacks()
            result = await self._position_sync_manager.reconcile_with_api_balance(
                api_positions, callbacks
            )

            if result.errors:
                for error in result.errors:
                    self._logger.warning(f"[API 잔고 대조] 오류: {error}")

        except Exception as e:
            self._logger.error(f"API 잔고 대조 실패: {e}")

    # =========================================
    # 트레일링 스탑 초기화
    # =========================================

    async def initialize_trailing_stops_after_recovery(self) -> None:
        """
        Grand Trend V6.2-A: 포지션 복구 후 트레일링 스탑 초기화

        V6.2-A (USE_PARTIAL_EXIT=false): 모든 포지션에 대해 TS 즉시 초기화
        V6 (USE_PARTIAL_EXIT=true): 분할 익절 포지션만 TS 초기화
        """
        all_positions = list(self._position_manager.get_all_positions())

        if not all_positions:
            self._logger.debug(
                "[Grand Trend] 포지션 없음 - 트레일링 스탑 초기화 스킵"
            )
            return

        if not self._risk_settings.use_partial_exit:
            self._logger.info(
                f"[V6.2-A] {len(all_positions)}개 포지션 트레일링 스탑 마이그레이션 중..."
            )

            for position in all_positions:
                stock_code = position.stock_code
                try:
                    initial_ts = await self._exit_manager.initialize_trailing_stop_on_entry_v62a(
                        stock_code, position.entry_price
                    )

                    if initial_ts > 0:
                        self._logger.info(
                            f"[V6.2-A] 포지션 마이그레이션 완료: "
                            f"{position.stock_name}({stock_code})",
                            trailing_stop=initial_ts,
                            entry_price=position.entry_price,
                        )
                    else:
                        await self.init_ts_fallback(stock_code, position)

                except Exception as e:
                    self._logger.error(
                        f"[V6.2-A] {stock_code} 마이그레이션 실패: {e}"
                    )

            return

        # V6 로직 (USE_PARTIAL_EXIT=true)
        partial_positions = [
            (pos.stock_code, pos)
            for pos in all_positions
            if self._risk_manager.is_partial_exited(pos.stock_code)
        ]

        if not partial_positions:
            self._logger.debug(
                "[Grand Trend] 분할 익절 포지션 없음 - 트레일링 스탑 초기화 스킵"
            )
            return

        self._logger.info(
            f"[Grand Trend] {len(partial_positions)}개 분할 익절 포지션 "
            "트레일링 스탑 초기화 중..."
        )

        for stock_code, position in partial_positions:
            await self.init_ts_fallback(stock_code, position)

    async def init_ts_fallback(self, stock_code: str, position) -> None:
        """V6/V6.2-A 공통: 캔들 기반 트레일링 스탑 초기화 (폴백)"""
        try:
            candle_count = self._risk_settings.candle_history_count
            candles_3m = await self._market_api.get_minute_chart(
                stock_code, timeframe=3, count=candle_count, use_pagination=True
            )

            if (
                not candles_3m
                or len(candles_3m) < self._risk_settings.atr_trailing_period
            ):
                self._logger.warning(
                    f"[Grand Trend] {stock_code} 캔들 부족 - "
                    "트레일링 스탑 초기화 실패"
                )
                return

            df = pd.DataFrame(
                [
                    {
                        "high": c.high_price,
                        "low": c.low_price,
                        "close": c.close_price,
                    }
                    for c in candles_3m
                ]
            )

            atr = Indicator.atr(
                df["high"],
                df["low"],
                df["close"],
                period=self._risk_settings.atr_trailing_period,
            )

            if atr is None or len(atr) == 0:
                return

            current_atr = float(atr.iloc[-1])
            current_close = candles_3m[-1].close_price

            if not self._risk_settings.use_partial_exit:
                multiplier = self._risk_settings.ts_atr_mult_base
            else:
                multiplier = self._risk_settings.atr_trailing_multiplier

            trailing_stop = int(current_close - current_atr * multiplier)
            trailing_stop = max(trailing_stop, 0)

            self._risk_manager.set_trailing_stop_price(stock_code, trailing_stop)

            self._logger.info(
                f"[Grand Trend] 트레일링 스탑 초기화: "
                f"{position.stock_name}({stock_code})",
                trailing_stop=trailing_stop,
                current_close=current_close,
                atr=int(current_atr),
            )

        except Exception as e:
            self._logger.error(
                f"[Grand Trend] {stock_code} 트레일링 스탑 초기화 실패: {e}"
            )

    async def init_trailing_stop_for_recovered_partial(
        self, stock_code: str
    ) -> None:
        """
        PRD v3.2.5: 단일 종목의 트레일링 스탑 초기화 (수량 기반 복구용)

        _sync_positions()에서 수량 감소로 분할 익절 상태가 감지된 경우,
        해당 종목의 트레일링 스탑을 즉시 초기화합니다.
        """
        position = self._position_manager.get_position(stock_code)
        if not position:
            return

        try:
            candle_count = self._risk_settings.candle_history_count
            candles_3m = await self._market_api.get_minute_chart(
                stock_code, timeframe=3, count=candle_count, use_pagination=True
            )

            if (
                not candles_3m
                or len(candles_3m) < self._risk_settings.atr_trailing_period
            ):
                self._logger.warning(
                    f"[수량 기반 복구] {stock_code} 캔들 부족 - "
                    "트레일링 스탑 초기화 실패"
                )
                return

            df = pd.DataFrame(
                [
                    {
                        "high": c.high_price,
                        "low": c.low_price,
                        "close": c.close_price,
                    }
                    for c in candles_3m
                ]
            )

            atr = Indicator.atr(
                df["high"],
                df["low"],
                df["close"],
                period=self._risk_settings.atr_trailing_period,
            )

            if atr is None or len(atr) == 0:
                return

            current_atr = float(atr.iloc[-1])
            current_close = candles_3m[-1].close_price

            trailing_stop = int(
                current_close
                - current_atr * self._risk_settings.atr_trailing_multiplier
            )
            trailing_stop = max(trailing_stop, 0)

            self._risk_manager.set_trailing_stop_price(stock_code, trailing_stop)

            self._logger.info(
                f"[수량 기반 복구] 트레일링 스탑 초기화 완료: "
                f"{position.stock_name}({stock_code})",
                trailing_stop=trailing_stop,
                current_close=current_close,
                atr=int(current_atr),
            )

            await self._telegram.send_message(
                f"수량 기반 분할 익절 복구\n\n"
                f"{position.stock_name}({stock_code})\n"
                f"ATR 트레일링 스탑 활성화\n"
                f"손절가: {trailing_stop:,}원"
            )

        except Exception as e:
            self._logger.error(
                f"[수량 기반 복구] {stock_code} 트레일링 스탑 초기화 실패: {e}"
            )
