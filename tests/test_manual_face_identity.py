"""A manual face belongs to canonical pixels, not one host's inode."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from api import config
from api.database import get_db
from db.manual_faces import same_image, source_identity


@pytest.fixture
def identity_photo(tmp_path, seed_photos_prefix, monkeypatch):
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {})
    image = tmp_path / 'pixels.jpg'
    pixels = Image.new('RGB', (100, 80), 'red')
    pixels.paste('blue', (50, 0, 100, 80))
    pixels.save(image)
    path = str(image)
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': image.name}])
    return path


@pytest.fixture(autouse=True)
def fresh_frame_cache():
    from utils.manual_face_frame import clear_cache
    clear_cache()
    yield
    clear_cache()


def _mark(client, path):
    response = client.get('/api/photo/manual-face-frame', params={'path': path})
    assert response.status_code == 200, response.text
    body = {'path': path, 'frame_token': response.json()['frame_token'],
            'bbox': [0.1, 0.1, 0.5, 0.8], 'new_person_name': 'Pixel person',
            'client_id': str(uuid4())}
    response = client.post('/api/photo/manual-faces', json=body)
    assert response.status_code == 201, response.text
    return body, response.json()


def _replace_metadata(path):
    """Replace a JPEG with identical compressed pixels and a harmless APP15 tag."""
    image = Path(path)
    content = image.read_bytes()
    assert content[:2] == b'\xff\xd8'
    payload = b'Facet metadata-only test'
    replacement = image.with_suffix('.replacement')
    replacement.write_bytes(content[:2] + b'\xff\xef' +
                            (len(payload) + 2).to_bytes(2, 'big') + payload + content[2:])
    os.replace(replacement, image)


def _regions(client, path):
    response = client.get('/api/photo/manual-faces', params={'path': path})
    assert response.status_code == 200, response.text
    return response.json()['regions']


def test_metadata_replacement_keeps_manual_export_and_overlap(edition_client, identity_photo):
    from api.routers.export import _fetch_regions_map
    from db.person_carry_over import replace_photo_faces
    from db.schema import FACES_UPSERT_SQL, face_upsert_row
    from processing.xmp_export import _cli_face_regions

    path = identity_photo
    _, saved = _mark(edition_client, path)
    original = source_identity(path)
    _replace_metadata(path)
    assert same_image(source_identity(path), original)
    assert _regions(edition_client, path)[0]['source_changed'] is False
    with get_db() as conn, conn:
        assert len(_fetch_regions_map(conn, [path])[path]) == 1
        assert len(_cli_face_regions(conn, path, 100, 80)) == 1
        detected = {'index': 0, 'embedding': bytes(2048), 'bbox': [11, 9, 49, 63]}
        replace_photo_faces(conn, [path], [face_upsert_row(path, detected, 'arcface_buffalo_l')],
                            FACES_UPSERT_SQL)
        assert [tuple(row) for row in conn.execute(
            'SELECT id,is_manual FROM faces WHERE photo_path=?', (path,))] == [(saved['id'], 1)]


def test_identity_survives_a_copy_to_another_host_path(identity_photo, tmp_path):
    copied = tmp_path / 'other-host.jpg'
    shutil.copy2(identity_photo, copied)
    assert same_image(source_identity(identity_photo), source_identity(copied))


@pytest.mark.skipif(not shutil.which('exiftool'), reason='real ExifTool is optional')
def test_two_real_embed_exports_keep_the_manual_region(edition_client, identity_photo):
    path = identity_photo
    _mark(edition_client, path)
    for _ in range(2):
        response = edition_client.post('/api/photo/embed_metadata', json={'path': path})
        assert response.status_code == 200, response.text
        assert Path(response.json()['embedded']).samefile(path)
        assert _regions(edition_client, path)[0]['source_changed'] is False
        root = ET.parse(path + '.xmp').getroot()
        name_tag = '{http://www.metadataworkinggroup.com/schemas/regions/}Name'
        names = [node.text for node in root.iter(name_tag)]
        names += [node.attrib[name_tag] for node in root.iter() if name_tag in node.attrib]
        assert names == ['Pixel person']


@pytest.mark.parametrize('form', ['stat-only', 'pixels-v1'])
def test_old_identity_mark_is_retained_until_a_deliberate_fresh_edit(edition_client, identity_photo, form):
    from api.routers.export import _fetch_regions_map
    path = identity_photo
    body, saved = _mark(edition_client, path)
    stat = os.stat(path)
    legacy = (json.dumps([stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns], separators=(',', ':'))
              if form == 'stat-only' else
              json.dumps(['upright-pixels-v1', 100, 80, 'a' * 64], separators=(',', ':')))
    with get_db() as conn, conn:
        conn.execute('UPDATE faces SET manual_source=? WHERE id=?', (legacy, saved['id']))
    assert _regions(edition_client, path)[0]['source_changed'] is True
    with get_db() as conn:
        assert not _fetch_regions_map(conn, [path]).get(path)
        assert conn.execute('SELECT person_id FROM faces WHERE id=?',
                            (saved['id'],)).fetchone()[0] == saved['person_id']
    body.pop('client_id')
    body['new_person_name'] = None
    body['person_id'] = saved['person_id']
    body['frame_token'] = edition_client.get(
        '/api/photo/manual-face-frame', params={'path': path}).json()['frame_token']
    updated = edition_client.put(f"/api/photo/manual-faces/{saved['id']}", json=body)
    assert updated.status_code == 200, updated.text
    assert updated.json()['source_changed'] is False
    with get_db() as conn:
        assert len(_fetch_regions_map(conn, [path])[path]) == 1


def test_preview_save_and_list_share_one_immutable_decode(edition_client, identity_photo, monkeypatch):
    from utils import manual_face_frame as frames
    original = frames.load_image_for_face_crop
    calls = []
    def decode(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(frames, 'load_image_for_face_crop', decode)
    _mark(edition_client, identity_photo)
    assert _regions(edition_client, identity_photo)[0]['source_changed'] is False
    snapshot = frames.read_frame(identity_photo)
    assert len(calls) == 1
    assert snapshot.pixels.shape == (80, 100, 3)
    assert snapshot.pixels.flags.writeable is False
    with pytest.raises(ValueError):
        snapshot.pixels[0, 0] = 0


def test_oversized_frames_are_not_retained_but_fingerprints_are(identity_photo, monkeypatch):
    from utils import manual_face_frame as frames
    original = frames.load_image_for_face_crop
    calls = []
    def decode(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(frames, 'load_image_for_face_crop', decode)
    monkeypatch.setattr(frames, '_MAX_FRAME_BYTES', 1)
    first = frames.read_frame(identity_photo)
    assert frames.source_identity(identity_photo) == first.identity
    assert frames.read_frame(identity_photo).identity == first.identity
    assert len(calls) == 2


def test_device_and_inode_are_only_cache_invalidators(identity_photo, monkeypatch):
    from utils import manual_face_frame as frames
    original = frames.file_stamp
    expected = frames.source_identity(identity_photo)
    def remounted(path):
        stamp = original(path)
        return (stamp[0], stamp[1] + 100, stamp[2] + 100, *stamp[3:])
    monkeypatch.setattr(frames, 'file_stamp', remounted)
    assert same_image(frames.source_identity(identity_photo), expected)


def test_changed_pixels_in_same_dimensions_still_require_review(edition_client, identity_photo):
    body, _ = _mark(edition_client, identity_photo)
    Image.new('RGB', (100, 80), 'green').save(identity_photo)
    assert _regions(edition_client, identity_photo)[0]['source_changed'] is True
    body['client_id'] = str(uuid4())
    assert edition_client.post('/api/photo/manual-faces', json=body).status_code == 409


def test_file_change_during_decode_is_not_cached_or_issued_as_a_frame(edition_client, identity_photo, monkeypatch):
    from utils import manual_face_frame as frames
    original = frames.load_image_for_face_crop
    def changing(path):
        pixels = original(path)
        _replace_metadata(path)
        return pixels
    monkeypatch.setattr(frames, 'load_image_for_face_crop', changing)
    assert edition_client.get('/api/photo/manual-face-frame',
                              params={'path': identity_photo}).status_code == 409
    monkeypatch.setattr(frames, 'load_image_for_face_crop', original)
    assert edition_client.get('/api/photo/manual-face-frame',
                              params={'path': identity_photo}).status_code == 200


def test_listing_rechecks_access_after_a_cold_content_hash(edition_client, identity_photo, monkeypatch):
    from api.routers import manual_faces as router
    from utils import manual_face_frame as frames
    _mark(edition_client, identity_photo)
    # An unchanged stat is current without a decode; a rewrite forces one.
    _replace_metadata(identity_photo)
    frames.clear_cache()
    original = frames.load_image_for_face_crop
    state = SimpleNamespace(revoked=False)
    def visible(*args):
        if state.revoked:
            raise LookupError('Revoked')
    def decode(path):
        pixels = original(path)
        state.revoked = True
        return pixels
    monkeypatch.setattr(router, 'assert_photo_visible', visible)
    monkeypatch.setattr(frames, 'load_image_for_face_crop', decode)
    assert edition_client.get('/api/photo/manual-faces',
                              params={'path': identity_photo}).status_code == 404


def test_decoder_profile_changes_invalidate_cached_pixels(identity_photo, monkeypatch):
    import numpy as np
    from utils import manual_face_frame as frames
    profile = {'bright': 1}
    monkeypatch.setattr(frames, 'get_raw_decode_settings', lambda: profile)
    monkeypatch.setattr(frames, 'load_image_for_face_crop',
                        lambda path: np.full((80, 100, 3), profile['bright'], dtype=np.uint8))
    before = frames.source_identity(identity_photo)
    profile['bright'] = 2
    assert frames.source_identity(identity_photo) != before


def test_unmarked_scanner_photo_does_not_need_a_second_decode(identity_photo, monkeypatch):
    from db.manual_faces import without_manual_overlaps
    from utils import manual_face_frame as frames
    def forbidden(path):
        pytest.fail('An unmarked scanner photo reached the manual-frame decoder')
    monkeypatch.setattr(frames, 'load_image_for_face_crop', forbidden)
    record = (identity_photo, 0, b'', 10, 10, 20, 20)
    with get_db() as conn:
        assert without_manual_overlaps(conn, identity_photo, [record]) == [record]


@pytest.mark.parametrize('second_needs_pixels', [False, True])
def test_concurrent_frame_and_identity_requests_share_decode(identity_photo, monkeypatch, second_needs_pixels):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from utils import manual_face_frame as frames
    original = frames.load_image_for_face_crop
    original_wait = frames._condition.wait
    loading, release, waiting, second_started = [threading.Event() for _ in range(4)]
    calls = []
    def decode(path):
        calls.append(path)
        loading.set()
        assert release.wait(5)
        return original(path)
    def wait(timeout=None):
        waiting.set()
        return original_wait(timeout)
    def second():
        second_started.set()
        if second_needs_pixels:
            return frames.read_frame(identity_photo).identity
        return frames.source_identity(identity_photo)
    monkeypatch.setattr(frames, 'load_image_for_face_crop', decode)
    monkeypatch.setattr(frames._condition, 'wait', wait)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(frames.read_frame, identity_photo)
        assert loading.wait(3)
        other = pool.submit(second)
        try:
            assert second_started.wait(3)
            waiting.wait(1)
        finally:
            release.set()
        assert first.result().identity == other.result()
    assert len(calls) == 1


def _pixels(offset=0):
    import numpy as np
    base = np.zeros((80, 100, 3), dtype=np.uint8)
    base[:, 50:] = 200
    return np.clip(base.astype(int) + offset, 0, 255).astype(np.uint8)


def test_decode_differing_by_one_per_pixel_still_reads_current(identity_photo, monkeypatch):
    """Another host's LibRaw/libheif build rounds differently; the mark must survive it."""
    from utils import manual_face_frame as frames
    monkeypatch.setattr(frames, 'load_image_for_face_crop', lambda path: _pixels(0))
    stored = frames.source_identity(identity_photo)
    frames.clear_cache()
    monkeypatch.setattr(frames, 'load_image_for_face_crop', lambda path: _pixels(1))
    stat = os.stat(identity_photo)
    os.utime(identity_photo, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))
    assert frames.is_current(identity_photo, stored) is True
    frames.clear_cache()
    monkeypatch.setattr(frames, 'load_image_for_face_crop', lambda path: _pixels(40))
    assert frames.is_current(identity_photo, stored) is False


def test_a_resized_copy_of_the_same_picture_still_requires_review(edition_client, identity_photo):
    """The 8x8 signature survives a resize; the frame size must not."""
    _mark(edition_client, identity_photo)
    Image.open(identity_photo).resize((200, 160)).save(identity_photo)
    assert _regions(edition_client, identity_photo)[0]['source_changed'] is True


def test_unchanged_stat_is_current_without_decoding(identity_photo, monkeypatch):
    from utils import manual_face_frame as frames
    stored = frames.source_identity(identity_photo)
    frames.clear_cache()
    def forbidden(path):
        raise AssertionError('decoded an unchanged file')
    monkeypatch.setattr(frames, 'load_image_for_face_crop', forbidden)
    assert frames.is_current(identity_photo, stored) is True


def test_stat_refresh_is_best_effort_and_keeps_the_original_signature(identity_photo):
    from utils import manual_face_frame as frames
    stored = frames.source_identity(identity_photo)
    _replace_metadata(identity_photo)
    class Broken:
        def execute(self, *args):
            raise RuntimeError('database is locked')
    assert frames.is_current(identity_photo, stored, Broken(), 1) is True
    class Recording:
        def execute(self, sql, params):
            self.params = params
    recording = Recording()
    assert frames.is_current(identity_photo, stored, recording, 1) is True
    refreshed = json.loads(recording.params[0])
    assert refreshed['sig'] == json.loads(stored)['sig']
    assert refreshed['stat'] != json.loads(stored)['stat']


def test_identity_failure_never_aborts_a_scan_batch_or_export(identity_photo, monkeypatch):
    from db import manual_faces
    from db.manual_faces import export_dimensions, without_manual_overlaps
    from utils import manual_face_frame as frames
    identity = frames.source_identity(identity_photo)
    def broken(path, *args):
        raise ValueError('identity exploded')
    monkeypatch.setattr(manual_faces, 'is_current', broken)
    record = (identity_photo, 0, b'', 10, 10, 20, 20)
    with get_db() as conn:
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,is_manual,manual_key,bbox_x1,bbox_y1,"
                     "bbox_x2,bbox_y2,manual_source,manual_width,manual_height) "
                     "VALUES (?,-1,X'',1,'boom',10,10,20,20,?,100,80)", (identity_photo, identity))
        try:
            assert without_manual_overlaps(conn, identity_photo, [record]) == [record]
        finally:
            conn.rollback()
    row = {'is_manual': 1, 'photo_path': identity_photo, 'manual_source': identity,
           'manual_width': 100, 'manual_height': 80}
    assert export_dimensions(row, 100, 80) is None


def test_mark_drawn_after_the_scan_snapshot_still_suppresses_detection(edition_client, identity_photo):
    from db.manual_faces import without_manual_overlaps
    _mark(edition_client, identity_photo)
    record = (identity_photo, 0, b'', 10, 8, 50, 64)
    with get_db() as conn:
        # An empty snapshot: the mark did not exist when the scan validated paths.
        assert without_manual_overlaps(conn, identity_photo, [record], review_states={}) == []


def test_scan_heals_the_stored_stat_after_a_metadata_only_rewrite(edition_client, identity_photo, monkeypatch):
    from db.manual_faces import validate_review_paths, without_manual_overlaps
    from db import DEFAULT_DB_PATH
    from utils import manual_face_frame as frames
    _mark(edition_client, identity_photo)
    _replace_metadata(identity_photo)
    states = validate_review_paths(DEFAULT_DB_PATH, [identity_photo])
    assert list(states.values()) == [True]
    with get_db() as conn:
        without_manual_overlaps(conn, identity_photo, [], review_states=states)
        conn.commit()
    frames.clear_cache()
    def forbidden(path):
        pytest.fail('A healed mark was decoded again on the next scan')
    monkeypatch.setattr(frames, 'load_image_for_face_crop', forbidden)
    assert list(validate_review_paths(DEFAULT_DB_PATH, [identity_photo]).values()) == [True]


def test_relink_unverified_identity_is_never_current_even_with_a_matching_stat(identity_photo):
    from utils import manual_face_frame as frames
    stored = frames.source_identity(identity_photo)
    assert frames.is_current(identity_photo, stored) is True
    unverified = json.dumps({**json.loads(stored), 'relink_unverified': True}, separators=(',', ':'))
    assert frames.is_current(identity_photo, unverified) is False
