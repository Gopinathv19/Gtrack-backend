"""Authentication endpoints: login, refresh, logout."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.models import RefreshToken, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- Cookie helpers ----------
def _set_refresh_cookie(response: Response, raw_refresh: str) -> None:
    """Set the refresh token as an HttpOnly Secure cookie.

    Note: when a path operation returns a Pydantic model, FastAPI builds a
    new JSONResponse but it *does* preserve cookies/headers set on the
    injected ``Response`` parameter. So calling ``response.set_cookie`` here
    works as long as the endpoint declares ``response: Response`` and the
    *same* object is passed in.
    """
    # samesite must be one of {"lax", "strict", "none"} or None
    samesite_val = settings.REFRESH_COOKIE_SAMESITE
    if isinstance(samesite_val, str):
        samesite_val = samesite_val.lower()
        if samesite_val not in ("lax", "strict", "none"):
            samesite_val = "lax"

    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=samesite_val,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
    )


def _build_token_pair(db: Session, user: User, response: Response) -> TokenPair:
    """Create access + refresh tokens, store refresh hash in DB,
    set refresh token as HttpOnly cookie, and return the access token in the body.
    """
    # roles list
    from app.api.deps import get_user_roles

    roles = get_user_roles(db, user.id)
    access = create_access_token(
        user_id=user.id,
        org_id=user.organization_id,
        email=user.email,
        name=user.name,
        roles=roles,
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

    # Set HttpOnly cookie for the refresh token
    _set_refresh_cookie(response, raw_refresh)

    # NOTE: refresh_token is intentionally NOT included in the response body
    # because it's delivered via a secure HttpOnly cookie.
    return TokenPair(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _extract_refresh_token(request: Request) -> str:
    """Read the refresh token from the HttpOnly cookie.

    The refresh token is delivered to the client as an HttpOnly cookie at
    login/register/refresh, and the browser automatically sends it back on
    subsequent calls to /refresh and /logout. The client never has to
    pass it in the body.
    """
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token cookie",
        )
    return token


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPair:
    """Register a new user.

    Only user details are required. The user is created without an
    organization — they can either create their own org via ``POST /orgs``
    once logged in, or be invited into an existing org.
    """
    # Email uniqueness
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        name=payload.name,
        hashed_password=hash_password(payload.password),
        organization_id=None,  # no org until they create or join one
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Issue tokens immediately so the user is logged in after registration.
    return _build_token_pair(db, user, response)


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPair:
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
    return _build_token_pair(db, user, response)


@router.post("/refresh", response_model=TokenPair)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenPair:
    """Rotate the refresh token using the HttpOnly cookie sent by the browser.

    The client does not need to send anything in the body — the browser
    automatically attaches the ``refresh_token`` cookie.
    """
    raw_token = _extract_refresh_token(request)
    token_hash = hash_token(raw_token)
    rt = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .one_or_none()
    )
    if not rt or rt.revoked or rt.expires_at < datetime.now(timezone.utc):
        # Clear any stale cookie on the client
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    user = db.get(User, rt.user_id)
    if not user or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive"
        )

    # rotate refresh token
    rt.revoked = True
    db.add(rt)
    new_pair = _build_token_pair(db, user, response)
    return new_pair


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Revoke the refresh token (read from cookie) and clear the cookie.

    The client does not need to send a body — the browser automatically
    attaches the ``refresh_token`` cookie.
    """
    raw_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)

    if raw_token:
        token_hash = hash_token(raw_token)
        rt = (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .one_or_none()
        )
        if rt and not rt.revoked:
            rt.revoked = True
            db.commit()

    # Always clear the cookie on logout (even if token wasn't found)
    _clear_refresh_cookie(response)
    return None
