"""Batch cache identities for already-authorized photo summaries."""

_CHUNK_SIZE = 300
_COLUMNS_SQL = 'PRAGMA table_info(photos)'


def _chunks(rows, path_key):
    paths = list(dict.fromkeys(row.get(path_key) for row in rows if row.get(path_key)))
    for start in range(0, len(paths), _CHUNK_SIZE):
        yield paths[start:start + _CHUNK_SIZE]


def _select_sql(paths):
    return 'SELECT path,preview_revision FROM photos WHERE path IN (' + ','.join('?' for _ in paths) + ')'


def _merge(rows, versions, path_key):
    for row in rows:
        version = versions.get(row.get(path_key))
        if version is not None:
            row['preview_revision'] = version


def attach_preview_versions(conn, rows, path_key='path'):
    if 'preview_revision' not in {row[1] for row in conn.execute(_COLUMNS_SQL)}:
        return
    versions = {}
    for paths in _chunks(rows, path_key):
        versions.update(conn.execute(_select_sql(paths), paths).fetchall())
    _merge(rows, versions, path_key)


async def attach_preview_versions_async(conn, rows, path_key='path'):
    cursor = await conn.execute(_COLUMNS_SQL)
    available = {row[1] for row in await cursor.fetchall()}
    await cursor.close()
    if 'preview_revision' not in available:
        return
    versions = {}
    for paths in _chunks(rows, path_key):
        cursor = await conn.execute(_select_sql(paths), paths)
        versions.update(await cursor.fetchall())
        await cursor.close()
    _merge(rows, versions, path_key)
