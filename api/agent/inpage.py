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

import copy
import json
from typing import Any, Mapping

from mcp.server.mcpserver.exceptions import UnexpectedToolError

from api.agent import tokens
from api.agent.internal_client import err
from api.agent.runtime import INPAGE_SCOPE_KEY, SETTINGS_SCOPE_KEY
from api.agent.tools_common import TOOL_LEVELS, tool_visible
from api.agent.ui_tools import UI_TOOLS

# An image block does not survive the JSON-string WebMCP result; ``available_actions`` is covered by the
# tab's own ``ui_get_context.actions``.
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


async def call(server: Any, grant: tokens.SessionGrant, settings: dict, name: str,
               arguments: dict) -> dict:
    """Run tool ``name`` for ``grant`` and return its envelope (never an exception)."""
    if excluded(name):
        return err("invalid_input", f"{name[:64]} is not available to an in-page agent")
    if "tab_id" in arguments:
        return err("invalid_input", "`tab_id` does not apply in-page: the call acts on this tab")
    forced = dict(arguments)
    forced["show"] = False
    tool = server._tool_manager.get_tool(name)
    if tool is not None and "show" not in (tool.parameters or {}).get("properties", {}):
        del forced["show"]
    try:
        result = await server.call_tool(name, forced, SessionContext(grant, settings))
    except UnexpectedToolError:
        return err("upstream_error", "The tool failed unexpectedly")
    envelope = _envelope(result)
    envelope.update(_changed(name, envelope))
    return envelope
