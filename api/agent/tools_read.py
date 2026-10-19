"""Read tools: search, detail, similarity, filter vocabularies, people, albums, stats.

Every tool reaches data through ``InternalClient`` (the existing ``/api`` routes),
declares ``readOnlyHint`` and carries the untrusted-content meta (captions, tags,
file names, paths and album/person names can all hold a prompt injection).
"""

from typing import Annotated, Any, Literal, Optional, Union

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field, create_model

from api.agent.internal_client import InternalClient, err, ok
from api.agent.runtime import run_tool
from api.agent.tools_common import READ_ANNOTATIONS, register_tool
from api.config import VIEWER_CONFIG
from api.models.gallery import GalleryParams

_METRIC_STEMS = (
    "score", "aggregate", "aesthetic", "sharpness", "exposure", "face_count", "face_ratio",
    "face_quality", "eye_sharpness", "face_sharpness", "face_confidence", "iso", "aperture",
    "focal_length", "composition", "color", "saturation", "noise", "contrast", "dynamic_range",
    "luminance", "isolation", "star_rating", "topiq", "liqe", "subject_sharpness",
    "subject_prominence", "bg_separation", "aesthetic_iaa", "face_quality_iqa",
)
_PLAIN_KEYS = (
    "camera", "lens", "type", "tag", "person", "search", "category", "narrative_moment",
    "junk_kind", "composition_pattern", "album_id", "path_prefix", "date_from", "date_to",
    "gps_lat", "gps_lng", "gps_radius_km", "hide_blinks", "hide_bursts", "hide_duplicates",
    "hide_brackets", "hide_panoramas", "is_monochrome", "is_silhouette", "favorites_only",
    "hide_rejected", "show_rejected", "min_rating", "require_tags", "exclude_tags",
    "color_temp", "quality_tier",
)
# min_/max_ for every stem GalleryParams knows; a stem it does not know is dropped
# here and caught by the subset test, not silently ignored by the route.
MCP_FILTER_KEYS = tuple(dict.fromkeys(
    _PLAIN_KEYS
    + tuple(f"{bound}_{stem}" for stem in _METRIC_STEMS for bound in ("min", "max")
            if f"{bound}_{stem}" in GalleryParams.model_fields)
))
HIDE_DEFAULT_KEYS = ("hide_blinks", "hide_bursts", "hide_duplicates", "hide_brackets", "hide_panoramas")

FilterValue = Union[str, int, float, bool]
_FILTER_FIELDS: dict[str, Any] = {
    key: (Optional[FilterValue], Field(
        default=None, description=f"Gallery filter `{key}` (same meaning as in the viewer)."))
    for key in MCP_FILTER_KEYS
}
# The route reads only show_rejected == "1" (rejected photos ONLY); anything else is
# silently the normal listing, so the key is a boolean rather than a free value.
_FILTER_FIELDS["show_rejected"] = (Optional[bool], Field(
    default=None, description="true lists ONLY the rejected photos; false or omitted is the "
    "normal listing. Other values are refused."))
SearchFilters = create_model("SearchFilters", __config__=ConfigDict(extra="forbid"), **_FILTER_FIELDS)

MetricField = Literal[
    "tech_sharpness", "exposure_score", "color_score", "contrast_score", "dynamic_range_stops",
    "noise_sigma", "isolation_bonus", "quality_score", "topiq_score", "aesthetic_iaa",
    "liqe_score", "face_quality_iqa", "eye_sharpness", "face_sharpness", "face_ratio",
    "face_confidence", "subject_sharpness", "subject_prominence", "bg_separation",
    "mean_saturation", "mean_luminance", "iso", "f_stop", "focal_length", "learned_score",
]
SortColumn = Literal[
    "aggregate", "aesthetic", "date_taken", "comp_score", "face_quality", "tech_sharpness",
    "exposure_score", "color_score", "contrast_score", "topiq_score", "quality_score",
    "top_picks_score", "learned_score", "star_rating", "filename",
]
FilterKind = Literal["cameras", "lenses", "tags", "persons", "patterns", "categories",
                     "narrative_moments", "junk_kinds", "metric_ranges"]

COMPACT_KEYS = ("path", "filename", "date_taken", "aggregate", "aesthetic", "comp_score",
                "face_quality", "category", "face_count", "is_favorite", "star_rating",
                "is_rejected", "sequence_kind")
CAPTION_LIMIT = 240
TAG_LIMIT = 5
FILTER_OPTION_LIMIT = 200


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def compact_photo(photo: dict, extra_fields: tuple = ()) -> dict:
    """A fixed, small key set -- never the raw ``/api/photos`` row."""
    row = {key: photo.get(key) for key in COMPACT_KEYS}
    tags = photo.get("tags_list")
    if tags is None:
        raw = photo.get("tags")
        tags = [t.strip() for t in raw.split(",")] if isinstance(raw, str) and raw else []
    row["tags"] = list(tags)[:TAG_LIMIT]
    caption = photo.get("caption")
    row["caption"] = caption[:CAPTION_LIMIT] if isinstance(caption, str) else caption
    for field in extra_fields:
        row[field] = photo.get(field)
    return row


def _list_result(upstream: dict, extra_fields: tuple = ()) -> dict:
    """Reshape a ``{photos, total, ...}`` route body into ``{rows, ...}``."""
    if not upstream["ok"]:
        return upstream
    body = upstream["data"] or {}
    data = {
        "rows": [compact_photo(p, extra_fields) for p in body.get("photos", [])],
        "total": body.get("total", 0),
    }
    for key in ("page", "per_page", "has_more", "hidden_summary", "query"):
        if key in body:
            data[key] = body[key]
    if body.get("error"):
        return err("upstream_error", str(body["error"]))
    return ok(data)


def _hide_defaults(filters: dict) -> dict:
    """Start from what the viewer shows: ``viewer.defaults.hide_*`` unless the caller set it."""
    defaults = VIEWER_CONFIG.get("defaults", {}) or {}
    merged = dict(filters)
    for key in HIDE_DEFAULT_KEYS:
        if key not in merged and defaults.get(key):
            merged[key] = True
    return merged


def register_read_tools(server: MCPServer, client: InternalClient, status_extra) -> None:
    """Register the read tools on ``server``. ``status_extra`` supplies status-only fields."""

    def add(fn, name: str, description: str) -> None:
        register_tool(server, fn, name, description, READ_ANNOTATIONS)

    async def search_photos(
        ctx: Context,
        filters: Optional[BaseModel] = None,
        sort: Optional[SortColumn] = None,
        sort_direction: Optional[Literal["asc", "desc"]] = None,
        page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=100)] = 50,
        fields: Optional[list[MetricField]] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            merged = _hide_defaults(
                filters.model_dump(exclude_none=True) if filters is not None else {})
            query = {key: _query_value(value) for key, value in merged.items()}
            query.update(page=page, per_page=per_page)
            if sort:
                query["sort"] = sort
            if sort_direction:
                query["sort_direction"] = sort_direction.upper()
            upstream = await client.call(grant, "search_photos", query=query,
                                         timeout=settings["call_timeout_s"])
            return _list_result(upstream, tuple(fields or ()))
        return await run_tool(ctx, "search_photos", handler)

    search_photos.__annotations__["filters"] = Optional[SearchFilters]

    async def semantic_search(
        ctx: Context,
        query: Annotated[str, Field(min_length=1, max_length=500)],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        threshold: Annotated[Optional[float], Field(ge=0.0, le=1.0)] = None,
        scope: Optional[Literal["text"]] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(
                grant, "semantic_search",
                query={"q": query, "limit": limit, "threshold": threshold, "scope": scope},
                timeout=settings["semantic_timeout_s"])
            return _list_result(upstream)
        return await run_tool(ctx, "semantic_search", handler)

    async def get_photo(ctx: Context, path: Annotated[str, Field(min_length=1)]) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "get_photo", query={"path": path},
                                         timeout=settings["call_timeout_s"])
            if upstream["ok"] and isinstance(upstream["data"], dict):
                upstream["data"].pop("histogram_data", None)
            return upstream
        return await run_tool(ctx, "get_photo", handler)

    async def similar_photos(
        ctx: Context,
        path: Annotated[str, Field(min_length=1)],
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
        mode: Literal["visual", "color"] = "visual",
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(
                grant, "similar_photos", path_args={"path": path},
                query={"limit": limit, "offset": offset, "mode": mode}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            photos = body.get("similar") or []
            return ok({"rows": [compact_photo(p) | {"similarity": p.get("similarity")} for p in photos],
                       "total": body.get("total", len(photos)),
                       "has_more": bool(body.get("has_more"))})
        return await run_tool(ctx, "similar_photos", handler)

    async def filter_options(
        ctx: Context,
        kind: FilterKind,
        query: Annotated[Optional[str], Field(max_length=100)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, f"filter_options.{kind}",
                                         timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            data, truncated = _trim_options(upstream["data"], query)
            return ok(data, **({"truncated": True} if truncated else {}))
        return await run_tool(ctx, "filter_options", handler)

    async def list_persons(
        ctx: Context,
        query: Annotated[Optional[str], Field(max_length=100)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 48,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "list_persons", query={
                "search": query or "", "per_page": limit}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            rows = [{k: p.get(k) for k in ("id", "name", "face_count")}
                    for p in body.get("persons", [])]
            return ok({"rows": rows, "total": body.get("total", len(rows))})
        return await run_tool(ctx, "list_persons", handler)

    async def list_albums(
        ctx: Context, query: Annotated[Optional[str], Field(max_length=100)] = None,
    ) -> CallToolResult:
        async def handler(grant, resolved, settings):
            upstream = await client.call(grant, "list_albums", query={
                "search": query or "", "per_page": 100}, timeout=settings["call_timeout_s"])
            if not upstream["ok"]:
                return upstream
            body = upstream["data"] or {}
            rows = [{k: a.get(k) for k in ("id", "name", "description", "is_smart", "photo_count")}
                    for a in body.get("albums", [])]
            return ok({"rows": rows, "total": body.get("total", len(rows))})
        return await run_tool(ctx, "list_albums", handler)

    async def library_stats(ctx: Context) -> CallToolResult:
        async def handler(grant, resolved, settings):
            counts = await client.call(grant, "library_stats.type_counts",
                                       timeout=settings["call_timeout_s"])
            overview = await client.call(grant, "library_stats.overview",
                                         timeout=settings["call_timeout_s"])
            if not counts["ok"]:
                return counts
            if not overview["ok"]:
                return overview
            return ok({"type_counts": counts["data"], "overview": overview["data"]})
        return await run_tool(ctx, "library_stats", handler)

    async def status(ctx: Context) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return ok({
                "owner": resolved.principal,
                "level": resolved.level,
                "token_level": grant.level,
                "mcp": {"enabled": settings["enabled"], "bridge": settings["bridge"]},
                **status_extra(resolved),
            })
        return await run_tool(ctx, "status", handler)

    add(search_photos, "search_photos",
        "Search and filter the photo library like the viewer gallery. Applies the viewer's "
        "default hide toggles (bursts, duplicates, brackets, panoramas, blinks) unless the filter "
        "sets them, and reports `hidden_summary` so you can say how many more are hidden.")
    add(semantic_search, "semantic_search",
        "Find photos by meaning (text-to-image) or, with scope='text', by words in captions/OCR.")
    add(get_photo, "get_photo", "Full detail of one photo by its path.")
    add(similar_photos, "similar_photos", "Photos similar to one photo (visual or colour); pass `offset` to page when has_more is true.")
    add(filter_options, "filter_options",
        "List the vocabulary a filter accepts (cameras, lenses, tags, persons, patterns, "
        "categories, narrative_moments, junk_kinds, metric_ranges).")
    add(list_persons, "list_persons", "Recognised people, optionally filtered by name.")
    add(list_albums, "list_albums", "Albums the token's owner can see.")
    add(library_stats, "library_stats", "Library size, type counts and score overview.")
    add(status, "status", "Who this token is, its effective level and the server flags.")


def _trim_options(data: Any, query: Optional[str]) -> tuple[Any, bool]:
    """Filter list values by ``query`` and cap each at 200; report whether any were cut."""
    needle = (query or "").lower()
    cut = False

    def trim(items: list) -> list:
        nonlocal cut
        kept = [item for item in items if not needle or needle in str(item).lower()]
        if len(kept) > FILTER_OPTION_LIMIT:
            cut = True
        return kept[:FILTER_OPTION_LIMIT]

    if isinstance(data, list):
        return trim(data), cut
    if isinstance(data, dict):
        return {key: trim(value) if isinstance(value, list) else value
                for key, value in data.items()}, cut
    return data, cut
