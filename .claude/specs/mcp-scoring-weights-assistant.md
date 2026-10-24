# Spec: let the Facet MCP assistant explain scores and tune category weights

Two phases, each its own commit. Phase 1 reads and previews only (nothing it calls writes). Phase 2 writes
(edition level, confirmation, snapshot-backed). Written against the tree as of 2026-10-23 on
`tmp/web-mcp-improvements`. Anything not read in the code is marked UNVERIFIED.

## Decisions (binding)

User decisions of 2026-10-23, plus orchestrator defaults. They override anything below that reads otherwise.

1. `category_weights` and `facet://scoring-weights` are EDITION only (open question 9 is closed: no readonly variant).
2. `POST /api/scan/recompute` gains the optional `category` field (step 8) and `npm run gen:api` is run and committed.
   `recompute_scores` supports `category` AND `all`; the "`all` only" fallback is deleted.
3. `preview_weights` stays approximate and says so in BOTH the payload (`basis: "approximate"`, plus a one-line
   `basis_note`) and the tool description. `preview_score` is not modified.
4. `misassigned_categories` is a v1 heuristic, labelled `confidence_basis: "heuristic"` in the payload and in the description.
   Overrides happen only through `override_categories` with dry run + `confirm` + `expected_count`.
5. Weight validation is EXACTLY the server's `update_weights` rule, no stricter: `_validate_weight_dict`
   (api/routers/comparison.py:106-116) requires each value numeric, 0..100 inclusive, and `bonus` numeric in -5..5;
   `UpdateWeightsBody` (comparison.py:119-126) requires `category` and `weights`, and the route 400s on empty weights.
   The server enforces NO sum rule and NO key-set rule. So the tools do NOT refuse a sum other than 100 nor an unlisted key.
   They report `weights_sum` and `warnings` (`sum_outside_95_105`: the config loader auto-normalises outside +-5,
   `NORMALIZATION_TOLERANCE`, config/scoring_config.py:24 and :410; `unknown_key`: stored verbatim, dropped as "not a valid
   weight" by a validating load, config/scoring_config.py:~478) in the preview and the apply result.
   The only extra refusal kept is `bonus`/modifiers/filters, which is a route-defect guard, not a stricter weight rule
   (preview_score divides `bonus` by 100; update_weights would store it under `weights`, not `modifiers.bonus`).
   Open point for the user, not decided here: an unknown key is a stored typo; the spec follows the directive (warn, do not refuse).
6. Step 11 (`ui_show_comparison` `tab` argument) is INCLUDED in Phase 2.
7. `explain_score` is NOT added to `CORE_TOOLS`; the "11-tool set" docs sentence is unchanged.

Adjudicated review decisions (2026-10-23, after the adversarial review; each is expanded in its step and listed under
`## Adversarial review`):
- B1: the tool sends `preview_score` the FULL proposed vector normalised exactly like `ScoringConfig.get_weights`
  (config/scoring_config.py:604-639: `*_percent / 100`, then divided by the sum when it is not 1.0 +-0.001). Rank shifts are
  the primary output, mean shift secondary, and the payload states the `min(10, ...)` clamp.
- B2: `preview_score` IS fixed (this deviates slightly from decision 3's "no change to preview_score": the route was wrong, not
  only approximate): its `weight_map` (comparison.py:908-930) covers every `VALID_WEIGHT_COLUMNS` key (config/category_filter.py:74-92).
  The payload still says `basis: "approximate"` (no normalisation snapshot, penalties, fold/renormalise).
- B3: `restore_weight_snapshot` refuses a snapshot that is not in `*_percent` format -> `unsupported_snapshot`.

Resolved by reading the code:
- `call_timeout_s` is a number in [1, 300] (config/scoring_config.schema.json, `viewer.mcp`), default 30.
- No test pins the `CORE_TOOLS` size; the profile tests are in `tests/test_agent_visibility.py`
  (`test_a_tool_hidden_by_the_core_profile_is_still_callable`, `test_an_unknown_profile_falls_back_to_full`).
- Tab error codes are the closed set `TAB_ERROR_CODES` (api/agent/ui_tools.py:37), mirrored by `UI_TOOL_ERROR_CODES`
  (client/src/app/core/agent/ui-tool.types.ts:9): `invalid_input`, `not_found`, `forbidden_level`, `no_active_view`,
  `upstream_error`, `too_large`, `unsaved_decisions`, `navigation_refused`, `plan_changed`, `plan_load_failed`, `no_plan`.
- `category_weights` pads dicts of a ScoringConfig built by `server_scoring_config()` (api/config.py:100);
  `get_categories()` returns that instance's own dicts (config/scoring_config.py:1454-1462), so the padding touches a per-call
  object. Whether `server_scoring_config` caches the instance is UNVERIFIED.
- Single-photo selection: `target.read_selection(registry, resolved, settings, tab_id)` (api/agent/target.py:69) returns
  `(refusal, TabSelection)` with `.scope` (`paths`|`view`), `.count`, `.paths`, `.filters`.

## Objective + success criteria

- Phase 1 (read/preview, no writes):
  - P1.1 `explain_score` returns, for one photo, its category, stored aggregate, per-metric
    `{metric_key, value, weight_percent, contribution}` (top N), strengths/weaknesses and the category reason, in a
    compact payload. It never runs the VLM and never writes.
  - P1.2 `category_weights` returns a category's (or every category's) non-zero weights, modifiers, filters and
    priority; it is invisible below `edition` and `status.hidden_tools` counts it. A `facet://scoring-weights`
    resource carries the same, listed only to keys that may call the tool.
  - P1.3 `preview_weights` validates a proposed change with the server's own rules plus the sum/key rules below, samples N
    photos of the category, and returns mean score shift, rank changes and a single-use `preview_digest`.
    No route it calls writes. A missing or stale digest is what makes Phase 2 refuse.
- Phase 2 (writes, edition, confirmation):
  - P2.4 `apply_weights(category, weights, preview_digest)` writes only when the digest matches the CURRENT weights plus
    the proposal; says scores are stale until recomputed; reads the result back.
  - P2.5 `list_weight_snapshots` / `restore_weight_snapshot` (dry run + `confirm`); the restore is itself undoable.
  - P2.6 `recompute_scores` starts a background recompute and returns at once; `recompute_status` follows it. One job at a
    time; refused while the gallery index build or any library job holds the lock; never `outcome_unknown` from a slow job.
  - P2.7 `learned_weights` reads the comparison-learned suggestion, honouring `available:false`
    (including `unavailable_if_external`) and `suggest_changes:false`; applying it goes through preview -> apply.
  - P2.8 `misassigned_categories` lists likely-wrong categories with the signal named (heuristic, UNVERIFIED as a
    probability); `override_categories` batch-pins them with dry run + `confirm` + `expected_count`.
- Cross-cutting, each independently testable:
  - Nothing in `api/agent` writes `scoring_config.json` except by calling `POST /api/config/update_weights` and
    `POST /api/config/restore_weights` (routes own `CONFIG_WRITE_LOCK`, the auto snapshot and `write_user_config`).
  - Every new route enters `ROUTE_ALLOWLIST` deliberately, with `tests/test_agent_comparison.py` updated and justified.
  - Every new tool: level recorded in `TOOL_LEVELS`, write tools `write=True`, listed in an `ACTIONS` row, described in
    `INSTRUCTIONS`, documented in `docs/AGENTS.md` and its six translations, covered by a failing-first test.
  - No agent write records a comparison or arms the retrain (`tests/test_agent_taste_isolation.py` stays green).

## Files to create / change

Create:
- `api/agent/tools_scoring.py` - registers all new tools (one module, like `tools_corrections.py`; `tools_write.py` is
  already 813 lines). Holds `SCORING_TOOL_LEVELS`; `tools_write.WRITE_TOOL_LEVELS` is the documented single table, so
  the levels are added THERE (see step 1) and imported here, exactly as `tools_corrections.py` does.
- `api/agent/weights.py` - pure helpers (no I/O): `validate_proposal`, `resulting_vector`, `shape_weights`,
  `rank_changes`, `proposal_digest_options`. Keeps the tool module thin and unit-testable.
- `tests/test_agent_scoring.py` - tools through `agent_app` (real auth chain), Phase 1 first.
- `tests/test_agent_weights_helpers.py` - the pure helpers.

Change:
- `api/agent/internal_client.py` - allowlist entries: `critique` (GET /api/critique, readonly), `category_weights`
  (GET, edition), `preview_score` (POST, edition, NOT write), `learned_weights` + `weight_confidence` (GET, edition),
  `weight_snapshots` (GET, edition), `update_weights` (POST, edition, write), `restore_weights` (POST, edition, write),
  `recompute_start` (POST /api/scan/recompute, edition, write), `recompute_status` (GET /api/scan/recompute_status,
  edition), `photos_by_paths` already exists.
- `api/agent/tools_write.py` - add the new tool names to `WRITE_TOOL_LEVELS`; none of their code lives here.
- `api/agent/server.py` - call `register_scoring_tools`; extend `INSTRUCTIONS`; `fill_tool_levels` must see the new names.
- `api/agent/actions.py` - new `Action` rows (`explain_scores`, `tune_weights`, `recompute_scores`, `fix_categories`).
- `api/agent/resources.py` - `facet://scoring-weights` (six resources, was five).
- `api/agent/requirements.py` - `critique_available` predicate (feature flag `viewer.features.show_critique`).
- `api/agent/live_updates.py` - classify `update_weights`, `restore_weights`, `recompute_start` in
  `NO_PHOTO_EFFECT_TOOLS` (the table is walked by `tests/test_agent_live_updates.py`; an unclassified write route fails CI).
- `api/agent/tools_corrections.py` - `override_categories` (next to `override_category`, reusing `photo_io.apply_category`).
- `api/routers/scan.py` - `RecomputeRequest.category: Optional[str] = None`; `_spawn_fixed_library_job` takes the argv
  tail (Phase 2, step 7). Changes the OpenAPI schema.
- `client/src/app/core/api/schema.d.ts` - regenerated by `cd client && npm run gen:api` (step 7 only).
- `api/agent/ui_tools.py`, `client/src/app/core/agent/ui-tools.schema.json`, `ui-tool.types.ts`, `ui-tool-handlers.ts`,
  `ui-tool-handlers.spec.ts` - ONLY if the optional UI step (11) is taken.
- `client/src/app/core/agent/ui-tools.schema.json` is also regenerated (`scripts/dump_ui_tools.py`) whenever `ACTIONS`
  changes, because `render_client_actions` writes the table into it - so steps 4, 8 and 12 regenerate it even though no UI tool changes.
- Tests to update: `tests/test_agent_comparison.py` (`ALLOWED_COMPARISON` and the "exactly the reviewed set" assertions),
  `tests/test_agent_resources.py` (five -> six), `tests/test_agent_actions.py` (drift test), `tests/test_agent_visibility.py`,
  `tests/test_agent_live_updates.py`, `tests/test_scan.py` (`TestRecompute`: category body), `tests/test_open_install_refusal.py`
  (unchanged route set; re-run only), `tests/test_agent_taste_isolation.py` (re-run; add an apply_weights case).
- Docs: `docs/AGENTS.md` and `docs/{fr,de,it,es,pt,zh}/AGENTS.md` (tool counts, levels table, new section "Scoring and
  weights", resources count). `docs/SCORING.md` + translations get one cross-link paragraph. There is NO `docs/MCP*.md` in this
  tree: `docs/AGENTS.md` is the single agent doc. `docs/CONFIGURATION.md` only if a setting is added (none planned).

## Open questions / risks

1. **`preview_score` is not the real scorer, and the first design did not cancel the difference (review B1).** The route
   (comparison.py ~868-955) takes the baseline from `config.get_weights(category)`, which is NORMALISED to sum 1.0 and carries
   the modifiers (config/scoring_config.py:604-639), then overwrites only the supplied keys with the RAW `value / 100`
   (comparison.py:899-904), then clamps with `min(10, ...)`. A proposal of 4 keys therefore mixes a normalised baseline with raw
   overrides, and the baseline-vs-proposal difference does not cancel the formula. Decision: the tool sends the FULL proposed
   vector, every key explicit, already normalised to the `get_weights` basis (so the route's `/100` reproduces exactly the
   decimals `get_weights` would give for that config). The normalisation is extracted from `get_weights` into one helper
   (`normalise_percent_weights`, config/scoring_config.py) and `get_weights` calls it - no second copy. No such helper exists
   today (searched: only the inline block above and the loader's `normalize_weights_to_100`, which targets 100 and
   tolerance 5, a different rule). Output order: rank changes first, mean shift second, and `clamp_note` says scores are
   capped at 10, so a shift on a photo at the cap understates. `original_score` / `delta` from the route are not used.
   The real exact path (`_calculate_breakdown`) takes no custom weights; making the route exact stays a follow-up.
2. **`bonus` in `preview_score` is wrong by x100.** The route divides EVERY supplied value by 100, `bonus` included
   (`weights[key] = value / 100`), while `_validate_weight_dict` allows -5..5 for it. UNVERIFIED whether `get_weights`
   returns the bonus in the same unit. Decision: both `preview_weights` and `apply_weights` REFUSE a `bonus` key
   (`invalid_input`: "bonus and modifiers are not editable through the assistant"). Also because `update_weights` would
   write `bonus` into `weights`, not `modifiers.bonus`. Modifiers/filters are never sent (so `backup` stays False).
3. **No sum or key rule on the server (decision 5).** `_validate_weight_dict` checks numeric and 0..100 (bonus -5..5) only and
   accepts ANY key, so a typo is stored and a sum of 96 is stored; the loader later rescales outside +-5 and drops invalid keys.
   Tools follow the server exactly and surface `weights_sum` and `warnings` instead of refusing.
4. **`/api/recalculate` and `/api/stats/categories/recompute` are synchronous** (up to 300 s, `asyncio.wait_for`), and
   `call_timeout_s` defaults to 30 s (schema bound 1..300). A write route that times out is reported as
   `outcome_unknown` by `InternalClient._timed_out`. They cannot back a tool. The async machinery that exists is
   `POST /api/scan/recompute` + `GET /api/scan/recompute_status`, but it recomputes the WHOLE library
   (`--recompute-average`, which also runs bursts and sequence detection). Per-category needs the one server change in step 7.
   Decision 2 takes the server change; there is no fallback.
5. **Status is per process.** `_scan_state` is a module global; `recompute_status` falls back to the cross-process lock
   holder (`running`, unknown progress) on another worker. docs already require `--workers 1` for `ui_*` tools; same caveat.
6. **Snapshots are best effort.** `record_category_snapshot` swallows failures with a warning and the write proceeds.
   So "undo available" must be VERIFIED by reading the newest snapshot after the write, not assumed (steps 4, 6).
7. **Restore DOES snapshot first** (confirmed, comparison.py ~1578-1610: `update_category_weights(..., 'auto:pre_restore', ...)`
   before overwriting; `apply` snapshots with `'auto:edit'`). A restore therefore is undone by restoring the newest snapshot.
   A snapshot whose `category_bonus` is NULL restores weights only.
8. **No category-confidence signal exists.** `photos.category` is first-match-wins over a priority sort
   (`determine_category`); nothing stores a margin or score. What exists: `/api/critique` recomputes the category under the
   CURRENT config (`category` vs the stored one) and lists `category_reason.rejected` (higher-priority categories that
   rejected the photo, each with the first failing filter and its actual value); `CategoryFilter.explain_mismatch`;
   `POST /api/comparison/suggest_filters`; `/api/stats/categories/overlap` (counts only). `misassigned_categories` is therefore
   a HEURISTIC and says so; UNVERIFIED as a precision claim. A "stale" hit (stored != current-config category) is a recompute
   job, not an override. A calibrated detector would need a new server route and is a follow-up.
9. **(Closed by decision 1.)** `library_stats(kind=category_weights)` already exposes weights at `readonly`** (`/api/stats/categories/weights`).
   `category_weights` at `edition` adds modifiers, filters and priority (edition-gated on the comparison router). Question
   for the user: keep the new tool edition-only (planned) or also allow readonly with the stats route? Default: edition.
10. **Live-update sink.** `InternalClient._notify_write` is called for every write route; `changed_paths` must return `None`
    (tab reloads) or the tool must be in `NO_PHOTO_EFFECT_TOOLS`. UNVERIFIED what a tab does on a weights change; default:
    nothing (classified as no photo effect). A `/compare` tab does not auto-refresh its weights tab.
11. **Rate limits / cost.** `preview_weights` costs 2N in-process requests (N <= 100, default 30, concurrency 4 like
    `cull_report`'s `COUNT_CONCURRENCY`). `misassigned_categories` costs up to `scan` critique calls (default 100, cap 200).
    `learned_weights` runs the optimizer synchronously: UNVERIFIED runtime; read-only so a longer timeout is safe (120 s,
    same pattern as `EXPORT_METADATA_TIMEOUT_S`); `use_cv`/confidence are opt-in.
12. **Digest semantics.** The "preview digest" is the existing single-use `nonce` (`api/agent/nonce.py`: TTL 300 s, per
    owner, 16 pending, in-memory per process) bound to `{category, current vector, resulting vector}`. A restart or a second
    worker loses it (apply then answers `confirmation_required`; re-preview). This is accepted and documented.
13. **Name collisions.** `apply_weights`, `preview_weights`, `learned_weights`, `recompute_scores` do not collide with the
    existing tools (`status`, `scan_status`, `comparison_status`, `override_category`...). The comparison regexes in
    `test_no_registered_tool_is_a_comparison_writer` (`(submit|record|answer).*(comparison|pair)`) do not match any new name.
14. **The `user` level.** All new tools are `readonly` or `edition`; none is a `user` tool, so the single-password-install
    note about `user` is unaffected.

## Steps

### Phase 1 - read and preview (one commit: `feat(assistant): explain scores and preview weight changes`)

1. **Tool-level table, module skeleton and pure helpers.**
   - description: add the Phase 1 names to `WRITE_TOOL_LEVELS` (`explain_score: readonly`, `category_weights: edition`,
     `preview_weights: edition`); create `tools_scoring.py` with `register_scoring_tools(server, client, registry)` and
     `weights.py` with the pure functions; call the registrar from `server.py`.
   - key decision: where the level lives. Default: `WRITE_TOOL_LEVELS` (the documented "one table holds every non-darkroom
     level"; a test walks it), though the Phase 1 tools do not write, because `tools_corrections.py`/`tools_report.py` already
     put `group_compare`/`cull_report` (readonly) there.
   - verify: `venv/bin/python -m pytest tests/test_agent_actions.py tests/test_agent_visibility.py -q` stays green with the
     names registered; new `test_agent_weights_helpers.py` fails first (import error) then passes.
   - affected files: `api/agent/tools_write.py`, `api/agent/tools_scoring.py`, `api/agent/weights.py`, `api/agent/server.py`,
     `tests/test_agent_weights_helpers.py`.

2. **`explain_score` (P1.1).**
   - description: `explain_score(path=None, target=None, top_n=5, tab_id=None)`; exactly one of `path`/`target="selection"`.
     Calls `critique` (`GET /api/critique?path=..&mode=rule`) - `mode` is hard-coded to `rule` (never `vlm`: GPU, and it
     writes `vlm_critique` into `photos`). Shapes: `{path, category, category_reason:{reason_key, details, rejected[:3]},
     stored_aggregate, current_formula_score, stored_matches_current, breakdown:[top_n of {metric_key, value,
     weight_percent, contribution}], rest:{count, contribution}, strengths, weaknesses, penalties, distortions,
     normalization_basis, explanation_unavailable_reason?, note}`. `weight_percent = round(weight*100, 1)`.
   - key decision: selection handling. Default: read the tab selection through `target.read_selection(registry, resolved, settings, tab_id)`
     (target.py:69, verified); `selection.count != 1` -> `invalid_input("explain_score takes one photo; the selection holds N")`;
     scope `paths` uses `selection.paths[0]`; scope `view` with count 1 expands through the existing `photos_paths` route.
     `resolve_selection` is not reused (it builds write-route bodies).
   - key decision: which weights are reported. The route returns EFFECTIVE weights (after `fold_quality_weight` and
     `renormalise_weights` for metrics unavailable in this config), not the configured `*_percent`. The result says
     `weights: "effective"` so the model does not compare them to `category_weights` literally. `contribution` is in score
     points of 10; the sum plus `native_adjustment` equals `current_formula_score`.
   - key decision: gating. Add `critique_available(resolved, settings)` in `requirements.py` reading
     `VIEWER_CONFIG['features']['show_critique']` (default true, the route's own test) so the tool is hidden (registered with `requires=` so it lands in `tools_common.TOOL_REQUIRES`, review G5; `misassigned_categories` is registered with the same predicate because it calls the critique route) and reported in
     `hidden_tools.disabled` rather than failing with a 403 that `_is_config_refusal` maps to `feature_disabled`
     ("Critique feature is disabled" contains "disabled"). Both paths are tested.
   - `explanation_unavailable_reason` (missing/invalid scoring inputs, no normalisation snapshot) is returned as `ok` data with
     that reason and an empty breakdown, never invented.
   - Level `readonly`: the route is `get_optional_user`, visibility is the caller's, and the same weights are already public
     through `/api/stats/categories/weights`.
   - verify (failing first): seed a photo with known metrics via `seed_photos_prefix`; assert breakdown sorted by contribution,
     `len(breakdown) <= top_n`, `rest.count` makes up the remainder, `weight_percent` sums (with rest) to ~100, a non-existent
     path -> `not_found`, `show_critique=false` -> tool absent from `tools/list` and `feature_disabled` on a direct call,
     selection of 2 -> `invalid_input`, an unauthenticated token -> `forbidden_level`; assert no `photos` row changed
     (`vlm_critique` stays NULL) and that the request carried `mode=rule`.
   - affected files: `api/agent/tools_scoring.py`, `api/agent/internal_client.py`, `api/agent/requirements.py`,
     `tests/test_agent_scoring.py`.

3. **`category_weights` tool and `facet://scoring-weights` resource (P1.2).**
   - description: `category_weights(category=None)` calls `category_weights` (`GET /api/comparison/category_weights`,
     edition). One category: `{category, weights:{<key>_percent: n} non-zero only, weights_sum, modifiers, filters,
     priority, zero_keys_count}`. No category: `{categories:[{name, priority, weights (non-zero), bonus}]}` capped by
     `max_rows`. The resource `facet://scoring-weights` reuses the all-categories reader with `required=("category_weights",)`,
     which `resources.list_resources` already filters through `prompts.visible_tools`, so it is hidden below edition for free.
   - key decision: reuse vs extend `facet://scoring-contexts`. Default: ADD a separate resource and leave scoring-contexts
     untouched (contexts are a delta over priority order; mixing weights into it changes a documented shape).
   - key decision: the route pads every valid weight key with 0 and may mutate the dict it got from
     `config.get_categories()` (UNVERIFIED whether that is a copy). The tool drops zero keys and never relies on the padding,
     and exposes `configured_keys` (the keys present in the stored config) plus `valid_keys` = `VALID_WEIGHT_COLUMNS` as `<name>_percent` (config/category_filter.py:74-92), NOT the route's `METRIC_NAME_MAPPING`-based padding (review G7); only when a category is named.
   - verify (failing first): edition token lists the tool and the resource; readonly token does not, `status.hidden_tools`
   - N18: `resources.read_resource` authorises (bearer, rate limit) but does NOT check `spec.required` against the key's level
     (only `list_resources` filters): a readonly key that knows the URI could read `facet://scoring-weights`. Fix in `read_resource`:
     refuse when `set(spec.required) - prompts.visible_tools(resolved, settings)` is non-empty, with the same `MCPError` family as
     an unknown resource. Test (fails first): a readonly token `read_resource("facet://scoring-weights")` -> error; edition ok; and
     the same check applied to the five existing resources does not change their results.
     counts it, direct call -> `forbidden_level`; resource read returns the same non-zero weights as the tool; unknown category
     -> `not_found`; an `edition` read changes nothing (config file bytes unchanged).
   - affected files: `api/agent/tools_scoring.py`, `api/agent/resources.py`, `api/agent/internal_client.py`,
     `tests/test_agent_scoring.py`, `tests/test_agent_resources.py`.

4. **`preview_weights` (P1.3).**
   - description: `preview_weights(category, weights=None, deltas=None, sample=30)`; exactly one of `weights` (partial map
     merged over the current weights, `*_percent` or bare keys) or `deltas` (signed percentage points added to the current
     values). Steps: (a) read current weights via `category_weights`; (b) build the resulting vector (`weights.py`); (c)
     validate exactly like the server (decision 5: numeric, 0..100, non-empty) plus: the category exists and no
     `bonus`/modifier keys; `invalid_input` lists every issue; a sum outside 95..105 or an unknown key is a `warnings` entry only; (d) sample;
     (e) per sampled photo call `preview_score` twice with the FULL vector each time: baseline = the current weights normalised by the same helper, proposal = the proposed vector normalised by it (never `weights={}`, never a partial map; review B1); (f) aggregate; (g) issue the digest.
   - key decision: the sample. Default: ONE `search_photos` page (`category=<c>`, sort `aggregate` desc, `per_page`=100,
     `hide_rejected=1`, every other hide toggle 0 so bursts/brackets are not under-sampled) and take `sample` rows at EVENLY
     SPACED ranks (deterministic, covers the whole range, no RNG so a repeat is comparable). `sampled_of` reports the category
     total; if the category has more than 100 visible photos the sample covers only the top 100 by aggregate and the result
     says `sample_scope: "top_100_by_aggregate"` - a selection bias the user must be told about. The alternative (a second page
     from the bottom) is cheap: default to taking half from the top page and half from a `sort_dir=asc` page. UNVERIFIED that
     `search_photos` exposes an ascending aggregate sort; if not, state the bias instead.
   - output: `{category, basis:"approximate", basis_note, warnings, weights_sum, sampled, sampled_of, proposal:{changed:{key:{from,to}}, sum}, mean_shift,
     median_shift, max_up, max_down, rank_changes:{moved_up, moved_down, unchanged, biggest:[{path, from_rank, to_rank,
     delta}] (<=5)}, stale_note, preview_digest, preview_digest_expires_in_s}`. `rank_changes` is computed within the sample by
     ranking baseline vs proposed scores (ties keep path order).
   - key decision: the digest. Default: `nonce.issue(grant.nonce_owner, "apply_weights", nonce.digest([], options))` with
   - key decision (B1/B2): what the preview is built on. Default: the helper `normalise_percent_weights` (extracted from
     `ScoringConfig.get_weights`, which then calls it) and the fixed `weight_map`. The server fix, in `api/routers/comparison.py`:
     `weight_map` gains every `VALID_WEIGHT_COLUMNS` key missing today (12 of the 31 valid keys are absent: `face_sharpness`,
     `power_point`, `saturation`, `noise`, `qrealign`, `aesthetic_v25`, `deqa`, `symmetry`, `balance`, `edge_entropy`, `fractal`,
     `color_harmony` - verify the exact list when implementing), each mapped to the SAME stored column and transform the real scorer
     reads (`processing.scorer.build_metric_vector` / `WEIGHT_TO_COLUMN`; read them, do not guess a column). This also fixes the
     /compare weights tab preview. A key the scorer only enables behind a flag (`iqa_extended`) keeps contributing 0 when the column
     is NULL, as `value or 0` already does. Rejected: leaving the route alone and refusing those keys in the tool (a user could not
     preview most of the config).
     `options={"category", "current": <full current vector>, "resulting": <full resulting vector>}`. Nothing is issued for an
     invalid proposal or a zero-shift proposal (nothing to apply: `changed` empty -> `invalid_input("no change")`).
   - key decision: failure mid-sample. A `not_found`/error on a photo is skipped and counted in `skipped`; if more than 20%
     skip, return `upstream_error` instead of a skewed mean. No route called here writes, so a timeout is a plain upstream error
     (`preview_score` is `write=False` in the allowlist, like `cull_apply.preview`).
   - tool description says "approximate preview" and tells the model: show the user the proposal, the shift and the bias note; the digest is not consent.
   - verify (failing first): a partial proposal of 2 keys must give the same shifts as the equivalent full vector (this fails on the old baseline-vs-raw design); a proposal summing to 80 or 120 is normalised before the route, so its shifts equal those of the rescaled vector; table tests on the helpers (sum 99/101 and an unknown key accepted WITH warnings, `bonus` refused, negative, >100, deltas pushing a key
     below 0, `weights` and `deltas` both given); tool test with 3 seeded photos asserting `rank_changes` and `mean_shift` equal values computed independently by the real scorer path (`Facet.calculate_aggregate_logic` on the same rows under the old and the new weights, comparing RANKS exactly and means within the clamp/penalty tolerance the payload documents) - NOT the hand-computed
     weighted-sum difference (the old check locked the non-cancelling behaviour and is dropped), that the config file bytes and the `weight_config_snapshots` row count are unchanged after the
     call, that a second preview issues a second digest and the first still lives (<=16), a readonly token is refused before any
     route call (patched `InternalClient` call counter == 0), and that `bonus` is refused.
   - affected files: `api/agent/tools_scoring.py`, `api/agent/weights.py`, `api/agent/internal_client.py`,
     `tests/test_agent_scoring.py`, `tests/test_agent_weights_helpers.py`.

5. **Phase 1 wiring, docs and contract tests.**
   - description: `ACTIONS` rows `explain_scores` (`explain_score`; `_when("detail","gallery","selection")`) and `tune_weights`
     (`category_weights`, `preview_weights`; `ANY`); `INSTRUCTIONS` sentence ("explain_score reads why a photo scored what it
     did; category_weights and preview_weights read and dry-run the scoring weights - nothing changes until apply_weights");
     update the tool-count sentences and the levels table in `docs/AGENTS.md` and the six translations (`fr de it es pt zh`),
     the resources line (six), and a "Scoring and weights" section; a cross-link in `docs/SCORING.md` (and translations).
     Regenerate `ui-tools.schema.json` with `scripts/dump_ui_tools.py` (ACTIONS changed).
   - key decision: whether `INSTRUCTIONS` duplicates the docs. Default: one sentence in `INSTRUCTIONS` (it is sent on every
     session, so it stays short); detail lives in each tool's description and in `docs/AGENTS.md`.
   - verify: `test_agent_actions.py` drift test (every ACTIONS tool is registered, levels match), `test_agent_prompts.py`,
     `test_agent_resources.py` (six), `test_agent_comparison.py` with `ALLOWED_COMPARISON` extended by exactly
     `/api/comparison/category_weights` and `/api/comparison/preview_score` (reads/previews; the two assertions
     `test_no_route_spec_reaches_a_comparison_write` and the string-constant walk still hold because neither matches
     `FORBIDDEN`), a test that loads `ui-tools.schema.json` and asserts `["actions"]` equals `render_client_actions()` and `version` equals `tools_version()` (fails if the dump was not re-run), a grep check over the 7 AGENTS.md files that each names every new tool (`for t in explain_score category_weights preview_weights ...; grep -c "$t" docs/AGENTS.md docs/*/AGENTS.md` all >= 1) and carries the same number of `|` table rows per language (the docs scripts are not used; they were not read and may not cover AGENTS.md),
     `venv/bin/python -m ruff check .`.
   - affected files: `api/agent/actions.py`, `api/agent/server.py`, `api/agent/resources.py`,
     `client/src/app/core/agent/ui-tools.schema.json`, `docs/AGENTS.md`, `docs/{fr,de,it,es,pt,zh}/AGENTS.md`,
     `docs/SCORING.md`, `docs/{fr,de,it,es,pt,zh}/SCORING.md`, `tests/test_agent_comparison.py`, `tests/test_agent_actions.py`,
     `tests/test_agent_resources.py`, `tests/test_agent_visibility.py`.

### Phase 2 - writes (one commit: `feat(assistant): apply, restore and recompute scoring weights`)

6. **`apply_weights` (P2.4).**
   - description: `apply_weights(category, weights=None, deltas=None, preview_digest)`. Re-reads the CURRENT weights, rebuilds the
     resulting vector exactly as step 4, validates again with the same server-equal rules (warnings carried into the result), then `nonce.check(owner, "apply_weights", digest, preview_digest)`;
     mismatch/absent/expired -> `confirmation_required` ("the weights or the proposal changed since the preview (or it expired
     after N min); preview again"). Then `update_weights` (`POST /api/config/update_weights`) with
     `{category, weights: <the category's existing configured keys plus the changed keys only - never padded zeros>, recalculate: false}` and NOTHING else (no `modifiers`,
     no `filters`, so no loose config backup). Read back through `category_weights`; return `{category, previous, applied,
     verified: bool, snapshot:{id, created_by} | null, scores_stale: true, next: "recompute_scores"}`.
   - key decision: partial or full write. Default (revised, G7): send the existing configured keys plus the changed keys, never the route's zero padding of absent keys (that would write ~30 explicit zero keys into the operator's override file); the digest still binds the full resulting vector. Reason for sending more than just the changes: the route MERGES (`replace_weights=False`),
     so sending only changed keys is also correct but sending the full vector makes the stored result independent of what a
     concurrent editor changed between preview and apply (the digest already refuses that; belt and braces).
   - key decision: `recalculate`. Default false and not exposed: the route's recalculation is a synchronous subprocess up to
     300 s (risk 4); recompute is its own tool (step 8).
   - key decision: check-then-write race. The digest check and the route's `CONFIG_WRITE_LOCK` are not one critical section; an
     operator edit in that window is overwritten. Accepted (single-operator tool, window is milliseconds), documented.
   - key decision: timeout. The write is a small file rewrite; `call_timeout_s` is enough. A timeout returns the standard
   - G6 (known limitation): an open /compare weights or suggestions tab holds the old full vector and would post it back on its
     next edit, silently reverting the change. No live frame exists for config changes (`live_updates.py` only builds
     `{type:"changed", tool, paths, count}` for photo writes; checked), so this is documentation only: the result carries
     `reload_compare: true` and a `note` ("tell the user to reload /compare before editing weights there"), and `docs/AGENTS.md` says
     the same. Not fixed by a new frame (scope).
   - N17: `nonce.issue` can raise `NonceCapacityError`; `run_tool` already maps it to `rate_limited`, but the digest tools catch it
     and answer `too_many_pending` ("too many unconfirmed previews/dry runs pending; finish or wait 5 minutes") so the model is not
     told it hit the call rate limit. Test: 17 previews from one token, the 17th is `too_many_pending` (16 per owner).
     `outcome_unknown`; the description tells the model to call `category_weights` before retrying (the digest was consumed).
   - `snapshot` (N16): read the category's newest snapshot id BEFORE the write and again after; `snapshot` is reported only if the max id grew and the new row has `created_by == "auto:edit"` (no timestamp comparison, clocks and second granularity make it unreliable); otherwise `snapshot: null` and a warning that undo is not
     guaranteed (risk 6).
   - tool description: edition; "stores the weights in scoring_config.json via the viewer's own route; existing scores are NOT
     recalculated until recompute_scores; ask the user before calling".
   - verify (failing first): (i) without a digest -> `confirmation_required`, config bytes unchanged, 0 route writes; (ii) preview
     then edit the config by hand then apply -> refused (stale); (iii) preview then apply -> weights changed, snapshot row
     exists with the OLD weights and `created_by='auto:edit'`, `scores_stale` true, `photos.aggregate` unchanged; (iv) a digest is
     single use (second apply refused); (v) a digest from another token is refused and NOT burned; (vi) readonly token ->
     `forbidden_level`, 0 route calls; (vii) `bonus`/modifiers refused; (viii) `tests/test_agent_taste_isolation.py` extension: the
     apply adds no `comparisons` row and does not call `trigger_auto_retrain`; (ix) the written file still RESOLVES to the
     intended config (`config_resolve.load_resolved`), not a bare `json.load`.
   - affected files: `api/agent/tools_scoring.py`, `api/agent/internal_client.py`, `api/agent/live_updates.py`,
     `api/agent/tools_write.py` (levels), `tests/test_agent_scoring.py`, `tests/test_agent_taste_isolation.py`,
     `tests/test_agent_live_updates.py`, `tests/test_agent_comparison.py`.

7. **Snapshots: `list_weight_snapshots` and `restore_weight_snapshot` (P2.5).**
   - description: `list_weight_snapshots(category=None, limit=10, offset=0)` -> `weight_snapshots` route (limit 1..100):
     `{snapshots:[{id, category, timestamp, created_by, description, weights (non-zero), category_bonus, accuracy_before,
     accuracy_after, comparisons_used}], has_more}`. `restore_weight_snapshot(snapshot_id, dry_run=True, confirm=None)`:
     dry run finds the snapshot, diffs it against the current weights (`changed` keys, bonus change), and returns a `confirm`
     nonce bound to `{snapshot_id, category, current vector, snapshot vector}`; the real run re-derives the same binding, consumes
     the nonce, calls `restore_weights` (`POST /api/config/restore_weights {snapshot_id}`), reads back, and reports
     `undo_snapshot_id` = the newest `auto:pre_restore` snapshot (the route takes it before overwriting - confirmed in
     the code; verified again by the read-back, risk 6/7) and `scores_stale: true`.
   - key decision: finding a snapshot by id. The list route has no id filter and there is no get-by-id route. Default: page the
     list (limit 100, up to 5 pages, optionally narrowed by `category`) and `not_found` past that, stating the window searched.
     A new GET-by-id route is rejected as scope creep. The dry-run output also lists the nearest ids so the model can retry.
   - key decision: confirm for a restore. Default: dry run + nonce, same shape as `cull_apply`, because a restore silently
   - B3 (accepted): `POST /api/config/save_snapshot` stores `get_weights()` output (decimals, bare names, `bonus` included), while
     `apply`/`restore`/optimizer snapshots store `*_percent` keys, and `restore_weights` writes the snapshot dict verbatim with
     `replace_weights=True`. Restoring a decimal snapshot would write a non-percent weights block into the config. Decision: BEFORE the
     dry run and again before the real run the tool checks that every key of the snapshot ends in `_percent` and its base name is in
     `VALID_WEIGHT_COLUMNS`; otherwise `invalid_input`-class error `unsupported_snapshot` ("this snapshot was saved in another format by
     the web UI; restore it from /compare") with no `confirm` issued. `list_weight_snapshots` marks each snapshot
     `restorable: true|false` by the same test. Tests (fail first): a percent snapshot restores; a decimal snapshot (manual save) ->
     `unsupported_snapshot` on both dry run and real run, config bytes unchanged; a snapshot with one unknown `*_percent` key likewise.
   - G12: a snapshot whose category was removed from the config makes the route answer 404 (`Category ... not found in config`); the tool
     maps it to `not_found` with that message (not a generic upstream error). Test with a snapshot of a deleted category.
   - N16 applies to the restore too: the `undo_snapshot_id` is found by max snapshot id before/after, not by timestamp.
     rewrites a category's weights wholesale (`replace_weights=True`). Not `allow_destructive`-gated: it is reversible by design.
   - NOT exposed, deliberately: `DELETE /api/config/weight_snapshots/{id}` and `POST /api/config/save_snapshot` (the apply and
     restore routes snapshot themselves). The allowlist test asserts these templates are absent.
   - verify (failing first): list is paginated and capped; restore dry run writes nothing (config bytes + snapshot count
     unchanged); real run without confirm -> `confirmation_required`; with confirm -> weights equal the snapshot's, a new
     `auto:pre_restore` snapshot holds the pre-restore weights, restoring THAT snapshot returns the original (round trip);
     a snapshot with NULL `category_bonus` leaves the bonus; a corrupt snapshot (weights not JSON) -> the route's 500 becomes
     `upstream_error` without leaking text; an id on page 6 -> `not_found`; readonly -> `forbidden_level`.
   - affected files: `api/agent/tools_scoring.py`, `api/agent/internal_client.py`, `api/agent/live_updates.py`,
     `tests/test_agent_scoring.py`, `tests/test_agent_comparison.py`.

8. **`recompute_scores` and `recompute_status` (P2.6).**
   - description: `recompute_scores(category=None, all=False)` (exactly one) -> `recompute_start`
     (`POST /api/scan/recompute {confirm: true, category?}`), returns at once `{started: true, kind: "recompute", scope:
     "category:<c>" | "all", poll: "recompute_status", note}`; `recompute_status()` -> `recompute_status` route:
     `{state: "running"|"succeeded"|"failed"|"idle", kind, progress, exit_code}` (state derived: running true -> running;
     exit_code 0 -> succeeded; non-zero -> failed; kind not recompute -> idle). Both edition (the route's own gate; NOT
     `scan_available`, since the route does not apply the scan feature flag - confirmed in `start_recompute`).
   - key decision: how to keep it async. Default: add a NEW request model `RecomputeScoresRequest` (G9) with `category: Optional[str] = None`; the server
     validates it against `server_scoring_config().get_categories()` (unknown -> 400) and spawns
     `--recompute-category <c>` instead of `--recompute-average` through `_spawn_fixed_library_job`, which already provides the
     single in-flight guard (409 `A job is already running`), the cross-process `LibraryLock` conflict (409, also covers the
     gallery index build because that build holds the same lock), the `confirm` requirement and the state/reader thread. The tool
     returns after `Popen`, so `call_timeout_s` is irrelevant and `outcome_unknown` can only mean the spawn call itself
     dropped (the description then says: call `recompute_status`, do not retry blindly). Rejected alternative: an agent-side
     asyncio task awaiting `/api/stats/categories/recompute` (not durable across workers or a restart, status unobservable,
     holds the 300 s cap). (Decision 2: server change taken.)
   - key decision: the refusal during an index build. The old stats route raises `refuse_while_gallery_index_build_runs`
   - G9: `RecomputeRequest` (`confirm: bool`) is shared with `detect_panoramas` (scan.py:137, :456). The category field goes in a NEW
     model `RecomputeScoresRequest(confirm: bool, category: Optional[str] = None)` used only by `/recompute`; `detect_panoramas` keeps
     `RecomputeRequest` and cannot accept a stray `category`.
   - G8: job identity. `start_recompute` returns `started_at` (epoch float from `_scan_state['started_at']`) and `scope`
     (`category:<c>` | `all`) in addition to `pid`; `recompute_status` gains `started_at` and `scope` from `_scan_state`. The tool echoes both
     from the start call, and `recompute_status` reports `matches_started_job: true|false` by comparing them to the values the model
     passes back (`recompute_status(started_at=...)`), so a different job (a scan, a panorama run, another worker's) is never reported as the
     user's recompute. `LIBRARY_LOCK_HELD_EXIT_CODE` (db_helpers) in `exit_code` maps to state `busy` ("another library job held the lock; nothing
     was recomputed; try again later"), never `failed`.
   - N15: the status tool derives a `reason` field (`exit_code`-based: `ok`, `lock_held`, `failed`, `not_this_job`, `no_job`) instead of exposing the raw
     number alone.
   - G10: caches. The async job finalises in `_read_scan_output` (scan.py), which already clears `_stats_cache` and the photo-types cache; the
     spec adds `invalidate_stats_cache()` (the comparison router's helper, used after `update_weights`) at the same point when
     `kind == 'recompute'` and exit code 0, so category counts and score distributions stop serving stale values. A per-category run also
     updates the library's persisted percentile snapshot (`normalizer.save_to_stats_cache`, facet.py:~3874-3880), which affects the
     normalisation of every category's scores on the next recompute/explain: the tool's `note` says so and `docs/AGENTS.md` repeats it.
     (503 `library_busy`); the scan route answers 409 `conflict` from the lock. The tool maps both to the existing
     `library_busy` / `conflict` envelopes unchanged (`_status_to_error`).
   - the per-category job skips `process_bursts` / `detect_all_sequences` (facet.py:3877); the tool says "category recompute
     does not refresh burst or sequence groups; `all` does".
   - schema: the OpenAPI changes -> `cd client && npm run gen:api` (CI fails if stale), commit `schema.d.ts`.
   - verify (failing first): in `tests/test_scan.py::TestRecompute`: body `{confirm:true, category:"portrait"}` spawns argv
     containing `--recompute-category portrait` and not `--recompute-average`; unknown category -> 400, nothing spawned; body
     without `confirm` still 400; second call while running -> 409. In `test_agent_scoring.py` (Popen recorder as in
     `test_agent_scan.py`): tool returns `started` without waiting; a second call returns `conflict`; a held library lock ->
     `conflict`; `recompute_status` maps running / exit 0 / exit 1 / idle; a slow fake process (never exits) does NOT make the
     tool return `outcome_unknown`; readonly -> `forbidden_level`, nothing spawned.
   - affected files: `api/routers/scan.py`, `api/agent/tools_scoring.py`, `api/agent/internal_client.py`,
     `api/agent/live_updates.py`, `client/src/app/core/api/schema.d.ts`, `tests/test_scan.py`, `tests/test_agent_scoring.py`,
     `tests/test_agent_comparison.py`.

9. **`learned_weights` (P2.7).**
   - description: `learned_weights(category, include_ties=True, with_confidence=False)` -> `learned_weights` route
     (`GET /api/comparison/learned_weights`) and, only when asked, `weight_confidence`
     (`GET /api/comparison/confidence?category=..&n_bootstrap=50`). Output when available:
     `{available: true, category, suggest_changes, comparisons_used, ties_included, accuracy_before, accuracy_after,
     improvement, mispredicted_count, changes:[{key, current, suggested, delta}] (non-zero deltas only), proposal:{<key>:
     suggested ...}, stable_components?, confidence?, next}` where `next` says to run `preview_weights(category, weights=proposal)`.
   - honouring the gates: the route answers HTTP 200 with `{available: false, message}` for (a) `unavailable_if_external`
     (`auto_retrain.backend != native`; message "Preferences retained; external GPU learning has not been dispatched here"),
     (b) fewer than `min_comparisons_for_optimization` (default 50: `viewer.comparison_mode.min_comparisons_for_optimization` in the shipped config; the route's own fallback of 30 applies only if the key is absent) decisive votes (adds `comparisons`, `min_required`), (c) an
     optimizer error. The tool passes these through as `ok({available:false, reason, message, comparisons?, min_required?})`
     and NEVER invents a suggestion; `suggest_changes: false` drops `changes`/`proposal` and returns
     `{suggest_changes:false, note:"the optimizer found no improvement; do not propose weight changes"}`.
   - key decision: category required. Default: required (an all-categories fit is the slowest path and blends categories that
     are tuned separately). Timeout 120 s (risk 11); `use_cv` not exposed (cross-validation multiplies the cost); `with_confidence`
     capped at `n_bootstrap=50`.
   - Reading is not a taste write: no comparison is recorded; the retrain is not armed.
   - verify (failing first): fake optimizer results via the route's seam (patch `WeightOptimizer` in `api.routers.comparison`,
     not an auth dependency) for the four shapes (available, `suggest_changes` false, below minimum, external); assert each
     tool output, `changes` excludes zero deltas, the proposal passes `weights.validate_proposal`, and `preview_weights(proposal)`
     accepts it; readonly -> `forbidden_level`; `comparisons` table row count unchanged.
   - affected files: `api/agent/tools_scoring.py`, `api/agent/internal_client.py`, `tests/test_agent_scoring.py`,
     `tests/test_agent_comparison.py`.

10. **`misassigned_categories` and `override_categories` (P2.8).**
    - description: `misassigned_categories(category, limit=20, scan=100)` (edition, read): pages `search_photos(category=<c>)`
      and for up to `scan` (<= 200, concurrency 4) calls `critique`.
      A photo that already carries a manual override is detected from the critique itself: `category_reason.reason_key == 'override'` (critique.py:176) -> skipped and counted in `skipped_overridden` (G4; no `fields`/`photos_by_paths` lookup of `category_override`). Signals, each labelled: `stale` (critique `category` != stored `category`: the CURRENT config puts it elsewhere - fix is
      `recompute_scores`, not an override), `near_miss` (`category_reason.rejected` has a higher-priority category whose first
      failing filter is one numeric filter missed by under 10% of its bound - the threshold is a named constant, not tuned),
      `weak_fit` (not used in v1). Output `{category, scanned, of_total, candidates:[{path, stored, suggested, signal, mismatch}],
      confidence_basis: "heuristic", note}` and an explicit statement that `scanned < of_total` means the list is partial.
    - `override_categories(category, paths, dry_run=True, expected_count=None, confirm=None)` (edition, write): paths only
      (<= 50, `PER_PHOTO_CAP`), NO filter scope - a category change is a scoring change per photo and a view-wide re-pin is not
      requested. Dry run reads each photo's current category and override through `photos_by_paths`, returns `would_change`,
      `already`, `missing`, and a `confirm` nonce bound to `{target category, {path: current category}}`. The real run needs
      `confirm` AND `expected_count == would_change`, re-derives the binding (any photo whose category moved since -> refused),
      then calls `override_category` per photo sequentially (the existing route recomputes `category` and `aggregate` for each and
      invalidates the stats cache), stops on the first error and reports `{affected, remaining, failed_path}` (the `_stopped`
      pattern used by `junk_clear`).
    - key decision: signal quality. Default: ship as a heuristic with the signals named and the claim limited to "worth a look",
      never "wrong". UNVERIFIED precision; no precision number is stated in docs. A calibrated detector needs a server route
      and labelled data and is a follow-up (roadmap item, not this spec).
    - key decision: batch vs reuse of `override_category`. Default: a NEW batch tool, because the single-photo tool has no
      dry-run/expected_count and looping it from the model is exactly what `expected_count` exists to prevent. Per-photo cost of
      the route (it builds a lightweight `Facet` each call) is UNVERIFIED; the cap of 50 and `call_timeout_s` bound it.
    - the `override` is sticky (survives `--recompute-average`): the description states it and points to
      `clear_category_override`. Not `allow_destructive`-gated (reversible).
    - verify (failing first): seed three photos (one stale, one near-miss, one fine) with a config whose filters make the signals
      deterministic; assert the two candidates and the labels, that a photo with an override is skipped, `scanned`/`of_total`
      honesty with `scan=1`; `override_categories`: dry run writes nothing (`photo_scoring_overrides` count unchanged); real run
      without confirm refused; with a wrong `expected_count` refused; a category change between dry run and run -> refused;
      success writes the override rows and the new `category`/`aggregate`; the first failing path stops the batch and reports
      `remaining`; a readonly token -> `forbidden_level`.
    - affected files: `api/agent/tools_scoring.py`, `api/agent/tools_corrections.py` (or keep both in `tools_scoring.py`;
      default `tools_scoring.py` to avoid reopening a file this branch already modifies), `api/agent/tools_write.py` (levels),
      `tests/test_agent_scoring.py`, `tests/test_agent_corrections.py`.

11. **`ui_show_comparison` `tab` argument (included, decision 6).**
    - description: add `tab` (`enum: ab | suggestions | weights | snapshots`, default `ab`) to `ui_show_comparison`
      (`ui-tool-handlers.ts` currently forces `COMPARE_AB_TAB_INDEX = 1`, `compare-filters.service.ts:4`). Tab indices from
      `comparison.component.ts`: snapshots 0, A/B 1, suggestions 2, weights 3 (the later priority/panorama tabs are not
      needed; their indices UNVERIFIED). The suggestions tab can be `weightsLocked()` (disabled until enough comparisons; G11: the handler does NOT check this - it only sets the tab and the component shows its own locked state; the component's unlock threshold (50) differs from the route default it displays against (30) - recorded, out of scope). Superseded text:
      previously proposed: the handler throws `UiToolError('invalid_input', ...)` with the remaining comparison count (`invalid_input` is in
      `TAB_ERROR_CODES`, ui_tools.py:37, so no new code and `error_codes` in the schema JSON is unchanged).
    - key decision: extend vs add a tool. Default: extend `ui_show_comparison` (no new tool name, fewer client/server surfaces),
      keeping its existing "answer is the user's click" contract: opening the weights tab arms nothing and the
      `comparison_open` refusal of `search_photos(show=true)` is unchanged.
    - the contract changes -> `scripts/dump_ui_tools.py` regenerates `ui-tools.schema.json` and bumps `tools_version`
      (open tabs then answer `tab_outdated` until reloaded - the docs already say so; keep that sentence).
    - verify: `tests/test_agent_ui_contract.py` (schema == dump), `cd client && npm run test` for the handler spec (failing
      first: `tab: 'weights'` sets `activeTab` 3; locked suggestions refuses), `npx tsc --noEmit -p tsconfig.app.json && npx tsc
      --noEmit -p tsconfig.spec.json`, `npx ng lint`, rebuild Angular (project rule) and remind the user to restart the server.
    - affected files: `api/agent/ui_tools.py`, `client/src/app/core/agent/ui-tools.schema.json`, `ui-tool.types.ts`,
      `ui-tool-handlers.ts`, `ui-tool-handlers.spec.ts`, `tests/test_agent_ui_contract.py`, `docs/AGENTS.md` and translations.

12. **Phase 2 wiring, docs and contract tests.**
    - description: `ACTIONS` rows `tune_weights` extended (`learned_weights`, `apply_weights`, `list_weight_snapshots`,
      `restore_weight_snapshot`), `recompute_scores` (`recompute_scores`, `recompute_status`; `ANY`) and `fix_categories`
      (`misassigned_categories`, `override_categories`; `_when("gallery","selection")`); `INSTRUCTIONS` sentence on the
      preview -> apply -> recompute order and the "scores are stale until recomputed" fact; docs section completed in all seven
      languages (levels, the two-step confirmation, digest TTL 5 min and its loss on restart, the per-process status caveat, the
      heuristic nature of `misassigned_categories`, that bonus/modifiers/filters are not assistant-editable).
    - key decision: `CORE_TOOLS` gains nothing (decision 7); no test pins its size, so no test or docs count changes.
    - verify: `tests/test_agent_actions.py`, `test_agent_visibility.py` (a readonly key lists none of the edition tools and
      `hidden_tools.count` includes them), `test_agent_prompts.py`, `test_agent_resources.py`; the allowlist test extended so
      `ALLOWED_COMPARISON` also lists `/api/comparison/learned_weights`, `/api/comparison/confidence` and the template set asserts
      `/api/config/update_weights`, `/api/config/restore_weights`, `/api/config/weight_snapshots`, `/api/scan/recompute`,
      `/api/scan/recompute_status` are present while `DELETE /api/config/weight_snapshots/{id}`,
      `/api/config/save_snapshot`, `/api/recalculate`, `/api/stats/categories/recompute` are absent (a new
      `test_scoring_routes_are_exactly_the_reviewed_set`); regenerate `ui-tools.schema.json`; docs parity + xlinks; ruff.
    - affected files: `api/agent/actions.py`, `api/agent/server.py`, `api/agent/tools_common.py` (only for `CORE_TOOLS`),
      `client/src/app/core/agent/ui-tools.schema.json`, `docs/AGENTS.md`, `docs/{fr,de,it,es,pt,zh}/AGENTS.md`,
      `tests/test_agent_comparison.py`, `tests/test_agent_actions.py`, `tests/test_agent_visibility.py`.

## Final verification gate

Per phase, before the commit (venv interpreter only; cap pytest at 2 workers if `-n` is used):
- `venv/bin/python -m pytest tests/test_agent_*.py tests/test_scan.py tests/test_open_install_refusal.py tests/test_api_contract.py -q`
  (use `--junitxml`/redirect, not a pipe, and read the real exit code).
- `venv/bin/python -m ruff check .`; the project's mypy ratchet run with CI's unpinned mypy.
- `venv/bin/python scripts/dump_ui_tools.py` leaves `git status --porcelain client/src/app/core/agent/ui-tools.schema.json` showing
  only the intended diff; the AGENTS.md grep checks above.
- Phase 2 only: `cd client && npm run gen:api` leaves `schema.d.ts` committed and current; if step 11 is taken, the client
  gates (vitest via `npm run test`, both `tsc --noEmit` projects, `npx ng lint`) and an Angular rebuild.
- Failing-first proof for every new test: write the test, see it fail for the stated reason, then implement. When injecting a
  fault to prove a guard bites (the digest check, the `expected_count` check, the readonly refusal), retype the original by hand
  and assert `git status --porcelain <file>` is clean afterwards (project rule).
- Real-usage check (project E2E harness, scratch config, never the production DB): connect an `edition` token, run
  `explain_score` on a photo, `preview_weights` for one category, `apply_weights`, confirm `scoring_config.json` still resolves
  and a snapshot exists, `recompute_scores(category)` and follow `recompute_status` to `succeeded`, then
  `restore_weight_snapshot` back, and confirm with a `readonly` token that `tools/list` shows none of the edition tools and
  `status.hidden_tools` counts them.
- `scoring_config.json` is untouched by any step except through the two routes: a test asserts the only writers reachable from
- N19: every `verify:` above must be able to fail: a guard test is proven by injecting the fault (remove the digest check, the `expected_count`
  check, the `_percent` check, the `read_resource` level check) and seeing red, then restoring by hand (project rule). The check "readonly token
  makes 0 route calls" counts calls on a spy around `InternalClient.call`, not on the response.
  `api/agent` are `update_weights` and `restore_weights` by walking `ROUTE_ALLOWLIST` for `/api/config/` templates.

## Adversarial review

Opus review, adjudicated 2026-10-23. Each finding with the decision and where it landed.

- B1 BLOCKER (accepted): the baseline-minus-proposal difference does not cancel the formula. The baseline is `get_weights` (normalised to
  1.0 + modifiers, config/scoring_config.py:604-639) while the proposal is the raw `value / 100` (comparison.py:899-904), with a `min(10, ...)`
  clamp. Decision: send the full proposed vector normalised through one extracted helper; rank shifts primary, mean shift secondary, clamp stated;
  the old mean-shift test is replaced by one that compares against the real scorer path. -> Risk 1, step 4, decisions.
- B2 BLOCKER (accepted, scope deviation): `weight_map` (comparison.py:908-930) omits 12 valid metrics. Decision: extend it to all of
  `VALID_WEIGHT_COLUMNS` (config/category_filter.py:74-92), mapped to the columns the real scorer reads; a server test proves each valid key moves
  the preview. This deviates slightly from "no change to preview_score" (decision 3) because the route was wrong, not just approximate. -> step 4.
- B3 BLOCKER (accepted): a manual snapshot (`save_snapshot`) stores decimal `get_weights()` output; restoring it writes a non-percent block.
  Decision: `unsupported_snapshot` for any snapshot whose keys are not all `*_percent` in `VALID_WEIGHT_COLUMNS`; `restorable` flag in the list.
  -> step 7.
- G4 (accepted): no `category_override` via `fields`/`photos_by_paths`; use `category_reason.reason_key == 'override'` (critique.py:176). -> step 10.
- G5 (accepted): `critique_available` is registered through `register_tool(requires=)` so it is in `tools_common.TOOL_REQUIRES`; it gates
  `misassigned_categories` too. -> steps 2, 10.
- G6 (accepted as limitation): an open /compare tab can post a stale vector back. No config-change frame exists (`live_updates.py` builds
  photo-path frames only), so `apply_weights` returns `reload_compare: true` and the docs say so. -> step 6.
- G7 (accepted): the valid key set is `VALID_WEIGHT_COLUMNS`, not the `METRIC_NAME_MAPPING` padding; `apply_weights` sends configured keys plus
  changed keys, never padded zeros. -> steps 3, 6.
- G8 (accepted): job identity. Start returns `started_at` and `scope`; status reports both; the tool reports `matches_started_job`; the lock-held
  exit code maps to `busy`. -> step 8.
- G9 (accepted): a new `RecomputeScoresRequest` model, not the `RecomputeRequest` shared with `detect_panoramas`. -> step 8.
- G10 (accepted): `invalidate_stats_cache()` when the async recompute finishes; the per-category run's effect on the persisted percentile
  snapshot is stated in the tool note and docs. -> step 8.
- G11 (accepted): the step 11 handler only opens the tab; the component shows its own locked state; the 50 vs 30 threshold mismatch is out of
  scope. -> step 11.
- G12 (accepted): restore of a removed category: 404 -> `not_found` with the route's message; invalid keys covered by B3. -> step 7.
- N14 (accepted): the real default of `min_comparisons_for_optimization` is 50 (30 is only the route's fallback). -> step 9.
- N15 (accepted): the status tool derives a `reason` field. -> step 8.
- N16 (accepted): detect the auto snapshot by max id before/after, not by timestamp (apply and restore). -> steps 6, 7.
- N17 (accepted): `NonceCapacityError` -> `too_many_pending` with a clear message and a test. -> step 6.
- N18 (accepted): `read_resource` did not check `required` against the key's level (only `list_resources` did); fix and a failing-first test. -> step 3.
- N19 (accepted): each `verify:` must be able to fail; fault-injection requirement and call-spy wording added; the cannot-fail schema diff check
  became a test comparing `ui-tools.schema.json` to `render_client_actions()` / `tools_version()`. -> step 5, final gate.
- N20 (accepted): `docs_parity.py` / `docs_xlinks.py` dropped (not read, may not cover AGENTS.md); replaced by grep checks over the 7 AGENTS.md. -> step 5, 12.
- N21, N22 (recorded): notes from the review, no spec change was requested.

Unresolved after review: the exact list of 12 missing `weight_map` keys and their real columns must be read from `processing.scorer`
(`build_metric_vector`, `WEIGHT_TO_COLUMN`) at implementation time; an unknown weight key is warned about, not refused (decision 5).
