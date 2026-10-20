"""Request/response models for the agent undo-journal routes (the Connect dialog's recent actions)."""

from typing import Optional

from pydantic import BaseModel, Field


class AgentActionBatch(BaseModel):
    """One tool call's worth of journaled changes."""

    batch_id: str
    tool: str
    source: str = Field(description="'mcp' (a token), 'inpage' (the in-page assistant) or 'dialog'.")
    token_name: Optional[str] = Field(default=None, description="The token's name, or the in-page actor.")
    created_at: str
    rows: int = Field(description="Journaled field changes in the batch.")
    undone: bool
    fields: list[str]


class AgentActionList(BaseModel):
    actions: list[AgentActionBatch]


class AgentUndoRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=64)


class AgentUndoItem(BaseModel):
    target: str
    field: str
    outcome: str = Field(description="restored | skipped_changed_since | missing | skipped_level | error")


class AgentUndoResult(BaseModel):
    batch_id: str
    outcomes: dict[str, int] = Field(description="Count of targets per outcome.")
    results: list[AgentUndoItem] = Field(description="At most 200 targets; see `results_count`.")
    results_count: int
