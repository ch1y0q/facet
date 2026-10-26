"""Embedding-only cache invalidation uses actual transactional SQLite triggers."""
import sqlite3

import pytest

from api.change_token import close_change_token_sentinels, db_change_token
from db.schema import init_database


def revision(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as reader:
        row = reader.execute('SELECT revision FROM embedding_cache_revision WHERE id=1').fetchone()
        return row[0] if row else None


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'revision.db'
    init_database(str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO photos(path,clip_embedding) VALUES ('a',X'0102')")
    yield path
    close_change_token_sentinels()


def test_unrelated_commits_and_same_vectors_leave_embedding_token_current(database):
    first = revision(database)
    broad = db_change_token(database)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE photos SET star_rating=4,is_favorite=1,caption='new text',tags='new' WHERE path='a'")
        conn.execute("UPDATE photos SET clip_embedding=X'0102' WHERE path='a'")
    assert revision(database) == first
    assert db_change_token(database) != broad


@pytest.mark.parametrize('statement', [
    "UPDATE photos SET clip_embedding=X'0304' WHERE path='a'",
    "UPDATE photos SET clip_embedding=NULL WHERE path='a'",
    "UPDATE photos SET path='moved' WHERE path='a'",
    "DELETE FROM photos WHERE path='a'",
    "INSERT INTO photos(path,clip_embedding) VALUES ('b',X'0304')",
    "INSERT OR REPLACE INTO photos(path,clip_embedding) VALUES ('a',NULL)",
])
def test_every_vector_or_path_identity_change_invalidates(database, statement):
    first = revision(database)
    with sqlite3.connect(database) as conn:
        conn.execute(statement)
    assert revision(database) != first


def test_rolled_back_vector_change_never_invalidates(database):
    first = revision(database)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE photos SET clip_embedding=X'0304' WHERE path='a'")
        conn.rollback()
    assert revision(database) == first


def test_missing_revision_is_repaired_only_on_schema_initialization(database):
    first = revision(database)
    with sqlite3.connect(database) as conn:
        conn.execute('DELETE FROM embedding_cache_revision')
    assert revision(database) is None
    init_database(str(database), build_photo_indexes=False)
    assert revision(database) not in {None, first}
    assert revision(database) == revision(database)


def test_current_schema_reinitialization_does_not_wait_for_a_writer(database):
    from db.schema import init_database
    with sqlite3.connect(database) as writer:
        writer.execute('BEGIN IMMEDIATE')
        # An existing revision row must not cause unconditional INSERT OR IGNORE.
        init_database(str(database), build_photo_indexes=False)
        writer.rollback()


def test_in_place_backup_restore_cannot_alias_another_database_generation(database, tmp_path):
    before = revision(database)
    replacement = tmp_path / 'other.db'
    init_database(str(replacement))
    with sqlite3.connect(replacement) as other:
        other.execute("INSERT INTO photos(path,clip_embedding) VALUES ('b',X'0304')")
        other.commit()
        inode = database.stat().st_ino
        with sqlite3.connect(database) as target:
            other.backup(target)
    assert database.stat().st_ino == inode
    assert revision(database) != before
