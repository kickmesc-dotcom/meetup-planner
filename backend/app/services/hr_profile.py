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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import ROLE_ADMIN, ROLE_AUP, ROLE_EMPLOYEE, Employee
from app.db.models import User
from app.services import hr_access, hr_checklists, hr_feed, hr_kpi

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
    # Заполняется только при can_view.
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


def may_view(viewer: Employee, target: Employee) -> bool:
    """Может ли смотрящий увидеть активность и цифры цели."""
    if int(viewer.id) == int(target.id):
        return True
    if viewer.is_simulation:
        return False
    if hr_access.is_admin(viewer):
        return True
    if (
        hr_access.is_aup(viewer)
        and viewer.department_id is not None
        and viewer.department_id == target.department_id
    ):
        return True
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

    can_view = may_view(viewer, target)
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
        profile_open=bool(target.profile_public),
        can_view=can_view,
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

    return replace(
        card,
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


async def set_visibility(
    session: AsyncSession, employee: Employee, *, is_public: bool
) -> bool:
    """Сотрудник сам решает, открыт ли его профиль для коллег."""
    employee.profile_public = bool(is_public)
    await session.commit()
    return bool(employee.profile_public)


async def colleague_ids(session: AsyncSession, viewer: Employee) -> set[int]:
    """Люди, чьи карточки заведомо открыты смотрящему (для подсказок в UI)."""
    stmt = select(Employee.id).where(
        Employee.is_simulation.is_(False), Employee.profile_public.is_(True)
    )
    rows = await session.scalars(stmt)
    ids = {int(value) for value in rows.all()}
    ids.add(int(viewer.id))
    return ids
