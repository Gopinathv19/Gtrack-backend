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
    # The store assigns where the sack starts (origin) and where it
    # should end up (destination) at creation time. Both are optional
    # for backwards compatibility, but the UI strongly nudges users to
    # set them.
    origin_location_id: UUID | None = None
    destination_location_id: UUID | None = None


class SackUpdate(BaseModel):
    sack_code: str | None = None


class SackOriginUpdate(BaseModel):
    """PATCH body for editing a sack's source / origin location.

    Used by the dedicated ``/sacks/{id}/origin`` endpoint which is
    restricted to ORG_ADMIN / STORE_MAINTAINER and allowed even while
    the sack is in transit.
    """

    origin_location_id: UUID | None = None
    remarks: str | None = None


class SackDestinationUpdate(BaseModel):
    """PATCH body for editing a sack's intended drop-off location.

    Used by the dedicated ``/sacks/{id}/destination`` endpoint which is
    restricted to ORG_ADMIN / STORE_MAINTAINER and allowed even while
    the sack is in transit.
    """

    destination_location_id: UUID | None = None
    remarks: str | None = None


class SackOut(ORMBase, SackBase):
    id: UUID
    organization_id: UUID
    group_id: UUID
    status: SackStatus
    created_by: UUID
    origin_location_id: UUID | None = None
    origin_location_name: str | None = None
    destination_location_id: UUID | None = None
    destination_location_name: str | None = None
    # Denormalised display fields populated by the endpoint so the UI doesn't
    # need a second roundtrip just to render "Created by Jane".
    created_by_name: str | None = None
    created_by_email: str | None = None
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
    # Denormalised display fields. These are populated by the endpoint
    # via a single LEFT JOIN; the UI uses them directly so it never has to
    # resolve user / location UUIDs on its own.
    performed_by_name: str | None = None
    performed_by_email: str | None = None
    from_location_id: UUID | None = None
    from_location_name: str | None = None
    to_location_id: UUID | None = None
    to_location_name: str | None = None
    remarks: str | None = None
    created_at: datetime
