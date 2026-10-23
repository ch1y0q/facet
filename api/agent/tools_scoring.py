"""Scoring tools, read and preview only: ``explain_score``, ``category_weights``, ``preview_weights``.

Nothing here writes. ``explain_score`` calls ``GET /api/critique`` in its rule mode (never the VLM mode, which
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
from api.agent.target import read_selection
from api.agent.tools_common import READ_ANNOTATIONS, register_tool
from api.agent.tools_write import WRITE_TOOL_LEVELS, TabId, Target
from config.category_filter import VALID_WEIGHT_COLUMNS

TOP_N_MAX = 12
REJECTED_SHOWN = 3
SAMPLE_DEFAULT = 30
SAMPLE_MAX = 100
SAMPLE_PAGE = 100
PREVIEW_CONCURRENCY = 4
SKIP_LIMIT = 0.2
CATEGORIES_SHOWN_KEYS = ("name", "priority", "weights", "bonus")
BASIS_NOTE = ("an approximation from the stored metrics only (nothing is re-scored or re-read from the files): no percentile normalisation snapshot, no penalties, "
              "no quality-folding or renormalisation for unavailable metrics. Read the RANK changes first; the "
              "mean shift is secondary")
CLAMP_NOTE = "scores are capped at 10, so a shift on a photo at the cap understates"
STALE_NOTE = "nothing was changed: stored scores and the config are untouched, and the digest is not consent"


def _non_zero(raw: Any) -> dict:
    """The ``*_percent`` weights of a route body that are not zero (the route pads every metric with 0)."""
    return {k: v for k, v in (raw or {}).items()
            if k.endswith(wm.SUFFIX) and isinstance(v, (int, float)) and v != 0}


def configured_keys(category: str) -> list[str]:
    """The ``*_percent`` keys the category's resolved config block holds, explicit zeros included.

    Read from a fresh ``server_scoring_config()`` (the override over the shipped defaults), not from the route
    body, which pads every metric with 0 and so cannot tell a key the operator set from one it never wrote.
    """
    from api.config import server_scoring_config
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


async def _one_path(client: InternalClient, grant: Any, registry: TabRegistry, resolved: Any, settings: dict,
                    tab_id: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    """``(error, path)`` for the tab's selection when it holds exactly one photo."""
    refusal, selection = await read_selection(registry, resolved, settings, tab_id)
    if refusal is not None or selection is None:
        return refusal, None
    if selection.count != 1:
        return err("invalid_input", f"explain_score takes one photo; the selection holds {selection.count}"), None
    if selection.scope == "paths":
        return None, selection.paths[0]
    listed = await client.call(grant, "photos_paths", query=selection.filters or {}, timeout=settings["call_timeout_s"])
    if not listed["ok"]:
        return listed, None
    left = [p for p in (listed["data"] or {}).get("paths") or [] if p not in set(selection.excluded)]
    if len(left) != 1:
        return err("invalid_input", "selection_changed: the view no longer holds the one photo the tab "
                   "selected; nothing was done. Re-read the selection and retry"), None
    return None, left[0]


async def _current_weights(client: InternalClient, grant: Any, category: str, timeout: float) -> tuple[Optional[dict], dict]:
    got = await client.call(grant, "category_weights", query={"category": category}, timeout=timeout)
    return (got, {}) if not got["ok"] else (None, got["data"] or {})


async def _sample_paths(client: InternalClient, grant: Any, category: str, count: int,
                        timeout: float) -> tuple[Optional[dict], list[str], int, str]:
    """``(error, paths, category_total, scope)``: evenly spaced ranks of the category's best (and, when the
    category is larger than one page, worst) photos by stored aggregate."""
    base = {"category": category, "sort": "aggregate", "page": 1, "per_page": SAMPLE_PAGE, "hide_rejected": "1",
            "hide_bursts": "0", "hide_duplicates": "0", "hide_brackets": "0", "hide_panoramas": "0",
            "hide_blinks": "0"}
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
    def add(fn, name: str, description: str, requires=None) -> None:
        register_tool(server, fn, name, description, READ_ANNOTATIONS, WRITE_TOOL_LEVELS[name], requires=requires)

    async def explain_score(
        ctx: Context, path: Annotated[Optional[str], Field(min_length=1, max_length=4096)] = None,
        target: Target = None, top_n: Annotated[int, Field(ge=1, le=TOP_N_MAX)] = 5, tab_id: TabId = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            if (path is None) == (target is None):
                return err("invalid_input", "Give exactly one of `path` or `target: \"selection\"`")
            photo = path
            if photo is None:
                failure, photo = await _one_path(client, grant, registry, resolved, settings, tab_id)
                if failure is not None or photo is None:
                    return failure or err("invalid_input", "Nothing is selected in the tab")
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
            failure, row = await _current_weights(client, grant, category, timeout)
            if failure is not None:
                return failure
            current = _non_zero(row.get("weights"))
            problems, resulting = wm.resulting_vector(current, weights, deltas)
            if problems:
                return _issues(problems)
            if wm.weights_sum(resulting) <= 0:
                return err("invalid_input", "all_weights_zero: the proposal leaves every weight at 0, so no photo "
                           "could be scored; give at least one metric a positive weight")
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
            try:
                token = nonce.issue(grant.nonce_owner, "apply_weights", digest)
            except nonce.NonceCapacityError:
                return err("too_many_pending", "Too many unconfirmed previews or dry runs are pending; finish "
                           f"one or wait {int(nonce.TTL_SECONDS // 60)} minutes")
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


def shape_category_weights(body: dict, single: bool) -> dict:
    """The route body as the tool and the ``facet://scoring-weights`` resource report it: zero weights dropped."""
    if single:
        shown = _non_zero(body.get("weights"))
        return {"category": body.get("category"), "weights": shown, "weights_sum": wm.weights_sum(shown),
                "modifiers": body.get("modifiers") or {}, "filters": body.get("filters") or {},
                "priority": body.get("priority"),
                "zero_keys_count": sum(1 for k in (body.get("weights") or {}) if k not in shown),
                "valid_keys": [wm.percent_key(c) for c in VALID_WEIGHT_COLUMNS]}
    return {"categories": [{"name": c.get("name"), "priority": c.get("priority"),
                            "weights": _non_zero(c.get("weights")),
                            "bonus": (c.get("modifiers") or {}).get("bonus")}
                           for c in body.get("categories") or []]}
