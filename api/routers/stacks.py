"""Private manual stacks; synchronous routes run SQLite in FastAPI's worker pool."""
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import CurrentUser, is_multi_user_enabled, require_authenticated, require_edition
from api.database import get_db
from api.db_helpers import after_commit, get_visibility_clause, is_locked_error, retry_on_locked
from api.models.stacks import (CreateStack, PhotoStack, StackMutation, UpdateStack,
                               StackSuggestionsRequest, StackSuggestionsResponse)
from db import stacks
from db.maintenance import evict_derived_stats_cache

router = APIRouter(tags=['stacks'])
logger = logging.getLogger(__name__)


def stack_owner(user_id: str | None) -> str:
    if is_multi_user_enabled():
        if not user_id:
            raise HTTPException(401, 'Authentication required')
        return user_id
    return ''


def _scope(user: CurrentUser) -> dict:
    clause, params = get_visibility_clause(user.user_id)
    return dict(visibility_sql=clause, visibility_params=params)


@router.get('/api/stacks/by-photo', response_model=PhotoStack | None)
def stack_by_photo(response: Response, path: str, user: CurrentUser = Depends(require_authenticated)):
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        return stacks.get_stack_by_photo(conn, stack_owner(user.user_id), path, editable=user.is_edition, **_scope(user))


@router.get('/api/stacks/{stack_id}', response_model=PhotoStack | None)
def stack_by_id(stack_id: str, response: Response, user: CurrentUser = Depends(require_authenticated)):
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        return stacks.get_stack(conn, stack_owner(user.user_id), stack_id, editable=user.is_edition, **_scope(user))


def _mutate(user, operation, *args, **kwargs):
    try:
        with get_db() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            result = operation(conn, stack_owner(user.user_id), *args, **kwargs, **_scope(user))
            evict_derived_stats_cache(conn)
    except stacks.StackError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, 'Organization history cannot represent this edit') from exc
    except sqlite3.Error as exc:
        if is_locked_error(exc):
            raise
        logger.exception('Could not change stack')
        raise HTTPException(500, 'Could not change stack') from exc
    after_commit()
    return result


@router.post('/api/stacks', response_model=StackMutation, status_code=201)
@retry_on_locked()
def create_stack(body: CreateStack, user: CurrentUser = Depends(require_edition)):
    return _mutate(user, stacks.create_stack, body.paths, body.cover_path)


@router.put('/api/stacks/{stack_id}', response_model=StackMutation)
@retry_on_locked()
def update_stack(stack_id: str, body: UpdateStack, user: CurrentUser = Depends(require_edition)):
    return _mutate(user, stacks.update_stack, stack_id, body.paths, body.cover_path, body.expected_revision)


@router.delete('/api/stacks/{stack_id}', response_model=StackMutation)
@retry_on_locked()
def delete_stack(stack_id: str, expected_revision: int = Query(gt=0), user: CurrentUser = Depends(require_edition)):
    return _mutate(user, stacks.delete_stack, stack_id, expected_revision)


@router.post('/api/stacks/suggestions', response_model=StackSuggestionsResponse)
def stack_suggestions(body: StackSuggestionsRequest, response: Response,
                      user: CurrentUser = Depends(require_authenticated)):
    """Scoped, bounded suggestions only; no writes, filesystem reads or cached private rows."""
    from pydantic import ValidationError
    from api.models.gallery import query_value
    from api.routers.gallery import gallery_scope_sql, _raise_422_for_invalid_gallery_params
    from db.stack_suggestions import suggestions

    response.headers['Cache-Control'] = 'no-store'
    # The gallery validator reads query-string values, so a JSON number or boolean
    # the request model accepts is converted the way /api/photos/by_paths does.
    filters = {**{key: query_value(value) for key, value in body.filters.items()},
               'collapse_stacks': 'false', 'hide_bursts': 'false', 'hide_duplicates': 'false'}
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        try:
            source, where, params = gallery_scope_sql(conn, filters, user.user_id)
        except ValidationError as exc:
            _raise_422_for_invalid_gallery_params(exc, logger, 'Invalid stack suggestion filters: %s')
        return dict(suggestions=suggestions(conn, stack_owner(user.user_id), source, where, params))
