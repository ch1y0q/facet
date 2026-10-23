# Spec: let the Facet MCP assistant open an album and a timeline month (`ui_open_album`, `ui_navigate` year/month)

Item B of /home/ncoevoet/.claude/plans/from-gallery-in-culling-async-goblet.md.

## Objective + success criteria
- "Open my Iceland album" works: `list_albums` -> `ui_open_album {album_id}` puts the tab on `/album/<id>`; a fixed album and a smart album (`smart_filter_json`) both open (the gallery page applies the saved filters itself).
- "Show March 2024" works: `ui_navigate {route:'/timeline', year:2024, month:3}` lands on `/timeline/2024/3`; `year` alone lands on `/timeline/2024`; neither stays `/timeline`.
- Chaining: `create_album` (returns `album_id`) -> `ui_open_album` opens the album just created.
- An unknown or inaccessible album id answers `not_found`, never a blank/mis-scoped gallery; `month` without `year`, `month` outside 1-12, `year` outside 1900-2100, or `year`/`month` with another route answers `invalid_input`; nothing navigates in any of those cases.
- Both paths reuse the D guard: leaving `/culling` over unconfirmed decisions answers `unsaved_decisions` before any side effect (no album fetch, no navigate); a router decline answers `navigation_refused`.
- The contract JSON, `available_actions` rows, docs (7 languages) and tests all move in the same change; `scripts/dump_ui_tools.py --check` is clean.

## Established facts (evidence)
- VERIFIED D guard exists: commit `f09e7604` ("keep unconfirmed culling decisions when the assistant navigates"). `leaveCullingGuard(target?)` at `client/src/app/core/agent/ui-tool-handlers.ts:191-195` throws `UiToolError('unsaved_decisions', UNSAVED_DECISIONS_MESSAGE)` when `pathOf(router.url)==='/culling' && target!=='/culling' && plan.hasUnsavedDecisions()`; `navigation_refused` is thrown where `router.navigate` returns false (`:207`, `:220`, `:346`, `:414`). `ui_navigate` calls the guard at `:344` AFTER its allowed/edition checks and BEFORE navigate; `ui_open_photo` at `:412`. `navigation_refused` is already in `TAB_ERROR_CODES` (`api/agent/ui_tools.py:37-40`).
- VERIFIED the two gaps: `appRoutes()` skips any path matching `/[:*]/` (`ui-tool-handlers.ts:46-56`), so `album/:albumId`, `timeline/:year`, `timeline/:year/:month` are unreachable; `UiRoute` is a static `Literal` (`api/agent/ui_tools.py:42-45`, includes `"/timeline"` but no params). The `query` argument cannot help: the timeline reads PATH params (`timeline.component.ts:133`, `paramMap` year/month), not query.
- VERIFIED client routes (`client/src/app/app.routes.ts`): `album/:albumId` (l.77, `authGuard`, gallery component), `timeline` (l.95), `timeline/:year` (l.101), `timeline/:year/:month` (l.107); none carries `edition` data, so no edition gate. Month in the URL is the unpadded number (`timeline.component.ts:164-168` `String(+parts[1])`; `selectedMonthFormatted` pads on read, l.145-150), so the tool must emit `3`, not `03`.
- VERIFIED silent failure to design around: for an unknown album id, `gallery.component.ts:1327-1341` catches the `albumService.get` error and only sets `filters.album_id`, leaving `currentAlbum=null` - a gallery scoped to a nonexistent album, no error. So existence MUST be checked by the handler first.
- VERIFIED album access: `GET /api/albums/{id}` -> `_check_album_access` (`api/routers/albums.py:88-102`) answers 404 "Album not found" and, on an access-controlled install, 403 for another user's album. `AlbumService.get(id)` is at `client/src/app/core/services/album.service.ts:70`. Smart and fixed albums share this route (smart ones carry `smart_filter_json`, applied at `gallery.component.ts:1331-1334`).
- VERIFIED `ui_get_context` already reports `album_id` for `/album/<n>` (`ui-tool-handlers.ts:469-470,487`). It does NOT report timeline year/month.
- VERIFIED `UiToolDeps` has no album service (`ui-tool-handlers.ts:19-35`); the factory is built in one place, `webmcp-registry.service.ts:61-70`.
- VERIFIED `create_album` returns the id (`api/agent/tools_write.py:378`, `"album_id": album.get("id")`; commit 494cca3b), so the chain needs no new server data.
- VERIFIED `available_actions`: `Action("drive_tab", ..., ("ui_navigate","ui_open_photo"), ANY)` at `api/agent/actions.py:52-53`.
- VERIFIED docs counts: `docs/AGENTS.md:5` and `:90` say "fourteen `ui_*` tools" (a new tool makes it fifteen); the `ui_open_photo` table row is at l.98 in `docs/AGENTS.md` and in all six `docs/<lang>/AGENTS.md`. `tests/test_agent_actions.py:64` has a number-word table (check at BUILD whether it pins the doc count).
- ASSUMED (check at BUILD): no test pins `len(UI_TOOLS)==14`; `tests/test_agent_show.py` has no navigate-tool cases and needs no change (`shown_in_tab` is untouched).

## Design decision (recommended)
- **Album: a new tool `ui_open_album(album_id, tab_id?)`.** It takes an entity id and needs an existence check with its own `not_found`; `ui_navigate` is "static page + query" and its allow-list is derived from the router config. A parameterised route string (`/album/12`) would need regex parsing and defeat that router-derived list.
- **Timeline: extend `ui_navigate` with optional `year` and `month`, valid only with `route:'/timeline'`.** `/timeline` is already in `UiRoute`; year/month are drill-down params of the same page, need no lookup, and a separate `ui_open_timeline` would be a 16th tool for two integers. Cost: a cross-field validator, enforced at BOTH ends (server `model_validator`, client handler) since the tab trusts nothing it receives.
- **Existence is checked client-side** (handler calls `AlbumService.get`): the tab carries the user's session, so the 404/403 answer is exactly what the album page would get; a server-side check would need a bridge round trip and would answer for the token owner, not the tab's account. 404 and 403 both map to `not_found` (do not confirm another user's album exists); other failures map to `upstream_error`.
- **ui_get_context:** keep `album_id` (exists); add `timeline: {year, month}` (cheap: parsed next to `albumMatch`), `null` off the timeline. Richer data (album name, smart/fixed) is left to item C.

## Files to create / change
- `api/agent/ui_tools.py` (UiNavigate fields+validator, new `UiOpenAlbum`, `UI_TOOLS` entry, descriptions)
- `api/agent/actions.py` (`drive_tab` tuple + description)
- `api/agent/server.py` (only if the INSTRUCTIONS text near l.60-75 should name the chain; one clause, else skip)
- `client/src/app/core/agent/ui-tool-handlers.ts`, `webmcp-registry.service.ts` (new `albums` dep), `ui-tool-handlers.spec.ts`
- `client/src/app/core/agent/ui-tools.schema.json` (generated, never hand-edited)
- `tests/test_agent_ui_contract.py`, `tests/test_agent_actions.py` (only if it pins the tool list/count)
- `docs/AGENTS.md`, `docs/{fr,de,it,es,pt,zh}/AGENTS.md`

## Open questions / risks
- Race: the album can be deleted between the check and the page mount; the page then falls into the silent `catch`. Accepted (millisecond window).
- RESOLVED (B1): album -> album reuses `GalleryComponent` (`client/src/app/core/gallery-reuse.strategy.ts:17`, default `shouldReuseRoute`), and the gallery reads `albumId` once in `ngOnInit` (`gallery.component.ts:1308,1327`), so a different id would keep showing the old album. Fix in step 7. Same album already open: return ok with `already_open: true`, no navigate (so no `tryRestoreView` stale-snapshot question).
- /compare and other non-culling pages are intentionally unguarded: only leaving `/culling` is guarded (same as the D guard).
- Ordering: steps 3 (`actions.py`) and 6 (`AGENTS.md` counts) must be rebased on scoring phase 2, which lands first; recount tools then.
- Year range 1900-2100 is a sanity bound, NOT a data check: an in-range year without photos opens an empty months view. A data check would need `timeline_years`; default is not to.
- Public `shared/album/:albumId` must stay unreachable: the handler builds `['/album', id]` itself, and `appRoutes()` keeps skipping `shared/`.
- `unsaved_decisions` must win over `not_found`: the guard runs BEFORE the fetch, so a refusal has no network side effect.
- A tab older than the server answers `tab_outdated` for the new tool (existing docs note covers it).

## Steps
1. Server contract: `UiOpenAlbum` + `UiNavigate` year/month.
   - description: add `class UiOpenAlbum(UiArgs)` with `album_id: int = Field(ge=1, le=2**31-1)` (G9) and a description carrying the chaining hint (`album_id` from `list_albums` or `create_album`) (G6); the validator also rejects `query` together with `year`/`month` (`invalid_input`, G8, mirrored in the client handler); add `year: Optional[int] = Field(default=None, ge=1900, le=2100)` and `month: Optional[int] = Field(default=None, ge=1, le=12)` to `UiNavigate` plus a `model_validator(mode="after")` raising `ValueError` unless year/month are absent or `route == "/timeline"`, and when `month` is set requiring `year`. Register `UiTool("ui_open_album", ..., UiOpenAlbum, False)` after `ui_open_photo` with the same `unsaved_decisions` / `navigation_refused` sentence plus `not_found` for an unknown or inaccessible album. Extend the `ui_navigate` description with the year/month sentence.
   - key decision: separate tool vs parameterised route string. default: separate tool for album, extension for timeline (see Design).
   - also update the `ui_get_context` description for the new `timeline` field (G5).
   - verify: `venv/bin/python scripts/dump_ui_tools.py`, then `git diff client/src/app/core/agent/ui-tools.schema.json` shows the new tool, the `ui_navigate` properties, description edits AND a changed `version` (the tools hash; expected, V12); extend the `test_agent_ui_contract.py:108` unsaved_decisions loop with `ui_open_album` (G7); `venv/bin/python -m pytest tests/test_agent_ui_contract.py -q`.
   - affected files: `api/agent/ui_tools.py`, `client/src/app/core/agent/ui-tools.schema.json` (generated).
2. Client handlers.
   - description: (a) add the raw album probe dep to `UiToolDeps`, wired at `webmcp-registry.service.ts:61-70`; update EVERY `createUiToolHandlers({...})` literal in `ui-tool-handlers.spec.ts` (:61, :101, :228) with it and give the mock a `get` (G4). (b) `ui_open_album`: `album_id` must be a positive integer (`invalid_input`); `leaveCullingGuard()`; if the router is already on `/album/<id>` return ok with `already_open: true` and do not navigate; otherwise probe existence through the RAW backend call path (as `server-tool-registry.service.ts` does), bypassing ApiService interceptors (no snackbar, no `auth.revalidate`, no retry, no crash report); 403 and 404 -> `UiToolError('not_found', ...)`, 5xx/other -> `upstream_error` with no toast (G3); then `router.navigate(['/album', id], {onSameUrlNavigation:'reload'})`, false -> `navigation_refused`; return `{route, album_id, name, is_smart}`. (c) `ui_navigate`: year/month with `route !== '/timeline'`, `month` without `year`, or non-integer/out-of-range -> `invalid_input` BEFORE the guard; commands `['/timeline', String(year), String(month)]` (unpadded), then the existing guard / `navigation_refused` path. (d) `ui_get_context`: add `timeline: {year, month}` parsed from `/timeline/<y>[/<m>]`, else `null`.
   - key decision: where the guard sits relative to the fetch. default: `invalid_input`, then guard, then fetch, then navigate (cheapest refusal first; a refusal causes no request).
   - verify: specs in step 5; `cd client && npx tsc --noEmit -p tsconfig.app.json && npx tsc --noEmit -p tsconfig.spec.json && npx ng lint`.
   - affected files: `client/src/app/core/agent/ui-tool-handlers.ts`, `client/src/app/core/agent/webmcp-registry.service.ts`.
3. `available_actions` and server instructions.
   - description: extend `drive_tab` (`api/agent/actions.py:52-53`) to `("ui_navigate","ui_open_photo","ui_open_album")` and its text to "Move the user's tab to another page, an album or a timeline month, or open a photo". Skip `api/agent/server.py` INSTRUCTIONS (the chaining hint lives in the `ui_open_album` description, G6).
   - key decision: new `Action` row vs extend `drive_tab`. default: extend (same `ANY` availability; a row per tool bloats the table).
   - verify: re-run `venv/bin/python scripts/dump_ui_tools.py` (V11; the actions table is emitted into the JSON), then `venv/bin/python -m pytest tests/test_agent_actions.py tests/test_agent_ui_contract.py -q`.
   - affected files: `api/agent/actions.py`, `ui-tools.schema.json` (generated).
4. Error-code plumbing.
   - description: no new code. `not_found`, `invalid_input`, `unsaved_decisions`, `navigation_refused` are all in `TAB_ERROR_CODES` and `UI_TOOL_ERROR_CODES`. Do not add `album_not_found`.
   - key decision: dedicated code vs reuse `not_found`. default: reuse; the message names the album.
   - verify: the equality spec at `ui-tool-handlers.spec.ts:114` and `tests/test_agent_ui_contract.py:101` pass unchanged.
   - affected files: none.
5. Tests (N17: do this BEFORE steps 2, 7 and 8 - write the specs, run them, watch them fail, then implement).
   - extra: G3 spec (raw probe: 403/404 -> `not_found`, 5xx -> error code, no snackbar/revalidate); `already_open: true` spec with `navigate` not called; N18 verify: an album made by `create_album` (token owner's `user_id`) opens from that user's tab on single-password and multi-user installs (`albums.py:99` `_check_album_access` with `user_id` None) - E2E on both.
   - client `ui-tool-handlers.spec.ts`: `ui_open_album` navigates to `['/album', 5]` and returns name/is_smart for a fixed and a smart fixture; 404 -> `not_found` with `navigate` not called; 403 -> `not_found`; 500 -> `upstream_error`; navigate false -> `navigation_refused`; probe true on `/culling` -> `unsaved_decisions` with `albums.get` and `navigate` not called; non-integer id -> `invalid_input`. `ui_navigate`: `/timeline` + year+month -> `['/timeline','2024','3']`; year only; month without year, month 13, year 1800, `{route:'/stats', year:2024}` -> `invalid_input`, no navigate; timeline + unsaved decisions -> `unsaved_decisions`. `ui_get_context` reports `timeline` on `/timeline/2024/3`, `null` elsewhere. In the "real client routes" block (`:201`) assert `/album/5` and `/timeline/2024/3` are still rejected as a bare `route`.
   - python `tests/test_agent_ui_contract.py`: `UiOpenAlbum(album_id=0)` rejected; `UiOpenAlbum(album_id=3).forward()=={"album_id":3}`; `UiNavigate(route='/timeline', year=2024, month=3).forward()` carries both; `UiNavigate(route='/stats', year=2024)` and `UiNavigate(route='/timeline', month=3)` raise; add `ui_open_album` to the description loop at `:108`; `drive_tab` includes it.
   - verify: `cd client && npm run test` (2 workers max); `venv/bin/python -m pytest tests/test_agent_ui_contract.py tests/test_agent_actions.py tests/test_agent_bridge.py tests/test_agent_show.py -q`.
   - affected files: `client/src/app/core/agent/ui-tool-handlers.spec.ts`, `tests/test_agent_ui_contract.py`, possibly `tests/test_agent_actions.py`.
6. Docs, same change, 7 languages.
   - description: in `docs/AGENTS.md` change "fourteen" to "fifteen" (l.5, l.90), add a table row after l.98 for `ui_open_album` (open one album, fixed or smart, by `album_id`; an unknown or inaccessible id answers `not_found`), amend the `ui_navigate` row and the "opens only the app's own static pages" bullet to say `/timeline` also takes `year` and `month` (1-12), and note that `ui_get_context` returns `timeline` on that page. Mirror in `docs/{fr,de,it,es,pt,zh}/AGENTS.md`, identifiers untranslated. Old number words to replace (V10): fr quatorze, de vierzehn, it quattordici, es catorce, pt catorze, zh 十四; new: quinze, fuenfzehn (fünfzehn), quindici, quince, quinze, 十五.
   - key decision: none beyond wording. default: mirror the English structure line for line.
   - verify: `venv/bin/python scripts/docs_parity.py && venv/bin/python scripts/docs_xlinks.py`; grep for the old number word in all seven files leaves nothing.
   - affected files: `docs/AGENTS.md`, `docs/{fr,de,it,es,pt,zh}/AGENTS.md`.

7. Route reuse (B1).
   - description: in `GalleryReuseStrategy.shouldReuseRoute` (`client/src/app/core/gallery-reuse.strategy.ts`), do NOT reuse when both routes are the `album/:albumId` route and the `albumId` param differs, so a fresh `GalleryComponent` reads the new id. Add a router-level spec (real Router): navigate album 3 -> album 5 renders a new instance that reads 5.
   - key decision: strategy change vs re-reading params in the component. default: strategy (one line, the component stays untouched).
   - verify: the new spec fails before and passes after; E2E: `ui_open_album` 3 then 5 shows album 5's photos.
   - affected files: `gallery-reuse.strategy.ts` and its spec.
8. Activity label i18n (B2).
   - description: add `assistant_activity.ui.ui_open_album` in all 7 bundles (`client/src/app/core/i18n/translations/*.json`, precedent `ui_open_photo` ~:2706) and regenerate `client/src/app/core/i18n/keys.ts` with `node scripts/gen-i18n-keys.mjs`.
   - key decision: none. default: mirror the `ui_open_photo` wording per language.
   - verify: `venv/bin/python -m pytest tests/test_activity_label_keys.py -q` and `venv/bin/python scripts/audit_i18n.py`.
   - affected files: the 7 translation JSONs, `keys.ts`.

## Final verification gate
- `venv/bin/python scripts/dump_ui_tools.py --check`; `venv/bin/python -m pytest tests/test_agent_*.py -q`; `venv/bin/python -m ruff check .`
- `cd client && npm run test && npx tsc --noEmit -p tsconfig.app.json && npx tsc --noEmit -p tsconfig.spec.json && npx ng lint && npm run gen:api`.
- Real browser (E2E harness): `create_album`, then `ui_open_album` with the returned id; open a smart album; `ui_open_album {album_id: 99999}` -> `not_found` and the tab stays put; `ui_navigate {route:'/timeline', year:2024, month:3}`; with an unconfirmed flip on `/culling`, both tools answer `unsaved_decisions` and the darkroom keeps its decisions.
- Rebuild Angular and restart the server (frontend change).

## Adversarial review
Findings and adjudication (coordinator's binding decisions):
- B1 BLOCKER, accepted: album -> album reuses the component; fixed by step 7 plus `already_open`.
- B2 BLOCKER, accepted: missing activity label in 7 bundles and `keys.ts`; step 8.
- G3 accepted: raw probe bypassing interceptors, 403/404 -> `not_found`, 5xx -> error code, no toast (step 2, step 5).
- G4 accepted: every `createUiToolHandlers` literal in the spec updated (step 2).
- G5 accepted: `ui_get_context` description (step 1). G6 accepted: chaining hint in the tool description, INSTRUCTIONS step dropped (steps 1, 3).
- G7 accepted: extend the `test_agent_ui_contract.py:108` loop (step 1 verify). G8 accepted: `query` with year/month -> `invalid_input` at both ends (step 1, 2).
- G9 accepted: `album_id` `le=2**31-1` (step 1).
- V10 accepted: number words per language (step 6). V11 accepted: re-run dump in step 3. V12 accepted: schema `version` changes (step 1 verify).
- N15 accepted: rebase steps 3/6 on scoring phase 2 (Open questions). N16 accepted: /compare unguarded by intent (Open questions). N17 accepted: specs first (step 5). N18 accepted: owner-visibility E2E (step 5).
