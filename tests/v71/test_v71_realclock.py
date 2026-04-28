"""Unit tests for ``src.core.v71.v71_realclock.V71RealClock``.

Production Clock impl extracted from trading_bridge in P-Wire-4a so
that BuyExecutor / ExitExecutor / NotificationService / ViMonitor share
a single concrete clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


def test_now_returns_utc_datetime():
    from src.core.v71.v71_realclock import V71RealClock

    clock = V71RealClock()
    result = clock.now()
    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_sleep_calls_asyncio_sleep():
    from src.core.v71.v71_realclock import V71RealClock

    clock = V71RealClock()
    with patch(
        "src.core.v71.v71_realclock.asyncio.sleep", new_callable=AsyncMock,
    ) as sleep_mock:
        await clock.sleep(0.5)
    sleep_mock.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_sleep_until_skips_when_target_in_past():
    from src.core.v71.v71_realclock import V71RealClock

    clock = V71RealClock()
    target = clock.now() - timedelta(seconds=10)
    with patch(
        "src.core.v71.v71_realclock.asyncio.sleep", new_callable=AsyncMock,
    ) as sleep_mock:
        await clock.sleep_until(target)
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_sleep_until_sleeps_when_target_in_future():
    from src.core.v71.v71_realclock import V71RealClock

    clock = V71RealClock()
    target = clock.now() + timedelta(seconds=2)
    with patch(
        "src.core.v71.v71_realclock.asyncio.sleep", new_callable=AsyncMock,
    ) as sleep_mock:
        await clock.sleep_until(target)
    sleep_mock.assert_awaited_once()
    # delta should be roughly 2.0s (some jitter from the now() call)
    actual_delta = sleep_mock.await_args.args[0]
    assert 1.0 < actual_delta <= 2.0
