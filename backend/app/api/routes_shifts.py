"""Табель смен: неделя отдела для сотрудника, все отделы — для управляющего.

Одна сетка отвечает на вопрос «кто когда работает»: сотрудник видит коллег
своего подразделения, руководитель и разработчик — все отделы с фильтром.
Правки (статус, часы, заметка, перенос) — только у управляющего.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
from app.services import hr_checklists, hr_settings, hr_shifts, hr_training_plan

router = APIRouter(tags=["shifts"])


class ShiftPersonOut(BaseModel):
    employee_id: int
    display_name: str
    position: str | None
    department_id: int | None
    department_name: str | None


class OnShiftPersonOut(ShiftPersonOut):
    """Смена сегодняшнего дня с состоянием на текущую минуту."""

    starts_at: str | None
    ends_at: str | None
    # on_shift — сейчас в смене, upcoming — ещё не началась, finished — кончилась,
    # planned — в графике без часов (такое бывает, когда часы не проставили).
    state: str


class OnShiftOut(BaseModel):
    now: datetime
    today: date
    on_shift: int
    items: list[OnShiftPersonOut]


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


class BulkShiftIn(BaseModel):
    """Шаблон недели / массовая правка: одна смена на много клеток сразу.

    `days` — конкретные даты, а не дни недели: фронтенд сам переводит
    «пн-ср» в числа выбранной недели, а сервер не угадывает часовой пояс.
    """

    employee_ids: list[int] = Field(
        min_length=1, max_length=hr_shifts.MAX_BULK_PEOPLE
    )
    days: list[date] = Field(min_length=1, max_length=hr_shifts.MAX_BULK_DAYS)
    status: str = Field(pattern="^(planned|worked|sick|absent|dayoff|vacation)$")
    starts_at: time | None = None
    ends_at: time | None = None
    note: str | None = Field(None, max_length=200)
    overwrite: bool = True


class CopyWeekIn(BaseModel):
    from_start: date
    to_start: date
    employee_ids: list[int] | None = Field(
        None, max_length=hr_shifts.MAX_BULK_PEOPLE
    )
    department_id: int | None = None
    overwrite: bool = False


class ClearCellsIn(BaseModel):
    employee_ids: list[int] = Field(
        min_length=1, max_length=hr_shifts.MAX_BULK_PEOPLE
    )
    days: list[date] = Field(min_length=1, max_length=hr_shifts.MAX_BULK_DAYS)


class BulkResultOut(BaseModel):
    saved: int
    skipped: int


class TemplateDayIn(BaseModel):
    """День шаблона: 0 = понедельник, время в «HH:MM» или ISO."""

    weekday: int = Field(ge=0, le=6)
    status: str = Field(pattern="^(planned|worked|sick|absent|dayoff|vacation)$")
    starts_at: time | None = None
    ends_at: time | None = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    # Общий шаблон, если отдел не задан.
    department_id: int | None = None
    days: list[TemplateDayIn] = Field(min_length=1, max_length=7)


class TemplateDayOut(BaseModel):
    """Время в ответе — строка «HH:MM»: так его сразу понимает `<input type=time>`."""

    weekday: int
    status: str
    starts_at: str | None
    ends_at: str | None


class TemplateOut(BaseModel):
    id: int
    name: str
    department_id: int | None
    department_name: str | None
    days: list[TemplateDayOut]


class ApplyTemplateIn(BaseModel):
    employee_ids: list[int] = Field(
        min_length=1, max_length=hr_shifts.MAX_BULK_PEOPLE
    )
    week_start: date
    overwrite: bool = False


def _shift_error(exc: hr_shifts.ShiftError) -> HTTPException:
    code = str(exc)
    if code in {
        "employee_not_found",
        "shift_not_found",
        "template_not_found",
        "department_not_found",
    }:
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


def _shift_state(
    starts_at: str | None, ends_at: str | None, minute_of_day: int
) -> str:
    """Состояние смены по часам. Вынесено из роута ради простого теста.

    `end` без `start` — тоже `planned`: без начала нельзя сказать, идёт смена
    или нет, и врать «в смене» хуже, чем показать «в графике».
    """
    start = _minutes(starts_at)
    end = _minutes(ends_at)
    if start is None:
        return "planned"
    if end is not None and minute_of_day > end:
        return "finished"
    if minute_of_day >= start:
        return "on_shift"
    return "upcoming"


def _minutes(hhmm: str | None) -> int | None:
    """«10:30» → 630. Мусор в базе не должен ронять панель."""
    if not hhmm:
        return None
    try:
        hours, minutes = hhmm.split(":", 1)
        hour, minute = int(hours), int(minutes)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute


@router.get("/shifts/on-shift", response_model=OnShiftOut)
async def shifts_on_shift(session: SessionDep, employee: EmployeeDep) -> OnShiftOut:
    """Кто на смене прямо сейчас — по видимому сотруднику табелю.

    Почему отдельная ручка, а не расчёт на клиенте. Правило видимости
    (свой отдел / все отделы), сегодняшняя дата и часовой пояс организации
    живут на сервере; клиент, считающий это сам, рано или поздно разойдётся с
    графиком и покажет соседа, который уже ушёл.

    «Сейчас» решается по часам смены, а не по отметке открытия чек-листа:
    отметка может отсутствовать (человек забыл), а график — единственный
    общий источник.
    """
    today = hr_checklists.local_today()
    moment = hr_settings.local_now()
    try:
        week = await hr_shifts.week(session, employee, start=today, end=today)
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc

    people = {person.employee_id: person for person in week.people}
    minute_of_day = moment.hour * 60 + moment.minute
    items: list[OnShiftPersonOut] = []
    for row in week.shifts:
        if row.day != today or row.status not in ("planned", "worked"):
            continue
        person = people.get(row.employee_id)
        if person is None:
            continue
        state = _shift_state(row.starts_at, row.ends_at, minute_of_day)
        items.append(
            OnShiftPersonOut(
                employee_id=person.employee_id,
                display_name=person.display_name,
                position=person.position,
                department_id=person.department_id,
                department_name=person.department_name,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                state=state,
            )
        )

    order = {"on_shift": 0, "upcoming": 1, "planned": 2, "finished": 3}
    items.sort(
        key=lambda item: (
            order.get(item.state, 9),
            item.starts_at or "99:99",
            item.display_name,
        )
    )
    return OnShiftOut(
        now=moment,
        today=today,
        on_shift=sum(1 for item in items if item.state == "on_shift"),
        items=items,
    )


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


def _template_out(template: hr_shifts.ShiftTemplate) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        department_id=template.department_id,
        department_name=template.department_name,
        days=[
            TemplateDayOut(
                weekday=day.weekday,
                status=day.status,
                starts_at=day.starts_at,
                ends_at=day.ends_at,
            )
            for day in template.days
        ],
    )


@router.get("/shifts/templates", response_model=list[TemplateOut])
async def list_shift_templates(
    session: SessionDep, employee: AupDep
) -> list[TemplateOut]:
    """Сохранённые шаблоны недели («официант 5/2», «бармен выходные»)."""
    try:
        items = await hr_shifts.templates(session, employee)
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return [_template_out(item) for item in items]


@router.post("/shifts/templates", response_model=TemplateOut)
async def save_shift_template(
    body: TemplateIn, session: SessionDep, employee: AupDep
) -> TemplateOut:
    """Сохранить рисунок недели. Одноимённый шаблон отдела перезаписывается."""
    try:
        saved = await hr_shifts.save_template(
            session,
            employee,
            name=body.name,
            department_id=body.department_id,
            raw_days=[
                {
                    "weekday": day.weekday,
                    "status": day.status,
                    "starts_at": day.starts_at,
                    "ends_at": day.ends_at,
                }
                for day in body.days
            ],
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return _template_out(saved)


@router.post("/shifts/templates/{template_id}/apply", response_model=BulkResultOut)
async def apply_shift_template(
    template_id: int,
    body: ApplyTemplateIn,
    session: SessionDep,
    employee: AupDep,
) -> BulkResultOut:
    """Разложить шаблон на неделю для выбранных людей."""
    try:
        result = await hr_shifts.apply_template(
            session,
            employee,
            template_id,
            employee_ids=body.employee_ids,
            week_start=body.week_start,
            overwrite=body.overwrite,
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return BulkResultOut(saved=result.saved, skipped=result.skipped)


@router.delete("/shifts/templates/{template_id}")
async def remove_shift_template(
    template_id: int, session: SessionDep, employee: AupDep
) -> dict[str, bool]:
    try:
        await hr_shifts.delete_template(session, employee, template_id)
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return {"removed": True}


@router.post("/shifts/bulk", response_model=BulkResultOut)
async def bulk_put_shifts(
    body: BulkShiftIn, session: SessionDep, employee: AupDep
) -> BulkResultOut:
    """Поставить одну смену сразу на несколько человек и дней (шаблон недели)."""
    try:
        result = await hr_shifts.bulk_apply(
            session,
            employee,
            employee_ids=body.employee_ids,
            days=body.days,
            status=body.status,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            note=body.note,
            overwrite=body.overwrite,
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return BulkResultOut(saved=result.saved, skipped=result.skipped)


@router.post("/shifts/copy-week", response_model=BulkResultOut)
async def copy_week_shifts(
    body: CopyWeekIn, session: SessionDep, employee: AupDep
) -> BulkResultOut:
    """Скопировать смены недели на другую неделю (день недели сохраняется)."""
    try:
        result = await hr_shifts.copy_week(
            session,
            employee,
            from_start=body.from_start,
            to_start=body.to_start,
            employee_ids=body.employee_ids,
            department_id=body.department_id,
            overwrite=body.overwrite,
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return BulkResultOut(saved=result.saved, skipped=result.skipped)


@router.post("/shifts/clear")
async def clear_shift_cells(
    body: ClearCellsIn, session: SessionDep, employee: AupDep
) -> dict[str, int]:
    """Массово снять смены с выбранных клеток (остальные дни не трогаем)."""
    try:
        removed = await hr_shifts.clear_cells(
            session,
            employee,
            employee_ids=body.employee_ids,
            days=body.days,
        )
    except hr_shifts.ShiftError as exc:
        raise _shift_error(exc) from exc
    return {"removed": removed}


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
