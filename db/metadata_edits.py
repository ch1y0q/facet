"""Bounded review-field edit clocks for explicit sidecar conflict detection.

One current receipt per photo/account/field, not an edit history. Triggers cover
all SQL writers; local means the writer is unknown, never a guessed actor.
"""
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
