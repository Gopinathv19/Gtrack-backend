"""Sack endpoints + sack movements."""
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
    Sack,
    SackAsset,
    SackMovement,
    User,
)
from app.models.enums import (
    AssetMovementAction,
    AssetStatus,
    RoleName,
    SackMovementAction,
    SackStatus,
)
from app.schemas.common import Page
from app.schemas.sack import (
    SackActionRequest,
    SackAssetsAdd,
    SackAssetsAddResult,
    SackCreate,
    SackMovementOut,
    SackOut,
    SackUpdate,
)
from app.services.state_machine import (
    validate_asset_transition,
    validate_sack_transition,
)

router = APIRouter(prefix="/sacks", tags=["sacks"])


def _get_sack(db: Session, sack_id: UUID, me: User) -> Sack:
    s = db.get(Sack, sack_id)
    if not s or s.organization_id != me.organization_id:
        raise HTTPException(404, "Sack not found")
    return s


# ---------- CRUD ----------
@router.post("", response_model=SackOut, status_code=201)
def create_sack(
    payload: SackCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    g = db.get(Group, payload.group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    inst = db.get(Instance, g.instance_id)
    if not inst or inst.organization_id != me.organization_id:
        raise HTTPException(404, "Group not found")
    sack = Sack(
        sack_code=payload.sack_code,
        organization_id=me.organization_id,
        group_id=payload.group_id,
        created_by=me.id,
        status=SackStatus.CREATED,
    )
    try:
        db.add(sack)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Sack code already exists")
    db.refresh(sack)
    db.add(
        SackMovement(
            sack_id=sack.id,
            action=SackMovementAction.CREATED,
            performed_by=me.id,
        )
    )
    db.commit()
    return sack


@router.get("", response_model=Page[SackOut])
def list_sacks(
    status_filter: SackStatus | None = Query(None, alias="status"),
    group_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = db.query(Sack).filter(Sack.organization_id == me.organization_id)
    if status_filter:
        q = q.filter(Sack.status == status_filter)
    if group_id:
        q = q.filter(Sack.group_id == group_id)
    q = q.order_by(Sack.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.get("/{sack_id}", response_model=SackOut)
def get_sack(
    sack_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return _get_sack(db, sack_id, me)


@router.patch("/{sack_id}", response_model=SackOut)
def update_sack(
    sack_id: UUID,
    payload: SackUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    s = _get_sack(db, sack_id, me)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{sack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sack(
    sack_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    s = _get_sack(db, sack_id, me)
    db.delete(s)
    db.commit()
    return None


# ---------- Assets in sack ----------
@router.post("/{sack_id}/assets", response_model=SackAssetsAddResult)
def add_assets_to_sack(
    sack_id: UUID,
    payload: SackAssetsAdd,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    sack = _get_sack(db, sack_id, me)
    if sack.status != SackStatus.CREATED:
        raise HTTPException(400, "Cannot add to a sack that is not in CREATED state")

    added: list[UUID] = []
    skipped: list[dict] = []
    for asset_id in payload.asset_ids:
        asset = db.get(Asset, asset_id)
        if not asset or asset.organization_id != me.organization_id:
            skipped.append({"asset_id": str(asset_id), "reason": "not found"})
            continue
        if asset.status != AssetStatus.CREATED:
            skipped.append(
                {"asset_id": str(asset_id), "reason": f"status is {asset.status.value}"}
            )
            continue
        existing = (
            db.query(SackAsset)
            .filter(SackAsset.asset_id == asset_id)
            .first()
        )
        if existing:
            skipped.append({"asset_id": str(asset_id), "reason": "already in a sack"})
            continue
        validate_asset_transition(asset.status, AssetStatus.PACKED)
        asset.status = AssetStatus.PACKED
        db.add(SackAsset(sack_id=sack.id, asset_id=asset.id, packed_by=me.id))
        db.add(
            AssetMovement(
                asset_id=asset.id,
                sack_id=sack.id,
                action=AssetMovementAction.PACKED,
                performed_by=me.id,
            )
        )
        added.append(asset.id)
    db.commit()
    return SackAssetsAddResult(sack_id=sack.id, added=added, skipped=skipped)


@router.delete(
    "/{sack_id}/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_asset_from_sack(
    sack_id: UUID,
    asset_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)),
):
    sack = _get_sack(db, sack_id, me)
    if sack.status != SackStatus.CREATED:
        raise HTTPException(400, "Sack already in transit or closed")
    sa = (
        db.query(SackAsset)
        .filter(SackAsset.sack_id == sack_id, SackAsset.asset_id == asset_id)
        .one_or_none()
    )
    if not sa:
        raise HTTPException(404, "Asset not in this sack")
    asset = db.get(Asset, asset_id)
    if asset:
        validate_asset_transition(asset.status, AssetStatus.CREATED)
        asset.status = AssetStatus.CREATED
        db.add(
            AssetMovement(
                asset_id=asset.id,
                sack_id=sack.id,
                action=AssetMovementAction.UNPACKED,
                performed_by=me.id,
            )
        )
    db.delete(sa)
    db.commit()
    return None


# ---------- Lifecycle actions ----------
def _transition_sack(
    db: Session,
    sack: Sack,
    new_status: SackStatus,
    action: SackMovementAction,
    asset_status: AssetStatus | None,
    asset_action: AssetMovementAction | None,
    me: User,
    payload: SackActionRequest,
) -> Sack:
    validate_sack_transition(sack.status, new_status)
    sack.status = new_status
    db.add(
        SackMovement(
            sack_id=sack.id,
            action=action,
            performed_by=me.id,
            from_location_id=payload.from_location_id,
            to_location_id=payload.to_location_id,
            remarks=payload.remarks,
        )
    )

    if asset_status and asset_action:
        sack_assets = db.query(SackAsset).filter(SackAsset.sack_id == sack.id).all()
        for sa in sack_assets:
            asset = db.get(Asset, sa.asset_id)
            if not asset:
                continue
            try:
                validate_asset_transition(asset.status, asset_status)
            except HTTPException:
                # skip already-DELIVERED etc.
                continue
            asset.status = asset_status
            if payload.to_location_id and asset_status in (
                AssetStatus.DELIVERED,
                AssetStatus.RECEIVED,
            ):
                asset.current_location_id = payload.to_location_id
            db.add(
                AssetMovement(
                    asset_id=asset.id,
                    sack_id=sack.id,
                    action=asset_action,
                    performed_by=me.id,
                    from_location_id=payload.from_location_id,
                    to_location_id=payload.to_location_id,
                    remarks=payload.remarks,
                )
            )
    db.commit()
    db.refresh(sack)
    return sack


@router.put("/{sack_id}/pickup", response_model=SackOut)
def pickup_sack(
    sack_id: UUID,
    payload: SackActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.SHIFT_PERSON, RoleName.ORG_ADMIN)),
):
    sack = _get_sack(db, sack_id, me)
    return _transition_sack(
        db, sack,
        SackStatus.PICKED_UP, SackMovementAction.PICKED_UP,
        AssetStatus.IN_TRANSIT, AssetMovementAction.PICKED_UP,
        me, payload,
    )


@router.put("/{sack_id}/deliver", response_model=SackOut)
def deliver_sack(
    sack_id: UUID,
    payload: SackActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.SHIFT_PERSON, RoleName.ORG_ADMIN)),
):
    sack = _get_sack(db, sack_id, me)
    return _transition_sack(
        db, sack,
        SackStatus.DELIVERED, SackMovementAction.DELIVERED,
        AssetStatus.DELIVERED, AssetMovementAction.DELIVERED,
        me, payload,
    )


@router.put("/{sack_id}/close", response_model=SackOut)
def close_sack(
    sack_id: UUID,
    payload: SackActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN, RoleName.SYSADMIN)),
):
    sack = _get_sack(db, sack_id, me)
    return _transition_sack(
        db, sack,
        SackStatus.CLOSED, SackMovementAction.CLOSED,
        AssetStatus.RECEIVED, AssetMovementAction.RECEIVED,
        me, payload,
    )


@router.get("/{sack_id}/movements", response_model=list[SackMovementOut])
def list_sack_movements(
    sack_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    _get_sack(db, sack_id, me)
    return (
        db.query(SackMovement)
        .filter(SackMovement.sack_id == sack_id)
        .order_by(SackMovement.created_at.desc())
        .all()
    )
