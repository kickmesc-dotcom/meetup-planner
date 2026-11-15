"""Первая неделя новичка: наставник и признаки, что он «тонет».

Зачем. Новичок уходит на третий день, и чаще всего об этом узнают не от
наставника, а когда смену некому закрыть. Причины простые и все видны в данных:
он перестал заходить, у него копятся просроченные поручения, за неделю не было
ни одной отработанной смены. Пока это не собрано в одном месте, никто не
смотрит — у руководителя своих дел хватает.

Здесь не «ещё один дашборд», а короткий список тех, кого стоит спросить сегодня.
Поэтому он ограничен двумя неделями с даты найма: дальше человек либо остался
(и попадает в обычную работу), либо ушёл — и это уже другой разговор.

Наставник хранится ссылкой на сотрудника. Один человек может вести нескольких
новичков; наставник без стажёров — нормально. Пустой наставник у стажёра — это
не ошибка данных, а задача: пару надо назначить.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    SHIFT_WORKED,
    TASK_OVERDUE,
    Department,
    Employee,
    HrShift,
    Task,
)
from app.db.models import User
from app.services import hr_reports, hr_settings

# Две недели — стандартный испытательный горизонт в общепите и рознице.
# Дольше держать в этом списке нет смысла: человек или остался, или ушёл.
WINDOW_DAYS = 14
# Два дня без захода — уже сигнал, а не случайность: смены идут каждый день.
RISK_DAYS = 2
SHIFT_WINDOW_DAYS = 7


class MentorshipError(Exception):
    """Код ошибки для клиента, как в остальных админских сервисах."""


@dataclass(frozen=True)
class Trainee:
    employee_id: int
    name: str
    position: str | None
    department_id: int | None
    department: str | None
    hired_on: date
    days_in_team: int
    shifts_week: int
    overdue_tasks: int
    last_seen_at: datetime | None
    mentor_employee_id: int | None
    mentor_name: str | None
    at_risk: bool


def _local_today(now: datetime | None) -> date:
    return hr_settings.local_now(now).date()


def _risk(
    *,
    days_in_team: int,
    shifts_week: int,
    overdue_tasks: int,
    last_seen_at: datetime | None,
    now: datetime,
) -> bool:
    """Кого стоит спросить сегодня.

    Правило намеренно грубое и объяснимое: либо человек не заходил два дня,
    либо у него просрочка, либо он две недели в команде и не отработал ни одной
    смены. Тонкие скоринги здесь вредны — руководителю нужно действие, а не
    рейтинг.
    """
    if days_in_team >= RISK_DAYS:
        seen_days = None
        if last_seen_at is not None:
            # SQLite в тестах отдаёт naive-время, Postgres — aware. Приводим к
            # одному виду, иначе вычитание падает в зависимости от контура.
            seen = (
                last_seen_at
                if last_seen_at.tzinfo is not None
                else last_seen_at.replace(tzinfo=now.tzinfo)
            )
            seen_days = (now - seen).days
        if seen_days is None or seen_days >= RISK_DAYS:
            return True
    if overdue_tasks > 0:
        return True
    return days_in_team >= WINDOW_DAYS - 1 and shifts_week == 0


async def list_trainees(
    session: AsyncSession,
    *,
    viewer: Employee,
    department_id: int | None = None,
    now: datetime | None = None,
) -> list[Trainee]:
    moment = hr_settings.local_now(now)
    today = moment.date()
    since = today - timedelta(days=WINDOW_DAYS - 1)

    _scope, department = hr_reports.resolve_scope(viewer, department_id)
    filters = [
        Employee.org_id == viewer.org_id,
        Employee.is_active.is_(True),
        Employee.is_demo.is_(False),
        Employee.is_simulation.is_(False),
        Employee.hire_date.is_not(None),
        Employee.hire_date >= since,
    ]
    if department is not None:
        filters.append(Employee.department_id == department)

    rows = (
        await session.execute(
            select(Employee, User.display_name, Department.name)
            .join(User, User.id == Employee.user_id)
            .outerjoin(Department, Department.id == Employee.department_id)
            .where(*filters)
            .order_by(Employee.hire_date.desc(), Employee.id)
        )
    ).all()
    if not rows:
        return []

    ids = [employee.id for employee, _name, _dept in rows]
    shifts = dict(
        (
            await session.execute(
                select(HrShift.employee_id, func.count())
                .where(
                    HrShift.employee_id.in_(ids),
                    HrShift.day >= today - timedelta(days=SHIFT_WINDOW_DAYS - 1),
                    HrShift.status == SHIFT_WORKED,
                )
                .group_by(HrShift.employee_id)
            )
        ).all()
    )
    overdue = dict(
        (
            await session.execute(
                select(Task.assignee_employee_id, func.count())
                .where(
                    Task.assignee_employee_id.in_(ids),
                    Task.status == TASK_OVERDUE,
                )
                .group_by(Task.assignee_employee_id)
            )
        ).all()
    )

    mentor_ids = {
        employee.mentor_employee_id
        for employee, _name, _dept in rows
        if employee.mentor_employee_id is not None
    }
    mentor_names: dict[int, str] = {}
    if mentor_ids:
        mentor_names = dict(
            (
                await session.execute(
                    select(Employee.id, User.display_name)
                    .join(User, User.id == Employee.user_id)
                    .where(Employee.id.in_(mentor_ids))
                )
            ).all()
        )

    result: list[Trainee] = []
    for employee, name, dept_name in rows:
        assert employee.hire_date is not None  # отфильтровано запросом
        days_in_team = max(0, (today - employee.hire_date).days)
        shifts_week = int(shifts.get(employee.id, 0))
        overdue_tasks = int(overdue.get(employee.id, 0))
        result.append(
            Trainee(
                employee_id=int(employee.id),
                name=str(name or ""),
                position=employee.position,
                department_id=employee.department_id,
                department=dept_name,
                hired_on=employee.hire_date,
                days_in_team=days_in_team,
                shifts_week=shifts_week,
                overdue_tasks=overdue_tasks,
                last_seen_at=employee.last_seen_at,
                mentor_employee_id=employee.mentor_employee_id,
                mentor_name=mentor_names.get(employee.mentor_employee_id or 0),
                at_risk=_risk(
                    days_in_team=days_in_team,
                    shifts_week=shifts_week,
                    overdue_tasks=overdue_tasks,
                    last_seen_at=employee.last_seen_at,
                    now=moment,
                ),
            )
        )
    return result


async def _scoped_employee(
    session: AsyncSession, viewer: Employee, employee_id: int
) -> Employee:
    employee = await session.get(Employee, employee_id)
    if (
        employee is None
        or employee.org_id != viewer.org_id
        or not employee.is_active
        or employee.is_simulation
    ):
        raise MentorshipError("employee_not_found")
    scope, department = hr_reports.resolve_scope(viewer, None)
    if scope != hr_reports.SCOPE_ALL and employee.department_id != department:
        raise MentorshipError("employee_not_found")
    return employee


async def assign_mentor(
    session: AsyncSession,
    *,
    viewer: Employee,
    employee_id: int,
    mentor_id: int | None,
) -> Trainee:
    """Назначить или снять наставника.

    Себя наставником назначить нельзя: получится «сам за себя отвечает», и
    список рисков перестанет кого-либо находить.
    """
    trainee = await _scoped_employee(session, viewer, employee_id)
    if mentor_id is not None:
        mentor = await _scoped_employee(session, viewer, mentor_id)
        if mentor.id == trainee.id:
            raise MentorshipError("mentor_is_trainee")
    trainee.mentor_employee_id = mentor_id
    await session.commit()

    items = await list_trainees(session, viewer=viewer, department_id=None)
    for item in items:
        if item.employee_id == employee_id:
            return item
    raise MentorshipError("employee_not_found")


__all__ = [
    "MentorshipError",
    "Trainee",
    "assign_mentor",
    "list_trainees",
]
