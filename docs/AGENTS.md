# AI Agents (MCP)

> 🌐 **English** · [Français](fr/AGENTS.md) · [Deutsch](de/AGENTS.md) · [Italiano](it/AGENTS.md) · [Español](es/AGENTS.md) · [Português](pt/AGENTS.md) · [简体中文](zh/AGENTS.md)

Facet can act as a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server, so an AI assistant such as Claude Code can search and inspect your library with the same filters the gallery uses. It exposes nine read tools that change nothing in your library and nine `ui_*` tools that move the browser tab you already have open (page, filters, selection) and never write library data. Tokens that are allowed to can also [change things](#changing-things) (ratings, flags, tags, albums, culling and deletion) and work the [darkroom](#darkroom-culling-groups).

## Enable it

The endpoint is **off by default**. Set `viewer.mcp.enabled` to `true` in `scoring_config.json` (see [Agent Endpoint (MCP)](CONFIGURATION.md#agent-endpoint-mcp)) and restart the viewer, or reload the configuration. While it is off, `/mcp` and every `/api/mcp/*` route answer 404.

The endpoint is `POST /mcp` on the viewer's own port: Streamable HTTP, stateless, plain JSON responses. `GET` answers 405. Only the tab bridge, `/api/mcp/bridge`, is a WebSocket; see [Control your open tab](#control-your-open-tab).

## Mint a token

The easiest way is the browser. With `viewer.mcp.enabled` on, open the account menu and choose **Connect an assistant**. Under **Create a token**, enter a **Name** and pick **What the assistant may do**: **Read and pilot only**, plus **Act as me** or **Full editing** when your session holds that level (a token cannot out-rank the session that creates it). Click **Create token**: the token appears once under **Your new token**, so copy it now. **Access tokens** lists your tokens with their last use and revokes one. **Add it to Claude Code** shows the ready-to-paste Claude Code command (see below), and **This tab** says whether this tab is connected so assistants can drive it. The level list is limited to what the server will grant: an open install offers only **Read and pilot only**, **Act as me** appears only on multi-user installs and **Full editing** only in an edition session. After creating, the dialog states the level actually granted ("Access granted: {level}").

Scripted alternative (curl):

An assistant authenticates with a personal token that starts with `fct_`. Mint one with an authenticated request (the token is returned **once**; Facet stores only its SHA-256 hash):

```bash
TOKEN=$(curl -s -X POST http://localhost:5000/api/auth/login -H 'Content-Type: application/json' -d '{"password": "YOUR_VIEWER_PASSWORD"}' | jq -r .access_token)
curl -s -X POST http://localhost:5000/api/mcp/tokens -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name": "claude-code", "level": "readonly"}'
```

The response carries the plaintext in `token`. `GET /api/mcp/tokens` lists your tokens (never the secret), and `DELETE /api/mcp/tokens/{id}` revokes one. A superadmin can list every owner's tokens with `?all=1` and revoke any of them. Each owner can hold at most 20 live tokens (412 beyond that). These routes refuse an agent's own credential, so an assistant can never mint, list or revoke tokens.

## Connect Claude Code

```bash
claude mcp add --transport http facet http://localhost:5000/mcp --header "Authorization: Bearer fct_YOUR_TOKEN"
```

The tools then appear as `mcp__facet__search_photos` and so on. Use HTTPS when the viewer is reachable beyond your own machine, since the token travels in a header on every call.

## Permission levels

A token is minted with a grant: `readonly`, `user` or `edition`. The **effective** level is recomputed on every call as the lower of the token's grant and its owner's live level:

- Single-password installs: `user` is capped to `readonly` at mint time, because that mode has no middle level. An `edition` token needs an edition session and works only while the edition password is unchanged.
- Multi-user installs: an `edition` token of a user who is later demoted drops to `user`; a promotion never raises a token above its grant.
- Open installs (no password set): tokens are always `readonly` and belong to a shared `_anonymous` owner.
- Single-password installs have no `user` level: the effective level is `edition` or `readonly`, so the tools marked `user` under [Changing things](#changing-things) also need an `edition` token there.
- Each tool has its own minimum level, checked before anything is read or written; a lower token gets `forbidden_level`.

A token dies automatically when its owner's credentials change: the viewer or edition password in single-password mode, the owner's password in multi-user mode, or the owner's account being deleted. It then answers 401 at the gate.

## Tools

The nine data tools are read-only:

| Tool | What it does |
|------|--------------|
| `search_photos` | Filter and sort the library like the gallery, with the viewer's default hide toggles applied unless the filter sets them (reports `hidden_summary`) |
| `semantic_search` | Find photos by meaning, or by words in captions with `scope: "text"` |
| `get_photo` | Full detail of one photo by its path (the histogram is left out) |
| `similar_photos` | Photos similar to one photo, by visual embedding or by colour |
| `filter_options` | The vocabulary a filter accepts: cameras, lenses, tags, persons, patterns, categories, narrative moments, junk kinds, metric ranges |
| `list_persons` | Recognised people, optionally filtered by name |
| `list_albums` | Albums the token's owner can see |
| `library_stats` | Library size, type counts and score overview |
| `status` | Who the token is, its effective level and the server flags |

## Control your open tab

Next to the data tools, the server always lists nine `ui_*` tools that act on the Facet tab you have open in a browser: they move the page, change the filters or the selection, and read back what you see. They never write library data, so a `readonly` token is enough.

| Tool | What it does |
|------|--------------|
| `ui_navigate` | Go to a page (gallery, persons, albums, stats, ...) |
| `ui_set_gallery_filters` | Merge a patch into the gallery filters and sort (`null` removes a filter, `replace: true` starts from none) |
| `ui_get_gallery_view` | Route, active filters, total matches, the first visible photo paths and the selection count |
| `ui_open_photo` | Open one photo |
| `ui_select_photos` | Select explicit `paths`, or the whole filtered view with `select_view: true`, with mode `replace`, `add` or `remove` |
| `ui_clear_selection` | Clear the selection |
| `ui_get_selection` | The `scope` (`paths` or `view`) and `count`, with the `paths`, or for a view the `filters` and `excluded_paths` |
| `ui_next_page` | Load the next page of the gallery |
| `ui_show_culling_group` | Open the darkroom on one group, identified by `(type, group_id)` (edition accounts) |

How it works:

- While you are signed in and both `viewer.mcp.enabled` and `viewer.mcp.bridge` are true, every Facet tab opens a same-origin WebSocket to `/api/mcp/bridge` and authenticates with your session in its first message. The bridge is on by default; set `viewer.mcp.bridge` to `false` to turn it off, and the `ui_*` tools then answer a clear error.
- A tool only reaches the tabs of the token's owner. On a single-password install every session is the same user, and on an open install every tab belongs to the shared `_anonymous` user.
- With several tabs open, the most recently focused one is used and the result's `tab` field says so. Pass `tab_id` (listed by `status`) to choose another.
- A tab refuses what its account may not do (for example `/culling` for a non-edition account) and the tool returns that refusal.
- What a tab sends back is untrusted: it is bounded in depth, string length and list length, and capped by `max_bytes`.
- Errors: `no_tab` (no tab is connected, or the bridge is off), `tab_timeout` (no answer within `call_timeout_s`) and `tab_outdated` (the open tab does not know the tool; reload the page after upgrading Facet).
- A reverse proxy must forward the WebSocket upgrade for `/api/mcp/bridge`; see [Deployment](DEPLOYMENT.md). If it rewrites the `Host` header, list the public origin in `viewer.mcp.allowed_origins` (for example `["https://photos.example.com"]`), because the page's origin must match the host or be listed.
- The tab registry is per process, so the bridge needs a single worker (the default).

Beyond the basics above:

- `ui_set_gallery_filters` takes you to the gallery first when another page is open, then applies the patch. It refuses a whole patch (`invalid_input`) that names a filter the tab has no control for; use `search_photos` for those.
- `ui_get_gallery_view`, `ui_next_page` and `ui_select_photos` with `select_view` need the gallery (or an album) to be the open page, otherwise they answer `no_active_view`; call `ui_navigate` to `/` first. Give `ui_select_photos` exactly one of `paths` and `select_view`.
- `no_tab` also means no Facet tab is open: open Facet in a browser and sign in. **This tab** in the **Connect an assistant** dialog shows the connection state, with the tab id.
- A tab stops reconnecting once its session is rejected (sign in again), and waits until you return to it after another tab of yours took over.
- The tab bridge connects only when the server reports the bridge as available (the endpoint is on and `viewer.mcp.bridge` is true); with the bridge off, tabs do not connect at all.
- `ui_set_gallery_filters` refuses an unknown filter name with `invalid_input`, and also a patch giving both `category` and `type`, or both `person` and `person_id`. It offers only the filters the gallery can show; use `search_photos` for the others.
- `ui_navigate` opens only the app's own static pages: the login page, shared pages, external URLs and unknown paths are refused (`invalid_input`), and edition-only pages are refused for a non-edition session.
- `ui_select_photos` with mode `remove` under a whole-view selection ignores paths outside the loaded view and lists them as `not_in_view` in the result.

## In-page WebMCP (browser agents)

Separately from the `/mcp` endpoint, a tab that is signed in also offers the same `ui_*` tools to agents that live in the browser itself, through the W3C [WebMCP](https://webmachinelearning.github.io/webmcp/) API (`navigator.modelContext`). A browser-native assistant therefore sees exactly the tools listed above, runs them in the tab you are looking at, and needs no token.

- **Secure context only.** Facet registers the tools only on HTTPS or `localhost`. On plain HTTP they are not offered and the **Connect an assistant** dialog says so; the token-based connection above keeps working.
- Registered when `viewer.mcp.enabled` is true and you are signed in, and removed when you sign out.
- The tools do the same things, and are bounded by the same account level, as in the table above.

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
| `junk_list` | `readonly` | List junk-sweep candidates, optionally of one `kind` | 100 per page |
| `junk_reject` | `edition` | Reject junk-sweep candidates (same as `batch_set_rejected`) | 1000 paths |
| `junk_clear` | `edition` | Keep candidates: mark them evaluated-clean so they leave the queue | 50 paths |
| `cull_apply` | `edition` | Copy the keepers, or move or trash the rejects ([preview then confirm](#destructive-actions-preview-then-confirm)) | 10000 paths, or `filters` |
| `delete_photos` | `edition` | Trash the files and delete their library rows ([preview then confirm](#destructive-actions-preview-then-confirm)) | 1000 paths |

- **The `user` tools need an edition token on a single-password install**, which has no middle level (see [Permission levels](#permission-levels)).
- **Set semantics.** The per-photo tools read the current state and write only a difference, so repeating a call is harmless; each path reports `changed` or `already`. They run one path at a time and stop at the first `library_busy`, `outcome_unknown` or `forbidden_level`, reporting `affected`, the per-path `results` and `not_attempted`. The batch tools set the same state.
- **Choosing the photos.** The batch, tag and `cull_apply` tools take EITHER `paths` OR `filters` (the `search_photos` filter object), plus an optional `exclude` list. A `filters` target must come with `expected_count`, the match count of the filters before `exclude` is applied (`search_photos` `total`). Facet counts the filters again first and writes nothing when the numbers differ (`invalid_input`, with `actual_count`).
- **Whose state.** Ratings, favourites and rejections are the token owner's own.

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
- **Brackets, panoramas and HDR panoramas are kept whole.** In `confirm_culling_groups`, `keep_paths` must equal `paths` for these types (otherwise `invalid_input`), and `auto_cull` never splits them.
- **Empty `keep_paths` rejects every frame of the group.** The first call then answers `confirmation_required` with a `confirm` value; show the user, then repeat the call with it. If a batch stops on `forbidden_level`, `library_busy` or `rate_limited`, the groups already done are reported.
- **`auto_cull` previews by default** and returns the keep and reject split per group plus a `confirm` value (only when something would be rejected). The apply re-computes the plan and refuses it as `confirmation_required` if it changed since the preview, or if the plan is too large to confirm as one set (narrow it with `album_id`, `date_from` and `date_to`, or `group_by`). Rejected frames feed the personal ranker like any manual cull.
- Call `ui_show_culling_group` to show a group to the user in their open tab (see [Control your open tab](#control-your-open-tab)).

## Results, limits and errors

Every result is a JSON envelope: `{"ok": true, "data": ...}` or `{"ok": false, "error": "<code>", "message": "..."}`. Listings return `data.rows` (a compact fixed set of fields per photo) plus `total`.

- **Caps:** at most `max_rows` rows and `max_bytes` serialized bytes. Tail rows are dropped and `truncated: true` is set. A result without rows that exceeds `max_bytes` becomes a `too_large` error.
- **Rate limit:** `rate_per_min` calls per minute per token for reads. Write tools draw on a separate `write_rate_per_min` budget (default 30), so searches cannot starve writes and the other way round; the dry run of `cull_apply` and `delete_photos` counts as a write, an `auto_cull` preview as a read. Beyond it: `rate_limited` with `retry_after_s`. Ten failed bearer attempts per minute from one address answer 429.
- **Error codes:** `forbidden_level` (disabled endpoint, dead token or too low a level), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `confirmation_required`, `too_large`, `no_tab`, `tab_timeout`, `tab_outdated`.
- **The newer codes:** `confirmation_required` (a destructive call has no live `confirm` value for exactly this set: dry-run again, show the user the result, then retry), `outcome_unknown` (a write timed out or the connection dropped, so it may or may not have happened: re-read the state before retrying, never retry blindly), `library_busy` (the library is busy with another job: retry in a moment).
- **Gate status codes:** 401 for a missing or unknown token, 403 for a cross-origin browser request, 404 when disabled.

## Security notes

- Captions, tags, file names, paths, and album and person names come from your library and can contain text written to manipulate an assistant (prompt injection). Every tool is flagged `facet/untrusted_content` and tells the model to treat them as data. Do not give an assistant that also reads untrusted content a way to act on what it finds here.
- Tokens never expire. Revoke the ones you no longer use.
- Logs record the token id, tool, outcome and row count, never arguments or the token.

## Known limitations

- On an open install (no password), anyone who can reach the viewer can mint and revoke the shared `_anonymous` tokens. Set a password before enabling the endpoint on a network. The tab bridge widens this: a non-browser client can send a made-up `Origin` and a null token, register a focused `_anonymous` tab, answer `ui_*` calls with data of its choosing, and evict real tabs through the 8-tab cap.
- Rate limits and failed-authentication counters live in memory in each process; with `viewer.py --workers N` each worker counts separately.
- The tab registry lives in memory in one process. Use a single worker (`viewer.py --workers 1`, the default) when you rely on `ui_*` tools; with several workers a call can reach a process that does not know your tab and answers `no_tab`.
- A user can have at most 8 tabs connected; opening a ninth closes the oldest.
