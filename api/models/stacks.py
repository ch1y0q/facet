"""Explicit stack requests and revisioned organization responses."""
from pydantic import BaseModel, Field


class StackMember(BaseModel):
    path: str
    position: int


class PhotoStack(BaseModel):
    id: str
    revision: int
    cover_path: str
    members: list[StackMember]
    editable: bool


class CreateStack(BaseModel):
    paths: list[str] = Field(min_length=2, max_length=1000)
    cover_path: str


class UpdateStack(BaseModel):
    paths: list[str] = Field(max_length=1000)
    cover_path: str | None = None
    expected_revision: int = Field(gt=0)


class StackUndo(BaseModel):
    entry_id: int


class StackMutation(BaseModel):
    stack: PhotoStack | None
    undo: StackUndo | None
