"""``/api/mcp/bridge``: the WebSocket a browser tab opens so an agent can move it.

Protocol (the Angular ``AgentBridgeService`` is the other half; every frame is one
JSON text message):

1. The socket is accepted first, then refused with an application close code: the
   feature or the bridge is off -> close 4404; the ``Origin`` header is missing or not
   this host (nor in ``viewer.mcp.allowed_origins``) -> close 4403. (A close BEFORE
   accept is an HTTP 403 on the wire, which a browser reports as 1006 and the tab
   would retry forever.) Browsers attach cookies to cross-site WebSocket handshakes, so
   the Origin check is what stops a foreign page from opening this socket; no frame is
   read from a refused socket.
2. The FIRST frame, within ``AUTH_TIMEOUT_S``, must be
   ``{type: "auth", token, tab_id, route, tools: [names], tools_version?, focused}``.
   ``token`` is the user's session JWT -- never in the URL, which would land in proxy
   and browser logs -- or ``null`` on an open install. Anything else -> close 4401.
   Reply ``{type: "ready", ...}``.
3. Server -> tab ``{type: "call", id, tool, args}`` and ``{type: "ping"}``; tab ->
   server ``{type: "result", id, ok, data | error, message?}``, ``{type: "state",
   route, focused, tools?, tools_version?}`` and ``{type: "pong"}``.

The session JWT is re-validated every ping and at its ``exp``; on expiry or rotation
the server closes 4401 so the client stops reconnecting until the user signs in again.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from api.agent import bridge
from api.agent.bridge import TabConn, TabRegistry
from api.agent.tokens import OPEN_PRINCIPAL, install_mode
from api.agent.ui_tools import TAB_ID_PATTERN, tools_version
from api.auth import EDITION_PASSWORD_KEY, SHARE_CLIENT_ROLE, VIEWER_PASSWORD_KEY, _is_open_install, decode_access_token
from api.config import VIEWER_CONFIG, mcp_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

_TAB_ID = re.compile(TAB_ID_PATTERN)
MAX_ROUTE_CHARS = 200
MAX_ANNOUNCED_TOOLS = 64
MAX_TOOL_NAME_CHARS = 64


class ProtocolError(Exception):
    """A frame the protocol does not allow."""


def _allowed_origins() -> set[str]:
    configured = (VIEWER_CONFIG.get("mcp") or {}).get("allowed_origins")
    if not isinstance(configured, list):
        return set()
    return {o.rstrip("/").lower() for o in configured if isinstance(o, str)}


def origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    """Same host as the request, or an operator-listed origin; never absent."""
    if not origin:
        return False
    if origin.rstrip("/").lower() in _allowed_origins():
        return True
    return bool(host) and urlparse(origin).netloc.lower() == (host or "").lower()


def _level_of(payload: dict) -> str:
    """The rights a session's JWT carries; ``edition`` / ``user`` / ``readonly`` as in a token grant."""
    if install_mode() == "multi":
        return "edition" if payload.get("role") in ("admin", "superadmin") else "user"
    return "edition" if payload.get("edition") is True and not _is_open_install(EDITION_PASSWORD_KEY) else "readonly"


def _authenticate(token: Any) -> Optional[tuple[str, str, Optional[str], Optional[float]]]:
    """``(principal, level, session_token, exp)`` for an auth frame's token, else None.

    The principal is the one a token resolves to (``TokenGrant.resolve``): the fixed
    ``_anonymous`` on an open install whatever the JWT's ``sub`` says (an edition login
    there still mints ``_legacy``), otherwise the JWT's own ``sub``.
    """
    if token is None:
        return (OPEN_PRINCIPAL, "readonly", None, None) if _is_open_install(VIEWER_PASSWORD_KEY) else None
    if not isinstance(token, str) or not token:
        return None
    payload = decode_access_token(token)
    if payload is None or payload.get("role") == SHARE_CLIENT_ROLE or payload.get("mcp"):
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    exp = payload.get("exp")
    principal = OPEN_PRINCIPAL if install_mode() == "open" else sub
    return principal, _level_of(payload), token, float(exp) if isinstance(exp, (int, float)) else None


def _session_level(session_token: Optional[str]) -> Optional[str]:
    """The session's current level, or None when it is no longer valid."""
    if session_token is None:
        return "readonly" if _is_open_install(VIEWER_PASSWORD_KEY) else None
    payload = decode_access_token(session_token)
    return None if payload is None else _level_of(payload)


_RESULT_ID = re.compile(r'"id"\s*:\s*"([0-9a-f]{1,32})"')
_RESULT_TYPE = re.compile(r'"type"\s*:\s*"result"')
OVERSIZE_SCAN_CHARS = 1024


def _parse(text: str) -> dict:
    """Decode one frame. The size is checked BEFORE parsing; nesting cannot crash the handler."""
    if len(text) > bridge.MAX_FRAME_BYTES:
        raise ProtocolError("frame too large")
    try:
        frame = json.loads(text)
    except (ValueError, RecursionError) as ex:
        raise ProtocolError("not JSON") from ex
    if not isinstance(frame, dict):
        raise ProtocolError("frame is not an object")
    return frame


async def _read_frame(ws: WebSocket) -> dict:
    message = await ws.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if not isinstance(text, str):
        raise ProtocolError("binary frames are not accepted")
    return _parse(text)


def _announced(frame: dict) -> Optional[tuple[frozenset, Optional[str]]]:
    tools = frame.get("tools")
    version = frame.get("tools_version")
    if not isinstance(tools, list) or len(tools) > MAX_ANNOUNCED_TOOLS:
        return None
    if not all(isinstance(t, str) and 0 < len(t) <= MAX_TOOL_NAME_CHARS for t in tools):
        return None
    if version is not None and (not isinstance(version, str) or len(version) > 64):
        return None
    return frozenset(tools), version


def _route_of(frame: dict) -> Optional[str]:
    route = frame.get("route", "")
    return route if isinstance(route, str) and len(route) <= MAX_ROUTE_CHARS else None


async def _handshake(ws: WebSocket, registry: TabRegistry) -> Optional[tuple[TabConn, Optional[str], Optional[float]]]:
    try:
        frame = await asyncio.wait_for(_read_frame(ws), bridge.AUTH_TIMEOUT_S)
    except asyncio.TimeoutError:
        await ws.close(bridge.CLOSE_UNAUTHORIZED)
        return None
    except ProtocolError:
        await ws.close(bridge.CLOSE_PROTOCOL)
        return None
    identity = _authenticate(frame.get("token", object())) if frame.get("type") == "auth" else None
    announced = _announced(frame)
    route = _route_of(frame)
    tab_id = frame.get("tab_id")
    focused = frame.get("focused", False)
    if identity is None:
        await ws.close(bridge.CLOSE_UNAUTHORIZED)
        return None
    if (announced is None or route is None or not isinstance(tab_id, str)
            or not _TAB_ID.match(tab_id) or not isinstance(focused, bool)):
        await ws.close(bridge.CLOSE_PROTOCOL)
        return None
    user_id, level, session_token, exp = identity
    conn = TabConn(tab_id=tab_id, user_id=user_id, level=level, ws=ws, loop=asyncio.get_running_loop(),
                   tools=announced[0], tools_version=announced[1], route=route, focused=focused)
    conn.send_lock = asyncio.Lock()
    for old in registry.add(conn):
        await old.close(bridge.CLOSE_SUPERSEDED)
    return conn, session_token, exp


async def _receive_loop(ws: WebSocket, conn: TabConn) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        if not isinstance(text, str):
            await ws.close(bridge.CLOSE_PROTOCOL)
            return
        conn.last_seen = time.monotonic()
        if len(text) > bridge.MAX_FRAME_BYTES:
            _reject_oversize(conn, text)
            continue
        try:
            frame = _parse(text)
        except ProtocolError:
            await ws.close(bridge.CLOSE_PROTOCOL)
            return
        kind = frame.get("type")
        if kind == "result":
            call_id = frame.get("id")
            if isinstance(call_id, str):
                conn.resolve(call_id, bridge.result_envelope(frame))
        elif kind == "state":
            _apply_state(conn, frame)


def _reject_oversize(conn: TabConn, text: str) -> None:
    """Drop a frame over the cap WITHOUT parsing it; a result's call still gets ``too_large``."""
    head = text[:OVERSIZE_SCAN_CHARS]
    call_id = _RESULT_ID.search(head)
    if call_id and _RESULT_TYPE.search(head):
        conn.resolve(call_id.group(1), bridge.err(
            "too_large", "The tab's result exceeded the bridge frame cap; narrow the request."))


def _apply_state(conn: TabConn, frame: dict) -> None:
    route = _route_of(frame)
    focused = frame.get("focused")
    if route is not None:
        conn.route = route
    if isinstance(focused, bool):
        conn.focused = focused
    announced = _announced(frame) if "tools" in frame else None
    if announced is not None:
        conn.tools, conn.tools_version = announced
    conn.last_active = time.monotonic()


async def _keepalive(ws: WebSocket, conn: TabConn, session_token: Optional[str], exp: Optional[float]) -> None:
    while True:
        wait = bridge.PING_INTERVAL_S
        if exp is not None:
            wait = min(wait, max(0.05, exp - time.time()))
        await asyncio.sleep(wait)
        settings = mcp_settings()
        if not (settings["enabled"] and settings["bridge"]):
            await ws.close(bridge.CLOSE_DISABLED)
            return
        level = _session_level(session_token)
        if level is None:
            await ws.close(bridge.CLOSE_UNAUTHORIZED)
            return
        conn.level = level
        if time.monotonic() - conn.last_seen > bridge.SILENCE_DROP_S:
            await ws.close(bridge.CLOSE_SILENT)
            return
        await conn.send({"type": "ping"})


@router.websocket("/bridge")
async def tab_bridge(ws: WebSocket) -> None:
    settings = mcp_settings()
    registry: Optional[TabRegistry] = getattr(ws.app.state, "tab_registry", None)
    await ws.accept()
    if not (settings["enabled"] and settings["bridge"]) or registry is None:
        await ws.close(bridge.CLOSE_DISABLED)
        return
    if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(bridge.CLOSE_FORBIDDEN_ORIGIN)
        return
    try:
        joined = await _handshake(ws, registry)
        if joined is None:
            return
        conn, session_token, exp = joined
        try:
            await ws.send_json({
                "type": "ready", "user_id": conn.user_id, "tab_id": conn.tab_id,
                "tools_version": tools_version(), "ping_interval_s": bridge.PING_INTERVAL_S,
                "call_timeout_s": settings["call_timeout_s"],
            })
            await _serve(ws, conn, session_token, exp)
        finally:
            registry.remove(conn)
    except WebSocketDisconnect:
        return


async def _serve(ws: WebSocket, conn: TabConn, session_token: Optional[str], exp: Optional[float]) -> None:
    """Run the reader and the pinger until either ends, then stop the other.

    The cleanup waits with ``asyncio.wait``, never ``gather``: when the handler itself
    is cancelled mid-cleanup (server shutdown; Starlette's TestClient cancels the app
    right after sending ``websocket.disconnect``), ``gather`` re-raises the CHILD's
    untagged ``CancelledError`` in place of the handler's own, so the caller's cancel
    scope no longer recognises it and the cancellation escapes it.
    """
    tasks = [asyncio.ensure_future(_receive_loop(ws, conn)),
             asyncio.ensure_future(_keepalive(ws, conn, session_token, exp))]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.wait(tasks)
    for task in tasks:
        outcome = None if task.cancelled() else task.exception()
        if isinstance(outcome, Exception) and not isinstance(outcome, (WebSocketDisconnect, RuntimeError)):
            logger.warning("Bridge tab %s ended with %r", conn.tab_id, outcome)
