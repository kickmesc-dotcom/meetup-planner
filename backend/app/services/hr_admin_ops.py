"""Админские операции над людьми и уведомлениями.

Здесь живёт то, что раньше приходилось делать «руками в базе»:

* **Журнал событий** (`journal`) — человекочитаемая история по поручениям,
  включая системные строки (`auto_overdue`, `reminder_sent`). В кабинете
  управляющего такие строки не показываются: там нужен разбор, а не лог
  планировщика, поэтому журнал живёт в админке.
* **Центр уведомлений** (`notification_feed`) — что уже лежит в колокольчиках
  и что запланировано: когда у кого сработает напоминание о сроке.
* **Пул сотрудников** (`directory`, `update_profile`, `reset_progress`,
  `force_done`) — переименовать, поменять должность, обнулить прогресс
  обучения, зачесть проваленное поручение.
* **Увольнение** (`fire`, `restore`, `purge`, `purge_due`) — доступ закрывается
  сразу, а данные либо уезжают в корзину на 30 дней, либо удаляются сразу.

Правила доступа держит роутер (`AupDep`/`AdminDep`), а область видимости —
здешние `_scope_*` функции: руководитель подразделения видит только своих.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ONBOARDING_NEW,
    ROLE_ADMIN,
    ROLES,
    TASK_DONE,
    TASK_FAILED,
    ChecklistCompletion,
    ChecklistRun,
    Department,
    Employee,
    EmployeeTrainingStep,
    FeedbackAnswer,
    Handover,
    Issue,
    SimulationSession,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskIssue,
    TaskPhoto,
    TaskReminder,
)
from app.db.models import AppNotification, User
from app.db.seed import color_for_user
from app.services import hr_access, hr_demo, hr_roster, hr_settings, hr_tasks

log = structlog.get_logger()

# Сколько данные уволенного лежат в корзине до автоудаления.
TRASH_DAYS = 30

FIRED_TRASH = "trash"
FIRED_PURGE = "purge"
FIRED_MODES = (FIRED_TRASH, FIRED_PURGE)

JOURNAL_LIMIT = 100
NOTIFICATION_LIMIT = 100
PENDING_LIMIT = 50
DIRECTORY_LIMIT = 500

MAX_NAME = 64
MAX_TEXT = 400


class AdminOpsError(Exception):
    """Ошибка админской операции (текст — код для клиента)."""


@dataclass(frozen=True)
class JournalItem:
    at: datetime
    kind: str
    text: str
    is_system: bool
    task_id: int | None
    task_title: str | None
    employee_id: int | None
    display_name: str | None


@dataclass(frozen=True)
class NotificationItem:
    id: int
    kind: str
    text: str
    created_at: datetime
    read_at: datetime | None
    employee_id: int | None
    user_id: int
    display_name: str | None
    department_name: str | None


@dataclass(frozen=True)
class PendingNotification:
    kind: str
    at: datetime
    text: str
    task_id: int
    task_title: str
    employee_id: int
    display_name: str
    # Время сдвинули вручную (админка), а не посчитал планировщик.
    moved: bool = False


@dataclass(frozen=True)
class DisabledReminder:
    """Напоминание, выключенное вручную: его можно вернуть одной кнопкой."""

    task_id: int
    task_title: str
    employee_id: int
    display_name: str


@dataclass(frozen=True)
class EmployeeCard:
    employee_id: int
    user_id: int
    telegram_id: int
    display_name: str
    position: str | None
    badge: str | None
    badge_emoji: str | None
    role: str
    department_id: int | None
    department_name: str | None
    onboarding_state: str
    learning_mode: bool
    is_demo: bool
    is_active: bool
    fired_at: datetime | None
    purge_after: datetime | None
    # «Профиль открыт»: видят ли коллеги карточку с активностью.
    profile_public: bool = True


# --------------------------------------------------------------------------
# Область видимости
# --------------------------------------------------------------------------


def _is_all(viewer: Employee) -> bool:
    """Управляющий видит всё, руководитель — только своё подразделение."""
    return hr_access.is_admin(viewer) or viewer.department_id is None


async def _department_people(session: AsyncSession, department_id: int) -> set[int]:
    rows = await session.scalars(
        select(Employee.id).where(
            Employee.department_id == department_id,
            Employee.is_simulation.is_(False),
        )
    )
    return {int(value) for value in rows.all()}


async def _scoped_task_ids(session: AsyncSession, viewer: Employee) -> set[int] | None:
    """id поручений в области видимости; `None` — все."""
    if _is_all(viewer):
        return None
    people = await _department_people(session, int(viewer.department_id or 0))
    rows = await session.scalars(
        select(Task.id).where(
            or_(
                Task.department_id == viewer.department_id,
                Task.assignee_employee_id.in_(people | {viewer.id}),
                Task.created_by_employee_id.in_(people | {viewer.id}),
            )
        )
    )
    return {int(value) for value in rows.all()}


# --------------------------------------------------------------------------
# Журнал событий
# --------------------------------------------------------------------------


def action_text(to_status: str | None, comment: str | None) -> tuple[str, bool]:
    """Человекочитаемый текст события поручения и признак «системное».

    Системные строки пишет планировщик (`auto_overdue`, `reminder_sent`) —
    руководителю в кабинете они не нужны, а в админском журнале нужны: по ним
    понятно, ушло ли напоминание и когда поручение стало просроченным.
    """
    value = (comment or "").strip()
    if value == "reminder_sent":
        return "напомнил(а) о сроке поручения (авто)", True
    if value == "auto_overdue":
        return "отметил(а) просрочку поручения (авто)", True
    if value.startswith("created"):
        return "поставил(а) поручение", False
    if value.startswith("assignment:force_done"):
        return "зачёл поручение вручную", False
    labels = {
        "accepted": "принял(а) поручение",
        "in_progress": "взял(а) поручение в работу",
        "on_review": "сдал(а) работу на проверку",
        "rework": "получил(а) доработку",
        "done": "выполнил(а) поручение",
        "overdue": "просрочил(а) поручение",
        "failed": "отметил(а) поручение как невыполненное",
        "new": "поставил(а) поручение",
    }
    return labels.get(to_status or "", "изменил(а) статус поручения"), False


async def journal(
    session: AsyncSession, viewer: Employee, *, limit: int = JOURNAL_LIMIT
) -> list[JournalItem]:
    """Последние события поручений — с системными строками и без «сырых» кодов."""
    scoped = await _scoped_task_ids(session, viewer)
    stmt = (
        select(
            TaskEvent.at,
            TaskEvent.to_status,
            TaskEvent.comment,
            Task.id,
            Task.title,
            TaskEvent.by_employee_id,
            User.display_name,
        )
        .join(Task, Task.id == TaskEvent.task_id)
        .outerjoin(Employee, Employee.id == TaskEvent.by_employee_id)
        .outerjoin(User, User.id == Employee.user_id)
        .order_by(TaskEvent.at.desc(), TaskEvent.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if scoped is not None:
        if not scoped:
            return []
        stmt = stmt.where(Task.id.in_(scoped))
    rows = (await session.execute(stmt)).all()
    items: list[JournalItem] = []
    for at, to_status, comment, task_id, title, employee_id, name in rows:
        text, is_system = action_text(to_status, comment)
        items.append(
            JournalItem(
                at=at,
                kind=to_status,
                text=text,
                is_system=is_system,
                task_id=int(task_id),
                task_title=str(title),
                employee_id=int(employee_id) if employee_id else None,
                display_name=str(name) if name else None,
            )
        )
    return items


# --------------------------------------------------------------------------
# Уведомления
# --------------------------------------------------------------------------


def _schedule_of(task: Task, before_minutes: int) -> datetime | None:
    """Когда по этому поручению уйдёт напоминание о сроке."""
    if task.due_at is None:
        return None
    due = task.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return due - timedelta(minutes=before_minutes)


async def notification_feed(
    session: AsyncSession, viewer: Employee, *, limit: int = NOTIFICATION_LIMIT
) -> tuple[
    list[NotificationItem],
    list[PendingNotification],
    datetime | None,
    list[DisabledReminder],
]:
    """Уже отправленные уведомления + те, что ещё сработают.

    Третье значение — до какого момента глушатся алерты в Telegram
    (`hr.notify.muted_until`): админка показывает это в одном месте с самими
    уведомлениями, а не в отдельной настройке. Четвёртое — напоминания,
    выключенные вручную, чтобы их можно было вернуть.
    """
    dept_people: set[int] | None = None
    if not _is_all(viewer):
        dept_people = await _department_people(session, int(viewer.department_id or 0))
        dept_people.add(int(viewer.id))

    stmt = (
        select(
            AppNotification.id,
            AppNotification.kind,
            AppNotification.text,
            AppNotification.created_at,
            AppNotification.read_at,
            AppNotification.user_id,
            Employee.id,
            User.display_name,
            Department.name,
        )
        .join(User, User.id == AppNotification.user_id)
        .outerjoin(Employee, Employee.user_id == AppNotification.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .order_by(AppNotification.created_at.desc(), AppNotification.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if dept_people is not None:
        # Руководителю — только уведомления своих людей. Записи без профиля
        # (медиа/игры) в его смене не участвуют.
        stmt = stmt.where(Employee.id.in_(dept_people))
    rows = (await session.execute(stmt)).all()
    items = [
        NotificationItem(
            id=int(nid),
            kind=str(kind),
            text=str(text),
            created_at=created_at,
            read_at=read_at,
            employee_id=int(eid) if eid else None,
            user_id=int(uid),
            display_name=str(name) if name else None,
            department_name=str(dept) if dept else None,
        )
        for nid, kind, text, created_at, read_at, uid, eid, name, dept in rows
    ]

    settings = await hr_settings.snapshot(session)
    before_minutes = int(settings.get("remind_before_minutes") or 60)
    seconds = int(settings.get("escalation_second_hours") or 4) * 3600
    now = datetime.now(UTC)

    task_stmt = (
        select(
            Task.id,
            Task.title,
            Task.due_at,
            Task.mode,
            Task.department_id,
            Employee.id,
            User.display_name,
        )
        .join(
            TaskAssignment,
            (TaskAssignment.task_id == Task.id) & (TaskAssignment.status != TASK_DONE),
        )
        .join(Employee, Employee.id == TaskAssignment.employee_id)
        .join(User, User.id == Employee.user_id)
        .where(
            Task.status.notin_((TASK_DONE, TASK_FAILED)),
            Task.due_at.is_not(None),
            Employee.is_active.is_(True),
            Employee.fired_at.is_(None),
            Employee.is_simulation.is_(False),
        )
        .order_by(Task.due_at)
        .limit(max(1, min(limit, 500)))
    )
    if dept_people is not None:
        task_stmt = task_stmt.where(
            or_(
                Task.department_id == viewer.department_id,
                TaskAssignment.employee_id.in_(dept_people),
            )
        )
    scoped_tasks = await _scoped_task_ids(session, viewer)
    if scoped_tasks is not None:
        if not scoped_tasks:
            return items, [], await _muted_until(session), []
        task_stmt = task_stmt.where(Task.id.in_(scoped_tasks))

    task_rows = (await session.execute(task_stmt)).all()
    rules: dict[int, TaskReminder] = {}
    if task_rows:
        for rule in (
            await session.scalars(
                select(TaskReminder).where(
                    TaskReminder.task_id.in_([int(row[0]) for row in task_rows])
                )
            )
        ).all():
            rules[int(rule.task_id)] = rule

    pending: list[PendingNotification] = []
    disabled: list[DisabledReminder] = []
    for task_id, title, due_at, _mode, _dept, employee_id, name in task_rows:
        rule = rules.get(int(task_id))
        if rule is not None and rule.skip:
            disabled.append(
                DisabledReminder(
                    task_id=int(task_id),
                    task_title=str(title),
                    employee_id=int(employee_id),
                    display_name=str(name),
                )
            )
            continue
        due = due_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        moved = rule is not None and rule.remind_at is not None
        remind_at = (
            rule.remind_at
            if moved and rule is not None and rule.remind_at is not None
            else due - timedelta(minutes=before_minutes)
        )
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=UTC)
        escalation_at = due + timedelta(seconds=seconds)
        if remind_at > now:
            pending.append(
                PendingNotification(
                    kind="deadline",
                    at=remind_at,
                    text=(
                        "Перенесённое напоминание о сроке"
                        if moved
                        else f"Напоминание за {before_minutes} мин до срока"
                    ),
                    task_id=int(task_id),
                    task_title=str(title),
                    employee_id=int(employee_id),
                    display_name=str(name),
                    moved=moved,
                )
            )
        elif not moved and escalation_at > now:
            pending.append(
                PendingNotification(
                    kind="escalation",
                    at=escalation_at,
                    text="Вторая ступень: срок прошёл, руководитель молчит",
                    task_id=int(task_id),
                    task_title=str(title),
                    employee_id=int(employee_id),
                    display_name=str(name),
                )
            )
    pending.sort(key=lambda item: item.at)
    return items, pending[:PENDING_LIMIT], await _muted_until(session), disabled


async def _muted_until(session: AsyncSession) -> datetime | None:
    """До какого момента заглушены Telegram-алерты (или `None`)."""
    return await hr_settings.get_muted_until(session)


async def _task_for_reminder(
    session: AsyncSession, viewer: Employee, task_id: int
) -> Task:
    """Поручение в области видимости, по которому ещё можно напомнить."""
    task = await session.get(Task, task_id)
    if task is None or task.status in (TASK_DONE, TASK_FAILED):
        raise AdminOpsError("task_not_found")
    scoped = await _scoped_task_ids(session, viewer)
    if scoped is not None and int(task_id) not in scoped:
        raise AdminOpsError("task_not_found")
    if task.due_at is not None:
        due = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=UTC)
        if due <= _now():
            raise AdminOpsError("task_overdue")
    return task


async def _rule_of(
    session: AsyncSession, task_id: int, *, create: bool
) -> TaskReminder | None:
    rule = await session.scalar(
        select(TaskReminder).where(TaskReminder.task_id == int(task_id))
    )
    if rule is None and create:
        rule = TaskReminder(task_id=int(task_id), skip=False)
        session.add(rule)
        await session.flush()
    return rule


async def postpone_pending(
    session: AsyncSession, viewer: Employee, task_id: int, *, minutes: int
) -> datetime:
    """Передвинуть напоминание по поручению, не меняя сам срок.

    `minutes` — на сколько сдвинуть от текущего плана. Позже дедлайна не
    переносим: напоминание после срока уже бесполезно. Если задача уже
    просрочена, менять нечего — это работа эскалации, а не напоминания.
    """
    span = max(5, min(int(minutes), 7 * 24 * 60))
    task = await _task_for_reminder(session, viewer, task_id)
    settings = await hr_settings.snapshot(session)
    before = int(settings.get("remind_before_minutes") or 60)
    now = _now()
    if task.due_at is None:
        target = now + timedelta(minutes=span)
    else:
        due = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=UTC)
        default_at = due - timedelta(minutes=before)
        target = max(now, default_at) + timedelta(minutes=span)
        if target > due - timedelta(minutes=1):
            raise AdminOpsError("too_late")
    rule = await _rule_of(session, int(task_id), create=True)
    assert rule is not None
    rule.remind_at = target
    rule.skip = False
    rule.updated_by_id = int(viewer.id)
    await session.commit()
    return target


async def skip_pending(session: AsyncSession, viewer: Employee, task_id: int) -> None:
    """Выключить напоминание о сроке по поручению.

    Вторая ступень — отдельный сценарий (срок уже прошёл), её этот выключатель
    не трогает: иначе «убрать напоминание» незаметно отключало бы эскалацию
    руководителям.
    """
    await _task_for_reminder(session, viewer, task_id)
    rule = await _rule_of(session, int(task_id), create=True)
    assert rule is not None
    rule.skip = True
    rule.remind_at = None
    rule.updated_by_id = int(viewer.id)
    await session.commit()


async def reset_pending(session: AsyncSession, viewer: Employee, task_id: int) -> None:
    """Вернуть напоминание к расчёту планировщика."""
    await _task_for_reminder(session, viewer, task_id)
    await session.execute(
        delete(TaskReminder).where(TaskReminder.task_id == int(task_id))
    )
    await session.commit()


async def cancel_notification(session: AsyncSession, notification_id: int) -> bool:
    """Убрать личное уведомление из колокольчика (админка)."""
    result = await session.execute(
        delete(AppNotification).where(AppNotification.id == notification_id)
    )
    await session.commit()
    return bool(result.rowcount)


async def send_notification(
    session: AsyncSession, *, employee: Employee, text: str
) -> AppNotification:
    """Личное сообщение сотруднику в приложение (в Telegram не дублируем)."""
    clean = text.strip()
    if not clean:
        raise AdminOpsError("empty_text")
    if len(clean) > MAX_TEXT:
        raise AdminOpsError("text_too_long")
    row = AppNotification(
        user_id=int(employee.user_id),
        kind="manual",
        text=clean,
        payload={"manual": True, "by_employee_id": None},
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


# --------------------------------------------------------------------------
# Пул сотрудников
# --------------------------------------------------------------------------


async def directory(session: AsyncSession, viewer: Employee) -> list[EmployeeCard]:
    """Сотрудники со всеми полями, которые админка умеет править."""
    stmt = (
        select(
            Employee,
            User.display_name,
            User.telegram_id,
            Department.name,
        )
        .join(User, User.id == Employee.user_id)
        .outerjoin(Department, Department.id == Employee.department_id)
        .where(Employee.is_simulation.is_(False))
        .order_by(Employee.is_active.desc(), User.display_name)
        .limit(DIRECTORY_LIMIT)
    )
    if not _is_all(viewer):
        stmt = stmt.where(Employee.department_id == viewer.department_id)
    rows = (await session.execute(stmt)).all()
    return [
        EmployeeCard(
            employee_id=int(employee.id),
            user_id=int(employee.user_id),
            telegram_id=int(tg_id),
            display_name=str(name),
            position=employee.position,
            badge=employee.badge,
            badge_emoji=employee.badge_emoji,
            role=str(employee.role),
            department_id=employee.department_id,
            department_name=str(dept) if dept else None,
            onboarding_state=str(employee.onboarding_state),
            learning_mode=bool(employee.learning_mode),
            is_demo=bool(employee.is_demo),
            is_active=bool(employee.is_active),
            fired_at=employee.fired_at,
            purge_after=employee.purge_after,
            profile_public=bool(employee.profile_public),
        )
        for employee, name, tg_id, dept in rows
    ]


async def add_person(
    session: AsyncSession,
    viewer: Employee,
    *,
    telegram_id: int | str,
    display_name: str | None = None,
    department_id: int | None = None,
    position: str | None = None,
    badge: str | None = None,
    role: str | None = None,
) -> EmployeeCard:
    """Завести человека по Telegram-ID, не дожидаясь его первого входа.

    Зачем руками: сотрудник может ещё не открыть бота (или открыть не тот бот),
    а место в пуле уже нужно — например, чтобы выдать ему поручение в первый же
    день. Раньше для этого приходилось ждать его захода или лезть в базу.

    Правила простые: ID проверяется (`hr_roster.normalize_telegram_id`),
    существующий профиль не перезаписывается — иначе кнопка «добавить» молча
    стёрла бы человеку имя и отдел. Уволенного возвращаем текстом-подсказкой
    (его место — «Вернуть из корзины»), а не создаём второй профиль.
    """
    try:
        number = hr_roster.normalize_telegram_id(telegram_id)
    except hr_roster.RosterError as exc:
        raise AdminOpsError(str(exc)) from exc
    if role is not None and role not in ROLES:
        raise AdminOpsError("bad_role")
    if department_id is not None:
        department = await session.get(Department, department_id)
        if department is None:
            raise AdminOpsError("department_not_found")

    user = await session.scalar(select(User).where(User.telegram_id == number))
    if user is not None:
        existing = await session.scalar(
            select(Employee).where(Employee.user_id == user.id)
        )
        if existing is not None:
            raise AdminOpsError(
                "employee_fired" if existing.fired_at is not None else "already_exists"
            )
    else:
        user = User(
            telegram_id=number,
            display_name=hr_roster.clean_name(display_name, number),
            color_hex=color_for_user(number),
        )
        session.add(user)
        await session.flush()

    employee = Employee(
        user_id=int(user.id),
        role=role or hr_access.default_role_for(number),
        onboarding_state=ONBOARDING_NEW,
        department_id=department_id,
        position=(position or "").strip()[:MAX_NAME] or None,
        badge=(badge or "").strip()[:MAX_NAME] or None,
    )
    session.add(employee)
    await session.flush()
    if role is not None:
        # Ручной выбор роли сильнее env-списка админов (`ensure_employee`).
        hr_access.set_role(employee, role)
    await session.commit()
    log.info("hr.admin.person_added", employee_id=int(employee.id), telegram_id=number)
    return await _card_of(session, viewer, int(employee.id))


async def employee_in_scope(
    session: AsyncSession, viewer: Employee, employee_id: int
) -> Employee:
    employee = await session.get(Employee, employee_id)
    if employee is None or employee.is_simulation:
        raise AdminOpsError("employee_not_found")
    if not _is_all(viewer) and employee.department_id != viewer.department_id:
        # Руководитель правит только своё подразделение; чужой id не подтверждаем.
        raise AdminOpsError("employee_not_found")
    return employee


async def card_by_telegram_id(
    session: AsyncSession, viewer: Employee, telegram_id: int
) -> EmployeeCard:
    """Карточка человека по Telegram-ID (для админки: выдать роль, проверить).

    Ищем по `users.telegram_id`, а не по загруженному списку пула: список
    ограничен `DIRECTORY_LIMIT`, и человек из хвоста выглядел бы «не найдённым».
    Область видимости та же, что у пула: руководитель подразделения найдёт
    только своих.
    """
    user = await session.scalar(select(User).where(User.telegram_id == int(telegram_id)))
    if user is None:
        raise AdminOpsError("employee_not_found")
    employee = await session.scalar(
        select(Employee).where(Employee.user_id == user.id, Employee.is_simulation.is_(False))
    )
    if employee is None:
        raise AdminOpsError("employee_not_found")
    return await _card_of(session, viewer, int(employee.id))


async def update_profile(
    session: AsyncSession,
    viewer: Employee,
    employee_id: int,
    *,
    display_name: str | None = None,
    position: str | None = None,
    badge: str | None = None,
    badge_emoji: str | None = None,
    role: str | None = None,
) -> EmployeeCard:
    """Переименование, должность/плашка и роль. Пустая строка = очистить поле.

    Роль меняет только администратор: руководитель подразделения может
    переименовать человека и поправить должность, но не выдать себе или соседу
    права выше своих.
    """
    employee = await employee_in_scope(session, viewer, employee_id)
    if role is not None:
        if not hr_access.is_admin(viewer):
            raise AdminOpsError("role_admin_only")
        if role not in ROLES:
            raise AdminOpsError("bad_role")
        if int(employee.id) == int(viewer.id) and role != ROLE_ADMIN:
            # Себя понижать можно только осознанно — через «Примерить роль» в
            # профиле, где рядом написано, как вернуть права обратно.
            raise AdminOpsError("cannot_demote_self")
        hr_access.set_role(employee, role)
    if display_name is not None:
        clean = display_name.strip()
        if not clean:
            raise AdminOpsError("empty_name")
        if len(clean) > MAX_NAME:
            raise AdminOpsError("name_too_long")
        user = await session.get(User, employee.user_id)
        if user is None:
            raise AdminOpsError("employee_not_found")
        # Тестовый пул носит метку `[BOT]` в имени: правка из админки не должна
        # её срезать, иначе тестовые люди станут неотличимы от настоящих.
        user.display_name = (
            hr_demo.demo_title(clean) if employee.is_demo else clean
        )
    if position is not None:
        employee.position = position.strip()[:MAX_NAME] or None
    if badge is not None:
        employee.badge = badge.strip()[:MAX_NAME] or None
    if badge_emoji is not None:
        employee.badge_emoji = badge_emoji.strip()[:8] or None
    await session.commit()
    cards = {card.employee_id: card for card in await directory(session, viewer)}
    card = cards.get(employee_id)
    if card is None:
        raise AdminOpsError("employee_not_found")
    return card


async def reset_progress(
    session: AsyncSession, viewer: Employee, employee_id: int
) -> EmployeeCard:
    """Обнулить прогресс знакомства: онбординг, уроки и режим обучения.

    Отдел и опыт не трогаем: иначе у человека исчезнет чек-лист смены, и это
    выглядело бы как поломка, а не как «начать знакомство заново».
    """
    employee = await employee_in_scope(session, viewer, employee_id)
    await session.execute(
        delete(EmployeeTrainingStep).where(
            EmployeeTrainingStep.employee_id == employee.id
        )
    )
    employee.onboarding_state = ONBOARDING_NEW
    employee.learning_mode = False
    await session.commit()
    cards = {card.employee_id: card for card in await directory(session, viewer)}
    card = cards.get(employee_id)
    if card is None:
        raise AdminOpsError("employee_not_found")
    return card


async def force_done(
    session: AsyncSession,
    viewer: Employee,
    task_id: int,
    employee_id: int,
    *,
    comment: str | None = None,
) -> Task:
    """Засчитать проваленное поручение выполненным за конкретного человека.

    Живёт в админке, потому что это ручное решение, а не рабочий статус: в
    обычном потоке `failed → done` закрывает руководитель приёмкой.
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise AdminOpsError("task_not_found")
    scoped = await _scoped_task_ids(session, viewer)
    if scoped is not None and task_id not in scoped:
        raise AdminOpsError("task_not_found")
    employee = await employee_in_scope(session, viewer, employee_id)
    assignment = await hr_tasks.assignment_of(session, task_id, employee.id)
    if assignment is None:
        raise AdminOpsError("assignment_not_found")
    if assignment.status == TASK_DONE:
        raise AdminOpsError("already_done")
    try:
        await hr_tasks.set_assignment_status(
            session,
            task,
            employee,
            TASK_DONE,
            comment=(comment or "").strip()[:120] or "force_done",
        )
    except hr_tasks.TaskError as exc:
        raise AdminOpsError(str(exc)) from exc
    await session.commit()
    await session.refresh(task)
    return task


# --------------------------------------------------------------------------
# Увольнение, корзина и удаление
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


async def fire(
    session: AsyncSession,
    viewer: Employee,
    employee_id: int,
    *,
    mode: str,
    restore_days: int = TRASH_DAYS,
) -> EmployeeCard:
    """Уволить: доступ закрывается сразу, данные — по выбранному режиму."""
    if mode not in FIRED_MODES:
        raise AdminOpsError("bad_mode")
    employee = await employee_in_scope(session, viewer, employee_id)
    if int(employee.id) == int(viewer.id):
        raise AdminOpsError("cannot_fire_self")
    if hr_access.is_admin(employee) and not hr_access.is_admin(viewer):
        raise AdminOpsError("cannot_fire_admin")
    if employee.fired_at is not None:
        raise AdminOpsError("already_fired")

    employee.fired_at = _now()
    employee.fired_mode = mode
    employee.is_active = False
    employee.purge_after = (
        _now() + timedelta(days=max(1, restore_days)) if mode == FIRED_TRASH else None
    )
    await session.commit()
    if mode == FIRED_PURGE:
        # Снимок ДО удаления: строка ещё на месте, состав полный. Это и есть
        # страховка «не потерять пул заведённых ID».
        await hr_roster.capture(
            session,
            created_by_employee_id=int(viewer.id),
            kind=hr_roster.KIND_AUTO,
            source=f"fire:{employee_id}",
            label="Перед удалением сотрудника",
        )
        await purge_data(session, employee_id)
    return await _card_of(session, viewer, employee_id)


async def restore(session: AsyncSession, viewer: Employee, employee_id: int) -> EmployeeCard:
    """Вернуть из корзины: доступ и данные на месте до истечения срока."""
    employee = await employee_in_scope(session, viewer, employee_id)
    if employee.fired_at is None:
        raise AdminOpsError("not_fired")
    if employee.fired_mode == FIRED_PURGE:
        raise AdminOpsError("already_purged")
    employee.fired_at = None
    employee.purge_after = None
    employee.fired_mode = None
    employee.is_active = True
    await session.commit()
    return await _card_of(session, viewer, employee_id)


async def _card_of(
    session: AsyncSession, viewer: Employee, employee_id: int
) -> EmployeeCard:
    cards = {card.employee_id: card for card in await directory(session, viewer)}
    card = cards.get(employee_id)
    if card is None:
        raise AdminOpsError("employee_not_found")
    return card


async def purge_data(session: AsyncSession, employee_id: int) -> None:
    """Удалить HR-данные сотрудника: поручения, смены, проблемы, уведомления.

    Профиль (`Employee`) и строка `users` остаются: первая нужна как
    «надгробие», чтобы уволенный не завёлся заново, вторая держит историю
    календаря и чата. Удаляем именно работу: задачи с отметками и событиями,
    прогоны чек-листов, проблемы, обучение, обратную связь, передачи смены.
    """
    task_ids = [
        int(value)
        for value in (
            await session.scalars(
                select(Task.id).where(
                    or_(
                        Task.created_by_employee_id == employee_id,
                        Task.assignee_employee_id == employee_id,
                        Task.id.in_(
                            select(TaskAssignment.task_id).where(
                                TaskAssignment.employee_id == employee_id
                            )
                        ),
                    )
                )
            )
        ).all()
    ]
    run_ids = [
        int(value)
        for value in (
            await session.scalars(
                select(ChecklistRun.id).where(ChecklistRun.employee_id == employee_id)
            )
        ).all()
    ]
    if run_ids:
        await session.execute(
            delete(ChecklistCompletion).where(ChecklistCompletion.run_id.in_(run_ids))
        )
        await session.execute(delete(ChecklistRun).where(ChecklistRun.id.in_(run_ids)))
    if task_ids:
        for model, column in (
            (TaskAssignment, TaskAssignment.task_id),
            (TaskEvent, TaskEvent.task_id),
            (TaskPhoto, TaskPhoto.task_id),
            (TaskIssue, TaskIssue.task_id),
        ):
            await session.execute(delete(model).where(column.in_(task_ids)))
        await session.execute(
            delete(AppNotification).where(
                AppNotification.payload["task_id"].astext.in_(
                    [str(value) for value in task_ids]
                )
            )
        )
        await session.execute(delete(Task).where(Task.id.in_(task_ids)))
    await session.execute(
        delete(Issue).where(
            or_(
                Issue.created_by_employee_id == employee_id,
                Issue.assignee_employee_id == employee_id,
            )
        )
    )
    await session.execute(
        delete(EmployeeTrainingStep).where(
            EmployeeTrainingStep.employee_id == employee_id
        )
    )
    await session.execute(
        delete(FeedbackAnswer).where(FeedbackAnswer.employee_id == employee_id)
    )
    await session.execute(
        delete(Handover).where(
            or_(
                Handover.from_employee_id == employee_id,
                Handover.to_employee_id == employee_id,
            )
        )
    )
    await session.execute(
        delete(AppNotification).where(
            AppNotification.payload["employee_id"].astext == str(employee_id)
        )
    )
    await session.execute(
        delete(SimulationSession).where(
            SimulationSession.subject_employee_id == employee_id
        )
    )
    await session.commit()
    log.info("hr.employee_purged", employee_id=employee_id, tasks=len(task_ids))


async def purge_due(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Снести корзины с истёкшим сроком. Возвращает, сколько удалено."""
    moment = now or _now()
    rows = await session.scalars(
        select(Employee.id).where(
            Employee.purge_after.is_not(None),
            Employee.purge_after <= moment,
        )
    )
    ids = [int(value) for value in rows.all()]
    for employee_id in ids:
        await purge_data(session, employee_id)
    return len(ids)


async def trash_size(session: AsyncSession) -> int:
    """Сколько людей лежит в корзине — для бейджа в админке."""
    count = await session.scalar(
        select(func.count())
        .select_from(Employee)
        .where(Employee.fired_at.is_not(None))
    )
    return int(count or 0)


__all__ = [
    "DIRECTORY_LIMIT",
    "FIRED_MODES",
    "FIRED_PURGE",
    "FIRED_TRASH",
    "TRASH_DAYS",
    "AdminOpsError",
    "DisabledReminder",
    "EmployeeCard",
    "JournalItem",
    "NotificationItem",
    "PendingNotification",
    "action_text",
    "cancel_notification",
    "directory",
    "employee_in_scope",
    "fire",
    "force_done",
    "journal",
    "notification_feed",
    "postpone_pending",
    "purge_due",
    "reset_pending",
    "reset_progress",
    "restore",
    "send_notification",
    "skip_pending",
    "trash_size",
    "update_profile",
]
