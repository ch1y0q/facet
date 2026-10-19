"""Rate limits and response caps for the agent surface.

In-memory and per process, like ``api.auth._login_limiter``. The clock is
injectable so the tests never sleep.
"""

import copy
import json
import threading
import time
from collections import defaultdict, deque
from typing import Callable, Optional

WINDOW_SECONDS = 60.0
FAILED_AUTH_MAX = 10

_clock: Callable[[], float] = time.monotonic
_lock = threading.Lock()
_calls: dict[tuple[int, bool], deque] = defaultdict(deque)
_failures: dict[str, deque] = defaultdict(deque)


def set_clock(clock: Optional[Callable[[], float]]) -> None:
    """Replace the monotonic clock (tests); ``None`` restores the real one."""
    global _clock
    _clock = clock or time.monotonic


def now() -> float:
    return _clock()


def reset_limits() -> None:
    with _lock:
        _calls.clear()
        _failures.clear()


def check_rate(token_id: int, write: bool, per_min: int) -> tuple[bool, float]:
    """Record one call for ``token_id``; return ``(allowed, retry_after_s)``.

    Reads and writes keep separate windows, so a burst of searches cannot starve
    the (much smaller) write budget, and the other way round.
    """
    current = now()
    with _lock:
        window = _calls[(token_id, write)]
        while window and window[0] <= current - WINDOW_SECONDS:
            window.popleft()
        if len(window) >= per_min:
            return False, max(1.0, round(window[0] + WINDOW_SECONDS - current, 1))
        window.append(current)
        return True, 0.0


def auth_blocked(client_ip: str) -> bool:
    """True once ``client_ip`` has failed bearer authentication too often."""
    current = now()
    with _lock:
        window = _failures.get(client_ip)
        if window is None:
            return False
        while window and window[0] <= current - WINDOW_SECONDS:
            window.popleft()
        if not window:
            del _failures[client_ip]
            return False
        return len(window) >= FAILED_AUTH_MAX


def record_auth_failure(client_ip: str) -> None:
    with _lock:
        _failures[client_ip].append(now())


def _encoded_size(envelope: dict) -> int:
    return len(json.dumps(envelope, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8"))


def fit_envelope(envelope: dict, max_rows: int, max_bytes: int) -> dict:
    """Cap a result envelope at ``max_rows`` rows and ``max_bytes`` serialized bytes.

    Tail rows are dropped (never the middle of a row), ``truncated: true`` is set,
    and the output stays valid JSON. ``total`` is left alone so the caller still
    learns how many rows exist. An envelope without a ``data.rows`` list that is
    over the byte cap becomes a ``too_large`` error rather than being cut mid-text.
    """
    data = envelope.get("data")
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(rows, list):
        if _encoded_size(envelope) <= max_bytes:
            return envelope
        return {"ok": False, "error": "too_large",
                "message": "The result exceeds the byte cap; narrow the request."}
    if len(rows) <= max_rows and _encoded_size(envelope) <= max_bytes:
        return envelope
    capped = copy.copy(envelope)
    capped["data"] = dict(data)
    capped["data"]["rows"] = rows[:max_rows]
    capped["truncated"] = True
    while capped["data"]["rows"] and _encoded_size(capped) > max_bytes:
        kept = capped["data"]["rows"]
        capped["data"]["rows"] = kept[:len(kept) // 2 if len(kept) > 8 else len(kept) - 1]
    return capped
