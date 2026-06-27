"""Location endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models import Group, Instance, Location, User
from app.models.enums import RoleName
from app.schemas.common import Page
from app.schemas.location import LocationCreate, LocationOut, LocationUpdate

router = APIRouter(tags=["locations"])


def _ensure_group_in_tenant(db: Session, group_id: UUID, user: User) -> Group:
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    inst = db.get(Instance, g.instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Group not found")
    return g


@router.get("/locations", response_model=Page[LocationOut])
def list_locations(
    group_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = (
        db.query(Location)
        .join(Group, Location.group_id == Group.id)
        .join(Instance, Group.instance_id == Instance.id)
        .filter(Instance.organization_id == me.organization_id)
    )
    if group_id:
        q = q.filter(Location.group_id == group_id)
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.post("/groups/{group_id}/locations", response_model=LocationOut, status_code=201)
def create_location(
    group_id: UUID,
    payload: LocationCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    _ensure_group_in_tenant(db, group_id, me)
    loc = Location(group_id=group_id, **payload.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.get("/locations/{location_id}", response_model=LocationOut)
def get_location(
    location_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    _ensure_group_in_tenant(db, loc.group_id, me)
    return loc


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    _ensure_group_in_tenant(db, loc.group_id, me)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(loc, k, v)
    db.commit()
    db.refresh(loc)
    return loc


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(
    location_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    _ensure_group_in_tenant(db, loc.group_id, me)
    db.delete(loc)
    db.commit()
    return None
