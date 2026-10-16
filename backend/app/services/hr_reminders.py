"""Джобы HR-ядра: напоминания о сроке и автоэскалация просрочки.

Один тик делает две вещи (бриф требует обе, правила настраиваются отдельно):

1. **Напоминание о приближающемся сроке.** Поручения, у которых `due_at`
   попадает в окно «сейчас … сейчас + N минут» и по которым напоминание ещё не
   отправлялось. Факт отправки фиксируем событием `TaskEvent` с комментарием
   `reminder_sent` — отдельной колонки не заводим, история и так пишется, а
   идемпотентность получается бесплатно (повторный тик не спамит).

2. **Эскалация просрочки.** Переводит открытые задачи с прошедшим сроком в
   `overdue` (`hr_tasks.sweep_overdue` — переход срабатывает ровно один раз,
   поэтому и уведомление уходит один раз) и уведомляет руководителей.

Куда уведомляем: **личные уведомления в мини-аппе** (основной канал, он уже
есть) + best-effort **личка в Telegram**, если сотрудник писал боту. В общий
групповой чат HR-события не уходят принципиально: поручения и просрочки — не
новость для всего зала.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    Employee,
    Task,
    TaskEvent,
)
from app.db.models import User
from app.services import hr_notify, hr_settings, hr_tasks

log = structlog.get_logger()

# Комментарий события-маркера «напоминание отправлено».
REMINDER_EVENT_COMMENT = "reminder_sent"

# Сколько задач максимум берём за один тик — защита от лавины после простоя.
BATCH_LIMIT = 200


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def reminder_due(
    task: Task, now: datetime, before_minutes: int
) -> bool:
    """Пора ли напомнить: срок ещё не прошёл и близко.

    Просроченные задачи сюда НЕ попадают: у них своя ветка (эскалация), иначе
    сотрудник получил бы «напоминание» уже после дедлайна.
    """
    if task.due_at is None or task.status not in hr_tasks.OPEN_STATUSES:
        return False
    moment = now if now.tzinfo else now.replace(tzinfo=UTC)
    due = task.due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    if due < moment:
        return False
    return due <= moment + timedelta(minutes=before_minutes)


def unique_employees(employees: list[Employee]) -> list[Employee]:
    """Убрать дубли по `id`, сохранив порядок (один человек — одно уведомление)."""
    seen: set[int] = set()
    out: list[Employee] = []
    for employee in employees:
        if employee.id in seen:
            continue
        seen.add(employee.id)
        out.append(employee)
    return out


def escalation_recipients(
    *, managers: list[Employee], creator: Employee | None
) -> list[Employee]:
    """Кому уходит эскалация просрочки: руководители + автор поручения.

    Дедуплицируем: автор обычно и есть руководитель, и получать два одинаковых
    уведомления ему незачем.
    """
    people = list(managers)
    if creator is not None:
        people.append(creator)
    return unique_employees(people)


# --------------------------------------------------------------------------
# Инфраструктура
# --------------------------------------------------------------------------


async def _reminded_task_ids(
    session: AsyncSession, task_ids: list[int]
) -> set[int]:
    """Задачи, по которым напоминание уже уходило (по событиям)."""
    if not task_ids:
        return set()
    rows = await session.scalars(
        select(TaskEvent.task_id).where(
            TaskEvent.task_id.in_(task_ids),
            TaskEvent.comment == REMINDER_EVENT_COMMENT,
        )
    )
    return {int(t) for t in rows.all()}


async def managers(session: AsyncSession) -> list[Employee]:
    """Все активные руководители и админы — адресаты эскалации и проблем."""
    from app.db.hr_models import ROLE_ADMIN, ROLE_AUP

    rows = await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.role.in_((ROLE_AUP, ROLE_ADMIN)),
        )
    )
    return list(rows.all())


async def _telegram_ids(session: AsyncSession, employees: list[Employee]) -> dict[int, int]:
    """`employee.user_id` → `telegram_id` (один запрос на пачку)."""
    user_ids = [e.user_id for e in employees]
    if not user_ids:
        return {}
    rows = await session.execute(
        select(User.id, User.telegram_id).where(User.id.in_(user_ids))
    )
    return {int(uid): int(tg) for uid, tg in rows.all()}


async def send_dm(bot, telegram_id: int, text: str) -> bool:  # noqa: ANN001
    """Best-effort личка. Сотрудник мог не начинать диалог с ботом — это норма.

    Никаких исключений наружу: не доставленное личное сообщение не должно
    ломать тик планировщика.
    """
    if bot is None or not telegram_id or not text:
        return False
    try:
        await bot.send_message(chat_id=telegram_id, text=text, parse_mode="HTML")
        return True
    except Exception as exc:  # noqa: BLE001
        log.info("hr.dm_failed", telegram_id=telegram_id, error=str(exc))
        return False


async def _deliver(
    session: AsyncSession,
    *,
    bot,  # noqa: ANN001
    employees: list[Employee],
    kind: str,
    text: str,
    payload: dict | None = None,
) -> None:
    """Личное уведомление в приложении + best-effort личка в Telegram."""
    recipients = unique_employees(employees)
    if not recipients:
        return
    await hr_notify.notify(
        session, employees=recipients, kind=kind, text=text, payload=payload
    )
    if bot is None:
        return
    tg_map = await _telegram_ids(session, recipients)
    for employee in recipients:
        tg_id = tg_map.get(employee.user_id)
        if tg_id:
            await send_dm(bot, tg_id, text)


# --------------------------------------------------------------------------
# Тик
# --------------------------------------------------------------------------


async def send_deadline_reminders(
    session: AsyncSession,
    *,
    bot=None,  # noqa: ANN001
    now: datetime | None = None,
    before_minutes: int | None = None,
) -> list[Task]:
    """Разослать напоминания по близким срокам. Возвращает затронутые задачи."""
    moment = now or datetime.now(UTC)
    window = (
        before_minutes
        if before_minutes is not None
        else await hr_settings.get_remind_before_minutes(session)
    )
    horizon = moment + timedelta(minutes=window)
    rows = await session.scalars(
        select(Task)
        .where(
            Task.due_at.is_not(None),
            Task.due_at > moment,
            Task.due_at <= horizon,
            Task.status.in_(tuple(hr_tasks.OPEN_STATUSES)),
        )
        .order_by(Task.due_at)
        .limit(BATCH_LIMIT)
    )
    candidates = list(rows.all())
    already = await _reminded_task_ids(session, [t.id for t in candidates])
    sent: list[Task] = []
    for task in candidates:
        if task.id in already:
            continue
        recipients = await hr_tasks.assignees(session, task)
        await _deliver(
            session,
            bot=bot,
            employees=recipients,
            kind=hr_notify.KIND_TASK_DEADLINE,
            text=f"⏳ Напоминание: {hr_notify.task_short(task)} — срок "
            f"{hr_notify.fmt_due(task.due_at)}",
            payload={"task_id": task.id},
        )
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=task.status,
                to_status=task.status,
                by_employee_id=None,
                comment=REMINDER_EVENT_COMMENT,
            )
        )
        sent.append(task)
    if sent:
        await session.commit()
    return sent


async def escalate_overdue(
    session: AsyncSession,
    *,
    bot=None,  # noqa: ANN001
    now: datetime | None = None,
) -> list[Task]:
    """Пометить просроченные и уведомить руководителей. Возвращает задачи."""
    moment = now or datetime.now(UTC)
    changed = await hr_tasks.sweep_overdue(session, now=moment)
    if not changed:
        return []
    recipients_base = await managers(session)
    for task in changed:
        creator = (
            await session.get(Employee, task.created_by_employee_id)
            if task.created_by_employee_id
            else None
        )
        recipients = escalation_recipients(managers=recipients_base, creator=creator)
        await _deliver(
            session,
            bot=bot,
            employees=recipients,
            kind=hr_notify.KIND_TASK_OVERDUE,
            text=hr_notify.task_overdue_text(task),
            payload={"task_id": task.id},
        )
    await session.commit()
    return changed


async def run_hr_tick(*, bot=None, now: datetime | None = None) -> dict:  # noqa: ANN001
    """Тело job'а планировщика: напоминания + эскалация. Идемпотентно."""
    from app.db.base import get_sessionmaker

    sm = get_sessionmaker()
    reminders = 0
    escalated = 0
    try:
        async with sm() as session:
            if await hr_settings.get_reminders_enabled(session):
                reminders = len(
                    await send_deadline_reminders(session, bot=bot, now=now)
                )
            if await hr_settings.get_escalation_enabled(session):
                escalated = len(await escalate_overdue(session, bot=bot, now=now))
    except Exception as exc:  # noqa: BLE001 — job не имеет права падать
        log.warning("hr.tick_failed", error=str(exc))
    if reminders or escalated:
        log.info("hr.tick_done", reminders=reminders, escalated=escalated)
    return {"reminders": reminders, "escalated": escalated}
