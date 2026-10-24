"""Manual face editing contracts; coordinates refer to canonical analysis pixels."""
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Box = tuple[Fraction, Fraction, Fraction, Fraction]


class ManualFaceRegion(BaseModel):
    id: int
    manual_key: str
    bbox: Box
    person_id: int | None
    person_name: str | None
    source_changed: bool


class ManualFacesResponse(BaseModel):
    regions: list[ManualFaceRegion]


class ManualFaceFrame(BaseModel):
    image_base64: str
    width: int
    height: int
    frame_token: str


class ManualFaceWrite(BaseModel):
    path: str
    frame_token: str
    bbox: Box
    person_id: int | None = None
    new_person_name: str | None = None

    @field_validator('new_person_name')
    @classmethod
    def name(cls, value):
        if value is not None:
            value = value.strip()
            if not 1 <= len(value) <= 120:
                raise ValueError('Name must contain 1 to 120 characters')
        return value

    @model_validator(mode='after')
    def valid_target_and_box(self):
        if (self.person_id is None) == (self.new_person_name is None):
            raise ValueError('Choose one existing person or a new name')
        x1, y1, x2, y2 = self.bbox
        if x1 >= x2 or y1 >= y2:
            raise ValueError('Rectangle must have positive area')
        return self


class ManualFaceCreate(ManualFaceWrite):
    client_id: UUID


class ManualFaceDelete(BaseModel):
    success: bool
