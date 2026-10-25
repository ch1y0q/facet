# Relink a missing photo after an explicit move

`python -m db.relink` updates existing Facet database paths after you have moved files yourself. It never moves, copies, deletes, edits originals/sidecars, or contacts Immich. It is an offline maintenance command for the operator who has access to the database and configured folders. Stop the viewer, scanners and external file editors first; back up the database and review the plan before applying it.

The existing database has no cryptographic hash of original file bytes. `phash` and manual-face grayscale signatures do not prove byte identity. Every plan therefore says `original_bytes_unknown`. The target SHA-256 only identifies the new file that was previewed. Applying explicitly asserts that you have independently identified the correct moved file; this is never an automatic verified match. A wrong assertion can attach existing annotations to the wrong image.

## Preview, review, then apply

Create a JSON list with exact canonical absolute paths. A missing source must already be registered in Facet; a destination must exist as an image and must not already have a photo row:

```json
[
  {
    "old": "/photos/before/portrait.jpg",
    "new": "/photos/after/portrait-renamed.jpg",
    "companions": [
      {
        "old": "/photos/before/portrait.jpg.xmp",
        "new": "/photos/after/portrait-renamed.jpg.xmp",
        "kind": "sidecar_full"
      }
    ]
  }
]
```

```sh
# Read-only database preview; create a private (0600), exclusive review artifact.
python -m db.relink --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Inspect every old/new path, unknown-byte identity label, target hash and
# dimensions, references, companions and visibility policy in relink-plan.json.
# Replace REVIEWED_PLAN_ID with that artifact's exact plan_id after reviewing it.
python -m db.relink --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

Multi-user mode also requires `--user alice` in both commands. This is an operator scope selector, not a replacement for OS access control or an authenticated API. Both paths must be visible to that user, and the set of **all** users able to see the photo must remain identical. Private-to-shared or other cross-user moves are refused. Both paths must be inside explicit configured scan/user/shared directories. Blank root configuration, inaccessible roots and `viewer.path_mapping` are refused; this initial tool supports native canonical paths only.

Apply rechecks the entire reviewed plan inside one SQLite write transaction. Changed target files, photo rows, annotations, schema, database inode or visibility policy require a new preview. A failed batch rolls back all its database writes. A successful apply prints a receipt with the plan ID. It does not store a new logical asset ID or remote UUID mapping.

## What follows the photo

Photo rowids, ratings/Keep/GPS, tags, face/person IDs and manual UUIDs, comparisons, learned scores, per-user preferences, overrides, fixed album membership/covers/client picks, extraction snapshots and vector embeddings retain their associations. Existing photos foreign keys are discovered from the real schema; a new unregistered path column is refused rather than silently orphaned. Derived statistics are invalidated; durable training state remains.

All manual rectangles are retained but require review on the new path. The coarse old signature cannot prove the missing original's pixels. A `relink_unverified` marker prevents ordinary signature checks from clearing that review state; open the editor and explicitly save each rectangle against the new frame before it can export or suppress detections. Existing rectangle/person IDs are preserved.

Immich push/pending state remains unchanged: a local filename assertion cannot verify a remote identity. No remote rating, clear, album membership or UUID is relinked. Review the remote mapping separately before syncing. Historical scan-failure paths remain historical; smart album filter predicates and logical sequence group keys are not silently rewritten. Static memberships and sequence/burst/duplicate group values remain intact.

## Explicit companions and refusals

List companions explicitly; the tool cannot discover unindexed RAW/XMP files that have vanished from the old directory. `sidecar_full` means `photo.ext.xmp`, `sidecar_basename` means `photo.xmp`, `sidecar_facet` means `photo.ext.facet.xmp`, and `raw` keeps an explicitly supplied same-directory/stem RAW pair compatible with current culling. These filename rules validate a declared relationship; they do not prove file identity. Indexed RAW photos need their own top-level relink entry so their annotations are preserved.

Unlisted sidecars or RAW companions at the destination are refused, including Facet fallback packets and case variants. Multiple RAW candidates and ambiguous XMP ownership are refused, including `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, basename and case/Unicode collisions. No companion is assigned by first match. Existing companion file bytes are hashed/rechecked and left untouched. Unlisted missing companions remain unknown; do not interpret an empty list as proof none existed.

Copies with a still-present old original, missing/unreadable old parents, existing destination photo/dependent rows, repeated mappings, duplicate photo content or target inodes, case-only/Unicode-only changes, symlinks and extension/format changes are refused. Stored canonical dimensions, when known, must match the decoded target. No similarity/filename search or automatic reconciliation runs.

Limits: 100 photos, 300 explicitly named files, 512 MiB per file, 2 GiB total file bytes and 2 MiB JSON input/review plan. Reduce a batch when a limit is reached. The database transaction is atomic; the filesystem is not locked against other applications, hence the offline requirement. No real external application or remote-server round trip is claimed by the fixture tests.

Readable directories do **not** prove that storage is mounted. An unmounted volume may leave an empty readable mount point indistinguishable from a genuinely empty post-move directory. The plan explicitly reports `source_mount_status: not_verified`; confirm independently that each source was moved rather than merely unavailable before acknowledging identity. The command does not detect every offline-volume condition. Review artifacts contain private full paths and user-scope policy; `--plan-out` creates them exclusively with mode 0600 on POSIX.
