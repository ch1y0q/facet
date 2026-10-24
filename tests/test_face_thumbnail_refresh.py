"""Private mutable crops are selected from the caller's visible face rows."""
from io import BytesIO
from uuid import uuid4

from PIL import Image
import pytest

from api import config, database
from db.schema import init_database


def jpeg(color):
    output = BytesIO()
    Image.new('RGB', (32, 32), color).save(output, format='JPEG')
    return output.getvalue()


@pytest.fixture
def crops(tmp_path, monkeypatch, edition_client):
    db_path = str(tmp_path / 'crops.db')
    init_database(db_path)
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', db_path)
    visible = tmp_path / 'visible'
    hidden = tmp_path / 'hidden'
    visible.mkdir()
    hidden.mkdir()
    path = str(visible / 'photo.jpg')
    image = Image.new('RGB', (100, 80), 'red')
    image.paste('blue', (50, 0, 100, 80))
    image.save(path)
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': [str(visible)]}}})
    with database.get_db() as conn, conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(path,), (str(hidden / 'secret.jpg'),)])
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Alice')").lastrowid
        fid = conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,face_thumbnail,confidence) "
                           "VALUES (?,0,X'',?,?,0.8)", (path, pid, jpeg('red'))).lastrowid
        hid = conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,face_thumbnail,confidence) "
                           "VALUES (?,0,X'',?,?,0.99)", (str(hidden / 'secret.jpg'), pid, jpeg('green'))).lastrowid
        conn.execute('UPDATE persons SET representative_face_id=?,face_thumbnail=? WHERE id=?',
                     (hid, jpeg('green'), pid))
    return edition_client, path, pid, fid, hid


def test_person_thumbnail_uses_visible_face_when_global_representative_hidden(crops):
    client, _, pid, fid, hid = crops
    assert client.get(f'/face_thumbnail/{hid}').status_code == 404
    response = client.get(f'/person_thumbnail/{pid}')
    assert response.status_code == 200
    assert response.content == client.get(f'/face_thumbnail/{fid}').content == jpeg('red')


def test_visible_explicit_representative_wins_over_higher_confidence(crops):
    client, path, pid, fid, _ = crops
    with database.get_db() as conn, conn:
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,face_thumbnail,confidence) "
                     "VALUES (?,1,X'',?,?,1)", (path, pid, jpeg('blue')))
        conn.execute('UPDATE persons SET representative_face_id=? WHERE id=?', (fid, pid))
    assert client.get(f'/person_thumbnail/{pid}').content == jpeg('red')


@pytest.mark.parametrize('route', ['face_thumbnail', 'person_thumbnail'])
def test_private_headers_and_revoked_conditional_request(crops, monkeypatch, route):
    client, _, pid, fid, _ = crops
    target = pid if route == 'person_thumbnail' else fid
    url = f'/{route}/{target}'
    first = client.get(url)
    assert first.status_code == 200
    for response in (first, client.get(url, headers={'If-None-Match': first.headers['etag']})):
        assert response.headers['cache-control'] == 'private, no-cache, must-revalidate'
        assert {'authorization', 'cookie'} <= set(response.headers['vary'].lower().replace(' ', '').split(','))
        assert response.headers['etag'] == first.headers['etag']
    assert client.get(url, headers={'If-None-Match': first.headers['etag']}).status_code == 304
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': []}}})
    assert client.get(url, headers={'If-None-Match': first.headers['etag']}).status_code == 404


def test_manual_put_refreshes_warmed_face_and_person_endpoints(crops):
    client, path, _, _, _ = crops
    token = client.get('/api/photo/manual-face-frame', params={'path': path}).json()['frame_token']
    body = {'path': path, 'frame_token': token, 'bbox': [.55, .1, .95, .9],
            'new_person_name': 'Manual Bob', 'client_id': str(uuid4())}
    created = client.post('/api/photo/manual-faces', json=body)
    assert created.status_code == 201, created.text
    region = created.json()
    urls = [f"/face_thumbnail/{region['id']}", f"/person_thumbnail/{region['person_id']}"]
    old = [client.get(url) for url in urls]
    body.pop('client_id')
    body['bbox'] = [.05, .1, .4, .9]
    changed = client.put(f"/api/photo/manual-faces/{region['id']}", json=body)
    assert changed.status_code == 200, changed.text
    for url, previous in zip(urls, old):
        current = client.get(url, headers={'If-None-Match': previous.headers['etag']})
        assert current.status_code == 200
        assert current.content != previous.content
        image = Image.open(BytesIO(current.content))
        red, _, blue = image.getpixel((image.width // 2, image.height // 2))
        assert red > blue + 100


@pytest.fixture
def legacy_crops(crops, monkeypatch):
    client, path, pid, fid, _ = crops
    source = jpeg('red') + uuid4().bytes
    with database.get_db() as conn, conn:
        conn.execute('UPDATE photos SET thumbnail=? WHERE path=?', (source, path))
        conn.execute('UPDATE faces SET face_thumbnail=NULL,bbox_x1=5,bbox_y1=5,bbox_x2=50,bbox_y2=60 WHERE id=?', (fid,))
        conn.execute('UPDATE persons SET representative_face_id=? WHERE id=?', (fid, pid))
    opened = []
    original_open = Image.open

    def count_open(*args, **kwargs):
        opened.append(1)
        return original_open(*args, **kwargs)

    monkeypatch.setattr(Image, 'open', count_open)
    return client, path, pid, fid, opened, source


def test_legacy_crop_revalidation_reuses_render_but_rechecks_access(legacy_crops, monkeypatch):
    client, _, _, fid, opened, _ = legacy_crops
    first = client.get(f'/face_thumbnail/{fid}')
    assert first.status_code == 200
    assert client.get(f'/face_thumbnail/{fid}', headers={'If-None-Match': first.headers['etag']}).status_code == 304
    assert len(opened) == 1
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': []}}})
    assert client.get(f'/face_thumbnail/{fid}', headers={'If-None-Match': first.headers['etag']}).status_code == 404
    assert len(opened) == 1


@pytest.mark.parametrize('change', ['source', 'bbox', 'crop_padding_ratio', 'min_crop_size_px', 'output_size_px', 'jpeg_quality'])
def test_legacy_crop_cache_tracks_current_inputs(legacy_crops, monkeypatch, change):
    from api.routers import thumbnails
    client, path, _, fid, opened, _ = legacy_crops
    first = client.get(f'/face_thumbnail/{fid}')
    assert first.status_code == 200
    if change == 'source':
        with database.get_db() as conn, conn:
            conn.execute('UPDATE photos SET thumbnail=? WHERE path=?', (jpeg('blue') + uuid4().bytes, path))
    elif change == 'bbox':
        with database.get_db() as conn, conn:
            conn.execute('UPDATE faces SET bbox_x1=10 WHERE id=?', (fid,))
    else:
        settings = dict(thumbnails.VIEWER_CONFIG['face_thumbnails'])
        settings[change] += 1
        monkeypatch.setitem(thumbnails.VIEWER_CONFIG, 'face_thumbnails', settings)
    current = client.get(f'/face_thumbnail/{fid}')
    assert current.status_code == 200
    if change == 'source':
        assert current.content != first.content
        assert current.headers['etag'] != first.headers['etag']
    assert len(opened) == 2
    assert client.get(f'/face_thumbnail/{fid}', headers={'If-None-Match': current.headers['etag']}).status_code == 304
    assert len(opened) == 2


@pytest.mark.parametrize('oversized', ['source', 'output'])
def test_large_crop_inputs_are_not_retained(legacy_crops, monkeypatch, oversized):
    from api.routers import thumbnails
    client, path, _, fid, opened, source = legacy_crops
    if oversized == 'source':
        with database.get_db() as conn, conn:
            conn.execute('UPDATE photos SET thumbnail=? WHERE path=?', (source + b'x' * (128 * 1024), path))
    else:
        monkeypatch.setitem(thumbnails.VIEWER_CONFIG, 'face_thumbnails', {
            **thumbnails.VIEWER_CONFIG['face_thumbnails'], 'output_size_px': 512,
        })
    assert client.get(f'/face_thumbnail/{fid}').status_code == 200
    assert client.get(f'/face_thumbnail/{fid}').status_code == 200
    assert len(opened) == 2


def test_legacy_crop_cache_evicts_after_64_distinct_renders(legacy_crops):
    client, path, _, fid, opened, source = legacy_crops
    for index in range(65):
        with database.get_db() as conn, conn:
            conn.execute('UPDATE photos SET thumbnail=? WHERE path=?', (source + index.to_bytes(2, 'big'), path))
        assert client.get(f'/face_thumbnail/{fid}').status_code == 200
    with database.get_db() as conn, conn:
        conn.execute('UPDATE photos SET thumbnail=? WHERE path=?', (source + (0).to_bytes(2, 'big'), path))
    assert client.get(f'/face_thumbnail/{fid}').status_code == 200
    assert len(opened) == 66


@pytest.mark.parametrize('representative_visible', [True, False])
def test_person_only_sorts_when_representative_is_unavailable(crops, monkeypatch, representative_visible):
    client, _, pid, fid, _ = crops
    if representative_visible:
        with database.get_db() as conn, conn:
            conn.execute('UPDATE persons SET representative_face_id=? WHERE id=?', (fid, pid))
    statements = []
    original_connection = database.get_db_connection

    def traced_connection():
        conn = original_connection()
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(database, 'get_db_connection', traced_connection)
    response = client.get(f'/person_thumbnail/{pid}')
    assert response.status_code == 200
    assert response.content == jpeg('red')  # The stored global avatar is the hidden green crop.
    sorted_faces = [query for query in statements if 'ORDER BY' in query.upper() and 'faces' in query.lower()]
    assert bool(sorted_faces) is not representative_visible


def test_reassigned_representative_is_not_used_for_the_old_person(crops):
    client, path, pid, fid, _ = crops
    with database.get_db() as conn, conn:
        other = conn.execute("INSERT INTO persons(name) VALUES ('Other')").lastrowid
        conn.execute('UPDATE persons SET representative_face_id=? WHERE id=?', (fid, pid))
        conn.execute('UPDATE faces SET person_id=? WHERE id=?', (other, fid))
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,face_thumbnail,confidence) VALUES (?,1,X'',?,?,0.5)",
                     (path, pid, jpeg('blue')))
    assert client.get(f'/person_thumbnail/{pid}').content == jpeg('blue')
