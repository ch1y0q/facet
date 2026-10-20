"""The undo journal: what an agent changed, so its owner can take it back.

Journaling lives in the TOOL WRAPPER, never in the routes, so an edit made in the UI is never
journaled and no route signature changes. One batch is one tool call; a batch holds one row per
changed field of a changed target, carrying the old value and the INTENDED new value (never a
post-read, so a concurrent edit is not recorded as the agent's).

Undo is a compare-and-set per row group: the current value is read as the owner through the same
routes the original write used, and the old value is restored only when the current value still
equals the one the agent wrote. The three rating fields (``star_rating``, ``is_favorite``,
``is_rejected``) are coupled by the routes' side effects, so they are restored as one TUPLE per
photo, all or nothing.

The journal never touches ``photos`` or ``user_preferences`` itself: reads and writes go through
:class:`InternalClient`, so single-user and multi-user storage are handled by the code that wrote
them in the first place.
"""

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Union

from api.agent import tokens
from api.agent.internal_client import InternalClient
from api.database import get_db
from api.db_helpers import retry_on_locked

logger = logging.getLogger(__name__)

ROWS_PER_BATCH = 5000
# A scope larger than this many photos (3 journal rows each) is not pinned to an exact list, so not journaled.
PIN_CAP = ROWS_PER_BATCH // 3
RETENTION_DAYS = 30
MAX_ROWS_PER_OWNER = 20000
BY_PATHS_CHUNK = 500
UNDONE_LIST_CAP = 50

SUPPRESSED = "suppressed"
SOURCE_MCP = "mcp"
SOURCE_DIALOG = "dialog"
RATING_FIELDS = ("star_rating", "is_favorite", "is_rejected")
RATING_LEVEL = "user"
# Outcomes of one restored target.
RESTORED = "restored"
SKIPPED_CHANGED = "skipped_changed_since"
MISSING = "missing"
SKIPPED_LEVEL = "skipped_level"
ERROR = "error"

Row = tuple[str, str, Any, Any]
"""``(target_key, field, old_value, new_value)``."""

NOT_UNDOABLE_FILES = ("Files were moved or sent to the trash and library rows removed; undo_last cannot "
                      "restore them. For a move, move the files back manually; for the OS trash, "
                      "restore them from the trash.")


def new_batch_id() -> str:
    return secrets.token_hex(8)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load(text: Optional[str]) -> Any:
    return None if text is None else json.loads(text)


def owner_of(resolved: Union[tokens.ResolvedGrant, tokens.SessionGrant]) -> str:
    return resolved.principal


def _rank(level: str) -> int:
    return tokens.level_rank(tokens.effective_requirement(level))


def seal_note(unavailable: Optional[str]) -> str:
    return unavailable or "journal unavailable"


async def seal(grant: Any, resolved: tokens.ResolvedGrant, tool: str, rows: list[Row], result: dict,
               *, unavailable: Optional[str] = None) -> dict:
    """Journal ``rows`` as one batch and attach ``undo`` to ``result`` (its ``data`` when ok).

    A result without rows is returned untouched ("already" results journal nothing). A batch above
    :data:`ROWS_PER_BATCH`, an unpinned scope, or a journal that cannot be written still lets the
    write stand: ``undo.available`` is false and says why.
    """
    if unavailable is None and not rows:
        return result
    undo: dict[str, Any] = {"available": False, "reason": unavailable}
    if unavailable is None and len(rows) > ROWS_PER_BATCH:
        undo["reason"] = f"{len(rows)} changes exceed the journal's {ROWS_PER_BATCH} per call"
    elif unavailable is None:
        batch_id = new_batch_id()
        try:
            await _to_thread(lambda: record(
                batch_id, token_id=grant.id, source=SOURCE_MCP, actor=None, session_id=None,
                owner=owner_of(resolved), tool=tool, rows=rows))
            undo = {"batch_id": batch_id, "rows": len(rows), "available": True}
        except Exception:
            logger.exception("Could not journal %s", tool)
            undo["reason"] = seal_note(None)
    holder = result["data"] if result.get("ok") and isinstance(result.get("data"), dict) else result
    holder["undo"] = undo
    return result


def not_undoable(result: dict, note: str) -> dict:
    """Mark a finished result as one ``undo_last`` cannot take back, and say why."""
    holder = result["data"] if result.get("ok") and isinstance(result.get("data"), dict) else result
    holder["undoable"] = False
    holder["undo_note"] = note
    return result


def required_level_of(field: str) -> str:
    return RATING_LEVEL if field in RATING_FIELDS else "edition"


# ---- rating tuple ---------------------------------------------------------------------------

def photo_tuple(photo: dict) -> tuple[int, int, int]:
    """``(star_rating, is_favorite, is_rejected)`` with NULL read as 0 (most rows carry NULL flags)."""
    return (int(photo.get("star_rating") or 0), int(bool(photo.get("is_favorite"))),
            int(bool(photo.get("is_rejected"))))


def intended_tuple(old: tuple[int, int, int], op: str, value: Any) -> tuple[int, int, int]:
    """The tuple the rating routes leave behind (their side effects, mirrored).

    ``favorite`` on clears rejected; off touches only the flag. ``rejected`` on clears rating and
    favourite; off touches only the flag. ``rating`` touches only the rating.
    """
    rating, favorite, rejected = old
    if op == "rating":
        return (int(value), favorite, rejected)
    if op == "favorite":
        return (rating, 1, 0) if value else (rating, 0, rejected)
    if op == "rejected":
        return (0, 0, 1) if value else (rating, favorite, 0)
    if op == "flag_rejected":
        # The darkroom's reject (``set_photos_rejected``) sets only the flag.
        return (rating, favorite, 1)
    raise ValueError(f"unknown rating op {op!r}")


def rating_rows(path: str, old: tuple[int, int, int], new: tuple[int, int, int]) -> list[Row]:
    """The three field rows of one photo whose tuple changed, none when it did not."""
    if old == new:
        return []
    return [(path, field, old[i], new[i]) for i, field in enumerate(RATING_FIELDS)]


# ---- storage --------------------------------------------------------------------------------

@retry_on_locked()
def record(batch_id: str, *, token_id: Optional[int], source: str, actor: Optional[str],
           session_id: Optional[str], owner: str, tool: str, rows: Iterable[Row]) -> int:
    """Insert one batch, then prune the owner's history. Returns the number of rows written."""
    stamp = _now()
    values = [(batch_id, token_id, source, actor, session_id, owner, tool, target, field,
               _dump(old), _dump(new), required_level_of(field), stamp)
              for target, field, old, new in rows]
    if not values:
        return 0
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO agent_actions (batch_id, token_id, source, actor, session_id, owner_user, tool, "
            "target_key, field, old_value, new_value, required_level, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        _prune(conn, owner)
        conn.commit()
    return len(values)


def _prune(conn: sqlite3.Connection, owner: str) -> None:
    """Whole batches only: older than the retention window, then oldest-first past the row cap."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM agent_actions WHERE owner_user = ? AND batch_id IN "
                 "(SELECT batch_id FROM agent_actions WHERE owner_user = ? GROUP BY batch_id "
                 "HAVING MAX(created_at) < ?)", (owner, owner, cutoff))
    total = conn.execute("SELECT COUNT(*) FROM agent_actions WHERE owner_user = ?", (owner,)).fetchone()[0]
    if total <= MAX_ROWS_PER_OWNER:
        return
    batches = conn.execute("SELECT batch_id, COUNT(*) AS n FROM agent_actions WHERE owner_user = ? "
                           "GROUP BY batch_id ORDER BY MIN(id) ASC", (owner,)).fetchall()
    for batch in batches:
        if total <= MAX_ROWS_PER_OWNER:
            break
        conn.execute("DELETE FROM agent_actions WHERE owner_user = ? AND batch_id = ?",
                     (owner, batch["batch_id"]))
        total -= batch["n"]


@retry_on_locked()
def prune_by_age() -> int:
    """Drop every owner's batches older than the retention window (server startup)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    with get_db() as conn:
        removed = conn.execute(
            "DELETE FROM agent_actions WHERE batch_id IN (SELECT batch_id FROM agent_actions "
            "GROUP BY batch_id HAVING MAX(created_at) < ?)", (cutoff,)).rowcount
        conn.commit()
    return removed


def list_batches(owner: str, *, limit: int, include_undone: bool = False,
                 ceiling_rank: Optional[int] = None) -> list[dict]:
    """The owner's batches, newest first: ``{batch_id, tool, source, token_name, created_at, rows,
    undone, fields}``. ``ceiling_rank`` hides batches whose rows need a higher level."""
    having = "" if include_undone else "HAVING SUM(CASE WHEN a.undone_at IS NULL THEN 1 ELSE 0 END) > 0"
    with get_db() as conn:
        rows = conn.execute(
            "SELECT a.batch_id, MIN(a.tool) AS tool, MIN(a.source) AS source, MIN(a.created_at) AS created_at, "
            "COUNT(*) AS rows, SUM(CASE WHEN a.undone_at IS NULL THEN 1 ELSE 0 END) AS open_rows, "
            "GROUP_CONCAT(DISTINCT a.field) AS fields, GROUP_CONCAT(DISTINCT a.required_level) AS levels, "
            "MIN(a.token_id) AS token_id, MIN(a.actor) AS actor, MAX(a.id) AS last_id, "
            "MIN(t.name) AS token_name "
            "FROM agent_actions a LEFT JOIN mcp_tokens t ON t.id = a.token_id "
            f"WHERE a.owner_user = ? GROUP BY a.batch_id {having} ORDER BY last_id DESC", (owner,)).fetchall()
    out = []
    for row in rows:
        levels = (row["levels"] or "").split(",")
        if ceiling_rank is not None and any(_rank(level) > ceiling_rank for level in levels if level):
            continue
        out.append({"batch_id": row["batch_id"], "tool": row["tool"], "source": row["source"],
                    "token_name": row["token_name"] or row["actor"], "created_at": row["created_at"],
                    "rows": row["rows"], "undone": row["open_rows"] == 0,
                    "fields": sorted((row["fields"] or "").split(","))})
        if len(out) >= limit:
            break
    return out


def latest_open_batch(owner: str, ceiling_rank: Optional[int] = None) -> Optional[str]:
    found = list_batches(owner, limit=1, ceiling_rank=ceiling_rank)
    return found[0]["batch_id"] if found else None


def batch_rows(owner: str, batch_id: str) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM agent_actions WHERE owner_user = ? AND batch_id = ? ORDER BY id",
                            (owner, batch_id)).fetchall()


@retry_on_locked()
def claim(owner: str, batch_id: str, undo_batch_id: str, allowed_levels: tuple[str, ...]) -> list[sqlite3.Row]:
    """Atomically take the batch's open rows (at the caller's levels). Two undos cannot both win."""
    marks = ",".join("?" * len(allowed_levels))
    with get_db() as conn:
        conn.execute(
            f"UPDATE agent_actions SET undone_at = ?, undo_batch_id = ? WHERE owner_user = ? AND batch_id = ? "
            f"AND undone_at IS NULL AND required_level IN ({marks})",
            (_now(), undo_batch_id, owner, batch_id, *allowed_levels))
        conn.commit()
        return conn.execute("SELECT * FROM agent_actions WHERE undo_batch_id = ? ORDER BY id",
                            (undo_batch_id,)).fetchall()


@retry_on_locked()
def reopen(row_ids: list[int]) -> None:
    """Make rows undoable again: used when a restore failed before anything was written for them."""
    if not row_ids:
        return
    marks = ",".join("?" * len(row_ids))
    with get_db() as conn:
        conn.execute(f"UPDATE agent_actions SET undone_at = NULL, undo_batch_id = NULL WHERE id IN ({marks})",
                     row_ids)
        conn.commit()


# ---- reads through the routes ---------------------------------------------------------------

async def read_photos(client: InternalClient, grant: Any, paths: list[str], timeout: float,
                      filters: Optional[dict] = None) -> tuple[Optional[dict], dict[str, dict]]:
    """``(error, {path: photo})`` for ``paths`` as the grant's owner sees them (chunks of 500)."""
    found: dict[str, dict] = {}
    for start in range(0, len(paths), BY_PATHS_CHUNK):
        got = await client.call(grant, "photos_by_paths", timeout=timeout,
                                json={"paths": paths[start:start + BY_PATHS_CHUNK], "filters": filters or {}})
        if not got["ok"]:
            return got, {}
        for photo in (got["data"] or {}).get("photos") or []:
            found[photo["path"]] = photo
    return None, found


async def snapshot_ratings(client: InternalClient, grant: Any, paths: list[str],
                           timeout: float) -> tuple[Optional[dict], dict[str, tuple[int, int, int]]]:
    failure, photos = await read_photos(client, grant, paths, timeout)
    return failure, {path: photo_tuple(photo) for path, photo in photos.items()}


# ---- undo -----------------------------------------------------------------------------------

def _split_album_key(key: str) -> tuple[int, str]:
    _, album_id, path = key.split(":", 2)
    return int(album_id), path


async def _undo_ratings(client: InternalClient, grant: Any, timeout: float,
                        by_path: dict[str, dict[str, sqlite3.Row]]) -> dict[str, str]:
    """Per photo: restore the whole tuple, or nothing. Order: un-reject, rating, favourite, re-reject."""
    failure, current = await snapshot_ratings(client, grant, list(by_path), timeout)
    outcomes: dict[str, str] = {}
    for path, fields in by_path.items():
        old_rating, old_favorite, old_rejected = (
            int(load(fields[f]["old_value"]) or 0) if f in fields else 0 for f in RATING_FIELDS)
        new_rating, new_favorite, new_rejected = (
            int(load(fields[f]["new_value"]) or 0) if f in fields else 0 for f in RATING_FIELDS)
        old = (old_rating, old_favorite, old_rejected)
        new = (new_rating, new_favorite, new_rejected)
        if failure is not None:
            outcomes[path] = ERROR
            continue
        if path not in current:
            outcomes[path] = MISSING
            continue
        now = current[path]
        if now != new:
            outcomes[path] = SKIPPED_CHANGED
            continue
        outcomes[path] = await _restore_tuple(client, grant, timeout, path, now, old)
    return outcomes


async def _restore_tuple(client: InternalClient, grant: Any, timeout: float, path: str,
                         now: tuple[int, int, int], old: tuple[int, int, int]) -> str:
    async def toggle(route: str) -> bool:
        return (await client.call(grant, route, json={"photo_path": path}, timeout=timeout))["ok"]

    async def reread() -> tuple[int, int, int]:
        failure, state = await snapshot_ratings(client, grant, [path], timeout)
        return state.get(path, now) if failure is None else now
    rating, favorite, rejected = now
    if rejected and not old[2]:
        if not await toggle("toggle_rejected"):
            return ERROR
        rating, favorite, rejected = await reread()
    if rating != old[0]:
        written = await client.call(grant, "set_rating", json={"photo_path": path, "rating": old[0]},
                                    timeout=timeout)
        if not written["ok"]:
            return ERROR
        rating, favorite, rejected = await reread()
    if favorite != old[1]:
        if not await toggle("toggle_favorite"):
            return ERROR
        rating, favorite, rejected = await reread()
    if old[2] and not rejected:
        if not await toggle("toggle_rejected"):
            return ERROR
    return RESTORED


async def _undo_tags(client: InternalClient, grant: Any, timeout: float, rows: list[sqlite3.Row]) -> dict[str, str]:
    failure, photos = await read_photos(client, grant, [r["target_key"] for r in rows], timeout)
    outcomes: dict[str, str] = {}
    for row in rows:
        key, tag = row["target_key"], row["field"].split(":", 1)[1]
        if failure is not None:
            outcomes[key + "|" + row["field"]] = ERROR
            continue
        photo = photos.get(key)
        if photo is None:
            outcomes[key + "|" + row["field"]] = MISSING
            continue
        if (tag in (photo.get("manual_tags") or [])) != bool(load(row["new_value"])):
            outcomes[key + "|" + row["field"]] = SKIPPED_CHANGED
            continue
        written = await client.call(
            grant, "batch_manual_tags", timeout=timeout,
            json={"photo_paths": [key], "tag": tag, "action": "add" if load(row["old_value"]) else "delete"})
        outcomes[key + "|" + row["field"]] = RESTORED if written["ok"] else ERROR
    return outcomes


async def _undo_albums(client: InternalClient, grant: Any, timeout: float, rows: list[sqlite3.Row]) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for row in rows:
        album_id, path = _split_album_key(row["target_key"])
        failure, members = await read_photos(client, grant, [path], timeout, {"album_id": album_id})
        key = row["target_key"] + "|" + row["field"]
        if failure is not None:
            outcomes[key] = ERROR
            continue
        if (path in members) != bool(load(row["new_value"])):
            outcomes[key] = SKIPPED_CHANGED
            continue
        route = "album_add_photos" if load(row["old_value"]) else "album_remove_photos"
        written = await client.call(grant, route, path_args={"album_id": album_id}, json={"photo_paths": [path]},
                                    timeout=timeout)
        outcomes[key] = RESTORED if written["ok"] else (MISSING if written.get("error") == "not_found" else ERROR)
    return outcomes


async def _undo_captions(client: InternalClient, grant: Any, timeout: float, rows: list[sqlite3.Row]) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for row in rows:
        key = row["target_key"] + "|" + row["field"]
        got = await client.call(grant, "get_photo", query={"path": row["target_key"]}, timeout=timeout)
        if not got["ok"]:
            outcomes[key] = MISSING if got.get("error") == "not_found" else ERROR
            continue
        if ((got["data"] or {}).get("caption") or "") != (load(row["new_value"]) or ""):
            outcomes[key] = SKIPPED_CHANGED
            continue
        written = await client.call(grant, "set_caption", timeout=timeout,
                                    json={"path": row["target_key"], "caption": load(row["old_value"]) or ""})
        outcomes[key] = RESTORED if written["ok"] else ERROR
    return outcomes


async def apply_sequence(client: InternalClient, grant: Any, timeout: float, paths: list[str],
                          value: Optional[str]) -> dict:
    """Write one override value (None clears) for ``paths`` through the same routes the tools use."""
    if value is None:
        return await client.call(grant, "clear_sequence_override", json={"paths": paths}, timeout=timeout)
    return await client.call(grant, "override_sequence", timeout=timeout,
                             json={"paths": paths, "kind": None if value == SUPPRESSED else value})


async def _undo_sequence(client: InternalClient, grant: Any, timeout: float, rows: list) -> dict[str, str]:
    """Restore each path's override, grouped by the value it had before (a split set goes back together)."""
    failure, photos = await read_photos(client, grant, [r["target_key"] for r in rows], timeout)
    outcomes: dict[str, str] = {}
    pending: dict[Optional[str], list] = {}
    for row in rows:
        key = row["target_key"] + "|" + row["field"]
        if failure is not None:
            outcomes[key] = ERROR
        elif row["target_key"] not in photos:
            outcomes[key] = MISSING
        elif photos[row["target_key"]].get("sequence_override") != load(row["new_value"]):
            outcomes[key] = SKIPPED_CHANGED
        else:
            pending.setdefault(load(row["old_value"]), []).append(row)
    for value, group in pending.items():
        written = await apply_sequence(client, grant, timeout, [r["target_key"] for r in group], value)
        for row in group:
            outcomes[row["target_key"] + "|" + row["field"]] = RESTORED if written["ok"] else ERROR
    return outcomes


async def apply_category(client: InternalClient, grant: Any, timeout: float, path: str,
                          value: Optional[str]) -> dict:
    if value is None:
        return await client.call(grant, "clear_category_override", json={"path": path}, timeout=timeout)
    return await client.call(grant, "override_category", json={"path": path, "category": value}, timeout=timeout)


async def _undo_category(client: InternalClient, grant: Any, timeout: float, rows: list) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for row in rows:
        key = row["target_key"] + "|" + row["field"]
        got = await client.call(grant, "get_photo", query={"path": row["target_key"]}, timeout=timeout)
        if not got["ok"]:
            outcomes[key] = MISSING if got.get("error") == "not_found" else ERROR
        elif (got["data"] or {}).get("category_override") != load(row["new_value"]):
            outcomes[key] = SKIPPED_CHANGED
        else:
            written = await apply_category(client, grant, timeout, row["target_key"], load(row["old_value"]))
            outcomes[key] = RESTORED if written["ok"] else ERROR
    return outcomes


async def undo_batch(client: InternalClient, grant: Any, resolved: tokens.ResolvedGrant, owner: str,
                     batch_id: str, timeout: float,
                     ceiling_rank: Optional[int] = None) -> dict:
    """Undo one batch. ``{ok, data}`` with per-target outcomes, or an error envelope's fields.

    Rows needing a level above the caller's are left open and reported ``skipped_level``.
    """
    from api.agent.internal_client import err, ok
    rows = await _to_thread(batch_rows, owner, batch_id)
    if ceiling_rank is not None and any(_rank(r["required_level"]) > ceiling_rank for r in rows):
        rows = []
    if not rows:
        return err("not_found", "No such action batch for this account")
    if all(r["undone_at"] is not None for r in rows):
        return err("already_undone", "That batch was already undone")
    allowed_rows = tuple(level for level in ("user", "edition")
                         if tokens.level_rank(resolved.level) >= tokens.level_rank(tokens.effective_requirement(level)))
    held = [r for r in rows if r["undone_at"] is None and r["required_level"] not in allowed_rows]
    if held and len(held) == sum(1 for r in rows if r["undone_at"] is None):
        return err("forbidden_level", f"Undoing this batch needs {held[0]['required_level']}; "
                   f"this credential is {resolved.level}")
    undo_id = new_batch_id()
    claimed = await _to_thread(claim, owner, batch_id, undo_id, allowed_rows)
    if not claimed:
        return err("already_undone", "That batch was already undone")
    outcomes: dict[str, str] = {}
    ratings: dict[str, dict[str, sqlite3.Row]] = {}
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in claimed:
        if row["field"] in RATING_FIELDS:
            ratings.setdefault(row["target_key"], {})[row["field"]] = row
        else:
            groups.setdefault(row["field"].split(":", 1)[0], []).append(row)
    try:
        if ratings:
            outcomes.update({k + "|rating": v for k, v in (await _undo_ratings(client, grant, timeout, ratings)).items()})
        for kind, applier in {"manual_tag": _undo_tags, "album_member": _undo_albums, "caption": _undo_captions,
                              "sequence_override": _undo_sequence, "category_override": _undo_category}.items():
            if kind in groups:
                outcomes.update(await applier(client, grant, timeout, groups[kind]))
    except Exception:
        await _to_thread(reopen, [r["id"] for r in claimed if r["id"] is not None and not outcomes])
        raise
    failed = [r["id"] for r in claimed if _outcome_of(r, outcomes) == ERROR]
    await _to_thread(reopen, failed)
    results = [{"target": r["target_key"], "field": r["field"], "outcome": _outcome_of(r, outcomes)}
               for r in claimed if r["field"] not in RATING_FIELDS[1:]]
    results += [{"target": r["target_key"], "field": r["field"], "outcome": SKIPPED_LEVEL} for r in held]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
    return ok({"batch_id": batch_id, "outcomes": counts, "results": results[:200],
               "results_count": len(results)})


def _outcome_of(row: sqlite3.Row, outcomes: dict[str, str]) -> str:
    if row["field"] in RATING_FIELDS:
        return outcomes.get(row["target_key"] + "|rating", ERROR)
    return outcomes.get(row["target_key"] + "|" + row["field"], ERROR)


async def _to_thread(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)
