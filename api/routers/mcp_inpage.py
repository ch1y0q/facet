"""The in-page agent routes: list the server tools a browser session may use, and call one.

Order of checks: the flags (404 when ``viewer.mcp.enabled`` or ``viewer.mcp.inpage_tools`` is off) -> a
foreign ``Origin`` (403) -> a HUMAN Bearer session (``require_human_session``: the cookie never
authenticates a POST, and the agent's internal ``mcp`` JWT is refused) -> the session grant, re-resolved
against the live config (401 when the account is gone). The tool then runs through the same wrapper as
``/mcp`` (:mod:`api.agent.inpage`).
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.agent import inpage, tokens
from api.auth import CurrentUser, require_human_session
from api.config import mcp_settings
from api.models.mcp_inpage import McpCallRequest, McpCallResponse, McpInpageTools
from api.routers.mcp_bridge import origin_allowed
from api.routers.mcp_tokens import _refuse_agent_token, session_claims

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _require_inpage() -> None:
    settings = mcp_settings()
    if not (settings["enabled"] and settings["inpage_tools"]):
        raise HTTPException(status_code=404, detail="Not Found")


def _refuse_foreign_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and not origin_allowed(origin, request.headers.get("host")):
        raise HTTPException(status_code=403, detail="Cross-origin requests are not accepted")


router = APIRouter(prefix="/api/mcp", tags=["mcp"],
                   dependencies=[Depends(_require_inpage), Depends(_refuse_foreign_origin),
                                 Depends(_refuse_agent_token)])


def _resolved(user: CurrentUser, request: Request) -> tuple[tokens.SessionGrant, tokens.ResolvedGrant]:
    grant = tokens.session_grant(user, session_claims(request))
    resolved = grant.resolve() if grant is not None else None
    if grant is None or resolved is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return grant, resolved


@router.get(
    "/inpage_tools",
    response_model=McpInpageTools,
    responses={
        401: {"description": "Authentication required."},
        403: {"description": "An agent credential or a foreign origin was used."},
        404: {"description": "In-page tools are disabled (viewer.mcp.enabled / viewer.mcp.inpage_tools)."},
    },
)
async def inpage_tools(request: Request, user: CurrentUser = Depends(require_human_session)):
    """The server tools this session may call from the page, live, with the schemas the registry holds."""
    _, resolved = _resolved(user, request)
    tools = await inpage.listing(request.app.state.mcp_server, resolved, mcp_settings())
    return {"level": resolved.level, "tools": tools}


@router.post(
    "/call",
    response_model=McpCallResponse,
    response_model_exclude_unset=True,
    responses={
        400: {"description": "Missing or malformed X-Facet-Agent-Session header."},
        401: {"description": "Authentication required."},
        403: {"description": "An agent credential or a foreign origin was used."},
        404: {"description": "In-page tools are disabled (viewer.mcp.enabled / viewer.mcp.inpage_tools)."},
    },
)
async def call_tool(
    body: McpCallRequest, request: Request, user: CurrentUser = Depends(require_human_session),
    session_id: Optional[str] = Header(default=None, alias=inpage.SESSION_HEADER),
):
    """Run one tool as this session. A tool failure is a 200 envelope (`ok: false`), like on `/mcp`."""
    if session_id is None or not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail=f"{inpage.SESSION_HEADER} must be 1-64 of A-Z a-z 0-9 _ -")
    grant, _ = _resolved(user, request)
    return await inpage.call(
        request.app.state.mcp_server, grant.with_call(session_id, body.selection_snapshot),
        mcp_settings(), body.tool, body.arguments)
