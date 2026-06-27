"""Group endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models import Group, Instance, User
from app.models.enums import RoleName
from app.schemas.common import Page
from app.schemas.organization import GroupCreate, GroupOut, GroupUpdate

router = APIRouter(tags=["groups"])


def _ensure_instance_in_tenant(db: Session, instance_id: UUID, user: User) -> Instance:
    inst = db.get(Instance, instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Instance not found")
    return inst


def _ensure_group_in_tenant(db: Session, group_id: UUID, user: User) -> Group:
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    inst = db.get(Instance, g.instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Group not found")
    return g


@router.get("/instances/{instance_id}/groups", response_model=Page[GroupOut])
def list_groups(
    instance_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_instance_in_tenant(db, instance_id, user)
    q = db.query(Group).filter(Group.instance_id == instance_id)
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.post("/instances/{instance_id}/groups", response_model=GroupOut, status_code=201)
def create_group(
    instance_id: UUID,
    payload: GroupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    _ensure_instance_in_tenant(db, instance_id, user)
    g = Group(instance_id=instance_id, **payload.model_dump())
    db.add(g)
    db.commit()
    db.refresh(g)
    return g


@router.get("/groups/{group_id}", response_model=GroupOut)
def get_group(
    group_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _ensure_group_in_tenant(db, group_id, user)


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    g = _ensure_group_in_tenant(db, group_id, user)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(g, k, v)
    db.commit()
    db.refresh(g)
    return g


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    g = _ensure_group_in_tenant(db, group_id, user)
    db.delete(g)
    db.commit()
    return None
