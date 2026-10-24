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
    set_org,
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


async def ensure_member(
    session: AsyncSession, *, org_id: int, user_id: int, role: str = "staff"
) -> OrganizationMember:
    """Гарантировать членство, НЕ трогая уже выданную роль.

    Отличие от `add_member` принципиальное: тот меняет роль на присланную, и
    вызов «на всякий случай» при каждом входе снимал бы у управляющего его
    права. Здесь роль ставится только новой строке.
    """
    if role not in ORG_ROLES:
        raise OrgsError("bad_role")
    existing = await member(session, org_id=org_id, user_id=user_id)
    if existing is not None:
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


# Латиница для короткого адреса: имя компании почти всегда русское, а `slug`
# попадает в ссылки и потому обязан быть латинским. Простая таблица покрывает
# бытовые названия; чего нет — выпадает, и адрес достраивается цифрами.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}


def slug_from_name(name: str) -> str:
    """Черновой код из названия: «Кофейня №1» → `kofeynya-1`.

    Пустой результат (название из иероглифов или знаков) не ошибка: вызывающий
    подставит запасной код. Здесь важно не упасть, а дать человеку читаемый
    адрес, который он потом увидит как ID компании.
    """
    mapped = "".join(
        _TRANSLIT.get(ch, ch) if ch.isalpha() else ch for ch in name.lower()
    )
    cleaned = re.sub(r"[^a-z0-9]+", "-", mapped).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if len(cleaned) < 2:
        cleaned = f"org-{abs(hash(name)) % 100000:05d}"
    return cleaned[:56].strip("-") or "org"


async def _free_slug(session: AsyncSession, base: str) -> str:
    """Свободный код: `kofeynya`, `kofeynya-2`, `kofeynya-3`…

    Уникальность проверяется запросом, а не перебором исключений: 409 от базы
    после `commit` оставил бы сессию в нерабочем состоянии.
    """
    candidate = base
    suffix = 2
    while await by_slug(session, candidate) is not None:
        candidate = f"{base[:56]}-{suffix}"
        suffix += 1
    return candidate


async def _move_sessions(
    session: AsyncSession, *, user_id: int, org_id: int
) -> None:
    """Перевести живые входы человека в организацию (как при принятии ссылки).

    Сессия помнит организацию на момент входа. Без этого следующий запрос
    с другого устройства продолжал бы смотреть в прежний тенант.
    """
    from app.db.auth_models import AuthSession

    live = await session.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
    )
    for row in live:
        row.org_id = org_id
    await session.commit()


async def join_by_code(
    session: AsyncSession, *, user: User, code: str
) -> tuple[Organization, str]:
    """Войти в организацию по точному коду или точному названию.

    Почему только точное совпадение. Список организаций — внутренняя информация
    платформы: по нему видно, кто уже клиент. Поэтому здесь нет поиска, подсказок
    и «похожих» — только строка, которую человек получил от своего руководителя.
    Совпадение по названию регистронезависимо, но пробелы по краям не спасают:
    «Кофейня» и «Кофейня на углу» — разные организации.

    Роль при входе — `staff`: код не даёт прав управления. Повысить может
    руководитель в своём разделе команды.
    """
    raw = (code or "").strip()
    if len(raw) < 2:
        raise OrgsError("org_not_found")

    org = await by_slug(session, raw.lower())
    if org is None:
        # Сравнение имён — в Python, а не `lower()` в SQL: в sqlite `lower`
        # сворачивает только латиницу, и кириллическое название перестало бы
        # находиться в тестах, работая на PostgreSQL. Таблица организаций
        # маленькая (строка на клиента), поэтому выборка целиком дешевле
        # разъезжающегося поведения двух СУБД.
        wanted = raw.lower()
        rows = await session.scalars(select(Organization))
        org = next(
            (row for row in rows if row.name.strip().lower() == wanted), None
        )
    if org is None:
        # Один и тот же ответ на «нет такой» и «не то название»: иначе по
        # разнице кодов можно перебирать названия клиентов.
        raise OrgsError("org_not_found")
    if not org.is_active:
        raise OrgsError("org_inactive")

    existing = await member(session, org_id=org.id, user_id=user.id)
    if existing is None:
        existing = await add_member(
            session, org_id=org.id, user_id=user.id, role="staff"
        )
    set_org(org.id)
    await _move_sessions(session, user_id=user.id, org_id=org.id)
    return org, existing.role


async def create_with_owner(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    industry: str = "restaurant",
    slug: str | None = None,
) -> Organization:
    """Завести организацию и сделать человека её владельцем.

    Владелец — не «ещё одна роль»: именно он получает админку и мастер первой
    настройки. Поэтому членство `owner` создаётся здесь же, до первого запроса
    приложения: иначе `ensure_employee` увидел бы `staff` и спрятал настройку.
    """
    clean_name = (name or "").strip()
    if len(clean_name) < 2:
        raise OrgsError("bad_name")
    base = normalize_slug(slug) if slug else slug_from_name(clean_name)
    org = await create_org(
        session,
        slug=await _free_slug(session, base),
        name=clean_name,
        industry=industry,
    )
    await add_member(
        session, org_id=org.id, user_id=user.id, role="owner"
    )
    set_org(org.id)
    await _move_sessions(session, user_id=user.id, org_id=org.id)
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
