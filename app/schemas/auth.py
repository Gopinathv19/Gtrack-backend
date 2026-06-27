"""Authentication schemas."""
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenPair(BaseModel):
    """Token pair returned on login/register/refresh.

    Only the access token is included in the JSON body — the refresh token
    is delivered to the client as an HttpOnly cookie by the backend.
    """
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    """User self-registration. No organization details required —
    the user can create or be invited to an organization later."""
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=255)


class TokenPayload(BaseModel):
    sub: str  # user id
    org_id: str | None = None  # users may not belong to an org yet
    email: str | None = None
    roles: list[str] = []
    exp: int
    iss: str | None = None
    aud: str | None = None
