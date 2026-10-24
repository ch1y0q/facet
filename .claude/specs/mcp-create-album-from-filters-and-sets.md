# Spec: MCP `create_album` from filters, the open view, or a set of photos (rev 2)

## Objective + success criteria
One `create_album` call takes at most one of: `filters` (smart album), `target="view"` (smart album from the
tab's open gallery view), `paths` / `target="selection"` (fixed album, created and filled). None = today's empty album, unchanged.
- The stored `smart_filter_json` is byte-compatible with what the gallery's own `smartAlbumFilterJson` writes.
- Parity (on the user-visible album surface, see D4): `create_album(filters)` total == `search_photos(filters)` total ==
  `/api/photos` with the stored filters normalised + default hide toggles.
- Fixed album: created and filled in one call; result carries `id`, `photo_count`, `added`, `skipped`.
- Unsupported combinations fail loudly (`unsupported_filters` / `invalid_input`), never diverge silently. `show` is out of scope.

## Orchestrator decisions (binding)
- D1 Stored form = the gallery client form (`person_id`, `type`, JSON booleans, its sort-direction casing). ONE Python
  contract-to-client key table in `api/agent/ui_tools.py` (next to `TAB_UNSUPPORTED_FILTER_KEYS`); a contract test proves it
  equals the TS `CONTRACT_TO_CLIENT_KEY`. `type` + `category` together -> `invalid_input`.
- D2 Accepted keys = those the client store can hold. Any `TAB_UNSUPPORTED_FILTER_KEYS` key, `album_id`, similar/semantic key,
  paging key, or any `SMART_ALBUM_EXCLUDE_KEYS` key -> `ok:false unsupported_filters`, naming the keys.
- D3 Backend reader fix: `_normalize_smart_filters` converts JSON booleans to the backend's string form and normalises
  sort-direction casing (also repairs gallery-saved `favorites_only`/`is_monochrome`, pre-existing).
- D4 Hide toggles are NOT stored. Album page = store filters + the user's display toggles (default = hide defaults).
- D5 `target="view"` reads store-form filters directly, saves them minus excluded keys; refuses while loading and for
  pinned/semantic/similar/album views. In-page payload reuses `selection_snapshot`.
- D6 Non-existent paths are dropped before insert and reported as `skipped`; `changed_paths` IS present (expected).
- D7 `list_albums`/`get_album` counts for smart albums stay 0 (out of scope: needs filter evaluation per album, not a one-liner).
  `create_album` returns the true count; the description says smart counts in `list_albums` read 0.
- D8 Docs/instructions: `server.py` instructions, `albums.py` docstring, `docs/AGENTS.md` row + 6 translations, `build_album` prompt.

## Findings (verified in the tree)
- `POST /api/albums` already takes `is_smart`/`smart_filter_json` (albums.py:41, 481): no route change.
- `search_photos` sends contract keys (gallery names) to `/api/photos` after `_hide_defaults` (tools_read.py:202). The client
  store uses other names (`person_id`, `type`; `CONTRACT_TO_CLIENT_KEY` exists only in TS, ui-tool-handlers.ts:59). `relay.search_patch`
  (show.py:61) returns contract keys and lower-case `sort_direction`: it is not a reusable client-form mapping.
- The album page spreads the stored JSON into the store (gallery.component.ts:1229) and lists via `/api/photos` with store filters;
  `buildApiParams` drops `album_id` for smart albums (util.ts:618). The gallery store auto-saves `smartAlbumFilterJson(filters())`
  on EVERY `filters()` change while an album is open (gallery.store.ts:657-675, even a page scroll, :984), which strips
  `SMART_ALBUM_EXCLUDE_KEYS` (hide_*, gps_*, ...). So stored hide defaults would be erased on first scroll: hence D4.
- Backend reads booleans only as strings `'1'`/`'true'` (gallery.py:255,418-423,459,461; db_helpers.py:512) while the client writes
  JSON `true` (`favorites_only`, `is_monochrome` are `boolean` in `GalleryFilters`): JSON `true` is ignored by `_fetch_album_photos`.
  albums.py:1166 compares the sort direction to `'ASC'` exactly.
- `append_album_photos` (albums.py:774) is `INSERT OR IGNORE` with no existence check: unknown paths are inserted and counted as added.
- `album_add_photos` is in `PHOTO_EFFECT_TOOLS` (live_updates.py:33) so `changed_paths` is reported; `create_album` stays in
  `NO_PHOTO_EFFECT_TOOLS` (and now also calls the add route when filled).
- No album delete route exists in `ROUTES`: no rollback.

## Files to create / change
- `api/agent/ui_tools.py` (key tables + emit them in `render_client_json`), `client/src/app/core/agent/ui-tools.schema.json` (regenerated via `scripts/dump_ui_tools.py`)
- new `api/agent/album_filters.py` (contract -> stored form, validation)
- `api/agent/tools_write.py`, `api/agent/target.py`, `api/agent/server.py` (instructions)
- `api/routers/albums.py` (`_normalize_smart_filters`, `add_photos_to_album` skipped list, docstring :616-627, line 1166 reader)
- `api/models/mcp_inpage.py` (`selection_snapshot` description) + `client/src/app/core/api/schema.d.ts` (`npm run gen:api`)
- `client/src/app/core/agent/ui-tool-handlers.ts`, `server-tool-registry.service.ts`, `client/src/app/features/gallery/gallery-filters.util.ts` + specs
- `client/src/app/features/gallery/testing/smart-album-stored.json` (shared golden fixture)
- tests: `tests/test_agent_write.py`, `test_agent_target.py`, `test_agent_actions.py`, `test_albums.py`; `api/agent/prompts.py`; 7 `AGENTS.md`

## Open questions / risks
1. `render_client_json` / schema-json consumers must tolerate two new top-level keys (`filter_key_map`, `smart_album_exclude_keys`); check the contract test that walks the file.
2. A `category` value that is not a `type` preset: TS maps category->type (`CONTRACT_TO_CLIENT_KEY`), the backend expands `type` via `TYPE_FILTERS`. The per-key parity seed (step 3) must cover every category present in config; any miss is a mapping bug to fix, not paper over.

## Steps
1. **Shared key tables + contract test.** In `ui_tools.py` define `CONTRACT_TO_CLIENT_KEY = {person: person_id, category: type,
   semantic_query: semanticQuery, semantic_threshold: search_threshold}` and `SMART_ALBUM_EXCLUDE_KEYS` (copy of util.ts:246-252);
   emit both in `render_client_json`. Vitest asserts TS `CONTRACT_TO_CLIENT_KEY` and `SMART_ALBUM_EXCLUDE_KEYS` equal the JSON.
   - key decision: Python is canonical, TS is checked against it. Default: yes (the contract already works that way for ui tools).
   - verify: `venv/bin/python scripts/dump_ui_tools.py --check`; vitest; failing-first: rename one TS key and see the spec fail.
   - files: ui_tools.py, ui-tools.schema.json, ui-tool-handlers.ts (export the tables), ui-tool-handlers.spec.ts
2. **Backend reader (D3).** `_normalize_smart_filters`: bool `True` -> `'1'`, `False`/None/`''` dropped, `sort_direction` upper-cased; keep the
   `person_id` -> `person` rename. Make line 1166 read the normalised dict.
   - verify: `tests/test_albums.py`: a smart album saved as `{"favorites_only": true}` / `{"is_monochrome": true}` returns only matching rows
     (red before the fix, covering the pre-existing bug); `"sort_direction": "asc"` sorts ascending.
   - files: albums.py, tests/test_albums.py
3. **`filters` -> smart album.** `album_filters.to_stored(filters)`: (a) refuse per D2 (use `show._is_effective` so `show_rejected: false` is not a refusal;
   explicit `hide_*` refused as display toggles); (b) `type`+`category` -> `invalid_input`; (c) rename via the table; (d) booleans for
   `favorites_only`/`is_monochrome` as JSON `true`, every other value `str()`; (e) `json.dumps` with no hide keys. Count via `photos_count`
   on `_scope_filters(filters)` (contract form + hide defaults = what `search_photos` counts); POST `create_album` with `is_smart:true`;
   return the album dict with `photo_count=count` and a `warning` when 0. Empty `filters` is allowed (everything).
   - key decision: stored without hide defaults (D4). Why: the album page applies the user's own toggles; the gallery erases them on first scroll anyway.
   - verify: parity test class `TestSmartAlbumParity` seeding photos so hiding discriminates (unhidden count > hidden count: burst followers,
     rejected, duplicates) plus one discriminating row per accepted key: `person`, `category` (every configured category) and `type=top_picks`,
     `favorites_only`, `is_monochrome`, `date_from`/`date_to`, `path_prefix`, a score range (`min_aggregate`-free: `min_score`/`max_score`),
     `min_star_rating`... each case asserts `create_album` total == `search_photos` total == `GET /api/photos` with the stored JSON normalised +
     default hide toggles. Refusal cases: each `TAB_UNSUPPORTED_FILTER_KEYS` key, `hide_bursts`, `gps_lat`, `type`+`category`. Failing-first: skip the rename and watch `person` fail.
   - files: album_filters.py, tools_write.py, tests/test_agent_write.py
4. **Album page golden fixture (G7).** Extract the inline spread (gallery.component.ts:1229) into `applySavedAlbumFilters(current, json, albumId)` in
   the util. Python test writes `to_stored(...)` for a multi-key filter set and asserts it equals `smart-album-stored.json`; vitest loads the same
   file and asserts the resulting store filters equal the expected `GalleryFilters` slice (booleans stay booleans, `person_id`/`type` populated)
   AND `smartAlbumFilterJson(result)` round-trips to the same JSON (so the auto-save does not rewrite it).
   - verify: both tests green; failing-first: change a fixture key on one side only.
   - files: gallery-filters.util.ts, gallery.component.ts, util spec, fixture, tests/test_agent_write.py
5. **`target="view"` (D5).** Client: `ui_get_gallery_view` also returns `album_filter_json: smartAlbumFilterJson(gallery.filters())` and
   `filters_scopable: gallery.canScopeSelectionToView()` (`loading` already exists). In-page: `server-tool-registry.service.ts` `call()` attaches
   that `ui_get_gallery_view` data as `selection_snapshot` when `input.target === 'view'`; external MCP: `relay.call_tab("ui_get_gallery_view", {limit: 1})`.
   Server `resolve_view`: refuse if `loading` (`invalid_input`, "the tab is still loading, retry"), `!filters_scopable`, route not the gallery, or the
   JSON is not an object of str/bool values; refuse keys that are not gallery keys (`gallery_filter_keys()` after inverse-mapping) or in the exclude/unsupported/`album_id`
   sets (`view_filters` alone does not reject `album_id`). Store the string as-is (no `type`->`category` rename; the contract `filters` field is not used for storage).
   Recount: `photos_count` over the stored filters (mapped to query form, bools `'1'`) PLUS the tab's own `hide_*` taken from its contract `filters`; it must equal the
   tab's `total`, else refuse and create nothing. `photo_count` = that total.
   - verify: `fake_tab` replying to `ui_get_gallery_view`: happy path (incl. `type=top_picks`), mismatch, `loading`, `filters_scopable:false`, album view,
     in-page `/api/mcp/call` with `selection_snapshot`. Vitest: snapshot attached only for `target:'view'`; handler returns the two new fields.
   - files: ui-tool-handlers.ts, server-tool-registry.service.ts, target.py, tools_write.py, mcp_inpage.py, specs, tests/test_agent_target.py
6. **`paths`/`selection` -> fixed album (D6).** Resolve first (`resolve_target(..., need_paths=True, path_cap=BATCH_CAP)`), then create, then add.
   Existence is fixed in the ROUTE, not the agent layer: it is one place, also repairs `album_add_photos` (which has the same bug) and the
   auto-cull caller, whereas an agent-layer filter would need `by_paths` chunking (cap 500 < 1000). `add_photos_to_album` selects the existing paths
   (chunks of 500), inserts only those, and returns `skipped` (the unknown paths, capped like `BY_PATHS_MISSING_CAP`). `append_album_photos` keeps its
   signature but the route passes it the filtered list. The tool returns `added`, `skipped`, `photo_count`.
   Partial failure: if the add fails after the create there is NO rollback; return `err(code, msg, album_id, created=True, added=0, not_attempted=len(paths))`
   (+ `in_doubt` for `outcome_unknown`). Never `ok` for a half-done call.
   - verify: paths with 1 unknown -> `added == n-1`, `skipped == [unknown]`, no `album_photos` row for it; too many -> `too_large`, no album; selection path;
     `intercept_internal_call` makes `album_add_photos` return `library_busy` -> album exists empty, error has `album_id`; `changed_paths` present on success.
   - files: albums.py, tools_write.py, tests/test_albums.py, test_agent_write.py, test_agent_target.py
7. **Schema, levels, live updates, routes.** `create_album(name, description, filters, paths, target: Optional[Literal["selection","view"]], tab_id)`; `filters`
   annotation set like search_photos' (`extra=forbid`); exactly-one check before any write. Level stays `edition`, `WRITE_ANNOTATIONS`, not in `CORE_TOOLS`.
   `tests/test_agent_actions.py:40` route list for `create_album` becomes `["create_album", "photos_count", "album_add_photos", "photos_paths"]` (photos_paths for a
   whole-view selection expansion). `NO_PHOTO_EFFECT_TOOLS` unchanged; the add leg already reports `changed_paths`.
   - verify: level matrix and live-update classification tests pass; in-page tool listing shows `filters`/`paths`/`target` without `tab_id`.
   - files: tools_write.py, tests/test_agent_actions.py, tests/test_agent_write.py
8. **Docs (D8).** `server.py:73` instructions mention `target="view"` (create_album only) and `filters`; `albums.py:616-627` docstring: hide toggles are the viewer's,
   and agent-created albums follow the same rule; the tool description states smart-album counts in `list_albums` read 0; `docs/AGENTS.md:178` row and
   `docs/{fr,de,it,es,pt,zh}/AGENTS.md`; `build_album` prompt (`prompts.py:~96`).
   - verify: `venv/bin/python scripts/docs_parity.py`, `docs_xlinks.py`, prompts tests.
   - files: server.py, albums.py, prompts.py, 7 AGENTS.md
9. **Types.** `cd client && npm run gen:api` (description change in `mcp_inpage.py`; the albums response gains `skipped` only if modelled, otherwise unchanged).
   - verify: `git diff --stat client/src/app/core/api/schema.d.ts` shows only expected lines; CI staleness check passes.

## Final verification gate
- `venv/bin/python -m pytest tests/test_agent_write.py tests/test_agent_target.py tests/test_agent_actions.py tests/test_albums.py -q`, then `tests/ -q`
  (2 workers max); `venv/bin/python -m ruff check .`; `scripts/dump_ui_tools.py --check`.
- `cd client && npm run test`; both `tsc --noEmit` projects; `npx ng lint`.
- Fixtures use `init_database`-built DBs, `agent_app`/`fake_tab`, no `mock.patch` on auth. Restore any injected fault by hand; `git status --porcelain <file>` empty.

## Adversarial review (opus findings, each verified against the tree)
- B1 CONFIRMED (show.py:61-70 contract keys + lower-case direction; table only in TS; albums.py:1166 exact `'ASC'`): step 1 adds the Python table + contract test; step 2 normalises casing.
- B2 CONFIRMED (backend `'1'`/`'true'` only; `favorites_only`/`is_monochrome` are `boolean`; client writes `v` raw): step 2 fixes the reader (also the pre-existing bug), step 4 round-trips a golden fixture.
- B3 CONFIRMED (gallery.store.ts:657-675 effect on any `filters()` change; util.ts:246-252 strips hide_*): hide defaults no longer stored (D4); parity moved to the album-page surface (step 3).
- G1 CONFIRMED (`TAB_UNSUPPORTED_FILTER_KEYS` has no store slot; album page lists with store filters): `unsupported_filters` refusal (steps 3, 5).
- G2 CONFIRMED (viewFilters renames type->category; `view_filters` does not reject `album_id`; no loading refusal): step 5 reads `album_filter_json` store form, adds explicit refusals.
- G3 CONFIRMED (`INSERT OR IGNORE`, no existence check): step 6 fixes at the route and says why.
- G4 CONFIRMED (`album_add_photos` in `PHOTO_EFFECT_TOOLS`; route list lacked `photos_paths`): step 7.
- G5 CONFIRMED (list/get count `album_photos`): out of scope per D7, create returns the true count, documented (step 8).
- G6 CONFIRMED (server.py:73 advertises only `target="selection"`): step 8.
- G7 CONFIRMED (earlier parity test was backend-only, one case): steps 3-4 add per-key discriminating seeds and a shared golden fixture with a vitest.
