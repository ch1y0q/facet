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
from api.agent.limits import encoded_size
from api.agent.runtime import run_tool
from api.agent.tools_common import TOOL_LEVELS, UNTRUSTED_META, UNTRUSTED_NOTE
from api.agent.ui_tools import UI_TOOLS, UiTool, tool_description

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
    facts = actions.facts_from_context(data)[0]
    rows, _hidden = actions.evaluate(level, facts, TOOL_LEVELS)
    data["level"] = level
    data["actions"] = [{"id": row["id"], "summary": row["summary"], "tools": [t["name"] for t in row["tools"]]}
                       for row in rows]


ACTIVITY_MAX_ITEMS = 50
ACTIVITY_MAX_PATHS = 20


def _cap_activity(activity: dict) -> None:
    """Hold ``user_activity`` to 50 items (the newest) of 20 paths, flagging every cut."""
    items = activity.get("items")
    if not isinstance(items, list):
        return
    if len(items) > ACTIVITY_MAX_ITEMS:
        activity["items"] = items = items[-ACTIVITY_MAX_ITEMS:]
        activity["truncated"] = True
    for item in items:
        paths = item.get("paths") if isinstance(item, dict) else None
        if isinstance(paths, list) and len(paths) > ACTIVITY_MAX_PATHS:
            item["paths"] = paths[:ACTIVITY_MAX_PATHS]
            item["truncated"] = True


CULLING_LISTS = ("confirmed", "pending", "changed", "suggestions_open")


def fit_culling(result: dict, max_bytes: int) -> None:
    """Trim ``culling.confirmed`` / ``pending`` / ``changed`` / ``suggestions_open`` and ``user_activity.items`` to fit ``max_bytes``.

    The tab reports every plan group the user touched, far more than the envelope can hold on a large plan.
    The biggest of the five lists is halved (activity drops its OLDEST half, the culling lists their tail)
    until the whole result fits. A cut culling list sets ``culling.truncated`` (only that: the tab's own capped-plan flag is
    ``culling.plan_truncated``, which is never touched here) and records the true size of
    EVERY list in ``confirmed_count`` / ``pending_count`` / ``changed_count`` / ``suggestions_open_count`` on the first cut;
    ``groups_total`` and ``untouched`` are never touched, so they stay true. The activity sets
    ``user_activity.truncated`` when it is cut and keeps its ``until``. A context without a ``culling`` block
    still has its activity capped and trimmed.
    """
    data = result.get("data") if result.get("ok") else None
    if not isinstance(data, dict):
        return
    found = data.get("user_activity")
    activity: dict = found if isinstance(found, dict) else {}
    if activity:
        _cap_activity(activity)
    if encoded_size(result) <= max_bytes:
        return
    found = data.get("culling")
    culling: dict = found if isinstance(found, dict) else {}
    lists = [name for name in CULLING_LISTS if isinstance(culling.get(name), list)]
    counted = False
    while encoded_size(result) > max_bytes:
        sizes = {name: encoded_size(culling[name]) for name in lists if culling[name]}
        if isinstance(activity.get("items"), list) and activity["items"]:
            sizes["activity"] = encoded_size(activity["items"])
        if not sizes:
            return
        biggest = max(sizes, key=lambda name: sizes[name])
        if biggest == "activity":
            activity["items"] = activity["items"][(len(activity["items"]) + 1) // 2:]
            activity["truncated"] = True
            continue
        if not counted:
            for name in lists:
                culling.setdefault(f"{name}_count", len(culling[name]))
            culling["truncated"] = True
            counted = True
        culling[biggest] = culling[biggest][:len(culling[biggest]) // 2]


def register_ui_tools(server: MCPServer, registry: TabRegistry) -> None:
    for tool in UI_TOOLS:
        TOOL_LEVELS[tool.name] = UI_TOOL_LEVEL
        server.add_tool(
            _make_tool(tool, registry), name=tool.name,
            description=tool_description(tool) + UNTRUSTED_NOTE,
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
                fit_culling(result, settings["max_bytes"])
            return result
        return await run_tool(ctx, tool.name, handler)

    run.__name__ = tool.name
    setattr(run, "__signature__", _signature(tool))
    run.__annotations__ = {p.name: p.annotation for p in _signature(tool).parameters.values()}
    return run
