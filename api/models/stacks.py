"""Explicit stack requests and revisioned organization responses."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.models.gallery import gallery_filter_keys


class StackMember(BaseModel):
    preview_revision: str | None = None
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


class StackSuggestionsRequest(BaseModel):
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator('filters')
    @classmethod
    def known_filters(cls, value):
        if value.keys() - gallery_filter_keys():
            raise ValueError('Unknown gallery filter')
        return value


class StackSuggestion(BaseModel):
    key: str
    kind: Literal['duplicate', 'burst']
    paths: list[str]
    cover_path: str


class StackSuggestionsResponse(BaseModel):
    suggestions: list[StackSuggestion]
