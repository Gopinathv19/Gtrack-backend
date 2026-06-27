"""Sack schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.common import ORMBase
from app.models.enums import SackStatus, SackMovementAction


class SackBase(BaseModel):
    sack_code: str = Field(..., min_length=1, max_length=64)


class SackCreate(SackBase):
    group_id: UUID


class SackUpdate(BaseModel):
    sack_code: str | None = None


class SackOut(ORMBase, SackBase):
    id: UUID
    organization_id: UUID
    group_id: UUID
    status: SackStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class SackAssetsAdd(BaseModel):
    asset_ids: list[UUID] = Field(..., min_length=1)


class SackAssetsAddResult(BaseModel):
    sack_id: UUID
    added: list[UUID]
    skipped: list[dict]


class SackActionRequest(BaseModel):
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    remarks: str | None = None


class SackMovementOut(ORMBase):
    id: UUID
    sack_id: UUID
    action: SackMovementAction
    performed_by: UUID
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    remarks: str | None = None
    created_at: datetime
