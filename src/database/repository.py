"""
데이터베이스 리포지토리

Trade, Order, DailyStats 등 엔티티에 대한 데이터 접근 계층입니다.
"""

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any, AsyncGenerator
from sqlalchemy import select, update, delete, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Trade,
    Order,
    DailyStats,
    Signal,
    SystemLog,
    TradeStatus,
    OrderSide,
    OrderStatus,
    EntrySource,
)
from src.database.connection import get_db_manager
from src.utils.logger import get_logger


logger = get_logger(__name__)


@asynccontextmanager
async def atomic_session() -> AsyncGenerator[AsyncSession, None]:
    """
    [P1-1] 원자적 트랜잭션을 위한 세션 컨텍스트

    여러 DB 작업을 하나의 트랜잭션으로 묶을 때 사용합니다.

    Usage:
        async with atomic_session() as session:
            trade = await trade_repo.create(..., session=session)
            order = await order_repo.create(trade_id=trade.id, ..., session=session)
            # 둘 다 성공해야 커밋, 하나라도 실패하면 롤백
    """
    db = get_db_manager()
    async with db.session() as session:
        yield session


class TradeRepository:
    """거래 내역 리포지토리"""

    async def create(
        self,
        stock_code: str,
        stock_name: str,
        strategy: str,
        entry_price: int,
        entry_quantity: int,
        entry_order_no: Optional[str] = None,
        entry_reason: Optional[str] = None,
        signal_strength: Optional[float] = None,
        entry_source: EntrySource = EntrySource.SYSTEM,
        session: Optional[AsyncSession] = None,     # [P1-1] 외부 세션 (트랜잭션 원자성)
    ) -> Trade:
        """
        새 거래 생성 (매수 시) - V6.2-Q

        Args:
            entry_source: 진입 출처 (MANUAL, SYSTEM, HTS, RESTORED)
            session: [P1-1] 외부 세션 (atomic_session()과 함께 사용)

        Returns:
            생성된 Trade 객체

        Raises:
            ValueError: 동일 종목에 이미 OPEN 상태 거래가 있는 경우
        """
        # V6.2-Q FIX: 중복 OPEN Trade 방지 (Double-Buy 차단)
        async def _check_duplicate(check_session: AsyncSession) -> bool:
            result = await check_session.execute(
                select(Trade).where(
                    and_(
                        Trade.stock_code == stock_code,
                        Trade.status == TradeStatus.OPEN
                    )
                )
            )
            return result.scalar_one_or_none() is not None

        if session is not None:
            if await _check_duplicate(session):
                logger.warning(f"중복 거래 차단: {stock_code} - 이미 OPEN 상태 거래 존재")
                raise ValueError(f"이미 {stock_code}에 대한 OPEN 상태 거래가 존재합니다")
        else:
            db = get_db_manager()
            async with db.session() as check_session:
                if await _check_duplicate(check_session):
                    logger.warning(f"중복 거래 차단: {stock_code} - 이미 OPEN 상태 거래 존재")
                    raise ValueError(f"이미 {stock_code}에 대한 OPEN 상태 거래가 존재합니다")

        trade = Trade(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy=strategy,
            entry_source=entry_source,
            entry_price=entry_price,
            entry_quantity=entry_quantity,
            entry_amount=entry_price * entry_quantity,
            entry_time=datetime.now(),
            entry_order_no=entry_order_no,
            entry_reason=entry_reason,
            signal_strength=signal_strength,
            status=TradeStatus.OPEN,
            # V6.2-Q: DB 컬럼 유지, 값은 기본값 사용 (Floor Line 삭제됨)
        )

        # [P1-1] 외부 세션이 있으면 사용, 없으면 새 세션 생성
        if session is not None:
            session.add(trade)
            await session.flush()
            await session.refresh(trade)
            logger.info(f"거래 생성: {trade.id} - {stock_code}")
            return trade

        db = get_db_manager()
        async with db.session() as new_session:
            new_session.add(trade)
            await new_session.flush()
            await new_session.refresh(trade)
            logger.info(f"거래 생성: {trade.id} - {stock_code}")
            return trade

    async def close(
        self,
        trade_id: int,
        exit_price: int,
        exit_order_no: Optional[str] = None,
        exit_reason: Optional[str] = None,
        max_profit_rate: Optional[float] = None,
        max_loss_rate: Optional[float] = None,
    ) -> Optional[Trade]:
        """
        거래 청산 (매도 시)

        Returns:
            업데이트된 Trade 객체
        """
        db = get_db_manager()

        async with db.session() as session:
            # V6.2-Q FIX: SELECT FOR UPDATE로 동시 청산 방지
            result = await session.execute(
                select(Trade).where(Trade.id == trade_id).with_for_update()
            )
            trade = result.scalar_one_or_none()

            if not trade:
                logger.warning(f"거래를 찾을 수 없음: {trade_id}")
                return None

            # 이미 청산된 거래인지 확인 (Double-Close 방지)
            if trade.status == TradeStatus.CLOSED:
                logger.warning(f"이미 청산된 거래: {trade_id}")
                return trade

            # 청산 정보 업데이트
            trade.exit_price = exit_price
            trade.exit_quantity = trade.entry_quantity
            trade.exit_amount = exit_price * trade.entry_quantity
            trade.exit_time = datetime.now()
            trade.exit_order_no = exit_order_no
            trade.exit_reason = exit_reason

            # 손익 계산
            trade.profit_loss = trade.exit_amount - trade.entry_amount
            trade.profit_loss_rate = (
                (trade.exit_price - trade.entry_price) / trade.entry_price * 100
            )
            trade.holding_seconds = int(
                (trade.exit_time - trade.entry_time).total_seconds()
            )

            # 최대 수익/손실률
            trade.max_profit_rate = max_profit_rate
            trade.max_loss_rate = max_loss_rate

            # 상태 변경
            trade.status = TradeStatus.CLOSED

            await session.flush()
            logger.info(
                f"거래 청산: {trade.id} - {trade.stock_code}, "
                f"손익: {trade.profit_loss:+,}원 ({trade.profit_loss_rate:+.2f}%)"
            )
            return trade

    async def update_partial_exit(
        self,
        trade_id: int,
        highest_price: int = 0,
    ) -> Optional[Trade]:
        """
        V6.2-Q: 분할 매도 완료 업데이트

        분할 매도 후 is_partial_exit=True로 업데이트
        highest_price_after_partial 초기화 (트레일링 스탑 시작점)

        Args:
            trade_id: 거래 ID
            highest_price: 분할 익절 시점 가격 (트레일링 스탑 시작점)

        Returns:
            업데이트된 Trade 객체
        """
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade:
                logger.warning(f"거래를 찾을 수 없음: {trade_id}")
                return None

            # V6.2-Q: 분할 매도 상태 업데이트 (stop_loss_price 제거됨)
            trade.is_partial_exit = True

            # 트레일링 스탑 시작점
            if highest_price > 0:
                trade.highest_price_after_partial = highest_price

            await session.flush()
            logger.info(
                f"분할 매도 완료: trade_id={trade.id}, "
                f"is_partial_exit=True, highest_price={highest_price:,}원"
            )
            return trade

    async def update_highest_price(
        self,
        trade_id: int,
        highest_price: int,
    ) -> bool:
        """
        PRD v3.0: 트레일링 스탑용 최고가 업데이트

        주기적으로 highest_price_after_partial을 DB에 저장하여
        시스템 크래시 시 복구 가능하게 합니다.

        Args:
            trade_id: 거래 ID
            highest_price: 현재 최고가

        Returns:
            업데이트 성공 여부
        """
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade:
                logger.warning(f"거래를 찾을 수 없음: {trade_id}")
                return False

            # 기존 값보다 높을 때만 업데이트
            if trade.highest_price_after_partial is None or highest_price > trade.highest_price_after_partial:
                trade.highest_price_after_partial = highest_price
                await session.flush()
                logger.debug(
                    f"최고가 업데이트: trade_id={trade.id}, highest_price={highest_price:,}원"
                )
                return True
            return False

    async def update_status(
        self,
        trade_id: int,
        status: TradeStatus,
    ) -> Optional[Trade]:
        """
        거래 상태 업데이트

        V6.2-A 코드리뷰 A2: DB 트랜잭션 원자성을 위한 롤백 지원
        - Trade 생성 후 Order 생성 실패 시 Trade 상태를 CANCELLED로 변경

        Args:
            trade_id: 거래 ID
            status: 새 상태 (OPEN, CLOSED, CANCELLED)

        Returns:
            업데이트된 Trade 객체
        """
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade:
                logger.warning(f"거래를 찾을 수 없음: {trade_id}")
                return None

            trade.status = status
            await session.flush()
            logger.info(f"거래 상태 변경: {trade.id} -> {status.value}")
            return trade

    async def get_by_id(self, trade_id: int) -> Optional[Trade]:
        """ID로 거래 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade).where(Trade.id == trade_id)
            )
            return result.scalar_one_or_none()

    async def get_open_trades(self) -> List[Trade]:
        """열린 거래 목록 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade)
                .where(Trade.status == TradeStatus.OPEN)
                .order_by(Trade.entry_time.desc())
            )
            return list(result.scalars().all())

    async def get_trades_by_date(self, target_date: date) -> List[Trade]:
        """특정 날짜의 거래 목록 조회"""
        db = get_db_manager()

        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())

        async with db.session() as session:
            result = await session.execute(
                select(Trade)
                .where(
                    and_(
                        Trade.entry_time >= start,
                        Trade.entry_time <= end,
                    )
                )
                .order_by(Trade.entry_time.desc())
            )
            return list(result.scalars().all())

    async def get_trades_by_stock(
        self,
        stock_code: str,
        limit: int = 10,
    ) -> List[Trade]:
        """종목별 거래 내역 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade)
                .where(Trade.stock_code == stock_code)
                .order_by(Trade.entry_time.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_recent_trades(self, limit: int = 20) -> List[Trade]:
        """최근 거래 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Trade)
                .order_by(Trade.entry_time.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_daily_summary(self, target_date: date) -> Dict[str, Any]:
        """일일 거래 요약"""
        trades = await self.get_trades_by_date(target_date)

        closed_trades = [t for t in trades if t.status == TradeStatus.CLOSED]

        if not closed_trades:
            return {
                "date": target_date,
                "trade_count": 0,
                "win_count": 0,
                "loss_count": 0,
                "total_pnl": 0,
                "win_rate": 0,
            }

        win_trades = [t for t in closed_trades if t.profit_loss > 0]
        loss_trades = [t for t in closed_trades if t.profit_loss <= 0]

        return {
            "date": target_date,
            "trade_count": len(closed_trades),
            "win_count": len(win_trades),
            "loss_count": len(loss_trades),
            "total_pnl": sum(t.profit_loss for t in closed_trades),
            "win_rate": len(win_trades) / len(closed_trades) * 100 if closed_trades else 0,
            "avg_profit": sum(t.profit_loss for t in win_trades) / len(win_trades) if win_trades else 0,
            "avg_loss": sum(t.profit_loss for t in loss_trades) / len(loss_trades) if loss_trades else 0,
        }


class OrderRepository:
    """주문 내역 리포지토리"""

    async def create(
        self,
        stock_code: str,
        side: OrderSide,
        order_type: str,
        quantity: int,
        price: Optional[int] = None,
        trade_id: Optional[int] = None,
        session: Optional[AsyncSession] = None,  # [P1-1] 외부 세션 (트랜잭션 원자성)
    ) -> Order:
        """
        주문 생성

        Args:
            session: [P1-1] 외부 세션 (atomic_session()과 함께 사용)
        """
        order = Order(
            stock_code=stock_code,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            trade_id=trade_id,
            status=OrderStatus.PENDING,
        )

        # [P1-1] 외부 세션이 있으면 사용, 없으면 새 세션 생성
        if session is not None:
            session.add(order)
            await session.flush()
            await session.refresh(order)
            return order

        db = get_db_manager()
        async with db.session() as new_session:
            new_session.add(order)
            await new_session.flush()
            await new_session.refresh(order)
            return order

    async def update_status(
        self,
        order_id: int,
        status: OrderStatus,
        order_no: Optional[str] = None,
        filled_quantity: Optional[int] = None,
        filled_price: Optional[int] = None,
        reject_reason: Optional[str] = None,
        session: Optional[AsyncSession] = None,  # V6.2-Q FIX: 외부 세션 지원
    ) -> Optional[Order]:
        """
        주문 상태 업데이트

        Args:
            session: [V6.2-Q] 외부 세션 (atomic_session()과 함께 사용)
        """
        async def _update(update_session: AsyncSession) -> Optional[Order]:
            result = await update_session.execute(
                select(Order).where(Order.id == order_id)
            )
            order = result.scalar_one_or_none()

            if not order:
                return None

            order.status = status
            if order_no:
                order.order_no = order_no
            if filled_quantity is not None:
                order.filled_quantity = filled_quantity
            if filled_price is not None:
                order.filled_price = filled_price
                order.filled_amount = filled_price * (filled_quantity or order.quantity)
            if reject_reason:
                order.reject_reason = reject_reason

            await update_session.flush()
            return order

        # V6.2-Q FIX: 외부 세션이 있으면 사용, 없으면 새 세션 생성
        if session is not None:
            return await _update(session)

        db = get_db_manager()
        async with db.session() as new_session:
            return await _update(new_session)

    async def get_by_order_no(self, order_no: str) -> Optional[Order]:
        """주문번호로 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Order).where(Order.order_no == order_no)
            )
            return result.scalar_one_or_none()


class DailyStatsRepository:
    """일일 통계 리포지토리"""

    async def upsert(
        self,
        target_date: date,
        stats: Dict[str, Any],
    ) -> DailyStats:
        """일일 통계 생성 또는 업데이트"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(DailyStats).where(DailyStats.date == target_date)
            )
            daily = result.scalar_one_or_none()

            if daily:
                # 업데이트
                for key, value in stats.items():
                    if hasattr(daily, key):
                        setattr(daily, key, value)
            else:
                # 생성
                daily = DailyStats(date=target_date, **stats)
                session.add(daily)

            await session.flush()
            await session.refresh(daily)
            return daily

    async def get_by_date(self, target_date: date) -> Optional[DailyStats]:
        """날짜별 통계 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(DailyStats).where(DailyStats.date == target_date)
            )
            return result.scalar_one_or_none()

    async def get_range(
        self,
        start_date: date,
        end_date: date,
    ) -> List[DailyStats]:
        """기간별 통계 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(DailyStats)
                .where(
                    and_(
                        DailyStats.date >= start_date,
                        DailyStats.date <= end_date,
                    )
                )
                .order_by(DailyStats.date)
            )
            return list(result.scalars().all())

    async def get_weekly_stats(self) -> List[DailyStats]:
        """최근 7일 통계"""
        end_date = date.today()
        start_date = end_date - timedelta(days=6)
        return await self.get_range(start_date, end_date)

    async def get_monthly_stats(self) -> List[DailyStats]:
        """최근 30일 통계"""
        end_date = date.today()
        start_date = end_date - timedelta(days=29)
        return await self.get_range(start_date, end_date)


class SignalRepository:
    """신호 기록 리포지토리"""

    async def create(
        self,
        stock_code: str,
        stock_name: str,
        strategy: str,
        signal_type: str,
        price: int,
        strength: Optional[float] = None,
        reason: Optional[str] = None,
        executed: bool = False,
        blocked_reason: Optional[str] = None,
        trade_id: Optional[int] = None,
    ) -> Signal:
        """신호 기록 생성"""
        db = get_db_manager()

        signal = Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy=strategy,
            signal_type=signal_type,
            price=price,
            strength=strength,
            reason=reason,
            executed=executed,
            blocked_reason=blocked_reason,
            trade_id=trade_id,
        )

        async with db.session() as session:
            session.add(signal)
            await session.flush()
            await session.refresh(signal)
            return signal

    async def get_recent(self, limit: int = 50) -> List[Signal]:
        """최근 신호 조회"""
        db = get_db_manager()

        async with db.session() as session:
            result = await session.execute(
                select(Signal)
                .order_by(Signal.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())


class SystemLogRepository:
    """시스템 로그 리포지토리"""

    async def create(
        self,
        level: str,
        category: str,
        message: str,
        details: Optional[str] = None,
        stock_code: Optional[str] = None,
        trade_id: Optional[int] = None,
        order_id: Optional[int] = None,
    ) -> SystemLog:
        """로그 기록"""
        db = get_db_manager()

        log = SystemLog(
            level=level,
            category=category,
            message=message,
            details=details,
            stock_code=stock_code,
            trade_id=trade_id,
            order_id=order_id,
        )

        async with db.session() as session:
            session.add(log)
            await session.flush()
            return log

    async def get_recent(
        self,
        level: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> List[SystemLog]:
        """최근 로그 조회"""
        db = get_db_manager()

        async with db.session() as session:
            query = select(SystemLog)

            if level:
                query = query.where(SystemLog.level == level)
            if category:
                query = query.where(SystemLog.category == category)

            query = query.order_by(SystemLog.created_at.desc()).limit(limit)

            result = await session.execute(query)
            return list(result.scalars().all())


# 싱글톤 인스턴스
_trade_repo: Optional[TradeRepository] = None
_order_repo: Optional[OrderRepository] = None
_daily_stats_repo: Optional[DailyStatsRepository] = None
_signal_repo: Optional[SignalRepository] = None
_system_log_repo: Optional[SystemLogRepository] = None


def get_trade_repository() -> TradeRepository:
    """TradeRepository 싱글톤"""
    global _trade_repo
    if _trade_repo is None:
        _trade_repo = TradeRepository()
    return _trade_repo


def get_order_repository() -> OrderRepository:
    """OrderRepository 싱글톤"""
    global _order_repo
    if _order_repo is None:
        _order_repo = OrderRepository()
    return _order_repo


def get_daily_stats_repository() -> DailyStatsRepository:
    """DailyStatsRepository 싱글톤"""
    global _daily_stats_repo
    if _daily_stats_repo is None:
        _daily_stats_repo = DailyStatsRepository()
    return _daily_stats_repo


def get_signal_repository() -> SignalRepository:
    """SignalRepository 싱글톤"""
    global _signal_repo
    if _signal_repo is None:
        _signal_repo = SignalRepository()
    return _signal_repo


def get_system_log_repository() -> SystemLogRepository:
    """SystemLogRepository 싱글톤"""
    global _system_log_repo
    if _system_log_repo is None:
        _system_log_repo = SystemLogRepository()
    return _system_log_repo


def reset_repositories() -> None:
    """
    모든 싱글톤 리포지토리 인스턴스 초기화

    주로 테스트 환경에서 사용됩니다. 테스트 간 상태 격리를 위해
    각 테스트 전후에 호출하여 싱글톤 인스턴스를 초기화합니다.

    Usage (pytest):
        @pytest.fixture(autouse=True)
        def reset_singletons():
            reset_repositories()
            yield
            reset_repositories()
    """
    global _trade_repo, _order_repo, _daily_stats_repo, _signal_repo, _system_log_repo
    _trade_repo = None
    _order_repo = None
    _daily_stats_repo = None
    _signal_repo = None
    _system_log_repo = None
    logger.debug("리포지토리 싱글톤 초기화됨")
