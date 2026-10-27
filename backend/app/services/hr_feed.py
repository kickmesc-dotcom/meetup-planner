"""Лента событий HR-ядра со строгими правилами видимости.

Требование брифа: лента остаётся, но видно в ней ровно то, что положено роли.

* **Сотрудник** — только свои действия.
* **Руководитель подразделения** (роль `aup` со своим `department_id`) — свои
  и действия сотрудников своего подразделения.
* **Управляющий** (роль `admin`, либо `aup` без привязки к подразделению) —
  всё, с фильтрами по сотруднику и подразделению.

Правило применяется НА СЕРВЕРЕ: фильтр `employee_id` из запроса проходит
только если запрошенный сотрудник и так входит в доступную область. Иначе —
пустой ответ, а не «чужой» лента.

Отдельной таблицы событий не заводим: источник — уже существующие сущности
(`checklist_runs`, `checklist_completions`, `task_events`, `task_photos`,
`task_issues`). Это дешевле и не даёт рассинхрона «событие есть, а факта нет».
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    TASK_ACCEPTED,
    TASK_DONE,
    TASK_FAILED,
    TASK_IN_PROGRESS,
    TASK_NEW,
    TASK_ON_REVIEW,
    TASK_OVERDUE,
    TASK_REWORK,
    ChecklistCompletion,
    ChecklistItem,
    ChecklistRun,
    ChecklistTemplate,
    Department,
    Employee,
    Kudos,
    Task,
    TaskEvent,
    TaskIssue,
    TaskPhoto,
)
from app.db.models import User
from app.services import hr_access, hr_demo

SCOPE_SELF = "self"
SCOPE_DEPARTMENT = "department"
SCOPE_ALL = "all"

KIND_CHECKLIST_DONE = "checklist_done"
KIND_CHECKLIST_ITEM = "checklist_item"
KIND_TASK_CREATED = "task_created"
KIND_TASK_STATUS = "task_status"
KIND_TASK_PHOTO = "task_photo"
KIND_TASK_ISSUE = "task_issue"
# Благодарность коллеге. Единственный источник — своя таблица (`hr_kudos`),
# а не событие чужой сущности: спасибо говорят и за то, чего в системе нет.
KIND_KUDOS = "kudos"

ALL_KINDS: tuple[str, ...] = (
    KIND_CHECKLIST_DONE,
    KIND_CHECKLIST_ITEM,
    KIND_TASK_CREATED,
    KIND_TASK_STATUS,
    KIND_TASK_PHOTO,
    KIND_TASK_ISSUE,
    KIND_KUDOS,
)

# Человеческие подписи переходов статуса (для текста записи).
_STATUS_TEXT: dict[str, str] = {
    TASK_NEW: "создано поручение",
    TASK_ACCEPTED: "принял(а) поручение",
    TASK_IN_PROGRESS: "взял(а) поручение в работу",
    TASK_ON_REVIEW: "сдал(а) работу на проверку",
    TASK_REWORK: "получил(а) доработку по поручению",
    TASK_DONE: "выполнил(а) поручение",
    TASK_OVERDUE: "просрочил(а) поручение",
    TASK_FAILED: "отметил(а) поручение как невыполненное",
}

# Английские шаблоны текста ленты. Ключ — русский шаблон: так фразы в коде
# остаются читаемыми, а язык выбирается на границе (`?lang=en`). Неизвестный
# шаблон остаётся русским — как и содержимое, которое человек написал сам.
SAY_EN: dict[str, str] = {
    "закрыл(а) чек-лист «{title}»": "closed the checklist “{title}”",
    "отметил(а) пункт «{title}»": "ticked the item “{title}”",
    "создал(а) поручение «{title}»": "created the task “{title}”",
    "{action}: «{title}»": "{action}: “{title}”",
    "сменил(а) статус на «{status}»: «{title}»":
        "changed the status to “{status}”: “{title}”",
    "прислал(а) фотоотчёт по «{title}»": "sent a photo report for “{title}”",
    "сообщил(а) о проблеме по «{title}»{suffix}":
        "reported a problem with “{title}”{suffix}",
    " (причина: {reason})": " (reason: {reason})",
    "поблагодарил(а) {name}{suffix}": "thanked {name}{suffix}",
    ": «{message}»": ": “{message}”",
    "создано поручение": "task created",
    "принял(а) поручение": "accepted the task",
    "взял(а) поручение в работу": "started the task",
    "сдал(а) работу на проверку": "submitted the work for review",
    "получил(а) доработку по поручению": "got the task back for rework",
    "выполнил(а) поручение": "completed the task",
    "просрочил(а) поручение": "missed the task deadline",
    "отметил(а) поручение как невыполненное": "marked the task as not done",
}


def say(lang: str, template: str, **params: object) -> str:
    """Фраза ленты на языке интерфейса (по умолчанию — русский)."""
    text = SAY_EN.get(template, template) if lang == "en" else template
    if not params:
        return text
    return text.format(**params)


DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class FeedItem:
    at: datetime
    kind: str
    employee_id: int | None
    user_id: int | None
    display_name: str
    department_id: int | None
    text: str
    ref_id: int | None
    # Плашка «должность/звание» — её видно рядом с именем в ленте. Пусто у тех,
    # кому она не назначена (массовых сотрудников).
    badge: str | None = None
    badge_emoji: str | None = None
    # Тестовый пул `[BOT]`. Фронтенд по этому флагу рисует ОДНУ пометку
    # («тест») вместо трёх (префикс в имени + плашка + чип BOT).
    is_demo: bool = False


# --------------------------------------------------------------------------
# Правила видимости
# --------------------------------------------------------------------------


def viewer_scope(viewer: Employee) -> str:
    """Какая область доступна смотрящему."""
    # Теневой профиль проверки живёт в своём сеансе: даже если у проверяемого
    # роль руководителя, лента показывает только действия сеанса, а не
    # реальную жизнь отдела.
    if viewer.is_simulation:
        return SCOPE_SELF
    if hr_access.is_admin(viewer):
        return SCOPE_ALL
    if hr_access.is_aup(viewer):
        # АУП без подразделения — «управляющий вообще»: видит всё.
        return SCOPE_DEPARTMENT if viewer.department_id is not None else SCOPE_ALL
    return SCOPE_SELF


def can_filter(viewer: Employee) -> bool:
    """Доступны ли фильтры по сотрудникам/подразделениям."""
    return viewer_scope(viewer) != SCOPE_SELF


def scoped_departments(
    viewer: Employee, departments: Sequence[Department]
) -> list[Department]:
    """Подразделения, которые смотрящий вправе увидеть в фильтре ленты.

    Списки фильтра нельзя брать из админской ручки: руководитель подразделения
    (`aup`) не админ, но фильтровать своих людей ему нужно. Здесь то же правило,
    что и у самой ленты, только применённое к справочнику подразделений, поэтому
    подсказка в фильтре не может выдать чужое подразделение.
    """
    scope = viewer_scope(viewer)
    if scope == SCOPE_ALL:
        return list(departments)
    if scope == SCOPE_DEPARTMENT:
        return [d for d in departments if d.id == viewer.department_id]
    return []


async def allowed_employee_ids(
    session: AsyncSession, viewer: Employee
) -> set[int] | None:
    """Множество доступных employee_id; `None` означает «видит всех»."""
    scope = viewer_scope(viewer)
    if scope == SCOPE_ALL:
        return None
    if scope == SCOPE_SELF:
        return {viewer.id}
    rows = await session.scalars(
        select(Employee.id).where(
            Employee.department_id == viewer.department_id,
            Employee.is_simulation.is_(False),
        )
    )
    ids = {int(i) for i in rows.all()}
    ids.add(viewer.id)
    return ids


def resolve_employee_filter(
    requested: int | None, allowed: set[int] | None
) -> int | None:
    """Пропустить фильтр по сотруднику, только если он в доступной области.

    Возвращает `employee_id` для запроса или `None`, если фильтр не задан.
    Для «чужого» сотрудника выбрасывает `PermissionError` — вызывающий
    превращает его в пустой ответ (чужие id не подтверждаем).
    """
    if requested is None:
        return None
    if allowed is None or requested in allowed:
        return requested
    raise PermissionError("employee_out_of_scope")


# --------------------------------------------------------------------------
# Сборка
# --------------------------------------------------------------------------


async def _directory(
    session: AsyncSession, employee_ids: set[int]
) -> dict[int, tuple[str, int, int | None, str | None, str | None, bool]]:
    """`employee.id` → (имя, user_id, department_id, плашка, эмодзи, демо)."""
    if not employee_ids:
        return {}
    rows = await session.execute(
        select(
            Employee.id,
            Employee.user_id,
            Employee.department_id,
            User.display_name,
            Employee.badge,
            Employee.badge_emoji,
            Employee.is_demo,
        )
        .join(User, User.id == Employee.user_id)
        .where(Employee.id.in_(employee_ids))
    )
    return {
        int(eid): (str(name), int(uid), did, badge, badge_emoji, bool(demo))
        for eid, uid, did, name, badge, badge_emoji, demo in rows.all()
    }


# `employee.id` → (имя, user_id, department_id, плашка, эмодзи, демо)
_Directory = dict[
    int, tuple[str, int, int | None, str | None, str | None, bool]
]


def _name_of(directory: _Directory, employee_id: int | None) -> str:
    if employee_id is None:
        return "Система"
    entry = directory.get(employee_id)
    return entry[0] if entry else "Сотрудник"


def _dept_of(directory: _Directory, employee_id: int | None) -> int | None:
    if employee_id is None:
        return None
    entry = directory.get(employee_id)
    return entry[2] if entry else None


async def collect_items(
    session: AsyncSession,
    *,
    employee_ids: set[int] | None,
    kinds: tuple[str, ...],
    since: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    excluded: set[int] | None = None,
    lang: str = "ru",
) -> list[FeedItem]:
    """Собрать записи из всех источников, отфильтровать и отсортировать.

    `excluded` — то, что надо спрятать даже от того, кто видит всех: так
    работает тумблер тестового пула `[BOT]` (п.2 в `services/hr_demo`).
    """
    want = set(kinds)
    raw: list[tuple[datetime, str, int | None, str, int | None]] = []

    def _allowed(employee_id: int | None) -> bool:
        if employee_id is None:
            # Служебные записи без автора («Система») видны только тем, кто
            # видит всех — у остальных в ленте только свои действия.
            return employee_ids is None
        if excluded and employee_id in excluded:
            return False
        if employee_ids is None:
            return True
        return employee_id in employee_ids

    if KIND_CHECKLIST_DONE in want:
        rows = await session.execute(
            select(
                ChecklistRun.employee_id,
                ChecklistRun.completed_at,
                ChecklistRun.id,
                ChecklistTemplate.title,
            )
            .join(ChecklistTemplate, ChecklistTemplate.id == ChecklistRun.template_id)
            .where(ChecklistRun.completed_at.is_not(None))
            .order_by(ChecklistRun.completed_at.desc())
            .limit(limit)
        )
        for employee_id, at, run_id, title in rows.all():
            if not _allowed(employee_id):
                continue
            raw.append(
                (
                    at,
                    KIND_CHECKLIST_DONE,
                    employee_id,
                    say(lang, "закрыл(а) чек-лист «{title}»", title=title),
                    run_id,
                )
            )

    if KIND_CHECKLIST_ITEM in want:
        rows = await session.execute(
            select(
                ChecklistRun.employee_id,
                ChecklistCompletion.done_at,
                ChecklistCompletion.id,
                ChecklistItem.title,
            )
            .join(ChecklistCompletion, ChecklistCompletion.run_id == ChecklistRun.id)
            .join(ChecklistItem, ChecklistItem.id == ChecklistCompletion.item_id)
            .order_by(ChecklistCompletion.done_at.desc())
            .limit(limit)
        )
        for employee_id, at, comp_id, title in rows.all():
            if not _allowed(employee_id):
                continue
            raw.append(
                (
                    at,
                    KIND_CHECKLIST_ITEM,
                    employee_id,
                    say(lang, "отметил(а) пункт «{title}»", title=title),
                    comp_id,
                )
            )

    if KIND_TASK_CREATED in want or KIND_TASK_STATUS in want:
        rows = await session.execute(
            select(
                TaskEvent.by_employee_id,
                TaskEvent.at,
                TaskEvent.to_status,
                TaskEvent.comment,
                Task.title,
                Task.id,
            )
            .join(Task, Task.id == TaskEvent.task_id)
            .order_by(TaskEvent.at.desc())
            .limit(limit)
        )
        for by_id, at, to_status, comment, title, task_id in rows.all():
            # Комментарий-маркер напоминания — служебный, в ленту не идёт.
            if comment in {"reminder_sent", "auto_overdue"}:
                continue
            # При создании в комментарии лежит режим (`created:employee`,
            # `created:group`): без префикса событие «поручение создано» вообще
            # выпадало из ленты.
            if comment and comment.startswith("created"):
                kind = KIND_TASK_CREATED
                text = say(lang, "создал(а) поручение «{title}»", title=title)
            else:
                kind = KIND_TASK_STATUS
                action = _STATUS_TEXT.get(to_status)
                if action is None:
                    text = say(
                        lang,
                        "сменил(а) статус на «{status}»: «{title}»",
                        status=to_status,
                        title=title,
                    )
                else:
                    text = say(
                        lang,
                        "{action}: «{title}»",
                        action=say(lang, action),
                        title=title,
                    )
            author = by_id
            if not _allowed(author):
                continue
            raw.append((at, kind, author, text, task_id))

    if KIND_TASK_PHOTO in want:
        rows = await session.execute(
            select(
                TaskPhoto.employee_id,
                TaskPhoto.created_at,
                Task.title,
                Task.id,
            )
            .join(Task, Task.id == TaskPhoto.task_id)
            .order_by(TaskPhoto.created_at.desc())
            .limit(limit)
        )
        for employee_id, at, title, task_id in rows.all():
            if not _allowed(employee_id):
                continue
            raw.append(
                (
                    at,
                    KIND_TASK_PHOTO,
                    employee_id,
                    say(lang, "прислал(а) фотоотчёт по «{title}»", title=title),
                    task_id,
                )
            )

    if KIND_TASK_ISSUE in want:
        rows = await session.execute(
            select(
                TaskIssue.employee_id,
                TaskIssue.created_at,
                TaskIssue.reason_code,
                Task.title,
                Task.id,
            )
            .join(Task, Task.id == TaskIssue.task_id)
            .order_by(TaskIssue.created_at.desc())
            .limit(limit)
        )
        for employee_id, at, reason, title, task_id in rows.all():
            if not _allowed(employee_id):
                continue
            suffix = say(lang, " (причина: {reason})", reason=reason) if reason else ""
            raw.append(
                (at, KIND_TASK_ISSUE, employee_id,
                 say(
                     lang,
                     "сообщил(а) о проблеме по «{title}»{suffix}",
                     title=title,
                     suffix=suffix,
                 ), task_id)
            )

    if KIND_KUDOS in want:
        rows = await session.execute(
            select(
                Kudos.from_employee_id,
                Kudos.to_employee_id,
                Kudos.created_at,
                Kudos.id,
                Kudos.message,
                User.display_name,
            )
            .join(Employee, Employee.id == Kudos.to_employee_id)
            .join(User, User.id == Employee.user_id)
            .order_by(Kudos.created_at.desc())
            .limit(limit)
        )
        for from_id, to_id, at, kudos_id, message, to_name in rows.all():
            # Запись видит и тот, кто сказал, и тот, кому сказали: получивший
            # благодарность должен найти её в своей ленте, а не только
            # в колокольчике, который однажды прочитают.
            if not (_allowed(from_id) or _allowed(to_id)):
                continue
            suffix = (
                say(lang, ": «{message}»", message=message) if message else ""
            )
            raw.append(
                (
                    at,
                    KIND_KUDOS,
                    from_id,
                    say(
                        lang,
                        "поблагодарил(а) {name}{suffix}",
                        name=to_name,
                        suffix=suffix,
                    ),
                    kudos_id,
                )
            )

    if since is not None:
        raw = [row for row in raw if row[0] is not None and row[0] >= since]

    raw.sort(key=lambda row: row[0], reverse=True)
    raw = raw[:limit]

    directory = await _directory(session, {row[2] for row in raw if row[2] is not None})
    items: list[FeedItem] = []
    for at, kind, employee_id, text, ref_id in raw:
        entry = directory.get(employee_id) if employee_id is not None else None
        items.append(
            FeedItem(
                at=at,
                kind=kind,
                employee_id=employee_id,
                user_id=entry[1] if entry else None,
                display_name=_name_of(directory, employee_id),
                department_id=_dept_of(directory, employee_id),
                text=text,
                ref_id=ref_id,
                badge=entry[3] if entry else None,
                badge_emoji=entry[4] if entry else None,
                is_demo=entry[5] if entry else False,
            )
        )
    return items


async def build_feed(
    session: AsyncSession,
    viewer: Employee,
    *,
    employee_id: int | None = None,
    department_id: int | None = None,
    kinds: tuple[str, ...] | None = None,
    since: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    lang: str = "ru",
) -> list[FeedItem]:
    """Лента для конкретного смотрящего с учётом его прав."""
    allowed = await allowed_employee_ids(session, viewer)
    selected = resolve_employee_filter(employee_id, allowed)  # PermissionError → 403

    scope = viewer_scope(viewer)
    if selected is not None:
        allowed = {selected} if allowed is None else {selected}
    # Фильтр по подразделению доступен только тем, кто вправе его применять.
    if department_id is not None and scope != SCOPE_ALL:
        if viewer.department_id is not None and department_id != viewer.department_id:
            raise PermissionError("department_out_of_scope")

    if department_id is not None:
        rows = await session.scalars(
            select(Employee.id).where(Employee.department_id == department_id)
        )
        dept_ids = {int(i) for i in rows.all()}
        allowed = dept_ids if allowed is None else (allowed & dept_ids)

    selected_kinds = kinds or ALL_KINDS
    # Тестовый пул `[BOT]` прячется целиком, когда админ выключил его видимость:
    # исключаем ПОСЛЕ расчёта области, чтобы спрятанное не всплыло через фильтр.
    excluded = await hr_demo.hidden_employee_ids(session)
    if not viewer.is_simulation:
        from app.services import hr_simulation

        excluded = excluded | await hr_simulation.hidden_employee_ids(session)
    items = await collect_items(
        session,
        employee_ids=allowed,
        kinds=tuple(k for k in selected_kinds if k in ALL_KINDS),
        since=since,
        limit=max(1, min(limit, MAX_LIMIT)),
        excluded=excluded,
        lang=lang,
    )
    return items


def now_utc() -> datetime:
    return datetime.now(UTC)
