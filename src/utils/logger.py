"""
구조화된 로깅 모듈

structlog를 사용하여 JSON 형식의 구조화된 로그를 제공합니다.
모든 타임스탬프는 KST(한국 표준시)로 표시됩니다.
"""

import logging
import sys
import uuid
from datetime import datetime, timezone, timedelta, date as date_type
from typing import Any, Dict, Optional
import structlog
from structlog.types import Processor

from src.utils.config import get_settings


# KST 타임존 (UTC+9)
KST = timezone(timedelta(hours=9))


def get_kst_now() -> datetime:
    """현재 KST 시간 반환"""
    return datetime.now(KST)


def generate_correlation_id(stock_code: str, trade_id: Optional[int] = None) -> str:
    """
    V6.2-A D1: 거래 추적용 correlation_id 생성

    형식: {stock_code}_{YYYYMMDD}_{trade_id or uuid8}
    예: 005930_20260103_42 또는 005930_20260103_a1b2c3d4

    Args:
        stock_code: 종목코드
        trade_id: DB의 trade.id (없으면 uuid 사용)

    Returns:
        고유한 correlation_id 문자열
    """
    date_str = date_type.today().strftime("%Y%m%d")
    if trade_id is not None:
        return f"{stock_code}_{date_str}_{trade_id}"
    return f"{stock_code}_{date_str}_{uuid.uuid4().hex[:8]}"


def kst_timestamper(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """KST 타임스탬프 추가 프로세서"""
    event_dict["timestamp"] = get_kst_now().strftime("%Y-%m-%d %H:%M:%S KST")
    return event_dict


def add_app_context(
    logger: logging.Logger, method_name: str, event_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """앱 컨텍스트 추가"""
    settings = get_settings()
    event_dict["environment"] = settings.environment
    event_dict["is_paper_trading"] = settings.is_paper_trading
    return event_dict


def setup_logging(
    log_level: Optional[str] = None,
    log_format: Optional[str] = None,
) -> None:
    """
    로깅 설정을 초기화합니다.

    Args:
        log_level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: 로그 포맷 (json, console)
    """
    settings = get_settings()

    level = log_level or settings.log_level
    fmt = log_format or settings.log_format

    # 로그 레벨 매핑
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    numeric_level = level_map.get(level.upper(), logging.INFO)

    # 공통 프로세서
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        kst_timestamper,  # KST 타임스탬프 사용
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        add_app_context,
    ]

    if fmt.lower() == "json":
        # JSON 포맷 (운영 환경)
        renderer: Processor = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        # 콘솔 포맷 (개발 환경)
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 표준 로깅 핸들러 설정
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )

    # 루트 로거 설정
    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)
    root_logger.setLevel(numeric_level)

    # 서드파티 라이브러리 로그 레벨 조정
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """
    로거 인스턴스를 반환합니다.

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        구조화된 로거 인스턴스
    """
    return structlog.get_logger(name)


class LogContext:
    """
    로그 컨텍스트를 관리하는 컨텍스트 매니저

    사용 예:
        with LogContext(order_id="12345", stock_code="005930"):
            logger.info("주문 처리 중")
    """

    def __init__(self, **kwargs: Any):
        self.context = kwargs

    def __enter__(self) -> "LogContext":
        structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        structlog.contextvars.unbind_contextvars(*self.context.keys())


def bind_context(**kwargs: Any) -> None:
    """전역 로그 컨텍스트에 값 바인딩"""
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """전역 로그 컨텍스트에서 키 제거"""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """전역 로그 컨텍스트 초기화"""
    structlog.contextvars.clear_contextvars()


# 편의를 위한 기본 로거
logger = get_logger("k_stock_trading")
