"""Asset schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.common import ORMBase
from app.models.enums import AssetStatus, AssetMovementAction


class AssetBase(BaseModel):
    ticket_id: str = Field(..., min_length=6, max_length=6, pattern=r"^[A-Za-z0-9]{6}$")
    asset_type: str = Field(..., min_length=1, max_length=100)
    serial_number: str | None = None
    description: str | None = None


class AssetCreate(AssetBase):
    instance_id: UUID
    group_id: UUID
    current_location_id: UUID | None = None


class AssetBulkCreate(BaseModel):
    instance_id: UUID
    group_id: UUID
    tickets: list[str] = Field(..., min_length=1, max_length=500)
    asset_type: str = Field(..., min_length=1, max_length=100)


class AssetBulkResult(BaseModel):
    created: list["AssetOut"]
    failed: list[dict]


class AssetUpdate(BaseModel):
    asset_type: str | None = None
    serial_number: str | None = None
    description: str | None = None
    current_location_id: UUID | None = None
    # if updated_at is provided, used for optimistic concurrency
    updated_at: datetime | None = None


class AssetOut(ORMBase, AssetBase):
    id: UUID
    organization_id: UUID
    instance_id: UUID
    group_id: UUID
    current_location_id: UUID | None = None
    status: AssetStatus
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class AssetMovementCreate(BaseModel):
    action: AssetMovementAction
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    remarks: str | None = None


class AssetMovementOut(ORMBase):
    id: UUID
    asset_id: UUID
    sack_id: UUID | None = None
    action: AssetMovementAction
    performed_by: UUID
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    remarks: str | None = None
    created_at: datetime


AssetBulkResult.model_rebuild()
