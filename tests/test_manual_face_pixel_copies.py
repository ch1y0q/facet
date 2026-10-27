"""Preview and crop conversion must not allocate a full RGB source frame."""
import base64
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from api import config
from api.database import get_db
from api.routers import manual_faces as routes
from utils import manual_face_frame as frames


def test_preview_and_save_convert_only_the_required_pixels(edition_client, tmp_path, seed_photos_prefix, monkeypatch):
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {})
    image = tmp_path / 'large.jpg'
    source = Image.new('RGB', (2000, 1000), 'red')
    source.paste('blue', (1000, 0, 2000, 1000))
    source.save(image)
    original = image.read_bytes()
    path = str(image)
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': image.name}])
    frames.clear_cache()
    sizes = []
    convert = routes._rgb
    def record(pixels):
        sizes.append(pixels.shape[:2])
        return convert(pixels)
    monkeypatch.setattr(routes, '_rgb', record)
    try:
        response = edition_client.get('/api/photo/manual-face-frame', params={'path': path})
        assert response.status_code == 200, response.text
        data = response.json()
        assert (data['width'], data['height']) == (2000, 1000)
        preview = Image.open(BytesIO(base64.b64decode(data['image_base64'])))
        assert preview.size == (1600, 800)
        assert preview.getpixel((100, 100))[0] > 240
        assert preview.getpixel((1500, 100))[2] > 240
        response = edition_client.post('/api/photo/manual-faces', json={
            'path': path, 'frame_token': data['frame_token'], 'bbox': [0.1, 0.1, 0.2, 0.3],
            'new_person_name': 'Pixel crop', 'client_id': str(uuid4())})
        assert response.status_code == 201, response.text
        assert sizes == [(800, 1600), (200, 200)]
        assert frames.read_frame(path).pixels.flags.writeable is False
        assert image.read_bytes() == original
    finally:
        frames.clear_cache()


@pytest.mark.parametrize('create_box, edit_box, create_blue', [
    ([0.5, 0.0, 1.0, 1.0], [0.0, 0.0, 0.5, 1.0], True),
    ([0.0, 0.0, 0.5, 1.0], [0.5, 0.0, 1.0, 1.0], False),
])
def test_edge_touching_boxes_convert_and_crop_the_right_pixels_on_create_and_edit(
        edition_client, tmp_path, seed_photos_prefix, monkeypatch, create_box, edit_box, create_blue):
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {})
    image = tmp_path / 'edge.jpg'
    source = Image.new('RGB', (2000, 1000), 'red')
    source.paste('blue', (1000, 0, 2000, 1000))
    source.save(image)
    path = str(image)
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': image.name}])
    frames.clear_cache()
    sizes = []
    convert = routes._rgb
    def record(pixels):
        sizes.append(pixels.shape[:2])
        return convert(pixels)
    monkeypatch.setattr(routes, '_rgb', record)
    def token():
        response = edition_client.get('/api/photo/manual-face-frame', params={'path': path})
        assert response.status_code == 200, response.text
        return response.json()['frame_token']
    def centre_is_blue(face_id):
        with get_db() as conn:
            row = conn.execute('SELECT face_thumbnail FROM faces WHERE id=?', (face_id,)).fetchone()
        red, _, blue = Image.open(BytesIO(row['face_thumbnail'])).convert('RGB').getpixel((50, 50))
        return blue > red + 100
    try:
        created = edition_client.post('/api/photo/manual-faces', json={
            'path': path, 'frame_token': token(), 'bbox': create_box,
            'new_person_name': 'Edge crop', 'client_id': str(uuid4())})
        assert created.status_code == 201, created.text
        face_id = created.json()['id']
        assert sizes[-1] == (1000, 1000) and centre_is_blue(face_id) is create_blue
        sizes.clear()
        edited = edition_client.put(f'/api/photo/manual-faces/{face_id}', json={
            'path': path, 'frame_token': token(), 'bbox': edit_box, 'new_person_name': 'Edge crop'})
        assert edited.status_code == 200, edited.text
        assert sizes[-1] == (1000, 1000) and centre_is_blue(face_id) is not create_blue
    finally:
        frames.clear_cache()
