"""WebSocket endpoint (09_API_SPEC §11).

Single mounted route ``/api/v71/ws``. Authentication: ``Authorization:
Bearer <access_token>`` header (preferred) or ``?token=`` query string.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from ..auth.security import decode_token
from ..config import get_settings
from ..exceptions import V71AuthenticationError
from .event_bus import event_bus
from .manager import WSConnection, connection_manager
from .messages import (
    CLIENT_TYPE_PING,
    CLIENT_TYPE_SUBSCRIBE,
    CLIENT_TYPE_UNSUBSCRIBE,
    TYPE_CONNECTION_ESTABLISHED,
    TYPE_ERROR,
    TYPE_PONG,
    TYPE_SUBSCRIBED,
    TYPE_UNSUBSCRIBED,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _extract_token(websocket: WebSocket, query_token: str | None) -> str | None:
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return query_token


def _authenticate(websocket: WebSocket, query_token: str | None) -> UUID:
    token = _extract_token(websocket, query_token)
    if not token:
        raise V71AuthenticationError("Missing access token", error_code="UNAUTHORIZED")
    settings = get_settings()
    claims = decode_token(token, settings=settings, expected_kind="access")
    return UUID(claims["sub"])


# ---------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------


@router.websocket("/api/v71/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    try:
        user_id = _authenticate(websocket, token)
    except V71AuthenticationError:
        # Per RFC 6455 we close before accept with 1008 (policy violation).
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    conn = await connection_manager.register(websocket, user_id=user_id)
    forward_task = asyncio.create_task(_forward_bus_events(conn))

    try:
        await websocket.send_json(
            {
                "type": TYPE_CONNECTION_ESTABLISHED,
                "session_id": str(conn.session_id),
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
        )
        await _client_loop(conn)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("WebSocket loop error: %s", exc)
    finally:
        forward_task.cancel()
        try:
            await forward_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        await connection_manager.unregister(conn.session_id)


# ---------------------------------------------------------------------
# Client -> server loop
# ---------------------------------------------------------------------


async def _client_loop(conn: WSConnection) -> None:
    while True:
        msg = await conn.websocket.receive_json()
        msg_type = msg.get("type") if isinstance(msg, dict) else None

        if msg_type == CLIENT_TYPE_PING:
            await conn.websocket.send_json({"type": TYPE_PONG})
            continue

        if msg_type == CLIENT_TYPE_SUBSCRIBE:
            channels = msg.get("channels") or []
            if not isinstance(channels, list):
                await _send_error(conn, "channels must be a list")
                continue
            ok = await connection_manager.subscribe(conn, [str(c) for c in channels])
            await conn.websocket.send_json(
                {"type": TYPE_SUBSCRIBED, "channels": ok}
            )
            continue

        if msg_type == CLIENT_TYPE_UNSUBSCRIBE:
            channels = msg.get("channels") or []
            if not isinstance(channels, list):
                await _send_error(conn, "channels must be a list")
                continue
            ok = await connection_manager.unsubscribe(
                conn, [str(c) for c in channels]
            )
            await conn.websocket.send_json(
                {"type": TYPE_UNSUBSCRIBED, "channels": ok}
            )
            continue

        await _send_error(conn, f"Unknown message type: {msg_type}")


async def _send_error(conn: WSConnection, message: str) -> None:
    await conn.websocket.send_json({"type": TYPE_ERROR, "message": message})


# ---------------------------------------------------------------------
# Bus -> server -> client forwarder
# ---------------------------------------------------------------------


async def _forward_bus_events(conn: WSConnection) -> None:
    async with event_bus.subscribe() as queue:
        while True:
            envelope: dict[str, Any] = await queue.get()
            channel = envelope.get("channel")
            if channel and channel in conn.channels:
                try:
                    await conn.websocket.send_json(envelope)
                except Exception:  # noqa: BLE001
                    return
