"""Дашборд подразделения: все сотрудники и что у них сейчас.

Зачем отдельный сервис. Лента отвечает на вопрос «что произошло», карточка
коллеги — «кто этот человек». Не хватало середины: «как дела у отдела прямо
сейчас» — кто в смене, у кого не закрыт чек-лист, у кого горит поручение.
Раньше это собирали глазами по ленте, и руководитель не видел людей, которые
сегодня ещё ничего не сделали (их в ленте просто нет).

Правило видимости — то же, что у ленты, и решает его сервер:

* сотрудник — только своё подразделение (и без личных отметок времени);
* руководитель подразделения — своё, а если организация разрешила наблюдение
  между отделами (`org_setup.cross_department_watch`) — любое;
* администратор/прописанный доступ — любое.

Строки дашборда намеренно лёгкие: имя, плашка, смена, чек-лист, поручения.
Тяжёлые вещи (история, XP, медиа) остаются в карточке коллеги — дашборд должен
открываться быстро даже на отделе из тридцати человек.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    TASK_DONE,
    TASK_FAILED,
    ChecklistCompletion,
    ChecklistItem,
    ChecklistRun,
    Department,
    Employee,
    HrShift,
    Task,
    TaskAssignment,
)
from app.db.models import User
from app.services import hr_access, hr_checklists, org_setup


class DepartmentAccessError(Exception):
    """Подразделение вне области видимости или его нет."""


@dataclass(frozen=True)
class PersonRow:
    employee_id: int
    display_name: str
    badge: str | None
    badge_emoji: str | None
    position: str | None
    role: str
    is_demo: bool
    is_self: bool
    shift_status: str | None
    checklist_done: int
    checklist_total: int
    tasks_open: int
    tasks_overdue: int
    # Личные отметки — только тем, кому их вообще положено видеть.
    last_seen_at: datetime | None
    profile_public: bool


@dataclass(frozen=True)
class DepartmentOverview:
    department_id: int
    department_name: str
    department_emoji: str | None
    can_manage: bool
    show_presence: bool
    people: list[PersonRow] = field(default_factory=list)

    @property
    def on_shift(self) -> int:
        return sum(1 for p in self.people if p.shift_status == "worked")

    @property
    def overdue(self) -> int:
        return sum(1 for p in self.people if p.tasks_overdue > 0)


async def _allowed_department_ids(
    session: AsyncSession, viewer: Employee
) -> set[int] | None:
    """`None` — можно любое подразделение; иначе конкретный список."""
    if viewer.is_simulation:
        return {int(viewer.department_id)} if viewer.department_id else set()
    if hr_access.is_admin(viewer):
        return None
    setup = await org_setup.load(session)
    if hr_access.is_aup(viewer):
        if viewer.department_id is None or setup.cross_department_watch:
            return None
        return {int(viewer.department_id)}
    return {int(viewer.department_id)} if viewer.department_id else set()


def _is_overdue(task: Task, now: datetime) -> bool:
    due = task.due_at
    if due is None:
        return False
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return due < now and task.status not in (TASK_DONE, TASK_FAILED)


async def overview(
    session: AsyncSession, viewer: Employee, department_id: int
) -> DepartmentOverview:
    """Собрать дашборд подразделения для конкретного смотрящего."""
    allowed = await _allowed_department_ids(session, viewer)
    if allowed is not None and department_id not in allowed:
        raise DepartmentAccessError("department_out_of_scope")

    department = await session.get(Department, department_id)
    if department is None or not department.is_active:
        raise DepartmentAccessError("department_not_found")

    can_manage = (
        not viewer.is_simulation
        and (
            hr_access.is_admin(viewer)
            or (
                hr_access.is_aup(viewer)
                and (
                    viewer.department_id is None
                    or int(viewer.department_id) == department_id
                    or allowed is None
                )
            )
        )
    )
    # Сотрудник видит состав и рабочий статус, но не «когда заходил»: личная
    # отметка времени — это уже наблюдение, а не сводка смены.
    show_presence = can_manage

    rows = list(
        (
            await session.scalars(
                select(Employee)
                .where(
                    Employee.department_id == department_id,
                    Employee.is_simulation.is_(False),
                    Employee.is_active.is_(True),
                    Employee.fired_at.is_(None),
                )
                .order_by(Employee.is_demo, Employee.id)
            )
        ).all()
    )
    ids = [int(row.id) for row in rows]
    if not ids:
        return DepartmentOverview(
            department_id=int(department.id),
            department_name=str(department.name),
            department_emoji=department.emoji,
            can_manage=can_manage,
            show_presence=show_presence,
            people=[],
        )

    users = {
        int(user.id): user
        for user in (
            await session.scalars(
                select(User).where(User.id.in_([row.user_id for row in rows]))
            )
        ).all()
    }

    today = hr_checklists.local_today()
    shifts = {
        int(shift.employee_id): str(shift.status)
        for shift in (
            await session.scalars(
                select(HrShift).where(
                    HrShift.employee_id.in_(ids), HrShift.day == today
                )
            )
        ).all()
    }

    done_by_emp: dict[int, int] = {}
    total_by_emp: dict[int, int] = {}
    runs = list(
        (
            await session.scalars(
                select(ChecklistRun).where(
                    ChecklistRun.employee_id.in_(ids),
                    ChecklistRun.shift_date == today,
                )
            )
        ).all()
    )
    if runs:
        run_ids = [int(run.id) for run in runs]
        template_ids = list({int(run.template_id) for run in runs})
        item_totals = {
            int(template_id): int(count)
            for template_id, count in (
                await session.execute(
                    select(ChecklistItem.template_id, func.count(ChecklistItem.id))
                    .where(ChecklistItem.template_id.in_(template_ids))
                    .group_by(ChecklistItem.template_id)
                )
            ).all()
        }
        completions = {
            int(run_id): int(count)
            for run_id, count in (
                await session.execute(
                    select(ChecklistCompletion.run_id, func.count(ChecklistCompletion.id))
                    .where(ChecklistCompletion.run_id.in_(run_ids))
                    .group_by(ChecklistCompletion.run_id)
                )
            ).all()
        }
        for run in runs:
            emp = int(run.employee_id)
            total_by_emp[emp] = total_by_emp.get(emp, 0) + item_totals.get(
                int(run.template_id), 0
            )
            done_by_emp[emp] = done_by_emp.get(emp, 0) + completions.get(
                int(run.id), 0
            )

    now = datetime.now(UTC)
    open_by_emp: dict[int, int] = {}
    overdue_by_emp: dict[int, int] = {}
    for assignment, task in (
        await session.execute(
            select(TaskAssignment, Task)
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(TaskAssignment.employee_id.in_(ids))
        )
    ).all():
        if assignment.status in (TASK_DONE, TASK_FAILED):
            continue
        emp = int(assignment.employee_id)
        open_by_emp[emp] = open_by_emp.get(emp, 0) + 1
        if _is_overdue(task, now):
            overdue_by_emp[emp] = overdue_by_emp.get(emp, 0) + 1

    people: list[PersonRow] = []
    for row in rows:
        emp_id = int(row.id)
        user = users.get(int(row.user_id))
        people.append(
            PersonRow(
                employee_id=emp_id,
                display_name=str(user.display_name) if user is not None else "—",
                badge=row.badge,
                badge_emoji=row.badge_emoji,
                position=row.position,
                role=str(row.role),
                is_demo=bool(row.is_demo),
                is_self=emp_id == int(viewer.id),
                shift_status=shifts.get(emp_id),
                checklist_done=done_by_emp.get(emp_id, 0),
                checklist_total=total_by_emp.get(emp_id, 0),
                tasks_open=open_by_emp.get(emp_id, 0),
                tasks_overdue=overdue_by_emp.get(emp_id, 0),
                last_seen_at=(
                    row.last_seen_at
                    if show_presence and bool(row.show_last_seen)
                    else None
                ),
                profile_public=bool(row.profile_public),
            )
        )

    return DepartmentOverview(
        department_id=int(department.id),
        department_name=str(department.name),
        department_emoji=department.emoji,
        can_manage=can_manage,
        show_presence=show_presence,
        people=people,
    )
