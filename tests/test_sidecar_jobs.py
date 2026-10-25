"""Real lock/receipt tests; cancellation never interrupts a file write."""
from pathlib import Path
import threading
import time

import pytest

from api import sidecar_jobs as jobs
from db.schema import init_database
from facet import LibraryLockError, library_job_holder


@pytest.fixture
def library(tmp_path):
    path = str(tmp_path / 'library.db')
    init_database(path)
    return path


def _done(library, job_id, owner='alice'):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = jobs.status(library, job_id, owner)
        if result['state'] != 'running' and library_job_holder(library) is None:
            return result
        threading.Event().wait(0.005)
    pytest.fail('export worker did not settle')


def test_one_active_library_job_and_cancel_between_files(library):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def work(path):
        calls.append(path)
        entered.set()
        assert release.wait(5)
        return {'written': 1, 'skipped': 0, 'errors': 0}
    state = jobs.start(library, 'alice', ['first', 'second'], work)
    try:
        assert entered.wait(3)
        assert state['total'] == 2
        with pytest.raises(LibraryLockError):
            jobs.start(library, 'alice', ['other'], work)
        assert jobs.cancel(library, state['id'], 'alice')['cancel_requested']
        # Cancellation has not torn a file write in half.
        assert calls == ['first']
    finally:
        release.set()
    result = _done(library, state['id'])
    assert result['state'] == 'cancelled'
    assert result['processed'] == result['written'] == 1
    assert calls == ['first']
    assert 'owner' not in result


def test_receipts_are_private_and_path_ids_cannot_escape(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    with pytest.raises(LookupError):
        jobs.status(library, state['id'], 'bob')
    with pytest.raises(LookupError):
        jobs.cancel(library, state['id'], 'bob')
    with pytest.raises(LookupError):
        jobs.status(library, '../../secret', 'alice')
    assert jobs._path(library, state['id']).stat().st_mode & 0o077 == 0


def test_failed_worker_releases_lock_and_retains_confirmed_counts(library):
    def work(path):
        if path == 'second':
            raise OSError('do not expose this secret')
        return {'written': 0, 'skipped': 0, 'errors': 1, 'first_error': 'metadata failed'}
    state = jobs.start(library, 'alice', ['first', 'second'], work)
    result = _done(library, state['id'])
    assert result['state'] == 'failed'
    assert result['processed'] == result['errors'] == 1
    assert 'secret' not in result['first_error']
    other = jobs.start(library, 'alice', [], lambda path: None)
    assert _done(library, other['id'])['state'] == 'completed'


def test_dead_receipt_is_interrupted_without_trusting_a_recycled_pid(library):
    from uuid import uuid4
    job_id = str(uuid4())
    path = jobs._path(library, job_id)
    state = {'id': job_id, 'owner': 'alice', 'state': 'running', 'started_at': 0,
             'total': 3, 'processed': 1, 'written': 1, 'skipped': 0, 'errors': 0, 'first_error': None}
    jobs._write(path, state)
    assert jobs.status(library, job_id, 'alice')['state'] == 'interrupted'
    assert jobs._read(path) == state  # poll cannot race-write over a terminal receipt


def test_prune_retains_twenty_receipts_and_other_principals(library):
    from uuid import uuid4
    for owner in ('alice', 'bob'):
        for index in range(25):
            job_id = str(uuid4())
            jobs._write(jobs._path(library, job_id), {'owner': owner, 'state': 'running', 'started_at': index})
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    receipts = [jobs._read(p) for p in jobs._directory(library).glob('*.json')]
    assert sum(r['owner'] == 'alice' for r in receipts) == 20
    assert sum(r['owner'] == 'bob' for r in receipts) == 25


def test_start_failure_releases_library_admission(library, monkeypatch):
    def fail(*args):
        raise OSError('no space')
    monkeypatch.setattr(jobs, '_write', fail)
    with pytest.raises(OSError):
        jobs.start(library, 'alice', [], lambda path: None)
    assert library_job_holder(library) is None


def test_api_returns_before_export_completes_and_rechecks_visibility(edition_client, tmp_path, seed_photos_prefix, monkeypatch):
    from api import config
    from api.routers import export
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    paths = [str(tmp_path / name) for name in ('one.jpg', 'two.jpg')]
    for path in paths:
        Path(path).write_bytes(b'temporary test media')
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': Path(path).name} for path in paths])
    entered, release = threading.Event(), threading.Event()
    calls = []
    def write(path, *args, **kwargs):
        calls.append(path)
        entered.set()
        assert release.wait(5)
        return {'sidecar': path + '.xmp'}
    monkeypatch.setattr(export, 'write_metadata', write)
    response = edition_client.post('/api/export/sidecar_jobs', json={'paths': paths})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    try:
        assert entered.wait(3)
        response = edition_client.get(f'/api/export/sidecar_jobs/{job_id}')
        assert response.json()['processed'] == 0
        assert edition_client.post('/api/export/sidecar_jobs', json={'paths': paths}).status_code == 409
        # Revocation of filesystem scope prevents the next file write.
        monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path / 'other')])
    finally:
        release.set()
    from api.database import DEFAULT_DB_PATH
    owner = jobs._read(jobs._path(DEFAULT_DB_PATH, job_id))['owner']
    result = _done(DEFAULT_DB_PATH, job_id, owner)
    assert result['written'] == result['skipped'] == 1
    assert result['processed'] == 2
    assert calls == [paths[0]]


def test_retry_plan_contains_failures_skips_and_unprocessed_tail(library):
    entered, release = threading.Event(), threading.Event()
    def work(path):
        if path == 'first':
            return {'written': 0, 'skipped': 0, 'errors': 1}
        entered.set()
        assert release.wait(5)
        return {'written': 1, 'skipped': 0, 'errors': 0}
    state = jobs.start(library, 'alice', ['first', 'second', 'third'], work, overwrite=True)
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError, match='still running'):
            jobs.remaining(library, state['id'], 'alice')
        jobs.cancel(library, state['id'], 'alice')
    finally:
        release.set()
    _done(library, state['id'])
    assert jobs.remaining(library, state['id'], 'alice') == (['first', 'third'], True)
    assert [r['id'] for r in jobs.recent(library, 'alice')] == [state['id']]
    assert jobs.recent(library, 'bob') == []
    with pytest.raises(LookupError):
        jobs.remaining(library, state['id'], 'bob')


def test_interrupted_receipt_retries_unknown_file_explicitly(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    old = jobs._read(path)
    old.update(state='running', total=2, processed=1, written=1)
    jobs._write(path, old)
    jobs._write(path.with_suffix('.plan'), {'owner': 'alice', 'paths': ['done', 'unknown'], 'overwrite': False})
    assert jobs.remaining(library, state['id'], 'alice') == (['unknown'], False)


def test_corrupt_receipt_does_not_break_recent_job_recovery(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    malformed = jobs._read(path)
    malformed['processed'] = 1  # total remains zero
    jobs._write(path, malformed)
    with pytest.raises(LookupError):
        jobs.status(library, state['id'], 'alice')
    assert jobs.recent(library, 'alice') == []


@pytest.mark.parametrize('cleanup_failure', ['plan', 'lock'])
def test_admission_cleanup_failure_cannot_hang_caller(library, monkeypatch, cleanup_failure):
    import facet
    original_write = jobs._write
    def write(path, state):
        if path.suffix == '.json':
            raise OSError('receipt write failed')
        return original_write(path, state)
    monkeypatch.setattr(jobs, '_write', write)
    if cleanup_failure == 'plan':
        unlink = Path.unlink
        def refuse_plan(path, *args, **kwargs):
            if path.suffix == '.plan':
                raise PermissionError('cleanup refused')
            return unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', refuse_plan)
    else:
        release = facet.LibraryLock.release
        def fail_release(lock):
            release(lock)
            raise OSError('release cleanup failed')
        monkeypatch.setattr(facet.LibraryLock, 'release', fail_release)
    settled = threading.Event()
    failures = []
    def call():
        try:
            jobs.start(library, 'alice', [], lambda path: None)
        except Exception as ex:
            failures.append(ex)
        finally:
            settled.set()
    caller = threading.Thread(target=call, daemon=True)
    caller.start()
    assert settled.wait(3), 'admission cleanup left the caller blocked'
    caller.join(1)
    assert len(failures) == 1 and 'receipt write failed' in str(failures[0])
    assert library_job_holder(library) is None


def test_retry_rereads_confirmed_progress_after_completion_race(library, monkeypatch):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    old = jobs._read(path)
    old.update(state='running', total=1)
    jobs._write(path, old)
    jobs._write(path.with_suffix('.plan'), {'owner': 'alice', 'paths': ['done'], 'overwrite': False})
    status = jobs.status
    def complete_then_status(*args):
        current = jobs._read(path)
        current.update(state='completed', processed=1, written=1)
        jobs._write(path, current)
        return status(*args)
    monkeypatch.setattr(jobs, 'status', complete_then_status)
    assert jobs.remaining(library, state['id'], 'alice') == ([], False)


@pytest.mark.parametrize('bad_timestamp', ['not-a-time', None, float('nan')])
def test_malformed_timestamp_does_not_block_history_or_new_admission(library, bad_timestamp):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    corrupt = jobs._read(path)
    corrupt['started_at'] = bad_timestamp
    jobs._write(path, corrupt)
    assert jobs.recent(library, 'alice') == []
    another = jobs.start(library, 'alice', [], lambda path: None)
    assert _done(library, another['id'])['state'] == 'completed'
    assert len(jobs.recent(library, 'alice')) == 1
