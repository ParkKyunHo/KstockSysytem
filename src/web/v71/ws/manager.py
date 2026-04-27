"""Per-connection state for the WebSocket router.

Tracks which channels each socket has subscribed to and exposes a single
``broadcast`` entry point used by ``router.py`` when forwarding events
from :data:`event_bus`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import WebSocket

from .messages import ALLOWED_CHANNELS


@dataclass
class WSConnection:
    websocket: WebSocket
    user_id: UUID
    session_id: UUID
    channels: set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[UUID, WSConnection] = {}
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket, *, user_id: UUID) -> WSConnection:
        await websocket.accept()
        conn = WSConnection(
            websocket=websocket,
            user_id=user_id,
            session_id=uuid4(),
        )
        async with self._lock:
            self._conns[conn.session_id] = conn
        return conn

    async def unregister(self, session_id: UUID) -> None:
        async with self._lock:
            self._conns.pop(session_id, None)

    async def subscribe(self, conn: WSConnection, channels: list[str]) -> list[str]:
        valid = [c for c in channels if c in ALLOWED_CHANNELS]
        async with self._lock:
            conn.channels.update(valid)
        return list(valid)

    async def unsubscribe(
        self, conn: WSConnection, channels: list[str],
    ) -> list[str]:
        async with self._lock:
            for c in channels:
                conn.channels.discard(c)
        return list(channels)

    async def snapshot(self) -> list[WSConnection]:
        async with self._lock:
            return list(self._conns.values())

    async def broadcast(self, envelope: dict[str, Any]) -> None:
        channel = envelope.get("channel")
        if not channel:
            return
        for conn in await self.snapshot():
            if channel not in conn.channels:
                continue
            try:
                await conn.websocket.send_json(envelope)
            except Exception:  # noqa: BLE001
                # Connection broke -- mark for cleanup.
                await self.unregister(conn.session_id)


connection_manager = ConnectionManager()
