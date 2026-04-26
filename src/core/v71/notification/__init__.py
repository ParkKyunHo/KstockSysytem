"""V7.1 notification package (P4.1).

Spec:
  - 02_TRADING_RULES.md §9 (severity tiers, priority queue, circuit breaker,
    rate limit, standard message format)
  - 07_SKILLS_SPEC.md §6 (notification_skill)
  - 03_DATA_MODEL.md §3.4 (notifications table)

Modules:
  - v71_notification_repository: persistence Protocol + in-memory + PG impls
  - v71_circuit_breaker: 3-fail / 30s timeout (Closed/Open/Half-Open)
  - v71_notification_queue: queue API w/ rate limit + expiry
  - v71_notification_service: Notifier Protocol implementation +
    async worker that drains the queue through the Telegram bot

Constitution:
  3 (no V7.0 collision): everything lives in v71/. The Telegram client is
    the V7.0 ``src.notification.telegram.TelegramBot`` (single direction
    import, parse_mode-disabled guard already in place).
  4 (system keeps running): Circuit Breaker isolates Telegram outages;
    CRITICAL notifications stay queued indefinitely, MEDIUM/LOW expire
    after 5 minutes (§9.4).
  5 (simplicity): pure pure dataclasses + Protocol DI + small worker.
"""

from src.core.v71.notification.v71_circuit_breaker import (
    V71CircuitBreaker,
    V71CircuitState,
)
from src.core.v71.notification.v71_daily_summary import (
    DailySummaryContext,
    ScheduledTime,
    V71DailySummary,
    V71DailySummaryScheduler,
)
from src.core.v71.notification.v71_monthly_review import (
    MonthlyCounts,
    MonthlyReviewContext,
    MonthlyReviewItem,
    V71MonthlyReview,
    V71MonthlyReviewScheduler,
)
from src.core.v71.notification.v71_notification_queue import (
    V71NotificationQueue,
)
from src.core.v71.notification.v71_notification_repository import (
    InMemoryNotificationRepository,
    NotificationRecord,
    NotificationRepository,
    NotificationStatus,
)
from src.core.v71.notification.v71_notification_service import (
    V71NotificationService,
)
from src.core.v71.notification.v71_telegram_commands import (
    COMMANDS,
    CommandContext,
    TrackedSummary,
    V71TelegramCommands,
)

__all__ = [
    "COMMANDS",
    "CommandContext",
    "DailySummaryContext",
    "InMemoryNotificationRepository",
    "NotificationRecord",
    "NotificationRepository",
    "NotificationStatus",
    "ScheduledTime",
    "TrackedSummary",
    "V71CircuitBreaker",
    "V71CircuitState",
    "MonthlyCounts",
    "MonthlyReviewContext",
    "MonthlyReviewItem",
    "V71DailySummary",
    "V71DailySummaryScheduler",
    "V71MonthlyReview",
    "V71MonthlyReviewScheduler",
    "V71NotificationQueue",
    "V71NotificationService",
    "V71TelegramCommands",
]
