"""Display-only manual-stack projection, after the authorized photo scope.

No photo data or encoded image is materialized here. The normal indexed gallery
query stays unchanged for accounts without stacks. Caller owns the read snapshot.
"""
from dataclasses import dataclass

from fastapi import HTTPException

from api.config import is_multi_user_enabled
from api.db_helpers import get_visibility_clause


_TABLES_SQL = ("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
               "AND name IN ('photo_stacks','photo_stack_members')")


def owner_for_user(user_id):
    if not is_multi_user_enabled():
        return ''
    return user_id or None


def enabled_owner(conn, user_id):
    owner = owner_for_user(user_id)
    if owner is None or conn.execute(_TABLES_SQL).fetchone()[0] != 2:
        return None
    return owner if conn.execute('SELECT 1 FROM photo_stacks WHERE owner=? LIMIT 1', (owner,)).fetchone() else None


async def enabled_owner_async(conn, user_id):
    owner = owner_for_user(user_id)
    if owner is None:
        return None
    async with conn.execute(_TABLES_SQL) as cur:
        if (await cur.fetchone())[0] != 2:
            return None
    async with conn.execute('SELECT 1 FROM photo_stacks WHERE owner=? LIMIT 1', (owner,)) as cur:
        return owner if await cur.fetchone() else None


def membership_clause():
    return ('EXISTS (SELECT 1 FROM photo_stack_members sm '
            'WHERE sm.owner=? AND sm.photo_path=photos.path)')


def _scope_query(user_id):
    vis, values = get_visibility_clause(user_id)
    return ('SELECT 1 FROM photo_stack_members sm JOIN photos ON photos.path=sm.photo_path '
            f'WHERE sm.owner=? AND sm.stack_id=? AND {vis} LIMIT 1'), values


def check_stack_scope(conn, owner, stack_id, user_id):
    if owner is None:
        raise HTTPException(404, 'Stack not found')
    sql, values = _scope_query(user_id)
    if conn.execute(sql, [owner, stack_id, *values]).fetchone() is None:
        raise HTTPException(404, 'Stack not found')


async def check_stack_scope_async(conn, owner, stack_id, user_id):
    if owner is None:
        raise HTTPException(404, 'Stack not found')
    sql, values = _scope_query(user_id)
    async with conn.execute(sql, [owner, stack_id, *values]) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(404, 'Stack not found')


@dataclass(frozen=True)
class StackProjection:
    cte: str
    params: list
    collapse: bool

    async def count(self, conn, photo_total):
        if not self.collapse:
            return photo_total
        async with conn.execute(
                self.cte + ' SELECT COUNT(*)-COUNT(DISTINCT _stack_id) FROM stack_ranked', self.params) as cur:
            return photo_total - (await cur.fetchone())[0]

    def page_query(self, select_cols, from_clause, where_str, params, order_by, per_page, offset):
        # Ranked columns have private names so unqualified existing sort/SELECT
        # expressions still resolve to the original photos/preference tables.
        sql = (self.cte + f" SELECT {', '.join(select_cols)}, "
               '_stack_id AS stack_id, _stack_matches AS stack_count, _stack_revision AS stack_revision '
               f'FROM {from_clause} LEFT JOIN stack_ranked ON photos.path=_stack_path{where_str}' +
               (' AND (_stack_id IS NULL OR _stack_rank=1)' if self.collapse else '') +
               f' ORDER BY {order_by} LIMIT ? OFFSET ?')
        return sql, [*self.params, *params, per_page, offset]


def projection(from_clause, where_str, params, owner, collapse=True):
    # Only actual stack members enter the window functions. Singletons retain
    # the gallery's ordinary indexed sort and never fill a library-sized window.
    cte = f"""WITH owned_stack_members AS (
        SELECT m.photo_path, m.stack_id, m.position, s.cover_path, s.revision
        FROM photo_stack_members m JOIN photo_stacks s ON s.id=m.stack_id AND s.owner=m.owner
        WHERE m.owner=?
    ), stack_candidates AS (
        SELECT photos.path AS _stack_path, m.stack_id AS _stack_id,
               m.revision AS _stack_revision, m.position AS _stack_position,
               m.cover_path AS _stack_cover
        FROM {from_clause} JOIN owned_stack_members m ON m.photo_path=photos.path{where_str}
    ), stack_ranked AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY _stack_id
            ORDER BY (_stack_path=_stack_cover) DESC, _stack_position, _stack_path
        ) AS _stack_rank,
        COUNT(*) OVER (PARTITION BY _stack_id) AS _stack_matches
        FROM stack_candidates
    )"""
    return StackProjection(cte, [owner, *params], collapse)


async def enrich_counts(photos, conn, owner, user_id):
    ids = sorted({p['stack_id'] for p in photos if p.get('stack_id')})
    if not ids:
        # Avoid publishing a fake one-photo stack for every singleton.
        for photo in photos:
            for key in ('stack_id', 'stack_count', 'stack_revision'):
                photo.pop(key, None)
        return
    vis, values = get_visibility_clause(user_id)
    marks = ','.join('?' for _ in ids)
    async with conn.execute(
            'SELECT m.stack_id, COUNT(*) AS n FROM photo_stack_members m '
            'JOIN photos ON photos.path=m.photo_path '
            f'WHERE m.owner=? AND m.stack_id IN ({marks}) AND {vis} GROUP BY m.stack_id',
            [owner, *ids, *values]) as cur:
        counts = {r['stack_id']: r['n'] for r in await cur.fetchall()}
    for photo in photos:
        if photo.get('stack_id'):
            photo['stack_total_count'] = counts.get(photo['stack_id'], 0)
        else:
            for key in ('stack_id', 'stack_count', 'stack_revision'):
                photo.pop(key, None)
