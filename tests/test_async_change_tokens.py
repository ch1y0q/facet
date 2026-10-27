"""Async token consumers keep synchronous sentinel I/O outside the loop."""
import sqlite3
from contextlib import closing

import aiosqlite
import numpy as np
import pytest

from api import change_token, database, db_helpers, visual_similarity
from api.routers import gallery
from db.schema import init_database

PHASH = '0' * 16


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A real schema with two photos, one of them similar to the other, as the default database."""
    path = str(tmp_path / 'tokens.db')
    init_database(path, build_photo_indexes=False)
    vector = np.ones(4, dtype=np.float32).tobytes()
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executemany(
            'INSERT INTO photos(path, filename, phash, clip_embedding) VALUES (?,?,?,?)',
            [('/a.jpg', 'a.jpg', PHASH, vector), ('/b.jpg', 'b.jpg', PHASH, vector)])
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', path)
    monkeypatch.setattr(db_helpers, '_count_cache', {})
    visual_similarity.clear_ranking_cache()
    yield path
    visual_similarity.clear_ranking_cache()
    change_token.close_change_token_sentinels()


@pytest.fixture
def token_calls(monkeypatch, off_event_loop):
    calls = []
    original = change_token.db_change_token

    def record(db_path):
        calls.append(db_path)
        return original(db_path)

    guarded = off_event_loop(record, 'cache token performs synchronous I/O on the event loop')
    monkeypatch.setattr(db_helpers, 'db_change_token', guarded)
    monkeypatch.setattr(gallery, 'db_change_token', guarded)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('consumer', ['count', 'hidden'])
async def test_cached_aggregate_reads_token_off_loop_and_queries_once(library, token_calls, monkeypatch, consumer):
    queries = []
    original_execute = aiosqlite.Connection.execute

    def spy(connection, sql, *args, **kwargs):
        if sql.lstrip().startswith('SELECT COUNT(*)'):
            queries.append(sql)
        return original_execute(connection, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, 'execute', spy)
    function = db_helpers.get_cached_count_async if consumer == 'count' else db_helpers.get_cached_hidden_aggregates_async
    async with aiosqlite.connect(library) as conn:
        conn.row_factory = aiosqlite.Row
        first = await function(conn, '', [])
        assert await function(conn, '', []) == first
    assert token_calls == [library, library]
    assert len(queries) == 1  # the warm read was served from the cache


@pytest.mark.asyncio
async def test_similar_reads_token_off_loop_and_ranks_once(library, token_calls, monkeypatch):
    rankings = []
    original_rank = visual_similarity.rank_visual

    def spy(*args, **kwargs):
        rankings.append(args[2])
        return original_rank(*args, **kwargs)

    monkeypatch.setattr(visual_similarity, 'rank_visual', spy)
    pages = [await gallery.api_similar_photos('/a.jpg', mode='visual', min_similarity=.5,
                                              offset=0, limit=5, full=0, user=None)
             for _ in range(2)]
    assert [item['path'] for item in pages[0]['similar']] == ['/b.jpg']
    assert pages[1] == pages[0]
    assert token_calls == [library, library]
    assert rankings == ['/a.jpg']  # the warm request reused the cached ranking


@pytest.mark.asyncio
async def test_similar_unknown_source_is_404_after_an_off_loop_token_read(library, token_calls):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await gallery.api_similar_photos('/missing.jpg', mode='visual', min_similarity=.5,
                                         offset=0, limit=5, full=0, user=None)
    assert error.value.status_code == 404
    assert token_calls == [library]
