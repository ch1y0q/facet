"""``ui_*`` tools: validate, forward to the user's open tab, wrap the answer.

The list is static (see ``ui_tools``): it is the same with or without a tab, and a
call without one answers ``no_tab`` instead of hanging. Every tool needs only the
``readonly`` grant -- they change what a tab shows, never library data -- and each
runs the same wrapper as the data tools (identity re-check, rate limit, byte cap).
What a tab returns is untrusted: it is bounded and enveloped in ``bridge``.
"""

import inspect
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import ValidationError

from api.agent import actions
from api.agent.bridge import TabRegistry
from api.agent.internal_client import err, validation_issues
from api.agent.runtime import run_tool
from api.agent.tools_common import TOOL_LEVELS, UNTRUSTED_META, UNTRUSTED_NOTE
from api.agent.ui_tools import UI_TOOLS, UiTool

# They change what a tab shows, never library data, so the lowest grant is enough.
UI_TOOL_LEVEL = "readonly"
BRIDGE_DISABLED = ("The tab bridge is disabled on this server (viewer.mcp.bridge is false), "
                   "so ui_* tools cannot reach a browser tab.")


def _signature(tool: UiTool) -> inspect.Signature:
    """``(ctx, *, <model fields>)`` so the SDK derives the MCP schema from the one model."""
    params = [inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context)]
    for name, field in tool.model.model_fields.items():
        default = inspect.Parameter.empty if field.is_required() else field.default
        params.append(inspect.Parameter(
            name, inspect.Parameter.KEYWORD_ONLY, default=default,
            annotation=Annotated[field.annotation, field]))
    return inspect.Signature(params)


def restrict_context(result: dict, level: str) -> None:
    """Rewrite the tab's ``actions`` for the TOKEN's level: the tab built them at its own session's."""
    data = result.get("data") if result.get("ok") else None
    if not isinstance(data, dict):
        return
    raw_gallery, raw_selection = data.get("gallery"), data.get("selection")
    gallery: dict = raw_gallery if isinstance(raw_gallery, dict) else {}
    selection: dict = raw_selection if isinstance(raw_selection, dict) else {}
    raw_count = selection.get("count")
    count = raw_count if isinstance(raw_count, int) else 0
    facts = actions.facts_for(str(data.get("route") or "/"), count, bool(gallery.get("pinned")))
    rows, _hidden = actions.evaluate(level, facts, TOOL_LEVELS)
    data["level"] = level
    data["actions"] = [{"id": row["id"], "summary": row["summary"], "tools": [t["name"] for t in row["tools"]]}
                       for row in rows]


def register_ui_tools(server: MCPServer, registry: TabRegistry) -> None:
    for tool in UI_TOOLS:
        TOOL_LEVELS[tool.name] = UI_TOOL_LEVEL
        server.add_tool(
            _make_tool(tool, registry), name=tool.name,
            description=tool.description + UNTRUSTED_NOTE,
            annotations=ToolAnnotations(
                read_only_hint=tool.read_only, destructive_hint=False,
                idempotent_hint=tool.read_only, open_world_hint=False),
            meta=UNTRUSTED_META,
            structured_output=False)


def _make_tool(tool: UiTool, registry: TabRegistry) -> Any:
    async def run(ctx: Context, **kwargs: Any) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if not settings["bridge"]:
                return err("no_tab", BRIDGE_DISABLED)
            try:
                args = tool.model(**kwargs)
            except ValidationError as ex:
                return err("invalid_input", "Invalid arguments", issues=validation_issues(ex))
            result = await registry.call(
                resolved.principal, tool.name, args.forward(), level=resolved.level,
                tab_id=args.tab_id, timeout=settings["call_timeout_s"],
                max_level=resolved.minted_level)
            if tool.name == "ui_get_context":
                restrict_context(result, resolved.level)
            return result
        return await run_tool(ctx, tool.name, handler)

    run.__name__ = tool.name
    setattr(run, "__signature__", _signature(tool))
    run.__annotations__ = {p.name: p.annotation for p in _signature(tool).parameters.values()}
    return run
