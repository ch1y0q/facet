"""The wrapper every tool runs inside: identity, rate limit, caps, audit.

Identity comes from the ``Authorization`` header the SDK exposes as
``ctx.headers``, re-verified against the token table on EVERY call. The header is
a bearer secret that is checked, never a trusted claim, and nothing is stashed in
a ContextVar by the middleware: task propagation through the SDK's dispatch is not
something this code relies on.
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional, cast

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, ImageContent, TextContent
from starlette.requests import Request

from api.agent import limits, nonce, tokens
from api.agent.internal_client import err
from api.agent.tools_common import TOOL_LEVELS

logger = logging.getLogger(__name__)

# ASGI scope key under which ``AgentAuthMiddleware`` leaves the request's ``mcp_settings()``
# for the tool wrapper, so one request reads the (clamped) config once.
SETTINGS_SCOPE_KEY = "facet.mcp_settings"

Handler = Callable[[tokens.TokenGrant, tokens.ResolvedGrant, dict], Awaitable[dict]]


def bearer_token(headers: Any) -> Optional[str]:
    """The ``fct_`` secret from an ``Authorization: Bearer`` header, else None."""
    value = (headers or {}).get("authorization") if headers is not None else None
    if not isinstance(value, str):
        return None
    scheme, _, secret = value.partition(" ")
    return secret.strip() if scheme.lower() == "bearer" and secret.strip() else None


def to_result(envelope: dict, images: Optional[list] = None) -> CallToolResult:
    """Compact JSON as the text block, after any images; no duplicated structured content."""
    text = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, default=str)
    content: list = [ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mime_type=mime)
                     for data, mime in images or ()]
    content.append(TextContent(type="text", text=text))
    return CallToolResult(content=content, is_error=not envelope.get("ok", False))


def _row_count(envelope: dict) -> int:
    data = envelope.get("data")
    rows = data.get("rows") if isinstance(data, dict) else None
    return len(rows) if isinstance(rows, list) else 0


async def run_tool(ctx: Context, name: str, handler: Handler, *, write: bool = False,
                   min_level: Optional[str] = None) -> CallToolResult:
    """Authenticate, rate-limit and run ``handler``; always return an envelope.

    Handlers never raise to the SDK: transport-level failure is reserved for the
    auth gate (401/403/429), so a tool problem reaches the model as data.

    The tool's floor (``min_level``, else its ``TOOL_LEVELS`` entry) is checked here
    BEFORE the rate limit and before ``handler`` runs, so a refused tool makes no
    upstream call at all (not even a read-only pre-count).
    """
    floor = min_level or TOOL_LEVELS[name]
    started = time.monotonic()
    images: list = []
    settings = cast(Request, ctx.request_context.request).scope[SETTINGS_SCOPE_KEY]
    token_id = None
    try:
        grant = await asyncio.to_thread(tokens.verify, bearer_token(ctx.headers))
        resolved = await asyncio.to_thread(grant.resolve) if grant else None
        if grant is None or resolved is None:
            envelope = err("forbidden_level", "This token is revoked or no longer valid")
        else:
            token_id = grant.id
            per_min = settings["write_rate_per_min" if write else "rate_per_min"]
            if tokens.level_rank(resolved.level) < tokens.level_rank(floor):
                needs = tokens.effective_requirement(floor)
                hint = (" (an open install cannot grant it: set viewer.password and mint an "
                        "edition token)" if needs == "edition" and tokens.install_mode() == "open" else "")
                envelope = err("forbidden_level",
                               f"This token's level is {resolved.level}; {name} needs {needs}{hint}")
            else:
                allowed, retry_after = limits.check_rate(grant.id, write, per_min)
                if allowed:
                    envelope = await handler(grant, resolved, settings)
                    # Images ride beside the JSON, so the JSON cap must not see (or count) them.
                    images = envelope.pop("_images", None) or []
                    envelope = limits.fit_envelope(
                        envelope, settings["max_rows"], settings["max_bytes"])
                else:
                    envelope = err("rate_limited", "Too many calls; slow down",
                                   retry_after_s=retry_after)
    except nonce.NonceCapacityError:
        envelope = err("rate_limited", "Too many confirmations are pending; retry in a few minutes",
                       retry_after_s=int(nonce.TTL_SECONDS))
    except Exception:
        logger.exception("Agent tool %s crashed", name)
        envelope = err("upstream_error", "The tool failed unexpectedly")
    else:
        if token_id is not None and envelope.get("error") not in ("forbidden_level", "rate_limited"):
            # Best effort, after the result exists: a locked database must not turn a
            # finished call into an error.
            try:
                await asyncio.to_thread(tokens.touch, token_id)
            except Exception as ex:
                logger.warning("Could not stamp last_used_at for MCP token %s: %r", token_id, ex)
    # Counts and codes only: never arguments (paths) and never the token.
    logger.info("MCP call token=%s tool=%s ok=%s code=%s rows=%d ms=%d", token_id, name,
                envelope.get("ok"), envelope.get("error", "-"), _row_count(envelope),
                (time.monotonic() - started) * 1000)
    return to_result(envelope, images if envelope.get("ok") else None)
