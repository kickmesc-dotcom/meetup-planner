"""Карточка коллеги: «кто это и что он делал на смене».

Зачем отдельный сервис. Лента и табель показывают имена, но по ним нельзя
понять, чем человек занимается: сколько пунктов закрыл, где стоит в недельном
рейтинге, что делал последним. Раньше это было видно только руководителю в
админке. Теперь карточка открывается тапом по человеку — и это же место, где
живёт правило приватности.

Правило видимости:

* свой профиль — всегда;
* администратор/прописанный доступ — всегда;
* руководитель подразделения — для своих людей всегда (иначе ему нечем
  работать: приёмка и поручения начинаются с «кто этот человек»);
* остальные — только если человек не закрыл профиль (`profile_public`).

Закрытый профиль не отдаёт активность и цифры, но имя, отдел и плашку — да:
они и так видны в ленте, и прятать их было бы лицемерием.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import (
    ROLE_ADMIN,
    ROLE_AUP,
    ROLE_EMPLOYEE,
    ChecklistCompletion,
    ChecklistItem,
    Employee,
    Task,
    TaskPhoto,
)
from app.db.models import User
from app.services import (
    hr_access,
    hr_checklists,
    hr_feed,
    hr_kpi,
    hr_media,
    org_setup,
)

ROLE_LABEL: dict[str, str] = {
    ROLE_EMPLOYEE: "Сотрудник",
    ROLE_AUP: "Руководитель",
    ROLE_ADMIN: "Администратор",
}

# Сколько последних действий показываем в карточке: этого хватает, чтобы
# понять «чем человек занят», и не превращает карточку в вторую ленту.
ACTIVITY_LIMIT = 12


class ProfileError(Exception):
    """Человека нет или карточка закрыта."""


@dataclass(frozen=True)
class MediaItem:
    """Снимок последнего фотоотчёта человека: ссылка уже готова для `<img>`."""

    id: int
    url: str
    at: datetime
    # Что это было: «Смена», «Закрытие смены», название поручения.
    caption: str
    source: str  # `task` | `checklist`


@dataclass(frozen=True)
class ProfileCard:
    employee_id: int
    display_name: str
    department_id: int | None
    department_name: str | None
    position: str | None
    badge: str | None
    badge_emoji: str | None
    role: str
    role_label: str
    is_demo: bool
    is_self: bool
    can_manage: bool
    profile_open: bool
    # Доступна ли активность и цифры этому смотрящему.
    can_view: bool
    # Приватность: что человек разрешил показывать и что разрешило руководство.
    show_last_seen: bool = True
    show_last_media: bool = True
    can_toggle_last_seen: bool = True
    can_toggle_last_media: bool = True
    # Заполняется только при can_view.
    last_seen_at: datetime | None = None
    last_media: MediaItem | None = None
    xp: int = 0
    rank_title: str = ""
    rank_emoji: str = ""
    week_xp: int = 0
    week_place: int | None = None
    week_total: int = 0
    checklist_items: int = 0
    tasks_done: int = 0
    shifts_done: int = 0
    activity: list[hr_feed.FeedItem] = field(default_factory=list)


def may_view(
    viewer: Employee,
    target: Employee,
    *,
    policy: str = "colleagues",
    cross_department_watch: bool = False,
) -> bool:
    """Может ли смотрящий увидеть активность и цифры цели.

    `policy` — выбор руководства в онбординге организации:
    * `colleagues` — решает сам человек (`profile_public`);
    * `managers`   — только руководитель своего отдела и админ;
    * `all_open`   — профиль открыт всем, личный тумблер не действует.
    """
    if int(viewer.id) == int(target.id):
        return True
    if viewer.is_simulation:
        return False
    if hr_access.is_admin(viewer):
        return True
    if hr_access.is_aup(viewer):
        if viewer.department_id is None or cross_department_watch:
            return True
        if viewer.department_id == target.department_id:
            return True
    if policy == "all_open":
        return True
    if policy == "managers":
        return False
    return bool(target.profile_public)


async def build_card(
    session: AsyncSession, viewer: Employee, employee_id: int
) -> ProfileCard:
    """Собрать карточку коллеги с учётом прав смотрящего."""
    target = await session.get(Employee, employee_id)
    if target is None or target.is_simulation:
        raise ProfileError("employee_not_found")
    user = await session.get(User, target.user_id)
    if user is None:
        raise ProfileError("employee_not_found")

    preferences = await org_setup.load(session)
    can_view = may_view(
        viewer,
        target,
        policy=preferences.profile_visibility,
        cross_department_watch=preferences.cross_department_watch,
    )
    is_self = int(viewer.id) == int(target.id)
    can_manage = is_self or hr_access.is_admin(viewer) or (
        hr_access.is_aup(viewer)
        and viewer.department_id is not None
        and viewer.department_id == target.department_id
    )

    department_name: str | None = None
    if target.department_id is not None:
        from app.db.hr_models import Department

        department = await session.get(Department, target.department_id)
        department_name = department.name if department else None

    card = ProfileCard(
        employee_id=int(target.id),
        display_name=str(user.display_name),
        department_id=target.department_id,
        department_name=department_name,
        position=target.position,
        badge=target.badge,
        badge_emoji=target.badge_emoji,
        role=str(target.role),
        role_label=ROLE_LABEL.get(target.role, "Сотрудник"),
        is_demo=bool(target.is_demo),
        is_self=is_self,
        can_manage=can_manage,
        # При политике `all_open`/`managers` личный тумблер не отражает
        # реальность: показываем то, что человек видит фактически.
        profile_open=(
            True
            if preferences.profile_visibility == "all_open"
            else bool(target.profile_public)
        ),
        can_view=can_view,
        show_last_seen=(
            True
            if not preferences.allow_hide_last_seen
            else bool(target.show_last_seen)
        ),
        show_last_media=(
            True
            if not preferences.allow_hide_media
            else bool(target.show_last_media)
        ),
        can_toggle_last_seen=preferences.allow_hide_last_seen,
        can_toggle_last_media=preferences.allow_hide_media,
    )
    if not can_view:
        return card

    today = hr_checklists.local_today()
    kpi = await hr_kpi.my_kpi(session, target, today)
    total = await hr_kpi.counts_for(session, int(target.id))
    activity = await hr_feed.collect_items(
        session,
        employee_ids={int(target.id)},
        kinds=hr_feed.ALL_KINDS,
        limit=ACTIVITY_LIMIT,
    )
    from dataclasses import replace

    # «Последнее медиа» — только если человек и руководство не против. Смотрим
    # оба источника (поручения и чек-листы) и берём более свежий.
    last_media = None
    if bool(target.show_last_media) and preferences.allow_hide_media:
        last_media = await _last_media(session, int(target.id))

    return replace(
        card,
        last_seen_at=(
            target.last_seen_at
            if bool(target.show_last_seen) or not preferences.allow_hide_last_seen
            else None
        ),
        last_media=last_media,
        xp=kpi.progress.xp,
        rank_title=kpi.progress.rank.title,
        rank_emoji=kpi.progress.rank.emoji,
        week_xp=kpi.week_xp,
        week_place=kpi.week_place,
        week_total=kpi.week_total,
        checklist_items=total.checklist_items,
        tasks_done=total.tasks_done,
        shifts_done=total.shifts_done,
        activity=activity,
    )


async def _last_media(
    session: AsyncSession, employee_id: int
) -> MediaItem | None:
    """Самый свежий фотоотчёт человека — из поручений или из чек-листа."""
    candidates: list[MediaItem] = []

    photo_row = (
        await session.execute(
            select(TaskPhoto, Task.title)
            .join(Task, Task.id == TaskPhoto.task_id)
            .where(TaskPhoto.employee_id == employee_id)
            .order_by(TaskPhoto.created_at.desc(), TaskPhoto.id.desc())
            .limit(1)
        )
    ).first()
    if photo_row is not None:
        photo, title = photo_row
        url = (
            hr_media.url_for(int(photo.media_id))
            if photo.media_id is not None
            else hr_media.photo_url(int(photo.id))
        )
        candidates.append(
            MediaItem(
                id=int(photo.id),
                url=url,
                at=photo.created_at,
                caption=str(title),
                source="task",
            )
        )

    checklist_row = (
        await session.execute(
            select(ChecklistCompletion, ChecklistItem.title)
            .join(ChecklistItem, ChecklistItem.id == ChecklistCompletion.item_id)
            .where(
                ChecklistCompletion.done_by_employee_id == employee_id,
                ChecklistCompletion.photo_media_id.is_not(None),
            )
            .order_by(ChecklistCompletion.done_at.desc(), ChecklistCompletion.id.desc())
            .limit(1)
        )
    ).first()
    if checklist_row is not None:
        completion, item_title = checklist_row
        candidates.append(
            MediaItem(
                id=int(completion.id),
                url=hr_media.url_for(int(completion.photo_media_id)),
                at=completion.done_at,
                caption=str(item_title),
                source="checklist",
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.at)


async def touch_seen(
    session: AsyncSession, employee: Employee, *, now: datetime | None = None
) -> None:
    """Отметить заход в приложение, но не чаще раза в две минуты.

    Без порога каждый запрос мини-аппа писал бы в базу: экран делает несколько
    вызовов подряд, и `last_seen_at` превратился бы в «время последнего
    запроса», а не «последнего захода».
    """
    moment = now or datetime.now(UTC)
    previous = employee.last_seen_at
    if previous is not None:
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
        if moment - previous < timedelta(minutes=2):
            return
    employee.last_seen_at = moment
    await session.commit()


async def set_visibility(
    session: AsyncSession, employee: Employee, *, is_public: bool
) -> bool:
    """Сотрудник сам решает, открыт ли его профиль для коллег."""
    preferences = await org_setup.load(session)
    if preferences.profile_visibility == "all_open" and not is_public:
        # Закрыть профиль нельзя: так решило руководство. Не молчание —
        # вызывающий получит понятную ошибку и покажет её человеку.
        raise PermissionError("profile_forced_open")
    employee.profile_public = bool(is_public)
    await session.commit()
    return bool(employee.profile_public)


async def set_privacy(
    session: AsyncSession,
    employee: Employee,
    *,
    show_last_seen: bool | None = None,
    show_last_media: bool | None = None,
) -> Employee:
    """Личные тумблеры «последний заход» и «последнее медиа».

    Руководство может запретить выключение: тогда значение принудительно
    остаётся включённым, даже если клиент прислал `false`. Это не ошибка
    ввода — человек просто не имеет права это скрыть, и UI ему об этом пишет.
    """
    preferences = await org_setup.load(session)
    if show_last_seen is not None:
        employee.show_last_seen = (
            bool(show_last_seen) if preferences.allow_hide_last_seen else True
        )
    if show_last_media is not None:
        employee.show_last_media = (
            bool(show_last_media) if preferences.allow_hide_media else True
        )
    await session.commit()
    return employee


async def colleague_ids(session: AsyncSession, viewer: Employee) -> set[int]:
    """Люди, чьи карточки заведомо открыты смотрящему (для подсказок в UI)."""
    stmt = select(Employee.id).where(
        Employee.is_simulation.is_(False), Employee.profile_public.is_(True)
    )
    rows = await session.scalars(stmt)
    ids = {int(value) for value in rows.all()}
    ids.add(int(viewer.id))
    return ids
