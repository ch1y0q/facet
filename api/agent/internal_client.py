"""The only way an agent tool touches data: an in-process ASGI call to an ``/api`` route.

Every tool maps to one allow-listed ``(method, path template, minimum level)``.
There is no generic "call any API" tool, so the reachable surface is exactly this
table -- admin, config, scan, share, proofing, frame, webdav and login routes are
not in it. Each call therefore runs the route's own auth, validation and guards;
there is no second SQL path.

Enforcement order, per call: (1) re-resolve the token against the live config;
(2) refuse when the EFFECTIVE level is below the route's, BEFORE any upstream
call; (3) mint a 60-second JWT whose role/edition MATCH the effective level.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Mapping, Optional
from urllib.parse import quote

import httpx

from api.agent import tokens
from api.auth import create_access_token

logger = logging.getLogger(__name__)

INTERNAL_BASE_URL = "http://facet.internal"
INTERNAL_JWT_SECONDS = 60
READ_ONLY_ROUTE_LEVEL = "readonly"


@dataclass(frozen=True)
class RouteSpec:
    method: str
    template: str
    min_level: str
    write: bool = False


ROUTE_ALLOWLIST: Mapping[str, RouteSpec] = MappingProxyType({
    "search_photos": RouteSpec("GET", "/api/photos", "readonly"),
    "semantic_search": RouteSpec("GET", "/api/search", "readonly"),
    "get_photo": RouteSpec("GET", "/api/photo", "readonly"),
    "similar_photos": RouteSpec("GET", "/api/similar_photos/{path}", "readonly"),
    "filter_options.cameras": RouteSpec("GET", "/api/filter_options/cameras", "readonly"),
    "filter_options.lenses": RouteSpec("GET", "/api/filter_options/lenses", "readonly"),
    "filter_options.tags": RouteSpec("GET", "/api/filter_options/tags", "readonly"),
    "filter_options.persons": RouteSpec("GET", "/api/filter_options/persons", "readonly"),
    "filter_options.patterns": RouteSpec("GET", "/api/filter_options/patterns", "readonly"),
    "filter_options.categories": RouteSpec("GET", "/api/filter_options/categories", "readonly"),
    "filter_options.narrative_moments": RouteSpec(
        "GET", "/api/filter_options/narrative_moments", "readonly"),
    "filter_options.junk_kinds": RouteSpec("GET", "/api/filter_options/junk_kinds", "readonly"),
    "filter_options.metric_ranges": RouteSpec("GET", "/api/filter_options/metric_ranges", "readonly"),
    "list_persons": RouteSpec("GET", "/api/persons", "readonly"),
    "list_albums": RouteSpec("GET", "/api/albums", "readonly"),
    "library_stats.type_counts": RouteSpec("GET", "/api/type_counts", "readonly"),
    "library_stats.overview": RouteSpec("GET", "/api/stats/overview", "readonly"),
    "photos_count": RouteSpec("GET", "/api/photos/count", "readonly"),
    # Write routes. ``user`` = the per-photo require_auth routes a regular account
    # may call in the UI; ``edition`` = everything gated by require_edition.
    "set_rating": RouteSpec("POST", "/api/photo/set_rating", "user", write=True),
    "toggle_favorite": RouteSpec("POST", "/api/photo/toggle_favorite", "user", write=True),
    "toggle_rejected": RouteSpec("POST", "/api/photo/toggle_rejected", "user", write=True),
    "batch_favorite": RouteSpec("POST", "/api/photos/batch_favorite", "edition", write=True),
    "batch_reject": RouteSpec("POST", "/api/photos/batch_reject", "edition", write=True),
    "batch_rating": RouteSpec("POST", "/api/photos/batch_rating", "edition", write=True),
    "batch_manual_tags": RouteSpec("POST", "/api/photos/batch_manual_tags", "edition", write=True),
    "clear_junk": RouteSpec("POST", "/api/photo/clear_junk", "edition", write=True),
    "create_album": RouteSpec("POST", "/api/albums", "edition", write=True),
    "album_add_photos": RouteSpec("POST", "/api/albums/{album_id}/photos", "edition", write=True),
    "album_remove_photos": RouteSpec("DELETE", "/api/albums/{album_id}/photos", "edition", write=True),
    "cull_apply": RouteSpec("POST", "/api/cull/apply", "edition", write=True),
    "delete_photos": RouteSpec("POST", "/api/photo/delete", "edition", write=True),
    # The same two routes with ``dry_run=true``: nothing is written, so a timeout is a
    # plain upstream error rather than ``outcome_unknown``.
    "cull_apply.preview": RouteSpec("POST", "/api/cull/apply", "edition"),
    "delete_photos.preview": RouteSpec("POST", "/api/photo/delete", "edition"),
})


class NotAllowedError(Exception):
    """A tool name that is not in the allowlist. Raised before anything is sent."""


def ok(data: Any = None, **extra: Any) -> dict:
    return {"ok": True, "data": data, **extra}


def err(code: str, message: str, **extra: Any) -> dict:
    return {"ok": False, "error": code, "message": message, **extra}


def _status_to_error(status: int, detail: Any) -> dict:
    message = detail if isinstance(detail, str) else "Request refused"
    issues = detail if isinstance(detail, list) else None
    if status in (401, 403):
        return err("forbidden_level", message)
    if status == 404:
        return err("not_found", message)
    if status in (400, 412, 422):
        return err("invalid_input", message if issues is None else "Invalid input",
                   **({"issues": issues} if issues else {}))
    if status == 429:
        return err("rate_limited", message)
    if status == 503:
        return err("library_busy", "The library is busy; retry in a moment")
    logger.warning("Agent upstream call failed with HTTP %s: %s", status, detail)
    return err("upstream_error", "The server could not complete the request")


class InternalClient:
    """Calls allow-listed routes of ``app`` in-process, as the token's owner."""

    def __init__(self, app: Any, allowlist: Mapping[str, RouteSpec] = ROUTE_ALLOWLIST,
                 peer_ip: str = "127.0.0.1"):
        self._app = app
        self._allowlist = allowlist
        self._peer_ip = peer_ip

    async def call(
        self,
        grant: tokens.TokenGrant,
        tool: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        path_args: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        timeout: float = 30.0,
    ) -> dict:
        spec = self._allowlist.get(tool)
        if spec is None:
            raise NotAllowedError(tool)
        resolved = await asyncio.to_thread(grant.resolve)
        if resolved is None:
            return err("forbidden_level", "This token is no longer valid")
        if tokens.level_rank(resolved.level) < tokens.level_rank(spec.min_level):
            return err("forbidden_level",
                       f"This token's level is {resolved.level}; {tool} needs {spec.min_level}")
        for value in (path_args or {}).values():
            text = str(value)
            if not text or any(part in (".", "..") for part in text.split("/")):
                return err("invalid_input", "A path argument may not be empty or contain '.' or '..' segments")
        headers = {}
        claims = resolved.jwt_claims()
        if claims is not None:
            jwt_token = create_access_token(claims, expires_delta=timedelta(seconds=INTERNAL_JWT_SECONDS))
            headers["Authorization"] = "Bearer " + jwt_token
        path = spec.template.format(
            **{key: quote(str(value), safe="") for key, value in (path_args or {}).items()})
        params = {k: v for k, v in (query or {}).items() if v is not None}
        transport = httpx.ASGITransport(
            app=self._app, raise_app_exceptions=False, client=(self._peer_ip, 0))
        try:
            async with httpx.AsyncClient(transport=transport, base_url=INTERNAL_BASE_URL) as client:
                async with asyncio.timeout(timeout):
                    response = await client.request(
                        spec.method, path, params=params or None, json=json, headers=headers)
        except TimeoutError:
            return self._timed_out(spec, tool)
        except (httpx.HTTPError, OSError) as ex:
            logger.warning("Agent upstream call %s failed: %r", tool, ex)
            return self._timed_out(spec, tool)
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        if response.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            return _status_to_error(response.status_code, detail)
        return ok(body)

    @staticmethod
    def _timed_out(spec: RouteSpec, tool: str) -> dict:
        if spec.write:
            return err("outcome_unknown",
                       f"{tool} timed out or the connection dropped: outcome unknown, "
                       "do not blindly retry; re-read state")
        return err("upstream_error", f"{tool} did not answer in time")
