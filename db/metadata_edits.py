"""Bounded review-field edit clocks for explicit sidecar conflict detection.

One current receipt per photo/account/field, not an edit history. Triggers cover
all SQL writers; local means the writer is unknown, never a guessed actor.
"""
from contextlib import contextmanager

REVIEW_FIELDS = ('star_rating', 'is_favorite', 'is_rejected', 'is_kept')


def create_review_edit_triggers(conn):
    now = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    for table, path, user in [('photos', 'path', "''"), ('user_preferences', 'photo_path', 'NEW.user_id')]:
        for field in REVIEW_FIELDS:
            values = f"NEW.{path}, {user}, '{field}', {now}, 'local'"
            update = ("changed_at=excluded.changed_at, source='local', source_path=NULL, source_at=NULL")
            statement = ("INSERT INTO photo_metadata_edits(photo_path,user_id,field,changed_at,source) "
                         f"VALUES ({values}) ON CONFLICT(photo_path,user_id,field) DO UPDATE SET {update};")
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_review_{table}_{field}_update
                AFTER UPDATE OF {field} ON {table} WHEN OLD.{field} IS NOT NEW.{field}
                BEGIN {statement} END""")
            if table == 'user_preferences':
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_review_{table}_{field}_insert
                    AFTER INSERT ON {table} WHEN COALESCE(NEW.{field},0) != 0
                    BEGIN {statement} END""")
                deleted_values = f"OLD.photo_path, OLD.user_id, '{field}', {now}, 'local'"
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_review_{table}_{field}_delete
                    AFTER DELETE ON {table} WHEN COALESCE(OLD.{field},0) != 0
                    AND EXISTS(SELECT 1 FROM photos WHERE path=OLD.photo_path)
                    BEGIN INSERT INTO photo_metadata_edits(photo_path,user_id,field,changed_at,source)
                    VALUES ({deleted_values}) ON CONFLICT(photo_path,user_id,field) DO UPDATE SET {update}; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS metadata_review_photo_delete AFTER DELETE ON photos
        BEGIN DELETE FROM photo_metadata_edits WHERE photo_path=OLD.path; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS metadata_review_photo_move AFTER UPDATE OF path ON photos
        BEGIN UPDATE photo_metadata_edits SET photo_path=NEW.path WHERE photo_path=OLD.path; END""")


def review_edit_state(conn, path, user_id):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_metadata_edits'").fetchone():
        return {}
    return {row['field']: dict(row) for row in conn.execute(
        'SELECT * FROM photo_metadata_edits WHERE photo_path=? AND user_id=?', (path, user_id or ''))}


def record_sidecar_receipt(conn, path, user_id, fields, sidecar, source_at):
    """Attribute actual changed fields; trigger clocks remain the local apply time."""
    conn.executemany("UPDATE photo_metadata_edits SET source='xmp',source_path=?,source_at=? "
                     'WHERE photo_path=? AND user_id=? AND field=?',
                     [(sidecar, source_at, path, user_id or '', field) for field in fields])


def viewer_review_preserved(table, field, *, per_user=False):
    """Destination edit receipts preserve explicit zeros; legacy policy stays intact."""
    path = f'{table}.photo_path' if per_user else f'{table}.path'
    owner = f'{table}.user_id' if per_user else "''"
    fields = ('is_kept', 'is_rejected') if field in ('is_kept', 'is_rejected') else (field,)
    clock = (f"EXISTS(SELECT 1 FROM main.photo_metadata_edits me WHERE me.photo_path={path} "
             f"AND me.user_id={owner} AND me.field IN ({','.join(repr(f) for f in fields)}))")
    legacy = ' OR '.join(f'COALESCE({table}.{f},0) != 0' for f in fields)
    return f'({clock} OR {legacy})'


@contextmanager
def viewer_review_sync(conn, table, *, new_photos=False):
    """Replicate values with their actual clocks, without minting export-time edits.

    TEMP snapshots live on the export connection. Trigger writes are restored
    inside the same savepoint; other connections never lose edit tracking.
    """
    per_user = table == 'user_preferences'
    scope = "user_id != ''" if per_user else "user_id = ''"
    path = 'photo_path' if per_user else 'path'
    match = f'd.{path}=s.{path}' + (' AND d.user_id=s.user_id' if per_user else '')
    owner = 's.user_id' if per_user else "''"
    columns = 'photo_path,user_id,field,changed_at,source,source_path,source_at'
    conn.execute('SAVEPOINT viewer_review_sync')
    try:
        if per_user:
            # Deleting preferences is an explicit reset too. Recreate its zero
            # baseline before merging; zero inserts do not create edit clocks.
            conn.execute("INSERT OR IGNORE INTO main.user_preferences(user_id,photo_path) "
                         "SELECT DISTINCT me.user_id,me.photo_path FROM main.photo_metadata_edits me "
                         "JOIN src.user_preferences sp ON sp.user_id=me.user_id AND sp.photo_path=me.photo_path "
                         "WHERE me.user_id != ''")
        conn.execute(f'CREATE TEMP TABLE viewer_saved_edits AS SELECT {columns} '
                     f'FROM main.photo_metadata_edits WHERE {scope}')
        conn.execute('CREATE TEMP TABLE viewer_source_edits(photo_path TEXT,user_id TEXT,field TEXT)')
        source_has_edits = conn.execute(
            "SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='photo_metadata_edits'").fetchone()
        source_columns = {row[1] for row in conn.execute(f'PRAGMA src.table_info({table})')}
        for field in REVIEW_FIELDS:
            if field not in source_columns:
                continue
            preserved = viewer_review_preserved('d', field, per_user=per_user)
            chosen = f'd.{path} IS NULL' if new_photos else f'(d.{path} IS NULL OR NOT {preserved})'
            conn.execute("INSERT INTO viewer_source_edits SELECT s." + path + f",{owner},? "
                         f'FROM src.{table} s LEFT JOIN main.{table} d ON {match} WHERE {chosen}', (field,))
            if per_user and source_has_edits:
                # A source-side preference deletion retains a reset clock but
                # no preference row. Its effective value is still zero.
                conn.execute('INSERT INTO viewer_source_edits SELECT se.photo_path,se.user_id,se.field '
                             'FROM src.photo_metadata_edits se '
                             'LEFT JOIN main.user_preferences d ON d.photo_path=se.photo_path AND d.user_id=se.user_id '
                             "WHERE se.user_id != '' AND se.field=? "
                             'AND NOT EXISTS(SELECT 1 FROM src.user_preferences sp '
                             'WHERE sp.photo_path=se.photo_path AND sp.user_id=se.user_id) '
                             f'AND (d.photo_path IS NULL OR NOT {preserved})', (field,))
        yield
        # Preserve every pre-existing receipt exactly, including zero resets.
        # Replication's UPDATE/INSERT triggers must not invent legacy edit time.
        conn.execute(f'DELETE FROM main.photo_metadata_edits WHERE {scope}')
        conn.execute(f'INSERT INTO main.photo_metadata_edits({columns}) SELECT {columns} FROM viewer_saved_edits')
        if source_has_edits:
            conn.execute(f'INSERT OR IGNORE INTO main.photo_metadata_edits({columns}) '
                         f"SELECT {','.join('se.' + c for c in columns.split(','))} FROM src.photo_metadata_edits se "
                         'JOIN viewer_source_edits choice USING(photo_path,user_id,field) '
                         'WHERE EXISTS(SELECT 1 FROM main.photos p WHERE p.path=se.photo_path)')
        conn.execute('DROP TABLE viewer_saved_edits')
        conn.execute('DROP TABLE viewer_source_edits')
        conn.execute('RELEASE viewer_review_sync')
    except BaseException:
        conn.execute('ROLLBACK TO viewer_review_sync')
        conn.execute('RELEASE viewer_review_sync')
        raise
