"""One admitted sidecar export per library, with cross-worker private receipts.

The existing OS library lock owns admission and crash recovery. JSON receipts
are diagnostic state, not a second source of lock ownership. Plans and receipts stay private in the library cache; request credentials
are never persisted; cancellation stops between complete files.
"""
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)
_KIND = 'sidecar-export:'
_TERMINAL = {'completed', 'cancelled', 'failed', 'interrupted'}


def _directory(db_path):
    from facet import _library_lock_path
    directory = Path(_library_lock_path(db_path)).parent / 'sidecar-jobs'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _path(db_path, job_id):
    try:
        if str(UUID(job_id)) != job_id:
            raise ValueError('invalid job ID')
    except (ValueError, TypeError, AttributeError) as ex:
        raise LookupError('Export job not found') from ex
    return _directory(db_path) / (job_id + '.json')


def _write(path, state):
    # NamedTemporaryFile is closed before replace for Windows. Both files are
    # confined to the app-owned cache folder; the mode keeps receipts private.
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read(path):
    try:
        with path.open(encoding='utf-8') as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError('invalid job record')
        return state
    except (OSError, ValueError) as ex:
        raise LookupError('Export job not found') from ex


def _owned(db_path, job_id, owner):
    path = _path(db_path, job_id)
    state = _read(path)
    try:
        from api.models.sidecar_jobs import SidecarJobStatus
        SidecarJobStatus.model_validate(state)
        if state['owner'] != owner:
            raise LookupError('Export job not found')
    except (ValueError, KeyError) as ex:
        raise LookupError('Export job not found') from ex
    return path, state


def status(db_path, job_id, owner):
    from facet import library_job_holder
    path, state = _owned(db_path, job_id, owner)
    if state['state'] not in _TERMINAL:
        holder = library_job_holder(db_path)
        if not holder or holder.get('kind') != _KIND + job_id:
            # Reread after probing: the worker may have just published its
            # terminal receipt and released the lock. Never overwrite it here.
            state = _read(path)
            if state['state'] not in _TERMINAL:
                state['state'] = 'interrupted'
    return {key: value for key, value in state.items() if key not in {'owner', 'retry'}} | {
        'cancel_requested': path.with_suffix('.cancel').exists()}


def cancel(db_path, job_id, owner):
    path, state = _owned(db_path, job_id, owner)
    if state['state'] not in _TERMINAL:
        fd = os.open(path.with_suffix('.cancel'), os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
    return status(db_path, job_id, owner)


def _prune(db_path, owner):
    # Keep the latest 20 terminal receipts per principal. Admission is locked;
    # this never removes an active job or a different user's receipt.
    receipts = []
    for path in _directory(db_path).glob('*.json'):
        try:
            state = _read(path)
            if state['owner'] == owner:
                # A newly admitted job holds the sole library lock, so older
                # nonterminal receipts necessarily belong to interrupted jobs.
                receipts.append((state['started_at'], path))
        except (LookupError, KeyError, TypeError):
            continue
    for _, path in sorted(receipts, reverse=True)[19:]:
        path.unlink(missing_ok=True)
        path.with_suffix('.cancel').unlink(missing_ok=True)
        path.with_suffix('.plan').unlink(missing_ok=True)


def start(db_path, owner, paths, work, *, overwrite=False):
    """Admit one bounded job; ``work(path)`` rechecks live visibility each time."""
    from facet import LibraryLock
    job_id = str(uuid4())
    state = {'id': job_id, 'owner': owner, 'state': 'running',
             'started_at': time.time(), 'total': len(paths), 'processed': 0,
             'written': 0, 'skipped': 0, 'errors': 0, 'first_error': None, 'retry': []}
    initial = {key: value for key, value in state.items() if key not in {'owner', 'retry'}} | {'cancel_requested': False}
    admitted = threading.Event()
    failures = []

    def admit_and_run():
        # Acquire/release on this worker. LibraryLock installs signal cleanup
        # only on the main thread; transferring a main-thread lock would try
        # to restore a signal handler from the worker during release.
        lock = LibraryLock(db_path, _KIND + job_id, origin='viewer')
        path = None
        try:
            lock.acquire()
            path = _path(db_path, job_id)
            _prune(db_path, owner)
            _write(path.with_suffix('.plan'), {'owner': owner, 'paths': list(paths), 'overwrite': overwrite})
            _write(path, state)
        except Exception as ex:
            lock.release()
            if path is not None:
                path.unlink(missing_ok=True)
                path.with_suffix('.plan').unlink(missing_ok=True)
            failures.append(ex)
            admitted.set()
            return
        admitted.set()
        _run(path, state, tuple(paths), work, lock)

    worker = threading.Thread(target=admit_and_run, name='facet-sidecar-export', daemon=True)
    worker.start()
    admitted.wait()  # Only lock admission/receipt IO; never waits for media work.
    if failures:
        raise failures[0]
    return initial


def _run(path, state, paths, work, lock):
    try:
        for index, photo in enumerate(paths):
            if path.with_suffix('.cancel').exists():
                state['state'] = 'cancelled'
                break
            result = work(photo)
            for key in ('written', 'skipped', 'errors'):
                state[key] += result[key]
            state['processed'] += 1
            if result['errors'] or result['skipped']:
                state['retry'].append(index)
            if result.get('first_error') and not state['first_error']:
                state['first_error'] = result['first_error'][:300]
            _write(path, state)
        else:
            state['state'] = 'completed'
    except Exception:
        logger.exception('Sidecar export job failed')
        state['state'] = 'failed'
        state['first_error'] = 'Export stopped unexpectedly; inspect server logs and retry remaining photos'
    finally:
        try:
            _write(path, state)
        finally:
            lock.release()


def recent(db_path, owner):
    """At most twenty private receipts, newest first, recoverable after restart."""
    rows = []
    for path in _directory(db_path).glob('*.json'):
        try:
            state = _read(path)
            if state['owner'] == owner:
                rows.append((state['started_at'], state['id']))
        except (LookupError, KeyError, TypeError):
            continue
    result = []
    for _, job_id in sorted(rows, reverse=True)[:20]:
        try:
            result.append(status(db_path, job_id, owner))
        except LookupError:
            continue
    return result


def remaining(db_path, job_id, owner):
    """Explicit retry includes failures/skips plus the unprocessed tail.

    An interrupted file may have finished before its receipt reached disk.
    Retrying is explicit, uses current metadata and never claims atomic rollback.
    """
    path, state = _owned(db_path, job_id, owner)
    if status(db_path, job_id, owner)['state'] == 'running':
        raise ValueError('Export is still running')
    plan = _read(path.with_suffix('.plan'))
    if plan.get('owner') != owner:
        raise LookupError('Export plan not found')
    paths = plan['paths']
    indices = sorted(set(state.get('retry', [])) | set(range(state['processed'], len(paths))))
    return [paths[index] for index in indices], bool(plan['overwrite'])
