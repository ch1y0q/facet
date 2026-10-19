"""The wrapper every tool runs inside: identity, rate limit, caps, audit.

Identity comes from the ``Authorization`` header the SDK exposes as
``ctx.headers``, re-verified against the token table on EVERY call. The header is
a bearer secret that is checked, never a trusted claim, and nothing is stashed in
a ContextVar by the middleware: task propagation through the SDK's dispatch is not
something this code relies on.
"""

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent

from api.agent import limits, tokens
from api.agent.internal_client import err
from api.config import mcp_settings

logger = logging.getLogger(__name__)

Handler = Callable[[tokens.TokenGrant, tokens.ResolvedGrant, dict], Awaitable[dict]]


def bearer_token(headers: Any) -> Optional[str]:
    """The ``fct_`` secret from an ``Authorization: Bearer`` header, else None."""
    value = (headers or {}).get("authorization") if headers is not None else None
    if not isinstance(value, str):
        return None
    scheme, _, secret = value.partition(" ")
    return secret.strip() if scheme.lower() == "bearer" and secret.strip() else None


def to_result(envelope: dict) -> CallToolResult:
    """Compact JSON as the single text block; no duplicated structured content."""
    text = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, default=str)
    return CallToolResult(content=[TextContent(type="text", text=text)],
                          is_error=not envelope.get("ok", False))


def _row_count(envelope: dict) -> int:
    data = envelope.get("data")
    rows = data.get("rows") if isinstance(data, dict) else None
    return len(rows) if isinstance(rows, list) else 0


async def run_tool(ctx: Context, name: str, handler: Handler, *, write: bool = False,
                   min_level: str = "readonly") -> CallToolResult:
    """Authenticate, rate-limit and run ``handler``; always return an envelope.

    Handlers never raise to the SDK: transport-level failure is reserved for the
    auth gate (401/403/429), so a tool problem reaches the model as data.

    ``min_level`` is the tool's own floor, checked here BEFORE the rate limit and
    before ``handler`` runs, so a refused tool makes no upstream call at all (not
    even a read-only pre-count).
    """
    started = time.monotonic()
    settings = mcp_settings()
    token_id = None
    try:
        if not settings["enabled"]:
            envelope = err("forbidden_level", "The agent endpoint is disabled")
        else:
            grant = await asyncio.to_thread(tokens.verify, bearer_token(ctx.headers))
            resolved = await asyncio.to_thread(grant.resolve) if grant else None
            if grant is None or resolved is None:
                envelope = err("forbidden_level", "This token is revoked or no longer valid")
            else:
                token_id = grant.id
                per_min = settings["write_rate_per_min" if write else "rate_per_min"]
                below_floor = tokens.level_rank(resolved.level) < tokens.level_rank(min_level)
                allowed, retry_after = (True, 0.0) if below_floor else limits.check_rate(
                    grant.id, write, per_min)
                if below_floor:
                    envelope = err("forbidden_level",
                                   f"This token's level is {resolved.level}; {name} needs {min_level}")
                elif not allowed:
                    envelope = err("rate_limited", "Too many calls; slow down",
                                   retry_after_s=retry_after)
                else:
                    envelope = await handler(grant, resolved, settings)
                    envelope = limits.fit_envelope(
                        envelope, settings["max_rows"], settings["max_bytes"])
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
    return to_result(envelope)
