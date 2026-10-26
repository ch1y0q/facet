"""Real JPEG XL discovery, metadata, orientation and browser rendering."""
from io import BytesIO
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image, ImageOps
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from utils import image_loading

pytest.importorskip("pillow_jxl")
imagecodecs = pytest.importorskip("imagecodecs")


def _jpegxl(path, orientation=1):
    pixels = np.zeros((24, 40, 3), dtype=np.uint8)
    pixels[:, :20] = (240, 20, 10)
    pixels[:, 20:] = (10, 40, 230)
    img = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[274] = orientation
    exif[306] = "2024:01:13 11:36:39"
    exif[34665] = {36867: "2024:01:13 11:36:39"}
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=95)
    original = buf.getvalue()
    encoded = imagecodecs.jpegxl_encode_jpeg(original, numthreads=1)
    path.write_bytes(encoded)
    return original


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_decode_matches_original_jpeg_and_preserves_metadata(tmp_path, orientation):
    path = tmp_path / "award.JXL"
    original = _jpegxl(path, orientation)
    expected = ImageOps.exif_transpose(Image.open(BytesIO(original)))
    actual = image_loading.open_nonraw_image(path)
    assert actual.mode == "RGB"
    assert actual.size == expected.size
    np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected))
    assert actual.getexif()[306] == "2024:01:13 11:36:39"
    assert imagecodecs.jpegxl_decode_jpeg(path.read_bytes(), numthreads=1) == original


def test_native_lossless_jpegxl_alpha_and_discovery(tmp_path):
    from facet import _gather_scan_files
    path = tmp_path / "certificate.JXL"
    Image.new("RGBA", (30, 20), (255, 0, 0, 0)).save(path, format="JXL", lossless=True)
    actual = image_loading.open_nonraw_image(path)
    assert actual.mode == "RGB"
    assert actual.getpixel((0, 0)) == (255, 255, 255)
    assert _gather_scan_files([str(tmp_path)], {}) == [path]
    assert ".jxl" in image_loading.WATCHABLE_IMAGE_EXTENSIONS


def test_optional_decoder_missing_skips_scan_but_watch_knows_extension():
    code = """
import sys
sys.modules['pillow_jxl'] = None
from utils.image_loading import JXL_EXTENSIONS, SCANNABLE_IMAGE_EXTENSIONS, WATCHABLE_IMAGE_EXTENSIONS
assert not JXL_EXTENSIONS
assert '.jxl' not in SCANNABLE_IMAGE_EXTENSIONS
assert '.jxl' in WATCHABLE_IMAGE_EXTENSIONS
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


@pytest.fixture
def jxl_client():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(user_id=None, role="admin")
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_browser_full_image_and_sharp_thumbnail_are_jpeg(tmp_path, seed_photos_prefix, jxl_client):
    path = tmp_path / "certificate.jxl"
    _jpegxl(path, orientation=6)
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + "/", [{
        "path": str(path), "filename": path.name, "thumbnail": stored.getvalue(),
    }])
    for endpoint, params in [("/image", {}), ("/thumbnail", {"size": 1920})]:
        response = jxl_client.get(endpoint, params={"path": str(path), **params})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert Image.open(BytesIO(response.content)).size == (24, 40)
    response = jxl_client.get("/image", params={"path": str(path)})
    cached = jxl_client.get("/image", params={"path": str(path)},
                            headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304


def test_bad_jpegxl_can_fall_back_to_stored_thumbnail(tmp_path, seed_photos_prefix, jxl_client):
    path = tmp_path / "broken.jxl"
    path.write_bytes(b"not JPEG XL")
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + "/", [{
        "path": str(path), "filename": path.name, "thumbnail": stored.getvalue(),
    }])
    response = jxl_client.get("/image", params={"path": str(path), "fallback": "thumbnail"})
    assert response.status_code == 200
    assert response.content == stored.getvalue()
    assert jxl_client.get("/image", params={"path": str(path)}).status_code == 500


def test_scanner_reads_original_capture_date(tmp_path):
    from processing.scorer import Facet
    path = tmp_path / "diploma.jxl"
    _jpegxl(path)
    scorer = object.__new__(Facet)
    assert scorer.get_exif_data(path)["date_taken"] == "2024:01:13 11:36:39"
