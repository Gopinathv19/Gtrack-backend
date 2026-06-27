"""Invite schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMBase
from app.models.enums import InviteStatus


class InviteCreate(BaseModel):
    email: EmailStr
    role_id: UUID
    group_id: UUID


class InviteAccept(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8)


class InviteOut(ORMBase):
    id: UUID
    email: EmailStr
    organization_id: UUID
    group_id: UUID
    role_id: UUID
    status: InviteStatus
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime


class InviteCreatedResponse(BaseModel):
    invite_id: UUID
    token: str
    accept_url: str
