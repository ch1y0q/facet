"""``cull_report``: one bounded summary of a scope, built only from existing routes.

A fixed set of ``/api/photos/count`` calls (one per entry of :data:`REPORT_COUNTS`, four at a time)
answers "how much is there, how much is rejected, what hides behind the gallery's hide toggles"; one
``/api/photos`` page gives the top keepers; an edition grant also gets the first darkroom sets. No new
route and no new SQL: every number is the owner's, because each route applies the owner's visibility
and preferences.
"""

import asyncio
from typing import Annotated, Any, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from pydantic import Field

from api.agent import tokens
from api.agent.internal_client import InternalClient, err, ok
from api.agent.limits import encoded_size
from api.agent.runtime import run_tool
from api.agent.tools_common import READ_ANNOTATIONS, register_tool
from api.agent.tools_culling import CULLING_ROUTES, EXIF_TIMESTAMP
from api.agent.tools_write import WRITE_TOOL_LEVELS
from api.agent.tools_read import SearchFilters, _hide_defaults, _query_value

COUNT_CONCURRENCY = 4
TOP_N_MAX = 10
SETS_MAX = 5
REPORT_MAX_BYTES = 6000
HIDE_KEYS = ("hide_blinks", "hide_bursts", "hide_duplicates", "hide_brackets", "hide_panoramas", "hide_rejected")
TOP_KEYS = ("path", "filename", "aggregate", "star_rating")

# (bucket, filters laid over the scope). Every hide toggle is neutralised first, so hidden members count.
REPORT_COUNTS: tuple[tuple[str, dict], ...] = (
    ("total", {}),
    ("rejected", {"show_rejected": 1}),
    ("favorites", {"favorites_only": 1}),
    ("rated", {"min_rating": 1, "hide_rejected": 1}),
    ("favorites_rated", {"favorites_only": 1, "min_rating": 1}),
    ("junk", {"junk_kind": "any"}),
    ("blinks_left_by_toggle", {"hide_blinks": 1}),
    ("bursts_left_by_toggle", {"hide_bursts": 1}),
    ("duplicates_left_by_toggle", {"hide_duplicates": 1}),
    ("brackets_left_by_toggle", {"hide_brackets": 1}),
    ("panoramas_left_by_toggle", {"hide_panoramas": 1}),
)
# Reasons a photo is not in the default view: the total minus what remains once that toggle hides its members.
HIDDEN_REASONS = (("blinks", "blinks_left_by_toggle"), ("burst_non_best", "bursts_left_by_toggle"),
                  ("duplicates_hidden", "duplicates_left_by_toggle"),
                  ("brackets_hidden", "brackets_left_by_toggle"),
                  ("panoramas_hidden", "panoramas_left_by_toggle"))


def _scope(filters: Any) -> dict:
    """The caller's filters minus every hide toggle (the report counts what the toggles would hide)."""
    given = filters.model_dump(exclude_none=True) if filters is not None else {}
    return {key: value for key, value in given.items() if key not in HIDE_KEYS}


async def _count(client: InternalClient, grant: Any, timeout: float, gate: asyncio.Semaphore,
                 query: dict) -> Optional[int]:
    async with gate:
        counted = await client.call(grant, "photos_count", query={k: _query_value(v) for k, v in query.items()},
                                    timeout=timeout)
    return (counted["data"] or {}).get("total") if counted["ok"] else None


def _minus(total: Optional[int], part: Optional[int]) -> Optional[int]:
    return None if total is None or part is None else total - part


def register_report_tools(server: MCPServer, app: Any, client: InternalClient) -> None:
    culling = InternalClient(app, CULLING_ROUTES)

    async def cull_report(
        ctx: Context, filters: Optional[Any] = None,
        low_score_below: Annotated[float, Field(ge=0, le=10)] = 4.0,
        top_n: Annotated[int, Field(ge=1, le=TOP_N_MAX)] = 5,
        target: Optional[Literal["selection"]] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if target is not None:
                return err("invalid_input", "cull_report does not take `target`: a selection is a path list. "
                           "Describe the scope with `filters` (path_prefix, date_from/date_to, album_id ...)")
            timeout = settings["call_timeout_s"]
            scope = _scope(filters)
            gate = asyncio.Semaphore(COUNT_CONCURRENCY)
            table = REPORT_COUNTS + (("low_score", {"max_score": low_score_below}),)
            numbers = await asyncio.gather(*(_count(client, grant, timeout, gate, {**scope, **extra})
                                             for _, extra in table))
            counts = dict(zip((name for name, _ in table), numbers))
            unavailable = sorted(name for name, number in counts.items() if number is None)
            total, rejected = counts["total"], counts["rejected"]
            kept = _minus(total, rejected)
            unreviewed = (None if None in (kept, counts["rated"], counts["favorites"], counts["favorites_rated"])
                          else kept - counts["rated"] - counts["favorites"] + counts["favorites_rated"])
            # A *_left_by_toggle bucket is what stays visible once the toggle hides its members.
            reasons = {name: _minus(total, counts[bucket]) for name, bucket in HIDDEN_REASONS}
            reasons.update(junk=counts["junk"], low_score=counts["low_score"])
            top = await client.call(grant, "search_photos", timeout=timeout, query={
                **{k: _query_value(v) for k, v in _hide_defaults(scope).items()},
                "sort": "aggregate", "sort_direction": "DESC", "page": 1, "per_page": top_n})
            sets, sets_note = None, "needs an edition token"
            if tokens.level_rank(resolved.level) >= tokens.level_rank(tokens.effective_requirement("edition")):
                groups = await culling.call(grant, "culling.groups", timeout=timeout, query={
                    "group_by": "all", "page": 1, "per_page": SETS_MAX, "sort": "easiest",
                    "album_id": scope.get("album_id"),
                    **{k: scope[k] for k in ("date_from", "date_to") if EXIF_TIMESTAMP.match(str(scope.get(k, "")))}})
                sets_note = None if groups["ok"] else "the darkroom feed could not be read"
                sets = [{"type": g.get("type"), "group_id": g.get("group_id"), "photo_count": len(g.get("photos") or []),
                         "keeper_best_path": g.get("keeper_best_path")}
                        for g in ((groups["data"] or {}).get("groups") or [])[:SETS_MAX]] if groups["ok"] else None
            report = {"total": total, "kept": kept, "rejected": rejected, "favorites": counts["favorites"],
                      "rated": counts["rated"], "unreviewed": unreviewed, "reasons": reasons,
                      "top_keepers": [{k: p.get(k) for k in TOP_KEYS}
                                      for p in ((top["data"] or {}).get("photos") or [])[:top_n]] if top["ok"] else None,
                      "sets": sets, "low_score_below": low_score_below,
                      "note": "Reasons overlap: one photo can count in several lines. burst_non_best, duplicates_hidden, "
                              "brackets_hidden and panoramas_hidden are what the gallery's hide toggles would hide; "
                              "unreviewed = not rejected, no star rating, not a favourite."}
            if sets_note:
                report["sets_note"] = sets_note
            if unavailable:
                report["unavailable"] = unavailable
            if encoded_size(report) > REPORT_MAX_BYTES:
                report["top_keepers"] = (report["top_keepers"] or [])[:3]
            return ok(report)
        return await run_tool(ctx, "cull_report", handler)

    cull_report.__annotations__["filters"] = Optional[SearchFilters]
    register_tool(server, cull_report, "cull_report",
                  "One bounded summary of a scope before culling it: total, kept, rejected, favourites, rated, "
                  "unreviewed (not rejected, no rating, not a favourite), what the hide toggles would hide "
                  "(blinks, non-best burst members, duplicates, brackets, panoramas), junk, low scores "
                  f"(aggregate below `low_score_below`, default 4), the top {TOP_N_MAX} keepers at most and, with an "
                  f"edition token, the first {SETS_MAX} darkroom sets. `filters` is the search_photos filter object "
                  "(path_prefix, date_from/date_to, album_id ...); hide toggles in it are ignored. A line the "
                  "library cannot answer is null and listed under `unavailable`. Reasons overlap. A selection "
                  "cannot be reported: describe it with filters.", READ_ANNOTATIONS, WRITE_TOOL_LEVELS["cull_report"])
