"""HEIF repair retries retain failed work and never rotate successful rows twice."""

import io
import sqlite3

import numpy as np
import pytest
from PIL import Image

pillow_heif = pytest.importorskip('pillow_heif')

from db import init_database  # noqa: E402
from processing import scorer  # noqa: E402


def _write_source_heif(path, orientation=8):
    exif = Image.Exif()
    exif[274] = orientation
    pillow_heif.from_pillow(Image.new('RGB', (8, 6), (80, 90, 100))).save(
        path, exif=exif.tobytes())
    return path


def _sideways_thumbnail(orientation=8, *, comment=b''):
    upright = Image.new('RGB', (60, 80), (240, 240, 240))
    upright.paste((10, 10, 10), (0, 40, 60, 80))
    extra_turn = Image.Transpose.ROTATE_90 if orientation == 8 else Image.Transpose.ROTATE_270
    buf = io.BytesIO()
    upright.transpose(extra_turn).save(buf, format='JPEG', quality=90, comment=comment)
    return buf.getvalue()


def _seed_photo(conn, path, scanned_at, *, orientation=8, blob=None):
    blob = _sideways_thumbnail(orientation) if blob is None else blob
    conn.execute(
        'INSERT INTO photos(path,filename,scanned_at,thumbnail,image_width,image_height,'
        'subject_sharpness,subject_prominence,subject_placement,bg_separation,subject_bbox) '
        'VALUES (?,?,?,?,800,600,5,5,5,5,?)',
        (str(path), path.name, scanned_at, blob, '[0.1,0.2,0.3,0.4]'))
    box, point = ((200, 400, 300, 500), (250, 450)) if orientation == 8 else ((500, 100, 600, 200), (550, 150))
    conn.execute(
        'INSERT INTO faces(photo_path,face_index,embedding,bbox_x1,bbox_y1,bbox_x2,bbox_y2,'
        'landmark_2d_106,face_thumbnail,manual_width,manual_height) VALUES (?,0,?,?, ?,?,?, ?,?,800,600)',
        (str(path), b'fixture', *box, np.array([point] * 106, dtype=np.float32).tobytes(), _sideways_thumbnail(orientation)))
    conn.execute('INSERT INTO iqa_declined(photo_path,model,scan_fingerprint) VALUES (?,?,?)',
                 (str(path), 'topiq_nr_face', 'old'))


def _stored_state(db, path):
    with sqlite3.connect(db) as conn:
        photo = conn.execute(
            'SELECT thumbnail,image_width,image_height,subject_sharpness,subject_prominence,'
            'subject_placement,bg_separation,subject_bbox FROM photos WHERE path=?', (str(path),)).fetchone()
        faces = conn.execute('SELECT * FROM faces WHERE photo_path=? ORDER BY id', (str(path),)).fetchall()
        declines = conn.execute('SELECT * FROM iqa_declined WHERE photo_path=?', (str(path),)).fetchall()
    return photo, faces, declines


def _watermark(db):
    with sqlite3.connect(db) as conn:
        row = conn.execute('SELECT value FROM stats_cache WHERE key=?',
                           (scorer.HEIF_DOUBLE_TRANSPOSE_WATERMARK_KEY,)).fetchone()
    return row[0] if row else None


def _assert_upright(db, path):
    photo, _, declines = _stored_state(db, path)
    assert photo[1:3] == (600, 800)
    assert photo[3:] == (None,) * 5
    assert not declines
    with Image.open(io.BytesIO(photo[0])) as image:
        assert image.size == (60, 80)
        assert image.getpixel((30, 10))[0] > 200
        assert image.getpixel((30, 70))[0] < 50
    with sqlite3.connect(db) as conn:
        face = conn.execute(
            'SELECT bbox_x1,bbox_y1,bbox_x2,bbox_y2,landmark_2d_106,face_thumbnail,'
            'manual_width,manual_height FROM faces WHERE photo_path=?', (str(path),)).fetchone()
    assert face[:4] == (100, 200, 200, 300)
    assert np.frombuffer(face[4], dtype=np.float32).reshape(-1, 2)[0].tolist() == [150, 250]
    assert face[6:] == (600, 800)
    with Image.open(io.BytesIO(face[5])) as crop:
        assert crop.size == (60, 80)
        assert crop.getpixel((30, 10))[0] > 200
        assert crop.getpixel((30, 70))[0] < 50


@pytest.mark.parametrize('failure_first', [False, True])
@pytest.mark.parametrize('same_timestamp', [False, True])
@pytest.mark.parametrize('prior_marker', [None, '2025-12-01 10:00:00'])
def test_offline_retry_preserves_progress_and_successful_faces(tmp_path, failure_first, same_timestamp, prior_marker):
    db = str(tmp_path / 'repair.db')
    init_database(db)
    ready = _write_source_heif(tmp_path / 'ready.hif')
    offline = tmp_path / 'offline.hif'
    first, second = (offline, ready) if failure_first else (ready, offline)
    with sqlite3.connect(db) as conn:
        _seed_photo(conn, first, '2026-01-01 10:00:00')
        _seed_photo(conn, second, '2026-01-01 10:00:00' if same_timestamp else '2026-02-01 10:00:00')
        if prior_marker:
            conn.execute('INSERT INTO stats_cache(key,value,updated_at) VALUES (?,?,0)',
                         (scorer.HEIF_DOUBLE_TRANSPOSE_WATERMARK_KEY, prior_marker))
    offline_before = _stored_state(db, offline)
    original = ready.read_bytes()
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 1
    assert _watermark(db) == prior_marker
    _assert_upright(db, ready)
    ready_after = _stored_state(db, ready)
    assert _stored_state(db, offline) == offline_before

    _write_source_heif(offline)
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 1
    _assert_upright(db, offline)
    assert _stored_state(db, ready) == ready_after
    assert ready.read_bytes() == original
    offline_date = '2026-01-01 10:00:00' if same_timestamp or failure_first else '2026-02-01 10:00:00'
    assert _watermark(db) == offline_date
    final = (_stored_state(db, ready), _stored_state(db, offline))
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 0
    assert (_stored_state(db, ready), _stored_state(db, offline)) == final


@pytest.mark.parametrize('failure_first', [False, True])
@pytest.mark.parametrize('failure', ['decode', 'encode'])
def test_bad_thumbnail_retries_after_replacement_without_rotating_ready_rows(tmp_path, monkeypatch, failure_first, failure):
    db = str(tmp_path / 'repair.db')
    init_database(db)
    ready = _write_source_heif(tmp_path / 'ready.hif', 6)
    failed = _write_source_heif(tmp_path / 'failed.hif', 6)
    originals = {path: path.read_bytes() for path in (ready, failed)}
    order = (failed, ready) if failure_first else (ready, failed)
    bad_blob = b'broken-thumbnail' if failure == 'decode' else _sideways_thumbnail(6, comment=b'encode-refusal')
    with sqlite3.connect(db) as conn:
        for path in order:
            _seed_photo(conn, path, '2026-01-01 10:00:00', orientation=6,
                 blob=bad_blob if path == failed else None)
    failed_before = _stored_state(db, failed)
    save = Image.Image.save
    refusals = []

    def refuse_tagged_thumbnail(image, *args, **kwargs):
        if image.info.get('comment') == b'encode-refusal':
            refusals.append(image.size)
            raise OSError('controlled JPEG encoder refusal')
        return save(image, *args, **kwargs)

    with monkeypatch.context() as patch:
        if failure == 'encode':
            patch.setattr(Image.Image, 'save', refuse_tagged_thumbnail)
        assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 1
    assert refusals == ([(60, 80)] if failure == 'encode' else [])
    assert _watermark(db) is None
    assert _stored_state(db, failed) == failed_before
    _assert_upright(db, ready)
    ready_after = _stored_state(db, ready)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE photos SET thumbnail=? WHERE path=?', (_sideways_thumbnail(6), str(failed)))
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 1
    _assert_upright(db, failed)
    assert _stored_state(db, ready) == ready_after
    assert {path: path.read_bytes() for path in originals} == originals
    final = (_stored_state(db, ready), _stored_state(db, failed))
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 0
    assert (_stored_state(db, ready), _stored_state(db, failed)) == final


def test_batch_commit_publishes_a_complete_repaired_photo_before_next_header(tmp_path, monkeypatch):
    db = str(tmp_path / 'repair.db')
    init_database(db)
    first = _write_source_heif(tmp_path / 'first.hif', 6)
    second = _write_source_heif(tmp_path / 'second.hif', 8)
    with sqlite3.connect(db) as conn:
        _seed_photo(conn, first, '2026-01-01 10:00:00', orientation=6)
        _seed_photo(conn, second, '2026-02-01 10:00:00', orientation=8)
    read = scorer._stored_heif_orientation
    observed = []

    def observe(path):
        if path == str(second):
            # These reads use another real connection: no timer or mocked commit.
            _assert_upright(db, first)
            assert _watermark(db) is None
            observed.append(_stored_state(db, first))
        return read(path)

    monkeypatch.setattr(scorer, '_stored_heif_orientation', observe)
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 2
    assert len(observed) == 1
    _assert_upright(db, second)
    assert _watermark(db) == '2026-02-01 10:00:00'
    final = (_stored_state(db, first), _stored_state(db, second))
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 0
    assert (_stored_state(db, first), _stored_state(db, second)) == final


def test_interruption_after_a_batch_keeps_committed_faces_and_retries_remaining_rows(tmp_path, monkeypatch):
    db = str(tmp_path / 'repair.db')
    init_database(db)
    first = _write_source_heif(tmp_path / 'first.hif', 6)
    second = _write_source_heif(tmp_path / 'second.hif')
    with sqlite3.connect(db) as conn:
        _seed_photo(conn, first, '2026-01-01 10:00:00', orientation=6)
        _seed_photo(conn, second, '2026-02-01 10:00:00')
    read = scorer._stored_heif_orientation

    def interrupt(path):
        if path == str(second):
            raise KeyboardInterrupt
        return read(path)

    with monkeypatch.context() as patch:
        patch.setattr(scorer, '_stored_heif_orientation', interrupt)
        with pytest.raises(KeyboardInterrupt):
            scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1)
    _assert_upright(db, first)
    committed = _stored_state(db, first)
    assert _watermark(db) is None
    assert scorer.fix_double_transposed_heif_thumbnails(db, batch_size=1) == 1
    _assert_upright(db, second)
    assert _stored_state(db, first) == committed


def test_missing_timestamp_offline_candidate_is_not_passed_by_dated_landscape(tmp_path):
    db = str(tmp_path / 'repair.db')
    init_database(db)
    offline = tmp_path / 'offline.hif'
    landscape = _write_source_heif(tmp_path / 'landscape.hif', 3)
    with sqlite3.connect(db) as conn:
        _seed_photo(conn, offline, None)
        _seed_photo(conn, landscape, '2026-02-01 10:00:00')
    landscape_before = _stored_state(db, landscape)
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 0
    assert _watermark(db) is None
    _write_source_heif(offline)
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 1
    _assert_upright(db, offline)
    assert _stored_state(db, landscape) == landscape_before
    assert _watermark(db) == '2026-02-01 10:00:00'
    final = _stored_state(db, offline)
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 0
    assert _stored_state(db, offline) == final


def test_old_watermark_does_not_hide_unfinished_work_and_new_marker_limits_headers(tmp_path, monkeypatch):
    db = str(tmp_path / 'repair.db')
    init_database(db)
    rotated = _write_source_heif(tmp_path / 'rotated.hif')
    landscape = _write_source_heif(tmp_path / 'landscape.hif', 3)
    with sqlite3.connect(db) as conn:
        _seed_photo(conn, rotated, '2026-01-01 10:00:00')
        _seed_photo(conn, landscape, '2026-02-01 10:00:00')
        conn.execute('INSERT INTO stats_cache(key,value,updated_at) VALUES (?,?,0)',
                     ('heif_double_transpose_watermark', '2026-12-01 10:00:00'))
    landscape_before = _stored_state(db, landscape)
    read = scorer._stored_heif_orientation
    headers = []

    def observe(path):
        headers.append(path)
        return read(path)

    monkeypatch.setattr(scorer, '_stored_heif_orientation', observe)
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 1
    _assert_upright(db, rotated)
    assert _stored_state(db, landscape) == landscape_before
    assert headers == [str(rotated), str(landscape)]
    assert _watermark(db) == '2026-02-01 10:00:00'
    headers.clear()
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 0
    assert headers == []
    later = _write_source_heif(tmp_path / 'later.hif', 6)
    with sqlite3.connect(db) as conn:
        _seed_photo(conn, later, '2026-03-01 10:00:00', orientation=6)
    assert scorer.fix_double_transposed_heif_thumbnails(db) == 1
    assert headers == [str(later)]
    _assert_upright(db, later)
