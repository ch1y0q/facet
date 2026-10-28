"""GET /api/config carries the running version and, when recorded, the build it came from."""

from utils.version import current_version


def test_config_reports_the_release_version(client, monkeypatch):
    monkeypatch.delenv('FACET_BUILD', raising=False)
    body = client.get('/api/config').json()
    assert body['version'] == current_version()
    assert body.get('build') is None


def test_config_reports_the_build_when_recorded(client, monkeypatch):
    monkeypatch.setenv('FACET_BUILD', ' local/test@dc6cb38b ')
    assert client.get('/api/config').json()['build'] == 'local/test@dc6cb38b'
