"""Request/response models for the in-page agent routes (``/api/mcp/inpage_tools``, ``/api/mcp/call``)."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class McpInpageAnnotations(BaseModel):
    readOnlyHint: bool
    consequentialHint: bool
    untrustedContentHint: bool


class McpInpageTool(BaseModel):
    name: str
    description: str
    inputSchema: dict[str, Any] = Field(description="JSON Schema of the arguments; `show` and `tab_id` are stripped.")
    annotations: McpInpageAnnotations
    required_level: Literal["readonly", "user", "edition"] = Field(
        description="The level the session needs to call the tool (single-password installs have no `user` rung).")


class McpInpageTools(BaseModel):
    level: Literal["readonly", "user", "edition"] = Field(description="The session's level right now.")
    tools: list[McpInpageTool]


class McpCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    selection_snapshot: Optional[dict[str, Any]] = Field(
        default=None, description="The calling tab's `ui_get_selection` data; read by `target: \"selection\"`.")


class McpCallResponse(BaseModel):
    """A tool's result envelope; failures are `ok: false` with an `error` code, never an HTTP error."""

    model_config = ConfigDict(extra="allow")

    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None
    changed: Optional[int] = Field(default=None, description="Photos a write changed (0 for a dry run).")
