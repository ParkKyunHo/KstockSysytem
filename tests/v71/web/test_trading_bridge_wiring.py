"""Unit tests for ``src/web/v71/trading_bridge.attach_trading_engine``
P-Wire-1 (kiwoom exchange) + P-Wire-2 (reconciler periodic loop).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from unittest.mock import AsyncMock, patch

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _isolate_flags():
    """Snapshot V71_FF__ env vars + restore after each test."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    saved_kiwoom = {
        k: os.environ.get(k)
        for k in ("KIWOOM_APP_KEY", "KIWOOM_SECRET", "KIWOOM_ENV")
    }
    saved_telegram = {
        k: os.environ.get(k)
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    }
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    for k, v in saved.items():
        os.environ[k] = v
    for k, v in saved_kiwoom.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    for k, v in saved_telegram.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    ff.reload()


# ---------------------------------------------------------------------------
# Group A: feature flag OFF -- kiwoom not constructed (4 cases)
# ---------------------------------------------------------------------------


class TestKiwoomExchangeFlagOff:
    async def test_handle_has_no_kiwoom_objects(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "false"
        ff.reload()
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )

        handle = await attach_trading_engine()
        try:
            assert handle.kiwoom_client is None
            assert handle.order_manager is None
            assert handle.exchange_adapter is None
            assert handle.token_manager is None
            assert handle.rate_limiter is None
        finally:
            await detach_trading_engine(handle)

    async def test_box_manager_independent_of_kiwoom_flag(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "false"
        os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
        ff.reload()
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )

        handle = await attach_trading_engine()
        try:
            assert handle.box_manager is not None
            assert handle.kiwoom_client is None
        finally:
            await detach_trading_engine(handle)

    async def test_detach_when_no_kiwoom_objects_does_not_raise(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "false"
        ff.reload()
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )

        handle = await attach_trading_engine()
        await detach_trading_engine(handle)  # must not raise
        assert handle.kiwoom_client is None

    async def test_handle_default_state_is_all_none(self):
        from src.web.v71.trading_bridge import _TradingEngineHandle

        handle = _TradingEngineHandle()
        assert handle.kiwoom_client is None
        assert handle.order_manager is None
        assert handle.exchange_adapter is None
        assert handle.token_manager is None
        assert handle.rate_limiter is None
        assert handle.box_manager is None
        assert handle.position_manager is None


# ---------------------------------------------------------------------------
# Group B: feature flag ON, env missing -- RuntimeError (3 cases)
# ---------------------------------------------------------------------------


class TestKiwoomExchangeFlagOnEnvMissing:
    async def test_missing_app_key_raises(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ.pop("KIWOOM_APP_KEY", None)
        os.environ["KIWOOM_SECRET"] = "test_secret"
        ff.reload()
        from src.web.v71.trading_bridge import attach_trading_engine

        with pytest.raises(RuntimeError, match="KIWOOM_APP_KEY"):
            await attach_trading_engine()

    async def test_missing_secret_raises(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ.pop("KIWOOM_SECRET", None)
        ff.reload()
        from src.web.v71.trading_bridge import attach_trading_engine

        with pytest.raises(RuntimeError, match="KIWOOM"):
            await attach_trading_engine()

    async def test_empty_string_env_raises(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "   "
        os.environ["KIWOOM_SECRET"] = "   "
        ff.reload()
        from src.web.v71.trading_bridge import attach_trading_engine

        with pytest.raises(RuntimeError, match="KIWOOM"):
            await attach_trading_engine()


# ---------------------------------------------------------------------------
# Group C: flag ON + env present -- exchange wired (4 cases)
# ---------------------------------------------------------------------------


class TestKiwoomExchangeWiring:
    async def test_paper_env_constructs_paper_client(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        os.environ["KIWOOM_ENV"] = "SANDBOX"
        ff.reload()

        with patch(
            "src.database.connection.get_db_manager",
        ) as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                assert handle.kiwoom_client is not None
                assert handle.kiwoom_client.is_paper is True
                assert handle.order_manager is not None
                assert handle.exchange_adapter is not None
            finally:
                await detach_trading_engine(handle)

    async def test_production_env_default(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        os.environ.pop("KIWOOM_ENV", None)  # default = PRODUCTION
        ff.reload()

        with patch(
            "src.database.connection.get_db_manager",
        ) as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                assert handle.kiwoom_client.is_paper is False
            finally:
                await detach_trading_engine(handle)

    async def test_same_instance_invariant_holds(self):
        # exchange_adapter must reuse the same V71KiwoomClient instance
        # the order_manager owns (P5-Kiwoom-Adapter same-instance rule).
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        ff.reload()

        with patch(
            "src.database.connection.get_db_manager",
        ) as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                assert handle.exchange_adapter._client is handle.kiwoom_client
                assert handle.order_manager._client is handle.kiwoom_client
            finally:
                await detach_trading_engine(handle)

    async def test_detach_calls_kiwoom_aclose(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        ff.reload()

        with patch(
            "src.database.connection.get_db_manager",
        ) as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            client = handle.kiwoom_client
            assert client is not None

            with patch.object(client, "aclose") as aclose_mock:
                aclose_mock.return_value = None
                await detach_trading_engine(handle)
                aclose_mock.assert_called_once()
            assert handle.kiwoom_client is None
            assert handle.order_manager is None
            assert handle.exchange_adapter is None


# ---------------------------------------------------------------------------
# Group D: P-Wire-2 reconciler periodic loop (5 cases)
# ---------------------------------------------------------------------------


class TestReconcilerWiring:
    async def test_flag_off_no_task(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["V71_FF__V71__RECONCILIATION_V71"] = "false"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        ff.reload()
        with patch("src.database.connection.get_db_manager") as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                assert handle.reconciler is None
                assert handle.reconciler_task is None
            finally:
                await detach_trading_engine(handle)

    async def test_flag_on_without_kiwoom_raises(self):
        # reconciliation_v71 ON + kiwoom_exchange OFF → RuntimeError.
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "false"
        os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
        ff.reload()
        from src.web.v71.trading_bridge import attach_trading_engine

        with pytest.raises(RuntimeError, match="kiwoom_exchange"):
            await attach_trading_engine()

    async def test_task_started_with_default_interval(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        os.environ.pop("V71_RECONCILER_INTERVAL_SECONDS", None)
        ff.reload()
        with patch("src.database.connection.get_db_manager") as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                assert handle.reconciler is not None
                assert handle.reconciler_task is not None
                assert handle.reconciler_task.get_name() == "v71_reconciler_loop"
                assert not handle.reconciler_task.done()
            finally:
                await detach_trading_engine(handle)
                # Task must be fully resolved after detach.
                assert handle.reconciler_task is None

    async def test_loop_runs_reconcile_all_periodically(self):
        # Use a very short interval + AsyncMock to verify the loop fires
        # repeatedly until cancellation.
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        os.environ["V71_RECONCILER_INTERVAL_SECONDS"] = "0.01"
        ff.reload()
        with patch("src.database.connection.get_db_manager") as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                handle.reconciler.reconcile_all = AsyncMock()
                # Replace the running task with one that uses the patched
                # method -- the original task captured the un-patched
                # reference at creation time.
                handle.reconciler_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handle.reconciler_task

                from src.web.v71.trading_bridge import _reconciler_loop

                handle.reconciler_task = asyncio.create_task(
                    _reconciler_loop(
                        handle.reconciler, interval_seconds=0.01,
                    ),
                )
                await asyncio.sleep(0.05)  # let it tick a few times
                assert handle.reconciler.reconcile_all.await_count >= 2
            finally:
                await detach_trading_engine(handle)

    async def test_loop_survives_reconcile_all_failure(self):
        os.environ["V71_FF__V71__KIWOOM_EXCHANGE"] = "true"
        os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
        os.environ["KIWOOM_APP_KEY"] = "test_key"
        os.environ["KIWOOM_SECRET"] = "test_secret"
        os.environ["V71_RECONCILER_INTERVAL_SECONDS"] = "0.01"
        ff.reload()
        with patch("src.database.connection.get_db_manager") as get_db_mock:
            get_db_mock.return_value.session = lambda: None
            from src.web.v71.trading_bridge import (
                _reconciler_loop,
                attach_trading_engine,
                detach_trading_engine,
            )
            handle = await attach_trading_engine()
            try:
                # Replace the loop with one whose reconcile_all raises
                # repeatedly -- the always-run policy must keep ticking.
                handle.reconciler_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handle.reconciler_task

                handle.reconciler.reconcile_all = AsyncMock(
                    side_effect=RuntimeError("boom"),
                )
                handle.reconciler_task = asyncio.create_task(
                    _reconciler_loop(
                        handle.reconciler, interval_seconds=0.01,
                    ),
                )
                await asyncio.sleep(0.05)
                # Despite RuntimeError, the loop kept running -- multiple
                # attempts means the catch-block fired.
                assert handle.reconciler.reconcile_all.await_count >= 2
                assert not handle.reconciler_task.done()
            finally:
                await detach_trading_engine(handle)


# ---------------------------------------------------------------------------
# Group E: _resolve_reconciler_interval helper (3 cases parametrize)
# ---------------------------------------------------------------------------


class TestReconcilerIntervalHelper:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("60", 60.0),
            ("0.5", 0.5),
            ("", 300.0),       # default
            ("abc", 300.0),    # invalid → fallback
            ("0", 300.0),      # non-positive → fallback
            ("-5", 300.0),     # negative → fallback
        ],
    )
    def test_interval_parsing(self, raw, expected):
        os.environ["V71_RECONCILER_INTERVAL_SECONDS"] = raw
        from src.web.v71.trading_bridge import _resolve_reconciler_interval
        assert _resolve_reconciler_interval() == expected
        os.environ.pop("V71_RECONCILER_INTERVAL_SECONDS", None)


# ---------------------------------------------------------------------------
# Group F: P-Wire-3 helper unit tests (15 cases)
# ---------------------------------------------------------------------------


class TestAsyncioRealClock:
    def test_now_returns_utc_datetime(self):
        from datetime import datetime, timezone

        from src.web.v71.trading_bridge import _AsyncioRealClock

        clock = _AsyncioRealClock()
        result = clock.now()
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc

    async def test_sleep_calls_asyncio_sleep(self):
        from src.web.v71.trading_bridge import _AsyncioRealClock

        clock = _AsyncioRealClock()
        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await clock.sleep(0.5)
        sleep_mock.assert_awaited_once_with(0.5)

    async def test_sleep_until_skips_when_target_in_past(self):
        from datetime import timedelta

        from src.web.v71.trading_bridge import _AsyncioRealClock

        clock = _AsyncioRealClock()
        target = clock.now() - timedelta(seconds=10)
        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            await clock.sleep_until(target)
        sleep_mock.assert_not_awaited()


class TestPgNotificationExecuteShim:
    @staticmethod
    def _mock_session_factory(result_mock):
        """Build a get_db_manager mock whose session() yields a session
        whose execute() returns ``result_mock``."""
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm
        return db, session

    async def test_placeholder_replaced_right_to_left_no_collision(self):
        """``$1`` and ``$11`` must NOT collide -- right-to-left subst."""
        from sqlalchemy import text as sql_text

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        rows_result = AsyncMock()
        rows_result.returns_rows = True
        rows_result.mappings = lambda: AsyncMock(all=lambda: [{"col": 1}])
        # Above is shorthand; we instead patch a concrete return.
        from unittest.mock import MagicMock
        rows_result = MagicMock()
        rows_result.returns_rows = True
        rows_result.mappings.return_value.all.return_value = [{"col": 1}]

        db, session = self._mock_session_factory(rows_result)
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            await execute_fn(
                "SELECT * FROM t WHERE a=$1 AND b=$11", "A", "B",
            )

        sent_text = session.execute.call_args[0][0]
        sent_binds = session.execute.call_args[0][1]
        # SQLAlchemy ``text`` instances stringify back to the SQL
        assert ":p1" in str(sent_text) and ":p11" in str(sent_text)
        assert "$1" not in str(sent_text) and "$11" not in str(sent_text)
        assert sent_binds == {"p1": "A", "p2": "B"}
        # Sanity that we wrapped in text(...)
        assert isinstance(sent_text, type(sql_text("")))

    async def test_select_returns_list_of_mappings(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        result = MagicMock()
        result.returns_rows = True
        result.mappings.return_value.all.return_value = [{"id": 1}, {"id": 2}]

        db, _ = self._mock_session_factory(result)
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            rows = await execute_fn("SELECT id FROM notifications")
        assert rows == [{"id": 1}, {"id": 2}]

    async def test_insert_returns_rowcount(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        result = MagicMock()
        result.returns_rows = False
        result.rowcount = 1

        db, _ = self._mock_session_factory(result)
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            rc = await execute_fn(
                "INSERT INTO notifications (id) VALUES ($1)", "uuid-1",
            )
        assert rc == 1

    async def test_update_returns_rowcount(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        result = MagicMock()
        result.returns_rows = False
        result.rowcount = 3

        db, _ = self._mock_session_factory(result)
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            rc = await execute_fn(
                "UPDATE notifications SET status = 'EXPIRED' "
                "WHERE expires_at <= $1",
                "2026-01-01",
            )
        assert rc == 3

    async def test_empty_params_passes_sql_unchanged(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        result = MagicMock()
        result.returns_rows = False
        result.rowcount = 0

        db, session = self._mock_session_factory(result)
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            await execute_fn("SELECT NOW()")

        sent_text = session.execute.call_args[0][0]
        sent_binds = session.execute.call_args[0][1]
        assert "SELECT NOW()" in str(sent_text)
        assert sent_binds == {}

    async def test_seventeen_placeholders_all_replaced(self):
        """notifications INSERT uses 17 columns -- two-digit safety."""
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        result = MagicMock()
        result.returns_rows = False
        result.rowcount = 1

        db, session = self._mock_session_factory(result)
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            sql = (
                "INSERT INTO notifications "
                "(c1,c2,c3,c4,c5,c6,c7,c8,c9,c10,c11,c12,c13,c14,c15,c16,c17) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,"
                "$16,$17)"
            )
            await execute_fn(sql, *(f"v{i}" for i in range(1, 18)))

        sent_text = str(session.execute.call_args[0][0])
        sent_binds = session.execute.call_args[0][1]
        for i in range(1, 18):
            assert f":p{i}" in sent_text
            assert sent_binds[f"p{i}"] == f"v{i}"
        # No leftover dollar placeholders
        assert "$" not in sent_text or "$$" in sent_text  # sanity: no $N

    async def test_propagates_session_error(self):
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_pg_notification_execute

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=RuntimeError("connection lost"),
        )

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm

        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            execute_fn = await _build_pg_notification_execute()
            with pytest.raises(RuntimeError, match="connection lost"):
                await execute_fn("SELECT 1")


class TestTelegramSendFnBuilder:
    def test_both_credentials_present_returns_callable(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TELEGRAM_CHAT_ID"] = "chat456"
        with patch("src.notification.telegram.TelegramBot") as bot_cls:
            bot_cls.return_value = AsyncMock()
            from src.web.v71.trading_bridge import _build_telegram_send_fn
            fn = _build_telegram_send_fn()
        assert callable(fn)
        bot_cls.assert_called_once()  # constructed exactly once

    @pytest.mark.parametrize(
        "token,chat",
        [
            (None, "chat456"),    # token absent
            ("token123", None),   # chat absent
            ("token123", ""),     # chat blank
            ("", "chat456"),      # token blank
        ],
    )
    def test_missing_credentials_returns_none(self, token, chat, caplog):
        if token is None:
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        else:
            os.environ["TELEGRAM_BOT_TOKEN"] = token
        if chat is None:
            os.environ.pop("TELEGRAM_CHAT_ID", None)
        else:
            os.environ["TELEGRAM_CHAT_ID"] = chat

        from src.web.v71.trading_bridge import _build_telegram_send_fn
        with caplog.at_level("WARNING"):
            fn = _build_telegram_send_fn()
        assert fn is None
        assert any(
            "TELEGRAM_BOT_TOKEN" in r.message
            or "TELEGRAM_CHAT_ID" in r.message
            for r in caplog.records
        )

    async def test_returned_callable_does_not_pass_parse_mode(self):
        """CLAUDE.md Part 1.1: parse_mode forbidden -- defence in depth."""
        os.environ["TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TELEGRAM_CHAT_ID"] = "chat456"
        with patch("src.notification.telegram.TelegramBot") as bot_cls:
            bot = AsyncMock()
            bot.send_message = AsyncMock(return_value=True)
            bot_cls.return_value = bot
            from src.web.v71.trading_bridge import _build_telegram_send_fn
            fn = _build_telegram_send_fn()
            await fn("hello")
        bot.send_message.assert_awaited_once()
        call = bot.send_message.call_args
        assert "parse_mode" not in call.kwargs


# ---------------------------------------------------------------------------
# Group G: P-Wire-3 attach integration (5 cases)
# ---------------------------------------------------------------------------


class _NotificationAttachFixture:
    """Common scaffolding for Group G/H tests."""

    @staticmethod
    def patch_db_manager(stack):
        """Push a get_db_manager mock onto ``stack`` (an ExitStack)."""
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        session = AsyncMock()
        execute_result = MagicMock()
        execute_result.returns_rows = False
        execute_result.rowcount = 0
        session.execute = AsyncMock(return_value=execute_result)

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm
        stack.enter_context(
            patch(
                "src.database.connection.get_db_manager", return_value=db,
            ),
        )
        return db, session


class TestNotificationAttachFlagOff:
    async def test_handle_has_no_notification_objects(self):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "false"
        ff.reload()
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )

        handle = await attach_trading_engine()
        try:
            assert handle.notification_repository is None
            assert handle.notification_queue is None
            assert handle.notification_circuit_breaker is None
            assert handle.notification_service is None
        finally:
            await detach_trading_engine(handle)


class TestNotificationAttachFlagOn:
    async def test_full_stack_started_when_telegram_present(self):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
        os.environ["TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TELEGRAM_CHAT_ID"] = "chat456"
        ff.reload()

        from contextlib import ExitStack

        with ExitStack() as stack:
            _NotificationAttachFixture.patch_db_manager(stack)
            stack.enter_context(
                patch("src.notification.telegram.TelegramBot"),
            )
            # service.start should be awaited; we replace it on the
            # class so the constructed instance picks it up.
            start_mock = AsyncMock()
            stop_mock = AsyncMock()
            stack.enter_context(
                patch(
                    "src.core.v71.notification.v71_notification_service."
                    "V71NotificationService.start",
                    start_mock,
                ),
            )
            stack.enter_context(
                patch(
                    "src.core.v71.notification.v71_notification_service."
                    "V71NotificationService.stop",
                    stop_mock,
                ),
            )
            from src.web.v71.api.system.state import system_state
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )

            handle = await attach_trading_engine()
            try:
                assert handle.notification_repository is not None
                assert handle.notification_queue is not None
                assert handle.notification_circuit_breaker is not None
                assert handle.notification_service is not None
                start_mock.assert_awaited_once()
                assert system_state.telegram_active is True
            finally:
                await detach_trading_engine(handle)

    async def test_queue_only_mode_when_telegram_missing(self):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)
        ff.reload()

        from contextlib import ExitStack

        with ExitStack() as stack:
            _NotificationAttachFixture.patch_db_manager(stack)
            from src.web.v71.api.system.state import system_state
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )

            handle = await attach_trading_engine()
            try:
                assert handle.notification_repository is not None
                assert handle.notification_queue is not None
                assert handle.notification_circuit_breaker is not None
                # Service NOT created -- queue-only mode
                assert handle.notification_service is None
                assert system_state.telegram_active is False
            finally:
                await detach_trading_engine(handle)

    async def test_db_build_failure_raises_after_log(self, caplog):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
        os.environ["TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TELEGRAM_CHAT_ID"] = "chat456"
        ff.reload()

        with patch(
            "src.database.connection.get_db_manager",
            side_effect=RuntimeError("no db"),
        ):
            from src.web.v71.trading_bridge import attach_trading_engine

            with caplog.at_level("ERROR"), pytest.raises(
                RuntimeError, match="no db",
            ):
                await attach_trading_engine()
            assert any(
                "v71.notification_v71" in r.message
                and "construction failed" in r.message
                for r in caplog.records
            )


# ---------------------------------------------------------------------------
# Group H: P-Wire-3 detach integration (3 cases)
# ---------------------------------------------------------------------------


class TestNotificationDetach:
    async def test_detach_calls_service_stop_first(self):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
        os.environ["TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TELEGRAM_CHAT_ID"] = "chat456"
        ff.reload()

        from contextlib import ExitStack

        call_order: list[str] = []
        with ExitStack() as stack:
            _NotificationAttachFixture.patch_db_manager(stack)
            stack.enter_context(
                patch("src.notification.telegram.TelegramBot"),
            )
            start_mock = AsyncMock()

            async def stop_capture(*_args, **_kwargs):
                call_order.append("notification_stop")

            stack.enter_context(
                patch(
                    "src.core.v71.notification.v71_notification_service."
                    "V71NotificationService.start",
                    start_mock,
                ),
            )
            stack.enter_context(
                patch(
                    "src.core.v71.notification.v71_notification_service."
                    "V71NotificationService.stop",
                    AsyncMock(side_effect=stop_capture),
                ),
            )
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )

            handle = await attach_trading_engine()
            await detach_trading_engine(handle)

        assert call_order == ["notification_stop"]

    async def test_detach_stop_failure_logs_and_continues(self, caplog):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "true"
        os.environ["TELEGRAM_BOT_TOKEN"] = "token123"
        os.environ["TELEGRAM_CHAT_ID"] = "chat456"
        ff.reload()

        from contextlib import ExitStack

        with ExitStack() as stack:
            _NotificationAttachFixture.patch_db_manager(stack)
            stack.enter_context(
                patch("src.notification.telegram.TelegramBot"),
            )
            stack.enter_context(
                patch(
                    "src.core.v71.notification.v71_notification_service."
                    "V71NotificationService.start",
                    AsyncMock(),
                ),
            )
            stack.enter_context(
                patch(
                    "src.core.v71.notification.v71_notification_service."
                    "V71NotificationService.stop",
                    AsyncMock(side_effect=RuntimeError("stop boom")),
                ),
            )
            from src.web.v71.trading_bridge import (
                attach_trading_engine,
                detach_trading_engine,
            )

            handle = await attach_trading_engine()
            with caplog.at_level("WARNING"):
                # Detach must NOT raise even when stop() blows up.
                await detach_trading_engine(handle)
            assert handle.notification_service is None
            assert handle.notification_queue is None
            assert any(
                "notification_service.stop" in r.message
                for r in caplog.records
            )

    async def test_detach_when_never_attached_no_raise(self):
        os.environ["V71_FF__V71__NOTIFICATION_V71"] = "false"
        ff.reload()
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )

        handle = await attach_trading_engine()
        # Nothing was attached, but detach must clear cleanly anyway.
        await detach_trading_engine(handle)
        assert handle.notification_service is None
        assert handle.notification_queue is None
        assert handle.notification_circuit_breaker is None
        assert handle.notification_repository is None
