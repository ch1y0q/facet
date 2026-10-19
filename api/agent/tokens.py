"""Agent bearer tokens: mint, verify, list, revoke, and per-call level resolution.

A token is ``fct_`` + 256 bits from the CSPRNG; only its SHA-256 and a short
display prefix are stored (``mcp_tokens``, a side table). Tokens never expire but
are revocable, and they are bound to the credentials of their owner at mint time:

* multi-user -- ``user_gen`` digests the user's ``password_hash`` (the role is live);
* single password -- ``user_gen`` is the viewer-password generation and
  ``edition_gen`` the edition-password generation (``api.auth.password_generation``);
* open install -- the principal is the fixed ``_anonymous`` and the token is
  read-only for good.

``TokenGrant.resolve`` re-derives the EFFECTIVE level on EVERY call as
``min(token.level, live level)``. The internal JWT is minted fresh with CURRENT
generation claims, so without this comparison a rotated password would silently
re-bless an old token.
"""

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from api.auth import (
    EDITION_PASSWORD_KEY, VIEWER_PASSWORD_KEY, _is_open_install, password_generation,
)
from api.config import config_load_failed, get_user_config, is_multi_user_enabled
from api.database import get_db
from api.db_helpers import retry_on_locked

TOKEN_PREFIX = "fct_"
DISPLAY_PREFIX_LENGTH = 12
MAX_TOKEN_LENGTH = 200
MAX_LIVE_TOKENS_PER_USER = 20
TOUCH_INTERVAL_SECONDS = 60.0
LEVELS = ("readonly", "user", "edition")
OPEN_PRINCIPAL = "_anonymous"
LEGACY_PRINCIPAL = "_legacy"
GENERATION_LENGTH = 16

PUBLIC_COLUMNS = ("id", "user_id", "name", "token_prefix", "level", "created_at",
                  "last_used_at", "revoked", "revoked_at")

_last_touched: dict[int, float] = {}
_touch_lock = threading.Lock()


def level_rank(level: str) -> int:
    return LEVELS.index(level)


def effective_requirement(min_level: str) -> str:
    """The level a caller really needs for a tool declared at ``min_level``.

    ``user`` is a multi-user rung: single-password mode has no middle rung (the rating
    routes demand edition there), so the honest requirement is ``edition``.
    """
    return "edition" if min_level == "user" and install_mode() != "multi" else min_level


def _lower(a: str, b: str) -> str:
    return a if level_rank(a) <= level_rank(b) else b


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def install_mode() -> str:
    """``multi`` | ``legacy`` | ``open`` | ``unreadable`` (config failed to parse)."""
    if config_load_failed():
        return "unreadable"
    if is_multi_user_enabled():
        return "multi"
    if _is_open_install(VIEWER_PASSWORD_KEY):
        return "open"
    return "legacy"


def user_generation(user: dict) -> str:
    """Digest of the stored password hash: a changed password kills the token.

    The role is deliberately NOT in it. It is re-read live on every call
    (``_resolve_multi``), so a demotion LOWERS an edition token to ``user`` instead
    of killing it, and a promotion can never raise one past its minted level.
    """
    return hashlib.sha256(str(user.get("password_hash", "")).encode("utf-8")).hexdigest()[:GENERATION_LENGTH]


def snapshot(principal: str) -> tuple[str, str]:
    """``(user_gen, edition_gen)`` for ``principal`` against the live config."""
    mode = install_mode()
    if mode == "multi":
        user = get_user_config(principal)
        if user is None:
            raise ValueError(f"unknown user {principal!r}")
        return user_generation(user), ""
    if mode == "legacy":
        return password_generation(VIEWER_PASSWORD_KEY), password_generation(EDITION_PASSWORD_KEY)
    return password_generation(VIEWER_PASSWORD_KEY), ""


def _public(row: sqlite3.Row) -> dict:
    return {column: row[column] for column in PUBLIC_COLUMNS}


@retry_on_locked()
def mint(principal: str, name: str, level: str) -> tuple[dict, str]:
    """Create a token; return ``(public row, plaintext)``. The plaintext is never stored."""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    user_gen, edition_gen = snapshot(principal)
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO mcp_tokens (user_id, name, token_prefix, token_hash, level, user_gen, "
            "edition_gen, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (principal, name, plaintext[:DISPLAY_PREFIX_LENGTH], _hash(plaintext), level,
             user_gen, edition_gen, _now_iso()))
        conn.commit()
        row = conn.execute("SELECT * FROM mcp_tokens WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _public(row), plaintext


def verify(plaintext: Optional[str]) -> Optional["TokenGrant"]:
    """The grant behind ``plaintext``, or None when unknown, malformed or revoked.

    Liveness against the owner's credentials is NOT decided here -- that is
    :meth:`TokenGrant.resolve`, which runs on every call.
    """
    if not isinstance(plaintext, str) or not plaintext.startswith(TOKEN_PREFIX) \
            or len(plaintext) > MAX_TOKEN_LENGTH:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, name, level, user_gen, edition_gen FROM mcp_tokens "
            "WHERE token_hash = ? AND revoked = 0", (_hash(plaintext),)).fetchone()
    if row is None:
        return None
    return TokenGrant(row["id"], row["user_id"], row["name"], row["level"],
                      row["user_gen"], row["edition_gen"])


def list_tokens(user_id: Optional[str] = None) -> list[dict]:
    """Token metadata (never the hash), newest first; ``user_id=None`` lists every owner's."""
    sql = "SELECT * FROM mcp_tokens"
    params: tuple = ()
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params = (user_id,)
    with get_db() as conn:
        return [_public(r) for r in conn.execute(sql + " ORDER BY id DESC", params)]


def count_live(user_id: str) -> int:
    with get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM mcp_tokens WHERE user_id = ? AND revoked = 0", (user_id,)
        ).fetchone()[0]


@retry_on_locked()
def revoke(token_id: int, user_id: Optional[str] = None) -> bool:
    """Revoke a live token (only ``user_id``'s when given). False when nothing changed."""
    sql = "UPDATE mcp_tokens SET revoked = 1, revoked_at = ? WHERE id = ? AND revoked = 0"
    params: list = [_now_iso(), token_id]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    with get_db() as conn:
        changed = conn.execute(sql, params).rowcount > 0
        conn.commit()
        return changed


@retry_on_locked()
def touch(token_id: int) -> None:
    """Stamp ``last_used_at``, at most once per minute per token."""
    current = time.monotonic()
    with _touch_lock:
        if current - _last_touched.get(token_id, -TOUCH_INTERVAL_SECONDS) < TOUCH_INTERVAL_SECONDS:
            return
        _last_touched[token_id] = current
    with get_db() as conn:
        conn.execute("UPDATE mcp_tokens SET last_used_at = ? WHERE id = ?", (_now_iso(), token_id))
        conn.commit()


@dataclass(frozen=True)
class ResolvedGrant:
    """What a token may do RIGHT NOW."""

    token_id: int
    principal: str
    level: str
    role: str
    display_name: str
    anonymous: bool

    def jwt_claims(self) -> Optional[dict]:
        """Claims for the 60-second internal JWT, or None on an open install.

        Role and ``edition`` MATCH the effective level: ``CurrentUser.is_edition``
        is derived from the ROLE, so a read-only token of an admin must not carry
        ``admin`` through, or it would reach edition routes on the role alone.
        """
        if self.anonymous:
            return None
        return {
            "sub": self.principal,
            "role": self.role,
            "display_name": self.display_name,
            "edition": self.level == "edition",
            "mcp": True,
            "mcp_token_id": self.token_id,
        }


@dataclass(frozen=True)
class TokenGrant:
    id: int
    user_id: str
    name: str
    level: str
    user_gen: str
    edition_gen: str

    def resolve(self) -> Optional[ResolvedGrant]:
        """Effective grant against the live config, or None when the token is dead."""
        mode = install_mode()
        if mode == "unreadable":
            return None
        if mode == "multi":
            return self._resolve_multi()
        if self.user_id not in (LEGACY_PRINCIPAL, OPEN_PRINCIPAL):
            return None
        if self.user_gen != password_generation(VIEWER_PASSWORD_KEY):
            return None
        if mode == "open":
            if self.user_id != OPEN_PRINCIPAL:
                return None
            return ResolvedGrant(self.id, OPEN_PRINCIPAL, "readonly", "user", "", True)
        if self.user_id != LEGACY_PRINCIPAL:
            return None
        edition_live = (
            self.level == "edition"
            and not _is_open_install(EDITION_PASSWORD_KEY)
            and self.edition_gen == password_generation(EDITION_PASSWORD_KEY)
        )
        # Single-password mode has no middle rung: the rating routes demand edition.
        level = "edition" if edition_live else "readonly"
        return ResolvedGrant(self.id, LEGACY_PRINCIPAL, level, "user", "", False)

    def _resolve_multi(self) -> Optional[ResolvedGrant]:
        user = get_user_config(self.user_id)
        if user is None or self.user_gen != user_generation(user):
            return None
        role = user.get("role", "user")
        live = "edition" if role in ("admin", "superadmin") else "user"
        level = _lower(self.level, live)
        return ResolvedGrant(
            self.id, self.user_id, level, role if level == "edition" else "user",
            user.get("display_name", self.user_id), False)
