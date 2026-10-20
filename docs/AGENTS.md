# AI Agents (MCP)

> 🌐 **English** · [Français](fr/AGENTS.md) · [Deutsch](de/AGENTS.md) · [Italiano](it/AGENTS.md) · [Español](es/AGENTS.md) · [Português](pt/AGENTS.md) · [简体中文](zh/AGENTS.md)

Facet can act as a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server, so an MCP-capable AI assistant can search and inspect your library with the same filters the gallery uses. It exposes thirteen read tools that change nothing in your library and twelve `ui_*` tools that move the browser tab you already have open (page, filters, selection) and never write library data. Tokens that are allowed to can also [change things](#changing-things) (ratings, flags, tags, albums, culling and deletion) and work the [darkroom](#darkroom-culling-groups).

## Enable it

The endpoint is **on by default**. To switch it off, set `viewer.mcp.enabled` to `false` in `scoring_config.json` (see [Agent Endpoint (MCP)](CONFIGURATION.md#agent-endpoint-mcp)) and restart the viewer, or reload the configuration; `/mcp` and every `/api/mcp/*` route then answer 404. Without `viewer.password` the install counts as open, even when `viewer.edition_password` is set, so its tokens can only be `readonly`. On an open install the endpoint serves only a read-only anonymous key, which grants nothing the open `/api` does not already grant.

The endpoint is `POST /mcp` on the viewer's own port: Streamable HTTP, stateless, plain JSON responses. `GET` answers 405. Only the tab bridge, `/api/mcp/bridge`, is a WebSocket; see [Control your open tab](#control-your-open-tab).

## Mint a token

The easiest way is the browser. With `viewer.mcp.enabled` on, open the account menu and choose **Connect an assistant**. Enter a **Name**, pick **What the assistant may do**: **Read and pilot only**, plus **Act as me** or **Full editing** when your session holds that level (a token cannot out-rank the session that creates it), and click **Create token**. The dialog then shows **Paste this into your assistant** with a ready-made prompt that contains the token. It is shown once, so click **Copy prompt**, paste it into your assistant and click **Done**. **Manage tokens (N)** lists your tokens with their last use and revokes one, and a status line says whether this tab is connected so assistants can drive it. The level list is limited to what the server will grant: an open install offers only **Read and pilot only**, **Act as me** appears only on multi-user installs and **Full editing** only in an edition session. The prompt states the level actually granted.

Scripted alternative (curl):

An assistant authenticates with a personal token that starts with `fct_`. Mint one with an authenticated request (the token is returned **once**; Facet stores only its SHA-256 hash):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "my-assistant", "level": "readonly"}'
```

The response carries the plaintext in `token`. `GET /api/mcp/tokens` lists your tokens (never the secret), and `DELETE /api/mcp/tokens/{id}` revokes one. A superadmin can list every owner's tokens with `?all=1` and revoke any of them. Each owner can hold at most 20 live tokens (412 beyond that). These routes refuse an agent's own credential (403), so an assistant can never mint, list or revoke tokens.

## Connect your assistant

The prompt the dialog generates holds everything an MCP-capable assistant needs: the server name `facet`, the URL (`http://<host>/mcp`), the transport (Streamable HTTP), the header `Authorization: Bearer fct_...`, the access level granted and a call to the `status` tool to confirm the connection. Paste it into your assistant, or add that server yourself to whichever MCP client you use. Use HTTPS when the viewer is reachable beyond your own machine, since the token travels in a header on every call.

## Permission levels

A token is minted with a grant: `readonly`, `user` or `edition`. The **effective** level is recomputed on every call as the lower of the token's grant and its owner's live level:

- Single-password installs: `user` is capped to `readonly` at mint time, because that mode has no middle level. An `edition` token needs an edition session and works only while the edition password is unchanged.
- Multi-user installs: an `edition` token of a user who is later demoted drops to `user`; a promotion never raises a token above its grant.
- Open installs (no `viewer.password`, even if `viewer.edition_password` is set): tokens are always `readonly` and belong to a shared `_anonymous` owner.
- Single-password installs have no `user` level: the effective level is `edition` or `readonly`, so the tools marked `user` under [Changing things](#changing-things) also need an `edition` token there. A `user` tool called with a lower token answers `forbidden_level`, saying it needs `edition`.
- Each tool has its own minimum level, checked before anything is read or written; a lower token gets `forbidden_level`.

A token dies automatically when its owner's credentials change: the viewer or edition password in single-password mode, the owner's password in multi-user mode, or the owner's account being deleted. It then answers 401 at the gate.

## Tools

The thirteen data tools are read-only:

| Tool | What it does |
|------|--------------|
| `search_photos` | Filter and sort the library like the gallery, with the viewer's default hide toggles (blinks, bursts, duplicates, brackets, panoramas, rejected) applied unless the filter sets them (reports `hidden_summary`). Shown in your open tab by default (see below); `fields` adds any photo column |
| `semantic_search` | Find photos by meaning, or by words in captions with `scope: "text"` (not shown in the tab). `filters` narrow the search like the gallery's, and each row carries its `similarity`. |
| `get_photo` | Full detail of one photo by its path (the histogram is left out) |
| `get_thumbnail` | Look at one photo: its thumbnail as an image part (`size` 160 to 640, default 512). A smaller size is used when the JPEG would exceed `viewer.mcp.max_image_bytes`; `too_large` when none fits |
| `contact_sheet` | Look at 1 to 16 photos as one numbered grid image (`columns` 2 to 4, longest edge 1024). The text part lists `legend` (tile number to path, in request order) and `unavailable` (tiles left blank because the photo is missing or not visible) |
| `possible_faces` | Faces that look like one recognised person: cosine similarity to the person's centroid, best first, same embedding model only. `scope` is `unassigned` (default), `other_persons` or `all`; `min_similarity` defaults to 0.30; `limit` up to 100. A scan above 192000 faces is refused (`too_large`): narrow it with `scope`, `path_prefix`, `date_from` or `date_to`. The photos are shown in your tab. `candidates` is the count of faces in scope you can see, before the embedding-dimension check; `faces_scanned` is the number of rows actually scored. |
| `similar_photos` | Photos similar to one photo, by visual embedding or by colour; `min_similarity` (0 to 1) sets the floor |
| `filter_options` | The vocabulary a filter accepts: cameras, lenses, tags, persons, patterns, categories, narrative moments, junk kinds, metric ranges |
| `list_persons` | Recognised people, optionally filtered by name |
| `list_albums` | Albums the token's owner can see |
| `library_stats` | Library statistics: `kind` selects the size and score overview (default) or any Stats page data (see below) |
| `status` | Who the token is, its effective level and the server flags and the open tabs it can drive |
| `available_actions` | The jobs that apply to your open tab and this token right now, each with its tools; tools above the token's level are not listed |

In every filter object, `show_rejected` is a boolean: `true` lists only the rejected photos, `false` or omitted gives the normal listing.

## Results are shown in your tab

- `search_photos`, `semantic_search` and `similar_photos` take `show` (default `true`). After a successful first-page search the server applies the same query to the Facet tab you have open, replacing its filters, so you see what the assistant found without being asked. Assistants are told never to ask whether to open or show results; `show: false` is for intermediate probes and counts, and the last shown search is what you see.
- The result carries `shown_in_tab`: `{"applied": true, "tab_id", "keys", "total"}`, or `{"applied": false, "reason"}` where the reason is `no_tab`, `bridge_disabled`, `tab_outdated`, `tab_timeout` (the tab may still apply it), `forbidden`, `page_not_first`, `empty_result`, `unsupported_filters` (with `keys`) or `invalid_combination`. A failed show never fails the search. Pass `tab_id` to choose a tab. Every reason: `error` (the show itself failed), `bridge_disabled`, `page_not_first`, `empty_result`, `invalid_combination`, `unsupported_filters` (with `keys`; for `semantic_search` the keys are `scope` or `threshold`, a threshold over 0.5 that the sidebar slider cannot express), and the codes the tab bridge returns (`no_tab`, `tab_outdated`, `tab_timeout`, `forbidden`, `invalid_input`, `upstream_error`). The tab pages itself, so for a semantic search it may show more rows than the agent received. When rows are trimmed, `next_page` (with `suggested_per_page`) names the page that continues exactly after the last returned row, or, when pages cannot express that point, `next_offset` gives it as a row offset.
- Only the first page is shown (the tab pages itself as you scroll), and an empty result is not shown, so you keep your previous view. A search using filters the gallery sidebar has no field for (`exclude_tags`, `require_tags`, `is_silhouette`, `junk_kind`, `narrative_moment`, `min_rating`, `min_aggregate`, `show_rejected: true`) is not partially applied, and `semantic_search` with `scope: "text"` is not shown either.
- A show leaves `/culling`, `/compare` and `/photo` for the gallery, clears a whole-view selection, and on an album page first goes back to the gallery, so an album's saved filters are never overwritten. A search whose count feeds the `expected_count` of a write tool should use `show: false`.
- `ui_show_photos` pins an exact list of photos: the gallery shows them in your order until any filter change replaces the list. `ui_get_context` reports whether a pinned list is shown.
- Rows carry camera, lens, aperture, shutter speed, ISO, focal length and `is_monochrome`. `fields` (on the three search tools) adds any other photo column except the image and embedding data, for example `leading_lines_score`; `learned_score` is filled only when sorting by it. When the byte cap trims rows, the result adds `returned` (and `next_offset` or `suggested_per_page`).
- `library_stats` takes `kind` (default `overview`: size, type counts and score overview). The other kinds are read-only and return the data of the Stats page; long lists are cut at 50 entries with `truncated: true`:

| Kind | Data |
|------|------|
| `score_distribution`, `top_cameras`, `categories`, `gear`, `stats_settings`, `timeline`, `correlations` | The Stats page panels; they accept `date_from`, `date_to` and `category`. `correlations` also takes `x`, `y` (comma list), `group_by` and `min_samples` |
| `category_breakdown`, `category_weights`, `category_correlations`, `category_overlap` | Category statistics (no parameters) |
| `timeline_dates`, `timeline_months` | Photo counts per day or per month; they need `year` (`timeline_dates` also takes `month`) |
| `timeline_years` | Photo counts per year |

## Control your open tab

Next to the data tools, the server always lists twelve `ui_*` tools that act on the Facet tab you have open in a browser: they move the page, change the filters or the selection, and read back what you see. They never write library data, so a `readonly` token is enough.

| Tool | What it does |
|------|--------------|
| `ui_navigate` | Go to a page (gallery, persons, albums, stats, ...) |
| `ui_set_gallery_filters` | Merge a patch into the gallery filters and sort (`null` removes a filter, `replace: true` starts from none) |
| `ui_get_gallery_view` | Route, active filters, total matches, the first visible photo paths and the selection count |
| `ui_get_context` | The open page (route), the gallery state (total, loaded count, whether a pinned list is shown), the selection count and the `actions` that apply to your token here |
| `ui_open_photo` | Open one photo |
| `ui_show_photos` | Show exactly these `paths` (up to 200) in this order as the gallery's list; unreachable ones come back as `missing`. Any filter change replaces the list |
| `ui_select_photos` | Select explicit `paths`, or the whole filtered view with `select_view: true`, with mode `replace`, `add` or `remove` |
| `ui_clear_selection` | Clear the selection |
| `ui_get_selection` | The `scope` (`paths` or `view`) and `count`, with the `paths`, or for a view the `filters` and `excluded_paths` |
| `ui_next_page` | Load the next page of the gallery |
| `ui_show_culling_group` | Open the darkroom on one group, identified by `(type, group_id)` (edition accounts) |

How it works:

- While you are signed in and both `viewer.mcp.enabled` and `viewer.mcp.bridge` are true, every Facet tab opens a same-origin WebSocket to `/api/mcp/bridge` and authenticates with your session in its first message. The bridge is on by default; set `viewer.mcp.bridge` to `false` to turn it off, and the `ui_*` tools then answer a clear error.
- `ui_get_context` reads the open page, the gallery state, the selection count and the `actions` that apply to this page and token; `available_actions` answers the same question from the server for your open tab. Tools above the token's level are not listed.
- A tool only reaches the tabs of the token's owner. On a single-password install every session is the same user, and on an open install every tab belongs to the shared `_anonymous` user, edition logins included.
- Each tab carries the level of the session that opened it, and a token only drives tabs at or above its effective level: an `edition` token never uses a tab signed in with a viewer-only session, while a `readonly` token may drive an `edition` tab. On a single-password install a token is also capped by the session that minted it: a token minted from a viewer-only session reaches only viewer-level tabs, never the edition tab (a token minted before this rule is capped at its own level). A tab can only be replaced by one of equal or higher level: a viewer-only session reusing an edition tab's `tab_id` is refused with 4409, and past the per-user tab cap the lowest-level tab goes first. `status` lists only the tabs the token can drive. `status` also reports `out_of_reach_tabs`, the number of open tabs this token cannot drive.
- With several tabs open, the most recently focused one is used and the result's `tab` field says so. Pass `tab_id` (listed by `status`) to choose another.
- A tab refuses what its account may not do (for example `/culling` for a non-edition account) and the tool returns that refusal.
- What a tab sends back is untrusted: it is bounded in depth, string length and list length, and capped by `max_bytes`.
- Errors: `no_tab` (no tab is connected, or the bridge is off), `tab_timeout` (no answer within `call_timeout_s`) and `tab_outdated` (the open tab does not know the tool; reload the page after upgrading Facet).
- The bridge accepts the WebSocket first and then refuses it with a close code rather than an HTTP status: 4404 when the endpoint or the bridge is off (the tab then stays disconnected until the page is reloaded), 4403 when the `Origin` is missing or not allowed, 4401 for a missing or rejected session.
- A reverse proxy must forward the WebSocket upgrade for `/api/mcp/bridge`; see [Deployment](DEPLOYMENT.md). If it rewrites the `Host` header, list the public origin in `viewer.mcp.allowed_origins` (for example `["https://photos.example.com"]`), because the page's origin must match the host or be listed.
- The tab registry is per process, so the bridge needs a single worker (the default).

Beyond the basics above:

- `ui_set_gallery_filters` takes you to the gallery first when another page is open, then applies the patch. It refuses a whole patch (`invalid_input`) that names a filter the tab has no control for; use `search_photos` for those. On an album page, `replace: true` first returns to the gallery, so the album's saved filters are not overwritten. It also accepts `semantic_query`, `semantic_threshold` (0 to 0.5), `similar_to`, `similarity_mode` and `min_similarity` (0 to 1); `similar_to` and `semantic_query` cannot be combined.
- `ui_get_gallery_view`, `ui_next_page` and `ui_select_photos` with `select_view` need the gallery (or an album) to be the open page, otherwise they answer `no_active_view`; call `ui_navigate` to `/` first. Give `ui_select_photos` exactly one of `paths` and `select_view`.
- `no_tab` also means no Facet tab is open: open Facet in a browser and sign in. The status line in the **Connect an assistant** dialog shows whether this tab is connected; the `status` tool lists open tabs and their ids.
- A tab stops reconnecting once its session is rejected (sign in again), and waits until you return to it after another tab of yours took over.
- The tab bridge connects only when the server reports the bridge as available (the endpoint is on and `viewer.mcp.bridge` is true); with the bridge off, tabs do not connect at all.
- `ui_set_gallery_filters` refuses an unknown filter name with `invalid_input`, and also a patch giving both `category` and `type`, or both `person` and `person_id`. It offers only the filters the gallery can show; use `search_photos` for the others.
- `ui_navigate` opens only the app's own static pages: the login page, shared pages, external URLs and unknown paths are refused (`invalid_input`), and edition-only pages are refused for a non-edition session.
- `ui_select_photos` with mode `remove` under a whole-view selection ignores paths outside the loaded view and lists them as `not_in_view` in the result.

## In-page WebMCP (browser agents)

Separately from the `/mcp` endpoint, a tab that is signed in also offers the same `ui_*` tools to agents that live in the browser itself, through the W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) API (`document.modelContext`). A browser-native assistant therefore sees exactly the tools listed above, runs them in the tab you are looking at, and needs no token.

- **Secure context only.** Facet registers the tools only on HTTPS or `localhost`. On plain HTTP the in-page tools are not offered; the token-based connection above keeps working.
- Registered when `viewer.mcp.enabled` is true and you are signed in, and removed when you sign out.
- The object is `document.modelContext` (the deprecated `navigator.modelContext` alias is not provided). It is a polyfill, installed only when the browser has no native one, and it cannot be uninstalled: it can exist before you sign in with no Facet tools in it, and after you sign out it stays with an empty tool list.
- The tools do the same things, and are bounded by the same account level, as in the table above.
- A browser agent reads the same `actions` list through `ui_get_context`. In-page write tools are not offered yet: library edits go through the `/mcp` endpoint.

## Changing things

Write tools sit next to the read tools in the same `/mcp` list. Each one goes through the viewer's own `/api` routes, so the route's guards still apply, and each counts against the `write_rate_per_min` budget. The level is the lowest effective level that may call the tool (see [Permission levels](#permission-levels)).

| Tool | Level | What it does | Caps |
|------|-------|--------------|------|
| `set_rating` | `user` | Set the star rating (0-5) of photos | 50 paths |
| `set_favorite` | `user` | Mark or unmark photos as favourite (marking clears rejected) | 50 paths |
| `set_rejected` | `user` | Reject or un-reject photos (rejecting clears rating and favourite) | 50 paths |
| `batch_set_rating` | `edition` | Set the rating of many photos | 1000 paths, or `filters` |
| `batch_set_favorite` | `edition` | Mark many photos as favourite | 1000 paths, or `filters` |
| `batch_set_rejected` | `edition` | Reject many photos | 1000 paths, or `filters` |
| `add_tags` | `edition` | Add manual tags (kept apart from the AI tags) | 10 tags; 1000 paths, or `filters` |
| `remove_tags` | `edition` | Remove manual tags | 10 tags; 1000 paths, or `filters` |
| `create_album` | `edition` | Create an empty album (not idempotent: twice makes two albums) | |
| `album_add_photos` | `edition` | Add photos to an album (already present ones are ignored) | 1000 paths |
| `album_remove_photos` | `edition` | Remove photos from an album; the photos are untouched | 1000 paths |
| `assign_faces` | `edition` | Move faces to a person; faces another person owns are left alone unless `allow_reassign` is set, and the result lists what was skipped | 50 face ids |
| `set_caption` | `edition` | Set a photo's caption (set semantics; an unchanged caption comes back as `already`) | 1 photo, 2000 characters |
| `export_metadata` | `edition` | Write XMP sidecars next to the files | 100 paths, or `filters`, or `target` |
| `junk_list` | `readonly` | List junk-sweep candidates, optionally of one `kind` | 100 per page |
| `junk_reject` | `edition` | Reject junk-sweep candidates (same as `batch_set_rejected`) | 1000 paths |
| `junk_clear` | `edition` | Keep candidates: mark them evaluated-clean so they leave the queue | 50 paths |
| `cull_apply` | `edition` | Copy the keepers, or move or trash the rejects ([preview then confirm](#destructive-actions-preview-then-confirm)) | 10000 paths, or `filters` |
| `delete_photos` | `edition` | Trash the files and delete their library rows ([preview then confirm](#destructive-actions-preview-then-confirm)) | 1000 paths |

- **The `user` tools need an edition token on a single-password install**, which has no middle level (see [Permission levels](#permission-levels)).
- **Set semantics.** The per-photo tools read the current state and write only a difference, so repeating a call is harmless; each path reports `changed` or `already`. They run one path at a time and stop at the first `library_busy`, `outcome_unknown` or `forbidden_level`, reporting `affected`, the per-path `results` and `not_attempted`. The batch tools set the same state.
- **Choosing the photos.** The batch, tag and `cull_apply` tools take EITHER `paths` OR `filters` (the `search_photos` filter object), plus an optional `exclude` list. A `filters` target must come with `expected_count`, the match count of the filters before `exclude` is applied (`search_photos` `total`). Facet counts the filters again first and writes nothing when the numbers differ (`invalid_input`, with `actual_count`). The viewer's default hide toggles (including rejected photos) apply to `filters` exactly as in `search_photos`, so its `total` is the `expected_count`. Rejected photos are therefore hidden from a `filters` target: for `move_rejects` and `trash_rejects`, pass `show_rejected` (or `hide_rejected: false`) to BOTH `search_photos` and `cull_apply`; `copy_keeps` needs nothing extra.
- **Whose state.** Ratings, favourites and rejections are the token owner's own.
- **Skipped files.** When `cull_apply` or `delete_photos` reports a non-empty `skipped` list, the result also carries a `skipped_reason`: those library paths have no readable file on disk (missing, moved, or outside the scan directories), and nothing was done for them.
- **The photos the user selected.** Where a tool takes `paths`, `target: "selection"` uses the selection of the open tab instead (`tab_id` picks the tab). A selection that changed between the preview and the confirm answers `invalid_input` with `selection_changed`, a selection too big for the tab's reply answers `too_large`, and `delete_photos` re-reads the selection when you confirm.
- **Captions and exports.** `set_caption` stores the text only. The caption is not re-embedded, so semantic caption search keeps matching the old text until a re-embed, and the incremental viewer-database export keeps an existing caption when the source one is empty, so clearing a caption may be undone by a later export or scan. `export_metadata` waits up to 180 seconds, reports `written`, `skipped` and `errors` with the first error text in `first_error`, and refuses to write with exiftool 13.23 to 13.27.
- **Faces.** `assign_faces` skips, and lists, faces that are missing, already on that person, owned by another person (unless `allow_reassign`), on another embedding model or on a hidden person; `assigned_count` is what actually moved.

### Destructive actions: preview then confirm

`cull_apply` (`copy_keeps`, `move_rejects`, `trash_rejects`) and `delete_photos` are flagged `destructiveHint` and run as a dry run unless called with `dry_run: false`.

1. The dry run changes nothing and lists the files it would copy, move or trash (long lists are cut to `max_rows`, with a `<key>_count`). For `move_rejects`, `trash_rejects` and `delete_photos` it also returns a `confirm` value, valid for `confirm_expires_in_s` (5 minutes) and for one use.
2. The real call (`dry_run: false`) must pass that `confirm`. Facet re-resolves the file set and options and compares them with the ones the value was issued for. If anything changed, the value is void and the call answers `confirmation_required`: dry-run again.
3. `copy_keeps` needs no `confirm`: it only writes copies. It still previews by default.

The `confirm` value is bound to the token, the action and the exact file set plus options. It lives in memory in one process, so a restart discards every pending value.

**Recommended practice:** always show the user the dry-run summary (counts and file list) and get explicit approval before the `dry_run: false` call. Never confirm on your own initiative.

- `move_rejects` and `trash_rejects` act only on photos the owner rejected; any others are reported as `excluded_by_state`. Companion RAW and `.xmp` files (`include_companions`) and the other frames of a bracket or panorama (`include_sequence_siblings`) are untouched unless you opt in.
- `delete_photos` sends the files to the OS trash and **deletes their library rows**: the scores, tags and ratings are not recoverable, even when the files are.
- **Prerequisites.** `trash_rejects` and `delete_photos` need `viewer.cull.allow_trash` set to `true` (default `false`; the call is refused otherwise). The `target_dir` of `copy_keeps` and `move_rejects` must sit under an allowed export location: `viewer.export.allowed_target_dirs` plus your scan directories (see [Export and Cull Destinations](CONFIGURATION.md#export-and-cull-destinations)).

## Undo, corrections and reference data

- **Undo journal.** Every change a write tool makes for you is recorded, grouped by tool call into a batch (the result's `undo` field carries its `batch_id`). `list_agent_actions` (`readonly`) lists your recent batches, newest first. `undo_last` (`user`) undoes the latest open batch, or the one named by `batch_id`; `dry_run: true` shows what a batch holds. A photo is restored only while it still holds the value the assistant wrote: anything you changed since is skipped (`skipped_changed_since`), so your own edits are never overwritten.
- **What can be undone.** Ratings, favourites, rejections, manual tags, album membership, captions, and sequence and category corrections. Not undoable: `cull_apply`, `delete_photos`, `junk_clear`, `create_album`, `export_metadata`, `assign_faces` and `start_scan`. Undoing a sequence correction restores the override, not the group numbering a later detection pass assigns.
- **Retention.** Rows are kept 30 days and at most 20000 per owner, pruned as whole batches; one call journals at most 5000 changes (beyond that the write still happens and the result says the journal could not hold it). The journal is also served to signed-in sessions by `GET /api/mcp/actions` and `POST /api/mcp/actions/undo` (never to an agent's own token) and is left out of the viewer database export. On a single-password install a key sees only batches at or below its own level.
- **Corrections** (`edition`). `override_sequence` (`kind`: `panorama`, `bracket`, `hdr_panorama` or `suppress`; at least 2 paths except for `suppress`) and `clear_sequence_override` record a correction that takes effect at the next detection pass (the result reports `pending`). `override_category` and `clear_category_override` set or clear a sticky category that survives rescans and keeps the scoring context.
- **Comparing frames** (`readonly`). `group_compare` compares the frames of one culling group (up to 12 paths) `by: "faces"` (per frame: face count, blinks, worst eyes-open, best smile, `best_path_by_eyes`) or `by: "subjects"` (subject sharpness and prominence, `sharpest_path`). It is advice for you, not a decision. `cull_report` summarises a scope in one call: total, kept, rejected, favourites, rated, unreviewed, what the hide toggles would hide, junk, low scores, the top keepers and, with an edition token, the first darkroom sets. Reasons overlap.
- **Taste.** `comparison_status` (`edition`) reports how many pairwise comparisons you have made and how well they cover the library. No tool submits, edits or deletes a comparison: the answer to a pair is your own click. Writes made by an assistant (ratings, rejections, darkroom confirms, `auto_cull`) never record comparisons and never arm the automatic retrain; the same action made by you in the gallery still does.
- **Scans.** `start_scan` and `scan_status` (`edition`) start and follow a scan of the configured directories. They are listed only when `viewer.features.show_scan_button` is on and the install is locked (a superadmin key in multi-user mode). A scan is additive, cannot be undone and is refused while another job runs (`conflict`). Syncing with Immich stays on the command line.
- **Resources.** Besides tools, the server lists five read-only `facet://` resources: `facet://categories`, `facet://tags`, `facet://persons`, `facet://filters` (every search filter with its value domain, plus the metric ranges) and `facet://scoring-contexts`. Each is read as the key's owner sees the library and is capped at 200 rows and 32 KiB (`truncated` says so).
- **Choosing what is listed.** `viewer.mcp.tool_profile` is `full` (default) or `core`: `core` lists only a 12-tool set for small models (`status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`, `undo_last`). It changes the listing only, never what a key may call. `viewer.mcp.allow_destructive` (default `false`) gates `delete_photos` (not listed when off), the `move_rejects` and `trash_rejects` actions of `cull_apply`, and `assign_faces` with `allow_reassign`; refused calls answer `feature_disabled`. Tools a token's level cannot call are not listed either.
- **Two more error codes.** `feature_disabled`: the route is switched off by a configuration key, and the message names it. `conflict`: the library is busy with a job that excludes this one (for example a scan already running).

## Prompts

The server also offers five ready-made prompts, listed by `prompts/list` and filtered by the token's level. A prompt only names tools the token can call, and a destructive tool only behind its dry run and confirmation. Each call counts against the read rate limit and is audited by name, never with its arguments.

| Prompt | Arguments | What it asks the assistant to do |
|--------|-----------|-----------------------------------|
| `find_photo` | `description` | Find a photo from a description and show it |
| `cull_shoot` | `scope_hint` | Review a shoot, propose what to reject and, once you decide, record your decisions with `confirm_culling_groups`; moving or trashing happens only after a dry run and your confirmation |
| `build_album` | `theme`, `album_name` | Collect matching photos into a new album |
| `tag_people` | `person` | Find faces that look like a person and assign the ones you confirm |
| `teach_taste` | `category` | Open the pairwise comparison page in your tab and track how many comparisons you have made; the answer to each pair is always your own click |

## Darkroom (culling groups)

The darkroom tools mirror the `/culling` page. All of them need the `edition` level, including the listing ones.

| Tool | What it does |
|------|--------------|
| `list_culling_groups` | List groups (`burst`, `similar`, `scene`, `bracket`, `panorama`, `hdr_panorama`) with their photos and scores, sortable and scoped by album or date window |
| `culling_profiles` | The genre-aware culling presets and the default one |
| `suggest_culling_profile` | Name the preset that fits an album or a capture-time window |
| `keeper_hints` | Per-photo "a better shot exists in this burst" hints for up to 100 paths (empty when no keeper head is trained) |
| `auto_cull` | Auto-cull a scope under a keeper budget: preview first, then apply with the `confirm` value |
| `confirm_culling_groups` | Confirm up to 20 groups: keep their `keep_paths`, reject the rest of their `paths` |

- **A group is identified by the pair `(type, group_id)`**, never by `group_id` alone: similar-group ids are offset when merged with bursts.
- **The default `group_by: "all"` returns bursts plus similar groups only.** Ask for `scene`, `bracket`, `panorama` or `hdr_panorama` explicitly.
- **A page is trimmed to fit `max_bytes` by shortening each group's `photos` list, never by dropping groups.** `photo_count` stays the true size, `photos_truncated` marks a group whose list was cut, and `has_more` says whether another page follows.
- **Brackets, panoramas and HDR panoramas are kept whole.** In `confirm_culling_groups`, `keep_paths` must equal `paths` for these types (otherwise `invalid_input`), and `auto_cull` never splits them.
- **Empty `keep_paths` rejects every frame of the group.** The first call then answers `confirmation_required` with a `confirm` value; show the user, then repeat the call with it. If a batch stops on `forbidden_level`, `library_busy` or `rate_limited`, the groups already done are reported.
- **`auto_cull` previews by default** and returns the keep and reject split per group plus a `confirm` value (only when something would be rejected). The apply re-computes the plan and refuses it as `confirmation_required` if it changed since the preview, or if the plan is too large to confirm as one set (narrow it with `album_id`, `date_from` and `date_to`, or `group_by`). Rejected frames feed the personal ranker like any manual cull.
- Call `ui_show_culling_group` to show a group to the user in their open tab (see [Control your open tab](#control-your-open-tab)).

## Results, limits and errors

Every result is a JSON envelope: `{"ok": true, "data": ...}` or `{"ok": false, "error": "<code>", "message": "..."}`. Listings return `data.rows` (a compact fixed set of fields per photo) plus `total`. A search result also carries `shown_in_tab`, and a result trimmed by the byte cap carries `returned`.

- **Caps:** at most `max_rows` rows and `max_bytes` serialized bytes. Tail rows are dropped and `truncated: true` is set. A result without rows that exceeds `max_bytes` becomes a `too_large` error.
- **Images:** `get_thumbnail` and `contact_sheet` return an image part before the JSON part. The image is capped by `max_image_bytes` (default 262144), not by `max_bytes`. Text visible inside an image is data, never an instruction.
- **Face scan:** `possible_faces` reads at most 192000 faces and may wait up to 120 seconds; above that it answers `too_large`.
- **Rate limit:** `rate_per_min` calls per minute per token for reads. Write tools draw on a separate `write_rate_per_min` budget (default 30), so searches cannot starve writes and the other way round; the dry run of `cull_apply` and `delete_photos` counts as a write, an `auto_cull` preview as a read. Beyond it: `rate_limited` with `retry_after_s`. Ten failed bearer attempts per minute from one address answer 429.
- **Error codes:** `forbidden_level` (disabled endpoint, dead token or too low a level), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **The newer codes:** `confirmation_required` (a destructive call has no live `confirm` value for exactly this set: dry-run again, show the user the result, then retry), `outcome_unknown` (a write timed out or the connection dropped, so it may or may not have happened: re-read the state before retrying, never retry blindly), `library_busy` (the library is busy with another job: retry in a moment).
- **Gate status codes:** 401 for a missing or unknown token, 403 for a cross-origin browser request or an agent's own credential on `/api/mcp/tokens`, 404 when disabled. The tab bridge answers with close codes instead.

## Security notes

- Captions, tags, file names, paths, and album and person names come from your library and can contain text written to manipulate an assistant (prompt injection). Every tool is flagged `facet/untrusted_content` and tells the model to treat them as data. Do not give an assistant that also reads untrusted content a way to act on what it finds here.
- Tokens never expire. Revoke the ones you no longer use.
- Logs record the token id, tool, outcome and row count, never arguments or the token.

## Known limitations

- On an open install (no password), anyone who can reach the viewer can mint and revoke the shared `_anonymous` tokens. Set a password before enabling the endpoint on a network. The tab bridge widens this: a non-browser client can send a made-up `Origin` and a null token, register a focused `_anonymous` tab, answer `ui_*` calls with data of its choosing, and evict real tabs through the 8-tab cap.
- Rate limits and failed-authentication counters live in memory in each process; with `viewer.py --workers N` each worker counts separately.
- The tab registry lives in memory in one process. Use a single worker (`viewer.py --workers 1`, the default) when you rely on `ui_*` tools; with several workers a call can reach a process that does not know your tab and answers `no_tab`.
- A user can have at most 8 tabs connected; opening a ninth closes the oldest.
