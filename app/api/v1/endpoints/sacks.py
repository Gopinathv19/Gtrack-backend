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
    ReturnAssetActionRequest,
    SackActionRequest,
    SackAssetsAdd,
    SackAssetsAddResult,
    SackCreate,
    SackDestinationUpdate,
    SackLifecycle,
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


# Asset terminal / "still in flight" helpers used by the lifecycle
# computation below.
_RETURN_LEG_OPEN_STATES = {
    AssetStatus.PACKED_FOR_RETURN,
    AssetStatus.IN_TRANSIT,  # for return-required assets, this is the reverse leg
}

_TERMINAL_STATES = {
    AssetStatus.RETURNED,
    AssetStatus.DAMAGED,
    AssetStatus.LOST,
}


def _asset_is_done(a: Asset) -> bool:
    """True when the asset's lifecycle is complete from the sack's pov.

    - "no return needed" assets are done at RECEIVED.
    - "return required" assets are done at RETURNED.
    - DAMAGED / LOST always count as done.
    """
    if a.status in (AssetStatus.DAMAGED, AssetStatus.LOST):
        return True
    if a.requires_return:
        return a.status == AssetStatus.RETURNED
    return a.status == AssetStatus.RECEIVED


def _compute_lifecycle(
    sack: Sack, assets: list[Asset]
) -> tuple[SackLifecycle, int, int]:
    """Derive the lifecycle of a sack from its contents.

    Returns ``(lifecycle, asset_count, pending_return_count)``.

    Rules:
    - CLOSED  ⇔ every asset in the sack has reached its terminal —
                RECEIVED for "no return needed" assets and RETURNED for
                "return required" assets (DAMAGED / LOST also terminal).
    - PENDING_RETURN ⇔ the forward leg of the sack is RECEIVED and at
                least one return-required asset still hasn't been
                RETURNED. This is the state where the 3-step reverse
                flow (sysadmin → shift person → store manager) runs in
                place on the same sack.
    - ACTIVE  ⇔ everything else (forward leg still in flight, etc).
    """
    asset_count = len(assets)
    if asset_count == 0:
        # Empty sack — only "closed" if the sack itself was RECEIVED;
        # otherwise it's just sitting there, ACTIVE.
        if sack.status == SackStatus.RECEIVED:
            return SackLifecycle.CLOSED, 0, 0
        return SackLifecycle.ACTIVE, 0, 0

    pending_return_count = sum(
        1
        for a in assets
        if a.requires_return and a.status not in _TERMINAL_STATES
    )

    if all(_asset_is_done(a) for a in assets):
        return SackLifecycle.CLOSED, asset_count, pending_return_count

    # PENDING_RETURN once the forward leg is done and the only open work
    # is the reverse leg for one or more return-required assets.
    if (
        sack.status == SackStatus.RECEIVED
        and pending_return_count > 0
        and all(
            _asset_is_done(a)
            or (
                a.requires_return
                and a.status
                in (
                    AssetStatus.RECEIVED,
                    AssetStatus.PACKED_FOR_RETURN,
                    AssetStatus.IN_TRANSIT,
                )
            )
            for a in assets
        )
    ):
        return SackLifecycle.PENDING_RETURN, asset_count, pending_return_count

    return SackLifecycle.ACTIVE, asset_count, pending_return_count


def _sack_assets(db: Session, sack_id: UUID) -> list[Asset]:
    """Return the assets currently packed into ``sack_id``."""
    return (
        db.query(Asset)
        .join(SackAsset, SackAsset.asset_id == Asset.id)
        .filter(SackAsset.sack_id == sack_id)
        .all()
    )


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
    assets = _sack_assets(db, sack.id)
    lifecycle, asset_count, pending_return_count = _compute_lifecycle(sack, assets)
    return {
        "id": sack.id,
        "sack_code": sack.sack_code,
        "organization_id": sack.organization_id,
        "group_id": sack.group_id,
        "status": sack.status,
        "lifecycle": lifecycle,
        "created_by": sack.created_by,
        "origin_location_id": sack.origin_location_id,
        "origin_location_name": origin.name if origin else None,
        "destination_location_id": sack.destination_location_id,
        "destination_location_name": dest.name if dest else None,
        "created_by_name": creator.name if creator else None,
        "created_by_email": creator.email if creator else None,
        "asset_count": asset_count,
        "pending_return_count": pending_return_count,
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
    lifecycle: SackLifecycle | None = Query(
        None,
        description=(
            "Filter by derived lifecycle: ACTIVE (forward leg in progress),"
            " PENDING_RETURN (forward done, returns outstanding),"
            " or CLOSED (every ticket terminal)."
        ),
    ),
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

    # Lifecycle is derived (not a column), so we can't push it down into
    # the SQL filter. The trade-off is acceptable: we always pre-filter
    # by ``status`` so the candidate set is small enough to materialise
    # and classify in Python. When lifecycle == ACTIVE we even short-
    # circuit at the SQL layer (Sack.status != RECEIVED).
    if lifecycle == SackLifecycle.ACTIVE:
        q = q.filter(Sack.status != SackStatus.RECEIVED)
    elif lifecycle in (SackLifecycle.PENDING_RETURN, SackLifecycle.CLOSED):
        q = q.filter(Sack.status == SackStatus.RECEIVED)

    q = q.order_by(Sack.created_at.desc())
    candidates = q.all()

    serialized = [_sack_to_out(db, s) for s in candidates]
    if lifecycle is not None:
        serialized = [s for s in serialized if s["lifecycle"] == lifecycle]

    total = len(serialized)
    start = (page - 1) * per_page
    return Page(
        items=serialized[start : start + per_page],
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

    # Fall back to the sack's known origin / destination when the caller
    # doesn't pass explicit locations. The pickup / deliver / receive
    # actions are normally invoked from the UI without a location payload,
    # but the sack itself already knows where it's coming from and where
    # it's headed — so the timeline (and downstream asset rows) should
    # reflect that instead of showing blank "From — / To —" entries.
    from_loc_id = payload.from_location_id
    to_loc_id = payload.to_location_id
    if from_loc_id is None:
        if action == SackMovementAction.PICKED_UP:
            from_loc_id = sack.origin_location_id
        elif action in (
            SackMovementAction.DELIVERED,
            SackMovementAction.RECEIVED,
        ):
            # Deliver/receive: we've left the origin and arrived at the
            # destination, so the movement row goes origin → destination.
            from_loc_id = sack.origin_location_id
    if to_loc_id is None:
        if action == SackMovementAction.PICKED_UP:
            # Picked up from origin, heading toward the destination.
            to_loc_id = sack.destination_location_id
        elif action in (
            SackMovementAction.DELIVERED,
            SackMovementAction.RECEIVED,
        ):
            to_loc_id = sack.destination_location_id

    db.add(
        SackMovement(
            sack_id=sack.id,
            action=action,
            performed_by=me.id,
            from_location_id=from_loc_id,
            to_location_id=to_loc_id,
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
            if to_loc_id and asset_status in (
                AssetStatus.DELIVERED,
                AssetStatus.RECEIVED,
            ):
                asset.current_location_id = to_loc_id
            db.add(
                AssetMovement(
                    asset_id=asset.id,
                    sack_id=sack.id,
                    action=asset_action,
                    performed_by=me.id,
                    from_location_id=from_loc_id,
                    to_location_id=to_loc_id,
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


# ---------- Reverse-leg actions (per asset, in place) ----------
#
# The reverse leg is broken into three distinct, role-gated steps so
# the audit trail captures who did what:
#
#   1. mark-return     — SYSADMIN / ORG_ADMIN.   RECEIVED → PACKED_FOR_RETURN
#   2. pickup-return   — SHIFT_PERSON / ORG_ADMIN. PACKED_FOR_RETURN → IN_TRANSIT
#   3. receive-return  — STORE_MAINTAINER / ORG_ADMIN. IN_TRANSIT → RETURNED
#
# All three live on the same sack the asset was originally shipped on
# — no new "return sack" is created. The sack-level audit timeline uses
# the existing SackMovementAction enum (PICKED_UP / DELIVERED /
# RECEIVED) with descriptive remarks so we don't need an enum
# migration just to add return-specific actions.


def _resolve_sack_and_asset(
    db: Session, sack_id: UUID, asset_id: UUID, me: User
) -> tuple[Sack, Asset]:
    """Shared precondition for the reverse-leg endpoints.

    Validates the sack exists in the caller's tenant, the asset is
    actually packed in it, and that the sack's forward leg is RECEIVED
    (so the reverse leg can legally begin / continue).
    """
    sack = _get_sack(db, sack_id, me)
    if sack.status != SackStatus.RECEIVED:
        raise HTTPException(
            400,
            "Reverse-leg actions are only allowed once the sack has been RECEIVED",
        )
    sa = (
        db.query(SackAsset)
        .filter(SackAsset.sack_id == sack.id, SackAsset.asset_id == asset_id)
        .one_or_none()
    )
    if not sa:
        raise HTTPException(404, "Asset is not in this sack")
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != me.organization_id:
        raise HTTPException(404, "Asset not found")
    if not asset.requires_return:
        raise HTTPException(
            400, "This asset was not flagged as needing a return"
        )
    return sack, asset


@router.post("/{sack_id}/assets/{asset_id}/mark-return", response_model=SackOut)
def mark_asset_for_return(
    sack_id: UUID,
    asset_id: UUID,
    payload: ReturnAssetActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.SYSADMIN, RoleName.ORG_ADMIN)),
):
    """Step 1 — sysadmin flags a RECEIVED asset for return.

    Transitions ``asset.status`` from RECEIVED → PACKED_FOR_RETURN and
    leaves it physically at the sack's destination (the asset still
    hasn't moved). The shift person picks it up in step 2.
    """
    sack, asset = _resolve_sack_and_asset(db, sack_id, asset_id, me)
    if asset.status != AssetStatus.RECEIVED:
        raise HTTPException(
            409,
            f"Asset must be RECEIVED to be marked for return; current status is {asset.status.value}",
        )

    validate_asset_transition(asset.status, AssetStatus.PACKED_FOR_RETURN)
    asset.status = AssetStatus.PACKED_FOR_RETURN

    # `location_id` here means "where the asset currently sits while
    # waiting for pickup" — defaults to the sack destination (where the
    # forward leg dropped it). We don't change current_location_id.
    note_location_id = payload.location_id or sack.destination_location_id

    db.add(
        AssetMovement(
            asset_id=asset.id,
            sack_id=sack.id,
            action=AssetMovementAction.PACKED,
            performed_by=me.id,
            from_location_id=asset.current_location_id,
            to_location_id=note_location_id,
            remarks=payload.remarks or "Marked for return",
        )
    )
    note = f"Asset {asset.ticket_id} marked for return"
    if payload.remarks:
        note = f"{note} ({payload.remarks})"
    db.add(
        SackMovement(
            sack_id=sack.id,
            action=SackMovementAction.CREATED,  # reused as "metadata change"
            performed_by=me.id,
            from_location_id=asset.current_location_id,
            to_location_id=note_location_id,
            remarks=note,
        )
    )

    db.commit()
    db.refresh(sack)
    return _sack_to_out(db, sack)


@router.post(
    "/{sack_id}/assets/{asset_id}/pickup-return", response_model=SackOut
)
def pickup_returned_asset(
    sack_id: UUID,
    asset_id: UUID,
    payload: ReturnAssetActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.SHIFT_PERSON, RoleName.ORG_ADMIN)),
):
    """Step 2 — shift person picks the marked asset up for return.

    Transitions ``asset.status`` from PACKED_FOR_RETURN → IN_TRANSIT
    (now travelling back to the store). The asset's
    ``current_location_id`` is left untouched until the store manager
    confirms receipt in step 3 — at that point the asset's location
    snaps to the sack origin (or the override).
    """
    sack, asset = _resolve_sack_and_asset(db, sack_id, asset_id, me)
    if asset.status != AssetStatus.PACKED_FOR_RETURN:
        raise HTTPException(
            409,
            f"Asset must be PACKED_FOR_RETURN before pickup; current status is {asset.status.value}",
        )

    validate_asset_transition(asset.status, AssetStatus.IN_TRANSIT)
    asset.status = AssetStatus.IN_TRANSIT

    from_loc = asset.current_location_id or sack.destination_location_id
    to_loc = payload.location_id or sack.origin_location_id

    db.add(
        AssetMovement(
            asset_id=asset.id,
            sack_id=sack.id,
            action=AssetMovementAction.PICKED_UP,
            performed_by=me.id,
            from_location_id=from_loc,
            to_location_id=to_loc,
            remarks=payload.remarks or "Picked up for return",
        )
    )
    note = f"Asset {asset.ticket_id} picked up for return"
    if payload.remarks:
        note = f"{note} ({payload.remarks})"
    db.add(
        SackMovement(
            sack_id=sack.id,
            action=SackMovementAction.PICKED_UP,
            performed_by=me.id,
            from_location_id=from_loc,
            to_location_id=to_loc,
            remarks=note,
        )
    )

    db.commit()
    db.refresh(sack)
    return _sack_to_out(db, sack)


@router.post(
    "/{sack_id}/assets/{asset_id}/receive-return", response_model=SackOut
)
def receive_returned_asset(
    sack_id: UUID,
    asset_id: UUID,
    payload: ReturnAssetActionRequest,
    db: Session = Depends(get_db),
    me: User = Depends(
        require_roles(RoleName.STORE_MAINTAINER, RoleName.ORG_ADMIN)
    ),
):
    """Step 3 — store manager confirms the asset is back at the store.

    Transitions ``asset.status`` from IN_TRANSIT → RETURNED (terminal)
    and updates ``asset.current_location_id`` to the chosen return
    location (defaults to the sack's origin — i.e. the store).
    """
    sack, asset = _resolve_sack_and_asset(db, sack_id, asset_id, me)
    if asset.status != AssetStatus.IN_TRANSIT:
        raise HTTPException(
            409,
            f"Asset must be IN_TRANSIT to be received as returned; current status is {asset.status.value}",
        )

    return_location_id = payload.location_id or sack.origin_location_id
    if return_location_id:
        _ensure_location_in_tenant(db, return_location_id, me)

    validate_asset_transition(asset.status, AssetStatus.RETURNED)
    prev_location = asset.current_location_id
    asset.status = AssetStatus.RETURNED
    if return_location_id:
        asset.current_location_id = return_location_id

    db.add(
        AssetMovement(
            asset_id=asset.id,
            sack_id=sack.id,
            action=AssetMovementAction.RECEIVED,
            performed_by=me.id,
            from_location_id=prev_location,
            to_location_id=return_location_id,
            remarks=payload.remarks or "Returned to store",
        )
    )
    note = f"Asset {asset.ticket_id} returned to store"
    if payload.remarks:
        note = f"{note} ({payload.remarks})"
    db.add(
        SackMovement(
            sack_id=sack.id,
            action=SackMovementAction.RECEIVED,
            performed_by=me.id,
            from_location_id=prev_location,
            to_location_id=return_location_id,
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
