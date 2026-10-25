"""Read-only import plans and exact review-edit conflict clocks on real SQLite."""
import json
import pytest
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET

from db.metadata_edits import review_edit_state
from db.schema import init_database
from processing.xmp_export import NS_XMP, NS_RDF, XmpRating, build_xmp
from processing.xmp_import import import_sidecars


def setup(tmp_path, rating=1):
    path = tmp_path / 'photo.jpg'
    db = tmp_path / 'test.db'
    init_database(str(db))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute('INSERT INTO photos(path,star_rating,scanned_at) VALUES (?,?,?)',
                 (str(path), rating, '2020-01-01 00:00:00'))
    conn.commit()
    return conn, path, db


def sidecar(path, *, rating=5, tags=(), gps=False, decision=False):
    packet = ET.fromstring(build_xmp(XmpRating(star_rating=rating, tags=list(tags), is_kept=decision,
                                              gps_manually_set=gps, gps_latitude=1, gps_longitude=2)))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}MetadataDate', '2021-01-01T00:00:00Z')
    filename = Path(str(path) + '.xmp')
    filename.write_bytes(ET.tostring(packet))
    return filename


def test_preview_changes_diagnostics_and_source_without_any_database_write(tmp_path):
    conn, path, db = setup(tmp_path)
    try:
        sidecar(path, tags=['new', 'a|hierarchy', 'bad,word'], gps=True)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before = db.read_bytes()
        writes = conn.total_changes
        result = import_sidecars(conn, str(path), dry_run=True)
        assert result['updated'] == 1
        assert result['dry_run'] is True
        plan = result['entries'][0]
        assert plan['changes']['star_rating'] == {'before': 1, 'after': 5}
        assert plan['changes']['keywords'] == {'added': ['new']}
        assert plan['changes']['gps']['after'] == [1, 2, 1]
        assert {d['reason'] for d in plan['diagnostics']} >= {'hierarchy_unsupported', 'invalid_keyword', 'untracked_legacy_edit'}
        assert plan['source']['metadata_date'] == '2021-01-01T00:00:00+00:00'
        assert conn.total_changes == writes
        assert db.read_bytes() == before
        assert not conn.in_transaction
        assert conn.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 1
        json.dumps(result)  # Preview is a CLI/API-ready JSON value.
    finally:
        conn.close()


def test_newer_manual_review_clock_blocks_old_packet_but_not_keyword_additions(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        sidecar(path, rating=5, tags=['external'])
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        conn.commit()
        preview = import_sidecars(conn, dry_run=True)
        assert preview['conflicts'] == 1
        assert preview['entries'][0]['changes'] == {'keywords': {'added': ['external']}}
        reason = next(d for d in preview['entries'][0]['diagnostics'] if d['reason'] == 'newer_local_edit')
        assert reason['fields'] == ['star_rating']
        assert reason['incoming']['star_rating'] == {'before': 3, 'after': 5}
        result = import_sidecars(conn)
        assert result['conflicts'] == 1
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 3
        assert review_edit_state(conn, str(path), '')['star_rating']['source'] == 'local'
        assert conn.execute('SELECT tag,source FROM photo_manual_tags').fetchone()[:] == ('external', 'xmp')
    finally:
        conn.close()


def test_explicit_review_override_records_exact_field_receipt_and_repeat_is_noop(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        filename = sidecar(path)
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        conn.commit()
        assert import_sidecars(conn, overwrite_review=True)['updated'] == 1
        receipt = review_edit_state(conn, str(path), '')['star_rating']
        assert receipt['source'] == 'xmp'
        assert receipt['source_path'] == str(filename)
        assert receipt['source_at'].startswith('2021-01-01')
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 5
        assert import_sidecars(conn)['unchanged'] == 1
        assert review_edit_state(conn, str(path), '')['star_rating'] == receipt
    finally:
        conn.close()


def test_apply_replans_after_an_intervening_manual_edit(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        sidecar(path)
        assert import_sidecars(conn, dry_run=True)['entries'][0]['changes']['star_rating']['after'] == 5
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        conn.commit()
        result = import_sidecars(conn)
        assert result['conflicts'] == 1
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 2
    finally:
        conn.close()


def test_selected_fields_do_not_import_review_or_gps_and_preview_does_not_commit_caller(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        sidecar(path, tags=['one'], gps=True)
        conn.execute('UPDATE photos SET caption=? WHERE path=?', ('pending', str(path)))
        result = import_sidecars(conn, fields=['keywords'], dry_run=True)
        assert conn.in_transaction
        assert result['entries'][0]['changes'] == {'keywords': {'added': ['one']}}
        conn.rollback()
        assert conn.execute('SELECT caption FROM photos').fetchone()[0] is None
        import_sidecars(conn, fields=['keywords'])
        row = conn.execute('SELECT star_rating,gps_manually_set FROM photos').fetchone()
        assert tuple(row) == (1, 0)
    finally:
        conn.close()


def test_per_user_clocks_and_visibility_are_isolated(tmp_path, monkeypatch):
    conn, path, _ = setup(tmp_path, rating=0)
    hidden = tmp_path / 'hidden.jpg'
    try:
        conn.execute('INSERT INTO photos(path) VALUES (?)', (str(hidden),))
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,?)',
                     ('alice', str(path), 3))
        conn.commit()
        sidecar(path)
        sidecar(hidden)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path=?', [str(path)]))
        alice = import_sidecars(conn, user_id='alice', dry_run=True)
        assert alice['conflicts'] == 1
        assert [e['path'] for e in alice['entries']] == [str(path)]
        assert import_sidecars(conn, user_id='bob')['updated'] == 1
        assert conn.execute('SELECT star_rating FROM user_preferences WHERE user_id=?', ('alice',)).fetchone()[0] == 3
        assert conn.execute('SELECT star_rating FROM user_preferences WHERE user_id=?', ('bob',)).fetchone()[0] == 5
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (str(path),)).fetchone()[0] == 0
        assert review_edit_state(conn, str(path), 'alice')['star_rating']['source'] == 'local'
        assert review_edit_state(conn, str(path), 'bob')['star_rating']['source'] == 'xmp'
        assert review_edit_state(conn, str(hidden), '') == {}
    finally:
        conn.close()


def test_edit_clocks_rollback_noop_delete_and_path_move(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        assert review_edit_state(conn, str(path), '')
        conn.rollback()
        assert review_edit_state(conn, str(path), '') == {}
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        conn.commit()
        clock = review_edit_state(conn, str(path), '')
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        assert review_edit_state(conn, str(path), '') == clock
        moved = str(path) + '.moved'
        conn.execute('UPDATE photos SET path=? WHERE path=?', (moved, str(path)))
        assert review_edit_state(conn, moved, '')['star_rating'] == {**clock['star_rating'], 'photo_path': moved}
        conn.execute('DELETE FROM photos WHERE path=?', (moved,))
        assert review_edit_state(conn, moved, '') == {}
    finally:
        conn.close()


def test_missing_malformed_and_manual_gps_are_explained(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        assert import_sidecars(conn, dry_run=True)['entries'][0]['diagnostics'] == [{'reason': 'missing_sidecar'}]
        filename = Path(str(path) + '.xmp')
        filename.write_text('broken xml')
        assert import_sidecars(conn, dry_run=True)['entries'][0]['diagnostics'] == [{'reason': 'unparseable_sidecar'}]
        sidecar(path, gps=True)
        conn.execute('UPDATE photos SET gps_latitude=7,gps_longitude=8,gps_manually_set=1 WHERE path=?', (str(path),))
        conn.commit()
        result = import_sidecars(conn, fields=['gps'], dry_run=True)
        assert result['entries'][0]['changes'] == {}
        assert result['entries'][0]['diagnostics'] == [{'field': 'gps', 'reason': 'manual_gps_protected'}]
    finally:
        conn.close()



def test_epoch_zero_metadata_date_never_falls_back_to_recent_file_mtime(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        filename = sidecar(path)
        packet = ET.parse(filename)
        packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}MetadataDate', '1970-01-01T00:00:00Z')
        packet.write(filename, encoding='utf-8')
        preview = import_sidecars(conn, dry_run=True)
        assert preview['entries'][0]['changes'] == {}
        assert preview['entries'][0]['source']['effective_at'].startswith('1970-01-01')
        assert preview['entries'][0]['source']['clock'] == 'metadata_date'
    finally:
        conn.close()


def test_cli_preview_opens_existing_database_readonly_without_schema_migration(tmp_path):
    import subprocess
    import sys
    conn, path, db = setup(tmp_path, rating=0)
    sidecar(path, tags=['external'])
    conn.execute('DROP TABLE photo_metadata_edits')
    conn.commit()
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
    before = db.read_bytes()
    result = subprocess.run([sys.executable, 'facet.py', '--db', str(db), '--import-sidecars', str(path),
                             '--dry-run', '--sidecar-fields', 'keywords'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert preview['dry_run'] is True
    assert preview['entries'][0]['changes'] == {'keywords': {'added': ['external']}}
    assert db.read_bytes() == before
    with sqlite3.connect(db) as check:
        assert not check.execute("SELECT 1 FROM sqlite_master WHERE name='photo_metadata_edits'").fetchone()
        assert check.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0



def test_explicit_override_also_bypasses_scan_gate_and_review_group_stays_atomic(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        sidecar(path, rating=5, decision=True)
        conn.execute('UPDATE photos SET star_rating=3,scanned_at=? WHERE path=?',
                     ('2099-01-01 00:00:00', str(path)))
        conn.commit()
        # Rejection/Keep and stars are one review group; never apply only the unconflicted half.
        result = import_sidecars(conn, dry_run=True)
        assert result['entries'][0]['changes'] == {}
        assert import_sidecars(conn, overwrite_review=True)['updated'] == 1
        assert tuple(conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos').fetchone()) == (5, 1, 0)
    finally:
        conn.close()


@pytest.mark.parametrize('per_user', [False, True])
def test_explicit_reset_clock_prevents_a_stale_sidecar_resurrecting_review(tmp_path, monkeypatch, per_user):
    conn, path, _ = setup(tmp_path, rating=0)
    try:
        sidecar(path)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: per_user)
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
            conn.execute('DELETE FROM user_preferences WHERE user_id=?', ('alice',))
        else:
            conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
            conn.execute('UPDATE photos SET star_rating=0 WHERE path=?', (str(path),))
        conn.commit()
        result = import_sidecars(conn, user_id='alice' if per_user else None)
        assert result['conflicts'] == 1
        assert result['updated'] == 0
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM user_preferences').fetchone()[0] == 0
    finally:
        conn.close()


def test_photo_deletion_cascades_preferences_without_recreating_edit_receipts(tmp_path):
    conn, path, _ = setup(tmp_path)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.commit()
        conn.execute('DELETE FROM photos WHERE path=?', (str(path),))
        conn.commit()
        assert conn.execute('SELECT COUNT(*) FROM photo_metadata_edits').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM user_preferences').fetchone()[0] == 0
    finally:
        conn.close()


def test_failed_apply_rolls_back_tags_and_releases_its_writer_transaction(tmp_path, monkeypatch):
    conn, path, db = setup(tmp_path, rating=0)
    try:
        sidecar(path, tags=['external'])
        def fail(*args, **kwargs):
            raise RuntimeError('simulated write failure')
        monkeypatch.setattr('processing.xmp_import.upsert_rating_state', fail)
        with pytest.raises(RuntimeError, match='simulated write failure'):
            import_sidecars(conn)
        assert not conn.in_transaction
        assert conn.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM photo_metadata_edits').fetchone()[0] == 0
        with sqlite3.connect(db, timeout=0.1) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.rollback()
    finally:
        conn.close()



def test_viewer_incremental_export_preserves_local_edit_clock_and_conflict(tmp_path):
    from db.maintenance import export_viewer_db
    conn, path, db = setup(tmp_path, rating=0)
    viewer = tmp_path / 'viewer.db'
    try:
        sidecar(path)
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            output.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
            output.commit()
            clock = review_edit_state(output, str(path), '')
            assert clock['star_rating']['source'] == 'local'
        conn.execute('UPDATE photos SET aggregate=8 WHERE path=?', (str(path),))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert review_edit_state(output, str(path), '') == clock
            result = import_sidecars(output)
            assert result['conflicts'] == 1
            assert output.execute('SELECT star_rating FROM photos').fetchone()[0] == 3
    finally:
        conn.close()


@pytest.mark.parametrize('rating', ['NaN', 'inf', 'not-a-rating'])
def test_invalid_review_value_is_reported_and_never_clears_existing_review(tmp_path, rating):
    conn, path, _ = setup(tmp_path)
    try:
        filename = sidecar(path, tags=['external'])
        packet = ET.parse(filename)
        packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}Rating', rating)
        packet.write(filename, encoding='utf-8')
        preview = import_sidecars(conn, dry_run=True)
        assert preview['entries'][0]['changes'] == {'keywords': {'added': ['external']}}
        assert {'field': 'review', 'reason': 'invalid_rating'} in preview['entries'][0]['diagnostics']
        import_sidecars(conn)
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.parametrize('per_user', [False, True])
@pytest.mark.parametrize('field', ['star_rating', 'is_favorite', 'is_rejected', 'is_kept'])
def test_viewer_incremental_preserves_explicit_zero_and_exact_clock(tmp_path, per_user, field):
    from db.maintenance import export_viewer_db
    conn, path, db = setup(tmp_path, rating=0)
    viewer = tmp_path / 'viewer.db'
    value = 3 if field == 'star_rating' else 1
    try:
        if per_user:
            conn.execute(f'INSERT INTO user_preferences(user_id,photo_path,{field}) VALUES (?,?,?)', ('alice', str(path), value))
        else:
            conn.execute(f'UPDATE photos SET {field}=? WHERE path=?', (value, str(path)))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        table = 'user_preferences' if per_user else 'photos'
        key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            output.execute(f'UPDATE {table} SET {field}=0 WHERE {key}', (str(path),))
            output.commit()
            clock = review_edit_state(output, str(path), 'alice' if per_user else '')
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert output.execute(f'SELECT {field} FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == 0
            assert review_edit_state(output, str(path), 'alice' if per_user else '') == clock
    finally:
        conn.close()


def test_viewer_incremental_preserves_deleted_preference_reset(tmp_path):
    from db.maintenance import export_viewer_db
    conn, path, db = setup(tmp_path, rating=0)
    viewer = tmp_path / 'viewer.db'
    try:
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            output.execute("DELETE FROM user_preferences WHERE user_id='alice'")
            output.commit()
            clock = review_edit_state(output, str(path), 'alice')
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert output.execute("SELECT star_rating FROM user_preferences WHERE user_id='alice'").fetchone()[0] == 0
            assert review_edit_state(output, str(path), 'alice') == clock
    finally:
        conn.close()


@pytest.mark.parametrize('per_user', [False, True])
@pytest.mark.parametrize('new_photo', [False, True])
def test_incremental_copies_source_receipts_with_selected_source_values(tmp_path, monkeypatch, per_user, new_photo):
    from db.maintenance import export_viewer_db
    from db.metadata_edits import record_sidecar_receipt
    conn, original, db = setup(tmp_path, rating=0)
    viewer = tmp_path / 'viewer.db'
    try:
        export_viewer_db(str(db), str(viewer), verbose=False)
        path = tmp_path / 'later.jpg' if new_photo else original
        if new_photo:
            conn.execute('INSERT INTO photos(path,scanned_at) VALUES (?,?)', (str(path), '2020-01-01'))
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        else:
            conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        scope = 'alice' if per_user else ''
        filename = sidecar(path)
        record_sidecar_receipt(conn, str(path), scope, ['star_rating'], str(filename), '2021-01-01T00:00:00+00:00')
        conn.commit()
        source_clock = review_edit_state(conn, str(path), scope)
        export_viewer_db(str(db), str(viewer), verbose=False)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: per_user)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path=?', [str(path)]))
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert review_edit_state(output, str(path), scope) == source_clock
            result = import_sidecars(output, str(path), user_id='alice' if per_user else None)
            assert result['conflicts'] == 1
            table = 'user_preferences' if per_user else 'photos'
            key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
            assert output.execute(f'SELECT star_rating FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == 3
    finally:
        conn.close()


def test_incremental_copies_source_deleted_preference_clock(tmp_path, monkeypatch):
    from db.maintenance import export_viewer_db
    conn, path, db = setup(tmp_path, rating=0)
    viewer = tmp_path / 'viewer.db'
    try:
        export_viewer_db(str(db), str(viewer), verbose=False)
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.execute("DELETE FROM user_preferences WHERE user_id='alice'")
        conn.commit()
        clock = review_edit_state(conn, str(path), 'alice')
        sidecar(path)
        export_viewer_db(str(db), str(viewer), verbose=False)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path=?', [str(path)]))
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert review_edit_state(output, str(path), 'alice') == clock
            assert import_sidecars(output, str(path), user_id='alice')['conflicts'] == 1
            assert output.execute("SELECT 1 FROM user_preferences WHERE user_id='alice'").fetchone() is None
    finally:
        conn.close()


def test_incremental_legacy_source_does_not_manufacture_clocks(tmp_path):
    from db.maintenance import export_viewer_db
    conn, _, db = setup(tmp_path, rating=0)
    viewer = tmp_path / 'viewer.db'
    path = str(tmp_path / 'legacy.jpg')
    try:
        export_viewer_db(str(db), str(viewer), verbose=False)
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'metadata_review_*'").fetchall():
            conn.execute('DROP TRIGGER "' + trigger.replace('"', '""') + '"')
        conn.execute('DROP TABLE photo_metadata_edits')
        conn.execute('INSERT INTO photos(path,star_rating) VALUES (?,3)', (path,))
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', path))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert output.execute('SELECT star_rating FROM photos WHERE path=?', (path,)).fetchone()[0] == 3
            assert review_edit_state(output, path, '') == {}
            assert review_edit_state(output, path, 'alice') == {}
    finally:
        conn.close()


def test_viewer_review_sync_failure_rolls_back_values_and_clocks(tmp_path):
    from db.metadata_edits import viewer_review_sync
    conn, path, db = setup(tmp_path, rating=1)
    source = tmp_path / 'source.db'
    init_database(str(source))
    try:
        with sqlite3.connect(source) as origin:
            origin.execute('INSERT INTO photos(path,star_rating) VALUES (?,3)', (str(path),))
        conn.execute('ATTACH DATABASE ? AS src', (str(source),))
        with pytest.raises(RuntimeError, match='late replication failure'):
            with viewer_review_sync(conn, 'photos'):
                conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
                raise RuntimeError('late replication failure')
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (str(path),)).fetchone()[0] == 1
        assert review_edit_state(conn, str(path), '') == {}
        assert not conn.in_transaction
        assert not conn.execute("SELECT 1 FROM sqlite_temp_master WHERE name LIKE 'viewer_%edits'").fetchone()
        with sqlite3.connect(db, timeout=0.1) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.rollback()
    finally:
        conn.close()
