"""Что мастер настройки реально сделал (B2B_PLATFORM_PLAN, шаг 3.4).

Зачем отдельная сводка, а не «мастер закрылся — значит готово». Мастер
закрывается и кнопкой «Пропустить», поэтому `done` отвечает на вопрос «человек
больше не хочет отвечать», а не «организация готова к рабочему дню». Между
этими двумя состояниями лежит пустой табель и пустой чек-лист: руководитель
уверен, что настроил, сотрудник открывает приложение и видит нечего делать.

Сводка отвечает числами: сколько подразделений, сколько людей, сколько живых
приглашений, есть ли шаблон недели и какие чек-листы уже ждут смену. Экрану
мастера этого достаточно, чтобы на последнем шаге показать не «Всё готово»
вообще, а конкретный список того, что произошло.

Демо-сотрудники (`is_simulation`) в счёт людей не входят: иначе витрина
«покажем на ваших данных» выглядела бы как настоящая команда, и руководитель
решал бы, что приглашать уже некого.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ChecklistItem,
    ChecklistTemplate,
    Department,
    Employee,
    HrShiftTemplate,
)
from app.services import invitations


@dataclass(frozen=True)
class ChecklistBrief:
    """Стартовый чек-лист в сводке: что именно ждёт сотрудников."""

    title: str
    kind: str
    department: str | None
    items: int


@dataclass(frozen=True)
class SetupProgress:
    departments: int
    people: int
    invites_pending: int
    shift_templates: int
    checklists: tuple[ChecklistBrief, ...]


async def _count(session: AsyncSession, model, org_id: int) -> int:
    value = await session.scalar(
        select(func.count()).select_from(model).where(model.org_id == org_id)
    )
    return int(value or 0)


async def summary(session: AsyncSession, *, org_id: int) -> SetupProgress:
    """Сводка по организации. Только чтение, без побочных эффектов."""
    departments = await session.scalars(
        select(Department)
        .where(Department.org_id == org_id)
        .order_by(Department.sort_order, Department.id)
    )
    department_rows = list(departments)
    names = {row.id: row.name for row in department_rows}

    people = await session.scalar(
        select(func.count())
        .select_from(Employee)
        .where(
            Employee.org_id == org_id,
            Employee.is_simulation.is_(False),
        )
    )

    # Шаблоны без зала: чек-лист зала — уточнение общего, а не второй старт.
    templates = list(
        await session.scalars(
            select(ChecklistTemplate)
            .where(
                ChecklistTemplate.org_id == org_id,
                ChecklistTemplate.hall_id.is_(None),
                ChecklistTemplate.is_active.is_(True),
            )
            .order_by(ChecklistTemplate.sort_order, ChecklistTemplate.id)
        )
    )
    items: dict[int, int] = {}
    if templates:
        rows = await session.execute(
            select(ChecklistItem.template_id, func.count(ChecklistItem.id))
            .where(
                ChecklistItem.template_id.in_([row.id for row in templates])
            )
            .group_by(ChecklistItem.template_id)
        )
        items = {int(template_id): int(count) for template_id, count in rows}

    return SetupProgress(
        departments=len(department_rows),
        people=int(people or 0),
        invites_pending=len(await invitations.active(session, org_id)),
        shift_templates=await _count(session, HrShiftTemplate, org_id),
        checklists=tuple(
            ChecklistBrief(
                title=row.title,
                kind=row.kind,
                department=names.get(row.department_id),
                items=items.get(row.id, 0),
            )
            for row in templates
        ),
    )
