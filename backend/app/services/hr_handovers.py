"""Передача смены: сдающий фиксирует хвосты, принимающий подтверждает.

Зачем отдельная сущность. Открытые поручения и проблемы уже есть в базе, но
«что именно висело на смене» — состояние на момент передачи, а не текущее.
Через сутки задача закроется, и без снимка никто не докажет, что её вообще
передавали. Поэтому `Handover` + `HandoverItem` хранят копию названий и
статусов, а `ref_id` оставляет ссылку на живые записи.

Правила:

* сдать смену может любой сотрудник, принимать — только выбранный человек;
* подтвердить или вернуть сдачу может ТОЛЬКО принимающий (`to_employee_id`);
* смотреть — участники передачи, руководитель отдела и администратор;
* вернуть сдачу можно только с причиной: «не принял» без объяснения бесполезно.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    HANDOVER_ACCEPTED,
    HANDOVER_ITEM_ISSUE,
    HANDOVER_ITEM_TASK,
    HANDOVER_REJECTED,
    HANDOVER_SENT,
    Employee,
    Handover,
    HandoverItem,
    Issue,
    Task,
)
from app.db.models import User
from app.services import hr_access, hr_checklists, hr_issues, hr_tasks

# Защита от «я передал 400 задач» — в сдачу попадают только открытые хвосты,
# но лимит всё равно нужен: снимок не должен раздуваться на весь квартал.
MAX_ITEMS = 100

BOX_INCOMING = "incoming"
BOX_OUTGOING = "outgoing"
BOX_ALL = "all"


class HandoverError(Exception):
    """Нарушение правил передачи смены (уходит в API как 400/403)."""


@dataclass(frozen=True)
class Snapshot:
    """Один пункт сдачи: то, что видит принимающий в списке."""

    kind: str
    ref_id: int | None
    title: str
    status: str
    meta: str | None = None


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def can_view(employee: Employee, handover: Handover) -> bool:
    if employee.id in {
        handover.from_employee_id,
        handover.to_employee_id,
        handover.accepted_by_employee_id,
    }:
        return True
    if hr_access.is_admin(employee):
        return True
    if not hr_access.is_aup(employee):
        return False
    return (
        employee.department_id is not None
        and handover.department_id == employee.department_id
    )


def can_accept(employee: Employee, handover: Handover) -> bool:
    return (
        handover.status == HANDOVER_SENT
        and handover.to_employee_id == employee.id
    )


def can_reject(employee: Employee, handover: Handover) -> bool:
    return can_accept(employee, handover)


# --------------------------------------------------------------------------
# Что попадает в сдачу
# --------------------------------------------------------------------------


def _task_meta(task: Task) -> str | None:
    parts: list[str] = []
    if task.priority and task.priority != "normal":
        parts.append(f"приоритет {task.priority}")
    if task.due_at is not None:
        parts.append(f"срок {task.due_at:%d.%m %H:%M}")
    return " · ".join(parts) or None


def _issue_meta(issue: Issue) -> str | None:
    parts: list[str] = [issue.severity]
    if issue.zone:
        parts.insert(0, issue.zone)
    return " · ".join(parts)


async def collect_open(session: AsyncSession, employee: Employee) -> list[Snapshot]:
    """Открытые поручения и проблемы, которые видит сдающий.

    Поручения берём личные и по своему отделу; проблемы — тем же правилом
    видимости, что и журнал (`hr_issues.visible_filter`), чтобы сдача не
    вытаскивала чужие карточки.
    """
    task_filters = [Task.assignee_employee_id == employee.id]
    if employee.department_id is not None:
        task_filters.append(Task.department_id == employee.department_id)
    tasks = await session.scalars(
        select(Task)
        .where(Task.status.in_(tuple(hr_tasks.OPEN_STATUSES)), or_(*task_filters))
        .order_by(Task.due_at.is_(None), Task.due_at, Task.id)
        .limit(MAX_ITEMS)
    )

    issue_stmt = select(Issue).where(Issue.status.in_(tuple(hr_issues.OPEN_STATUSES)))
    issue_filter = hr_issues.visible_filter(employee)
    if issue_filter is not None:
        issue_stmt = issue_stmt.where(issue_filter)
    issues = await session.scalars(
        issue_stmt.order_by(Issue.id.desc()).limit(MAX_ITEMS)
    )

    snapshots = [
        Snapshot(
            kind=HANDOVER_ITEM_TASK,
            ref_id=task.id,
            title=task.title,
            status=task.status,
            meta=_task_meta(task),
        )
        for task in tasks.all()
    ]
    snapshots += [
        Snapshot(
            kind=HANDOVER_ITEM_ISSUE,
            ref_id=issue.id,
            title=issue.title,
            status=issue.status,
            meta=_issue_meta(issue),
        )
        for issue in issues.all()
    ]
    return snapshots[:MAX_ITEMS]


# --------------------------------------------------------------------------
# Создание и подтверждение
# --------------------------------------------------------------------------


async def create_handover(
    session: AsyncSession,
    *,
    author: Employee,
    to_employee_id: int,
    note: str | None = None,
    snapshots: list[Snapshot] | None = None,
    shift_date: date | None = None,
) -> Handover:
    if to_employee_id == author.id:
        raise HandoverError("handover_to_self")
    target = await session.get(Employee, to_employee_id)
    if target is None or not target.is_active:
        raise HandoverError("handover_target_unavailable")

    items = snapshots if snapshots is not None else await collect_open(session, author)
    handover = Handover(
        department_id=author.department_id,
        from_employee_id=author.id,
        to_employee_id=target.id,
        status=HANDOVER_SENT,
        note=(note or "").strip()[:2000] or None,
        shift_date=shift_date or hr_checklists.local_today(),
    )
    session.add(handover)
    await session.flush()

    for item in items[:MAX_ITEMS]:
        session.add(
            HandoverItem(
                handover_id=handover.id,
                kind=item.kind,
                ref_id=item.ref_id,
                title=item.title[:500],
                status=item.status,
                meta=(item.meta or "")[:128] or None,
            )
        )
    await session.flush()
    return handover


async def accept(
    session: AsyncSession,
    handover: Handover,
    *,
    actor: Employee,
    note: str | None = None,
) -> Handover:
    if not can_view(actor, handover):
        raise HandoverError("forbidden")
    if not can_accept(actor, handover):
        raise HandoverError("not_addressed_to_you")

    handover.status = HANDOVER_ACCEPTED
    handover.accepted_by_employee_id = actor.id
    handover.accepted_at = datetime.now(UTC)
    clean = (note or "").strip()
    if clean:
        handover.note = (handover.note + "\n" + clean)[-2000:] if handover.note else clean[:2000]
    await session.flush()
    return handover


async def reject(
    session: AsyncSession,
    handover: Handover,
    *,
    actor: Employee,
    reason: str,
) -> Handover:
    if not can_view(actor, handover):
        raise HandoverError("forbidden")
    if not can_reject(actor, handover):
        raise HandoverError("not_addressed_to_you")
    clean = (reason or "").strip()
    if not clean:
        raise HandoverError("reason_required")

    handover.status = HANDOVER_REJECTED
    handover.reject_reason = clean[:2000]
    await session.flush()
    return handover


# --------------------------------------------------------------------------
# Выборки
# --------------------------------------------------------------------------


async def get_handover(session: AsyncSession, handover_id: int) -> Handover | None:
    return await session.get(Handover, handover_id)


async def items_of(session: AsyncSession, handover_id: int) -> list[HandoverItem]:
    rows = await session.scalars(
        select(HandoverItem)
        .where(HandoverItem.handover_id == handover_id)
        .order_by(HandoverItem.kind, HandoverItem.id)
    )
    return list(rows.all())


async def list_for(
    session: AsyncSession,
    employee: Employee,
    *,
    box: str = BOX_ALL,
    limit: int = 50,
) -> list[Handover]:
    stmt = select(Handover)
    if box == BOX_INCOMING:
        stmt = stmt.where(Handover.to_employee_id == employee.id)
    elif box == BOX_OUTGOING:
        stmt = stmt.where(Handover.from_employee_id == employee.id)
    else:
        own = or_(
            Handover.from_employee_id == employee.id,
            Handover.to_employee_id == employee.id,
            Handover.accepted_by_employee_id == employee.id,
        )
        if hr_access.is_admin(employee):
            pass
        elif hr_access.is_aup(employee) and employee.department_id is not None:
            stmt = stmt.where(
                or_(own, Handover.department_id == employee.department_id)
            )
        else:
            stmt = stmt.where(own)
    stmt = stmt.order_by(Handover.created_at.desc(), Handover.id.desc()).limit(
        max(1, min(limit, 200))
    )
    rows = await session.scalars(stmt)
    return list(rows.all())


async def pending_count(session: AsyncSession, employee: Employee) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Handover)
            .where(
                Handover.to_employee_id == employee.id,
                Handover.status == HANDOVER_SENT,
            )
        )
        or 0
    )


async def colleagues(
    session: AsyncSession, employee: Employee
) -> list[tuple[int, str, str | None]]:
    """Кому можно передать смену: активные люди своего отдела.

    Без отдела (онбординг не пройден) — все активные, кроме себя: иначе
    сотрудник не смог бы сдать смену в первый же день.
    """
    stmt = (
        select(Employee.id, User.display_name, Employee.department_id)
        .join(User, User.id == Employee.user_id)
        .where(Employee.is_active.is_(True), Employee.id != employee.id)
        .order_by(User.display_name)
        .limit(200)
    )
    if employee.department_id is not None and not hr_access.is_admin(employee):
        stmt = stmt.where(Employee.department_id == employee.department_id)
    rows = await session.execute(stmt)
    return [(int(eid), str(name), dept) for eid, name, dept in rows.all()]
