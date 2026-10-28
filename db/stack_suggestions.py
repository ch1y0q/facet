"""Read-only candidates from existing detectors, scoped before grouping."""
import hashlib
import json
from itertools import groupby

from db.stacks import MAX_MEMBERS

MAX_SUGGESTIONS = 20
MAX_RETURNED_MEMBERS = 2000
MAX_CANDIDATE_GROUPS = 40


def suggestions(conn, owner, source, where, params):
    # Reused CTE keeps membership, filters, visibility and owner-stack membership
    # in one read snapshot. SQL identifiers are fixed; all user data stays bound.
    query = f"""WITH scoped AS (
        SELECT photos.path, photos.aggregate,
               photos.duplicate_group_id, photos.burst_group_id,
               photos.is_duplicate_lead, photos.is_burst_lead,
               EXISTS(SELECT 1 FROM photo_stack_members m
                      WHERE m.owner=? AND m.photo_path=photos.path) AS stacked
        FROM {source}{where}
        AND COALESCE(photos.sequence_kind,'') NOT IN ('bracket','panorama','hdr_panorama')
    ), grouped AS (
        SELECT 'duplicate' AS kind, duplicate_group_id AS group_id, COUNT(*) AS n, SUM(stacked) AS stacked
        FROM scoped WHERE duplicate_group_id IS NOT NULL GROUP BY duplicate_group_id
        UNION ALL
        SELECT 'burst', burst_group_id, COUNT(*), SUM(stacked)
        FROM scoped WHERE burst_group_id IS NOT NULL GROUP BY burst_group_id
    ), chosen AS (
        SELECT * FROM grouped WHERE n BETWEEN 2 AND ? AND stacked=0
        ORDER BY CASE kind WHEN 'duplicate' THEN 0 ELSE 1 END, group_id LIMIT ?
    )
    SELECT g.kind,g.group_id,s.path,
        CASE g.kind WHEN 'duplicate' THEN s.is_duplicate_lead ELSE s.is_burst_lead END AS lead
    FROM chosen g JOIN scoped s ON
        (g.kind='duplicate' AND s.duplicate_group_id=g.group_id) OR
        (g.kind='burst' AND s.burst_group_id=g.group_id)
    ORDER BY CASE g.kind WHEN 'duplicate' THEN 0 ELSE 1 END,g.group_id,
             lead DESC, s.aggregate DESC, s.path
    """
    rows = conn.execute(query, [owner, *params, MAX_MEMBERS, MAX_CANDIDATE_GROUPS])
    result, used = [], set()
    for (kind, group_id), group in groupby(rows, key=lambda r: (r['kind'], r['group_id'])):
        paths = [r['path'] for r in group]
        # Overlaps are skipped whole; don't turn a detector group into an
        # unexplained residual group or give the same photo multiple suggestions.
        if used.intersection(paths) or len(used) + len(paths) > MAX_RETURNED_MEMBERS:
            continue
        # Detector IDs can be reassigned by a rescan. Dismissal belongs to the
        # observed membership, so an unrelated replacement group stays visible.
        identity = json.dumps([kind, sorted(paths)], ensure_ascii=False, separators=(',', ':'))
        key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        result.append(dict(key=key, kind=kind, paths=paths, cover_path=paths[0]))
        used.update(paths)
        if len(result) == MAX_SUGGESTIONS:
            break
    return result
