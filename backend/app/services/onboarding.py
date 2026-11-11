"""Онбординг: цифры вместо ощущений (этап 8, AAA_ROADMAP).

Зачем. Usability-тест отвечает на вопрос «где человек застрял» на пяти людях, но
не отвечает «сколько людей вообще доходит» на всех клиентах. Опыт и чек-листы уже
лежат в базе, поэтому отдельные «события онбординга» не нужны: считаем по фактам —
первое закрытое поручение и первый закрытый чек-лист.

Что считается успехом. Не «открыл экран», а «закрыл задачу»: это единственное
действие, которое подтверждает, что человек понял работу. Время — от `created_at`
профиля (момент, когда его завели), а не от `hire_date`: профиль может появиться
позже найма, и тогда метрика врала бы в меньшую сторону.

Почему медиана, а не среднее. Один сотрудник, вернувшийся из отпуска и закрывший
задачу через месяц, сдвинул бы среднее на дни. Медиана показывает типичный путь.

Демо- и симуляционные профили исключены: их «активность» создаёт бот, и они
испортили бы долю дошедших.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ONBOARDING_DONE,
    TASK_DONE,
    ChecklistRun,
    Employee,
    TaskEvent,
)
from app.db.org_models import Organization
from app.db.tenancy import all_orgs


def _hours(start: datetime, end: datetime) -> float:
    """Часы между моментами; отрицательное время считаем нулём.

    Отрицательное бывает у импортированных данных: `created_at` профиля
    выставился при импорте, а событие пришло с датой раньше. Это не «дошёл за
    минус два часа», это шум, и он не должен портить медиану.
    """
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 1)


def _share(part: int, total: int) -> float:
    return round(part / total, 3) if total else 0.0


async def snapshot(session: AsyncSession) -> dict[str, Any]:
    """Сводка онбординга по всем организациям и итог по платформе."""
    with all_orgs():
        orgs = list(await session.scalars(select(Organization).order_by(Organization.id)))
        employees = list(
            await session.scalars(
                select(Employee).where(
                    Employee.is_demo.is_(False),
                    Employee.is_simulation.is_(False),
                )
            )
        )
        done_events = list(
            await session.scalars(
                select(TaskEvent).where(
                    TaskEvent.to_status == TASK_DONE,
                    TaskEvent.by_employee_id.is_not(None),
                )
            )
        )
        done_runs = list(
            await session.scalars(
                select(ChecklistRun).where(ChecklistRun.completed_at.is_not(None))
            )
        )

    first_task: dict[int, datetime] = {}
    for event in done_events:
        if event.by_employee_id is None or event.at is None:
            continue
        employee_id = int(event.by_employee_id)
        moment = event.at
        current = first_task.get(employee_id)
        if current is None or moment < current:
            first_task[employee_id] = moment

    first_run: dict[int, datetime] = {}
    for run in done_runs:
        if run.completed_at is None:
            continue
        employee_id = int(run.employee_id)
        moment = run.completed_at
        current = first_run.get(employee_id)
        if current is None or moment < current:
            first_run[employee_id] = moment

    by_org: dict[int, list[Employee]] = {}
    for employee in employees:
        by_org.setdefault(int(employee.org_id), []).append(employee)

    items: list[dict[str, Any]] = []
    total_people = total_tasks = total_runs = total_done = 0
    task_hours: list[float] = []
    run_hours: list[float] = []

    for org in orgs:
        people = by_org.get(int(org.id), [])
        if not people:
            continue
        task_hours_org: list[float] = []
        run_hours_org: list[float] = []
        with_task = with_run = onboarding_done = 0
        for employee in people:
            employee_id = int(employee.id)
            if employee_id in first_task:
                with_task += 1
                task_hours_org.append(_hours(employee.created_at, first_task[employee_id]))
            if employee_id in first_run:
                with_run += 1
                run_hours_org.append(_hours(employee.created_at, first_run[employee_id]))
            if employee.onboarding_state == ONBOARDING_DONE:
                onboarding_done += 1

        items.append(
            {
                "org_id": int(org.id),
                "name": org.name,
                "people": len(people),
                "first_task_done": with_task,
                "first_task_share": _share(with_task, len(people)),
                "median_hours_to_first_task": _median(task_hours_org),
                "first_checklist_done": with_run,
                "first_checklist_share": _share(with_run, len(people)),
                "median_hours_to_first_checklist": _median(run_hours_org),
                "onboarding_done": onboarding_done,
                "onboarding_share": _share(onboarding_done, len(people)),
            }
        )
        total_people += len(people)
        total_tasks += with_task
        total_runs += with_run
        total_done += onboarding_done
        task_hours.extend(task_hours_org)
        run_hours.extend(run_hours_org)

    return {
        "orgs": items,
        "totals": {
            "people": total_people,
            "first_task_done": total_tasks,
            "first_task_share": _share(total_tasks, total_people),
            "median_hours_to_first_task": _median(task_hours),
            "first_checklist_done": total_runs,
            "first_checklist_share": _share(total_runs, total_people),
            "median_hours_to_first_checklist": _median(run_hours),
            "onboarding_done": total_done,
            "onboarding_share": _share(total_done, total_people),
        },
    }
