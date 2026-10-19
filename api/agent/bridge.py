"""The tab registry and call forwarding behind ``ui_*`` tools.

A browser tab holds a WebSocket (``api/routers/mcp_bridge.py``) and announces who it
is and which UI tools it implements. An agent call for a user is forwarded to that
user's best tab as ``{type: "call", id, tool, args}`` and answered by
``{type: "result", id, ok, data | error}``.

In production the SDK awaits async tools on the server's own loop. The registry
is nevertheless guarded by a thread lock and every hand-off goes through
``concurrent.futures``, because the test harnesses run the WebSocket and the MCP
session manager on different loops (Starlette's TestClient portal, or uvicorn
started without the app lifespan).

The registry is per process: with several uvicorn workers a tab and an agent call
may land in different processes. The bridge needs ``--workers 1`` (the default).
"""

import asyncio
import concurrent.futures
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import WebSocket

from api.agent.internal_client import err, ok
from api.agent.ui_tools import UI_TOOLS, tools_version

logger = logging.getLogger(__name__)

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN_ORIGIN = 4403
CLOSE_DISABLED = 4404
CLOSE_SUPERSEDED = 4409
CLOSE_PROTOCOL = 4400
CLOSE_SILENT = 4408

# Rights a tab's session carries, lowest first. A tab serves an agent call only when its
# level is at least the calling token's effective level: otherwise a viewer-password
# session (same `_legacy` principal as the edition session) could feed an edition agent.
LEVEL_RANK = {"readonly": 0, "user": 1, "edition": 2}

AUTH_TIMEOUT_S = 5.0
PING_INTERVAL_S = 25.0
SILENCE_DROP_S = 60.0
MAX_TABS_PER_USER = 8
MAX_FRAME_BYTES = 256 * 1024

MAX_DATA_DEPTH = 8
MAX_STRING_CHARS = 2000
MAX_LIST_ITEMS = 1000
MAX_MESSAGE_CHARS = 500
# Codes a tab may report; anything else becomes upstream_error. `no_active_view`
# is the darkroom action registry's "that view is not mounted".
TAB_ERROR_CODES = frozenset({
    "invalid_input", "not_found", "forbidden_level", "no_active_view", "upstream_error", "too_large",
})


SERVER_TOOL_NAMES = tuple(tool.name for tool in UI_TOOLS)


@dataclass(eq=False)
class TabConn:
    tab_id: str
    user_id: str
    ws: WebSocket
    loop: asyncio.AbstractEventLoop
    tools: frozenset
    tools_version: Optional[str]
    level: str = "readonly"
    route: str = ""
    focused: bool = False
    connected_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)
    pending: dict[str, concurrent.futures.Future] = field(default_factory=dict)
    send_lock: Optional[asyncio.Lock] = None
    closed: bool = False

    def current(self, tool: str) -> bool:
        """True when this tab implements ``tool`` at the server's contract version."""
        if tool not in self.tools:
            return False
        return self.tools_version is None or self.tools_version == tools_version()

    async def _send_local(self, frame: dict) -> None:
        if self.send_lock is None:
            self.send_lock = asyncio.Lock()
        async with self.send_lock:
            await self.ws.send_json(frame)

    async def send(self, frame: dict) -> None:
        """Send from any loop: the socket is only ever written on its own."""
        fut = asyncio.run_coroutine_threadsafe(self._send_local(frame), self.loop)
        await asyncio.wrap_future(fut)

    async def close(self, code: int) -> None:
        """Close the socket from any loop; a socket that is already gone is not an error."""
        try:
            fut = asyncio.run_coroutine_threadsafe(self.ws.close(code), self.loop)
            await asyncio.wrap_future(fut)
        except Exception as ex:
            logger.debug("Closing tab %s with %s failed: %r", self.tab_id, code, ex)

    def resolve(self, call_id: str, envelope: dict) -> bool:
        fut = self.pending.get(call_id)
        if fut is None or fut.done():
            return False
        try:
            fut.set_result(envelope)
        except concurrent.futures.InvalidStateError:
            return False
        return True

    def fail_all(self, envelope: dict) -> None:
        for fut in list(self.pending.values()):
            if not fut.done():
                try:
                    fut.set_result(envelope)
                except concurrent.futures.InvalidStateError:
                    pass


def clean_data(value: Any, depth: int = 0) -> tuple[Any, bool]:
    """Bound untrusted tab data: depth, string length, list length. Returns ``(clean, cut)``."""
    if depth >= MAX_DATA_DEPTH:
        return None, True
    if isinstance(value, str):
        return (value[:MAX_STRING_CHARS], True) if len(value) > MAX_STRING_CHARS else (value, False)
    if isinstance(value, (bool, int, float)) or value is None:
        return value, False
    if isinstance(value, list):
        cut = len(value) > MAX_LIST_ITEMS
        items = [clean_data(item, depth + 1) for item in value[:MAX_LIST_ITEMS]]
        return [item for item, _ in items], cut or any(flag for _, flag in items)
    if isinstance(value, dict):
        cut = False
        out = {}
        for key, item in value.items():
            cleaned, flag = clean_data(item, depth + 1)
            out[str(key)[:MAX_STRING_CHARS]] = cleaned
            cut = cut or flag
        return out, cut
    return str(value)[:MAX_STRING_CHARS], True


def result_envelope(frame: dict) -> dict:
    """A tab's ``result`` frame as a D4 envelope. The tab is untrusted: nothing passes unbounded."""
    if frame.get("ok") is True:
        data, cut = clean_data(frame.get("data"))
        return ok(data, **({"truncated": True} if cut else {}))
    code = frame.get("error")
    message = frame.get("message")
    safe_code = code if isinstance(code, str) and code in TAB_ERROR_CODES else "upstream_error"
    text = message[:MAX_MESSAGE_CHARS] if isinstance(message, str) else "The tab reported an error"
    return err(safe_code, text)


class TabRegistry:
    """``user_id -> tab_id -> TabConn`` for one app."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tabs: dict[str, dict[str, TabConn]] = {}

    def add(self, conn: TabConn) -> list[TabConn]:
        """Register ``conn``; return the connections it displaced (same id, or over the cap)."""
        displaced: list[TabConn] = []
        with self._lock:
            tabs = self._tabs.setdefault(conn.user_id, {})
            same = tabs.pop(conn.tab_id, None)
            if same is not None:
                displaced.append(same)
            while len(tabs) >= MAX_TABS_PER_USER:
                oldest = min(tabs.values(), key=lambda t: t.connected_at)
                displaced.append(tabs.pop(oldest.tab_id))
            tabs[conn.tab_id] = conn
        return displaced

    def remove(self, conn: TabConn) -> None:
        """Drop ``conn`` (only if it is still the registered one) and fail its pending calls."""
        with self._lock:
            tabs = self._tabs.get(conn.user_id)
            if tabs is not None and tabs.get(conn.tab_id) is conn:
                del tabs[conn.tab_id]
                if not tabs:
                    del self._tabs[conn.user_id]
        conn.closed = True
        conn.fail_all(err("no_tab", "The tab closed before it answered"))

    def tabs_for(self, user_id: str, min_level: Optional[str] = None) -> list[TabConn]:
        floor = LEVEL_RANK[min_level] if min_level is not None else 0
        with self._lock:
            return [t for t in self._tabs.get(user_id, {}).values() if LEVEL_RANK.get(t.level, 0) >= floor]

    def describe(self, user_id: str, min_level: Optional[str] = None) -> list[dict]:
        """Public view for ``status``: no sockets, no tool lists, ages instead of clocks."""
        now = time.monotonic()
        return [{
            "tab_id": t.tab_id,
            "route": t.route,
            "focused": t.focused,
            "last_seen_s": round(now - t.last_seen, 1),
            "tools_current": all(t.current(name) for name in SERVER_TOOL_NAMES),
        } for t in sorted(self.tabs_for(user_id, min_level), key=lambda t: -t.last_active)]

    @staticmethod
    def pick(tabs: list[TabConn], tab_id: Optional[str]) -> tuple[Optional[TabConn], str]:
        """The explicit tab, else the most recently focused, else the most recently active."""
        if tab_id is not None:
            return next((t for t in tabs if t.tab_id == tab_id), None), "explicit"
        if not tabs:
            return None, ""
        focused = [t for t in tabs if t.focused]
        if focused:
            return max(focused, key=lambda t: t.last_active), "focused"
        return max(tabs, key=lambda t: t.last_active), "most_recent"

    async def call(self, user_id: str, tool: str, args: dict, *, level: str, tab_id: Optional[str],
                   timeout: float) -> dict:
        """Forward ``tool`` to the user's tab and wait for its result envelope.

        Only tabs whose session level is at least ``level`` (the token's effective level)
        are considered.

        Never raises: ``no_tab`` (no tab, or it closed mid-call), ``tab_outdated``,
        ``tab_timeout`` and ``upstream_error`` (tab sent a broken reply) are envelopes.
        """
        tabs = self.tabs_for(user_id, level)
        if not tabs and self.tabs_for(user_id):
            return err("no_tab", f"Only tabs signed in with less than {level} rights are open. Ask the user to "
                                 "unlock edition in the viewer, or use a read-only token.")
        if not tabs:
            return err("no_tab", "No Facet tab is open and connected for this user. Ask the user to "
                                 "open the viewer in a browser and sign in.")
        conn, how = self.pick(tabs, tab_id)
        if conn is None:
            return err("no_tab", f"Tab {tab_id} is not connected; `status` lists the open tabs.")
        if not conn.current(tool):
            return err("tab_outdated", f"The open tab does not implement {tool} at this server's "
                                       "version. Ask the user to reload the Facet page.")
        call_id = secrets.token_hex(8)
        fut: concurrent.futures.Future = concurrent.futures.Future()
        conn.pending[call_id] = fut
        if conn.closed:
            conn.pending.pop(call_id, None)
            return err("no_tab", "The tab closed before it could be asked")
        try:
            await conn.send({"type": "call", "id": call_id, "tool": tool, "args": args})
            envelope = await asyncio.wait_for(asyncio.wrap_future(fut), timeout)
        except asyncio.TimeoutError:
            return err("tab_timeout", f"The tab did not answer {tool} within {timeout:g} s")
        except Exception as ex:
            logger.info("Bridge send to tab %s failed: %r", conn.tab_id, ex)
            return err("no_tab", "The tab disconnected before it could be asked")
        finally:
            conn.pending.pop(call_id, None)
        tab_info = {"tab_id": conn.tab_id, "route": conn.route, "selected_by": how,
                    "tab_count": len(tabs)}
        if len(tabs) > 1 and how != "explicit":
            tab_info["note"] = (f"{len(tabs)} tabs are open; this used the {how.replace('_', ' ')} one. "
                                "Pass tab_id to target another.")
        return {**envelope, "tab": tab_info}
