"""Tests for the thumbnails API router (api/routers/thumbnails.py)."""

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from utils import image_loading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cm(conn):
    """Wrap a mock connection in a context manager compatible with get_db()."""
    @contextmanager
    def _ctx():
        yield conn
    return _ctx


def _make_jpeg_bytes() -> bytes:
    """Create a minimal valid 1x1 JPEG image."""
    from PIL import Image
    buf = BytesIO()
    img = Image.new("RGB", (1, 1), (255, 0, 0))
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def jpeg_bytes():
    return _make_jpeg_bytes()


@pytest.fixture()
def client():
    app = create_app()
    # Override auth so all requests are treated as authenticated
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
        user_id="u1", role="admin"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /thumbnail
# ---------------------------------------------------------------------------

class TestGetThumbnail:
    """GET /thumbnail?path=... — photo thumbnail."""

    def test_thumbnail_returns_jpeg(self, client, jpeg_bytes):
        mock_conn = mock.MagicMock()
        mock_row = {"thumbnail": jpeg_bytes}
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/thumbnail", params={"path": "/photo.jpg"})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert len(resp.content) > 0

    def test_thumbnail_not_found(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/thumbnail", params={"path": "/missing.jpg"})

        assert resp.status_code == 404

    def test_thumbnail_resize(self, client):
        """Requesting size=200 should return resized (smaller) bytes."""
        # Create a larger image so resize actually shrinks it
        from PIL import Image
        buf = BytesIO()
        img = Image.new("RGB", (640, 640), (0, 128, 255))
        img.save(buf, format="JPEG")
        large_jpeg = buf.getvalue()

        mock_conn = mock.MagicMock()
        mock_row = {"thumbnail": large_jpeg}
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/thumbnail", params={"path": "/photo.jpg", "size": 200})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        # Resized image should be smaller than the original 640x640
        assert len(resp.content) < len(large_jpeg)


# ---------------------------------------------------------------------------
# GET /face_thumbnail/{face_id}
# ---------------------------------------------------------------------------

class TestFaceThumbnail:
    """GET /face_thumbnail/{face_id} — cropped face thumbnail."""

    def test_face_thumbnail_not_found(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("api.routers.thumbnails.get_db_connection", return_value=mock_conn):
            # Clear the LRU cache to avoid stale results
            from api.routers.thumbnails import _get_face_thumbnail_data
            _get_face_thumbnail_data.cache_clear()

            resp = client.get("/face_thumbnail/99999")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /image
# ---------------------------------------------------------------------------

class TestImage:
    """GET /image?path=... — full-size image."""

    def test_image_path_traversal_blocked(self, client):
        """A path not present in the database returns 404."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/image", params={"path": "/etc/passwd"})

        assert resp.status_code == 404

    def test_image_raw_decode_failure_falls_back_to_thumbnail(self, client, jpeg_bytes, tmp_path):
        """fallback=thumbnail degrades to the stored thumbnail on a RuntimeError, not a 500."""
        raw_file = tmp_path / "photo.cr2"
        raw_file.write_bytes(b"not a real raw file")

        mock_conn = mock.MagicMock()
        photo_row = {"path": "/library/photo.cr2", "sequence_kind": None}
        thumbnail_row = {"thumbnail": jpeg_bytes}
        mock_conn.execute.side_effect = [
            mock.Mock(fetchone=mock.Mock(return_value=photo_row)),
            mock.Mock(fetchone=mock.Mock(return_value=thumbnail_row)),
        ]

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)), \
             mock.patch("api.routers.thumbnails.resolve_photo_disk_path", return_value=str(raw_file)), \
             mock.patch(
                 "api.routers.thumbnails._convert_raw_cached",
                 side_effect=RuntimeError(f"RAW decode failed: {raw_file}"),
             ):
            resp = client.get(
                "/image", params={"path": "/library/photo.cr2", "fallback": "thumbnail"}
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == jpeg_bytes

    def test_image_raw_decode_failure_without_fallback_returns_500(self, client, tmp_path):
        """Without fallback=thumbnail, a RAW decode failure still surfaces as a 500."""
        raw_file = tmp_path / "photo.cr2"
        raw_file.write_bytes(b"not a real raw file")

        mock_conn = mock.MagicMock()
        photo_row = {"path": "/library/photo.cr2", "sequence_kind": None}
        mock_conn.execute.return_value.fetchone.return_value = photo_row

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)), \
             mock.patch("api.routers.thumbnails.resolve_photo_disk_path", return_value=str(raw_file)), \
             mock.patch(
                 "api.routers.thumbnails._convert_raw_cached",
                 side_effect=RuntimeError(f"RAW decode failed: {raw_file}"),
             ):
            resp = client.get("/image", params={"path": "/library/photo.cr2"})

        assert resp.status_code == 500


def test_heif_conversion_uses_shared_loader():
    """_convert_nonraw_cached routes through open_nonraw_image (EXIF orientation + PQ tone map).

    Before the Canon .HIF fix the viewer decoded HEIF directly with PIL, so the
    browser showed a dark/rotated image relative to what the scanner scored.
    """
    from PIL import Image as PILImage
    from api.routers import thumbnails

    sentinel = PILImage.new("RGB", (2, 2), (10, 20, 30))
    thumbnails._convert_nonraw_cached.cache_clear()
    try:
        with mock.patch("utils.image_loading.open_nonraw_image", return_value=sentinel) as m:
            out = thumbnails._convert_nonraw_cached("/library/photo.heif", 1.0, 96)
            m.assert_called_once_with("/library/photo.heif")
        im = PILImage.open(BytesIO(out))
        assert im.size == (2, 2)
        assert im.getpixel((0, 0)) == (10, 20, 30)
    finally:
        thumbnails._convert_nonraw_cached.cache_clear()


@pytest.mark.skipif(not image_loading._heif_available, reason='pillow-heif not installed')
def test_heif_conversion_matches_what_the_scanner_scored():
    """The browser JPEG and the scored buffer must come from one decode.

    Run on the real Canon HDR PQ frame: before the shared loader the viewer
    decoded HEIF with a bare PIL open, so it showed the untone-mapped, dark
    image while the models scored a different one.
    """
    from api.routers import thumbnails
    from PIL import Image as PILImage

    fixture = str(Path(__file__).parent / 'fixtures' / 'canon_eos_r8_hdr_pq.hif')
    thumbnails._convert_nonraw_cached.cache_clear()
    try:
        jpeg = thumbnails._convert_nonraw_cached(fixture, 1.0, 100)
    finally:
        thumbnails._convert_nonraw_cached.cache_clear()

    served = np.asarray(PILImage.open(BytesIO(jpeg)).convert('RGB')).astype(int)
    scored = np.asarray(image_loading.open_nonraw_image(fixture)).astype(int)
    assert served.shape == scored.shape
    # JPEG at quality 100 is still lossy; the two must agree to within it, and
    # nowhere near the gulf a missing tone map would open.
    assert np.abs(served - scored).mean() < 2.0
