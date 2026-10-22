"""Reliability tests for the plugin webhook delivery path.

`PluginManager._send_webhook` is the single chokepoint for outbound HTTP
notifications. These tests verify it:

* rejects SSRF-vulnerable targets (loopback, private subnets,
  link-local, file:// scheme, missing host)
* never raises when a webhook times out, returns 5xx, or the target is
  unreachable — failures are logged, the event loop / caller continues
* posts a well-formed JSON body with `event` + `data` keys
* uses the resolved IP as the request host so DNS rebinding cannot
  redirect the request to a private address after validation

There is *no* automatic retry layer in the current implementation; these
tests document the current behaviour so a future retry/backoff change
can be added under test instead of by inspection.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.error import HTTPError, URLError

import pytest


def _new_manager():
    from plugins import PluginManager
    return PluginManager(config=None)


class TestSSRFBlocking:
    @pytest.mark.parametrize('url', [
        'http://127.0.0.1/hook',
        'http://localhost/hook',
        'http://10.0.0.1/hook',
        'http://192.168.1.1/hook',
        'http://172.16.0.1/hook',
        'http://169.254.169.254/latest/meta-data/',
        'http://[::1]/hook',
    ])
    def test_blocks_private_target(self, url, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch('plugins._WEBHOOK_OPENER.open') as fake_open:
            mgr._send_webhook(url, 'on_score_complete', {'photo': 'x.jpg'})
        fake_open.assert_not_called()
        assert any(
            'blocked' in rec.message.lower() or 'ssrf' in rec.message.lower()
            for rec in caplog.records
        )

    @pytest.mark.parametrize('url', [
        'ftp://example.com/hook',
        'file:///etc/passwd',
        'gopher://example.com/',
    ])
    def test_blocks_unsupported_scheme(self, url):
        mgr = _new_manager()
        with mock.patch('plugins._WEBHOOK_OPENER.open') as fake_open:
            mgr._send_webhook(url, 'on_score_complete', {})
        fake_open.assert_not_called()

    def test_blocks_missing_hostname(self):
        mgr = _new_manager()
        with mock.patch('plugins._WEBHOOK_OPENER.open') as fake_open:
            mgr._send_webhook('http:///nohost', 'on_score_complete', {})
        fake_open.assert_not_called()


def _resolving_to(address):
    """``socket.getaddrinfo`` stand-in answering one fixed address."""
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    return mock.patch(
        'socket.getaddrinfo',
        return_value=[(family, socket.SOCK_STREAM, 6, '', (address, 80))],
    )


class TestResolvedAddressMustBePublic:
    """`_validate_webhook_url` accepts a host only when every address it
    resolves to is globally routable.  Beyond RFC 1918 / loopback /
    link-local that excludes shared address space (100.64.0.0/10, where
    cloud metadata services live), multicast, the reserved and unspecified
    ranges, and an IPv4 address smuggled inside an IPv6 one (IPv4-mapped,
    NAT64 64:ff9b::/96, IPv4-compatible ::/96)."""

    @pytest.mark.parametrize('address', [
        '10.0.0.1',
        '127.0.0.1',
        '169.254.169.254',
        '100.64.0.1',
        '100.100.100.200',
        '224.0.0.1',
        '0.0.0.0',
        '240.0.0.1',
        '255.255.255.255',
        '::',
        '::1',
        'fe80::1',
        'fc00::1',
        '::ffff:127.0.0.1',
        '::ffff:10.0.0.1',
        '::ffff:100.64.0.1',
        '64:ff9b::7f00:1',
        '64:ff9b::a9fe:a9fe',
        '::127.0.0.1',
        '::10.0.0.1',
        '::2',
        'ff02::1',
    ])
    def test_rejects_non_public_address(self, address):
        from plugins import PluginManager
        with _resolving_to(address), pytest.raises(ValueError, match='private'):
            PluginManager._validate_webhook_url('http://webhook.example.com/hook')

    @pytest.mark.parametrize('address', [
        '93.184.216.34',
        '1.1.1.1',
        '2606:4700:4700::1111',
        '::ffff:93.184.216.34',
        '64:ff9b::5db8:d822',
    ])
    def test_accepts_public_address(self, address):
        from plugins import PluginManager
        with _resolving_to(address):
            resolved = PluginManager._validate_webhook_url('http://webhook.example.com/hook')
        # Compared as addresses: the spelling of an IPv6 text form varies by Python.
        assert ipaddress.ip_address(resolved) == ipaddress.ip_address(address)

    def test_one_non_public_answer_among_public_ones_rejects_the_host(self):
        from plugins import PluginManager
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('100.100.100.200', 80)),
        ]
        with mock.patch('socket.getaddrinfo', return_value=answers), \
                pytest.raises(ValueError, match='private'):
            PluginManager._validate_webhook_url('http://webhook.example.com/hook')

    @pytest.mark.parametrize('address', ['100.100.100.200', '224.0.0.1', '64:ff9b::7f00:1'])
    def test_test_webhook_reports_the_private_message(self, address):
        mgr = _new_manager()
        with _resolving_to(address), mock.patch('plugins._WEBHOOK_OPENER.open') as fake_open:
            result = mgr.test_webhook('http://webhook.example.com/hook')
        fake_open.assert_not_called()
        assert result['ok'] is False
        assert result['error'] == mgr._WEBHOOK_ERRORS['private_ip']


class TestPayloadShape:
    def test_posts_event_and_data_keys(self):
        mgr = _new_manager()
        captured = {}

        def _fake_urlopen(req, timeout=None):
            captured['data'] = req.data
            captured['method'] = req.get_method()
            captured['headers'] = dict(req.header_items())

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Resp()

        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('plugins._WEBHOOK_OPENER.open', side_effect=_fake_urlopen):
            mgr._send_webhook(
                'http://example.com/hook',
                'on_high_score',
                {'photo': '/path/a.jpg', 'aggregate': 9.5},
            )

        body = json.loads(captured['data'].decode('utf-8'))
        assert body['event'] == 'on_high_score'
        assert body['data']['photo'] == '/path/a.jpg'
        assert body['data']['aggregate'] == 9.5
        assert captured['method'] == 'POST'
        # Host header must reflect the original hostname, request hits the IP.
        assert captured['headers'].get('Host') == 'example.com'

    def test_payload_serialises_non_json_values_via_str(self):
        """The webhook uses `default=str` so PosixPaths / datetimes survive."""
        mgr = _new_manager()
        captured = {}

        def _fake_urlopen(req, timeout=None):
            captured['data'] = req.data

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Resp()

        from pathlib import PurePosixPath
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('plugins._WEBHOOK_OPENER.open', side_effect=_fake_urlopen):
            mgr._send_webhook(
                'http://example.com/hook',
                'on_score_complete',
                {'path': PurePosixPath('/photos/a.jpg')},
            )

        body = json.loads(captured['data'].decode('utf-8'))
        assert body['data']['path'] == '/photos/a.jpg'


class TestFailureAbsorption:
    """Failure modes that must NOT propagate to the caller."""

    def test_timeout_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch(
            'plugins._WEBHOOK_OPENER.open',
            side_effect=URLError('timed out'),
        ):
            # Caller continues — no exception escapes.
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {'x': 1}
            )
        assert any('failed' in rec.message.lower() for rec in caplog.records)

    def test_http_5xx_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.INFO)

        class _Resp:
            status = 500

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('plugins._WEBHOOK_OPENER.open', return_value=_Resp()):
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {}
            )
        # The implementation logs every response by status; 500 is logged
        # but not re-raised.
        assert any('500' in rec.message for rec in caplog.records)

    def test_dns_failure_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            side_effect=ValueError('DNS resolution failed'),
        ):
            mgr._send_webhook(
                'http://no-such-host.example.invalid/hook',
                'on_score_complete',
                {},
            )
        assert any('blocked' in rec.message.lower() for rec in caplog.records)

    def test_unexpected_exception_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch(
            'plugins._WEBHOOK_OPENER.open',
            side_effect=RuntimeError('out of memory'),
        ):
            # Should not raise — `_send_webhook` catches `Exception` broadly.
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {}
            )
        assert any(
            'unexpected error' in rec.message.lower() for rec in caplog.records
        )


class TestTimeoutValueWired:
    def test_urlopen_called_with_timeout(self):
        """The `_send_webhook` call must pass a finite timeout so a slow
        target can't pin a worker thread indefinitely."""
        mgr = _new_manager()
        captured_timeout = {}

        def _fake_urlopen(req, timeout=None):
            captured_timeout['value'] = timeout

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Resp()

        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('plugins._WEBHOOK_OPENER.open', side_effect=_fake_urlopen):
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {}
            )
        assert captured_timeout['value'] is not None
        assert captured_timeout['value'] > 0
        # 10 second timeout is the current implementation default; loosely
        # check it's in a sane range so a future tweak doesn't silently
        # drop the timeout to ~0.
        assert 1 < captured_timeout['value'] <= 60


class _LoopbackHandler(BaseHTTPRequestHandler):
    """Counts every request; ``/redirect/<code>`` answers with that status
    and a ``Location`` pointing at the server's ``target_url``, anything
    else answers 200."""

    def _handle(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length:
            self.rfile.read(length)
        self.server.hits.append((self.command, self.path))
        if self.path.startswith('/redirect/'):
            self.send_response(int(self.path.rsplit('/', 1)[1]))
            self.send_header('Location', self.server.target_url)
        else:
            self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    do_GET = do_POST = _handle

    def log_message(self, *_args):
        pass


@pytest.fixture
def loopback_pair():
    """A redirector and a redirect target, both on 127.0.0.1 (port 0)."""
    servers = []
    for _ in range(2):
        server = ThreadingHTTPServer(('127.0.0.1', 0), _LoopbackHandler)
        server.hits = []
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={'poll_interval': 0.01},
            daemon=True,
        )
        thread.start()
        servers.append((server, thread))
    (redirector, _), (target, _) = servers
    redirector.target_url = f'http://127.0.0.1:{target.server_port}/secret'
    try:
        yield redirector, target
    finally:
        for server, thread in servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class TestRedirectsNotFollowed:
    """A 3xx from the webhook host must not be followed: the redirect
    target never went through `_validate_webhook_url`, so following it
    would reach loopback / private addresses (SSRF)."""

    @pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
    def test_test_webhook_does_not_follow_redirect(self, loopback_pair, code):
        redirector, target = loopback_pair
        mgr = _new_manager()
        url = f'http://127.0.0.1:{redirector.server_port}/redirect/{code}'
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='127.0.0.1',
        ):
            result = mgr.test_webhook(url)
        assert target.hits == []
        assert result['ok'] is False
        assert result['error'] == mgr._WEBHOOK_ERRORS['conn_fail']
        assert [path for _, path in redirector.hits] == [f'/redirect/{code}']

    @pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
    def test_send_webhook_does_not_follow_redirect(
        self, loopback_pair, code, caplog
    ):
        redirector, target = loopback_pair
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        url = f'http://127.0.0.1:{redirector.server_port}/redirect/{code}'
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='127.0.0.1',
        ):
            mgr._send_webhook(url, 'on_score_complete', {'x': 1})
        assert target.hits == []
        assert [path for _, path in redirector.hits] == [f'/redirect/{code}']
        assert any('failed' in rec.message.lower() for rec in caplog.records)

    @pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
    def test_opener_refuses_a_get_redirect_itself(self, loopback_pair, code):
        """The POST tests above cannot tell our handler from urllib's own
        rule: urllib never re-sends a POST on 307/308, so they pass with the
        default opener too.  A GET is the case urllib DOES follow on every
        one of these codes, so only the handler can stop it."""
        import plugins
        redirector, target = loopback_pair
        url = f'http://127.0.0.1:{redirector.server_port}/redirect/{code}'
        with pytest.raises(HTTPError) as refused:
            plugins._WEBHOOK_OPENER.open(urllib.request.Request(url), timeout=5)
        assert refused.value.code == code
        assert 'redirect to another URL refused (webhook SSRF guard)' in str(refused.value)
        assert target.hits == []
        assert [path for _, path in redirector.hits] == [f'/redirect/{code}']

    @pytest.mark.parametrize('code', [301, 302, 303, 307, 308])
    def test_control_the_default_opener_follows_that_same_get(self, loopback_pair, code):
        """Pins the premise of the test above: with urllib's stock handlers the
        very same request reaches the redirect target."""
        redirector, target = loopback_pair
        url = f'http://127.0.0.1:{redirector.server_port}/redirect/{code}'
        with urllib.request.build_opener().open(urllib.request.Request(url), timeout=5) as resp:
            assert resp.status == 200
        assert [path for _, path in target.hits] == ['/secret']

    def test_handler_says_why_in_the_error_it_raises(self):
        import plugins
        req = urllib.request.Request('http://webhook.example.com/hook')
        with pytest.raises(HTTPError) as refused:
            plugins._NoRedirectHandler().redirect_request(
                req, None, 307, 'Temporary Redirect', {}, 'http://127.0.0.1/secret'
            )
        assert refused.value.code == 307
        assert refused.value.msg == 'redirect to another URL refused (webhook SSRF guard)'
        assert refused.value.url == 'http://webhook.example.com/hook'

    def test_direct_200_still_succeeds(self, loopback_pair):
        _, target = loopback_pair
        mgr = _new_manager()
        url = f'http://127.0.0.1:{target.server_port}/hook'
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='127.0.0.1',
        ):
            result = mgr.test_webhook(url)
            mgr._send_webhook(url, 'on_score_complete', {'x': 1})
        assert result == {'ok': True, 'status': 200, 'url': url}
        assert [method for method, _ in target.hits] == ['POST', 'POST']
