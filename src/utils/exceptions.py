"""
커스텀 예외 클래스 모듈

애플리케이션 전반에서 사용되는 예외들을 정의합니다.
"""


class KStockTradingError(Exception):
    """기본 예외 클래스"""

    def __init__(self, message: str, code: str = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


# =====================
# API 관련 예외
# =====================

class APIError(KStockTradingError):
    """API 호출 관련 기본 예외"""
    pass


class AuthenticationError(APIError):
    """인증 관련 예외 (토큰 발급 실패 등)"""
    pass


class TokenExpiredError(AuthenticationError):
    """토큰 만료 예외"""
    pass


class RateLimitError(APIError):
    """Rate Limit 초과 예외"""

    def __init__(self, message: str = "API 호출 한도 초과", retry_after: int = None):
        super().__init__(message, code="RATE_LIMIT_EXCEEDED")
        self.retry_after = retry_after


class APIResponseError(APIError):
    """API 응답 오류"""

    def __init__(self, message: str, status_code: int = None, response_body: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class CircuitBreakerOpenError(APIError):
    """Circuit Breaker가 열려있어 요청 차단됨"""

    def __init__(self, message: str = "API 연속 실패로 요청이 차단되었습니다"):
        super().__init__(message, code="CIRCUIT_BREAKER_OPEN")


# =====================
# 주문 관련 예외
# =====================

class OrderError(KStockTradingError):
    """주문 관련 기본 예외"""
    pass


class OrderSubmitError(OrderError):
    """주문 제출 실패"""
    pass


class OrderCancelError(OrderError):
    """주문 취소 실패"""
    pass


class InsufficientBalanceError(OrderError):
    """잔고 부족"""
    pass


class InvalidOrderError(OrderError):
    """잘못된 주문 (수량, 가격 등)"""
    pass


# =====================
# 리스크 관련 예외
# =====================

class RiskError(KStockTradingError):
    """리스크 관련 기본 예외"""
    pass


class DailyLossLimitError(RiskError):
    """일일 손실 한도 초과"""

    def __init__(self, current_loss: float, limit: float):
        message = f"일일 손실 한도 초과: 현재 손실 {current_loss:,.0f}원 / 한도 {limit:,.0f}원"
        super().__init__(message, code="DAILY_LOSS_LIMIT")
        self.current_loss = current_loss
        self.limit = limit


class MaxPositionsError(RiskError):
    """최대 보유 종목 수 초과"""

    def __init__(self, current_count: int, limit: int):
        message = f"최대 보유 종목 수 초과: 현재 {current_count}개 / 한도 {limit}개"
        super().__init__(message, code="MAX_POSITIONS")
        self.current_count = current_count
        self.limit = limit


class TradingHoursError(RiskError):
    """거래 시간 외 주문 시도"""
    pass


# =====================
# WebSocket 관련 예외
# =====================

class WebSocketError(KStockTradingError):
    """WebSocket 관련 기본 예외"""
    pass


class WebSocketConnectionError(WebSocketError):
    """WebSocket 연결 실패"""
    pass


class WebSocketDisconnectedError(WebSocketError):
    """WebSocket 연결 끊김"""
    pass


# =====================
# 데이터베이스 관련 예외
# =====================

class DatabaseError(KStockTradingError):
    """데이터베이스 관련 기본 예외"""
    pass


class RecordNotFoundError(DatabaseError):
    """레코드를 찾을 수 없음"""
    pass


class DuplicateRecordError(DatabaseError):
    """중복 레코드"""
    pass


# =====================
# 설정 관련 예외
# =====================

class ConfigurationError(KStockTradingError):
    """설정 관련 예외"""
    pass


class MissingConfigError(ConfigurationError):
    """필수 설정 누락"""

    def __init__(self, config_name: str):
        message = f"필수 설정이 누락되었습니다: {config_name}"
        super().__init__(message, code="MISSING_CONFIG")
        self.config_name = config_name
