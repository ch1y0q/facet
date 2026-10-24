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
may land in different processes. The bridge needs ``--workers 1`` (the default); the same goes for
the ``changed`` broadcast, which reaches only the tabs of the process that served the write.
"""

import asyncio
import concurrent.futures
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import WebSocket

from api.agent.internal_client import err, ok
from api.agent.tokens import install_mode
from api.agent.ui_tools import TAB_ERROR_CODES, UI_TOOLS, tools_version

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

def same_origin(origin: str, host: Optional[str]) -> bool:
    """The one same-origin test, shared by the ``/mcp`` gate and the tab WebSocket."""
    return bool(host) and urlparse(origin).netloc.lower() == (host or "").lower()


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

    def add(self, conn: TabConn) -> Optional[list[TabConn]]:
        """Register ``conn``; return the connections it displaced, or None when it is refused.

        Replacement is level-aware, so a lower-rights session cannot knock a higher one off
        the bridge: a newcomer reusing the id of a higher-level tab is refused, and over the
        per-user cap the oldest tab of the LOWEST level present goes (the newcomer is refused
        instead when it ranks below every registered tab).
        """
        rank = LEVEL_RANK.get(conn.level, 0)
        displaced: list[TabConn] = []
        with self._lock:
            tabs = self._tabs.setdefault(conn.user_id, {})
            same = tabs.get(conn.tab_id)
            if same is not None and LEVEL_RANK.get(same.level, 0) > rank:
                return None
            if same is not None:
                displaced.append(tabs.pop(conn.tab_id))
            if len(tabs) >= MAX_TABS_PER_USER:
                lowest = min(LEVEL_RANK.get(t.level, 0) for t in tabs.values())
                if rank < lowest:
                    if same is not None:
                        tabs[same.tab_id] = displaced.pop()
                    return None
            while len(tabs) >= MAX_TABS_PER_USER:
                lowest = min(LEVEL_RANK.get(t.level, 0) for t in tabs.values())
                oldest = min((t for t in tabs.values() if LEVEL_RANK.get(t.level, 0) == lowest),
                             key=lambda t: t.connected_at)
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

    def tabs_for(self, user_id: str, min_level: Optional[str] = None,
                 max_level: Optional[str] = None) -> list[TabConn]:
        """Tabs with ``min_level <= level <= max_level`` (either bound optional)."""
        floor = LEVEL_RANK[min_level] if min_level is not None else 0
        ceiling = LEVEL_RANK[max_level] if max_level is not None else max(LEVEL_RANK.values())
        with self._lock:
            return [t for t in self._tabs.get(user_id, {}).values()
                    if floor <= LEVEL_RANK.get(t.level, 0) <= ceiling]

    def reach_counts(self, user_id: str, min_level: Optional[str] = None,
                     max_level: Optional[str] = None) -> tuple[list[dict], int]:
        """Reachable tabs (public view) and the count of the user's other open tabs, from one locked read."""
        floor = LEVEL_RANK[min_level] if min_level is not None else 0
        ceiling = LEVEL_RANK[max_level] if max_level is not None else max(LEVEL_RANK.values())
        with self._lock:
            every = list(self._tabs.get(user_id, {}).values())
        reach = [t for t in every if floor <= LEVEL_RANK.get(t.level, 0) <= ceiling]
        return self._view(reach), len(every) - len(reach)

    def describe(self, user_id: str, min_level: Optional[str] = None,
                 max_level: Optional[str] = None) -> list[dict]:
        """Public view for ``status``: no sockets, no tool lists, ages instead of clocks."""
        return self._view(self.tabs_for(user_id, min_level, max_level))

    @staticmethod
    def _view(tabs: list[TabConn]) -> list[dict]:
        now = time.monotonic()
        return [{
            "tab_id": t.tab_id,
            "route": t.route,
            "focused": t.focused,
            "last_seen_s": round(now - t.last_seen, 1),
            "tools_current": all(t.current(name) for name in SERVER_TOOL_NAMES),
        } for t in sorted(tabs, key=lambda t: -t.last_active)]

    @staticmethod
    def _out_of_reach(level: str, max_level: Optional[str]) -> str:
        """Why open tabs do not serve this token, worded for the install mode."""
        mode = install_mode()
        if mode == "multi":
            return (f"Only tabs whose account role is below {level} rights are open. Ask the user to "
                    "sign in again if their role changed, or use a token at a lower level.")
        if mode == "legacy" and max_level is not None and LEVEL_RANK[max_level] < LEVEL_RANK["edition"]:
            return ("This token was minted from a viewer-only session, so it reaches only viewer-level "
                    "tabs, and only higher-rights tabs are open. Mint the token from the edition session.")
        if mode == "legacy":
            return (f"Only tabs signed in with less than {level} rights are open. Ask the user to "
                    "unlock edition in the viewer, or use a read-only token.")
        if mode == "open" and max_level is not None and LEVEL_RANK[max_level] < LEVEL_RANK["edition"]:
            return ("A tab of this install is open but runs at a higher level than this token may reach "
                    "(a non-local request cannot steer a local editing tab).")
        return "No open tab is reachable by this token."

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

    async def broadcast(self, user_id: str, frame: dict, exclude_tab_id: Optional[str] = None) -> None:
        """Send ``frame`` to every tab of ``user_id`` (except ``exclude_tab_id``). Never raises.

        A tab that cannot be written to is logged at debug and skipped; it cannot delay or fail the others.
        """
        targets = [t for t in self.tabs_for(user_id) if t.tab_id != exclude_tab_id and not t.closed]
        results = await asyncio.gather(*(t.send(frame) for t in targets), return_exceptions=True)
        for conn, outcome in zip(targets, results):
            if isinstance(outcome, BaseException):
                logger.debug("Broadcast to tab %s failed: %r", conn.tab_id, outcome)

    async def call(self, user_id: str, tool: str, args: dict, *, level: str, tab_id: Optional[str],
                   timeout: float, max_level: Optional[str] = None) -> dict:
        """Forward ``tool`` to the user's tab and wait for its result envelope.

        Only tabs whose session level is at least ``level`` (the token's effective level)
        are considered, and at most ``max_level`` when given (single-password installs: the
        level of the session that minted the token).

        Never raises: ``no_tab`` (no tab, or it closed mid-call), ``tab_outdated``,
        ``tab_timeout`` and ``upstream_error`` (tab sent a broken reply) are envelopes.
        """
        tabs = self.tabs_for(user_id, level, max_level)
        everything = self.tabs_for(user_id)
        if not tabs and everything:
            return err("no_tab", self._out_of_reach(level, max_level))
        if not tabs:
            return err("no_tab", "No Facet tab is open and connected for this user. Ask the user to "
                                 "open the viewer in a browser and sign in.")
        conn, how = self.pick(tabs, tab_id)
        if conn is None:
            if any(t.tab_id == tab_id for t in everything):
                return err("no_tab", f"Tab {tab_id} is open but outside this token's reach: its session "
                                     f"level is outside the range this token can drive (at least {level}, "
                                     f"at most {max_level or 'any'}). `status` lists the tabs it can.")
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
