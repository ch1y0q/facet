# AI Agents (MCP)

> 🌐 **English** · [Français](fr/AGENTS.md) · [Deutsch](de/AGENTS.md) · [Italiano](it/AGENTS.md) · [Español](es/AGENTS.md) · [Português](pt/AGENTS.md) · [简体中文](zh/AGENTS.md)

Facet can act as a [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server, so an AI assistant such as Claude Code can search and inspect your library with the same filters the gallery uses. The endpoint is read-only: it exposes nine read tools and changes nothing in your library.

## Enable it

The endpoint is **off by default**. Set `viewer.mcp.enabled` to `true` in `scoring_config.json` (see [Agent Endpoint (MCP)](CONFIGURATION.md#agent-endpoint-mcp)) and restart the viewer, or reload the configuration. While it is off, `/mcp` and every `/api/mcp/*` route answer 404.

The endpoint is `POST /mcp` on the viewer's own port: Streamable HTTP, stateless, plain JSON responses. `GET` answers 405. No WebSocket headers are needed in a reverse proxy.

## Mint a token

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

A token dies automatically when its owner's credentials change: the viewer or edition password in single-password mode, the owner's password in multi-user mode, or the owner's account being deleted. It then answers 401 at the gate.

## Tools

All nine registered tools are read-only:

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

## Results, limits and errors

Every result is a JSON envelope: `{"ok": true, "data": ...}` or `{"ok": false, "error": "<code>", "message": "..."}`. Listings return `data.rows` (a compact fixed set of fields per photo) plus `total`.

- **Caps:** at most `max_rows` rows and `max_bytes` serialized bytes. Tail rows are dropped and `truncated: true` is set. A result without rows that exceeds `max_bytes` becomes a `too_large` error.
- **Rate limit:** `rate_per_min` calls per minute per token (a separate `write_rate_per_min` budget exists for write calls). Beyond it: `rate_limited` with `retry_after_s`. Ten failed bearer attempts per minute from one address answer 429.
- **Error codes:** `forbidden_level` (disabled endpoint, dead token or too low a level), `invalid_input`, `not_found`, `rate_limited`, `library_busy`, `upstream_error`, `outcome_unknown`, `too_large`.
- **Gate status codes:** 401 for a missing or unknown token, 403 for a cross-origin browser request, 404 when disabled.

## Security notes

- Captions, tags, file names, paths, and album and person names come from your library and can contain text written to manipulate an assistant (prompt injection). Every tool is flagged `facet/untrusted_content` and tells the model to treat them as data. Do not give an assistant that also reads untrusted content a way to act on what it finds here.
- Tokens never expire. Revoke the ones you no longer use.
- Logs record the token id, tool, outcome and row count, never arguments or the token.

## Known limitations

- On an open install (no password), anyone who can reach the viewer can mint and revoke the shared `_anonymous` tokens. Set a password before enabling the endpoint on a network.
- Rate limits and failed-authentication counters live in memory in each process; with `viewer.py --workers N` each worker counts separately.
- `viewer.mcp.bridge` is read by the `status` tool but nothing else uses it yet.
