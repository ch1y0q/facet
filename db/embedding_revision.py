"""Derived, database-local cache generation for photo paths and CLIP vectors.

There is no actor, path or edit authority in this singleton revision token. Changes
made by external SQLite writers are covered by the same transactional triggers.
"""


def init_schema(conn):
    from db.schema import EMBEDDING_CACHE_REVISION_COLUMNS, _build_create_table_sql
    conn.execute(_build_create_table_sql("embedding_cache_revision", EMBEDDING_CACHE_REVISION_COLUMNS))
    # Do not acquire a write lock on an already initialized schema.
    if not conn.execute('SELECT 1 FROM embedding_cache_revision WHERE id=1').fetchone():
        conn.execute('INSERT INTO embedding_cache_revision(id,revision) VALUES (1,lower(hex(randomblob(16))))')
    # Every insert invalidates, including INSERT OR REPLACE replacing a vector
    # with NULL (SQLite may not run the implicit DELETE trigger in that case).
    conn.execute("""CREATE TRIGGER IF NOT EXISTS embedding_cache_photos_insert
        AFTER INSERT ON photos BEGIN
        UPDATE embedding_cache_revision SET revision=lower(hex(randomblob(16))) WHERE id=1; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS embedding_cache_photos_delete
        AFTER DELETE ON photos WHEN OLD.clip_embedding IS NOT NULL BEGIN
        UPDATE embedding_cache_revision SET revision=lower(hex(randomblob(16))) WHERE id=1; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS embedding_cache_photos_update
        AFTER UPDATE OF path,clip_embedding ON photos
        WHEN OLD.clip_embedding IS NOT NEW.clip_embedding
          OR (OLD.path IS NOT NEW.path AND NEW.clip_embedding IS NOT NULL) BEGIN
        UPDATE embedding_cache_revision SET revision=lower(hex(randomblob(16))) WHERE id=1; END""")
