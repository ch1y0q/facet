# Facet contribution guidance

Read `CLAUDE.md` and the relevant module documentation before changing code. These notes capture recurring maintainer feedback; verify them against current source rather than treating old PR descriptions as specifications.

## Reviews and parallel work

Facet's maintainer uses [claude-review-all](https://github.com/ncoevoet/claude-review-all) for the review axes and severity tiers reflected in PR comments. In Claude Code with that plugin installed, use `/review-all:review-all` against the diff or PR before publishing; see its README for current setup and targets. It runs the repository gates and parallel reviews, then independently verifies findings. If the plugin is unavailable in the current environment, run the available gates and independent reviews explicitly and record that limitation; never claim the plugin ran. Treat CRITICAL/IMPORTANT as blocking defects, DEBT as maintenance work, SUGGESTED as a measured improvement, and QUESTION as an intent decision to resolve explicitly.

- Fetch the current upstream master and the exact remote PR head before editing. The maintainer sometimes pushes fixes directly to our branches. Preserve those commits; never force-push.
- Read issue comments, submitted reviews, and inline review comments. Track each concrete item by comment URL, current status, reproducer or source evidence, tests, and fixing commit. A merged PR or green CI does not prove every comment was addressed.
- Assign one owner per branch/worktree. Keep independent PRs separate; review overlapping changes at their integration boundaries. Request a second review after fixes, including error, cancellation, and retry paths.
- Use an isolated worktree. Preserve the user's dirty checkout and the worktree serving the live app. Tests must use temporary databases and images, never the user's library. Back up the live database before a requested runtime upgrade.
- Before pushing, check the remote head again, regenerate affected contracts, and check mergeability against current master. Push only the intended branch without tags. Record the exact tested and pushed SHA.
- CI results belong to a particular SHA. Empty checks do not mean success: inspect conflicts, queued runs, and approval requirements. Distinguish local passes, hosted passes, pending runs, and skips.
- Keep PR titles and bodies brief and concrete: behavior changed, why, and validation. Avoid review transcripts and claims unsupported by tests. Do not post GitHub comments or messages without user authorization.

## Metadata, imports, and viewer exports

- Preserve foreign XMP values and structures. ExifTool JSON can coerce numeric-looking strings and case variants of booleans; test exact lexical round trips with real ExifTool, including repeated export and clear.
- Respect the supported ExifTool versions, not only the local version or Docker image. Feature-gate unsupported structured writes and document skipped fields. Verify older distribution versions and Windows transport when changing metadata commands.
- Encode fixtures and subprocess I/O explicitly as UTF-8. Unicode argument transport must preserve whitespace, CR/LF, backslashes, punctuation, and option-like caption text. Clean private temporary files on success and failure.
- Validate all targets and preconditions before the first write. Test embedded originals with malformed companion sidecars and assert unchanged bytes on refusal. A preflight does not make separate filesystem writes atomic; document the actual boundary.
- Distinguish unsafe existing metadata from serializer failures. Return the documented precondition status without leaking resolved server paths. One bad photo must not abort an entire batch through an unexpected exception type.
- Combine naming policy, field selection, ownership, edit clocks, and explicit overrides in both preview and apply. Reject ambiguity between RAW/JPEG, double extensions, fallback names, case variants, and Unicode variants.
- Dry-run must work on supported released schemas without migrating or writing. Test a real older schema, not merely a current schema with one new table removed.
- Viewer-local edits and scanner edits have different authority. Imported receipts must not become independent viewer edits on a later export. Test multiple export/reset/edit/export cycles for global and per-user state. Treat Keep and Reject as one consistent decision.
- Classify private operational tables explicitly for viewer export and relinking. Never silently ship user-specific paths/history or drop durable edit provenance.
- Relinking must handle independently indexed RAW/JPEG pairs, supported SQLite versions, concurrent file changes, and transaction rollback. Define and test moved-folder and missing/offline-file policies explicitly. Test each refusal with a meaningful case.

## Async work, navigation, and performance

- SQLite sentinel/token reads and filesystem checks can block even when warm. Keep synchronous operations off async request loops, including cache hits and count helpers. Preserve the order between token capture and snapshot reads.
- Cached authorized results must include the actual database and visibility scope. A shared internal vector matrix must check current visibility before limiting results; its revision, vectors and visibility belong to one read snapshot. Test replacement, in-place restore, external commits, read failure, cancellation, and multi-user alternation. Measure invalidation and memory behavior before claiming an optimization.
- Derived cache revisions need transactional tracking, a collision-resistant identity across restores, schema-change invalidation, and safe uncached reads when tracking is missing. A shared vector matrix uses the requested encoder width; malformed private vectors must not break other accounts. Keep peak allocations bounded by permitted rows: an empty or small authorized scope must not allocate hidden-library vectors. Document cold/warm and distinct-scope cache tradeoffs.
- Parking the gallery must stop obsolete background reads while permitting explicit photo-page paging and review actions. Keep page, targeted-row, count, and advisory-hint refresh needs distinct; one completed request must not erase another operation's pending refresh.
- Test real router events and HTTP requests for ArrowRight, Keep, Back, cancelled/redirected album navigation, failed recovery, retry, and identity changes. Component destruction alone is not a sufficient guard during navigation. Verify stale completions cannot overwrite a newer route or account.
- Avoid replaying all loaded pages for a targeted update. Cancelled keeper hints need a bounded retry; unchanged Back should not issue redundant page reads or counts.
- Background jobs need portable atomic receipt handling, recoverable status polling, cancellation between files, precise lock errors, and documented album membership/caps. Do not conflate an unusable lock with a busy job.

## Tests, contracts, and documentation

- Reproduce reported bugs before fixing them. Assert actual effects: bytes, database rows, requests, positive branches, and rollback. A stubbed refresh does not prove selection preservation; a negative-only test does not protect a success path.
- Use synchronization events instead of timing sleeps for concurrency assertions. Preserve production dependency injection and authorization in tests.
- Run both application and spec TypeScript checks, relevant client/backend suites, lint, and production build when affected. Use dependencies and runtime versions matching the branch and CI.
- Regenerate API schemas, i18n constants, tool manifests, and filter keys when their inputs change. Update every pinned route authorization set for new routes.
- Keep all seven language files and guides consistent. Place changelog entries under the proper section; keep documentation headings and cross-links correct and remove duplicated paragraphs.
- Use the project's date format (`dd/MM/yyyy`, with time when needed), generated i18n constants, proper singular/plural text, and accessible hint associations. Check read-only users see instructions for actions actually available to them.
- Review shared-browser persistence deliberately: identity-scoped storage is not the same as clearing private history on logout. Do not claim image HTTP caches are cleared unless that is implemented and verified.

## Context and handoff

When `LOCAL_REVIEW_HANDOFF.md` is present, read it for the ongoing local task and report locations; it is a private, untracked handoff, not PR content. Keep changing PR status in a separate review ledger, not in this instruction file. Record exact heads, remaining questions, test commands/results, and local runtime source so the next session can resume without repeating old mistakes. Use the existing Graphify graph for orientation when available, then verify current source because the graph may be stale. Follow the user's Context7 requirements when consulting library or tool documentation.
