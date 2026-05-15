from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AvailabilityRangeBase(BaseModel):
    starts_at: datetime
    ends_at: datetime
    all_day: bool = True
    status: int = Field(..., ge=1, le=3)
    confidence: int = Field(3, ge=1, le=5)
    note: str | None = None

    @field_validator("ends_at")
    @classmethod
    def _ends_after_starts(cls, v: datetime, info) -> datetime:  # type: ignore[no-untyped-def]
        starts = info.data.get("starts_at")
        if starts is not None and v <= starts:
            raise ValueError("ends_at must be after starts_at")
        return v


class AvailabilityRangeCreate(AvailabilityRangeBase):
    pass


class AvailabilityRangePatch(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    status: int | None = Field(None, ge=1, le=3)
    confidence: int | None = Field(None, ge=1, le=5)
    note: str | None = None
    expected_updated_at: datetime | None = None  # optimistic concurrency


class AvailabilityRangeOut(AvailabilityRangeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class BulkOp(BaseModel):
    op: Literal["create", "update", "delete"]
    id: int | None = None
    data: AvailabilityRangeBase | None = None


class BulkRequest(BaseModel):
    ops: list[BulkOp]


class BulkResult(BaseModel):
    created_ids: list[int]
    updated_ids: list[int]
    deleted_ids: list[int]
