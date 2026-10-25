"""Private progress receipts for a bounded sidecar export."""
import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SidecarJobStatus(BaseModel):
    id: str
    state: Literal['running', 'completed', 'cancelled', 'failed', 'interrupted']
    started_at: float
    total: int = Field(ge=0, le=10000)
    processed: int = Field(ge=0, le=10000)
    written: int = Field(ge=0, le=10000)
    skipped: int = Field(ge=0, le=10000)
    errors: int = Field(ge=0, le=10000)
    first_error: str | None = None
    cancel_requested: bool = False


    @model_validator(mode='after')
    def consistent_counts(self):
        if self.processed > self.total or self.written + self.skipped + self.errors != self.processed:
            raise ValueError('Export progress counts are inconsistent')
        return self


class SidecarJobRecord(SidecarJobStatus):
    """On-disk worker state; validate before ordering or doing retry arithmetic."""
    model_config = ConfigDict(strict=True)

    owner: str | None
    retry: list[int] = Field(max_length=10000)

    @model_validator(mode='after')
    def valid_private_record(self):
        if str(UUID(self.id)) != self.id or not math.isfinite(self.started_at):
            raise ValueError('Invalid export receipt identity/timestamp')
        if (any(index < 0 or index >= self.processed for index in self.retry)
                or len(set(self.retry)) != len(self.retry)
                or len(self.retry) != self.skipped + self.errors):
            raise ValueError('Invalid export retry indices')
        return self


class SidecarJobPlan(BaseModel):
    """Immutable private selection, written by the admitted worker."""
    model_config = ConfigDict(strict=True)

    owner: str | None
    paths: list[str] = Field(max_length=10000)
    overwrite: bool
