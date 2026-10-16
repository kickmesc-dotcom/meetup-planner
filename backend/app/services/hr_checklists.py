"""Чек-листы смены и адаптации (п.3 mainPROMT).

Прогон (`ChecklistRun`) — это «смена конкретного сотрудника за конкретную дату».
Отметки (`ChecklistCompletion`) отдельной строкой на пункт, `UNIQUE(run,item)`
даёт идемпотентность: двойной тап по кнопке не создаёт дубль и не «переоткрывает»
уже закрытый пункт.

Логика проверки фотоотчёта и подсчёта прогресса вынесена в чистые функции
(`applicable_items`, `progress`) — их и тестируем без БД.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.hr_models import (
    RUN_DONE,
    RUN_IN_PROGRESS,
    TEMPLATE_FIRST_DAY,
    TEMPLATE_SHIFT,
    ChecklistCompletion,
    ChecklistItem,
    ChecklistRun,
    ChecklistTemplate,
    Employee,
)


class ChecklistError(Exception):
    """Нарушение правил чек-листа (например, фото не приложено)."""


@dataclass(frozen=True)
class ChecklistProgress:
    done: int
    total: int

    @property
    def finished(self) -> bool:
        return self.total > 0 and self.done >= self.total

    def text(self) -> str:
        return f"Выполнено {self.done} из {self.total}"


def local_today(tz: str | None = None) -> date:
    """Сегодняшняя дата в часовом поясе ресторана (не по UTC).

    Смена может «перевалить» за полночь: считаем по локальному дню ресторана,
    а не по UTC, иначе вечерняя смена окажется «вчерашней».
    """
    zone = ZoneInfo(tz or get_settings().scheduler_tz)
    return datetime.now(zone).date()


# --------------------------------------------------------------------------
# Чистые правила
# --------------------------------------------------------------------------


def applicable_items(
    items: list[ChecklistItem], position: str | None
) -> list[ChecklistItem]:
    """Пункты, видимые сотруднику с данной должностью.

    `condition_position IS NULL` — пункт для всех. Иначе сравниваем без учёта
    регистра и лишних пробелов (пример mainPROMT: бракераж только у су-шефа).
    """
    normalized = (position or "").strip().casefold()
    out: list[ChecklistItem] = []
    for item in items:
        condition = (item.condition_position or "").strip().casefold()
        if condition and condition != normalized:
            continue
        out.append(item)
    return out


def progress(items: list[ChecklistItem], completed_item_ids: set[int]) -> ChecklistProgress:
    """Сколько пунктов закрыто из применимых."""
    return ChecklistProgress(
        done=sum(1 for item in items if item.id in completed_item_ids),
        total=len(items),
    )


def requires_photo(items: list[ChecklistItem], item_id: int) -> bool:
    for item in items:
        if item.id == item_id:
            return bool(item.requires_photo)
    return False


# --------------------------------------------------------------------------
# Шаблоны
# --------------------------------------------------------------------------


async def list_templates(
    session: AsyncSession,
    *,
    department_id: int | None = None,
    kind: str | None = None,
    active_only: bool = True,
) -> list[ChecklistTemplate]:
    stmt = select(ChecklistTemplate)
    if department_id is not None:
        stmt = stmt.where(ChecklistTemplate.department_id == department_id)
    if kind is not None:
        stmt = stmt.where(ChecklistTemplate.kind == kind)
    if active_only:
        stmt = stmt.where(ChecklistTemplate.is_active.is_(True))
    stmt = stmt.order_by(ChecklistTemplate.sort_order, ChecklistTemplate.id)
    return list(await session.scalars(stmt))


async def get_template(
    session: AsyncSession, template_id: int
) -> ChecklistTemplate | None:
    return await session.get(ChecklistTemplate, template_id)


async def select_template(
    session: AsyncSession,
    *,
    department_id: int | None,
    kind: str,
) -> ChecklistTemplate | None:
    """Активный шаблон подразделения нужного вида (или None).

    Новичку показываем `first_day`, если он есть, иначе обычную смену: так
    первый рабочий день не проваливается в пустой экран, пока админ не завёл
    отдельный шаблон.
    """
    if department_id is None:
        return None
    first = await list_templates(session, department_id=department_id, kind=kind)
    if first:
        return first[0]
    if kind == TEMPLATE_FIRST_DAY:
        fallback = await list_templates(
            session, department_id=department_id, kind=TEMPLATE_SHIFT
        )
        return fallback[0] if fallback else None
    return None


async def items_of(session: AsyncSession, template_id: int) -> list[ChecklistItem]:
    rows = await session.scalars(
        select(ChecklistItem)
        .where(ChecklistItem.template_id == template_id)
        .order_by(ChecklistItem.sort_order, ChecklistItem.id)
    )
    return list(rows)


# --------------------------------------------------------------------------
# Прогон смены
# --------------------------------------------------------------------------


async def get_run(
    session: AsyncSession, employee_id: int, template_id: int, shift_date: date
) -> ChecklistRun | None:
    return await session.scalar(
        select(ChecklistRun).where(
            ChecklistRun.employee_id == employee_id,
            ChecklistRun.template_id == template_id,
            ChecklistRun.shift_date == shift_date,
        )
    )


async def get_or_create_run(
    session: AsyncSession,
    employee: Employee,
    template: ChecklistTemplate,
    shift_date: date,
) -> ChecklistRun:
    run = await get_run(session, employee.id, template.id, shift_date)
    if run is not None:
        return run
    run = ChecklistRun(
        employee_id=employee.id,
        template_id=template.id,
        shift_date=shift_date,
        status=RUN_IN_PROGRESS,
    )
    session.add(run)
    await session.flush()
    return run


async def completed_item_ids(session: AsyncSession, run_id: int) -> set[int]:
    rows = await session.scalars(
        select(ChecklistCompletion.item_id).where(ChecklistCompletion.run_id == run_id)
    )
    return {int(i) for i in rows.all()}


async def completions_of(
    session: AsyncSession, run_id: int
) -> dict[int, ChecklistCompletion]:
    rows = await session.scalars(
        select(ChecklistCompletion).where(ChecklistCompletion.run_id == run_id)
    )
    return {c.item_id: c for c in rows.all()}


async def complete_item(
    session: AsyncSession,
    *,
    employee: Employee,
    run: ChecklistRun,
    item: ChecklistItem,
    photo_file_id: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> ChecklistCompletion:
    """Отметить пункт выполненным.

    Если пункт требует фото — без `photo_file_id` это ошибка (п.3.5 mainPROMT:
    «задача не может считаться завершённой до отправки фотографии»). Повторная
    отметка идемпотентна: возвращаем существующую, но фото/заметку можно
    дополнить.
    """
    if run.employee_id != employee.id:
        raise ChecklistError("run_not_owned")
    if item.template_id != run.template_id:
        raise ChecklistError("item_not_in_run")

    existing = await session.scalar(
        select(ChecklistCompletion).where(
            ChecklistCompletion.run_id == run.id,
            ChecklistCompletion.item_id == item.id,
        )
    )
    if existing is None:
        if item.requires_photo and not photo_file_id:
            raise ChecklistError("photo_required")
        existing = ChecklistCompletion(
            run_id=run.id,
            item_id=item.id,
            done_by_employee_id=employee.id,
            photo_file_id=photo_file_id,
            note=note,
        )
        session.add(existing)
    else:
        if item.requires_photo and not (photo_file_id or existing.photo_file_id):
            raise ChecklistError("photo_required")
        if photo_file_id:
            existing.photo_file_id = photo_file_id
        if note:
            existing.note = note

    await session.flush()
    await _refresh_run_status(session, run, now=now)
    return existing


async def _refresh_run_status(
    session: AsyncSession, run: ChecklistRun, *, now: datetime | None = None
) -> None:
    """Пересчитать статус прогона: все применимые пункты закрыты → `done`."""
    template = await session.get(ChecklistTemplate, run.template_id)
    if template is None:
        return
    employee = await session.get(Employee, run.employee_id)
    position = employee.position if employee else None
    items = applicable_items(await items_of(session, template.id), position)
    done_ids = await completed_item_ids(session, run.id)
    if progress(items, done_ids).finished:
        if run.status != RUN_DONE:
            run.status = RUN_DONE
            run.completed_at = now or datetime.now(UTC)
    elif run.status == RUN_DONE:
        # Пункт могли «дополнить» так, что состав изменился (админ добавил новый
        # обязательный пункт) — тогда прогон снова открываем.
        run.status = RUN_IN_PROGRESS
        run.completed_at = None
    await session.flush()


# --------------------------------------------------------------------------
# Представление для API/бота
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChecklistItemView:
    id: int
    title: str
    description: str | None
    requires_photo: bool
    is_mandatory: bool
    done: bool
    done_at: datetime | None
    photo_file_id: str | None
    note: str | None


@dataclass(frozen=True)
class ChecklistView:
    run_id: int | None
    template_id: int | None
    template_title: str | None
    kind: str
    shift_date: date
    status: str
    progress: ChecklistProgress
    items: list[ChecklistItemView]


async def build_view(
    session: AsyncSession,
    employee: Employee,
    *,
    kind: str = TEMPLATE_SHIFT,
    shift_date: date | None = None,
) -> ChecklistView:
    """Собрать чек-лист сотрудника к показу (без создания прогона).

    Прогон создаём только при первой отметке — иначе «открыл экран» навсегда
    плодил бы пустые строки смен.
    """
    shift_date = shift_date or local_today()
    template = await select_template(
        session, department_id=employee.department_id, kind=kind
    )
    if template is None:
        return ChecklistView(
            run_id=None,
            template_id=None,
            template_title=None,
            kind=kind,
            shift_date=shift_date,
            status=RUN_IN_PROGRESS,
            progress=ChecklistProgress(done=0, total=0),
            items=[],
        )

    items = applicable_items(await items_of(session, template.id), employee.position)
    run = await get_run(session, employee.id, template.id, shift_date)
    completions = await completions_of(session, run.id) if run else {}
    views = [
        ChecklistItemView(
            id=item.id,
            title=item.title,
            description=item.description,
            requires_photo=bool(item.requires_photo),
            is_mandatory=bool(item.is_mandatory),
            done=item.id in completions,
            done_at=completions[item.id].done_at if item.id in completions else None,
            photo_file_id=completions[item.id].photo_file_id
            if item.id in completions
            else None,
            note=completions[item.id].note if item.id in completions else None,
        )
        for item in items
    ]
    return ChecklistView(
        run_id=run.id if run else None,
        template_id=template.id,
        template_title=template.title,
        kind=template.kind,
        shift_date=shift_date,
        status=run.status if run else RUN_IN_PROGRESS,
        progress=progress(items, set(completions)),
        items=views,
    )
