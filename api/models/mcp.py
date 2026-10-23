"""Request/response models for the agent token routes."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

TokenLevel = Literal['readonly', 'user', 'edition']


class McpTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    level: TokenLevel = 'readonly'

    @field_validator('name')
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('name must not be blank')
        return value


class McpTokenItem(BaseModel):
    """Token metadata. Never carries the secret or its hash.

    ``revoked`` is int-typed because SQLite has no boolean: the wire carries 0/1.
    """

    id: int
    user_id: str
    name: str
    token_prefix: str
    level: TokenLevel
    created_at: str
    last_used_at: Optional[str] = None
    revoked: int
    revoked_at: Optional[str] = None


class McpTokenCreated(McpTokenItem):
    """The one response that carries the plaintext token."""

    token: str


class McpTokenList(BaseModel):
    tokens: list[McpTokenItem]


class McpTokenRevoked(BaseModel):
    ok: bool
    id: int
