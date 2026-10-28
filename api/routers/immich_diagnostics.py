"""Bounded read-only diagnostics. Never synchronizes or modifies remote assets."""
from contextlib import closing
from copy import deepcopy
import datetime
import json
import logging
import math
import sqlite3
import threading
from pathlib import Path
from urllib import error, request

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from starlette.concurrency import run_in_threadpool

from api.auth import require_scan_access
from api.models.immich import ImmichDiagnosticsResponse
from sync.immich import ImmichClient, _scope_key, map_facet_path

logger = logging.getLogger(__name__)
_SAMPLE_LIMIT = 200
_RESPONSE_LIMIT = 65536
_TIMEOUT = 3
_connection_test = threading.Lock()


class _PrivateRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def private_handler(req):
            try:
                response = await original(req)
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(req, exc)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), 'Cache-Control': 'no-store'}
                raise
            response.headers['Cache-Control'] = 'no-store'
            return response
        return private_handler


router = APIRouter(tags=['immich'], route_class=_PrivateRoute)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_remote(client, path):
    # Only fixed read endpoints; no provider redirect may forward the API key.
    req = request.Request(client.base_url + path,
                          headers={'x-api-key': client.api_key, 'Accept': 'application/json'})
    with request.build_opener(_NoRedirect()).open(req, timeout=_TIMEOUT) as response:
        data = response.read(_RESPONSE_LIMIT + 1)
    if len(data) > _RESPONSE_LIMIT:
        raise ValueError('Oversized diagnostic response')
    return json.loads(data)


def _local_status(config, user_id=None):
    from db import DEFAULT_DB_PATH
    from api.config import is_multi_user_enabled
    from api.db_helpers import get_visibility_clause

    cfg = config.get('immich', {}) or {}
    invalid_config = not isinstance(cfg, dict)
    if invalid_config:
        cfg = {}
    pairs = cfg.get('path_map', []) or []
    if (invalid_config or not isinstance(pairs, list) or any(not isinstance(p, dict) or
            not isinstance(p.get('facet_prefix', ''), str) or
            not isinstance(p.get('immich_prefix', ''), str) for p in pairs)):
        pairs = []
        invalid_mapping = True
    else:
        invalid_mapping = False
    with closing(sqlite3.connect(Path(DEFAULT_DB_PATH).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')
        vis, params = get_visibility_clause(user_id) if is_multi_user_enabled() else ('1=1', [])
        paths = conn.execute(f'SELECT path FROM photos WHERE {vis} ORDER BY path LIMIT ?',
                             [*params, _SAMPLE_LIMIT]).fetchall()
        row = conn.execute("SELECT updated_at FROM stats_cache WHERE key = ?",
                           (_scope_key(user_id if is_multi_user_enabled() else None),)).fetchone()
        last = row[0] if row else None
    last_push = None
    try:
        timestamp = float(last)
        if math.isfinite(timestamp):
            last_push = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    url, key = cfg.get('url', ''), cfg.get('api_key', '')
    invalid_fields = not isinstance(url, str) or not isinstance(key, str)
    if not invalid_fields:
        invalid_fields = any(c in url or c in key for c in ('\r', '\n'))
    configured = not invalid_fields and bool(url.strip() and key.strip())
    return dict(configured=configured, mapping_rules=sum(bool(p.get('facet_prefix')) for p in pairs),
                sample_limit=_SAMPLE_LIMIT, sampled_photos=len(paths),
                mapped_photos=0 if invalid_mapping else sum(map_facet_path(p[0], pairs) is not None for p in paths),
                last_push_at=last_push, connection='invalid_config' if invalid_mapping or invalid_fields else 'not_checked',
                version=None, stack_version_supported=None)


def _diagnose(config, check_connection, user_id=None):
    from api.config import CONFIG_WRITE_LOCK

    # One version of URL, key and mappings; never retain this private snapshot
    # in the response or hold the configuration lock across DB/network work.
    with CONFIG_WRITE_LOCK:
        config = {'immich': deepcopy(config.get('immich', {}) or {})}
    status = _local_status(config, user_id)
    if not check_connection or status['connection'] == 'invalid_config':
        return status
    if not status['configured']:
        return {**status, 'connection': 'not_configured'}
    cfg = config.get('immich', {}) or {}
    try:
        client = ImmichClient(cfg['url'], cfg['api_key'], timeout=_TIMEOUT)
    except (TypeError, ValueError):
        return {**status, 'connection': 'invalid_config'}
    if not _connection_test.acquire(blocking=False):
        raise HTTPException(429, 'An Immich connection test is already running', headers={'Retry-After': '3'})
    try:
        version = _read_remote(client, '/api/server/version')
        fields = ('major', 'minor', 'patch')
        if not isinstance(version, dict) or any(type(version.get(f)) is not int or not 0 <= version[f] <= 10000 for f in fields):
            raise ValueError('Invalid version')
        # /server/version can be public. A user identity read checks key access;
        # do not return that account's private identity to the browser.
        account = _read_remote(client, '/api/users/me')
        if not isinstance(account, dict) or not isinstance(account.get('id'), str) or not account['id']:
            raise ValueError('Invalid account response')
        status.update(connection='connected', version='.'.join(str(version[f]) for f in fields),
                      stack_version_supported=version['major'] >= 3)
    except error.HTTPError as exc:
        status['connection'] = 'access_denied' if exc.code in (401, 403) else 'unreachable'
        logger.warning('Immich diagnostic HTTP request failed (status %s)', exc.code)
    except (OSError, error.URLError):
        status['connection'] = 'unreachable'
        logger.warning('Immich diagnostic connection failed')
    except (ValueError, TypeError, RecursionError):
        status['connection'] = 'invalid_response'
        logger.warning('Immich diagnostic response was invalid')
    finally:
        _connection_test.release()
    return status


@router.get('/api/immich/diagnostics', response_model=ImmichDiagnosticsResponse)
async def immich_diagnostics(response: Response, check_connection: bool = False,
                             _user=Depends(require_scan_access)):
    """Administrator-only local status; network reads require an explicit flag."""
    from api.config import _FULL_CONFIG

    try:
        return await run_in_threadpool(_diagnose, _FULL_CONFIG, check_connection, _user.user_id)
    except sqlite3.Error:
        logger.warning('Immich diagnostic database read failed')
        raise HTTPException(503, 'Library status is temporarily unavailable') from None
