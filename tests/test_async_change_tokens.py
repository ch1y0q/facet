"""Async token consumers keep synchronous sentinel I/O outside the loop."""
import asyncio

import aiosqlite
import pytest
from fastapi import HTTPException

from api import change_token, database, db_helpers
from api.routers import gallery
from db.schema import init_database


@pytest.mark.asyncio
@pytest.mark.parametrize('consumer', ['count', 'hidden', 'similar'])
async def test_async_token_reads_run_in_worker_on_repeated_requests(tmp_path, monkeypatch, consumer):
    path = str(tmp_path / 'tokens.db')
    init_database(path)
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', path)
    monkeypatch.setattr(db_helpers, '_count_cache', {})
    original = change_token.db_change_token
    calls = []

    def guarded_token(db_path):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            pytest.fail('cache token performs synchronous I/O on the event loop')
        calls.append(db_path)
        return original(db_path)

    monkeypatch.setattr(db_helpers, 'db_change_token', guarded_token)
    monkeypatch.setattr(gallery, 'db_change_token', guarded_token)
    if consumer == 'similar':
        for _ in range(2):
            with pytest.raises(HTTPException) as error:
                await gallery.api_similar_photos('/missing.jpg', mode='color', min_similarity=.5,
                                                 offset=0, limit=5, full=0, user=None)
            assert error.value.status_code == 404
    else:
        async with aiosqlite.connect(path) as conn:
            conn.row_factory = aiosqlite.Row
            function = db_helpers.get_cached_count_async if consumer == 'count' else db_helpers.get_cached_hidden_aggregates_async
            first = await function(conn, '', [])
            assert await function(conn, '', []) == first
    assert calls == [path, path]
