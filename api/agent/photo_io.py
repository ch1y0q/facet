"""Reads and writes the agent tools share, all through :class:`InternalClient` so the routes' own rules apply."""

from typing import Any, Optional

from api.agent.internal_client import InternalClient
from api.types import SEQUENCE_OVERRIDE_SUPPRESSED

BY_PATHS_CHUNK = 500


async def read_photos(client: InternalClient, grant: Any, paths: list[str], timeout: float,
                      filters: Optional[dict] = None) -> tuple[Optional[dict], dict[str, dict]]:
    """``(error, {path: photo})`` for ``paths`` as the grant's owner sees them (chunks of 500)."""
    found: dict[str, dict] = {}
    for start in range(0, len(paths), BY_PATHS_CHUNK):
        got = await client.call(grant, "photos_by_paths", timeout=timeout,
                                json={"paths": paths[start:start + BY_PATHS_CHUNK], "filters": filters or {}})
        if not got["ok"]:
            return got, {}
        for photo in (got["data"] or {}).get("photos") or []:
            found[photo["path"]] = photo
    return None, found


async def apply_sequence(client: InternalClient, grant: Any, timeout: float, paths: list[str],
                         value: Optional[str]) -> dict:
    """Write one override value (None clears) for ``paths`` through the same routes the tools use."""
    if value is None:
        return await client.call(grant, "clear_sequence_override", json={"paths": paths}, timeout=timeout)
    return await client.call(grant, "override_sequence", timeout=timeout,
                             json={"paths": paths, "kind": None if value == SEQUENCE_OVERRIDE_SUPPRESSED else value})


async def apply_category(client: InternalClient, grant: Any, timeout: float, path: str,
                         value: Optional[str]) -> dict:
    if value is None:
        return await client.call(grant, "clear_category_override", json={"path": path}, timeout=timeout)
    return await client.call(grant, "override_category", json={"path": path, "category": value}, timeout=timeout)
