"""WebSocket endpoint (09_API_SPEC §11).

Single mounted route ``/api/v71/ws``. Authentication priority:

  1. ``Sec-WebSocket-Protocol`` subprotocol (preferred -- not exposed in
     URL, never logged by uvicorn access log). Browser passes the JWT
     directly as the first protocol via
     ``new WebSocket(url, [token])``. Server echoes the same protocol
     back via ``accept(subprotocol=...)`` per RFC 6455.
  2. ``Authorization: Bearer <token>`` header (used by Python /
     server-to-server clients that can set headers on WS upgrade).
  3. ``?token=`` query string (deprecated, kept for transitional clients;
     the request URL gets masked by ``mask_access_log_query_secrets`` in
     ``main.py`` so the JWT is not persisted to journalctl in clear text).
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


def _extract_token(
    websocket: WebSocket, query_token: str | None,
) -> tuple[str | None, str | None]:
    """Return ``(token, subprotocol_to_echo)``.

    ``subprotocol_to_echo`` is non-None only when the client sent a
    ``Sec-WebSocket-Protocol`` header, in which case RFC 6455 requires
    the server to echo one of the offered protocols on accept; we echo
    the first (which is the token itself).
    """
    proto_header = websocket.headers.get("sec-websocket-protocol")
    if proto_header:
        # JWT 는 base64url + dots 만 포함하므로 ',' 단순 split 안전.
        protos = [p.strip() for p in proto_header.split(",") if p.strip()]
        if protos:
            return protos[0], protos[0]

    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip(), None

    return query_token, None


def _authenticate_token(token: str) -> UUID:
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
    token_value, echo_subprotocol = _extract_token(websocket, token)
    try:
        if not token_value:
            raise V71AuthenticationError(
                "Missing access token", error_code="UNAUTHORIZED",
            )
        user_id = _authenticate_token(token_value)
    except V71AuthenticationError:
        # Per RFC 6455 we close before accept with 1008 (policy violation).
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    conn = await connection_manager.register(
        websocket, user_id=user_id, subprotocol=echo_subprotocol,
    )
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
