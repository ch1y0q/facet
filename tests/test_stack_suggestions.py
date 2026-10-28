"""Suggestion discovery never writes decisions or broadens the reviewed set."""
from api.database import get_db


def seed(seed_photos_prefix, **overrides):
    rows = [dict(path=f'/suggestions/{n}.jpg', filename=f'{n}.jpg',
                 burst_group_id=900001, duplicate_group_id=900002,
                 is_burst_lead=int(n == 0), is_duplicate_lead=int(n == 1), **overrides)
            for n in range(3)]
    seed_photos_prefix('/suggestions/', rows)
    return [r['path'] for r in rows]


def discover(client, **filters):
    return client.post('/api/stacks/suggestions', json={'filters': {'path_prefix': '/suggestions/', **filters}})


def test_suggestions_bypass_only_group_hiding_and_prefer_nonoverlapping_duplicates(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    with get_db() as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM photos WHERE path LIKE '/suggestions/%' ORDER BY path")]
    response = discover(edition_client, hide_bursts='true', hide_duplicates='true')
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    suggestions = response.json()['suggestions']
    assert len(suggestions) == 1 and suggestions[0]['kind'] == 'duplicate'
    assert set(suggestions[0]['paths']) == set(paths)
    assert suggestions[0]['cover_path'] == paths[1]
    with get_db() as conn:
        assert [tuple(r) for r in conn.execute("SELECT * FROM photos WHERE path LIKE '/suggestions/%' ORDER BY path")] == before
        assert conn.execute("SELECT COUNT(*) FROM photo_stack_members WHERE photo_path LIKE '/suggestions/%'").fetchone()[0] == 0


def test_preserves_filters_and_skips_existing_owner_stacks(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET is_rejected=1 WHERE path=?', (paths[-1],))
    visible = discover(edition_client, hide_rejected='true').json()['suggestions']
    assert len(visible) == 1 and set(visible[0]['paths']) == set(paths[:2])
    assert discover(edition_client, path_prefix='/no-matching-root/').json()['suggestions'] == []
    create = edition_client.post('/api/stacks', json={'paths': paths[:2], 'cover_path': paths[0]})
    assert create.status_code == 201, create.text
    assert discover(edition_client).json()['suggestions'] == []


def test_sequence_sets_and_singletons_are_not_suggested(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, sequence_kind='bracket', sequence_group_id=900004)
    assert discover(edition_client).json()['suggestions'] == []
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET sequence_kind=NULL, burst_group_id=NULL,duplicate_group_id=NULL WHERE path LIKE '/suggestions/%'")
        conn.execute('UPDATE photos SET burst_group_id=900001 WHERE path=?', (paths[0],))
    assert discover(edition_client).json()['suggestions'] == []


def test_visibility_is_applied_before_grouping_and_private_stacks_do_not_cross_accounts(
        edition_client, regular_client, seed_photos_prefix, monkeypatch):
    from api import config
    paths = seed(seed_photos_prefix)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': ['/suggestions/']},
        'u1': {'directories': ['/other/']},
    })
    assert discover(regular_client).json()['suggestions'] == []
    assert len(discover(edition_client).json()['suggestions']) == 1
    created = edition_client.post('/api/stacks', json={'paths': paths[:2], 'cover_path': paths[0]})
    assert created.status_code == 201
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': ['/suggestions/']},
        'u1': {'directories': ['/suggestions/']},
    })
    own = discover(regular_client)
    assert own.status_code == 200 and len(own.json()['suggestions']) == 1
    assert 'stack_id' not in str(own.json())


def test_unknown_filters_refuse_and_readonly_can_discover(regular_client):
    response = regular_client.post('/api/stacks/suggestions', json={'filters': {'unexpected_scope': 'x'}})
    assert response.status_code == 422
    assert discover(regular_client).status_code == 200


def test_stale_acceptance_refuses_existing_stack_without_modifying_decisions(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    proposal = discover(edition_client).json()['suggestions'][0]
    first = edition_client.post('/api/stacks', json={'paths': paths[:2], 'cover_path': paths[0]})
    assert first.status_code == 201
    with get_db() as conn:
        history_count = conn.execute("SELECT COUNT(*) FROM organization_history WHERE kind='stack'").fetchone()[0]
    stale = edition_client.post('/api/stacks', json={'paths': proposal['paths'], 'cover_path': proposal['cover_path']})
    assert stale.status_code == 409
    with get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM photo_stack_members WHERE photo_path LIKE '/suggestions/%'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM organization_history WHERE kind='stack'").fetchone()[0] == history_count


def test_partial_visibility_never_exposes_hidden_member_or_hidden_cover(regular_client, seed_photos_prefix, monkeypatch):
    from api import config
    paths = ['/suggestion-scope/visible/a.jpg', '/suggestion-scope/visible/b.jpg', '/suggestion-scope/hidden/c.jpg']
    seed_photos_prefix('/suggestion-scope/', [dict(path=p, filename=p.rsplit('/', 1)[-1],
        duplicate_group_id=900005, is_duplicate_lead=int('/hidden/' in p)) for p in paths])
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'u1': {'directories': ['/suggestion-scope/visible/']}})
    response = regular_client.post('/api/stacks/suggestions', json={'filters': {'path_prefix': '/suggestion-scope/'}})
    assert response.status_code == 200
    candidate = response.json()['suggestions'][0]
    assert set(candidate['paths']) == set(paths[:2])
    assert candidate['cover_path'] in paths[:2]
    assert '/hidden/' not in response.text


def test_group_and_response_limits_are_bounded(edition_client, seed_photos_prefix):
    rows = [dict(path=f'/suggestion-bounds/{group}-{member}.jpg', filename=f'{group}-{member}.jpg',
                 duplicate_group_id=910000 + group) for group in range(45) for member in range(2)]
    # An oversized group must be skipped whole, never quietly truncated.
    rows += [dict(path=f'/suggestion-bounds/oversized-{i}.jpg', filename=f'oversized-{i}.jpg',
                  duplicate_group_id=909999) for i in range(1001)]
    seed_photos_prefix('/suggestion-bounds/', rows)
    result = edition_client.post('/api/stacks/suggestions', json={'filters': {'path_prefix': '/suggestion-bounds/'}})
    assert result.status_code == 200
    candidates = result.json()['suggestions']
    assert len(candidates) == 20
    assert all(len(c['paths']) == 2 for c in candidates)
    assert len({p for c in candidates for p in c['paths']}) == 40
    assert 'oversized' not in result.text


def test_reviewed_suggestion_creates_exact_members_cover_and_undo_without_file_or_decision_changes(
        edition_client, seed_photos_prefix, tmp_path):
    import hashlib
    import json
    import os
    prefix = str(tmp_path) + os.sep
    files = [tmp_path / f'{i}.jpg' for i in range(3)]
    for i, file in enumerate(files):
        file.write_bytes(f'original-{i}'.encode())
    paths = [str(p) for p in files]
    before_bytes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    seed_photos_prefix(prefix, [dict(path=p, filename=f'{i}.jpg', duplicate_group_id=900009,
        is_duplicate_lead=int(i == 1), is_kept=1, is_favorite=1, star_rating=4) for i, p in enumerate(paths)])
    with get_db() as conn:
        before = [tuple(r) for r in conn.execute('SELECT * FROM photos WHERE path IN (SELECT value FROM json_each(?)) ORDER BY path',
                   (json.dumps(paths),))]
    proposal = edition_client.post('/api/stacks/suggestions', json={'filters': {'path_prefix': prefix}}).json()['suggestions'][0]
    created = edition_client.post('/api/stacks', json={'paths': proposal['paths'], 'cover_path': proposal['cover_path']})
    assert created.status_code == 201, created.text
    stack = created.json()['stack']
    assert [m['path'] for m in stack['members']] == proposal['paths']
    assert stack['cover_path'] == proposal['cover_path'] == paths[1]
    with get_db() as conn:
        after = [tuple(r) for r in conn.execute('SELECT * FROM photos WHERE path IN (SELECT value FROM json_each(?)) ORDER BY path',
                 (json.dumps(paths),))]
    assert after == before
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in files] == before_bytes
    entry = created.json()['undo']['entry_id']
    assert edition_client.post(f'/api/organization_history/{entry}/revert').status_code == 200
    assert edition_client.get('/api/stacks/by-photo', params={'path': paths[0]}).json() is None


def test_total_member_budget_skips_whole_groups(edition_client, seed_photos_prefix):
    rows = [dict(path=f'/suggestion-budget/{g}-{i}.jpg', filename=f'{g}-{i}.jpg',
                 duplicate_group_id=920000 + g) for g in range(3) for i in range(900)]
    seed_photos_prefix('/suggestion-budget/', rows)
    result = edition_client.post('/api/stacks/suggestions', json={'filters': {'path_prefix': '/suggestion-budget/'}})
    assert result.status_code == 200
    candidates = result.json()['suggestions']
    assert [len(c['paths']) for c in candidates] == [900, 900]
    assert sum(len(c['paths']) for c in candidates) == 1800


def test_suggestion_identity_follows_membership_not_reused_detector_id(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    original = discover(edition_client).json()['suggestions'][0]
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET duplicate_group_id=900003 WHERE path LIKE '/suggestions/%'")
    renumbered = discover(edition_client).json()['suggestions'][0]
    assert renumbered['key'] == original['key']
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET duplicate_group_id=NULL,burst_group_id=NULL WHERE path=?', (paths[-1],))
    changed = discover(edition_client).json()['suggestions'][0]
    assert changed['key'] != original['key']
