"""Explicit online lookup: bounds, privacy and no assignment."""
import gzip
import io
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import create_app, place_search
from api.auth import CurrentUser, require_authenticated, require_edition
from api.database import get_db

_SCOPE = ('installation', '')


def feature(coords=None, **props):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [13.4, 52.5] if coords is None else coords}, 'properties': {'name': 'Berlin', **props}}


@pytest.fixture(autouse=True)
def reset_search():
    place_search._cache.clear()
    place_search._next_request = 0
    place_search._inflight = False
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': 'https://example.org/api'}):
        yield


def test_explicit_contract_and_no_assignment(edition_client, seeded_photos):
    # A previous GPS edit may have populated recents before search is opened.
    photo = seeded_photos[0]['path']
    assert edition_client.put('/api/photo/gps', json={
        'path': photo, 'gps_latitude': 1, 'gps_longitude': 2,
    }).status_code == 200
    with patch('api.place_search._fetch', return_value={'type': 'FeatureCollection', 'features': [feature(city='Berlin', country='Germany')]}) as fetch:
        before = edition_client.get('/api/places')
        assert before.status_code == 200
        assert before.json()['recent']
        with get_db() as conn:
            gps_before = tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (photo,)).fetchone())
        fetch.assert_not_called()
        result = edition_client.get('/api/places/search', params={'q': ' Berlin '})
        assert result.status_code == 200
        assert result.json() == {'results': [{'label': 'Berlin, Germany', 'latitude': 52.5, 'longitude': 13.4}]}
        fetch.assert_called_once_with('https://example.org/api', 'Berlin')
        assert edition_client.get('/api/places').json() == before.json()
        with get_db() as conn:
            assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (photo,)).fetchone()) == gps_before


@pytest.mark.parametrize('query', ['', 'ab', 'x' * 201, '   '])
def test_query_bounds(edition_client, query):
    with patch('api.place_search._fetch') as fetch:
        assert edition_client.get('/api/places/search', params={'q': query}).status_code == 422
        fetch.assert_not_called()


@pytest.mark.parametrize('query', ['   ', '  ab  ', 'ab\nc', 'a' * 201, 'ab'])
def test_http_validation_detail_matches_declared_schema(edition_client, query):
    with patch('api.place_search._fetch') as fetch:
        response = edition_client.get('/api/places/search', params={'q': query})
    assert response.status_code == 422
    document = edition_client.app.openapi()
    spec = document['paths']['/api/places/search']['get']['responses']['422']['content']['application/json']['schema']
    model = document['components']['schemas'][spec['$ref'].split('/')[-1]]
    assert model['properties']['detail']['type'] == 'array'
    assert isinstance(response.json()['detail'], list)
    assert response.json()['detail'][0]['loc'] == ['query', 'q']
    fetch.assert_not_called()


def test_http_query_normalization_keeps_safe_surrounding_whitespace(edition_client):
    with patch('api.place_search._fetch', return_value={'type': 'FeatureCollection', 'features': []}) as fetch:
        response = edition_client.get('/api/places/search', params={'q': '\t Berlin \n'})
    assert response.status_code == 200
    fetch.assert_called_once_with('https://example.org/api', 'Berlin')


def _assert_declared_search_error(client, response):
    document = client.app.openapi()
    responses = document['paths']['/api/places/search']['get']['responses']
    assert str(response.status_code) in responses
    spec = responses[str(response.status_code)]['content']['application/json']['schema']
    model = document['components']['schemas'][spec['$ref'].split('/')[-1]]
    assert model['properties']['detail']['type'] == 'string'
    assert isinstance(response.json()['detail'], str)


def test_http_throttle_error_contract_and_explicit_retry(edition_client):
    with patch('api.place_search._fetch', return_value={'type': 'FeatureCollection', 'features': [feature()]} ) as fetch, patch('api.place_search.time.monotonic', return_value=100):
        assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
        response = edition_client.get('/api/places/search', params={'q': 'Paris'})
        assert response.status_code == 429
        assert response.headers['Retry-After'] == '1'
        assert response.json() == {'detail': 'Wait before searching again'}
        _assert_declared_search_error(edition_client, response)
        assert 'Retry-After' in edition_client.app.openapi()['paths']['/api/places/search']['get']['responses']['429']['headers']
        fetch.assert_called_once()
    with patch('api.place_search._fetch', return_value={'type': 'FeatureCollection', 'features': [feature()]}), patch('api.place_search.time.monotonic', return_value=102):
        assert edition_client.get('/api/places/search', params={'q': 'Paris'}).status_code == 200


@pytest.mark.parametrize('mode', ['disabled', 'timeout'])
def test_provider_error_body_matches_declared_schema_without_private_details(edition_client, mode):
    if mode == 'disabled':
        with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': ''}), patch('api.place_search._fetch') as fetch:
            response = edition_client.get('/api/places/search', params={'q': 'Private address'})
            fetch.assert_not_called()
        assert response.status_code == 503
        assert response.json() == {'detail': 'Online place search is disabled'}
    else:
        with patch('api.place_search._fetch', side_effect=TimeoutError('private-provider-and-address')):
            response = edition_client.get('/api/places/search', params={'q': 'Private address'})
        assert response.status_code == 502
        assert response.json() == {'detail': 'Online place search is unavailable'}
    assert 'private' not in response.text.lower()
    _assert_declared_search_error(edition_client, response)


@pytest.mark.parametrize('query', ['   ', 'ab\nc', 'a' * 201])
def test_non_http_lookup_keeps_its_validation_boundary(query):
    with patch('api.place_search._fetch') as fetch, pytest.raises(HTTPException) as error:
        place_search.search(query, ('installation', ''))
    assert error.value.status_code == 422
    fetch.assert_not_called()


@pytest.mark.parametrize('query,valid', [
    ('😀', False), ('😀😀', False), ('😀😀😀', True), ('ab', False), ('abc', True),
    ('a' * 199 + '😀', True), ('😀' * 200, True), ('😀' * 201, False),
])
def test_http_query_bounds_count_unicode_codepoints(edition_client, query, valid):
    with patch('api.place_search._fetch', return_value={'type': 'FeatureCollection', 'features': []}) as fetch:
        response = edition_client.get('/api/places/search', params={'q': query})
    assert response.status_code == (200 if valid else 422)
    if valid:
        assert response.json() == {'results': []}
        fetch.assert_called_once_with('https://example.org/api', query)
    else:
        assert isinstance(response.json()['detail'], list)
        fetch.assert_not_called()


@pytest.mark.parametrize('url', [
    None, False, 123, [], {}, '',
    'https://example.org/' + 'x' * 1981,
    ' https://example.org/api',
    'https://example.org/a b',
    'https://example.org/a\nb',
    'https://example.org/a\tb',
    'file:///etc/passwd',
    'ftp://example.org/api',
    'https:///api',
    'https://user:secret@example.org/api',
    'https://user@example.org/api',
    'https://:secret@example.org/api',
    'https://@example.org/api',
    'https://example.org/api?q=x',
    'https://example.org/api#fragment',
    'https://example.org:invalid/api',
    'https://example.org:65536/api',
    'https://[::1/api',
])
def test_disabled_invalid_endpoint(edition_client, url):
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': url}), patch('api.place_search._fetch') as fetch:
        response = edition_client.get('/api/places/search', params={'q': 'Berlin'})
    assert response.status_code == 503
    assert response.json() == {'detail': 'Online place search is disabled'}
    fetch.assert_not_called()
    assert not place_search._cache
    assert place_search._next_request == 0
    assert not place_search._inflight


@pytest.mark.parametrize('url', [
    'https://example.org/api',
    'http://localhost:2322/api',
    'https://[::1]:8443/api',
    'https://example.org/geocoder%20name/api',
    'https://example.org/' + 'x' * 1980,
])
def test_valid_configured_endpoint_is_used_unchanged(edition_client, url):
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': url}), patch('api.place_search._fetch', return_value={'type': 'FeatureCollection', 'features': [feature()]}) as fetch:
        response = edition_client.get('/api/places/search', params={'q': 'Berlin'})
    assert response.status_code == 200
    assert response.json() == {'results': [{'label': 'Berlin', 'latitude': 52.5, 'longitude': 13.4}]}
    fetch.assert_called_once_with(url, 'Berlin')


@pytest.mark.parametrize('coords', [[float('nan'), 0], [0, float('inf')], [181, 0], [0, 91], ['1', 2], [True, 2], [1], [1, 2, 3]])
def test_invalid_coordinates(coords):
    assert place_search._results({'type': 'FeatureCollection', 'features': [feature(coords)]}) == []


def test_strict_results_and_limit():
    bad = [None, {}, feature(name=''), feature(name='x' * 301), {**feature(), 'geometry': {'type': 'LineString', 'coordinates': [1, 2]}}, feature(name=12)]
    assert len(place_search._results({'type': 'FeatureCollection', 'features': bad + [feature() for _ in range(10)]})) == 5
    assert place_search._results({'type': 'wrong', 'features': [feature()]}) == []


def test_cache_ttl_cap_endpoint_and_rate():
    with patch('api.place_search._fetch', return_value={}) as fetch, patch('api.place_search.time.monotonic', return_value=100):
        assert place_search.search('Berlin', _SCOPE) == place_search.search('Berlin', _SCOPE)
        assert fetch.call_count == 1
        with pytest.raises(HTTPException) as exc:
            place_search.search('Paris', _SCOPE)
        assert exc.value.status_code == 429
    with patch('api.place_search._fetch', return_value={}) as fetch, patch('api.place_search.time.monotonic', return_value=1000):
        place_search.search('Berlin', _SCOPE)
        assert fetch.call_count == 1
    for n in range(130):
        with patch('api.place_search._fetch', return_value={}), patch('api.place_search.time.monotonic', return_value=2000 + n):
            place_search.search(f'query{n}', ('user', f'user{n % 2}'))
    assert len(place_search._cache) == 128
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': 'https://other.org/api'}), patch('api.place_search._fetch', return_value={}) as fetch, patch('api.place_search.time.monotonic', return_value=3000):
        place_search.search('query129', ('user', 'user1'))
        fetch.assert_called_once()


def test_timeout_generic_not_cached(edition_client):
    with patch('api.place_search._fetch', side_effect=TimeoutError('private address')):
        response = edition_client.get('/api/places/search', params={'q': 'Berlin'})
        assert response.status_code == 502
        assert 'private' not in response.text
        assert not place_search._cache


class Response(io.BytesIO):
    status = 200
    def __init__(self, data, encoding='identity'):
        super().__init__(data)
        self.encoding = encoding
    def getheader(self, key, default=None):
        return self.encoding if key == 'Content-Encoding' else default


@pytest.mark.parametrize('compressed', [False, True])
def test_size_bound_after_decompression(compressed):
    payload = b' ' * 65537
    response = Response(gzip.compress(payload) if compressed else payload, 'gzip' if compressed else 'identity')
    with patch('api.place_search._DeadlineConnection') as connection:
        connection.return_value.expired = False
        connection.return_value.getresponse.return_value = response
        with pytest.raises(ValueError):
            place_search._fetch('https://example.org/api', 'Berlin')
        assert place_search._TIMEOUT_SECONDS == 5
        assert connection.return_value.request.call_count == 1


def test_no_redirect_or_retry_valid_transport():
    with patch('api.place_search._DeadlineConnection') as connection:
        connection.return_value.expired = False
        connection.return_value.getresponse.return_value = Response(json.dumps({'type': 'FeatureCollection', 'features': []}).encode())
        assert place_search._fetch('https://example.org/api', 'Berlin')['features'] == []
        assert connection.return_value.request.call_args.args[1] == '/api?q=Berlin&limit=5'
        response = Response(b'')
        response.status = 302
        connection.return_value.expired = False
        connection.return_value.getresponse.return_value = response
        with pytest.raises(ValueError):
            place_search._fetch('https://example.org/api', 'Berlin')
        assert connection.return_value.request.call_count == 2


def test_config_discloses_only_availability(client):
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': 'https://private.example/api'}):
        response = client.get('/api/config')
        assert response.status_code == 200
        assert response.json()['place_search_enabled'] is True
        assert 'private.example' not in response.text
        assert 'place_search_url' not in response.json()
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': ''}):
        assert client.get('/api/config').json()['place_search_enabled'] is False


def test_concurrent_miss_refused_but_cached_hit_available():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    started, finish = Event(), Event()
    def fetch(*args):
        started.set()
        assert finish.wait(2)
        return {}
    place_search._cache[(_SCOPE, 'https://example.org/api', 'cached')] = (place_search.time.monotonic(), [])
    with ThreadPoolExecutor(max_workers=1) as pool, patch('api.place_search._fetch', side_effect=fetch):
        future = pool.submit(place_search.search, 'Berlin', _SCOPE)
        try:
            assert started.wait(2)
            assert place_search.search('cached', _SCOPE) == []
            with pytest.raises(HTTPException) as exc:
                place_search.search('Paris', _SCOPE)
            assert exc.value.status_code == 429
        finally:
            finish.set()
        assert future.result() == []


@pytest.mark.parametrize('prefix', [
    b'HTTP/1.1 200 OK\r\nX-Slow: ',
    b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n1;slow=',
    b'HTTP/1.1 200 OK\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n\r\n1;slow=',
])
def test_total_deadline_interrupts_trickled_headers_and_chunk_framing(prefix):
    import socket
    import threading
    import time

    stop = threading.Event()
    accepted = threading.Event()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(1)
        def serve():
            with listener.accept()[0] as peer:
                accepted.set()
                try:
                    peer.sendall(prefix)
                    for _ in range(24):
                        if stop.wait(0.05):
                            break
                        peer.sendall(b'x')
                except OSError:
                    pass
        server = threading.Thread(target=serve)
        server.start()
        started = time.monotonic()
        try:
            with patch('api.place_search._TIMEOUT_SECONDS', 0.3):
                with pytest.raises(TimeoutError):
                    place_search._fetch(f'http://127.0.0.1:{listener.getsockname()[1]}/api', 'Berlin')
            assert accepted.is_set()
            assert time.monotonic() - started < 0.9
        finally:
            stop.set()
            server.join(1)
        assert not server.is_alive()
        assert not any(thread.name == 'facet-place-search-deadline' for thread in threading.enumerate())


class _FakeSocket:
    def __init__(self, fail_connect=False):
        self.fail_connect = fail_connect
        self.closed = False

    def settimeout(self, _):
        pass

    def connect(self, _):
        if self.fail_connect:
            raise ConnectionRefusedError

    def close(self):
        self.closed = True


def _connection(url='https://geo.example/search', ttl=30.0):
    import time
    return place_search._DeadlineConnection(url, time.monotonic() + ttl)


def test_https_connect_verifies_the_hostname_and_handshakes():
    secure = _FakeSocket()
    secure.do_handshake = lambda: setattr(secure, 'handshaken', True)
    context = type('Ctx', (), {'wrap_socket': lambda self, sock, **kwargs: (setattr(secure, 'kwargs', kwargs), secure)[1]})()
    with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('203.0.113.1', 443))]), \
            patch('socket.socket', return_value=_FakeSocket()), \
            patch('ssl.create_default_context', return_value=context):
        connection = _connection()
        connection.connect()
    assert secure.kwargs == {'server_hostname': 'geo.example', 'do_handshake_on_connect': False}
    assert secure.handshaken is True
    assert connection.sock is secure


def test_connect_falls_through_to_the_next_address():
    first, second = _FakeSocket(fail_connect=True), _FakeSocket()
    with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('203.0.113.1', 80)), (2, 1, 6, '', ('203.0.113.2', 80))]), \
            patch('socket.socket', side_effect=[first, second]):
        connection = _connection('http://geo.example/search')
        connection.connect()
    assert first.closed is True
    assert connection.sock is second


def test_connect_stops_when_the_deadline_passes_during_dns():
    with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('203.0.113.1', 80))]), \
            patch('socket.socket') as opened:
        connection = _connection('http://geo.example/search', ttl=-1.0)
        with pytest.raises(TimeoutError):
            connection.connect()
    opened.assert_not_called()


@pytest.mark.parametrize('probe', ['Berlin', 'unsearched address'])
def test_cache_does_not_probe_other_users_searches(monkeypatch, probe):
    # Keep the real require_edition gate: both authenticated admins may search,
    # but Bob must get the same throttled miss for Alice's query as any new one.
    monkeypatch.setattr('api.auth.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('api.routers.places.is_multi_user_enabled', lambda: True)
    app = create_app()
    alice = CurrentUser(user_id='alice', role='admin')
    bob = CurrentUser(user_id='bob', role='admin')
    app.dependency_overrides[require_authenticated] = lambda: alice
    try:
        with TestClient(app) as client, patch('api.place_search._fetch', return_value={}) as fetch:
            with patch('api.place_search.time.monotonic', return_value=100):
                assert client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
                assert client.get('/api/places/search', params={'q': ' Berlin '}).status_code == 200
                app.dependency_overrides[require_authenticated] = lambda: bob
                response = client.get('/api/places/search', params={'q': probe})
                assert response.status_code == 429
                assert response.headers['Retry-After'] == '1'
                assert fetch.call_count == 1
            with patch('api.place_search.time.monotonic', return_value=102):
                assert client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
                assert fetch.call_count == 2
                app.dependency_overrides[require_authenticated] = lambda: alice
                assert client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
                assert fetch.call_count == 2
    finally:
        app.dependency_overrides.clear()


def test_deep_provider_json_maps_to_generic_failure_and_releases_gate(edition_client):
    # A valid JSON document below the byte limit can still exceed decoder depth.
    payload = b'[' * 20000 + b'0' + b']' * 20000
    assert len(payload) < place_search._MAX_BYTES
    with patch('api.place_search._DeadlineConnection') as connection:
        connection.return_value.expired = False
        connection.return_value.getresponse.return_value = Response(payload)
        with patch('api.place_search.time.monotonic', return_value=100):
            response = edition_client.get('/api/places/search', params={'q': 'Berlin'})
            assert response.status_code == 502
            assert response.json() == {'detail': 'Online place search is unavailable'}
            assert not place_search._cache
            assert place_search._inflight is False
            assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 429
        connection.return_value.getresponse.return_value = Response(b'{"type":"FeatureCollection","features":[]}')
        with patch('api.place_search.time.monotonic', return_value=102):
            assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
            assert len(place_search._cache) == 1



def test_single_user_cache_is_separate_from_named_account(monkeypatch, edition_client):
    # A multi-user account can have the same ID as the single-user owner label.
    monkeypatch.setattr('api.routers.places.is_multi_user_enabled', lambda: False)
    with patch('api.place_search._fetch', return_value={}) as fetch:
        with patch('api.place_search.time.monotonic', return_value=100):
            assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
            monkeypatch.setattr('api.routers.places.is_multi_user_enabled', lambda: True)
            edition_client.app.dependency_overrides[require_edition] = lambda: CurrentUser(user_id='installation', role='admin')
            assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 429
            assert fetch.call_count == 1
        with patch('api.place_search.time.monotonic', return_value=102):
            assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 200
            assert fetch.call_count == 2


def test_non_editor_cannot_search_online(regular_client):
    with patch('api.place_search._fetch') as fetch:
        assert regular_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 403
        fetch.assert_not_called()


def test_unicode_result_label_counts_characters_not_utf16_units(edition_client):
    name, city = '🚋' * 299, '🌳' * 299
    label = name + ', ' + city
    assert len(label) == 600
    with patch('api.place_search._fetch', return_value={
            'type': 'FeatureCollection', 'features': [feature(name=name, city=city)]}) as fetch:
        response = edition_client.get('/api/places/search', params={'q': 'Station'})
    assert response.status_code == 200, response.text
    assert response.json() == {'results': [{'label': label, 'latitude': 52.5, 'longitude': 13.4}]}
    fetch.assert_called_once()
