"""Unit tests for ``src/web/v71/trading_bridge.attach_trading_engine``
P-Wire-1 (kiwoom exchange wiring).
"""

from __future__ import annotations

import os
from unittest.mock import patch

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
