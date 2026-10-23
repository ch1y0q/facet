"""Missing GPS filters use the same SQL for rows, counts, and whole-view selection."""

import json


def test_no_geolocation_across_gallery_endpoints(edition_client, seed_photos_prefix):
    prefix = '/no-geolocation/'
    seed_photos_prefix(prefix, [
        {'path': prefix + 'missing.jpg', 'filename': 'missing.jpg', 'camera_model': 'Canon'},
        {'path': prefix + 'partial.jpg', 'filename': 'partial.jpg', 'gps_latitude': 12, 'camera_model': 'Nikon'},
        {'path': prefix + 'longitude-only.jpg', 'filename': 'longitude-only.jpg', 'gps_longitude': 34},
        {'path': prefix + 'zero.jpg', 'filename': 'zero.jpg', 'gps_latitude': 0, 'gps_longitude': 0, 'camera_model': 'Canon'},
        {'path': prefix + 'located.jpg', 'filename': 'located.jpg', 'gps_latitude': 12, 'gps_longitude': 34},
    ])
    params = {'path_prefix': prefix, 'no_gps': '1', 'hide_blinks': 'false', 'hide_bursts': 'false',
              'hide_duplicates': 'false', 'hide_brackets': 'false', 'hide_panoramas': 'false'}
    listing = edition_client.get('/api/photos', params=params)
    assert listing.status_code == 200
    assert {p['path'] for p in listing.json()['photos']} == {prefix + 'missing.jpg', prefix + 'partial.jpg', prefix + 'longitude-only.jpg'}
    assert edition_client.get('/api/photos/count', params=params).json()['total'] == 3
    assert set(edition_client.get('/api/photos/paths', params=params).json()['paths']) == {prefix + 'missing.jpg', prefix + 'partial.jpg', prefix + 'longitude-only.jpg'}
    combined = edition_client.get('/api/photos', params={**params, 'camera': 'Canon'}).json()
    assert [p['path'] for p in combined['photos']] == [prefix + 'missing.jpg']
    assert edition_client.get('/api/photos/count', params={**params, 'no_gps': ''}).json()['total'] == 5
    assert edition_client.get('/api/photos/count', params={**params, 'gps_lat': '0', 'gps_lng': '0', 'gps_radius_km': '5'}).json()['total'] == 3
    assert edition_client.put('/api/photo/gps', json={'path': prefix + 'missing.jpg', 'gps_latitude': 0, 'gps_longitude': 0}).status_code == 200
    assert edition_client.get('/api/photos/count', params=params).json()['total'] == 2



def test_smart_album_missing_gps_membership_tracks_manual_assignments(edition_client, seed_photos_prefix):
    prefix = '/no-geolocation-smart/'
    seed_photos_prefix(prefix, [
        {'path': prefix + 'missing.jpg', 'filename': 'missing.jpg'},
        {'path': prefix + 'zero.jpg', 'filename': 'zero.jpg', 'gps_latitude': 0, 'gps_longitude': 0},
    ])
    created = edition_client.post('/api/albums', json={
        'name': 'Needs GPS', 'is_smart': True,
        'smart_filter_json': json.dumps({'path_prefix': prefix, 'no_gps': '1'}),
    })
    assert created.status_code == 200
    album_id = created.json()['id']
    try:
        photos = edition_client.get(f'/api/albums/{album_id}/photos').json()['photos']
        assert [p['path'] for p in photos] == [prefix + 'missing.jpg']
        assert edition_client.put('/api/photo/gps', json={
            'path': prefix + 'missing.jpg', 'gps_latitude': 0, 'gps_longitude': 0,
        }).status_code == 200
        assert edition_client.get(f'/api/albums/{album_id}/photos').json()['total'] == 0
    finally:
        assert edition_client.delete(f'/api/albums/{album_id}').status_code == 200
