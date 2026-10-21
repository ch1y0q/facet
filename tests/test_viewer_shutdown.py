"""viewer.main bounds uvicorn's graceful shutdown.

uvicorn waits for every in-flight request before a worker exits, and its default
is to wait forever, so one request that never finished hung a --reload after a
source edit, a Ctrl+C or a container stop, with new requests queueing unanswered.
"""

import sys

import pytest


@pytest.mark.parametrize("argv", [["viewer.py"], ["viewer.py", "--production"]],
                         ids=["reload", "production"])
def test_viewer_bounds_the_graceful_shutdown(monkeypatch, argv):
    import uvicorn

    import viewer

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    monkeypatch.setattr(sys, "argv", argv)

    viewer.main()

    assert seen["timeout_graceful_shutdown"] == viewer.GRACEFUL_SHUTDOWN_SECONDS
    assert 0 < viewer.GRACEFUL_SHUTDOWN_SECONDS <= 10
