"""Organization / Instance / Group schemas."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class OrganizationOut(ORMBase, OrganizationBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class InstanceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class InstanceCreate(InstanceBase):
    pass


class InstanceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class InstanceOut(ORMBase, InstanceBase):
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


class GroupBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class GroupCreate(GroupBase):
    pass


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class GroupOut(ORMBase, GroupBase):
    id: UUID
    instance_id: UUID
    created_at: datetime
    updated_at: datetime
