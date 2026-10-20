"""The undo journal for a logged-in human: list recent agent changes, undo one batch.

Human sessions only (``require_human_session``): the dialog forwards the user's OWN bearer to the
same in-process routes the agent's undo uses, so nothing is minted and nothing escalates. Rows are
scoped by the session's principal; on a single password every session shares one principal, so a
viewer-only session sees and undoes only batches at or below its own level.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.agent import journal, tokens
from api.agent.internal_client import InternalClient
from api.auth import CurrentUser, require_human_session
from api.config import mcp_settings
from api.models.agent_actions import AgentActionList, AgentUndoRequest, AgentUndoResult
from api.routers.mcp_tokens import _refuse_agent_token, _require_enabled, _shared_principal_scope

logger = logging.getLogger(__name__)

LIST_LIMIT_MAX = 50
router = APIRouter(prefix="/api/mcp", tags=["mcp"],
                   dependencies=[Depends(_require_enabled), Depends(_refuse_agent_token)])


def _bearer(request: Request) -> Optional[str]:
    scheme, _, secret = request.headers.get("authorization", "").partition(" ")
    return secret.strip() if scheme.lower() == "bearer" and secret.strip() else None


@router.get(
    "/actions",
    response_model=AgentActionList,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "An agent credential was used."},
        404: {"description": "The agent endpoint is disabled (viewer.mcp.enabled)."},
    },
)
def list_actions(
    limit: int = Query(20, ge=1, le=LIST_LIMIT_MAX),
    include_undone: int = Query(0, description="1 also lists batches that were already undone"),
    user: CurrentUser = Depends(require_human_session),
):
    """The caller's recent agent changes, newest first, grouped by tool call."""
    grant = tokens.session_grant(user)
    return {"actions": journal.list_batches(
        journal.owner_of(grant), limit=limit, include_undone=bool(include_undone),
        ceiling_rank=_shared_principal_scope(user))}


@router.post(
    "/actions/undo",
    response_model=AgentUndoResult,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "An agent credential was used, or the session's level is below the batch's."},
        404: {"description": "No such batch for this account, or the endpoint is disabled."},
        409: {"description": "The batch was already undone."},
    },
)
async def undo_action(
    body: AgentUndoRequest, request: Request, user: CurrentUser = Depends(require_human_session),
):
    """Undo one batch as the session's owner. Each target is restored only if it still holds the agent's value."""
    grant = tokens.session_grant(user, _bearer(request))
    resolved = grant.resolve()
    if resolved is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    envelope = await journal.undo_batch(
        InternalClient(request.app), grant, resolved, journal.owner_of(grant), body.batch_id,
        mcp_settings()["call_timeout_s"], ceiling_rank=_shared_principal_scope(user))
    if envelope["ok"]:
        return envelope["data"]
    status = {"not_found": 404, "already_undone": 409, "forbidden_level": 403}.get(envelope["error"], 502)
    raise HTTPException(status_code=status, detail=envelope["message"])
