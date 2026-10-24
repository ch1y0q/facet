"""Path changes must not block maintenance or revive stale history."""
import sqlite3

import pytest

from db.organization_history import init_schema, record, snapshot
from db.schema import init_database


def test_renaming_a_photo_away_and_back_blocks_history_revert(edition_client, seed_photos_prefix):
    from api.database import get_db
    path = '/history-rename/a.jpg'
    moved = '/history-rename/b.jpg'
    seed_photos_prefix('/history-rename/', [dict(path=path, filename='a.jpg')])
    assert edition_client.put('/api/photo/gps', json=dict(path=path, gps_latitude=1, gps_longitude=2)).status_code == 200
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET path=? WHERE path=?', (moved, path))
        conn.execute('UPDATE photos SET path=? WHERE path=?', (path, moved))
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 409
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude FROM photos WHERE path=?', (path,)).fetchone()) == (1, 2)


@pytest.mark.parametrize('foreign_keys', [False, True])
def test_photo_path_changes_invalidate_revisions(tmp_path, foreign_keys):
    filename = str(tmp_path / 'history.db')
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        conn.execute(f'PRAGMA foreign_keys={int(foreign_keys)}')
        conn.execute("INSERT INTO photos(path) VALUES ('a')")
        before = snapshot(conn, 'gps', '', ['a'])
        conn.execute("UPDATE photos SET gps_latitude=1 WHERE path='a'")
        record(conn, 'alice', 'gps', '', before)
        original = snapshot(conn, 'gps', '', ['a'])['a']
        conn.execute("UPDATE photos SET path='b' WHERE path='a'")
        assert not conn.execute("SELECT 1 FROM organization_revisions WHERE path='a'").fetchone()
        moved = snapshot(conn, 'gps', '', ['b'])['b']
        assert moved['values'] == original['values']
        assert moved['revision'] > original['revision']
        conn.execute("UPDATE photos SET path='a' WHERE path='b'")
        assert snapshot(conn, 'gps', '', ['a'])['a']['revision'] > moved['revision']


def test_path_change_without_foreign_keys_invalidates_private_review(tmp_path):
    filename = str(tmp_path / 'history.db')
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute("INSERT INTO photos(path) VALUES ('a')")
        conn.execute("INSERT INTO user_preferences(user_id,photo_path,is_kept) VALUES ('alice','a',1)")
        original = snapshot(conn, 'review', 'alice', ['a'])['a']
        assert original['revision'] > 0
        conn.execute("UPDATE photos SET path='b' WHERE path='a'")
        conn.execute("UPDATE photos SET path='a' WHERE path='b'")
        restored = snapshot(conn, 'review', 'alice', ['a'])['a']
        assert restored['values'] == original['values']
        assert restored['revision'] != original['revision']


def _legacy_revisions(filename):
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        conn.execute("INSERT INTO photos(path) VALUES ('a')")
        before = snapshot(conn, 'gps', '', ['a'])
        conn.execute("UPDATE photos SET gps_latitude=1 WHERE path='a'")
        record(conn, 'alice', 'gps', '', before)
        rows = conn.execute('SELECT * FROM organization_revisions').fetchall()
        conn.execute('DROP TABLE organization_revisions')
        conn.execute('''CREATE TABLE organization_revisions (
            path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
            kind TEXT NOT NULL, scope TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY(path,kind,scope))''')
        conn.executemany('INSERT INTO organization_revisions VALUES (?,?,?,?)', rows)
        return rows, conn.execute('SELECT * FROM organization_history').fetchall()


def test_upgrade_preserves_revisions_history_and_is_idempotent(tmp_path):
    filename = str(tmp_path / 'legacy.db')
    revisions, entries = _legacy_revisions(filename)
    with sqlite3.connect(filename) as conn:
        clock = conn.execute('SELECT revision FROM organization_clock').fetchone()
    init_database(filename)
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        assert conn.execute('PRAGMA foreign_key_list(organization_revisions)').fetchone()[5] == 'CASCADE'
        assert conn.execute('SELECT * FROM organization_revisions').fetchall() == revisions
        assert conn.execute('SELECT * FROM organization_history').fetchall() == entries
        assert conn.execute('SELECT revision FROM organization_clock').fetchone() == clock
        conn.execute("UPDATE photos SET path='b' WHERE path='a'")
        assert conn.execute("SELECT min(revision) FROM organization_revisions WHERE path='b'").fetchone()[0] > clock[0]
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()


def test_upgrade_failure_rolls_back_revisions_and_triggers(tmp_path):
    filename = str(tmp_path / 'legacy.db')
    revisions, entries = _legacy_revisions(filename)
    with sqlite3.connect(filename) as conn:
        triggers = conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name GLOB 'organization_*' ORDER BY name").fetchall()
        conn.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK)
        with pytest.raises(sqlite3.DatabaseError), conn:
            init_schema(conn)
        conn.set_authorizer(None)
        assert conn.execute('PRAGMA foreign_key_list(organization_revisions)').fetchone()[5] == 'NO ACTION'
        assert conn.execute('SELECT * FROM organization_revisions').fetchall() == revisions
        assert conn.execute('SELECT * FROM organization_history').fetchall() == entries
        assert conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name GLOB 'organization_*' ORDER BY name").fetchall() == triggers


def test_upgrade_discards_only_orphaned_revision_cache(tmp_path):
    filename = str(tmp_path / 'legacy.db')
    revisions, entries = _legacy_revisions(filename)
    with sqlite3.connect(filename) as conn:
        conn.execute("INSERT INTO organization_revisions VALUES ('missing','gps','',100)")
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        assert conn.execute('SELECT * FROM organization_revisions').fetchall() == revisions
        assert conn.execute('SELECT * FROM organization_history').fetchall() == entries


def test_current_schema_startup_does_not_need_writer_lock(tmp_path):
    filename = str(tmp_path / 'history.db')
    init_database(filename)
    with sqlite3.connect(filename) as writer, sqlite3.connect(filename, timeout=0.01) as reader:
        writer.execute('BEGIN IMMEDIATE')
        init_schema(reader)
