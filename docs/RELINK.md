# Relink a missing photo after an explicit move

`python database.py --relink-photos` updates Facet's database paths after you moved files yourself. It never moves, copies, deletes or edits originals or sidecars, and it never contacts Immich. It is an offline maintenance command.

Before you apply a plan:

- Stop the viewer, scanners and external file editors.
- Back up the database.
- Review the plan.

Apply takes Facet's library lock. If another library job is running, it exits with code 75 and changes nothing; an unusable lock exits with code 1. Preview is read-only and takes no lock. The lock only covers jobs on one host.

> **Warning:** Facet stores no hash of the original file bytes, so it cannot prove the new file is the moved one. Every plan says `original_bytes_unknown`; `phash` and manual-face signatures do not prove identity. The target SHA-256 only identifies the file you previewed. Applying asserts that you checked the match yourself. A wrong assertion attaches existing annotations to the wrong image.

Moving or renaming a whole directory is not supported when the old parent no longer exists. Do not recreate empty old parents to get around this check.

## Preview, review, then apply

Create a JSON list of exact canonical absolute paths. Each source must already be in Facet. Each destination must exist as an image and must not already have a photo row:

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
python database.py --relink-photos --db library.db --config scoring_config.json \
  --mapping moved.json --plan-out relink-plan.json

# Inspect every old/new path, unknown-byte identity label, target hash and
# dimensions, references, companions and visibility policy in relink-plan.json.
# Replace REVIEWED_PLAN_ID with that artifact's exact plan_id after reviewing it.
python database.py --relink-photos --db library.db --config scoring_config.json \
  --apply-plan relink-plan.json --ack-plan REVIEWED_PLAN_ID \
  --acknowledge-unverified-identity
```

In multi-user mode, add `--user alice` to both commands. It selects whose scope to check; it is not access control. Rules:

- Both paths must be visible to that user.
- The set of **all** users who can see the photo must stay the same. Private-to-shared and other cross-user moves are refused.
- Both paths must be inside explicitly configured scan, user or shared directories.
- Blank root configuration, inaccessible roots and `viewer.path_mapping` are refused. Only native canonical paths are supported.

Apply rechecks the whole plan in one database transaction. If target files, photo rows, annotations, schema, the database file or visibility changed, run a new preview. A failed batch rolls back all its database writes. A successful apply prints a receipt with the plan ID.

## What follows the photo

These keep their association with the photo:

- photo IDs, ratings, Keep and GPS
- tags, faces, person IDs and manual face UUIDs
- comparisons, learned scores and per-user preferences
- overrides, fixed album membership, covers and client picks
- extraction snapshots and vector embeddings
- burst, duplicate and sequence group values

Derived statistics are invalidated; training state stays.

What does not change:

- **Undo history** keeps its old paths. An entry for the old path may no longer appear or be revertable after relinking.
- **Manual face rectangles** are kept but marked `relink_unverified`. Open the editor and save each rectangle against the new frame before it can export or suppress detections.
- **Immich** push and pending state stay as they were; no remote rating, album or UUID is relinked. Check the remote mapping yourself before syncing.
- **Scan-failure history, smart album filters and sequence group keys** are not rewritten.

## Explicit companions and refusals

List companions yourself; the tool cannot find RAW or XMP files that vanished from the old directory. Companion kinds:

| Kind | File |
|---|---|
| `sidecar_full` | `photo.ext.xmp` |
| `sidecar_basename` | `photo.xmp` |
| `sidecar_facet` | `photo.ext.facet.xmp` |
| `raw` | same-directory, same-stem RAW pair |

These rules check the declared relationship; they do not prove identity. An indexed RAW photo needs its own top-level entry so its annotations are kept. Existing companion files are hashed and left untouched. An empty companion list does not prove none existed.

Facet refuses:

- unlisted sidecars or RAW companions at the destination, including Facet fallback packets and case variants
- several RAW candidates or ambiguous XMP ownership, e.g. `IMG.CR2` + `IMG.CR2.jpg` + `IMG.CR2.xmp`, or `IMG.CR2` + `IMG.CR2.facet.jpg` + `IMG.CR2.facet.xmp`, and basename, case or Unicode collisions
- copies where the old original is still present
- missing or unreadable old parents
- destinations that already have photo or dependent rows
- repeated mappings, duplicate photo content or target inodes
- case-only or Unicode-only renames, symlinks, and extension or format changes
- a decoded target whose dimensions differ from the stored ones, when those are known

No similarity or filename search runs.

Limits per batch: 100 photos, 300 named files, 512 MiB per file, 2 GiB total, and 2 MiB for the JSON input or plan. Split the batch if you hit one. The database write is atomic, but other applications can still touch the files, which is why the job must run offline.

> **Warning:** A readable directory does not prove the storage is mounted. An unmounted volume can look like an empty folder. The plan reports `source_mount_status: not_verified`; confirm each source was really moved before you acknowledge identity. The command does not detect every offline-volume condition.

Plan files contain full private paths and user scope. `--plan-out` creates them exclusively with mode 0600 on POSIX.

| Option | Purpose |
|---|---|
| `--db` | Existing database |
| `--config` | Resolved configuration |
| `--user` | Required configured user in multi-user mode |
| `--mapping` | Explicit old/new JSON mappings; preview mode |
| `--plan-out` | Create a new private plan file; never overwrite |
| `--apply-plan` | Apply a previously reviewed plan |
| `--ack-plan` | Exact reviewed plan digest |
| `--acknowledge-unverified-identity` | Explicit assertion despite unknown original bytes |
