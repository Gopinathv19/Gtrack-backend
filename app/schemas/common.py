"""Common Pydantic types and helpers."""
from typing import Generic, TypeVar, List
from pydantic import BaseModel, Field

T = TypeVar("T")


class ORMBase(BaseModel):
    model_config = {"from_attributes": True}


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int = 1
    per_page: int = 50


class Message(BaseModel):
    message: str


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=200)
