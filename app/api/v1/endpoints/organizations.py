"""Organization endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models import Group, Instance, Organization, Role, User, UserRole
from app.models.enums import RoleName
from app.schemas.common import Page
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)

router = APIRouter(prefix="/orgs", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=201)
def create_org(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new organization (authenticated).

    The caller becomes the organization's first ``ORG_ADMIN``. The org is
    bootstrapped with a default ``Instance`` and ``Group`` so the user can
    immediately start adding locations, assets, and inviting members.

    A user can only create an org if they don't already belong to one.
    """
    if current_user.organization_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already belong to an organization",
        )

    if db.query(Organization).filter(Organization.name == payload.name).first():
        raise HTTPException(409, "Organization name already exists")

    org_admin_role = (
        db.query(Role).filter(Role.name == RoleName.ORG_ADMIN.value).first()
    )
    if not org_admin_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ORG_ADMIN role not found. Run seed_roles.py first.",
        )

    # Create org + default instance + default group
    org = Organization(**payload.model_dump())
    db.add(org)
    db.flush()

    default_instance = Instance(
        organization_id=org.id,
        name="Default Instance",
        description="Default instance for the organization",
    )
    db.add(default_instance)
    db.flush()

    default_group = Group(
        instance_id=default_instance.id,
        name="Default Group",
        description="Default group for the instance",
    )
    db.add(default_group)
    db.flush()

    # Attach the creator to the new org and grant ORG_ADMIN role in the default group
    current_user.organization_id = org.id
    db.add(current_user)

    db.add(
        UserRole(
            user_id=current_user.id,
            role_id=org_admin_role.id,
            group_id=default_group.id,
        )
    )

    db.commit()
    db.refresh(org)
    return org


@router.get("", response_model=Page[OrganizationOut])
def list_orgs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # tenant scoped
    q = db.query(Organization).filter(Organization.id == user.organization_id)
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.get("/{org_id}", response_model=OrganizationOut)
def get_org(
    org_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    return org


@router.patch("/{org_id}", response_model=OrganizationOut)
def update_org(
    org_id: UUID,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(org, k, v)
    db.commit()
    db.refresh(org)
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org(
    org_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    db.delete(org)
    db.commit()
    return None
