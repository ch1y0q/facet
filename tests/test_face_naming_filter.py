"""Naming queue uses actual face ownership rather than cached face counts."""
import pytest

from api.database import get_db


@pytest.fixture
def naming_photos(seed_photos_prefix):
    prefix = '/face-naming-filter/'
    names = ['unassigned', 'unnamed', 'blank', 'named', 'hidden', 'mixed', 'no-faces', 'orphan']
    paths = {name: prefix + name + '.jpg' for name in names}
    seed_photos_prefix(prefix, [dict(path=path, filename=name + '.jpg', aggregate=7, face_count=0)
                               for name, path in paths.items()])
    person_ids = []
    faces = {}
    with get_db() as conn, conn:
        for name, hidden in [(None, 0), ('   ', 0), ('Ada', 0), (None, 1)]:
            person_ids.append(conn.execute('INSERT INTO persons(name,is_hidden) VALUES (?,?)', (name, hidden)).lastrowid)
        owners = {'unassigned': [None, None], 'unnamed': [person_ids[0]], 'blank': [person_ids[1]],
                  'named': [person_ids[2]], 'hidden': [person_ids[3]],
                  'mixed': [person_ids[2], None], 'orphan': [max(person_ids) + 100000]}
        for name, ids in owners.items():
            faces[name] = [conn.execute('INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,?,?,?)',
                                       (paths[name], index, b'', owner)).lastrowid
                           for index, owner in enumerate(ids)]
    try:
        yield prefix, paths, person_ids, faces
    finally:
        with get_db() as conn, conn:
            conn.execute('DELETE FROM faces WHERE photo_path LIKE ?', (prefix + '%',))
            conn.executemany('DELETE FROM persons WHERE id=?', [(pid,) for pid in person_ids])


def _queue(client, prefix, **extra):
    response = client.get('/api/photos', params={'path_prefix': prefix, 'faces_need_names': '1', **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_naming_filter_membership_pagination_and_false(edition_client, naming_photos):
    prefix, paths, _, _ = naming_photos
    expected = {paths[name] for name in ['unassigned', 'unnamed', 'blank', 'mixed']}
    for _ in range(2):  # Warm the count cache too.
        data = _queue(edition_client, prefix)
        assert {p['path'] for p in data['photos']} == expected
        assert data['total'] == 4  # Multiple unnamed faces must not duplicate a photo.
    pages = [_queue(edition_client, prefix, per_page=2, page=page) for page in [1, 2]]
    assert {p['path'] for page in pages for p in page['photos']} == expected
    assert all(page['total'] == 4 for page in pages)
    inactive = _queue(edition_client, prefix, faces_need_names='0')
    assert inactive['total'] == len(paths)
    assert {photo['path'] for photo in inactive['photos']} == set(paths.values())
    default = edition_client.get('/api/photos', params={'path_prefix': prefix}).json()
    assert {photo['path'] for photo in default['photos']} == set(paths.values())


def test_naming_filter_assignment_and_unassignment_invalidate_warm_counts(edition_client, naming_photos):
    prefix, paths, ids, faces = naming_photos
    assert _queue(edition_client, prefix)['total'] == 4
    result = edition_client.post(f"/api/face/{faces['mixed'][1]}/assign", json={'person_id': ids[2]})
    assert result.status_code == 200, result.text
    data = _queue(edition_client, prefix)
    assert paths['mixed'] not in {p['path'] for p in data['photos']} and data['total'] == 3
    result = edition_client.post('/api/photo/unassign_person', json={'photo_path': paths['mixed'], 'person_id': ids[2]})
    assert result.status_code == 200, result.text
    assert _queue(edition_client, prefix)['total'] == 4


def test_naming_filter_by_paths_and_batch_share_membership(edition_client, naming_photos):
    prefix, paths, _, _ = naming_photos
    filters = {'faces_need_names': '1', 'path_prefix': prefix}
    result = edition_client.post('/api/photos/by_paths', json={'paths': list(paths.values()), 'filters': filters})
    assert result.status_code == 200, result.text
    expected = {paths[name] for name in ['unassigned', 'unnamed', 'blank', 'mixed']}
    assert {p['path'] for p in result.json()['photos']} == expected
    result = edition_client.post('/api/photos/batch_rating', json={'filters': filters, 'rating': 4})
    assert result.status_code == 200, result.text
    with get_db() as conn:
        rated = {row[0] for row in conn.execute('SELECT path FROM photos WHERE path LIKE ? AND star_rating=4', (prefix+'%',))}
    assert rated == expected


def test_naming_filter_respects_photo_visibility(edition_client, naming_photos, monkeypatch):
    from api.routers import gallery
    prefix, paths, _, _ = naming_photos
    monkeypatch.setattr(gallery, 'get_visibility_clause', lambda *a, **k: ('photos.path = ?', [paths['named']]))
    assert _queue(edition_client, prefix)['total'] == 0
    result = edition_client.post('/api/photos/by_paths', json={'paths': list(paths.values()), 'filters': {'faces_need_names': True}})
    assert result.status_code == 200, result.text
    assert result.json()['photos'] == []


def test_naming_filter_agent_album_round_trip():
    from api.agent import album_filters
    from api.agent.tools_common import MCP_FILTER_KEYS
    assert 'faces_need_names' in MCP_FILTER_KEYS
    refusal, stored = album_filters.to_stored({'faces_need_names': '1'})
    assert refusal is None and stored == {'faces_need_names': True}
    assert album_filters.query_form(stored) == {'faces_need_names': '1'}


def test_naming_probe_uses_covering_face_index(naming_photos):
    from api.routers.gallery import _build_gallery_where

    with get_db() as conn:
        clauses, params = _build_gallery_where({'faces_need_names': '1'}, conn)
        plan = conn.execute(
            'EXPLAIN QUERY PLAN SELECT COUNT(*) FROM photos WHERE ' + ' AND '.join(clauses), params,
        ).fetchall()
    assert any('COVERING INDEX idx_faces_photo_person' in row[3] for row in plan)


def test_face_covering_index_replaces_legacy_index_on_upgrade(tmp_path):
    import sqlite3
    from db.schema import init_database

    path = str(tmp_path / 'old-index.db')
    init_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute('DROP INDEX idx_faces_photo_person')
        conn.execute('CREATE INDEX idx_faces_photo ON faces(photo_path)')
        conn.execute("INSERT INTO photos(path) VALUES ('/a.jpg')")
        conn.execute("INSERT INTO faces(photo_path, face_index, embedding) VALUES ('/a.jpg',0,X'00')")
        before = conn.execute("SELECT id,person_id FROM faces WHERE photo_path='/a.jpg'").fetchall()
    init_database(path)
    with sqlite3.connect(path) as conn:
        indexes = {row[1] for row in conn.execute('PRAGMA index_list(faces)')}
        assert 'idx_faces_photo_person' in indexes
        assert 'idx_faces_photo' not in indexes
        assert conn.execute("SELECT id,person_id FROM faces WHERE photo_path='/a.jpg'").fetchall() == before
