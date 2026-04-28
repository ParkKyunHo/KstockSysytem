"""V71RealClock -- production :class:`Clock` Protocol implementation.

Wraps ``asyncio.sleep`` + UTC ``datetime.now`` for the V7.1 background
services that consume the :class:`Clock` Protocol defined at
``src.core.v71.strategies.v71_buy_executor:Clock``.

Consumers (P-Wire-3 / P-Wire-4):
  * V71NotificationService -- worker loop sleep_until
  * V71BuyExecutor -- PATH_B 09:01 sleep_until
  * V71ExitExecutor -- (no Clock use today, but ExitExecutorContext takes one)
  * V71ViMonitor -- timestamping + (future) timeout sweeps

Tests inject fakes (e.g. ``FakeClock`` in
``tests/v71/strategies/conftest.py``); production wires this single
class so all background tasks share the same time source.

Constitution:
  * §3 (no V7.0 collision): pure stdlib, no V7.0 imports.
  * §4 (system keeps running): does not raise -- ``sleep_until`` clamps
    negative deltas to zero.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone


class V71RealClock:
    """Production Clock impl wrapping ``asyncio.sleep`` + UTC ``now``.

    Stateless: a single instance can be shared by every V7.1 background
    service. Use :class:`tests.helpers.FakeClock` in tests instead.
    """

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def sleep_until(self, target: datetime) -> None:
        delta = (target - self.now()).total_seconds()
        if delta > 0:
            await asyncio.sleep(delta)


__all__ = ["V71RealClock"]
