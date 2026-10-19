"""Расписание учебных и обычных смен плюс ставка сотрудника.

Зачем отдельный сервис: «учимся вместе» было одним флагом на профиль, и
управляющий не мог сказать «сегодня ещё учебная смена, а завтра уже обычная».
Теперь план считается по дням:

* по умолчанию учебные — первые `Employee.training_days` дней после `hire_date`;
* точечная строка `EmployeeTrainingDay` сильнее правила (учебная четвёртая
  смена или обычная третья);
* ставка (`full` / `partial`) живёт рядом, в той же карточке.

План только описывает смену: обязательные чек-листы, поручения и уведомления
работают одинаково в учебный и обычный день.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    ONBOARDING_DONE,
    RATE_FULL,
    RATE_PARTIAL,
    RATES,
    SHIFT_PLANNED,
    SHIFT_WORKED,
    Department,
    Employee,
    EmployeeTrainingDay,
    HrShift,
)
from app.db.models import User
from app.services import hr_access, hr_admin_ops

DEFAULT_TRAINING_DAYS = 3
MAX_TRAINING_DAYS = 30
DEFAULT_HORIZON_DAYS = 14
MAX_HORIZON_DAYS = 60
PLAN_LIMIT = 200

RATE_LABELS: dict[str, str] = {
    RATE_FULL: "Полная ставка",
    RATE_PARTIAL: "Частичная ставка",
}


class PlanError(Exception):
    """Ошибка операции с планом (текст — код для клиента)."""


@dataclass(frozen=True)
class PlanDay:
    day: date
    is_training: bool
    # Время задано вручную, а не выведено из `hire_date`/`training_days`.
    explicit: bool
    # Смена в табеле на этот день (None — строки нет).
    shift_status: str | None = None


@dataclass(frozen=True)
class ShiftMark:
    """Что табель говорит про день: статус и учебная ли это смена."""

    status: str
    is_training: bool


@dataclass(frozen=True)
class EmployeePlan:
    employee_id: int
    user_id: int
    display_name: str
    position: str | None
    department_name: str | None
    role: str
    onboarding_state: str
    learning_mode: bool
    rate_type: str
    training_days: int
    hire_date: date | None
    # В табеле есть хотя бы одна смена: значит, считаем по факту, а не по
    # календарю. Пусто — старый расчёт до появления табеля.
    has_shifts: bool
    days: tuple[PlanDay, ...]


def today() -> date:
    """Сегодняшняя дата по часовому поясу ресторана, а не машины."""
    return datetime.now(ZoneInfo(get_settings().scheduler_tz)).date()


def clamp_training_days(value: int) -> int:
    return max(0, min(int(value), MAX_TRAINING_DAYS))


def clamp_horizon(value: int) -> int:
    return max(1, min(int(value), MAX_HORIZON_DAYS))


def default_is_training(employee: Employee, day: date) -> bool:
    """Учебная ли смена по правилу «первые N дней после найма».

    Без `hire_date` опираемся на старый флаг `learning_mode`: так ведут себя
    профили, заведённые до появления плана, и теневые сотрудники проверки.
    """
    if employee.hire_date is None:
        return bool(employee.learning_mode)
    offset = (day - employee.hire_date).days
    return 0 <= offset < clamp_training_days(int(employee.training_days))


def build_days(
    employee: Employee,
    *,
    start: date,
    days: int,
    overrides: dict[date, bool],
    marks: dict[date, ShiftMark] | None = None,
) -> tuple[PlanDay, ...]:
    """Полоса дней: ручное правило → табель → календарный расчёт.

    `marks is None` означает «в табеле нет ни одной смены»: только тогда
    включается старый расчёт по дате найма. Как только табель заполнен, день
    без смены — не учебный, даже если календарь говорил обратное.
    """
    out: list[PlanDay] = []
    for index in range(clamp_horizon(days)):
        day = start + timedelta(days=index)
        mark = marks.get(day) if marks is not None else None
        if day in overrides:
            is_training = overrides[day]
            explicit = True
        elif marks is not None:
            is_training = mark.is_training if mark else False
            explicit = False
        else:
            is_training = default_is_training(employee, day)
            explicit = False
        out.append(
            PlanDay(
                day=day,
                is_training=is_training,
                explicit=explicit,
                shift_status=mark.status if mark else None,
            )
        )
    return tuple(out)


def _sees_all(viewer: Employee) -> bool:
    return hr_access.is_admin(viewer) or viewer.department_id is None


async def _overrides(
    session: AsyncSession,
    employee_ids: list[int],
    *,
    start: date,
    end: date,
) -> dict[int, dict[date, bool]]:
    if not employee_ids:
        return {}
    rows = (
        await session.execute(
            select(
                EmployeeTrainingDay.employee_id,
                EmployeeTrainingDay.day,
                EmployeeTrainingDay.is_training,
            ).where(
                EmployeeTrainingDay.employee_id.in_(employee_ids),
                EmployeeTrainingDay.day >= start,
                EmployeeTrainingDay.day <= end,
            )
        )
    ).all()
    out: dict[int, dict[date, bool]] = {}
    for employee_id, day, is_training in rows:
        out.setdefault(int(employee_id), {})[day] = bool(is_training)
    return out


async def shift_marks(
    session: AsyncSession,
    employees: list[Employee],
    *,
    start: date,
    end: date,
) -> dict[int, dict[date, ShiftMark]]:
    """Учебность по табелю: первые N **отработанных** смен.

    Прошлые дни считаются только по `worked`: если смену не отметили, она не
    съедает учебную. Будущие `planned` участвуют как прогноз — иначе новый
    сотрудник не увидел бы, что завтра его ждёт учебная смена.

    Пустой словарь для сотрудника = в табеле нет ни одной строки; вызывающий
    тогда включает календарный расчёт до появления табеля.
    """
    if not employees:
        return {}
    ids = [int(employee.id) for employee in employees]
    rows = (
        await session.execute(
            select(HrShift.employee_id, HrShift.day, HrShift.status)
            .where(
                HrShift.employee_id.in_(ids),
                HrShift.day <= end,
            )
            .order_by(HrShift.employee_id, HrShift.day)
        )
    ).all()
    grouped: dict[int, list[tuple[date, str]]] = {}
    for employee_id, day, status in rows:
        grouped.setdefault(int(employee_id), []).append((day, str(status)))
    moment = today()
    out: dict[int, dict[date, ShiftMark]] = {}
    for employee in employees:
        history = grouped.get(int(employee.id))
        if not history:
            continue
        limit = clamp_training_days(int(employee.training_days))
        ordinal = 0
        marks: dict[date, ShiftMark] = {}
        for day, status in history:
            counts = status == SHIFT_WORKED or (
                day >= moment and status == SHIFT_PLANNED
            )
            if counts:
                ordinal += 1
            if start <= day <= end:
                marks[day] = ShiftMark(
                    status=status,
                    is_training=bool(counts) and ordinal <= limit,
                )
        out[int(employee.id)] = marks
    return out


async def day_flags(
    session: AsyncSession,
    employees: list[Employee],
    *,
    start: date,
    end: date,
) -> dict[int, dict[date, bool]]:
    """Итоговый флаг «учебная смена» по дням: правило → табель → ручная точка.

    Нужен там, где показывают не только план, но и сам табель: одна и та же
    смена не должна называться учебной на одном экране и обычной на другом.
    """
    ids = [int(employee.id) for employee in employees]
    overrides = await _overrides(session, ids, start=start, end=end)
    marks_by = await shift_marks(session, employees, start=start, end=end)
    out: dict[int, dict[date, bool]] = {}
    for employee in employees:
        employee_id = int(employee.id)
        manual = overrides.get(employee_id, {})
        marks = marks_by.get(employee_id)
        flags: dict[date, bool] = {}
        for index in range((end - start).days + 1):
            day = start + timedelta(days=index)
            if day in manual:
                flags[day] = manual[day]
            elif marks is not None:
                mark = marks.get(day)
                flags[day] = bool(mark and mark.is_training)
            else:
                flags[day] = default_is_training(employee, day)
        out[employee_id] = flags
    return out


async def plans(
    session: AsyncSession,
    viewer: Employee,
    *,
    days: int = DEFAULT_HORIZON_DAYS,
    start: date | None = None,
) -> list[EmployeePlan]:
    """Планы сотрудников в области видимости, новички — первыми."""
    horizon = clamp_horizon(days)
    first = start or today()
    stmt = (
        select(Employee, User.display_name, Department.name)
        .join(User, User.id == Employee.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .where(
            Employee.is_simulation.is_(False),
            Employee.fired_at.is_(None),
            Employee.is_active.is_(True),
        )
        .order_by(
            (Employee.onboarding_state == ONBOARDING_DONE).asc(),
            Employee.hire_date.desc().nullslast(),
            User.display_name,
        )
        .limit(PLAN_LIMIT)
    )
    if not _sees_all(viewer):
        stmt = stmt.where(Employee.department_id == viewer.department_id)
    rows = (await session.execute(stmt)).all()
    ids = [int(employee.id) for employee, _name, _dept in rows]
    last = first + timedelta(days=horizon - 1)
    overrides = await _overrides(session, ids, start=first, end=last)
    marks_by = await shift_marks(
        session, [employee for employee, _name, _dept in rows], start=first, end=last
    )
    return [
        EmployeePlan(
            employee_id=int(employee.id),
            user_id=int(employee.user_id),
            display_name=str(name),
            position=employee.position,
            department_name=str(dept) if dept else None,
            role=str(employee.role),
            onboarding_state=str(employee.onboarding_state),
            learning_mode=bool(employee.learning_mode),
            rate_type=str(employee.rate_type or RATE_FULL),
            training_days=int(employee.training_days or 0),
            hire_date=employee.hire_date,
            has_shifts=int(employee.id) in marks_by,
            days=build_days(
                employee,
                start=first,
                days=horizon,
                overrides=overrides.get(int(employee.id), {}),
                marks=marks_by.get(int(employee.id)),
            ),
        )
        for employee, name, dept in rows
    ]


async def plan_for(
    session: AsyncSession,
    viewer: Employee,
    employee_id: int,
    *,
    days: int = DEFAULT_HORIZON_DAYS,
    start: date | None = None,
) -> EmployeePlan:
    employee = await hr_admin_ops.employee_in_scope(session, viewer, employee_id)
    horizon = clamp_horizon(days)
    first = start or today()
    user = await session.get(User, int(employee.user_id))
    dept = (
        await session.get(Department, int(employee.department_id))
        if employee.department_id is not None
        else None
    )
    last = first + timedelta(days=horizon - 1)
    overrides = await _overrides(session, [int(employee.id)], start=first, end=last)
    marks_by = await shift_marks(session, [employee], start=first, end=last)
    return EmployeePlan(
        employee_id=int(employee.id),
        user_id=int(employee.user_id),
        display_name=str(user.display_name) if user and user.display_name else "—",
        position=employee.position,
        department_name=str(dept.name) if dept else None,
        role=str(employee.role),
        onboarding_state=str(employee.onboarding_state),
        learning_mode=bool(employee.learning_mode),
        rate_type=str(employee.rate_type or RATE_FULL),
        training_days=int(employee.training_days or 0),
        hire_date=employee.hire_date,
        has_shifts=int(employee.id) in marks_by,
        days=build_days(
            employee,
            start=first,
            days=horizon,
            overrides=overrides.get(int(employee.id), {}),
            marks=marks_by.get(int(employee.id)),
        ),
    )


async def update_plan(
    session: AsyncSession,
    viewer: Employee,
    employee_id: int,
    *,
    rate_type: str | None = None,
    training_days: int | None = None,
) -> EmployeePlan:
    """Ставка и «сколько первых смен учебные». Дни не переписываем списком."""
    employee = await hr_admin_ops.employee_in_scope(session, viewer, employee_id)
    changed = False
    if rate_type is not None:
        if rate_type not in RATES:
            raise PlanError("bad_rate")
        employee.rate_type = rate_type
        changed = True
    if training_days is not None:
        employee.training_days = clamp_training_days(training_days)
        changed = True
    if changed:
        await session.commit()
    return await plan_for(session, viewer, employee_id)


async def set_day(
    session: AsyncSession,
    viewer: Employee,
    employee_id: int,
    day: date,
    *,
    is_training: bool,
) -> PlanDay:
    """Сделать конкретную смену учебной или обычной."""
    employee = await hr_admin_ops.employee_in_scope(session, viewer, employee_id)
    row = await session.scalar(
        select(EmployeeTrainingDay).where(
            EmployeeTrainingDay.employee_id == int(employee.id),
            EmployeeTrainingDay.day == day,
        )
    )
    if row is None:
        row = EmployeeTrainingDay(
            employee_id=int(employee.id),
            day=day,
            is_training=is_training,
            set_by_id=int(viewer.id),
        )
        session.add(row)
    else:
        row.is_training = is_training
        row.set_by_id = int(viewer.id)
    await session.commit()
    return PlanDay(day=day, is_training=is_training, explicit=True)


async def clear_day(
    session: AsyncSession, viewer: Employee, employee_id: int, day: date
) -> None:
    """Вернуть день к правилу «первые N смен после найма»."""
    employee = await hr_admin_ops.employee_in_scope(session, viewer, employee_id)
    await session.execute(
        delete(EmployeeTrainingDay).where(
            EmployeeTrainingDay.employee_id == int(employee.id),
            EmployeeTrainingDay.day == day,
        )
    )
    await session.commit()


async def today_is_training(session: AsyncSession, employee: Employee) -> bool:
    """Учебная ли у сотрудника сегодняшняя смена (по табелю, если он есть)."""
    day = today()
    override = await session.scalar(
        select(EmployeeTrainingDay.is_training).where(
            EmployeeTrainingDay.employee_id == int(employee.id),
            EmployeeTrainingDay.day == day,
        )
    )
    if override is not None:
        return bool(override)
    marks = await shift_marks(session, [employee], start=day, end=day)
    if int(employee.id) in marks:
        mark = marks[int(employee.id)].get(day)
        return bool(mark and mark.is_training)
    return default_is_training(employee, day)


async def week_preview(
    session: AsyncSession, employee: Employee, *, days: int = 7
) -> tuple[PlanDay, ...]:
    first = today()
    last = first + timedelta(days=clamp_horizon(days) - 1)
    overrides = await _overrides(session, [int(employee.id)], start=first, end=last)
    marks = await shift_marks(session, [employee], start=first, end=last)
    return build_days(
        employee,
        start=first,
        days=days,
        overrides=overrides.get(int(employee.id), {}),
        marks=marks.get(int(employee.id)),
    )


__all__ = [
    "DEFAULT_HORIZON_DAYS",
    "DEFAULT_TRAINING_DAYS",
    "MAX_HORIZON_DAYS",
    "MAX_TRAINING_DAYS",
    "RATE_LABELS",
    "EmployeePlan",
    "PlanDay",
    "PlanError",
    "ShiftMark",
    "build_days",
    "clamp_horizon",
    "day_flags",
    "clamp_training_days",
    "clear_day",
    "default_is_training",
    "plan_for",
    "plans",
    "set_day",
    "shift_marks",
    "today",
    "today_is_training",
    "update_plan",
    "week_preview",
]
