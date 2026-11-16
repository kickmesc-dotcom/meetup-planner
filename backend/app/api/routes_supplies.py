"""Склад расходников: список, создание, движения и история.

Права разделены по смыслу действия, а не по экрану:

* **читать** может любой сотрудник — «сколько осталось» не секрет, и именно
  сотрудник решает, хватит ли ему перчаток до конца смены;
* **создавать и менять порог** — только руководитель (`AupDep`): это настройка
  склада, а не работа смены;
* **приход** — только руководитель: приход означает, что кто-то принял товар;
* **списание** — любой сотрудник: он физически берёт расходник, и лишний шаг
  «попроси руководителя» вернул бы устный учёт, ради ухода от которого всё
  и делалось.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import AupDep, EmployeeDep, SessionDep
from app.db.hr_models import SUPPLY_IN
from app.services import hr_access, hr_supplies

router = APIRouter(prefix="/supplies", tags=["supplies"])


class SupplyOut(BaseModel):
    id: int
    name: str
    unit: str
    quantity: float
    min_quantity: float
    low: bool
    department_id: int | None
    department: str | None
    updated_at: datetime


class MovementOut(BaseModel):
    id: int
    kind: str
    quantity: float
    comment: str | None
    employee_name: str | None
    created_at: datetime


class MoveResultOut(BaseModel):
    supply: SupplyOut
    movement: MovementOut


class SupplyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(default="шт", max_length=16)
    quantity: float | None = 0
    min_quantity: float | None = 0
    department_id: int | None = None


class SupplyPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    unit: str | None = Field(default=None, max_length=16)
    min_quantity: float | None = None
    is_active: bool | None = None


class MoveIn(BaseModel):
    kind: str = Field(pattern="^(in|out)$")
    quantity: float
    comment: str | None = Field(default=None, max_length=300)


def _error(exc: hr_supplies.SupplyError) -> HTTPException:
    code = str(exc)
    if code == "supply_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    if code == "not_enough":
        return HTTPException(status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _out(row: hr_supplies.SupplyRow) -> SupplyOut:
    return SupplyOut(
        id=row.id,
        name=row.name,
        unit=row.unit,
        quantity=row.quantity,
        min_quantity=row.min_quantity,
        low=row.low,
        department_id=row.department_id,
        department=row.department,
        updated_at=row.updated_at,
    )


def _movement(row: hr_supplies.MovementRow) -> MovementOut:
    return MovementOut(
        id=row.id,
        kind=row.kind,
        quantity=row.quantity,
        comment=row.comment,
        employee_name=row.employee_name,
        created_at=row.created_at,
    )


@router.get("", response_model=list[SupplyOut])
async def supplies(
    session: SessionDep,
    employee: EmployeeDep,
    include_inactive: bool = False,
) -> list[SupplyOut]:
    rows = await hr_supplies.list_supplies(
        session, viewer=employee, include_inactive=include_inactive
    )
    return [_out(row) for row in rows]


@router.post("", response_model=SupplyOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: SupplyIn, session: SessionDep, employee: AupDep
) -> SupplyOut:
    try:
        row = await hr_supplies.create_supply(
            session,
            viewer=employee,
            name=body.name,
            unit=body.unit,
            quantity=body.quantity,
            min_quantity=body.min_quantity,
            department_id=body.department_id,
        )
    except hr_supplies.SupplyError as exc:
        raise _error(exc) from exc
    return _out(row)


@router.patch("/{supply_id}", response_model=SupplyOut)
async def patch(
    supply_id: int, body: SupplyPatchIn, session: SessionDep, employee: AupDep
) -> SupplyOut:
    try:
        row = await hr_supplies.update_supply(
            session,
            viewer=employee,
            supply_id=supply_id,
            name=body.name,
            unit=body.unit,
            min_quantity=body.min_quantity,
            is_active=body.is_active,
        )
    except hr_supplies.SupplyError as exc:
        raise _error(exc) from exc
    return _out(row)


@router.post("/{supply_id}/movements", response_model=MoveResultOut)
async def create_movement(
    supply_id: int, body: MoveIn, session: SessionDep, employee: EmployeeDep
) -> MoveResultOut:
    if body.kind == SUPPLY_IN and not hr_access.is_aup(employee):
        # Приход — это приёмка товара: сотрудник не может «положить на склад».
        # Списание остаётся ему доступным, иначе учёт снова станет устным.
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="in_forbidden")
    try:
        supply, movement = await hr_supplies.move(
            session,
            viewer=employee,
            supply_id=supply_id,
            kind=body.kind,
            quantity=body.quantity,
            comment=body.comment,
        )
    except hr_supplies.SupplyError as exc:
        raise _error(exc) from exc
    return MoveResultOut(supply=_out(supply), movement=_movement(movement))


@router.get("/{supply_id}/movements", response_model=list[MovementOut])
async def movements(
    supply_id: int,
    session: SessionDep,
    employee: EmployeeDep,
    limit: int = Query(50, ge=1, le=200),
) -> list[MovementOut]:
    try:
        rows = await hr_supplies.history(
            session, viewer=employee, supply_id=supply_id, limit=limit
        )
    except hr_supplies.SupplyError as exc:
        raise _error(exc) from exc
    return [_movement(row) for row in rows]


__all__ = ["router"]
