"""Authentication endpoints: login, refresh, logout."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_token,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair

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
