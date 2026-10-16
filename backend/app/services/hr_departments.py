"""Подразделения (шаг 2 онбординга, п.2 mainPROMT).

Список подразделений редактируется администратором без разработчика: создание,
переименование, эмодзи, порядок и доступность для новых сотрудников (`is_active`).
Удаляем не физически, а гасим флагом — за подразделением тянутся чек-листы,
поручения и ссылки, и «тихое» удаление осиротило бы историю.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import Department

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class DepartmentError(Exception):
    """Некорректные данные подразделения."""


# Транслитерация для авто-slug, когда админ вводит русское название.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(name: str) -> str:
    """`Повар` → `povar`; латиница остаётся как есть."""
    lowered = name.strip().lower()
    translit = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    slug = _SLUG_RE.sub("-", translit).strip("-")
    return slug or "dept"


async def list_departments(
    session: AsyncSession, *, active_only: bool = True
) -> list[Department]:
    stmt = select(Department)
    if active_only:
        stmt = stmt.where(Department.is_active.is_(True))
    stmt = stmt.order_by(Department.sort_order, Department.id)
    return list(await session.scalars(stmt))


async def get_department(session: AsyncSession, department_id: int) -> Department | None:
    return await session.get(Department, department_id)


async def get_by_slug(session: AsyncSession, slug: str) -> Department | None:
    return await session.scalar(select(Department).where(Department.slug == slug))


async def _unique_slug(
    session: AsyncSession, name: str, *, exclude_id: int | None = None
) -> str:
    base = slugify(name)
    candidate = base
    suffix = 2
    while True:
        existing = await get_by_slug(session, candidate)
        if existing is None or existing.id == exclude_id:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


async def create_department(
    session: AsyncSession,
    *,
    name: str,
    emoji: str | None = None,
    slug: str | None = None,
    sort_order: int | None = None,
) -> Department:
    clean_name = name.strip()
    if not clean_name:
        raise DepartmentError("empty_name")

    resolved_slug = (slug.strip() if slug else "") or await _unique_slug(
        session, clean_name
    )
    if await get_by_slug(session, resolved_slug) is not None:
        raise DepartmentError("slug_taken")

    if sort_order is None:
        sort_order = len(await list_departments(session, active_only=False))

    dept = Department(
        name=clean_name,
        slug=resolved_slug,
        emoji=emoji,
        is_active=True,
        sort_order=sort_order,
    )
    session.add(dept)
    await session.flush()
    return dept


async def update_department(
    session: AsyncSession,
    department: Department,
    *,
    name: str | None = None,
    emoji: str | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> Department:
    if name is not None:
        clean = name.strip()
        if not clean:
            raise DepartmentError("empty_name")
        department.name = clean
        # Slug не трогаем: на него могут ссылаться условия/сидинг, а имя — только
        # то, что видит сотрудник.
    if emoji is not None:
        department.emoji = emoji
    if is_active is not None:
        department.is_active = is_active
    if sort_order is not None:
        department.sort_order = sort_order
    await session.flush()
    return department
