"""Write tools: ratings, flags, albums, tags, junk, cull and delete.

Every tool reaches the library through ``InternalClient`` (the existing ``/api``
routes), so each route's own auth, validation and guards still apply. Three layers
sit on top:

* ``min_level`` (:data:`WRITE_TOOL_LEVELS`), enforced in ``run_tool`` before any
  upstream call -- ``user`` mirrors what a regular account may do in the UI
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
from api.agent.internal_client import InternalClient, err, ok
from api.agent.runtime import run_tool
from api.agent.tools_common import (
    DESTRUCTIVE_ANNOTATIONS, READ_ANNOTATIONS, WRITE_ANNOTATIONS, register_tool,
)
from api.agent.tools_read import SearchFilters, _hide_defaults, _list_result, _query_value

PER_PHOTO_CAP = 50
BATCH_CAP = 1000
CULL_PATHS_CAP = 10000
TAGS_CAP = 10
# The levels each write tool needs; the matrix test walks this table.
WRITE_TOOL_LEVELS: dict[str, str] = {
    "set_rating": "user", "set_favorite": "user", "set_rejected": "user",
    "batch_set_rating": "edition", "batch_set_favorite": "edition", "batch_set_rejected": "edition",
    "create_album": "edition", "album_add_photos": "edition", "album_remove_photos": "edition",
    "add_tags": "edition", "remove_tags": "edition",
    "junk_list": "readonly", "junk_reject": "edition", "junk_clear": "edition",
    "cull_apply": "edition", "delete_photos": "edition",
}
NONCE_ACTIONS = ("move_rejects", "trash_rejects")
LIST_KEYS = ("would_copy", "would_move", "would_trash")

Paths = Annotated[list[str], Field(min_length=1)]
NO_PATHS_ERROR = "Name at least one path"


def _too_large(count: int, cap: int) -> dict:
    return err("too_large", f"{count} paths exceeds the cap of {cap} for this tool; split the call")


def _scope_filters(filters: Any) -> dict:
    """The filters as the routes read them, with the viewer's hide defaults applied exactly as
    ``search_photos`` applies them, so its ``total`` is the ``expected_count`` and the set written."""
    merged = _hide_defaults(filters.model_dump(exclude_none=True))
    return {key: _query_value(value) for key, value in merged.items()}


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


def _stopped(failure: dict, changed: int, results: list, remaining: int, in_doubt: Optional[str]) -> dict:
    extra: dict[str, Any] = {"affected": changed, "results": results, "not_attempted": remaining}
    if in_doubt is not None and failure["error"] == "outcome_unknown":
        extra["in_doubt"] = in_doubt
    return err(failure["error"], failure["message"], **extra)


async def set_each(client: InternalClient, grant: Any, settings: dict, paths: list[str],
                   is_current: Callable[[dict], bool], write: Callable[[str], Any]) -> dict:
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
    return nonce.check(grant.id, action, nonce.digest(files, options), confirm)


def _with_confirm(shaped: dict, grant: Any, action: str, files: list[str], options: dict) -> dict:
    """Bind a single-use ``confirm`` nonce to the resolved file set of a dry run."""
    shaped["confirm"] = nonce.issue(grant.id, action, nonce.digest(files, options))
    shaped["confirm_expires_in_s"] = int(nonce.TTL_SECONDS)
    return shaped

def register_write_tools(server: MCPServer, client: InternalClient) -> None:
    """Register the write tools on ``server``."""

    def add(fn: Callable, name: str, description: str, *, destructive: bool = False,
            read_only: bool = False, filtered: bool = False) -> None:
        if filtered:
            fn.__annotations__["filters"] = Optional[SearchFilters]
        annotations = READ_ANNOTATIONS if read_only else (
            DESTRUCTIVE_ANNOTATIONS if destructive else WRITE_ANNOTATIONS)
        register_tool(server, fn, name, description, annotations)

    def level(name: str) -> str:
        return WRITE_TOOL_LEVELS[name]

    # ---- per-photo tools (level `user`) -------------------------------------------------

    async def set_rating(
        ctx: Context, paths: Paths, rating: Annotated[int, Field(ge=0, le=5)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await set_each(
                client, grant, settings, paths,
                lambda photo: int(photo.get("star_rating") or 0) == rating,
                lambda path: client.call(grant, "set_rating", json={"photo_path": path, "rating": rating},
                                         timeout=settings["call_timeout_s"]))
        return await run_tool(ctx, "set_rating", handler, write=True, min_level=level("set_rating"))

    async def set_favorite(ctx: Context, paths: Paths, value: bool) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await set_each(
                client, grant, settings, paths,
                lambda photo: bool(photo.get("is_favorite")) == value,
                lambda path: client.call(grant, "toggle_favorite", json={"photo_path": path},
                                         timeout=settings["call_timeout_s"]))
        return await run_tool(ctx, "set_favorite", handler, write=True, min_level=level("set_favorite"))

    async def set_rejected(ctx: Context, paths: Paths, value: bool) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await set_each(
                client, grant, settings, paths,
                lambda photo: bool(photo.get("is_rejected")) == value,
                lambda path: client.call(grant, "toggle_rejected", json={"photo_path": path},
                                         timeout=settings["call_timeout_s"]))
        return await run_tool(ctx, "set_rejected", handler, write=True, min_level=level("set_rejected"))

    per_photo = (f"At most {PER_PHOTO_CAP} paths per call. SET semantics: the current state is read first "
                 "and only a difference is written, so repeating a call is harmless; each path reports "
                 "`changed` or `already`.")
    add(set_rating, "set_rating", "Set the star rating (0-5) of photos for the token's owner. " + per_photo)
    add(set_favorite, "set_favorite", "Mark or unmark photos as favourite (marking clears rejected). " + per_photo)
    add(set_rejected, "set_rejected",
        "Reject or un-reject photos (rejecting clears the rating and favourite). " + per_photo)

    # ---- batch tools (edition) ---------------------------------------------------------

    async def batch(ctx: Context, name: str, route: str, paths, filters, exclude, expected_count,
                    extra: dict) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body = await resolve_scope(
                client, grant, settings, paths=paths, filters=filters, exclude=exclude,
                expected_count=expected_count, path_cap=BATCH_CAP)
            if refusal is not None:
                return refusal
            upstream = await client.call(grant, route, json={**body, **extra},
                                         timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            count = (upstream["data"] or {}).get("count", 0)
            requested = len(paths) if paths is not None else expected_count
            return ok({"affected": count, "requested": requested,
                       "skipped_count": max(0, (requested or 0) - count - len(exclude or ()))
                       if paths is not None else 0})
        return await run_tool(ctx, name, handler, write=True, min_level=level(name))

    batch_scope = ("Target EITHER `paths` (<=1000) OR `filters` (the search_photos filter object; "
                   "then `expected_count` is REQUIRED and must equal the filters' match count, otherwise "
                   "nothing is written). `exclude` removes paths from either target. "
                   "The change SETs the state, so repeating it is harmless.")

    async def batch_set_rating(
        ctx: Context, rating: Annotated[int, Field(ge=0, le=5)],
        paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
    ) -> CallToolResult:
        return await batch(ctx, "batch_set_rating", "batch_rating", paths, filters, exclude,
                           expected_count, {"rating": rating})

    async def batch_set_favorite(
        ctx: Context, paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
    ) -> CallToolResult:
        return await batch(ctx, "batch_set_favorite", "batch_favorite", paths, filters, exclude,
                           expected_count, {})

    async def batch_set_rejected(
        ctx: Context, paths: Optional[list[str]] = None, filters: Optional[Any] = None,
        exclude: Optional[list[str]] = None, expected_count: Optional[int] = None,
    ) -> CallToolResult:
        return await batch(ctx, "batch_set_rejected", "batch_reject", paths, filters, exclude,
                           expected_count, {})

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
        return await run_tool(ctx, "create_album", handler, write=True, min_level=level("create_album"))

    async def album_add_photos(ctx: Context, album_id: Annotated[int, Field(ge=1)],
                               paths: Paths) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(paths) > BATCH_CAP:
                return _too_large(len(paths), BATCH_CAP)
            return await client.call(grant, "album_add_photos", path_args={"album_id": album_id},
                                     json={"photo_paths": paths}, timeout=settings["call_timeout_s"])
        return await run_tool(ctx, "album_add_photos", handler, write=True,
                              min_level=level("album_add_photos"))

    async def album_remove_photos(ctx: Context, album_id: Annotated[int, Field(ge=1)],
                                  paths: Paths) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(paths) > BATCH_CAP:
                return _too_large(len(paths), BATCH_CAP)
            return await client.call(grant, "album_remove_photos", path_args={"album_id": album_id},
                                     json={"photo_paths": paths}, timeout=settings["call_timeout_s"])
        return await run_tool(ctx, "album_remove_photos", handler, write=True,
                              min_level=level("album_remove_photos"))

    add(create_album, "create_album", "Create an empty album. Not idempotent: calling twice makes two albums.")
    add(album_add_photos, "album_add_photos", f"Add photos to an album (<={BATCH_CAP} paths). Already-present photos are ignored.")
    add(album_remove_photos, "album_remove_photos",
        f"Remove photos from an album (<={BATCH_CAP} paths). The photos themselves are untouched.")

    # ---- manual tags -------------------------------------------------------------------

    async def tag_batch(ctx: Context, name: str, action: str, tags, paths, filters, exclude,
                        expected_count) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(tags) > TAGS_CAP:
                return _too_large(len(tags), TAGS_CAP)
            refusal, body = await resolve_scope(
                client, grant, settings, paths=paths, filters=filters, exclude=exclude,
                expected_count=expected_count, path_cap=BATCH_CAP)
            if refusal is not None:
                return refusal
            affected = 0
            for tag in tags:
                upstream = await client.call(grant, "batch_manual_tags", json={**body, "tag": tag, "action": action},
                                             timeout=settings["call_timeout_s"])
                if not upstream["ok"]:
                    return err(upstream["error"], upstream["message"], affected=affected)
                affected += (upstream["data"] or {}).get("count", 0)
            return ok({"affected": affected})
        return await run_tool(ctx, name, handler, write=True, min_level=level(name))

    async def add_tags(
        ctx: Context, tags: Annotated[list[str], Field(min_length=1)], paths: Optional[list[str]] = None,
        filters: Optional[Any] = None, exclude: Optional[list[str]] = None,
        expected_count: Optional[int] = None,
    ) -> CallToolResult:
        return await tag_batch(ctx, "add_tags", "add", tags, paths, filters, exclude, expected_count)

    async def remove_tags(
        ctx: Context, tags: Annotated[list[str], Field(min_length=1)], paths: Optional[list[str]] = None,
        filters: Optional[Any] = None, exclude: Optional[list[str]] = None,
        expected_count: Optional[int] = None,
    ) -> CallToolResult:
        return await tag_batch(ctx, "remove_tags", "delete", tags, paths, filters, exclude, expected_count)

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
        return await run_tool(ctx, "junk_list", handler, min_level=level("junk_list"))

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
        return await run_tool(ctx, "junk_reject", handler, write=True, min_level=level("junk_reject"))

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
        return await run_tool(ctx, "junk_clear", handler, write=True, min_level=level("junk_clear"))

    add(junk_list, "junk_list", "List junk-sweep candidates (blurry, accidental ... frames). `kind` from "
        "filter_options(kind='junk_kinds'); omit for all kinds. Review them before junk_reject.", read_only=True)
    add(junk_reject, "junk_reject", f"Reject junk-sweep candidates (<={BATCH_CAP} paths); same as batch_set_rejected.")
    add(junk_clear, "junk_clear",
        f"Keep junk-sweep candidates: mark them evaluated-clean so they leave the queue (<={PER_PHOTO_CAP} paths).")

    # ---- destructive: cull_apply, delete_photos ----------------------------------------

    async def cull_apply(
        ctx: Context, action: Literal["copy_keeps", "move_rejects", "trash_rejects"],
        target_dir: Optional[str] = None, paths: Optional[list[str]] = None,
        filters: Optional[Any] = None, exclude: Optional[list[str]] = None,
        expected_count: Optional[int] = None, include_companions: bool = False,
        include_sequence_siblings: bool = False, dry_run: bool = True, confirm: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            refusal, body = await resolve_scope(
                client, grant, settings, paths=paths, filters=filters, exclude=exclude,
                expected_count=expected_count, path_cap=CULL_PATHS_CAP, paths_key="paths")
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
                return ok(_with_confirm(shaped, grant, "cull_apply", files, options)
                          if guarded and files else shaped)
            if guarded and not _confirmed(grant, "cull_apply", confirm, files, options):
                return _confirmation_required(
                    "This destructive run needs the `confirm` value from a dry run of the SAME request "
                    "whose file list has not changed since. Dry-run again, show the user the result, and retry.")
            return await _finish(client, grant, "cull_apply", {**body, "dry_run": False}, timeout, limit)
        return await run_tool(ctx, "cull_apply", handler, write=True, min_level=level("cull_apply"))

    async def delete_photos(
        ctx: Context, paths: Paths, include_companions: bool = False,
        include_sequence_siblings: bool = False, dry_run: bool = True, confirm: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if len(paths) > BATCH_CAP:
                return _too_large(len(paths), BATCH_CAP)
            body = {"paths": paths, "include_companions": include_companions,
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
                return ok(_with_confirm(shaped, grant, "delete_photos", files, options) if files else shaped)
            if not _confirmed(grant, "delete_photos", confirm, files, options):
                return _confirmation_required(
                    "delete_photos needs the `confirm` value from a dry run of the SAME request whose file "
                    "list has not changed since. Dry-run again, show the user the result, and retry.")
            return await _finish(client, grant, "delete_photos", {**body, "dry_run": False}, timeout,
                                 settings["max_rows"])
        return await run_tool(ctx, "delete_photos", handler, write=True, min_level=level("delete_photos"))

    destructive_note = (" ALWAYS call with dry_run=true first (the default) and show the user the counts and "
                        "file list; ask the user to confirm before any dry_run=false call, which also needs "
                        "the single-use `confirm` value from that dry run (valid " + str(int(nonce.TTL_SECONDS // 60)) + " minutes, void if the "
                        "affected files change).")
    add(cull_apply, "cull_apply",
        "Act on culling decisions: copy_keeps copies non-rejected photos into target_dir; move_rejects moves, "
        "and trash_rejects sends to the OS trash, ONLY photos the owner rejected (others are reported as "
        "excluded_by_state). target_dir must be inside an allowed export location. Companion RAW/xmp files "
        "and bracket/panorama siblings are untouched unless include_companions / include_sequence_siblings "
        "is set. Target EITHER `paths` OR `filters` (+ required `expected_count`)." + destructive_note,
        destructive=True, filtered=True)
    add(delete_photos, "delete_photos",
        "Send photos to the OS trash and DELETE their library rows (the metadata is not recoverable). "
        "Companion files and sequence siblings only with include_companions / include_sequence_siblings."
        + destructive_note, destructive=True)


async def _finish(client: InternalClient, grant: Any, tool: str, body: dict, timeout: float, limit: int) -> dict:
    upstream = await client.call(grant, tool, json=body, timeout=timeout)
    if not upstream["ok"]:
        return upstream
    return ok(_cap_lists(upstream["data"] or {}, limit))
