"""GET /api/config carries the running version and, when recorded, the build it came from."""

import pytest

from api.auth import create_access_token
from api.config import VIEWER_CONFIG
from utils.version import current_version


@pytest.fixture()
def locked(monkeypatch):
    monkeypatch.setitem(VIEWER_CONFIG, 'password', 'secret')


def _bearer(claims):
    return {'Authorization': f'Bearer {create_access_token(claims)}'}


def test_an_open_install_reports_the_release_version(client, monkeypatch):
    monkeypatch.setitem(VIEWER_CONFIG, 'password', '')
    monkeypatch.delenv('FACET_BUILD', raising=False)
    body = client.get('/api/config').json()
    assert body['version'] == current_version()
    assert 'build' in body and body['build'] is None


def test_config_reports_the_build_when_recorded(client, monkeypatch):
    monkeypatch.setitem(VIEWER_CONFIG, 'password', '')
    monkeypatch.setenv('FACET_BUILD', ' local/test@dc6cb38b ')
    assert client.get('/api/config').json()['build'] == 'local/test@dc6cb38b'


def test_a_signed_in_caller_on_a_locked_install_gets_the_version(client, locked, monkeypatch):
    monkeypatch.setenv('FACET_BUILD', 'local/test@dc6cb38b')
    body = client.get('/api/config', headers=_bearer({'sub': '_legacy'})).json()
    assert body['version'] == current_version()
    assert body['build'] == 'local/test@dc6cb38b'


def test_a_visitor_on_a_locked_install_gets_neither(client, locked, monkeypatch):
    monkeypatch.setenv('FACET_BUILD', 'local/test@dc6cb38b')
    body = client.get('/api/config').json()
    assert 'version' not in body
    assert 'build' not in body


def test_a_token_naming_no_user_on_a_locked_install_gets_neither(client, locked, monkeypatch):
    monkeypatch.setenv('FACET_BUILD', 'local/test@dc6cb38b')
    body = client.get('/api/config', headers=_bearer({})).json()
    assert 'version' not in body
    assert 'build' not in body
