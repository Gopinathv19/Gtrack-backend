"""Sack schemas."""
from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.common import ORMBase
from app.models.enums import SackStatus, SackMovementAction


class SackLifecycle(str, Enum):
    """Derived "ticket-level" lifecycle for a sack.

    Distinct from ``SackStatus`` which only tracks the *current leg*
    (CREATED/IN_TRANSIT/DELIVERED/RECEIVED). Lifecycle answers the wider
    question "is the work for this sack actually done?" — which depends
    on whether any of the assets in it still need to come back.

    - ACTIVE          → forward leg is in progress (sack not yet RECEIVED).
    - PENDING_RETURN  → forward leg done, but at least one asset is
                        flagged ``requires_return = True`` and hasn't
                        reached its RETURNED terminal yet.
    - CLOSED          → every ticket has reached its terminal state.
    """

    ACTIVE = "ACTIVE"
    PENDING_RETURN = "PENDING_RETURN"
    CLOSED = "CLOSED"


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
    # Derived lifecycle (ACTIVE / PENDING_RETURN / CLOSED). Computed
    # server-side from the sack status + the ``requires_return`` /
    # ``status`` of each contained asset, so the UI can filter without
    # needing to fetch all assets.
    lifecycle: SackLifecycle = SackLifecycle.ACTIVE
    created_by: UUID
    origin_location_id: UUID | None = None
    origin_location_name: str | None = None
    destination_location_id: UUID | None = None
    destination_location_name: str | None = None
    # Denormalised display fields populated by the endpoint so the UI doesn't
    # need a second roundtrip just to render "Created by Jane".
    created_by_name: str | None = None
    created_by_email: str | None = None
    # Counts used by the lifecycle UI to explain *why* a sack is
    # PENDING_RETURN ("3 of 5 assets still to return") without an extra
    # round-trip.
    asset_count: int = 0
    pending_return_count: int = 0
    created_at: datetime
    updated_at: datetime


class ReturnAssetActionRequest(BaseModel):
    """Body for one of the per-asset reverse-leg actions.

    The reverse leg is modelled as three discrete steps on the *same*
    sack the asset originally shipped on:

      1. ``POST .../mark-return``   — sysadmin marks the asset
         PACKED_FOR_RETURN once they've confirmed it's coming back.
      2. ``POST .../pickup-return`` — shift person picks it up; the
         asset moves to IN_TRANSIT and the asset's
         ``current_location_id`` snaps to the sack origin (or the
         override below).
      3. ``POST .../receive-return`` — store manager confirms the
         asset is back; the asset moves to its terminal RETURNED state.

    ``location_id`` is optional. When omitted, each step falls back to
    the sack's ``origin_location_id`` (i.e. "back to the store"), which
    is what the timeline + asset.current_location_id should reflect for
    the common case.
    """

    location_id: UUID | None = None
    remarks: str | None = None


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
