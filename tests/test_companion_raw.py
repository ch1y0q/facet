"""Companion discovery preserves filesystem names without enumerating a library."""
import os
from pathlib import Path
import sys

import pytest

from api import raw_processing


pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='macOS spelling regression; Windows lookup is unchanged')


@pytest.fixture(autouse=True)
def clear_companion_cache():
    raw_processing._companion_raw_cache.clear()
    yield
    raw_processing._companion_raw_cache.clear()


def test_companion_uses_the_existing_filename(tmp_path):
    photo = tmp_path / 'shot.jpg'
    photo.write_bytes(b'JPEG fixture')
    raw = tmp_path / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')

    found = raw_processing.find_companion_raw(str(photo))
    assert found == str(raw)
    assert Path(found).read_bytes() == b'RAW fixture'


def test_companion_preserves_the_symlink_entry_name(tmp_path):
    library = tmp_path / 'library'
    library.mkdir()
    target = tmp_path / 'foreign.bin'
    target.write_bytes(b'linked RAW fixture')
    photo = library / 'shot.jpg'
    photo.write_bytes(b'JPEG fixture')
    raw = library / 'shot.CR2'
    raw.symlink_to(target)

    found = raw_processing.find_companion_raw(str(photo))
    assert found == str(raw)
    assert Path(found).is_symlink()
    assert Path(found).parent == library
    assert Path(found).read_bytes() == b'linked RAW fixture'


def test_extension_precedence_is_unchanged(tmp_path):
    preferred = tmp_path / 'shot.NEF'
    preferred.write_bytes(b'first extension')
    other = tmp_path / 'shot.CR2'
    other.write_bytes(b'second extension')

    found = raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.nef', '.cr2'))
    assert found == str(preferred)
    assert other.read_bytes() == b'second extension'


def test_raw_input_is_returned_without_companion_lookup(tmp_path, monkeypatch):
    raw = tmp_path / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')
    monkeypatch.setattr(raw_processing, '_find_companion_raw_cached', lambda *args: pytest.fail('RAW input was searched again'))
    assert raw_processing.find_companion_raw(str(raw)) == str(raw)


@pytest.mark.parametrize('exists', [False, True])
def test_cold_lookup_is_independent_of_directory_size_and_warm_lookup_skips_candidate_probes(tmp_path, monkeypatch, exists):
    for i in range(500):
        (tmp_path / f'unrelated-{i}.jpg').write_bytes(b'unrelated fixture')
    raw = tmp_path / 'shot.CR2'
    if exists:
        raw.write_bytes(b'RAW fixture')
    probes = []
    real_is_file = Path.is_file
    real_open = os.open
    opens = []

    def open_path(*args, **kwargs):
        opens.append(args[0])
        return real_open(*args, **kwargs)

    def is_file(path):
        probes.append(path)
        return real_is_file(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'is_file', is_file)
        patch.setattr(raw_processing.os, 'open', open_path)
        patch.setattr(raw_processing.os, 'scandir', lambda *args: pytest.fail('companion lookup enumerated the directory'))
        first = raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2', '.nef'))
        cold_probes = len(probes)
        assert 1 <= cold_probes <= 4
        native_opens = int(exists and sys.platform == 'darwin')
        assert len(opens) == native_opens
        second = raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2', '.nef'))
        assert len(probes) == cold_probes
        assert len(opens) == 2 * native_opens
    assert first == second == (str(raw) if exists else None)


@pytest.mark.parametrize('action', ['copy_keeps', 'move_rejects'])
@pytest.mark.parametrize('include_companions', [False, True])
def test_cull_keeps_companion_filename_and_bytes(edition_client, seed_photos_prefix, tmp_path, monkeypatch, action, include_companions):
    from api import config

    source = tmp_path / 'source'
    source.mkdir()
    target = tmp_path / 'out'
    photo = source / 'shot.jpg'
    photo.write_bytes(b'JPEG fixture')
    raw = source / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')
    unrelated = source / 'unrelated.CR2'
    unrelated.write_bytes(b'unrelated fixture')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(source)])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'export', {'allowed_target_dirs': [str(target)]})
    seed_photos_prefix(str(source), [{'path': str(photo), 'filename': photo.name, 'is_rejected': int(action == 'move_rejects')}])
    body = {'paths': [str(photo)], 'action': action, 'target_dir': str(target), 'include_companions': include_companions}
    preview = edition_client.post('/api/cull/apply', json=body)
    assert preview.status_code == 200, preview.text
    assert not target.exists()
    assert photo.read_bytes() == b'JPEG fixture'
    assert raw.read_bytes() == b'RAW fixture'

    applied = edition_client.post('/api/cull/apply', json={**body, 'dry_run': False})
    assert applied.status_code == 200, applied.text
    verb = 'copied' if action == 'copy_keeps' else 'moved'
    assert applied.json()[verb] == 1 + int(include_companions)
    assert applied.json()['errors'] == 0
    assert sorted(path.name for path in target.iterdir()) == (['shot.CR2', 'shot.jpg'] if include_companions else ['shot.jpg'])
    assert (target / 'shot.jpg').read_bytes() == b'JPEG fixture'
    if include_companions:
        assert (target / 'shot.CR2').read_bytes() == b'RAW fixture'
    assert raw.exists() == (action == 'copy_keeps' or not include_companions)
    assert unrelated.read_bytes() == b'unrelated fixture'


def test_raw_download_uses_the_companions_actual_filename(edition_client, seed_photos_prefix, tmp_path, monkeypatch):
    from api import config

    photo = tmp_path / 'shot.jpg'
    photo.write_bytes(b'JPEG fixture')
    raw = tmp_path / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    seed_photos_prefix(str(tmp_path), [{'path': str(photo), 'filename': photo.name}])
    response = edition_client.get('/api/download', params={'path': str(photo), 'type': 'raw'})
    assert response.status_code == 200, response.text
    assert response.content == b'RAW fixture'
    assert 'filename="shot.CR2"' in response.headers['content-disposition']
    assert raw.read_bytes() == b'RAW fixture'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS directory-entry spelling')
def test_cached_companion_tracks_a_case_only_rename(tmp_path):
    raw = tmp_path / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')
    renamed = tmp_path / 'shot.cr2'
    if not renamed.is_file():
        pytest.skip('requires a case-insensitive filesystem')
    assert raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2',)) == str(raw)
    raw.rename(renamed)
    assert raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2',)) == str(renamed)
    assert renamed.read_bytes() == b'RAW fixture'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native filename lookup')
def test_failed_native_lookup_closes_its_descriptor_and_can_retry(tmp_path, monkeypatch):
    import fcntl

    raw = tmp_path / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')
    descriptors = []
    real_fcntl = fcntl.fcntl

    def read_path(descriptor, *args):
        descriptors.append(descriptor)
        if len(descriptors) == 1:
            raise OSError('temporary filename lookup failure')
        return real_fcntl(descriptor, *args)

    monkeypatch.setattr(fcntl, 'fcntl', read_path)
    with pytest.raises(OSError, match='temporary filename lookup failure'):
        raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2',))
    assert raw_processing._companion_raw_cache == {}
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2',)) == str(raw)
    with pytest.raises(OSError):
        os.fstat(descriptors[1])


def test_companion_keeps_a_symlinked_parent_path(tmp_path):
    folder = tmp_path / 'original'
    folder.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(folder, target_is_directory=True)
    (folder / 'shot.jpg').write_bytes(b'JPEG fixture')
    (folder / 'shot.CR2').write_bytes(b'RAW fixture')
    found = raw_processing.find_companion_raw(str(alias / 'shot.jpg'))
    assert found == str(alias / 'shot.CR2')
    assert Path(found).read_bytes() == b'RAW fixture'


def test_companion_keeps_the_filesystems_unicode_spelling(tmp_path):
    photo = tmp_path / 'café.jpg'
    photo.write_bytes(b'JPEG fixture')
    (tmp_path / 'café.CR2').write_bytes(b'RAW fixture')
    actual_name = next(name for name in os.listdir(tmp_path) if name.endswith('.CR2'))
    found = raw_processing.find_companion_raw(str(photo))
    assert found == str(tmp_path / actual_name)
    assert Path(found).read_bytes() == b'RAW fixture'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native filename lookup')
def test_native_lookup_refuses_a_file_renamed_to_another_stem(tmp_path, monkeypatch):
    import fcntl

    raw = tmp_path / 'shot.CR2'
    raw.write_bytes(b'RAW fixture')
    renamed = tmp_path / 'another.CR2'
    real_fcntl = fcntl.fcntl

    def rename_before_read(descriptor, *args):
        raw.rename(renamed)
        return real_fcntl(descriptor, *args)

    monkeypatch.setattr(fcntl, 'fcntl', rename_before_read)
    with pytest.raises(OSError, match='name changed during lookup'):
        raw_processing._find_companion_raw_cached('shot', str(tmp_path), ('.cr2',))
    assert raw_processing._companion_raw_cache == {}
    assert renamed.read_bytes() == b'RAW fixture'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native filename lookup')
def test_native_lookup_failure_refuses_culling_before_any_file_changes(edition_client, seed_photos_prefix, tmp_path, monkeypatch):
    import fcntl
    from fastapi.testclient import TestClient
    from api import config

    photo = tmp_path / 'shot.jpg'
    raw = tmp_path / 'shot.CR2'
    photo.write_bytes(b'JPEG fixture')
    raw.write_bytes(b'RAW fixture')
    target = tmp_path / 'out'
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'export', {'allowed_target_dirs': [str(target)]})
    seed_photos_prefix(str(tmp_path), [{'path': str(photo), 'filename': photo.name, 'is_rejected': 1}])

    def unavailable(*args):
        raise OSError('temporary native filename lookup failure')

    monkeypatch.setattr(fcntl, 'fcntl', unavailable)
    client = TestClient(edition_client.app, raise_server_exceptions=False)
    try:
        response = client.post('/api/cull/apply', json={'paths': [str(photo)], 'action': 'move_rejects',
            'target_dir': str(target), 'include_companions': True, 'dry_run': False})
    finally:
        client.close()
    assert response.status_code == 500
    assert str(tmp_path) not in response.text
    assert photo.read_bytes() == b'JPEG fixture'
    assert raw.read_bytes() == b'RAW fixture'
    assert not target.exists()
