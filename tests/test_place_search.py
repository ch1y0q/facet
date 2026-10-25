"""Explicit online lookup: bounds, privacy and no assignment."""
import gzip
import io
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api import place_search
from api.database import get_db


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


def test_disabled_invalid_endpoint(edition_client):
    for url in ('', 'file:///etc/passwd', 'https://user:secret@example.org/api', 'https://example.org/api?q=x'):
        with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': url}), patch('api.place_search._fetch') as fetch:
            assert edition_client.get('/api/places/search', params={'q': 'Berlin'}).status_code == 503
            fetch.assert_not_called()


@pytest.mark.parametrize('coords', [[float('nan'), 0], [0, float('inf')], [181, 0], [0, 91], ['1', 2], [True, 2], [1], [1, 2, 3]])
def test_invalid_coordinates(coords):
    assert place_search._results({'type': 'FeatureCollection', 'features': [feature(coords)]}) == []


def test_strict_results_and_limit():
    bad = [None, {}, feature(name=''), feature(name='x' * 301), {**feature(), 'geometry': {'type': 'LineString', 'coordinates': [1, 2]}}, feature(name=12)]
    assert len(place_search._results({'type': 'FeatureCollection', 'features': bad + [feature() for _ in range(10)]})) == 5
    assert place_search._results({'type': 'wrong', 'features': [feature()]}) == []


def test_cache_ttl_cap_endpoint_and_rate():
    with patch('api.place_search._fetch', return_value={}) as fetch, patch('api.place_search.time.monotonic', return_value=100):
        assert place_search.search('Berlin') == place_search.search('Berlin')
        assert fetch.call_count == 1
        with pytest.raises(HTTPException) as exc:
            place_search.search('Paris')
        assert exc.value.status_code == 429
    with patch('api.place_search._fetch', return_value={}) as fetch, patch('api.place_search.time.monotonic', return_value=1000):
        place_search.search('Berlin')
        assert fetch.call_count == 1
    for n in range(130):
        with patch('api.place_search._fetch', return_value={}), patch('api.place_search.time.monotonic', return_value=2000 + n):
            place_search.search(f'query{n}')
    assert len(place_search._cache) == 128
    with patch.dict('api.place_search.VIEWER_CONFIG', {'place_search_url': 'https://other.org/api'}), patch('api.place_search._fetch', return_value={}) as fetch, patch('api.place_search.time.monotonic', return_value=3000):
        place_search.search('query129')
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
    place_search._cache[('https://example.org/api', 'cached')] = (place_search.time.monotonic(), [])
    with ThreadPoolExecutor(max_workers=1) as pool, patch('api.place_search._fetch', side_effect=fetch):
        future = pool.submit(place_search.search, 'Berlin')
        try:
            assert started.wait(2)
            assert place_search.search('cached') == []
            with pytest.raises(HTTPException) as exc:
                place_search.search('Paris')
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
