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
