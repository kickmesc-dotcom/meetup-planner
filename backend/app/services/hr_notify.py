"""Уведомления HR-ядра: тексты и запись в личные уведомления мини-аппа.

Разделение обязанностей как в `services/notifications.py`: здесь только обёртки
над `notifications.add` + сборка человеческих текстов, а доставку в чат делает
бот (Этап C). Так одно и то же событие можно показать и в приложении
(колокольчик), и в Telegram — из одного места.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, Handover, Issue, Task, TaskIssue
from app.services import notifications

KIND_TASK_ASSIGNED = "task_assigned"
KIND_TASK_DEADLINE = "task_deadline"
KIND_TASK_OVERDUE = "task_overdue"
# Вторая ступень эскалации: руководитель молчит дольше порога — пишем админам.
KIND_TASK_ESCALATED = "task_escalated"
KIND_TASK_ISSUE = "task_issue"
KIND_TASK_DONE = "task_done"
# Проверка руководителем: работа сдана → приёмка → принято/возврат.
KIND_TASK_SUBMITTED = "task_submitted"
KIND_TASK_REVIEWED = "task_reviewed"
KIND_CHECKLIST_DONE = "checklist_done"
# Журнал операционных проблем (не поручения): тихое уведомление в колокольчик.
KIND_ISSUE_CREATED = "issue_created"
KIND_ISSUE_ASSIGNED = "issue_assigned"
# Передача смены: отправлена / принята / возвращена.
KIND_HANDOVER_SENT = "handover_sent"
KIND_HANDOVER_ACCEPTED = "handover_accepted"
KIND_HANDOVER_REJECTED = "handover_rejected"

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


def second_escalation_text(
    title: str, due_at: datetime | None, *, hours: int
) -> str:
    """Текст для админов: не «ещё раз то же», а «руководитель не отреагировал».

    В сообщении есть срок и название поручения — по ним админ найдёт задачу
    без перехода в приложение. Про руководителя пишем нейтрально: получатель
    сам знает, кто в отделе отвечает.
    """
    return (
        f"🚨 Поручение «{title}» просрочено больше {hours} ч, "
        f"реакции руководителя нет (срок {fmt_due(due_at)}). "
        "Нужно вмешательство."
    )


def task_second_escalation_text(task: Task, *, hours: int) -> str:
    return second_escalation_text(task.title, task.due_at, hours=hours)


def task_issue_text(task: Task, issue: TaskIssue) -> str:
    lines = [f"⚠️ Сотрудник сообщил о проблеме по {task_short(task)}."]
    if issue.reason_code:
        lines.append(f"Причина: {issue.reason_code}")
    if issue.comment:
        lines.append(f"Комментарий: {issue.comment}")
    if issue.eta_at is not None:
        lines.append(f"Планирует выполнить к {fmt_due(issue.eta_at)}")
    return "\n".join(lines)


def task_submitted_text(task: Task, *, employee_name: str | None = None) -> str:
    who = f"{employee_name} " if employee_name else ""
    return (
        f"🔍 {who}сдал(а) работу по {task_short(task)} — нужна приёмка. "
        "Открой приёмку в кабинете, чтобы принять или вернуть."
    )


def task_reviewed_text(task: Task, *, approved: bool, comment: str | None) -> str:
    if approved:
        lines = [f"✅ Работа по {task_short(task)} принята."]
    else:
        lines = [f"↩️ Работу по {task_short(task)} вернули на доработку."]
    if comment:
        lines.append(f"Комментарий: {comment}")
    return "\n".join(lines)


def checklist_done_text(template_title: str) -> str:
    return f"✅ Чек-лист «{template_title}» закрыт полностью."


_ISSUE_CATEGORY_LABEL: dict[str, str] = {
    "equipment": "оборудование",
    "supplies": "расходники",
    "staffing": "люди",
    "guest": "гость",
    "cleanliness": "чистота",
    "safety": "безопасность",
    "it": "техника/системы",
    "other": "другое",
}

_ISSUE_SEVERITY_LABEL: dict[str, str] = {
    "low": "не срочно",
    "normal": "обычно",
    "high": "срочно",
    "critical": "авария",
}


def issue_short(issue: Issue) -> str:
    return f"«{issue.title}»"


def issue_created_text(issue: Issue, *, by_name: str | None = None) -> str:
    """Строка для колокольчика: что произошло и где.

    В Telegram журнал не дублируется: операционная проблема — не срочный алерт,
    иначе телефон руководителя звенел бы из-за каждой закончившейся салфетки.
    Срочное по-прежнему идёт отдельным алертом по поручению.
    """
    who = f"{by_name}: " if by_name else ""
    labels = [
        _ISSUE_CATEGORY_LABEL.get(issue.category, issue.category),
        _ISSUE_SEVERITY_LABEL.get(issue.severity, issue.severity),
    ]
    if issue.zone:
        labels.insert(0, issue.zone)
    return f"🛠 {who}новая проблема {issue_short(issue)} ({' · '.join(labels)})"


def issue_assigned_text(issue: Issue) -> str:
    return f"🛠 Тебе передали проблему {issue_short(issue)} — посмотри в журнале."


async def notify_issue_created(
    session: AsyncSession,
    issue: Issue,
    recipients: list[Employee],
    *,
    by_name: str | None = None,
) -> int:
    return await notify(
        session,
        employees=recipients,
        kind=KIND_ISSUE_CREATED,
        text=issue_created_text(issue, by_name=by_name),
        payload={"issue_id": issue.id},
    )


async def notify_issue_assigned(
    session: AsyncSession, issue: Issue, recipient: Employee
) -> int:
    return await notify(
        session,
        employees=[recipient],
        kind=KIND_ISSUE_ASSIGNED,
        text=issue_assigned_text(issue),
        payload={"issue_id": issue.id},
    )


def handover_sent_text(handover: Handover, *, items: int, by_name: str) -> str:
    tail = f"Открытых пунктов: {items}." if items else "Открытых пунктов нет."
    return (
        f"🌙 {by_name} передаёт тебе смену {handover.shift_date:%d.%m}. {tail} "
        "Открой журнал передачи, чтобы принять или вернуть с причиной."
    )


def handover_accepted_text(handover: Handover, *, by_name: str) -> str:
    return f"✅ {by_name} принял(а) передачу смены {handover.shift_date:%d.%m}."


def handover_rejected_text(handover: Handover, *, by_name: str) -> str:
    reason = handover.reject_reason or "без причины"
    return (
        f"↩️ {by_name} вернул(а) передачу смены {handover.shift_date:%d.%m}: "
        f"{reason}"
    )


async def notify_handover_sent(
    session: AsyncSession,
    handover: Handover,
    recipient: Employee,
    *,
    items: int,
    by_name: str,
) -> int:
    return await notify(
        session,
        employees=[recipient],
        kind=KIND_HANDOVER_SENT,
        text=handover_sent_text(handover, items=items, by_name=by_name),
        payload={"handover_id": handover.id},
    )


async def notify_handover_accepted(
    session: AsyncSession,
    handover: Handover,
    recipient: Employee,
    *,
    by_name: str,
) -> int:
    return await notify(
        session,
        employees=[recipient],
        kind=KIND_HANDOVER_ACCEPTED,
        text=handover_accepted_text(handover, by_name=by_name),
        payload={"handover_id": handover.id},
    )


async def notify_handover_rejected(
    session: AsyncSession,
    handover: Handover,
    recipient: Employee,
    *,
    by_name: str,
) -> int:
    return await notify(
        session,
        employees=[recipient],
        kind=KIND_HANDOVER_REJECTED,
        text=handover_rejected_text(handover, by_name=by_name),
        payload={"handover_id": handover.id},
    )


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


async def notify_task_submitted(
    session: AsyncSession,
    task: Task,
    recipients: list[Employee],
    *,
    employee_name: str | None = None,
) -> int:
    return await notify(
        session,
        employees=recipients,
        kind=KIND_TASK_SUBMITTED,
        text=task_submitted_text(task, employee_name=employee_name),
        payload={"task_id": task.id},
    )


async def notify_task_reviewed(
    session: AsyncSession,
    task: Task,
    recipients: list[Employee],
    *,
    approved: bool,
    comment: str | None = None,
) -> int:
    return await notify(
        session,
        employees=recipients,
        kind=KIND_TASK_REVIEWED,
        text=task_reviewed_text(task, approved=approved, comment=comment),
        payload={"task_id": task.id, "approved": approved},
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
