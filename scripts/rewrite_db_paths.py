"""Rewrite stored photo paths in a Facet database from one prefix to another.

Built for moving a library scanned in Docker (``/data/photos/...``) to a native
Windows install, where the scanner stores ``Path.resolve()`` paths such as
``\\\\NAS\\share\\...``. ``viewer.path_mapping`` only covers the viewer, so a
mapped database would gain duplicate rows on the next scan; rewriting keeps the
viewer and the scanner on one spelling.

Run it on a COPY. It rewrites every plain path column, the JSON columns that
embed paths, drops the stats cache, and rebuilds FTS. ``photos_vec`` is keyed by
path, so it is emptied; repopulate it with ``python database.py --populate-vec``.

    python scripts/rewrite_db_paths.py DB /data/photos "\\\\192.168.1.90\\Photos and Videos"
"""
import argparse
import json
import sqlite3
import sys

JSON_COLUMNS = [('albums', 'smart_filter_json'), ('scan_runs', 'args_json')]


def convert(value, src, dst, sep):
    if not isinstance(value, str):
        return value
    if value == src or value.startswith(src + '/'):
        return dst + value[len(src):].replace('/', sep)
    return value


def convert_json(obj, src, dst, sep):
    if isinstance(obj, dict):
        return {k: convert_json(v, src, dst, sep) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_json(v, src, dst, sep) for v in obj]
    return convert(obj, src, dst, sep)


def path_columns(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql NOT LIKE 'CREATE VIRTUAL%' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'photos_fts_%' AND name NOT LIKE 'photos_vec_%'")]
    for table in tables:
        for col in conn.execute(f'PRAGMA table_info("{table}")'):
            name = col[1]
            if name == 'path' or name.endswith('_path'):
                yield table, name


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('db')
    ap.add_argument('src', help='stored prefix, e.g. /data/photos')
    ap.add_argument('dst', help='new prefix, e.g. \\\\NAS\\share')
    ap.add_argument('--sep', default='\\', help='separator for the rest of the path')
    args = ap.parse_args()
    src = args.src.rstrip('/')

    conn = sqlite3.connect(args.db)
    conn.execute('PRAGMA foreign_keys = OFF')
    conn.create_function('facet_rewrite', 1, lambda v: convert(v, src, args.dst, args.sep), deterministic=True)
    with conn:
        for table, col in path_columns(conn):
            n = conn.execute(
                f'UPDATE "{table}" SET "{col}" = facet_rewrite("{col}") '
                f'WHERE "{col}" = ? OR "{col}" LIKE ?', (src, src + '/%')).rowcount
            if n:
                print(f'{table}.{col}: {n}')
        for table, col in JSON_COLUMNS:
            rows = conn.execute(f'SELECT rowid, "{col}" FROM "{table}" WHERE "{col}" LIKE ?',
                                ('%' + src + '%',)).fetchall()
            for rowid, raw in rows:
                new = json.dumps(convert_json(json.loads(raw), src, args.dst, args.sep))
                conn.execute(f'UPDATE "{table}" SET "{col}" = ? WHERE rowid = ?', (new, rowid))
            if rows:
                print(f'{table}.{col}: {len(rows)} (json)')
        conn.execute('DELETE FROM stats_cache')
        conn.execute("INSERT INTO photos_fts(photos_fts) VALUES('rebuild')")
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        with conn:
            n = conn.execute('DELETE FROM photos_vec').rowcount
        print(f'photos_vec: emptied {n} rows (run database.py --populate-vec)')
    except Exception as exc:  # sqlite-vec absent: the table cannot be touched
        print(f'photos_vec not changed: {exc}', file=sys.stderr)
    left = conn.execute('SELECT count(*) FROM photos WHERE path LIKE ?', (src + '/%',)).fetchone()[0]
    print('integrity:', conn.execute('PRAGMA integrity_check').fetchone()[0],
          '| foreign keys:', len(conn.execute('PRAGMA foreign_key_check').fetchall()), 'violations',
          '| photos left on old prefix:', left)


if __name__ == '__main__':
    main()
