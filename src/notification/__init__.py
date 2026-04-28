"""V7.1 notification package.

V7.0 templates / reporter / notification_queue 모듈은 Phase A Step D에서 폐기되었습니다.
V7.1 알림 시스템은 ``src/core/v71/notification/`` 패키지가 담당합니다 (V71NotificationService).

여기서는 V7.1 trading_bridge가 fail-secure send 콜러블로 사용하는
``TelegramBot``만 보존합니다.
"""

from src.notification.telegram import TelegramBot, get_telegram_bot

__all__ = [
    "TelegramBot",
    "get_telegram_bot",
]
