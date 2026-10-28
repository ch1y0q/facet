"""Explicit, conservative stack exchange. No automatic reconciliation.

Preview is database read-only; apply creates new groups or adopts exact matches.
Immich has no conditional stack writes: fresh pre/postvalidation cannot eliminate
cross-client races. Uncertain sends are never automatically submitted twice.
"""
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import quote, urlsplit
import uuid

from db import stacks
from db.immich_stacks import init_schema
from db.maintenance import evict_derived_stats_cache
from sync.immich import ImmichClient, PUSH_ERRORS, map_facet_path, map_immich_path

logger = logging.getLogger(__name__)
MAX_GROUPS = 1000
MAX_PLAN_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = stacks.MAX_MEMBERS
MAX_TOTAL_MEMBERS = 20000


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except RecursionError:
        raise ValueError('Invalid stack plan nesting') from None


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError('Invalid remote identity')
    try:
        parsed = str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError('Invalid remote identity') from exc
    if parsed != value.lower():
        raise ValueError('Invalid remote identity')
    return parsed


@contextmanager
def _connection(db_path, *, write=False):
    try:
        path = Path(db_path).resolve(strict=True)
    except OSError as exc:
        raise ValueError('An existing readable Facet database is required') from exc
    if not path.is_file():
        raise ValueError('An existing readable Facet database is required')
    conn = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'photos', 'photo_stacks', 'photo_stack_members'} <= tables:
            raise ValueError('Stack schema unavailable; preview never creates or upgrades a database')
        conn.execute('SELECT path FROM photos LIMIT 1').fetchone()
        yield conn
    finally:
        conn.close()


def _owner_scope(config, user_id):
    users = config.get('users', {})
    if not isinstance(users, dict):
        raise ValueError('Invalid user configuration')
    multi = any(k != 'shared_directories' for k in users)
    if not multi:
        return '', '1=1', []
    user = users.get(user_id) if user_id else None
    if not isinstance(user, dict):
        raise ValueError('Multi-user stack exchange requires an explicit existing --user')
    own_roots, shared_roots = user.get('directories', []), users.get('shared_directories', [])
    if not isinstance(own_roots, list) or not isinstance(shared_roots, list):
        raise ValueError('Invalid visibility configuration')
    roots = own_roots + shared_roots
    clauses, params = [], []
    for root in roots:
        if not isinstance(root, str) or not root.strip():
            raise ValueError('Visibility directories must be nonblank paths')
        # Exact native prefixes preserve literal %, _ and backslashes; a sibling
        # directory never grants access. This deliberately never guesses moves.
        separator = '\\' if '\\' in root and '/' not in root else '/'
        prefix = root.rstrip('/\\') + separator
        clauses.append('substr(photos.path,1,length(?))=?')
        params.extend([prefix, prefix])
    return user_id, '(' + ' OR '.join(clauses) + ')' if clauses else '0=1', params


def _client(config):
    cfg = config.get('immich', {})
    url = cfg.get('url', '')
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Immich URL must not contain credentials, query or fragment')
    if not cfg.get('api_key'):
        raise ValueError('Immich API key is not configured')
    client = ImmichClient(url, cfg['api_key'], timeout=cfg.get('timeout_seconds', 30),
                          owner_id=cfg.get('owner_id', ''), library_id=cfg.get('library_id', ''))
    client.response_byte_limit = MAX_PLAN_BYTES
    return client


def _identity(client, config, db_path, owner, visibility):
    version = client._request('GET', '/api/server/version')
    if (not isinstance(version, dict) or isinstance(version.get('major'), bool)
            or not isinstance(version.get('major'), int) or version['major'] < 3):
        raise ValueError('Stack exchange requires Immich 3.0 or newer')
    account = client._request('GET', '/api/users/me')
    account_id = _uuid(account.get('id') if isinstance(account, dict) else None)
    if client.owner_id and client.owner_id != account_id:
        raise ValueError('Configured asset owner differs from the authenticated Immich account')
    binding = dict(server=client.base_url, account=account_id, owner=owner,
                   database=str(Path(db_path).resolve()), visibility=visibility,
                   mapping=config.get('immich', {}).get('path_map', []), library=client.library_id)
    # Admission is deliberately broader than plan/link scope. Account and asset
    # UUIDs remain stable when local owners, URL aliases, mapping or visibility
    # change. Cloned remote identities conservatively share uncertainty too.
    return _digest(binding), account_id, _digest({'account': account_id})


def _resolve_asset(client, path):
    ids = set()
    for index, item in enumerate(client._iter_assets(path)):
        if index >= MAX_TOTAL_MEMBERS:
            raise ValueError('Remote identity search exceeds its safe candidate limit')
        if item['originalPath'] == path:
            ids.add(item['id'])
    if len(ids) > 1:
        raise ValueError('Remote image identity is ambiguous')
    aid = next(iter(ids), None)
    if aid is not None:
        client.assert_asset_identity(aid, path)
    return aid


def _check_asset(client, aid, account):
    aid = _uuid(aid)
    asset = client._request('GET', '/api/assets/' + quote(aid, safe=''))
    if (not isinstance(asset, dict) or asset.get('id') != aid
            or asset.get('ownerId') != account or not client._in_scope(asset)
            or asset.get('type') != 'IMAGE' or asset.get('visibility') != 'timeline'
            or asset.get('isTrashed') is not False or asset.get('isOffline') is not False
            or not isinstance(asset.get('originalPath'), str) or not 1 <= len(asset['originalPath']) <= 4096
            or '\x00' in asset['originalPath']
            or 'stack' not in asset):
        raise ValueError('Asset ownership, availability or stack membership could not be verified')
    if _resolve_asset(client, asset['originalPath']) != aid:
        raise ValueError('Remote image identity is ambiguous')
    group = asset['stack']
    if group is not None:
        if not isinstance(group, dict):
            raise ValueError('Unknown remote stack membership')
        _uuid(group.get('id'))
        _uuid(group.get('primaryAssetId'))
        count = group.get('assetCount')
        if isinstance(count, bool) or not isinstance(count, int) or count < 2 or count > MAX_MEMBERS:
            raise ValueError('Incomplete or oversized remote stack')
    return {key: asset[key] for key in ('id', 'originalPath', 'ownerId', 'stack')}


def _remote_group(client, sid, account):
    sid = _uuid(sid)
    data = client._request('GET', '/api/stacks/' + quote(sid, safe=''))
    if not isinstance(data, dict) or data.get('id') != sid or not isinstance(data.get('assets'), list):
        raise ValueError('Unknown remote stack')
    ids = [_uuid(a.get('id') if isinstance(a, dict) else None) for a in data['assets']]
    primary = _uuid(data.get('primaryAssetId'))
    if not 2 <= len(ids) <= MAX_MEMBERS or len(set(ids)) != len(ids) or primary not in ids:
        raise ValueError('Incomplete or oversized remote stack')
    assets = [_check_asset(client, aid, account) for aid in ids]
    for asset in assets:
        state = asset['stack']
        if (state is None or state['id'] != sid or state['primaryAssetId'] != primary
                or state['assetCount'] != len(ids)):
            raise ValueError('Remote stack changed or contains unavailable members')
    return dict(id=sid, cover=primary, ids=sorted(ids), assets=assets)


def _mapped_path(path, mapping, *, inbound=False):
    pairs = [p for p in mapping if p.get('facet_prefix') and p.get('immich_prefix')]
    if not pairs:
        return path
    source = 'immich_prefix' if inbound else 'facet_prefix'
    target = 'facet_prefix' if inbound else 'immich_prefix'
    choices = {p[target] + path[len(p[source]):] for p in pairs if path.startswith(p[source])}
    if len(choices) != 1:
        raise ValueError('Missing or ambiguous path mapping')
    result = next(iter(choices))
    # Keep the existing integration's mapping contract, but refuse ambiguity.
    forward = map_immich_path if inbound else map_facet_path
    reverse = map_facet_path if inbound else map_immich_path
    if forward(path, mapping) != result or reverse(result, mapping) != path:
        raise ValueError('Path mapping does not round-trip uniquely')
    return result


def _local(conn, owner, sid, visibility):
    group = stacks.get_stack(conn, owner, sid, visibility_sql=visibility[0], visibility_params=visibility[1])
    if group is None or not group['editable']:
        raise ValueError('Local stack changed or is unavailable')
    return dict(id=group['id'], revision=group['revision'], cover=group['cover_path'],
                paths=[m['path'] for m in group['members']])


def _remote_for_local(conn, client, group, owner, account, config, visibility):
    del conn, owner, visibility  # Group was read and authorized through _local.
    mapping = config.get('immich', {}).get('path_map', [])
    assets = []
    for path in group['paths']:
        remote_path = _mapped_path(path, mapping)
        aid = _resolve_asset(client, remote_path)
        if aid is None:
            raise ValueError('A stack member is not indexed in Immich')
        asset = _check_asset(client, aid, account)
        if asset['originalPath'] != remote_path:
            raise ValueError('Mapped identity changed')
        assets.append(asset)
    ids = [a['id'] for a in assets]
    if len(set(ids)) != len(ids):
        raise ValueError('Multiple local photos map to one remote asset')
    cover = ids[group['paths'].index(group['cover'])]
    memberships = {a['stack']['id'] for a in assets if a['stack'] is not None}
    if not memberships:
        return dict(id=None, cover=cover, ids=sorted(ids))
    if len(memberships) != 1 or any(a['stack'] is None for a in assets):
        raise ValueError('Remote photos already belong to a different stack')
    remote = _remote_group(client, next(iter(memberships)), account)
    if remote['ids'] != sorted(ids) or remote['cover'] != cover:
        raise ValueError('Remote stack membership or cover conflicts')
    return {k: remote[k] for k in ('id', 'cover', 'ids')}


def _import_item(conn, client, sid, owner, account, config, visibility, scope):
    remote = _remote_group(client, sid, account)
    mapping = config.get('immich', {}).get('path_map', [])
    paths = [_mapped_path(a['originalPath'], mapping, inbound=True) for a in remote['assets']]
    if len(set(paths)) != len(paths) or len(stacks.visible_paths(conn, paths, *visibility)) != len(paths):
        raise ValueError('An import member is unmapped, missing or invisible locally')
    cover = paths[[a['id'] for a in remote['assets']].index(remote['cover'])]
    current = set()
    for start in range(0, len(paths), 300):
        chunk = paths[start:start + 300]
        marks = ','.join('?' for _ in chunk)
        current.update(r[0] for r in conn.execute(
            f'SELECT DISTINCT stack_id FROM photo_stack_members WHERE owner=? AND photo_path IN ({marks})',
            [owner, *chunk]))
        if len(current) > 1:
            raise ValueError('Import overlaps existing local stacks')
    local = None
    if current:
        if len(current) != 1:
            raise ValueError('Import overlaps existing local stacks')
        local = _local(conn, owner, next(iter(current)), visibility)
        if set(local['paths']) != set(paths) or local['cover'] != cover:
            raise ValueError('Import conflicts with local stack membership or cover')
    linked = _existing_link(conn, scope, remote_id=sid)
    if linked is not None and (local is None or linked['local_stack_id'] != local['id']):
        raise ValueError('A previously linked local stack was removed or changed')
    return dict(key=sid, local=local, remote={k: remote[k] for k in ('id', 'cover', 'ids')},
                paths=paths, cover=cover, status='identical' if local else 'ready')


def _push_item(conn, client, sid, owner, account, config, visibility, scope):
    local = _local(conn, owner, sid, visibility)
    remote = _remote_for_local(conn, client, local, owner, account, config, visibility)
    linked = _existing_link(conn, scope, local_id=sid)
    if linked is not None and linked['remote_stack_id'] != remote['id']:
        raise ValueError('A previously linked remote stack was removed or changed')
    return dict(key=sid, local=local, remote=remote, paths=local['paths'], cover=local['cover'],
                status='identical' if remote['id'] else 'ready')


def _existing_link(conn, scope, *, local_id=None, remote_id=None):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='immich_stack_links' AND type='table'").fetchone() is None:
        return None
    column, value = ('local_stack_id', local_id) if local_id is not None else ('remote_stack_id', remote_id)
    return conn.execute(f'SELECT * FROM immich_stack_links WHERE scope=? AND {column}=?', (scope, value)).fetchone()


def _evaluate(conn, client, direction, key, owner, account, config, visibility, scope):
    try:
        return (_push_item if direction == 'push' else _import_item)(
            conn, client, key, owner, account, config, visibility, scope)
    except PUSH_ERRORS:
        logger.exception('Stack exchange preflight refused a group')
        return dict(key=key, status='conflict', reason='Stack membership or identity could not be verified')


def plan_stacks(db_path, config, direction, *, user_id=None, stack_ids=None, client=None):
    if direction not in ('push', 'import'):
        raise ValueError('Choose import or push')
    owner, vis, values = _owner_scope(config, user_id)
    visibility = (vis, values)
    with _connection(db_path) as conn:
        client = client or _client(config)
        scope, account, admission_scope = _identity(client, config, db_path, owner, visibility)
        if stack_ids is not None:
            keys = list(dict.fromkeys(_uuid(sid) for sid in stack_ids))
        elif direction == 'push':
            keys = [r[0] for r in conn.execute('SELECT id FROM photo_stacks WHERE owner=? ORDER BY id LIMIT ?',
                                               (owner, MAX_GROUPS + 1))]
        else:
            groups = client._request('GET', '/api/stacks')
            if not isinstance(groups, list):
                raise ValueError('Immich stack list is unavailable')
            keys = [_uuid(g.get('id') if isinstance(g, dict) else None) for g in groups]
        if len(keys) > MAX_GROUPS or len(set(keys)) != len(keys):
            raise ValueError('Too many or duplicate stacks; select at most 1000 explicit stack IDs')
        if stack_ids is None and conn.execute("SELECT 1 FROM sqlite_master WHERE name='immich_stack_links'").fetchone():
            column = 'local_stack_id' if direction == 'push' else 'remote_stack_id'
            linked = [r[0] for r in conn.execute(f'SELECT {column} FROM immich_stack_links WHERE scope=? LIMIT ?',
                                                (scope, MAX_GROUPS + 1))]
            keys = list(dict.fromkeys([*keys, *linked]))
        if len(keys) > MAX_GROUPS:
            raise ValueError('Too many stacks; select at most 1000 explicit stack IDs')
        items, byte_count, member_count = [], 0, 0
        for key in keys:
            item = _evaluate(conn, client, direction, key, owner, account, config, visibility, scope)
            byte_count += len(_json(item).encode('utf-8'))
            member_count += len(item.get('paths', []))
            if byte_count > MAX_PLAN_BYTES or member_count > MAX_TOTAL_MEMBERS:
                raise ValueError('Stack plan exceeds its size limit; narrow the selection')
            items.append(item)
    plan = dict(version=1, direction=direction, scope=scope, owner=owner, items=items)
    if len(_json(plan).encode('utf-8')) > MAX_PLAN_BYTES:
        raise ValueError('Stack plan exceeds its size limit; narrow the selection')
    plan['plan_id'] = _digest(plan)
    return plan


def _verify_plan(plan, ack_plan):
    if not isinstance(plan, dict) or type(plan.get('version')) is not int or plan.get('version') != 1 or plan.get('direction') not in ('push', 'import'):
        raise ValueError('Invalid stack plan')
    if len(_json(plan).encode('utf-8')) > MAX_PLAN_BYTES:
        raise ValueError('Stack plan exceeds its size limit')
    expected = _digest({k: v for k, v in plan.items() if k != 'plan_id'})
    if expected != plan.get('plan_id') or expected != ack_plan:
        raise ValueError('Stack plan digest does not match the explicit acknowledgement')
    if not isinstance(plan.get('items'), list) or len(plan['items']) > MAX_GROUPS:
        raise ValueError('Invalid stack plan items')
    seen, members = set(), 0
    for item in plan['items']:
        if not isinstance(item, dict) or item.get('status') not in ('ready', 'identical', 'conflict'):
            raise ValueError('Invalid stack plan item')
        key = _uuid(item.get('key'))
        if key in seen:
            raise ValueError('Duplicate stack plan item')
        seen.add(key)
        if item['status'] == 'conflict':
            continue
        paths, cover, remote, local = item.get('paths'), item.get('cover'), item.get('remote'), item.get('local')
        if (not isinstance(paths, list) or not 2 <= len(paths) <= MAX_MEMBERS
                or any(not isinstance(p, str) or not p or len(p)>4096 or '\x00' in p for p in paths)
                or len(set(paths)) != len(paths) or cover not in paths or not isinstance(remote, dict)):
            raise ValueError('Invalid stack plan membership')
        ids = remote.get('ids')
        if not isinstance(ids, list) or len(ids) != len(paths) or len({_uuid(a) for a in ids}) != len(ids):
            raise ValueError('Invalid stack plan identities')
        if _uuid(remote.get('cover')) not in ids:
            raise ValueError('Invalid remote cover')
        if remote.get('id') is not None:
            _uuid(remote['id'])
        if local is not None:
            if (not isinstance(local, dict) or not isinstance(local.get('revision'), int)
                    or isinstance(local['revision'], bool) or local['revision'] < 1
                    or not isinstance(local.get('paths'), list)
                    or any(not isinstance(p, str) for p in local['paths'])
                    or len(local['paths']) != len(paths) or set(local['paths']) != set(paths)
                    or (plan['direction'] == 'push' and local['paths'] != paths)
                    or local.get('cover') != cover):
                raise ValueError('Invalid local stack snapshot')
            _uuid(local.get('id'))
        elif plan['direction'] == 'push':
            raise ValueError('Push plan needs a local stack snapshot')
        members += len(paths)
        if members > MAX_TOTAL_MEMBERS:
            raise ValueError('Too many planned members')



def _record(conn, scope, admission_scope, operation, status, local_id=None, remote_id=None, asset_ids=None):
    conn.execute("""INSERT INTO immich_stack_receipts(scope,admission_scope,operation_id,status,local_stack_id,remote_stack_id,asset_ids,updated_at)
        VALUES (?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(scope,operation_id) DO UPDATE SET status=excluded.status,
            local_stack_id=excluded.local_stack_id,remote_stack_id=excluded.remote_stack_id,
            asset_ids=CASE WHEN excluded.asset_ids='[]' THEN immich_stack_receipts.asset_ids ELSE excluded.asset_ids END,
            updated_at=excluded.updated_at""",
                 (scope, admission_scope, operation, status, local_id, remote_id, _json(asset_ids or [])))


def _link(conn, scope, local, remote):
    conn.execute("""INSERT INTO immich_stack_links VALUES (?,?,?,?,?)
        ON CONFLICT(scope,local_stack_id) DO UPDATE SET remote_stack_id=excluded.remote_stack_id,
            local_fingerprint=excluded.local_fingerprint,remote_fingerprint=excluded.remote_fingerprint""",
                 (scope, local['id'], remote['id'], _digest(local), _digest(remote)))


def apply_stacks(db_path, config, plan, *, ack_plan, user_id=None, cancelled=lambda: False, client=None):
    _verify_plan(plan, ack_plan)
    owner, vis, values = _owner_scope(config, user_id)
    visibility = (vis, values)
    # Validate identity/schema before the first local/remote write.
    with _connection(db_path) as conn:
        client = client or _client(config)
        scope, account, admission_scope = _identity(client, config, db_path, owner, visibility)
    if plan['scope'] != scope or plan['owner'] != owner:
        raise ValueError('Stack plan account, database or configuration changed')
    result = dict(items=[], cancelled=False)
    for original in plan['items']:
        if cancelled():
            result['cancelled'] = True
            break
        if not isinstance(original, dict) or original.get('status') not in ('ready', 'identical', 'conflict'):
            raise ValueError('Invalid stack plan item')
        if original['status'] == 'conflict':
            result['items'].append(dict(key=original['key'], status='conflict', reason='Preview contained a conflict'))
            continue
        key = _uuid(original['key'])
        operation = _digest(dict(scope=scope, direction=plan['direction'], key=key,
                                 local=original.get('local'), remote_ids=original['remote']['ids'], cover=original['cover']))
        sent = False
        try:
            with _connection(db_path) as conn:
                current = _evaluate(conn, client, plan['direction'], key, owner, account, config, visibility, scope)
            if current['status'] == 'conflict':
                raise ValueError('Stack changed since preview')
            if current['paths'] != original['paths'] or current['cover'] != original['cover']:
                raise ValueError('Stack changed since preview')
            if plan['direction'] == 'push' and current['local'] != original['local']:
                raise ValueError('Local stack changed since preview')
            if plan['direction'] == 'import' and current['remote'] != original['remote']:
                raise ValueError('Remote stack changed since preview')
            if plan['direction'] == 'import':
                if original['local'] is not None and current['local'] != original['local']:
                    raise ValueError('Planned local stack changed since preview')
                if original['local'] is None and current['local'] is not None:
                    # Only a confirmed completion of THIS originally absent
                    # import permits retry adoption; unrelated manual edits need
                    # a fresh preview rather than an implicit new group/link.
                    with _connection(db_path) as conn:
                        done = conn.execute(
                            "SELECT local_stack_id,remote_stack_id FROM immich_stack_receipts "
                            "WHERE scope=? AND operation_id=? AND status='completed'",
                            (scope, operation)).fetchone()
                    if (done is None or done['local_stack_id'] != current['local']['id']
                            or done['remote_stack_id'] != current['remote']['id']):
                        raise ValueError('Local absence precondition changed since preview')
            if current['remote']['ids'] != original['remote']['ids']:
                raise ValueError('Remote identity changed since preview')
            # Recheck cancellation after bounded preflight network work.
            if cancelled():
                result['cancelled'] = True
                break
            with _connection(db_path, write=True) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                init_schema(conn)
                if current['status'] == 'identical':
                    local = current['local']
                    if local is None:
                        raise ValueError('Local stack is unavailable')
                    if _local(conn, owner, local['id'], visibility) != local:
                        raise ValueError('Local stack changed during preflight')
                    _link(conn, scope, local, current['remote'])
                    _record(conn, scope, admission_scope, operation, 'completed', local['id'], current['remote']['id'])
                    result['items'].append(dict(key=key, status='identical'))
                    continue
                if plan['direction'] == 'import':
                    # Re-evaluate all local targets inside the same write transaction.
                    paths = current['paths']
                    created = stacks.create_stack(conn, owner, paths, current['cover'],
                                                  visibility_sql=vis, visibility_params=values)['stack']
                    local = _local(conn, owner, created['id'], visibility)
                    _link(conn, scope, local, current['remote'])
                    _record(conn, scope, admission_scope, operation, 'completed', local['id'], current['remote']['id'])
                    evict_derived_stats_cache(conn)
                    result['items'].append(dict(key=key, status='imported'))
                    continue
                local = _local(conn, owner, key, visibility)
                if local != original['local']:
                    raise ValueError('Local stack changed during preflight')
                receipt = conn.execute(
                    'SELECT 1 FROM immich_stack_send_claims '
                    'WHERE admission_scope=? AND asset_id IN (SELECT value FROM json_each(?)) LIMIT 1',
                    (admission_scope, _json(current['remote']['ids']))).fetchone()
                if receipt is not None:
                    result['items'].append(dict(key=key, status='uncertain', reason='A remote send is already recorded; refresh the preview to reconcile'))
                    continue
                _record(conn, scope, admission_scope, operation, 'attempted', key, asset_ids=current['remote']['ids'])
                conn.executemany('INSERT INTO immich_stack_send_claims VALUES (?,?,?)',
                                 [(admission_scope, aid, operation) for aid in current['remote']['ids']])
            # No SQLite write lock is held across network work.
            ids = [current['remote']['cover'], *[aid for aid in current['remote']['ids'] if aid != current['remote']['cover']]]
            sent = True
            try:
                client._request('POST', '/api/stacks', {'assetIds': ids})
            except PUSH_ERRORS:
                logger.exception('Stack create response was not confirmed; reconciling remote state')
            with _connection(db_path) as conn:
                observed = _evaluate(conn, client, 'push', key, owner, account, config, visibility, scope)
            with _connection(db_path, write=True) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                try:
                    actual_local = _local(conn, owner, key, visibility)
                except ValueError:
                    actual_local = None
                if (observed['status'] == 'identical' and observed['local'] == original['local']
                        and actual_local == original['local']):
                    _link(conn, scope, actual_local, observed['remote'])
                    _record(conn, scope, admission_scope, operation, 'completed', key, observed['remote']['id'])
                    result['items'].append(dict(key=key, status='created'))
                else:
                    _record(conn, scope, admission_scope, operation, 'uncertain', key)
                    result['items'].append(dict(key=key, status='uncertain', reason='Remote write needs reconciliation'))
        except PUSH_ERRORS:
            logger.exception('Stack exchange stopped an item without confirmed completion')
            result['items'].append(dict(key=key, status='uncertain' if sent else 'conflict',
                                        reason='Stack changed or could not be verified'))
    return result


def write_plan(path, plan, *, db_path):
    _verify_plan(plan, plan.get('plan_id'))
    target = Path(path).absolute()
    db = Path(db_path).resolve()
    if target.resolve() in (db, Path(str(db) + '-wal'), Path(str(db) + '-shm')):
        raise ValueError('A plan must not overwrite the source database')
    if target.exists():
        raise ValueError('Choose a new private plan filename')
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.facet-stacks-', dir=target.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(_json(plan) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication refuses a concurrently-created target atomically.
        os.link(temporary, target)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def read_plan(path):
    with open(path, 'rb') as handle:
        raw = handle.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise ValueError('Stack plan exceeds its size limit')
    try:
        plan = json.loads(raw.decode('utf-8'))
    except RecursionError:
        raise ValueError('Invalid stack plan nesting') from None
    _verify_plan(plan, plan.get('plan_id') if isinstance(plan, dict) else None)
    return plan


def run_cli(args, config):
    try:
        if args.immich_stacks_plan:
            plan = plan_stacks(args.db, config, args.immich_stacks_plan,
                               user_id=args.user, stack_ids=args.immich_stack_ids)
            if args.stack_plan_out:
                write_plan(args.stack_plan_out, plan, db_path=args.db)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        result = apply_stacks(args.db, config, read_plan(args.immich_stacks_apply),
                              ack_plan=args.ack_stack_plan, user_id=args.user)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if any(i['status'] in ('conflict', 'uncertain') for i in result['items']) else 0
    except KeyboardInterrupt:
        print('Stack exchange cancelled; reconcile the same plan before retrying an unconfirmed write.', file=sys.stderr)
        return 130
    except PUSH_ERRORS:
        logger.exception('Stack exchange failed')
        print('Stack exchange failed. Check the database, plan, mapping and API permissions; no automatic retry was attempted.', file=sys.stderr)
        return 1
