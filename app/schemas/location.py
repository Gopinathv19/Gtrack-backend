"""Location schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class LocationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    description: str | None = None


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = None
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    description: str | None = None


class LocationOut(ORMBase, LocationBase):
    id: UUID
    group_id: UUID
    created_at: datetime
    updated_at: datetime
