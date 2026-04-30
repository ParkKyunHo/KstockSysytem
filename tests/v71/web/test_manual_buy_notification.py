"""P-Wire-Manual-Buy-Notification integration tests.

User-reported deficiency #2 (2026-04-30): external (HTS / MTS) buys
landed in the Kiwoom WS but produced no Telegram alert; the silent
``self._on_manual_order is None`` branch in V71OrderManager swallowed
them. Pre-P-Wire callback was never wired because notification_service
is built after the order_manager.

These tests verify two contract points:
    1. V71OrderManager.set_on_manual_order replaces the callback at
       runtime (post-construction wiring).
    2. The trading_bridge factory ``_make_manual_buy_callback`` builds
       a callback that calls the notifier with HIGH severity +
       MANUAL_BUY_DETECTED + stock_code only (no price/qty — 12 §6.3).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.v71.exchange.order_manager import WS_FIELD
from src.web.v71.trading_bridge import _make_manual_buy_callback


def _ws_msg(stock_code: str | None) -> MagicMock:
    """Build a minimal V71WebSocketMessage stub for the callback."""
    msg = MagicMock()
    msg.values = {WS_FIELD["STOCK_CODE"]: stock_code} if stock_code else {}
    return msg


@pytest.mark.asyncio
async def test_callback_emits_high_severity_alert():
    notifier = MagicMock()
    notifier.notify = AsyncMock()
    callback = _make_manual_buy_callback(notifier)

    await callback(_ws_msg("005930"))

    notifier.notify.assert_awaited_once()
    kwargs = notifier.notify.await_args.kwargs
    assert kwargs["severity"] == "HIGH"
    assert kwargs["event_type"] == "MANUAL_BUY_DETECTED"
    assert kwargs["stock_code"] == "005930"
    # 12_SECURITY §6.3: no price / quantity in the message body.
    body = kwargs["message"]
    assert "005930" in body
    # 12 §6.3: no Korean won amount + no fill-quantity labels.
    # "원" stand-alone (after a digit) is the leak signal; we just
    # check that no digit-원 / 주 patterns slip in.
    import re
    assert re.search(r"\d+\s*원", body) is None
    assert re.search(r"\d+\s*주", body) is None


@pytest.mark.asyncio
async def test_callback_handles_unknown_stock_code():
    notifier = MagicMock()
    notifier.notify = AsyncMock()
    callback = _make_manual_buy_callback(notifier)

    await callback(_ws_msg(None))

    kwargs = notifier.notify.await_args.kwargs
    assert kwargs["stock_code"] is None
    assert "(unknown)" in kwargs["message"]


@pytest.mark.asyncio
async def test_callback_swallows_notifier_exception():
    """Constitution 4: a flaky notifier must not crash the WS loop."""
    notifier = MagicMock()
    notifier.notify = AsyncMock(side_effect=RuntimeError("telegram down"))
    callback = _make_manual_buy_callback(notifier)

    # No raise.
    await callback(_ws_msg("005930"))


@pytest.mark.asyncio
async def test_set_on_manual_order_replaces_callback():
    """V71OrderManager.set_on_manual_order assigns the callback at
    runtime (post-construction wiring; trading_bridge calls this once
    the notification service is up)."""
    import os

    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    from src.utils import feature_flags
    feature_flags.reload()

    from src.core.v71.exchange.order_manager import V71OrderManager

    om = V71OrderManager(
        kiwoom_client=MagicMock(),
        db_session_factory=MagicMock(),
    )
    assert om._on_manual_order is None  # noqa: SLF001

    cb = AsyncMock()
    om.set_on_manual_order(cb)
    assert om._on_manual_order is cb  # noqa: SLF001

    # Replace with None (rare, but allowed for shutdown).
    om.set_on_manual_order(None)
    assert om._on_manual_order is None  # noqa: SLF001
