"""Supabase client wrapper.

Provides:
- A service-role client for backend administrative operations
  (creating users in Supabase Auth, sending magic links, etc.).
- A helper to verify Supabase-issued JWTs when integrating
  Supabase Auth on the frontend.
"""
from functools import lru_cache
from typing import Optional

from app.core.config import settings

try:
    from supabase import Client, create_client  # type: ignore
except ImportError:  # pragma: no cover
    Client = None  # type: ignore
    create_client = None  # type: ignore


@lru_cache
def get_supabase() -> Optional["Client"]:
    """Return a singleton Supabase service-role client, or None if not configured."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        return None
    if create_client is None:
        return None
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def verify_supabase_jwt(token: str) -> dict:
    """Verify a JWT issued by Supabase Auth using the project's JWT secret.

    Useful if the frontend logs in via Supabase Auth directly and forwards
    the JWT to this API.
    """
    from jose import jwt

    if not settings.SUPABASE_JWT_SECRET:
        raise RuntimeError("SUPABASE_JWT_SECRET is not configured")
    return jwt.decode(
        token,
        settings.SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        audience="authenticated",
    )
