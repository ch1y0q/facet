"""Agent (MCP) token management: mint (plaintext shown once), list, revoke.

Order of checks: the feature flag (404 when off) -> a HUMAN session
(``require_human_session`` refuses the agent's own internal JWT) -> the level rule.
Bearer-only on a password-protected install: a state-changing request never
authenticates from the cookie.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.agent import tokens
from api.auth import CurrentUser, _edition_refusal, require_human_session
from api.config import is_multi_user_enabled, mcp_settings
from api.models.mcp import (
    McpTokenCreate, McpTokenCreated, McpTokenList, McpTokenRevoked,
)

logger = logging.getLogger(__name__)


def _require_enabled() -> None:
    if not mcp_settings()['enabled']:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(prefix="/api/mcp", tags=["mcp"], dependencies=[Depends(_require_enabled)])


def _principal(user: CurrentUser) -> str:
    """The identity a token is bound to: the account, the shared password, or nobody."""
    mode = tokens.install_mode()
    if mode == 'multi':
        return user.user_id or ''
    if mode == 'legacy':
        return tokens.LEGACY_PRINCIPAL
    return tokens.OPEN_PRINCIPAL


def _granted_level(user: CurrentUser, requested: str) -> str:
    """The level to mint at, or a 403 when the session may not hold ``requested``.

    ``readonly`` is always allowed. ``edition`` needs an edition session. ``user``
    is a multi-user concept (an account's own per-photo rights); on a single
    password it has no meaning -- the rating routes demand edition -- so it is
    capped to ``readonly``. An open install can never hold more than ``readonly``.
    """
    mode = tokens.install_mode()
    if mode in ('open', 'unreadable'):
        return 'readonly'
    if requested == 'edition':
        if not user.is_edition:
            raise _edition_refusal("Edition access required to mint an edition token")
        return 'edition'
    if requested == 'user' and mode == 'multi':
        return 'user'
    return 'readonly'


def _session_level(user: CurrentUser) -> str:
    return 'edition' if user.is_edition else 'readonly'


def _shared_principal_scope(user: CurrentUser) -> Optional[int]:
    """The highest token rank this session may see and revoke, or None when it is unbounded.

    On a single password every session shares one principal (``_legacy``), so a
    viewer-only session would otherwise list and revoke the tokens an edition
    session minted. There the session may only manage tokens at or below its own
    level. In multi-user mode the owner scoping already isolates accounts.
    """
    if tokens.install_mode() == 'multi':
        return None
    return tokens.level_rank(_session_level(user))


@router.post(
    "/tokens",
    response_model=McpTokenCreated,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "The session may not hold the requested level, or an agent credential was used."},
        404: {"description": "The agent endpoint is disabled (viewer.mcp.enabled)."},
        412: {"description": "The owner already has the maximum number of live tokens."},
    },
)
def create_token(body: McpTokenCreate, user: CurrentUser = Depends(require_human_session)):
    """Mint a token. The plaintext is in this response and nowhere else, ever."""
    principal = _principal(user)
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    level = _granted_level(user, body.level)
    if tokens.count_live(principal) >= tokens.MAX_LIVE_TOKENS_PER_USER:
        raise HTTPException(
            status_code=412,
            detail=f"At most {tokens.MAX_LIVE_TOKENS_PER_USER} live tokens per user; revoke one first")
    row, plaintext = tokens.mint(principal, body.name, level)
    logger.info("MCP token %d minted (level %s)", row['id'], level)
    return {**row, 'token': plaintext}


@router.get(
    "/tokens",
    response_model=McpTokenList,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "Superadmin access required, or an agent credential was used."},
        404: {"description": "The agent endpoint is disabled (viewer.mcp.enabled)."},
    },
)
def list_tokens(
    all: int = Query(0, description="1 lists every owner's tokens (superadmin only)"),
    user: CurrentUser = Depends(require_human_session),
):
    """The caller's own tokens, newest first. Never the secret or its hash."""
    if all:
        if not (is_multi_user_enabled() and user.is_superadmin):
            raise HTTPException(status_code=403, detail="Superadmin access required")
        return {'tokens': tokens.list_tokens(None)}
    rows = tokens.list_tokens(_principal(user))
    ceiling = _shared_principal_scope(user)
    if ceiling is not None:
        rows = [row for row in rows if tokens.level_rank(row['level']) <= ceiling]
    return {'tokens': rows}


@router.delete(
    "/tokens/{token_id}",
    response_model=McpTokenRevoked,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "An agent credential was used, or the token's level is above the session's."},
        404: {"description": "No such live token, or the endpoint is disabled."},
    },
)
def revoke_token(token_id: int, user: CurrentUser = Depends(require_human_session)):
    """Revoke one of the caller's tokens (any token, for a superadmin)."""
    owner: Optional[str] = None if (is_multi_user_enabled() and user.is_superadmin) else _principal(user)
    ceiling = _shared_principal_scope(user)
    if ceiling is not None:
        target = next((row for row in tokens.list_tokens(owner) if row['id'] == token_id), None)
        if target is not None and tokens.level_rank(target['level']) > ceiling:
            raise _edition_refusal("Edition access required to revoke an edition token")
    if not tokens.revoke(token_id, owner):
        raise HTTPException(status_code=404, detail="Token not found")
    logger.info("MCP token %d revoked", token_id)
    return {'ok': True, 'id': token_id}
