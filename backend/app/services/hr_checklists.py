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
    TEMPLATE_CLOSE,
    TEMPLATE_FIRST_DAY,
    TEMPLATE_SHIFT,
    ChecklistCompletion,
    ChecklistItem,
    ChecklistRun,
    ChecklistTemplate,
    Employee,
    Hall,
    ShiftHallChoice,
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
    hall_id: int | None = None,
    common_only: bool = False,
) -> list[ChecklistTemplate]:
    stmt = select(ChecklistTemplate)
    if department_id is not None:
        stmt = stmt.where(ChecklistTemplate.department_id == department_id)
    if kind is not None:
        stmt = stmt.where(ChecklistTemplate.kind == kind)
    if common_only:
        stmt = stmt.where(ChecklistTemplate.hall_id.is_(None))
    elif hall_id is not None:
        stmt = stmt.where(ChecklistTemplate.hall_id == hall_id)
    if active_only:
        stmt = stmt.where(ChecklistTemplate.is_active.is_(True))
    stmt = stmt.order_by(ChecklistTemplate.sort_order, ChecklistTemplate.id)
    return list(await session.scalars(stmt))


async def get_template(
    session: AsyncSession, template_id: int
) -> ChecklistTemplate | None:
    return await session.get(ChecklistTemplate, template_id)


async def _first_active_template(
    session: AsyncSession,
    department_id: int,
    kind: str,
    hall_id: int | None,
) -> ChecklistTemplate | None:
    """Один активный шаблон нужного вида и зала (None — общий)."""
    rows = await list_templates(
        session,
        department_id=department_id,
        kind=kind,
        hall_id=hall_id,
        common_only=hall_id is None,
    )
    return rows[0] if rows else None


async def select_template(
    session: AsyncSession,
    *,
    department_id: int | None,
    kind: str,
    hall_id: int | None = None,
) -> ChecklistTemplate | None:
    """Активный шаблон подразделения нужного вида (или None).

    Открытие зала (`shift`) ищется сначала по выбранному залу, потом — общий:
    заведение без залов работает ровно как раньше. Новичку показываем
    `first_day`, если он есть, иначе обычную смену: так первый рабочий день не
    проваливается в пустой экран, пока админ не завёл отдельный шаблон.
    """
    if department_id is None:
        return None
    common = await _first_active_template(session, department_id, kind, None)
    if kind == TEMPLATE_SHIFT:
        if hall_id is not None:
            specific = await _first_active_template(
                session, department_id, kind, hall_id
            )
            if specific is not None:
                return specific
        return common
    if common is not None:
        return common
    if kind == TEMPLATE_FIRST_DAY:
        return await _first_active_template(
            session, department_id, TEMPLATE_SHIFT, None
        )
    return None


# --------------------------------------------------------------------------
# Залы и выбор зала на смену
# --------------------------------------------------------------------------


async def list_halls(
    session: AsyncSession, *, active_only: bool = True
) -> list[Hall]:
    stmt = select(Hall)
    if active_only:
        stmt = stmt.where(Hall.is_active.is_(True))
    stmt = stmt.order_by(Hall.sort_order, Hall.id)
    return list(await session.scalars(stmt))


async def get_hall(session: AsyncSession, hall_id: int) -> Hall | None:
    return await session.get(Hall, hall_id)


async def department_has_halls(
    session: AsyncSession, department_id: int | None
) -> bool:
    """Есть ли у подразделения отдельные шаблоны по залам.

    Если нет — спрашивать «в каком ты зале» бессмысленно: повар, бармен и
    менеджер продолжают видеть один общий чек-лист.
    """
    if department_id is None:
        return False
    stmt = (
        select(ChecklistTemplate.id)
        .where(
            ChecklistTemplate.department_id == department_id,
            ChecklistTemplate.kind == TEMPLATE_SHIFT,
            ChecklistTemplate.is_active.is_(True),
            ChecklistTemplate.hall_id.is_not(None),
        )
        .limit(1)
    )
    return await session.scalar(stmt) is not None


async def hall_choice(
    session: AsyncSession, employee_id: int, shift_date: date
) -> Hall | None:
    row = await session.scalar(
        select(ShiftHallChoice).where(
            ShiftHallChoice.employee_id == employee_id,
            ShiftHallChoice.shift_date == shift_date,
        )
    )
    if row is None:
        return None
    return await session.get(Hall, row.hall_id)


async def choose_hall(
    session: AsyncSession, *, employee: Employee, hall: Hall, shift_date: date
) -> None:
    """Запомнить зал на смену (повторный выбор перезаписывает)."""
    row = await session.scalar(
        select(ShiftHallChoice).where(
            ShiftHallChoice.employee_id == employee.id,
            ShiftHallChoice.shift_date == shift_date,
        )
    )
    if row is None:
        session.add(
            ShiftHallChoice(
                employee_id=employee.id,
                shift_date=shift_date,
                hall_id=hall.id,
            )
        )
    else:
        row.hall_id = hall.id
    await session.flush()


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
    photo_media_id: int | None = None,
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
        if item.requires_photo and not (photo_file_id or photo_media_id):
            raise ChecklistError("photo_required")
        existing = ChecklistCompletion(
            run_id=run.id,
            item_id=item.id,
            done_by_employee_id=employee.id,
            photo_file_id=photo_file_id,
            photo_media_id=photo_media_id,
            note=note,
        )
        session.add(existing)
    else:
        if item.requires_photo and not (
            photo_file_id
            or photo_media_id
            or existing.photo_file_id
            or existing.photo_media_id
        ):
            raise ChecklistError("photo_required")
        if photo_file_id:
            existing.photo_file_id = photo_file_id
        if photo_media_id:
            existing.photo_media_id = photo_media_id
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
    # Подписанная ссылка на снимок, загруженный в приложении (None — фото нет
    # или оно пришло из старого потока и ещё не закешировано).
    photo_url: str | None = None


def _completion_photo_url(completion: ChecklistCompletion | None) -> str | None:
    """Ссылка на фото пункта: блоб из приложения или ленивый кеш Telegram."""
    if completion is None:
        return None
    from app.services import hr_media

    if completion.photo_media_id is not None:
        return hr_media.url_for(int(completion.photo_media_id))
    if completion.photo_file_id:
        # Старый поток: фото есть только в Telegram. Ленивый роут скачает его
        # и закеширует, поэтому в приложении оно тоже станет видимым.
        return f"/api/media/checklist/{int(completion.id)}?s=" + hr_media.sign(
            "checklist_photo", int(completion.id)
        )
    return None


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
    # Зал смены: у открытия он обязателен, у закрытия всегда None.
    hall_id: int | None = None
    hall_name: str | None = None
    # Сотруднику нужно сначала выбрать зал — пунктов поэтому нет.
    needs_hall: bool = False


async def build_view(
    session: AsyncSession,
    employee: Employee,
    *,
    kind: str = TEMPLATE_SHIFT,
    shift_date: date | None = None,
) -> ChecklistView:
    """Собрать чек-лист сотрудника к показу (без создания прогона).

    Прогон создаём только при первой отметке — иначе «открыл экран» навсегда
    плодил бы пустые строки смен. Но зал нужен раньше: пока он не выбран,
    отдаём `needs_hall=True` и пустой список — фронт показывает выбор зала.
    """
    shift_date = shift_date or local_today()
    day = shift_date

    hall: Hall | None = None
    needs_hall = False
    if kind == TEMPLATE_SHIFT:
        hall = await hall_choice(session, employee.id, day)
        needs_hall = hall is None and await department_has_halls(
            session, employee.department_id
        )
    elif kind not in (TEMPLATE_CLOSE, TEMPLATE_FIRST_DAY):
        # Неизвестный вид — не падаем, показываем пустое состояние.
        kind = TEMPLATE_SHIFT

    if needs_hall:
        return ChecklistView(
            run_id=None,
            template_id=None,
            template_title=None,
            kind=kind,
            shift_date=day,
            status=RUN_IN_PROGRESS,
            progress=ChecklistProgress(done=0, total=0),
            items=[],
            needs_hall=True,
        )

    template = await select_template(
        session,
        department_id=employee.department_id,
        kind=kind,
        hall_id=hall.id if hall is not None else None,
    )
    if template is None:
        return ChecklistView(
            run_id=None,
            template_id=None,
            template_title=None,
            kind=kind,
            shift_date=day,
            status=RUN_IN_PROGRESS,
            progress=ChecklistProgress(done=0, total=0),
            items=[],
            hall_id=hall.id if hall is not None else None,
            hall_name=hall.name if hall is not None else None,
        )

    items = applicable_items(await items_of(session, template.id), employee.position)
    run = await get_run(session, employee.id, template.id, day)
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
            photo_url=_completion_photo_url(completions.get(item.id)),
            note=completions[item.id].note if item.id in completions else None,
        )
        for item in items
    ]
    return ChecklistView(
        run_id=run.id if run else None,
        template_id=template.id,
        template_title=template.title,
        kind=template.kind,
        shift_date=day,
        status=run.status if run else RUN_IN_PROGRESS,
        progress=progress(items, set(completions)),
        items=views,
        hall_id=hall.id if hall is not None else None,
        hall_name=hall.name if hall is not None else None,
    )
