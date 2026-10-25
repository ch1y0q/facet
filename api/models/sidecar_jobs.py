"""Private progress receipts for a bounded sidecar export."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
