"""
데이터베이스 모델 정의

거래 내역, 일일 통계 등 영속화할 데이터 모델입니다.
SQLAlchemy ORM을 사용합니다.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from enum import Enum

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Float,
    DateTime,
    Date,
    Boolean,
    Text,
    Enum as SQLEnum,
    Index,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 베이스 클래스"""
    pass


class OrderSide(str, Enum):
    """주문 방향"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """주문 상태"""
    PENDING = "PENDING"         # 접수 대기
    SUBMITTED = "SUBMITTED"     # 접수됨
    PARTIAL = "PARTIAL"         # 부분 체결
    FILLED = "FILLED"           # 전체 체결
    CANCELLED = "CANCELLED"     # 취소됨
    REJECTED = "REJECTED"       # 거부됨


class TradeStatus(str, Enum):
    """거래 상태"""
    OPEN = "OPEN"           # 보유 중
    CLOSED = "CLOSED"       # 청산됨
    CANCELLED = "CANCELLED" # V6.2-A 코드리뷰 A2: 롤백된 거래 (Order 생성 실패 시)


class EntrySource(str, Enum):
    """포지션 진입 출처"""
    MANUAL = "MANUAL"           # /buy 명령어 수동 매수
    SYSTEM = "SYSTEM"           # /add 후 신호 발생 자동 매수
    HTS = "HTS"                 # HTS 직접 매수 (동기화로 감지됨)
    RESTORED = "RESTORED"       # 시스템 재시작 시 복구됨


class Trade(Base):
    """
    거래 내역 모델

    매수~매도까지의 한 사이클을 나타냅니다.
    """
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 종목 정보
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(100), nullable=False)

    # 전략 정보
    strategy = Column(String(50), nullable=False)  # CEILING_BREAK, SNIPER_TRAP 등

    # 진입 출처 (PRD v2.0: 수동/시스템/HTS 구분)
    # native_enum=False: pgbouncer 호환성 (VARCHAR로 저장)
    entry_source = Column(
        SQLEnum(EntrySource, native_enum=False),
        nullable=False,
        default=EntrySource.SYSTEM
    )

    # 매수 정보
    entry_price = Column(Integer, nullable=False)
    entry_quantity = Column(Integer, nullable=False)
    entry_amount = Column(BigInteger, nullable=False)  # 매수 금액
    entry_time = Column(DateTime, nullable=False, default=datetime.now)
    entry_order_no = Column(String(50), nullable=True)  # 주문번호
    entry_reason = Column(Text, nullable=True)  # 진입 사유

    # 매도 정보 (청산 시 업데이트)
    exit_price = Column(Integer, nullable=True)
    exit_quantity = Column(Integer, nullable=True)
    exit_amount = Column(BigInteger, nullable=True)  # 매도 금액
    exit_time = Column(DateTime, nullable=True)
    exit_order_no = Column(String(50), nullable=True)
    exit_reason = Column(String(100), nullable=True)  # HARD_STOP, TRAILING_STOP, MANUAL 등

    # 손익
    profit_loss = Column(Integer, nullable=True)  # 실현손익 (원)
    profit_loss_rate = Column(Float, nullable=True)  # 수익률 (%)
    holding_seconds = Column(Integer, nullable=True)  # 보유 시간 (초)

    # 상태
    # native_enum=False: pgbouncer 호환성 (VARCHAR로 저장)
    status = Column(SQLEnum(TradeStatus, native_enum=False), nullable=False, default=TradeStatus.OPEN)

    # 메타데이터
    signal_strength = Column(Float, nullable=True)  # 신호 강도
    max_profit_rate = Column(Float, nullable=True)  # 최대 수익률 (보유 중 고점)
    max_loss_rate = Column(Float, nullable=True)    # 최대 손실률 (보유 중 저점)

    # PRD v2.5: 기술적 손절 및 분할 매도
    stop_loss_price = Column(Integer, nullable=True)  # 기술적 손절 가격 (Floor Line)
    is_partial_exit = Column(Boolean, default=False)  # 분할 매도 실행 여부
    entry_floor_line = Column(Integer, nullable=True)  # 진입 시점 바닥 라인

    # PRD v2.5 보완: 트레일링 스탑
    highest_price_after_partial = Column(Integer, nullable=True)  # 분할 익절 후 최고가

    # 타임스탬프
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    # 인덱스
    __table_args__ = (
        Index("ix_trades_entry_time", "entry_time"),
        Index("ix_trades_status", "status"),
        Index("ix_trades_strategy", "strategy"),
    )

    def __repr__(self):
        return (
            f"<Trade(id={self.id}, stock={self.stock_code}, "
            f"status={self.status}, pnl={self.profit_loss})>"
        )


class Order(Base):
    """
    주문 내역 모델

    개별 주문 기록입니다.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 관련 거래
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True, index=True)

    # 종목 정보
    stock_code = Column(String(10), nullable=False, index=True)

    # 주문 정보
    # native_enum=False: pgbouncer 호환성 (VARCHAR로 저장)
    side = Column(SQLEnum(OrderSide, native_enum=False), nullable=False)
    order_type = Column(String(20), nullable=False)  # MARKET, LIMIT 등
    quantity = Column(Integer, nullable=False)
    price = Column(Integer, nullable=True)  # 지정가 주문 시

    # 체결 정보
    filled_quantity = Column(Integer, nullable=False, default=0)
    filled_price = Column(Integer, nullable=True)  # 평균 체결가
    filled_amount = Column(BigInteger, nullable=True)

    # 키움 주문번호
    order_no = Column(String(50), nullable=True, index=True)

    # 상태
    # native_enum=False: pgbouncer 호환성 (VARCHAR로 저장)
    status = Column(SQLEnum(OrderStatus, native_enum=False), nullable=False, default=OrderStatus.PENDING)
    reject_reason = Column(Text, nullable=True)

    # 타임스탬프
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    # 관계
    trade = relationship("Trade", backref="orders")

    __table_args__ = (
        Index("ix_orders_created_at", "created_at"),
    )

    def __repr__(self):
        return (
            f"<Order(id={self.id}, stock={self.stock_code}, "
            f"side={self.side}, status={self.status})>"
        )


class DailyStats(Base):
    """
    일일 통계 모델

    매일의 거래 결과를 집계합니다.
    """
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 날짜 (유니크)
    date = Column(Date, nullable=False, unique=True, index=True)

    # 거래 통계
    trade_count = Column(Integer, nullable=False, default=0)  # 총 거래 수
    win_count = Column(Integer, nullable=False, default=0)    # 수익 거래 수
    loss_count = Column(Integer, nullable=False, default=0)   # 손실 거래 수

    # 손익
    total_profit = Column(BigInteger, nullable=False, default=0)  # 총 수익 (원)
    total_loss = Column(BigInteger, nullable=False, default=0)    # 총 손실 (원)
    net_pnl = Column(BigInteger, nullable=False, default=0)       # 순손익

    # 수익률
    avg_profit_rate = Column(Float, nullable=True)   # 평균 수익률 (수익 거래)
    avg_loss_rate = Column(Float, nullable=True)     # 평균 손실률 (손실 거래)
    win_rate = Column(Float, nullable=True)          # 승률 (%)

    # 시작/종료 잔고
    start_balance = Column(BigInteger, nullable=True)
    end_balance = Column(BigInteger, nullable=True)
    return_rate = Column(Float, nullable=True)  # 일일 수익률 (%)

    # 신호 통계
    signals_detected = Column(Integer, nullable=False, default=0)
    signals_executed = Column(Integer, nullable=False, default=0)
    signals_blocked = Column(Integer, nullable=False, default=0)

    # 타임스탬프
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return (
            f"<DailyStats(date={self.date}, trades={self.trade_count}, "
            f"pnl={self.net_pnl}, win_rate={self.win_rate})>"
        )


class SystemLog(Base):
    """
    시스템 로그 모델

    중요 시스템 이벤트를 기록합니다.
    """
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 로그 정보
    level = Column(String(20), nullable=False)  # INFO, WARNING, ERROR 등
    category = Column(String(50), nullable=False)  # ENGINE, ORDER, RISK 등
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)  # JSON 형태의 추가 정보

    # 관련 엔티티
    stock_code = Column(String(10), nullable=True)
    trade_id = Column(Integer, nullable=True)
    order_id = Column(Integer, nullable=True)

    # 타임스탬프
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_system_logs_level", "level"),
        Index("ix_system_logs_category", "category"),
    )

    def __repr__(self):
        return f"<SystemLog(id={self.id}, level={self.level}, category={self.category})>"


class Signal(Base):
    """
    신호 기록 모델

    탐지된 모든 매수 신호를 기록합니다 (실행 여부 무관).
    """
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 종목 정보
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(100), nullable=False)

    # 신호 정보
    strategy = Column(String(50), nullable=False)
    signal_type = Column(String(20), nullable=False)  # BUY, SELL
    price = Column(Integer, nullable=False)
    strength = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)

    # 실행 여부
    executed = Column(Boolean, nullable=False, default=False)
    blocked_reason = Column(String(100), nullable=True)  # 실행되지 않은 이유
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)

    # 타임스탬프
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)

    # 관계
    trade = relationship("Trade", backref="signals")

    def __repr__(self):
        return (
            f"<Signal(id={self.id}, stock={self.stock_code}, "
            f"strategy={self.strategy}, executed={self.executed})>"
        )
