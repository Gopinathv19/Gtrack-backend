"""Authentication endpoints: login, refresh, logout."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models import Group, Instance, Organization, RefreshToken, Role, User, UserRole
from app.models.enums import RoleName
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_token_pair(db: Session, user: User) -> TokenPair:
    # roles list
    from app.api.deps import get_user_roles

    roles = get_user_roles(db, user.id)
    access = create_access_token(
        user_id=user.id, org_id=user.organization_id, email=user.email, roles=roles
    )
    raw_refresh, refresh_hash = generate_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    """
    Register a new user and organization.
    Creates a new organization and the first user (admin) for that organization.
    """
    # Check if email already exists
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Check if organization name already exists
    existing_org = db.query(Organization).filter(
        Organization.name == payload.organization_name
    ).first()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name already taken"
        )
    
    # Get ORG_ADMIN role
    org_admin_role = db.query(Role).filter(Role.name == RoleName.ORG_ADMIN.value).first()
    if not org_admin_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ORG_ADMIN role not found. Please run seed_roles.py script first."
        )
    
    # Create organization
    org = Organization(
        name=payload.organization_name,
        description=None
    )
    db.add(org)
    db.flush()  # Get the organization ID
    
    # Create default instance for the organization
    default_instance = Instance(
        organization_id=org.id,
        name="Default Instance",
        description="Default instance for organization"
    )
    db.add(default_instance)
    db.flush()  # Get the instance ID
    
    # Create default group for the instance
    default_group = Group(
        instance_id=default_instance.id,
        name="Default Group",
        description="Default group for instance"
    )
    db.add(default_group)
    db.flush()  # Get the group ID
    
    # Create user
    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        organization_id=org.id,
        is_active=True
    )
    db.add(user)
    db.flush()  # Get the user ID
    
    # Assign ORG_ADMIN role to the user in the default group
    user_role = UserRole(
        user_id=user.id,
        role_id=org_admin_role.id,
        group_id=default_group.id
    )
    db.add(user_role)
    
    db.commit()
    db.refresh(user)
    
    # Return token pair for immediate login
    return _build_token_pair(db, user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not user.hashed_password or not verify_password(
        payload.password, user.hashed_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account inactive"
        )
    return _build_token_pair(db, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    token_hash = hash_token(payload.refresh_token)
    rt = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .one_or_none()
    )
    if not rt or rt.revoked or rt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user = db.get(User, rt.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive"
        )

    # rotate
    rt.revoked = True
    db.add(rt)
    new_pair = _build_token_pair(db, user)
    return new_pair


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    token_hash = hash_token(payload.refresh_token)
    rt = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .one_or_none()
    )
    if rt:
        rt.revoked = True
        db.commit()
    return None
