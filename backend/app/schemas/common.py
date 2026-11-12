from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PageResponse(APIModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class TimestampedResponse(APIModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
