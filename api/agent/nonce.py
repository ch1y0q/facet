"""Single-use confirmation nonces for destructive agent tools.

A dry run ``issue``s a nonce bound to (token, action, digest of the RESOLVED target
set + options). The real run re-resolves the set, recomputes the digest and
``consume``s: the nonce must exist, be unexpired, belong to the same token and
action, and carry the same digest. In-memory and per process, like the rate
limits; the clock is ``limits.now`` so tests inject one.
"""

import hashlib
import json
import secrets
import threading
from typing import Any, Iterable, Optional

from api.agent import limits

TTL_SECONDS = 300.0
MAX_PENDING = 256
MAX_PENDING_PER_TOKEN = 16

_lock = threading.Lock()
_pending: dict[str, tuple[int, str, str, float]] = {}


def digest(paths: Iterable[str], options: Any) -> str:
    """Stable digest of a resolved path set plus its options."""
    body = json.dumps({"paths": sorted(set(paths)), "options": options}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def reset() -> None:
    with _lock:
        _pending.clear()


def _oldest(keys: Iterable[str]) -> str:
    return min(keys, key=lambda k: _pending[k][3])


class NonceCapacityError(Exception):
    """The global pending cap is full of other tokens' live confirmations."""


def _prune(current: float, token_id: int) -> None:
    """Make room for one more nonce of ``token_id`` without touching another token's.

    A token over its own cap loses its own oldest entry. The global cap is a backstop:
    it evicts the issuing token's own entries, and when that is not enough it refuses
    with :class:`NonceCapacityError` rather than flush the confirmation another token
    is about to use.
    """
    for key in [k for k, v in _pending.items() if v[3] <= current]:
        del _pending[key]
    own = [k for k, v in _pending.items() if v[0] == token_id]
    while len(own) >= MAX_PENDING_PER_TOKEN:
        victim = _oldest(own)
        own.remove(victim)
        del _pending[victim]
    while len(_pending) >= MAX_PENDING:
        if not own:
            raise NonceCapacityError("Too many pending confirmations")
        del _pending[own.pop(own.index(_oldest(own)))]


def issue(token_id: int, action: str, payload_hash: str) -> str:
    current = limits.now()
    nonce = secrets.token_urlsafe(24)
    with _lock:
        _prune(current, token_id)
        _pending[nonce] = (token_id, action, payload_hash, current + TTL_SECONDS)
    return nonce


def check(token_id: int, action: str, payload_hash: str, confirm: Optional[str]) -> bool:
    """:func:`consume` for a caller-supplied value: an absent ``confirm`` never matches."""
    if not confirm:
        return False
    return consume(token_id, action, payload_hash, confirm)


def consume(token_id: int, action: str, payload_hash: str, nonce: str) -> bool:
    """True exactly once for a matching, live nonce.

    A nonce presented by another token or for another action is left alone (a
    stranger must not be able to burn it). One whose digest no longer matches is
    burned: the target set changed, so a fresh dry run is required.
    """
    current = limits.now()
    with _lock:
        entry = _pending.get(nonce)
        if entry is None:
            return False
        owner, entry_action, entry_hash, expires = entry
        if owner != token_id or entry_action != action:
            return False
        del _pending[nonce]
        return expires > current and secrets.compare_digest(entry_hash, payload_hash)
