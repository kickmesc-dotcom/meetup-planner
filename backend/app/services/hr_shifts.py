"""Табель смен: кто в какой день работает, болеет или отдыхает.

Раньше «смена» в системе была только датой чек-листа и поручений. Из-за этого
нельзя было ответить на простые вопросы: кто выходит завтра, почему у новичка
«сгорела» учебная смена, куда переехала смена после переноса. Теперь на каждый
день есть строка `HrShift` со статусом.

Правила:

* сотрудник видит смены своего подразделения (read-only);
* управляющий и разработчик/админ — все подразделения, с фильтром по отделу;
* статусы: `planned`, `worked`, `sick`, `absent`, `dayoff`, `vacation`;
* перенос — это update даты с проверкой занятости; `moved_from` хранит исходный
  день, чтобы история не терялась.

Учебные смены считает `hr_training_plan` по `worked`: табель — источник правды,
а не календарь.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    SHIFT_LABELS,
    SHIFT_SHORT,
    SHIFT_STATUSES,
    Department,
    Employee,
    HrShift,
)
from app.db.models import User
from app.services import hr_access


class ShiftError(Exception):
    """Ошибка операции с табелем (текст — код для клиента)."""


@dataclass(frozen=True)
class ShiftPerson:
    employee_id: int
    display_name: str
    position: str | None
    department_id: int | None
    department_name: str | None


@dataclass(frozen=True)
class ShiftRow:
    id: int
    employee_id: int
    day: date
    status: str
    starts_at: str | None
    ends_at: str | None
    note: str | None
    moved_from: date | None


@dataclass(frozen=True)
class ShiftWeek:
    people: tuple[ShiftPerson, ...]
    shifts: tuple[ShiftRow, ...]


def can_edit(viewer: Employee) -> bool:
    """Править табель может руководитель и выше, смотреть — любой сотрудник."""
    return hr_access.is_aup(viewer)


def _fmt_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _row(row: HrShift) -> ShiftRow:
    return ShiftRow(
        id=int(row.id),
        employee_id=int(row.employee_id),
        day=row.day,
        status=str(row.status),
        starts_at=_fmt_time(row.starts_at),
        ends_at=_fmt_time(row.ends_at),
        note=row.note,
        moved_from=row.moved_from,
    )


async def week(
    session: AsyncSession,
    viewer: Employee,
    *,
    start: date,
    end: date,
    department_id: int | None = None,
) -> ShiftWeek:
    """Люди и их смены за период. Сотруднику — только своё подразделение."""
    if end < start:
        raise ShiftError("bad_range")
    people_stmt = (
        select(Employee, User.display_name, Department.name)
        .join(User, User.id == Employee.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .where(
            Employee.is_simulation.is_(False),
            Employee.fired_at.is_(None),
            Employee.is_active.is_(True),
        )
        .order_by(Department.name, User.display_name)
    )
    if not hr_access.is_aup(viewer):
        people_stmt = people_stmt.where(Employee.department_id == viewer.department_id)
    elif department_id is not None:
        people_stmt = people_stmt.where(Employee.department_id == department_id)
    rows = (await session.execute(people_stmt)).all()
    people = tuple(
        ShiftPerson(
            employee_id=int(employee.id),
            display_name=str(name),
            position=employee.position,
            department_id=employee.department_id,
            department_name=str(dept) if dept else None,
        )
        for employee, name, dept in rows
    )
    ids = [person.employee_id for person in people]
    if not ids:
        return ShiftWeek(people=(), shifts=())
    shifts = [
        _row(row)
        for row in (
            await session.scalars(
                select(HrShift)
                .where(
                    HrShift.employee_id.in_(ids),
                    HrShift.day >= start,
                    HrShift.day <= end,
                )
                .order_by(HrShift.day)
            )
        ).all()
    ]
    return ShiftWeek(people=people, shifts=tuple(shifts))


async def _employee_for_shift(
    session: AsyncSession, employee_id: int
) -> Employee:
    employee = await session.get(Employee, int(employee_id))
    if (
        employee is None
        or employee.is_simulation
        or employee.fired_at is not None
        or not employee.is_active
    ):
        raise ShiftError("employee_not_found")
    return employee


async def upsert_shift(
    session: AsyncSession,
    viewer: Employee,
    *,
    employee_id: int,
    day: date,
    status: str,
    starts_at: time | None = None,
    ends_at: time | None = None,
    note: str | None = None,
) -> ShiftRow:
    """Поставить или поправить смену. Повторный вызов на тот же день — правка."""
    if not can_edit(viewer):
        raise ShiftError("forbidden")
    if status not in SHIFT_STATUSES:
        raise ShiftError("bad_status")
    employee = await _employee_for_shift(session, employee_id)
    clean_note = (note or "").strip()
    if len(clean_note) > 200:
        raise ShiftError("note_too_long")
    row = await session.scalar(
        select(HrShift).where(
            HrShift.employee_id == int(employee.id), HrShift.day == day
        )
    )
    if row is None:
        row = HrShift(
            employee_id=int(employee.id),
            day=day,
            created_by_id=int(viewer.id),
        )
        session.add(row)
    row.status = status
    row.starts_at = starts_at
    row.ends_at = ends_at
    row.note = clean_note or None
    await session.commit()
    await session.refresh(row)
    return _row(row)


async def move_shift(
    session: AsyncSession,
    viewer: Employee,
    shift_id: int,
    *,
    day: date,
) -> ShiftRow:
    """Перенести смену на другой день. Два смены в один день не слипаются."""
    if not can_edit(viewer):
        raise ShiftError("forbidden")
    row = await session.get(HrShift, int(shift_id))
    if row is None:
        raise ShiftError("shift_not_found")
    if day == row.day:
        return _row(row)
    taken = await session.scalar(
        select(HrShift.id).where(
            HrShift.employee_id == int(row.employee_id),
            HrShift.day == day,
        )
    )
    if taken is not None:
        raise ShiftError("day_taken")
    row.moved_from = row.moved_from or row.day
    row.day = day
    await session.commit()
    await session.refresh(row)
    return _row(row)


async def delete_shift(session: AsyncSession, viewer: Employee, shift_id: int) -> None:
    if not can_edit(viewer):
        raise ShiftError("forbidden")
    result = await session.execute(delete(HrShift).where(HrShift.id == int(shift_id)))
    if not result.rowcount:
        raise ShiftError("shift_not_found")
    await session.commit()


__all__ = [
    "SHIFT_LABELS",
    "SHIFT_SHORT",
    "SHIFT_STATUSES",
    "ShiftError",
    "ShiftPerson",
    "ShiftRow",
    "ShiftWeek",
    "can_edit",
    "delete_shift",
    "move_shift",
    "upsert_shift",
    "week",
]
