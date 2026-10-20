"""``target: "selection"``: act on what the user has selected in their open Facet tab.

The tab is untrusted input, so nothing it reports is used unchecked:

* an explicit selection must be complete (``truncated`` is refused) and its ``count`` must
  equal the number of paths it sent;
* a whole-view selection travels as the gallery's filter payload. Its keys must be gallery
  filter keys (:func:`api.models.gallery.gallery_filter_keys`), its values scalars; the
  paging and ordering keys are dropped; the viewer's hide defaults are NEVER added (the
  payload already carries the tab's effective toggles); the view cannot be a similar /
  semantic / assistant-pinned view (the tab reports ``filters: null`` for those);
* the server recounts the view and requires it to equal the tab's count plus its excluded
  paths EXACTLY, so a view that changed since the tab last counted writes nothing.
"""

from dataclasses import dataclass
from typing import Any, Optional

from api.agent import show as relay
from api.agent.bridge import TabRegistry
from api.agent.internal_client import InternalClient, err
from api.agent.tokens import ResolvedGrant
from api.models.gallery import GALLERY_PAGING_KEYS, gallery_filter_keys

SELECTION = "selection"
SELECTION_RULE = (
    'Or pass `target: "selection"` (and optionally `tab_id`) to act on exactly what the user has '
    "selected in their open Facet tab, instead of `paths` / `filters`. Exactly one of the three. "
    "A whole-view selection is re-counted on the server and refused (`invalid_input`) if the view "
    "changed since the tab counted it.")
FRAME_LIMIT_NOTE = "the bridge frame limit is 256 KB"
_SCALAR = (str, int, float, bool)


@dataclass(frozen=True)
class TabSelection:
    scope: str
    count: int
    tab_id: Optional[str]
    paths: tuple[str, ...] = ()
    filters: Optional[dict[str, str]] = None
    excluded: tuple[str, ...] = ()
    excluded_count: int = 0

    def describe(self) -> dict:
        return {"source": "tab_selection", "tab_id": self.tab_id, "scope": self.scope, "count": self.count}


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def view_filters(raw: Any) -> tuple[Optional[dict], dict[str, str]]:
    """``(error, filters)``: the tab's view payload, whitelisted and stringified."""
    if raw is None:
        return err("invalid_input", "The tab's current view (similar photos, a semantic search or a list "
                   "chosen by an assistant) cannot be targeted as a whole; select the photos by path instead"), {}
    if not isinstance(raw, dict):
        return err("invalid_input", "The tab reported its view filters in an unusable form"), {}
    allowed = gallery_filter_keys()
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        return err("invalid_input", f"The tab's view carries filters this server does not know: "
                   f"{', '.join(unknown[:10])}"), {}
    if any(not isinstance(value, _SCALAR) for value in raw.values()):
        return err("invalid_input", "The tab's view filters must be plain values"), {}
    return None, {key: _stringify(value) for key, value in raw.items() if key not in GALLERY_PAGING_KEYS}


async def read_selection(registry: TabRegistry, resolved: ResolvedGrant, settings: dict,
                         tab_id: Optional[str]) -> tuple[Optional[dict], Optional[TabSelection]]:
    """``(error, selection)`` from the tab's own ``ui_get_selection``."""
    envelope = await relay.call_tab(registry, resolved, settings, "ui_get_selection", {}, tab_id)
    if not envelope.get("ok"):
        code = str(envelope.get("error") or "upstream_error")
        if code == "too_large":
            return err("too_large", f"The tab's selection is too large to read ({FRAME_LIMIT_NOTE}); "
                       "select fewer photos or use `filters`"), None
        return err(code, str(envelope.get("message") or "The tab could not report its selection")), None
    data = envelope.get("data")
    if not isinstance(data, dict):
        return err("upstream_error", "The tab reported its selection in an unusable form"), None
    if envelope.get("truncated"):
        return err("too_large", "The tab's reply was cut by the bridge's string limit, so its selection "
                   "cannot be read in full; select fewer photos or use `filters`"), None
    seen_tab = (envelope.get("tab") or {}).get("tab_id")
    count = data.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return err("upstream_error", "The tab reported an unusable selection count"), None
    if data.get("scope") == "paths":
        paths = data.get("paths")
        if data.get("truncated"):
            return err("too_large", "The tab's selection is too large to read in full; select fewer "
                       "photos or use `filters`"), None
        if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths) or len(paths) != count:
            return err("invalid_input", "The tab's selection changed while it was read; nothing was done"), None
        return None, TabSelection("paths", count, seen_tab, paths=tuple(paths))
    if data.get("scope") != "view":
        return err("upstream_error", "The tab reported an unknown selection scope"), None
    refusal, filters = view_filters(data.get("filters"))
    if refusal is not None:
        return refusal, None
    excluded = data.get("excluded_paths") or []
    excluded_count = data.get("excluded_count", len(excluded))
    if (data.get("excluded_truncated") or not isinstance(excluded, list)
            or not isinstance(excluded_count, int) or excluded_count != len(excluded)):
        return err("too_large", "The tab excludes too many photos from its whole-view selection to read "
                   "them all; narrow the view or select by path"), None
    return None, TabSelection("view", count, seen_tab, filters=filters, excluded=tuple(excluded),
                              excluded_count=excluded_count)


def _changed() -> dict:
    return err("invalid_input", "selection_changed: the view holds a different number of photos than the "
               "tab's selection says; nothing was done. Re-read the selection and retry")


async def resolve_selection(
    client: InternalClient, grant: Any, registry: TabRegistry, resolved: ResolvedGrant, settings: dict, *,
    tab_id: Optional[str], path_cap: int, paths_key: str, need_paths: bool,
) -> tuple[Optional[dict], dict, Optional[dict]]:
    """``(error, route_body, target_meta)`` for the tab's selection.

    A route that takes a filter set (``need_paths`` false) gets the whole view as
    ``filters`` + ``exclude``; one that only takes a path list gets the view expanded
    through ``/api/photos/paths`` minus the exclusions, under ``path_cap``.
    """
    refusal, selection = await read_selection(registry, resolved, settings, tab_id)
    if refusal is not None or selection is None:
        return refusal, {}, None
    timeout = settings["call_timeout_s"]
    meta = selection.describe()
    if selection.scope == "paths":
        if not selection.paths:
            return err("invalid_input", "Nothing is selected in the tab"), {}, None
        if len(selection.paths) > path_cap:
            return err("too_large", f"{len(selection.paths)} selected paths exceeds the cap of {path_cap} "
                       "for this tool; select fewer photos"), {}, None
        return None, {paths_key: list(selection.paths)}, meta
    if selection.count == 0:
        return err("invalid_input", "Nothing is selected in the tab"), {}, None
    scope = selection.filters or {}
    if need_paths:
        listed = await client.call(grant, "photos_paths", query=scope, timeout=timeout)
        if not listed["ok"]:
            return listed, {}, None
        body = listed["data"] or {}
        every = body.get("paths") or []
        if body.get("total", len(every)) != selection.count + selection.excluded_count:
            return _changed(), {}, None
        gone = set(selection.excluded)
        paths = [p for p in every if p not in gone]
        if len(paths) != selection.count:
            return _changed(), {}, None
        if len(paths) > path_cap:
            return err("too_large", f"{len(paths)} selected photos exceeds the cap of {path_cap} for this "
                       "tool; narrow the selection"), {}, None
        return None, {paths_key: paths}, meta
    counted = await client.call(grant, "photos_count", query=scope, timeout=timeout)
    if not counted["ok"]:
        return counted, {}, None
    if (counted["data"] or {}).get("total") != selection.count + selection.excluded_count:
        return _changed(), {}, None
    body = {"filters": scope}
    if selection.excluded:
        body["exclude"] = list(selection.excluded)
    return None, body, meta
