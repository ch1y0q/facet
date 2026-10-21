"""The in-page agent's door to the server tools: one implementation, run for a logged-in session.

``POST /api/mcp/call`` looks the tool up on the SAME server object ``/mcp`` serves and invokes it
through the SAME wrapper (``runtime.run_tool``: level floor, ``TOOL_REQUIRES`` incl. ``allow_destructive``,
rate limit, caps, audit). The only difference is who the caller is: a duck-typed context shim
whose ASGI scope carries the session's :class:`~api.agent.tokens.SessionGrant` instead of a bearer token.
Nothing here reimplements a tool.

The in-page agent drives the user's own tab, so a few things are fixed server-side rather than trusted:
``show`` is forced off (it has ``ui_show_photos``), ``tab_id`` is refused, ``target: "selection"`` reads
the snapshot the CALLER tab sent (never a bridge tab), and the image tools are not offered.
"""

import asyncio
import copy
import json
from typing import Any, Mapping, Optional

from mcp.server.mcpserver.exceptions import UnexpectedToolError

from api.agent import tokens
from api.agent.internal_client import err
from api.agent.live_updates import LIVE_SINK_OVERRIDE, WriteCollector
from api.agent.runtime import INPAGE_SCOPE_KEY, SETTINGS_SCOPE_KEY
from api.agent.tools_common import TOOL_LEVELS, tool_visible
from api.agent.ui_tools import UI_TOOLS

# An image block does not survive the JSON-string WebMCP result; ``available_actions`` is covered by the
# tab's own ``ui_get_context.actions``.
_broadcasts: set[asyncio.Task] = set()

EXCLUDED_TOOLS = frozenset({"get_thumbnail", "contact_sheet", "available_actions"})
STRIPPED_ARGS = ("show", "tab_id")
SESSION_HEADER = "X-Facet-Agent-Session"


def excluded(name: str) -> bool:
    return name in EXCLUDED_TOOLS or name in {tool.name for tool in UI_TOOLS}


def _schema(raw: Mapping[str, Any]) -> dict:
    schema = copy.deepcopy(dict(raw))
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key in STRIPPED_ARGS:
            properties.pop(key, None)
    if isinstance(schema.get("required"), list):
        schema["required"] = [key for key in schema["required"] if key not in STRIPPED_ARGS]
    return schema


async def listing(server: Any, resolved: tokens.ResolvedGrant, settings: dict) -> list[dict]:
    """The tools the session may call right now: ``tool_visible`` minus the in-page exclusions."""
    out = []
    for tool in await server.list_tools():
        if excluded(tool.name) or not tool_visible(tool.name, resolved, settings):
            continue
        read_only = bool(tool.annotations and tool.annotations.read_only_hint)
        out.append({
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": _schema(tool.input_schema),
            "annotations": {"readOnlyHint": read_only, "consequentialHint": not read_only,
                            "untrustedContentHint": True},
            "required_level": tokens.effective_requirement(TOOL_LEVELS[tool.name]),
        })
    return out


class _Request:
    def __init__(self, scope: dict):
        self.scope = scope
        self.headers: dict = {}


class _RequestContext:
    def __init__(self, request: _Request):
        self.request = request


class SessionContext:
    """What a tool function and ``run_tool`` read from the SDK's ``Context``: ``headers`` and the scope."""

    def __init__(self, grant: tokens.SessionGrant, settings: dict):
        self.request_context = _RequestContext(_Request({INPAGE_SCOPE_KEY: grant, SETTINGS_SCOPE_KEY: settings}))
        self.headers: dict = {}


def _envelope(result: Any) -> dict:
    try:
        parsed = json.loads(result.content[-1].text)
    except (AttributeError, IndexError, ValueError):
        return err("upstream_error", "The tool failed unexpectedly")
    return parsed if isinstance(parsed, dict) else err("upstream_error", "The tool failed unexpectedly")


def _changed(name: str, envelope: dict) -> dict:
    """``changed``: photos a write changed (0 for a dry run or a read)."""
    data = envelope.get("data") if envelope.get("ok") else None
    if not isinstance(data, dict):
        return {}
    affected = data.get("affected")
    extra: dict[str, Any] = {}
    if isinstance(affected, int) and not isinstance(affected, bool):
        extra["changed"] = affected
    return extra


def _broadcast_to_other_tabs(registry: Any, collector: WriteCollector, tab_id: str) -> None:
    """Tell the principal's OTHER tabs about the writes this call made (fire-and-forget, one frame per write)."""
    if collector.principal is None:
        return

    async def send() -> None:
        for frame in collector.frames:
            await registry.broadcast(collector.principal, frame, exclude_tab_id=tab_id)

    task = asyncio.get_running_loop().create_task(send())
    _broadcasts.add(task)
    task.add_done_callback(_broadcasts.discard)


async def call(server: Any, grant: tokens.SessionGrant, settings: dict, name: str,
               arguments: dict, registry: Any = None, tab_id: Optional[str] = None) -> dict:
    """Run tool ``name`` for ``grant`` and return its envelope (never an exception).

    Every photo-changing write the call makes is collected, not broadcast to the caller: the caller IS
    the tab, so the envelope carries ``changed_paths`` (present only when a write ran) and the page applies
    it. The user's other tabs get the same writes as ``changed`` frames when ``tab_id`` names the caller.
    """
    if excluded(name):
        return err("invalid_input", f"{name[:64]} is not available to an in-page agent")
    if "tab_id" in arguments:
        return err("invalid_input", "`tab_id` does not apply in-page: the call acts on this tab")
    forced = dict(arguments)
    forced["show"] = False
    tool = server._tool_manager.get_tool(name)
    if tool is not None and "show" not in (tool.parameters or {}).get("properties", {}):
        del forced["show"]
    collector = WriteCollector()
    marker = LIVE_SINK_OVERRIDE.set(collector)
    try:
        result = await server.call_tool(name, forced, SessionContext(grant, settings))
    except UnexpectedToolError:
        result = None
    finally:
        LIVE_SINK_OVERRIDE.reset(marker)
    envelope = err("upstream_error", "The tool failed unexpectedly") if result is None else _envelope(result)
    if result is not None:
        envelope.update(_changed(name, envelope))
    if collector.wrote:
        envelope["changed_paths"] = collector.paths()
        if registry is not None and tab_id is not None:
            _broadcast_to_other_tabs(registry, collector, tab_id)
    return envelope
