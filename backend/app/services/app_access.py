"""Вход в приложение из браузера по ссылке (веб-версия на ПК).

Зачем это вообще нужно. Внутри Telegram мини-апп получает `initData` —
подписанный ботом набор данных, по которому сервер точно знает, кто пришёл.
Прямая ссылка на Pages таких данных не несёт: браузер снаружи Telegram. Отсюда
два требования, которые задают всю конструкцию:

1. **Токен — это пароль.** Значит, в базе лежит только SHA-256, а сам токен
   показывается один раз (в ссылке). Утечка дампа БД входа не даёт.
2. **Срок и отзыв обязательны.** Ссылка живёт 30 дней, любую можно отозвать
   одной кнопкой, а `last_used_at` показывает, когда её последний раз
   использовали. Потеряли ноутбук — отозвали ссылку, и всё.

Почему не пароль/логин. Сотруднику уже выдали Telegram; второй пароль он
забудет, а хранить и сбрасывать его — работа для управляющего. Ссылка
выпускается из бота (`/app`) и из профиля, живёт в закладке браузера.

Важная деталь: выпуск и отзыв ссылок разрешены **только** с `initData`
(внутри Telegram). Иначе украденный токен мог бы продлевать сам себя: отозвали
ссылку — а он выпустил новую.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.hr_models import AppAccessLink
from app.db.models import User

# Префикс нужен, чтобы отличить свой токен от чего угодно ещё и не пытаться
# искать в базе мусор из адресной строки.
TOKEN_PREFIX = "sweb_"
# 32 байта энтропии → 43 символа base64url. Для перебора недостижимо.
_TOKEN_BYTES = 32
DEFAULT_TTL_DAYS = 30
# Сколько ссылок держим у одного человека. Старые отзываем при выпуске новой:
# «веб-версия» — это закладка, а не коллекция.
MAX_ACTIVE_LINKS = 5

# `last_used_at` пишем не на каждый запрос: это лишний UPDATE в каждой ручке.
# Раз в час достаточно, чтобы человек увидел «последний раз — сегодня».
TOUCH_INTERVAL = timedelta(hours=1)


def now() -> datetime:
    return datetime.now(UTC)


def hash_token(raw: str) -> str:
    """SHA-256 от токена. В базе хранится только это."""
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def is_active(link: AppAccessLink, at: datetime | None = None) -> bool:
    moment = at or now()
    return link.revoked_at is None and link.expires_at > moment


def build_url(mini_app_url: str, token: str) -> str:
    """Ссылка для браузера. `?access=` переживает уже существующий query."""
    base = (mini_app_url or "").strip()
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}access={token}"


async def issue(
    session: AsyncSession,
    *,
    user: User,
    mini_app_url: str,
    label: str = "",
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> tuple[AppAccessLink, str]:
    """Выпустить ссылку. Возвращает (строку БД, сырой токен — показать один раз)."""
    moment = now()
    token = generate_token()
    link = AppAccessLink(
        user_id=user.id,
        token_hash=hash_token(token),
        label=(label or "").strip()[:80],
        expires_at=moment + timedelta(days=max(1, ttl_days)),
    )
    session.add(link)
    await session.flush()

    # Держим не больше MAX_ACTIVE_LINKS живых ссылок: всё, что старше, отзываем.
    alive = (
        await session.scalars(
            select(AppAccessLink)
            .where(AppAccessLink.user_id == user.id)
            .where(AppAccessLink.revoked_at.is_(None))
            .where(AppAccessLink.expires_at > moment)
            .order_by(AppAccessLink.created_at.desc(), AppAccessLink.id.desc())
        )
    ).all()
    for stale in alive[MAX_ACTIVE_LINKS:]:
        stale.revoked_at = moment

    await session.commit()
    await session.refresh(link)
    return link, token


async def list_for(session: AsyncSession, user_id: int) -> list[AppAccessLink]:
    rows = await session.scalars(
        select(AppAccessLink)
        .where(AppAccessLink.user_id == user_id)
        .order_by(AppAccessLink.created_at.desc(), AppAccessLink.id.desc())
    )
    return list(rows.all())


async def revoke(session: AsyncSession, *, user_id: int, link_id: int) -> bool:
    """Отозвать свою ссылку. Чужую отозвать нельзя — фильтр по `user_id`."""
    link = await session.scalar(
        select(AppAccessLink).where(AppAccessLink.id == link_id, AppAccessLink.user_id == user_id)
    )
    if link is None:
        return False
    if link.revoked_at is None:
        link.revoked_at = now()
        await session.commit()
    return True


async def revoke_all(session: AsyncSession, *, user_id: int) -> int:
    rows = await session.scalars(
        select(AppAccessLink)
        .where(AppAccessLink.user_id == user_id)
        .where(AppAccessLink.revoked_at.is_(None))
    )
    moment = now()
    count = 0
    for link in rows.all():
        link.revoked_at = moment
        count += 1
    if count:
        await session.commit()
    return count


async def resolve(session: AsyncSession, raw: str | None) -> User | None:
    """Пользователь по токену доступа. `None` — токен неизвестен/просрочен/отозван."""
    token = (raw or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        return None
    link = await session.scalar(
        select(AppAccessLink).where(AppAccessLink.token_hash == hash_token(token))
    )
    if link is None:
        return None
    moment = now()
    if not is_active(link, moment):
        return None
    user = await session.get(User, link.user_id)
    if user is None:
        return None
    if link.last_used_at is None or moment - link.last_used_at > TOUCH_INTERVAL:
        link.last_used_at = moment
        await session.commit()
    return user
