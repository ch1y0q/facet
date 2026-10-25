"""Native receipt IO: atomic publication while readers hold old snapshots."""
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
