"""Suggestion discovery never writes decisions or broadens the reviewed set."""
import pytest

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
    # The other account's stack must not hide or shrink this account's suggestion.
    assert set(own.json()['suggestions'][0]['paths']) == set(paths)


def test_unknown_filters_refuse_and_readonly_can_discover(regular_client):
    response = regular_client.post('/api/stacks/suggestions', json={'filters': {'unexpected_scope': 'x'}})
    assert response.status_code == 422
    assert discover(regular_client).status_code == 200


def test_burst_group_is_suggested_with_its_lead_as_cover(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET duplicate_group_id=NULL WHERE path LIKE '/suggestions/%'")
    suggestions = discover(edition_client).json()['suggestions']
    assert len(suggestions) == 1 and suggestions[0]['kind'] == 'burst'
    assert set(suggestions[0]['paths']) == set(paths)
    assert suggestions[0]['cover_path'] == paths[0]


def test_json_number_and_boolean_filters_match_their_string_form(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET is_rejected=1 WHERE path=?', (paths[-1],))
    typed = discover(edition_client, hide_rejected=True, per_page=50)
    assert typed.status_code == 200, typed.text
    assert typed.json() == discover(edition_client, hide_rejected='true', per_page='50').json()
    assert set(typed.json()['suggestions'][0]['paths']) == set(paths[:2])


def test_invalid_filter_value_is_a_422(edition_client):
    assert discover(edition_client, per_page='0').status_code == 422


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


@pytest.fixture(autouse=True)
def _drop_dismissals():
    yield
    with get_db() as conn, conn:
        conn.execute("DELETE FROM stack_suggestion_dismissals WHERE photo_path LIKE '/suggestions/%'")


def skip(client, suggestion):
    return client.post('/api/stacks/suggestions/dismissals',
                       json={'kind': suggestion['kind'], 'paths': suggestion['paths']})


def test_dismissal_persists_and_can_be_restored(edition_client, regular_client, seed_photos_prefix):
    seed(seed_photos_prefix)
    duplicate = discover(edition_client).json()['suggestions'][0]
    assert skip(edition_client, duplicate).status_code == 204
    assert skip(edition_client, duplicate).status_code == 204
    # The same photos' burst group is a different suggestion and surfaces instead.
    [burst] = discover(edition_client).json()['suggestions']
    assert burst['kind'] == 'burst'
    assert skip(regular_client, burst).status_code == 403
    assert skip(edition_client, burst).status_code == 204
    assert discover(edition_client).json()['suggestions'] == []
    assert edition_client.delete(f"/api/stacks/suggestions/dismissals/{duplicate['key']}").status_code == 204
    assert [s['key'] for s in discover(edition_client).json()['suggestions']] == [duplicate['key']]


def test_skip_is_lifted_when_membership_changes(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    for suggestion in discover(edition_client).json()['suggestions']:
        skip(edition_client, suggestion)
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET burst_group_id=NULL, duplicate_group_id=NULL WHERE path=?', (paths[2],))
    assert {s['kind'] for s in discover(edition_client).json()['suggestions']} == {'duplicate'}


def test_skips_are_private_to_each_account(edition_client, regular_client, seed_photos_prefix, monkeypatch):
    from api import config
    from api.routers import stacks as stacks_router
    seed(seed_photos_prefix)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': ['/suggestions/']}, 'u1': {'directories': ['/suggestions/']}})
    monkeypatch.setattr(stacks_router, 'is_multi_user_enabled', lambda: True)
    first = discover(edition_client).json()['suggestions']
    # The duplicate and burst groups cover the same photos: at most two skips empty the feed.
    for _ in range(2):
        suggestions = discover(edition_client).json()['suggestions']
        if suggestions:
            assert skip(edition_client, suggestions[0]).status_code == 204
    assert discover(edition_client).json()['suggestions'] == []
    assert [s['key'] for s in discover(regular_client).json()['suggestions']] == [first[0]['key']]


def test_dismissal_requests_are_validated(edition_client):
    for body in ({'kind': 'burst', 'paths': ['/a.jpg']}, {'kind': 'scene', 'paths': ['/a.jpg', '/b.jpg']}):
        assert edition_client.post('/api/stacks/suggestions/dismissals', json=body).status_code == 422
    assert edition_client.delete('/api/stacks/suggestions/dismissals/NOTAHASH').status_code == 422


def test_skipped_groups_do_not_use_up_the_candidate_window(edition_client, seed_photos_prefix, monkeypatch):
    from db import stack_suggestions
    monkeypatch.setattr(stack_suggestions, 'MAX_CANDIDATE_GROUPS', 2)
    rows = [dict(path=f'/suggestions/{n}.jpg', filename=f'{n}.jpg', burst_group_id=900100 + n // 2)
            for n in range(8)]
    seed_photos_prefix('/suggestions/', rows)
    first = discover(edition_client).json()['suggestions']
    assert len(first) == 2
    for suggestion in first:
        skip(edition_client, suggestion)
    later = discover(edition_client).json()['suggestions']
    assert len(later) == 2 and not {s['key'] for s in later} & {s['key'] for s in first}


def test_deleting_a_photo_drops_its_skip_rows(edition_client, seed_photos_prefix):
    seed(seed_photos_prefix)
    skip(edition_client, discover(edition_client).json()['suggestions'][0])
    with get_db() as conn, conn:
        conn.execute("DELETE FROM photos WHERE path='/suggestions/0.jpg'")
        assert conn.execute("SELECT COUNT(*) FROM stack_suggestion_dismissals WHERE photo_path='/suggestions/0.jpg'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM stack_suggestion_dismissals WHERE photo_path LIKE '/suggestions/%'").fetchone()[0] == 2


def skip_rows(owner):
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM stack_suggestion_dismissals WHERE owner=? AND photo_path LIKE '/suggestions/%'",
                            (owner,)).fetchone()[0]


def test_restore_only_lifts_the_callers_own_skip(edition_client, superadmin_client, seed_photos_prefix, monkeypatch):
    from api import config
    from api.routers import stacks as stacks_router
    seed(seed_photos_prefix)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': ['/suggestions/']}, 'root': {'directories': ['/suggestions/']}})
    monkeypatch.setattr(stacks_router, 'is_multi_user_enabled', lambda: True)
    duplicate = discover(edition_client).json()['suggestions'][0]
    assert skip(edition_client, duplicate).status_code == 204
    assert skip_rows('test') == 3
    # The key is a content hash, so any account that sees these photos can compute it.
    assert superadmin_client.delete(f"/api/stacks/suggestions/dismissals/{duplicate['key']}").status_code == 204
    assert skip_rows('test') == 3
    assert duplicate['key'] not in {s['key'] for s in discover(edition_client).json()['suggestions']}
    assert edition_client.delete(f"/api/stacks/suggestions/dismissals/{duplicate['key']}").status_code == 204
    assert skip_rows('test') == 0


def test_skipped_group_that_gains_a_photo_is_suggested_again(edition_client, seed_photos_prefix):
    seed_photos_prefix('/suggestions/', [dict(path=f'/suggestions/{n}.jpg', filename=f'{n}.jpg',
        duplicate_group_id=900002 if n < 3 else None) for n in range(4)])
    [group] = discover(edition_client).json()['suggestions']
    assert len(group['paths']) == 3
    assert skip(edition_client, group).status_code == 204
    assert discover(edition_client).json()['suggestions'] == []
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET duplicate_group_id=900002 WHERE path='/suggestions/3.jpg'")
    [grown] = discover(edition_client).json()['suggestions']
    assert len(grown['paths']) == 4 and grown['key'] != group['key']


def test_skip_matches_the_membership_under_the_filters_it_was_made_with(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix)
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET burst_group_id=NULL WHERE path LIKE '/suggestions/%'")
        conn.execute('UPDATE photos SET is_rejected=1 WHERE path=?', (paths[-1],))
    [narrow] = discover(edition_client, hide_rejected='true').json()['suggestions']
    assert len(narrow['paths']) == 2
    assert skip(edition_client, narrow).status_code == 204
    assert discover(edition_client, hide_rejected='true').json()['suggestions'] == []
    # Without the filter the group has three members, which is not what was skipped.
    [wide] = discover(edition_client).json()['suggestions']
    assert len(wide['paths']) == 3
    assert skip(edition_client, wide).status_code == 204
    assert discover(edition_client).json()['suggestions'] == []
    assert discover(edition_client, hide_rejected='true').json()['suggestions'] == []
    assert edition_client.delete(f"/api/stacks/suggestions/dismissals/{narrow['key']}").status_code == 204
    # Only the narrow skip was lifted, so the wide read stays skipped.
    assert discover(edition_client).json()['suggestions'] == []
    assert len(discover(edition_client, hide_rejected='true').json()['suggestions']) == 1


def test_moving_a_photo_carries_its_skip_rows_along(edition_client, seed_photos_prefix):
    seed(seed_photos_prefix)
    skip(edition_client, discover(edition_client).json()['suggestions'][0])
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET path='/suggestions/moved.jpg' WHERE path='/suggestions/0.jpg'")
        old = conn.execute("SELECT COUNT(*) FROM stack_suggestion_dismissals WHERE photo_path='/suggestions/0.jpg'").fetchone()[0]
        new = conn.execute("SELECT COUNT(*) FROM stack_suggestion_dismissals WHERE photo_path='/suggestions/moved.jpg'").fetchone()[0]
    assert (old, new) == (0, 1)


def test_skipped_lookup_uses_an_index_on_the_group_id(edition_client, seed_photos_prefix):
    """A bare CASE has no type affinity, so SQLite's automatic index drops the group id and the
    check scans every skipped group per candidate."""
    from api.routers.gallery import gallery_scope_sql
    from db import stack_suggestions
    seed(seed_photos_prefix)
    statements = []
    with get_db() as conn:
        conn.set_trace_callback(statements.append)
        source, where, params = gallery_scope_sql(conn, {'path_prefix': '/suggestions/', 'collapse_stacks': 'false'}, 'test')
        stack_suggestions.suggestions(conn, '', source, where, params)
        conn.set_trace_callback(None)
        [sql] = [q for q in statements if q.lstrip().startswith('WITH scoped')]
        plan = ' '.join(r[3] for r in conn.execute('EXPLAIN QUERY PLAN ' + sql))
    assert 'AUTOMATIC COVERING INDEX (kind=? AND group_id=?' in plan, plan


def test_skipped_group_with_a_swapped_member_is_suggested_again(edition_client, seed_photos_prefix):
    seed_photos_prefix('/suggestions/', [dict(path=f'/suggestions/{n}.jpg', filename=f'{n}.jpg',
        duplicate_group_id=900002 if n < 3 else None) for n in range(4)])
    assert skip(edition_client, discover(edition_client).json()['suggestions'][0]).status_code == 204
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET duplicate_group_id=NULL WHERE path='/suggestions/2.jpg'")
        conn.execute("UPDATE photos SET duplicate_group_id=900002 WHERE path='/suggestions/3.jpg'")
    [swapped] = discover(edition_client).json()['suggestions']
    assert len(swapped['paths']) == 3 and '/suggestions/3.jpg' in swapped['paths']
