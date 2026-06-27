"""User / Role schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMBase


class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    phone: str | None = None


class UserCreate(UserBase):
    password: str | None = Field(default=None, min_length=8)
    organization_id: UUID


class UserUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    is_active: bool | None = None


class UserOut(ORMBase, UserBase):
    id: UUID
    organization_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoleOut(ORMBase):
    id: UUID
    name: str
    description: str | None = None


class UserRoleAssign(BaseModel):
    user_id: UUID
    role_id: UUID


class UserRoleOut(ORMBase):
    id: UUID
    user_id: UUID
    role_id: UUID
    group_id: UUID
