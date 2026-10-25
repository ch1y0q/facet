"""Relinking is a reviewed database rewrite, never a file move or identity guess."""
import json
import os
import sqlite3
import stat
from pathlib import Path

import pytest
from PIL import Image

from db import relink
from db.connection import HAS_SQLITE_VEC, load_sqlite_vec
from db.schema import init_database
from utils import manual_face_frame


@pytest.fixture(autouse=True)
def reset_decoder_profiles():
    from utils import image_loading
    raw, hdr = image_loading._raw_decode_settings, image_loading._hdr_pq_tonemap_settings
    yield
    image_loading._raw_decode_settings, image_loading._hdr_pq_tonemap_settings = raw, hdr
    manual_face_frame.clear_cache()


@pytest.fixture
def library(tmp_path):
    root = tmp_path.resolve()
    (root / 'before').mkdir()
    (root / 'after').mkdir()
    old, new = str(root / 'before' / 'a.jpg'), str(root / 'after' / 'renamed.jpg')
    Image.new('RGB', (40, 30), 'blue').save(new)
    db = str(root / 'library.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('INSERT INTO photos(path,filename,image_width,image_height,thumbnail,star_rating,is_kept) '
                     'VALUES (?,?,?,?,?,?,?)', (old, 'a.jpg', 40, 30, b'thumbnail', 5, 1))
    config = {'viewer': {'scan_directories': [str(root)]}, 'users': {}}
    return db, old, new, config


def preview(library, mapping=None, config=None, user=None):
    db, old, new, default = library
    return relink.preview_relinks(db, mapping or [{'old': old, 'new': new}], config or default, user)


def apply(library, plan, **kwargs):
    return relink.apply_relinks(library[0], plan, library[3], acknowledge_plan=plan['plan_id'],
                               acknowledge_unverified_identity=True, **kwargs)


def test_preview_is_read_only_and_acknowledgment_is_required(library):
    db, old, new, config = library
    original = Path(new).read_bytes()
    plan = preview(library)
    assert plan['entries'][0]['identity'] == 'original_bytes_unknown'
    assert plan['entries'][0]['target_dimensions'] == [40, 30]
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == old
    with pytest.raises(ValueError, match='acknowledgment'):
        relink.apply_relinks(db, plan, config, acknowledge_plan='wrong', acknowledge_unverified_identity=True)
    with pytest.raises(ValueError, match='unknown original bytes'):
        relink.apply_relinks(db, plan, config, acknowledge_plan=plan['plan_id'])
    edited = json.loads(json.dumps(plan))
    edited['mapping'][0]['new'] = '/elsewhere.jpg'
    with pytest.raises(ValueError, match='acknowledgment'):
        apply(library, edited)
    assert Path(new).read_bytes() == original


def test_all_current_associations_survive_and_manual_marks_require_review(library):
    db, old, new, _ = library
    other = str(Path(new).with_name('other.jpg'))
    source = manual_face_frame.source_identity(new)
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('INSERT INTO photos(path,filename) VALUES (?,?)', (other, 'other.jpg'))
        conn.execute("INSERT INTO persons(id,name,representative_face_id,face_count) VALUES (3,'Ada',7,1)")
        conn.execute("INSERT INTO faces(id,photo_path,face_index,embedding,is_manual,manual_key,manual_source,"
                     "manual_width,manual_height,person_id,bbox_x1,bbox_y1,bbox_x2,bbox_y2) "
                     "VALUES (7,?,-1,X'',1,'stable-uuid',?,40,30,3,1,2,9,10)", (old, source))
        conn.execute('INSERT INTO photo_tags VALUES (?,?)', (old, 'ai-tag'))
        conn.execute("INSERT INTO photo_manual_tags(photo_path,tag,source,created_by) VALUES (?, 'manual','user','alice')", (old,))
        conn.execute("INSERT INTO comparisons(photo_a_path,photo_b_path,winner,user_id) VALUES (?,?,'a','alice')", (old, other))
        conn.execute('INSERT INTO learned_scores(photo_path,learned_score) VALUES (?,7)', (old,))
        conn.execute("INSERT INTO iqa_declined VALUES (?,'model','scan-stamp')", (old,))
        conn.execute("INSERT INTO photo_scoring_overrides(photo_path,category_override) VALUES (?,'portrait')", (old,))
        conn.execute("INSERT INTO photo_sequence_overrides(photo_path,sequence_kind,override_group_key) VALUES (?,'panorama',?)", (old, old))
        conn.execute("INSERT INTO user_preferences(user_id,photo_path,star_rating,is_kept) VALUES ('alice',?,4,1)", (old,))
        conn.execute("INSERT INTO rating_provenance(user_id,photo_path,star_rating) VALUES ('alice',?,4)", (old,))
        conn.execute("INSERT INTO albums(id,user_id,name,cover_photo_path) VALUES (2,'alice','Picks',?)", (old,))
        conn.execute('INSERT INTO album_photos(album_id,photo_path,position) VALUES (2,?,8)', (old,))
        conn.execute("INSERT INTO album_client_picks(album_id,photo_path,comment) VALUES (2,?,'private comment')", (old,))
        conn.execute('INSERT INTO face_reextract_snapshot(photo_path,person_id) VALUES (?,3)', (old,))
        conn.execute("INSERT INTO scan_runs(id,status) VALUES (1,'failed')")
        conn.execute('INSERT INTO scan_failures(scan_run_id,path) VALUES (1,?)', (old,))
        conn.execute('CREATE TABLE future_annotation(asset TEXT REFERENCES photos(path), note TEXT)')
        conn.execute("INSERT INTO future_annotation VALUES (?,'preserved dynamically')", (old,))
        for key, value in [('immich_synced_paths:global', json.dumps({old: {'rating': True}})),
                           ('immich_webhook_pending:global', json.dumps([old])),
                           ('auto_retrain_pending:alice', '9'), ('count_all', '123')]:
            conn.execute('INSERT INTO stats_cache(key,value) VALUES (?,?)', (key, value))
        rowid = conn.execute('SELECT rowid FROM photos WHERE path=?', (old,)).fetchone()[0]
        refs = relink._references(conn)
        expected = {(table, col): conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}"=?', (old,)).fetchone()[0]
                    for table, col in refs}
    plan = preview(library)
    assert apply(library, plan)['relinked'] == 1
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('SELECT rowid,filename,star_rating,is_kept,thumbnail FROM photos WHERE path=?', (new,)).fetchone() == (rowid, 'renamed.jpg', 5, 1, b'thumbnail')
        for (table, col), count in expected.items():
            if table == 'organization_revisions':
                # Existing path-change triggers invalidate private revision caches,
                # retaining fresh global revisions rather than rebinding old history.
                assert conn.execute('SELECT COUNT(*) FROM organization_revisions WHERE path=? AND scope=?', (new, 'alice')).fetchone()[0] == 0
                assert conn.execute('SELECT COUNT(*) FROM organization_revisions WHERE path=? AND scope=?', (new, '')).fetchone()[0] == 3
                assert conn.execute('SELECT COUNT(*) FROM organization_revisions WHERE path=?', (old,)).fetchone()[0] == 0
                continue
            assert conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}"=?', (new,)).fetchone()[0] == count
            assert conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}"=?', (old,)).fetchone()[0] == 0
        face = conn.execute('SELECT id,manual_key,manual_review_required,manual_source FROM faces').fetchone()
        assert face[:3] == (7, 'stable-uuid', 1)
        assert json.loads(face[3])['relink_unverified'] is True
        assert not manual_face_frame.is_current(new, face[3])
        assert conn.execute('SELECT representative_face_id FROM persons WHERE id=3').fetchone()[0] == 7
        assert conn.execute('SELECT override_group_key FROM photo_sequence_overrides').fetchone()[0] == old
        assert conn.execute('SELECT path FROM scan_failures').fetchone()[0] == old  # historical location
        assert old in conn.execute("SELECT value FROM stats_cache WHERE key='immich_synced_paths:global'").fetchone()[0]
        assert conn.execute("SELECT value FROM stats_cache WHERE key='auto_retrain_pending:alice'").fetchone()[0] == '9'
        assert conn.execute("SELECT 1 FROM stats_cache WHERE key='count_all'").fetchone() is None
    assert Path(new).is_file() and not Path(old).exists()


@pytest.mark.skipif(not HAS_SQLITE_VEC, reason='sqlite-vec unavailable')
def test_vector_path_is_rewritten_without_losing_embedding(library):
    import struct
    db, old, new, _ = library
    vector = struct.pack('4f', 1, 0, 0, 0)
    with sqlite3.connect(db) as conn:
        load_sqlite_vec(conn)
        conn.execute('CREATE VIRTUAL TABLE photos_vec USING vec0(path TEXT PRIMARY KEY, embedding float[4])')
        conn.execute('INSERT INTO photos_vec(path,embedding) VALUES (?,?)', (old, vector))
    apply(library, preview(library))
    with sqlite3.connect(db) as conn:
        load_sqlite_vec(conn)
        assert conn.execute('SELECT path,embedding FROM photos_vec').fetchall() == [(new, vector)]


@pytest.mark.parametrize('change', ['target_bytes', 'original_reappears', 'source_rating', 'policy'])
def test_stale_plan_refuses_without_database_writes(library, change):
    db, old, new, config = library
    plan = preview(library)
    if change == 'target_bytes':
        Image.new('RGB', (40, 30), 'red').save(new)
    elif change == 'original_reappears':
        Path(old).write_bytes(b'copy is back')
    elif change == 'source_rating':
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE photos SET star_rating=2')
    else:
        config['viewer']['scan_directories'].append(str(Path(new).parent))
    with pytest.raises(ValueError):
        apply(library, plan)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == old


def test_whole_batch_rolls_back_on_dependent_write_failure(library):
    db, old, _, _ = library
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO user_preferences(user_id,photo_path) VALUES ('alice',?)", (old,))
        conn.execute("CREATE TRIGGER refuse_relink BEFORE UPDATE ON user_preferences BEGIN SELECT RAISE(ABORT,'forced'); END")
    plan = preview(library)
    with pytest.raises(sqlite3.IntegrityError, match='forced'):
        apply(library, plan)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == old
        assert conn.execute('SELECT photo_path FROM user_preferences').fetchone()[0] == old


@pytest.mark.parametrize('bad', ['present_copy', 'duplicate_mapping', 'case_only', 'existing_photo', 'symlink', 'path_mapping', 'unknown_reference', 'wrong_shape'])
def test_ambiguous_or_unconfined_mapping_is_refused(library, bad):
    db, old, new, config = library
    mapping = [{'old': old, 'new': new}]
    if bad == 'present_copy':
        Path(old).write_bytes(Path(new).read_bytes())
    elif bad == 'duplicate_mapping':
        mapping *= 2
    elif bad == 'case_only':
        mapping[0]['new'] = old.upper()
    elif bad == 'existing_photo':
        with sqlite3.connect(db) as conn:
            conn.execute('INSERT INTO photos(path) VALUES (?)', (new,))
    elif bad == 'symlink':
        link = Path(new).with_name('link.jpg')
        link.symlink_to(new)
        mapping[0]['new'] = str(link)
    elif bad == 'path_mapping':
        config['viewer']['path_mapping'] = {'/other': str(Path(new).parent)}
    elif bad == 'unknown_reference':
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE unknown_annotation(photo_path TEXT)')
    else:
        Image.new('RGB', (41, 30), 'blue').save(new)
    with pytest.raises(ValueError):
        preview(library, mapping)


def test_user_visibility_must_be_unchanged_for_every_user(library):
    _, old, new, config = library
    root = str(Path(old).parent.parent)
    config['users'] = {'alice': {'directories': [root]}, 'bob': {'directories': [str(Path(new).parent)]}}
    with pytest.raises(ValueError, match='--user'):
        preview(library)
    with pytest.raises(ValueError, match='visibility boundary'):
        preview(library, user='alice')
    with pytest.raises(ValueError, match='visibility boundary'):
        preview(library, user='bob')
    config['users']['bob']['directories'] = [root]
    plan = preview(library, user='alice')
    assert plan['policy']['user'] == 'alice'
    assert apply(library, plan, user='alice')['relinked'] == 1


def test_explicit_full_name_sidecar_survives_relink_and_double_extension_is_refused(library):
    db, old, new, _ = library
    old_sidecar, new_sidecar = old + '.xmp', new + '.xmp'
    Path(new_sidecar).write_text('<xmp>portable data</xmp>')
    entry = {'old': old, 'new': new, 'companions': [
        {'old': old_sidecar, 'new': new_sidecar, 'kind': 'sidecar_full'}]}
    with pytest.raises(ValueError, match='explicit companion'):
        preview(library)
    before = Path(new_sidecar).read_bytes()
    plan = preview(library, [entry])
    assert apply(library, plan)['relinked'] == 1
    assert Path(new_sidecar).read_bytes() == before
    # IMG.CR2.xmp is simultaneously full-name for IMG.CR2 and basename for
    # IMG.CR2.jpg. Explicitly naming one owner cannot erase the other claim.
    photo = str(Path(old).with_name('IMG.CR2'))
    sibling = photo + '.jpg'
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(photo,), (sibling,)])
    entry = {'old': photo, 'new': str(Path(new).with_name('IMG.CR2')), 'companions': [
        {'old': photo + '.xmp', 'new': str(Path(new).with_name('IMG.CR2.xmp')), 'kind': 'sidecar_full'}]}
    with pytest.raises(ValueError, match='Ambiguous sidecar'):
        preview(library, [entry])


def test_basename_case_collision_is_refused(library):
    db, old, new, _ = library
    sibling = str(Path(old).with_name('A.JPG'))
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO photos(path) VALUES (?)', (sibling,))
    entry = {'old': old, 'new': new, 'companions': [
        {'old': str(Path(old).with_suffix('.xmp')), 'new': str(Path(new).with_suffix('.xmp')), 'kind': 'sidecar_basename'}]}
    with pytest.raises(ValueError, match='case/Unicode'):
        preview(library, [entry])


def test_explicit_raw_companion_keeps_culling_relationship_without_moving_files(library):
    _, old, new, _ = library
    raw_old, raw_new = str(Path(old).with_suffix('.CR2')), str(Path(new).with_suffix('.CR2'))
    Path(raw_new).write_bytes(b'generated companion fixture; no RAW decoder invoked')
    with pytest.raises(ValueError, match='explicit companion'):
        preview(library)
    entry = {'old': old, 'new': new, 'companions': [{'old': raw_old, 'new': raw_new, 'kind': 'raw'}]}
    receipt = preview(library, [entry])
    before = Path(raw_new).read_bytes()
    apply(library, receipt)
    assert Path(raw_new).read_bytes() == before
    assert not Path(raw_old).exists()
    # Same exact directory/stem contract used by find_companion_raw; no new
    # ownership inference or on-disk rename was performed by the relinker.
    assert Path(raw_new).with_suffix('') == Path(new).with_suffix('')


def test_copied_or_hardlinked_destinations_are_refused(library):
    db, old, new, _ = library
    old_two, new_two = str(Path(old).with_name('b.jpg')), str(Path(new).with_name('b.jpg'))
    Path(new_two).write_bytes(Path(new).read_bytes())
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO photos(path,filename) VALUES (?,?)', (old_two, 'b.jpg'))
    mapping = [{'old': old, 'new': new}, {'old': old_two, 'new': new_two}]
    with pytest.raises(ValueError, match='Duplicate/copied'):
        preview(library, mapping)
    Path(new_two).unlink()
    Path(new_two).hardlink_to(new)
    with pytest.raises(ValueError, match='Duplicate/copied'):
        preview(library, mapping)


@pytest.mark.parametrize('boundary', ['outside', 'empty_roots', 'blank_root', 'missing_parent', 'missing_root'])
def test_missing_or_unconfined_roots_fail_closed(library, boundary):
    _, old, new, config = library
    if boundary == 'outside':
        config['viewer']['scan_directories'] = [str(Path(old).parent)]
    elif boundary == 'empty_roots':
        config['viewer']['scan_directories'] = []
    elif boundary == 'blank_root':
        config['viewer']['scan_directories'] = ['']
    elif boundary == 'missing_root':
        config['viewer']['scan_directories'] = [str(Path(old).parent / 'offline')]
    else:
        Path(old).parent.rmdir()
    with pytest.raises(ValueError):
        preview(library)
    assert Path(new).is_file()


def test_changed_annotation_invalidates_review_plan(library):
    db, old, _, _ = library
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES (?,'before','user')", (old,))
    plan = preview(library)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE photo_manual_tags SET tag='after'")
    with pytest.raises(ValueError, match='stale'):
        apply(library, plan)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT photo_path,tag FROM photo_manual_tags').fetchone() == (old, 'after')


def test_cli_defaults_to_preview_and_applies_only_exact_saved_plan(library, tmp_path, capsys):
    db, old, new, config = library
    mapping_file = tmp_path / 'mapping.json'
    config_file = tmp_path / 'config.json'
    plan_file = tmp_path / 'review-plan.json'
    mapping_file.write_text(json.dumps([{'old': old, 'new': new}]))
    config_file.write_text(json.dumps(config))
    relink.main(['--db', db, '--config', str(config_file), '--mapping', str(mapping_file), '--plan-out', str(plan_file)])
    plan = json.loads(plan_file.read_text())
    if os.name == 'posix':
        assert stat.S_IMODE(plan_file.stat().st_mode) == 0o600
    assert json.loads(capsys.readouterr().out)['plan_id'] == plan['plan_id']
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == old
    # The plan file cannot silently replace a prior reviewed artifact.
    with pytest.raises(SystemExit) as error:
        relink.main(['--db', db, '--config', str(config_file), '--mapping', str(mapping_file), '--plan-out', str(plan_file)])
    assert error.value.code == 1
    capsys.readouterr()
    relink.main(['--db', db, '--config', str(config_file), '--apply-plan', str(plan_file),
                 '--ack-plan', plan['plan_id'], '--acknowledge-unverified-identity'])
    assert json.loads(capsys.readouterr().out)['relinked'] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == new


@pytest.mark.parametrize('limit', ['MAX_PHOTOS', 'MAX_FILES', 'MAX_FILE_BYTES', 'MAX_TOTAL_BYTES', 'MAX_PLAN_BYTES'])
def test_work_limits_refuse_without_changing_database(library, monkeypatch, limit):
    monkeypatch.setattr(relink, limit, 0)
    with pytest.raises(ValueError):
        preview(library)
    with sqlite3.connect(library[0]) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == library[1]


def test_atomic_database_replacement_invalidates_review_plan(library):
    db, old, _, _ = library
    plan = preview(library)
    replacement = str(Path(db).with_name('replacement.db'))
    with sqlite3.connect(db) as source, sqlite3.connect(replacement) as target:
        source.backup(target)
    Path(replacement).replace(db)
    with pytest.raises(ValueError, match='stale'):
        apply(library, plan)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == old


def test_two_photo_batch_preserves_comparison_endpoints(library):
    db, old, new, _ = library
    old_two, new_two = str(Path(old).with_name('b.jpg')), str(Path(new).with_name('b.jpg'))
    Image.new('RGB', (40, 30), 'red').save(new_two)
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO photos(path,filename) VALUES (?,?)', (old_two, 'b.jpg'))
        conn.execute("INSERT INTO comparisons(photo_a_path,photo_b_path,winner) VALUES (?,?,'a')", (old, old_two))
    plan = preview(library, [{'old': old, 'new': new}, {'old': old_two, 'new': new_two}])
    assert apply(library, plan)['relinked'] == 2
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT photo_a_path,photo_b_path FROM comparisons').fetchone() == (new, new_two)
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_unknown_nonstandard_column_also_fails_closed(library):
    db, old, _, _ = library
    with sqlite3.connect(db) as conn:
        conn.execute('ALTER TABLE photos ADD COLUMN archive_ref TEXT')
        conn.execute('UPDATE photos SET archive_ref=?', (old,))
    with pytest.raises(ValueError, match='Unregistered schema column'):
        preview(library)


def test_unicode_normalization_aliases_are_not_guessed(library):
    db, old, new, _ = library
    first = str(Path(old).with_name('caf\u00e9.jpg'))
    second = str(Path(old).with_name('cafe\u0301.jpg'))
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(first,), (second,)])
    with pytest.raises(ValueError, match='case/Unicode'):
        preview(library, [{'old': first, 'new': new}])


@pytest.mark.parametrize('suffix', ['.facet.xmp', '.FACET.XMP'])
def test_unlisted_destination_facet_sidecar_is_refused(library, suffix):
    db, old, new, _ = library
    packet = Path(new + suffix)
    packet.write_text('<xmp>stale decisions for another photo</xmp>')
    before = packet.read_bytes()
    with pytest.raises(ValueError, match='explicit companion'):
        preview(library)
    assert packet.read_bytes() == before
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchone()[0] == old


def test_explicit_facet_sidecar_mapping_preserves_bytes(library):
    _, old, new, _ = library
    old_packet, new_packet = old + '.facet.xmp', new + '.facet.xmp'
    Path(new_packet).write_text('<xmp>explicitly identified fallback</xmp>')
    before = Path(new_packet).read_bytes()
    plan = preview(library, [{'old': old, 'new': new, 'companions': [
        {'old': old_packet, 'new': new_packet, 'kind': 'sidecar_facet'}]}])
    assert apply(library, plan)['relinked'] == 1
    assert Path(new_packet).read_bytes() == before


@pytest.mark.parametrize('sibling_name', ['IMG.CR2.facet.jpg', 'IMG.CR2.FACET.JPG'])
def test_facet_sidecar_claim_collides_with_double_extension_basename(library, sibling_name):
    db, old, new, _ = library
    photo = str(Path(old).with_name('IMG.CR2'))
    sibling = str(Path(old).with_name(sibling_name))
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(photo,), (sibling,)])
    entry = {'old': photo, 'new': str(Path(new).with_name('IMG.CR2')), 'companions': [
        {'old': photo + '.facet.xmp', 'new': str(Path(new).with_name('IMG.CR2.facet.xmp')),
         'kind': 'sidecar_facet'}]}
    with pytest.raises(ValueError, match='Ambiguous sidecar'):
        preview(library, [entry])


def test_empty_readable_old_parent_does_not_claim_mount_verification(library):
    # An empty readable directory can be a normal post-move directory OR an
    # unmounted mount point. Filesystem existence cannot distinguish the two.
    assert list(Path(library[1]).parent.iterdir()) == []
    plan = preview(library)
    assert plan['source_mount_status'].startswith('not_verified;')
    assert plan['entries'][0]['identity'] == 'original_bytes_unknown'


def test_organization_history_keeps_historical_paths_and_invalidates_revisions(library, monkeypatch):
    from contextlib import contextmanager
    from fastapi import HTTPException, Response
    from api.auth import CurrentUser
    from api.routers import organization_history as history_api
    from db.organization_history import record, snapshot

    db, old, new, _ = library
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        before = snapshot(conn, 'review', '', [old])
        conn.execute('UPDATE photos SET star_rating=4 WHERE path=?', (old,))
        record(conn, 'alice', 'review', '', before)
        history = conn.execute('SELECT * FROM organization_history').fetchall()
        clock = conn.execute('SELECT revision FROM organization_clock').fetchone()[0]
        refs = relink._references(conn)
        assert ('organization_revisions', 'path') in refs
        assert all(table not in {'organization_clock', 'organization_history'} for table, _column in refs)

    @contextmanager
    def database():
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    monkeypatch.setattr(history_api, 'get_db', database)
    user = CurrentUser(user_id='alice', edition_authenticated=True)
    entry_id = history[0][0]
    assert [entry['id'] for entry in history_api.list_history(Response(), user)['entries']] == [entry_id]
    apply(library, preview(library))
    assert history_api.list_history(Response(), user)['entries'] == []
    with pytest.raises(HTTPException) as refused:
        history_api.revert_history(entry_id, Response(), user)
    assert refused.value.status_code == 404
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM organization_history').fetchall() == history
        assert json.loads(history[0][5])[0]['path'] == old
        assert conn.execute('SELECT revision FROM organization_clock').fetchone()[0] > clock
        assert conn.execute('SELECT 1 FROM organization_revisions WHERE path=?', (old,)).fetchone() is None
        assert conn.execute('SELECT 1 FROM organization_revisions WHERE path=?', (new,)).fetchone() is not None
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_unknown_organization_history_columns_still_require_review(library):
    with sqlite3.connect(library[0]) as conn:
        conn.execute('ALTER TABLE organization_history ADD COLUMN future_field TEXT')
    with pytest.raises(ValueError, match='Unregistered schema column in organization_history'):
        preview(library)


@pytest.mark.parametrize('variant', ['exact', 'case', 'unicode'])
def test_indexed_raw_jpeg_pair_relinks_as_two_top_level_entries(library, monkeypatch, variant):
    db, old, new, config = library
    if variant == 'unicode':
        destination = str(Path(new).with_name('réponse.jpg'))
        Path(new).rename(destination)
        new = destination
        library = (db, old, new, config)
    old_raw, new_raw = str(Path(old).with_suffix('.cr2')), str(Path(new).with_suffix('.cr2'))
    if variant == 'case':
        old_raw = str(Path(old_raw).with_name(Path(old_raw).name.upper()))
        new_raw = str(Path(new_raw).with_name(Path(new_raw).name.upper()))
    elif variant == 'unicode':
        import unicodedata
        new_raw = unicodedata.normalize('NFD', new_raw)
    Path(new_raw).write_bytes(b'indexed-raw-target')
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO photos(path,filename,image_width,image_height,star_rating) VALUES (?,?,40,30,3)', (old_raw, Path(old_raw).name))
    # Exercise real mapping/DB/file receipts without claiming a synthetic RAW decode.
    real_identity = manual_face_frame.source_identity
    monkeypatch.setattr(manual_face_frame, 'source_identity', lambda path: real_identity(new if path == new_raw else path))
    mapping = [{'old': old, 'new': new}, {'old': old_raw, 'new': new_raw}]
    plan = preview(library, mapping)
    assert apply(library, plan)['relinked'] == 2
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path,star_rating FROM photos ORDER BY path').fetchall() == sorted([(new, 5), (new_raw, 3)])
    assert Path(new_raw).read_bytes() == b'indexed-raw-target'


def test_fts_shadow_inventory_does_not_need_sqlite_337_table_list(library):
    db, _, _, _ = library
    with sqlite3.connect(db) as conn:
        class OlderSQLite:
            def execute(self, sql, parameters=()):
                if sql.lower().strip() == 'pragma table_list':
                    return iter(())
                return conn.execute(sql, parameters)
        assert any(row[0] == 'photos_fts_data' for row in conn.execute("SELECT name FROM sqlite_master"))
        refs = relink._references(OlderSQLite())
        assert ('faces', 'photo_path') in refs


def test_final_file_recheck_failure_rolls_back_all_relinked_rows(library, monkeypatch):
    db, old, new, _ = library
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES ('alice',?,4)", (old,))
    plan = preview(library)
    real = relink._file_receipt
    calls = []
    def changed_after_rebuild(*args):
        calls.append(1)
        if len(calls) == 2:
            Path(args[1]).write_bytes(b'changed immediately before final receipt')
        return real(*args)
    monkeypatch.setattr(relink, '_file_receipt', changed_after_rebuild)
    with pytest.raises(ValueError, match='file changed before commit'):
        apply(library, plan)
    assert len(calls) == 2  # First in-transaction rebuild passed; final check refused.
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT path FROM photos').fetchall() == [(old,)]
        assert conn.execute('SELECT photo_path,star_rating FROM user_preferences').fetchall() == [(old, 4)]
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    assert Path(new).is_file()


@pytest.mark.parametrize('case,reason', [
    ('multiple_raw', 'Multiple possible RAW'),
    ('indexed_raw', 'Indexed companions'),
    ('registered_companion_destination', 'Companion destination'),
    ('unknown_kind', 'Unknown explicit companion kind'),
    ('duplicate_companion', 'companion was supplied twice'),
    ('hardlinked_companion', 'Duplicate/copied destinations'),
])
def test_companion_refusals_are_explicit_and_leave_rows_unchanged(library, case, reason):
    db, old, new, _ = library
    old_raw, new_raw = str(Path(old).with_suffix('.cr2')), str(Path(new).with_suffix('.cr2'))
    companion = {'old': old_raw, 'new': new_raw, 'kind': 'raw'}
    entry = {'old': old, 'new': new, 'companions': [companion]}
    if case == 'hardlinked_companion':
        os.link(new, new_raw)
    else:
        Path(new_raw).write_bytes(b'raw-target')
    if case == 'multiple_raw':
        Path(new).with_suffix('.nef').write_bytes(b'second-raw')
    elif case == 'indexed_raw':
        with sqlite3.connect(db) as conn:
            conn.execute('INSERT INTO photos(path) VALUES (?)', (old_raw,))
    elif case == 'registered_companion_destination':
        with sqlite3.connect(db) as conn:
            conn.execute('INSERT INTO photos(path) VALUES (?)', (new_raw,))
    elif case == 'unknown_kind':
        companion['kind'] = 'guess'
    elif case == 'duplicate_companion':
        entry['companions'].append(dict(companion))
    with sqlite3.connect(db) as conn:
        before = conn.execute('SELECT * FROM photos ORDER BY path').fetchall()
    with pytest.raises(ValueError, match=reason):
        preview(library, [entry])
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM photos ORDER BY path').fetchall() == before


def test_database_cli_relink_entrypoint_previews_and_requires_normal_acknowledgment(library, tmp_path):
    import subprocess
    import sys
    db, old, new, config = library
    config_file = tmp_path / 'config.json'
    mapping_file = tmp_path / 'mapping.json'
    plan_file = tmp_path / 'plan.json'
    config_file.write_text(json.dumps(config))
    mapping_file.write_text(json.dumps([{'old': old, 'new': new}]))
    base = [sys.executable, 'database.py', '--relink-photos', '--db', db, '--config', str(config_file)]
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([*base, '--mapping', str(mapping_file), '--plan-out', str(plan_file)], cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    refused = subprocess.run([*base, '--apply-plan', str(plan_file)], cwd=root, capture_output=True, text=True, timeout=30)
    assert refused.returncode == 1
    assert 'acknowledgment' in refused.stderr
    applied = subprocess.run([*base, '--apply-plan', str(plan_file), '--ack-plan', plan['plan_id'], '--acknowledge-unverified-identity'], cwd=root, capture_output=True, text=True, timeout=30)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)['relinked'] == 1
