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
from sqlalchemy import select

from app.api.deps import AupDep, EmployeeDep, SessionDep
from app.db.hr_models import ROLE_ADMIN, ROLE_AUP, SUPPLY_IN, Employee
from app.services import hr_access, hr_notify, hr_supplies

router = APIRouter(prefix="/supplies", tags=["supplies"])


class SupplyOut(BaseModel):
    id: int
    name: str
    unit: str
    quantity: float
    min_quantity: float
    low: bool
    max_out_per_shift: float | None
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
    crossed_low: bool = False


class CountIn(BaseModel):
    quantity: float = Field(ge=0)
    comment: str | None = Field(default=None, max_length=250)


class CountOut(BaseModel):
    supply: SupplyOut
    delta: float
    movement: MovementOut | None = None


class DiscrepancyOut(BaseModel):
    supply_id: int
    supply_name: str
    unit: str
    delta: float
    comment: str | None
    employee_name: str | None
    created_at: datetime


class SupplyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(default="шт", max_length=16)
    quantity: float | None = 0
    min_quantity: float | None = 0
    max_out_per_shift: float | None = None
    department_id: int | None = None


class SupplyPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    unit: str | None = Field(default=None, max_length=16)
    min_quantity: float | None = None
    max_out_per_shift: float | None = None
    is_active: bool | None = None


class MoveIn(BaseModel):
    kind: str = Field(pattern="^(in|out)$")
    quantity: float
    comment: str | None = Field(default=None, max_length=300)


def _error(exc: hr_supplies.SupplyError) -> HTTPException:
    code = str(exc)
    if code == "supply_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    if code in ("not_enough", "limit_exceeded"):
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
        max_out_per_shift=row.max_out_per_shift,
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
            max_out_per_shift=body.max_out_per_shift,
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
            max_out_per_shift=body.max_out_per_shift,
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
        result = await hr_supplies.move(
            session,
            viewer=employee,
            supply_id=supply_id,
            kind=body.kind,
            quantity=body.quantity,
            comment=body.comment,
        )
    except hr_supplies.SupplyError as exc:
        raise _error(exc) from exc

    if result.crossed_low:
        # Одно событие на пересечение порога, а не на каждое списание: иначе
        # плашка «мало» превратится в шум и её перестанут читать.
        managers = list(
            await session.scalars(
                select(Employee).where(
                    Employee.org_id == employee.org_id,
                    Employee.role.in_((ROLE_AUP, ROLE_ADMIN)),
                    Employee.is_active.is_(True),
                    Employee.is_simulation.is_(False),
                )
            )
        )
        await hr_notify.push_event(
            session,
            employees=managers,
            title=f"Мало на складе: {result.supply.name}",
            body=f"Осталось {result.supply.quantity:g} {result.supply.unit}",
            url="/?open=supplies",
            tag=f"supply-low-{result.supply.id}",
        )
    return MoveResultOut(
        supply=_out(result.supply),
        movement=_movement(result.movement),
        crossed_low=result.crossed_low,
    )


@router.post("/{supply_id}/count", response_model=CountOut)
async def count(
    supply_id: int, body: CountIn, session: SessionDep, employee: AupDep
) -> CountOut:
    """Сверка: фактический остаток. Расхождение становится движением.

    Сверяет руководитель: это не работа смены, а контроль учёта. Сотрудник,
    который взял расходник, уже списал его обычным движением.
    """
    try:
        result = await hr_supplies.count_supply(
            session,
            viewer=employee,
            supply_id=supply_id,
            quantity=body.quantity,
            comment=body.comment,
        )
    except hr_supplies.SupplyError as exc:
        raise _error(exc) from exc
    return CountOut(
        supply=_out(result.supply),
        delta=result.delta,
        movement=_movement(result.movement) if result.movement else None,
    )


@router.get("/discrepancies", response_model=list[DiscrepancyOut])
async def discrepancies(
    session: SessionDep,
    employee: AupDep,
    days: int = Query(30, ge=1, le=180),
) -> list[DiscrepancyOut]:
    """Где учёт разошёлся с фактом за период."""
    rows = await hr_supplies.discrepancies(session, viewer=employee, days=days)
    return [
        DiscrepancyOut(
            supply_id=row.supply_id,
            supply_name=row.supply_name,
            unit=row.unit,
            delta=row.delta,
            comment=row.comment,
            employee_name=row.employee_name,
            created_at=row.created_at,
        )
        for row in rows
    ]


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
