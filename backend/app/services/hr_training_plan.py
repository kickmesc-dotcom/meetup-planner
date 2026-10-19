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
    Department,
    Employee,
    EmployeeTrainingDay,
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
) -> tuple[PlanDay, ...]:
    """Полоса дней: сначала ручные правила, остальное — расчёт."""
    out: list[PlanDay] = []
    for index in range(clamp_horizon(days)):
        day = start + timedelta(days=index)
        if day in overrides:
            out.append(PlanDay(day=day, is_training=overrides[day], explicit=True))
        else:
            out.append(
                PlanDay(
                    day=day,
                    is_training=default_is_training(employee, day),
                    explicit=False,
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
    overrides = await _overrides(
        session,
        ids,
        start=first,
        end=first + timedelta(days=horizon - 1),
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
            days=build_days(
                employee,
                start=first,
                days=horizon,
                overrides=overrides.get(int(employee.id), {}),
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
    overrides = await _overrides(
        session,
        [int(employee.id)],
        start=first,
        end=first + timedelta(days=horizon - 1),
    )
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
        days=build_days(
            employee,
            start=first,
            days=horizon,
            overrides=overrides.get(int(employee.id), {}),
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
    """Учебная ли у сотрудника сегодняшняя смена."""
    day = today()
    override = await session.scalar(
        select(EmployeeTrainingDay.is_training).where(
            EmployeeTrainingDay.employee_id == int(employee.id),
            EmployeeTrainingDay.day == day,
        )
    )
    if override is not None:
        return bool(override)
    return default_is_training(employee, day)


async def week_preview(
    session: AsyncSession, employee: Employee, *, days: int = 7
) -> tuple[PlanDay, ...]:
    first = today()
    overrides = await _overrides(
        session,
        [int(employee.id)],
        start=first,
        end=first + timedelta(days=clamp_horizon(days) - 1),
    )
    return build_days(
        employee,
        start=first,
        days=days,
        overrides=overrides.get(int(employee.id), {}),
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
    "build_days",
    "clamp_horizon",
    "clamp_training_days",
    "clear_day",
    "default_is_training",
    "plan_for",
    "plans",
    "set_day",
    "today",
    "today_is_training",
    "update_plan",
    "week_preview",
]
