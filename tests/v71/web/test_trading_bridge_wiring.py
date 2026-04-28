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
