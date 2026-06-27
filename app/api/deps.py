"""FastAPI dependencies for authentication, RBAC, and DB sessions."""
from typing import Generator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models import User, UserRole, Role
from app.models.enums import RoleName

# Use HTTPBearer for cleaner Swagger UI (just access token field, no OAuth2 fields)
security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise JWTError("Missing sub claim")
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, UUID(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_current_org_id(user: User = Depends(get_current_user)) -> UUID:
    return user.organization_id


def get_user_roles(
    db: Session, user_id: UUID, group_id: UUID | None = None
) -> list[str]:
    """Return list of role names a user has (optionally scoped to a group)."""
    q = (
        db.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
    )
    if group_id:
        q = q.filter(UserRole.group_id == group_id)
    return [r[0] for r in q.all()]


def require_roles(*allowed: RoleName):
    """Dependency factory: require the user to have at least one of the roles
    anywhere in their organization."""

    def _checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        roles = set(get_user_roles(db, user.id))
        allowed_set = {r.value for r in allowed}
        if not (roles & allowed_set):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {sorted(allowed_set)}",
            )
        return user

    return _checker


def require_roles_in_group(*allowed: RoleName):
    """Dependency factory: require the user to have one of the roles within
    a specific group (group_id provided as path/query parameter)."""

    def _checker(
        group_id: UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        roles = set(get_user_roles(db, user.id, group_id=group_id))
        allowed_set = {r.value for r in allowed}
        if not (roles & allowed_set):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles in this group: {sorted(allowed_set)}",
            )
        return user

    return _checker
