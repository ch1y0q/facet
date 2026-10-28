"""Batch cache identities for already-authorized photo summaries."""


def _chunks(rows, path_key):
    paths = list(dict.fromkeys(row.get(path_key) for row in rows if row.get(path_key)))
    for start in range(0, len(paths), 300):
        yield paths[start:start + 300]


def attach_preview_versions(conn, rows, path_key='path'):
    versions = {}
    if 'preview_revision' not in {row[1] for row in conn.execute('PRAGMA table_info(photos)')}:
        return
    for paths in _chunks(rows, path_key):
        versions.update(conn.execute('SELECT path,preview_revision FROM photos WHERE path IN ('+
                                     ','.join('?' for _ in paths)+')', paths).fetchall())
    for row in rows:
        version = versions.get(row.get(path_key))
        if version is not None:
            row['preview_revision'] = version


async def attach_preview_versions_async(conn, rows, path_key='path'):
    versions = {}
    columns = await conn.execute('PRAGMA table_info(photos)')
    available = {row[1] for row in await columns.fetchall()}
    await columns.close()
    if 'preview_revision' not in available:
        return
    for paths in _chunks(rows, path_key):
        cursor = await conn.execute('SELECT path,preview_revision FROM photos WHERE path IN ('+
                                    ','.join('?' for _ in paths)+')', paths)
        versions.update(await cursor.fetchall())
        await cursor.close()
    for row in rows:
        version = versions.get(row.get(path_key))
        if version is not None:
            row['preview_revision'] = version
