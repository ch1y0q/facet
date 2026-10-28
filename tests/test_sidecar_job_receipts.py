"""Native receipt IO: atomic publication while readers hold old snapshots."""
import json
import os
from pathlib import Path
import threading

import pytest

from api import sidecar_jobs as jobs

def test_progress_replacement_while_receipt_reader_is_open(tmp_path, monkeypatch):
    """Also exercises native SHARE_DELETE on Windows; no mocked filesystem API."""
    path = tmp_path / 'receipt.json'
    jobs._write(path, {'version': 1})
    reading, release = threading.Event(), threading.Event()
    original_load = jobs.json.load
    def paused_load(handle):
        reading.set()
        assert release.wait(5)
        return original_load(handle)
    monkeypatch.setattr(jobs.json, 'load', paused_load)
    results, errors = [], []
    def read():
        try:
            results.append(jobs._read(path))
        except BaseException as ex:
            errors.append(ex)
    reader = threading.Thread(target=read)
    reader.start()
    try:
        assert reading.wait(3)
        jobs._write(path, {'version': 2})
    finally:
        release.set()
        reader.join(5)
    assert not reader.is_alive()
    assert errors == []
    assert results == [{'version': 1}]
    assert jobs._read(path) == {'version': 2}



@pytest.mark.parametrize('content', [b'{invalid JSON', b'\xff'])
def test_invalid_receipt_closes_reader_before_replacement(tmp_path, content):
    path = tmp_path / 'receipt.json'
    path.write_bytes(content)
    with pytest.raises(LookupError):
        jobs._read(path)
    jobs._write(path, {'recovered': True})
    assert jobs._read(path) == {'recovered': True}
    path.unlink()  # Native Windows removal proves the read handle was closed.


def test_missing_receipt_open_failure_allows_later_publication(tmp_path):
    path = tmp_path / 'receipt.json'
    with pytest.raises(LookupError):
        jobs._read(path)
    jobs._write(path, {'published': True})
    assert jobs._read(path) == {'published': True}
    path.unlink()


def test_prepublication_refusal_preserves_previous_receipt_and_cleans_temporary(tmp_path, monkeypatch):
    path = tmp_path / 'receipt.json'
    jobs._write(path, {'version': 1})
    previous = path.read_bytes()
    attempted = []
    def refuse(temporary, destination):
        assert destination == path
        attempted.append(temporary)
        # The replacement was staged under its own name, never over the receipt.
        assert Path(temporary).parent == tmp_path and Path(temporary) != path
        assert json.loads(Path(temporary).read_text(encoding='utf-8')) == {'version': 2}
        raise PermissionError('publication refused')
    monkeypatch.setattr(jobs, '_replace_receipt', refuse)
    with pytest.raises(PermissionError, match='publication refused'):
        jobs._write(path, {'version': 2})
    assert len(attempted) == 1 and not os.path.exists(attempted[0])
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


def _stub_replace_file(monkeypatch, tmp_path, error, replace_file=None):
    """Run ``_write`` down the Windows branch with ReplaceFileW stubbed to fail with ``error``."""
    import ctypes
    calls = []
    def refuse(replaced, replacement, backup, flags, exclude, reserved):
        calls.append((replaced, replacement))
        return 0
    kernel = type('Kernel', (), {'ReplaceFileW': staticmethod(replace_file or refuse)})()
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error, raising=False)
    monkeypatch.setattr(ctypes, 'WinError', lambda code: OSError(code, 'ReplaceFile'), raising=False)
    monkeypatch.setattr(jobs.os, 'name', 'nt')
    return calls


def test_replace_file_access_denied_raises_and_keeps_previous_receipt(tmp_path, monkeypatch):
    """ERROR_ACCESS_DENIED (5) is not a 1176/1177 state: surface it, never fall back to os.replace."""
    path = tmp_path / 'receipt.json'
    jobs._write(path, {'version': 1})
    previous = path.read_bytes()
    calls = _stub_replace_file(monkeypatch, tmp_path, 5)
    with pytest.raises(OSError) as raised:
        jobs._write(path, {'version': 2})
    monkeypatch.undo()
    assert raised.value.errno == 5
    assert len(calls) == 1 and calls[0][0] == str(path)
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


def test_replace_file_without_destination_publishes_initial_receipt(tmp_path, monkeypatch):
    """ERROR_FILE_NOT_FOUND (2): first publication has no destination, so the plain replace runs."""
    path = tmp_path / 'receipt.json'
    calls = _stub_replace_file(monkeypatch, tmp_path, 2)
    jobs._write(path, {'version': 1})
    monkeypatch.undo()
    assert len(calls) == 1
    assert jobs._read(path) == {'version': 1}
    assert list(tmp_path.iterdir()) == [path]


def test_repeated_publication_keeps_each_open_reader_on_its_snapshot(tmp_path):
    path = tmp_path / 'receipt.json'
    jobs._write(path, {'version': 1})
    with jobs._open_receipt(path) as first:
        jobs._write(path, {'version': 2})
        with jobs._open_receipt(path) as second:
            jobs._write(path, {'version': 3})
            assert jobs.json.load(first) == {'version': 1}
            assert jobs.json.load(second) == {'version': 2}
            assert jobs._read(path) == {'version': 3}
    path.unlink()


@pytest.mark.parametrize('error', [1176, 1177])
def test_replace_file_that_removed_the_old_receipt_still_publishes(tmp_path, monkeypatch, error):
    """ReplaceFile can fail after moving the old receipt away; the new one must not be lost."""
    import ctypes
    path = tmp_path / 'receipt.json'
    path.write_text('{"version": 1}', encoding='utf-8')
    def replace_file(replaced, replacement, backup, flags, exclude, reserved):
        # Documented 1176/1177 state: the replaced file is gone from its name,
        # the replacement still sits under its temporary name.
        path.rename(tmp_path / 'moved-aside.json')
        return 0
    kernel = type('Kernel', (), {'ReplaceFileW': staticmethod(replace_file)})()
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error, raising=False)
    monkeypatch.setattr(ctypes, 'WinError', lambda code: OSError(code, 'ReplaceFile'), raising=False)
    monkeypatch.setattr(jobs.os, 'name', 'nt')
    jobs._write(path, {'version': 2})
    monkeypatch.undo()
    assert jobs._read(path) == {'version': 2}
    assert not list(tmp_path.glob('*.tmp'))
