"""Организации: единственная точка правды про тенантов (B2B_PLATFORM_PLAN, фаза 1).

Зачем сервис, а не запросы по месту. Когда организаций станет больше одной,
любая ручка, забывшая про `org_id`, начнёт отдавать чужие данные. Поэтому
резолв организации, создание и членство живут здесь, а API-слой получает
готовый объект через зависимость (`deps.current_org`).

Пока в базе один контур: `default_org_for` отдаёт организацию из членства, а
если членства нет — первую активную (это ровно то поведение, что было до
тенантов). Как только появится второй клиент, ветку «первая активная» нужно
убрать: она и есть тот самый молчаливый переход в чужие данные.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.org_models import (
    DEFAULT_ORG_ID,
    DEFAULT_ORG_SLUG,
    INDUSTRIES,
    ORG_ROLES,
    Organization,
    OrganizationMember,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


class OrgsError(Exception):
    """Ошибка работы с организациями: код уходит в detail, текст — человеку."""


def normalize_slug(raw: str) -> str:
    """Привести код организации к машинному виду.

    Слаг попадает в ссылки и конфиги, поэтому допускаем только латиницу,
    цифры и дефис. Пробелы и подчёркивания превращаем в дефис, а не молча
    выбрасываем: «krasota plus» → `krasota-plus`.
    """
    slug = raw.strip().lower().replace("_", "-").replace(" ", "-")
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not SLUG_RE.match(slug):
        raise OrgsError("bad_slug")
    return slug


async def get(session: AsyncSession, org_id: int) -> Organization | None:
    return await session.get(Organization, org_id)


async def by_slug(session: AsyncSession, slug: str) -> Organization | None:
    return await session.scalar(
        select(Organization).where(Organization.slug == slug)
    )


async def list_active(session: AsyncSession) -> list[Organization]:
    rows = await session.scalars(
        select(Organization)
        .where(Organization.is_active.is_(True))
        .order_by(Organization.id)
    )
    return list(rows)


async def create_org(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    industry: str = "restaurant",
) -> Organization:
    """Завести организацию. Валидация — здесь, а не в ручке.

    `slug` уникален глобально (он часть ссылок), `industry` — из известного
    набора, иначе пакеты и словари терминов не найдут свою ветку.
    """
    clean_slug = normalize_slug(slug)
    clean_name = name.strip()
    if not clean_name:
        raise OrgsError("bad_name")
    if industry not in INDUSTRIES:
        raise OrgsError("bad_industry")
    if await by_slug(session, clean_slug) is not None:
        raise OrgsError("slug_taken")

    org = Organization(slug=clean_slug, name=clean_name, industry=industry)
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org


async def member(
    session: AsyncSession, *, org_id: int, user_id: int
) -> OrganizationMember | None:
    return await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.user_id == user_id,
        )
    )


async def add_member(
    session: AsyncSession,
    *,
    org_id: int,
    user_id: int,
    role: str = "staff",
) -> OrganizationMember:
    """Добавить человека в организацию (повторный вызов — идемпотентен)."""
    if role not in ORG_ROLES:
        raise OrgsError("bad_role")
    existing = await member(session, org_id=org_id, user_id=user_id)
    if existing is not None:
        if existing.role != role:
            existing.role = role
            await session.commit()
            await session.refresh(existing)
        return existing
    row = OrganizationMember(org_id=org_id, user_id=user_id, role=role)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def orgs_of(session: AsyncSession, user_id: int) -> list[Organization]:
    """Все организации, где человек состоит (для переключателя в UI)."""
    rows = await session.scalars(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
        .where(
            OrganizationMember.user_id == user_id,
            Organization.is_active.is_(True),
        )
        .order_by(Organization.id)
    )
    return list(rows)


async def default_org_for(session: AsyncSession, user: User) -> Organization | None:
    """Организация по умолчанию для человека.

    Сначала членство, затем текущее «единственное» поведение — первая активная
    организация. Второе уйдёт, когда появится второй клиент: новый сотрудник
    обязан попадать в организацию по приглашению, а не в первую по id.
    """
    memberships = await orgs_of(session, user.id)
    if memberships:
        return memberships[0]
    return await session.scalar(
        select(Organization)
        .where(Organization.is_active.is_(True), Organization.id == DEFAULT_ORG_ID)
        .order_by(Organization.id)
    )


TOKEN_RE = re.compile(r"^[0-9]{3,}:[A-Za-z0-9_-]{10,}$")


async def set_bot(
    session: AsyncSession,
    org_id: int,
    *,
    token: str | None,
    username: str | None = None,
    webhook_secret: str | None = None,
    chat_id: int | None = None,
) -> Organization:
    """Подключить организации своего бота (шаг 1.6).

    Три правила, без которых второй клиент сломает первого:

    * бот без секрета вебхука не подключается — апдейт некуда маршрутизировать,
      и он ушёл бы «первому совпавшему»;
    * токен и секрет не должны повторяться у двух организаций (в базе на них
      уникальные индексы, здесь — понятная ошибка вместо 500);
    * пустой токен отключает своего бота и возвращает организацию на общий
      (env), а не оставляет её без бота вовсе.
    """
    org = await session.get(Organization, org_id)
    if org is None:
        raise OrgsError("org_missing")

    clean_token = (token or "").strip() or None
    clean_secret = (webhook_secret or "").strip() or None
    if clean_token is not None:
        if not TOKEN_RE.match(clean_token):
            raise OrgsError("bad_token")
        if not clean_secret:
            raise OrgsError("bot_needs_secret")
        clash = await session.scalar(
            select(Organization).where(
                Organization.bot_token == clean_token, Organization.id != org_id
            )
        )
        if clash is not None:
            raise OrgsError("token_taken")
        clash = await session.scalar(
            select(Organization).where(
                Organization.webhook_secret == clean_secret,
                Organization.id != org_id,
            )
        )
        if clash is not None:
            raise OrgsError("secret_taken")

    org.bot_token = clean_token
    clean_username = (username or "").strip() or None if clean_token else None
    org.bot_username = clean_username
    org.webhook_secret = clean_secret if clean_token else None
    org.group_chat_id = chat_id if clean_token else None
    await session.commit()
    await session.refresh(org)

    # Реестр читается синхронно из 150 мест, поэтому после правки настроек его
    # нужно обновить сразу — иначе бот до перезапуска останется прежним.
    from app.services import org_bots

    await org_bots.reload(session)
    return org


async def ensure_default(session: AsyncSession) -> Organization:
    """Гарантировать существование организации по умолчанию (тесты, dev).

    На проде строку создаёт миграция `0053_tenancy`; в sqlite-фикстурах таблицы
    создаются с нуля, и без этой функции любой тест начинался бы с ручной
    вставки организации.
    """
    org = await session.get(Organization, DEFAULT_ORG_ID)
    if org is not None:
        return org
    org = Organization(
        id=DEFAULT_ORG_ID,
        slug=DEFAULT_ORG_SLUG,
        name="Моя организация",
        industry="restaurant",
    )
    session.add(org)
    await session.commit()
    await session.refresh(org)
    return org
