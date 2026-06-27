"""Authentication schemas."""
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPayload(BaseModel):
    sub: str  # user id
    org_id: str
    email: str | None = None
    roles: list[str] = []
    exp: int
    iss: str | None = None
    aud: str | None = None
