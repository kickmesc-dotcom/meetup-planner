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

from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    MODE_ONE_OF,
    MODE_PARTS,
    PRIORITY_NORMAL,
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_MODES,
    TASK_NEW,
    TASK_ON_REVIEW,
    TASK_OVERDUE,
    TASK_REWORK,
    TASK_SCOPE_DEPARTMENT,
    TASK_SCOPE_EMPLOYEE,
    TASK_STATUSES,
    Employee,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskIssue,
    TaskPhoto,
)


class TaskError(Exception):
    """Нарушение правил поручения."""


# Открытые статусы — те, что ещё «в работе» и могут уйти в просрочку.
# `on_review` сюда не входит: работа сдана, ждём руководителя — просрочка тут
# его, а не исполнителя (для этого есть очередь приёмки). `rework` — наоборот:
# руководитель вернул, значит задача снова на человеке.
OPEN_STATUSES: frozenset[str] = frozenset(
    {TASK_NEW, TASK_ACCEPTED, TASK_IN_PROGRESS, TASK_REWORK}
)

# Кто в кого может переходить. Сотрудник закрывает задачу, руководитель может
# вернуть её в работу (`failed` → `in_progress`) — это и есть «требуется
# внимание руководителя».
_TRANSITIONS: dict[str, frozenset[str]] = {
    TASK_NEW: frozenset(
        {
            TASK_ACCEPTED,
            TASK_IN_PROGRESS,
            TASK_ON_REVIEW,
            TASK_DONE,
            TASK_OVERDUE,
            TASK_FAILED,
        }
    ),
    TASK_ACCEPTED: frozenset(
        {TASK_IN_PROGRESS, TASK_ON_REVIEW, TASK_DONE, TASK_OVERDUE, TASK_FAILED}
    ),
    TASK_IN_PROGRESS: frozenset(
        {TASK_ON_REVIEW, TASK_DONE, TASK_OVERDUE, TASK_FAILED}
    ),
    # Сдано на проверку: принимаем (`done`) или возвращаем на доработку.
    TASK_ON_REVIEW: frozenset({TASK_DONE, TASK_REWORK, TASK_FAILED}),
    TASK_REWORK: frozenset(
        {TASK_IN_PROGRESS, TASK_ON_REVIEW, TASK_DONE, TASK_FAILED}
    ),
    TASK_OVERDUE: frozenset(
        {TASK_IN_PROGRESS, TASK_ON_REVIEW, TASK_DONE, TASK_FAILED}
    ),
    TASK_DONE: frozenset(),
    TASK_FAILED: frozenset({TASK_IN_PROGRESS, TASK_DONE}),
}


def aggregate_status(mode: str, statuses: list[str]) -> str:
    """Статус группового поручения по отметкам исполнителей.

    Чистая функция — именно ею живёт вся разница между режимами:

    * `one_of` («один за всех») — закрыл любой, задача закрыта;
    * `each` / `parts` — пока кто-то не отметил, задача открыта; но когда все
      допили свои части и среди них есть «не выполнено», задача уходит в
      `failed`: часть работы смены действительно не сделана, и это должен
      видеть руководитель (а не считать поручение закрытым).
    """
    if not statuses:
        return TASK_NEW
    if mode == MODE_ONE_OF:
        if TASK_DONE in statuses:
            return TASK_DONE
        if statuses and all(status == TASK_FAILED for status in statuses):
            return TASK_FAILED
        if all(status == TASK_REWORK for status in statuses):
            return TASK_IN_PROGRESS
    else:
        if all(status == TASK_DONE for status in statuses):
            return TASK_DONE
        if all(status in {TASK_DONE, TASK_FAILED} for status in statuses):
            return TASK_FAILED
        if all(status == TASK_NEW for status in statuses):
            return TASK_NEW
        if any(status == TASK_IN_PROGRESS for status in statuses):
            return TASK_IN_PROGRESS
        # Кто-то сдал работу и ждёт приёмки — это важнее, чем «часть людей ещё
        # не начинала»: руководителю надо принять или вернуть.
        if any(status == TASK_ON_REVIEW for status in statuses):
            return TASK_ON_REVIEW
        # Часть работы закрыта, остальные ещё не открывали — поручение в работе.
        if any(status in {TASK_DONE, TASK_FAILED} for status in statuses):
            return TASK_IN_PROGRESS
    if any(status == TASK_IN_PROGRESS for status in statuses):
        return TASK_IN_PROGRESS
    if any(status == TASK_ON_REVIEW for status in statuses):
        # Работа сдана и ждёт приёмки — руководителю это должно быть видно
        # раньше, чем «часть людей ещё не открывала поручение».
        return TASK_ON_REVIEW
    # Руководитель вернул работу — это не «новое» поручение: сотрудник должен
    # увидеть, что дело в доработке, а не что задача только появилась.
    if any(status == TASK_REWORK for status in statuses):
        return TASK_REWORK
    if any(status == TASK_ACCEPTED for status in statuses):
        return TASK_ACCEPTED
    if all(status == TASK_OVERDUE for status in statuses):
        return TASK_OVERDUE
    if any(status == TASK_OVERDUE for status in statuses):
        return TASK_IN_PROGRESS
    return TASK_NEW


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
    mode: str = MODE_ONE_OF,
    shift_date: date | None = None,
    parts: dict[int, str] | None = None,
    requires_review: bool = False,
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
    if mode not in TASK_MODES:
        raise TaskError("bad_mode")
    if parts and mode != MODE_PARTS:
        raise TaskError("parts_only_for_parts_mode")

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
        mode=mode,
        shift_date=shift_date,
        requires_review=requires_review,
        created_by_employee_id=creator.id,
    )
    session.add(task)
    await session.flush()

    # Строки исполнителей заводим сразу: в `each`/`parts` без них нечего
    # отмечать, а в `one_of` они показывают, кто взял поручение и кто закрыл.
    recipients = await _recipients(session, task)
    labeled = parts or {}
    for employee in recipients:
        session.add(
            TaskAssignment(
                task_id=task.id,
                employee_id=employee.id,
                status=TASK_NEW,
                part=(labeled.get(employee.id) or "").strip() or None,
            )
        )

    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=None,
            to_status=TASK_NEW,
            by_employee_id=creator.id,
            comment=f"created:{mode}",
        )
    )
    await session.flush()
    return task


async def _recipients(session: AsyncSession, task: Task) -> list[Employee]:
    """Кому адресовано поручение (без обращений к БД сверх нужного)."""
    if task.scope == TASK_SCOPE_EMPLOYEE and task.assignee_employee_id is not None:
        employee = await session.get(Employee, task.assignee_employee_id)
        return [employee] if employee is not None else []
    if task.scope == TASK_SCOPE_DEPARTMENT and task.department_id is not None:
        rows = await session.scalars(
            select(Employee).where(
                Employee.department_id == task.department_id,
                Employee.is_active.is_(True),
            )
        )
        return list(rows.all())
    return []


async def assignments_of(
    session: AsyncSession, task_id: int
) -> list[TaskAssignment]:
    rows = await session.scalars(
        select(TaskAssignment)
        .where(TaskAssignment.task_id == task_id)
        .order_by(TaskAssignment.id)
    )
    return list(rows.all())


async def assignment_of(
    session: AsyncSession, task_id: int, employee_id: int
) -> TaskAssignment | None:
    return await session.scalar(
        select(TaskAssignment).where(
            TaskAssignment.task_id == task_id,
            TaskAssignment.employee_id == employee_id,
        )
    )


async def sync_task_status(
    session: AsyncSession,
    task: Task,
    *,
    by: Employee | None = None,  # noqa: ARG001 — оставлено для читаемости вызовов
    now: datetime | None = None,
) -> Task:
    """Пересчитать агрегатный статус задачи по отметкам исполнителей."""
    rows = await assignments_of(session, task.id)
    if not rows:
        return task
    target = aggregate_status(task.mode, [row.status for row in rows])
    if target == task.status:
        return task

    moment = now or datetime.now(UTC)
    previous = task.status
    task.status = target
    if target == TASK_ACCEPTED and task.accepted_at is None:
        task.accepted_at = moment
    if target == TASK_DONE:
        task.done_at = moment
    elif target != TASK_OVERDUE:
        task.done_at = None
    # Агрегат пишем без автора намеренно: KPI и ачивки считают «закрытые
    # поручения» по событиям с `by_employee_id`, и если приписать агрегат
    # последнему отметившему, опыт начислился бы дважды за одну работу.
    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=previous,
            to_status=target,
            by_employee_id=None,
            comment="assignment_sync",
        )
    )
    await session.flush()
    return task


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    return await session.get(Task, task_id)


async def assignees(session: AsyncSession, task: Task) -> list[Employee]:
    """Кому адресовано поручение сейчас.

    Сначала смотрим строки исполнителей (они есть у всех новых поручений), и
    только если их нет — старый путь по `scope`. Так исторические задачи
    продолжают работать без бэкфилла.
    """
    rows = await assignments_of(session, task.id)
    if rows:
        ids = [row.employee_id for row in rows]
        employees = await session.scalars(
            select(Employee).where(Employee.id.in_(ids))
        )
        by_id = {employee.id: employee for employee in employees.all()}
        return [by_id[i] for i in ids if i in by_id]
    return await _recipients(session, task)


async def list_for_employee(
    session: AsyncSession,
    employee: Employee,
    *,
    include_closed: bool = False,
) -> list[Task]:
    """Поручения, «видимые» сотруднику: личные, по подразделению и там, где он
    исполнитель (строки `task_assignments` попадают и в групповые поручения).
    """
    assigned = select(TaskAssignment.task_id).where(
        TaskAssignment.employee_id == employee.id
    )
    stmt = select(Task).where(
        (Task.assignee_employee_id == employee.id)
        | (Task.id.in_(assigned))
        | (
            (Task.scope == TASK_SCOPE_DEPARTMENT)
            & (Task.department_id == employee.department_id)
        )
    )
    if not include_closed:
        stmt = stmt.where(Task.status.notin_((TASK_DONE, TASK_FAILED)))
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


async def submit_work(
    session: AsyncSession,
    task: Task,
    employee: Employee,
    *,
    comment: str | None = None,
    now: datetime | None = None,
) -> Task:
    """Сотрудник сдаёт работу: на проверку или сразу закрывает.

    Разница только в `requires_review`: без проверки поведение прежнее (как было
    до MEGAPROMT2), с проверкой работа уходит руководителю и закрыть её отметкой
    исполнителя нельзя.
    """
    target = TASK_ON_REVIEW if task.requires_review else TASK_DONE
    return await change_status(
        session, task, target, by=employee, comment=comment, now=now
    )


async def pending_reviews(
    session: AsyncSession, *, department_id: int | None = None
) -> list[tuple[Task, TaskAssignment]]:
    """Что ждёт приёмки руководителя: поручения со строками `on_review`."""
    stmt = (
        select(TaskAssignment, Task)
        .join(Task, Task.id == TaskAssignment.task_id)
        .where(TaskAssignment.status == TASK_ON_REVIEW)
        .order_by(Task.due_at.is_(None), Task.due_at, TaskAssignment.id)
    )
    if department_id is not None:
        stmt = stmt.where(Task.department_id == department_id)
    rows = await session.execute(stmt)
    return [(task, assignment) for assignment, task in rows.all()]


async def review(
    session: AsyncSession,
    task: Task,
    *,
    manager: Employee,
    approve: bool,
    employee_id: int | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> list[TaskAssignment]:
    """Принять работу или вернуть на доработку.

    Событие приёмки пишется на ИМЯ ИСПОЛНИТЕЛЯ — иначе опыт за закрытое
    поручение получил бы руководитель, который всего лишь нажал «принять».
    """
    rows = await assignments_of(session, task.id)
    targets = [
        row
        for row in rows
        if row.status == TASK_ON_REVIEW
        and (employee_id is None or row.employee_id == employee_id)
    ]
    if not targets:
        raise TaskError("nothing_to_review")

    moment = now or datetime.now(UTC)
    for assignment in targets:
        assignment.status = TASK_DONE if approve else TASK_REWORK
        assignment.done_at = moment if approve else None
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=TASK_ON_REVIEW,
                to_status=assignment.status,
                by_employee_id=(
                    assignment.employee_id if approve else manager.id
                ),
                comment=f"review_{'accept' if approve else 'rework'}"
                + (f":{comment}" if comment else ""),
            )
        )
    await session.flush()
    await sync_task_status(session, task, by=manager, now=moment)
    return targets


async def set_assignment_status(
    session: AsyncSession,
    task: Task,
    employee: Employee,
    to_status: str,
    *,
    comment: str | None = None,
    now: datetime | None = None,
) -> TaskAssignment:
    """Отметка конкретного исполнителя. Агрегат задачи пересчитывается после."""
    assignment = await assignment_of(session, task.id, employee.id)
    if assignment is None:
        # Историческая задача без строк исполнителей: заводим её на месте,
        # чтобы не терять отметку.
        assignment = TaskAssignment(
            task_id=task.id, employee_id=employee.id, status=task.status
        )
        session.add(assignment)
        await session.flush()

    if to_status not in TASK_STATUSES:
        raise TaskError("bad_status")
    if assignment.status != to_status:
        if not can_transition(assignment.status, to_status):
            raise TaskError(f"bad_transition:{assignment.status}->{to_status}")

    moment = now or datetime.now(UTC)
    assignment.status = to_status
    assignment.done_at = moment if to_status == TASK_DONE else None
    await session.flush()

    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=None,
            to_status=to_status,
            by_employee_id=employee.id,
            comment=f"assignment:{comment or 'status'}",
        )
    )
    await sync_task_status(session, task, by=employee, now=moment)
    return assignment


async def change_status(
    session: AsyncSession,
    task: Task,
    to_status: str,
    *,
    by: Employee | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> Task:
    """Смена статуса от конкретного человека или системно.

    Если у человека есть строка исполнителя, меняется она (и агрегат считается
    по всем); иначе — прежнее поведение с самим статусом задачи: так работают
    исторические задачи и правки администратора/планировщика.
    """
    if by is not None and await assignment_of(session, task.id, by.id) is not None:
        await set_assignment_status(
            session, task, by, to_status, comment=comment, now=now
        )
        return task

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
        assignment = await assignment_of(session, task.id, employee.id)
        current = assignment.status if assignment is not None else task.status
        target = TASK_ON_REVIEW if task.requires_review else TASK_DONE
        if can_transition(current, target):
            await change_status(
                session, task, target, by=employee, comment="photo_report", now=now
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
        # Строки исполнителей тоже уходят в просрочку: иначе в «каждый сам»
        # задача числилась бы просроченной, а у людей висели бы свежие отметки.
        assignments = await assignments_of(session, task.id)
        if assignments:
            for assignment in assignments:
                if assignment.status in OPEN_STATUSES:
                    assignment.status = TASK_OVERDUE
            previous = task.status
            await sync_task_status(session, task, now=moment)
            if task.status == TASK_DONE:
                # Пока шёл тик, все отметились — просрочки нет.
                continue
            if task.status != TASK_OVERDUE:
                # Агрегат не дал просрочку (например, часть работы сделана), но
                # срок прошёл — фиксируем явно, иначе руководитель не узнает.
                session.add(
                    TaskEvent(
                        task_id=task.id,
                        from_status=previous,
                        to_status=TASK_OVERDUE,
                        by_employee_id=None,
                        comment="auto_overdue",
                    )
                )
                task.status = TASK_OVERDUE
            if previous != TASK_OVERDUE:
                # Задача стала просроченной именно сейчас — по ней и уведомляем.
                changed.append(task)
            continue

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
