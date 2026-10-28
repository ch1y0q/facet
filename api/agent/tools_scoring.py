"""Scoring tools: reads and previews (``explain_score``, ``category_weights``, ``preview_weights``, ``learned_weights``,
``misassigned_categories``, ``list_weight_snapshots``, ``recompute_status``) and the writes (``apply_weights``,
``restore_weight_snapshot``, ``recompute_scores``, ``override_categories``).

The only code in ``api/agent`` that changes ``scoring_config.json`` is a call to the viewer's own
``update_weights`` / ``restore_weights`` routes, which own ``CONFIG_WRITE_LOCK``, the automatic weight snapshot and
``write_user_config``. Both writes are two-step: a preview (or dry run) issues a single-use digest bound to the weights
it saw, and the write refuses ``confirmation_required`` unless it is presented with the digest of the SAME proposal over
the SAME current weights. ``explain_score`` calls ``GET /api/critique`` in its rule mode (never the VLM mode, which
needs a GPU and caches its text into ``photos``); ``category_weights`` reads ``GET /api/comparison/category_weights``;
``preview_weights`` scores a sample of the category's photos twice through ``POST /api/comparison/preview_score``,
once with the current weights and once with the proposal, both normalised exactly like ``ScoringConfig.get_weights``
(:func:`api.agent.weights.route_vectors`), and issues a single-use digest bound to the current weights plus the
proposal. The digest is what a later apply step must present; it is not consent.
"""

import asyncio
import statistics
from typing import Annotated, Any, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from pydantic import Field

from api.agent import nonce
from api.agent import weights as wm
from api.agent.bridge import TabRegistry
from api.agent.internal_client import InternalClient, err, ok
from api.agent.requirements import critique_available
from api.agent.runtime import run_tool
from api.agent import photo_io
from api.agent.target import resolve_selected_paths
from api.agent.tools_common import READ_ANNOTATIONS, WRITE_ANNOTATIONS, register_tool
from api.agent.tools_write import PER_PHOTO_CAP, WRITE_TOOL_LEVELS, Paths, TabId, Target, _too_large
from api.config import server_scoring_config
from config.category_filter import VALID_WEIGHT_COLUMNS
from optimization.learning_policy import external_learning_result

TOP_N_MAX = 12
REJECTED_SHOWN = 3
SAMPLE_DEFAULT = 30
SAMPLE_MAX = 100
SAMPLE_PAGE = 100
PREVIEW_CONCURRENCY = 4
SKIP_LIMIT = 0.2
SNAPSHOT_LIST_DEFAULT = 10
SNAPSHOT_PAGE_SIZE = 100
SNAPSHOT_PAGES = 5
# The newest snapshots read to find the one a write just made (by id, never by timestamp).
SNAPSHOT_LATEST = 10
# How many of the newest ids a not_found answer offers.
NEAREST_IDS = 5
# The optimizer runs synchronously and read-only, so it gets longer than call_timeout_s (cf. EXPORT_METADATA_TIMEOUT_S).
LEARNED_TIMEOUT_S = 120
CONFIDENCE_BOOTSTRAP = 50
MISASSIGNED_LIMIT_DEFAULT = 20
MISASSIGNED_LIMIT_MAX = 100
MISASSIGNED_SCAN_DEFAULT = 100
MISASSIGNED_SCAN_MAX = 200
CRITIQUE_CONCURRENCY = 4
# Every hide toggle off except rejected, so a category audit or a weight sample is not under-counted.
ALL_VISIBLE = {"hide_rejected": "1", "hide_bursts": "0", "hide_duplicates": "0", "hide_brackets": "0",
               "hide_panoramas": "0", "hide_blinks": "0", "collapse_stacks": "0"}
BASIS_NOTE = ("an approximation from the stored metrics only (nothing is re-scored or re-read from the files): no percentile normalisation snapshot, no penalties, "
              "no quality-folding or renormalisation for unavailable metrics. Read the RANK changes first; the "
              "mean shift is secondary")
CLAMP_NOTE = "scores are capped at 10, so a shift on a photo at the cap understates"
STALE_NOTE = "nothing was changed: stored scores and the config are untouched, and the digest is not consent"
SCORES_STALE_NOTE = ("the weights are stored but NO photo was re-scored: stored scores, ranks and the gallery change only "
                     "after recompute_scores. Ask the user before recomputing")
RELOAD_COMPARE_NOTE = ("tell the user to reload /compare before editing weights there: an open weights or suggestions "
                       "tab holds the old vector and would post it back on its next edit")
NO_UNDO_WARNING = {"code": "no_undo_snapshot",
                   "message": "no weight snapshot was found for this change, so undo is not guaranteed"}
CONFIRMATION_MESSAGE = ("the weights or the proposal changed since the preview (or it expired after "
                        f"{int(nonce.TTL_SECONDS // 60)} minutes, or the server restarted); preview again, show the user "
                        "the result and retry with the new preview_digest")
RESTORE_CONFIRMATION_MESSAGE = ("the weights moved since the dry run, `confirm` is missing or wrong, or it expired after "
                                f"{int(nonce.TTL_SECONDS // 60)} minutes; dry-run again, show the user the result and "
                                "retry with the new `confirm`")
OVERRIDE_CONFIRMATION_MESSAGE = ("a photo's category changed since the dry run, `confirm` is missing or wrong, or it "
                                 f"expired after {int(nonce.TTL_SECONDS // 60)} minutes; dry-run again, show the user "
                                 "the list and retry with the new `confirm`")
RECOMPUTE_NOTE = ("A category recompute rewrites only that category's scores and does not refresh burst or sequence groups "
                  "(`all` does). Either run also saves the library's percentile snapshot, which every category's next "
                  "normalisation reads. Poll recompute_status; do not start another job meanwhile")
CATEGORY_PIN_NOTE = ("Sticky: survives --recompute-average; each aggregate was recomputed now. Undo one photo with "
                     "clear_category_override")
MISASSIGNED_NOTE = ("A heuristic, not a probability: each candidate is only worth a look, never proof of a wrong "
                    "category. `stale` means the CURRENT config files the photo elsewhere (fix: recompute_scores, not an "
                    "override); `near_miss` means it missed a higher-priority category's first failing numeric bound by "
                    f"under {int(wm.NEAR_MISS_FRACTION * 100)}% (only the first five rejected categories are examined)")


def configured_keys(category: str) -> list[str]:
    """The ``*_percent`` keys the category's resolved config block holds, explicit zeros included.

    Read from a fresh ``server_scoring_config()`` (the override over the shipped defaults), not from the route
    body, which pads every metric with 0 and so cannot tell a key the operator set from one it never wrote.
    """
    for cat in server_scoring_config().get_categories():
        if cat.get("name") == category:
            return sorted(k for k in (cat.get("weights") or {}) if k.endswith(wm.SUFFIX))
    return []


def _issues(messages: list[str]) -> dict:
    return err("invalid_input", "; ".join(messages), issues=[{"message": m} for m in messages])


def _shape_breakdown(items: list, top_n: int) -> dict:
    shaped = [{"metric_key": i.get("metric_key"), "value": i.get("value"),
               "weight_percent": round((i.get("weight") or 0) * 100, 1), "contribution": i.get("contribution")}
              for i in items]
    rest = shaped[top_n:]
    return {"breakdown": shaped[:top_n],
            "rest": {"count": len(rest), "contribution": round(sum(i["contribution"] or 0 for i in rest), 2)}}


def _shape_explanation(path: str, body: dict, top_n: int) -> dict:
    reason = body.get("category_reason") or {}
    shaped = {
        "path": path, "category": body.get("category"),
        "category_reason": {"reason_key": reason.get("reason_key"), "details": reason.get("details") or [],
                            "rejected": (reason.get("rejected") or [])[:REJECTED_SHOWN]},
        "stored_aggregate": body.get("aggregate"), "current_formula_score": body.get("current_formula_score"),
        "stored_matches_current": body.get("stored_score_matches_current_formula"),
        **_shape_breakdown(body.get("breakdown") or [], top_n),
        "native_adjustment": body.get("native_adjustment"),
        "strengths": body.get("strengths") or [], "weaknesses": body.get("weaknesses") or [],
        "penalties": body.get("penalties") or {}, "distortions": body.get("distortions") or [],
        "normalization_basis": body.get("normalization_basis"), "weights": "effective",
        "note": ("weight_percent is the EFFECTIVE weight (after folding `quality` into `aesthetic` and "
                 "renormalising for metrics this install does not run), not the configured *_percent. "
                 "contribution is in score points of 10; the contributions plus native_adjustment make "
                 "current_formula_score. A stored aggregate that differs from it means the scores are stale "
                 "or a penalty applies."),
    }
    if body.get("explanation_unavailable_reason"):
        shaped["explanation_unavailable_reason"] = body["explanation_unavailable_reason"]
    return shaped


async def _current_weights(client: InternalClient, grant: Any, category: str, timeout: float) -> tuple[Optional[dict], dict]:
    got = await client.call(grant, "category_weights", query={"category": category}, timeout=timeout)
    return (got, {}) if not got["ok"] else (None, got["data"] or {})


async def _proposal(client: InternalClient, grant: Any, category: str, weights: Optional[dict], deltas: Optional[dict],
                    timeout: float) -> tuple[Optional[dict], dict, dict]:
    """``(error, current, resulting)``: the category's weights and the vector the proposal produces.

    Shared by the preview and the apply, so both validate exactly alike (the server's own rule plus the
    modifier refusal) and bind their digest to the same two vectors.
    """
    failure, row = await _current_weights(client, grant, category, timeout)
    if failure is not None:
        return failure, {}, {}
    current = wm.nonzero(row.get("weights"), True)
    problems, resulting = wm.resulting_vector(current, weights, deltas)
    if problems:
        return _issues(problems), {}, {}
    if wm.weights_sum(resulting) <= 0:
        return err("invalid_input", "all_weights_zero: the proposal leaves every weight at 0, so no photo "
                   "could be scored; give at least one metric a positive weight"), {}, {}
    return None, current, resulting


async def _newest_snapshot(client: InternalClient, grant: Any, category: str,
                           timeout: float) -> tuple[bool, Optional[dict]]:
    """``(known, row)``: the category's snapshot with the highest id (``None`` when it has none).

    ``known`` is False when the read failed: the caller then cannot say which snapshot a write made, and must
    report it as unknown instead of reading the failure as "no snapshots yet".
    """
    got = await client.call(grant, "weight_snapshots", query={"category": category, "limit": SNAPSHOT_LATEST},
                            timeout=timeout)
    if not got["ok"]:
        return False, None
    rows = (got["data"] or {}).get("snapshots") or []
    return True, (max(rows, key=lambda r: r.get("id") or 0) if rows else None)


async def _made_snapshot(client: InternalClient, grant: Any, category: str, timeout: float,
                         before: tuple[bool, Optional[dict]], created_by: str) -> Optional[dict]:
    """The snapshot a write just made: the id grew AND the row carries the writer's tag (never a timestamp compare).

    ``None`` when either read failed (unknown) or no such row appeared.
    """
    known_after, after = await _newest_snapshot(client, grant, category, timeout)
    if not before[0] or not known_after:
        return None
    if after and (after.get("id") or 0) > ((before[1] or {}).get("id") or 0) and after.get("created_by") == created_by:
        return {"id": after["id"], "created_by": created_by}
    return None


def _shape_snapshot(snapshot: dict) -> dict:
    stored = snapshot.get("weights")
    reason = wm.snapshot_unrestorable_reason(stored)
    shaped = {key: snapshot.get(key) for key in ("id", "category", "timestamp", "created_by", "description",
                                                 "category_bonus", "accuracy_before", "accuracy_after",
                                                 "comparisons_used")}
    shaped["weights"] = wm.nonzero(stored)
    shaped["restorable"] = reason is None
    if reason is not None:
        shaped["not_restorable_reason"] = reason
    return shaped


async def _find_snapshot(client: InternalClient, grant: Any, snapshot_id: int,
                         timeout: float) -> tuple[Optional[dict], Optional[dict], list[int], bool]:
    """``(error, snapshot, ids_seen, window_full)``: the list route has no id filter, so page it (newest first)."""
    seen: list[int] = []
    more = False
    for page in range(SNAPSHOT_PAGES):
        got = await client.call(grant, "weight_snapshots", timeout=timeout, query={
            "limit": SNAPSHOT_PAGE_SIZE, "offset": page * SNAPSHOT_PAGE_SIZE})
        if not got["ok"]:
            return got, None, seen, False
        body = got["data"] or {}
        for snapshot in body.get("snapshots") or []:
            if snapshot.get("id") == snapshot_id:
                return None, snapshot, seen, False
            seen.append(snapshot.get("id"))
        more = bool(body.get("has_more"))
        if not more:
            break
    return None, None, seen, more


async def _sample_paths(client: InternalClient, grant: Any, category: str, count: int,
                        timeout: float) -> tuple[Optional[dict], list[str], int, str]:
    """``(error, paths, category_total, scope)``: evenly spaced ranks of the category's best (and, when the
    category is larger than one page, worst) photos by stored aggregate."""
    base = {"category": category, "sort": "aggregate", "page": 1, "per_page": SAMPLE_PAGE, **ALL_VISIBLE}
    top = await client.call(grant, "search_photos", query={**base, "sort_direction": "DESC"}, timeout=timeout)
    if not top["ok"]:
        return top, [], 0, ""
    body = top["data"] or {}
    total = int(body.get("total") or 0)
    best = [p["path"] for p in body.get("photos") or []]
    if total <= SAMPLE_PAGE:
        return None, wm.evenly_spaced(best, count), total, "whole_category"
    bottom = await client.call(grant, "search_photos", query={**base, "sort_direction": "ASC"}, timeout=timeout)
    if not bottom["ok"]:
        return bottom, [], total, ""
    worst = [p["path"] for p in (bottom["data"] or {}).get("photos") or []]
    half = max(1, count // 2)
    picked = wm.evenly_spaced(best, half) + wm.evenly_spaced(worst, count - half)
    return None, list(dict.fromkeys(picked)), total, "top_and_bottom_100_by_aggregate"


async def _score(client: InternalClient, grant: Any, gate: asyncio.Semaphore, path: str, body: dict,
                 timeout: float) -> Optional[float]:
    async with gate:
        got = await client.call(grant, "preview_score", json={"path": path, "weights": body}, timeout=timeout)
    score = (got["data"] or {}).get("preview_score") if got["ok"] else None
    return float(score) if isinstance(score, (int, float)) else None


def register_scoring_tools(server: MCPServer, client: InternalClient, registry: TabRegistry) -> None:
    def add(fn, name: str, description: str, requires=None, write: bool = False) -> None:
        register_tool(server, fn, name, description, WRITE_ANNOTATIONS if write else READ_ANNOTATIONS,
                      WRITE_TOOL_LEVELS[name], requires=requires)

    async def explain_score(
        ctx: Context, path: Annotated[Optional[str], Field(min_length=1, max_length=4096)] = None,
        target: Target = None, top_n: Annotated[int, Field(ge=1, le=TOP_N_MAX)] = 5, tab_id: TabId = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if (path is None) == (target is None):
                return err("invalid_input", "Give exactly one of `path` or `target: \"selection\"`")
            photo = path
            if photo is None:
                failure, chosen, _ = await resolve_selected_paths(
                    client, grant, registry, resolved, settings, tab_id=tab_id, cap=1, exact_one=True)
                if failure is not None or not chosen:
                    return failure or err("invalid_input", "Nothing is selected in the tab")
                photo = chosen[0]
            got = await client.call(grant, "critique", query={"path": photo, "mode": "rule"},
                                    timeout=settings["call_timeout_s"])
            if not got["ok"]:
                return got
            return ok(_shape_explanation(photo, got["data"] or {}, top_n))
        return await run_tool(ctx, "explain_score", handler)

    async def category_weights(
        ctx: Context, category: Annotated[Optional[str], Field(min_length=1, max_length=100)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            got = await client.call(grant, "category_weights", query={"category": category},
                                    timeout=settings["call_timeout_s"])
            if not got["ok"]:
                return got
            shaped = shape_category_weights(got["data"] or {}, category is not None)
            if category is not None:
                shaped["configured_keys"] = await asyncio.to_thread(configured_keys, category)
            return ok(shaped)
        return await run_tool(ctx, "category_weights", handler)

    async def preview_weights(
        ctx: Context, category: Annotated[str, Field(min_length=1, max_length=100)],
        weights: Annotated[Optional[dict[str, float]], Field(max_length=len(VALID_WEIGHT_COLUMNS) * 2)] = None,
        deltas: Annotated[Optional[dict[str, float]], Field(max_length=len(VALID_WEIGHT_COLUMNS) * 2)] = None,
        sample: Annotated[int, Field(ge=3, le=SAMPLE_MAX)] = SAMPLE_DEFAULT,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            failure, current, resulting = await _proposal(client, grant, category, weights, deltas, timeout)
            if failure is not None:
                return failure
            before, after = wm.route_vectors(current, resulting)
            failure, paths, total, scope = await _sample_paths(client, grant, category, sample, timeout)
            if failure is not None:
                return failure
            if not paths:
                return err("invalid_input", f"The category `{category}` has no visible photo to preview on")
            gate = asyncio.Semaphore(PREVIEW_CONCURRENCY)
            old, new = await asyncio.gather(
                asyncio.gather(*(_score(client, grant, gate, p, before, timeout) for p in paths)),
                asyncio.gather(*(_score(client, grant, gate, p, after, timeout) for p in paths)))
            scored = [(p, a, b) for p, a, b in zip(paths, old, new) if a is not None and b is not None]
            skipped = len(paths) - len(scored)
            if skipped > SKIP_LIMIT * len(paths):
                return err("upstream_error", f"{skipped} of {len(paths)} sampled photos could not be scored; "
                           "the preview would be skewed, try again")
            shifts = [b - a for _, a, b in scored]
            digest = nonce.digest([], wm.digest_options(category, current, resulting))
            token = nonce.issue(grant.nonce_owner, "apply_weights", digest)
            return ok({
                "category": category, "basis": "approximate", "basis_note": BASIS_NOTE, "clamp_note": CLAMP_NOTE,
                "warnings": wm.warnings_for(resulting), "weights_sum": wm.weights_sum(resulting),
                "sampled": len(scored), "sampled_of": total, "sample_scope": scope, "skipped": skipped,
                "proposal": {"changed": wm.changed_keys(current, resulting), "sum": wm.weights_sum(resulting)},
                "mean_shift": round(statistics.fmean(shifts), 3), "median_shift": round(statistics.median(shifts), 3),
                "max_up": round(max(shifts), 2), "max_down": round(min(shifts), 2),
                "rank_changes": wm.rank_changes({p: a for p, a, _ in scored}, {p: b for p, _, b in scored}),
                "stale_note": STALE_NOTE, "preview_digest": token,
                "preview_digest_expires_in_s": int(nonce.TTL_SECONDS)})
        return await run_tool(ctx, "preview_weights", handler)

    async def apply_weights(
        ctx: Context, category: Annotated[str, Field(min_length=1, max_length=100)],
        preview_digest: Annotated[Optional[str], Field(max_length=200)] = None,
        weights: Annotated[Optional[dict[str, float]], Field(max_length=len(VALID_WEIGHT_COLUMNS) * 2)] = None,
        deltas: Annotated[Optional[dict[str, float]], Field(max_length=len(VALID_WEIGHT_COLUMNS) * 2)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            failure, current, resulting = await _proposal(client, grant, category, weights, deltas, timeout)
            if failure is not None:
                return failure
            digest = nonce.digest([], wm.digest_options(category, current, resulting))
            if not nonce.check(grant.nonce_owner, "apply_weights", digest, preview_digest):
                return err("confirmation_required", CONFIRMATION_MESSAGE)
            before = await _newest_snapshot(client, grant, category, timeout)
            changed = wm.changed_keys(current, resulting)
            keys = set(await asyncio.to_thread(configured_keys, category)) | set(changed)
            written = await client.call(grant, "update_weights", timeout=timeout, json={
                "category": category, "recalculate": False, "weights": {k: resulting.get(k, 0) for k in sorted(keys)}})
            if not written["ok"]:
                return written
            failure, row = await _current_weights(client, grant, category, timeout)
            stored = {} if failure is not None else wm.nonzero(row.get("weights"), True)
            known = {k for k in resulting if wm.base_key(k) in VALID_WEIGHT_COLUMNS}
            verified = failure is None and all(stored.get(k, 0) == resulting.get(k, 0) for k in known)
            snapshot = await _made_snapshot(client, grant, category, timeout, before, "auto:edit")
            warnings = wm.warnings_for(resulting) + ([] if snapshot else [NO_UNDO_WARNING])
            return ok({
                "category": category, "verified": verified, "previous": {k: v["from"] for k, v in changed.items()},
                "applied": {k: v["to"] for k, v in changed.items()}, "weights_sum": wm.weights_sum(resulting),
                "warnings": warnings, "snapshot": snapshot, "scores_stale": True, "next": "recompute_scores",
                "reload_compare": True, "note": f"{SCORES_STALE_NOTE}. {RELOAD_COMPARE_NOTE}"})
        return await run_tool(ctx, "apply_weights", handler, write=True)

    async def list_weight_snapshots(
        ctx: Context, category: Annotated[Optional[str], Field(min_length=1, max_length=100)] = None,
        limit: Annotated[int, Field(ge=1, le=SNAPSHOT_PAGE_SIZE)] = SNAPSHOT_LIST_DEFAULT,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            got = await client.call(grant, "weight_snapshots", timeout=settings["call_timeout_s"],
                                    query={"category": category, "limit": limit, "offset": offset})
            if not got["ok"]:
                return got
            body = got["data"] or {}
            return ok({"snapshots": [_shape_snapshot(s) for s in body.get("snapshots") or []],
                       "has_more": bool(body.get("has_more")), "offset": offset, "limit": limit})
        return await run_tool(ctx, "list_weight_snapshots", handler)

    async def restore_weight_snapshot(
        ctx: Context, snapshot_id: Annotated[int, Field(ge=1)], dry_run: bool = True,
        confirm: Annotated[Optional[str], Field(max_length=200)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            failure, snapshot, seen, window_full = await _find_snapshot(client, grant, snapshot_id, timeout)
            if failure is not None:
                return failure
            if snapshot is None:
                window = SNAPSHOT_PAGE_SIZE * SNAPSHOT_PAGES
                return err("not_found", f"Snapshot {snapshot_id} was not found among the newest {window} snapshots"
                           if window_full else f"Snapshot {snapshot_id} was not found",
                           nearest_ids=seen[:NEAREST_IDS])
            reason = wm.snapshot_unrestorable_reason(snapshot.get("weights"))
            if reason is not None:
                return err("unsupported_snapshot", reason)
            category = snapshot["category"]
            failure, row = await _current_weights(client, grant, category, timeout)
            if failure is not None:
                if failure.get("error") == "not_found":
                    return err("not_found", f"The snapshot's category `{category}` no longer exists in the config")
                return failure
            current, target = wm.nonzero(row.get("weights"), True), wm.nonzero(snapshot["weights"])
            changed = wm.changed_keys(current, target)
            bonus_now, bonus_then = (row.get("modifiers") or {}).get("bonus") or 0, snapshot.get("category_bonus")
            # No bonus and a bonus of 0 are the same to the scorer, so a recorded 0 over an absent bonus is no change.
            bonus_change = ({"from": bonus_now, "to": bonus_then}
                            if bonus_then is not None and bonus_then != bonus_now else None)
            if not changed and bonus_change is None:
                return err("invalid_input", "no change: the snapshot equals the current weights")
            digest = nonce.digest([], {"snapshot_id": snapshot_id, "category": category, "bonus": [bonus_now, bonus_then],
                                       "current": dict(sorted(current.items())), "target": dict(sorted(target.items()))})
            if dry_run:
                token = nonce.issue(grant.nonce_owner, "restore_weight_snapshot", digest)
                return ok({"category": category, "snapshot": {k: snapshot.get(k) for k in (
                               "id", "created_by", "timestamp", "description")},
                           "would_change": changed, "bonus_change": bonus_change,
                           "weights_sum_after": wm.weights_sum(target), "warnings": wm.warnings_for(target),
                           "confirm": token, "confirm_expires_in_s": int(nonce.TTL_SECONDS),
                           "note": "nothing was changed; show the user the change and retry with dry_run=false and `confirm`"})
            if not nonce.check(grant.nonce_owner, "restore_weight_snapshot", digest, confirm):
                return err("confirmation_required", RESTORE_CONFIRMATION_MESSAGE)
            before = await _newest_snapshot(client, grant, category, timeout)
            restored = await client.call(grant, "restore_weights", json={"snapshot_id": snapshot_id}, timeout=timeout)
            if not restored["ok"]:
                return restored
            failure, after_row = await _current_weights(client, grant, category, timeout)
            bonus_ok = bonus_change is None or (after_row.get("modifiers") or {}).get("bonus") == bonus_then
            verified = failure is None and wm.nonzero(after_row.get("weights"), True) == target and bonus_ok
            undo = await _made_snapshot(client, grant, category, timeout, before, "auto:pre_restore")
            return ok({"category": category, "restored_snapshot_id": snapshot_id, "verified": verified,
                       "would_have_changed": changed, "bonus_change": bonus_change,
                       "undo_snapshot_id": undo["id"] if undo else None,
                       "warnings": [] if undo else [NO_UNDO_WARNING], "scores_stale": True,
                       "next": "recompute_scores", "reload_compare": True,
                       "note": f"{SCORES_STALE_NOTE}. {RELOAD_COMPARE_NOTE}"})
        return await run_tool(ctx, "restore_weight_snapshot", handler, write=True)

    async def recompute_scores(
        ctx: Context, category: Annotated[Optional[str], Field(min_length=1, max_length=100)] = None,
        all: bool = False,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if (category is None) == (not all):
                return err("invalid_input", "Give exactly one of `category` or `all: true`")
            got = await client.call(grant, "recompute_start", timeout=settings["call_timeout_s"],
                                    json={"confirm": True, **({"category": category} if category else {})})
            if not got["ok"]:
                return got
            body = got["data"] or {}
            return ok({"started": True, "kind": "recompute", "scope": body.get("scope"),
                       "started_at": body.get("started_at"), "poll": "recompute_status", "note": RECOMPUTE_NOTE})
        return await run_tool(ctx, "recompute_scores", handler, write=True)

    async def recompute_status(
        ctx: Context, started_at: Optional[float] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            got = await client.call(grant, "recompute_status", timeout=settings["call_timeout_s"])
            if not got["ok"]:
                return got
            return ok(wm.job_state(got["data"] or {}, started_at))
        return await run_tool(ctx, "recompute_status", handler)

    async def learned_weights(
        ctx: Context, category: Annotated[str, Field(min_length=1, max_length=100)], with_confidence: bool = False,
        include_ties: bool = True,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = max(settings["call_timeout_s"], LEARNED_TIMEOUT_S)
            got = await client.call(grant, "learned_weights", timeout=timeout, query={
                "category": category, "include_ties": "true" if include_ties else "false"})
            if not got["ok"]:
                return got
            body = got["data"] or {}
            if not body.get("available"):
                message = body.get("message")
                if message == external_learning_result()["error"]:
                    reason = "unavailable_if_external"
                elif "min_required" in body:
                    reason = "not_enough_comparisons"
                else:
                    reason = "optimizer_unavailable"
                return ok({"available": False, "reason": reason, "message": message,
                           **{k: body[k] for k in ("comparisons", "min_required") if k in body}})
            changes, proposal = wm.learned_changes(body.get("current_weights") or {}, body.get("suggested_weights") or {})
            shaped = {"available": True, "category": category, "method": body.get("method"),
                      "suggest_changes": bool(body.get("suggest_changes")),
                      "accuracy_before": body.get("accuracy_before"), "accuracy_after": body.get("accuracy_after"),
                      "improvement": body.get("improvement"), "comparisons_used": body.get("comparisons_used"),
                      "ties_included": body.get("ties_included"), "mispredicted_count": body.get("mispredicted_count")}
            if shaped["suggest_changes"]:
                shaped.update(changes=changes, proposal=proposal,
                              next="pass `proposal` as `weights` to preview_weights, show the user the shift, "
                                   "then apply_weights",
                              note="learned from the user's own A/B comparisons; a suggestion, not a verdict")
            else:
                shaped["note"] = "the optimizer found no improvement over the current weights: do not propose a change"
            if with_confidence:
                conf = await client.call(grant, "weight_confidence", timeout=timeout,
                                         query={"category": category, "n_bootstrap": CONFIDENCE_BOOTSTRAP})
                cbody = conf["data"] or {} if conf["ok"] else {}
                shaped["confidence"] = (
                    {"stable_components": cbody.get("stable_components") or [], "n_bootstrap": cbody.get("n_bootstrap"),
                     "comparisons_used": cbody.get("comparisons_used"),
                     **{k: wm.nonzero(cbody.get(k)) for k in ("lower_bounds", "upper_bounds", "confidence_intervals")}}
                    if cbody.get("available") else {"available": False, "message": cbody.get("message") or conf.get("message")})
            return ok(shaped)
        return await run_tool(ctx, "learned_weights", handler)

    async def misassigned_categories(
        ctx: Context, category: Annotated[str, Field(min_length=1, max_length=100)],
        limit: Annotated[int, Field(ge=1, le=MISASSIGNED_LIMIT_MAX)] = MISASSIGNED_LIMIT_DEFAULT,
        scan: Annotated[int, Field(ge=1, le=MISASSIGNED_SCAN_MAX)] = MISASSIGNED_SCAN_DEFAULT,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            failure, _ = await _current_weights(client, grant, category, timeout)
            if failure is not None:
                return failure
            rows: list[dict] = []
            total = 0
            for page in range(1, (scan + SAMPLE_PAGE - 1) // SAMPLE_PAGE + 1):
                got = await client.call(grant, "search_photos", timeout=timeout, query={
                    "category": category, "sort": "aggregate", "sort_direction": "DESC", "page": page,
                    "per_page": SAMPLE_PAGE, **ALL_VISIBLE})
                if not got["ok"]:
                    return got
                body = got["data"] or {}
                total = int(body.get("total") or 0)
                rows += body.get("photos") or []
                if len(rows) >= min(scan, total):
                    break
            rows = rows[:scan]
            gate = asyncio.Semaphore(CRITIQUE_CONCURRENCY)

            async def critique(photo):
                async with gate:
                    return await client.call(grant, "critique", query={"path": photo["path"], "mode": "rule"},
                                             timeout=timeout)

            answers = await asyncio.gather(*(critique(p) for p in rows))
            if rows and not any(a["ok"] for a in answers):
                return answers[0]
            candidates: list[dict] = []
            pinned = 0
            failed = 0
            for photo, answer in zip(rows, answers):
                if not answer["ok"]:
                    failed += 1
                    continue
                crit = answer["data"] or {}
                reason = crit.get("category_reason") or {}
                if reason.get("reason_key") == "override":
                    pinned += 1
                    continue
                stored, formula = photo.get("category"), crit.get("category")
                if formula and formula != stored:
                    candidates.append({"path": photo["path"], "stored": stored, "suggested": formula,
                                       "signal": "stale", "aggregate": photo.get("aggregate")})
                elif (miss := wm.near_miss(reason.get("rejected") or [])) is not None:
                    candidates.append({"path": photo["path"], "stored": stored, "suggested": miss["suggested"],
                                       "signal": "near_miss", "mismatch": miss["mismatch"],
                                       "aggregate": photo.get("aggregate")})
            partial = len(rows) < total or failed > 0
            return ok({"category": category, "candidates": candidates[:limit], "candidates_total": len(candidates),
                       "scanned": len(rows) - failed, "failed": failed, "of_total": total, "partial": partial,
                       "skipped_overridden": pinned, "confidence_basis": "heuristic",
                       "note": MISASSIGNED_NOTE + ("; the scan was partial: " + "; ".join(filter(None, [
                           "only the best-scored photos were examined" if len(rows) < total else "",
                           f"{failed} photo(s) could not be examined" if failed else ""])) if partial else "")})
        return await run_tool(ctx, "misassigned_categories", handler)

    async def override_categories(
        ctx: Context, category: Annotated[str, Field(min_length=1, max_length=100)], paths: Paths,
        dry_run: bool = True, confirm: Annotated[Optional[str], Field(max_length=200)] = None,
        expected_count: Optional[int] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            if len(paths) > PER_PHOTO_CAP:
                return _too_large(len(paths), PER_PHOTO_CAP)
            names = await asyncio.to_thread(lambda: [c.get("name") for c in server_scoring_config().get_categories()])
            if category not in names:
                return err("invalid_input", f"Unknown category `{category}`; see the facet://categories resource")
            unique = list(dict.fromkeys(paths))
            failure, found = await photo_io.read_photos(client, grant, unique, timeout)
            if failure is not None:
                return failure
            missing = [p for p in unique if p not in found]
            already = [p for p in unique if p in found and found[p].get("category") == category]
            pin = [p for p in unique if p in found]
            change = [p for p in pin if p not in already]
            # Every found photo is pinned, the ones already in the category too: a later --recompute-average
            # would otherwise move them.
            digest = nonce.digest(pin, {"category": category, "from": {p: found[p].get("category") for p in pin}})
            if dry_run:
                shaped = {"category": category, "would_change": len(change), "would_pin": len(pin),
                          "already": already, "missing": missing,
                          "photos": [{"path": p, "from": found[p].get("category")} for p in pin],
                          "note": "nothing was changed; `already` photos are pinned too, so a recompute cannot move "
                                  "them. Show the user the list and retry with dry_run=false, `confirm` and "
                                  "`expected_count` equal to would_pin"}
                if pin:
                    shaped["confirm"] = nonce.issue(grant.nonce_owner, "override_categories", digest)
                    shaped["confirm_expires_in_s"] = int(nonce.TTL_SECONDS)
                return ok(shaped)
            if expected_count is None:
                return err("invalid_input", "A real run requires `expected_count`: the `would_pin` of the dry run")
            if not nonce.check(grant.nonce_owner, "override_categories", digest, confirm):
                return err("confirmation_required", OVERRIDE_CONFIRMATION_MESSAGE)
            if expected_count != len(pin):
                return err("invalid_input", f"expected_count {expected_count} does not match the {len(pin)} "
                           "photos that would be pinned; dry-run again")
            for done, path in enumerate(pin):
                applied = await photo_io.apply_category(client, grant, timeout, path, category)
                if not applied["ok"]:
                    return {**applied, "affected": done, "remaining": len(pin) - done - 1, "failed_path": path}
            return ok({"category": category, "affected": len(pin), "recategorised": len(change), "remaining": 0,
                       "already": already, "missing": missing, "note": CATEGORY_PIN_NOTE})
        return await run_tool(ctx, "override_categories", handler, write=True)

    add(explain_score, "explain_score",
        "Why one photo scored what it did: its category (and why it is not a higher-priority one), the stored "
        "aggregate, the top `top_n` metrics as {metric_key, value, weight_percent, contribution}, the rest as a "
        "count and a sum, strengths, weaknesses, penalties and distortions. Pass `path` or "
        "`target: \"selection\"` (one photo selected in the tab). Rule-based and read-only: it never runs the "
        "VLM and writes nothing. weight_percent is the EFFECTIVE weight, not the configured one.",
        requires=critique_available)
    add(category_weights, "category_weights",
        "Read a category's scoring weights (non-zero only), modifiers, filters and priority; without `category`, "
        "every category's non-zero weights. Edition level. Changing weights is a separate, confirmed step.")
    add(preview_weights, "preview_weights",
        "APPROXIMATE preview of a weight change for one category, nothing is stored. Give exactly one of `weights` "
        "(a partial map merged over the current weights, `<metric>` or `<metric>_percent`: 0..100) or `deltas` "
        "(signed percentage points added to the current values). It re-scores up to `sample` photos of the "
        "category under the current and the proposed weights (both normalised like the scorer) and returns the "
        "rank changes first, the mean shift second, `warnings` (a sum outside 95..105 is rescaled by the config "
        "loader; an unknown key is stored as typed and dropped later) and a single-use `preview_digest`. Show the "
        "user the proposal, the shift and `basis_note`; the digest is not consent. Bonus and modifiers are not "
        "editable here. A category with more than 100 photos is sampled from its best and worst 100 only "
        "(`sample_scope`).")
    add(apply_weights, "apply_weights",
        "Write a category's weights to the config, ONLY after the user agreed to the previewed change. Repeat the SAME "
        "`weights` or `deltas` you gave preview_weights and pass its `preview_digest`: without the digest of this exact "
        "proposal over the current weights it refuses `confirmation_required` and writes nothing. The old weights are "
        "snapshotted first (`snapshot`, undo with restore_weight_snapshot). No photo is re-scored: the result says "
        "`scores_stale` and `next: recompute_scores`; ask the user before recomputing. Edition level; bonus and "
        "modifiers are not editable here.", write=True)
    add(list_weight_snapshots, "list_weight_snapshots",
        "The saved weight snapshots, newest first (optionally one `category`), with their non-zero weights and whether "
        "each is `restorable`. Every apply_weights and restore makes one (`auto:edit`, `auto:pre_restore`). Paginate "
        "with `limit` (<=100) and `offset`; `has_more` says whether another page exists.")
    add(restore_weight_snapshot, "restore_weight_snapshot",
        "Put a snapshot's weights (and its recorded bonus) back. `dry_run` (the default) lists the change and returns a "
        "single-use `confirm`; the real run needs `dry_run=false` and that `confirm`, and refuses "
        "`confirmation_required` if the weights moved meanwhile. A snapshot saved in another format by the web UI is "
        "`unsupported_snapshot`. The current weights are snapshotted first (`undo_snapshot_id`). No photo is re-scored "
        "(`scores_stale`).", write=True)
    add(recompute_scores, "recompute_scores",
        "Re-score the library with the current weights as a background job: give `category` (that category only) or "
        "`all: true` (every photo, also refreshes burst and sequence groups). It starts at once and returns "
        "`started_at`; poll recompute_status. Only one job runs at a time (`conflict`). Ask the user first: it can run "
        "for a long while.", write=True)
    add(recompute_status, "recompute_status",
        "State of the recompute job: `running`, `succeeded`, `failed`, `busy` (another process holds the library) or "
        "`idle`. Pass the `started_at` recompute_scores returned to learn whether the status describes that job "
        "(`matches_started_job`).")
    add(learned_weights, "learned_weights",
        "The weights the user's own A/B comparisons favour for a category, from the optimizer (nothing stored). "
        "Returns the non-zero `changes` and a `proposal` to hand to preview_weights; `available: false` with a "
        "`reason` when there are too few comparisons or the learning backend is external. `with_confidence` adds "
        "bootstrap intervals. A suggestion, never applied by itself.")
    add(misassigned_categories, "misassigned_categories",
        "Photos of a category that may belong elsewhere, from the best-scored `scan` photos: `stale` (the current "
        "config files it in another category: recompute_scores fixes that) or `near_miss` (it just missed a "
        "higher-priority category's numeric bound). A heuristic to look at, not proof; photos with a manual category "
        "are skipped. Read-only.", requires=critique_available)
    add(override_categories, "override_categories",
        f"Pin the category of several photos (<={PER_PHOTO_CAP} paths) after the user agreed. `dry_run` (the default) "
        "lists who would change (photos already in the category are pinned too) and returns a single-use `confirm`; the real run needs `dry_run=false`, that "
        "`confirm` and `expected_count` equal to `would_pin`. It stops at the first failure and reports `affected`, "
        "`remaining` and `failed_path`. Sticky; undo one photo with clear_category_override.", write=True)


def shape_category_weights(body: dict, single: bool) -> dict:
    """The route body as the tool and the ``facet://scoring-weights`` resource report it: zero weights dropped."""
    if single:
        shown = wm.nonzero(body.get("weights"), True)
        return {"category": body.get("category"), "weights": shown, "weights_sum": wm.weights_sum(shown),
                "modifiers": body.get("modifiers") or {}, "filters": body.get("filters") or {},
                "priority": body.get("priority"),
                "zero_keys_count": sum(1 for k in (body.get("weights") or {}) if k not in shown),
                "valid_keys": [wm.percent_key(c) for c in VALID_WEIGHT_COLUMNS]}
    return {"categories": [{"name": c.get("name"), "priority": c.get("priority"),
                            "weights": wm.nonzero(c.get("weights"), True),
                            "bonus": (c.get("modifiers") or {}).get("bonus")}
                           for c in body.get("categories") or []]}
