"""Real CLI field authority, independent override flags and transactional effects."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from xml.etree import ElementTree as ET

import pytest

from db.schema import init_database
from processing.xmp_export import NS_RDF, NS_XMP, XmpRating, build_xmp


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / 'visible'
    folder.mkdir()
    photo = folder / 'photo.jpg'
    photo.write_bytes(b'disposable original image')
    packet = ET.fromstring(build_xmp(XmpRating(star_rating=0, is_rejected=True,
        tags=['external'], gps_manually_set=True, gps_latitude=1, gps_longitude=2)))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}MetadataDate', '2021-01-01T00:00:00Z')
    sidecar = Path(str(photo) + '.xmp')
    sidecar.write_bytes(ET.tostring(packet, encoding='utf-8'))
    db = tmp_path / 'library.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO photos(path,scanned_at,star_rating,is_favorite,is_rejected,is_kept,'
                     'gps_latitude,gps_longitude,gps_manually_set) VALUES (?,?,?,?,?,?,?,?,?)',
                     (str(photo), '2020-01-01', 0, 0, 0, 0, 10, 20, 1))
        conn.execute('UPDATE photos SET star_rating=3,is_favorite=1,is_kept=1 WHERE path=?', (str(photo),))
        for user in ('alice', 'bob'):
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating,is_favorite,is_rejected,is_kept) '
                         'VALUES (?,?,3,1,0,1)', (user, str(photo)))
    config = tmp_path / 'scoring_config.json'
    config.write_text(json.dumps({'users': {'alice': {'directories': [str(folder)]},
                                          'bob': {'directories': [str(tmp_path / 'hidden')]}}}), encoding='utf-8')
    secret = tmp_path / '.facet_secret'
    secret.write_text(secrets.token_hex(32) + '\n', encoding='utf-8')
    secret.chmod(0o600)
    env = {**os.environ, 'FACET_CONFIG': str(config)}
    env.pop('FACET_JWT_SECRET', None)
    env.pop('FACET_NO_CONFIG_MIGRATION', None)
    return db, photo, sidecar, config, secret, env


def run_import(library, user, fields, *flags):
    db, photo, _, _, _, env = library
    command = [sys.executable, 'facet.py', '--db', str(db), '--import-sidecars', str(photo),
               '--sidecar-fields', fields, *flags]
    if user:
        command += ['--user', user]
    return subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=30)


def snapshot(db):
    with sqlite3.connect(db) as conn:
        return {table: conn.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()
                for table in ('photos', 'user_preferences', 'photo_metadata_edits', 'photo_manual_tags')}


def review(db, user):
    with sqlite3.connect(db) as conn:
        if user:
            row = conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM user_preferences WHERE user_id=?',
                               (user,)).fetchone()
        else:
            row = conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM photos').fetchone()
        return row


@pytest.mark.parametrize('user', [None, 'alice'])
@pytest.mark.parametrize('fields,flags,gps_applied,review_applied', [
    ('gps', (), False, False),
    ('gps', ('--overwrite-sidecar-review',), False, False),
    ('gps', ('--overwrite-manual-gps',), True, False),
    ('keywords', ('--overwrite-manual-gps', '--overwrite-sidecar-review'), False, False),
    ('gps,keywords', ('--overwrite-manual-gps', '--overwrite-sidecar-review'), True, False),
    ('review', ('--overwrite-manual-gps',), False, False),
    ('review', ('--overwrite-manual-gps', '--overwrite-sidecar-review'), False, True),
])
def test_cli_selected_fields_and_override_flags_preserve_authority(library, user, fields, flags, gps_applied, review_applied):
    db, photo, sidecar, config, secret, _ = library
    selected = set(fields.split(','))
    before = snapshot(db)
    bytes_before = {path: path.read_bytes() for path in (db, photo, sidecar, config, secret)}
    preview = run_import(library, user, fields, *flags, '--dry-run')
    assert preview.returncode == 0, preview.stderr
    plan = json.loads(preview.stdout)
    entry = plan['entries'][0]
    expected = {}
    if gps_applied:
        expected['gps'] = {'before': [10, 20, 1], 'after': [1, 2, 1]}
    if 'keywords' in selected:
        expected['keywords'] = {'added': ['external']}
    if review_applied:
        expected.update({field: {'before': old, 'after': new} for field, old, new in
                         [('star_rating', 3, 0), ('is_favorite', 1, 0), ('is_rejected', 0, 1), ('is_kept', 1, 0)]})
    assert entry['changes'] == expected
    reasons = {item['reason'] for item in entry['diagnostics']}
    assert ('manual_gps_protected' in reasons) == ('gps' in selected and not gps_applied)
    assert ('newer_local_edit' in reasons) == ('review' in selected and not review_applied)
    assert plan['conflicts'] == int('review' in selected and not review_applied)
    assert entry['review_provenance']
    assert snapshot(db) == before
    assert all(path.read_bytes() == data for path, data in bytes_before.items())

    applied = run_import(library, user, fields, *flags)
    assert applied.returncode == 0, applied.stderr
    assert review(db, user) == ((0, 0, 1, 0) if review_applied else (3, 1, 0, 1))
    assert review(db, 'bob') == (3, 1, 0, 1)
    if user:
        assert review(db, None) == (3, 1, 0, 1)
    else:
        assert review(db, 'alice') == (3, 1, 0, 1)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos').fetchone() == (
            (1, 2, 1) if gps_applied else (10, 20, 1))
        assert conn.execute('SELECT tag,source,created_by FROM photo_manual_tags').fetchall() == (
            [('external', 'xmp', user)] if 'keywords' in selected else [])
        receipts = conn.execute('SELECT * FROM photo_metadata_edits ORDER BY 1,2').fetchall()
    if not review_applied:
        assert receipts == before['photo_metadata_edits']
    else:
        changed = [row for row in receipts if row[1] == (user or '')]
        assert {row[2] for row in changed} == {'star_rating', 'is_favorite', 'is_rejected', 'is_kept'}
        assert all(row[3] > '2021-01-01' and row[4:] == ('xmp', str(sidecar), '2021-01-01T00:00:00+00:00')
                   for row in changed)
        old_clocks = {row[2]: row[3] for row in before['photo_metadata_edits'] if row[1] == (user or '')}
        assert all(row[3] >= old_clocks.get(row[2], '') for row in changed)
        assert [row for row in receipts if row[1] != (user or '')] == [
            row for row in before['photo_metadata_edits'] if row[1] != (user or '')]
    after = snapshot(db)
    repeat = run_import(library, user, fields, *flags, '--dry-run')
    assert repeat.returncode == 0, repeat.stderr
    assert json.loads(repeat.stdout)['entries'][0]['changes'] == {}
    assert snapshot(db) == after
    assert all(path.read_bytes() == bytes_before[path] for path in (photo, sidecar, config, secret))


@pytest.mark.parametrize('user', [None, 'alice'])
def test_cli_failed_apply_rolls_back_prior_keywords_review_and_receipts(library, user):
    db, photo, sidecar, config, secret, _ = library
    with sqlite3.connect(db) as conn:
        # The importer writes tags and review before GPS; fail that last step
        # using a real database constraint, not a patched CLI/import function.
        conn.execute("CREATE TRIGGER refuse_gps BEFORE UPDATE OF gps_latitude ON photos "
                     "WHEN NEW.gps_latitude IS NOT OLD.gps_latitude BEGIN SELECT RAISE(ABORT,'test GPS refusal'); END")
    before = snapshot(db)
    files = {path: path.read_bytes() for path in (photo, sidecar, config, secret)}
    flags = ('--overwrite-manual-gps', '--overwrite-sidecar-review')
    preview = run_import(library, user, 'review,gps,keywords', *flags, '--dry-run')
    assert preview.returncode == 0, preview.stderr
    assert set(json.loads(preview.stdout)['entries'][0]['changes']) == {
        'star_rating', 'is_favorite', 'is_rejected', 'is_kept', 'gps', 'keywords'}
    refused = run_import(library, user, 'review,gps,keywords', *flags)
    assert refused.returncode != 0
    assert 'test GPS refusal' in refused.stderr
    assert snapshot(db) == before
    assert all(path.read_bytes() == data for path, data in files.items())
    with sqlite3.connect(db, timeout=0.1) as conn:
        conn.execute('BEGIN IMMEDIATE')  # No abandoned writer lock after failure.
        conn.execute('DROP TRIGGER refuse_gps')
    retried = run_import(library, user, 'review,gps,keywords', *flags)
    assert retried.returncode == 0, retried.stderr
    assert review(db, user) == (0, 0, 1, 0)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT tag FROM photo_manual_tags').fetchall() == [('external',)]
        assert conn.execute('SELECT gps_latitude,gps_longitude FROM photos').fetchone() == (1, 2)
    assert all(path.read_bytes() == data for path, data in files.items())


@pytest.mark.parametrize('user', [None, 'alice'])
def test_cli_manual_gps_clear_is_protected_until_explicit_override(library, user):
    db, photo, sidecar, _, _, _ = library
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE photos SET gps_latitude=NULL,gps_longitude=NULL,gps_manually_set=1')
    before = snapshot(db)
    data = {path: path.read_bytes() for path in (db, photo, sidecar)}
    preview = run_import(library, user, 'gps', '--overwrite-sidecar-review', '--dry-run')
    assert preview.returncode == 0, preview.stderr
    entry = json.loads(preview.stdout)['entries'][0]
    assert entry['changes'] == {}
    assert entry['diagnostics'] == [{'field': 'gps', 'reason': 'manual_gps_protected'}]
    assert all(path.read_bytes() == value for path, value in data.items())
    protected = run_import(library, user, 'gps', '--overwrite-sidecar-review')
    assert protected.returncode == 0, protected.stderr
    assert snapshot(db) == before
    override = run_import(library, user, 'gps', '--overwrite-manual-gps', '--dry-run')
    assert override.returncode == 0, override.stderr
    assert json.loads(override.stdout)['entries'][0]['changes'] == {
        'gps': {'before': [None, None, 1], 'after': [1, 2, 1]}}
    applied = run_import(library, user, 'gps', '--overwrite-manual-gps')
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos').fetchone() == (1, 2, 1)
    after = snapshot(db)
    assert {table: rows for table, rows in after.items() if table != 'photos'} == {
        table: rows for table, rows in before.items() if table != 'photos'}
    assert photo.read_bytes() == data[photo] and sidecar.read_bytes() == data[sidecar]


def test_cli_named_user_cannot_override_outside_visible_folders(library):
    db, photo, sidecar, config, secret, _ = library
    before = snapshot(db)
    files = {path: path.read_bytes() for path in (photo, sidecar, config, secret)}
    flags = ('--overwrite-manual-gps', '--overwrite-sidecar-review')
    preview = run_import(library, 'bob', 'review,gps,keywords', *flags, '--dry-run')
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)['entries'] == []
    applied = run_import(library, 'bob', 'review,gps,keywords', *flags)
    assert applied.returncode == 0, applied.stderr
    assert snapshot(db) == before
    assert all(path.read_bytes() == data for path, data in files.items())
