"""Кабинет управляющего: сводка по подразделениям и людям за смену.

Один экран отвечает на три вопроса, с которых начинается рабочий день
руководителя: кто сегодня не начал смену, у кого она не закрыта к вечеру и что
горит прямо сейчас (просрочки и открытые проблемы).

Именно сводка, а не список всех задач: сначала исключения, которые требуют
вмешательства, потом спокойные цифры. Данные считаются на чтение и не создают
побочных эффектов — в отличие от `hr_checklists.build_view`, который заводит
прогон смены, здесь только SELECT'ы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    ROLE_ADMIN,
    ChecklistCompletion,
    ChecklistItem,
    ChecklistRun,
    ChecklistTemplate,
    Department,
    Employee,
    Task,
    TaskEvent,
    TaskIssue,
)
from app.db.models import User
from app.services import hr_access, hr_demo, hr_settings, hr_tasks

STATUS_DONE = "done"
STATUS_LATE = "late"
STATUS_IN_PROGRESS = "in_progress"
STATUS_IDLE = "idle"

KIND_OVERDUE = "overdue"
KIND_ISSUE = "issue"
KIND_LATE_SHIFT = "late_shift"

SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"


@dataclass(frozen=True)
class EmployeeStatus:
    employee_id: int
    display_name: str
    telegram_id: int
    department_id: int | None
    department_name: str | None
    department_emoji: str | None
    # Должность из HR-профиля («повар», «су-шеф»). В карточке сотрудника
    # показывается компактно рядом с именем: руководителю важно видеть, кто
    # есть кто, не открывая профиль.
    position: str | None
    role: str
    badge: str | None
    badge_emoji: str | None
    checklist_done: int
    checklist_total: int
    tasks_open: int
    tasks_overdue: int
    has_run: bool
    last_activity_at: datetime | None
    status: str


@dataclass(frozen=True)
class DepartmentStatus:
    department_id: int
    name: str
    emoji: str | None
    employees: int
    started: int
    done: int
    open_tasks: int
    overdue_tasks: int
    open_issues: int


@dataclass(frozen=True)
class Attention:
    kind: str
    severity: str
    text: str
    task_id: int | None = None
    employee_id: int | None = None
    department_id: int | None = None


@dataclass(frozen=True)
class ActivityItem:
    at: datetime
    kind: str
    text: str
    employee_id: int | None
    display_name: str | None


@dataclass(frozen=True)
class Dashboard:
    work_date: date
    scope: str
    departments: list[DepartmentStatus] = field(default_factory=list)
    employees: list[EmployeeStatus] = field(default_factory=list)
    attention: list[Attention] = field(default_factory=list)
    activity: list[ActivityItem] = field(default_factory=list)
    total_employees: int = 0
    shifts_started: int = 0
    shifts_done: int = 0
    tasks_open: int = 0
    tasks_overdue: int = 0
    open_issues: int = 0


def _local_day(now: datetime) -> date:
    tz = ZoneInfo(get_settings().scheduler_tz)
    return (now if now.tzinfo else now.replace(tzinfo=tz)).astimezone(tz).date()


def _local_time(now: datetime) -> time:
    tz = ZoneInfo(get_settings().scheduler_tz)
    return (now if now.tzinfo else now.replace(tzinfo=tz)).astimezone(tz).time()


def viewer_scope(viewer: Employee) -> str:
    """`all` для администратора, `department` для руководителя подразделения."""
    if hr_access.role_rank(viewer.role) >= hr_access.role_rank(ROLE_ADMIN):
        return "all"
    return "department"


def employee_status(
    *, has_run: bool, done: int, total: int, now_time: time, late_after: time
) -> str:
    """Статус смены человека по времени ресторана. Чистая функция для тестов."""
    if has_run and total > 0 and done >= total:
        return STATUS_DONE
    if has_run:
        return STATUS_LATE if now_time >= late_after else STATUS_IN_PROGRESS
    return STATUS_LATE if now_time >= late_after else STATUS_IDLE


def late_after_from_close(close_at: time) -> time:
    """За сколько до закрытия смена считается «незакрытой вовремя» — 2 часа."""
    anchor = datetime(2000, 1, 1, close_at.hour, close_at.minute)
    return (anchor - timedelta(hours=2)).time()


async def build_dashboard(
    session: AsyncSession,
    *,
    viewer: Employee,
    now: datetime | None = None,
) -> Dashboard:
    moment = now or datetime.now(tz=ZoneInfo(get_settings().scheduler_tz))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(get_settings().scheduler_tz))
    today = _local_day(moment)
    now_time = _local_time(moment)
    scope = viewer_scope(viewer)
    allowed_department = viewer.department_id

    def in_scope_department(department_id: int | None) -> bool:
        if scope == "all" or allowed_department is None:
            return True
        return department_id == allowed_department

    hidden = await hr_demo.hidden_employee_ids(session)

    departments = list(
        (
            await session.scalars(
                select(Department)
                .where(Department.is_active.is_(True))
                .order_by(Department.sort_order, Department.id)
            )
        ).all()
    )
    departments = [d for d in departments if in_scope_department(d.id)]
    department_by_id = {int(d.id): d for d in departments}

    rows = (
        await session.execute(
            select(Employee, User)
            .join(User, User.id == Employee.user_id)
            .where(Employee.is_active.is_(True))
            .order_by(Employee.id)
        )
    ).all()
    people = [
        (employee, user)
        for employee, user in rows
        if int(employee.id) not in hidden and in_scope_department(employee.department_id)
    ]
    employee_ids = [int(e.id) for e, _ in people]
    employee_by_id = {int(e.id): e for e, _ in people}
    name_by_id = {int(e.id): u.display_name for e, u in people}

    # Прогоны смены за сегодня и прогресс по ним — без создания новых прогонов.
    runs: dict[int, tuple[int, int]] = {}
    if employee_ids:
        run_rows = (
            await session.execute(
                select(ChecklistRun.id, ChecklistRun.employee_id, ChecklistRun.template_id)
                .where(
                    ChecklistRun.shift_date == today,
                    ChecklistRun.employee_id.in_(employee_ids),
                )
            )
        ).all()
        template_ids = {int(tid) for _, _, tid in run_rows}
        totals: dict[int, int] = {}
        if template_ids:
            for template_id, total in (
                await session.execute(
                    select(ChecklistTemplate.id, func.count(ChecklistItem.id))
                    .join(ChecklistItem, ChecklistItem.template_id == ChecklistTemplate.id)
                    .where(ChecklistTemplate.id.in_(template_ids))
                    .group_by(ChecklistTemplate.id)
                )
            ).all():
                totals[int(template_id)] = int(total)
        done_by_run: dict[int, int] = {}
        if run_rows:
            for run_id, done in (
                await session.execute(
                    select(ChecklistCompletion.run_id, func.count(ChecklistCompletion.id))
                    .where(ChecklistCompletion.run_id.in_([int(r[0]) for r in run_rows]))
                    .group_by(ChecklistCompletion.run_id)
                )
            ).all():
                done_by_run[int(run_id)] = int(done)
        for run_id, employee_id, template_id in run_rows:
            done = done_by_run.get(int(run_id), 0)
            total = totals.get(int(template_id), 0)
            prev_done, prev_total = runs.get(int(employee_id), (0, 0))
            runs[int(employee_id)] = (prev_done + done, prev_total + total)

    open_tasks = list(
        (
            await session.scalars(
                select(Task)
                .where(Task.status.in_(tuple(hr_tasks.OPEN_STATUSES)))
                .order_by(Task.due_at)
            )
        ).all()
    )
    open_tasks = [
        t
        for t in open_tasks
        if (t.assignee_employee_id in employee_by_id)
        or (t.department_id is not None and in_scope_department(t.department_id))
    ]

    issues = (
        await session.execute(
            select(TaskIssue, Task)
            .join(Task, Task.id == TaskIssue.task_id)
            .where(Task.status.in_(tuple(hr_tasks.OPEN_STATUSES)))
            .order_by(TaskIssue.created_at.desc())
            .limit(100)
        )
    ).all()
    issues = [
        (issue, task)
        for issue, task in issues
        if (task.assignee_employee_id in employee_by_id)
        or (task.department_id is not None and in_scope_department(task.department_id))
    ]

    close_at = await hr_settings.get_work_close(session)
    late_after = late_after_from_close(close_at)

    tasks_open_by_employee: dict[int, int] = {}
    tasks_overdue_by_employee: dict[int, int] = {}
    for task in open_tasks:
        if task.assignee_employee_id in employee_by_id:
            key = int(task.assignee_employee_id)
            tasks_open_by_employee[key] = tasks_open_by_employee.get(key, 0) + 1
            if hr_tasks.is_overdue(task):
                tasks_overdue_by_employee[key] = tasks_overdue_by_employee.get(key, 0) + 1

    last_activity: dict[int, datetime] = {}
    if employee_ids:
        for employee_id, at in (
            await session.execute(
                select(TaskEvent.by_employee_id, func.max(TaskEvent.at))
                .where(TaskEvent.by_employee_id.in_(employee_ids))
                .group_by(TaskEvent.by_employee_id)
            )
        ).all():
            if employee_id is not None and at is not None:
                last_activity[int(employee_id)] = at

    employees: list[EmployeeStatus] = []
    for employee, user in people:
        done, total = runs.get(int(employee.id), (0, 0))
        department = (
            department_by_id.get(int(employee.department_id))
            if employee.department_id
            else None
        )
        employees.append(
            EmployeeStatus(
                employee_id=int(employee.id),
                display_name=user.display_name,
                telegram_id=int(user.telegram_id),
                department_id=int(employee.department_id) if employee.department_id else None,
                department_name=department.name if department else None,
                department_emoji=department.emoji if department else None,
                position=employee.position,
                role=employee.role,
                badge=employee.badge,
                badge_emoji=employee.badge_emoji,
                checklist_done=done,
                checklist_total=total,
                tasks_open=tasks_open_by_employee.get(int(employee.id), 0),
                tasks_overdue=tasks_overdue_by_employee.get(int(employee.id), 0),
                has_run=int(employee.id) in runs,
                last_activity_at=last_activity.get(int(employee.id)),
                status=employee_status(
                    has_run=int(employee.id) in runs,
                    done=done,
                    total=total,
                    now_time=now_time,
                    late_after=late_after,
                ),
            )
        )

    department_rows: list[DepartmentStatus] = []
    for department in departments:
        dept_id = int(department.id)
        team = [e for e in employees if e.department_id == dept_id]
        dept_tasks = [t for t in open_tasks if t.department_id == dept_id] or []
        dept_team_ids = {e.employee_id for e in team}
        dept_tasks += [
            t for t in open_tasks if t.assignee_employee_id in dept_team_ids
        ]
        unique_tasks = {int(t.id): t for t in dept_tasks}
        department_rows.append(
            DepartmentStatus(
                department_id=dept_id,
                name=department.name,
                emoji=department.emoji,
                employees=len(team),
                started=sum(1 for e in team if e.has_run),
                done=sum(1 for e in team if e.status == STATUS_DONE),
                open_tasks=len(unique_tasks),
                overdue_tasks=sum(1 for t in unique_tasks.values() if hr_tasks.is_overdue(t)),
                open_issues=sum(
                    1
                    for _, task in issues
                    if task.department_id == dept_id
                    or task.assignee_employee_id in dept_team_ids
                ),
            )
        )

    attention: list[Attention] = []
    for task in open_tasks:
        if not hr_tasks.is_overdue(task):
            continue
        assignee = (
            employee_by_id.get(int(task.assignee_employee_id))
            if task.assignee_employee_id
            else None
        )
        attention.append(
            Attention(
                kind=KIND_OVERDUE,
                severity=SEVERITY_HIGH,
                text=f"Просрочено: «{task.title}»"
                + (f" — {name_by_id.get(int(assignee.id), '')}" if assignee else ""),
                task_id=int(task.id),
                employee_id=int(assignee.id) if assignee else None,
                department_id=(
                    int(assignee.department_id)
                    if assignee and assignee.department_id
                    else None
                ),
            )
        )
    for issue, task in issues:
        author = employee_by_id.get(int(issue.employee_id)) if issue.employee_id else None
        reason = issue.reason_code or "проблема"
        attention.append(
            Attention(
                kind=KIND_ISSUE,
                severity=SEVERITY_MEDIUM,
                text=f"Проблема по «{task.title}»: {reason}",
                task_id=int(task.id),
                employee_id=int(author.id) if author else None,
                department_id=(
                    int(author.department_id) if author and author.department_id else None
                ),
            )
        )
    for employee in employees:
        if employee.status == STATUS_LATE and employee.has_run:
            attention.append(
                Attention(
                    kind=KIND_LATE_SHIFT,
                    severity=SEVERITY_MEDIUM,
                    text=(
                        f"Смена не закрыта: {employee.display_name} "
                        f"({employee.checklist_done}/{employee.checklist_total})"
                    ),
                    employee_id=employee.employee_id,
                    department_id=employee.department_id,
                )
            )

    activity_rows = (
        await session.execute(
            select(TaskEvent, User.display_name)
            .outerjoin(Employee, Employee.id == TaskEvent.by_employee_id)
            .outerjoin(User, User.id == Employee.user_id)
            .order_by(TaskEvent.at.desc())
            .limit(12)
        )
    ).all()
    activity = [
        ActivityItem(
            at=event.at,
            kind=event.to_status,
            text=event.comment or f"статус → {event.to_status}",
            employee_id=int(event.by_employee_id) if event.by_employee_id else None,
            display_name=name,
        )
        for event, name in activity_rows
        if event.by_employee_id is None or int(event.by_employee_id) in employee_by_id
    ]

    return Dashboard(
        work_date=today,
        scope=scope,
        departments=department_rows,
        employees=employees,
        attention=attention,
        activity=activity,
        total_employees=len(employees),
        shifts_started=sum(1 for e in employees if e.has_run),
        shifts_done=sum(1 for e in employees if e.status == STATUS_DONE),
        tasks_open=len({int(t.id) for t in open_tasks}),
        tasks_overdue=sum(1 for t in open_tasks if hr_tasks.is_overdue(t)),
        open_issues=len(issues),
    )
