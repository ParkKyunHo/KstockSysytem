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


# ---------------------------------------------------------------------------
# Group J: P-Wire-4a `_coerce_int` (5 cases parametrized)
# ---------------------------------------------------------------------------


class TestCoerceInt:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, 0),
            ("", 0),
            ("00012345", 12345),
            ("abc", 0),
            ("-100", 0),  # security L2: negatives clamped
            (12345, 12345),
        ],
    )
    def test_coerce_int_cases(self, raw, expected):
        from src.web.v71.trading_bridge import _coerce_int
        assert _coerce_int(raw) == expected


# ---------------------------------------------------------------------------
# Group K: `_build_total_capital_cache` (H1/M4 + TTL)
# ---------------------------------------------------------------------------


class TestTotalCapitalCache:
    @staticmethod
    def _make_kiwoom_client(body):
        from unittest.mock import MagicMock
        client = MagicMock()
        response = MagicMock()
        response.body = body
        client.get_account_balance = AsyncMock(return_value=response)
        return client

    async def test_first_refresh_populates_cache(self):
        from src.web.v71.trading_bridge import _build_total_capital_cache

        client = self._make_kiwoom_client(
            {"prsm_dpst_aset_amt": "0001000000"},
        )
        get_total, refresh = _build_total_capital_cache(client)
        assert get_total() == 0  # before refresh
        await refresh()
        assert get_total() == 1000000

    async def test_kiwoom_error_falls_back_to_zero(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_total_capital_cache

        client = MagicMock()
        client.get_account_balance = AsyncMock(
            side_effect=RuntimeError("kt00018 down"),
        )
        _, refresh = _build_total_capital_cache(client)
        await refresh()
        get_total, _ = _build_total_capital_cache(client)
        assert get_total() == 0  # fail-secure

    async def test_body_not_dict_returns_zero(self):
        # M4 form check: body is a string -> caching 0 + WARNING
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_total_capital_cache

        client = MagicMock()
        response = MagicMock()
        response.body = "ERROR_STRING"
        client.get_account_balance = AsyncMock(return_value=response)
        get_total, refresh = _build_total_capital_cache(client)
        await refresh()
        assert get_total() == 0

    async def test_missing_keys_returns_zero(self):
        from src.web.v71.trading_bridge import _build_total_capital_cache

        client = self._make_kiwoom_client({"unrelated_key": "12345"})
        get_total, refresh = _build_total_capital_cache(client)
        await refresh()
        assert get_total() == 0

    async def test_inflight_guard_blocks_concurrent_refreshes(self):
        # H1 inflight: simulate burst of sync get_total_capital() calls;
        # each schedules at most one refresh.
        from src.web.v71.trading_bridge import _build_total_capital_cache

        client = self._make_kiwoom_client(
            {"prsm_dpst_aset_amt": "0001000000"},
        )
        get_total, _ = _build_total_capital_cache(client)
        # Drain prior value so first sync call expires TTL
        # 100 sync calls before any task gets a chance to run
        for _ in range(100):
            get_total()
        # Yield once so the create_task can drain
        await asyncio.sleep(0)
        # Wait briefly for the refresh to land
        for _ in range(5):
            if client.get_account_balance.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        assert client.get_account_balance.await_count == 1


# ---------------------------------------------------------------------------
# Group L: `_build_invested_pct_factory` (4 cases)
# ---------------------------------------------------------------------------


class TestInvestedPctFactory:
    @staticmethod
    def _pos(stock, qty, price, status="OPEN"):
        from types import SimpleNamespace
        return SimpleNamespace(
            stock_code=stock,
            weighted_avg_price=price,
            total_quantity=qty,
            status=status,
        )

    def test_capital_zero_returns_zero(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_invested_pct_factory

        pm = MagicMock()
        pm.list_for_stock.return_value = [self._pos("005930", 10, 70000)]
        factory = _build_invested_pct_factory(pm, lambda: 0)
        assert factory("005930") == 0.0

    def test_empty_positions_returns_zero(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_invested_pct_factory

        pm = MagicMock()
        pm.list_for_stock.return_value = []
        factory = _build_invested_pct_factory(pm, lambda: 1000000)
        assert factory("005930") == 0.0

    def test_open_and_partial_summed(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_invested_pct_factory

        pm = MagicMock()
        pm.list_for_stock.return_value = [
            self._pos("005930", 10, 50000, "OPEN"),         # 500,000
            self._pos("005930", 5, 60000, "PARTIAL_CLOSED"),  # 300,000
        ]
        factory = _build_invested_pct_factory(pm, lambda: 2000000)
        # (500_000 + 300_000) / 2_000_000 * 100 = 40.0
        assert factory("005930") == 40.0

    def test_closed_excluded(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_invested_pct_factory

        pm = MagicMock()
        pm.list_for_stock.return_value = [
            self._pos("005930", 10, 50000, "OPEN"),       # included 500k
            self._pos("005930", 20, 50000, "CLOSED"),     # excluded 1M
        ]
        factory = _build_invested_pct_factory(pm, lambda: 1000000)
        assert factory("005930") == 50.0


# ---------------------------------------------------------------------------
# Group M: `_build_prev_close_cache` + `_build_tracked_stock_lookup` +
#          `_load_tracked_stocks_cache`
# ---------------------------------------------------------------------------


class TestPrevCloseCache:
    async def test_cache_miss_returns_zero(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_prev_close_cache

        client = MagicMock()
        get_prev, _cache = _build_prev_close_cache(client)
        assert get_prev("005930") == 0
        # Drain orphan task
        await asyncio.sleep(0)

    async def test_cache_hit_returns_value(self):
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _build_prev_close_cache

        client = MagicMock()
        get_prev, cache = _build_prev_close_cache(client)
        cache["005930"] = ("20260427", 75000)
        assert get_prev("005930") == 75000


class TestTrackedStockLookup:
    def test_hit_returns_stock_code(self):
        from src.web.v71.trading_bridge import _build_tracked_stock_lookup

        lookup, _ = _build_tracked_stock_lookup({"uuid-1": "005930"})
        assert lookup("uuid-1") == "005930"

    def test_miss_raises_keyerror(self):
        from src.web.v71.trading_bridge import _build_tracked_stock_lookup

        lookup, _ = _build_tracked_stock_lookup({})
        with pytest.raises(KeyError):
            lookup("nonexistent")


class TestLoadTrackedStocksCache:
    async def test_normal_select_returns_dict(self):
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        # Build a mock that yields (id, "005930"), (id2, "012345")
        rows = [("uuid-1", "005930"), ("uuid-2", "012345")]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm

        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            from src.web.v71.trading_bridge import _load_tracked_stocks_cache
            cache = await _load_tracked_stocks_cache()
        assert cache == {"uuid-1": "005930", "uuid-2": "012345"}

    async def test_invalid_stock_codes_filtered(self, caplog):
        # M1 regex: empty / 4-digit / special chars all skipped
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        rows = [
            ("uuid-1", "005930"),    # valid 6-digit
            ("uuid-2", ""),          # invalid (empty)
            ("uuid-3", "1234"),      # invalid (4 digits)
            ("uuid-4", "12-345"),    # invalid (special char)
            ("uuid-5", "abcdefghi"), # invalid (>8 chars)
        ]
        result_mock = MagicMock()
        result_mock.all.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm

        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            from src.web.v71.trading_bridge import _load_tracked_stocks_cache
            with caplog.at_level("WARNING"):
                cache = await _load_tracked_stocks_cache()
        assert cache == {"uuid-1": "005930"}
        assert any("invalid stock_code" in r.message for r in caplog.records)

    async def test_db_exception_returns_empty(self, caplog):
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=RuntimeError("conn dropped"))

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm

        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            from src.web.v71.trading_bridge import _load_tracked_stocks_cache
            with caplog.at_level("WARNING"):
                cache = await _load_tracked_stocks_cache()
        assert cache == {}
        assert any(
            "tracked_stocks cache prime failed" in r.message
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Group N: `_build_buy_executor` cross-flag invariant (4 cases)
# ---------------------------------------------------------------------------


class TestBuildBuyExecutorCrossFlag:
    @staticmethod
    def _make_full_handle():
        """Construct a handle with all required attrs set to mocks."""
        from unittest.mock import MagicMock

        from src.web.v71.trading_bridge import _TradingEngineHandle

        h = _TradingEngineHandle()
        h.kiwoom_client = MagicMock()
        h.kiwoom_client.get_account_balance = AsyncMock(
            return_value=MagicMock(body={"prsm_dpst_aset_amt": "1000000"}),
        )
        h.exchange_adapter = MagicMock()
        h.box_manager = MagicMock()
        h.position_manager = MagicMock()
        h.position_manager.list_for_stock = MagicMock(return_value=[])
        h.notification_service = MagicMock()
        return h

    @pytest.mark.parametrize(
        "flag_off",
        ["v71.box_system", "v71.kiwoom_exchange", "v71.notification_v71"],
    )
    async def test_missing_flag_raises(self, flag_off):
        for flag in (
            "v71.box_system", "v71.kiwoom_exchange", "v71.notification_v71",
        ):
            os.environ[
                f"V71_FF__V71__{flag.split('.')[-1].upper()}"
            ] = "false" if flag == flag_off else "true"
        ff.reload()
        from contextlib import asynccontextmanager
        from unittest.mock import MagicMock

        # Stub DB so the function reaches the cross-flag check
        rows_result = MagicMock()
        rows_result.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=rows_result)

        @asynccontextmanager
        async def _session_cm():
            yield session

        db = MagicMock()
        db.session = _session_cm
        with patch(
            "src.database.connection.get_db_manager", return_value=db,
        ):
            from src.web.v71.trading_bridge import _build_buy_executor
            handle = self._make_full_handle()
            with pytest.raises(RuntimeError, match="dependencies are OFF"):
                await _build_buy_executor(handle)

    async def test_notification_service_none_raises(self):
        for flag in (
            "box_system", "kiwoom_exchange", "notification_v71",
        ):
            os.environ[f"V71_FF__V71__{flag.upper()}"] = "true"
        ff.reload()
        from src.web.v71.trading_bridge import _build_buy_executor
        handle = self._make_full_handle()
        handle.notification_service = None
        with pytest.raises(RuntimeError, match="notification_service"):
            await _build_buy_executor(handle)


# ---------------------------------------------------------------------------
# Group O: attach/detach integration with feature flag
# ---------------------------------------------------------------------------


class TestBuyExecutorAttachDetach:
    async def test_attach_buy_executor_flag_off_leaves_slots_none(self):
        os.environ["V71_FF__V71__BUY_EXECUTOR_V71"] = "false"
        ff.reload()
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )
        handle = await attach_trading_engine()
        try:
            assert handle.buy_executor is None
            assert handle.clock is None
            assert handle.total_capital_refresh is None
            assert handle.prev_close_cache is None
            assert handle.tracked_stock_cache is None
        finally:
            await detach_trading_engine(handle)

    async def test_detach_clears_all_p_wire_4_slots(self):
        # Even when flag was off, detach must reset degraded_vi defensively
        os.environ["V71_FF__V71__BUY_EXECUTOR_V71"] = "false"
        ff.reload()
        from src.web.v71.api.system.state import system_state
        from src.web.v71.trading_bridge import (
            attach_trading_engine,
            detach_trading_engine,
        )
        # Force degraded_vi True to verify reset
        system_state.degraded_vi = True
        handle = await attach_trading_engine()
        await detach_trading_engine(handle)
        assert system_state.degraded_vi is False
        assert handle.buy_executor is None
