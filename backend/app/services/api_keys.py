"""Ключи публичного API организации (B2B_PLATFORM_PLAN, шаг 6.1).

Зачем ключ, а не пароль владельца. Интегратору нужны люди и график, но не
кабинет: пароль дал бы ему всё, включая удаление организации. Ключ — отдельная
сущность с набором прав и отзывом в один клик; его можно выписать на подрядчика
и отозвать, не меняя пароль владельца.

Почему в базе хеш, а не сам ключ. Ключ показывается один раз при создании.
Дальше хранится SHA-256 и префикс: утечка дампа не даёт доступа к API, а
человек всё равно узнаёт свой ключ в списке по началу «stk_live_7fa2…».

Почему scopes строкой через запятую. Их пять, они меняются вместе с кодом, а
отдельная таблица `api_key_scopes` потребовала бы join на каждый запрос ради
списка из двух слов. Строка проверяется на входе и на выходе — набор закрытый.

Почему `resolve` идёт через `all_orgs()`. Ключ приходит без пользователя и без
`initData`; организацию можно узнать только из самой строки ключа. Обычный
тенантский фильтр искал бы ключ в организации по умолчанию, и ключи всех
остальных клиентов «не находились» бы — та же ловушка, что у приглашений.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.org_models import ApiKey
from app.db.tenancy import all_orgs

# Префикс отделяет наши ключи от чужих токенов в логах и в глазах человека.
TOKEN_PREFIX = "stk_live_"

# Набор прав закрытый. `contacts.read` отдельно от `people.read`: интегратору
# для расстановки смен хватает имени и должности, а почта и телефон — это уже
# персональные данные, которые не должны уезжать по умолчанию.
SCOPES: tuple[str, ...] = (
    "people.read",
    "schedule.read",
    "menu.read",
    "contacts.read",
)

DEFAULT_SCOPES: tuple[str, ...] = ("people.read", "schedule.read", "menu.read")

# Как часто обновлять `last_used_at`. Поле нужно человеку («этот ключ ещё
# живой?»), а не аудиту: писать в базу на каждый запрос интегратора — это
# лишняя запись на ровном месте.
TOUCH_INTERVAL = timedelta(minutes=5)


class ApiKeyError(Exception):
    """Ошибка ключа: неизвестный набор прав или пустое имя."""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_scopes(scopes: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Проверить набор прав. Неизвестное право — ошибка, а не молчание.

    Молча отброшенный scope даёт интегратору 403 на ручке, которую он считал
    разрешённой, и разбор начинается с чужой стороны.
    """
    if not scopes:
        return DEFAULT_SCOPES
    cleaned: list[str] = []
    for raw in scopes:
        code = (raw or "").strip()
        if not code:
            continue
        if code not in SCOPES:
            raise ApiKeyError(f"unknown_scope:{code}")
        if code not in cleaned:
            cleaned.append(code)
    if not cleaned:
        return DEFAULT_SCOPES
    return tuple(cleaned)


def scopes_of(key: ApiKey) -> tuple[str, ...]:
    return tuple(part for part in (key.scopes or "").split(",") if part)


def has_scope(key: ApiKey, scope: str) -> bool:
    return scope in scopes_of(key)


async def create(
    session: AsyncSession,
    *,
    org_id: int,
    name: str,
    scopes: list[str] | tuple[str, ...] | None = None,
    user: User | None = None,
) -> tuple[ApiKey, str]:
    """Выписать ключ. Возвращает строку и сам ключ — единственный раз."""
    title = (name or "").strip()
    if not title:
        raise ApiKeyError("name_required")
    chosen = normalize_scopes(scopes)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(
        org_id=org_id,
        name=title[:80],
        prefix=token[:16],
        token_hash=hash_token(token),
        scopes=",".join(chosen),
        created_by_user_id=user.id if user is not None else None,
    )
    session.add(key)
    await session.flush()
    return key, token


async def resolve(session: AsyncSession, token: str) -> ApiKey | None:
    """Найти живой ключ по токену. `None` — ключа нет или он отозван."""
    raw = (token or "").strip()
    if not raw:
        return None
    with all_orgs():
        key = await session.scalar(
            select(ApiKey).where(
                ApiKey.token_hash == hash_token(raw),
                ApiKey.revoked_at.is_(None),
            )
        )
    if key is None:
        return None
    now = datetime.now(timezone.utc)
    if key.last_used_at is None or now - key.last_used_at > TOUCH_INTERVAL:
        key.last_used_at = now
        await session.commit()
    return key


async def for_org(session: AsyncSession, org_id: int) -> list[ApiKey]:
    rows = await session.scalars(
        select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.id.desc())
    )
    return list(rows)


async def revoke(session: AsyncSession, org_id: int, key_id: int) -> ApiKey | None:
    key = await session.get(ApiKey, key_id)
    if key is None or key.org_id != org_id:
        return None
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
    return key


async def get(session: AsyncSession, org_id: int, key_id: int) -> ApiKey | None:
    key = await session.get(ApiKey, key_id)
    if key is None or key.org_id != org_id:
        return None
    return key


__all__ = [
    "DEFAULT_SCOPES",
    "SCOPES",
    "TOKEN_PREFIX",
    "ApiKeyError",
    "create",
    "for_org",
    "get",
    "has_scope",
    "hash_token",
    "normalize_scopes",
    "resolve",
    "revoke",
    "scopes_of",
]
