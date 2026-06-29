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
    # Set by the store manager when creating the ticket. True means a
    # return leg is expected (e.g. swap-out scenario where the old asset
    # has to come back). The asset only "closes" once it reaches the
    # RETURNED terminal state.
    requires_return: bool = False


class AssetBulkCreate(BaseModel):
    instance_id: UUID
    group_id: UUID
    tickets: list[str] = Field(..., min_length=1, max_length=500)
    asset_type: str = Field(..., min_length=1, max_length=100)
    requires_return: bool = False


class AssetBulkResult(BaseModel):
    created: list["AssetOut"]
    failed: list[dict]


class AssetUpdate(BaseModel):
    asset_type: str | None = None
    serial_number: str | None = None
    description: str | None = None
    current_location_id: UUID | None = None
    # Allow the store manager to toggle the return-required flag after
    # the fact (e.g. they forgot to tick it at creation time). The asset
    # must not have entered its return leg yet, but we leave that
    # business rule to the endpoint.
    requires_return: bool | None = None
    # if updated_at is provided, used for optimistic concurrency
    updated_at: datetime | None = None


class AssetOut(ORMBase, AssetBase):
    id: UUID
    organization_id: UUID
    instance_id: UUID
    group_id: UUID
    current_location_id: UUID | None = None
    status: AssetStatus
    requires_return: bool = False
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
