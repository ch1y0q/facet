"""Real revert effects: inverse entries, cache invalidation, origin and rollback."""

import json

import pytest
from fastapi import Response

from api.auth import CurrentUser
from api.database import get_db
from api.routers.organization_history import revert_history


def _entry(client, seed, prefix, kind, per_user=False):
    path = prefix + 'photo.jpg'
    seed(prefix, [dict(path=path, filename='photo.jpg', gps_latitude=1, gps_longitude=2,
                       gps_manually_set=0, date_taken='2024:01:01 00:00:00', date_manually_set=0,
                       star_rating=4, is_favorite=1, is_rejected=1, is_kept=0)])
    if per_user:
        with get_db() as conn, conn:
            conn.executemany('INSERT INTO user_preferences(user_id,photo_path,star_rating,is_favorite,is_rejected,is_kept) VALUES (?,?,?,?,?,?)',
                             [('test', path, 2, 1, 1, 0), ('bob', path, 5, 0, 0, 1)])
    if kind == 'gps':
        response = client.put('/api/photo/gps', json=dict(path=path, gps_latitude=3, gps_longitude=4))
    elif kind == 'date':
        body = dict(photo_paths=[path], offset_seconds=60)
        preview = client.post('/api/photos/capture_date/preview', json=body)
        assert preview.status_code == 200
        response = client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': preview.json()['preview_token']})
    else:
        response = client.post('/api/photos/batch_review', json=dict(photo_paths=[path], decision='kept'))
    assert response.status_code == 200, response.text
    result = client.get('/api/organization_history')
    assert result.status_code == 200
    entry = result.json()['entries'][0]
    assert entry['kind'] == kind
    assert entry['changes'][0]['path'] == path
    return path, entry


def _cache_probe(conn):
    conn.execute("INSERT OR REPLACE INTO stats_cache(key,value,updated_at) VALUES ('history_effects_probe','stale',1)")


@pytest.mark.parametrize('kind', ['gps', 'date', 'review'])
def test_revert_records_an_exact_inverse_and_invalidates_cached_statistics(edition_client, seed_photos_prefix, kind):
    from db.organization_history import FIELDS

    path, original = _entry(edition_client, seed_photos_prefix, f'/history-effects-{kind}/', kind)
    with get_db() as conn, conn:
        _cache_probe(conn)
        owner, scope = conn.execute('SELECT owner,scope FROM organization_history WHERE id=?', (original['id'],)).fetchone()
    response = edition_client.post(f"/api/organization_history/{original['id']}/revert")
    assert response.status_code == 200, response.text
    assert response.json() == {'changed': 1}
    assert response.headers['cache-control'] == 'no-store'
    with get_db() as conn:
        assert conn.execute("SELECT value FROM stats_cache WHERE key='history_effects_probe'").fetchone() is None
        assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (original['id'],)).fetchone()[0] == 1
        inverse = conn.execute('SELECT * FROM organization_history WHERE id>? ORDER BY id', (original['id'],)).fetchall()
        assert len(inverse) == 1
        inverse = inverse[0]
        assert (inverse['owner'], inverse['scope'], inverse['kind'], inverse['reverted']) == (owner, scope, kind, 0)
        changes = json.loads(inverse['payload'])
        assert len(changes) == 1
        assert (changes[0]['path'], changes[0]['before'], changes[0]['after']) == (
            path, original['changes'][0]['after'], original['changes'][0]['before'])
        columns = ','.join(FIELDS[kind])
        assert list(conn.execute(f'SELECT {columns} FROM photos WHERE path=?', (path,)).fetchone()) == changes[0]['after']
        inverse_id = inverse['id']
    # The new entry is an actual usable inverse, not merely an audit row.
    response = edition_client.post(f'/api/organization_history/{inverse_id}/revert')
    assert response.status_code == 200, response.text
    with get_db() as conn:
        assert list(conn.execute(f'SELECT {columns} FROM photos WHERE path=?', (path,)).fetchone()) == original['changes'][0]['after']
        assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (inverse_id,)).fetchone()[0] == 1


@pytest.mark.parametrize('agent', [False, True])
@pytest.mark.parametrize('per_user', [False, True])
def test_review_revert_records_the_actual_writer_without_touching_other_accounts(
    edition_client, seed_photos_prefix, monkeypatch, agent, per_user,
):
    from api import config

    prefix = f'/history-origin-{agent}-{per_user}/'
    if per_user:
        monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': [prefix]}, 'bob': {'directories': [prefix]}})
    path, original = _entry(edition_client, seed_photos_prefix, prefix, 'review', per_user=per_user)
    if per_user:
        assert original['changes'][0]['before'] == [2, 1, 1, 0]
    scope = 'test' if per_user else ''
    with get_db() as conn, conn:
        conn.executemany('INSERT INTO rating_provenance(user_id,photo_path,star_rating,is_favorite,is_rejected) VALUES (?,?,0,0,0)',
                         [(scope, path), ('bob', path)])
        other_before = tuple(conn.execute("SELECT * FROM rating_provenance WHERE user_id='bob' AND photo_path=?", (path,)).fetchone())
        global_before = tuple(conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM photos WHERE path=?', (path,)).fetchone())
        if per_user:
            other_preferences = tuple(conn.execute("SELECT * FROM user_preferences WHERE user_id='bob' AND photo_path=?", (path,)).fetchone())
    # Exercise the production route function with an explicit injected writer.
    # The edition_client above covers HTTP; this branch pins human/agent origin semantics.
    response = Response()
    assert revert_history(original['id'], response, CurrentUser(user_id='test', role='admin', edition_authenticated=True, agent=agent)) == {'changed': 1}
    assert response.headers['cache-control'] == 'no-store'
    with get_db() as conn:
        origin = conn.execute('SELECT star_rating,is_favorite,is_rejected FROM rating_provenance WHERE user_id=? AND photo_path=?', (scope, path)).fetchone()
        assert (tuple(origin) if origin else None) == (tuple(original['changes'][0]['before'][:3]) if agent else None)
        assert tuple(conn.execute("SELECT * FROM rating_provenance WHERE user_id='bob' AND photo_path=?", (path,)).fetchone()) == other_before
        if per_user:
            assert tuple(conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM photos WHERE path=?', (path,)).fetchone()) == global_before
            assert list(conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM user_preferences WHERE user_id=? AND photo_path=?', ('test', path)).fetchone()) == original['changes'][0]['before']
            assert tuple(conn.execute("SELECT * FROM user_preferences WHERE user_id='bob' AND photo_path=?", (path,)).fetchone()) == other_preferences


def _effects(conn, path):
    return {
        'photo': tuple(conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM photos WHERE path=?', (path,)).fetchone() or ()),
        'history': [tuple(row) for row in conn.execute('SELECT * FROM organization_history ORDER BY id')],
        'origin': [tuple(row) for row in conn.execute('SELECT * FROM rating_provenance WHERE photo_path=? ORDER BY user_id', (path,))],
        'cache': tuple(conn.execute("SELECT * FROM stats_cache WHERE key='history_effects_probe'").fetchone() or ()),
    }


@pytest.mark.parametrize('reason,status', [('missing', 404), ('unavailable', 404), ('conflict', 409), ('already-reverted', 409)])
def test_refused_revert_keeps_history_origin_and_cached_statistics(edition_client, seed_photos_prefix, reason, status):
    path, original = _entry(edition_client, seed_photos_prefix, f'/history-refusal-{reason}/', 'review')
    with get_db() as conn, conn:
        _cache_probe(conn)
        conn.execute('INSERT INTO rating_provenance(user_id,photo_path,star_rating,is_favorite,is_rejected) VALUES (?,?,4,1,0)', ('', path))
        if reason == 'unavailable':
            conn.execute('DELETE FROM photos WHERE path=?', (path,))
        elif reason == 'conflict':
            conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (path,))
        elif reason == 'already-reverted':
            conn.execute('UPDATE organization_history SET reverted=1 WHERE id=?', (original['id'],))
        before = _effects(conn, path)
    target = original['id'] + 1000000 if reason == 'missing' else original['id']
    response = edition_client.post(f'/api/organization_history/{target}/revert')
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'no-store'
    with get_db() as conn:
        assert _effects(conn, path) == before


def test_failure_after_origin_and_inverse_writes_rolls_back_every_effect_then_retries(edition_client, seed_photos_prefix):
    path, original = _entry(edition_client, seed_photos_prefix, '/history-effects-rollback/', 'review')
    with get_db() as conn, conn:
        _cache_probe(conn)
        conn.execute('INSERT INTO rating_provenance(user_id,photo_path,star_rating,is_favorite,is_rejected) VALUES (?,?,4,1,0)', ('', path))
        conn.execute("CREATE TRIGGER refuse_history_cache_delete BEFORE DELETE ON stats_cache "
                     "WHEN OLD.key='history_effects_probe' BEGIN SELECT RAISE(ABORT,'private storage failure'); END")
        before = _effects(conn, path)
    try:
        response = edition_client.post(f"/api/organization_history/{original['id']}/revert")
        assert response.status_code == 500
        assert response.json() == {'detail': 'Could not restore history'}
        assert response.headers['cache-control'] == 'no-store'
        with get_db() as conn:
            assert _effects(conn, path) == before
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER refuse_history_cache_delete')
    assert edition_client.post(f"/api/organization_history/{original['id']}/revert").status_code == 200
    with get_db() as conn:
        assert conn.execute("SELECT * FROM stats_cache WHERE key='history_effects_probe'").fetchone() is None
        assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (original['id'],)).fetchone()[0] == 1
