"""Production boot smoke -- 모든 P-Wire 플래그 ON + production 모드일 때
attach_trading_engine이 끝까지 깨지지 않는지 검증.

배경
----
사용자 결정 2026-04-28: paper 트레이딩 단계를 건너뛰고 production 키로
직접 자금을 투입한다. 즉, ``KIWOOM_ENV`` 가 ``SANDBOX`` 가 아니어야 하고
``KIWOOM_APP_KEY`` / ``KIWOOM_APP_SECRET`` 만 사용한다.

이 테스트는 실전 자금 투입 직전 라이프스팬 부팅이 silently 깨지지 않는다
는 invariant 한 줄짜리 안전망이다. 실제 외부 호출(키움 REST / 텔레그램 /
WebSocket / DB)은 모두 mocked -- 본 테스트의 목적은 wiring 그래프 그
자체 (의존성 순서, cross-flag invariant, 슬롯 채움 누락)에만 한정된다.

배포 전 실제 paper smoke가 아닌 dry-run 검증 용도.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils import feature_flags as ff

_PRODUCTION_FLAGS = (
    "v71.kiwoom_exchange",
    "v71.notification_v71",
    "v71.box_system",
    "v71.position_v71",
    "v71.exit_v71",
    "v71.vi_monitor",
    "v71.reconciliation_v71",
    "v71.kiwoom_websocket",
    "v71.buy_executor_v71",
    "v71.exit_executor_v71",
    "v71.exit_orchestrator",
    "v71.daily_summary",
    "v71.monthly_review",
    "v71.telegram_commands_v71",
    "v71.restart_recovery",
)


@pytest.fixture(autouse=True)
def _isolate_env():
    """Snapshot every env var the bridge reads + restore after test."""
    keys = (
        *(
            f"V71_FF__V71__{flag.split('.')[-1].upper()}"
            for flag in _PRODUCTION_FLAGS
        ),
        "KIWOOM_APP_KEY", "KIWOOM_APP_SECRET", "KIWOOM_ENV",
        "KIWOOM_PAPER_APP_KEY", "KIWOOM_PAPER_APP_SECRET",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        "V71_RECONCILER_INTERVAL_SECONDS",
    )
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    ff.reload()


@pytest.fixture
def production_env(_isolate_env):
    """Set every flag ON + production-mode kiwoom env."""
    for flag in _PRODUCTION_FLAGS:
        env_key = f"V71_FF__V71__{flag.split('.')[-1].upper()}"
        os.environ[env_key] = "true"
    os.environ["KIWOOM_APP_KEY"] = "PROD_test_app_key_placeholder"
    os.environ["KIWOOM_APP_SECRET"] = "PROD_test_app_secret_placeholder"
    os.environ["KIWOOM_ENV"] = "PRODUCTION"
    os.environ["TELEGRAM_BOT_TOKEN"] = "telegram_token_placeholder"
    os.environ["TELEGRAM_CHAT_ID"] = "12345"
    # Avoid real ka10081 / kt00018 cache priming bursts.
    os.environ["V71_RECONCILER_INTERVAL_SECONDS"] = "9999"
    ff.reload()


def _mock_db_manager():
    """Stub get_db_manager so tracked_stocks SELECT + repo INSERT both
    succeed without hitting Postgres."""
    rows_result = MagicMock()
    rows_result.all.return_value = []
    insert_result = MagicMock()
    insert_result.returns_rows = False
    insert_result.rowcount = 0

    session = AsyncMock()
    session.execute = AsyncMock(return_value=rows_result)

    @asynccontextmanager
    async def _session_cm():
        yield session

    db = MagicMock()
    db.session = _session_cm
    return db


def _mock_kiwoom_balance():
    """kt00018 stub returning a 1억 capital placeholder so the cache
    primes without raising."""
    response = MagicMock()
    response.body = {"prsm_dpst_aset_amt": "0100000000"}  # 1억 KRW
    return response


@pytest.mark.asyncio
async def test_attach_with_all_flags_on_production_succeeds(production_env):  # noqa: ARG001
    """모든 P-Wire 플래그 ON + production 자격증명 → attach 끝까지 통과
    + 모든 슬롯이 None 이외 값으로 채워짐."""
    # Pre-import patched modules so mock.patch can walk the dotted path.
    import src.core.v71.exchange.kiwoom_client  # noqa: F401
    import src.core.v71.exchange.kiwoom_websocket  # noqa: F401
    import src.core.v71.exchange.token_manager  # noqa: F401
    import src.core.v71.notification.v71_notification_service  # noqa: F401
    import src.notification.telegram  # noqa: F401

    db = _mock_db_manager()

    with (
        patch("src.database.connection.get_db_manager", return_value=db),
        patch(
            "src.notification.telegram.TelegramBot",
            return_value=MagicMock(
                send_message=AsyncMock(return_value=True),
                register_command=MagicMock(),
                start_polling=AsyncMock(),
                stop_polling=AsyncMock(),
            ),
        ),
        patch(
            "src.core.v71.notification.v71_notification_service."
            "V71NotificationService.start", AsyncMock(),
        ),
        patch(
            "src.core.v71.notification.v71_notification_service."
            "V71NotificationService.stop", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_client.V71KiwoomClient."
            "get_account_balance",
            AsyncMock(return_value=_mock_kiwoom_balance()),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "subscribe", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "unsubscribe", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "run", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "aclose", AsyncMock(),
        ),
    ):
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )
        handle = await attach_trading_engine()
        try:
            # Production keys path took effect (paper keys were never read)
            assert handle.kiwoom_client is not None
            assert handle.kiwoom_client.is_paper is False
            assert handle.token_manager is not None
            assert handle.rate_limiter is not None
            assert handle.order_manager is not None
            assert handle.exchange_adapter is not None

            # Trading rule core building blocks
            assert handle.box_manager is not None
            assert handle.position_manager is not None

            # Notification
            assert handle.notification_repository is not None
            assert handle.notification_queue is not None
            assert handle.notification_circuit_breaker is not None
            assert handle.notification_service is not None

            # P-Wire-4a/b/c orchestrators
            assert handle.buy_executor is not None
            assert handle.exit_executor is not None
            assert handle.vi_monitor is not None
            assert handle.clock is not None
            assert handle.total_capital_refresh is not None
            assert handle.prev_close_cache is not None
            assert handle.tracked_stock_cache is not None

            # P-Wire-5 / 6
            assert handle.kiwoom_websocket is not None
            assert handle.kiwoom_websocket_task is not None
            assert handle.exit_calculator is not None
            assert handle.exit_orchestrator is not None

            # P-Wire-2
            assert handle.reconciler is not None
            assert handle.reconciler_task is not None

            # P-Wire-8: daily summary scheduler
            assert handle.daily_summary is not None
            assert handle.daily_summary_scheduler is not None

            # P-Wire-9: monthly review scheduler
            assert handle.monthly_review is not None
            assert handle.monthly_review_scheduler is not None

            # P-Wire-10: telegram bot + commands
            assert handle.telegram_bot is not None
            assert handle.telegram_commands is not None

            # P-Wire-11: restart recovery ran once at attach
            assert handle.restart_recovery is not None
            assert handle.position_reconciler is not None
            assert handle.restart_recovery_report is not None

            # Production mode guarantee: ViMonitor wired so degraded_vi
            # flag is OFF (BuyExecutor uses real is_vi_active).
            from src.web.v71.api.system.state import system_state
            assert system_state.degraded_vi is False
            # Production wiring should toggle telegram_active=True after
            # service.start(). Mocked start; service is non-None which
            # should drive mark_telegram_active(True).
            assert system_state.telegram_active is True
        finally:
            await detach_trading_engine(handle)
            # Yield once so any background tasks (notification worker,
            # reconciler) get a chance to surface cancellation.
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_attach_production_keys_used_not_paper(production_env):  # noqa: ARG001
    """Production 환경에서 paper 키가 설정돼 있어도 attach는 production
    키만 읽어야 한다 (사용자 결정 2026-04-28 ON 모델)."""
    import src.core.v71.exchange.kiwoom_client  # noqa: F401
    import src.core.v71.exchange.kiwoom_websocket  # noqa: F401
    import src.core.v71.exchange.token_manager  # noqa: F401
    import src.core.v71.notification.v71_notification_service  # noqa: F401
    import src.notification.telegram  # noqa: F401

    os.environ["KIWOOM_PAPER_APP_KEY"] = "should_not_be_read"
    os.environ["KIWOOM_PAPER_APP_SECRET"] = "should_not_be_read"
    db = _mock_db_manager()

    with (
        patch("src.database.connection.get_db_manager", return_value=db),
        patch(
            "src.notification.telegram.TelegramBot",
            return_value=MagicMock(
                send_message=AsyncMock(return_value=True),
                register_command=MagicMock(),
                start_polling=AsyncMock(),
                stop_polling=AsyncMock(),
            ),
        ),
        patch(
            "src.core.v71.notification.v71_notification_service."
            "V71NotificationService.start", AsyncMock(),
        ),
        patch(
            "src.core.v71.notification.v71_notification_service."
            "V71NotificationService.stop", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_client.V71KiwoomClient."
            "get_account_balance",
            AsyncMock(return_value=_mock_kiwoom_balance()),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "subscribe", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "unsubscribe", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "run", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.kiwoom_websocket.V71KiwoomWebSocket."
            "aclose", AsyncMock(),
        ),
        patch(
            "src.core.v71.exchange.token_manager.V71TokenManager.__init__",
            return_value=None,
        ) as token_init,
    ):
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )
        handle = await attach_trading_engine()
        try:
            # V71TokenManager was called with PRODUCTION app_key /
            # app_secret (NOT the paper variants).
            kwargs = token_init.call_args.kwargs
            assert kwargs["app_key"] == "PROD_test_app_key_placeholder"
            assert kwargs["app_secret"] == "PROD_test_app_secret_placeholder"
            assert kwargs["is_paper"] is False
        finally:
            await detach_trading_engine(handle)
            await asyncio.sleep(0)
