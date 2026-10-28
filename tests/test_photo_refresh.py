"""Refresh uses actual source bytes and preserves viewer/AI state."""
import hashlib
import os
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from api.database import get_db


def _source(tmp_path, color='red'):
    path = tmp_path / 'image.jpg'
    exif = Image.Exif()
    exif[272] = 'Fresh Camera'
    exif[34665] = {36867: '2024:01:02 03:04:05', 34855: 640}
    Image.new('RGB', (800, 600), color).save(path, exif=exif)
    return str(path)


def _row(path):
    with get_db() as conn:
        return dict(conn.execute('SELECT * FROM photos WHERE path=?', (path,)).fetchone())


def _seed(seed_photos_prefix, path, **extra):
    seed_photos_prefix(os.path.dirname(path)+os.sep, [dict(path=path, filename='image.jpg',
        thumbnail=b'old thumbnail', aesthetic=8.5, aggregate=7.1, caption='My caption',
        is_kept=1, star_rating=4, tags='original tags', **extra)])


def test_refresh_reads_real_exif_and_preview_without_scoring_or_source_write(edition_client, seed_photos_prefix, tmp_path):
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path)
    original = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    before = _row(path)
    response = edition_client.post('/api/photos/refresh', json={'paths': [path]})
    assert response.status_code == 200, response.text
    assert response.json() == {'refreshed': [path], 'failed': []}
    after = _row(path)
    assert after['camera_model'] == 'Fresh Camera'
    assert after['date_taken'] == '2024:01:02 03:04:05'
    assert after['iso'] == 640
    assert after['preview_revision'] and after['preview_revision'] != before['preview_revision']
    with Image.open(BytesIO(after['thumbnail'])) as img:
        assert img.size == (640, 480)
        assert img.getpixel((10, 10))[0] > 200
    for key in ['aesthetic', 'aggregate', 'caption', 'is_kept', 'is_rejected', 'star_rating', 'tags', 'scanned_at']:
        assert after[key] == before[key]
    assert hashlib.sha256(open(path, 'rb').read()).hexdigest() == original
    photo = edition_client.get('/api/photo', params={'path': path}).json()
    assert photo['preview_revision'] == after['preview_revision']


def test_refresh_preserves_manual_date_gps_and_refreshes_token_even_same_thumbnail(edition_client, seed_photos_prefix, tmp_path):
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path, date_taken='2001:01:01 01:01:01', date_manually_set=1,
          gps_latitude=20, gps_longitude=30, gps_manually_set=1)
    for _ in range(2):
        old = _row(path)
        response = edition_client.post('/api/photos/refresh', json={'paths': [path]})
        assert response.json()['refreshed'] == [path]
        row = _row(path)
        assert (row['date_taken'], row['date_manually_set'], row['gps_latitude'], row['gps_longitude'], row['gps_manually_set']) == ('2001:01:01 01:01:01', 1, 20, 30, 1)
        assert row['preview_revision'] != old['preview_revision']


def test_partial_failure_leaves_bad_row_untouched_and_success_can_be_retried(edition_client, seed_photos_prefix, tmp_path):
    good = _source(tmp_path)
    bad = str(tmp_path/'broken.jpg')
    open(bad, 'wb').write(b'not an image')
    _seed(seed_photos_prefix, good)
    # Seeding another prefix clears the first; add both in one fixture call.
    seed_photos_prefix(str(tmp_path)+os.sep, [dict(path=p, filename=os.path.basename(p), thumbnail=b'old') for p in [good, bad]])
    old = _row(bad)
    result = edition_client.post('/api/photos/refresh', json={'paths': [good, bad]}).json()
    assert result['refreshed'] == [good]
    assert result['failed'] == [{'path': bad, 'reason': 'failed'}]
    assert _row(bad) == old
    Image.new('RGB', (50, 50), 'blue').save(bad)
    assert edition_client.post('/api/photos/refresh', json={'paths': [bad]}).json()['refreshed'] == [bad]


def test_changed_source_refuses_without_changing_photo(edition_client, seed_photos_prefix, tmp_path):
    from api.routers.photo_refresh import get_exif_batch
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path)
    before = _row(path)
    def replace_during_read(paths):
        data = get_exif_batch(paths)
        Image.new('RGB', (90, 90), 'blue').save(path)
        return data
    with patch('api.routers.photo_refresh.get_exif_batch', side_effect=replace_during_read):
        result = edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()
    assert result['failed'] == [{'path': path, 'reason': 'changed'}]
    assert _row(path) == before


def test_all_targets_authorized_before_any_read(edition_client, seed_photos_prefix, tmp_path):
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path)
    before = _row(path)
    with patch('api.routers.photo_refresh.load_viewer_image') as load:
        assert edition_client.post('/api/photos/refresh', json={'paths': [path, '/unknown.jpg']}).status_code == 404
        load.assert_not_called()
    assert _row(path) == before


def test_refresh_requires_edition_and_bounded_explicit_paths(regular_client, edition_client):
    assert regular_client.post('/api/photos/refresh', json={'paths': ['/x.jpg']}).status_code in (401, 403)
    assert edition_client.post('/api/photos/refresh', json={'paths': ['/x.jpg'] * 101}).status_code == 422
    assert edition_client.post('/api/photos/refresh', json={'paths': []}).status_code == 422


def test_refresh_replaces_warm_preview_caches_even_when_source_mtime_is_preserved(edition_client, seed_photos_prefix, tmp_path):
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path)
    assert edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()['refreshed'] == [path]
    stored = edition_client.get('/thumbnail', params={'path': path, 'size': 96})
    sharp = edition_client.get('/thumbnail', params={'path': path, 'size': 1920})
    stat = os.stat(path)
    _source(tmp_path, 'blue')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    response = edition_client.post('/api/photos/refresh', json={'paths': [path]})
    assert response.json()['refreshed'] == [path]
    fresh = edition_client.get('/thumbnail', params={'path': path, 'size': 96}, headers={'If-None-Match': stored.headers['etag']})
    assert fresh.status_code == 200
    assert fresh.content != stored.content
    new_sharp = edition_client.get('/thumbnail', params={'path': path, 'size': 1920})
    assert new_sharp.content != sharp.content
    with Image.open(BytesIO(new_sharp.content)) as img:
        assert img.getpixel((10, 10))[2] > 200


def test_manual_authority_acquired_during_metadata_read_wins(edition_client, seed_photos_prefix, tmp_path):
    from api.routers.photo_refresh import get_exif_batch
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path)
    def edit_during_read(paths):
        values = get_exif_batch(paths)
        with get_db() as conn, conn:
            conn.execute("UPDATE photos SET date_manually_set=1,date_taken='1999:01:01 00:00:00',gps_manually_set=1,gps_latitude=1,gps_longitude=2 WHERE path=?", (path,))
        values[path]['gps_latitude'] = 50
        values[path]['gps_longitude'] = 40
        return values
    with patch('api.routers.photo_refresh.get_exif_batch', side_effect=edit_during_read):
        assert edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()['refreshed'] == [path]
    row = _row(path)
    assert (row['date_taken'], row['gps_latitude'], row['gps_longitude']) == ('1999:01:01 00:00:00', 1, 2)


def test_refresh_visibility_refusal_keeps_other_accounts_private(edition_client, seed_photos_prefix, tmp_path, monkeypatch):
    from api import config
    own = tmp_path/'own'
    own.mkdir()
    hidden = tmp_path/'hidden'
    hidden.mkdir()
    first = _source(own)
    second = _source(hidden)
    seed_photos_prefix(str(tmp_path)+os.sep, [dict(path=p,filename='image.jpg',thumbnail=b'old') for p in [first,second]])
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': [str(own)]}, 'other': {'directories': [str(hidden)]}}})
    with patch('api.routers.photo_refresh.load_viewer_image') as load:
        response = edition_client.post('/api/photos/refresh', json={'paths': [first, second]})
        assert response.status_code == 404
        load.assert_not_called()
    assert _row(first)['thumbnail'] == b'old'
    assert _row(second)['thumbnail'] == b'old'


def test_refreshed_native_jxl_validator_changes_with_preserved_size_and_mtime(edition_client, seed_photos_prefix, tmp_path):
    import struct
    import imagecodecs
    import numpy as np
    import pytest
    if not imagecodecs.JPEGXL.available:
        pytest.skip('JPEG XL codec is unavailable')
    def encoded(color):
        pixels = np.zeros((24, 32, 3), dtype=np.uint8)
        pixels[:] = color
        raw = imagecodecs.jpegxl_encode(pixels, lossless=True, numthreads=1)
        def box(kind, payload):
            return struct.pack('>I4s', len(payload) + 8, kind) + payload
        prefix = b'\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a' + box(b'ftyp', b'jxl \x00\x00\x00\x00jxl ') + box(b'jxlc', raw)
        return prefix + box(b'free', b'x' * (1024 - len(prefix) - 8))
    path = tmp_path/'image.jxl'
    path.write_bytes(encoded((240, 20, 10)))
    seed_photos_prefix(str(tmp_path)+os.sep, [dict(path=str(path), filename=path.name, thumbnail=b'old')])
    before = edition_client.get('/image', params={'path': str(path)}, headers={'Accept': 'image/jxl'})
    assert before.status_code == 200
    stat = path.stat()
    path.write_bytes(encoded((10, 40, 230)))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    assert edition_client.post('/api/photos/refresh', json={'paths': [str(path)]}).json()['refreshed'] == [str(path)]
    response = edition_client.get('/image', params={'path': str(path)}, headers={'Accept': 'image/jxl', 'If-None-Match': before.headers['etag']})
    assert response.status_code == 200
    assert response.content == path.read_bytes()


def test_refresh_refuses_active_library_job_before_decode(edition_client, seed_photos_prefix, tmp_path):
    from facet import LibraryLock
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path)
    with get_db() as conn:
        db_path = conn.execute('PRAGMA database_list').fetchone()[2]
    lock = LibraryLock(db_path, 'test-scanner').acquire()
    try:
        with patch('api.routers.photo_refresh.load_viewer_image') as load:
            response = edition_client.post('/api/photos/refresh', json={'paths': [path]})
            assert response.status_code == 503
            assert response.headers['retry-after'] == '5'
            load.assert_not_called()
    finally:
        lock.release()
    assert edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()['refreshed'] == [path]


def test_refresh_updates_original_upright_dimensions_after_external_crop(edition_client, seed_photos_prefix, tmp_path):
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path, image_width=800, image_height=600)
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (500, 300), 'green').save(path, exif=exif)
    response = edition_client.post('/api/photos/refresh', json={'paths': [path]})
    assert response.json()['refreshed'] == [path]
    row = _row(path)
    assert (row['image_width'], row['image_height']) == (300, 500)
    with Image.open(BytesIO(row['thumbnail'])) as thumbnail:
        assert thumbnail.size == (300, 500)


def test_refresh_marks_changed_manual_face_for_review_without_deleting_assignment(edition_client, seed_photos_prefix, tmp_path):
    import uuid
    path = _source(tmp_path)
    _seed(seed_photos_prefix, path, image_width=800, image_height=600)
    frame = edition_client.get('/api/photo/manual-face-frame', params={'path': path})
    assert frame.status_code == 200
    created = edition_client.post('/api/photo/manual-faces', json={
        'path': path, 'frame_token': frame.json()['frame_token'], 'bbox': [0.1, 0.1, 0.5, 0.5],
        'new_person_name': 'Test person', 'client_id': str(uuid.uuid4())})
    assert created.status_code == 201, created.text
    face_id = created.json()['id']
    assert edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()['refreshed'] == [path]
    with get_db() as conn:
        before = dict(conn.execute('SELECT * FROM faces WHERE id=?', (face_id,)).fetchone())
    assert before['manual_review_required'] == 0
    Image.new('RGB', (500, 300), 'green').save(path)
    assert edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()['refreshed'] == [path]
    with get_db() as conn:
        after = dict(conn.execute('SELECT * FROM faces WHERE id=?', (face_id,)).fetchone())
    assert after['manual_review_required'] == 1
    for name in ['person_id', 'manual_source', 'manual_key', 'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2']:
        assert after[name] == before[name]


def test_explicit_refresh_rechecks_cached_manual_pixels_with_preserved_size_and_mtime(edition_client, seed_photos_prefix, tmp_path):
    import uuid
    path = str(tmp_path/'frame.bmp')
    Image.new('RGB', (200, 160), 'white').save(path)
    _seed(seed_photos_prefix, path, image_width=200, image_height=160)
    frame = edition_client.get('/api/photo/manual-face-frame', params={'path': path}).json()
    created = edition_client.post('/api/photo/manual-faces', json={
        'path': path, 'frame_token': frame['frame_token'], 'bbox': [0.1, 0.1, 0.5, 0.5],
        'new_person_name': 'Cached person', 'client_id': str(uuid.uuid4())})
    assert created.status_code == 201
    stat = os.stat(path)
    Image.new('RGB', (200, 160), 'green').save(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert os.stat(path).st_size == stat.st_size
    assert edition_client.post('/api/photos/refresh', json={'paths': [path]}).json()['refreshed'] == [path]
    with get_db() as conn:
        assert conn.execute('SELECT manual_review_required FROM faces WHERE id=?', (created.json()['id'],)).fetchone()[0] == 1
    fresh = edition_client.get('/api/photo/manual-face-frame', params={'path': path}).json()
    assert fresh['image_base64'] != frame['image_base64']
