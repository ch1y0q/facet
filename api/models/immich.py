"""Read-only administrator diagnostics for the configured Immich integration."""
from typing import Literal

from pydantic import BaseModel


class ImmichDiagnosticsResponse(BaseModel):
    configured: bool
    mapping_rules: int
    sample_limit: int
    sampled_photos: int
    mapped_photos: int
    last_push_at: str | None
    connection: Literal['not_checked', 'not_configured', 'invalid_config', 'connected',
                        'access_denied', 'unreachable', 'invalid_response']
    version: str | None
    stack_version_supported: bool | None
