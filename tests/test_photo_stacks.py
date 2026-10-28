"""Manual stacks preserve photos and use caller-owned transactions."""
import sqlite3

import pytest

from db.schema import init_database
from db import stacks


@pytest.fixture
def conn(tmp_path):
    filename = str(tmp_path / 'stacks.db')
    init_database(filename)
    with sqlite3.connect(filename) as connection:
        connection.row_factory = sqlite3.Row
        connection.executemany('INSERT INTO photos(path,is_kept,is_rejected) VALUES (?,1,0)', [(p,) for p in ('a', 'b', 'c', 'd')])
        connection.commit()
        yield connection


def test_create_order_cover_owner_overlap_and_rollback(conn):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        result = stacks.create_stack(conn, 'alice', ['b', 'a'], 'a')
    stack = result['stack']
    assert stack['cover_path'] == 'a'
    assert stack['members'] == [{'path': 'b', 'position': 0}, {'path': 'a', 'position': 1}]
    assert result['undo']['entry_id'] > 0
    assert stacks.get_stack(conn, 'bob', stack['id']) is None
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        assert stacks.create_stack(conn, 'bob', ['a', 'b'], 'b')['stack']['id'] != stack['id']
    for paths in (['a', 'a'], ['a', 'c'], ['c', 'missing']):
        with pytest.raises(stacks.StackError), conn:
            conn.execute('BEGIN IMMEDIATE')
            stacks.create_stack(conn, 'alice', paths, paths[0])
    with pytest.raises(RuntimeError), conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.create_stack(conn, 'alice', ['c', 'd'], 'c')
        raise RuntimeError('rollback caller')
    assert stacks.get_stack_by_photo(conn, 'alice', 'c') is None
    assert [tuple(r) for r in conn.execute('SELECT is_kept,is_rejected FROM photos')] == [(1, 0)] * 4


def test_revision_remove_cover_dissolve_and_visibility(conn):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stack = stacks.create_stack(conn, 'alice', ['a', 'b', 'c'], 'a')['stack']
    partial = stacks.get_stack(conn, 'alice', stack['id'], visibility_sql='photos.path != ?', visibility_params=('a',))
    assert partial['cover_path'] == 'b' and not partial['editable']
    assert [m['path'] for m in partial['members']] == ['b', 'c']
    with pytest.raises(stacks.StackError), conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.update_stack(conn, 'alice', stack['id'], ['b', 'c'], 'b', stack['revision'], visibility_sql='photos.path != ?', visibility_params=('a',))
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        changed = stacks.update_stack(conn, 'alice', stack['id'], ['b', 'c'], None, stack['revision'])['stack']
    assert changed['cover_path'] == 'b' and changed['revision'] > stack['revision']
    with pytest.raises(stacks.StackError), conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.delete_stack(conn, 'alice', stack['id'], stack['revision'])
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        assert stacks.update_stack(conn, 'alice', stack['id'], ['c'], None, changed['revision'])['stack'] is None
    assert stacks.get_stack_by_photo(conn, 'alice', 'b') is None


def test_rescan_deletion_repair_and_path_move(conn):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stack = stacks.create_stack(conn, 'alice', ['a', 'b', 'c'], 'a')['stack']
    with conn:
        conn.execute("INSERT OR REPLACE INTO photos(path,is_kept) VALUES ('a',1)")
    assert stacks.get_stack(conn, 'alice', stack['id'])['cover_path'] == 'a'
    with conn:
        conn.execute("UPDATE photos SET path='renamed' WHERE path='a'")
    assert stacks.get_stack(conn, 'alice', stack['id'])['cover_path'] == 'renamed'
    with conn:
        conn.execute("DELETE FROM photos WHERE path='renamed'")
    repaired = stacks.get_stack(conn, 'alice', stack['id'])
    assert repaired['cover_path'] == 'b' and repaired['revision'] > stack['revision']
    with conn:
        conn.execute("DELETE FROM photos WHERE path='b'")
    assert stacks.get_stack(conn, 'alice', stack['id']) is None
    assert conn.execute('SELECT count(*) FROM photo_stack_members').fetchone()[0] == 0


def test_helpers_require_transaction(conn):
    with pytest.raises(RuntimeError):
        stacks.create_stack(conn, 'alice', ['a', 'b'], 'a')


def test_indexed_missing_original_and_original_bytes_unchanged(conn, tmp_path):
    original = tmp_path / 'original.jpg'
    original.write_bytes(b'original bytes not decoded by organization')
    missing = str(tmp_path / 'missing.jpg')
    with conn:
        conn.execute('INSERT INTO photos(path,is_kept) VALUES (?,1)', (str(original),))
        conn.execute('INSERT INTO photos(path,is_rejected) VALUES (?,1)', (missing,))
        stack = stacks.create_stack(conn, 'alice', [str(original), missing], missing)['stack']
    assert original.read_bytes() == b'original bytes not decoded by organization'
    assert stack['cover_path'] == missing
    assert conn.execute('SELECT is_rejected FROM photos WHERE path=?', (missing,)).fetchone()[0] == 1


def test_schema_constraints_and_ordered_index(conn):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stack = stacks.create_stack(conn, 'alice', ['a', 'b'], 'a')['stack']
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute('INSERT INTO photo_stack_members VALUES (?,?,?,?)', (stack['id'], 'alice', 'a', 10))
    conn.execute('PRAGMA foreign_keys=ON')
    with pytest.raises(sqlite3.IntegrityError), conn:
        conn.execute('INSERT INTO photo_stack_members VALUES (?,?,?,?)', (stack['id'], 'bob', 'c', 10))
    plan = ' '.join(str(tuple(r)) for r in conn.execute('EXPLAIN QUERY PLAN SELECT stack_id FROM photo_stack_members WHERE owner=? AND photo_path=?', ('alice', 'a')))
    assert 'INDEX' in plan and 'SCAN photo_stack_members' not in plan


def test_relink_reference_inventory_and_rewrite(conn):
    from db.relink import _references, _rewrite_refs
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stack = stacks.create_stack(conn, 'alice', ['a', 'b', 'c'], 'a')['stack']
        refs = _references(conn)
        assert ('photo_stacks', 'cover_path') in refs
        assert ('photo_stack_members', 'photo_path') in refs
        conn.execute("UPDATE photos SET path='renamed' WHERE path='a'")
        _rewrite_refs(conn, refs, 'a', 'renamed')
    changed = stacks.get_stack(conn, 'alice', stack['id'])
    assert changed['cover_path'] == 'renamed'
    assert [m['path'] for m in changed['members']] == ['renamed', 'b', 'c']
    assert changed['revision'] > stack['revision']


def test_viewer_export_excludes_private_stacks_and_paths(tmp_path):
    from db.maintenance import export_viewer_db
    source, dest = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    init_database(source)
    with sqlite3.connect(source) as connection:
        connection.executemany('INSERT INTO photos(path) VALUES (?)', [('a',), ('b',)])
        stacks.create_stack(connection, 'private-account', ['a', 'b'], 'a')
    export_viewer_db(source, dest, verbose=False)
    with sqlite3.connect(dest) as connection:
        assert not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('photo_stacks','photo_stack_members')").fetchall()
        assert not connection.execute("SELECT * FROM organization_revisions WHERE kind='stack'").fetchall()
    init_database(dest)
    with sqlite3.connect(dest) as connection:
        assert connection.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0
        connection.execute("UPDATE photos SET path='renamed' WHERE path='a'")
    export_viewer_db(source, dest, verbose=False)
    with sqlite3.connect(dest) as connection:
        assert connection.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0


def test_oversized_history_and_insert_failure_roll_back_all_effects(conn, monkeypatch):
    from db import organization_history
    before = [tuple(r) for r in conn.execute('SELECT * FROM photos')]
    monkeypatch.setattr(organization_history, 'MAX_BYTES', 20)
    with pytest.raises(ValueError), conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.create_stack(conn, 'alice', ['a', 'b'], 'a')
    assert conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM photo_stack_members').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == 0
    assert [tuple(r) for r in conn.execute('SELECT * FROM photos')] == before


def test_viewer_export_accepts_actual_released_pre_history_schema(tmp_path):
    from pathlib import Path
    from db.maintenance import export_viewer_db
    source, dest = str(tmp_path / 'released.db'), str(tmp_path / 'viewer.db')
    released_schema = Path(__file__).with_name('fixtures') / 'photo_stacks_v1_23_1_schema.sql'
    with sqlite3.connect(source) as connection:
        connection.executescript(released_schema.read_text())
        connection.execute("INSERT INTO photos(path,filename,star_rating) VALUES ('released.jpg','released.jpg',4)")
        assert connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'organization_%'").fetchall() == []
    before = Path(source).read_bytes()
    export_viewer_db(source, dest, verbose=False)
    assert Path(source).read_bytes() == before
    with sqlite3.connect(dest) as connection:
        assert connection.execute('SELECT path,star_rating FROM photos').fetchall() == [('released.jpg', 4)]
        assert connection.execute("SELECT name FROM sqlite_master WHERE name IN ('photo_stacks','photo_stack_members','organization_revisions')").fetchall() == []


def test_full_viewer_export_omits_private_stack_albums_but_incremental_keeps_viewer_albums(tmp_path):
    import json
    from db.maintenance import export_viewer_db

    source, destination = tmp_path / 'source.db', tmp_path / 'viewer.db'
    init_database(str(source))
    with sqlite3.connect(source) as connection:
        connection.executemany('INSERT INTO photos(path,filename) VALUES (?,?)', [('a.jpg', 'a.jpg'), ('b.jpg', 'b.jpg')])
        private = stacks.create_stack(connection, '', ['a.jpg', 'b.jpg'], 'a.jpg')['stack']
        ordinary = connection.execute("INSERT INTO albums(name,is_smart,smart_filter_json) VALUES ('ordinary',1,?)",
                                      (json.dumps({'min_score': 5}),)).lastrowid
        # More than one SQLite variable batch; explicit relation cleanup works
        # even though this backup connection does not enable foreign keys.
        for index in range(1001):
            album_id = connection.execute('INSERT INTO albums(name,is_smart,smart_filter_json) VALUES (?,1,?)',
                                          (f'private-{index}', json.dumps({'stack_id': private['id']}))).lastrowid
            connection.execute('INSERT INTO album_photos(album_id,photo_path) VALUES (?,?)', (album_id, 'a.jpg'))
            connection.execute('INSERT INTO album_client_picks(album_id,photo_path) VALUES (?,?)', (album_id, 'a.jpg'))
        connection.execute("INSERT INTO albums(name,is_smart,smart_filter_json) VALUES ('unreadable',1,'{broken')")
        connection.execute("INSERT INTO albums(name,is_smart,smart_filter_json) VALUES ('inert',1,?)", (json.dumps({'stack_id': ''}),))
    before = source.read_bytes()
    export_viewer_db(str(source), str(destination), verbose=False)
    assert source.read_bytes() == before
    with sqlite3.connect(destination) as connection:
        albums = connection.execute('SELECT id,name,smart_filter_json FROM albums ORDER BY id').fetchall()
        assert [row[1] for row in albums] == ['ordinary', 'inert']
        assert private['id'] not in repr(albums)
        assert connection.execute('SELECT count(*) FROM album_photos').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM album_client_picks').fetchone()[0] == 0
        assert connection.execute('SELECT smart_filter_json FROM albums WHERE id=?', (ordinary,)).fetchone()[0] == json.dumps({'min_score': 5})
    init_database(str(destination))
    with sqlite3.connect(destination) as connection:
        connection.execute('BEGIN IMMEDIATE')
        viewer_stack = stacks.create_stack(connection, '', ['a.jpg', 'b.jpg'], 'b.jpg')['stack']
        viewer_album = connection.execute("INSERT INTO albums(name,is_smart,smart_filter_json) VALUES ('viewer local',1,?)",
                                          (json.dumps({'stack_id': viewer_stack['id']}),)).lastrowid
    export_viewer_db(str(source), str(destination), verbose=False)
    with sqlite3.connect(destination) as connection:
        assert connection.execute('SELECT smart_filter_json FROM albums WHERE id=?', (viewer_album,)).fetchone()[0] == json.dumps({'stack_id': viewer_stack['id']})
        assert connection.execute('SELECT cover_path FROM photo_stacks WHERE id=?', (viewer_stack['id'],)).fetchone()[0] == 'b.jpg'
        assert connection.execute('SELECT name FROM albums ORDER BY id').fetchall() == [('ordinary',), ('inert',), ('viewer local',)]
