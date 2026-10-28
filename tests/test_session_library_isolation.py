"""Different pytest workers must not compete for the same library lock."""
import tempfile

from db import DEFAULT_DB_PATH
from facet import LibraryLock


def test_another_workers_temp_database_does_not_share_our_library_lock():
    # Simulate a second process's old filename-only fixture. The lock is derived
    # from the database DIRECTORY, not the unique NamedTemporaryFile basename.
    # Before the fixture fix this is our own lock and acquire raises instead.
    with tempfile.NamedTemporaryFile(suffix='.db') as other_worker:
        own = LibraryLock(DEFAULT_DB_PATH, kind='test-isolation').acquire()
        other = LibraryLock(other_worker.name, kind='other-worker')
        try:
            other.acquire()
        finally:
            other.release()
            own.release()
