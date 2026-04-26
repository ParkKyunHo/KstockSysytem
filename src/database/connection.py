"""
데이터베이스 연결 관리

PostgreSQL (메인) + SQLite (폴백) 이중 구조를 지원합니다.
"""

from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator
import asyncio
import sys

# Windows에서 psycopg3 비동기 지원을 위한 이벤트 루프 설정
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import OperationalError

from src.database.models import Base
from src.utils.config import get_database_settings, DatabaseSettings
from src.utils.logger import get_logger


logger = get_logger(__name__)


class DatabaseManager:
    """
    데이터베이스 연결 관리자

    - PostgreSQL 우선 연결 시도
    - 연결 실패 시 SQLite 폴백
    - 비동기 세션 지원
    """

    def __init__(self, settings: Optional[DatabaseSettings] = None):
        self._settings = settings or get_database_settings()
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._is_postgres = False
        self._initialized = False

    @property
    def is_postgres(self) -> bool:
        """PostgreSQL 사용 여부"""
        return self._is_postgres

    @property
    def is_initialized(self) -> bool:
        """초기화 완료 여부"""
        return self._initialized

    async def initialize(self) -> bool:
        """
        데이터베이스 초기화

        PostgreSQL 연결 시도 후 실패 시 SQLite 폴백

        Returns:
            초기화 성공 여부
        """
        if self._initialized:
            return True

        # PostgreSQL 연결 시도 (DATABASE_URL 또는 개별 설정)
        if self._settings.postgres_url:
            try:
                await self._connect_postgres()
                # 연결 정보 로깅 (비밀번호 숨김)
                if self._settings.database_url:
                    # DATABASE_URL에서 호스트 추출
                    url = self._settings.database_url
                    host_info = url.split("@")[-1].split("/")[0] if "@" in url else "configured"
                    logger.info(f"PostgreSQL 연결 성공 (Supabase/URL)", host=host_info)
                else:
                    logger.info(
                        "PostgreSQL 연결 성공",
                        host=self._settings.postgres_host,
                        database=self._settings.postgres_db,
                    )
                self._is_postgres = True
                self._initialized = True
                return True

            except Exception as e:
                logger.warning(f"PostgreSQL 연결 실패, SQLite 폴백: {e}")

        # SQLite 폴백
        try:
            await self._connect_sqlite()
            logger.info("SQLite 연결 성공", path=str(self._settings.sqlite_path))
            self._is_postgres = False
            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"SQLite 연결 실패: {e}")
            return False

    async def _connect_postgres(self) -> None:
        """PostgreSQL 연결"""
        url = self._settings.postgres_async_url

        self._engine = create_async_engine(
            url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            # pgbouncer 호환성: prepared statement 완전 비활성화
            # - 0: 첫 실행부터 prepare (비활성화 아님)
            # - None: prepare 완전 비활성화 (PgBouncer transaction mode 필수)
            connect_args={"prepare_threshold": None},
            # PRD v3.2.1: 트랜잭션 격리 수준 설정 (Phantom Read 방지)
            isolation_level="REPEATABLE READ",
        )

        # 연결 테스트
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # 테이블 생성
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def _connect_sqlite(self) -> None:
        """SQLite 연결"""
        # SQLite 파일 경로
        db_path = self._settings.sqlite_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"sqlite+aiosqlite:///{db_path}"

        self._engine = create_async_engine(
            url,
            echo=False,
        )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # 테이블 생성
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """연결 종료"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._initialized = False
            logger.info("데이터베이스 연결 종료")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        세션 컨텍스트 매니저

        Usage:
            async with db.session() as session:
                session.add(obj)
                await session.commit()
        """
        if not self._initialized or not self._session_factory:
            raise RuntimeError("데이터베이스가 초기화되지 않음")

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def execute(self, statement, params=None):
        """
        SQL 실행

        Args:
            statement: SQL 문 또는 SQLAlchemy 표현식
            params: 파라미터

        Returns:
            실행 결과
        """
        async with self.session() as session:
            result = await session.execute(statement, params)
            return result


# 싱글톤 인스턴스
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """싱글톤 DatabaseManager 인스턴스 반환"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


async def init_database() -> bool:
    """데이터베이스 초기화 (애플리케이션 시작 시 호출)"""
    db = get_db_manager()
    return await db.initialize()


async def close_database() -> None:
    """데이터베이스 연결 종료 (애플리케이션 종료 시 호출)"""
    db = get_db_manager()
    await db.close()


def reset_db_manager() -> None:
    """
    DatabaseManager 싱글톤 인스턴스 초기화

    주로 테스트 환경에서 사용됩니다. 테스트 간 상태 격리를 위해
    각 테스트 전후에 호출하여 싱글톤 인스턴스를 초기화합니다.

    Usage (pytest):
        @pytest.fixture(autouse=True)
        async def reset_db():
            reset_db_manager()
            yield
            await close_database()
            reset_db_manager()
    """
    global _db_manager
    _db_manager = None
    logger.debug("DatabaseManager 싱글톤 초기화됨")
