"""Shared sidecar-job test helper."""
import threading
import time

import pytest


def settle_sidecar_job(db_path, job_id, owner, timeout=5):
    """Wait until the job is terminal AND its worker has released the library lock."""
    from api import sidecar_jobs
    from facet import library_job_holder
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = sidecar_jobs.status(db_path, job_id, owner)
        if result['state'] != 'running' and library_job_holder(db_path) is None:
            return result
        threading.Event().wait(0.005)
    pytest.fail('sidecar worker did not finish and release its library lock')
