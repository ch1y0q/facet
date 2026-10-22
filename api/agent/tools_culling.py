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

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Sequence, cast

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from api.agent import limits, nonce
from api.agent import show as relay
from api.agent.bridge import TabRegistry
from api.agent.inpage import REVIEW_SCOPE_KEY
from api.agent.internal_client import InternalClient, RouteSpec, err, ok
from api.agent.live_updates import WriteSink
from api.agent.limits import encoded_size
from api.agent.runtime import run_tool
from api.agent.ui_tools import TAB_ID_PATTERN
from api.agent.tools_common import DESTRUCTIVE_ANNOTATIONS, READ_ANNOTATIONS, register_tool
from api.db_helpers import to_second_granularity

CULLING_ROUTES: dict[str, RouteSpec] = {
    "culling.groups": RouteSpec("GET", "/api/culling-groups", "edition"),
    "culling.profiles": RouteSpec("GET", "/api/culling/profiles", "edition"),
    "culling.suggest_profile": RouteSpec("GET", "/api/culling/suggest_profile", "edition"),
    "culling.keeper_hints": RouteSpec("POST", "/api/photos/keeper_hints", "edition"),
    "culling.auto": RouteSpec("POST", "/api/culling/auto", "edition", write=True),
    "culling.confirm": RouteSpec("POST", "/api/culling-groups/confirm", "edition", write=True),
}

# Every darkroom route is edition-gated upstream; the tools carry the same floor.
CULLING_LEVEL = "edition"

GroupType = Literal["burst", "similar", "scene", "bracket", "panorama", "hdr_panorama"]
KEEP_WHOLE_TYPES = ("bracket", "panorama", "hdr_panorama")
GROUP_PHOTO_LIMIT = 12
GROUP_PHOTO_KEYS = ("path", "filename", "date_taken", "aggregate", "aesthetic", "tech_sharpness",
                    "is_blink", "sequence_ev_offset", "keeper_prob")
SEE_GROUP = " Call ui_show_culling_group to show a group to the user."
SHOW_PIN_MAX = 200
AUTO_CULL_SHOW = (
    " A successful dry run with rows pins its current page in the user's open Facet tab (`show`, "
    "default true; never ask whether to show it): the user sees the photos numbered by group and "
    "flagged Keep or Remove, and can flip Keep/Remove on the cards. Their flips are read from the tab "
    "for you: OMIT keep_paths and remove_paths to use them (`overrides_from_tab` counts only the marks that "
    "change the plan, not ones restating it, and lists any in `dropped` that could not be honoured; "
    "`{skipped: truncated}` means the tab held too many to trust). Report `shown_in_tab` (applied, or the reason it was not, including `unpinned` when "
    "a page holds more than 200 photos). The apply never shows; show=false skips it. Photos the user already "
    "committed with the tab's Apply (`review.applied`; `overrides_from_tab.applied` counts them) are never "
    "re-decided: the apply leaves them out, and an Apply made after the preview makes it stale (preview again).")


SUMMARY_PATHS = 20
CONFIRM_WIDTH = 40
APPLY_KEYS = ("groups_processed", "kept", "rejected", "highlights_added", "dry_run",
              "skipped_user_changed", "skipped_user_changed_count", "skipped_user_changed_groups",
              "state_guard")
# The tab caps each review list here, so a list this long may have been cut and is not trusted.
TAB_REVIEW_CAP = 1000
SKIP_PATHS_MAX = 1000
MAX_REMEMBERED = 64


@dataclass(frozen=True)
class Marks:
    """The user's Keep/Remove marks as the tab reported them; ``truncated`` marks are never used.

    ``applied`` are the photos the user already committed with the tab's Apply (keep and remove together):
    decided, so never pending marks and never re-decided by an ``auto_cull`` apply. ``applied_truncated``
    says the tab cut that list, which is not trusted either.
    """
    keep: tuple = ()
    remove: tuple = ()
    truncated: bool = False
    applied: tuple = ()
    applied_truncated: bool = False

    @property
    def usable(self) -> bool:
        return not self.truncated and bool(self.keep or self.remove)

    @property
    def has_applied(self) -> bool:
        return bool(self.applied)


@dataclass(frozen=True)
class _Preview:
    digest: str
    marks: Marks
    expires: float


_previews: dict[tuple, _Preview] = {}
_page_marks: dict[tuple, tuple[Marks, float]] = {}


def reset_preview_memory() -> None:
    _previews.clear()
    _page_marks.clear()


def _remember(store: dict, key: tuple, value: Any) -> None:
    """Insert into ``store``, shedding expired entries first and then the oldest past ``MAX_REMEMBERED``."""
    current = limits.now()
    for stale in [k for k, v in store.items() if (v.expires if isinstance(v, _Preview) else v[1]) <= current]:
        del store[stale]
    store[key] = value
    while len(store) > MAX_REMEMBERED:
        del store[next(iter(store))]


def _recall(store: dict, key: tuple) -> Any:
    value = store.get(key)
    if value is None or (value.expires if isinstance(value, _Preview) else value[1]) <= limits.now():
        store.pop(key, None)
        return None
    return value


def marks_from_review(review: Any) -> Optional[Marks]:
    """``Marks`` of a tab's ``ui_get_context`` ``review`` (empty when it holds none), or None when it is absent."""
    if not isinstance(review, dict):
        return None
    lists = [[p for p in (review.get(side) or []) if isinstance(p, str)]
             if isinstance(review.get(side) or [], list) else [] for side in ("keep", "remove")]
    cut = bool(review.get("truncated")) or any(len(item) >= TAB_REVIEW_CAP for item in lists)
    block = review.get("applied")
    block = block if isinstance(block, dict) else {}
    done = [[p for p in (block.get(side) or []) if isinstance(p, str)]
            if isinstance(block.get(side) or [], list) else [] for side in ("keep", "remove")]
    applied_cut = bool(block.get("truncated")) or any(len(item) >= TAB_REVIEW_CAP for item in done)
    return Marks(tuple(lists[0]), tuple(lists[1]), cut, tuple(dict.fromkeys(done[0] + done[1])), applied_cut)


def flips_since(before: Marks, now: Optional[Marks]) -> list[str]:
    """Paths whose Keep/Remove mark differs between ``before`` and ``now`` (unknown ``now`` flips nothing)."""
    if now is None or now.truncated:
        return []
    old, new = (before.keep, before.remove), (now.keep, now.remove)
    return sorted({p for a, b in zip(old, new) for p in set(a) ^ set(b)})
# Room kept for what the tool adds after the page is fitted (`shown_in_tab`).
SHOWN_RESERVE = 4096


def _fit_page(data: dict, extra: dict, settings: dict) -> None:
    """Drop whole rows from the end of ``data['rows']`` until the envelope fits the runtime caps.

    The tool owns the page budget: ``fit_envelope`` would otherwise cut rows while the route's
    ``next_cursor`` still points past them. Rows dropped here move ``next_cursor`` back to the last
    returned row's ``number`` (the next group's 0-based plan index). At least one row stays; if that
    one row alone is still over budget its path lists are clipped (``keep_count`` / ``reject_count``
    carry the full sizes, ``paths_clipped`` is true) so the group is never silently dropped.
    """
    rows = data["rows"]
    budget = max(settings["max_bytes"] - SHOWN_RESERVE, settings["max_bytes"] // 2)
    shown = len(rows)
    while shown > 1 and (shown > settings["max_rows"]
                         or encoded_size(ok({**data, "rows": rows[:shown]}, **extra)) > budget):
        shown -= 1
    if shown < len(rows):
        data["rows"] = rows[:shown]
        data["next_cursor"] = rows[shown - 1]["number"]
    if shown == 1 and encoded_size(ok(data, **extra)) > budget:
        _clip_row(data, extra, budget)


def _clip_row(data: dict, extra: dict, budget: int) -> None:
    """Clip the only row's path lists to the longest prefix that fits ``budget``."""
    row = dict(data["rows"][0])
    keep, reject = row.get("keep_paths") or [], row.get("reject_paths") or []
    row.update(keep_count=len(keep), reject_count=len(reject), paths_clipped=True)
    reasons = row.get("reasons") or {}

    def fits(n: int) -> bool:
        trial = {**row, "keep_paths": keep[:n], "reject_paths": reject[:n],
                 "reasons": {p: reasons[p] for p in reject[:n] if p in reasons}}
        return encoded_size(ok({**data, "rows": [trial]}, **extra)) <= budget

    low, high = 0, max(len(keep), len(reject))
    while low < high:
        mid = (low + high + 1) // 2
        low, high = (mid, high) if fits(mid) else (low, mid - 1)
    row.update(keep_paths=keep[:low], reject_paths=reject[:low],
               reasons={p: reasons[p] for p in reject[:low] if p in reasons})
    data["rows"] = [row]


@dataclass(frozen=True)
class PinnedPage:
    """The parallel arrays ``ui_show_photos`` takes, all aligned with ``paths``."""
    paths: list[str]
    groups: list[int]
    marks: list[str]
    labels: list[dict]
    reasons: list[dict]
    kinds: list[str]
    unpinned: int


def _pinned_page(rows: list[dict]) -> PinnedPage:
    """A page of plan rows as a pin, capped at ``SHOW_PIN_MAX``.

    Plan order; past the cap the keepers come first so every keeper is pinned before any removal. A keeper's
    reason is ``best``; a removal's is the row's ``{key, value}`` (``near_duplicate`` when the row has none).
    """
    cards = []
    for row in rows:
        count = (row.get("keep_count") or 0) + (row.get("reject_count") or 0) or (
            len(row.get("keep_paths") or []) + len(row.get("reject_paths") or []))
        label = row.get("group_reason") or {"key": "photo_count", "params": {"n": count}}
        reasons = row.get("reasons") or {}
        for paths, mark in ((row.get("keep_paths") or [], "keep"), (row.get("reject_paths") or [], "remove")):
            for path in paths:
                reason = {"key": "best"} if mark == "keep" else reasons.get(path) or {"key": "near_duplicate"}
                cards.append((path, row["number"], mark, label, reason, row.get("kind") or "burst"))
    unpinned = max(0, len(cards) - SHOW_PIN_MAX)
    if unpinned:
        cards = ([c for c in cards if c[2] == "keep"] + [c for c in cards if c[2] == "remove"])[:SHOW_PIN_MAX]
    return PinnedPage([c[0] for c in cards], [c[1] for c in cards], [c[2] for c in cards],
                      [c[3] for c in cards], [c[4] for c in cards], [c[5] for c in cards], unpinned)


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


PLAN_CHANGED = "The plan changed since it was previewed"
PLAN_CHANGED_BY_APPLY = "The plan changed because groups were applied"
PLAN_CHANGED_BY_APPLY_HINT = (
    "You applied groups in the tab since the preview; preview again with dry_run=true (the re-preview "
    "leaves out the groups you applied, and skip_paths protects the rest).")
APPLIED_UNREADABLE = (
    "The photos you applied in the tab could not be read in full (or there are too many to leave out), so "
    "one of them could still be rejected: preview again with dry_run=true")


def _confirm_digest(groups: list[ConfirmGroup]) -> str:
    tagged = [f"{g.type}:{g.group_id}:{side}:{path}" for g in groups
              for side, paths in (("all", g.paths), ("keep", g.keep_paths)) for path in paths]
    return nonce.digest(tagged, "confirm_culling_groups")


def normalise_window(date_from: Optional[str], date_to: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[dict]]:
    """``(date_from, date_to, error)``: the darkroom routes' ``YYYY:MM:DD HH:MM:SS`` form.

    Accepts ISO dates, ISO datetimes and EXIF forms; a date-only ``date_to`` becomes 23:59:59.
    """
    try:
        return (to_second_granularity(date_from) if date_from is not None else None,
                to_second_granularity(date_to, end_of_day=True) if date_to is not None else None, None)
    except ValueError as ex:
        return None, None, err("invalid_input", f"date_from/date_to: {ex}")


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


def register_culling_tools(server: MCPServer, app: Any, registry: TabRegistry,
                           on_write: Optional[WriteSink] = None) -> None:
    """Register the darkroom tools. ``app`` is the FastAPI app the routes live on."""
    client = InternalClient(app, CULLING_ROUTES, on_write=on_write)

    def add(fn, name: str, description: str, annotations: ToolAnnotations = READ_ANNOTATIONS) -> None:
        register_tool(server, fn, name, description, annotations, CULLING_LEVEL)

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
            since, until, bad = normalise_window(date_from, date_to)
            if bad:
                return bad
            upstream = await client.call(
                grant, "culling.groups", timeout=settings["call_timeout_s"],
                query={"group_by": group_by, "page": page, "per_page": per_page, "sort": sort,
                       "direction": direction, "exclude_rejected": "1" if exclude_rejected else "0",
                       "album_id": album_id, "date_from": since, "date_to": until})
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
            since, until, bad = normalise_window(date_from, date_to)
            if bad:
                return bad
            return await client.call(
                grant, "culling.suggest_profile", timeout=settings["call_timeout_s"],
                query={"album_id": album_id, "date_from": since, "date_to": until})
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
        cursor: Annotated[int, Field(ge=0)] = 0,
        plan_digest: Optional[str] = None,
        keep_paths: Annotated[Optional[list[str]], Field(max_length=1000)] = None,
        remove_paths: Annotated[Optional[list[str]], Field(max_length=1000)] = None,
        show: bool = True,
        tab_id: Annotated[Optional[str], Field(pattern=TAB_ID_PATTERN)] = None,
    ) -> CallToolResult:
        snapshot = cast(Request, ctx.request_context.request).scope.get(REVIEW_SCOPE_KEY)

        async def handler(grant, resolved, settings):
            since, until, bad = normalise_window(date_from, date_to)
            if bad:
                return bad
            timeout = settings["call_timeout_s"]
            owner = grant.nonce_owner
            explicit = keep_paths is not None or remove_paths is not None
            if dry_run and cursor > 0 and not plan_digest:
                return err("invalid_input", "plan_digest is required when cursor > 0: pass the "
                           "`plan_digest` of the cursor-0 page, so every page comes from the same plan")
            memory = None if dry_run or explicit or not confirm else _recall(_previews, (owner, confirm))
            marks: Optional[Marks] = None
            if explicit:
                # Only what the user already applied is taken from the tab: their pending marks are replaced
                # by the explicit lists, but a photo they committed is never re-decided.
                tab = await read_marks(resolved, settings, tab_id, timeout, snapshot)
                marks = Marks(applied=tab.applied, applied_truncated=tab.applied_truncated) if tab else None
            elif memory is not None:
                marks = memory.marks
            elif dry_run and cursor > 0:
                recalled = _recall(_page_marks, (owner, plan_digest))
                marks = recalled[0] if recalled else None
            else:
                marks = await read_marks(resolved, settings, tab_id, timeout, snapshot)
            used = marks is not None and marks.usable
            options = {"group_by": group_by, "album_id": album_id, "date_from": since,
                       "date_to": until, "strictness": strictness,
                       "min_keep_per_group": min_keep_per_group, "profile": profile,
                       "trim_brackets": trim_brackets, "highlights_album": highlights_album,
                       "keep_paths": list(marks.keep) if used else (keep_paths or []),
                       "remove_paths": list(marks.remove) if used else (remove_paths or [])}
            if used:
                options["lenient_overrides"] = True
            page_call = {**options, "dry_run": True, "cursor": cursor if dry_run else 0}
            if dry_run and plan_digest:
                page_call["expected_digest"] = plan_digest
            if memory is not None:
                return await apply_preview(grant, memory, options, confirm, resolved, settings, tab_id, timeout,
                                           snapshot)
            preview = await client.call(grant, "culling.auto", json=page_call, timeout=timeout)
            if not preview["ok"] and PLAN_CHANGED_BY_APPLY in preview.get("message", ""):
                return err("confirmation_required", PLAN_CHANGED_BY_APPLY_HINT)
            if not preview["ok"] and PLAN_CHANGED in preview.get("message", ""):
                return err("confirmation_required",
                           "The plan changed since the first page; nothing was written. Restart the "
                           "preview from cursor 0 (without plan_digest) and use its new `confirm`")
            if not preview["ok"] or dry_run:
                result = _preview_result(grant, preview, settings, cursor)
                if result["ok"]:
                    attach_tab_marks(result, marks, preview["data"] or {})
                    if not explicit:
                        remember_marks(owner, result, marks or Marks())
                if show and dry_run and result["ok"]:
                    result["shown_in_tab"] = await _show_page(
                        result["data"].get("rows") or [], resolved, settings, tab_id, timeout)
                return result
            digest = (preview["data"] or {}).get("plan_digest")
            if not digest or not (preview["data"] or {}).get("rejected") \
                    or not nonce.check(grant.nonce_owner, "auto_cull", digest, confirm):
                return err("confirmation_required",
                           "Preview with dry_run=true first and pass its `confirm` value, with the "
                           "same overrides; the plan must be unchanged since that preview")
            skip = applied_skip(marks)
            if skip is None:
                return err("confirmation_required", APPLIED_UNREADABLE)
            return await send_apply(grant, options, digest, marks, timeout, skip, marks.applied if marks else ())
        return await run_tool(ctx, "auto_cull", handler, write=not dry_run)

    async def read_marks(resolved, settings, tab_id: Optional[str], timeout: float,
                         snapshot: Optional[dict]) -> Optional[Marks]:
        """The user's current marks: the in-page caller's own snapshot, else the bridge tab (never both).

        Any failure (no tab, bridge off, outdated tab, timeout) reads as no marks. The read passes no
        ``activity_since``, so it consumes nothing of what ``ui_get_context`` reports to the agent.
        """
        if resolved.inpage:
            return marks_from_review(snapshot)
        if not settings["bridge"]:
            return None
        envelope = await relay.call_tab(registry, resolved, settings, "ui_get_context", {}, tab_id,
                                        timeout=timeout)
        data = envelope.get("data") if envelope.get("ok") else None
        return marks_from_review(data.get("review")) if isinstance(data, dict) else None

    def attach_tab_marks(result: dict, marks: Optional[Marks], body: dict) -> None:
        """Add ``overrides_from_tab`` to ``result``: the marks that changed the plan, the dropped ones or the skip."""
        if marks is None or not (marks.usable or marks.truncated or marks.has_applied):
            return
        if marks.truncated:
            result["overrides_from_tab"] = {"skipped": "truncated"}
            return
        report: dict = {}
        if marks.usable:
            dropped = body.get("dropped_overrides") or []
            effective = body.get("effective_overrides") or {}
            report = {"keep": effective.get("keep", 0), "remove": effective.get("remove", 0)}
            if dropped:
                report["dropped"] = dropped[:SUMMARY_PATHS]
                if len(dropped) > SUMMARY_PATHS:
                    report["dropped_count"] = len(dropped)
            result.get("data", {}).pop("dropped_overrides", None)
        if marks.has_applied:
            report["applied"] = len(marks.applied)
        result["overrides_from_tab"] = report

    def remember_marks(owner, result: dict, marks: Marks) -> None:
        """Keep the cursor-0 marks for later pages (by plan digest) and for the apply (by ``confirm``)."""
        digest = (result.get("data") or {}).get("plan_digest")
        if not digest:
            return
        expires = limits.now() + nonce.TTL_SECONDS
        _remember(_page_marks, (owner, digest), (marks, expires))
        if result.get("confirm"):
            _remember(_previews, (owner, result["confirm"]), _Preview(digest, marks, expires))

    def applied_skip(marks: Optional[Marks], flips: Sequence[str] = ()) -> Optional[list[str]]:
        """The photos an apply leaves out (``flips`` plus what the user applied), or None when that cannot be trusted."""
        if marks is not None and marks.applied_truncated:
            return None
        skip = list(dict.fromkeys([*flips, *(marks.applied if marks else ())]))
        return None if len(skip) > SKIP_PATHS_MAX else skip

    async def send_apply(grant, options: dict, digest: str, marks: Optional[Marks], timeout: float,
                         skip: Optional[list[str]] = None, applied_paths: Sequence[str] = ()) -> dict:
        applied = await client.call(
            grant, "culling.auto",
            json={**options, "dry_run": False, "expected_digest": digest,
                  **({"skip_paths": skip} if skip else {}),
                  **({"applied_paths": list(applied_paths)} if applied_paths else {})},
            timeout=timeout)
        if not applied["ok"]:
            if PLAN_CHANGED_BY_APPLY in applied.get("message", ""):
                return err("confirmation_required", PLAN_CHANGED_BY_APPLY_HINT)
            if PLAN_CHANGED in applied.get("message", ""):
                return err("confirmation_required", applied["message"])
            return applied
        body = applied["data"] or {}
        result = ok({key: body.get(key) for key in APPLY_KEYS if key in body})
        attach_tab_marks(result, marks, body)
        return result

    async def apply_preview(grant, memory: _Preview, options: dict, confirm: Optional[str],
                            resolved, settings, tab_id: Optional[str], timeout: float,
                            snapshot: Optional[dict]) -> dict:
        """Apply the plan the user was shown: the ORIGINAL preview's digest, its marks, and the flips since.

        No dry run is re-run (it would hand the route a new digest and, for a plan the user's own edit
        moved, a nonce that cannot match); the route compares the plan with its preview-time snapshot.
        """
        if not nonce.check(grant.nonce_owner, "auto_cull", memory.digest, confirm):
            return err("confirmation_required",
                       "Preview with dry_run=true first and pass its `confirm` value, with the "
                       "same overrides; the plan must be unchanged since that preview")
        current = await read_marks(resolved, settings, tab_id, timeout, snapshot)
        flips = flips_since(memory.marks, current)
        if memory.marks.usable and (current is None or current.truncated or len(flips) > SKIP_PATHS_MAX):
            return err("confirmation_required",
                       "The marks in the tab could not be re-read in full (or too many changed since the "
                       "preview), so a photo you flipped to Keep could still be rejected: preview again "
                       "with dry_run=true")
        done = tuple(dict.fromkeys([*memory.marks.applied, *(current.applied if current else ())]))
        skip = applied_skip(Marks(applied=done, applied_truncated=bool(current and current.applied_truncated)),
                            flips)
        if skip is None:
            return err("confirmation_required", APPLIED_UNREADABLE)
        return await send_apply(grant, options, memory.digest, memory.marks, timeout, skip, done)

    async def _show_page(rows: list[dict], resolved, settings, tab_id: Optional[str], timeout: float) -> dict:
        page = _pinned_page(rows)
        unpinned = page.unpinned
        if not page.paths:
            return relay.not_shown("empty_result")
        shown = await relay.show_paths_in_tab(registry, resolved, settings, tab_id, page.paths,
                                              timeout=timeout, groups=page.groups, marks=page.marks,
                                              labels=page.labels, reasons=page.reasons, kinds=page.kinds)
        missing = shown.get("missing")
        if isinstance(missing, list) and len(missing) > SUMMARY_PATHS:
            shown["missing_count"] = len(missing)
            shown["missing"] = missing[:SUMMARY_PATHS]
        if unpinned:
            shown["unpinned"] = unpinned
        return shown

    def _preview_result(grant, upstream: dict, settings: dict, cursor: int) -> dict:
        if not upstream["ok"]:
            return upstream
        body = upstream["data"] or {}
        data = {**body, "rows": list(body.get("preview", []))}
        data.pop("preview", None)
        data.pop("effective_overrides", None)
        ignored = body.get("ignored_overrides") or []
        if len(ignored) > SUMMARY_PATHS:
            data["ignored_overrides"] = ignored[:SUMMARY_PATHS]
        if ignored:
            data["ignored_overrides_count"] = len(ignored)
        kinds = body.get("scope_dependent_kinds")
        notes = []
        if not body.get("rejected"):
            notes.append("Nothing to apply")
        if kinds:
            notes.append(f"Groups of kind {', '.join(kinds)} depend on the date range / candidate pool: "
                         "cull the whole range in one call.")
        extra = {"note": " ".join(notes)} if notes else {}
        issues = bool(body.get("rejected")) and cursor == 0
        if issues:
            extra["confirm"] = "x" * CONFIRM_WIDTH
        _fit_page(data, extra, settings)
        if issues:
            extra["confirm"] = nonce.issue(grant.nonce_owner, "auto_cull", body["plan_digest"])
        return ok(data, **extra)

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
                if not nonce.check(grant.nonce_owner, "confirm_culling_groups", digest, confirm):
                    return err("confirmation_required",
                               "A group with empty keep_paths rejects every frame it names. Show "
                               "the user, then repeat this call with `confirm` set to this value.",
                               confirm=nonce.issue(grant.nonce_owner, "confirm_culling_groups", digest))
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
                    stopped = upstream if not rows else ok({"rows": rows + [
                        {**head, "ok": False, "error": upstream["error"]}]})
                    return stopped
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
        "Name the preset that fits an album or capture-time window. date_from/date_to accept "
        "'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS' or the EXIF 'YYYY:MM:DD HH:MM:SS'; a date-only "
        "date_to covers the whole day.")
    add(keeper_hints, "keeper_hints",
        "Per-photo 'a better shot exists in this burst' hints for up to 100 paths. Empty when no "
        "keeper head is trained.")
    add(auto_cull, "auto_cull",
        "Auto-cull a scope under a keeper budget. dry_run=true (default) only previews the split "
        "and returns a `confirm` value; show the user the counts, then call again with "
        "dry_run=false and that `confirm` to reject the planned frames. The apply leaves out the photos "
        "the user rated, favourited or rejected since the preview (`skipped_user_changed`, with "
        "`skipped_user_changed_count`) and is refused when the plan changed for any other reason. The preview is paged by whole groups: repeat the call "
        "with `cursor` set to the result's `next_cursor` and `plan_digest` set to the cursor-0 "
        "page's `plan_digest` (required when cursor > 0; a changed plan is refused, restart from "
        "cursor 0) until next_cursor is null; a page is cut by whole groups to fit the result size (a single group too big for it has its "
        "path lists clipped: `paths_clipped`, with `keep_count` / `reject_count`). "
        "Counts cover the full plan and ONE confirm, issued on the cursor-0 page only, covers all "
        "of it (valid 300 s, single use). The apply returns counts only. To honour the user's review, "
        "OMIT keep_paths and remove_paths: the user's Keep/Remove flips are read from their open tab "
        "(`ui_get_context` shows the same `review`). Pass explicit lists (up to 1000 each) only to replace "
        "the tab's marks, never merged: paths outside the plan come back as `ignored_overrides` (the first 20, "
        "with `ignored_overrides_count`), and removing a frame of a bracket or panorama, emptying a group of "
        "keepers or listing a path in both is refused. Explicit lists must be the SAME on the dry run that "
        "issues the confirm and on the apply. "
        "Brackets and panoramas are kept whole. date_from/date_to "
        "accept 'YYYY-MM-DD' (date_to covers the whole day) or 'YYYY-MM-DD HH:MM:SS'. Cull a whole "
        "range in ONE call: do not split it by month, because similar and scene groups depend on "
        "the date range (see `scope_dependent_kinds` in the result)." + AUTO_CULL_SHOW + SEE_GROUP,
        DESTRUCTIVE_ANNOTATIONS)
    add(confirm_culling_groups, "confirm_culling_groups",
        "Confirm up to 20 groups, each keyed by (type, group_id) with the group's `paths` and the "
        "`keep_paths` to keep; the rest are rejected. bracket/panorama/hdr_panorama groups must "
        "keep every path. A group with empty keep_paths (reject all) first answers "
        "confirmation_required with a `confirm` value to repeat the call with." + SEE_GROUP,
        DESTRUCTIVE_ANNOTATIONS)
