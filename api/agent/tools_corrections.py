"""Correction tools (sequence sets, category) and the per-face / per-subject group comparison.

The correction writers are edition tools that go through the same ``/api`` routes the darkroom and the
lightbox use. ``group_compare`` is a readonly read of the darkroom's
face / subject feeds with every bulky key (bounding boxes, base64 crops) dropped.
"""

from typing import Annotated, Any, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from pydantic import Field

from api.agent import photo_io
from api.types import SEQUENCE_OVERRIDE_SUPPRESSED
from api.agent.internal_client import InternalClient, err, ok
from api.agent.runtime import run_tool
from api.agent.tools_common import READ_ANNOTATIONS, WRITE_ANNOTATIONS, register_tool
from api.agent.tools_write import WRITE_TOOL_LEVELS

SEQUENCE_PATHS_CAP = 500
GROUP_COMPARE_CAP = 12
FACE_ITEMS_CAP = 6
ECHO_CAP = 5
SEQUENCE_KINDS = ("panorama", "hdr_panorama", "bracket")
PENDING_NEXT = ("Takes effect on the next detection pass (POST /api/scan/detect_panoramas, or "
                "`facet.py --detect-panoramas`); until then the gallery and culling groups look unchanged, and the "
                "photos carry sequence_override_pending=true.")
CLEARED_NEXT = ("The detector takes the frames back at the next pass; a cleared correction that was already "
                "applied changes the library only when that pass runs.")
CATEGORY_NOTE = "Sticky: survives --recompute-average; the aggregate was recomputed now."
CATEGORY_CLEARED_NOTE = "The filters decide the category again; the aggregate was recomputed now."

CorrectionKind = Literal["panorama", "hdr_panorama", "bracket", "suppress"]


def _round(value: Any) -> Any:
    return round(value, 2) if isinstance(value, (int, float)) else value


async def _echo(client: InternalClient, grant: Any, paths: list[str], timeout: float) -> dict:
    """What the library now says about the first few paths, so the agent reports the data, not the assumption."""
    failure, photos = await photo_io.read_photos(client, grant, paths[:ECHO_CAP], timeout)
    if failure is not None:
        return {}
    return {"state": [{"path": p, "sequence_override": photos[p].get("sequence_override"),
                       "sequence_override_pending": photos[p].get("sequence_override_pending")}
                      for p in paths[:ECHO_CAP] if p in photos]}


def _sequence_value(kind: str) -> str:
    return SEQUENCE_OVERRIDE_SUPPRESSED if kind == "suppress" else kind


def _faces_of(faces: list) -> dict:
    scored = [f for f in faces if f.get("eyes_open_score") is not None]
    smiles = [f["smile_score"] for f in faces if f.get("smile_score") is not None]
    return {"faces": len(faces), "blinks": sum(1 for f in faces if f.get("is_blink")),
            "worst_eyes_open": _round(min((f["eyes_open_score"] for f in scored), default=None)),
            "best_smile": _round(max(smiles, default=None)),
            "items": [{"id": f.get("id"), "eyes_open_score": _round(f.get("eyes_open_score")),
                       "smile_score": _round(f.get("smile_score")), "is_blink": bool(f.get("is_blink")),
                       "confidence": _round(f.get("confidence"))} for f in faces[:FACE_ITEMS_CAP]]}


def register_correction_tools(server: MCPServer, client: InternalClient) -> None:
    def add(fn, name: str, description: str, read_only: bool = False) -> None:
        register_tool(server, fn, name, description, READ_ANNOTATIONS if read_only else WRITE_ANNOTATIONS,
                      WRITE_TOOL_LEVELS[name])

    async def override_sequence(
        ctx: Context, paths: Annotated[list[str], Field(min_length=1, max_length=SEQUENCE_PATHS_CAP)],
        kind: CorrectionKind,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            named = list(dict.fromkeys(paths))
            if kind != "suppress" and len(named) < 2:
                return err("invalid_input", f"A {kind} set needs at least 2 frames; give 2 or more paths "
                           "(only kind=suppress and clear_sequence_override accept a single path)")
            timeout = settings["call_timeout_s"]
            upstream = await photo_io.apply_sequence(client, grant, timeout, named, _sequence_value(kind))
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            return ok({"overridden": body.get("overridden", 0), "skipped": body.get("skipped", 0), "kind": kind,
                       "pending": True, "next": PENDING_NEXT, **await _echo(client, grant, named, timeout)})
        return await run_tool(ctx, "override_sequence", handler, write=True)

    async def clear_sequence_override(
        ctx: Context, paths: Annotated[list[str], Field(min_length=1, max_length=SEQUENCE_PATHS_CAP)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            named = list(dict.fromkeys(paths))
            timeout = settings["call_timeout_s"]
            upstream = await photo_io.apply_sequence(client, grant, timeout, named, None)
            if not upstream["ok"]:
                return upstream
            return ok({"cleared": (upstream["data"] or {}).get("cleared", 0), "next": CLEARED_NEXT,
                       **await _echo(client, grant, named, timeout)})
        return await run_tool(ctx, "clear_sequence_override", handler, write=True)

    keyed = ("Keyed on the member paths you name, never on a group id (ids are renumbered on every detection "
             "run). To SPLIT a set, clear_sequence_override then override_sequence on the new groups.")
    add(override_sequence, "override_sequence",
        f"Correct what a set of frames is (<={SEQUENCE_PATHS_CAP} paths): kind `panorama`, `hdr_panorama` or "
        "`bracket` (needs >=2 frames; a bracket also needs distinct exposures and capture times, otherwise the "
        "route's reason comes back as invalid_input), or `suppress` (\"this is not one of these\"; one path is "
        "enough). The correction is STICKY but PENDING: it changes nothing visible until the next detection pass "
        "(`pending: true`; `state` echoes `sequence_override` / `sequence_override_pending` for the first "
        f"{ECHO_CAP} paths). " + keyed)
    add(clear_sequence_override, "clear_sequence_override",
        f"Drop the manual corrections of the named frames (<={SEQUENCE_PATHS_CAP} paths) and hand them back to "
        "the detector at its next pass. " + keyed)

    async def override_category(
        ctx: Context, path: Annotated[str, Field(min_length=1, max_length=4096)],
        category: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            upstream = await photo_io.apply_category(client, grant, timeout, path, category)
            if not upstream["ok"]:
                return upstream
            data = dict(upstream["data"] or {})
            data.pop("success", None)
            return ok({**data, "note": CATEGORY_NOTE})
        return await run_tool(ctx, "override_category", handler, write=True)

    async def clear_category_override(
        ctx: Context, path: Annotated[str, Field(min_length=1, max_length=4096)],
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            timeout = settings["call_timeout_s"]
            got = await client.call(grant, "get_photo", query={"path": path}, timeout=timeout)
            if not got["ok"]:
                return got
            old = (got["data"] or {}).get("category_override")
            if old is None:
                return ok({"path": path, "already": True})
            upstream = await photo_io.apply_category(client, grant, timeout, path, None)
            if not upstream["ok"]:
                return upstream
            data = dict(upstream["data"] or {})
            data.pop("success", None)
            return ok({**data, "note": CATEGORY_CLEARED_NOTE})
        return await run_tool(ctx, "clear_category_override", handler, write=True)

    add(override_category, "override_category",
        "Pin ONE photo's category (e.g. a portrait the filters called street). The valid names are the config "
        "categories: see the `facet://categories` resource or filter_options(kind='categories'); an unknown name "
        "comes back as invalid_input. Scoring-context overrides are not touched.")
    add(clear_category_override, "clear_category_override",
        "Remove ONE photo's manual category and let the filters decide again; the aggregate is recomputed. "
        "A photo with no override answers `already: true`.")

    async def group_compare(
        ctx: Context, paths: Annotated[list[str], Field(min_length=1)],
        by: Literal["faces", "subjects"], profile: Optional[str] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            named = list(dict.fromkeys(paths))
            if len(named) > GROUP_COMPARE_CAP:
                return err("too_large", f"{len(named)} paths exceeds the cap of {GROUP_COMPARE_CAP} for this tool; "
                           "compare one culling group at a time")
            timeout = settings["call_timeout_s"]
            failure, visible = await photo_io.read_photos(client, grant, named, timeout)
            if failure is not None:
                return failure
            missing = [p for p in named if p not in visible]
            known = [p for p in named if p in visible]
            if not known:
                return ok({"by": by, "rows": [], "missing_paths": missing})
            if by == "faces":
                upstream = await client.call(grant, "group_faces", json={"paths": known, "profile": profile},
                                             timeout=timeout)
                if not upstream["ok"]:
                    return upstream
                body = upstream["data"] or {}
                rows = {p: _faces_of((body.get("faces_by_path") or {}).get(p) or []) for p in known}
                scored = {p: r["worst_eyes_open"] for p, r in rows.items() if r["worst_eyes_open"] is not None}
                best = None
                for p in sorted(scored):
                    if best is None or scored[p] > scored[best]:
                        best = p
                return ok({"by": by, "rows": [{"path": p, **rows[p]} for p in known],
                           "thresholds": body.get("thresholds"), "best_path_by_eyes": best,
                           "missing_paths": missing,
                           "note": "best_path_by_eyes is advice (the frame whose worst-eyed face is most open)"})
            upstream = await client.call(grant, "group_subjects", json={"paths": known}, timeout=timeout)
            if not upstream["ok"]:
                return upstream
            subjects = (upstream["data"] or {}).get("subjects_by_path") or {}
            rows = [{"path": p, "has_subject": bool((subjects.get(p) or {}).get("has_subject")),
                     "subject_sharpness": _round((subjects.get(p) or {}).get("subject_sharpness")),
                     "subject_prominence": _round((subjects.get(p) or {}).get("subject_prominence")),
                     "crop_sharpness_score": _round((subjects.get(p) or {}).get("crop_sharpness_score"))}
                    for p in known]
            scored_rows = [r for r in sorted(rows, key=lambda r: r["path"]) if r["crop_sharpness_score"] is not None]
            sharpest = None
            for r in scored_rows:
                if sharpest is None or r["crop_sharpness_score"] > sharpest["crop_sharpness_score"]:
                    sharpest = r
            return ok({"by": by, "rows": rows, "sharpest_path": sharpest["path"] if sharpest else None,
                       "missing_paths": missing})
        return await run_tool(ctx, "group_compare", handler)

    add(group_compare, "group_compare",
        f"Compare the frames of ONE culling group (<={GROUP_COMPARE_CAP} paths) where the score is not enough. "
        "`by: \"faces\"` lists per path the face count, blinks, worst eyes-open, best smile and up to "
        f"{FACE_ITEMS_CAP} faces, plus `best_path_by_eyes`; `by: \"subjects\"` gives subject sharpness, prominence "
        "and `sharpest_path` (no images). Both are advice for the user, not a decision. Paths the viewer cannot "
        "show are in `missing_paths`.", read_only=True)
