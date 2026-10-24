# Spec: web-MCP navigation safety (leave-/culling guard + `navigation_refused`)

## Objective + success criteria
- No UI-tool handler navigates the tab away from `/culling` while `plan.hasUnsavedDecisions()` is true; it throws `unsaved_decisions` (the code `ui_show_culling_plan` already throws) and `router.navigate` is not called.
- A navigation that stays on `/culling` (`ui_show_culling_group`, `ui_navigate {route:'/culling'}`, `ui_show_culling_plan`) is never blocked by that guard.
- Every `router.navigate` returning `false` reports `navigation_refused`, not `forbidden_level`. `forbidden_level` remains only for real permission checks (`!auth.isEdition()`, edition-only route).
- `navigation_refused` is in the client union, the server `TAB_ERROR_CODES`, the regenerated contract JSON, tool descriptions and the 7-language docs, all in one change.

## Established facts (evidence)
- `hasUnsavedDecisions()` (`assistant-cull-plan.service.ts:339`) = `decisionsProbe !== null && (probe() || hasUnconfirmedFlips())`. Manual decisions in the darkroom OR an unconfirmed plan group whose keepers were flipped.
- It is true only while `/culling` is mounted: the only probe registrant is `culling.store.ts:213` (`registerDecisionsProbe`), and its unregister runs on the store's `destroyRef.onDestroy`; off `/culling` the probe is null and the method returns false. So the guard needs no URL test of its own, but should still skip when the target is `/culling` itself.
- NO `canDeactivate` guard exists: `app.routes.ts:46-50` (`culling`) has only `EDITION_ONLY`; a grep for `canDeactivate|CanDeactivate` in `client/src/app` returns nothing. Therefore `router.navigate` resolves `true` and the decisions are silently dropped. The bug is real silent data loss on the unguarded handlers, NOT mis-reporting. (Item 2 mis-reporting is a separate defect: a `false` result comes from router cancellation/redirect, e.g. an `authGuard` or superseded navigation, not from permissions.)
- Navigation sites in `ui-tool-handlers.ts`: `ensureGalleryView` 195 (used by ui_set_gallery_filters l.344 and ui_show_photos l.362, and any search `show`), `leaveAlbum` 209 (only fires from `/album/*`, cannot be on /culling: needs only the code change), `ui_navigate` 333, `ui_open_photo` 396 (reports `not_found` on false), `ui_show_comparison` 515, `ui_show_culling_group` 530 (target /culling), `ui_show_culling_plan` 562 (target /culling).
- Server already forwards `unsaved_decisions` verbatim: `api/agent/show.py:130` maps tab code to `shown_in_tab.reason`, so a gallery `show` refused by the guard surfaces as `{"applied": false, "reason": "unsaved_decisions"}` with no server logic change (`navigation_refused` likewise becomes a reason, replacing today's misleading `forbidden`).
- `UI_TOOL_ERROR_CODES` (client) is asserted equal to `error_codes` in `ui-tools.schema.json` (`ui-tool-handlers.spec.ts:114`), and that JSON is generated from `TAB_ERROR_CODES` by `scripts/dump_ui_tools.py`.

## Files to create / change
- `client/src/app/core/agent/ui-tool.types.ts`, `ui-tool-handlers.ts`, `ui-tool-handlers.spec.ts`, `ui-tools.schema.json` (generated)
- `api/agent/ui_tools.py`, `tests/test_agent_ui_contract.py`, `tests/test_agent_bridge.py`
- `docs/AGENTS.md` + `docs/{fr,de,it,es,pt,zh}/AGENTS.md`

## Open questions / risks
- `ui_show_comparison` mutates `compareFilters` BEFORE navigating (l.510-513): the guard must run first so a refusal leaves no side effect.
- `ui_open_photo` today maps `false` to `not_found`; it becomes `navigation_refused` (the photo exists; the navigation was refused). Its existing spec expectations change.
- Guard must not trigger on `onSameUrlNavigation:'reload'` of `/culling` via `ui_navigate`.
- `ui_show_culling_plan`'s inline digest-based check stays (it protects plan replacement even when staying on /culling); do not fold it into the leave guard.
- Not decided here (out of scope): a router-level `canDeactivate` for user-driven navigation.

## Steps
1. Add `navigation_refused` to `UI_TOOL_ERROR_CODES` (client) and `TAB_ERROR_CODES` (server) and update the comment above `TAB_ERROR_CODES`.
   - key decision: one new code vs reusing `upstream_error`. default: new code `navigation_refused` (the JSON list is `sorted()` by the generator; do not hand-order it).
   - verify: `venv/bin/python scripts/dump_ui_tools.py` then `git diff` of `ui-tools.schema.json` shows only the added code (plus any description edits from step 4); the client spec at `ui-tool-handlers.spec.ts:114` passes.
   - affected files: `ui-tool.types.ts`, `api/agent/ui_tools.py`, `ui-tools.schema.json`.
2. Introduce `leaveCullingGuard(target?: string)` inside the handler factory, next to `requireGalleryView`: if `pathOf(router.url) === '/culling'`, the target is not `/culling`, and `plan.hasUnsavedDecisions()`, throw `UiToolError('unsaved_decisions', 'The user has decisions on the darkroom they have not confirmed; ask them to confirm or leave them first.')`. Extract that message to one constant and reuse it in `ui_show_culling_plan`.
   - key decision: guard in a shared helper vs inside each navigate. default: helper called BEFORE any state mutation and before `router.navigate`; one message constant (no duplicated string).
   - verify: new specs in step 5.
   - affected files: `ui-tool-handlers.ts`.
3. Apply the guard and swap the code:
   - `ensureGalleryView`: guard (only when `!isGalleryUrl`) then `navigation_refused` on false. Covers ui_set_gallery_filters, ui_show_photos, search shows.
   - `leaveAlbum`: `navigation_refused` only (no guard; cannot be on /culling).
   - `ui_navigate`: guard when `route !== '/culling'`, after the allowed/edition checks and before navigate; `navigation_refused` on false. Edition-only check at l.329 stays `forbidden_level`.
   - `ui_open_photo`: guard + `navigation_refused`.
   - `ui_show_comparison`: guard first, at the top after the edition check (before the `compareFilters` writes). `navigation_refused` on false.
   - `ui_show_culling_group` (l.530) and `ui_show_culling_plan` (l.564): no guard; `navigation_refused` on false.
   - key decision: where in `ui_show_comparison` the guard sits. default: right after the edition check, so no filter write happens on refusal.
   - verify: `grep -n "forbidden_level" ui-tool-handlers.ts` leaves only `!auth.isEdition()` / edition-only-route sites (l.329, 507, 527, 547, 586); `grep -n "router.navigate"` shows each of the 7 sites either guarded or documented as a stay-on-/culling target.
   - affected files: `ui-tool-handlers.ts`.
4. Server text: add `navigation_refused` and the "refused with `unsaved_decisions` when it would leave /culling" behaviour to the descriptions of the navigating UI tools in `api/agent/ui_tools.py` (ui_navigate, ui_open_photo, ui_show_photos, ui_set_gallery_filters, ui_show_comparison) and the shown_in_tab reason list in `api/agent/tools_culling.py:56` / `tools_read.py:76` if they enumerate reasons. Regenerate the JSON.
   - key decision: how much prose. default: one short clause per tool, no new tool arguments.
   - verify: `venv/bin/python -m pytest tests/test_agent_ui_contract.py tests/test_agent_bridge.py tests/test_agent_show.py -q` (contract JSON freshness test included).
   - affected files: `api/agent/ui_tools.py`, `api/agent/tools_culling.py`, `api/agent/tools_read.py`, `ui-tools.schema.json`.
5. Tests.
   - `ui-tool-handlers.spec.ts` CHANGE: l.153-155 (`reports a refused navigation as forbidden_level`) -> `navigation_refused`; the `ui_open_photo` false-navigation case (not_found) -> `navigation_refused`; keep l.143/262/267/292/879/934/1071/1118 (`forbidden_level` permission cases).
   - ADD (use `plan.registerDecisionsProbe(() => true)` with `router.url='/culling'`, as in the existing l.970 test): for each of ui_navigate('/stats'), ui_open_photo, ui_show_photos, ui_set_gallery_filters (via ensureGalleryView), ui_show_comparison: result `{ok:false,error:'unsaved_decisions'}`, `navigate` not called, and for comparison `compareFilters` untouched. ADD flipped-unconfirmed-group variant once (as l.975). ADD negatives: probe true + `ui_navigate('/culling')`, `ui_show_culling_group`, `ui_show_culling_plan` same digest do navigate/succeed; probe false/null on /culling navigates normally; probe true but `router.url='/stats'` navigates. ADD `navigation_refused` for ensureGalleryView, leaveAlbum, ui_show_comparison, ui_show_culling_group, ui_show_culling_plan with `navigate.mockResolvedValueOnce(false)` (the plan case also still calls `plan.clear()`).
   - `assistant-cull-plan.service.spec.ts` (l.151-169) already covers the predicate: no change.
   - Python: `tests/test_agent_ui_contract.py:101` extend the set with `navigation_refused`; `tests/test_agent_bridge.py:725` add `navigation_refused` to the passthrough tuple; `tests/test_agent_show.py` add a case that a tab `navigation_refused` / `unsaved_decisions` reply yields `shown_in_tab.reason` of the same name.
   - Failing-first: write the new client specs and run them before steps 2-3 to see them fail.
   - affected files: the spec/test files above.
6. Docs, same change, 7 languages. No doc lists the UI error-code set; the closest surfaces are `docs/AGENTS.md` l.127 (the `no_active_view` note on UI tools) and l.261 (`shown_in_tab` reasons incl. `unsaved_decisions`). Add one sentence at l.127: a UI tool that would leave `/culling` while the user holds unconfirmed decisions answers `unsaved_decisions`; a navigation the tab itself refuses answers `navigation_refused`; `forbidden_level` is only a permission refusal. Mirror in `docs/{fr,de,it,es,pt,zh}/AGENTS.md` (same line numbers) keeping code identifiers untranslated. The `forbidden_level` lines at l.41/42/273 describe server-tool token levels and stay unchanged.
   - verify: `venv/bin/python scripts/docs_parity.py && venv/bin/python scripts/docs_xlinks.py`; `venv/bin/python scripts/audit_i18n.py` (not affected, run for safety).
   - affected files: `docs/AGENTS.md`, `docs/{fr,de,it,es,pt,zh}/AGENTS.md`.

## Final verification gate
- `cd client && npm run test` (max 2 workers), `npx tsc --noEmit -p tsconfig.app.json && npx tsc --noEmit -p tsconfig.spec.json`, `npx ng lint`.
- `venv/bin/python -m pytest tests/test_agent_ui_contract.py tests/test_agent_bridge.py tests/test_agent_show.py tests/test_agent_culling.py -q`, `venv/bin/python -m ruff check .` (use /home/ncoevoet/work/photoscore/venv).
- `cd client && npm run gen:api` not needed (no REST schema change); `git status --porcelain` shows no stale generated JSON after re-running `scripts/dump_ui_tools.py`.
- Manual (optional, E2E harness): on /culling flip a group, ask the assistant to `search_photos` with show; tab stays, reason `unsaved_decisions`.

## Adversarial review
- Not run (spec-only task). Premise checked against the tree: the task's claim that a route guard might exist is false (none); the client message to user is unchanged.

## Adversarial review (opus, 2026-10-23) — adjudicated; these OVERRIDE earlier steps
- **B1 accepted.** `ui-tool-handlers.spec.ts` l.258-262 and l.1069-1072 are refused-navigation tests → expect
  `navigation_refused`. Real permission tests (l.143, 292, 879, 934, 1118) keep `forbidden_level`.
  `ui_open_photo` refusal test does not exist: ADD one (navigate→false ⇒ `navigation_refused`).
- **G1 accepted.** Update prose that says a show leaves /culling: `api/agent/server.py:62` INSTRUCTIONS,
  `api/agent/tools_read.py:75` SHOW_RULE, `docs/AGENTS.md:73` + 6 translations → "leaves /culling only
  when it has no unconfirmed decisions; otherwise refused with `unsaved_decisions`". Add
  `tests/test_agent_prompts.py` to the gate and update its assertion if it pins the old text.
- **G2/G3 accepted.** `docs/AGENTS.md:71` shown_in_tab reason list and `:273` error-code list (all 7
  languages) gain `unsaved_decisions` and `navigation_refused` (l.273 also `no_active_view` if absent).
- **G4 accepted.** In `ui_show_culling_group` (~529-531) and `ui_show_culling_plan` (~561-564): when the tab
  is already on /culling, a `false` from router.navigate is a same-URL skip, not a refusal — handle it like
  `ui_show_comparison` (~513-514) does (do not throw, do not `plan.clear()`); add a test for each.
- **G5 out of scope** (pre-existing: re-navigating to /culling drops the scope query); note only.
- **N1:** step 3's verify is the step-5 vitest per guarded handler (each must fail if its guard is removed).
- **N2 risk:** check-then-act — a decision made while a lazy chunk loads is still lost; only a route
  `canDeactivate` would close it (out of scope).
- **N3 out of scope:** user-clicked navigations (`assistant-activity-chip.component.ts:98`, `app.ts:608`).
