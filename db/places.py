"""Owner-private named coordinates and bounded assignment history.

Callers own transactions; these operations never commit independently.
"""
import sqlite3


class PlaceError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


_FIELDS = 'id, name, latitude, longitude, last_used_at, use_count'


def get_place(conn, owner, place_id):
    row = conn.execute(f'SELECT {_FIELDS} FROM saved_places WHERE owner=? AND id=?',
                       (owner, place_id)).fetchone()
    if row is None:
        raise PlaceError(404, 'Place not found')
    return dict(row)


def list_places(conn, owner):
    return {
        'places': [dict(r) for r in conn.execute(
            f'SELECT {_FIELDS} FROM saved_places WHERE owner=? ORDER BY normalized_name, id', (owner,))],
        'recent': [dict(r) for r in conn.execute(
            'SELECT latitude, longitude, last_used_at FROM recent_places WHERE owner=? '
            'ORDER BY last_used_at DESC, rowid DESC LIMIT 20', (owner,))],
    }


def save_place(conn, owner, name, latitude, longitude, place_id=None):
    if place_id is not None:
        get_place(conn, owner, place_id)
    elif conn.execute('SELECT COUNT(*) FROM saved_places WHERE owner=?', (owner,)).fetchone()[0] >= 100:
        raise PlaceError(409, 'Saved place limit reached')
    try:
        if place_id is None:
            place_id = conn.execute(
                'INSERT INTO saved_places(owner,name,normalized_name,latitude,longitude) VALUES (?,?,?,?,?)',
                (owner, name, name.casefold(), latitude, longitude)).lastrowid
        else:
            conn.execute('UPDATE saved_places SET name=?,normalized_name=?,latitude=?,longitude=? WHERE owner=? AND id=?',
                         (name, name.casefold(), latitude, longitude, owner, place_id))
    except sqlite3.IntegrityError as exc:
        raise PlaceError(409, 'A place with this name already exists') from exc
    return get_place(conn, owner, place_id)


def delete_place(conn, owner, place_id):
    get_place(conn, owner, place_id)
    conn.execute('DELETE FROM saved_places WHERE owner=? AND id=?', (owner, place_id))


def record_assignment(conn, owner, latitude, longitude, place_id=None):
    if latitude is None:
        return
    conn.execute("""INSERT INTO recent_places(owner,latitude,longitude,last_used_at)
        VALUES (?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(owner,latitude,longitude) DO UPDATE SET last_used_at=excluded.last_used_at,
        rowid=(SELECT COALESCE(MAX(rowid),0)+1 FROM recent_places)""",
        (owner, latitude, longitude))
    conn.execute('DELETE FROM recent_places WHERE owner=? AND rowid NOT IN '
                 '(SELECT rowid FROM recent_places WHERE owner=? ORDER BY last_used_at DESC,rowid DESC LIMIT 20)',
                 (owner, owner))
    if place_id is not None:
        conn.execute("UPDATE saved_places SET use_count=use_count+1,last_used_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE owner=? AND id=?",
                     (owner, place_id))
