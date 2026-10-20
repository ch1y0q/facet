"""Write tools: ratings, flags, albums, tags, junk, cull and delete.

Every tool reaches the library through ``InternalClient`` (the existing ``/api``
routes), so each route's own auth, validation and guards still apply. Three layers
sit on top:

* the tool's floor (:data:`WRITE_TOOL_LEVELS`, recorded in ``TOOL_LEVELS`` at registration),
  enforced in ``run_tool`` before any upstream call -- ``user`` mirrors what a regular account may do in the UI
  (per-photo rating / favourite / reject), ``edition`` is everything else;
* a view-scoped (``filters``) write must carry ``expected_count``, checked against
  ``/api/photos/count`` first -- a mismatch writes nothing;
* ``cull_apply`` (move / trash) and ``delete_photos`` run as a dry run first. The
  dry run returns a single-use ``confirm`` nonce bound to the RESOLVED file set
  (:mod:`api.agent.nonce`); the real run re-resolves the set through the route's
  own dry run and refuses ``confirmation_required`` when it is not the one the user
  was shown.
"""

from typing import Annotated, Any, Callable, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from pydantic import Field

from api.agent import nonce
from api.agent.bridge import TabRegistry
from api.agent.internal_client import InternalClient, err, ok
from api.agent.runtime import run_tool
from api.agent.requirements import destructive_allowed, scan_available
from api.agent.tools_common import (
    ARG_REQUIRES, DESTRUCTIVE_ANNOTATIONS, READ_ANNOTATIONS, WRITE_ANNOTATIONS, Requirement, register_tool,
)
from api.agent.target import SELECTION_RULE, resolve_selection
from api.agent.tools_read import SearchFilters, _hide_defaults, _list_result
from api.agent.ui_tools import TAB_ID_PATTERN
from api.models.gallery import query_value

PER_PHOTO_CAP = 50
BATCH_CAP = 1000
CULL_PATHS_CAP = 10000
TAGS_CAP = 10
FACES_CAP = 50
SCAN_DIRECTORIES_CAP = 20
SCAN_LINES_CAP = 50
CAPTION_MAX = 2000
EXPORT_CAP = 100
EXPORT_SIDECARS_SHOWN = 20
# A sidecar export runs two exiftool processes per photo; call_timeout_s would abort a legitimate batch.
EXPORT_METADATA_TIMEOUT_S = 180
# The levels each write tool needs; the matrix test walks this table.
WRITE_TOOL_LEVELS: dict[str, str] = {
    "set_rating": "user", "set_favorite": "user", "set_rejected": "user",
    "batch_set_rating": "edition", "batch_set_favorite": "edition", "batch_set_rejected": "edition",
    "create_album": "edition", "album_add_photos": "edition", "album_remove_photos": "edition",
    "add_tags": "edition", "remove_tags": "edition",
    "junk_list": "readonly", "junk_reject": "edition", "junk_clear": "edition",
    "cull_apply": "edition", "delete_photos": "edition",
    "assign_faces": "edition", "set_caption": "edition", "export_metadata": "edition",
    "start_scan": "edition", "scan_status": "edition", "comparison_status": "edition",
    # Registered by tools_corrections / tools_report; listed here so one table holds every non-darkroom level.
    "override_sequence": "edition", "clear_sequence_override": "edition",
    "override_category": "edition", "clear_category_override": "edition",
    "group_compare": "readonly", "cull_report": "readonly",
}
NONCE_ACTIONS = ("move_rejects", "trash_rejects")
LIST_KEYS = ("would_copy", "would_move", "would_trash")

Paths = Annotated[list[str], Field(min_length=1)]
Target = Optional[Literal["selection"]]
TabId = Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)]
NO_PATHS_ERROR = "Name at least one path"


def _too_large(count: int, cap: int) -> dict:
    return err("too_large", f"{count} paths exceeds the cap of {cap} for this tool; split the call")


def _scope_filters(filters: Any) -> dict:
    """The filters as the routes read them, with the viewer's hide defaults applied exactly as
    ``search_photos`` applies them, so its ``total`` is the ``expected_count`` and the set written."""
    merged = _hide_defaults(filters.model_dump(exclude_none=True))
    return {key: query_value(value) for key, value in merged.items()}


async def resolve_scope(
    client: InternalClient, grant: Any, settings: dict, *, paths: Optional[list[str]],
    filters: Any, exclude: Optional[list[str]], expected_count: Optional[int], path_cap: int,
    paths_key: str = "photo_paths",
) -> tuple[Optional[dict], dict]:
    """``(error, body)``: the route body naming the target set, or the refusal.

    Exactly one of ``paths`` / ``filters``. A ``filters`` set must come with
    ``expected_count``, compared with ``/api/photos/count`` (the count BEFORE
    ``exclude``) so a view that changed since the agent looked is never written.
    """
    if (paths is None) == (filters is None):
        return err("invalid_input", "Give exactly one of `paths` or `filters`"), {}
    body: dict[str, Any] = {}
    if exclude:
        body["exclude"] = exclude
    if paths is not None:
        if not paths:
            return err("invalid_input", NO_PATHS_ERROR), {}
        if len(paths) > path_cap:
            return _too_large(len(paths), path_cap), {}
        body[paths_key] = paths
        return None, body
    scope = _scope_filters(filters)
    if expected_count is None:
        return err("invalid_input", "A filter-scoped write requires `expected_count`: "
                   "the number of photos the filters match (see search_photos `total`)"), {}
    counted = await client.call(grant, "photos_count", query=scope, timeout=settings["call_timeout_s"])
    if not counted["ok"]:
        return counted, {}
    actual = (counted["data"] or {}).get("total")
    if actual != expected_count:
        return err("invalid_input", f"expected_count {expected_count} does not match the {actual} "
                   "photos these filters match now; nothing was written. Re-check and retry",
                   actual_count=actual), {}
    body["filters"] = scope
    return None, body


async def resolve_target(
    client: InternalClient, registry: TabRegistry, grant: Any, resolved: Any, settings: dict, *,
    paths: Optional[list[str]], filters: Any, target: Target, tab_id: Optional[str],
    exclude: Optional[list[str]] = None, expected_count: Optional[int] = None, path_cap: int,
    paths_key: str = "photo_paths", need_paths: bool = False,
) -> tuple[Optional[dict], dict, Optional[dict]]:
    """``(error, body, target_meta)``: ``resolve_scope`` extended with the tab's selection.

    Exactly one of ``paths`` / ``filters`` / ``target``. ``need_paths`` is for routes that take
    only a path list (a view selection is then expanded to its paths).
    """
    given = sum(value is not None for value in (paths, filters, target))
    if given != 1:
        return err("invalid_input", "Give exactly one of `paths`, `filters` or `target`"), {}, None
    if target is None:
        if need_paths and filters is not None:
            return err("invalid_input", "This tool takes `paths` or `target`, not `filters`"), {}, None
        refusal, body = await resolve_scope(
            client, grant, settings, paths=paths, filters=filters, exclude=exclude,
            expected_count=expected_count, path_cap=path_cap, paths_key=paths_key)
        return refusal, body, None
    if exclude or expected_count is not None:
        return err("invalid_input", "`exclude` and `expected_count` do not apply to `target`: the tab's "
                   "selection already carries its own exclusions and count"), {}, None
    return await resolve_selection(client, grant, registry, resolved, settings, tab_id=tab_id,
                                   path_cap=path_cap, paths_key=paths_key, need_paths=need_paths)


def _with_target(result: dict, meta: Optional[dict]) -> dict:
    if meta is not None and result.get("ok") and isinstance(result.get("data"), dict):
        result["data"]["target"] = meta
    return result


def _stopped(failure: dict, changed: int, results: list, remaining: int, in_doubt: Optional[str]) -> dict:
    extra: dict[str, Any] = {"affected": changed, "results": results, "not_attempted": remaining}
    if in_doubt is not None and failure["error"] == "outcome_unknown":
        extra["in_doubt"] = in_doubt
    return err(failure["error"], failure["message"], **extra)


async def set_each(client: InternalClient, grant: Any, settings: dict, paths: list[str],
                   is_current: Callable[[dict], bool], write: Callable[[str], Any],
                   ) -> dict:
    """SET semantics over the per-photo routes: read the state, write only on a difference.

    Sequential, and a ``library_busy`` / ``outcome_unknown`` / ``forbidden_level`` stops
    the loop at once, reporting what was done, so it is never hammered on.
    """
    if not paths:
        return err("invalid_input", NO_PATHS_ERROR)
    if len(paths) > PER_PHOTO_CAP:
        return _too_large(len(paths), PER_PHOTO_CAP)
    timeout = settings["call_timeout_s"]
    results: list[dict] = []
    skipped: list[dict] = []
    changed = 0
    for index, path in enumerate(paths):
        got = await client.call(grant, "get_photo", query={"path": path}, timeout=timeout)
        outcome = got
        if got["ok"]:
            if is_current(got["data"] or {}):
                results.append({"path": path, "outcome": "already"})
                continue
            outcome = await write(path)
        if outcome["ok"]:
            changed += 1
            results.append({"path": path, "outcome": "changed"})
        elif outcome["error"] in ("not_found", "invalid_input"):
            skipped.append({"path": path, "reason": outcome["error"]})
            results.append({"path": path, "outcome": "error", "reason": outcome["error"]})
        else:
            return _stopped(outcome, changed, results, len(paths) - index - (outcome["error"] == "outcome_unknown"),
                            path)
    return ok({"affected": changed, "already": sum(1 for r in results if r["outcome"] == "already"),
               "skipped": skipped, "results": results})


SKIPPED_REASON = ("these library paths have no readable file on disk (missing, moved, or outside "
                  "the scan directories); nothing was done for them")


def _cap_lists(data: dict, limit: int) -> dict:
    """Long lists become their first ``limit`` entries plus a ``<key>_count``.

    A non-empty ``skipped`` list gets a ``skipped_reason``: the routes report bare paths.
    """
    shaped = dict(data)
    if data.get("skipped"):
        shaped["skipped_reason"] = SKIPPED_REASON
    for key, value in data.items():
        if isinstance(value, list) and len(value) > limit:
            shaped[key] = value[:limit]
            shaped[key + "_count"] = len(value)
            shaped["truncated"] = True
        elif isinstance(value, list):
            shaped[key + "_count"] = len(value)
    return shaped


def _confirmation_required(message: str) -> dict:
    return err("confirmation_required", message)


def _confirmed(grant: Any, action: str, confirm: Optional[str], files: list[str], options: dict) -> bool:
    return nonce.check(grant.nonce_owner, action, nonce.digest(files, options), confirm)


def _with_confirm(shaped: dict, grant: Any, action: str, files: list[str], options: dict) -> dict:
    """Bind a single-use ``confirm`` nonce to the resolved file set of a dry run."""
    shaped["confirm"] = nonce.issue(grant.nonce_owner, action, nonce.digest(files, options))
    shaped["confirm_expires_in_s"] = int(nonce.TTL_SECONDS)
    return shaped


def register_write_tools(server: MCPServer, client: InternalClient, registry: TabRegistry) -> None:
    """Register the write tools on ``server``."""

    def add(fn: Callable, name: str, description: str, *, destructive: bool = False,
            read_only: bool = False, filtered: bool = False, requires: Optional[Requirement] = None) -> None:
        if filtered:
            fn.__annotations__["filters"] = Optional[SearchFilters]
        if "target" in fn.__annotations__:
            fn.__annotations__["tab_id"] = TabId
        annotations = READ_ANNOTATIONS if read_only else (
            DESTRUCTIVE_ANNOTATIONS if destructive else WRITE_ANNOTATIONS)
        register_tool(server, fn, name, description, annotations, WRITE_TOOL_LEVELS[name], requires)

    # ---- per-photo tools (level `user`) -------------------------------------------------

    async def per_photo_rating(ctx: Context, name: str, paths: list[str],
                               is_current: Callable[[dict], bool], route: str, body: Callable[[str], dict]) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await set_each(
                client, grant, settings, paths, is_current,
                lambda path: client.call(grant, route, json=body(path), timeout=settings["call_timeout_s"]))
        return await run_tool(ctx, name, handler, write=True)

    async def set_rating(
        ctx: Context, paths: Paths, rating: Annotated[int, Field(ge=0, le=5)],
    ) -> CallToolResult:
        return await per_photo_rating(
            ctx, "set_rating", paths,
            lambda photo: int(photo.get("star_rating") or 0) == rating,
            "set_rating", lambda path: {"photo_path": path, "rating": rating})

    async def set_favorite(ctx: Context, paths: Paths, value: bool) -> CallToolResult:
        return await per_photo_rating(
            ctx, "set_favorite", paths,
            lambda photo: bool(photo.get("is_favorite")) == value,
            "toggle_favorite", lambda path: {"photo_path": path})

    async def set_rejected(ctx: Context, paths: Paths, value: bool) -> CallToolResult:
        return await per_photo_rating(
            ctx, "set_rejected", paths,
            lambda photo: bool(photo.get("is_rejected")) == value,
            "toggle_rejected", lambda path: {"photo_path": path})

    per_photo = (f"At most {PER_PHOTO_CAP} paths per call. SET semantics: the current state is read first "
                 "and only a difference is written, so repeating a call is harmless; each path reports "
                 "`changed` or `already`.")
    add(set_rating, "set_rating", "Set the star rating (0-5) of photos for the token's owner. " + per_photo)
    add(set_favorite, "set_favorite", "Mark or unmark photos as favourite (marking clears rejected). " + per_photo)
    add(set_rejected, "set_rejected",
        "Reject or un-reject photos (rejecting clears the rating and favourite). " + per_photo)

    # ---- batch tools (edition) ---------------------------------------------------------

    async def batch(ctx: Context, name: str, route: str, paths, filters, exclude, expected_count,
                    extra: dict, target: Target, tab_id: Optional[str]) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body, meta = await resolve_target(
                client, registry, grant, resolved, settings, paths=paths, filters=filters, target=target,
                tab_id=tab_id, exclude=exclude, expected_count=expected_count, path_cap=BATCH_CAP)
            if refusal is not None:
                return refusal
            upstream = await client.call(grant, route, json={**body, **extra}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            count = (upstream["data"] or {}).get("count", 0)
            listed = body.get("photo_paths")
            requested = len(listed) if listed is not None else (meta["count"] if meta else expected_count)
            excluded = len(set(exclude or ()) & set(listed or ()))
            return _with_target(ok({"affected": count, "requested": requested,
                                    "skipped_count": max(0, (requested or 0) - count - excluded)
                                    if listed is not None else 0}), meta)
        return await run_tool(ctx, name, handler, write=True)

    batch_scope = ("Target EITHER `paths` (<=1000) OR `filters` (the search_photos filter object; "
                   "then `expected_count` is REQUIRED and must equal the filters' match count, otherwise "
                   "nothing is written). `exclude` removes paths from either target. "
                   + SELECTION_RULE + " The change SETs the state, so repeating it is harmless.")

    async def batch_set_rating(
        ctx: Context, rating: Annotated[int, Field(ge=0, le=5)],
        paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
        target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        return await batch(ctx, "batch_set_rating", "batch_rating", paths, filters, exclude,
                           expected_count, {"rating": rating}, target, tab_id)

    async def batch_set_favorite(
        ctx: Context, paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
        target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        return await batch(ctx, "batch_set_favorite", "batch_favorite", paths, filters, exclude,
                           expected_count, {}, target, tab_id)

    async def batch_set_rejected(
        ctx: Context, paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
        target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        return await batch(ctx, "batch_set_rejected", "batch_reject", paths, filters, exclude,
                           expected_count, {}, target, tab_id)

    add(batch_set_rating, "batch_set_rating", "Set the star rating of many photos. " + batch_scope,
        filtered=True)
    add(batch_set_favorite, "batch_set_favorite",
        "Mark many photos as favourite (clears rejected). " + batch_scope, filtered=True)
    add(batch_set_rejected, "batch_set_rejected",
        "Reject many photos (clears rating and favourite). Rejecting is what cull_apply later acts on. "
        + batch_scope, filtered=True)

    # ---- albums ------------------------------------------------------------------------

    async def create_album(
        ctx: Context, name: Annotated[str, Field(min_length=1, max_length=200)],
        description: Annotated[str, Field(max_length=2000)] = "",
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await client.call(grant, "create_album", json={"name": name, "description": description},
                                     timeout=settings["call_timeout_s"])
        return await run_tool(ctx, "create_album", handler, write=True)

    async def album_paths(name: str, route: str, ctx: Context, album_id: int, paths: Optional[list[str]],
                          target: Target, tab_id: Optional[str]) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body, meta = await resolve_target(
                client, registry, grant, resolved, settings, paths=paths, filters=None, target=target,
                tab_id=tab_id, path_cap=BATCH_CAP, need_paths=True)
            if refusal is not None:
                return refusal
            return _with_target(await client.call(grant, route, path_args={"album_id": album_id}, json=body,
                                                  timeout=settings["call_timeout_s"]), meta)
        return await run_tool(ctx, name, handler, write=True)

    async def album_add_photos(ctx: Context, album_id: Annotated[int, Field(ge=1)],
                               paths: Optional[Paths] = None, target: Target = None,
                               tab_id: Optional[str] = None) -> CallToolResult:
        return await album_paths("album_add_photos", "album_add_photos", ctx, album_id, paths, target, tab_id)

    async def album_remove_photos(ctx: Context, album_id: Annotated[int, Field(ge=1)],
                                  paths: Optional[Paths] = None, target: Target = None,
                                  tab_id: Optional[str] = None) -> CallToolResult:
        return await album_paths("album_remove_photos", "album_remove_photos", ctx, album_id, paths, target,
                                 tab_id)

    add(create_album, "create_album", "Create an empty album. Not idempotent: calling twice makes two albums.")
    add(album_add_photos, "album_add_photos",
        f"Add photos to an album (<={BATCH_CAP}): `paths` OR `target: \"selection\"` (the tab's selection, "
        "optional `tab_id`). Already-present photos are ignored.")
    add(album_remove_photos, "album_remove_photos",
        f"Remove photos from an album (<={BATCH_CAP}): `paths` OR `target: \"selection\"`. The photos "
        "themselves are untouched.")
    # ---- faces -------------------------------------------------------------------------

    async def assign_faces(
        ctx: Context, person_id: Annotated[int, Field(ge=1)],
        face_ids: Annotated[list[int], Field(min_length=1)],
        allow_reassign: bool = False,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(face_ids) > FACES_CAP:
                return _too_large(len(face_ids), FACES_CAP)
            upstream = await client.call(
                grant, "assign_faces", path_args={"person_id": person_id},
                json={"face_ids": face_ids, "tolerant": True, "only_unassigned": not allow_reassign},
                timeout=settings["call_timeout_s"])
            if upstream["ok"] and isinstance(upstream["data"], dict):
                upstream["data"].pop("success", None)
            return upstream
        return await run_tool(ctx, "assign_faces", handler, write=True, args={"allow_reassign": allow_reassign})

    add(assign_faces, "assign_faces",
        f"Assign faces (<={FACES_CAP} ids, e.g. from `possible_faces`) to a recognised person; ask the user "
        "before calling it. By default faces another person already owns are left alone "
        "(`skipped_assigned`); `allow_reassign: true` moves them, which can empty and DELETE that person (it needs "
        "viewer.mcp.allow_destructive): confirm with the user first. Ids that do not exist are `missing`; faces already on the person, of "
        "another embedding model, or of a hidden person are skipped and listed. `assigned_count` is what "
        "really moved. A face clustering run recomputing people can still overwrite an edit made earlier "
        "in that run.")

    # ---- caption and metadata ----------------------------------------------------------

    async def set_caption(
        ctx: Context, path: Annotated[str, Field(min_length=1, max_length=4096)],
        caption: Annotated[str, Field(max_length=CAPTION_MAX)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            got = await client.call(grant, "get_photo", query={"path": path}, timeout=timeout)
            if not got["ok"]:
                return got
            if ((got["data"] or {}).get("caption") or "") == caption:
                return ok({"path": path, "caption": caption or None, "already": True})
            written = await client.call(grant, "set_caption", json={"path": path, "caption": caption},
                                        timeout=timeout)
            if not written["ok"]:
                return written
            return ok({"path": path, "caption": caption or None, "already": False})
        return await run_tool(ctx, "set_caption", handler, write=True)

    add(set_caption, "set_caption",
        f"Set one photo's caption (<={CAPTION_MAX} characters); an empty string clears it. Setting the text it "
        "already has answers `already: true`. The translated caption is cleared. Two limits: the "
        "caption is NOT re-embedded, so semantic caption search keeps matching the old text until a "
        "re-embed; and the incremental viewer-database export keeps an existing caption when the source "
        "one is empty, so a cleared caption may come back with a later export or scan.")

    async def export_metadata(
        ctx: Context, paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
        target: Target = None, overwrite: bool = False, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body, meta = await resolve_target(
                client, registry, grant, resolved, settings, paths=paths, filters=filters, target=target,
                tab_id=tab_id, exclude=exclude, expected_count=expected_count, path_cap=EXPORT_CAP,
                paths_key="paths")
            if refusal is not None:
                return refusal
            chosen = expected_count if filters is not None else (meta or {}).get("count")
            if isinstance(chosen, int) and chosen > EXPORT_CAP:
                return _too_large(chosen, EXPORT_CAP)
            upstream = await client.call(grant, "export_metadata", json={**body, "overwrite": overwrite},
                                         timeout=EXPORT_METADATA_TIMEOUT_S)
            if not upstream["ok"]:
                return upstream
            data = upstream["data"] or {}
            sidecars = data.get("sidecars") or []
            shaped = {"written": data.get("written", 0), "skipped": data.get("skipped", 0),
                      "errors": data.get("errors", 0), "sidecars": sidecars[:EXPORT_SIDECARS_SHOWN],
                      "sidecars_count": len(sidecars)}
            if data.get("first_error"):
                shaped["first_error"] = data["first_error"]
            if shaped["skipped"]:
                shaped["skipped_reason"] = SKIPPED_REASON
            return _with_target(ok(shaped), meta)
        return await run_tool(ctx, "export_metadata", handler, write=True)

    add(export_metadata, "export_metadata",
        f"Write XMP sidecar files (rating, flags, tags, caption, faces) next to <={EXPORT_CAP} photos: "
        "`paths`, `filters` with `expected_count`, or `target: \"selection\"`. The original image files are "
        "never touched; existing sidecars are kept unless `overwrite`. The call can take minutes (the "
        f"server waits up to {EXPORT_METADATA_TIMEOUT_S} s, so raise your client timeout). `skipped` counts photos with "
        "no readable file on disk; `errors` counts failed writes with the first message in `first_error` "
        "(an exiftool 13.23 to 13.27 install refuses to write).", filtered=True)

    # ---- manual tags -------------------------------------------------------------------

    async def tag_batch(ctx: Context, name: str, action: str, tags, paths, filters, exclude,
                        expected_count, target: Target, tab_id: Optional[str]) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(tags) > TAGS_CAP:
                return _too_large(len(tags), TAGS_CAP)
            refusal, body, meta = await resolve_target(
                client, registry, grant, resolved, settings, paths=paths, filters=filters, target=target,
                tab_id=tab_id, exclude=exclude, expected_count=expected_count, path_cap=BATCH_CAP)
            if refusal is not None:
                return refusal
            timeout = settings["call_timeout_s"]
            affected = 0
            for tag in tags:
                upstream = await client.call(grant, "batch_manual_tags", json={**body, "tag": tag, "action": action},
                                             timeout=timeout)
                if not upstream["ok"]:
                    return err(upstream["error"], upstream["message"], affected=affected)
                affected += (upstream["data"] or {}).get("count", 0)
            return _with_target(ok({"affected": affected}), meta)
        return await run_tool(ctx, name, handler, write=True)

    async def add_tags(
        ctx: Context, tags: Annotated[list[str], Field(min_length=1)], paths: Optional[list[str]] = None,
        filters: Optional[Any] = None, exclude: Optional[list[str]] = None,
        expected_count: Optional[int] = None, target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        return await tag_batch(ctx, "add_tags", "add", tags, paths, filters, exclude, expected_count,
                               target, tab_id)

    async def remove_tags(
        ctx: Context, tags: Annotated[list[str], Field(min_length=1)], paths: Optional[list[str]] = None,
        filters: Optional[Any] = None, exclude: Optional[list[str]] = None,
        expected_count: Optional[int] = None, target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        return await tag_batch(ctx, "remove_tags", "delete", tags, paths, filters, exclude, expected_count,
                               target, tab_id)

    tag_note = (f"Manual tags (<={TAGS_CAP} per call), kept apart from the AI tags. " + batch_scope)
    add(add_tags, "add_tags", "Add manual tags to photos. " + tag_note, filtered=True)
    add(remove_tags, "remove_tags", "Remove manual tags from photos. " + tag_note, filtered=True)

    # ---- junk sweep --------------------------------------------------------------------

    async def junk_list(
        ctx: Context, kind: Optional[str] = None, page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "search_photos", query={
                "junk_kind": kind or "any", "page": page, "per_page": per_page, "hide_rejected": 1,
                "hide_blinks": 0, "hide_bursts": 0, "hide_duplicates": 0},
                timeout=settings["call_timeout_s"])
            return _list_result(upstream, ("junk_kind",))
        return await run_tool(ctx, "junk_list", handler)

    async def junk_reject(ctx: Context, paths: Paths) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body = await resolve_scope(
                client, grant, settings, paths=paths, filters=None, exclude=None,
                expected_count=None, path_cap=BATCH_CAP)
            if refusal is not None:
                return refusal
            upstream = await client.call(grant, "batch_reject", json=body, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            return ok({"affected": (upstream["data"] or {}).get("count", 0), "requested": len(paths)})
        return await run_tool(ctx, "junk_reject", handler, write=True)

    async def junk_clear(ctx: Context, paths: Paths) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(paths) > PER_PHOTO_CAP:
                return _too_large(len(paths), PER_PHOTO_CAP)
            cleared = 0
            for index, path in enumerate(paths):
                upstream = await client.call(grant, "clear_junk", json={"photo_path": path},
                                             timeout=settings["call_timeout_s"])
                if upstream["ok"]:
                    cleared += 1
                elif upstream["error"] != "not_found":
                    return _stopped(upstream, cleared, [], len(paths) - index, path)
            return ok({"affected": cleared, "requested": len(paths)})
        return await run_tool(ctx, "junk_clear", handler, write=True)

    add(junk_list, "junk_list", "List junk-sweep candidates (blurry, accidental ... frames). `kind` from "
        "filter_options(kind='junk_kinds'); omit for all kinds. Review them before junk_reject.", read_only=True)
    add(junk_reject, "junk_reject", f"Reject junk-sweep candidates (<={BATCH_CAP} paths); same as batch_set_rejected.")
    add(junk_clear, "junk_clear",
        f"Keep junk-sweep candidates: mark them evaluated-clean so they leave the queue (<={PER_PHOTO_CAP} paths).")

    # ---- scan and the read-only comparison counters ----------------

    async def start_scan(
        ctx: Context, directories: Annotated[list[str], Field(min_length=1, max_length=SCAN_DIRECTORIES_CAP)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            listed = await client.call(grant, "scan_directories", timeout=timeout)
            if not listed["ok"]:
                return listed
            configured = [d.get("path") for d in (listed["data"] or {}).get("directories") or []]
            unknown = [d for d in directories if d not in configured]
            if unknown:
                return err("invalid_input", "Only configured scan directories can be scanned; not configured: "
                           + ", ".join(unknown), configured_directories=configured)
            upstream = await client.call(grant, "scan_start", json={"directories": directories}, timeout=timeout)
            if not upstream["ok"]:
                return upstream
            return ok(upstream["data"])
        return await run_tool(ctx, "start_scan", handler, write=True)

    async def scan_status(
        ctx: Context, lines: Annotated[int, Field(ge=0, le=SCAN_LINES_CAP)] = 10,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            status = await client.call(grant, "scan_status", query={"lines": max(lines, 1)}, timeout=timeout)
            if not status["ok"]:
                return status
            listed = await client.call(grant, "scan_directories", timeout=timeout)
            body = status["data"] or {}
            output = body.get("output") or []
            return ok({"running": body.get("running"), "directories": body.get("directories"),
                       "exit_code": body.get("exit_code"), "elapsed_seconds": body.get("elapsed_seconds"),
                       "progress": body.get("progress"), "output": output[-lines:] if lines else [],
                       "configured_directories": [d.get("path") for d in (listed["data"] or {}).get("directories") or []]
                       if listed["ok"] else None})
        return await run_tool(ctx, "scan_status", handler)

    add(start_scan, "start_scan",
        f"Start a photo scan of configured directories (<={SCAN_DIRECTORIES_CAP}; see scan_status "
        "`configured_directories`). State the directories to the user first: a scan can run for hours and uses the "
        "GPU. It is additive and is refused while another scan or library job runs (`conflict`). "
        "It needs viewer.features.show_scan_button and a locked install (a superadmin key in multi-user mode). "
        "Syncing with Immich stays on the command line.", requires=scan_available)
    add(scan_status, "scan_status",
        f"The running or last scan: running, exit code, progress, the last `lines` (<={SCAN_LINES_CAP}) log lines "
        "(untrusted text) and the configured directories you may scan.", read_only=True, requires=scan_available)

    async def comparison_status(ctx: Context, category: Optional[str] = None) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            stats = await client.call(grant, "comparison_stats", timeout=timeout)
            if not stats["ok"]:
                return stats
            coverage = await client.call(grant, "comparison_coverage", query={"category": category}, timeout=timeout)
            return ok({"stats": stats["data"], "coverage": coverage["data"] if coverage["ok"] else None})
        return await run_tool(ctx, "comparison_status", handler)

    add(comparison_status, "comparison_status",
        "How many pairwise comparisons the user has made and how well they cover the library (optionally for one "
        "`category`). Read-only: the answer to a pair is the user's own click, so there is no tool that submits, "
        "edits, resets or deletes a comparison. Use ui_show_comparison to open the page, then read this to see the "
        "count grow. While a comparison is open, search with show=false so the page is not navigated away.",
        read_only=True)

    # ---- destructive: cull_apply, delete_photos ----------------------------------------

    async def cull_apply(
        ctx: Context, action: Literal["copy_keeps", "move_rejects", "trash_rejects"],
        target_dir: Optional[str] = None, paths: Optional[list[str]] = None,
        filters: Optional[Any] = None, exclude: Optional[list[str]] = None,
        expected_count: Optional[int] = None, include_companions: bool = False,
        include_sequence_siblings: bool = False, dry_run: bool = True, confirm: Optional[str] = None,
        target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body, meta = await resolve_target(
                client, registry, grant, resolved, settings, paths=paths, filters=filters, target=target,
                tab_id=tab_id, exclude=exclude, expected_count=expected_count, path_cap=CULL_PATHS_CAP,
                paths_key="paths")
            if refusal is not None:
                return refusal
            body.update(action=action, target_dir=target_dir, include_companions=include_companions,
                        include_sequence_siblings=include_sequence_siblings)
            options = {"action": action, "target_dir": target_dir, "include_companions": include_companions,
                       "include_sequence_siblings": include_sequence_siblings}
            guarded = action in NONCE_ACTIONS
            timeout = settings["call_timeout_s"]
            limit = settings["max_rows"]
            if dry_run or guarded:
                preview = await client.call(grant, "cull_apply.preview", json={**body, "dry_run": True},
                                            timeout=timeout)
                if not preview["ok"]:
                    return preview
                data = preview["data"] or {}
                files = next((data[key] for key in LIST_KEYS if isinstance(data.get(key), list)), [])
            if dry_run:
                shaped = _cap_lists(data, limit)
                return _with_target(ok(_with_confirm(shaped, grant, "cull_apply", files, options)
                                       if guarded and files else shaped), meta)
            if guarded and not _confirmed(grant, "cull_apply", confirm, files, options):
                return _confirmation_required(
                    "This destructive run needs the `confirm` value from a dry run of the SAME request "
                    "whose file list has not changed since. Dry-run again, show the user the result, and retry.")
            finished = await _finish(client, grant, "cull_apply", {**body, "dry_run": False}, timeout, limit)
            return _with_target(finished, meta)
        return await run_tool(ctx, "cull_apply", handler, write=True, args={"action": action})

    async def delete_photos(
        ctx: Context, paths: Optional[Paths] = None, include_companions: bool = False,
        include_sequence_siblings: bool = False, dry_run: bool = True, confirm: Optional[str] = None,
        target: Target = None, tab_id: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, scope_body, meta = await resolve_target(
                client, registry, grant, resolved, settings, paths=paths, filters=None, target=target,
                tab_id=tab_id, path_cap=BATCH_CAP, paths_key="paths", need_paths=True)
            if refusal is not None:
                return refusal
            body = {**scope_body, "include_companions": include_companions,
                    "include_sequence_siblings": include_sequence_siblings}
            options = {"include_companions": include_companions,
                       "include_sequence_siblings": include_sequence_siblings}
            timeout = settings["call_timeout_s"]
            preview = await client.call(grant, "delete_photos.preview", json={**body, "dry_run": True},
                                        timeout=timeout)
            if not preview["ok"]:
                return preview
            data = preview["data"] or {}
            files = list(data.get("would_trash") or []) + ["seq:" + p for p in data.get("sequence_siblings") or []]
            if dry_run:
                shaped = _cap_lists(data, settings["max_rows"])
                return _with_target(ok(_with_confirm(shaped, grant, "delete_photos", files, options)
                                       if files else shaped), meta)
            if not _confirmed(grant, "delete_photos", confirm, files, options):
                return _confirmation_required(
                    "delete_photos needs the `confirm` value from a dry run of the SAME request whose file "
                    "list has not changed since. Dry-run again, show the user the result, and retry.")
            finished = await _finish(client, grant, "delete_photos", {**body, "dry_run": False},
                                     timeout, settings["max_rows"])
            return _with_target(finished, meta)
        return await run_tool(ctx, "delete_photos", handler, write=True)

    destructive_note = (" ALWAYS call with dry_run=true first (the default) and show the user the counts and "
                        "file list; ask the user to confirm before any dry_run=false call, which also needs "
                        f"the single-use `confirm` value from that dry run (valid {int(nonce.TTL_SECONDS // 60)} "
                        "minutes, void if the affected files change).")
    add(cull_apply, "cull_apply",
        "Act on culling decisions: copy_keeps copies non-rejected photos into target_dir; move_rejects moves, "
        "and trash_rejects sends to the OS trash, ONLY photos the owner rejected (others are reported as "
        "excluded_by_state). target_dir must be inside an allowed export location. Companion RAW/xmp files "
        "and bracket/panorama siblings are untouched unless include_companions / include_sequence_siblings "
        "is set. Target EITHER `paths` OR `filters` (+ required `expected_count`); the viewer's default hide "
        "toggles apply as in search_photos, so rejected photos are hidden from `filters` unless you pass "
        "`show_rejected` (or `hide_rejected: false`) to BOTH search_photos (for `expected_count`) and this "
        "call: move_rejects and trash_rejects need that, copy_keeps does not. " + SELECTION_RULE
        + destructive_note + " move_rejects and trash_rejects need viewer.mcp.allow_destructive "
        "(copy_keeps does not).",
        destructive=True, filtered=True)
    ARG_REQUIRES["cull_apply"] = ("action", {"move_rejects": destructive_allowed, "trash_rejects": destructive_allowed})
    ARG_REQUIRES["assign_faces"] = ("allow_reassign", {True: destructive_allowed})
    add(delete_photos, "delete_photos",
        "Send photos to the OS trash and DELETE their library rows (the metadata is not recoverable). "
        "Companion files and sequence siblings only with include_companions / include_sequence_siblings. "
        "Name `paths` (<=1000) OR `target: \"selection\"` (the tab's selection, optional `tab_id`)."
        + destructive_note + " Needs viewer.mcp.allow_destructive (otherwise the tool is not offered).", destructive=True, requires=destructive_allowed)


async def _finish(client: InternalClient, grant: Any, tool: str, body: dict, timeout: float, limit: int) -> dict:
    upstream = await client.call(grant, tool, json=body, timeout=timeout)
    if not upstream["ok"]:
        return upstream
    return ok(_cap_lists(upstream["data"] or {}, limit))
