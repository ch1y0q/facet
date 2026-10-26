# Editor Interop Recipes

> 🌐 **English** · [Français](fr/INTEROP.md) · [Deutsch](de/INTEROP.md) · [Italiano](it/INTEROP.md) · [Español](es/INTEROP.md) · [Português](pt/INTEROP.md) · [简体中文](zh/INTEROP.md)

Practical, step-by-step recipes for round-tripping Facet's ratings, labels, and tags with the external editors and DAM tools people actually use. This page assumes you already know *that* Facet writes XMP — see [Commands — Preview & Export](COMMANDS.md#preview--export) for the full `--export-sidecars` / `--import-sidecars` flag reference and the field mapping (`xmp:Rating`, `xmp:Label`, `dc:subject`).

Manual locations and review decisions travel only when you explicitly export metadata in the viewer or run `--export-sidecars`. GPS uses standard `exif:GPSLatitude` / `exif:GPSLongitude`; only manually set locations are exported, so stale scanned GPS cannot replace file GPS. `--embed-originals` also writes EXIF GPS in supported originals. A corrected capture date is exported as `exif:DateTimeOriginal` (and, with `--embed-originals`, as EXIF `DateTimeOriginal` in supported originals); after **Use file date**, the next export removes it from the sidecar without touching a date another editor wrote there. Clearing a location exports an explicit clear; absent fields never clear a location on import.

The Facet namespace `https://github.com/ncoevoet/facet/ns/1.0/` defines `facet:ReviewDecision` (`kept`, `rejected`, `undecided`) and `facet:GPSState` (`set`, `cleared`), plus `facet:DateState` (`set`), which marks a sidecar capture date that Facet exported. Keep is independent of stars and favorites; rejection clears Keep, stars and favorite. `--import-sidecars` applies a present Facet decision when standard review fields agree or are absent. If standard rejection state disagrees, an external editor has changed the standard fields while preserving the private tag: the private decision is ignored and the standard fields use the existing newest-wins scan-time check. Decision-only imports remain explicit and do not use scan times. A decision exported alongside standard review fields uses the same newest-wins check, except for a photo with no review state yet (no stars, favorite, Keep or reject), so a rescanned library still restores its decisions while an older export cannot revert a decision made since. Manual GPS already in Facet is preserved unless you add `--overwrite-manual-gps`. Invalid or incomplete coordinates are ignored. Named-user imports/exports (`--user alice`) respect that user's visible folders and private decisions; GPS remains shared. With no user, the CLI operates on global state. ExifTool merges foreign metadata; without it, export leaves an existing editor sidecar intact and writes the fallback. Originals remain untouched unless you explicitly request embedding.

## The RAW sidecar naming gotcha

Facet exports `IMG_1234.CR2.xmp` beside `IMG_1234.CR2`, preserving darktable's full-filename convention. Lightroom Classic and Capture One generally use `IMG_1234.xmp` for proprietary RAW. Export filenames do not change with the import policy below. For JPEG/HEIC/TIFF/PNG/DNG, `--embed-originals` offers a separate in-file channel; GIF/WebP/BMP/AVIF and proprietary RAW still need a matching sidecar convention.

Choose discovery explicitly with `--import-sidecars --sidecar-naming full|basename|auto`:

- `full` (default): read `<image.ext>.xmp` or `<image.ext>.facet.xmp`, whichever has the newer filesystem modification time; the primary wins a tie.
- `basename`: read `<image>.xmp`, stripping only the final image extension. Full-name sidecars and their fallback are ignored.
- `auto`: accept either family when only one exists. If both full-name and basename sidecars exist, skip that photo and report ambiguity; modification times do not resolve this conflict. Select `full` or `basename` deliberately.

A basename shared by indexed photos or sibling image files, such as `same.CR3` and `same.jpg`, is refused under `basename` and `auto`, even if only one photo is in the selected folder/user scope. Use independent full-name sidecars for those files. Versions such as `same_v1.jpg` have a different basename. Naming mismatches, ambiguity and unreadable/invalid selected packets are reported; no other naming family is tried after a parse failure. The CLI summary counts ambiguity within skipped photos and naming mismatches within photos without a selected sidecar.

Double-extension derivatives such as `IMG.CR2.jpg` must not read `IMG.CR2.xmp` owned by `IMG.CR2`; the same protection covers another image’s `.facet.xmp` fallback. Naming notices in every policy show one example of each kind per import; summary counts still include every affected photo.

Import needs no ExifTool. Export merging, embedding and MWG face rectangles require ExifTool. Without it, an existing editor sidecar is left intact and the XML fallback writes `<image.ext>.facet.xmp` with no MWG rectangles. This fallback needs an intentional handoff to another editor; it is not a universally discovered filename. No files are renamed by these policies.

## Lightroom Classic

### Facet → Lightroom

1. `python facet.py --export-sidecars` (add a path to scope it, e.g. `--export-sidecars /photos/2026-wedding`). Add `--embed-originals` to also write directly into JPEG/HEIC/TIFF/PNG/DNG files.
2. In Lightroom Classic's Library module, select the photos (Ctrl/Cmd+A for all) and choose **Metadata → Read Metadata from File(s)**. Lightroom overwrites its catalog's rating, color label, and keywords from the sidecar (or the embedded metadata, for the formats above).

Facet's reject marker (`xmp:Rating = -1`) reads back as Lightroom's Reject flag. A Facet favorite writes `xmp:Label = Yellow`, which Lightroom shows as the **Yellow color label** — not the Pick flag. If your Lightroom workflow keys off Picks rather than color labels, add a color-label-to-pick step, or filter by the Yellow label instead.

A `python facet.py --export-manifest` feed (path, category, every score, tags, and the same rating columns as `--export-sidecars` — including per-user ratings via `--export-manifest --user alice` on a multi-user install) now exists for tools that want Facet's data without parsing XMP — see [Commands — Preview & Export](COMMANDS.md#preview--export). The Facet plug-in below consumes it.

**Manifest version 2.** The manifest now also carries `burst_group_id`, `sequence_kind`, `sequence_group_id`, `score_stars` and a top-level `pending_corrections` count (manual bracket/panorama corrections not yet applied by a detection run — re-run `--detect-panoramas`). The plug-in uses the per-photo fields for the burst pick/reject and star-fallback options below, and surfaces `pending_corrections` as a warning line in its Preview so you know a re-run of detection may still change which frames are leads. There is no backward-compatible read path: a plug-in built for version 2 refuses a version-1 manifest outright with a dialog telling you to re-export, and an older plug-in cannot read a version-2 manifest either. If you see that dialog, just re-run `--export-manifest`.

In the viewer, the gallery's **Export to editor** dialog offers the same manifest as a **Download Lightroom manifest** button, scoped to the same selection/filter set as the sidecar export next to it — see [Editor Export](VIEWER.md#editor-export). It writes the identical `facet_manifest.json` shape `--export-manifest` does, so the plug-in dialog above works the same way regardless of which side generated the file.

### The Facet plug-in (star ratings, pick flags, metadata fields and keywords)

`facet.lrplugin/` in the Facet repository is a Lightroom Classic plug-in that writes Facet's star rating and favorite/reject state **straight into the catalog**. It exists because two things above cannot be fixed from the XMP side: Lightroom never finds a Facet sidecar for a proprietary RAW file, and XMP has no channel at all for Lightroom's Pick flag. The plug-in reads a manifest file, so it never talks to the Facet server, needs no password, and works while Facet is not running — and because it matches photos by path rather than by sidecar, **a RAW-only library works exactly like a JPEG one**.

The plug-in registers two **Library → Plug-in Extras** menu items: **Facet: Apply ratings and flags...** (the manifest → catalog direction, documented in this section) and **Facet: Export Lightroom State to Facet...** (the reverse direction — see [Lightroom → Facet](#lightroom--facet) below).

**Install** (once):

1. Copy the `facet.lrplugin` folder to the machine running Lightroom. On macOS, zip it first — Finder treats a `.lrplugin` folder as a bundle.
2. In Lightroom Classic: **File → Plug-in Manager → Add**, select the `facet.lrplugin` folder, then **Done**.

**Use** (each time you want Facet's verdict in the catalog):

1. `python facet.py --export-manifest /photos/2026-wedding` (the path scopes the export; the file always lands as `facet_manifest.json` in the current directory). Copy it to the Lightroom machine if Facet runs elsewhere.
2. In the Library module, select the photos, then **Library → Plug-in Extras → Facet: Apply ratings and flags...**
3. Point the dialog at `facet_manifest.json`. The path is remembered for next time.
4. **If Facet scanned the photos from another machine, fill in the two path prefixes.** The manifest stores the paths of the machine that did the scanning (`/volume1/photos/...` on a NAS), and Lightroom holds the desktop's (`Z:\photos\...`). Enter the Lightroom prefix and the Facet prefix that mean the same folder; leave both empty when the two agree. Getting this wrong is the one first-run failure that matters — it simply matches nothing.
5. Choose the scope: the selected photos (default), or every photo of the current folder.
6. Press **Preview...**. **Nothing is written yet.** The plug-in reports how many photos it matched in the manifest, how many it did not, and how many ratings and flags it would set. If the matched count is 0, it shows a sample Lightroom path next to a sample manifest path so you can see what the prefixes must be.
7. Press **Apply**. Progress is shown and can be cancelled; a summary dialog reports what was set, skipped, and not found.

**What it writes** — nothing else, and never to your image files:

| Facet state | Lightroom field |
|---|---|
| `star_rating` 1-5 | star rating |
| favorite | Pick flag |
| rejected | Reject flag |

A Facet star rating of 0 means "no opinion" (see `xmp_export.score_to_rating`) and is never written.

**Overwrite semantics** — by default the plug-in never argues with you: it sets a star rating only when the photo is *unrated* in Lightroom, and a pick/reject flag only when the photo is *unflagged*. Anything you rated or flagged by hand is left alone and counted as "kept as they are" in the preview. Tick **Overwrite ratings and flags that are already set in Lightroom** to replace them instead. This mirrors `only_when_unrated` in `xmp_export.score_to_rating`, so the plug-in and the sidecar path treat your manual edits the same way.

**New dialog options** (all opt-in, each persisted for next time):

- **Fill in star ratings from Facet scores for photos you have not rated** — when a photo has no `star_rating` in the manifest (or it is 0) but Facet's `aggregate` score maps to a star count, that derived rating fills in the gap. Because it is a fallback for an *unrated* photo, not a real manifest rating, it **never overwrites an existing Lightroom rating — even with Overwrite ticked.** A real manifest `star_rating` still follows the normal overwrite rule above unchanged.
- **Pick the recommended frame of each burst** — for every burst group with at least 2 members in the manifest, every member the manifest marks `is_burst_lead` (a burst can keep more than one frame) is set to Picked. A lone frame that the manifest never grouped with siblings is never touched by this option, and a burst group with no `is_burst_lead` member anywhere in the manifest is skipped entirely (nothing to pick from). A manual Pick/Reject flag you already set — or a Facet favorite/reject in the manifest — always wins over this derived pick.
- **Reject the other frames** (nested under the pick option, enabled only alongside it) — sets every burst member that is *not* the lead to Rejected, with two exceptions: a member of a bracket, panorama, or HDR panorama is never rejected by this rule, no matter that its `burst_group_id` also groups it with siblings — those sets are kept whole; and a group with no lead anywhere in the manifest (see above) gets no rejects either.
- **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** — for every group with at least 2 matched photos in your current scope, creates or reuses a collection named `<yyyy-mm-dd HH:MM:SS> – <filename>` (the earliest member's capture time and filename; `~ (no date) – <filename>` when the earliest member has no capture time), nested under `Facet › Bursts`, `Facet › Brackets`, `Facet › Panoramas` or `Facet › HDR panoramas` as appropriate. A plain burst group whose members are *all* already part of one bracket/panorama/HDR-panorama set gets no separate Bursts collection, since it would just duplicate the one under Brackets/Panoramas/HDR panoramas. **Re-running only adds** photos to a collection it finds again — it never removes any, so a collection can go stale relative to a set that later gets re-grouped or re-detected (a photo dropped from a bracket on a later scan is not dropped from the collection). Collection names collide when two different groups' earliest members share the same capture time to the second and the same filename — two cameras that both happened to write `IMG_0001` at the same timestamp end up sharing one collection instead of getting one each. This is a known limitation, not a bug to report.
  - **Rebuild (clear and refill) Facet collections fully covered by this run** (nested under the option above) — instead of only adding, clears and refills a collection, but only when the collection AND its whole group are entirely inside the current scope; a collection that is only partly covered (some members outside the run's selection) or points at a smart/unresolved collection is left untouched and counted as skipped, and the summary reports how many were rebuilt, deleted, skipped and failed. It also reaches a Facet collection whose group DISSOLVED this run (no longer at least 2 in-scope members, so no plan entry at all) — that collection is emptied and deleted too, but only when every photo it currently holds was matched by this run; one holding any photo outside this run is left untouched. Rebuild is only ever offered — and only ever runs — while **Create Facet collections for bursts, brackets, panoramas and HDR panoramas** is on; unticking that option turns Rebuild off too. The dissolved-collection sweep only ever touches a collection whose name matches the shape Facet itself generates (an ISO date-time, or the undated `~ (no date)`, followed by ` – <filename>`), so a collection you named yourself under a Facet set is never emptied or deleted. When the sweep has anything to delete, the Preview adds a `Facet collections to delete: N` line, and the sweep runs even when it is the only pending change, rather than being reported as nothing to change.
- **Write Facet scores/category/set-kind as Lightroom plug-in metadata fields** — writes the aggregate score (e.g. `8.4`), a whole-point band (`0`-`10`), the category and the set kind into Facet's own plug-in metadata fields, visible in the Metadata panel and usable in the Library Filter/smart collections as text (`sdktext:`) criteria — for example, a smart collection matching the band field as "any of 8, 9, 10". A field that no longer applies to a photo (for example, it left a bracket, so the set kind is gone) is cleared rather than left stale — otherwise a smart collection or Library Filter criterion built on that field keeps matching a photo that no longer qualifies. Adobe's SDK only admits a plug-in's own fields into the search vocabulary as text or enum, never as a numeric range, so there is still no "aggregate > 8" smart collection; band is the closest text-only substitute. Two further bookkeeping properties (the rating/pick value this run derived) are written alongside but kept out of the Library Filter and smart-collection criteria — see the reverse-export note under [Lightroom → Facet](#lightroom--facet). **UNVERIFIED against a live catalog:** whether a titleless metadata field is actually invisible in the Metadata panel and Library Filter is not confirmed against the Lightroom SDK docs alone, so the two bookkeeping properties are marked `searchable = false, browsable = false` as the safer, confirmed fallback rather than relying on an unconfirmed title-omission behaviour — they may still be visible in some Lightroom Classic versions.
- **Create "Facet" keywords from Facet tags (never included on export)** — creates a `Facet` root keyword with one child per Facet tag your photos carry (AI tags and your [manual tags](#manual-tags-and-xmp-keywords) alike), and sets each photo's `Facet ›` child keywords to exactly match its manifest tags (adds and removes as tags change between runs, so removing a manual tag in Facet removes its child keyword at the next Apply). Every keyword this option creates or touches has `Include on Export` turned off, so Facet's auto-tags never leak into a JPEG/TIFF export or a client gallery. Your own keywords outside the `Facet` root are read (to detect a pre-existing top-level `Facet` keyword, which is adopted as the root) but are never added, removed or written by this option; any child keyword you put under that adopted `Facet` root yourself is treated as stale and removed.

**Why collections, not stacks.** Lightroom's SDK has no call to create or manage a Stack — `stackInFolder`/`stackPositionInFolder` are read-only on `LrPhoto`. A collection is the closest writable substitute, and `canReturnPrior` means re-running the plug-in resolves the same collection rather than duplicating it. If you want an actual Lightroom stack, select a collection's photos and use **Photo → Stacking → Group into Stack** (Ctrl/Cmd+G) yourself — the plug-in cannot do this step for you.

**Limitations**, honestly:

- **Pick flags are catalog-only.** That is Lightroom's design, not the plug-in's: Lightroom never writes the pick flag to XMP, so it reaches no other application and is lost if you rebuild the catalog from the files. Star ratings do survive, via **Metadata → Save Metadata to File(s)**.
- **The metadata-field smart-collection route is still text-only.** Adobe's SDK admits a plug-in's own fields into the search vocabulary only as text or enum (`sdktext:`); the numeric operators (`>`, `<`, `in range`) belong to Lightroom's built-in criteria alone. The band field above is the closest text-only substitute for "aggregate > 8"; routing the raw score through the **star rating** (the fill-in option above) remains the only channel Lightroom itself filters and sorts numerically.
- **Undo** works one batch at a time: the plug-in writes in chunks of 200 photos, so Ctrl/Cmd+Z reverts 200 photos per press.
- Tick **Write facet-apply.log next to the manifest** before a run if you need to see, line by line, which paths matched and what was written.

### Lightroom → Facet

**Ratings, picks and rejects — Lightroom wins (via the plug-in).** **Library → Plug-in Extras → Facet: Export Lightroom State to Facet...** opens a save panel (no default file name or location) to write a Lightroom state file (one record per photo: `path`, and `rating`/`pick` only when they still need to travel — see below). Feed it back with `python facet.py --import-lightroom facet_lightroom_state.json` (add `--user alice` on a multi-user install; required there) or, in the viewer, the gallery's **Export to editor** dialog's **Import Lightroom state…** button, which posts the file's contents straight to the server. Lightroom's value wins unconditionally for every key present in a record — CLI and viewer share one `processing/lightroom_sync.py` importer, reporting `matched`/`unmatched`/`changed` counts:

| Lightroom state | Facet result |
|---|---|
| Pick flag = Picked (`pick = 1`) | favorite = on, rejected = off |
| Pick flag = Rejected (`pick = -1`) | favorite = off, rejected = on |
| Pick flag = none (`pick = 0`) | favorite = off, rejected = off |
| star rating (`rating`, 0-5) | `star_rating` (`0` clears it) |

A record that omits `rating` or `pick` entirely leaves Facet's corresponding value untouched — the export only includes a key when Lightroom's current value differs from what the Apply direction itself last derived for that photo (two hidden, non-searchable plug-in properties record that baseline), so re-exporting an untouched photo writes an empty record and changes nothing. Because Lightroom wins unconditionally, exporting also clears a Facet rating/favorite/reject on any exported photo the Apply direction never touched — an unrated, unflagged photo in Lightroom (`pick = 0`, no `rating`) overwrites an existing Facet star rating or favorite/reject with "none". A successful import that changes anything also rebuilds the rating-derived training pairs and nudges the same idle-triggered auto-retrain every other rating write does. Virtual copies are deduped to their master by path before export, preferring the master when both exist for the same file.

**Ratings, labels and keywords via XMP.** Separately, and still one-way in this direction:

1. In Lightroom, select the photos and choose **Metadata → Save Metadata to File(s)** (Ctrl/Cmd+S). This flushes the catalog's rating/label/keywords into the XMP sidecar (RAW) or embeds them in the file itself (DNG/JPEG/PSD/TIFF).
2. `python facet.py --import-sidecars /path --sidecar-naming basename` reads saved RAW sidecars into Facet; shared RAW/JPEG basenames are refused. This command does not extract embedded metadata. Imported foreign keywords become manual tags.

### Conflict rules

- **Tags and keywords merge by default.** Exports add Facet keywords; `--reconcile-keywords` also removes only stale Facet-owned names. Imports add manual tags and never replace AI tags. [Manual tags and XMP keywords](#manual-tags-and-xmp-keywords).
- **Multi-user** (`--export-sidecars --user alice` / `--import-sidecars --user alice`): ratings route to Alice's `user_preferences` row instead of the global columns. Keywords stay global regardless of `--user` — manual tags are shared across users.
- Imported keywords go to the `photo_manual_tags` table, which the tag filters read directly, so no `python database.py --migrate-tags` is needed after `--import-sidecars`.

## Capture One

Capture One never writes into the original file or into a continuously-synced XMP sidecar the way Lightroom's autosave does — it keeps its own adjustments in `.cos` settings (Sessions) or its catalog database, and its **Sync Metadata** preference has a bidirectional "Full Sync" mode that can silently overwrite whichever side wrote last. Running a two-way loop through that setting risks losing either Facet's or Capture One's edits. The safe pattern is **one-way, Facet → Capture One**:

1. `python facet.py --export-sidecars /path/to/shoot --embed-originals`.
2. In Capture One, leave **Preferences → General → Sync Metadata** at its default (not "Full Sync").
3. Select the imported images, right-click, and choose **Load Metadata** to pull the rating/label/keywords from the sidecar (or embedded metadata) into Capture One's catalog fields once.

Treat Facet as the source of AI-derived ratings and tags for that shoot: perform the one-time `Load Metadata` pull, then continue in Capture One without automatic bidirectional synchronization. To import saved XMP deliberately, run `--import-sidecars /path/to/shoot --sidecar-naming basename` for stripped-extension RAW sidecars, or `full` for full filenames. Shared RAW/JPEG basenames are refused. This command reads sidecars, not embedded metadata.

## digiKam

digiKam's [sidecar settings](https://docs.digikam.org/en/setup_application/metadata_settings.html#sidecars-settings) select a naming convention: normally `filename.ext.xmp`, or `filename.xmp` with **Sidecar file names are compatible with commercial programs** enabled. Do not assume it tries both. For Facet's exports, use the full-name setting and enable **Read from sidecar files**; explicitly reread file metadata into the digiKam database and verify the selected fields. For digiKam → Facet, select `--sidecar-naming full` or `basename` to match the saved setting. Stars, color labels and pick flags have different semantics; filename agreement alone is not a verified application round trip.

### Batch Queue Manager hook

You can run a Facet import from digiKam's Batch Queue Manager (BQM) **Custom Script** tool. Enable sidecar writing, save the naming setting, and apply pending metadata changes before importing (lazy synchronization may defer writes). The example below assumes full-name sidecars; replace `full` with `basename` only for an unambiguous commercial-naming collection:

```bash
#!/bin/bash
python /path/to/facet.py --import-sidecars --sidecar-naming full "$(dirname "$INPUT")"
cp "$INPUT" "$OUTPUT"
```

`$INPUT` / `$OUTPUT` are digiKam's per-file placeholders (BQM runs the script through `/bin/bash` on Linux/macOS and expects an output file, hence the `cp` passthrough). Because `--import-sidecars` scans the whole folder, running it once per photo in a large batch is redundant, if harmless (it's idempotent — unchanged photos are skipped). For big batches, skip the BQM hook and just run `python facet.py --import-sidecars /path/to/folder` once by hand after the queue finishes.

## darktable

darktable already has first-class treatment in [Configuration — Viewer](CONFIGURATION.md#viewer) (`viewer.raw_processor.darktable` export profiles/styles) and [Viewer — Download](VIEWER.md#api-endpoints) (`type=darktable` conversions). On the XMP side: darktable authors its own `<image><ext>.xmp` to store its edit history, and Facet's exiftool-backed sidecar writer merges into that same file in place — the `darktable:history`/mask nodes are preserved, never overwritten. No separate recipe is needed here; the two-way sidecar behavior described above for Lightroom (export/import, newest-wins, tag union) applies the same way, without the RAW naming mismatch since darktable and Facet agree on `<image><ext>.xmp`.

**exiftool version.** ExifTool **13.28 or newer** is recommended. Face updates require **12.65 or newer**; older or unknown versions skip face changes with a warning while exporting other metadata. Versions 13.23 through 13.27 corrupt XMP sidecars that carry darktable edit history (an attribute value ending in `=` followed by another attribute is mis-parsed, and exiftool still exits 0), so Facet refuses to write with them and reports an error telling you to upgrade. The Docker image ships a pinned exiftool, so it is unaffected; a distribution package may not be (Debian trixie's `libimage-exiftool-perl` is 13.25).

**Caveat: darktable's own XMP reload is unreliable.** Independent of Facet's write path, re-importing an image that darktable has already edited can make darktable overwrite the sidecar's edit history with a blank one instead of loading it back — an open upstream bug ([darktable#20537](https://github.com/darktable-org/darktable/issues/20537), reported 2026-03-15) that the "check for new/updated xmp files on start" preference does not protect against. Facet is not the cause (the exiftool merge above already preserves `darktable:history`), but the risk sits in the read-back step this page's round trip depends on. Practical workaround, following the same one-shot discipline as the Capture One recipe above: after `--export-sidecars`, don't bulk re-import an already-edited folder — reload sidecars for just the images Facet touched and confirm the edit history is still there before trusting the rest of the batch.

## Manual tags and XMP keywords

Facet keeps the tags you type yourself (see [Viewer — Manual Tags](VIEWER.md#manual-tags)) in a side table, `photo_manual_tags`, apart from the AI tags in `photos.tags`. That split is what lets a rescan or a retag leave them alone, and it fixes how keywords travel through XMP:

- **Export.** Every keyword writer emits the AI tags, then the manual tags, then person names, deduped case-insensitively: `--export-sidecars`, the gallery's XMP export and "Write metadata to file" actions, and the Lightroom manifest (`--export-manifest`, `/api/lightroom/manifest`).
- **Import.** `--import-sidecars` reads `dc:subject` only. Each keyword is normalised like a typed tag (trimmed, lowercased, at most 64 characters, 50 manual tags per photo). It is stored as a manual tag with source `xmp`, unless it is already one of the photo's current AI tags, equals one of its person names, is a hierarchical `a|b` path, contains a comma or a control character, or would exceed the cap. Imported keywords never write to `photos.tags` again, so a retag no longer overwrites them.
- **Keyword removal is explicit.** Exports remain additive by default. Use `--export-sidecars /path --reconcile-keywords` with ExifTool to remove names previously claimed by Facet and now absent from the exported keywords. Pre-existing foreign names, including same-name collisions, remain untouched; old unmarked packets grant no ownership. `facet:KeywordState` records owned names and deletion markers. A marker expires when its name reappears in the file or Facet writes it again; an externally re-added manual keyword can be imported again and is treated as foreign on later exports. Keywords are shared library values even with `--user`.
- **Exports use Facet's current keywords as authority.** In both modes, a keyword still in Facet is written back if another editor removed it from the file. To adopt that removal, remove the tag in Facet too. Reconciliation does not delete database tags or implement bidirectional synchronization. Names such as `2024`, `1.50`, `1e3`, `true`, `false` and `null` retain their spelling even when ExifTool reports numeric or boolean JSON tokens. A failed or malformed read of an existing file refuses export before writing, in additive mode as well as reconciliation.
- **The Lightroom manifest does propagate removals.** The plug-in's keyword option rewrites each photo's `Facet ›` children to match the manifest at Apply time, so a tag removed in Facet disappears from Lightroom at the next Apply.
- **AI provenance survives retagging.** New packets identify exported AI and manual tags separately. An old AI keyword does not become a manual tag merely because a retag changed it; a keyword explicitly stored as manual can still be restored. Older unmarked packets keep the legacy additive behavior. Reconciliation requires ExifTool; without it the operation refuses before writing. Hierarchical keywords remain additive. Ownership lists are bounded to 10,000 names each and 1,024 characters per name; an export that would exceed these limits refuses before writing, preserving all deletion markers. Archive and manually reconcile a full packet before establishing fresh ownership; markers are never silently evicted.
- **Keywords imported by an older Facet stay where they are.** Before manual tags existed, imports merged keywords straight into `photos.tags`, where they are indistinguishable from AI tags, and no migration moves them. Such a keyword keeps showing as an AI tag until `photos.tags` is cleared or the photo is retagged, and because the import skips a keyword already in `photos.tags` it will not reappear as a manual tag either. To convert one, clear or retag `photos.tags` first, then run `--import-sidecars` again; or just add the tag by hand.
- **A moved or renamed file loses its manual tags.** They are keyed on the photo's path, which is a different photo after a move or rename.
- **`--export-csv` and `--export-json` stay AI-only.** Their `tags` value is the raw AI column, without manual tags.

## How Facet merges

| Field | Facet writes | Facet reads back | Conflict rule |
|---|---|---|---|
| Star rating / reject | `xmp:Rating` (`-1` = rejected) | `xmp:Rating` | Tracked review clocks; legacy scan fallback |
| Color label | `xmp:Label` (`Red` = rejected, `Yellow` = favorite) | `xmp:Label` | Tracked review clocks; legacy scan fallback |
| Tags / keywords | `dc:subject` (flat, AI tags + manual tags, includes named-face person names) | `dc:subject` (stored as manual tags) | Additive by default; `--reconcile-keywords` removes only stale Facet-owned names; imports stay additive ([Manual tags and XMP keywords](#manual-tags-and-xmp-keywords)) |
| Hierarchical tags | `lr:hierarchicalSubject` (`Category\|<cat>`, `People\|<name>`) | Not re-imported | Export-only |
| Caption | `dc:description` default language (+ `IPTC:Caption-Abstract` via exiftool) | Not re-imported | Export-only |
| Named face regions | MWG `mwg-rs:RegionList` + `facet:RegionOwner=Facet` (center-normalized, `Type=Face`) | Not re-imported | Export-only; read natively by digiKam, **not** read by Lightroom (a known Adobe limitation — Lightroom only consumes MWG regions it wrote itself) |

See [Commands — Preview & Export](COMMANDS.md#preview--export) for the full CLI reference (`--export-sidecars`, `--import-sidecars`, `--embed-originals`, `--score-to-stars`, `--user`).

When a stale `facet:GPSState=cleared` accompanies standard GPS fields, a complete valid latitude/longitude pair wins. A partial or invalid nonblank pair is ambiguous and ignored; it never clears a location. Only an absent or blank pair with the explicit clear marker clears GPS. Existing manual GPS remains protected unless overwrite is explicitly requested.

Caption export with ExifTool updates only `dc:description`’s `x-default` language and preserves other language alternatives in each existing sidecar or embedded image. An empty Facet caption leaves existing captions unchanged; it does not request deletion. Without ExifTool, the XML writer creates a default-language caption in its output packet and, by default, diverts to `<image>.facet.xmp` when an editor sidecar exists. Explicit fallback `overwrite=True` still replaces the target packet.

Face export with ExifTool replaces only MWG rectangles explicitly marked `facet:RegionOwner=Facet` in each region’s Extensions. Unmarked regions, including older Facet exports, are preserved because names and coordinates do not prove ownership: after upgrading, an old unmarked face and its new marked copy can appear together, and clearing faces leaves the old copy. Repeated exports replace the marked copies without accumulating more. Foreign regions and unknown extensions remain untouched. Different current face dimensions, or different/unknown foreign applied image dimensions, skip all face changes with a warning while rating, label, keywords and GPS still export. Unreadable or invalid existing face metadata refuses single-photo export/embed with HTTP 412 before writing. The XML fallback does not export face rectangles. External edits to a marked region remain Facet-owned; remove its ownership marker before treating it as an independent annotation. Known original/companion preconditions are checked before embedding. Separate file writes are not atomic: later external changes or I/O failures can still leave partial results.

## Sidecar import preview and review conflicts

Use `--import-sidecars /path --dry-run` to inspect JSON before writing. It reports the chosen packet, intended before/after fields, keyword additions, source time and skip/conflict reasons. Preview opens the existing database read-only, performs no migration and never commits. Apply reads the current packets and database again under its write transaction; the preview JSON is not an apply token.

`--sidecar-fields review,gps,keywords` selects field groups; omit groups to leave them alone. Review groups stars, favorite, rejection and Keep together so a conflict cannot apply half a decision. GPS keeps the existing manual-location protection unless `--overwrite-manual-gps` is given. Keywords remain additive and shared even with `--user`.

After this version initializes the database, SQLite triggers keep one edit receipt per photo/account/review field, including resets and preference-row deletion. A packet older than a changed field is a `newer_local_edit` conflict and that review group stays unchanged. `--overwrite-sidecar-review` explicitly overrides both edit clocks and the legacy scan gate. A source receipt identifies the XMP packet/time; `local` means an unknown SQL writer, not a verified human author. No caption, face, hierarchy or unmarked external GPS import is added.

Rows without receipts have unknown edit time, rather than an obsolete schema alias. The explicit data-state rule reports `untracked_legacy_edit` and uses scan time; no human edit time is guessed. Preview opens released schemas without migration, treating an absent Keep field as undecided. The source clock is `xmp:MetadataDate`, or file mtime when absent/invalid. Details include the first 1,000 scoped photos and 100 diagnostics per photo, with omitted counts; scope and named-user visibility apply before planning.

Edit receipts are private to their database. Fresh viewer exports contain no scanner receipts or sidecar paths; incremental exports preserve only receipts already held by the viewer and never copy scanner receipt authority. Explicit viewer resets, including deleted per-user preferences, survive later exports. Scanner values without viewer edits continue to update normally. Existing preview-build databases may already contain copied receipts whose origin cannot be inferred: these are conservatively preserved, without inventing timestamps or silently discarding actual viewer edits. Back up and review that database before explicitly rebuilding it. A fresh/full rebuild does not preserve viewer-local changes.
