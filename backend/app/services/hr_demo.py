"""Тестовый пул сотрудников `[BOT]` — завести, показать, спрятать, снести.

Зачем отдельный сервис. Для проверки продукта нужны живые сотрудники, которые
«ходят на смену»: закрывают чек-листы, принимают и заваливают поручения, пишут
обратную связь. Заводить их руками больно, а главное — их нельзя путать с
боевыми людьми. Поэтому у пула три свойства:

1. **Явная метка.** Префикс `[BOT]` в имени и флаг `Employee.is_demo`, который
   нельзя выставить через обычные ручки.
2. **Один тумблер видимости.** `hr.demo.visible` = показывать следы пула или нет:
   лента и списки просто перестают их видеть (`hidden_employee_ids`).
3. **Полное удаление.** `purge()` сносит активность пула (чек-листы, поручения с
   историей, фото, проблемы, обратную связь), а по флагу — и сами строки
   сотрудников вместе с их `users`.

Телеграм-ID пула синтетические (`DEMO_TG_BASE + N`), поэтому «свой/чужой» пула
определяется без похода в базу и никогда не совпадёт с настоящим аккаунтом.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.hr_models import (
    ONBOARDING_DONE,
    PRIORITY_HIGH,
    PRIORITY_NORMAL,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    RUN_DONE,
    RUN_IN_PROGRESS,
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_SCOPE_EMPLOYEE,
    TEMPLATE_SHIFT,
    ChecklistCompletion,
    ChecklistItem,
    ChecklistRun,
    ChecklistTemplate,
    Department,
    Employee,
    FeedbackAnswer,
    FeedbackQuestion,
    Task,
    TaskEvent,
    TaskIssue,
    TaskPhoto,
)
from app.db.models import User
from app.db.seed import color_for_user
from app.services import hr_checklists, hr_settings

log = structlog.get_logger()

DEMO_PREFIX = "[BOT]"
# Синтетическая база телеграм-ID: настоящие аккаунты TG до неё не дотягиваются,
# поэтому сравнение `>= DEMO_TG_BASE` однозначно опознаёт пул.
DEMO_TG_BASE = 900_000_000

# (имя, slug подразделения, должность, текст плашки, эмодзи плашки)
_DEMO_PEOPLE: tuple[tuple[str, str, str, str, str], ...] = (
    ("Алина", "cook", "повар", "Стажёр", "🌱"),
    ("Игорь", "cook", "су-шеф", "Су-шеф", "🍳"),
    ("Марина", "waiter", "официант", "Официант", "🍽"),
    ("Пётр", "barman", "бармен", "Бармен", "🍸"),
    ("Ольга", "manager", "менеджер смены", "Менеджер", "📋"),
    ("Тимур", "waiter", "официант", "Новичок", "🌱"),
)

# (название поручения, нужен ли фотоотчёт)
_DEMO_TASKS: tuple[tuple[str, bool], ...] = (
    ("Проверить сроки годности на раздаче", True),
    ("Убрать кухонный инвентарь после закрытия", False),
    ("Обновить ценники в зале", False),
)

# Чередование статусов по индексу сотрудника: у пула должны быть и «новые», и
# «в работе», и «выполненные» поручения — иначе лента и отчёты выглядят мертво.
_DEMO_STATUSES: tuple[str, ...] = (
    TASK_NEW,
    TASK_ACCEPTED,
    TASK_IN_PROGRESS,
    TASK_DONE,
)

_EMPTY_COUNTS: dict[str, int] = {
    "checklist_runs": 0,
    "checklist_completions": 0,
    "tasks": 0,
    "task_events": 0,
    "task_photos": 0,
    "task_issues": 0,
    "feedback_answers": 0,
}


def demo_display_name(name: str) -> str:
    return f"{DEMO_PREFIX} {name}"


def is_demo_name(name: str) -> bool:
    return name.strip().startswith(DEMO_PREFIX)


def demo_title(name: str) -> str:
    """Имя тестового сотрудника с меткой, без двойного префикса.

    Админка переименовывает людей обычной ручкой и перезаписывает
    `users.display_name` целиком. Для пула это значило бы потерять `[BOT]` —
    и тестовые люди стали бы неотличимы от настоящих в ленте и списках.
    Поэтому любая правка имени у `is_demo` проходит через эту функцию.
    """
    clean = name.strip()
    while clean.startswith(DEMO_PREFIX):
        clean = clean[len(DEMO_PREFIX) :].strip()
    return demo_display_name(clean)


def demo_telegram_id(index: int) -> int:
    return DEMO_TG_BASE + index


def is_demo_telegram_id(telegram_id: int) -> bool:
    return telegram_id >= DEMO_TG_BASE


def demo_pool_size() -> int:
    return len(_DEMO_PEOPLE)


# --------------------------------------------------------------------------
# Чтение состояния
# --------------------------------------------------------------------------


async def _count(
    session: AsyncSession, model: type[Base], *criteria: ColumnElement[bool]
) -> int:
    stmt = select(func.count()).select_from(model)
    if criteria:
        stmt = stmt.where(*criteria)
    return int(await session.scalar(stmt) or 0)


async def _delete(
    session: AsyncSession, model: type[Base], *criteria: ColumnElement[bool]
) -> int:
    result = await session.execute(delete(model).where(*criteria))
    return int(result.rowcount or 0)


async def demo_rows(session: AsyncSession) -> list[tuple[Employee, User]]:
    """Строки пула вместе с `users` — одной выборкой, для бота и админки."""
    rows = await session.execute(
        select(Employee, User)
        .join(User, User.id == Employee.user_id)
        .where(Employee.is_demo.is_(True))
        .order_by(Employee.id)
    )
    return [(employee, user) for employee, user in rows.all()]


async def demo_employee_ids(session: AsyncSession) -> set[int]:
    rows = await session.scalars(select(Employee.id).where(Employee.is_demo.is_(True)))
    return {int(i) for i in rows.all()}


async def hidden_employee_ids(session: AsyncSession) -> set[int]:
    """ID, которые надо спрятать. Пусто, когда пул виден (или его нет)."""
    if await hr_settings.get_demo_visible(session):
        return set()
    return await demo_employee_ids(session)


@dataclass(frozen=True)
class DemoEmployeeRow:
    employee_id: int
    telegram_id: int | None
    display_name: str
    badge: str | None
    badge_emoji: str | None
    department_id: int | None
    department_name: str | None
    is_active: bool


@dataclass(frozen=True)
class DemoActivity:
    checklist_runs: int
    tasks: int
    feedback_answers: int


@dataclass(frozen=True)
class DemoOverview:
    """Состояние пула одним объектом — для админки бота и REST."""

    visible: bool
    prefix: str
    employees: list[DemoEmployeeRow]
    activity: DemoActivity


async def overview(session: AsyncSession) -> DemoOverview:
    rows = await demo_rows(session)
    ids = {int(employee.id) for employee, _ in rows}
    departments = {
        int(d.id): d.name for d in await session.scalars(select(Department))
    }
    return DemoOverview(
        visible=await hr_settings.get_demo_visible(session),
        prefix=DEMO_PREFIX,
        employees=[
            DemoEmployeeRow(
                employee_id=int(employee.id),
                telegram_id=user.telegram_id,
                display_name=str(user.display_name),
                badge=employee.badge,
                badge_emoji=employee.badge_emoji,
                department_id=(
                    int(employee.department_id)
                    if employee.department_id is not None
                    else None
                ),
                department_name=(
                    departments.get(int(employee.department_id))
                    if employee.department_id is not None
                    else None
                ),
                is_active=bool(employee.is_active),
            )
            for employee, user in rows
        ],
        activity=DemoActivity(
            checklist_runs=await _count(
                session, ChecklistRun, ChecklistRun.employee_id.in_(ids)
            ),
            tasks=await _count(session, Task, Task.assignee_employee_id.in_(ids)),
            feedback_answers=await _count(
                session, FeedbackAnswer, FeedbackAnswer.employee_id.in_(ids)
            ),
        ),
    )


# --------------------------------------------------------------------------
# Заведение пула
# --------------------------------------------------------------------------


async def seed_pool(session: AsyncSession) -> int:
    """Создать/дополнить тестовый пул. Идемпотентно: повтор не дублирует людей."""
    departments = {
        d.slug: d for d in await session.scalars(select(Department))
    }
    created = 0
    for index, (name, slug, position, badge, emoji) in enumerate(_DEMO_PEOPLE):
        telegram_id = demo_telegram_id(index)
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(
                telegram_id=telegram_id,
                display_name=demo_display_name(name),
                color_hex=color_for_user(telegram_id),
            )
            session.add(user)
            await session.flush()

        department = departments.get(slug)
        department_id = department.id if department is not None else None
        employee = await session.scalar(select(Employee).where(Employee.user_id == user.id))
        if employee is None:
            session.add(
                Employee(
                    user_id=user.id,
                    department_id=department_id,
                    position=position,
                    badge=badge,
                    badge_emoji=emoji,
                    role=ROLE_EMPLOYEE,
                    onboarding_state=ONBOARDING_DONE,
                    is_demo=True,
                )
            )
            created += 1
            continue

        # Повторный заведение — не «пересоздать», а подтянуть метки: так правка
        # списка пула в коде применяется к уже существующим тестовым людям.
        employee.is_demo = True
        employee.badge = badge
        employee.badge_emoji = emoji
        if department_id is not None:
            employee.department_id = department_id
    await session.flush()
    log.info("hr.demo.seeded", created=created, total=demo_pool_size())
    return created


# --------------------------------------------------------------------------
# Симуляция деятельности
# --------------------------------------------------------------------------


async def simulate(session: AsyncSession, *, days: int = 3) -> dict[str, int]:
    """Сгенерировать правдоподобную активность пула за последние `days` смен.

    Генератор детерминированный (сид — id сотрудника и дата), поэтому повторный
    запуск не плодит хаос: те же люди получают ту же картину смены.
    """
    rows = await demo_rows(session)
    if not rows:
        return dict(_EMPTY_COUNTS)

    counters = dict(_EMPTY_COUNTS)
    owner_id = await session.scalar(
        select(Employee.id).where(Employee.role == ROLE_ADMIN).order_by(Employee.id)
    )
    questions = list(
        await session.scalars(
            select(FeedbackQuestion)
            .where(FeedbackQuestion.is_active.is_(True))
            .order_by(FeedbackQuestion.sort_order)
        )
    )
    today = hr_checklists.local_today()
    now = datetime.now(UTC)

    for offset in range(max(1, days)):
        shift_date = today - timedelta(days=offset)
        for index, (employee, _user) in enumerate(rows):
            rng = random.Random(f"{employee.id}:{shift_date.isoformat()}")

            await _simulate_checklist(session, employee, shift_date, rng, counters)
            if offset == 0:
                await _simulate_task(
                    session, employee, index, owner_id, now, rng, counters
                )
                await _simulate_feedback(
                    session, employee, shift_date, index, questions, counters
                )

    await session.commit()
    log.info("hr.demo.simulated", days=days, **counters)
    return counters


async def _simulate_checklist(
    session: AsyncSession,
    employee: Employee,
    shift_date: date,
    rng: random.Random,
    counters: dict[str, int],
) -> None:
    template = await session.scalar(
        select(ChecklistTemplate)
        .where(
            ChecklistTemplate.department_id == employee.department_id,
            ChecklistTemplate.kind == TEMPLATE_SHIFT,
        )
        .order_by(ChecklistTemplate.id)
    )
    if template is None:
        return
    run = ChecklistRun(
        employee_id=employee.id,
        template_id=template.id,
        shift_date=shift_date,
        status=RUN_IN_PROGRESS,
    )
    session.add(run)
    await session.flush()
    counters["checklist_runs"] += 1

    item_ids = list(
        await session.scalars(
            select(ChecklistItem.id)
            .where(ChecklistItem.template_id == template.id)
            .order_by(ChecklistItem.sort_order)
        )
    )
    # Часть пунктов закрыта: у одной смены чек-лист закрыт целиком, у другой —
    # брошен на середине. Так у руководителя есть и «выполнено», и «в работе».
    take = min(len(item_ids), 2 + rng.randrange(2))
    for item_id in item_ids[:take]:
        session.add(
            ChecklistCompletion(
                run_id=run.id,
                item_id=item_id,
                done_by_employee_id=employee.id,
            )
        )
        counters["checklist_completions"] += 1
    if take >= len(item_ids) and item_ids:
        run.status = RUN_DONE
        run.completed_at = datetime.now(UTC) - timedelta(hours=rng.randrange(1, 6))


async def _simulate_task(
    session: AsyncSession,
    employee: Employee,
    index: int,
    owner_id: int | None,
    now: datetime,
    rng: random.Random,
    counters: dict[str, int],
) -> None:
    title, needs_photo = _DEMO_TASKS[index % len(_DEMO_TASKS)]
    target_status = _DEMO_STATUSES[index % len(_DEMO_STATUSES)]
    task = Task(
        title=title,
        scope=TASK_SCOPE_EMPLOYEE,
        assignee_employee_id=employee.id,
        department_id=employee.department_id,
        due_at=now + timedelta(hours=rng.randrange(2, 30)),
        priority=PRIORITY_HIGH if needs_photo else PRIORITY_NORMAL,
        requires_photo=needs_photo,
        status=TASK_NEW,
        created_by_employee_id=owner_id,
    )
    session.add(task)
    await session.flush()
    counters["tasks"] += 1
    session.add(
        TaskEvent(
            task_id=task.id,
            from_status=None,
            to_status=TASK_NEW,
            by_employee_id=owner_id,
            comment="created",
        )
    )
    counters["task_events"] += 1

    if target_status != TASK_NEW:
        task.status = TASK_ACCEPTED
        task.accepted_at = now - timedelta(hours=rng.randrange(1, 3))
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=TASK_NEW,
                to_status=TASK_ACCEPTED,
                by_employee_id=employee.id,
            )
        )
        counters["task_events"] += 1

    if target_status in {TASK_IN_PROGRESS, TASK_DONE}:
        task.status = TASK_IN_PROGRESS
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=TASK_ACCEPTED,
                to_status=TASK_IN_PROGRESS,
                by_employee_id=employee.id,
            )
        )
        counters["task_events"] += 1

    if target_status == TASK_DONE:
        task.status = TASK_DONE
        task.done_at = now - timedelta(minutes=rng.randrange(10, 120))
        session.add(
            TaskEvent(
                task_id=task.id,
                from_status=TASK_IN_PROGRESS,
                to_status=TASK_DONE,
                by_employee_id=employee.id,
            )
        )
        counters["task_events"] += 1
        if needs_photo:
            session.add(
                TaskPhoto(task_id=task.id, employee_id=employee.id, file_id="demo-photo")
            )
            counters["task_photos"] += 1

    # Один из пула «не успевает» — чтобы у руководителя было что эскалировать.
    if index == len(_DEMO_PEOPLE) - 1:
        session.add(
            TaskIssue(
                task_id=task.id,
                employee_id=employee.id,
                reason_code="no_time",
                comment="Данные тестового пула [BOT]",
                eta_at=now + timedelta(hours=6),
            )
        )
        counters["task_issues"] += 1


async def _simulate_feedback(
    session: AsyncSession,
    employee: Employee,
    shift_date: date,
    index: int,
    questions: list[FeedbackQuestion],
    counters: dict[str, int],
) -> None:
    for question in questions[:2]:
        answer = FeedbackAnswer(
            employee_id=employee.id,
            shift_date=shift_date,
            question_id=question.id,
        )
        if question.kind == "scale":
            answer.value_scale = 3 + index % 3
        elif question.kind == "choice":
            options = list(question.options or [])
            answer.value_choice = options[index % len(options)] if options else None
        else:
            answer.value_text = "Данные тестового пула [BOT]"
        session.add(answer)
        counters["feedback_answers"] += 1


# --------------------------------------------------------------------------
# Удаление следов
# --------------------------------------------------------------------------


async def purge(session: AsyncSession, *, delete_employees: bool = False) -> dict[str, int]:
    """Снести активность пула, а по флагу — и сами строки сотрудников и `users`.

    Порядок важен: сначала история (события/фото/проблемы), потом сами поручения
    и чек-листы, и только затем люди — иначе остались бы записи, ссылающиеся на
    удалённых (FK выставлены в `SET NULL`, и след «неизвестный сотрудник» остался
    бы в ленте).
    """
    ids = await demo_employee_ids(session)
    counters = dict(_EMPTY_COUNTS)
    counters["employees"] = 0
    counters["users"] = 0
    if not ids:
        return counters

    task_ids = set(
        await session.scalars(
            select(Task.id).where(
                or_(
                    Task.assignee_employee_id.in_(ids),
                    Task.created_by_employee_id.in_(ids),
                )
            )
        )
    )
    run_ids = set(
        await session.scalars(select(ChecklistRun.id).where(ChecklistRun.employee_id.in_(ids)))
    )

    counters["task_events"] = await _delete(
        session,
        TaskEvent,
        or_(TaskEvent.task_id.in_(task_ids), TaskEvent.by_employee_id.in_(ids)),
    )
    counters["task_photos"] = await _delete(
        session,
        TaskPhoto,
        or_(TaskPhoto.task_id.in_(task_ids), TaskPhoto.employee_id.in_(ids)),
    )
    counters["task_issues"] = await _delete(
        session,
        TaskIssue,
        or_(TaskIssue.task_id.in_(task_ids), TaskIssue.employee_id.in_(ids)),
    )
    counters["tasks"] = await _delete(session, Task, Task.id.in_(task_ids))
    counters["checklist_completions"] = await _delete(
        session,
        ChecklistCompletion,
        or_(
            ChecklistCompletion.run_id.in_(run_ids),
            ChecklistCompletion.done_by_employee_id.in_(ids),
        ),
    )
    counters["checklist_runs"] = await _delete(
        session, ChecklistRun, ChecklistRun.id.in_(run_ids)
    )
    counters["feedback_answers"] = await _delete(
        session, FeedbackAnswer, FeedbackAnswer.employee_id.in_(ids)
    )

    if delete_employees:
        # Снимок состава ДО удаления — пул ID восстановим из админки.
        from app.services import hr_roster

        await hr_roster.capture(
            session,
            kind=hr_roster.KIND_AUTO,
            source="demo:purge",
            label="Перед очисткой тестового пула",
        )
        user_ids = set(
            await session.scalars(select(Employee.user_id).where(Employee.id.in_(ids)))
        )
        counters["employees"] = await _delete(session, Employee, Employee.id.in_(ids))
        counters["users"] = await _delete(session, User, User.id.in_(user_ids))

    await session.commit()
    log.info("hr.demo.purged", delete_employees=delete_employees, **counters)
    return counters
