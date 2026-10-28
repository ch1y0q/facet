"""Local stack tools through real MCP, HTTP authorization and temporary storage."""
import pytest

from api.agent.live_updates import frame_for
from api.database import get_db
from tests.conftest import AGENT_DIR, intercept_internal_call

P = [AGENT_DIR + f'stacks/{i}/photo.jpg' for i in range(4)]


@pytest.fixture()
def photos(seed_photos_prefix):
    seed_photos_prefix(AGENT_DIR, [dict(path=p, filename=p.rsplit('/', 1)[-1],
                                      star_rating=3, is_kept=1, is_rejected=0) for p in P])
    yield
    with get_db() as conn, conn:
        conn.execute("DELETE FROM organization_history WHERE kind='stack'")


@pytest.fixture()
def edition(agent_app, photos):
    env = agent_app('legacy')
    return env, env.token(env.login(edition=True), 'edition')


def create(env, token):
    result = env.call(token, 'create_photo_stack', dict(paths=P[:3], cover_path=P[1]))
    assert result['ok'], result
    assert result['data']['undo']['entry_id'] > 0
    return result['data']


def test_create_read_update_unstack_undo_preserve_decisions(edition):
    env, token = edition
    original = create(env, token)
    stack = original['stack']
    assert env.call(token, 'get_photo_stack', dict(path=P[0]))['data'] == stack
    updated = env.call(token, 'update_photo_stack', dict(stack_id=stack['id'], paths=[P[0], P[2], P[3]],
                       cover_path=P[3], expected_revision=stack['revision']))
    assert updated['ok'], updated
    assert updated['data']['stack']['cover_path'] == P[3]
    stale = env.call(token, 'unstack_photos', dict(stack_id=stack['id'], expected_revision=stack['revision']))
    assert not stale['ok']
    assert env.call(token, 'undo_photo_stack', updated['data']['undo'])['ok']
    restored = env.call(token, 'get_photo_stack', dict(path=P[0]))['data']
    assert restored['cover_path'] == P[1]
    assert [m['path'] for m in restored['members']] == P[:3]
    deleted = env.call(token, 'unstack_photos', dict(stack_id=stack['id'], expected_revision=restored['revision']))
    assert deleted['ok'] and deleted['data']['stack'] is None
    assert env.call(token, 'get_photo_stack', dict(path=P[0]))['data'] is None
    assert env.call(token, 'undo_photo_stack', deleted['data']['undo'])['ok']
    assert not env.call(token, 'undo_photo_stack', original['undo'])['ok']
    with get_db() as conn:
        rows = conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path IN (?,?,?,?)', P).fetchall()
    assert [tuple(row) for row in rows] == [(3, 1, 0)] * 4


@pytest.mark.parametrize('paths', [[], P[:1]])
def test_update_zero_or_one_member_dissolves(edition, paths):
    env, token = edition
    stack = create(env, token)['stack']
    result = env.call(token, 'update_photo_stack', dict(stack_id=stack['id'], paths=paths,
                       expected_revision=stack['revision']))
    assert result['ok'] and result['data']['stack'] is None
    assert env.call(token, 'get_photo_stack', dict(path=P[0]))['data'] is None


def test_owner_scope_and_edition_floor(agent_app, photos, monkeypatch):
    from api import config
    env = agent_app('multi')
    monkeypatch.setitem(config._FULL_CONFIG['users']['alice'], 'role', 'admin')
    monkeypatch.setitem(config._FULL_CONFIG['users']['bob'], 'directories', [AGENT_DIR])
    root = env.token(env.login('root'), 'edition')
    alice = env.token(env.login('alice'), 'edition')
    bob = env.token(env.login('bob'), 'user')
    stack = create(env, root)['stack']
    assert env.call(alice, 'get_photo_stack', dict(path=P[0]))['data'] is None
    assert not env.call(alice, 'unstack_photos', dict(stack_id=stack['id'], expected_revision=1))['ok']
    for name, args in (
        ('create_photo_stack', dict(paths=P[:2], cover_path=P[0])),
        ('update_photo_stack', dict(stack_id=stack['id'], paths=P[:2], expected_revision=1)),
        ('unstack_photos', dict(stack_id=stack['id'], expected_revision=1)),
        ('undo_photo_stack', dict(entry_id=1)),
    ):
        assert env.call(bob, name, args)['error'] == 'forbidden_level'
    assert env.call(root, 'get_photo_stack', dict(path=P[0]))['data'] == stack


@pytest.mark.parametrize('name,args', [
    ('get_photo_stack', {}), ('get_photo_stack', {'path': ''}),
    ('create_photo_stack', {'paths': P[:1], 'cover_path': P[0]}),
    ('create_photo_stack', {'paths': P * 251, 'cover_path': P[0]}),
    ('create_photo_stack', {'paths': ['', P[1]], 'cover_path': P[1]}),
    ('update_photo_stack', {'stack_id': 'not-uuid', 'paths': [], 'expected_revision': 1}),
    ('unstack_photos', {'stack_id': '../stacks', 'expected_revision': 1}),
    ('unstack_photos', {'stack_id': '00000000-0000-0000-0000-000000000001', 'expected_revision': 0}),
    ('undo_photo_stack', {'entry_id': 0}),
])
def test_invalid_inputs_never_route(edition, monkeypatch, name, args):
    env, token = edition
    calls = []
    intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
    assert env.call(token, name, args)['error'] == 'invalid_input'
    assert calls == []


def test_undo_rejects_unrelated_history_without_writing(edition, monkeypatch):
    env, token = edition
    headers = env.login(edition=True)
    edited = env.client.post('/api/photos/batch_review', headers=headers,
                             json=dict(photo_paths=[P[0]], decision='undecided'))
    assert edited.status_code == 200, edited.text
    history = env.client.get('/api/organization_history', headers=headers).json()['entries']
    entry = next(entry for entry in history if entry['kind'] == 'review' and entry['changes'][0]['path'] == P[0])
    calls = []
    intercept_internal_call(monkeypatch, lambda tool, kw: calls.append(tool))
    result = env.call(token, 'undo_photo_stack', dict(entry_id=entry['id']))
    assert not result['ok'] and result['error'] == 'invalid_input'
    assert calls == ['undo_photo_stack']
    with get_db() as conn:
        assert conn.execute('SELECT is_kept FROM photos WHERE path=?', [P[0]]).fetchone()[0] == 0


def test_undo_accepts_a_stack_entry_older_than_the_history_list_window(edition):
    env, token = edition
    created = create(env, token)
    with get_db() as conn, conn:
        conn.executemany("INSERT INTO organization_history(owner,kind,scope,payload,part,parts) VALUES ('','stack','','[]',1,1)",
                         [()] * 55)
    listed = env.client.get('/api/organization_history', headers=env.login(edition=True)).json()['entries']
    assert all(entry['id'] != created['undo']['entry_id'] for entry in listed)
    assert env.call(token, 'undo_photo_stack', created['undo'])['ok']
    assert env.call(token, 'get_photo_stack', dict(path=P[0]))['data'] is None


def test_partial_visibility_refuses_updates_unstack_and_undo(agent_app, photos, monkeypatch):
    from api import config
    env = agent_app('multi')
    token = env.token(env.login('root'), 'edition')
    created = create(env, token)
    stack = created['stack']
    monkeypatch.setitem(config._FULL_CONFIG['users']['root'], 'directories', [AGENT_DIR + 'stacks/1/', AGENT_DIR + 'stacks/2/'])
    partial = env.call(token, 'get_photo_stack', dict(path=P[1]))['data']
    assert not partial['editable'] and partial['cover_path'] == P[1]
    assert [member['path'] for member in partial['members']] == P[1:3]
    for name, args in (
        ('update_photo_stack', dict(stack_id=stack['id'], paths=P[1:3], expected_revision=stack['revision'])),
        ('unstack_photos', dict(stack_id=stack['id'], expected_revision=stack['revision'])),
        ('undo_photo_stack', created['undo']),
    ):
        refusal = env.call(token, name, args)
        assert not refusal['ok'] and P[0] not in str(refusal)
    monkeypatch.setitem(config._FULL_CONFIG['users']['root'], 'directories', [AGENT_DIR])
    assert env.call(token, 'get_photo_stack', dict(path=P[0]))['data'] == stack


def test_stack_writes_emit_library_refresh_hints(edition, monkeypatch):
    # InternalClient's actual on_write path is observed; no refresh is stubbed.
    from api.agent.internal_client import InternalClient
    env, token = edition
    frames = []
    original = InternalClient._notify_write

    async def observe(self, resolved, tool, body, response):
        frames.append(frame_for(tool, body, response))
        return await original(self, resolved, tool, body, response)

    monkeypatch.setattr(InternalClient, '_notify_write', observe)
    stack = create(env, token)['stack']
    changed = env.call(token, 'update_photo_stack', dict(stack_id=stack['id'], paths=P[1:],
                      cover_path=P[3], expected_revision=stack['revision']))['data']
    assert env.call(token, 'undo_photo_stack', changed['undo'])['ok']
    stack = env.call(token, 'get_photo_stack', dict(path=P[0]))['data']
    assert env.call(token, 'unstack_photos', dict(stack_id=stack['id'], expected_revision=stack['revision']))['ok']
    assert len(frames) == 4
    assert all(frame is not None and frame['paths'] is None for frame in frames)


def test_create_annotations_are_not_retry_safe(edition):
    env, token = edition
    tools = {tool['name']: tool for tool in env.rpc(token, 'tools/list').json()['result']['tools']}
    assert tools['create_photo_stack']['annotations']['idempotentHint'] is False
    assert tools['get_photo_stack']['annotations']['readOnlyHint'] is True
    assert 'immich' not in ' '.join(tools).lower()
    # The stack tools state the absence ("no Immich call is made"); nothing else may mention a remote.
    described = ' '.join(tool.get('description', '') for tool in tools.values()).lower()
    assert 'immich' not in described.replace('no immich call is made', '')


def test_search_retains_display_and_original_totals(edition):
    env, token = edition
    create(env, token)
    result = env.call(token, 'search_photos', dict(filters={'path_prefix': AGENT_DIR}, show=False))
    assert result['ok'], result
    assert result['data']['total'] == 2
    assert result['data']['photo_total'] == 4


def test_ui_context_describes_stack_activity_and_both_totals():
    from api.agent.ui_tools import UI_TOOLS
    description = next(tool.description for tool in UI_TOOLS if tool.name == 'ui_get_context')
    assert 'photo_total' in description and 'stack' in description
    assert 'create/update/unstack/undo' in description


def test_large_mutation_preserves_success_and_undo_below_response_cap(agent_app, seed_photos_prefix):
    paths = [AGENT_DIR + f'large-stack/{i}/' + 'x' * 300 + '.jpg' for i in range(20)]
    seed_photos_prefix(AGENT_DIR, [dict(path=path, filename='photo.jpg') for path in paths])
    env = agent_app('legacy', max_bytes=4096)
    token = env.token(env.login(edition=True), 'edition')
    result = env.call(token, 'create_photo_stack', dict(paths=paths, cover_path=paths[0]))
    assert result['ok'], result
    assert result['data']['stack_truncated'] is True
    assert result['data']['stack']['member_count'] == 20
    assert 'members' not in result['data']['stack']
    with get_db() as conn:
        assert conn.execute('SELECT count(*) FROM photo_stack_members WHERE stack_id=?',
                            [result['data']['stack']['id']]).fetchone()[0] == 20
    assert env.call(token, 'undo_photo_stack', result['data']['undo'])['ok']
