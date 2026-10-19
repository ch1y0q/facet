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

from api.agent.bridge import TabRegistry
from api.agent.internal_client import err, validation_issues
from api.agent.runtime import run_tool
from api.agent.tools_common import UNTRUSTED_META, UNTRUSTED_NOTE
from api.agent.ui_tools import UI_TOOLS, UiTool

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


def register_ui_tools(server: MCPServer, registry: TabRegistry) -> None:
    for tool in UI_TOOLS:
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
            return await registry.call(
                resolved.principal, tool.name, args.forward(), level=resolved.level,
                tab_id=args.tab_id, timeout=settings["call_timeout_s"],
                max_level=resolved.minted_level)
        return await run_tool(ctx, tool.name, handler)

    run.__name__ = tool.name
    setattr(run, "__signature__", _signature(tool))
    run.__annotations__ = {p.name: p.annotation for p in _signature(tool).parameters.values()}
    return run
