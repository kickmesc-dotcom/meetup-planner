"""Уведомления HR-ядра: тексты и запись в личные уведомления мини-аппа.

Разделение обязанностей как в `services/notifications.py`: здесь только обёртки
над `notifications.add` + сборка человеческих текстов, а доставку в чат делает
бот (Этап C). Так одно и то же событие можно показать и в приложении
(колокольчик), и в Telegram — из одного места.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, Task, TaskIssue
from app.services import notifications

KIND_TASK_ASSIGNED = "task_assigned"
KIND_TASK_DEADLINE = "task_deadline"
KIND_TASK_OVERDUE = "task_overdue"
KIND_TASK_ISSUE = "task_issue"
KIND_TASK_DONE = "task_done"
KIND_CHECKLIST_DONE = "checklist_done"

_TZ = UTC


def fmt_due(dt: datetime | None) -> str:
    """Срок «дд.мм чч:мм» в UTC-подписи; без срока — «без срока»."""
    if dt is None:
        return "без срока"
    return dt.astimezone(_TZ).strftime("%d.%m %H:%M")


def task_short(task: Task) -> str:
    return f"«{task.title}»"


def task_assigned_text(task: Task, *, via_department: bool) -> str:
    who = "подразделению" if via_department else "тебе"
    parts = [f"📌 Новое поручение {who}: {task_short(task)}"]
    if task.due_at is not None:
        parts.append(f"Срок: {fmt_due(task.due_at)}")
    if task.requires_photo:
        parts.append("Нужен фотоотчёт.")
    return "\n".join(parts)


def task_overdue_text(task: Task) -> str:
    return (
        f"⏰ Просрочено поручение {task_short(task)} (срок {fmt_due(task.due_at)}). "
        "Требуется внимание руководителя."
    )


def task_issue_text(task: Task, issue: TaskIssue) -> str:
    lines = [f"⚠️ Сотрудник сообщил о проблеме по {task_short(task)}."]
    if issue.reason_code:
        lines.append(f"Причина: {issue.reason_code}")
    if issue.comment:
        lines.append(f"Комментарий: {issue.comment}")
    if issue.eta_at is not None:
        lines.append(f"Планирует выполнить к {fmt_due(issue.eta_at)}")
    return "\n".join(lines)


def checklist_done_text(template_title: str) -> str:
    return f"✅ Чек-лист «{template_title}» закрыт полностью."


async def notify(
    session: AsyncSession,
    *,
    employees: list[Employee],
    kind: str,
    text: str,
    payload: dict | None = None,
) -> int:
    """Личное уведомление каждому получателю. Коммитит вызывающий.

    `employees` — HR-профили; в уведомление пишем `users.id` (employee.user_id).
    Возвращаем, сколько строк добавлено.
    """
    count = 0
    for employee in employees:
        await notifications.add(
            session,
            user_id=employee.user_id,
            kind=kind,
            text=text,
            payload=payload,
        )
        count += 1
    return count


async def notify_task_assigned(
    session: AsyncSession,
    task: Task,
    recipients: list[Employee],
) -> int:
    from app.db.hr_models import TASK_SCOPE_DEPARTMENT

    text = task_assigned_text(task, via_department=task.scope == TASK_SCOPE_DEPARTMENT)
    return await notify(
        session,
        employees=recipients,
        kind=KIND_TASK_ASSIGNED,
        text=text,
        payload={"task_id": task.id},
    )


async def notify_overdue(
    session: AsyncSession, task: Task, recipients: list[Employee]
) -> int:
    return await notify(
        session,
        employees=recipients,
        kind=KIND_TASK_OVERDUE,
        text=task_overdue_text(task),
        payload={"task_id": task.id},
    )


async def notify_issue(
    session: AsyncSession, task: Task, issue: TaskIssue, recipients: list[Employee]
) -> int:
    return await notify(
        session,
        employees=recipients,
        kind=KIND_TASK_ISSUE,
        text=task_issue_text(task, issue),
        payload={"task_id": task.id, "issue_id": issue.id},
    )
