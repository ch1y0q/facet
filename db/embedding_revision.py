"""Derived, database-local cache generation for photo paths and CLIP vectors.

There is no actor, path or edit authority in this singleton revision token. Changes
made by external SQLite writers are covered by the same transactional triggers.
"""

TRIGGER_NAMES = (
    'embedding_cache_photos_insert',
    'embedding_cache_photos_delete',
    'embedding_cache_photos_update',
)
_NEW_REVISION = 'lower(hex(randomblob(16)))'
_BUMP = f'UPDATE embedding_cache_revision SET revision={_NEW_REVISION} WHERE id=1'
_REVISION_LENGTH = 32
_HEX_DIGITS = frozenset('0123456789abcdef')


def is_valid_revision(value):
    """Whether ``value`` has the shape ``_NEW_REVISION`` writes: 32 lowercase hex digits."""
    return isinstance(value, str) and len(value) == _REVISION_LENGTH and _HEX_DIGITS.issuperset(value)


def init_schema(conn):
    from db.schema import EMBEDDING_CACHE_REVISION_COLUMNS, _build_create_table_sql
    conn.execute(_build_create_table_sql("embedding_cache_revision", EMBEDDING_CACHE_REVISION_COLUMNS))
    # Do not acquire a write lock on an already initialized schema.
    if not conn.execute('SELECT 1 FROM embedding_cache_revision WHERE id=1').fetchone():
        conn.execute(f'INSERT INTO embedding_cache_revision(id,revision) VALUES (1,{_NEW_REVISION})')
    # Every insert invalidates, including INSERT OR REPLACE replacing a vector
    # with NULL (SQLite may not run the implicit DELETE trigger in that case).
    conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAMES[0]}
        AFTER INSERT ON photos BEGIN
        {_BUMP}; END""")
    conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAMES[1]}
        AFTER DELETE ON photos WHEN OLD.clip_embedding IS NOT NULL BEGIN
        {_BUMP}; END""")
    conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {TRIGGER_NAMES[2]}
        AFTER UPDATE OF path,clip_embedding ON photos
        WHEN OLD.clip_embedding IS NOT NEW.clip_embedding
          OR (OLD.path IS NOT NEW.path AND NEW.clip_embedding IS NOT NULL) BEGIN
        {_BUMP}; END""")
