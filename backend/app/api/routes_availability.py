from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import and_, delete, select

from app.api.deps import CurrentUser, SessionDep
from app.db.models import AvailabilityRange
from app.schemas.availability import (
    AvailabilityRangeCreate,
    AvailabilityRangeOut,
    AvailabilityRangePatch,
    BulkRequest,
    BulkResult,
)

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("", response_model=list[AvailabilityRangeOut])
async def list_ranges(
    session: SessionDep,
    _: CurrentUser,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
) -> list[AvailabilityRange]:
    if to <= from_:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to must be after from")
    stmt = select(AvailabilityRange).where(
        and_(
            AvailabilityRange.starts_at < to,
            AvailabilityRange.ends_at > from_,
        )
    ).order_by(AvailabilityRange.user_id, AvailabilityRange.starts_at)
    result = await session.scalars(stmt)
    return list(result.all())


@router.post("", response_model=AvailabilityRangeOut, status_code=status.HTTP_201_CREATED)
async def create_range(
    body: AvailabilityRangeCreate,
    session: SessionDep,
    user: CurrentUser,
) -> AvailabilityRange:
    if body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ends_at must be after starts_at")
        
    row = AvailabilityRange(
        user_id=user.id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        all_day=body.all_day,
        status=body.status,
        confidence=body.confidence,
        note=body.note,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/{range_id}", response_model=AvailabilityRangeOut)
async def patch_range(
    range_id: int,
    body: AvailabilityRangePatch,
    session: SessionDep,
    user: CurrentUser,
) -> AvailabilityRange:
    row = await session.get(AvailabilityRange, range_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "range_not_found")
    if row.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_owner")

    if body.expected_updated_at is not None and body.expected_updated_at != row.updated_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "stale_update")

    data = body.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
    for k, v in data.items():
        setattr(row, k, v)

    if row.ends_at <= row.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ends_at_before_starts_at")

    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/{range_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_range(
    range_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    row = await session.get(AvailabilityRange, range_id)
    if row is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if row.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_owner")
    
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bulk", response_model=BulkResult)
async def bulk_ops(
    body: BulkRequest,
    session: SessionDep,
    user: CurrentUser,
) -> BulkResult:
    created: list[int] = []
    updated: list[int] = []
    deleted: list[int] = []

    for op in body.ops:
        if op.op == "create":
            if op.data is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "create_missing_data")
            row = AvailabilityRange(
                user_id=user.id,
                starts_at=op.data.starts_at,
                ends_at=op.data.ends_at,
                all_day=op.data.all_day,
                status=op.data.status,
                confidence=op.data.confidence,
                note=op.data.note,
            )
            session.add(row)
            await session.flush()
            created.append(row.id)
        elif op.op == "update":
            if op.id is None or op.data is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "update_missing_id_or_data")
            row = await session.get(AvailabilityRange, op.id)
            if row is None or row.user_id != user.id:
                continue
            row.starts_at = op.data.starts_at
            row.ends_at = op.data.ends_at
            row.all_day = op.data.all_day
            row.status = op.data.status
            row.confidence = op.data.confidence
            row.note = op.data.note
            updated.append(row.id)
        elif op.op == "delete":
            if op.id is None:
                continue
            await session.execute(
                delete(AvailabilityRange).where(
                    and_(
                        AvailabilityRange.id == op.id,
                        AvailabilityRange.user_id == user.id,
                    )
                )
            )
            deleted.append(op.id)

    await session.commit()
    return BulkResult(created_ids=created, updated_ids=updated, deleted_ids=deleted)