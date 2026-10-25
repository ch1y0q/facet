"""Assignment picker uses production schema and SQL, before pagination."""
import sqlite3
from contextlib import asynccontextmanager

import aiosqlite
import pytest

from db.schema import init_database


@pytest.fixture()
def picker_db(tmp_path, monkeypatch):
    path = tmp_path / 'picker.db'
    init_database(str(path))
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO photos(path) VALUES ('/visible/a.jpg')")
    conn.execute("INSERT INTO photos(path) VALUES ('/private/a.jpg')")
    # Cached face_count deliberately contradicts the actual visible counts.
    for person_id in range(1, 56):
        conn.execute('INSERT INTO persons(id,name,face_count,is_hidden) VALUES (?,?,?,?)',
                     (person_id, f'Person {person_id:02}', 1000 if person_id == 1 else 0, int(person_id == 54)))
        if person_id != 55:
            conn.execute('INSERT INTO faces(photo_path,person_id,face_index,embedding) VALUES (?,?,?,?)', ('/visible/a.jpg', person_id, person_id, b'face'))
    for index in range(3):
        conn.execute('INSERT INTO faces(photo_path,person_id,face_index,embedding) VALUES (?,2,?,?)', ('/visible/a.jpg', 100 + index, b'face'))
    for index in range(10):
        conn.execute('INSERT INTO faces(photo_path,person_id,face_index,embedding) VALUES (?,1,?,?)', ('/private/a.jpg', index, b'face'))
    conn.execute("UPDATE persons SET name='  ' WHERE id=53")
    conn.commit()
    conn.close()

    @asynccontextmanager
    async def database():
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            yield db

    monkeypatch.setattr('api.routers.persons.get_async_db', database)
    # Exercise the real query with a parameterized directory visibility rule.
    monkeypatch.setattr('api.routers.persons.get_visibility_clause',
                        lambda _user, alias: (f'{alias}.path LIKE ?', ['/visible/%']))
    return path


def test_global_order_and_visible_counts(edition_client, picker_db):
    response = edition_client.get('/api/persons', params={'sort': 'assignment', 'recent_ids': '52,54,999'})
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 53
    rows = data['persons']
    assert [row['id'] for row in rows[:4]] == [52, 2, 1, 3]
    assert [row['face_count'] for row in rows[:4]] == [1, 4, 1, 1]
    second = edition_client.get('/api/persons', params={'sort': 'assignment', 'recent_ids': '52,54,999', 'page': 2}).json()
    ids = [row['id'] for row in rows + second['persons']]
    assert len(ids) == len(set(ids)) == 53
    assert ids[-1] == 55


def test_search_recent_order_and_stable_name_ties(edition_client, picker_db):
    with sqlite3.connect(picker_db) as conn:
        conn.execute("UPDATE persons SET name='Ada' WHERE id IN (3,4)")
        conn.execute("UPDATE persons SET name='ada' WHERE id=5")
    rows = edition_client.get('/api/persons', params={'sort': 'assignment', 'search': 'Ada'}).json()['persons']
    assert [row['id'] for row in rows] == [3, 4, 5]
    recent = edition_client.get('/api/persons', params={'sort': 'assignment', 'search': 'Ada', 'recent_ids': '5,5,3'}).json()['persons']
    assert [row['id'] for row in recent] == [5, 3, 4]


@pytest.mark.parametrize('recent', ['0', '-1', '1,,2', 'a', '1.5', '9007199254740992', ','.join(map(str, range(1,14)))])
def test_invalid_recent_ids_rejected(edition_client, picker_db, recent):
    assert edition_client.get('/api/persons', params={'sort': 'assignment', 'recent_ids': recent}).status_code == 422


def test_recent_ids_require_explicit_assignment_sort(edition_client, picker_db):
    assert edition_client.get('/api/persons', params={'recent_ids': '2'}).status_code == 422


def test_assignment_visibility_uses_current_user_directories(edition_client, picker_db, monkeypatch):
    from api.db_helpers import get_visibility_clause
    monkeypatch.setattr('api.routers.persons.get_visibility_clause', get_visibility_clause)
    monkeypatch.setattr('api.db_helpers.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('api.db_helpers.get_user_directories', lambda user: ['/visible'] if user == 'test' else [])
    with sqlite3.connect(picker_db) as conn:
        conn.execute("INSERT INTO persons(id,name,face_count) VALUES (56,'Private only',1)")
        conn.execute("INSERT INTO faces(photo_path,person_id,face_index,embedding) VALUES ('/private/a.jpg',56,100,X'00')")
    rows = edition_client.get('/api/persons', params={'sort': 'assignment', 'recent_ids': '1,55,56'}).json()['persons']
    assert 55 not in [row['id'] for row in rows]
    assert 56 not in [row['id'] for row in rows]
    assert rows[0]['id'] == 1
    assert rows[0]['face_count'] == 1
    monkeypatch.setattr('api.db_helpers.get_user_directories', lambda _user: [])
    assert edition_client.get('/api/persons', params={'sort': 'assignment', 'recent_ids': '1'}).json()['persons'] == []


def test_hidden_recent_is_not_an_assignment_candidate(edition_client, picker_db):
    rows = edition_client.get('/api/persons', params={
        'sort': 'assignment', 'recent_ids': '54', 'include_hidden': 'true',
    }).json()['persons']
    assert 54 not in [row['id'] for row in rows]


def test_unrestricted_named_empty_person_remains_assignable_and_searchable(edition_client, picker_db):
    response = edition_client.get('/api/persons', params={'sort': 'assignment', 'search': 'Person 55'})
    assert response.status_code == 200
    assert [(row['id'], row['face_count']) for row in response.json()['persons']] == [(55, 0)]


@pytest.mark.parametrize('name', ['²', '9999999999999999999999999999999', '9223372036854775808'])
@pytest.mark.parametrize('sort', ['assignment', 'name_asc'])
def test_non_integer_and_oversized_numeric_names_remain_searchable(edition_client, picker_db, name, sort):
    with sqlite3.connect(picker_db) as conn:
        conn.execute('UPDATE persons SET name=? WHERE id=3', (name,))
    response = edition_client.get('/api/persons', params={'sort': sort, 'search': name})
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['persons']] == [3]


def test_count_does_not_aggregate_visible_faces(edition_client, picker_db, monkeypatch):
    statements = []

    @asynccontextmanager
    async def traced_database():
        async with aiosqlite.connect(picker_db) as db:
            db.row_factory = aiosqlite.Row
            await db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr('api.routers.persons.get_async_db', traced_database)
    response = edition_client.get('/api/persons', params={'sort': 'assignment', 'search': 'Person 02'})
    assert response.status_code == 200
    assert response.json()['total'] == 1
    assert response.json()['persons'][0]['face_count'] == 4
    counts = [sql for sql in statements if sql.startswith('SELECT COUNT(*) FROM persons')]
    assert len(counts) == 1
    assert 'visible_counts' not in counts[0]
    assert 'GROUP BY' not in counts[0]
