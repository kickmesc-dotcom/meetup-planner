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

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta

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


@dataclass(frozen=True)
class BulkResult:
    """Итог массовой операции: сколько клеток записано и сколько не тронуто."""

    saved: int
    skipped: int


# Сетка табеля — это максимум 31 день × 200 человек. Ограничения не
# бюрократия: без них один запрос мог бы переписать весь год всему штату.
MAX_BULK_DAYS = 31
MAX_BULK_PEOPLE = 200


def can_edit(viewer: Employee) -> bool:
    """Править табель может руководитель и выше, смотреть — любой сотрудник."""
    return hr_access.is_aup(viewer)


def bulk_days(days: Iterable[date]) -> tuple[date, ...]:
    """Набор дней для массовой операции: без дублей, по порядку, не больше месяца."""
    unique = sorted(set(days))
    if not unique or len(unique) > MAX_BULK_DAYS:
        raise ShiftError("bad_days")
    return tuple(unique)


def weekdays_days(week_start: date, weekdays: Iterable[int]) -> tuple[date, ...]:
    """Шаблон недели: 0 = понедельник … 6 = воскресенье → даты этой недели.

    Дни вне диапазона отбрасываются: шаблон приходит из интерфейса, и лишняя
    цифра не должна превращаться в смену в следующем месяце.
    """
    picked = {
        week_start + timedelta(days=offset)
        for offset in weekdays
        if 0 <= offset <= 6
    }
    return bulk_days(picked)


def _clean_note(note: str | None) -> str | None:
    clean = (note or "").strip()
    if len(clean) > 200:
        raise ShiftError("note_too_long")
    return clean or None


def _check_bulk(
    status: str, employee_ids: Sequence[int], days: Sequence[date], note: str | None
) -> None:
    """Проверки до похода в базу: дешёвые и одинаковые для всех массовых ручек."""
    if status not in SHIFT_STATUSES:
        raise ShiftError("bad_status")
    if not employee_ids:
        raise ShiftError("no_employees")
    if len(set(employee_ids)) > MAX_BULK_PEOPLE:
        raise ShiftError("too_many_employees")
    if not days:
        raise ShiftError("bad_days")
    _clean_note(note)


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


async def bulk_apply(
    session: AsyncSession,
    viewer: Employee,
    *,
    employee_ids: Sequence[int],
    days: Sequence[date],
    status: str,
    starts_at: time | None = None,
    ends_at: time | None = None,
    note: str | None = None,
    overwrite: bool = True,
) -> BulkResult:
    """Шаблон недели и массовые правки: одна смена сразу на много клеток.

    `overwrite=False` — режим «не трогать уже заполненное»: так шаблон можно
    накатить поверх черновика и не потерять то, что руководитель уже поставил
    руками. По умолчанию перезаписываем: человек явно выбрал клетки.
    """
    if not can_edit(viewer):
        raise ShiftError("forbidden")
    clean_days = bulk_days(days)
    people = sorted({int(value) for value in employee_ids})
    _check_bulk(status, people, clean_days, note)
    clean_note = _clean_note(note)

    # Люди — одним запросом: иначе 200 человек × 7 дней давали бы 200 запросов.
    found = {
        int(row)
        for row in (
            await session.scalars(
                select(Employee.id).where(
                    Employee.id.in_(people),
                    Employee.is_simulation.is_(False),
                    Employee.fired_at.is_(None),
                    Employee.is_active.is_(True),
                )
            )
        ).all()
    }
    if found != set(people):
        raise ShiftError("employee_not_found")

    existing = {
        (int(row.employee_id), row.day): row
        for row in (
            await session.scalars(
                select(HrShift).where(
                    HrShift.employee_id.in_(people),
                    HrShift.day.in_(clean_days),
                )
            )
        ).all()
    }

    saved = 0
    skipped = 0
    for employee_id in people:
        for day in clean_days:
            row = existing.get((employee_id, day))
            if row is None:
                row = HrShift(
                    employee_id=employee_id,
                    day=day,
                    created_by_id=int(viewer.id),
                )
                session.add(row)
                existing[(employee_id, day)] = row
            elif not overwrite:
                skipped += 1
                continue
            row.status = status
            row.starts_at = starts_at
            row.ends_at = ends_at
            row.note = clean_note
            saved += 1
    if saved:
        await session.commit()
    return BulkResult(saved=saved, skipped=skipped)


async def copy_week(
    session: AsyncSession,
    viewer: Employee,
    *,
    from_start: date,
    to_start: date,
    employee_ids: Sequence[int] | None = None,
    department_id: int | None = None,
    overwrite: bool = False,
) -> BulkResult:
    """Скопировать неделю на неделю: каждый день переезжает на тот же день недели.

    По умолчанию существующие смены не затираются — копирование заполняет
    пустые клетки, а не сюрпризы в готовом графике. Часы, статус и заметка
    сохраняются; `moved_from` не копируется — это история исходной строки.
    """
    if not can_edit(viewer):
        raise ShiftError("forbidden")
    if from_start == to_start:
        raise ShiftError("same_week")
    offset = (to_start - from_start).days
    source_end = from_start + timedelta(days=6)
    target_end = to_start + timedelta(days=6)

    people_stmt = select(Employee.id).where(
        Employee.is_simulation.is_(False),
        Employee.fired_at.is_(None),
        Employee.is_active.is_(True),
    )
    if employee_ids:
        ids = sorted({int(value) for value in employee_ids})
        if len(ids) > MAX_BULK_PEOPLE:
            raise ShiftError("too_many_employees")
        people_stmt = people_stmt.where(Employee.id.in_(ids))
    elif department_id is not None:
        people_stmt = people_stmt.where(Employee.department_id == department_id)
    people = [int(row) for row in (await session.scalars(people_stmt)).all()]
    if not people:
        raise ShiftError("no_employees")

    source = list(
        (
            await session.scalars(
                select(HrShift).where(
                    HrShift.employee_id.in_(people),
                    HrShift.day >= from_start,
                    HrShift.day <= source_end,
                )
            )
        ).all()
    )
    if not source:
        return BulkResult(saved=0, skipped=0)

    existing = {
        (int(row.employee_id), row.day): row
        for row in (
            await session.scalars(
                select(HrShift).where(
                    HrShift.employee_id.in_(people),
                    HrShift.day >= to_start,
                    HrShift.day <= target_end,
                )
            )
        ).all()
    }

    saved = 0
    skipped = 0
    for row in source:
        target = row.day + timedelta(days=offset)
        key = (int(row.employee_id), target)
        target_row = existing.get(key)
        if target_row is None:
            target_row = HrShift(
                employee_id=int(row.employee_id),
                day=target,
                created_by_id=int(viewer.id),
            )
            session.add(target_row)
            existing[key] = target_row
        elif not overwrite:
            skipped += 1
            continue
        target_row.status = row.status
        target_row.starts_at = row.starts_at
        target_row.ends_at = row.ends_at
        target_row.note = row.note
        saved += 1
    if saved:
        await session.commit()
    return BulkResult(saved=saved, skipped=skipped)


async def clear_cells(
    session: AsyncSession,
    viewer: Employee,
    *,
    employee_ids: Sequence[int],
    days: Sequence[date],
) -> int:
    """Массовая очистка: снять смены с набора клеток, не трогая остальные дни."""
    if not can_edit(viewer):
        raise ShiftError("forbidden")
    clean_days = bulk_days(days)
    people = sorted({int(value) for value in employee_ids})
    if not people:
        raise ShiftError("no_employees")
    if len(people) > MAX_BULK_PEOPLE:
        raise ShiftError("too_many_employees")
    result = await session.execute(
        delete(HrShift).where(
            HrShift.employee_id.in_(people), HrShift.day.in_(clean_days)
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


__all__ = [
    "MAX_BULK_DAYS",
    "MAX_BULK_PEOPLE",
    "SHIFT_LABELS",
    "SHIFT_SHORT",
    "SHIFT_STATUSES",
    "BulkResult",
    "ShiftError",
    "ShiftPerson",
    "ShiftRow",
    "ShiftWeek",
    "bulk_apply",
    "bulk_days",
    "can_edit",
    "clear_cells",
    "copy_week",
    "delete_shift",
    "move_shift",
    "upsert_shift",
    "week",
    "weekdays_days",
]
