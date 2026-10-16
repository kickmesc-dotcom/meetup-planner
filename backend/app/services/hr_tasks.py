"""Поручения АУП (п.4 mainPROMT).

Ключевые правила из брифа, зашитые в сервис:

* получатель — либо подразделение (всем его активным сотрудникам), либо один
  сотрудник (`scope`);
* фотоотчёт опционален и задаётся при создании: если он включён, поручение
  закрывается ПРИХОДОМ фото (п.4.4), а не кнопкой «выполнено»;
* «не успеваю / есть проблема» (п.4.5) — отдельная сущность `TaskIssue`,
  руководитель видит причину и комментарий;
* просрочку проставляет планировщик (`sweep_overdue`), а не сам сотрудник;
* каждое изменение статуса пишется в `TaskEvent` (журнал/аудит, п.11).

Разрешённые переходы описаны таблицей `_TRANSITIONS` и проверяются в
`can_transition` — чистая функция, потому и тестируемая.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    PRIORITY_NORMAL,
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_OVERDUE,
    TASK_SCOPE_DEPARTMENT,
    TASK_SCOPE_EMPLOYEE,
    TASK_STATUSES,
    Employee,
    Task,
    TaskEvent,
    TaskIssue,
    TaskPhoto,
)


class TaskError(Exception):
    """Нарушение правил поручения."""


# Открытые статусы — те, что ещё «в работе» и могут уйти в просрочку.
OPEN_STATUSES: frozenset[str] = frozenset({TASK_NEW, TASK_ACCEPTED, TASK_IN_PROGRESS})

# Кто в кого может переходить. Сотрудник закрывает задачу, руководитель может
# вернуть её в работу (`failed` → `in_progress`) — это и есть «требуется
# внимание руководителя».
_TRANSITIONS: dict[str, frozenset[str]] = {
    TASK_NEW: frozenset({TASK_ACCEPTED, TASK_IN_PROGRESS, TASK_DONE, TASK_OVERDUE, TASK_FAILED}),
    TASK_ACCEPTED: frozenset({TASK_IN_PROGRESS, TASK_DONE, TASK_OVERDUE, TASK_FAILED}),
    TASK_IN_PROGRESS: frozenset({TASK_DONE, TASK_OVERDUE, TASK_FAILED}),
    TASK_OVERDUE: frozenset({TASK_IN_PROGRESS, TASK_DONE, TASK_FAILED}),
    TASK_DONE: frozenset(),
    TASK_FAILED: frozenset({TASK_IN_PROGRESS, TASK_DONE}),
}


def can_transition(current: str, new: str) -> bool:
    if current not in TASK_STATUSES or new not in TASK_STATUSES:
        return False
    return new in _TRANSITIONS.get(current, frozenset())


def is_overdue(task: Task, now: datetime | None = None) -> bool:
    """Просрочено ли поручение прямо сейчас (без учёта текущего статуса)."""
    if task.due_at is None or task.status not in OPEN_STATUSES:
        return False
    moment = now or datetime.now(UTC)
    due = task.due_at
    if due.tzinfo is None:  # защита от naive-даты из тестов/сидинга
        due = due.replace(tzinfo=UTC)
    return due < moment


# --------------------------------------------------------------------------
# Создание и выборки
# --------------------------------------------------------------------------


async def create_task(
    session: AsyncSession,
    *,
    creator: Employee,
    title: str,
    scope: str,
    description: str | None = None,
    expected_result: str | None = None,
    department_id: int | None = None,
    assignee_employee_id: int | None = None,
    due_at: datetime | None = None,
    priority: str = PRIORITY_NORMAL,
    requires_photo: bool = False,
    comment: str | None = None,
) -> Task:
    clean_title = title.strip()
    if not clean_title:
        raise TaskError("empty_title")
    if scope == TASK_SCOPE_DEPARTMENT and department_id is None:
        raise TaskError("department_required")
    if scope == TASK_SCOPE_EMPLOYEE and assignee_employee_id is None:
        raise TaskError("assignee_required")
    if scope not in {TASK_SCOPE_DEPARTMENT, TASK_SCOPE_EMPLOYEE}:
        raise TaskError("bad_scope")

    task = Task(
        title=clean_title,
        description=description,
        expected_result=expected_result,
        scope=scope,
        department_id=department_id if scope == TASK_SCOPE_DEPARTMENT else None,
        assignee_employee_id=(
            assignee_employee_id if scope == TASK_SCOPE_EMPLOYEE else None
        ),
        due_at=due_at,
        priority=priority,
        requires_photo=requires_photo,
        comment=comment,
        status=TASK_NEW,
        created_by_employee_id=creator.id,
    )
    session.add(task)
    await session.flush()
    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=None,
            to_status=TASK_NEW,
            by_employee_id=creator.id,
            comment="created",
        )
    )
    await session.flush()
    return task


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    return await session.get(Task, task_id)


async def assignees(session: AsyncSession, task: Task) -> list[Employee]:
    """Кому адресовано поручение сейчас (один сотрудник или всё подразделение)."""
    if task.scope == TASK_SCOPE_EMPLOYEE and task.assignee_employee_id is not None:
        emp = await session.get(Employee, task.assignee_employee_id)
        return [emp] if emp is not None else []
    if task.scope == TASK_SCOPE_DEPARTMENT and task.department_id is not None:
        rows = await session.scalars(
            select(Employee).where(
                Employee.department_id == task.department_id,
                Employee.is_active.is_(True),
            )
        )
        return list(rows.all())
    return []


async def list_for_employee(
    session: AsyncSession,
    employee: Employee,
    *,
    include_closed: bool = False,
) -> list[Task]:
    """Поручения, «видимые» сотруднику: личные + на его подразделение."""
    stmt = select(Task).where(
        (Task.assignee_employee_id == employee.id)
        | (
            (Task.scope == TASK_SCOPE_DEPARTMENT)
            & (Task.department_id == employee.department_id)
        )
    )
    if not include_closed:
        stmt = stmt.where(Task.status.notin_((TASK_DONE,)))
    stmt = stmt.order_by(Task.due_at.is_(None), Task.due_at, Task.id.desc())
    return list(await session.scalars(stmt))


async def list_all(
    session: AsyncSession,
    *,
    statuses: list[str] | None = None,
    exclude_employee_ids: set[int] | None = None,
) -> list[Task]:
    """Все поручения (АУП).

    `exclude_employee_ids` — фильтр «спрятать»: им пользуется тумблер тестового
    пула `[BOT]` (services/hr_demo), чтобы поручения симуляторов не висели в
    боевом списке руководителя. Поручения на всё подразделение (без исполнителя)
    остаются: их автор — не тестовый человек.
    """
    stmt = select(Task)
    if statuses:
        stmt = stmt.where(Task.status.in_(statuses))
    if exclude_employee_ids:
        hidden = set(exclude_employee_ids)
        stmt = stmt.where(
            or_(
                Task.assignee_employee_id.is_(None),
                Task.assignee_employee_id.notin_(hidden),
            )
        )
    stmt = stmt.order_by(Task.due_at.is_(None), Task.due_at, Task.id.desc())
    return list(await session.scalars(stmt))


# --------------------------------------------------------------------------
# Изменение состояния
# --------------------------------------------------------------------------


async def change_status(
    session: AsyncSession,
    task: Task,
    to_status: str,
    *,
    by: Employee | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> Task:
    if not can_transition(task.status, to_status):
        raise TaskError(f"bad_transition:{task.status}->{to_status}")

    moment = now or datetime.now(UTC)
    previous = task.status
    task.status = to_status
    if to_status == TASK_ACCEPTED and task.accepted_at is None:
        task.accepted_at = moment
    if to_status == TASK_DONE:
        task.done_at = moment
    if to_status in {TASK_IN_PROGRESS, TASK_OVERDUE}:
        # Вернули в работу — снимаем метку выполнения.
        task.done_at = None

    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=previous,
            to_status=to_status,
            by_employee_id=by.id if by else None,
            comment=comment,
        )
    )
    await session.flush()
    return task


async def add_issue(
    session: AsyncSession,
    task: Task,
    *,
    employee: Employee,
    reason_code: str | None = None,
    comment: str | None = None,
    eta_at: datetime | None = None,
) -> TaskIssue:
    """«Не успеваю / есть проблема» (п.4.5). Статус задачи не меняем."""
    issue = TaskIssue(
        task_id=task.id,
        employee_id=employee.id,
        reason_code=reason_code,
        comment=comment,
        eta_at=eta_at,
    )
    session.add(issue)
    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=task.status,
            to_status=task.status,
            by_employee_id=employee.id,
            comment=f"issue:{reason_code or 'other'}",
        )
    )
    await session.flush()
    return issue


async def add_photo(
    session: AsyncSession,
    task: Task,
    *,
    employee: Employee,
    file_id: str,
    now: datetime | None = None,
) -> TaskPhoto:
    """Фотоотчёт. Если он требовался — поручение закрывается (п.4.4)."""
    if not file_id:
        raise TaskError("empty_file_id")
    photo = TaskPhoto(task_id=task.id, employee_id=employee.id, file_id=file_id)
    session.add(photo)
    await session.flush()
    if task.requires_photo and task.status != TASK_DONE:
        if can_transition(task.status, TASK_DONE):
            await change_status(
                session, task, TASK_DONE, by=employee, comment="photo_report", now=now
            )
    return photo


async def issues_of(session: AsyncSession, task_id: int) -> list[TaskIssue]:
    rows = await session.scalars(
        select(TaskIssue)
        .where(TaskIssue.task_id == task_id)
        .order_by(TaskIssue.created_at.desc(), TaskIssue.id.desc())
    )
    return list(rows.all())


async def photos_of(session: AsyncSession, task_id: int) -> list[TaskPhoto]:
    rows = await session.scalars(
        select(TaskPhoto)
        .where(TaskPhoto.task_id == task_id)
        .order_by(TaskPhoto.created_at.desc(), TaskPhoto.id.desc())
    )
    return list(rows.all())


async def events_of(session: AsyncSession, task_id: int) -> list[TaskEvent]:
    rows = await session.scalars(
        select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.at, TaskEvent.id)
    )
    return list(rows.all())


async def sweep_overdue(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Task]:
    """Перевести в `overdue` все открытые поручения с прошедшим сроком.

    Возвращает изменённые задачи — по ним планировщик шлёт уведомления
    ответственным руководителям (п.4.5: «ответственному руководителю
    отправляется уведомление согласно настройкам»).
    """
    moment = now or datetime.now(UTC)
    rows = await session.scalars(
        select(Task).where(
            Task.due_at.is_not(None),
            Task.due_at < moment,
            Task.status.in_(tuple(OPEN_STATUSES)),
        )
    )
    changed: list[Task] = []
    for task in rows.all():
        previous = task.status
        task.status = TASK_OVERDUE
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=previous,
                to_status=TASK_OVERDUE,
                by_employee_id=None,
                comment="auto_overdue",
            )
        )
        changed.append(task)
    if changed:
        await session.flush()
    return changed
