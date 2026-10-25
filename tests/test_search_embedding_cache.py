"""Real SQLite regression coverage for the NumPy fallback matrix cache."""
import asyncio
import sqlite3
import threading

import aiosqlite
import numpy as np
import pytest

from api.change_token import close_change_token_sentinels
from api.routers import search


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(search, '_embedding_cache', None)
    monkeypatch.setattr(search, '_embedding_cache_lock', asyncio.Lock())
    yield
    close_change_token_sentinels()


def vector(axis):
    value = np.zeros(4, dtype=np.float32)
    value[axis] = 1
    return value.tobytes()


async def database(path):
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute('CREATE TABLE photos (path TEXT PRIMARY KEY, clip_embedding BLOB, owner INTEGER)')
    await conn.execute('INSERT INTO photos VALUES (?, ?, ?)', ('a', vector(0), 1))
    await conn.commit()
    return conn


async def load(conn, sql='1=1', params=(), user=None):
    return await search._load_embedding_matrix(conn, sql, params, user)


@pytest.mark.asyncio
async def test_external_same_count_embedding_update_and_delete_add(tmp_path):
    path = tmp_path / 'photos.db'
    conn = await database(path)
    try:
        first, _ = await load(conn)
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        second, paths = await load(conn)
        np.testing.assert_array_equal(second, [np.frombuffer(vector(1), dtype=np.float32)])
        assert second is not first
        with sqlite3.connect(path) as writer:
            writer.execute('DELETE FROM photos')
            writer.execute('INSERT INTO photos VALUES (?, ?, ?)', ('b', vector(2), 1))
        third, paths = await load(conn)
        assert paths == ['b']
        np.testing.assert_array_equal(third, [np.frombuffer(vector(2), dtype=np.float32)])
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_database_identity_and_stable_reads_across_connections(tmp_path):
    one = await database(tmp_path / 'one.db')
    two = await database(tmp_path / 'two.db')
    reader = await aiosqlite.connect(tmp_path / 'one.db')
    reader.row_factory = aiosqlite.Row
    try:
        await two.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        await two.commit()
        first, _ = await load(one)
        reused, _ = await load(reader)
        assert reused is first
        second, _ = await load(two)
        assert second is not first
        np.testing.assert_array_equal(second, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await one.close()
        await two.close()
        await reader.close()


@pytest.mark.asyncio
async def test_visibility_scope_and_user_are_both_part_of_key(tmp_path):
    conn = await database(tmp_path / 'photos.db')
    try:
        await conn.execute('INSERT INTO photos VALUES (?, ?, ?)', ('b', vector(1), 2))
        await conn.commit()
        first, paths = await load(conn, 'owner=?', (1,), 1)
        assert paths == ['a']
        second, paths = await load(conn, 'owner=?', (2,), 1)
        assert paths == ['b']  # same user, changed allowed directories
        third, _ = await load(conn, 'owner=?', (2,), 2)
        assert third is not second
        fourth, paths = await load(conn, 'owner=1', (), 2)
        assert paths == ['a']  # same user, changed predicate text
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_memory_databases_and_own_writes():
    one = await database(':memory:')
    two = await database(':memory:')
    try:
        first, _ = await load(one)
        assert (await load(one))[0] is first
        await one.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        await one.commit()
        changed, _ = await load(one)
        np.testing.assert_array_equal(changed, [np.frombuffer(vector(1), dtype=np.float32)])
        other, _ = await load(two)
        np.testing.assert_array_equal(other, [np.frombuffer(vector(0), dtype=np.float32)])
    finally:
        await one.close()
        await two.close()


@pytest.mark.asyncio
async def test_transaction_result_does_not_poison_shared_cache(tmp_path):
    conn = await database(tmp_path / 'photos.db')
    try:
        first, _ = await load(conn)
        await conn.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        pending, _ = await load(conn)
        np.testing.assert_array_equal(pending, [np.frombuffer(vector(1), dtype=np.float32)])
        await conn.rollback()
        assert (await load(conn))[0] is first
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_concurrent_misses_build_once(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'photos.db')
    started = threading.Event()
    release = threading.Event()
    original = np.stack
    builds = []

    def blocked_stack(*args, **kwargs):
        builds.append(1)
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(np, 'stack', blocked_stack)
    tasks = [asyncio.create_task(load(conn)) for _ in range(5)]
    try:
        assert await asyncio.to_thread(started.wait, 5)
        # Give all five callers a chance to reach construction if the guard is
        # removed: merely checking sequential cache hits would miss this bug.
        await asyncio.sleep(0.05)
        release.set()
        results = await asyncio.gather(*tasks)
        assert len(builds) == 1
        assert all(matrix is results[0][0] for matrix, _ in results)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await conn.close()


@pytest.mark.asyncio
async def test_commit_during_build_does_not_publish_under_new_token(tmp_path, monkeypatch):
    path = tmp_path / 'photos.db'
    conn = await database(path)
    original = np.stack

    def change_during_build(*args, **kwargs):
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        return original(*args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(np, 'stack', change_during_build)
            first, _ = await load(conn)
        second, _ = await load(conn)
        assert second is not first
        np.testing.assert_array_equal(second, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_empty_matrix_is_reused_until_embedding_appears(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'photos.db')
    try:
        await conn.execute('DELETE FROM photos')
        await conn.commit()
        calls = []
        original = asyncio.to_thread

        async def counted(*args, **kwargs):
            calls.append(1)
            return await original(*args, **kwargs)

        monkeypatch.setattr(asyncio, 'to_thread', counted)
        assert await load(conn) == (None, [])
        assert await load(conn) == (None, [])
        assert len(calls) == 1
        await conn.execute('INSERT INTO photos VALUES (?, ?, ?)', ('new', vector(0), 1))
        await conn.commit()
        matrix, paths = await load(conn)
        assert paths == ['new']
        assert matrix is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_atomic_replacement_old_reader_cannot_poison_new_file(tmp_path):
    path = tmp_path / 'photos.db'
    replacement_path = tmp_path / 'replacement.db'
    old = await database(path)
    replacement = await database(replacement_path)
    fresh = None
    try:
        # Establish the old reader's open inode, and a cached old generation.
        first, _ = await load(old)
        await replacement.execute('DELETE FROM photos')
        await replacement.execute('INSERT INTO photos VALUES (?, ?, ?)', ('new', vector(1), 1))
        await replacement.commit()
        await replacement.close()
        replacement = None
        replacement_path.replace(path)
        # Prove this is a stale live SQLite handle, not a pathname-only mock.
        async with old.execute('SELECT path FROM photos') as cur:
            assert (await cur.fetchone())[0] == 'a'
        through_old, paths = await load(old)
        assert paths == ['new']
        assert through_old is not first
        fresh = await aiosqlite.connect(path)
        fresh.row_factory = aiosqlite.Row
        current, paths = await load(fresh)
        assert paths == ['new']
        assert current is through_old
        np.testing.assert_array_equal(current, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await old.close()
        if replacement is not None:
            await replacement.close()
        if fresh is not None:
            await fresh.close()


@pytest.mark.asyncio
async def test_cancelled_builder_drains_before_releasing_lock(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'photos.db')
    started = threading.Event()
    release = threading.Event()
    original = np.stack
    builds = []

    def blocked_stack(*args, **kwargs):
        builds.append(1)
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(np, 'stack', blocked_stack)
    first = asyncio.create_task(load(conn))
    second = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        second = asyncio.create_task(load(conn))
        await asyncio.sleep(0.05)
        first.cancel()  # repeated request cancellation cannot release the guard
        await asyncio.sleep(0.05)
        assert not first.done()
        assert not second.done()
        assert len(builds) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        matrix, paths = await second
        assert paths == ['a']
        assert len(builds) == 1
        assert (await load(conn))[0] is matrix
        assert not search._embedding_cache_lock.locked()
    finally:
        release.set()
        await asyncio.gather(*(t for t in (first, second) if t is not None), return_exceptions=True)
        await conn.close()
