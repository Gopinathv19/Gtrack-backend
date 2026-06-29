"""Asset endpoints + asset movements."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models import (
    Asset,
    AssetMovement,
    Group,
    Instance,
    Location,
    User,
)
from app.models.enums import (
    AssetMovementAction,
    AssetStatus,
    RoleName,
)
from app.schemas.asset import (
    AssetBulkCreate,
    AssetBulkResult,
    AssetCreate,
    AssetMovementCreate,
    AssetMovementOut,
    AssetOut,
    AssetUpdate,
)
from app.schemas.common import Page
from app.services.state_machine import validate_asset_transition

router = APIRouter(prefix="/assets", tags=["assets"])


def _validate_group(db: Session, group_id: UUID, instance_id: UUID, user: User) -> None:
    g = db.get(Group, group_id)
    if not g or g.instance_id != instance_id:
        raise HTTPException(404, "Group not found in instance")
    inst = db.get(Instance, instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Instance not found")


@router.post("", response_model=AssetOut, status_code=201)
def create_asset(
    payload: AssetCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    _validate_group(db, payload.group_id, payload.instance_id, me)
    if payload.current_location_id:
        loc = db.get(Location, payload.current_location_id)
        if not loc or loc.group_id != payload.group_id:
            raise HTTPException(400, "Location not in given group")

    asset = Asset(
        ticket_id=payload.ticket_id,
        asset_type=payload.asset_type,
        serial_number=payload.serial_number,
        description=payload.description,
        organization_id=me.organization_id,
        instance_id=payload.instance_id,
        group_id=payload.group_id,
        current_location_id=payload.current_location_id,
        created_by=me.id,
        status=AssetStatus.CREATED,
        requires_return=payload.requires_return,
    )
    try:
        db.add(asset)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ticket ID already exists")
    db.refresh(asset)

    db.add(
        AssetMovement(
            asset_id=asset.id,
            action=AssetMovementAction.CREATED,
            performed_by=me.id,
            to_location_id=asset.current_location_id,
        )
    )
    db.commit()
    return asset


@router.post("/bulk", response_model=AssetBulkResult, status_code=207)
def bulk_create_assets(
    payload: AssetBulkCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    _validate_group(db, payload.group_id, payload.instance_id, me)
    created: list[Asset] = []
    failed: list[dict] = []
    for tid in payload.tickets:
        if len(tid) != 6:
            failed.append({"ticket_id": tid, "error": "ticket must be 6 chars"})
            continue
        try:
            asset = Asset(
                ticket_id=tid,
                asset_type=payload.asset_type,
                organization_id=me.organization_id,
                instance_id=payload.instance_id,
                group_id=payload.group_id,
                created_by=me.id,
                status=AssetStatus.CREATED,
                requires_return=payload.requires_return,
            )
            db.add(asset)
            db.flush()
            db.add(
                AssetMovement(
                    asset_id=asset.id,
                    action=AssetMovementAction.CREATED,
                    performed_by=me.id,
                )
            )
            created.append(asset)
        except IntegrityError:
            db.rollback()
            failed.append({"ticket_id": tid, "error": "duplicate"})
    db.commit()
    return AssetBulkResult(
        created=[AssetOut.model_validate(a) for a in created], failed=failed
    )


@router.get("", response_model=Page[AssetOut])
def list_assets(
    status_filter: AssetStatus | None = Query(default=None, alias="status"),
    group_id: UUID | None = Query(default=None),
    instance_id: UUID | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = db.query(Asset).filter(Asset.organization_id == me.organization_id)
    if status_filter:
        q = q.filter(Asset.status == status_filter)
    if group_id:
        q = q.filter(Asset.group_id == group_id)
    if instance_id:
        q = q.filter(Asset.instance_id == instance_id)
    if asset_type:
        q = q.filter(Asset.asset_type == asset_type)
    sort_col = getattr(Asset, sort, Asset.created_at)
    q = q.order_by(sort_col.desc() if order.lower() == "desc" else sort_col.asc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != me.organization_id:
        raise HTTPException(404, "Asset not found")
    return asset


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: UUID,
    payload: AssetUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != me.organization_id:
        raise HTTPException(404, "Asset not found")

    # Optimistic concurrency via updated_at, if client sent it
    if payload.updated_at and asset.updated_at != payload.updated_at:
        raise HTTPException(409, "Asset modified by another user (stale updated_at)")

    data = payload.model_dump(exclude_unset=True, exclude={"updated_at"})
    for k, v in data.items():
        setattr(asset, k, v)
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != me.organization_id:
        raise HTTPException(404, "Asset not found")
    db.delete(asset)
    db.commit()
    return None


# ---------- Asset movements ----------
@router.post(
    "/{asset_id}/movements",
    response_model=AssetMovementOut,
    status_code=201,
)
def create_asset_movement(
    asset_id: UUID,
    payload: AssetMovementCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != me.organization_id:
        raise HTTPException(404, "Asset not found")

    # Map action -> resulting status, validate transitions
    action_to_status: dict[AssetMovementAction, AssetStatus | None] = {
        AssetMovementAction.PACKED: AssetStatus.PACKED,
        AssetMovementAction.UNPACKED: AssetStatus.CREATED,
        AssetMovementAction.PICKED_UP: AssetStatus.IN_TRANSIT,
        AssetMovementAction.IN_TRANSIT: AssetStatus.IN_TRANSIT,
        AssetMovementAction.DELIVERED: AssetStatus.DELIVERED,
        AssetMovementAction.RECEIVED: AssetStatus.RECEIVED,
        AssetMovementAction.DAMAGED: AssetStatus.DAMAGED,
        AssetMovementAction.LOST: AssetStatus.LOST,
        AssetMovementAction.CREATED: None,
    }
    target = action_to_status.get(payload.action)
    if target and target != asset.status:
        validate_asset_transition(asset.status, target)
        asset.status = target

    if payload.to_location_id:
        asset.current_location_id = payload.to_location_id

    mv = AssetMovement(
        asset_id=asset.id,
        action=payload.action,
        performed_by=me.id,
        from_location_id=payload.from_location_id,
        to_location_id=payload.to_location_id,
        remarks=payload.remarks,
    )
    db.add(mv)
    db.commit()
    db.refresh(mv)
    return mv


@router.get("/{asset_id}/movements", response_model=list[AssetMovementOut])
def list_asset_movements(
    asset_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != me.organization_id:
        raise HTTPException(404, "Asset not found")
    return (
        db.query(AssetMovement)
        .filter(AssetMovement.asset_id == asset_id)
        .order_by(AssetMovement.created_at.desc())
        .all()
    )
