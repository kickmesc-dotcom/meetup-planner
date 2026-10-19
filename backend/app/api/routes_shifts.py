"""Табель смен: неделя отдела для сотрудника, все отделы — для управляющего.

Одна сетка отвечает на вопрос «кто когда работает»: сотрудник видит коллег
своего подразделения, руководитель и разработчик — все отделы с фильтром.
Правки (статус, часы, заметка, перенос) — только у управляющего.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AupDep, EmployeeDep, SessionDep
from app.db.hr_models import (
    SHIFT_LABELS,
    SHIFT_SHORT,
    SHIFT_STATUSES,
    Department,
    Employee,
)
from app.services import hr_shifts, hr_training_plan

router = APIRouter(tags=["shifts"])


class ShiftPersonOut(BaseModel):
    employee_id: int
    display_name: str
    position: str | None
    department_id: int | None
    department_name: str | None


class ShiftOut(BaseModel):
    id: int
    employee_id: int
    day: date
    status: str
    status_label: str
    short: str
    starts_at: str | None
    ends_at: str | None
    note: str | None
    moved_from: date | None
    is_training: bool


class DepartmentBriefOut(BaseModel):
    id: int
    name: str


class ShiftStatusOut(BaseModel):
    value: str
    label: str
    short: str


class ShiftWeekOut(BaseModel):
    start: date
    end: date
    today: date
    can_edit: bool
    statuses: list[ShiftStatusOut]
    departments: list[DepartmentBriefOut]
    people: list[ShiftPersonOut]
    shifts: list[ShiftOut]


class ShiftIn(BaseModel):
    status: str = Field(pattern="^(planned|worked|sick|absent|dayoff|vacation)$")
    starts_at: time | None = None
    ends_at: time | None = None
    note: str | None = Field(None, max_length=200)


class ShiftMoveIn(BaseModel):
    day: date


def _shift_error(exc: hr_shifts.ShiftError) -> HTTPException:
    code = str(exc)
    if code in {"employee_not_found", "shift_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=code)
    if code == "forbidden":
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=code)
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=code)


def _shift_out(
    row: hr_shifts.ShiftRow, flags: dict[date, bool] | None
) -> ShiftOut:
    return ShiftOut(
        id=row.id,
        employee_id=row.employee_id,
        day=row.day,
        status=row.status,
        status_label=SHIFT_LABELS.get(row.status, row.status),
        short=SHIFT_SHORT.get(row.status, "?"),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        note=row.note,
        moved_from=row.moved_from,
        is_training=bool(flags and flags.get(row.day)),
    )


async def _flags(
    session: AsyncSession,
    ids: list[int],
    *,
    start: date,
    end: date,
) -> dict[int, dict[date, bool]]:
    """Учебные смены по табелю — чтобы сетка и план говорили одно и то же."""
    if not ids:
        return {}
    employees = list(
        (await session.scalars(select(Employee).where(Employee.id.in_(ids)))).all()
    )
    return await hr_training_plan.day_flags(session, employees, start=start, end=end)


@router.get("/shifts", response_model=ShiftWeekOut)
async def shifts_week(
    session: SessionDep,
    employee: EmployeeDep,
    start: Annotated[date | None, Query()] = None,
    days: Annotated[int, Query(ge=1, le=31)] = 7,
    department_id: Annotated[int | None, Query()] = None,
) -> ShiftWeekOut:
    """Сетка табеля на неделю (или другой короткий период)."""
    first = start or _week_start()
    last = first + timedelta(days=max(1, min(days, 31)) - 1)
    try:
        week = await hr_shifts.week(
            session,
            employee,
            start=first,
            end=last,
            department_id=department_id,
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    flags = await _flags(
        session,
        [person.employee_id for person in week.people],
        start=first,
        end=last,
    )
    departments = (
        list(
            (
                await session.execute(
                    select(Department.id, Department.name).order_by(Department.name)
                )
            ).all()
        )
        if hr_shifts.can_edit(employee)
        else []
    )
    return ShiftWeekOut(
        start=first,
        end=last,
        today=hr_training_plan.today(),
        can_edit=hr_shifts.can_edit(employee),
        statuses=[
            ShiftStatusOut(
                value=value,
                label=SHIFT_LABELS[value],
                short=SHIFT_SHORT[value],
            )
            for value in SHIFT_STATUSES
        ],
        departments=[
            DepartmentBriefOut(id=int(dep_id), name=str(name))
            for dep_id, name in departments
        ],
        people=[
            ShiftPersonOut(
                employee_id=person.employee_id,
                display_name=person.display_name,
                position=person.position,
                department_id=person.department_id,
                department_name=person.department_name,
            )
            for person in week.people
        ],
        shifts=[
            _shift_out(row, flags.get(row.employee_id))
            for row in week.shifts
        ],
    )


def _week_start() -> date:
    """Понедельник текущей недели по часовому поясу ресторана."""
    moment = hr_training_plan.today()
    return moment - timedelta(days=moment.weekday())


@router.put("/shifts/{employee_id}/{day}", response_model=ShiftOut)
async def put_shift(
    employee_id: int,
    day: date,
    body: ShiftIn,
    session: SessionDep,
    employee: AupDep,
) -> ShiftOut:
    """Поставить или поправить смену сотрудника в конкретный день."""
    try:
        row = await hr_shifts.upsert_shift(
            session,
            employee,
            employee_id=employee_id,
            day=day,
            status=body.status,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            note=body.note,
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    flags = await _flags(session, [employee_id], start=day, end=day)
    return _shift_out(row, flags.get(employee_id))


@router.post("/shifts/{shift_id}/move", response_model=ShiftOut)
async def move_shift(
    shift_id: int,
    body: ShiftMoveIn,
    session: SessionDep,
    employee: AupDep,
) -> ShiftOut:
    """Перенести смену на другую дату (с занятостью и историей)."""
    try:
        row = await hr_shifts.move_shift(
            session, employee, shift_id, day=body.day
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    flags = await _flags(session, [row.employee_id], start=row.day, end=row.day)
    return _shift_out(row, flags.get(row.employee_id))


@router.delete("/shifts/{shift_id}")
async def remove_shift(
    shift_id: int, session: SessionDep, employee: AupDep
) -> dict[str, bool]:
    """Удалить смену из табеля."""
    try:
        await hr_shifts.delete_shift(session, employee, shift_id)
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return {"removed": True}


__all__ = ["router"]
