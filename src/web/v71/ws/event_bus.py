"""In-process publish/subscribe bus (09_API_SPEC §11).

The trading engine (P5.4.6) calls :meth:`AsyncEventBus.publish` whenever
something interesting happens; the WebSocket layer subscribes via
:meth:`subscribe` and broadcasts to every interested client.

Until P5.4.6 lands the bus is purely receive-only -- this lets the
WebSocket endpoint and message contracts ship now without coupling to
the trading engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

from .messages import ALLOWED_CHANNELS

# Event payload sent over the bus. ``channel`` is one of ALLOWED_CHANNELS.
EventDict = dict[str, Any]


class AsyncEventBus:
    """Fan-out async queue for cross-component events."""

    def __init__(self, queue_size: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[EventDict]] = set()
        self._queue_size = queue_size
        self._lock = asyncio.Lock()

    async def publish(
        self,
        *,
        type: str,
        channel: str,
        data: dict[str, Any],
    ) -> None:
        """Push an event to every active subscriber."""
        if channel not in ALLOWED_CHANNELS:
            raise ValueError(f"Unknown channel: {channel}")
        envelope: EventDict = {
            "type": type,
            "channel": channel,
            "data": _ensure_timestamp(data),
        }
        # Snapshot under lock; deliver outside to avoid blocking.
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                # Slow consumer -- drop oldest then push.
                try:
                    q.get_nowait()
                    q.put_nowait(envelope)
                except Exception:  # noqa: BLE001
                    pass

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[EventDict]]:
        q: asyncio.Queue[EventDict] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subscribers.discard(q)


def _ensure_timestamp(data: dict[str, Any]) -> dict[str, Any]:
    if "timestamp" not in data:
        data = {**data, "timestamp": datetime.now(timezone.utc).isoformat()}
    return data


# Module-level singleton -- both the WebSocket layer and the trading
# engine import the same instance.
event_bus = AsyncEventBus()
