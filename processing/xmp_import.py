"""Import external XMP sidecar metadata back into Facet's database.

The reverse of :mod:`processing.xmp_export`: read ``<image>.xmp`` written by
darktable / Lightroom / etc. and fold ratings, picks and keywords back into the
``photos`` table. Pure stdlib XML — no exiftool needed (sidecars are plain XMP).

Facet decisions apply on explicit import when standard review fields agree or
are absent. A mismatch indicates an external editor changed standard fields
while preserving Facet's private tag; those standard fields then follow the
legacy timestamp gate and the stale private decision is ignored. A decision
that rides with standard fields follows the same timestamp gate, unless the
photo has no review state yet (no stars, favourite, Keep or reject), so a
stale export cannot revert a decision made in Facet after a later scan.
Manual GPS overrides (including clears) import only where no manual override
exists, unless the caller requests ``overwrite_manual_gps=True``; they never use
scanned_at as a proxy for the time of a manual edit. Missing/invalid new fields
preserve state. If both primary and fallback sidecars exist, read the most
recently modified file.

Conflict policy for legacy fields: ratings / labels apply **newest-wins** by
``xmp:MetadataDate`` (falling back to the sidecar file mtime) versus the photo's
``scanned_at``; when the photo has no ``scanned_at``, the sidecar wins. Keywords
never touch ``photos.tags`` (the tagger owns that column and rewrites it on every
retag): the foreign ones are stored in ``photo_manual_tags`` with
``source='xmp'`` and are never lost to a retag. A keyword is foreign unless it
already is one of the photo's AI tags, a person name of the photo, or a
hierarchical ``a|b`` path.

Caveat: the photo-side timestamp is ``scanned_at`` (when Facet last scored the
photo), not a rating-edit time — Facet has no per-rating ``updated_at`` column. A
rating changed inside Facet *after* the last scan therefore carries no newer
timestamp, so an external sidecar that is newer than the scan (but older than the
in-app edit) will still win and overwrite it. Run an import before re-rating in
Facet if the external editor is the source of truth. By default imports write
the global ``photos.*`` rating columns; pass ``user_id`` (CLI ``--user``) in
multi-user mode to read and write that user's ``user_preferences`` ratings
instead. Keywords always go to the global ``photo_manual_tags`` (tags are not
per-user); ``user_id`` is recorded as ``created_by``.
"""

from __future__ import annotations

import logging
import math
import os
import unicodedata
import re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from db.manual_tags import (
    MAX_TAGS_PER_PHOTO,
    SOURCE_XMP,
    ManualTagError,
    insert_manual_tag,
    is_ai_tag,
    load_manual_tags,
    normalize_manual_tag,
)
from processing.rating_writer import upsert_rating_state
from utils.image_loading import WATCHABLE_IMAGE_EXTENSIONS
from processing.xmp_export import (
    LABEL_FAVORITE,
    LABEL_REJECTED,
    NS_DC,
    NS_EXIF,
    NS_FACET,
    NS_RDF,
    NS_XMP,
    sidecar_scope,
)

logger = logging.getLogger(__name__)


def _find_scalar(root, qname: str):
    """Return a scalar XMP value written either as an attribute (darktable) or
    as a child element (exiftool), or ``None``."""
    for el in root.iter():
        if qname in el.attrib:
            return el.attrib[qname]
    for el in root.iter(qname):
        if el.text and el.text.strip():
            return el.text.strip()
    return None


def _find_subjects(root) -> list[str]:
    """Collect ``dc:subject`` keywords from every ``rdf:Bag`` in the packet."""
    subjects: list[str] = []
    for subject in root.iter(f"{{{NS_DC}}}subject"):
        for li in subject.iter(f"{{{NS_RDF}}}li"):
            if li.text and li.text.strip():
                subjects.append(li.text.strip())
    return subjects


def _parse_date(value):
    """Parse an XMP / SQL timestamp into a datetime, or ``None``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_epoch(dt) -> float | None:
    """Epoch seconds for a datetime (naive values are assumed UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_xmp(path: str):
    """Parse an XMP file, rejecting any ``DOCTYPE`` declaration.

    A standard XMP packet never declares a DTD, so refusing one closes the
    entity-expansion ("billion laughs") DoS class without adding a third-party
    parser. Returns the root element.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if b"<!DOCTYPE" in data.upper():
        raise ET.ParseError("DOCTYPE declarations are not allowed in XMP sidecars")
    return ET.fromstring(data)


def _coordinate(raw: str | None, limit: int) -> float | None:
    """Parse standard XMP degrees/minutes[/seconds] plus hemisphere."""
    if not raw:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?(?:,(\d+(?:\.\d+)?))?([NSEW])\s*", raw)
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    d, m, sec = float(degrees), float(minutes or 0), float(seconds or 0)
    value = d + m / 60 + sec / 3600
    if (not math.isfinite(value) or m >= 60 or sec >= 60 or value > limit
            or direction not in ("NS" if limit == 90 else "EW")):
        return None
    return -value if direction in "SW" else value


def _gps_override(root):
    state = _find_scalar(root, f"{{{NS_FACET}}}GPSState")
    if state not in {"set", "cleared"}:
        return None
    latitude = _find_scalar(root, f"{{{NS_EXIF}}}GPSLatitude")
    longitude = _find_scalar(root, f"{{{NS_EXIF}}}GPSLongitude")
    # Editors may retain the private clear marker when adding standard GPS.
    # Only an absent/blank pair is an unambiguous clear; partial/invalid
    # coordinates must never delete the destination location.
    if state == "cleared" and not (latitude or "").strip() and not (longitude or "").strip():
        return (None, None)
    lat = _coordinate(latitude, 90)
    lon = _coordinate(longitude, 180)
    return (lat, lon) if lat is not None and lon is not None else None


def parse_sidecar(path: str):
    """Parse an XMP sidecar into a dict of Facet fields, or ``None`` on error.

    Maps ``xmp:Rating`` (−1 → rejected, 0-5 → stars), ``xmp:Label`` (Red →
    rejected, Yellow → favorite), ``dc:subject`` → tags, and ``xmp:MetadataDate``.
    """
    try:
        root = _parse_xmp(path)
    except (ET.ParseError, OSError):
        return None

    rating_raw = _find_scalar(root, f"{{{NS_XMP}}}Rating")
    label = _find_scalar(root, f"{{{NS_XMP}}}Label")
    metadata_date = _find_scalar(root, f"{{{NS_XMP}}}MetadataDate")

    star_rating = 0
    is_rejected = False
    is_favorite = False
    if rating_raw is not None:
        try:
            value = int(float(rating_raw))
        except ValueError:
            value = 0
        if value < 0:
            is_rejected = True
        else:
            star_rating = max(0, min(5, value))
    if label == LABEL_REJECTED:
        is_rejected = True
    elif label == LABEL_FAVORITE:
        is_favorite = True

    decision = _find_scalar(root, f"{{{NS_FACET}}}ReviewDecision")
    if decision not in {"kept", "rejected", "undecided"}:
        decision = None
    return {
        "review_decision": decision,
        "gps": _gps_override(root),
        "star_rating": star_rating,
        "is_favorite": is_favorite,
        "is_rejected": is_rejected,
        "tags": _find_subjects(root),
        "metadata_date": _parse_date(metadata_date),
        "has_rating": rating_raw is not None or label is not None,
    }


def _person_names(conn, path: str) -> set[str]:
    """Normalized names of the persons recognised in one photo."""
    names: set[str] = set()
    for (name,) in conn.execute(
        "SELECT pe.name FROM faces f JOIN persons pe ON f.person_id = pe.id "
        "WHERE f.photo_path = ? AND pe.name IS NOT NULL",
        (path,),
    ):
        try:
            names.add(normalize_manual_tag(name))
        except ManualTagError:
            continue
    return names


def _foreign_keywords(conn, path: str, ai_tags, keywords: list[str]) -> list[str]:
    """Normalized, de-duplicated keywords that are neither AI tags, person names
    nor hierarchical paths. Unstorable keywords are dropped with a warning."""
    people: set[str] | None = None
    foreign: list[str] = []
    for keyword in keywords:
        if "|" in keyword:
            continue
        try:
            tag = normalize_manual_tag(keyword)
        except ManualTagError as ex:
            logger.warning("Ignoring XMP keyword %r on %s: %s", keyword, path, ex)
            continue
        if is_ai_tag(ai_tags, tag) or tag in foreign:
            continue
        if people is None:
            people = _person_names(conn, path)
        if tag not in people:
            foreign.append(tag)
    return foreign


def _image_key(path: str) -> str:
    """Treat case and Unicode normalization variants as one packet filename."""
    return unicodedata.normalize("NFC", os.path.normcase(os.path.abspath(path)).casefold())


def _sidecar_stems(path: str) -> tuple[str, str, str]:
    """Names before .xmp for this image's basename, full and fallback packets.

    IMG.CR2.xmp belongs to IMG.CR2 by full name, so IMG.CR2.jpg must not also
    claim it by basename. The same collision can involve .facet.xmp fallbacks.
    """
    return _image_key(os.path.splitext(path)[0]), _image_key(path), _image_key(path + ".facet")


def _shared_indexed_stems(conn) -> set[str]:
    """Find packet names claimed by multiple photos, including outside scope."""
    first: dict[str, str] = {}
    shared: set[str] = set()
    for (path,) in conn.execute("SELECT path FROM photos"):
        # Keep logical photo owners distinct even when their packet keys alias.
        normalized = os.path.normcase(os.path.abspath(path))
        for stem in _sidecar_stems(path):
            if stem in first and first[stem] != normalized:
                shared.add(stem)
            first[stem] = normalized
    return shared


def _directory_image_claims(directory: str) -> dict[str, set[str]]:
    """Index all sibling image packet names; decoding availability is irrelevant."""
    images: dict[str, set[str]] = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            if (os.path.splitext(entry.name)[1].lower() in WATCHABLE_IMAGE_EXTENSIONS
                    and entry.is_file()):
                normalized = os.path.normcase(os.path.abspath(entry.path))
                for stem in _sidecar_stems(entry.path):
                    images.setdefault(stem, set()).add(normalized)
    return images


def _warn_full_naming_once(reported: set[str], image_path: str, basename: str,
                           selected: str | None) -> None:
    if "full_naming" in reported:
        return
    reported.add("full_naming")
    logger.warning("Full-name sidecar policy for %s: selected %s; ignoring basename packet %s. "
                   "Check --sidecar-naming and image ownership before changing policy; "
                   "shared or other-image packets are refused. Further naming notices are suppressed for this run.",
                   image_path, selected or "no full-name sidecar", basename)


def _warn_discovery_once(reported, kind, message, *args):
    if kind not in reported:
        reported.add(kind)
        logger.warning(message + '; further notices of this kind are suppressed for this run', *args)


def _discover_sidecar(image_path: str, naming: str, shared_stems: set[str],
                      directory_images: dict[str, dict[str, set[str]]],
                      reported: set[str]) -> tuple[str | None, str | None]:
    """Choose a naming family before parsing; never use mtime across families.

    Return ``(path, None)`` or ``(None, reason)``. Basename discovery refuses any
    packet also claimed by another indexed or on-disk image, by basename, full
    name or fallback. Directory scans and full-policy notices are cached only
    for this import; inspection failures propagate for the caller to report.
    """
    full = [image_path + suffix for suffix in (".xmp", ".facet.xmp")]
    full = [path for path in full if os.path.exists(path)]
    basename = os.path.splitext(image_path)[0] + ".xmp"
    has_basename = basename != image_path + ".xmp" and os.path.exists(basename)
    if full and has_basename and naming == "auto":
        _warn_discovery_once(reported, 'ambiguous_families',
                             "Skipping %s: ambiguous sidecar naming (%s and %s); "
                             "select --sidecar-naming full or basename", image_path, full, basename)
        return None, "ambiguous"
    if naming != "basename" and full:
        # Preserve the existing primary/fallback rule; list order breaks ties.
        selected = max(full, key=os.path.getmtime)
        if has_basename:
            _warn_full_naming_once(reported, image_path, basename, selected)
        return selected, None
    if naming != "full" and has_basename:
        stem = _sidecar_stems(image_path)[0]
        directory = os.path.dirname(os.path.abspath(image_path))
        shared = stem in shared_stems
        if not shared:
            if directory not in directory_images:
                directory_images[directory] = _directory_image_claims(directory)
            siblings = directory_images[directory].get(stem, set())
            for sibling in siblings - {os.path.normcase(os.path.abspath(image_path))}:
                # APFS may return this image's own entry in a different Unicode
                # spelling. Only that same canonical full name AND inode is self;
                # another image name (even a hard link) still owns its packets.
                if _image_key(sibling) == _image_key(image_path):
                    try:
                        if os.path.samefile(sibling, image_path):
                            continue
                    except FileNotFoundError:
                        pass
                shared = True
                break
        if shared:
            if "shared_basename" not in reported:
                reported.add("shared_basename")
                logger.warning("Skipping %s: shared basename or another image's full-name/fallback "
                               "sidecar makes %s ambiguous; use per-image full-name sidecars. "
                               "Further shared-packet notices are suppressed for this run.", image_path, basename)
            return None, "ambiguous"
        if full:
            _warn_discovery_once(reported, 'basename_selected',
                                 "Sidecar naming basename for %s: selecting %s; ignoring %s", image_path, basename, full)
        return basename, None
    if full or has_basename:
        if naming == "full":
            _warn_full_naming_once(reported, image_path, basename, None)
        else:
            _warn_discovery_once(reported, 'missing_basename',
                                 "No basename sidecar for %s; found %s; use --sidecar-naming full to read it",
                                 image_path, full)
        return None, "naming_mismatch"
    return None, "missing"


def import_sidecars(conn, root: str | None = None, *, user_id: str | None = None,
                    overwrite_manual_gps: bool = False, sidecar_naming: str = "full") -> dict:
    """Import ``<image>.xmp`` sidecars into the ``photos`` table.

    ``root`` limits the import to photos whose path is, or is under, that path.
    By default ratings are written to the global ``photos`` columns. When
    ``user_id`` is given and multi-user mode is enabled, ratings are read from and
    written to that user's ``user_preferences`` row instead. Foreign keywords are
    written to the global ``photo_manual_tags`` (``source='xmp'``), never to
    ``photos.tags``. Returns counts: ``updated`` / ``unchanged`` / ``missing`` (no
    sidecar) / ``skipped`` (unparseable, unreadable or ambiguous) / ``tags_added``.
    ``ambiguous`` is a subset of skipped; ``naming_mismatch`` is a subset of missing.
    ``sidecar_naming`` selects ``full`` (default: newest of ``<image>.xmp`` and
    ``<image>.facet.xmp``), ``basename`` (strip image extension), or ``auto``
    (accept one family only). Basename packets also claimed by another image's
    basename, full name or fallback are refused even when only one photo is in
    scope. No sidecars are rewritten.
    """
    if sidecar_naming not in {"full", "basename", "auto"}:
        raise ValueError("sidecar_naming must be full, basename or auto")
    from api.config import is_multi_user_enabled
    per_user = bool(user_id and is_multi_user_enabled())

    where, params = sidecar_scope(root, user_id)

    if per_user:
        rows = conn.execute(
            f"SELECT photos.path AS path, photos.tags AS tags, photos.scanned_at AS scanned_at, "
            f"COALESCE(up.star_rating, 0) AS star_rating, "
            f"COALESCE(up.is_favorite, 0) AS is_favorite, "
            f"COALESCE(up.is_rejected, 0) AS is_rejected, COALESCE(up.is_kept, 0) AS is_kept, "
            f"photos.gps_latitude, photos.gps_longitude, photos.gps_manually_set "
            f"FROM photos LEFT JOIN user_preferences up "
            f"ON up.photo_path = photos.path AND up.user_id = ? {where}",
            [user_id] + params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT path, tags, star_rating, is_favorite, is_rejected, is_kept, scanned_at, "
            f"gps_latitude, gps_longitude, gps_manually_set "
            f"FROM photos {where}",
            params,
        ).fetchall()

    updated = unchanged = missing = skipped = tags_added = ambiguous = naming_mismatch = 0
    shared_stems = _shared_indexed_stems(conn) if sidecar_naming != "full" else set()
    directory_images: dict[str, dict[str, set[str]]] = {}
    reported: set[str] = set()
    created_by = user_id if per_user else None
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        try:
            sidecar, reason = _discover_sidecar(row["path"], sidecar_naming, shared_stems, directory_images, reported)
        except OSError as ex:
            logger.warning("Skipping %s: cannot inspect sidecars or image siblings: %s", row["path"], ex)
            skipped += 1
            continue
        if sidecar is None:
            if reason == "ambiguous":
                ambiguous += 1
                skipped += 1
            else:
                missing += 1
                if reason == "naming_mismatch":
                    naming_mismatch += 1
            continue
        parsed = parse_sidecar(sidecar)
        if parsed is None:
            logger.warning("Skipping %s: cannot parse sidecar %s", row["path"], sidecar)
            skipped += 1
            continue

        existing = set(load_manual_tags(conn, row["path"]))
        new_keywords = [
            tag for tag in _foreign_keywords(conn, row["path"], row["tags"], parsed["tags"])
            if tag not in existing
        ]
        room = max(0, MAX_TAGS_PER_PHOTO - len(existing))
        if len(new_keywords) > room:
            logger.info("Skipping %d keyword(s) on %s: photo is at the %d-tag cap",
                        len(new_keywords) - room, row["path"], MAX_TAGS_PER_PHOTO)
            new_keywords = new_keywords[:room]
        star = row["star_rating"] or 0
        favorite = bool(row["is_favorite"])
        rejected = bool(row["is_rejected"])
        kept = bool(row["is_kept"])
        untouched = not (star or favorite or rejected or kept)

        sidecar_epoch = _to_epoch(parsed["metadata_date"]) or os.path.getmtime(sidecar)
        photo_epoch = _to_epoch(_parse_date(row["scanned_at"]))
        sidecar_wins = photo_epoch is None or sidecar_epoch >= photo_epoch
        if parsed["has_rating"] and sidecar_wins:
            star = parsed["star_rating"]
            favorite = parsed["is_favorite"]
            rejected = parsed["is_rejected"]

        # Facet exports consistent private/standard rejection state. Editors
        # preserve unknown tags, so disagreement means the private decision is
        # stale: leave the standard fields to the timestamp gate above. Missing
        # standard fields still allow deliberate decision-only imports. Every
        # Facet export stamps a decision, so one riding with standard fields
        # follows their timestamp gate too, except into a photo with no review
        # state yet (a restore into a rescanned library).
        decision = parsed["review_decision"]
        decision_conflicts = (parsed["has_rating"] and decision is not None
                              and parsed["is_rejected"] != (decision == "rejected"))
        if (decision is not None and not decision_conflicts
                and (not parsed["has_rating"] or sidecar_wins or untouched)):
            kept = decision == "kept"
            rejected = decision == "rejected"
            if rejected:
                star, favorite = 0, False
        if rejected:
            kept = False
        gps = parsed["gps"]
        gps_changed = (gps is not None and (not row["gps_manually_set"] or overwrite_manual_gps)
                       and (not row["gps_manually_set"]
                            or gps != (row["gps_latitude"], row["gps_longitude"])))

        if (not new_keywords and not gps_changed and kept == bool(row["is_kept"]) and star == (row["star_rating"] or 0)
                and favorite == bool(row["is_favorite"])
                and rejected == bool(row["is_rejected"])):
            unchanged += 1
            continue

        for tag in new_keywords:
            if insert_manual_tag(conn, row["path"], tag, SOURCE_XMP, created_by, created_at):
                tags_added += 1
        upsert_rating_state(
            conn, row["path"], user_id,
            star_rating=star, is_favorite=favorite, is_rejected=rejected, is_kept=kept,
        )
        if gps_changed:
            conn.execute("UPDATE photos SET gps_latitude=?, gps_longitude=?, gps_manually_set=1 WHERE path=?",
                         (*gps, row["path"]))
        updated += 1

    conn.commit()
    return {"updated": updated, "unchanged": unchanged, "missing": missing, "skipped": skipped,
            "tags_added": tags_added, "ambiguous": ambiguous, "naming_mismatch": naming_mismatch}
