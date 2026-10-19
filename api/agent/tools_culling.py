"""Darkroom tools: culling groups, profiles, keeper hints, auto-cull and group confirm.

Every tool needs the ``edition`` level (the darkroom feeds, ``confirm`` and ``auto``
are edition-gated upstream) and reaches data through ``InternalClient`` over the
existing ``/api`` routes -- there is no second SQL path. A group's identity is the
PAIR ``(type, group_id)``: similar ids are offset when merged with bursts, and a
bracket / panorama / hdr_panorama set is always kept whole (the darkroom's rule).

The two writers are bounded server-side by a target-bound confirmation nonce:
``auto_cull`` apply needs the ``confirm`` value from a preview of the SAME resolved
plan, and ``confirm_culling_groups`` needs one whenever a group would reject every
frame it names.
"""

import re
from typing import Annotated, Any, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from api.agent import nonce
from api.agent.internal_client import InternalClient, RouteSpec, err, ok
from api.agent.limits import encoded_size
from api.agent.runtime import run_tool
from api.agent.tools_common import DESTRUCTIVE_ANNOTATIONS, READ_ANNOTATIONS, register_tool

CULLING_ROUTES: dict[str, RouteSpec] = {
    "culling.groups": RouteSpec("GET", "/api/culling-groups", "edition"),
    "culling.profiles": RouteSpec("GET", "/api/culling/profiles", "edition"),
    "culling.suggest_profile": RouteSpec("GET", "/api/culling/suggest_profile", "edition"),
    "culling.keeper_hints": RouteSpec("POST", "/api/photos/keeper_hints", "edition"),
    "culling.auto": RouteSpec("POST", "/api/culling/auto", "edition", write=True),
    "culling.confirm": RouteSpec("POST", "/api/culling-groups/confirm", "edition", write=True),
}

GroupType = Literal["burst", "similar", "scene", "bracket", "panorama", "hdr_panorama"]
KEEP_WHOLE_TYPES = ("bracket", "panorama", "hdr_panorama")
EXIF_TIMESTAMP = re.compile(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")
GROUP_PHOTO_LIMIT = 12
GROUP_PHOTO_KEYS = ("path", "filename", "date_taken", "aggregate", "aesthetic", "tech_sharpness",
                    "is_blink", "sequence_ev_offset", "keeper_prob")
SEE_GROUP = " Call ui_show_culling_group to show a group to the user."


class ConfirmGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: GroupType
    group_id: int
    paths: Annotated[list[str], Field(min_length=1, max_length=1000)]
    keep_paths: Annotated[list[str], Field(max_length=1000)]


def _compact_group(group: dict) -> dict:
    photos = group.get("photos") or []
    kind = group.get("sequence_kind")
    if kind is None:
        kind = next((p.get("sequence_kind") for p in photos if p.get("sequence_kind")), None)
    return {
        "type": group.get("type"),
        "group_id": group.get("group_id"),
        "sequence_kind": kind,
        "reason": group.get("reason"),
        "keeper_best_path": group.get("keeper_best_path"),
        "photo_count": len(photos),
        "photos": [{key: p.get(key) for key in GROUP_PHOTO_KEYS}
                   for p in photos[:GROUP_PHOTO_LIMIT]],
    }


def _fit_groups(rows: list[dict], budget: int) -> list[dict]:
    """Shed group members (never groups) until the page fits ``budget`` serialized bytes.

    A scene page is ~20 groups of up to ``GROUP_PHOTO_LIMIT`` photos; halving every group's
    member list keeps each group visible. ``photo_count`` stays the true size and
    ``photos_truncated`` marks a group whose list was cut.
    """
    shown = GROUP_PHOTO_LIMIT
    while shown > 1 and encoded_size({"rows": rows}) > budget:
        shown = max(1, shown // 2)
        for row in rows:
            if len(row["photos"]) > shown:
                row["photos"] = row["photos"][:shown]
    for row in rows:
        row["photos_truncated"] = len(row["photos"]) < row["photo_count"]
    return rows


def _plan_digest(options: dict, preview: list[dict]) -> str:
    """Digest of the options plus the RESOLVED keep/reject split of every group."""
    tagged = [f"{g.get('type')}:{g.get('group_id')}:{side}:{path}" for g in preview
              for side in ("keep", "reject") for path in g.get(f"{side}_paths", [])]
    return nonce.digest(tagged, options)


def _confirm_digest(groups: list[ConfirmGroup]) -> str:
    tagged = [f"{g.type}:{g.group_id}:{side}:{path}" for g in groups
              for side, paths in (("all", g.paths), ("keep", g.keep_paths)) for path in paths]
    return nonce.digest(tagged, "confirm_culling_groups")


def _check_timestamps(**stamps: Optional[str]) -> Optional[dict]:
    for name, value in stamps.items():
        if value is not None and not EXIF_TIMESTAMP.match(value):
            return err("invalid_input", f"{name} must look like 'YYYY:MM:DD HH:MM:SS'")
    return None


def _validate_confirm(groups: list[ConfirmGroup]) -> Optional[dict]:
    seen = set()
    for g in groups:
        if (g.type, g.group_id) in seen:
            return err("invalid_input", f"Group ({g.type}, {g.group_id}) is listed twice")
        seen.add((g.type, g.group_id))
        if not set(g.keep_paths) <= set(g.paths):
            return err("invalid_input",
                       f"keep_paths of ({g.type}, {g.group_id}) must be a subset of its paths")
        if g.type in KEEP_WHOLE_TYPES and set(g.keep_paths) != set(g.paths):
            return err("invalid_input",
                       f"A {g.type} set is kept whole: keep_paths must equal paths for "
                       f"({g.type}, {g.group_id})")
    return None


def register_culling_tools(server: MCPServer, app: Any) -> None:
    """Register the darkroom tools. ``app`` is the FastAPI app the routes live on."""
    client = InternalClient(app, CULLING_ROUTES)

    def add(fn, name: str, description: str, annotations: ToolAnnotations = READ_ANNOTATIONS) -> None:
        register_tool(server, fn, name, description, annotations)

    async def list_culling_groups(
        ctx: Context,
        group_by: Literal["all", "burst", "similar", "scene", "bracket", "panorama",
                          "hdr_panorama"] = "all",
        page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=50)] = 20,
        sort: Literal["easiest", "redundant", "best", "recent", "needs_comparisons",
                      "chronological"] = "easiest",
        direction: Literal["", "asc", "desc"] = "",
        exclude_rejected: bool = True,
        album_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            bad = _check_timestamps(date_from=date_from, date_to=date_to)
            if bad:
                return bad
            upstream = await client.call(
                grant, "culling.groups", timeout=settings["call_timeout_s"],
                query={"group_by": group_by, "page": page, "per_page": per_page, "sort": sort,
                       "direction": direction, "exclude_rejected": "1" if exclude_rejected else "0",
                       "album_id": album_id, "date_from": date_from, "date_to": date_to})
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            rows = _fit_groups([_compact_group(g) for g in body.get("groups", [])],
                               settings["max_bytes"] // 2)
            return ok({"rows": rows,
                       "total": body.get("total_groups", 0), "page": body.get("page", page),
                       "per_page": body.get("per_page", per_page),
                       "total_pages": body.get("total_pages", 0),
                       "has_more": body.get("page", page) < body.get("total_pages", 0)})
        return await run_tool(ctx, "list_culling_groups", handler)

    async def culling_profiles(ctx: Context) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await client.call(grant, "culling.profiles", timeout=settings["call_timeout_s"])
        return await run_tool(ctx, "culling_profiles", handler)

    async def suggest_culling_profile(
        ctx: Context, album_id: Optional[int] = None,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            bad = _check_timestamps(date_from=date_from, date_to=date_to)
            if bad:
                return bad
            return await client.call(
                grant, "culling.suggest_profile", timeout=settings["call_timeout_s"],
                query={"album_id": album_id, "date_from": date_from, "date_to": date_to})
        return await run_tool(ctx, "suggest_culling_profile", handler)

    async def keeper_hints(
        ctx: Context, paths: Annotated[list[str], Field(min_length=1, max_length=100)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "culling.keeper_hints", json={"paths": paths},
                                         timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            hints = upstream["data"] or {}
            return ok({"rows": [{"path": path, **hint} for path, hint in hints.items()],
                       "trained": bool(hints)})
        return await run_tool(ctx, "keeper_hints", handler)

    async def auto_cull(
        ctx: Context,
        group_by: Literal["all", "burst", "similar", "scene"] = "all",
        album_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        strictness: Annotated[Optional[int], Field(ge=0, le=100)] = None,
        min_keep_per_group: Annotated[Optional[int], Field(ge=1)] = None,
        profile: Optional[str] = None,
        trim_brackets: bool = False,
        highlights_album: Annotated[str, Field(max_length=200)] = "",
        dry_run: bool = True,
        confirm: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            bad = _check_timestamps(date_from=date_from, date_to=date_to)
            if bad:
                return bad
            options = {"group_by": group_by, "album_id": album_id, "date_from": date_from,
                       "date_to": date_to, "strictness": strictness,
                       "min_keep_per_group": min_keep_per_group, "profile": profile,
                       "trim_brackets": trim_brackets, "highlights_album": highlights_album}
            timeout = settings["call_timeout_s"]
            preview = await client.call(grant, "culling.auto", json={**options, "dry_run": True},
                                        timeout=timeout)
            if not preview["ok"] or dry_run:
                return _preview_result(grant, preview, options)
            body = preview["data"] or {}
            if body.get("preview_truncated"):
                return err("confirmation_required",
                           "The plan is too large to confirm as one set; narrow it with "
                           "album_id, date_from/date_to or group_by")
            if not nonce.check(grant.id, "auto_cull", _plan_digest(options, body.get("preview", [])), confirm):
                return err("confirmation_required",
                           "Preview with dry_run=true first and pass its `confirm` value; the "
                           "plan must be unchanged since that preview")
            return await client.call(grant, "culling.auto", json={**options, "dry_run": False},
                                     timeout=timeout)
        return await run_tool(ctx, "auto_cull", handler, write=not dry_run)

    def _preview_result(grant, upstream: dict, options: dict) -> dict:
        if not upstream["ok"]:
            return upstream
        body = upstream["data"] or {}
        groups = body.get("preview", [])
        data = {**body, "rows": [{"type": g["type"], "group_id": g["group_id"],
                                  "keep_paths": g["keep_paths"], "reject_paths": g["reject_paths"],
                                  "best_path": g["best_path"]} for g in groups]}
        data.pop("preview", None)
        if body.get("preview_truncated") or not body.get("rejected"):
            return ok(data, note="Nothing to apply" if not body.get("rejected")
                      else "Plan truncated: narrow the scope to get a confirmable preview")
        return ok(data, confirm=nonce.issue(grant.id, "auto_cull", _plan_digest(options, groups)))

    async def confirm_culling_groups(
        ctx: Context,
        groups: Annotated[list[ConfirmGroup], Field(min_length=1, max_length=20)],
        confirm: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            bad = _validate_confirm(groups)
            if bad:
                return bad
            if any(not g.keep_paths for g in groups):
                digest = _confirm_digest(groups)
                if not nonce.check(grant.id, "confirm_culling_groups", digest, confirm):
                    return err("confirmation_required",
                               "A group with empty keep_paths rejects every frame it names. Show "
                               "the user, then repeat this call with `confirm` set to this value.",
                               confirm=nonce.issue(grant.id, "confirm_culling_groups", digest))
            rows = []
            for g in groups:
                upstream = await client.call(
                    grant, "culling.confirm", json=g.model_dump(), timeout=settings["call_timeout_s"])
                head = {"type": g.type, "group_id": g.group_id}
                if upstream["ok"]:
                    body = upstream["data"] or {}
                    rows.append({**head, "ok": True, "kept": body.get("kept"),
                                 "rejected": body.get("rejected"), "skipped": body.get("skipped")})
                elif upstream["error"] in ("forbidden_level", "library_busy", "rate_limited"):
                    return upstream if not rows else ok({"rows": rows + [
                        {**head, "ok": False, "error": upstream["error"]}]})
                else:
                    rows.append({**head, "ok": False, "error": upstream["error"],
                                 "message": upstream["message"]})
            return ok({"rows": rows})
        return await run_tool(ctx, "confirm_culling_groups", handler, write=True)

    add(list_culling_groups, "list_culling_groups",
        "List the darkroom's culling groups (burst, similar, scene, bracket, panorama, "
        "hdr_panorama), each with its photos and scores. A group is identified by the PAIR "
        "(type, group_id); bracket/panorama/hdr_panorama sets are kept whole by design, never "
        "culled frame by frame." + SEE_GROUP)
    add(culling_profiles, "culling_profiles", "The genre-aware culling presets and the default one.")
    add(suggest_culling_profile, "suggest_culling_profile",
        "Name the preset that fits an album or capture-time window. date_from/date_to are "
        "'YYYY:MM:DD HH:MM:SS'.")
    add(keeper_hints, "keeper_hints",
        "Per-photo 'a better shot exists in this burst' hints for up to 100 paths. Empty when no "
        "keeper head is trained.")
    add(auto_cull, "auto_cull",
        "Auto-cull a scope under a keeper budget. dry_run=true (default) only previews the split "
        "and returns a `confirm` value; show the user the counts, then call again with "
        "dry_run=false and that `confirm` to reject the planned frames. The apply is refused when "
        "the plan changed since the preview. Brackets and panoramas are kept whole." + SEE_GROUP,
        DESTRUCTIVE_ANNOTATIONS)
    add(confirm_culling_groups, "confirm_culling_groups",
        "Confirm up to 20 groups, each keyed by (type, group_id) with the group's `paths` and the "
        "`keep_paths` to keep; the rest are rejected. bracket/panorama/hdr_panorama groups must "
        "keep every path. A group with empty keep_paths (reject all) first answers "
        "confirmation_required with a `confirm` value to repeat the call with." + SEE_GROUP,
        DESTRUCTIVE_ANNOTATIONS)
