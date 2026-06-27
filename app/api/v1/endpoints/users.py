"""User and Role endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.core.security import hash_password
from app.models import Group, Instance, Role, User, UserRole
from app.models.enums import RoleName
from app.schemas.common import Page
from app.schemas.user import (
    RoleOut,
    UserCreate,
    UserOut,
    UserRoleAssign,
    UserRoleOut,
    UserUpdate,
)

router = APIRouter(tags=["users"])


# ---------- Users ----------
@router.get("/users", response_model=Page[UserOut])
def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    q = db.query(User).filter(User.organization_id == me.organization_id)
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return Page(items=items, total=total, page=page, per_page=per_page)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    if payload.organization_id != me.organization_id:
        raise HTTPException(403, "Cannot create users in other organization")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(409, "Email already exists")
    data = payload.model_dump(exclude={"password"})
    user = User(**data)
    if payload.password:
        user.hashed_password = hash_password(payload.password)
        user.is_active = True
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    u = db.get(User, user_id)
    if not u or u.organization_id != me.organization_id:
        raise HTTPException(404, "User not found")
    return u


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    u = db.get(User, user_id)
    if not u or u.organization_id != me.organization_id:
        raise HTTPException(404, "User not found")
    # only self or org admin
    if u.id != me.id:
        from app.api.deps import get_user_roles

        roles = set(get_user_roles(db, me.id))
        if RoleName.ORG_ADMIN.value not in roles:
            raise HTTPException(403, "Forbidden")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    db.commit()
    db.refresh(u)
    return u


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    u = db.get(User, user_id)
    if not u or u.organization_id != me.organization_id:
        raise HTTPException(404, "User not found")
    db.delete(u)
    db.commit()
    return None


# ---------- Roles ----------
@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db), _me: User = Depends(get_current_user)
):
    return db.query(Role).all()


# ---------- User-Role assignment within a group ----------
@router.post(
    "/groups/{group_id}/users",
    response_model=UserRoleOut,
    status_code=201,
)
def assign_user_to_group(
    group_id: UUID,
    payload: UserRoleAssign,
    db: Session = Depends(get_db),
    me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    g = db.get(Group, group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    inst = db.get(Instance, g.instance_id)
    if not inst or inst.organization_id != me.organization_id:
        raise HTTPException(404, "Group not found")
    user = db.get(User, payload.user_id)
    if not user or user.organization_id != me.organization_id:
        raise HTTPException(404, "User not found")
    role = db.get(Role, payload.role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    existing = (
        db.query(UserRole)
        .filter(
            UserRole.user_id == payload.user_id,
            UserRole.role_id == payload.role_id,
            UserRole.group_id == group_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Role already assigned")
    ur = UserRole(user_id=payload.user_id, role_id=payload.role_id, group_id=group_id)
    db.add(ur)
    db.commit()
    db.refresh(ur)
    return ur


@router.delete(
    "/groups/{group_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_user_from_group(
    group_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    _me: User = Depends(require_roles(RoleName.ORG_ADMIN)),
):
    db.query(UserRole).filter(
        UserRole.group_id == group_id, UserRole.user_id == user_id
    ).delete()
    db.commit()
    return None


@router.get("/groups/{group_id}/user_roles", response_model=list[UserRoleOut])
def list_group_user_roles(
    group_id: UUID,
    db: Session = Depends(get_db),
    _me: User = Depends(get_current_user),
):
    return db.query(UserRole).filter(UserRole.group_id == group_id).all()
