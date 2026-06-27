"""Security utilities: password hashing and JWT signing/verification."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------- Password helpers ----------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------- JWT helpers ----------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    user_id: UUID | str,
    org_id: UUID | str,
    email: str | None = None,
    roles: list[str] | None = None,
    expires_minutes: int | None = None,
) -> str:
    expires = _now_utc() + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "email": email,
        "roles": roles or [],
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(_now_utc().timestamp()),
        "exp": int(expires.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT.

    Raises:
        JWTError: if invalid.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
    )


def generate_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Persist the hash, return the raw to the client."""
    import hashlib

    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def hash_token(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)
