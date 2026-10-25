"""Preview and crop conversion must not allocate a full RGB source frame."""
import base64
from io import BytesIO
from uuid import uuid4

from PIL import Image

from api import config
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
