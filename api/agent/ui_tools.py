"""The canonical UI-tool contract: what an agent may ask the user's open tab to do.

Declared ONCE, here. The server validates every call against these models before a
frame reaches a tab (a bad call never leaves the server), registers them as MCP
tools (``tools_ui``) and emits them as the JSON the Angular client consumes
(``scripts/dump_ui_tools.py`` -> ``client/src/app/core/agent/ui-tools.schema.json``).

Nothing here writes library data: every tool changes what the tab SHOWS or which
photos it has selected. That is why they are all ``readonly`` grants; whatever a
follow-up action needs (rating, rejecting) goes through the data tools and their
own levels.

The tool set is static: the stateless transport has no channel to push
``tools/list_changed``. A tab that predates a tool answers ``tab_outdated``.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from api.agent.tools_common import MCP_FILTER_KEYS, FilterValue, SortColumn

TAB_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
MAX_SELECT_PATHS = 1000
MAX_QUERY_ENTRIES = 20
# Codes a tab may report; anything else becomes upstream_error. `no_active_view` is the
# darkroom action registry's "that view is not mounted". Emitted into the client JSON
# so the client's own list is checked against it.
TAB_ERROR_CODES = frozenset({
    "invalid_input", "not_found", "forbidden_level", "no_active_view", "upstream_error", "too_large",
})

UiRoute = Literal[
    "/", "/persons", "/merge-suggestions", "/compare", "/culling", "/scenes", "/junk",
    "/stats", "/albums", "/capsules", "/folders", "/timeline", "/map",
]
CullingGroupType = Literal["burst", "similar", "scene", "bracket", "panorama", "hdr_panorama"]


class UiArgs(BaseModel):
    """Base of every UI-tool input: no unknown keys, optional routing to one tab."""

    model_config = ConfigDict(extra="forbid")

    tab_id: Optional[str] = Field(
        default=None, pattern=TAB_ID_PATTERN,
        description="Target a specific tab (ids are listed by `status`). Default: the most "
                    "recently focused tab of this user.")

    def forward(self) -> dict:
        """The arguments the TAB receives: no routing keys, no unset optionals."""
        return self.model_dump(mode="json", exclude={"tab_id"}, exclude_none=True)


# Keys the open tab's filter sidebar has no field for (checked against `GalleryFilters`):
# offering them would only earn the agent an `invalid_input`; `search_photos` covers them.
TAB_UNSUPPORTED_FILTER_KEYS = frozenset({
    "exclude_tags", "require_tags", "is_silhouette", "junk_kind", "narrative_moment",
    "min_rating", "min_aggregate", "show_rejected",
})
_PATCH_FIELDS: dict[str, Any] = {
    key: (Optional[FilterValue], Field(default=None, description=f"Gallery filter `{key}`."))
    for key in MCP_FILTER_KEYS
    if key not in TAB_UNSUPPORTED_FILTER_KEYS
}
_PATCH_FIELDS["sort"] = (Optional[SortColumn], Field(default=None, description="Sort column."))
_PATCH_FIELDS["sort_direction"] = (
    Optional[Literal["asc", "desc"]], Field(default=None, description="Sort direction."))
# Semantic and similar views. Bounds are checked by the validator below, not by Field
# constraints: a constraint would turn the nullable scalar into an `anyOf` the client's
# hand-written schema checker does not read.
SEMANTIC_THRESHOLD_MAX = 0.5
_PATCH_FIELDS["semantic_query"] = (Optional[str], Field(
    default=None, description="Show the gallery as a semantic (text-to-image) search for this text."))
_PATCH_FIELDS["semantic_threshold"] = (Optional[float], Field(
    default=None, description="Semantic match threshold, 0 to 0.5 (null: the server default)."))
_PATCH_FIELDS["similar_to"] = (Optional[str], Field(
    default=None, description="Show the photos similar to the photo at this path. "
                              "Cannot be combined with `semantic_query`."))
_PATCH_FIELDS["similarity_mode"] = (Optional[Literal["visual", "color", "person"]], Field(
    default=None, description="How `similar_to` compares photos."))
_PATCH_FIELDS["min_similarity"] = (Optional[float], Field(
    default=None, description="Minimum similarity for `similar_to`, 0 to 1 (null: the tab default)."))


class _PatchBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check_patch(self) -> "_PatchBase":
        threshold = getattr(self, "semantic_threshold", None)
        similarity = getattr(self, "min_similarity", None)
        if threshold is not None and not 0 <= threshold <= SEMANTIC_THRESHOLD_MAX:
            raise ValueError(f"semantic_threshold must be between 0 and {SEMANTIC_THRESHOLD_MAX}")
        if similarity is not None and not 0 <= similarity <= 1:
            raise ValueError("min_similarity must be between 0 and 1")
        if getattr(self, "semantic_query", None) and getattr(self, "similar_to", None):
            raise ValueError("`semantic_query` and `similar_to` cannot be combined")
        return self


UiFilterPatch = create_model("UiFilterPatch", __base__=_PatchBase, **_PATCH_FIELDS)

QueryValue = Union[str, int, float, bool]


class UiNavigate(UiArgs):
    route: UiRoute = Field(description="Where to go. Edition-only pages (/culling, /junk, /compare, "
                                       "/merge-suggestions) are refused by the tab for other users.")
    query: Optional[dict[str, QueryValue]] = Field(
        default=None, description="Query-string parameters for the route.")

    @field_validator("query")
    @classmethod
    def _small_query(cls, value: Optional[dict]) -> Optional[dict]:
        if value is not None and len(value) > MAX_QUERY_ENTRIES:
            raise ValueError(f"at most {MAX_QUERY_ENTRIES} query parameters")
        return value


class UiSetGalleryFilters(UiArgs):
    patch: BaseModel = Field(
        description="Filters to change, keyed like the `search_photos` filters plus `sort` and "
                    "`sort_direction`. A key set to null removes that filter. Filters the gallery "
                    "sidebar has no field for (tag include/exclude lists, rating, aggregate, "
                    "silhouette, junk, moment, rejected) are not offered: use `search_photos`.")
    replace: bool = Field(default=False, description="true: reset every other filter first.")

    def forward(self) -> dict:
        return {"patch": self.patch.model_dump(mode="json", exclude_unset=True), "replace": self.replace}


# `UiFilterPatch` is built at import time, so it cannot be named in an annotation.
UiSetGalleryFilters.model_fields["patch"].annotation = UiFilterPatch
UiSetGalleryFilters.model_rebuild(force=True)


class UiGetGalleryView(UiArgs):
    limit: int = Field(default=50, ge=1, le=200, description="Most visible photo paths to return.")


class UiOpenPhoto(UiArgs):
    path: str = Field(min_length=1, max_length=4096, description="Path of the photo to open.")


class UiSelectPhotos(UiArgs):
    paths: Optional[list[str]] = Field(
        default=None, max_length=MAX_SELECT_PATHS,
        description="Photo paths to select. Exactly one of `paths` and `select_view`.")
    select_view: bool = Field(
        default=False,
        description="true: select the WHOLE filtered view (not just the loaded rows), "
                    "scope 'view'. Only with mode replace or add.")
    mode: Literal["replace", "add", "remove"] = Field(default="replace")

    @field_validator("paths")
    @classmethod
    def _clean_paths(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is not None and any(not p or len(p) > 4096 for p in value):
            raise ValueError("every path must be 1..4096 characters")
        return value

    @model_validator(mode="after")
    def _one_target(self) -> "UiSelectPhotos":
        if bool(self.paths) == self.select_view:
            raise ValueError("give exactly one of a non-empty `paths` and `select_view: true`")
        if self.select_view and self.mode == "remove":
            raise ValueError("`select_view` cannot be combined with mode 'remove'; use ui_clear_selection")
        return self


class UiClearSelection(UiArgs):
    pass


class UiGetSelection(UiArgs):
    pass


class UiNextPage(UiArgs):
    pass


class UiShowCullingGroup(UiArgs):
    type: CullingGroupType = Field(description="Group kind; a group's identity is (type, group_id).")
    group_id: int = Field(ge=0, description="The `group_id` from list_culling_groups.")


@dataclass(frozen=True)
class UiTool:
    name: str
    description: str
    model: type[UiArgs]
    read_only: bool
    returns_library_text: bool = True


UI_TOOLS: tuple[UiTool, ...] = (
    UiTool("ui_navigate",
           "Move the user's open Facet tab to another page (gallery, persons, albums, stats, ...).",
           UiNavigate, False),
    UiTool("ui_set_gallery_filters",
           "Change the gallery filters and sort in the user's open tab. `patch` merges into the "
           "current filters (null removes one); `replace: true` starts from none.",
           UiSetGalleryFilters, False),
    UiTool("ui_get_gallery_view",
           "What the user's tab shows now: route, active filters, total matches, the first visible "
           "photo paths and the selection count.",
           UiGetGalleryView, True),
    UiTool("ui_open_photo", "Open one photo in the user's tab (the detail view).", UiOpenPhoto, False),
    UiTool("ui_select_photos",
           "Change the selection in the user's tab: explicit `paths`, or the whole filtered view "
           "(`select_view`). Selecting does not modify any photo.",
           UiSelectPhotos, False),
    UiTool("ui_clear_selection", "Clear the selection in the user's tab.", UiClearSelection, False),
    UiTool("ui_get_selection",
           "The user's current selection: `scope` 'paths' (explicit `paths`) or 'view' (the whole "
           "filtered view: `filters`, minus `excluded_paths`), and `count`.",
           UiGetSelection, True),
    UiTool("ui_next_page", "Load the next page of the gallery in the user's tab (infinite scroll).",
           UiNextPage, False),
    UiTool("ui_show_culling_group",
           "Open the darkroom (/culling) and focus one group, identified by (type, group_id). "
           "Edition accounts only.",
           UiShowCullingGroup, False),
)


def _simplify(node: Any, defs: dict, keep_null: bool = False) -> Any:
    """Plain JSON Schema for a hand-written client checker: inline refs, no titles, flat types.

    ``anyOf`` of scalars becomes a ``type`` array; an ``Optional`` loses its ``null``
    branch (absence already means "not given") except inside the filter patch, where
    null means "remove this filter".
    """
    if isinstance(node, list):
        return [_simplify(item, defs, keep_null) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return _simplify(defs[name], defs, keep_null or name == "UiFilterPatch")
    if "anyOf" in node:
        branches = [b for b in node["anyOf"] if keep_null or b.get("type") != "null"]
        rest = {k: v for k, v in node.items() if k != "anyOf"}
        nullable = [b for b in branches if b.get("type") == "null"]
        others = [b for b in branches if b.get("type") != "null"]
        if nullable and len(others) == 1 and "enum" in others[0]:
            merged = {**others[0], "type": [others[0]["type"], "null"],
                      "enum": [*others[0]["enum"], None]}
            return _simplify({**rest, **merged}, defs, keep_null)
        if len(branches) == 1:
            return _simplify({**rest, **branches[0]}, defs, keep_null)
        if all(set(b) == {"type"} for b in branches):
            return _simplify({**rest, "type": [b["type"] for b in branches]}, defs, keep_null)
        return {**_simplify(rest, defs, keep_null),
                "anyOf": [_simplify(b, defs, keep_null) for b in branches]}
    out = {}
    for key, value in node.items():
        dropped = key == "$defs" or (key == "title" and isinstance(value, str))
        if dropped or (key == "default" and value is None):
            continue
        if key == "properties":
            out[key] = {name: _simplify(prop, defs, keep_null) for name, prop in value.items()}
        else:
            out[key] = _simplify(value, defs, keep_null)
    return out


def input_schema(tool: UiTool) -> dict:
    """The tool's input schema as the TAB sees it (no server-side ``tab_id``)."""
    raw = tool.model.model_json_schema()
    schema = _simplify(raw, raw.get("$defs", {}))
    schema["properties"] = {k: v for k, v in schema.get("properties", {}).items() if k != "tab_id"}
    schema.setdefault("required", [])
    schema["required"] = [k for k in schema["required"] if k != "tab_id"]
    if not schema["required"]:
        del schema["required"]
    return schema


def annotations(tool: UiTool) -> dict:
    return {
        "readOnlyHint": tool.read_only,
        "destructiveHint": False,
        "idempotentHint": tool.read_only,
        "untrustedContentHint": tool.returns_library_text,
    }


def tool_descriptors() -> list[dict]:
    return [{"name": t.name, "description": t.description, "inputSchema": input_schema(t),
             "annotations": annotations(t)} for t in UI_TOOLS]


_version_memo: tuple[Any, str] = (None, "")


def tools_version() -> str:
    """Digest of the whole contract. A tab announcing another value is ``tab_outdated``.

    The contract is static for the process, but building its schemas costs ~12 ms of
    pydantic work and this runs per tab on the event loop, so the digest is memoised
    against the identity of ``UI_TOOLS`` (a test that swaps the tuple still sees a new value).
    """
    global _version_memo
    tools, version = _version_memo
    if tools is not UI_TOOLS:
        blob = json.dumps(tool_descriptors(), sort_keys=True, separators=(",", ":"))
        version = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        _version_memo = (UI_TOOLS, version)
    return version


def render_client_json() -> str:
    """The committed ``ui-tools.schema.json``: ``{version, tools: [...], error_codes: [...]}``."""
    return json.dumps({"version": tools_version(), "tools": tool_descriptors(),
                       "error_codes": sorted(TAB_ERROR_CODES)},
                      indent=2, sort_keys=True, ensure_ascii=False) + "\n"
