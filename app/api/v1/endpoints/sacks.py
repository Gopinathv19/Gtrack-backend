"""Sack endpoints + sack movements."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_current_user, get_db, require_roles
from app.models import (
    Asset,
    AssetMovement,
    Group,
    Instance,
    Location,
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
from app.schemas.asset import AssetOut
from app.schemas.common import Page
from app.schemas.sack import (
    SackActionRequest,
    SackAssetsAdd,
    SackAssetsAddResult,
    SackCreate,
    SackDestinationUpdate,
    SackMovementOut,
    SackOriginUpdate,
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


def _sack_to_out(db: Session, sack: Sack) -> dict:
    """Serialize a sack with denormalised "created by" + destination data.

    Returning a dict (rather than a SackOut) keeps FastAPI's response model
    validation in charge of the actual shape while letting us slot in the
    name/email lookup as a single tiny query.
    """
    creator = db.get(User, sack.created_by) if sack.created_by else None
    origin = (
        db.get(Location, sack.origin_location_id)
        if sack.origin_location_id
        else None
    )
    dest = (
        db.get(Location, sack.destination_location_id)
        if sack.destination_location_id
        else None
    )
    return {
        "id": sack.id,
        "sack_code": sack.sack_code,
        "organization_id": sack.organization_id,
        "group_id": sack.group_id,
        "status": sack.status,
        "created_by": sack.created_by,
        "origin_location_id": sack.origin_location_id,
        "origin_location_name": origin.name if origin else None,
        "destination_location_id": sack.destination_location_id,
        "destination_location_name": dest.name if dest else None,
        "created_by_name": creator.name if creator else None,
        "created_by_email": creator.email if creator else None,
        "created_at": sack.created_at,
        "updated_at": sack.updated_at,
    }


def _ensure_location_in_tenant(
    db: Session, location_id: UUID, me: User
) -> Location:
    """Verify a destination location belongs to the caller's organization.

    The lookup walks Location → Group → Instance to confirm the location
    is reachable from the user's org. Returns the Location so the caller
    can use its name in the audit-log remark.
    """
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    group = db.get(Group, loc.group_id)
    inst = db.get(Instance, group.instance_id) if group else None
    if not inst or inst.organization_id != me.organization_id:
        raise HTTPException(404, "Location not found")
    return loc


def _enrich_movements(
    db: Session, sack_id: UUID
) -> list[dict]:
    """Load sack movements joined with the performer + from/to locations.

    The frontend renders this list as the lifecycle timeline ("Created by
    Jane → Picked up by Bob at Dock A → ..."), so we resolve the user and
    location names server-side to avoid extra round-trips per row.
    """
    FromLoc = aliased(Location, name="from_loc")
    ToLoc = aliased(Location, name="to_loc")

    rows = (
        db.query(
            SackMovement,
            User.name,
            User.email,
            FromLoc.name,
            ToLoc.name,
        )
        .outerjoin(User, User.id == SackMovement.performed_by)
        .outerjoin(FromLoc, FromLoc.id == SackMovement.from_location_id)
        .outerjoin(ToLoc, ToLoc.id == SackMovement.to_location_id)
        .filter(SackMovement.sack_id == sack_id)
        .order_by(SackMovement.created_at.asc())
        .all()
    )

    out: list[dict] = []
    for m, u_name, u_email, from_name, to_name in rows:
        out.append(
            {
                "id": m.id,
                "sack_id": m.sack_id,
                "action": m.action,
                "performed_by": m.performed_by,
                "performed_by_name": u_name,
                "performed_by_email": u_email,
                "from_location_id": m.from_location_id,
                "from_location_name": from_name,
                "to_location_id": m.to_location_id,
                "to_location_name": to_name,
                "remarks": m.remarks,
                "created_at": m.created_at,
            }
        )
    return out


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
    # Validate origin and destination locations (if provided) belong to
    # this tenant.
    origin_loc: Location | None = None
    if payload.origin_location_id:
        origin_loc = _ensure_location_in_tenant(
            db, payload.origin_location_id, me
        )
    dest_loc: Location | None = None
    if payload.destination_location_id:
        dest_loc = _ensure_location_in_tenant(
            db, payload.destination_location_id, me
        )
    sack = Sack(
        sack_code=payload.sack_code,
        organization_id=me.organization_id,
        group_id=payload.group_id,
        created_by=me.id,
        status=SackStatus.CREATED,
        origin_location_id=payload.origin_location_id,
        destination_location_id=payload.destination_location_id,
    )
    try:
        db.add(sack)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Sack code already exists")
    db.refresh(sack)
    # Record creation; include the assigned origin and destination in
    # the audit trail so the timeline shows "Dock A → Bay 3" right from
    # the start.
    note_parts: list[str] = []
    if origin_loc:
        note_parts.append(f"Origin: {origin_loc.name}")
    if dest_loc:
        note_parts.append(f"Destination: {dest_loc.name}")
    db.add(
        SackMovement(
            sack_id=sack.id,
            action=SackMovementAction.CREATED,
            performed_by=me.id,
            from_location_id=sack.origin_location_id,
            to_location_id=sack.destination_location_id,
            remarks=" · ".join(note_parts) if note_parts else None,
        )
    )
    db.commit()
    return _sack_to_out(db, sack)


@router.get("", response_model=Page[SackOut])
def list_sacks(
    status_filter: SackStatus | None = Query(None, alias="status"),
    group_id: UUID | None = Query(None),
    ticket_id: str | None = Query(
        None,
        description="Find sacks that contain an asset with this ticket id (case-insensitive substring match).",
    ),
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
    if ticket_id:
        # Sacks whose contents include an asset matching this ticket id.
        ticket_q = ticket_id.strip()
        if ticket_q:
            q = (
                q.join(SackAsset, SackAsset.sack_id == Sack.id)
                .join(Asset, Asset.id == SackAsset.asset_id)
                .filter(Asset.ticket_id.ilike(f"%{ticket_q}%"))
                .distinct()
            )
    q = q.order_by(Sack.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(
        items=[_sack_to_out(db, s) for s in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{sack_id}", response_model=SackOut)
def get_sack(
    sack_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return _sack_to_out(db, _get_sack(db, sack_id, me))


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
    return _sack_to_out(db, s)


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
@router.get("/{sack_id}/assets", response_model=list[AssetOut])
def list_sack_assets(
    sack_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Return all assets currently packed into the given sack."""
    _get_sack(db, sack_id, me)
    return (
        db.query(Asset)
        .join(SackAsset, SackAsset.asset_id == Asset.id)
        .filter(SackAsset.sack_id == sack_id)
        .order_by(Asset.ticket_id.asc())
        .all()
    )


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
    """Shifting person picks up the sack → IN_TRANSIT."""
    sack = _get_sack(db, sack_id, me)
    sack = _transition_sack(
        db, sack,
        SackStatus.IN_TRANSIT, SackMovementAction.PICKED_UP,
        AssetStatus.IN_TRANSIT, AssetMovementAction.PICKED_UP,
        me, payload,
    )
    return _sack_to_out(db, sack)


@router.put("/{sack_id}/deliver", response_model=SackOut)
def deliver_sack(
    sack_id: UUID,
    payload: SackActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.SHIFT_PERSON, RoleName.ORG_ADMIN)),
):
    """Shifting person drops off the sack → DELIVERED."""
    sack = _get_sack(db, sack_id, me)
    sack = _transition_sack(
        db, sack,
        SackStatus.DELIVERED, SackMovementAction.DELIVERED,
        AssetStatus.DELIVERED, AssetMovementAction.DELIVERED,
        me, payload,
    )
    return _sack_to_out(db, sack)


@router.put("/{sack_id}/receive", response_model=SackOut)
def receive_sack(
    sack_id: UUID,
    payload: SackActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.SYSADMIN, RoleName.ORG_ADMIN)),
):
    """Sysadmin (or org admin) confirms receipt → RECEIVED (terminal)."""
    sack = _get_sack(db, sack_id, me)
    sack = _transition_sack(
        db, sack,
        SackStatus.RECEIVED, SackMovementAction.RECEIVED,
        AssetStatus.RECEIVED, AssetMovementAction.RECEIVED,
        me, payload,
    )
    return _sack_to_out(db, sack)


@router.patch("/{sack_id}/origin", response_model=SackOut)
def update_sack_origin(
    sack_id: UUID,
    payload: SackOriginUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN, RoleName.STORE_MAINTAINER)),
):
    """Change a sack's origin / source location.

    Mirrors the ``/destination`` endpoint:
    - Only ORG_ADMIN and STORE_MAINTAINER can call it.
    - Allowed even while the sack is IN_TRANSIT.
    - Frozen once the sack is RECEIVED.
    - Every change is logged as a SackMovement so the audit trail
      shows who reassigned the origin and from where.
    """
    sack = _get_sack(db, sack_id, me)

    if sack.status == SackStatus.RECEIVED:
        raise HTTPException(
            400, "Cannot change origin after the sack has been RECEIVED"
        )

    new_origin_id = payload.origin_location_id
    new_loc: Location | None = None
    if new_origin_id is not None:
        new_loc = _ensure_location_in_tenant(db, new_origin_id, me)

    if sack.origin_location_id == new_origin_id:
        # Noop — don't pollute the timeline.
        return _sack_to_out(db, sack)

    prev_origin_id = sack.origin_location_id
    prev_loc = (
        db.get(Location, prev_origin_id) if prev_origin_id else None
    )
    sack.origin_location_id = new_origin_id

    prev_name = prev_loc.name if prev_loc else "—"
    new_name = new_loc.name if new_loc else "—"
    note = f"Origin changed: {prev_name} → {new_name}"
    if payload.remarks:
        note = f"{note} ({payload.remarks})"

    db.add(
        SackMovement(
            sack_id=sack.id,
            # See ``update_sack_destination`` for why we reuse CREATED here.
            action=SackMovementAction.CREATED,
            performed_by=me.id,
            from_location_id=prev_origin_id,
            to_location_id=new_origin_id,
            remarks=note,
        )
    )
    db.commit()
    db.refresh(sack)
    return _sack_to_out(db, sack)


@router.patch("/{sack_id}/destination", response_model=SackOut)
def update_sack_destination(
    sack_id: UUID,
    payload: SackDestinationUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN, RoleName.STORE_MAINTAINER)),
):
    """Change a sack's intended drop-off location.

    Why this is its own endpoint:
    - Only ORG_ADMIN and STORE_MAINTAINER are allowed to call it.
    - It must remain available *while the sack is in transit*, which the
      generic PATCH/lifecycle endpoints intentionally don't cover.
    - Every change is logged as a SackMovement so the audit trail
      shows who rerouted the sack and to where.

    Once the sack is RECEIVED the destination is frozen — at that point
    the package has already been handed over and rerouting is meaningless.
    """
    sack = _get_sack(db, sack_id, me)

    if sack.status == SackStatus.RECEIVED:
        raise HTTPException(
            400, "Cannot change destination after the sack has been RECEIVED"
        )

    new_dest_id = payload.destination_location_id
    new_loc: Location | None = None
    if new_dest_id is not None:
        new_loc = _ensure_location_in_tenant(db, new_dest_id, me)

    if sack.destination_location_id == new_dest_id:
        # Nothing actually changed — return the current state without
        # spamming the timeline with a no-op entry.
        return _sack_to_out(db, sack)

    prev_dest_id = sack.destination_location_id
    prev_loc = (
        db.get(Location, prev_dest_id) if prev_dest_id else None
    )
    sack.destination_location_id = new_dest_id

    # Build a human-readable remark for the timeline. The frontend already
    # renders from_location_name → to_location_name, but the remark gives
    # an unambiguous "Destination changed: X → Y" trace.
    prev_name = prev_loc.name if prev_loc else "—"
    new_name = new_loc.name if new_loc else "—"
    note = f"Destination changed: {prev_name} → {new_name}"
    if payload.remarks:
        note = f"{note} ({payload.remarks})"

    db.add(
        SackMovement(
            sack_id=sack.id,
            # Reuse the CREATED action enum value as the "metadata change"
            # marker — the new sack_movement_action enum doesn't have a
            # dedicated DESTINATION_CHANGED value yet, and adding one is
            # an enum migration we don't want to bundle into this change.
            # The remark text makes the intent unambiguous in the UI.
            action=SackMovementAction.CREATED,
            performed_by=me.id,
            from_location_id=prev_dest_id,
            to_location_id=new_dest_id,
            remarks=note,
        )
    )
    db.commit()
    db.refresh(sack)
    return _sack_to_out(db, sack)


@router.get("/{sack_id}/movements", response_model=list[SackMovementOut])
def list_sack_movements(
    sack_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Lifecycle timeline for a sack, oldest first.

    Each row is enriched with the performer's name/email and the
    from/to location names so the UI can render "Picked up by Bob at
    Dock A → North Depot" without any extra round-trips.
    """
    _get_sack(db, sack_id, me)
    return _enrich_movements(db, sack_id)
