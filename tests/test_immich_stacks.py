"""Stack exchange against a real isolated HTTP server; never a live Immich."""
import copy
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple

import pytest

from db.schema import init_database
from db import stacks
from sync.immich_stacks import plan_stacks, apply_stacks, write_plan, read_plan


class Exchange(NamedTuple):
    db: Path
    conn: sqlite3.Connection
    paths: list
    asset_ids: list
    remote: dict
    cfg: dict


@pytest.fixture
def exchange(tmp_path):
    owner = str(uuid.uuid4())
    paths = [str(tmp_path / 'photos' / (c + '.jpg')) for c in 'abc']
    for path in paths:
        Path(path).parent.mkdir(exist_ok=True)
        Path(path).write_bytes(b'original photo fixture')
    asset_ids = [str(uuid.uuid4()) for _ in paths]
    assets = {aid: {'id': aid, 'originalPath': '/remote/' + c + '.jpg', 'ownerId': owner,
                    'type': 'IMAGE', 'isTrashed': False, 'isOffline': False, 'visibility': 'timeline'}
              for aid, c in zip(asset_ids, 'abc')}
    state = {'assets': assets, 'stacks': {}, 'creates': 0, 'drop_create': False,
             'omit_stack': False, 'deny': False, 'owner': owner, 'drop_before_create': False}

    def detail(aid):
        item = copy.deepcopy(assets[aid])
        group = next((s for s in state['stacks'].values() if aid in s['assetIds']), None)
        if not state['omit_stack']:
            item['stack'] = ({'id': group['id'], 'primaryAssetId': group['assetIds'][0],
                              'assetCount': len(group['assetIds'])} if group else None)
        return item

    def group(s):
        return {'id': s['id'], 'primaryAssetId': s['assetIds'][0],
                'assets': [detail(aid) for aid in s['assetIds']]}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, body, status=200):
            raw = json.dumps(body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if state['deny']:
                return self.respond({'message': 'private remote failure'}, 403)
            if self.path == '/api/server/version':
                return self.respond({'major': 3, 'minor': 3, 'patch': 0})
            if self.path == '/api/users/me':
                return self.respond({'id': state['owner']})
            if self.path == '/api/stacks':
                return self.respond([group(s) for s in state['stacks'].values()])
            if self.path.startswith('/api/stacks/'):
                sid = self.path.rsplit('/', 1)[-1]
                return self.respond(group(state['stacks'][sid])) if sid in state['stacks'] else self.respond({}, 404)
            if self.path.startswith('/api/assets/'):
                aid = self.path.rsplit('/', 1)[-1]
                return self.respond(detail(aid)) if aid in assets else self.respond({}, 404)
            return self.respond({}, 404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path == '/api/search/metadata':
                hits = [copy.deepcopy(a) for a in assets.values()
                        if not payload.get('originalPath') or a['originalPath'] == payload['originalPath']]
                # Search intentionally omits membership, as actual Immich does.
                return self.respond({'assets': {'items': hits, 'nextPage': None}})
            if self.path == '/api/stacks':
                state['creates'] += 1
                if state.get('create_entered') is not None:
                    state['create_entered'].set()
                    if not state['release_create'].wait(10):
                        return self.respond({}, 503)
                if state['drop_before_create']:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                sid = str(uuid.uuid4())
                state['stacks'][sid] = {'id': sid, 'assetIds': payload['assetIds']}
                if state['drop_create']:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                return self.respond(group(state['stacks'][sid]), 201)
            return self.respond({}, 404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    db = tmp_path / 'library.db'
    init_database(str(db))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executemany('INSERT INTO photos(path,filename,is_kept) VALUES (?,?,1)',
                         [(p, p.rsplit('/', 1)[-1]) for p in paths])
    config = {'immich': {'url': f'http://127.0.0.1:{server.server_port}', 'api_key': 'fixture-only',
                         'path_map': [{'facet_prefix': str(tmp_path / 'photos') + os.sep, 'immich_prefix': '/remote/'}]},
              'users': {}}
    yield Exchange(db, conn, paths, asset_ids, state, config)
    conn.close()
    server.shutdown()
    thread.join()
    server.server_close()


def local_group(data):
    with data.conn:
        data.conn.execute('BEGIN IMMEDIATE')
        return stacks.create_stack(data.conn, '', data.paths, data.paths[1])['stack']


def apply(data, plan):
    return apply_stacks(str(data.db), data.cfg, plan, ack_plan=plan['plan_id'])


def test_push_create_once_and_repeated_apply_is_idempotent(exchange):
    stack = local_group(exchange)
    before = [Path(p).read_bytes() for p in exchange.paths]
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert plan['items'][0]['status'] == 'ready'
    assert exchange.remote['creates'] == 0
    result = apply(exchange, plan)
    assert result['items'][0]['status'] == 'created'
    assert exchange.remote['creates'] == 1
    assert next(iter(exchange.remote['stacks'].values()))['assetIds'][0] == exchange.asset_ids[1]
    assert apply(exchange, plan)['items'][0]['status'] == 'identical'
    assert exchange.remote['creates'] == 1
    assert [Path(p).read_bytes() for p in exchange.paths] == before
    assert [r[0] for r in exchange.conn.execute('SELECT is_kept FROM photos')] == [1, 1, 1]
    assert exchange.conn.execute('SELECT id FROM photo_stacks').fetchone()[0] == stack['id']


def test_lost_create_response_is_reconciled_without_repeating_post(exchange):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    exchange.remote['drop_create'] = True
    result = apply(exchange, plan)
    assert result['items'][0]['status'] == 'created'
    assert exchange.remote['creates'] == 1
    retry = apply(exchange, plan)
    assert retry['items'][0]['status'] == 'identical'
    assert exchange.remote['creates'] == 1


def test_child_overlap_and_cover_disagreement_refuse_before_write(exchange):
    local_group(exchange)
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': [exchange.asset_ids[0], exchange.asset_ids[2]]}
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert plan['items'][0]['status'] == 'conflict'
    assert apply(exchange, plan)['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 0


def test_absent_detail_stack_field_is_unknown_not_unstacked(exchange):
    local_group(exchange)
    exchange.remote['omit_stack'] = True
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert plan['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 0


def test_import_full_group_then_repeat_adopts_identical(exchange):
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': [exchange.asset_ids[2], exchange.asset_ids[0], exchange.asset_ids[1]]}
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert exchange.conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0
    assert apply(exchange, plan)['items'][0]['status'] == 'imported'
    stack = exchange.conn.execute('SELECT cover_path FROM photo_stacks').fetchone()
    assert stack[0] == exchange.paths[2]
    repeat = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert repeat['items'][0]['status'] == 'identical'
    assert apply(exchange, repeat)['items'][0]['status'] == 'identical'
    assert exchange.conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 1
    assert exchange.remote['creates'] == 0


def test_stale_local_and_changed_remote_preconditions_refuse(exchange):
    stack = local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        stacks.update_stack(exchange.conn, '', stack['id'], exchange.paths, exchange.paths[0], stack['revision'])
    assert apply(exchange, plan)['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 0
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': [exchange.asset_ids[2], exchange.asset_ids[1]]}
    assert apply(exchange, plan)['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 0


def test_changed_account_mapping_or_plan_digest_is_rejected(exchange):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    bad = copy.deepcopy(plan)
    bad['items'][0]['status'] = 'invented'
    with pytest.raises(ValueError):
        apply(exchange, bad)
    exchange.remote['owner'] = str(uuid.uuid4())
    with pytest.raises(ValueError):
        apply(exchange, plan)
    assert exchange.remote['creates'] == 0


def test_cancellation_stops_before_remote_write(exchange):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    result = apply_stacks(str(exchange.db), exchange.cfg, plan, ack_plan=plan['plan_id'], cancelled=lambda: True)
    assert result['cancelled'] is True and exchange.remote['creates'] == 0


def test_private_plan_file_and_digest_round_trip(exchange, tmp_path):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    path = tmp_path / 'plan.json'
    write_plan(path, plan, db_path=str(exchange.db))
    if os.name != 'nt':
        assert path.stat().st_mode & 0o077 == 0
    assert read_plan(path) == plan
    assert exchange.cfg['immich']['api_key'] not in path.read_text(encoding='utf-8')
    original = path.read_bytes()
    with pytest.raises(ValueError, match='new private plan filename'):
        write_plan(path, plan, db_path=str(exchange.db))
    assert path.read_bytes() == original
    with pytest.raises(ValueError):
        write_plan(exchange.db, plan, db_path=str(exchange.db))


def test_preview_refuses_missing_and_schema_empty_database_without_creation(tmp_path):
    missing = tmp_path / 'missing.db'
    with pytest.raises((ValueError, sqlite3.Error)):
        plan_stacks(str(missing), {}, 'push')
    assert not missing.exists()
    empty = tmp_path / 'empty.db'
    empty.write_bytes(b'')
    with pytest.raises((ValueError, sqlite3.Error)):
        plan_stacks(str(empty), {}, 'push')
    assert empty.read_bytes() == b''


def test_uncertain_send_without_observable_result_is_not_resubmitted(exchange):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    exchange.remote['drop_before_create'] = True
    assert apply(exchange, plan)['items'][0]['status'] == 'uncertain'
    assert exchange.remote['creates'] == 1
    assert apply(exchange, plan)['items'][0]['status'] == 'uncertain'
    assert exchange.remote['creates'] == 1


def test_remote_unstack_is_conflict_not_automatic_recreation(exchange):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert apply(exchange, plan)['items'][0]['status'] == 'created'
    exchange.remote['stacks'].clear()
    new_plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert new_plan['items'][0]['status'] == 'conflict'
    assert apply(exchange, new_plan)['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 1


def test_local_unstack_is_not_reimported_automatically(exchange):
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': exchange.asset_ids}
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert apply(exchange, plan)['items'][0]['status'] == 'imported'
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        row = exchange.conn.execute('SELECT id,revision FROM photo_stacks').fetchone()
        stacks.delete_stack(exchange.conn, '', row['id'], row['revision'])
    new_plan = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert new_plan['items'][0]['status'] == 'conflict'
    assert apply(exchange, new_plan)['items'][0]['status'] == 'conflict'
    assert exchange.conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0


def test_import_with_missing_local_member_is_refused_without_partial_stack(exchange):
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': exchange.asset_ids}
    with exchange.conn:
        exchange.conn.execute('DELETE FROM photos WHERE path=?', (exchange.paths[2],))
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert plan['items'][0]['status'] == 'conflict'
    assert apply(exchange, plan)['items'][0]['status'] == 'conflict'
    assert exchange.conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 0


def test_wrong_remote_owner_and_duplicate_identity_are_refused(exchange):
    local_group(exchange)
    exchange.remote['assets'][exchange.asset_ids[0]]['ownerId'] = str(uuid.uuid4())
    assert plan_stacks(str(exchange.db), exchange.cfg, 'push')['items'][0]['status'] == 'conflict'
    exchange.remote['assets'][exchange.asset_ids[0]]['ownerId'] = exchange.remote['owner']
    duplicate = copy.deepcopy(exchange.remote['assets'][exchange.asset_ids[0]])
    duplicate['id'] = str(uuid.uuid4())
    exchange.remote['assets'][duplicate['id']] = duplicate
    assert plan_stacks(str(exchange.db), exchange.cfg, 'push')['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 0


def test_preview_preserves_database_and_contains_no_credential(exchange):
    local_group(exchange)
    exchange.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    before = exchange.db.read_bytes()
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert exchange.db.read_bytes() == before
    assert exchange.cfg['immich']['api_key'] not in json.dumps(plan)
    assert exchange.remote['creates'] == 0


def test_multiuser_requires_explicit_owner_and_excludes_invisible_members(exchange):
    exchange.cfg['users'] = {'alice': {'directories': [str(Path(exchange.paths[0]).parent)]}}
    with pytest.raises(ValueError, match='explicit'):
        plan_stacks(str(exchange.db), exchange.cfg, 'push')
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        stacks.create_stack(exchange.conn, 'alice', exchange.paths, exchange.paths[0])
    exchange.cfg['users']['alice']['directories'] = ['/different/']
    assert plan_stacks(str(exchange.db), exchange.cfg, 'push', user_id='alice')['items'][0]['status'] == 'conflict'
    assert exchange.remote['creates'] == 0


def test_cli_preview_and_apply_use_explicit_digest_and_private_file(exchange, tmp_path):
    local_group(exchange)
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(exchange.cfg), encoding='utf-8')
    output = tmp_path / 'stacks-plan.json'
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items()
           if not any(secret in k.upper() for secret in ('TOKEN', 'PASSWORD', 'SECRET', 'API_KEY'))}
    env.pop('FACET_CONFIG', None)
    args = [sys.executable, str(root / 'facet.py'), '--config', str(config_path), '--db', str(exchange.db)]
    preview = subprocess.run([*args, '--immich-stacks-plan', 'push', '--stack-plan-out', str(output)],
                             cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert preview.returncode == 0, preview.stderr
    assert output.exists() and exchange.remote['creates'] == 0
    plan = read_plan(output)
    refused = subprocess.run([*args, '--immich-stacks-apply', str(output)],
                             cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert refused.returncode != 0 and exchange.remote['creates'] == 0
    applied = subprocess.run([*args, '--immich-stacks-apply', str(output), '--ack-stack-plan', plan['plan_id']],
                             cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)['items'][0]['status'] == 'created'
    assert exchange.remote['creates'] == 1


def test_uncertain_assets_cannot_be_reposted_through_a_new_local_stack(exchange):
    stack = local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    exchange.remote['drop_before_create'] = True
    assert apply(exchange, plan)['items'][0]['status'] == 'uncertain'
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        stacks.delete_stack(exchange.conn, '', stack['id'], stack['revision'])
        stacks.create_stack(exchange.conn, '', exchange.paths, exchange.paths[1])
    replacement = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert apply(exchange, replacement)['items'][0]['status'] == 'uncertain'
    assert exchange.remote['creates'] == 1


def test_windows_visibility_prefix_uses_one_native_separator():
    from sync.immich_stacks import _owner_scope
    root = 'C:' + chr(92) + 'Photos'
    _, _, params = _owner_scope({'users': {'alice': {'directories': [root]}}}, 'alice')
    assert params == [root + chr(92), root + chr(92)]


def test_uncertain_send_admission_survives_mapping_changes(exchange):
    local_group(exchange)
    exchange.remote['drop_before_create'] = True
    first = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert apply(exchange, first)['items'][0]['status'] == 'uncertain'
    exchange.cfg['immich']['path_map'].append({'facet_prefix': '/unused/', 'immich_prefix': '/unused-exchange.remote/'})
    second = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    assert first['scope'] != second['scope']
    assert apply(exchange, second)['items'][0]['status'] == 'uncertain'
    assert exchange.remote['creates'] == 1


def test_identical_import_preserves_different_local_order(exchange, tmp_path):
    local = local_group(exchange)  # local a,b,c; cover b
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': [exchange.asset_ids[1], exchange.asset_ids[0], exchange.asset_ids[2]]}
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert plan['items'][0]['status'] == 'identical'
    saved = tmp_path / 'adopt.json'
    write_plan(saved, plan, db_path=str(exchange.db))
    assert apply(exchange, read_plan(saved))['items'][0]['status'] == 'identical'
    assert stacks.get_stack(exchange.conn, '', local['id'])['members'] == local['members']
    assert exchange.remote['creates'] == 0


def test_stale_identical_import_cannot_recreate_manual_unstack(exchange):
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        local = stacks.create_stack(exchange.conn, '', exchange.paths, exchange.paths[0])['stack']
    sid = str(uuid.uuid4())
    exchange.remote['stacks'][sid] = {'id': sid, 'assetIds': exchange.asset_ids}
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'import')
    assert plan['items'][0]['status'] == 'identical'
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        stacks.delete_stack(exchange.conn, '', local['id'], local['revision'])
    assert apply(exchange, plan)['items'][0]['status'] == 'conflict'
    assert exchange.conn.execute('SELECT COUNT(*) FROM photo_stacks').fetchone()[0] == 0


def test_local_delete_after_postvalidation_is_not_marked_completed(exchange, monkeypatch):
    from sync import immich_stacks as bridge
    local = local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    original = bridge._evaluate
    deleted = False
    def evaluate(*args, **kwargs):
        nonlocal deleted
        observed = original(*args, **kwargs)
        if exchange.remote['creates'] and observed['status'] == 'identical' and not deleted:
            with exchange.conn:
                exchange.conn.execute('BEGIN IMMEDIATE')
                stacks.delete_stack(exchange.conn, '', local['id'], local['revision'])
            deleted = True
        return observed
    monkeypatch.setattr(bridge, '_evaluate', evaluate)
    result = apply(exchange, plan)
    assert deleted and result['items'][0]['status'] == 'uncertain'
    assert exchange.conn.execute("SELECT COUNT(*) FROM immich_stack_receipts WHERE status='completed'").fetchone()[0] == 0
    assert exchange.conn.execute('SELECT COUNT(*) FROM immich_stack_links').fetchone()[0] == 0
    assert exchange.remote['creates'] == 1


def test_concurrent_local_scopes_share_remote_asset_send_admission(exchange):
    from concurrent.futures import ThreadPoolExecutor
    exchange.cfg['users'] = {name: {'directories': [str(Path(exchange.paths[0]).parent)]} for name in ('alice', 'bob')}
    with exchange.conn:
        exchange.conn.execute('BEGIN IMMEDIATE')
        for owner in exchange.cfg['users']:
            stacks.create_stack(exchange.conn, owner, exchange.paths, exchange.paths[1])
    first = plan_stacks(str(exchange.db), exchange.cfg, 'push', user_id='alice')
    second = plan_stacks(str(exchange.db), exchange.cfg, 'push', user_id='bob')
    assert first['scope'] != second['scope']
    exchange.remote['create_entered'], exchange.remote['release_create'] = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(apply_stacks, str(exchange.db), exchange.cfg, first, ack_plan=first['plan_id'], user_id='alice')
        try:
            assert exchange.remote['create_entered'].wait(5), 'first send never started'
            other = apply_stacks(str(exchange.db), exchange.cfg, second, ack_plan=second['plan_id'], user_id='bob')
            assert other['items'][0]['status'] == 'uncertain'
            assert exchange.remote['creates'] == 1
        finally:
            exchange.remote['release_create'].set()
        assert pending.result(timeout=5)['items'][0]['status'] == 'created'
    assert exchange.remote['creates'] == 1


def test_completed_send_between_preflight_and_admission_cannot_send_again(exchange, monkeypatch):
    from sync import immich_stacks as bridge
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    evaluate = bridge._evaluate
    nested = []
    def interleave(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        if result['status'] == 'ready' and not nested:
            nested.append(None)  # Prevent recursive injection.
            nested[0] = apply(exchange, plan)
        return result
    monkeypatch.setattr(bridge, '_evaluate', interleave)
    outer = apply(exchange, plan)
    assert nested[0]['items'][0]['status'] == 'created'
    assert outer['items'][0]['status'] == 'uncertain'
    assert exchange.remote['creates'] == 1
    assert exchange.conn.execute("SELECT status FROM immich_stack_receipts").fetchall()[0][0] == 'completed'


def test_excessively_nested_plan_refuses_cleanly_before_any_database_write(tmp_path, capsys):
    from types import SimpleNamespace
    from sync.immich_stacks import run_cli

    plan = tmp_path / 'nested.json'
    depth = 100000
    plan.write_text('[' * depth + '0' + ']' * depth, encoding='utf-8')
    db = tmp_path / 'untouched.db'
    db.write_bytes(b'not opened before a plan has been verified')
    before = db.read_bytes()
    with pytest.raises(ValueError, match='Invalid stack plan'):
        read_plan(plan)
    args = SimpleNamespace(immich_stacks_plan=None, immich_stacks_apply=str(plan),
                           ack_stack_plan='untrusted', db=str(db), user=None)
    assert run_cli(args, {}) == 1
    assert 'Stack exchange failed.' in capsys.readouterr().err
    assert db.read_bytes() == before


def test_plan_publication_failure_removes_temporary_file(exchange, tmp_path, monkeypatch):
    local_group(exchange)
    plan = plan_stacks(str(exchange.db), exchange.cfg, 'push')
    target = tmp_path / 'unpublished-plan.json'

    def refuse_link(*args):
        raise OSError('fixture: volume cannot publish a hard link')

    monkeypatch.setattr('sync.immich_stacks.os.link', refuse_link)
    with pytest.raises(OSError):
        write_plan(target, plan, db_path=str(exchange.db))
    assert not target.exists()
    assert list(tmp_path.glob('.facet-stacks-*')) == []
