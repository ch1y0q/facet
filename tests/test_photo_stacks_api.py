"""HTTP stack mutations and shared organization Undo."""
import pytest

from api.database import get_db


@pytest.fixture(autouse=True)
def clear_stacks(monkeypatch):
    from api.auth import VIEWER_CONFIG
    monkeypatch.setitem(VIEWER_CONFIG, 'edition_password', 'test-stack-edition')
    with get_db() as conn, conn:
        conn.execute('DELETE FROM photo_stack_members')
        conn.execute('DELETE FROM photo_stacks')
        conn.execute("DELETE FROM organization_history WHERE kind='stack'")
    yield
    with get_db() as conn, conn:
        conn.execute('DELETE FROM photo_stack_members')
        conn.execute('DELETE FROM photo_stacks')
        conn.execute("DELETE FROM organization_history WHERE kind='stack'")


def seed(seed_photos_prefix):
    paths = ['/stack-api/' + p + '.jpg' for p in 'abcd']
    seed_photos_prefix('/stack-api/', [dict(path=p, filename=p.rsplit('/', 1)[-1], is_kept=1) for p in paths])
    return paths


def test_http_create_update_unstack_undo(edition_client, seed_photos_prefix):
    a, b, c, _ = seed(seed_photos_prefix)
    response = edition_client.post('/api/stacks', json=dict(paths=[a, b, c], cover_path=b))
    assert response.status_code == 201, response.text
    created = response.json()
    stack = created['stack']
    assert edition_client.get('/api/stacks/by-photo', params=dict(path=a)).json() == stack
    assert edition_client.get('/api/stacks/' + stack['id']).json() == stack
    update = edition_client.put('/api/stacks/' + stack['id'], json=dict(paths=[a, c], cover_path=c, expected_revision=stack['revision']))
    assert update.status_code == 200, update.text
    assert edition_client.delete('/api/stacks/' + stack['id'], params=dict(expected_revision=stack['revision'])).status_code == 409
    reverted = edition_client.post('/api/organization_history/' + str(update.json()['undo']['entry_id']) + '/revert')
    assert reverted.status_code == 200, reverted.text
    restored = edition_client.get('/api/stacks/' + stack['id']).json()
    assert restored['members'] == stack['members'] and restored['cover_path'] == b
    assert edition_client.post('/api/organization_history/' + str(created['undo']['entry_id']) + '/revert').status_code == 409
    deleted = edition_client.delete('/api/stacks/' + stack['id'], params=dict(expected_revision=restored['revision']))
    assert deleted.status_code == 200
    assert edition_client.get('/api/stacks/by-photo', params=dict(path=a)).json() is None
    assert edition_client.post('/api/organization_history/' + str(deleted.json()['undo']['entry_id']) + '/revert').status_code == 200
    with get_db() as conn:
        assert [r[0] for r in conn.execute("SELECT is_kept FROM photos WHERE path LIKE '/stack-api/%'")] == [1] * 4


def test_mutations_require_edition(regular_client):
    assert regular_client.post('/api/stacks', json=dict(paths=['a', 'b'], cover_path='a')).status_code == 403
    assert regular_client.put('/api/stacks/x', json=dict(paths=['a', 'b'], cover_path='a', expected_revision=1)).status_code == 403
    assert regular_client.delete('/api/stacks/x', params=dict(expected_revision=1)).status_code == 403


def test_partial_visibility_refuses_every_organization_edit(edition_client, seed_photos_prefix, monkeypatch):
    from api import config
    a, b, c, _ = seed(seed_photos_prefix)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': ['/stack-api/']}})
    created = edition_client.post('/api/stacks', json=dict(paths=[a, b, c], cover_path=a)).json()
    stack = created['stack']
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': [], 'files': [b, c]}})
    # Configure explicit visibility through the production clause interface.
    monkeypatch.setattr('api.routers.stacks.get_visibility_clause', lambda _: ('photos.path IN (?,?)', [b, c]))
    partial = edition_client.get('/api/stacks/' + stack['id']).json()
    assert partial['cover_path'] == b and not partial['editable']
    assert a not in str(partial)
    for response in (
        edition_client.put('/api/stacks/' + stack['id'], json=dict(paths=[b, c], cover_path=b, expected_revision=stack['revision'])),
        edition_client.delete('/api/stacks/' + stack['id'], params=dict(expected_revision=stack['revision'])),
    ):
        assert response.status_code == 409 and a not in response.text
    monkeypatch.setattr('api.routers.organization_history.get_visibility_clause', lambda _: ('photos.path IN (?,?)', [b, c]))
    assert edition_client.post('/api/organization_history/' + str(created['undo']['entry_id']) + '/revert').status_code == 409


def test_create_and_two_member_removal_undo_and_membership_add(edition_client, seed_photos_prefix):
    a, b, c, _ = seed(seed_photos_prefix)
    created = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)).json()
    assert edition_client.post(f"/api/organization_history/{created['undo']['entry_id']}/revert").status_code == 200
    assert edition_client.get('/api/stacks/by-photo', params=dict(path=a)).json() is None
    created = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)).json()
    stack = created['stack']
    added = edition_client.put('/api/stacks/' + stack['id'], json=dict(paths=[a, b, c], cover_path=a, expected_revision=stack['revision'])).json()
    assert edition_client.post(f"/api/organization_history/{added['undo']['entry_id']}/revert").status_code == 200
    stack = edition_client.get('/api/stacks/' + stack['id']).json()
    removed = edition_client.put('/api/stacks/' + stack['id'], json=dict(paths=[b], expected_revision=stack['revision'])).json()
    assert removed['stack'] is None
    assert edition_client.post(f"/api/organization_history/{removed['undo']['entry_id']}/revert").status_code == 200
    assert len(edition_client.get('/api/stacks/' + stack['id']).json()['members']) == 2


def test_multiuser_private_owner_and_singleuser_readonly(edition_client, regular_client, seed_photos_prefix, monkeypatch):
    from api import config
    a, b, _, _ = seed(seed_photos_prefix)
    # All configured accounts may see the same photos, but stacks remain private.
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': ['/stack-api/']}, 'u1': {'directories': ['/stack-api/']}})
    created = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)).json()
    stack = created['stack']
    assert regular_client.get('/api/stacks/' + stack['id']).json() is None
    assert regular_client.get('/api/stacks/by-photo', params=dict(path=a)).json() is None
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    installation = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)).json()['stack']
    read = regular_client.get('/api/stacks/' + installation['id'])
    assert read.status_code == 200 and read.json()['editable'] is False
    assert len(read.json()['members']) == 2


def test_history_failure_rolls_back_http_and_errors_are_private(edition_client, seed_photos_prefix):
    a, b, _, _ = seed(seed_photos_prefix)
    with get_db() as conn, conn:
        conn.execute("CREATE TRIGGER fail_stack_history BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT,'private /server/db'); END")
    try:
        response = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a))
        assert response.status_code == 500 and '/server/db' not in response.text
        assert response.headers['cache-control'] == 'no-store'
        with get_db() as conn:
            assert conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0
            assert conn.execute('SELECT count(*) FROM photo_stack_members').fetchone()[0] == 0
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER fail_stack_history')


def test_undo_refuses_membership_reuse_after_dissolve(edition_client, seed_photos_prefix):
    a, b, c, _ = seed(seed_photos_prefix)
    old = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)).json()['stack']
    deleted = edition_client.delete('/api/stacks/' + old['id'], params=dict(expected_revision=old['revision'])).json()
    newer = edition_client.post('/api/stacks', json=dict(paths=[a, c], cover_path=c)).json()['stack']
    assert edition_client.post(f"/api/organization_history/{deleted['undo']['entry_id']}/revert").status_code == 409
    assert edition_client.get('/api/stacks/' + newer['id']).json() == newer


def test_partial_snapshot_does_not_expose_hidden_order(edition_client, seed_photos_prefix, monkeypatch):
    a, b, c, _ = seed(seed_photos_prefix)
    stack = edition_client.post('/api/stacks', json=dict(paths=[a, b, c], cover_path=a)).json()['stack']
    monkeypatch.setattr('api.routers.stacks.get_visibility_clause', lambda _: ('photos.path=?', [c]))
    read = edition_client.get('/api/stacks/' + stack['id']).json()
    assert read['members'] == [dict(path=c, position=0)]
    assert read['cover_path'] == c and read['editable'] is False


def test_stack_mutations_and_undo_preserve_durable_state(edition_client, seed_photos_prefix):
    a, b, c, _ = seed(seed_photos_prefix)
    durable = {
        'keeper_head:global': b'\x00trained weights\xff',
        'immich_synced_paths:global': b'["remote-clear-receipt"]',
        'percentiles_snapshot': b'{"distribution":42}',
        'refresh_thumbnails_watermark': b'2026-10-27T00:01:02',
        'auto_retrain_pending:global': b'17',
    }
    with get_db() as conn, conn:
        conn.executemany('INSERT OR REPLACE INTO stats_cache(key,value,updated_at) VALUES (?,?,1)', durable.items())

    def prepare():
        with get_db() as conn, conn:
            conn.execute("INSERT OR REPLACE INTO stats_cache VALUES ('stack-gallery-derived','outdated',1)")

    def check(response):
        assert response.status_code in (200, 201), response.text
        with get_db() as conn:
            rows = dict(conn.execute('SELECT key,value FROM stats_cache'))
        assert {k: rows.get(k) for k in durable} == durable
        assert 'stack-gallery-derived' not in rows
        return response.json()

    try:
        prepare()
        created = check(edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)))
        stack = created['stack']
        prepare()
        noop = check(edition_client.put('/api/stacks/' + stack['id'], json=dict(paths=[a, b], cover_path=a, expected_revision=stack['revision'])))
        assert noop['undo'] is None
        prepare()
        changed = check(edition_client.put('/api/stacks/' + stack['id'], json=dict(paths=[a, b, c], cover_path=c, expected_revision=stack['revision'])))
        prepare()
        check(edition_client.post(f"/api/organization_history/{changed['undo']['entry_id']}/revert"))
        stack = edition_client.get('/api/stacks/' + stack['id']).json()
        prepare()
        deleted = check(edition_client.delete('/api/stacks/' + stack['id'], params=dict(expected_revision=stack['revision'])))
        prepare()
        check(edition_client.post(f"/api/organization_history/{deleted['undo']['entry_id']}/revert"))
    finally:
        with get_db() as conn, conn:
            conn.executemany('DELETE FROM stats_cache WHERE key=?', [(k,) for k in durable])


def test_full_member_replacement_keeps_one_atomic_history_entry_and_undo(edition_client, seed_photos_prefix):
    old_paths = [f'/stack-replacement/old-{i}.jpg' for i in range(1000)]
    new_paths = [f'/stack-replacement/new-{i}.jpg' for i in range(1000)]
    seed_photos_prefix('/stack-replacement/', [dict(path=p, filename=p.rsplit('/', 1)[-1], is_kept=1)
                                              for p in old_paths + new_paths])
    created = edition_client.post('/api/stacks', json=dict(paths=old_paths, cover_path=old_paths[-1]))
    assert created.status_code == 201, created.text
    original = created.json()['stack']
    replaced = edition_client.put('/api/stacks/' + original['id'], json=dict(
        paths=new_paths, cover_path=new_paths[0], expected_revision=original['revision']))
    assert replaced.status_code == 200, replaced.text
    entry_id = replaced.json()['undo']['entry_id']
    history = edition_client.get('/api/organization_history').json()['entries']
    entry = next(entry for entry in history if entry['id'] == entry_id)
    assert len(entry['changes']) == 2000
    assert entry['part'] == entry['parts'] == 1
    reverted = edition_client.post(f'/api/organization_history/{entry_id}/revert')
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()['changed'] == 2000
    restored = edition_client.get('/api/stacks/' + original['id']).json()
    assert restored['members'] == original['members']
    assert restored['cover_path'] == old_paths[-1]
    assert edition_client.get('/api/stacks/by-photo', params=dict(path=new_paths[0])).json() is None
    with get_db() as conn:
        assert conn.execute("SELECT count(*) FROM photos WHERE path LIKE '/stack-replacement/%' AND is_kept=1").fetchone()[0] == 2000


def test_single_user_stack_does_not_become_installation_named_accounts_stack(edition_client, seed_photos_prefix, monkeypatch):
    from api import config
    from api.auth import CurrentUser, get_optional_user, require_authenticated, require_edition

    a, b, _, _ = seed(seed_photos_prefix)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    single_user = CurrentUser(user_id=None, role='admin', edition_authenticated=True)
    for dependency in (get_optional_user, require_authenticated, require_edition):
        edition_client.app.dependency_overrides[dependency] = lambda: single_user
    created = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a))
    assert created.status_code == 201, created.text
    installation_stack = created.json()['stack']
    installation_entry = created.json()['undo']['entry_id']

    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'installation': {'directories': ['/stack-api/']}})
    account = CurrentUser(user_id='installation', role='admin', edition_authenticated=True)
    for dependency in (get_optional_user, require_authenticated, require_edition):
        edition_client.app.dependency_overrides[dependency] = lambda: account
    assert edition_client.get('/api/stacks/' + installation_stack['id']).json() is None
    assert edition_client.get('/api/stacks/by-photo', params=dict(path=a)).json() is None
    listing = edition_client.get('/api/photos', params=dict(path_prefix='/stack-api/')).json()
    assert listing['total'] == listing['photo_total'] == 4
    assert all(not photo.get('stack_id') for photo in listing['photos'])
    history = edition_client.get('/api/organization_history').json()['entries']
    assert all(entry['id'] != installation_entry for entry in history)
    assert edition_client.post(f'/api/organization_history/{installation_entry}/revert').status_code == 404
    personal = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=b))
    assert personal.status_code == 201, personal.text
    assert personal.json()['stack']['id'] != installation_stack['id']
    assert edition_client.get('/api/stacks/by-photo', params=dict(path=a)).json()['cover_path'] == b

    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    for dependency in (get_optional_user, require_authenticated, require_edition):
        edition_client.app.dependency_overrides[dependency] = lambda: single_user
    assert edition_client.get('/api/stacks/' + installation_stack['id']).json() == installation_stack
    assert edition_client.get('/api/stacks/' + personal.json()['stack']['id']).json() is None


def test_single_user_review_and_stack_history_share_one_retention_budget(edition_client, seed_photos_prefix, monkeypatch):
    from api import config
    from api.auth import CurrentUser, get_optional_user, require_authenticated, require_edition

    a, b, _, _ = seed(seed_photos_prefix)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    user = CurrentUser(user_id=None, role='admin', edition_authenticated=True)
    for dependency in (get_optional_user, require_authenticated, require_edition):
        edition_client.app.dependency_overrides[dependency] = lambda: user
    created = edition_client.post('/api/stacks', json=dict(paths=[a, b], cover_path=a)).json()['stack']
    for index in range(50):
        response = edition_client.post('/api/photos/batch_review', json=dict(
            photo_paths=[a], decision='undecided' if index % 2 == 0 else 'kept'))
        assert response.status_code == 200, response.text
    changed = edition_client.put('/api/stacks/' + created['id'], json=dict(
        paths=[b, a], cover_path=b, expected_revision=created['revision']))
    assert changed.status_code == 200, changed.text
    with get_db() as conn:
        assert conn.execute("SELECT count(*) FROM organization_history WHERE owner=''").fetchone()[0] == 50
        assert conn.execute("SELECT count(*) FROM organization_history WHERE kind='stack' AND owner!=''").fetchone()[0] == 0
    entries = edition_client.get('/api/organization_history').json()['entries']
    assert len(entries) == 50
    assert entries[0]['id'] == changed.json()['undo']['entry_id']
    assert {entry['kind'] for entry in entries} == {'review', 'stack'}
