"""Security utilities: password hashing and JWT signing/verification."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


# ---------- Password helpers ----------
def hash_password(password: str) -> str:
    """Hash a password using bcrypt.
    
    Note: bcrypt has a 72 byte limit. We truncate to 72 bytes to avoid errors.
    This is a standard practice and still provides strong security.
    """
    # Truncate to 72 bytes to comply with bcrypt limitations
    password_bytes = password.encode('utf-8')[:72]
    # Generate salt and hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash.
    
    Note: Truncates to 72 bytes to match hash_password behavior.
    """
    # Truncate to 72 bytes to match hashing behavior
    password_bytes = plain.encode('utf-8')[:72]
    hashed_bytes = hashed.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# ---------- JWT helpers ----------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    *,
    user_id: UUID | str,
    org_id: UUID | str | None = None,
    email: str | None = None,
    roles: list[str] | None = None,
    expires_minutes: int | None = None,
) -> str:
    expires = _now_utc() + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        # org_id may be None for newly-registered users who haven't
        # created or joined an organization yet.
        "org_id": str(org_id) if org_id is not None else None,
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
