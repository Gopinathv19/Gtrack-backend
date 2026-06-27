"""Instance endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models import Instance, User
from app.models.enums import RoleName
from app.schemas.common import Page
from app.schemas.organization import InstanceCreate, InstanceOut, InstanceUpdate

router = APIRouter(tags=["instances"])


@router.get("/orgs/{org_id}/instances", response_model=Page[InstanceOut])
def list_instances(
    org_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    q = db.query(Instance).filter(Instance.organization_id == org_id)
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.post("/orgs/{org_id}/instances", response_model=InstanceOut, status_code=201)
def create_instance(
    org_id: UUID,
    payload: InstanceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    inst = Instance(organization_id=org_id, **payload.model_dump())
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


@router.get("/instances/{instance_id}", response_model=InstanceOut)
def get_instance(
    instance_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inst = db.get(Instance, instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Instance not found")
    return inst


@router.patch("/instances/{instance_id}", response_model=InstanceOut)
def update_instance(
    instance_id: UUID,
    payload: InstanceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    inst = db.get(Instance, instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Instance not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(inst, k, v)
    db.commit()
    db.refresh(inst)
    return inst


@router.delete("/instances/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instance(
    instance_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    inst = db.get(Instance, instance_id)
    if not inst or inst.organization_id != user.organization_id:
        raise HTTPException(404, "Instance not found")
    db.delete(inst)
    db.commit()
    return None
