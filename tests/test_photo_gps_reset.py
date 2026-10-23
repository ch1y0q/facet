"""DELETE /api/photo/gps hands a hand-set location back to the file's own GPS."""
from unittest.mock import patch

import pytest

from api.database import get_db


@pytest.fixture(autouse=True)
def _disk_paths():
    # The seeded rows have no file on disk: map each DB path to a fake disk path, so the
    # route is shown reading the RESOLVED file (path_mapping, scan-dir allowlist), not the DB path.
    with patch('api.routers.map.resolve_photo_disk_path', side_effect=lambda p: '/disk' + p):
        yield


def _row(path):
    with get_db() as conn:
        return dict(conn.execute(
            'SELECT gps_latitude, gps_longitude, gps_manually_set FROM photos WHERE path = ?', (path,)
        ).fetchone())


def test_delete_restores_file_gps_and_clears_flag(edition_client, seed_photos_prefix):
    path = '/gpsreset/a.jpg'
    seed_photos_prefix('/gpsreset/', [{'path': path, 'filename': 'a.jpg'}])
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 1, 'gps_longitude': 2}).status_code == 200
    assert _row(path)['gps_manually_set'] == 1
    with patch('api.routers.map.get_exif_batch', return_value={path: {'gps_latitude': 48.5, 'gps_longitude': 2.25}}) as stub:
        response = edition_client.delete('/api/photo/gps', params={'path': path})
    assert response.status_code == 200
    assert response.json() == {'gps_latitude': 48.5, 'gps_longitude': 2.25}
    stub.assert_called_once_with(['/disk' + path])
    assert _row(path) == {'gps_latitude': 48.5, 'gps_longitude': 2.25, 'gps_manually_set': 0}


def test_delete_stores_null_when_file_has_no_gps(edition_client, seed_photos_prefix):
    path = '/gpsreset/b.jpg'
    seed_photos_prefix('/gpsreset/', [{'path': path, 'filename': 'b.jpg'}])
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 1, 'gps_longitude': 2}).status_code == 200
    with patch('api.routers.map.get_exif_batch', return_value={path: {}}):
        response = edition_client.delete('/api/photo/gps', params={'path': path})
    assert response.json() == {'gps_latitude': None, 'gps_longitude': None}
    assert _row(path) == {'gps_latitude': None, 'gps_longitude': None, 'gps_manually_set': 0}


def test_delete_unknown_photo_is_404(edition_client):
    with patch('api.routers.map.get_exif_batch', return_value={}):
        assert edition_client.delete('/api/photo/gps', params={'path': '/gpsreset/missing.jpg'}).status_code == 404


def test_delete_refused_for_non_edition_client(regular_client, seed_photos_prefix):
    path = '/gpsreset/c.jpg'
    seed_photos_prefix('/gpsreset/', [{'path': path, 'filename': 'c.jpg', 'gps_latitude': 1, 'gps_longitude': 2, 'gps_manually_set': 1}])
    with patch('api.routers.map.get_exif_batch', return_value={path: {}}) as stub:
        response = regular_client.delete('/api/photo/gps', params={'path': path})
    assert response.status_code in (401, 403)
    stub.assert_not_called()
    assert _row(path) == {'gps_latitude': 1, 'gps_longitude': 2, 'gps_manually_set': 1}


def test_delete_with_unreadable_file_keeps_the_manual_location(edition_client, seed_photos_prefix):
    path = '/gpsreset/d.jpg'
    seed_photos_prefix('/gpsreset/', [{'path': path, 'filename': 'd.jpg'}])
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 1, 'gps_longitude': 2}).status_code == 200
    with patch('api.routers.map.get_exif_batch', return_value={}):
        assert edition_client.delete('/api/photo/gps', params={'path': path}).status_code == 404
    assert _row(path) == {'gps_latitude': 1, 'gps_longitude': 2, 'gps_manually_set': 1}
