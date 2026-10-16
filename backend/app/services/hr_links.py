"""Полезные ссылки (п.8 mainPROMT): График, Фудбук и что ещё заведёт админ.

Ссылка либо общая (`department_id IS NULL`), либо видна только своему
подразделению. Список для сотрудника фильтруется по его подразделению — на
сервере, а не «прячем кнопку».
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Employee, UsefulLink


class LinkError(Exception):
    pass


def looks_like_url(url: str) -> bool:
    value = url.strip()
    return value.startswith(("http://", "https://", "tg://")) and " " not in value


async def list_links(
    session: AsyncSession,
    employee: Employee | None = None,
    *,
    include_inactive: bool = False,
) -> list[UsefulLink]:
    stmt = select(UsefulLink)
    if not include_inactive:
        stmt = stmt.where(UsefulLink.is_active.is_(True))
    if employee is not None and employee.department_id is not None:
        stmt = stmt.where(
            or_(
                UsefulLink.department_id.is_(None),
                UsefulLink.department_id == employee.department_id,
            )
        )
    elif employee is not None:
        # Сотрудник без подразделения видит только общие ссылки.
        stmt = stmt.where(UsefulLink.department_id.is_(None))
    stmt = stmt.order_by(UsefulLink.sort_order, UsefulLink.id)
    return list(await session.scalars(stmt))


async def get_link(session: AsyncSession, link_id: int) -> UsefulLink | None:
    return await session.get(UsefulLink, link_id)


async def create_link(
    session: AsyncSession,
    *,
    title: str,
    url: str,
    emoji: str | None = None,
    department_id: int | None = None,
    sort_order: int | None = None,
) -> UsefulLink:
    if not title.strip():
        raise LinkError("empty_title")
    if not looks_like_url(url):
        raise LinkError("bad_url")
    if sort_order is None:
        sort_order = len(await list_links(session, include_inactive=True))
    link = UsefulLink(
        title=title.strip(),
        url=url.strip(),
        emoji=emoji,
        department_id=department_id,
        is_active=True,
        sort_order=sort_order,
    )
    session.add(link)
    await session.flush()
    return link


async def update_link(
    session: AsyncSession,
    link: UsefulLink,
    *,
    title: str | None = None,
    url: str | None = None,
    emoji: str | None = None,
    department_id: int | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
    clear_department: bool = False,
) -> UsefulLink:
    if title is not None:
        if not title.strip():
            raise LinkError("empty_title")
        link.title = title.strip()
    if url is not None:
        if not looks_like_url(url):
            raise LinkError("bad_url")
        link.url = url.strip()
    if emoji is not None:
        link.emoji = emoji
    if clear_department:
        link.department_id = None
    elif department_id is not None:
        link.department_id = department_id
    if is_active is not None:
        link.is_active = is_active
    if sort_order is not None:
        link.sort_order = sort_order
    await session.flush()
    return link
