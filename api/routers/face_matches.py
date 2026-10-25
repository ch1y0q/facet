"""Faces that look like a given person, scored against the person's centroid.

A bounded read: the candidate faces are counted first and refused above ``MAX_FACE_SCAN``,
then streamed in chunks, so a library of any size cannot make one request load every embedding.
"""

import logging
import time
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import CurrentUser, require_authenticated
from api.database import get_db
from api.db_helpers import get_visibility_clause, person_visibility_exists, select_in_chunks
from api.models.culling import PossibleFacesResponse
from db.embedding_space import ARCFACE_MODEL, expected_dim, tag_matches
from db.schema import person_not_hidden_clause

logger = logging.getLogger(__name__)

router = APIRouter(tags=["faces"])

# What one scan may cost: the budget the tool waits for, and the embeddings it may stream.
FACE_SCAN_TIMEOUT_S = 120
FACE_SCAN_ROWS_PER_S = 1600
MAX_FACE_SCAN = int(FACE_SCAN_TIMEOUT_S * FACE_SCAN_ROWS_PER_S)
CHUNK_ROWS = 2000
KEEP_FACTOR = 4
DEFAULT_MIN_SIMILARITY = 0.30
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
FLOAT_BYTES = 4
SCOPES = ("unassigned", "unnamed", "other_persons", "all")

# ``unnamed`` is every face without a name: in no cluster, or in a cluster nobody has named
# yet. ``unassigned`` is the narrower "in no cluster at all".
_SCOPE_SQL = {
    "unassigned": "f.person_id IS NULL",
    "unnamed": "(f.person_id IS NULL OR (f.person_id != ? AND (pe.name IS NULL OR TRIM(pe.name) = '')))",
    "other_persons": "f.person_id IS NOT NULL AND f.person_id != ?",
    "all": "(f.person_id IS NULL OR f.person_id != ?)",
}


def _candidate_filter(person_id: int, scope: str, user_id, path_prefix: Optional[str],
                      date_from: Optional[str], date_to: Optional[str]) -> tuple[str, str, list]:
    """``(from_sql, where_sql, params)`` selecting the faces a scan may count and read.

    The caller's photo visibility and the hidden-person rule are part of the SQL, so the counts
    reported only ever cover faces the caller may see. Without a join the plain scopes are
    answered from ``idx_faces_person`` (and ``idx_faces_person_photo`` for ``path_prefix``) alone.
    """
    clauses = [_SCOPE_SQL[scope]]
    params: list = [person_id] if scope != "unassigned" else []
    from_sql = "faces f"
    if scope != "unassigned":
        from_sql += " LEFT JOIN persons pe ON pe.id = f.person_id"
        clauses.append(f"(pe.id IS NULL OR {person_not_hidden_clause('pe')})")
    if path_prefix:
        norm = path_prefix.replace('\\', '/').rstrip('/') + '/'
        clauses.append("REPLACE(f.photo_path, '\\', '/') LIKE ? ESCAPE '\\'")
        params.append(norm.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    vis_sql, vis_params = get_visibility_clause(user_id, 'ph')
    if date_from or date_to or vis_sql != '1=1':
        from_sql += " JOIN photos ph ON ph.path = f.photo_path"
        if vis_sql != '1=1':
            clauses.append(vis_sql)
            params.extend(vis_params)
    if date_from or date_to:
        expr = "DATE(REPLACE(SUBSTR(ph.date_taken,1,10),':','-'))"
        for bound, op in ((date_from, ">="), (date_to, "<=")):
            if bound:
                clauses.append(f"{expr} {op} ?")
                params.append(bound)
    return from_sql, " AND ".join(clauses), params


def _scan(conn, from_sql: str, where_sql: str, params: list, centroid: np.ndarray, dim: int,
          min_similarity: float, keep: int) -> tuple[int, np.ndarray, np.ndarray]:
    """Stream the candidates; return ``(scanned, face_ids, similarities)`` of the best ``keep``."""
    cursor = conn.execute(
        f"SELECT f.id, f.embedding FROM {from_sql} WHERE {where_sql} AND length(f.embedding) = ?",
        [*params, dim * FLOAT_BYTES])
    best_ids = np.empty(0, dtype=np.int64)
    best_sims = np.empty(0, dtype=np.float32)
    scanned = 0
    while True:
        chunk = cursor.fetchmany(CHUNK_ROWS)
        if not chunk:
            break
        scanned += len(chunk)
        ids = np.fromiter((row[0] for row in chunk), dtype=np.int64, count=len(chunk))
        matrix = np.frombuffer(b"".join(row[1] for row in chunk), dtype=np.float32).reshape(len(chunk), dim)
        sims = (matrix @ centroid) / (np.linalg.norm(matrix, axis=1) + 1e-10)
        hit = sims >= min_similarity
        best_ids = np.concatenate([best_ids, ids[hit]])
        best_sims = np.concatenate([best_sims, sims[hit].astype(np.float32)])
        if len(best_ids) > keep:
            top = np.argpartition(-best_sims, keep - 1)[:keep]
            best_ids, best_sims = best_ids[top], best_sims[top]
    return scanned, best_ids, best_sims


@router.get("/api/person/{person_id}/possible_faces", response_model=PossibleFacesResponse,
            response_model_exclude_unset=True,
            responses={404: {"description": "Person not found"},
                       412: {"description": "No usable centroid, or the scan is over MAX_FACE_SCAN faces"}})
def api_person_possible_faces(
    person_id: int,
    scope: Literal["unassigned", "unnamed", "other_persons", "all"] = "unassigned",
    min_similarity: float = Query(DEFAULT_MIN_SIMILARITY, ge=0.0, le=1.0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    path_prefix: Optional[str] = Query(None, max_length=4096),
    date_from: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(require_authenticated),
):
    """Faces most like ``person_id``'s centroid, best first (same embedding model only)."""
    user_id = user.user_id if user else None
    started = time.monotonic()
    with get_db() as conn:
        row = conn.execute(
            "SELECT centroid, centroid_model FROM persons WHERE id = ?", (person_id,)).fetchone()
        fragment, frag_params = person_visibility_exists(user_id, 'persons.id')
        visible = row is not None and (not fragment or conn.execute(
            f"SELECT 1 FROM persons WHERE id = ? AND {fragment}", [person_id, *frag_params]).fetchone())
        if not visible:
            raise HTTPException(status_code=404, detail="Person not found")
        if not row[0]:
            raise HTTPException(status_code=412, detail="This person has no centroid yet; run face clustering first")
        model = row[1] or ARCFACE_MODEL
        try:
            dim = expected_dim(model)
        except ValueError:
            raise HTTPException(status_code=412, detail="This person's centroid uses an unknown embedding model")
        centroid = np.frombuffer(row[0], dtype=np.float32)
        if len(centroid) != dim:
            raise HTTPException(status_code=412, detail="This person's centroid does not match its embedding model")
        centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
        from_sql, where_sql, params = _candidate_filter(
            person_id, scope, user_id, path_prefix, date_from, date_to)
        candidates = conn.execute(
            f"SELECT COUNT(*) FROM {from_sql} WHERE {where_sql}", params).fetchone()[0]
        if candidates > MAX_FACE_SCAN:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail=(f"{candidates} faces would be scanned, over the ceiling of {MAX_FACE_SCAN}; "
                        "narrow the scan with scope, path_prefix, date_from or date_to"))
        scanned, ids, sims = _scan(conn, from_sql, where_sql, params, centroid, dim,
                                   min_similarity, KEEP_FACTOR * limit)
        similarity = {int(i): float(s) for i, s in zip(ids, sims)}
        faces = _resolve(conn, model, similarity)
    faces.sort(key=lambda face: -face["similarity"])
    logger.info("possible_faces person=%d scanned=%d kept=%d ms=%d", person_id, scanned, len(faces),
                (time.monotonic() - started) * 1000)
    return {"faces": faces[:limit], "faces_scanned": scanned, "candidates": candidates}


def _resolve(conn, model: str, similarity: dict[int, float]) -> list[dict]:
    """Attach photo, owner and model to the best faces; drop what is hidden."""
    if not similarity:
        return []
    rows = list(select_in_chunks(
        conn,
        "SELECT f.id, f.photo_path, f.person_id, f.embedding_model, pe.name "
        "FROM faces f LEFT JOIN persons pe ON pe.id = f.person_id "
        f"WHERE f.id IN ({{placeholders}}) AND (pe.id IS NULL OR {person_not_hidden_clause('pe')})",
        list(similarity)))
    return [{"face_id": r[0], "photo_path": r[1], "person_id": r[2], "person_name": r[4],
             "similarity": round(similarity[r[0]], 4), "distance": round(1.0 - similarity[r[0]], 4)}
            for r in rows if tag_matches(r[3], model)]
