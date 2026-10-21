"""MCP resources: five read-only reference lists under ``facet://``.

They are served from this module's own table, not from the SDK's resource manager: that one has no
request context at list time, and what a reader returns depends on WHO asks (a person hidden for a
user is absent). Each read re-runs its reader through :class:`InternalClient` with the caller's grant,
so every route's own visibility applies and nothing here touches the database. There are no URI
templates: parametrised reads stay with the tools (``list_persons``, ``filter_options``, ``get_photo``).
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional, Union, cast, get_args, get_origin

from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR, INVALID_PARAMS, ListResourcesResult, ReadResourceResult, Resource, TextResourceContents,
)

from api.agent import prompts, tokens
from api.agent.internal_client import InternalClient
from api.agent.runtime import SETTINGS_SCOPE_KEY, bearer_token
from api.agent.tools_common import MCP_FILTER_KEYS, UNTRUSTED_META
from api.models.gallery import GalleryParams

MAX_BYTES = 32 * 1024
MAX_ROWS = 200
MIME = "application/json"

Reader = Callable[[InternalClient, Any, float], Awaitable[dict]]


@dataclass(frozen=True)
class ResourceSpec:
    uri: str
    name: str
    description: str
    read: Reader
    required: tuple[str, ...] = ()


async def _route(client: InternalClient, grant: Any, timeout: float, route: str, **query: Any) -> Any:
    got = await client.call(grant, route, query=query or None, timeout=timeout)
    if not got["ok"]:
        raise MCPError(INTERNAL_ERROR, got["message"])
    return got["data"]


async def _categories(client: InternalClient, grant: Any, timeout: float) -> dict:
    return {"categories": ((await _route(client, grant, timeout, "filter_options.categories")) or {}).get("categories")}


async def _tags(client: InternalClient, grant: Any, timeout: float) -> dict:
    return {"tags": ((await _route(client, grant, timeout, "filter_options.tags")) or {}).get("tags")}


async def _persons(client: InternalClient, grant: Any, timeout: float) -> dict:
    body = await _route(client, grant, timeout, "list_persons", per_page=MAX_ROWS) or {}
    return {"persons": [{k: p.get(k) for k in ("id", "name", "face_count")} for p in body.get("persons") or []
                        if p.get("name")], "total": body.get("total")}


async def _scoring_contexts(client: InternalClient, grant: Any, timeout: float) -> dict:
    body = await _route(client, grant, timeout, "scoring_contexts") or {}
    return {"scoring_contexts": [{k: c.get(k) for k in ("name", "promote", "excluded", "effective_order")}
                                 for c in body.get("contexts") or []]}


def _domain(key: str) -> dict:
    """The value domain of one gallery filter, read off ``GalleryParams`` rather than restated here."""
    field = GalleryParams.model_fields.get(key)
    if field is None:
        return {"type": "string"}
    annotation = field.annotation
    if get_origin(annotation) is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        annotation = args[0] if len(args) == 1 else annotation
    if get_origin(annotation) is Literal:
        return {"enum": list(get_args(annotation))}
    named = {int: "integer", float: "number", bool: "boolean", str: "string"}
    return {"type": named.get(cast(Any, annotation), "string")}


async def _filters(client: InternalClient, grant: Any, timeout: float) -> dict:
    ranges = await _route(client, grant, timeout, "filter_options.metric_ranges")
    return {"filters": {key: _domain(key) for key in MCP_FILTER_KEYS}, "metric_ranges": ranges}


RESOURCES: dict[str, ResourceSpec] = {spec.uri: spec for spec in (
    ResourceSpec("facet://categories", "Categories", "Scoring category names with their photo counts.", _categories,
                 ("filter_options",)),
    ResourceSpec("facet://tags", "Tags", "The tag vocabulary with counts (top 200).", _tags,
                 ("filter_options",)),
    ResourceSpec("facet://persons", "Persons", "Named people with their photo counts, as this key's owner sees them.",
                 _persons, ("list_persons",)),
    ResourceSpec("facet://filters", "Filters", "Every search_photos filter key with its value domain and the "
                 "library's metric ranges.", _filters, ("search_photos", "filter_options")),
    ResourceSpec("facet://scoring-contexts", "Scoring contexts", "Scoring contexts: promoted and excluded "
                 "categories and the resulting order.", _scoring_contexts),
)}


def _limit(value: Any) -> tuple[Any, bool]:
    """Cut every list (one level deep inside a dict) to ``MAX_ROWS``, then halve until it fits ``MAX_BYTES``."""
    cut = False

    def trim(items: Any, size: int) -> Any:
        nonlocal cut
        if isinstance(items, list) and len(items) > size:
            cut = True
            return items[:size]
        return items

    size = MAX_ROWS
    while True:
        shaped = ({k: trim(v, size) for k, v in value.items()} if isinstance(value, dict) else trim(value, size))
        if len(json.dumps(shaped, ensure_ascii=False, default=str).encode("utf-8")) <= MAX_BYTES or size <= 1:
            return shaped, cut
        size //= 2
        cut = True


def list_resources(resolved: tokens.ResolvedGrant, settings: dict) -> ListResourcesResult:
    """The resources whose tools this key is offered, by the filter ``tools/list`` and ``prompts/list`` use."""
    seen = prompts.visible_tools(resolved, settings)
    return ListResourcesResult(resources=[
        Resource(uri=spec.uri, name=spec.name, description=spec.description, mime_type=MIME, _meta=UNTRUSTED_META)
        for spec in RESOURCES.values() if set(spec.required) <= seen])


async def read_resource(request: Any, uri: str, client: Optional[InternalClient]) -> ReadResourceResult:
    """Gate (bearer, rate limit, audit) like a prompt, then run the reader as the caller."""
    await prompts.authorize(request, uri)
    spec = RESOURCES.get(str(uri))
    if spec is None or client is None:
        raise MCPError(INVALID_PARAMS, f"Unknown resource: {str(uri)[:64]}", data={"uri": str(uri)[:64]})
    grant = await asyncio.to_thread(tokens.verify_request, bearer_token(request.headers), request)
    settings = request.scope[SETTINGS_SCOPE_KEY]
    data, truncated = _limit(await spec.read(client, grant, settings["call_timeout_s"]))
    text = json.dumps({"uri": spec.uri, "truncated": truncated, "data": data}, ensure_ascii=False, default=str)
    return ReadResourceResult(contents=[TextResourceContents(uri=spec.uri, text=text, mime_type=MIME,
                                                            _meta=UNTRUSTED_META)])
